"""Git and SSH helpers for isolated agent clones."""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

QUOTE_WRAPPED_MIN_LENGTH = 2


def load_env_file(path: Path) -> dict[str, str]:
    """Load simple KEY=VALUE entries without shell evaluation."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        clean = value.strip()
        if (
            len(clean) >= QUOTE_WRAPPED_MIN_LENGTH
            and clean[0] == clean[-1]
            and clean[0] in {"'", '"'}
        ):
            clean = clean[1:-1]
        values[key.strip()] = clean
    return values


def env_with_agent_ssh(repo_root: Path, base_env: dict[str, str] | None = None) -> dict[str, str]:
    """Return an environment using AGENTS_* SSH settings with non-interactive defaults."""
    env = dict(os.environ if base_env is None else base_env)
    env.update({key: value for key, value in load_env_file(repo_root / ".env").items()})

    # Force non-interactive git
    env["GIT_TERMINAL_PROMPT"] = "0"

    key_path = env.get("AGENTS_GIT_SSH_KEY_PATH")
    if not key_path:
        # Still force non-interactive SSH for the default user environment
        env["GIT_SSH_COMMAND"] = "ssh -o BatchMode=yes"
        return env

    strict = env.get("AGENTS_GIT_SSH_STRICT_HOST_KEY_CHECKING") or "accept-new"
    command_parts = [
        "ssh",
        "-i",
        shlex.quote(str(Path(key_path).expanduser())),
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "BatchMode=yes",  # Fail if passphrase or interaction required
        "-o",
        f"StrictHostKeyChecking={shlex.quote(strict)}",
    ]
    known_hosts = env.get("AGENTS_GIT_SSH_KNOWN_HOSTS")
    if known_hosts:
        command_parts.extend(
            ["-o", f"UserKnownHostsFile={shlex.quote(str(Path(known_hosts).expanduser()))}"]
        )
    env["GIT_SSH_COMMAND"] = env.get("GIT_SSH_COMMAND", " ".join(command_parts))
    return env


def run_git(
    args: list[str], cwd: Path | None, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    """Run one git command and return the completed process."""
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def verify_git_write_access(repo_root: Path, env: dict[str, str]) -> None:
    """Verify write access to the repository via a non-destructive dry-run push."""
    # First check if we can write to the local ref database (checks local FS rights)
    ref_check = run_git(
        ["update-ref", "refs/agentsloop/write-test", "HEAD"],
        repo_root,
        env,
    )
    if ref_check.returncode != 0:
        raise PermissionError(f"Local git write access denied: {ref_check.stderr.strip()}")

    # Clean up the test ref
    run_git(["update-ref", "-d", "refs/agentsloop/write-test"], repo_root, env)

    # Then check if we can push to origin (dry-run doesn't affect the remote)
    # We use a unique ref name in refs/agentsloop to avoid branch naming conflicts
    push_check = run_git(
        ["push", "--dry-run", "origin", "HEAD:refs/agentsloop/remote-write-test"],
        repo_root,
        env,
    )
    if push_check.returncode != 0:
        # We only treat it as a hard error if it's clearly a permission/auth issue.
        err = push_check.stderr.lower()
        is_auth_error = (
            "permission denied" in err
            or "authentication failed" in err
            or "fatal: could not read from remote repository" in err
            or "host key verification failed" in err
        )
        if is_auth_error:
            msg = push_check.stderr.strip()
            if "batchmode" in err or "permission denied" in err:
                msg += (
                    "\n\nHINT: Your SSH key might be protected by a passphrase "
                    "or missing from the agent."
                )
            raise PermissionError(f"Remote git push access denied: {msg}")


def clone_for_agent(
    *,
    repo_url: str,
    base_branch: str,
    working_branch: str,
    repo_path: Path,
    env: dict[str, str],
) -> None:
    """Clone the repository and check out the requested working branch."""
    repo_path.parent.mkdir(parents=True, exist_ok=True)
    clone = run_git(
        ["clone", "--branch", base_branch, "--single-branch", repo_url, str(repo_path)], None, env
    )
    if clone.returncode != 0:
        raise RuntimeError(f"git clone failed:\n{clone.stderr}")
    if not working_branch:
        return
    remote = run_git(
        ["ls-remote", "--exit-code", "--heads", "origin", working_branch], repo_path, env
    )
    if remote.returncode == 0:
        fetch = run_git(
            ["fetch", "origin", f"{working_branch}:refs/remotes/origin/{working_branch}"],
            repo_path,
            env,
        )
        if fetch.returncode != 0:
            raise RuntimeError(f"git fetch failed:\n{fetch.stderr}")
        checkout = run_git(
            ["checkout", "-B", working_branch, f"origin/{working_branch}"], repo_path, env
        )
    else:
        checkout = run_git(["checkout", "-B", working_branch, base_branch], repo_path, env)
    if checkout.returncode != 0:
        raise RuntimeError(f"git checkout failed:\n{checkout.stderr}")

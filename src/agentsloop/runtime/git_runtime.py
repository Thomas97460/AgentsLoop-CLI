"""Git and SSH helpers for isolated agent clones."""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

QUOTE_WRAPPED_MIN_LENGTH = 2


class GitCommandError(RuntimeError):
    """Raised when a checked Git command fails."""

    def __init__(self, args: list[str], result: subprocess.CompletedProcess[str]) -> None:
        self.args_list = args
        self.result = result
        super().__init__(_format_git_error(args, result))


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


def list_available_ssh_keys() -> list[Path]:
    """List all potential private SSH keys in ~/.ssh/."""
    ssh_dir = Path("~/.ssh").expanduser()
    if not ssh_dir.exists():
        return []
    keys: list[Path] = []
    # Common names
    for name in ["id_ed25519", "id_rsa", "id_ecdsa", "id_dsa"]:
        key = ssh_dir / name
        if key.exists() and key.is_file():
            keys.append(key)
    # Any other id_* that is not a public key
    for key in ssh_dir.glob("id_*"):
        if key.suffix != ".pub" and key.is_file() and key not in keys:
            keys.append(key)
    return sorted(keys)


def discover_ssh_key_path() -> Path | None:
    """Find a reasonable default SSH key path in ~/.ssh/."""
    ssh_dir = Path("~/.ssh").expanduser()
    if not ssh_dir.exists():
        return None
    # Prioritize ed25519 then rsa
    for name in ["id_ed25519", "id_rsa", "id_ecdsa"]:
        key = ssh_dir / name
        if key.exists():
            return key
    # Fallback to any id_* file that doesn't end in .pub
    for key in ssh_dir.glob("id_*"):
        if key.suffix != ".pub" and key.is_file():
            return key
    return None


def env_with_agent_ssh(
    repo_root: Path, base_env: dict[str, str] | None = None, ssh_key_path: Path | None = None
) -> dict[str, str]:
    """Return an environment using AGENTS_* SSH settings with non-interactive defaults."""
    env = dict(os.environ if base_env is None else base_env)
    # repo_root is used to find .env file
    if repo_root.exists() and repo_root.is_dir():
        env.update({key: value for key, value in load_env_file(repo_root / ".env").items()})

    # Force non-interactive git
    env["GIT_TERMINAL_PROMPT"] = "0"

    key_path = str(ssh_key_path) if ssh_key_path else env.get("AGENTS_GIT_SSH_KEY_PATH")
    if not key_path:
        default_key = discover_ssh_key_path()
        if not default_key:
            raise OSError(
                "Git SSH key path is mandatory. Please set AGENTS_GIT_SSH_KEY_PATH "
                "or ensure a default key exists in ~/.ssh/id_*"
            )
        key_path = str(default_key)

    strict = env.get("AGENTS_GIT_SSH_STRICT_HOST_KEY_CHECKING") or "accept-new"
    command_parts = [
        "ssh",
        "-F",
        "/dev/null",
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
    env["GIT_SSH_COMMAND"] = " ".join(command_parts)
    return env


def list_remote_branches(repo_path: Path, env: dict[str, str] | None = None) -> list[str]:
    """List remote branches from the 'origin' remote."""
    try:
        result = run_git(
            ["branch", "-r"],
            repo_path,
            env,
            check=True,
        )
        branches: list[str] = []
        for raw_line in result.stdout.splitlines():
            line = raw_line.strip()
            # Skip HEAD pointer and empty lines
            if "->" in line or not line:
                continue
            # Remove 'origin/' prefix
            if line.startswith("origin/"):
                branches.append(line.removeprefix("origin/"))
            else:
                # Handle cases where it might just be the branch name or other remotes
                parts = line.split("/", 1)
                if len(parts) > 1:
                    branches.append(parts[1])
                else:
                    branches.append(line)
        return sorted(list(set(branches)))
    except (GitCommandError, FileNotFoundError):
        return []


def run_git(
    args: list[str], cwd: Path | None, env: dict[str, str] | None, check: bool = False
) -> subprocess.CompletedProcess[str]:
    """Run one git command and return the completed process."""
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise GitCommandError(["git", *args], result)
    return result


def _format_git_error(args: list[str], result: subprocess.CompletedProcess[str]) -> str:
    """Return a readable Git failure message with captured output."""
    command = " ".join(shlex.quote(arg) for arg in args)
    parts = [f"Git command failed with exit {result.returncode}: {command}"]
    if result.stderr.strip():
        parts.extend(["", "stderr:", result.stderr.strip()])
    if result.stdout.strip():
        parts.extend(["", "stdout:", result.stdout.strip()])
    return "\n".join(parts)


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
        err = "\n".join((push_check.stderr, push_check.stdout)).lower()
        if _is_remote_access_error(err):
            msg = push_check.stderr.strip() or push_check.stdout.strip()
            if "batchmode" in err or "permission denied" in err:
                msg += (
                    "\n\nHINT: Your SSH key might be protected by a passphrase "
                    "or missing from the agent."
                )
            raise PermissionError(f"Remote git push access denied: {msg}")


def _is_remote_access_error(message: str) -> bool:
    """Return whether a Git remote failure is clearly auth or permission related."""
    return any(
        marker in message
        for marker in (
            "permission denied",
            "permission to",
            "denied to deploy key",
            "authentication failed",
            "could not read from remote repository",
            "impossible de lire le dépôt distant",
            "impossible de lire le depot distant",
            "host key verification failed",
        )
    )


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
        # Branch exists on remote, fetch and track it
        run_git(
            ["fetch", "origin", f"{working_branch}:refs/remotes/origin/{working_branch}"],
            repo_path,
            env,
            check=True,
        )
        run_git(
            ["checkout", "-B", working_branch, f"origin/{working_branch}"],
            repo_path,
            env,
            check=True,
        )
    else:
        # Branch is new, create it from base
        run_git(
            ["checkout", "-B", working_branch, base_branch],
            repo_path,
            env,
            check=True,
        )

"""Git and SSH helpers for isolated agent clones."""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path


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
        if len(clean) >= 2 and clean[0] == clean[-1] and clean[0] in {"'", '"'}:
            clean = clean[1:-1]
        values[key.strip()] = clean
    return values


def env_with_agent_ssh(repo_root: Path, base_env: dict[str, str] | None = None) -> dict[str, str]:
    """Return an environment using AGENTS_* SSH settings with N8N_* fallback."""
    env = dict(os.environ if base_env is None else base_env)
    env.update({key: value for key, value in load_env_file(repo_root / "agents" / ".env").items()})
    key_path = env.get("AGENTS_GIT_SSH_KEY_PATH") or env.get("N8N_GIT_SSH_KEY_PATH")
    if not key_path:
        return env
    strict = (
        env.get("AGENTS_GIT_SSH_STRICT_HOST_KEY_CHECKING")
        or env.get("N8N_GIT_SSH_STRICT_HOST_KEY_CHECKING")
        or "accept-new"
    )
    command_parts = [
        "ssh",
        "-i",
        shlex.quote(str(Path(key_path).expanduser())),
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        f"StrictHostKeyChecking={shlex.quote(strict)}",
    ]
    known_hosts = env.get("AGENTS_GIT_SSH_KNOWN_HOSTS") or env.get("N8N_GIT_SSH_KNOWN_HOSTS")
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

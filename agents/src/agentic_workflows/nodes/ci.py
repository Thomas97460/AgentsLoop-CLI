"""CI quiet validation node."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterable
from itertools import islice
from pathlib import Path

from agentic_workflows.domain.models import NodeStatus, WorkflowState
from agentic_workflows.runtime.git_runtime import clone_for_agent
from agentic_workflows.storage.json_store import RunStore

CI_COMMAND = ["bash", "-lc", "direnv allow && task setup && task ci-quiet"]
CI_COMMAND_TEXT = "direnv allow && task setup && task ci-quiet"


def run_ci_validation(state: WorkflowState, env: dict[str, str], store: RunStore) -> None:
    """Clone the developer branch and run compact CI."""
    iteration = state.loop_count
    node_run = store.start_node(
        state,
        role="ci",
        iteration=iteration,
        model=None,
    )
    repo_path = node_run.repo_path
    if repo_path.exists():
        shutil.rmtree(repo_path)
    clone_for_agent(
        repo_url=state.config.repo_url,
        base_branch=state.config.base_branch,
        working_branch=state.developer_branch,
        repo_path=repo_path,
        env=env,
    )
    node_run.stdout_path.parent.mkdir(parents=True, exist_ok=True)
    with (
        node_run.stdout_path.open("w", encoding="utf-8") as stdout,
        node_run.stderr_path.open("w", encoding="utf-8") as stderr,
    ):
        process = subprocess.Popen(
            CI_COMMAND,
            cwd=repo_path,
            env=env,
            text=True,
            stdout=stdout,
            stderr=stderr,
        )
        process.wait()
    output = _first_lines((node_run.stdout_path, node_run.stderr_path), 160)
    status: NodeStatus = "success" if process.returncode == 0 else "error"
    ci_result = {
        "status": status,
        "exit_code": process.returncode,
        "developer_branch": state.developer_branch,
        "command": CI_COMMAND_TEXT,
        "repo_path": str(repo_path),
        "stdout_path": str(node_run.stdout_path),
        "stderr_path": str(node_run.stderr_path),
        "output": output,
    }
    state.validation["ci"] = ci_result
    store.write_node_result(state, node_run, ci_result)
    store.write_node_report(state, node_run, output or "_empty_")
    store.finish_node(
        state,
        node_run,
        status=status,
        exit_code=process.returncode,
        repo_path=str(repo_path),
    )
    store.save_state(state)


def _first_lines(paths: Iterable[Path], limit: int) -> str:
    """Read the first lines from log files without loading full logs."""
    lines: list[str] = []
    for path in paths:
        if len(lines) >= limit or not path.exists():
            continue
        with path.open(encoding="utf-8") as handle:
            lines.extend(line.rstrip() for line in islice(handle, limit - len(lines)))
    return "\n".join(lines)

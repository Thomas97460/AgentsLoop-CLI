"""Detached workflow process launcher."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import orjson

from agentsloop.domain.models import ContinuationContext, RuntimeConfig
from agentsloop.orchestrator import create_state
from agentsloop.runtime.git_runtime import env_with_agent_ssh
from agentsloop.storage.json_store import RunStore, json_dumps


@dataclass(frozen=True, slots=True)
class WorkflowLaunch:
    """Metadata returned after spawning one detached workflow process."""

    task_id: str
    run_dir: Path
    pid: int
    worker_log_path: Path
    request_path: Path


@dataclass(frozen=True, slots=True)
class WorkflowContinuation:
    """Optional continuation metadata for a resumed workflow launch."""

    source_task_id: str
    developer_branch: str
    context: ContinuationContext


def spawn_workflow_process(
    *,
    human_request_md: str,
    config: RuntimeConfig,
    task_id: str,
    runs_dir: Path,
    continuation: WorkflowContinuation | None = None,
) -> WorkflowLaunch:
    """Create a run envelope and spawn the workflow in a detached process."""
    store = RunStore(runs_dir)
    state = create_state(
        human_request_md=human_request_md,
        config=config,
        task_id=task_id,
        runs_dir=runs_dir,
    )
    if continuation is not None:
        state.continued_from_task_id = continuation.source_task_id
        state.continuation_context = continuation.context
        state.developer_branch = continuation.developer_branch
    store.prepare(state)
    request_path = state.run_dir / "request.json"
    worker_log_path = state.run_dir / "worker.log"
    request_path.write_text(
        json_dumps(
            {
                "human_request_md": human_request_md,
                "config": config.model_dump(mode="json"),
                "task_id": task_id,
                "runs_dir": str(runs_dir),
                "continuation": (
                    {
                        "source_task_id": continuation.source_task_id,
                        "developer_branch": continuation.developer_branch,
                        "context": continuation.context.model_dump(mode="json"),
                    }
                    if continuation is not None
                    else None
                ),
            }
        ),
        encoding="utf-8",
    )
    store.event(state, "worker_queued", task_id=task_id, request_path=str(request_path))
    if continuation is not None:
        store.event(
            state,
            "workflow_resumed_from",
            task_id=task_id,
            source_task_id=continuation.source_task_id,
            developer_branch=continuation.developer_branch,
        )
    process = _spawn_worker(
        request_path=request_path,
        run_dir=state.run_dir,
        log_path=worker_log_path,
        repo_url=config.repo_url,
        ssh_key_path=config.ssh_key_path,
    )
    state.worker_pid = process.pid
    state.worker_log_path = worker_log_path
    store.save_state(state)
    store.event(
        state,
        "worker_spawned",
        task_id=task_id,
        pid=process.pid,
        log_path=str(worker_log_path),
    )
    return WorkflowLaunch(
        task_id=task_id,
        run_dir=state.run_dir,
        pid=process.pid,
        worker_log_path=worker_log_path,
        request_path=request_path,
    )


def _spawn_worker(
    *,
    request_path: Path,
    run_dir: Path,
    log_path: Path,
    repo_url: str,
    ssh_key_path: Path | None,
) -> subprocess.Popen[bytes]:
    """Spawn the detached Python worker process with non-interactive agent SSH."""
    command = [
        sys.executable,
        "-m",
        "agentsloop.worker",
        "--request-file",
        str(request_path),
    ]
    env = env_with_agent_ssh(Path(repo_url), ssh_key_path=ssh_key_path)
    env["AGENTSLOOP_REQUEST_FILE"] = str(request_path)
    with log_path.open("a", encoding="utf-8") as log_handle:
        return subprocess.Popen(
            command,
            cwd=run_dir,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=env,
        )


def workflow_payload_from_file(path: Path) -> dict[str, Any]:
    """Read a workflow worker request payload."""
    return cast(dict[str, Any], orjson.loads(path.read_bytes()))

"""Detached workflow process launcher."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from agentic_workflows.domain.models import RuntimeConfig
from agentic_workflows.orchestrator import create_state
from agentic_workflows.storage.json_store import RunStore, json_dumps


@dataclass(frozen=True, slots=True)
class WorkflowLaunch:
    """Metadata returned after spawning one detached workflow process."""

    task_id: str
    run_dir: Path
    pid: int
    worker_log_path: Path
    request_path: Path


def spawn_workflow_process(
    *,
    human_request_md: str,
    config: RuntimeConfig,
    task_id: str,
    runs_dir: Path,
) -> WorkflowLaunch:
    """Create a run envelope and spawn the workflow in a detached process."""
    store = RunStore(runs_dir)
    state = create_state(
        human_request_md=human_request_md,
        config=config,
        task_id=task_id,
        runs_dir=runs_dir,
    )
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
            }
        ),
        encoding="utf-8",
    )
    store.event(state, "worker_queued", task_id=task_id, request_path=str(request_path))
    process = _spawn_worker(
        request_path=request_path,
        run_dir=state.run_dir,
        log_path=worker_log_path,
    )
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
) -> subprocess.Popen[bytes]:
    """Spawn the detached Python worker process."""
    command = [
        sys.executable,
        "-m",
        "agentic_workflows.worker",
        "--request-file",
        str(request_path),
    ]
    env = os.environ.copy()
    env["AGENTIC_WORKFLOW_REQUEST_FILE"] = str(request_path)
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
    import orjson

    return cast(dict[str, Any], orjson.loads(path.read_bytes()))

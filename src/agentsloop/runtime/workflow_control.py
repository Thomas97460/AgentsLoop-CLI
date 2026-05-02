"""Workflow lifecycle controls shared by workers and the TUI."""

from __future__ import annotations

import os
import signal
from typing import Literal

from agentsloop.domain.models import NodeStatus, WorkflowState, WorkflowStatus, utc_now
from agentsloop.storage.json_store import RunStore

ACTIVE_WORKFLOW_STATUSES = {"running", "stopping"}


def request_workflow_stop(store: RunStore, task_id: str, reason: str = "user") -> WorkflowState:
    """Ask a detached workflow to stop and signal its worker process group."""
    state = store.load_state(task_id)
    if state.status not in ACTIVE_WORKFLOW_STATUSES:
        return state
    store.request_stop(state, reason)
    signaled = _terminate_process_group(state.worker_pid)
    store.event(
        state,
        "worker_stop_signal_sent",
        task_id=task_id,
        pid=state.worker_pid,
        signaled=signaled,
    )
    if state.worker_pid is None or not _process_is_alive(state.worker_pid):
        return _complete_workflow(store, state, status="stopped", reason=reason)
    return state


def reconcile_workflow_state(store: RunStore, task_id: str) -> WorkflowState:
    """Fix stale running workflow state when the detached worker is gone."""
    state = store.load_state(task_id)
    if state.status not in ACTIVE_WORKFLOW_STATUSES:
        return state
    if state.worker_pid is not None and _process_is_alive(state.worker_pid):
        return state
    if store.stop_requested(state):
        return _complete_workflow(store, state, status="stopped", reason="stop requested")
    return _complete_workflow(store, state, status="error", reason="worker process exited")


def _complete_workflow(
    store: RunStore,
    state: WorkflowState,
    *,
    status: Literal["stopped", "error"],
    reason: str,
) -> WorkflowState:
    node_status: NodeStatus = "stopped" if status == "stopped" else "error"
    store.finish_running_nodes(state, status=node_status, exit_code=None, reason=reason)
    workflow_status: WorkflowStatus = status
    state.status = workflow_status
    state.finished_at = utc_now()
    if status == "stopped":
        state.approval_status = "done"
        state.reports["human_response"] = "Workflow stopped by request."
    else:
        state.failure_message = reason
    store.save_state(state)
    store.write_summary(state)
    store.event(state, "run_finished", task_id=state.task_id, status=status, reason=reason)
    return state


def _process_is_alive(pid: int) -> bool:
    """Return whether a process id currently exists."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _terminate_process_group(pid: int | None) -> bool:
    """Send SIGTERM to the detached worker process group."""
    if pid is None:
        return False
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return False
    except PermissionError:
        return False
    return True

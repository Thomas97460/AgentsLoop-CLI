"""Top-level CTO/developer workflow orchestration."""

from __future__ import annotations

import uuid
from pathlib import Path

from agentsloop.domain.models import ContinuationContext, RuntimeConfig, WorkflowState, utc_now
from agentsloop.nodes.cto import run_cto
from agentsloop.nodes.developer import run_developer
from agentsloop.nodes.validation import run_validation
from agentsloop.paths import prompts_root, runs_root
from agentsloop.runtime.git_runtime import env_with_agent_ssh
from agentsloop.storage.json_store import EventSink, RunStore


def create_state(
    *,
    human_request_md: str,
    config: RuntimeConfig,
    task_id: str | None = None,
    runs_dir: Path | None = None,
    continued_from_task_id: str | None = None,
    continuation_context: ContinuationContext | None = None,
    developer_branch: str = "",
) -> WorkflowState:
    """Create the initial durable workflow state."""
    resolved_task_id = task_id or str(uuid.uuid4())
    root = runs_dir or runs_root()
    return WorkflowState(
        task_id=resolved_task_id,
        human_request_md=human_request_md,
        config=config,
        run_dir=root / resolved_task_id,
        continued_from_task_id=continued_from_task_id,
        continuation_context=continuation_context,
        developer_branch=developer_branch,
    )


def run_workflow(
    *,
    human_request_md: str,
    config: RuntimeConfig,
    task_id: str | None = None,
    event_sink: EventSink | None = None,
    runs_dir: Path | None = None,
    continued_from_task_id: str | None = None,
    continuation_context: ContinuationContext | None = None,
    developer_branch: str = "",
) -> WorkflowState:
    """Run the real provider-backed CTO/developer loop."""
    store = RunStore(runs_dir or runs_root(), event_sink=event_sink)
    state = _load_or_create_state(
        store=store,
        human_request_md=human_request_md,
        config=config,
        task_id=task_id,
        continued_from_task_id=continued_from_task_id,
        continuation_context=continuation_context,
        developer_branch=developer_branch,
    )
    env = env_with_agent_ssh(Path(config.repo_url), ssh_key_path=config.ssh_key_path)
    store.prepare(state)
    store.event(
        state,
        "run_started",
        task_id=state.task_id,
        provider=config.provider,
        cto_model=config.cto_model,
        cto_reasoning_effort=config.cto_reasoning_effort,
        developer_model=config.developer_model,
        developer_reasoning_effort=config.developer_reasoning_effort,
    )
    try:
        while True:
            if _stop_requested(store, state):
                break
            # Nodes might change status to success/stopped, but if we are starting a cycle,
            # we are definitely running.
            state.status = "running"
            store.save_state(state)

            run_cto(state, prompts_root(), env, store)
            # parse_decision inside run_cto already updated state.status and state.approval_status
            if state.approval_status == "done":
                break
            if _stop_requested(store, state):
                break

            run_developer(state, prompts_root(), env, store)
            if _stop_requested(store, state):
                break
            run_validation(state, env, store)

        if state.status in {"success", "stopped", "error"}:
            state.finished_at = utc_now()
        store.save_state(state)
        store.write_summary(state)
        store.event(
            state,
            "run_finished",
            task_id=state.task_id,
            status=state.status,
            approval_status=state.approval_status,
            loop_count=state.loop_count,
        )
    except Exception as exc:
        store.finish_running_nodes(state, status="error", exit_code=None, reason=str(exc))
        state.status = "error"
        state.failure_message = str(exc)
        state.finished_at = utc_now()
        store.save_state(state)
        store.write_summary(state)
        store.event(state, "run_failed", task_id=state.task_id, error=str(exc))
        raise
    return state


def _load_or_create_state(
    *,
    store: RunStore,
    human_request_md: str,
    config: RuntimeConfig,
    task_id: str | None,
    continued_from_task_id: str | None,
    continuation_context: ContinuationContext | None,
    developer_branch: str,
) -> WorkflowState:
    """Reuse a launch envelope when a detached worker starts."""
    if task_id is not None and (store.runs_dir / task_id / "state.json").exists():
        state = store.load_state(task_id)
        state.human_request_md = human_request_md
        state.config = config
        state.run_dir = store.runs_dir / task_id
        return state
    return create_state(
        human_request_md=human_request_md,
        config=config,
        task_id=task_id,
        runs_dir=store.runs_dir,
        continued_from_task_id=continued_from_task_id,
        continuation_context=continuation_context,
        developer_branch=developer_branch,
    )


def _stop_requested(store: RunStore, state: WorkflowState) -> bool:
    """Move the workflow to stopped when a cooperative stop is requested."""
    if not store.stop_requested(state):
        return False
    state.status = "stopped"
    state.approval_status = "done"
    state.finished_at = state.stop_requested_at or utc_now()
    state.reports["human_response"] = "Workflow stopped by request."
    store.finish_running_nodes(state, status="stopped", exit_code=None, reason="stop requested")
    store.event(state, "run_stopped", task_id=state.task_id)
    return True

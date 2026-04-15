"""Top-level CTO/developer workflow orchestration."""

from __future__ import annotations

import uuid
from pathlib import Path

from agentsloop.domain.models import RuntimeConfig, WorkflowState
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
) -> WorkflowState:
    """Create the initial durable workflow state."""
    resolved_task_id = task_id or str(uuid.uuid4())
    root = runs_dir or runs_root()
    return WorkflowState(
        task_id=resolved_task_id,
        human_request_md=human_request_md,
        config=config,
        run_dir=root / resolved_task_id,
    )


def run_workflow(
    *,
    human_request_md: str,
    config: RuntimeConfig,
    task_id: str | None = None,
    event_sink: EventSink | None = None,
    runs_dir: Path | None = None,
) -> WorkflowState:
    """Run the real Gemini-backed CTO/developer loop."""
    state = create_state(
        human_request_md=human_request_md,
        config=config,
        task_id=task_id,
        runs_dir=runs_dir,
    )
    store = RunStore(runs_dir or runs_root(), event_sink=event_sink)
    env = env_with_agent_ssh(Path(config.repo_url), ssh_key_path=config.ssh_key_path)
    store.prepare(state)
    store.event(
        state,
        "run_started",
        task_id=state.task_id,
        provider=config.provider,
        model=config.model,
    )
    try:
        while True:
            # Nodes might change status to success/stopped, but if we are starting a cycle,
            # we are definitely running.
            state.status = "running"
            store.save_state(state)

            run_cto(state, prompts_root(), env, store)
            # parse_decision inside run_cto already updated state.status and state.approval_status
            if state.approval_status == "done":
                break

            run_developer(state, prompts_root(), env, store)
            run_validation(state, env, store)

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
        state.status = "error"
        store.save_state(state)
        store.event(state, "run_failed", task_id=state.task_id, error=str(exc))
        raise
    return state

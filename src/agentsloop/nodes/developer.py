"""Developer implementation node."""

from __future__ import annotations

from pathlib import Path

from agentsloop.domain.models import WorkflowState
from agentsloop.runtime.agent_runner import AgentRunSpec, run_agent
from agentsloop.runtime.templates import render_template
from agentsloop.storage.json_store import RunStore


def build_prompt(state: WorkflowState, prompts_dir: Path) -> str:
    """Render the developer prompt for the current CTO task."""
    return render_template(
        prompts_dir / "developer_prompt.md",
        {
            "task_id": state.task_id,
            "repo_path": "current working directory (isolated /repo clone)",
            "base_branch": state.config.base_branch,
            "working_branch": state.developer_branch,
            "human_request_md": state.human_request_md,
            "developer_task_md": state.cto_result.get("developer_task_md") or "_none_",
            "technical_summary": state.reports.get("technical_summary") or "_none_",
            "previous_cto_report": state.reports.get("cto") or "_none_",
        },
    )


def run_developer(
    state: WorkflowState,
    prompts_dir: Path,
    env: dict[str, str],
    store: RunStore,
) -> None:
    """Execute one developer pass."""
    iteration = state.loop_count + 1
    prompt_md = build_prompt(state, prompts_dir)
    node_run = store.start_node(
        state,
        role="developer",
        iteration=iteration,
        model=state.config.model,
        prompt_md=prompt_md,
    )
    result = run_agent(
        AgentRunSpec(
            role="developer",
            provider=state.config.provider,
            model=state.config.model,
            prompt_md=prompt_md,
            repo_url=state.config.repo_url,
            base_branch=state.config.base_branch,
            working_branch=state.developer_branch,
            repo_path=node_run.repo_path,
            stdout_path=node_run.stdout_path,
            stderr_path=node_run.stderr_path,
            env=env,
            iteration=iteration,
        ),
        state.task_id,
    )
    report_md = result.report_md
    if not report_md:
        report_md = (
            "# Summary\nDeveloper execution failed.\n\n"
            f"# Findings\nstderr artifact: `{result.stderr_path}`\n\n"
            "# Remaining Work\nRetry with a clearer task.\n\n"
            "# Risks\nExecution error.\n\n"
            "# Handoff To CTO\nTask blocked."
        )
    state.loop_count = iteration
    state.stopped_by_limit = state.loop_count >= state.config.loop_limit
    state.reports["developer"] = report_md
    state.developer_result = result.model_dump(mode="json", exclude={"report_md"})
    state.approval_status = "continue"
    store.write_node_result(state, node_run, result.model_dump(mode="json", exclude={"report_md"}))
    store.write_node_report(state, node_run, report_md)
    store.finish_node(
        state,
        node_run,
        status=result.status,
        exit_code=result.exit_code,
    )
    store.save_state(state)

"""CTO controller node."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, cast

from agentsloop.domain.models import WorkflowState
from agentsloop.runtime.agent_runner import AgentRunSpec, run_agent
from agentsloop.runtime.git_runtime import run_git
from agentsloop.runtime.templates import (
    extract_section,
    parse_approval_status,
    parse_developer_branch,
    render_template,
    slugify,
)
from agentsloop.storage.json_store import RunStore


def ensure_developer_branch(state: WorkflowState) -> None:
    """Create the developer branch name once and reuse it afterward."""
    if state.developer_branch:
        return
    state.developer_branch = f"agent/dev/{slugify(state.human_request_md)}-{state.task_id_short}"


def build_validation_summary(state: WorkflowState) -> str:
    """Return the CTO prompt validation block."""
    validation = state.validation.get("validation")
    if not isinstance(validation, dict) or not validation:
        return "_none_"
    return (
        f"status: {validation.get('status') or ''}\n"
        f"exit_code: {validation.get('exit_code')}\n"
        f"branch: {validation.get('developer_branch') or ''}\n"
        f"command: {validation.get('command') or ''}\n"
        f"output:\n{validation.get('output') or ''}"
    )


def build_prompt(state: WorkflowState, prompts_dir: Path, store: RunStore) -> str:
    """Render the CTO prompt for the current state."""
    supports_reasoning = state.config.provider in {"codex", "copilot"}
    cto_reasoning_effort = state.config.cto_reasoning_effort if supports_reasoning else "_none_"
    developer_reasoning_effort = (
        state.config.developer_reasoning_effort if supports_reasoning else "_none_"
    )
    return render_template(
        prompts_dir / "cto_prompt.md",
        {
            "task_id": state.task_id,
            "repo_path": "current working directory (isolated /repo clone)",
            "base_branch": state.config.base_branch,
            "developer_branch": state.developer_branch,
            "developer_binary": state.config.provider,
            "cto_model": state.config.cto_model,
            "cto_reasoning_effort": cto_reasoning_effort,
            "developer_model": state.config.developer_model,
            "developer_reasoning_effort": developer_reasoning_effort,
            "loop_count": state.loop_count,
            "loop_limit": state.config.loop_limit,
            "human_request_md": state.human_request_md,
            "previous_cto_report": state.reports["cto"] or "_none_",
            "latest_developer_report": state.reports["developer"] or "_none_",
            "latest_developer_execution_log": state.developer_result.get("stderr_path") or "_none_",
            "validation_summary": build_validation_summary(state),
        },
    )


def parse_decision(state: WorkflowState, report_md: str) -> None:
    """Update state from the CTO Markdown report."""
    approval_status = parse_approval_status(report_md)
    # Update branch name if chosen by CTO in first iteration
    chosen_branch = parse_developer_branch(report_md)
    if chosen_branch and state.loop_count == 0:
        state.developer_branch = chosen_branch

    developer_task_md = extract_section(report_md, "Developer Task") or "_none_"
    human_response_md = extract_section(report_md, "Human Response") or "_none_"
    technical_summary_md = extract_section(report_md, "Technical Summary") or "_none_"
    stopped_by_limit = state.stopped_by_limit or state.loop_count >= state.config.loop_limit
    if not state.reports.get("developer") and approval_status == "done":
        approval_status = "continue"
        developer_task_md = state.human_request_md
        human_response_md = "I am handing the task to the developer now."
        technical_summary_md = "The CTO cannot mark work as done before a developer report exists."
    if stopped_by_limit and approval_status != "done":
        approval_status = "done"
        developer_task_md = "_none_"
        human_response_md = (
            f"Execution stopped after reaching the loop limit ({state.config.loop_limit})."
        )
        technical_summary_md = (
            f"Loop guard triggered at {state.loop_count}/{state.config.loop_limit} cycles."
        )

    # If the CTO said done, it's a success regardless of the limit
    if approval_status == "done" and not technical_summary_md.startswith("Loop guard triggered"):
        state.status = "success"
    elif stopped_by_limit:
        state.status = "stopped"
    else:
        state.status = "running"

    state.approval_status = cast(Literal["continue", "done"], approval_status)
    state.stopped_by_limit = stopped_by_limit
    state.reports["cto"] = report_md
    state.reports["human_response"] = human_response_md
    state.reports["technical_summary"] = technical_summary_md
    state.cto_result = {
        "approval_status": approval_status,
        "developer_task_md": developer_task_md,
        "human_response_md": human_response_md,
        "technical_summary_md": technical_summary_md,
        "report_md": report_md,
    }


def run_cto(
    state: WorkflowState,
    prompts_dir: Path,
    env: dict[str, str],
    store: RunStore,
) -> None:
    """Execute one CTO pass."""
    ensure_developer_branch(state)
    prompt_md = build_prompt(state, prompts_dir, store)
    supports_reasoning = state.config.provider in {"codex", "copilot"}
    reasoning_effort = state.config.cto_reasoning_effort if supports_reasoning else None
    node_run = store.start_node(
        state,
        role="cto",
        iteration=state.loop_count,
        provider=state.config.provider,
        model=state.config.cto_model,
        reasoning_effort=reasoning_effort,
        prompt_md=prompt_md,
    )
    result = run_agent(
        AgentRunSpec(
            role="cto",
            provider=state.config.provider,
            model=state.config.cto_model,
            reasoning_effort=reasoning_effort,
            prompt_md=prompt_md,
            repo_url=state.config.repo_url,
            base_branch=state.config.base_branch,
            working_branch=state.developer_branch,
            repo_path=node_run.repo_path,
            stdout_path=node_run.stdout_path,
            stderr_path=node_run.stderr_path,
            env=env,
            iteration=state.loop_count,
        ),
        state.task_id,
    )

    report_md = result.report_md or "# Controller\napproval_status: continue\n"
    store.write_node_result(state, node_run, result.model_dump(mode="json", exclude={"report_md"}))
    store.write_node_report(state, node_run, report_md)
    if result.status == "error":
        state.status = "error"
        summary = result.report_md.strip().splitlines()[0] if result.report_md.strip() else ""
        if summary:
            state.failure_message = f"CTO node failed: {summary}"
        else:
            state.failure_message = f"CTO node failed with exit code {result.exit_code}"
        store.finish_node(
            state,
            node_run,
            status=result.status,
            exit_code=result.exit_code,
        )
        store.save_state(state)
        raise RuntimeError(state.failure_message)
    parse_decision(state, report_md)

    # Ensure the developer branch is pushed to origin during the first CTO iteration.
    # This fulfills the CTO prompt mandate and ensures the branch exists on remote.
    if state.loop_count == 0:
        # In case the CTO chose a different branch name in the report, ensure it's checked out.
        run_git(
            ["checkout", "-B", state.developer_branch],
            Path(result.repo_path),
            env,
            check=True,
        )
        run_git(
            ["push", "-u", "origin", state.developer_branch],
            Path(result.repo_path),
            env,
            check=True,
        )

    store.finish_node(
        state,
        node_run,
        status=result.status,
        exit_code=result.exit_code,
        approval_status=state.approval_status,
    )
    store.save_state(state)

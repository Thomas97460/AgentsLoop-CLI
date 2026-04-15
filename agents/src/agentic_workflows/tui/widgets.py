"""Reusable Textual rendering helpers."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import DataTable, RichLog

from agentic_workflows.domain.models import NodeRun, RunSummary, WorkflowEvent, WorkflowState


def status_text(status: str) -> Text:
    """Return colored status text."""
    colors = {
        "running": "#8fd694",
        "success": "#8fd694",
        "error": "#ff6b6b",
        "stopped": "#f3c66d",
        "done": "#8fd694",
        "continue": "#f3c66d",
    }
    return Text(status, style=colors.get(status, "#ecefe7"))


def populate_runs_table(table: DataTable[str], runs: list[RunSummary]) -> None:
    """Fill a runs table with compact workflow metadata."""
    table.clear(columns=True)
    for column in ("Run", "Status", "Loops", "Updated", "Request"):
        table.add_column(column)
    for run in runs:
        table.add_row(
            run.task_id,
            run.status,
            str(run.loop_count),
            run.updated_at,
            run.request_preview.replace("\n", " "),
            key=run.task_id,
        )


def populate_timeline(table: DataTable[str], nodes: list[NodeRun]) -> None:
    """Fill a node timeline table."""
    table.clear(columns=True)
    for column in ("Node", "Status", "Exit"):
        table.add_column(column)
    for node in nodes:
        table.add_row(
            f"{node.role.upper()} {node.iteration:02d}",
            node.status,
            "-" if node.exit_code is None else str(node.exit_code),
            key=node.key,
        )


def populate_events(log: RichLog, events: list[WorkflowEvent]) -> None:
    """Render workflow events into a RichLog."""
    log.clear()
    for event in events[-80:]:
        details = " ".join(f"{key}={value}" for key, value in event.fields.items())
        log.write(Text.assemble((event.ts, "dim"), " ", (event.event, "#8fd694"), " ", details))


def selected_row_key(table: DataTable[str]) -> str | None:
    """Return the selected row key from a table when available."""
    if table.cursor_row < 0 or table.row_count == 0:
        return None
    return str(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value)


def state_markdown(state: WorkflowState) -> str:
    """Render a workflow state summary as Markdown."""
    return "\n".join(
        [
            f"# Workflow `{state.task_id}`",
            "",
            f"- status: `{state.status}`",
            f"- approval_status: `{state.approval_status}`",
            f"- model: `{state.config.model}`",
            f"- loop_count: `{state.loop_count}/{state.config.loop_limit}`",
            f"- developer_branch: `{state.developer_branch or '_none_'}`",
            "",
            "## Human Request",
            "",
            state.human_request_md,
            "",
            "## Human Response",
            "",
            state.reports.get("human_response") or "_none_",
            "",
            "## Technical Summary",
            "",
            state.reports.get("technical_summary") or "_none_",
        ]
    )


def node_report_markdown(state: WorkflowState, node_key: str | None) -> str:
    """Return the selected node report or workflow overview."""
    if node_key is None:
        return state_markdown(state)
    node = next((item for item in state.node_runs if item.key == node_key), None)
    if node is None:
        return state_markdown(state)
    if not node.report_path.exists():
        return f"# {node.role.upper()} {node.iteration:02d}\n\n_Report pending._"
    return node.report_path.read_text(encoding="utf-8")

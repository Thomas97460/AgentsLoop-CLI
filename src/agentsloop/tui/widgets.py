"""Reusable Textual rendering helpers."""

from __future__ import annotations

from art import text2art
from rich.align import Align
from rich.console import RenderableType
from rich.text import Text
from textual.widgets import DataTable, RichLog, Static

from agentsloop.domain.models import NodeRun, RunSummary, WorkflowEvent


class LargeLogo(Static):
    """A high-quality slanted ASCII art logo, framed and centered."""

    def render(self) -> RenderableType:
        """Render the large slanted ASCII logo with a heavy frame."""
        # Use 'slant' for the slanted look as requested
        agents_part = text2art("AGENTS", font="slant")
        loop_part = text2art("LOOP", font="slant")

        # Split both into lines so we can combine them horizontally.
        agents_lines = agents_part.splitlines()
        loop_lines = loop_part.splitlines()

        # Build the core logo lines with theme variables
        logo_lines = []
        max_width = 0
        for agents_line, loop_line in zip(agents_lines, loop_lines, strict=True):
            line = Text()
            line.append(agents_line, style="bold $foreground")
            # Always orange as requested
            line.append(loop_line, style="bold #f0a35a")
            logo_lines.append(line)
            max_width = max(max_width, line.cell_len)

        # Add a heavy frame (double lines) around the logo
        framed_logo = Text()
        border_style = "$primary 60%"

        # content width is max_width. Top/Bottom border characters: ╔ ═ ╗ ║ ╚ ╝
        framed_logo.append("╔" + "═" * (max_width + 2) + "╗\n", style=border_style)

        # Content with side borders
        for line in logo_lines:
            padding = " " * (max_width - line.cell_len)
            framed_logo.append("║ ", style=border_style)
            framed_logo.append(line)
            framed_logo.append(padding + " ║\n", style=border_style)

        # Bottom border
        framed_logo.append("╚" + "═" * (max_width + 2) + "╝", style=border_style)

        return Align.center(framed_logo, vertical="middle")


def status_text(status: str) -> Text:
    """Return colored status text."""
    colors = {
        "running": "#f0a35a",
        "success": "#7fbf9a",
        "error": "#e07868",
        "stopped": "#d7b66f",
        "done": "#7fbf9a",
        "continue": "#f0a35a",
    }
    return Text(status, style=colors.get(status, "#eee7dd"))


def populate_runs_table(table: DataTable[str], runs: list[RunSummary]) -> None:
    """Fill a runs table with compact workflow metadata."""
    table.clear(columns=True)
    # Using a slightly cleaner column set
    for column in ("ID", "STATUS", "LOOPS", "UPDATED", "REQUEST"):
        table.add_column(column)
    for run in runs:
        # Format ID and status more cleanly
        status = status_text(run.status)
        table.add_row(
            run.task_id[:8],
            status.markup,
            str(run.loop_count),
            run.updated_at.split("T")[0],  # Simpler date
            run.request_preview.replace("\n", " ")[:60],
            key=run.task_id,
        )


def populate_events(log: RichLog, events: list[WorkflowEvent]) -> None:
    """Render workflow events into a RichLog."""
    log.clear()
    for event in events[-80:]:
        details = " ".join(f"{key}={value}" for key, value in event.fields.items())
        log.write(Text.assemble((event.ts, "dim"), " ", (event.event, "#f0a35a"), " ", details))


def populate_nodes_table(table: DataTable[str], nodes: list[NodeRun]) -> None:
    """Fill a node table with execution history."""
    table.clear(columns=True)
    table.add_column("ITER")
    table.add_column("NODE")
    table.add_column("STATUS")
    for node in nodes:
        status = status_text(node.status)
        table.add_row(
            f"{node.iteration:02d}",
            node.role.upper(),
            status.markup,
            key=f"{node.role}:{node.iteration}",
        )


def node_report_markdown(node: NodeRun) -> str:
    """Render a node report as Markdown."""
    if not node.report_path.exists():
        return f"# {node.role.upper()} {node.iteration:02d}\n\n_Report pending._"

    try:
        report = node.report_path.read_text(encoding="utf-8")
        return f"# {node.role.upper()} {node.iteration:02d}\n\n{report}"
    except Exception as exc:
        return f"### Error reading report\n\n{exc!s}"

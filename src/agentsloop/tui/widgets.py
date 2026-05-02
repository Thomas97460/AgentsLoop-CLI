"""Reusable Textual rendering helpers."""

from __future__ import annotations

from art import text2art
from rich.align import Align
from rich.console import RenderableType
from rich.text import Text
from textual.timer import Timer
from textual.widgets import DataTable, RichLog, Static

from agentsloop.domain.models import NodeRun, RunSummary, WorkflowEvent

ROLE_LABELS = {
    "cto": "CTO",
    "developer": "Developer",
    "validation": "Validation / Tests",
}


class LargeLogo(Static):
    """A high-quality slanted ASCII art logo, framed and centered."""

    def render(self) -> RenderableType:
        """Render the large slanted ASCII logo with a heavy frame."""
        agents_part = text2art("AGENTS", font="slant")
        loop_part = text2art("LOOP", font="slant")
        agents_lines = agents_part.splitlines()
        loop_lines = loop_part.splitlines()

        logo_lines = []
        max_width = 0
        for agents_line, loop_line in zip(agents_lines, loop_lines, strict=True):
            line = Text()
            line.append(agents_line, style="bold $foreground")
            line.append(loop_line, style="bold #f0a35a")
            logo_lines.append(line)
            max_width = max(max_width, line.cell_len)

        framed_logo = Text()
        border_style = "$primary 60%"
        framed_logo.append("╔" + "═" * (max_width + 2) + "╗\n", style=border_style)
        for line in logo_lines:
            padding = " " * (max_width - line.cell_len)
            framed_logo.append("║ ", style=border_style)
            framed_logo.append(line)
            framed_logo.append(padding + " ║\n", style=border_style)
        framed_logo.append("╚" + "═" * (max_width + 2) + "╝", style=border_style)
        return Align.center(framed_logo, vertical="middle")


class LoadingLogo(Static):
    """An animated version of the LargeLogo with a rotating progress border."""

    can_focus = True

    def on_mount(self) -> None:
        """Start the animation."""
        self.frame = 0
        self._animation_timer: Timer = self.set_interval(0.05, self.refresh)

    def pause_animation(self) -> None:
        """Pause the logo animation."""
        self._animation_timer.pause()

    def resume_animation(self) -> None:
        """Resume the logo animation."""
        self._animation_timer.resume()

    def render(self) -> RenderableType:
        """Render the logo with a rotating orange segment on the full border."""
        self.frame += 6
        agents_art = text2art("AGENTS", font="slant")
        loop_art = text2art("LOOP", font="slant")
        lines = []
        for agents_line, loop_line in zip(
            agents_art.splitlines(), loop_art.splitlines(), strict=True
        ):
            t = Text()
            t.append(agents_line, style="bold $foreground")
            t.append(loop_line, style="bold #f0a35a")
            lines.append(t)

        w = max(line.cell_len for line in lines)
        working_line = Text("is working...".center(w), style="dim $foreground")
        lines.append(working_line)
        h = len(lines)
        w2 = w + 2

        # Border: Top(w2), Right(h), Bottom(w2), Left(h)
        # Sequence indices to map
        border_len = (w2 * 2) + (h * 2)
        idx = self.frame % border_len

        def get_style(i: int) -> str:
            # sliding window of 8 chars
            if idx <= i < idx + 8 or (idx + 8 > border_len and (idx + 8) % border_len > i):
                return "bold #f0a35a"
            return "$primary"

        # Construct frame
        f = Text()
        # Top
        f.append("╔", style=get_style(0))
        for i in range(w2):
            f.append("═", style=get_style(i + 1))
        f.append("╗\n", style=get_style(w2 + 1))

        # Middle
        for r, line in enumerate(lines):
            f.append("║", style=get_style(border_len - 1 - r))
            f.append(" ")
            f.append(line)
            f.append(" ║\n", style=get_style(w2 + 2 + r))

        # Bottom
        f.append("╚", style=get_style(w2 + 1 + h + w2 + 1))
        for i in range(w2):
            # Reverse direction: w2+1+h is index of right side bottom, count backwards for the line
            f.append("═", style=get_style(w2 + 1 + h + (w2 - i)))
        f.append("╝", style=get_style(w2 + 1 + h))

        return Align.center(f, vertical="middle")


def status_text(status: str) -> Text:
    """Return colored status text."""
    colors = {
        "running": "#f0a35a",
        "stopping": "#d7b66f",
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
    for column in ("APPLICATION / WORKFLOW", "STATUS", "PROVIDER", "LOOPS", "UPDATED", "REQUEST"):
        table.add_column(column)

    for index, (application, app_runs) in enumerate(_group_runs_by_application(runs).items()):
        if index > 0:
            table.add_row("", "", "", "", "", "", key=f"spacer:app:{application}")
        table.add_row(
            f"[bold $primary]{application}[/]",
            "",
            "",
            "",
            _workflow_count_label(len(app_runs)),
            "",
            key=f"app:{application}",
        )
        for run in app_runs:
            status = status_text(run.status)
            table.add_row(
                f"  {run.task_id[:8]}",
                status.markup,
                run.provider,
                str(run.loop_count),
                _compact_timestamp(run.updated_at),
                run.request_preview.replace("\n", " ")[:60],
                key=run.task_id,
            )


def _group_runs_by_application(runs: list[RunSummary]) -> dict[str, list[RunSummary]]:
    """Return runs grouped in first-seen order."""
    grouped: dict[str, list[RunSummary]] = {}
    for run in runs:
        grouped.setdefault(run.application, []).append(run)
    return grouped


def _workflow_count_label(count: int) -> str:
    """Return a compact workflow count label."""
    if count == 1:
        return "1 workflow"
    return f"{count} workflows"


def _compact_timestamp(value: str) -> str:
    """Return a compact local-ish timestamp from an ISO timestamp."""
    date, separator, time = value.partition("T")
    if not separator:
        return value[:16]
    return f"{date} {time[:5]}"


def populate_events(log: RichLog, events: list[WorkflowEvent]) -> None:
    """Render workflow events into a RichLog."""
    log.clear()
    for event in events[-80:]:
        log.write(
            Text.assemble(
                (event.ts, "dim"),
                " ",
                (event.event, "#f0a35a"),
                " ",
                _event_details(event),
            )
        )


def workflow_events_plain_text(events: list[WorkflowEvent]) -> str:
    """Render workflow events as copyable plain text."""
    return "\n".join(
        f"{event.ts} {event.event} {_event_details(event)}".rstrip() for event in events[-80:]
    )


def _event_details(event: WorkflowEvent) -> str:
    """Return compact event fields text."""
    return " ".join(f"{key}={value}" for key, value in event.fields.items())


def populate_nodes_table(table: DataTable[str], nodes: list[NodeRun]) -> None:
    """Fill a node table with execution history grouped by iteration."""
    table.clear(columns=True)
    table.add_column("ITER")
    table.add_column("ROLE")
    table.add_column("AGENT")
    table.add_column("STATUS")
    table.add_column("OUTPUT")

    last_iteration = -1
    for node in nodes:
        if node.iteration != last_iteration:
            if last_iteration != -1:
                table.add_row("", "", "", "", "", key=f"spacer:iteration:{node.iteration}")
            table.add_row(
                f"[bold $primary on $surface] Iteration {node.iteration:02d} [/]",
                "",
                "",
                "",
                _iteration_node_count(nodes, node.iteration),
                key=f"iteration:{node.iteration}",
            )
            last_iteration = node.iteration

        status = status_text(node.status)
        table.add_row(
            "",
            ROLE_LABELS[node.role],
            _node_agent_label(node),
            status.markup,
            _node_output_label(node),
            key=f"{node.role}:{node.iteration}",
        )


def _iteration_node_count(nodes: list[NodeRun], iteration: int) -> str:
    """Return the number of nodes in one iteration."""
    count = sum(1 for node in nodes if node.iteration == iteration)
    if count == 1:
        return "1 node"
    return f"{count} nodes"


def _node_output_label(node: NodeRun) -> str:
    """Return a compact node output availability label."""
    if node.status == "running":
        return "[#f0a35a]live[/]"
    if node.report_path.exists():
        return "report"
    if node.stdout_path.exists() or node.stderr_path.exists():
        return "logs"
    return "-"


def _node_agent_label(node: NodeRun) -> str:
    """Return a compact provider/model label for one node."""
    if node.provider is None:
        return "-"
    if node.model is None:
        return node.provider
    if node.reasoning_effort is None:
        return f"{node.provider} / {node.model}"
    return f"{node.provider} / {node.model} / {node.reasoning_effort}"


def node_report_markdown(node: NodeRun) -> str | None:
    """Render a node report as Markdown. Returns None if loading."""
    if not node.report_path.exists():
        return None
    try:
        report = node.report_path.read_text(encoding="utf-8")
        return f"# {node.role.upper()} {node.iteration:02d}\n\n{report}"
    except Exception as exc:
        return f"### Error reading report\n\n{exc!s}"

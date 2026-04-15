"""Textual screens for launching and browsing workflows."""

from __future__ import annotations

import uuid
from typing import cast

from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import (
    Button,
    Collapsible,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    LoadingIndicator,
    Markdown,
    RichLog,
    Select,
    Static,
    TextArea,
)

from agentic_workflows.domain.models import (
    DEFAULT_GEMINI_MODEL,
    GEMINI_MODELS,
    GeminiModel,
    RuntimeConfig,
)
from agentic_workflows.runtime.workflow_launcher import spawn_workflow_process
from agentic_workflows.storage.json_store import RunStore
from agentic_workflows.tui.widgets import (
    node_report_markdown,
    populate_events,
    populate_runs_table,
    populate_timeline,
    selected_row_key,
    state_markdown,
)

DEFAULT_REPO_URL = "git@github.com:Thomas97460/hyperliquid-ml-trading.git"


class HomeScreen(Screen[None]):
    """Home screen with workflow history."""

    BINDINGS = [
        ("r", "refresh", "Refresh"),
        ("n", "new", "New workflow"),
        ("enter", "open_selected", "Open"),
        ("q", "app.quit", "Quit"),
    ]

    def __init__(self, store: RunStore) -> None:
        super().__init__()
        self.store = store

    def compose(self) -> ComposeResult:
        """Compose the home screen."""
        yield Header(show_clock=True)
        with Vertical(classes="page"):
            with Container(classes="hero"):
                yield Label("Agentic Workflows", classes="title")
                yield Static(
                    "Launch, monitor, and review CTO -> Developer -> CI loops.", classes="subtitle"
                )
            yield DataTable[str](id="runs")
        yield Footer()

    def on_mount(self) -> None:
        """Load history on mount."""
        self.action_refresh()

    def action_refresh(self) -> None:
        """Refresh the run table."""
        populate_runs_table(self.query_one("#runs", DataTable), self.store.list_runs())

    def action_new(self) -> None:
        """Open the launch screen."""
        self.app.push_screen(LaunchScreen(self.store))

    def action_open_selected(self) -> None:
        """Open the selected workflow."""
        task_id = selected_row_key(self.query_one("#runs", DataTable))
        if task_id is not None:
            self.app.push_screen(DetailScreen(self.store, task_id))


class LaunchScreen(Screen[None]):
    """Workflow launch form."""

    BINDINGS = [("escape", "app.pop_screen", "Back")]

    def __init__(self, store: RunStore) -> None:
        super().__init__()
        self.store = store

    def compose(self) -> ComposeResult:
        """Compose the launch form."""
        yield Header(show_clock=True)
        with Vertical(classes="page"):
            with Container(classes="hero"):
                yield Label("New Workflow", classes="title")
                yield Static(
                    "Describe the objective, choose the Gemini model, then follow the run live."
                )
            yield TextArea("", id="request")
            yield Select[GeminiModel](
                [(model, model) for model in GEMINI_MODELS],
                value=DEFAULT_GEMINI_MODEL,
                allow_blank=False,
                id="model",
                prompt="Gemini model",
            )
            yield Input(placeholder="Loop limit", value="3", id="loop_limit")
            with Collapsible(title="Advanced", collapsed=True):
                yield Input(placeholder="Base branch", value="main", id="base_branch")
                yield Input(placeholder="Repository SSH URL", value=DEFAULT_REPO_URL, id="repo_url")
            with Horizontal(classes="actions"):
                yield Button("Run", variant="success", id="run")
                yield Button("Back", id="back")
        yield Footer()

    @on(Button.Pressed, "#back")
    def back(self) -> None:
        """Return to the previous screen."""
        self.app.pop_screen()

    @on(Button.Pressed, "#run")
    def launch(self) -> None:
        """Start a workflow and open its live view."""
        request = self.query_one("#request", TextArea).text.strip()
        if not request:
            self.notify("Request is required", severity="error")
            return
        model = self._selected_model()
        loop_limit = self._loop_limit()
        if model is None or loop_limit is None:
            return
        config = RuntimeConfig(
            model=model,
            repo_url=self.query_one("#repo_url", Input).value,
            base_branch=self.query_one("#base_branch", Input).value,
            loop_limit=loop_limit,
        )
        task_id = str(uuid.uuid4())
        launch = spawn_workflow_process(
            human_request_md=request,
            config=config,
            task_id=task_id,
            runs_dir=self.store.runs_dir,
        )
        self.app.push_screen(LiveScreen(self.store, launch.task_id))

    def _selected_model(self) -> GeminiModel | None:
        """Return the selected model after UI validation."""
        value = self.query_one("#model", Select).value
        if value not in GEMINI_MODELS:
            self.notify("Select a supported Gemini model", severity="error")
            return None
        return cast(GeminiModel, value)

    def _loop_limit(self) -> int | None:
        """Return the loop limit after UI validation."""
        raw_value = self.query_one("#loop_limit", Input).value
        try:
            loop_limit = int(raw_value)
        except ValueError:
            self.notify("Loop limit must be an integer", severity="error")
            return None
        if loop_limit < 1:
            self.notify("Loop limit must be at least 1", severity="error")
            return None
        return loop_limit


class LiveScreen(Screen[None]):
    """Live workflow reader screen."""

    BINDINGS = [("escape", "app.pop_screen", "Back"), ("r", "refresh", "Refresh")]

    def __init__(self, store: RunStore, task_id: str) -> None:
        super().__init__()
        self.store = store
        self.task_id = task_id
        self.selected_node: str | None = None

    def compose(self) -> ComposeResult:
        """Compose the live workflow screen."""
        yield Header(show_clock=True)
        with Vertical(classes="page"):
            with Container(classes="hero"):
                yield Label("Live Workflow", classes="title")
                yield Static(f"Run `{self.task_id}`.", classes="subtitle")
                yield LoadingIndicator()
            with Horizontal(id="live-grid"):
                yield DataTable[str](id="timeline")
                yield Markdown(id="report")
            yield RichLog(id="events", highlight=True, markup=True)
        yield Footer()

    def on_mount(self) -> None:
        """Start polling persisted workflow artifacts."""
        self.set_interval(0.5, self.refresh_live)
        self.refresh_live()

    def action_refresh(self) -> None:
        """Refresh the live view from persisted artifacts."""
        self.refresh_live()

    @on(DataTable.RowHighlighted, "#timeline")
    def select_node(self, event: DataTable.RowHighlighted) -> None:
        """Update the rendered report when the timeline selection changes."""
        self.selected_node = str(event.row_key.value)
        self.refresh_report()

    def refresh_live(self) -> None:
        """Refresh timeline, report, and events."""
        populate_events(self.query_one("#events", RichLog), self.store.read_events(self.task_id))
        state_path = self.store.runs_dir / self.task_id / "state.json"
        if not state_path.exists():
            return
        state = self.store.load_state(self.task_id)
        populate_timeline(self.query_one("#timeline", DataTable), state.node_runs)
        if self.selected_node is None and state.node_runs:
            self.selected_node = state.node_runs[-1].key
        self.query_one("#report", Markdown).update(node_report_markdown(state, self.selected_node))

    def refresh_report(self) -> None:
        """Refresh only the selected report pane."""
        state_path = self.store.runs_dir / self.task_id / "state.json"
        if state_path.exists():
            state = self.store.load_state(self.task_id)
            self.query_one("#report", Markdown).update(
                node_report_markdown(state, self.selected_node)
            )


class DetailScreen(Screen[None]):
    """Workflow detail screen."""

    BINDINGS = [("escape", "app.pop_screen", "Back"), ("r", "refresh", "Refresh")]

    def __init__(self, store: RunStore, task_id: str) -> None:
        super().__init__()
        self.store = store
        self.task_id = task_id
        self.selected_node: str | None = None

    def compose(self) -> ComposeResult:
        """Compose the workflow detail screen."""
        yield Header(show_clock=True)
        with Vertical(classes="page"):
            with Container(classes="hero"):
                yield Label("Workflow History", classes="title")
                yield Static(f"Run `{self.task_id}`.", classes="subtitle")
            yield Markdown(id="summary")
            with Horizontal(id="detail-grid"):
                yield DataTable[str](id="timeline")
                yield Markdown(id="report")
            yield RichLog(id="events", highlight=True, markup=True)
        yield Footer()

    def on_mount(self) -> None:
        """Load run details."""
        self.action_refresh()

    def action_refresh(self) -> None:
        """Refresh persisted run details."""
        state = self.store.load_state(self.task_id)
        self.query_one("#summary", Markdown).update(state_markdown(state))
        populate_timeline(self.query_one("#timeline", DataTable), state.node_runs)
        populate_events(self.query_one("#events", RichLog), self.store.read_events(self.task_id))
        if self.selected_node is None and state.node_runs:
            self.selected_node = state.node_runs[-1].key
        self.query_one("#report", Markdown).update(node_report_markdown(state, self.selected_node))

    @on(DataTable.RowHighlighted, "#timeline")
    def select_node(self, event: DataTable.RowHighlighted) -> None:
        """Update the report when the selected timeline row changes."""
        self.selected_node = str(event.row_key.value)
        state = self.store.load_state(self.task_id)
        self.query_one("#report", Markdown).update(node_report_markdown(state, self.selected_node))

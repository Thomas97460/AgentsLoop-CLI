"""Textual screens for launching and browsing workflows."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import ClassVar, cast

from textual import on
from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import (
    Button,
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

from agentsloop.domain.models import (
    DEFAULT_GEMINI_MODEL,
    DEFAULT_VALIDATION_COMMAND,
    GEMINI_MODELS,
    GeminiModel,
    RuntimeConfig,
    WorkflowState,
)
from agentsloop.project_config import ProjectContext
from agentsloop.runtime.git_runtime import env_with_agent_ssh, verify_git_write_access
from agentsloop.runtime.workflow_launcher import spawn_workflow_process
from agentsloop.storage.json_store import RunStore
from agentsloop.tui.widgets import (
    LargeLogo,
    node_report_markdown,
    populate_events,
    populate_nodes_table,
    populate_runs_table,
)


class WarningScreen(Screen[None]):
    """Mandatory security warning before entering the application."""

    def __init__(self, store: RunStore, project_context: ProjectContext) -> None:
        super().__init__()
        self.store = store
        self.project_context = project_context

    def compose(self) -> ComposeResult:
        """Compose the warning view."""
        with Vertical(classes="warning-container"):
            with Vertical(classes="warning-panel"):
                yield Label("CRITICAL SECURITY WARNING", classes="warning-title")
                yield Static(
                    "Agents operate in autonomous (YOLO) mode. It is critical to run them "
                    "in a controlled environment and ensure your repository's main branch is protected.\n\n"
                    "Users are solely responsible for all actions performed by the agents; no liability "
                    "is assumed for any unintended consequences or damages.",
                    classes="warning-text",
                )
                with Horizontal(classes="actions centered-actions"):
                    yield Button("I Understand & Accept", variant="success", id="accept")
                    yield Button("Quit", variant="error", id="quit")

    @on(Button.Pressed, "#accept")
    def accept(self) -> None:
        """Move to the loading screen."""
        self.app.switch_screen(LoadingScreen(self.store, self.project_context))

    @on(Button.Pressed, "#quit")
    def quit_app(self) -> None:
        """Exit the application."""
        self.app.exit()


class LoadingScreen(Screen[None]):
    """Startup screen that verifies repository access."""

    def __init__(self, store: RunStore, project_context: ProjectContext) -> None:
        super().__init__()
        self.store = store
        self.project_context = project_context

    def compose(self) -> ComposeResult:
        """Compose the loading view."""
        with Vertical(classes="loading-container"):
            yield LargeLogo()
            yield LoadingIndicator(id="loader")
            yield Label("Verifying repository access...", id="loading-status")
            yield Static("", id="error-details", classes="error-text")
            with Horizontal(id="loading-actions", classes="hidden"):
                yield Button("Quit", variant="error", id="quit")

    def on_mount(self) -> None:
        """Skip verification and move to next screen."""
        if self.project_context.configured:
            self.app.switch_screen(HomeScreen(self.store, self.project_context))
        else:
            self.app.switch_screen(ProjectSetupScreen(self.store, self.project_context))

    def _handle_error(self, message: str) -> None:
        """Show error state in the UI."""
        self.query_one("#loader").add_class("hidden")
        self.query_one("#loading-status", Label).update("[bold red]Access Verification Failed[/]")
        self.query_one("#error-details", Static).update(message)
        self.query_one("#loading-actions").remove_class("hidden")

    @on(Button.Pressed, "#quit")
    def quit_app(self) -> None:
        """Exit the application."""
        self.app.exit()


class HomeScreen(Screen[None]):
    """Home screen with workflow history."""

    BINDINGS: ClassVar[list[BindingType]] = [
        ("r", "refresh", "Refresh"),
        ("n", "new", "New workflow"),
        ("q", "app.quit", "Quit"),
    ]

    def __init__(self, store: RunStore, project_context: ProjectContext) -> None:
        super().__init__()
        self.store = store
        self.project_context = project_context

    def compose(self) -> ComposeResult:
        """Compose the home screen."""
        with Vertical(classes="page"):
            with Vertical(classes="home-header"):
                yield LargeLogo(classes="home-logo")

            with Vertical(classes="table-container"):
                yield Label("WORKFLOWS", classes="table-title")
                yield DataTable[str](id="runs", cursor_type="row")

            with Horizontal(classes="home-footer"):
                yield Static(
                    "[bold]N[/] New   [bold]ENTER[/] Open   [bold]R[/] Refresh   [bold]Q[/] Quit",
                    classes="home-hints",
                )
        yield Footer()

    def on_mount(self) -> None:
        """Load history on mount and set title."""
        self.app.title = f"AgentsLoop - {self.project_context.repo_root.name}"
        self.app.sub_title = str(self.project_context.repo_root)
        self.action_refresh()
        self.query_one("#runs", DataTable).focus()
        # Auto-refresh home screen every 3 seconds to update statuses
        self.set_interval(3.0, self.action_refresh)

    def action_refresh(self) -> None:
        """Refresh the run table."""
        populate_runs_table(self.query_one("#runs", DataTable), self.store.list_runs())

    @on(DataTable.RowSelected, "#runs")
    def on_row_selected(self, event: DataTable.RowSelected) -> None:
        """Open the selected workflow."""
        task_id = str(event.row_key.value)
        self.app.push_screen(WorkflowScreen(self.store, task_id))

    def action_new(self) -> None:
        """Open the launch screen."""
        self.app.push_screen(LaunchScreen(self.store, self.project_context))


class ProjectSetupScreen(Screen[None]):
    """First-run setup for a repository."""

    BINDINGS: ClassVar[list[BindingType]] = [("q", "app.quit", "Quit")]

    def __init__(self, store: RunStore, project_context: ProjectContext) -> None:
        super().__init__()
        self.store = store
        self.project_context = project_context

    def compose(self) -> ComposeResult:
        """Compose the first-run setup form."""
        yield Header(show_clock=True)
        with Vertical(classes="page"):
            with Container(classes="hero"):
                yield Label("Project Setup", classes="title")
                yield Static(
                    "AgentsLoop uses the current Git repository and needs one validation command."
                )
            with Vertical(id="setup-panel", classes="panel"):
                yield Label("Current repository", classes="field-label")
                yield Static(str(self.project_context.repo_root), classes="repo-path")
                yield Label("Validation command", classes="field-label")
                yield Input(
                    value=self.project_context.validation_command,
                    placeholder=DEFAULT_VALIDATION_COMMAND,
                    id="validation_command",
                )
                yield Label("Git SSH Key Path", classes="field-label")
                yield Input(
                    value=str(self.project_context.ssh_key_path),
                    placeholder="~/.ssh/id_ed25519",
                    id="ssh_key_path",
                )
                yield Static(
                    "This key must have push access to the remote repository.",
                    classes="hint",
                )
            with Horizontal(classes="actions"):
                yield Button("Save", variant="success", id="save")
                yield Button("Quit", id="quit")
        yield Footer()

    def on_mount(self) -> None:
        """Focus the validation command input."""
        self.query_one("#validation_command", Input).focus()

    @on(Button.Pressed, "#save")
    def save(self) -> None:
        """Persist setup and open the home screen."""
        command = self.query_one("#validation_command", Input).value.strip()
        ssh_key = Path(self.query_one("#ssh_key_path", Input).value.strip()).expanduser()

        if not command:
            self.notify("Validation command is required", severity="error")
            return

        # Verify git access before saving
        try:
            env = env_with_agent_ssh(self.project_context.repo_root, ssh_key_path=ssh_key)
            verify_git_write_access(self.project_context.repo_root, env)
        except Exception as exc:
            self.notify(
                f"Cannot save: {exc!s}",
                title="Git Access Required",
                severity="error",
                timeout=10,
            )
            return

        self.project_context.save_config(command, ssh_key)
        self.app.switch_screen(HomeScreen(self.store, self.project_context))

    @on(Button.Pressed, "#quit")
    def quit(self) -> None:
        """Exit setup."""
        self.app.exit()


class LaunchScreen(Screen[None]):
    """Workflow launch form."""

    BINDINGS: ClassVar[list[BindingType]] = [("escape", "app.pop_screen", "Back")]

    def __init__(self, store: RunStore, project_context: ProjectContext) -> None:
        super().__init__()
        self.store = store
        self.project_context = project_context

    def on_mount(self) -> None:
        """Set screen title on mount."""
        self.app.title = "New Workflow"
        self.app.sub_title = str(self.project_context.repo_root)

    def compose(self) -> ComposeResult:
        """Compose the launch form."""
        with Vertical(classes="page"):
            with Horizontal(id="launch-grid"):
                with Vertical(id="launch-main", classes="panel"):
                    yield Label("GOAL", classes="field-label")
                    yield TextArea("", id="request")
                    yield Static(
                        "Describe what you want the loop to achieve.",
                        classes="hint",
                    )
                with Vertical(id="launch-side", classes="panel"):
                    yield Label("BASE BRANCH", classes="field-label")
                    yield Input(
                        placeholder=self.project_context.base_branch,
                        value=self.project_context.base_branch,
                        id="base_branch",
                    )
                    yield Label("GEMINI MODEL", classes="field-label")
                    yield Select[GeminiModel](
                        [(model, model) for model in GEMINI_MODELS],
                        value=DEFAULT_GEMINI_MODEL,
                        allow_blank=False,
                        id="model",
                        prompt="Select Model",
                    )
                    yield Label("VALIDATION COMMAND", classes="field-label")
                    yield Input(
                        placeholder=DEFAULT_VALIDATION_COMMAND,
                        value=self.project_context.validation_command,
                        id="validation_command",
                    )
                    yield Label("LOOP LIMIT", classes="field-label")
                    yield Input(placeholder="3", value="3", id="loop_limit")

            with Horizontal(id="launch-actions", classes="actions"):
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
        validation_command = self.query_one("#validation_command", Input).value.strip()
        if not validation_command:
            self.notify("Validation command is required", severity="error")
            return
        repo_url = self.project_context.remote_url or str(self.project_context.repo_root)
        if not self.project_context.remote_url:
            self.notify(
                "No 'origin' remote found. Work will only be pushed to your local repository.",
                severity="warning",
            )

        config = RuntimeConfig(
            model=model,
            repo_url=repo_url,
            ssh_key_path=self.project_context.ssh_key_path,
            base_branch=(
                self.query_one("#base_branch", Input).value.strip()
                or self.project_context.base_branch
            ),
            loop_limit=loop_limit,
            validation_command=validation_command,
        )
        task_id = str(uuid.uuid4())
        launch = spawn_workflow_process(
            human_request_md=request,
            config=config,
            task_id=task_id,
            runs_dir=self.store.runs_dir,
        )
        self.app.push_screen(WorkflowScreen(self.store, launch.task_id))

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


class WorkflowScreen(Screen[None]):
    """Unified live workflow and historical activity reader."""

    BINDINGS: ClassVar[list[BindingType]] = [
        ("escape", "app.pop_screen", "Back"),
        ("r", "refresh", "Refresh"),
    ]

    def __init__(self, store: RunStore, task_id: str) -> None:
        super().__init__()
        self.store = store
        self.task_id = task_id
        self._last_nodes_count = -1

    def compose(self) -> ComposeResult:
        """Compose the workflow screen."""
        with Vertical(classes="page"):
            with Horizontal(id="workflow-top"):
                with Vertical(id="workflow-nodes-panel"):
                    yield Label("NODES", classes="table-title")
                    yield DataTable[str](id="nodes", cursor_type="row")
                with Vertical(id="workflow-side-panel"):
                    yield Label("NODE REPORT", classes="table-title")
                    with Vertical(id="workflow-report-panel"):
                        yield Markdown(id="report")

            with Vertical(id="workflow-bottom"):
                yield Label("ACTIVITY LOG", classes="table-title")
                yield RichLog(id="events", highlight=True, markup=True)
        yield Footer()

    def on_mount(self) -> None:
        """Start polling workflow events."""
        self.app.title = f"Workflow {self.task_id[:8]}"
        self.app.sub_title = "Viewing activity..."
        self.set_interval(1.5, self.action_refresh)
        self.action_refresh()

    def action_refresh(self) -> None:
        """Refresh events and nodes from the store."""
        try:
            state = self.store.load_state(self.task_id)
            nodes = state.node_runs

            # Only update nodes table if count changed or first run
            if len(nodes) != self._last_nodes_count:
                table = self.query_one("#nodes", DataTable)
                current_key = None
                try:
                    if table.row_count > 0:
                        current_key = table.coordinate_to_cell_key(
                            table.cursor_coordinate
                        ).row_key.value
                except Exception:
                    pass

                populate_nodes_table(table, nodes)
                self._last_nodes_count = len(nodes)

                # Reselect or select last
                if current_key:
                    try:
                        table.move_cursor(row=table.get_row_index(current_key))
                    except Exception:
                        table.move_cursor(row=len(nodes) - 1)
                elif len(nodes) > 0:
                    table.move_cursor(row=len(nodes) - 1)

                self._update_report(state)

            # Always refresh the current report content to show live progress
            self._update_report(state)

            populate_events(
                self.query_one("#events", RichLog), self.store.read_events(self.task_id)
            )
        except Exception:
            pass

    @on(DataTable.RowSelected, "#nodes")
    def on_node_selected(self) -> None:
        """Update report when a node is selected."""
        try:
            state = self.store.load_state(self.task_id)
            self._update_report(state)
        except Exception:
            pass

    def _update_report(self, state: WorkflowState) -> None:
        """Update the Markdown report for the selected node."""
        table = self.query_one("#nodes", DataTable)
        if table.row_count == 0:
            return

        try:
            key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
            role, iter_str = str(key).split(":")
            iteration = int(iter_str)

            node = next(
                (n for n in state.node_runs if n.role == role and n.iteration == iteration), None
            )
            if node:
                self.query_one("#report", Markdown).update(node_report_markdown(node))
        except Exception:
            pass

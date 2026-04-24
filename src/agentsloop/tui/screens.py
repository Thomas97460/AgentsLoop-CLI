"""Textual screens for launching and browsing workflows."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, cast

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.timer import Timer
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
    DEFAULT_CODEX_REASONING_EFFORT,
    DEFAULT_PROVIDER,
    DEFAULT_VALIDATION_COMMAND,
    PROVIDERS,
    REASONING_EFFORTS,
    NodeRun,
    ProviderModel,
    ProviderName,
    ReasoningEffort,
    RuntimeConfig,
    WorkflowState,
    default_model_for_provider,
    models_for_provider,
)
from agentsloop.project_config import ProjectContext
from agentsloop.runtime.git_runtime import (
    env_with_agent_ssh,
    is_ssh_remote_url,
    list_available_ssh_keys,
    list_remote_branches,
    verify_git_write_access,
)
from agentsloop.runtime.workflow_control import reconcile_workflow_state, request_workflow_stop
from agentsloop.runtime.workflow_launcher import WorkflowContinuation, spawn_workflow_process
from agentsloop.storage.json_store import RunStore, read_text_tail
from agentsloop.tui.widgets import (
    LargeLogo,
    LoadingLogo,
    node_report_markdown,
    populate_events,
    populate_nodes_table,
    populate_runs_table,
    status_text,
    workflow_events_plain_text,
)

if TYPE_CHECKING:
    from agentsloop.tui.app import WorkflowApp


class WarningScreen(Screen[None]):
    """Mandatory security warning before entering the application."""

    def __init__(self, store: RunStore, project_context: ProjectContext) -> None:
        super().__init__()
        self.store = store
        self.project_context = project_context

    def compose(self) -> ComposeResult:
        """Compose the warning view."""
        with Vertical(classes="warning-container"), Vertical(classes="warning-panel"):
            yield Label("CRITICAL SECURITY WARNING", classes="warning-title")
            yield Static(
                "Agents operate in autonomous (YOLO) mode. It is critical to run them "
                "in a controlled environment and ensure your repository's main branch is "
                "protected.\n\nUsers are solely responsible for all actions performed "
                "by the agents; no liability is assumed for any unintended consequences "
                "or damages.",
                classes="warning-text",
            )
            with Horizontal(classes="actions centered-actions"):
                yield Button("I Understand & Accept", variant="success", id="accept")
                yield Button("Quit", variant="error", id="quit")

    @on(Button.Pressed, "#accept")
    def accept(self) -> None:
        """Move to the SSH key selection screen."""
        self.app.switch_screen(SSHKeySelectionScreen(self.store, self.project_context))

    @on(Button.Pressed, "#quit")
    def quit_app(self) -> None:
        """Exit the application."""
        self.app.exit()


class SSHKeySelectionScreen(Screen[None]):
    """Choose the Git SSH key before entering the application."""

    def __init__(self, store: RunStore, project_context: ProjectContext) -> None:
        super().__init__()
        self.store = store
        self.project_context = project_context
        self.available_keys = list_available_ssh_keys()

    def compose(self) -> ComposeResult:
        """Compose the SSH key selection view."""
        with Vertical(classes="page"):
            with Vertical(classes="panel"):
                yield Label("GIT SSH KEY SELECTION", classes="table-title")
                yield Static(
                    "Select the SSH key to be used for Git operations. "
                    "This key must have write access to the repository.",
                    classes="hint",
                )

                options = [(str(key), str(key)) for key in self.available_keys]
                default_value = str(self.project_context.ssh_key_path)

                # Ensure the current key is in options even if not in common discovery
                if default_value not in [opt[1] for opt in options]:
                    options.insert(0, (default_value, default_value))

                yield Select(
                    options,
                    value=default_value,
                    id="ssh_key_select",
                    prompt="Choose an SSH key",
                )

                yield Label("OR ENTER CUSTOM PATH", classes="field-label")
                yield Input(
                    value=default_value,
                    placeholder="~/.ssh/your_key",
                    id="ssh_key_custom",
                )

                yield Static("", id="test-status", classes="hint")

            with Horizontal(classes="actions centered-actions"):
                yield Button("Test Access & Continue", variant="success", id="test_and_save")
                yield Button("Back", id="back")
                yield Button("Quit", variant="error", id="quit")

    @on(Select.Changed, "#ssh_key_select")
    def on_key_selected(self, event: Select.Changed) -> None:
        """Update the custom input field when a selection is made."""
        if event.value:
            self.query_one("#ssh_key_custom", Input).value = str(event.value)

    @on(Input.Submitted, "#ssh_key_custom")
    def on_submit(self) -> None:
        """Handle enter key in custom input."""
        self.test_and_save()

    @on(Button.Pressed, "#test_and_save")
    def test_and_save(self) -> None:
        """Verify the selected key and proceed."""
        ssh_key_str = self.query_one("#ssh_key_custom", Input).value.strip()
        if not ssh_key_str:
            self.notify("SSH key path is required", severity="error")
            return

        ssh_key = Path(ssh_key_str).expanduser()
        if not ssh_key.exists():
            self.notify(f"SSH key not found: {ssh_key}", severity="error")
            return

        self.query_one("#test-status", Static).update("Testing Git write access...")
        self.run_worker(self._verify_and_proceed(ssh_key))

    async def _verify_and_proceed(self, ssh_key: Path) -> None:
        """Background worker to verify git access."""
        try:
            # env_with_agent_ssh and verify_git_write_access are blocking
            # We wrap them to keep the UI alive.

            def check() -> None:
                env = env_with_agent_ssh(self.project_context.repo_root, ssh_key_path=ssh_key)
                verify_git_write_access(self.project_context.repo_root, env)

            await asyncio.to_thread(check)

            # Update the context
            self.project_context.ssh_key_path = ssh_key
            # If already configured, we might want to update the stored config too
            if self.project_context.configured:
                self.project_context.save_config(self.project_context.validation_command, ssh_key)

            # Success, move to the next screen
            self._finish_selection()

        except Exception as exc:
            self._handle_test_error(str(exc))

    def _finish_selection(self) -> None:
        """Switch to LoadingScreen after successful verification."""
        self.app.switch_screen(LoadingScreen(self.store, self.project_context))

    def _handle_test_error(self, message: str) -> None:
        """Show verification error."""
        self.query_one("#test-status", Static).update(f"[bold red]Failed: {message}[/]")
        self.notify("Git access verification failed", severity="error")

    @on(Button.Pressed, "#back")
    def back(self) -> None:
        """Return to the warning screen."""
        self.app.switch_screen(WarningScreen(self.store, self.project_context))

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
        self._last_runs_hash: str = ""

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
        for run in self.store.list_runs():
            if run.status in {"running", "stopping"}:
                reconcile_workflow_state(self.store, run.task_id)
        runs = self.store.list_runs()
        runs_hash = str([run.model_dump(mode="json") for run in runs])
        if runs_hash != self._last_runs_hash:
            populate_runs_table(self.query_one("#runs", DataTable), runs)
            self._last_runs_hash = runs_hash

    @on(DataTable.RowSelected, "#runs")
    def on_row_selected(self, event: DataTable.RowSelected) -> None:
        """Open the selected workflow."""
        task_id = str(event.row_key.value)
        if task_id.startswith(("app:", "spacer:")):
            return
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
                yield Static(
                    "This command runs in a fresh clone of the developer branch.",
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

        if not command:
            self.notify("Validation command is required", severity="error")
            return

        self.project_context.save_validation_command(command)
        self.app.switch_screen(HomeScreen(self.store, self.project_context))

    @on(Button.Pressed, "#quit")
    def quit(self) -> None:
        """Exit setup."""
        self.app.exit()


class LaunchScreen(Screen[None]):
    """Workflow launch form."""

    BINDINGS: ClassVar[list[BindingType]] = [("escape", "app.pop_screen", "Back")]

    def __init__(
        self,
        store: RunStore,
        project_context: ProjectContext,
        *,
        source_state: WorkflowState | None = None,
    ) -> None:
        super().__init__()
        self.store = store
        self.project_context = project_context
        self.source_state = source_state

    def on_mount(self) -> None:
        """Set screen title and fetch remote branches on mount."""
        self.app.title = "Resume Workflow" if self.source_state is not None else "New Workflow"
        self.app.sub_title = str(self.project_context.repo_root)
        provider = (
            self.source_state.config.provider
            if self.source_state is not None
            else DEFAULT_PROVIDER
        )
        self._refresh_reasoning_controls(provider)
        if self.project_context.remote_url:
            self.run_worker(self._fetch_branches())

    async def _fetch_branches(self) -> None:
        """Fetch remote branches in the background."""
        try:
            env = env_with_agent_ssh(
                self.project_context.repo_root, ssh_key_path=self.project_context.ssh_key_path
            )
            branches = await asyncio.to_thread(
                list_remote_branches, self.project_context.repo_root, env
            )
            if branches:
                select = self.query_one("#base_branch", Select)
                select.set_options([(b, b) for b in branches])
                if self.project_context.base_branch in branches:
                    select.value = self.project_context.base_branch
        except Exception:
            # Fallback to current branch if fetch fails
            pass

    def compose(self) -> ComposeResult:
        """Compose the launch form."""
        source_config = self.source_state.config if self.source_state is not None else None
        default_provider = source_config.provider if source_config is not None else DEFAULT_PROVIDER
        default_cto_model = (
            source_config.cto_model
            if source_config is not None
            else default_model_for_provider(DEFAULT_PROVIDER)
        )
        default_developer_model = (
            source_config.developer_model
            if source_config is not None
            else default_model_for_provider(DEFAULT_PROVIDER)
        )
        default_cto_reasoning = (
            source_config.cto_reasoning_effort
            if source_config is not None
            else DEFAULT_CODEX_REASONING_EFFORT
        )
        default_developer_reasoning = (
            source_config.developer_reasoning_effort
            if source_config is not None
            else DEFAULT_CODEX_REASONING_EFFORT
        )
        default_base_branch = (
            source_config.base_branch
            if source_config is not None
            else self.project_context.base_branch
        )
        default_validation_command = (
            source_config.validation_command
            if source_config is not None
            else self.project_context.validation_command
        )
        default_loop_limit = str(source_config.loop_limit) if source_config is not None else "3"
        default_request = (
            self.source_state.human_request_md if self.source_state is not None else ""
        )
        with Vertical(classes="page"):
            with Horizontal(id="launch-grid"):
                with Vertical(id="launch-main", classes="panel"):
                    yield Label("GOAL", classes="field-label")
                    yield TextArea(default_request, id="request")
                    yield Static(
                        "Describe what you want the loop to achieve.",
                        classes="hint",
                    )
                with Vertical(id="launch-side", classes="panel"):
                    yield Label("BASE BRANCH", classes="field-label")
                    yield Select(
                        [(default_base_branch, default_base_branch)],
                        value=default_base_branch,
                        id="base_branch",
                        prompt="Select base branch",
                    )
                    yield Label("PROVIDER", classes="field-label")
                    yield Select[ProviderName](
                        [(provider, provider) for provider in PROVIDERS],
                        value=default_provider,
                        allow_blank=False,
                        id="provider",
                        prompt="Select Provider",
                    )
                    yield Label("CTO MODEL", classes="field-label")
                    yield Select[ProviderModel](
                        [(model, model) for model in models_for_provider(default_provider)],
                        value=default_cto_model,
                        allow_blank=False,
                        id="cto_model",
                        prompt="Select CTO model",
                    )
                    yield Label("DEVELOPER MODEL", classes="field-label")
                    yield Select[ProviderModel](
                        [(model, model) for model in models_for_provider(default_provider)],
                        value=default_developer_model,
                        allow_blank=False,
                        id="developer_model",
                        prompt="Select developer model",
                    )
                    yield Label(
                        "CTO REASONING",
                        id="cto_reasoning_label",
                        classes="field-label reasoning-provider",
                    )
                    yield Select[ReasoningEffort](
                        [(effort, effort) for effort in REASONING_EFFORTS],
                        value=default_cto_reasoning,
                        allow_blank=False,
                        id="cto_reasoning_effort",
                        classes="reasoning-provider",
                        prompt="Select CTO reasoning",
                    )
                    yield Label(
                        "DEVELOPER REASONING",
                        id="developer_reasoning_label",
                        classes="field-label reasoning-provider",
                    )
                    yield Select[ReasoningEffort](
                        [(effort, effort) for effort in REASONING_EFFORTS],
                        value=default_developer_reasoning,
                        allow_blank=False,
                        id="developer_reasoning_effort",
                        classes="reasoning-provider",
                        prompt="Select developer reasoning",
                    )
                    yield Label("VALIDATION COMMAND", classes="field-label")
                    yield Input(
                        placeholder=DEFAULT_VALIDATION_COMMAND,
                        value=default_validation_command,
                        id="validation_command",
                    )
                    yield Label("LOOP LIMIT", classes="field-label")
                    yield Input(placeholder="3", value=default_loop_limit, id="loop_limit")

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
        provider = self._selected_provider()
        if provider is None:
            return
        cto_model = self._selected_model(provider, "#cto_model")
        developer_model = self._selected_model(provider, "#developer_model")
        cto_reasoning_effort = self._selected_reasoning_effort("#cto_reasoning_effort")
        developer_reasoning_effort = self._selected_reasoning_effort("#developer_reasoning_effort")
        loop_limit = self._loop_limit()
        if (
            cto_model is None
            or developer_model is None
            or cto_reasoning_effort is None
            or developer_reasoning_effort is None
            or loop_limit is None
        ):
            return
        validation_command = self.query_one("#validation_command", Input).value.strip()
        if not validation_command:
            self.notify("Validation command is required", severity="error")
            return
        repo_url = self.project_context.remote_url
        if not repo_url or not is_ssh_remote_url(repo_url):
            self.notify(
                "Git remote 'origin' must use SSH before launching a workflow.",
                severity="error",
            )
            return

        config = RuntimeConfig(
            provider=provider,
            cto_model=cto_model,
            developer_model=developer_model,
            cto_reasoning_effort=cto_reasoning_effort,
            developer_reasoning_effort=developer_reasoning_effort,
            repo_url=repo_url,
            ssh_key_path=self.project_context.ssh_key_path,
            base_branch=(
                str(self.query_one("#base_branch", Select).value)
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
            continuation=self._continuation_payload(),
        )
        self.app.push_screen(WorkflowScreen(self.store, launch.task_id))

    @on(Select.Changed, "#provider")
    def on_provider_changed(self, event: Select.Changed) -> None:
        """Refresh model choices for the selected provider."""
        if event.value not in PROVIDERS:
            return
        provider = cast(ProviderName, event.value)
        self._refresh_model_select("#cto_model", provider)
        self._refresh_model_select("#developer_model", provider)
        self._refresh_reasoning_controls(provider)

    def _refresh_model_select(self, select_id: str, provider: ProviderName) -> None:
        """Refresh one model selector for the selected provider."""
        model_select = self.query_one(select_id, Select)
        model_select.set_options([(model, model) for model in models_for_provider(provider)])
        model_select.value = default_model_for_provider(provider)

    def _refresh_reasoning_controls(self, provider: ProviderName) -> None:
        """Show reasoning controls only for providers that support them."""
        hidden = provider not in {"codex", "copilot"}
        for widget in self.query(".reasoning-provider"):
            widget.set_class(hidden, "hidden")
        self.query_one("#cto_reasoning_effort", Select).disabled = hidden
        self.query_one("#developer_reasoning_effort", Select).disabled = hidden

    def _selected_provider(self) -> ProviderName | None:
        """Return the selected provider after UI validation."""
        value = self.query_one("#provider", Select).value
        if value not in PROVIDERS:
            self.notify("Select a supported provider", severity="error")
            return None
        return cast(ProviderName, value)

    def _selected_model(self, provider: ProviderName, select_id: str) -> ProviderModel | None:
        """Return the selected model after UI validation."""
        value = self.query_one(select_id, Select).value
        if value not in models_for_provider(provider):
            self.notify(f"Select a supported {provider} model", severity="error")
            return None
        return cast(ProviderModel, value)

    def _selected_reasoning_effort(self, select_id: str) -> ReasoningEffort | None:
        """Return the selected reasoning effort after UI validation."""
        value = self.query_one(select_id, Select).value
        if value not in REASONING_EFFORTS:
            self.notify("Select a supported reasoning effort", severity="error")
            return None
        return cast(ReasoningEffort, value)

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

    def _continuation_payload(self) -> WorkflowContinuation | None:
        """Build the optional continuation payload for resumed workflows."""
        if self.source_state is None:
            return None
        return WorkflowContinuation(
            source_task_id=self.source_state.task_id,
            developer_branch=self.source_state.developer_branch,
            context=self.store.build_continuation_context(self.source_state),
        )


class UserPromptScreen(Screen[None]):
    """Collect one additional user prompt for a running workflow."""

    BINDINGS: ClassVar[list[BindingType]] = [("escape", "app.pop_screen", "Back")]

    def __init__(self, store: RunStore, task_id: str) -> None:
        super().__init__()
        self.store = store
        self.task_id = task_id

    def compose(self) -> ComposeResult:
        """Compose the add-prompt form."""
        with Vertical(classes="page"):
            with Vertical(classes="panel"):
                yield Label("USER PROMPT", classes="table-title")
                yield TextArea("", id="user-prompt-input")
                yield Static(
                    "This message will be queued for the next CTO pass.",
                    classes="hint",
                )
            with Horizontal(classes="actions"):
                yield Button("Queue Prompt", variant="success", id="queue-user-prompt")
                yield Button("Back", id="back")
        yield Footer()

    def on_mount(self) -> None:
        """Focus the input when the screen opens."""
        self.query_one("#user-prompt-input", TextArea).focus()

    @on(Button.Pressed, "#queue-user-prompt")
    def queue_prompt(self) -> None:
        """Persist a prompt for the next CTO pass."""
        content = self.query_one("#user-prompt-input", TextArea).text.strip()
        if not content:
            self.notify("Prompt is required", severity="error")
            return
        state = self.store.load_state(self.task_id)
        if state.status not in {"running", "stopping"}:
            self.notify(f"Workflow is already {state.status}", severity="warning")
            return
        self.store.append_user_prompt(state, content)
        self.app.pop_screen()

    @on(Button.Pressed, "#back")
    def back(self) -> None:
        """Return to the previous screen."""
        self.app.pop_screen()


class WorkflowScreen(Screen[None]):
    """Unified live workflow and historical activity reader."""

    BINDINGS: ClassVar[list[BindingType]] = [
        ("escape", "app.pop_screen", "Back"),
        ("r", "refresh", "Refresh"),
        ("p", "toggle_refresh", "Pause live"),
        ("b", "copy_branch", "Copy branch"),
        ("c", "copy_current_node", "Copy node"),
        ("e", "copy_events", "Copy activity"),
        ("a", "add_user_prompt", "Add prompt"),
        ("u", "resume_workflow", "Resume"),
        ("s", "stop_workflow", "Stop"),
    ]

    def __init__(self, store: RunStore, task_id: str) -> None:
        super().__init__()
        self.store = store
        self.task_id = task_id
        self._last_nodes_hash = 0
        self._last_events_hash = ""
        self._last_report_content = ""
        self._last_status_content = ""
        self._report_mode = ""
        self._refresh_paused = False
        self._refresh_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        """Compose the workflow screen."""
        with Vertical(classes="page"):
            with Horizontal(id="workflow-status-bar"):
                yield Static("", id="workflow-status")
                yield Button("Pause", id="pause-refresh")
                yield Button("Add Prompt", id="add-user-prompt")
                yield Button("Resume", id="resume-workflow")
                yield Button("Copy Node", id="copy-node")
                yield Button("Copy Activity", id="copy-events")
                yield Button("Stop", variant="error", id="stop-workflow")
            with Horizontal(id="workflow-meta-bar"):
                yield Static("", id="workflow-branch")
                yield Button("Copy", id="copy-branch")
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
        self._refresh_timer = self.set_interval(1.5, self.action_refresh)
        self.action_refresh()

    def action_refresh(self) -> None:
        """Refresh events and nodes from the store."""
        try:
            state = reconcile_workflow_state(self.store, self.task_id)
            self._update_workflow_status(state)
            self._update_branch_bar(state)
            nodes = state.node_runs
            nodes_hash = hash(str(nodes))

            # Update nodes table if count OR status changed
            if nodes_hash != self._last_nodes_hash:
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
                self._last_nodes_hash = nodes_hash

                # Reselect or select last
                if current_key:
                    try:
                        table.move_cursor(row=table.get_row_index(current_key))
                    except Exception:
                        table.move_cursor(row=len(nodes) - 1)
                elif nodes:
                    last_node = nodes[-1]
                    key = f"{last_node.role}:{last_node.iteration}"
                    table.move_cursor(row=table.get_row_index(key))

            # Always refresh the current report content to show live progress
            self._update_report(state)

            self._update_events()
        except Exception:
            pass

    @on(Button.Pressed, "#pause-refresh")
    def on_pause_pressed(self) -> None:
        """Pause or resume live refresh."""
        self.action_toggle_refresh()

    @on(Button.Pressed, "#copy-node")
    def on_copy_node_pressed(self) -> None:
        """Copy the selected node output."""
        self.action_copy_current_node()

    @on(Button.Pressed, "#copy-events")
    def on_copy_events_pressed(self) -> None:
        """Copy workflow activity."""
        self.action_copy_events()

    @on(Button.Pressed, "#copy-branch")
    def on_copy_branch_pressed(self) -> None:
        """Copy the developer branch name."""
        self.action_copy_branch()

    @on(Button.Pressed, "#add-user-prompt")
    def on_add_user_prompt_pressed(self) -> None:
        """Open the prompt queue screen."""
        self.action_add_user_prompt()

    @on(Button.Pressed, "#resume-workflow")
    def on_resume_pressed(self) -> None:
        """Open the resume form for finished workflows."""
        self.action_resume_workflow()

    def action_toggle_refresh(self) -> None:
        """Pause or resume live refresh to allow terminal text selection."""
        self._refresh_paused = not self._refresh_paused
        if self._refresh_timer is not None:
            if self._refresh_paused:
                self._refresh_timer.pause()
            else:
                self._refresh_timer.resume()
        self._set_loading_animations_paused(self._refresh_paused)
        self._update_pause_button()
        self.app.sub_title = (
            "Live refresh paused" if self._refresh_paused else "Viewing activity..."
        )
        if not self._refresh_paused:
            self.action_refresh()

    @on(Button.Pressed, "#stop-workflow")
    def on_stop_pressed(self) -> None:
        """Request a running workflow stop."""
        self.action_stop_workflow()

    def action_stop_workflow(self) -> None:
        """Request a workflow stop without blocking the TUI."""
        try:
            state = self.store.load_state(self.task_id)
        except Exception:
            self.notify("Unable to read workflow state", severity="error")
            return
        if state.status not in {"running", "stopping"}:
            self.notify(f"Workflow is already {state.status}", severity="warning")
            return
        self.run_worker(self._request_stop())

    async def _request_stop(self) -> None:
        """Run the stop command off the UI thread."""
        await asyncio.to_thread(request_workflow_stop, self.store, self.task_id)
        self.notify("Stop requested", severity="warning")
        self.action_refresh()

    def action_copy_current_node(self) -> None:
        """Copy the currently selected node report or live logs."""
        try:
            state = self.store.load_state(self.task_id)
            node = self._selected_node(state)
            content = self._copyable_node_text(state, node)
        except Exception:
            self.notify("Unable to copy node content", severity="error")
            return
        self._copy_text(content, "Node content copied")

    def action_copy_events(self) -> None:
        """Copy the workflow activity log."""
        try:
            content = workflow_events_plain_text(self.store.read_events(self.task_id))
        except Exception:
            self.notify("Unable to copy activity", severity="error")
            return
        if not content:
            content = "No workflow activity."
        self._copy_text(content, "Workflow activity copied")

    def action_copy_branch(self) -> None:
        """Copy the current developer branch name."""
        try:
            state = self.store.load_state(self.task_id)
        except Exception:
            self.notify("Unable to read workflow state", severity="error")
            return
        branch = state.developer_branch.strip()
        if not branch:
            self.notify("No developer branch yet", severity="warning")
            return
        self._copy_text(branch, "Developer branch copied")

    def action_add_user_prompt(self) -> None:
        """Open a form to queue an extra user prompt."""
        try:
            state = self.store.load_state(self.task_id)
        except Exception:
            self.notify("Unable to read workflow state", severity="error")
            return
        if state.status not in {"running", "stopping"}:
            self.notify("Add prompts only while the workflow is active", severity="warning")
            return
        self.app.push_screen(UserPromptScreen(self.store, self.task_id))

    def action_resume_workflow(self) -> None:
        """Open a prefilled launch form to continue a finished workflow."""
        try:
            state = self.store.load_state(self.task_id)
        except Exception:
            self.notify("Unable to read workflow state", severity="error")
            return
        if state.status in {"running", "stopping"}:
            self.notify("Stop the active workflow before resuming it", severity="warning")
            return
        app = cast("WorkflowApp", self.app)
        self.app.push_screen(LaunchScreen(self.store, app.project_context, source_state=state))

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
        report_panel = self.query_one("#workflow-report-panel", Vertical)
        node = self._selected_node(state)

        if node is None:
            self._show_live_output(report_panel, state, None)
            return

        content = node_report_markdown(node)
        if content is None and node.status == "running":
            self._show_live_output(report_panel, state, node)
            return
        if content is None:
            content = self._node_log_markdown(node)
        self._show_markdown(report_panel, content)

    def _update_workflow_status(self, state: WorkflowState) -> None:
        """Render compact workflow status and lifecycle hints."""
        status = status_text(state.status)
        text = Text.assemble(
            ("WORKFLOW ", "bold"),
            status,
            ("  ", "dim"),
            (f"loop {state.loop_count}/{state.config.loop_limit}", "dim"),
            ("  ", "dim"),
            (state.config.provider, "#f0a35a"),
            ("  ", "dim"),
            (
                "paused" if self._refresh_paused else "live",
                "#d7b66f" if self._refresh_paused else "#7fbf9a",
            ),
            ("  ", "dim"),
            (f"queued prompts {len(self.store.pending_user_prompts(state))}", "#88a7c7"),
            ("  ", "dim"),
            ("resumed" if state.continued_from_task_id else "fresh", "#d7b66f"),
            ("  P pause/resume  A add prompt  U resume  C copy node  E copy activity", "dim"),
        )
        if state.failure_message:
            text.append(f"  {state.failure_message}", style="bold #e07868")
        status_content = text.plain + str(state.failure_message)
        if status_content != self._last_status_content:
            self.query_one("#workflow-status", Static).update(text)
            self._last_status_content = status_content
        stop = self.query_one("#stop-workflow", Button)
        stop.disabled = state.status not in {"running", "stopping"}
        self.query_one("#add-user-prompt", Button).disabled = state.status not in {
            "running",
            "stopping",
        }
        self.query_one("#resume-workflow", Button).disabled = state.status in {
            "running",
            "stopping",
        }
        self._update_pause_button()

    def _update_branch_bar(self, state: WorkflowState) -> None:
        """Render the compact developer branch row."""
        branch = state.developer_branch or "_not assigned yet_"
        text = Text.assemble(
            ("BRANCH ", "bold"),
            (branch, "#88a7c7"),
        )
        text.no_wrap = True
        text.overflow = "ellipsis"
        self.query_one("#workflow-branch", Static).update(text)
        self.query_one("#copy-branch", Button).disabled = not state.developer_branch

    def _copy_text(self, content: str, notice: str) -> None:
        """Copy text to the clipboard and notify the user."""
        self.app.copy_to_clipboard(content)
        self.notify(notice)

    def _selected_node(self, state: WorkflowState) -> NodeRun | None:
        """Return the selected node, falling back to the latest node."""
        if not state.node_runs:
            return None
        table = self.query_one("#nodes", DataTable)
        try:
            key = str(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value)
            if key.startswith("spacer:"):
                return state.node_runs[-1]
            if key.startswith("iteration:"):
                iteration = int(key.split(":", 1)[1])
                return _latest_node_in_iteration(state.node_runs, iteration)
            role, iter_str = key.split(":")
            iteration = int(iter_str)
            return next(
                node
                for node in state.node_runs
                if node.role == role and node.iteration == iteration
            )
        except Exception:
            return state.node_runs[-1]

    def _show_live_output(
        self,
        report_panel: Vertical,
        state: WorkflowState,
        node: NodeRun | None,
    ) -> None:
        """Show the animated working state plus a live log tail."""
        if self._report_mode != "live" or not report_panel.query("#node-live-log"):
            for widget in report_panel.children:
                widget.remove()
            report_panel.mount(LoadingLogo(classes="node-loading-logo"))
            report_panel.mount(RichLog(id="node-live-log", highlight=True, markup=False))
            self._report_mode = "live"
            self._last_report_content = ""
            self._set_loading_animations_paused(self._refresh_paused)
        content = self._live_output_text(state, node)
        if content == self._last_report_content:
            return
        log = self.query_one("#node-live-log", RichLog)
        log.clear()
        log.write(content)
        self._last_report_content = content

    def _live_output_text(self, state: WorkflowState, node: NodeRun | None) -> str:
        """Return live text for the current node or worker startup."""
        if node is not None:
            output = self.store.read_node_log_tail(node, lines=120)
            return output or "Waiting for node output..."
        if state.worker_log_path is not None:
            output = read_text_tail(state.worker_log_path, lines=120)
            if output:
                return output
        return "Waiting for the first node to start..."

    def _node_log_markdown(self, node: NodeRun) -> str:
        """Render logs when a node ended without a Markdown report."""
        output = self.store.read_node_log_tail(node, lines=120) or "No node output was written."
        return f"# {node.role.upper()} {node.iteration:02d}\n\n```text\n{output}\n```"

    def _show_markdown(self, report_panel: Vertical, content: str) -> None:
        """Show the final node report Markdown."""
        if self._report_mode != "markdown" or not report_panel.query(Markdown):
            for widget in report_panel.children:
                widget.remove()
            report_panel.mount(Markdown(id="report"))
            self._report_mode = "markdown"
            self._last_report_content = ""
        if content == self._last_report_content:
            return
        self.query_one("#report", Markdown).update(content)
        self._last_report_content = content

    def _update_events(self) -> None:
        """Refresh the activity log only when event content changed."""
        events = self.store.read_events(self.task_id)
        events_hash = "\n".join(event.model_dump_json() for event in events[-80:])
        if events_hash == self._last_events_hash:
            return
        populate_events(self.query_one("#events", RichLog), events)
        self._last_events_hash = events_hash

    def _copyable_node_text(self, state: WorkflowState, node: NodeRun | None) -> str:
        """Return the selected node panel as copyable plain text."""
        if node is None:
            if state.worker_log_path is not None:
                return read_text_tail(state.worker_log_path, lines=200) or "No worker output yet."
            return "No node selected."
        if node.report_path.exists():
            return node.report_path.read_text(encoding="utf-8")
        output = self.store.read_node_log_tail(node, lines=200)
        return output or "No node output yet."

    def _set_loading_animations_paused(self, paused: bool) -> None:
        """Pause or resume loading animations mounted in this screen."""
        for logo in self.query(LoadingLogo):
            if paused:
                logo.pause_animation()
            else:
                logo.resume_animation()

    def _update_pause_button(self) -> None:
        """Keep the pause button label in sync."""
        self.query_one("#pause-refresh", Button).label = (
            "Resume" if self._refresh_paused else "Pause"
        )


def _latest_node_in_iteration(nodes: list[NodeRun], iteration: int) -> NodeRun | None:
    """Return the latest node recorded for one iteration."""
    matches = [node for node in nodes if node.iteration == iteration]
    if not matches:
        return None
    return matches[-1]

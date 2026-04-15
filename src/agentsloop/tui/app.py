"""Textual app entrypoint for agentic workflows."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from textual.app import App
from textual.binding import BindingType
from textual.theme import Theme

from agentsloop.paths import runs_root
from agentsloop.project_config import ProjectContext
from agentsloop.runtime.git_runtime import discover_ssh_key_path
from agentsloop.storage.json_store import RunStore
from agentsloop.tui.screens import LoadingScreen
from agentsloop.tui.theme import APP_CSS

# Soft themes definitions
SOFT_DARK = Theme(
    name="soft-dark",
    primary="#f0a35a",
    secondary="#88a7c7",
    accent="#7fbf9a",
    background="#1e1e1e",
    surface="#262626",
    panel="#323232",
    foreground="#eee7dd",
)

SOFT_LIGHT = Theme(
    name="soft-light",
    primary="#d37a1f",
    secondary="#4a76a8",
    accent="#4e8c6b",
    background="#dcdcdc",  # Distinct light gray
    surface="#e8e8e8",
    panel="#cfcfcf",
    foreground="#1a1a1a",
)


class WorkflowApp(App[None]):
    """Textual shell for agentic workflows."""

    CSS = APP_CSS
    TITLE = "AgentsLoop"
    SUB_TITLE = "Local Repository Orchestrator"

    # Register custom themes
    BINDINGS: ClassVar[list[BindingType]] = [
        ("t", "toggle_theme", "Toggle Light/Dark"),
    ]

    def __init__(
        self, runs_dir: Path | None = None, project_context: ProjectContext | None = None
    ) -> None:
        super().__init__()
        self.store = RunStore(runs_dir or runs_root())
        if project_context is None:
            default_key = discover_ssh_key_path()
            if not default_key:
                # This should normally be handled by cli.py,
                # but we need a valid Path to instantiate ProjectContext
                default_key = Path("~/.ssh/id_rsa").expanduser()

            project_context = ProjectContext(
                repo_root=Path.cwd(),
                base_branch="main",
                ssh_key_path=default_key,
            )
        self.project_context = project_context

    def on_mount(self) -> None:
        """Register themes and open the initial screen."""
        self.register_theme(SOFT_DARK)
        self.register_theme(SOFT_LIGHT)
        self.theme = "soft-dark"

        # Start with the loading/verification screen
        self.push_screen(LoadingScreen(self.store, self.project_context))

    def action_toggle_theme(self) -> None:
        """Switch between soft-dark and soft-light themes."""
        self.theme = "soft-light" if self.theme == "soft-dark" else "soft-dark"


__all__ = ["WorkflowApp"]

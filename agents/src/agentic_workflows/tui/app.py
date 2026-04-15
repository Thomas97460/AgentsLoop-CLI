"""Textual app entrypoint for agentic workflows."""

from __future__ import annotations

from pathlib import Path

from textual.app import App

from agentic_workflows.paths import runs_root
from agentic_workflows.storage.json_store import RunStore
from agentic_workflows.tui.screens import DEFAULT_REPO_URL, HomeScreen
from agentic_workflows.tui.theme import APP_CSS


class WorkflowApp(App[None]):
    """Textual shell for agentic workflows."""

    CSS = APP_CSS
    TITLE = "Agentic Workflows"
    SUB_TITLE = "Gemini CTO / Developer / CI"

    def __init__(self, runs_dir: Path | None = None) -> None:
        super().__init__()
        self.store = RunStore(runs_dir or runs_root())

    def on_mount(self) -> None:
        """Open the home screen."""
        self.push_screen(HomeScreen(self.store))


__all__ = ["DEFAULT_REPO_URL", "WorkflowApp"]

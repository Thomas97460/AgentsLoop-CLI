"""Command line entrypoint for the Textual workflow TUI."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from agentic_workflows.tui.app import WorkflowApp

cli = typer.Typer(
    add_completion=False,
    help="Open the agentic workflow TUI.",
    invoke_without_command=True,
    no_args_is_help=False,
)


@cli.callback(invoke_without_command=True)
def launch(
    ctx: typer.Context,
    runs_root: Annotated[
        Path | None,
        typer.Option("--runs-root", help="Override the workflow runs directory."),
    ] = None,
) -> None:
    """Open the Textual application."""
    if ctx.invoked_subcommand is None:
        WorkflowApp(runs_root).run()


def main() -> None:
    """Run the CLI application."""
    cli()


if __name__ == "__main__":
    main()

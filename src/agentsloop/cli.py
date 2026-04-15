"""Command line entrypoint for the AgentsLoop TUI."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Annotated

import typer

from agentsloop.domain.models import DEFAULT_VALIDATION_COMMAND
from agentsloop.project_config import ProjectConfigStore, ProjectContext
from agentsloop.tui.app import WorkflowApp

cli = typer.Typer(
    add_completion=False,
    help="Open the AgentsLoop workflow TUI.",
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
        project_context = build_project_context(Path.cwd())
        if project_context is None:
            typer.secho(
                "AgentsLoop must be launched from inside a Git repository.",
                err=True,
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)
        WorkflowApp(runs_root, project_context).run()


def build_project_context(cwd: Path) -> ProjectContext | None:
    """Build the current repository context or return None outside Git."""
    repo_root = find_git_root(cwd)
    if repo_root is None:
        return None
    branch = current_git_branch(repo_root)
    if branch is None:
        return None
    store = ProjectConfigStore(repo_root)
    config = store.load()
    return ProjectContext(
        repo_root=repo_root,
        base_branch=branch,
        validation_command=config.validation_command
        if config is not None
        else DEFAULT_VALIDATION_COMMAND,
        config_store=store,
        configured=config is not None,
    )


def find_git_root(cwd: Path) -> Path | None:
    """Return the enclosing Git repository root."""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip()).resolve()


def current_git_branch(repo_root: Path) -> str | None:
    """Return the current branch name for a Git repository."""
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    branch = result.stdout.strip()
    return branch or None


def main() -> None:
    """Run the CLI application."""
    cli()


if __name__ == "__main__":
    main()

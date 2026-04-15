"""Command line entrypoint for the AgentsLoop TUI."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Annotated

import typer

from agentsloop.domain.models import DEFAULT_VALIDATION_COMMAND
from agentsloop.project_config import ProjectConfigStore, ProjectContext
from agentsloop.runtime.git_runtime import discover_ssh_key_path
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
    ssh_key: Annotated[
        Path | None,
        typer.Option(
            "--ssh-key",
            help="Path to the Git SSH key. Defaults to ~/.ssh/id_*.",
            envvar="AGENTS_GIT_SSH_KEY_PATH",
        ),
    ] = None,
) -> None:
    """Open the Textual application."""
    if ctx.invoked_subcommand is None:
        try:
            project_context = build_project_context(Path.cwd(), ssh_key)
        except OSError as e:
            typer.secho(str(e), err=True, fg=typer.colors.RED)
            raise typer.Exit(1) from None

        if project_context is None:
            typer.secho(
                "AgentsLoop must be launched from inside a Git repository.",
                err=True,
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)
        WorkflowApp(runs_root, project_context).run()


def build_project_context(cwd: Path, ssh_key: Path | None = None) -> ProjectContext | None:
    """Build the current repository context or return None outside Git."""
    repo_root = find_git_root(cwd)
    if repo_root is None:
        return None

    store = ProjectConfigStore(repo_root)
    config = store.load()

    # Resolve SSH key: CLI > Env > Stored Config > Discovery
    # Note: Typer already handled CLI and Env if provided to `launch`
    resolved_ssh_key = ssh_key
    if not resolved_ssh_key and config:
        resolved_ssh_key = config.ssh_key_path

    if not resolved_ssh_key:
        resolved_ssh_key = discover_ssh_key_path()

    if not resolved_ssh_key:
        raise OSError(
            "Git SSH key path is mandatory. Please use --ssh-key, "
            "set AGENTS_GIT_SSH_KEY_PATH, or ensure a default key exists in ~/.ssh/id_*"
        )

    branch = current_git_branch(repo_root)
    if branch is None:
        return None
    remote_url = get_git_remote_url(repo_root)
    return ProjectContext(
        repo_root=repo_root,
        base_branch=branch,
        ssh_key_path=resolved_ssh_key,
        remote_url=remote_url,
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


def get_git_remote_url(repo_root: Path) -> str | None:
    """Return the origin remote URL if it exists."""
    result = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def main() -> None:
    """Run the CLI application."""
    cli()


if __name__ == "__main__":
    main()

"""Filesystem locations used by the workflow CLI."""

from __future__ import annotations

from pathlib import Path


def package_root() -> Path:
    """Return the installed Python package directory."""
    return Path(__file__).resolve().parent


def repo_root() -> Path:
    """Return the directory where the CLI was invoked."""
    return Path.cwd()


def runs_root() -> Path:
    """Return the directory where workflow runs are persisted."""
    return Path("~/agentsloop-runs").expanduser()


def prompts_root() -> Path:
    """Return the bundled prompt templates directory."""
    return package_root() / "prompts"

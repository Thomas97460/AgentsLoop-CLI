"""Repository-relative paths used by the workflow CLI."""

from __future__ import annotations

from pathlib import Path


def agents_root() -> Path:
    """Return the repository ``agents`` directory."""
    return Path(__file__).resolve().parents[2]


def repo_root() -> Path:
    """Return the repository root containing the ``agents`` directory."""
    return agents_root().parent


def runs_root() -> Path:
    """Return the directory where workflow runs are persisted."""
    return Path("~/algosia-agent-workflows").expanduser()


def prompts_root() -> Path:
    """Return the prompt templates directory."""
    return agents_root() / "prompts"

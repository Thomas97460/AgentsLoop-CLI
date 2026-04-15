"""Provider-specific command builders and execution."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from agentsloop.domain.models import GeminiModel, ProviderName


@dataclass(frozen=True, slots=True)
class ProviderCommand:
    """Concrete provider command plus execution input."""

    args: list[str]
    stdin: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderExecution:
    """Completed provider execution metadata."""

    returncode: int


def build_provider_command(
    provider: ProviderName,
    model: GeminiModel,
    prompt_md: str,
) -> ProviderCommand:
    """Build the full-access command for one supported provider."""
    if provider == "gemini":
        return ProviderCommand(
            ["gemini", "--model", model, "--yolo", "--output-format", "text", "--prompt", prompt_md]
        )


def run_provider(
    *,
    provider: ProviderName,
    model: GeminiModel,
    prompt_md: str,
    cwd: Path,
    env: dict[str, str],
    stdout_path: Path,
    stderr_path: Path,
) -> ProviderExecution:
    """Execute one provider command and stream output directly to artifacts."""
    command = build_provider_command(provider, model, prompt_md)
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    with (
        stdout_path.open("w", encoding="utf-8") as stdout,
        stderr_path.open("w", encoding="utf-8") as stderr,
    ):
        process = subprocess.Popen(
            command.args,
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE if command.stdin is not None else None,
            stdout=stdout,
            stderr=stderr,
            text=True,
        )
        process.communicate(command.stdin)
    return ProviderExecution(returncode=process.returncode)

"""Provider-specific command builders and execution."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from agentsloop.domain.models import (
    DEFAULT_CODEX_REASONING_EFFORT,
    ProviderModel,
    ProviderName,
    ReasoningEffort,
)


@dataclass(frozen=True, slots=True)
class ProviderCommand:
    """Concrete provider command plus execution input."""

    args: list[str]
    stdin: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderExecution:
    """Completed provider execution metadata."""

    returncode: int
    report_md: str | None = None


def build_provider_command(
    provider: ProviderName,
    model: ProviderModel,
    prompt_md: str,
    *,
    reasoning_effort: ReasoningEffort | None = None,
    output_path: Path | None = None,
) -> ProviderCommand:
    """Build the full-access command for one supported provider."""
    if provider == "gemini":
        return ProviderCommand(
            [
                "gemini",
                "--model",
                model,
                "--approval-mode=yolo",
                "--output-format",
                "text",
                "--prompt",
                prompt_md,
            ]
        )
    if provider == "codex":
        if output_path is None:
            raise ValueError("Codex provider requires an output_path for the last message")
        effort = reasoning_effort or DEFAULT_CODEX_REASONING_EFFORT
        return ProviderCommand(
            [
                "codex",
                "exec",
                "--dangerously-bypass-approvals-and-sandbox",
                "--model",
                model,
                "-c",
                f'model_reasoning_effort="{effort}"',
                "--color",
                "never",
                "--output-last-message",
                str(output_path),
                "-",
            ],
            stdin=prompt_md,
        )
    if provider == "copilot":
        effort = reasoning_effort or DEFAULT_CODEX_REASONING_EFFORT
        args = [
            "copilot",
            "--allow-all-tools",
            "--no-ask-user",
            "--no-color",
            "-s",
            "-p",
            prompt_md,
        ]
        if model != "auto":
            args[1:1] = ["--model", model]
            args[3:3] = ["--reasoning-effort", effort]
        return ProviderCommand(args)
    raise ValueError(f"Unsupported provider: {provider}")


def run_provider(
    *,
    provider: ProviderName,
    model: ProviderModel,
    reasoning_effort: ReasoningEffort | None = None,
    prompt_md: str,
    cwd: Path,
    env: dict[str, str],
    stdout_path: Path,
    stderr_path: Path,
) -> ProviderExecution:
    """Execute one provider command and stream output directly to artifacts."""
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    last_message_path = stdout_path.parent / "last-message.md"
    command = build_provider_command(
        provider,
        model,
        prompt_md,
        reasoning_effort=reasoning_effort,
        output_path=last_message_path if provider == "codex" else None,
    )
    if provider == "codex" and last_message_path.exists():
        last_message_path.unlink()
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
    report_md = None
    if provider == "codex" and last_message_path.exists():
        report_md = last_message_path.read_text(encoding="utf-8").strip() or None
    return ProviderExecution(returncode=process.returncode, report_md=report_md)

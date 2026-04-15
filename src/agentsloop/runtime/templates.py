"""Prompt rendering and Markdown parsing helpers."""

from __future__ import annotations

import re
from pathlib import Path


def render_template(template_path: Path, values: dict[str, object]) -> str:
    """Render a simple ``{{key}}`` Markdown template."""
    rendered = template_path.read_text(encoding="utf-8")
    for key, value in values.items():
        rendered = rendered.replace("{{" + key + "}}", str(value))
    return rendered


def slugify(value: str) -> str:
    """Return a short branch-safe slug."""
    text = value.lower()
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    if not text:
        return "task"
    parts = [part for part in text.split("-") if part]
    return "-".join(parts[:4])[:48].strip("-") or "task"


def extract_section(text: str, header: str) -> str:
    """Extract one top-level Markdown section by title."""
    pattern = rf"(?ms)^# {re.escape(header)}\s*(.*?)\s*(?=^# |\Z)"
    match = re.search(pattern, text)
    return match.group(1).strip() if match else ""


def parse_approval_status(report_md: str) -> str:
    """Extract a CTO decision, defaulting to ``continue``."""
    match = re.search(r"(?im)^approval_status:\s*(done|continue)\s*$", report_md)
    return match.group(1).lower() if match else "continue"


def parse_developer_branch(report_md: str) -> str | None:
    """Extract a developer branch name, if provided."""
    match = re.search(r"(?im)^developer_branch:\s*([a-z0-9/-]+)\s*$", report_md)
    return match.group(1) if match else None

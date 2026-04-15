"""Typed workflow state and artifact models."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

JsonValue = dict[str, Any] | list[Any] | str | int | float | bool | None
ProviderName = Literal["gemini"]
WorkflowStatus = Literal["running", "success", "error", "stopped"]
NodeRole = Literal["cto", "developer", "validation"]
NodeStatus = Literal["running", "success", "error"]
GeminiModel = Literal[
    "gemini-3.1-pro-preview",
    "gemini-3-flash-preview",
    "gemini-3.1-flash-lite-preview",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
]

DEFAULT_GEMINI_MODEL: GeminiModel = "gemini-3-flash-preview"
DEFAULT_VALIDATION_COMMAND = 'echo "everything is fine here"'
GEMINI_MODELS: tuple[GeminiModel, ...] = (
    "gemini-3.1-pro-preview",
    DEFAULT_GEMINI_MODEL,
    "gemini-3.1-flash-lite-preview",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
)


def utc_now() -> str:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(UTC).isoformat()


class RuntimeConfig(BaseModel):
    """User-selected runtime settings."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    provider: ProviderName = "gemini"
    model: GeminiModel = DEFAULT_GEMINI_MODEL
    repo_url: str
    ssh_key_path: Path | None = None
    base_branch: str = "main"
    loop_limit: int = Field(default=3, ge=1)
    validation_command: str = Field(default=DEFAULT_VALIDATION_COMMAND, min_length=1)


class WorkflowEvent(BaseModel):
    """One append-only workflow event."""

    ts: str = Field(default_factory=utc_now)
    event: str
    fields: dict[str, JsonValue] = Field(default_factory=dict)


class ProviderResult(BaseModel):
    """Normalized result from one provider execution."""

    provider: ProviderName
    role: str
    model: GeminiModel
    status: Literal["success", "error"]
    report_md: str
    stdout_path: str
    stderr_path: str
    exit_code: int | None
    started_at: str
    finished_at: str
    repo_path: str
    branch: str


class NodeRun(BaseModel):
    """Durable metadata for one workflow node execution."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    role: NodeRole
    iteration: int
    status: NodeStatus
    started_at: str
    finished_at: str | None = None
    model: GeminiModel | None = None
    prompt_path: Path | None = None
    report_path: Path
    result_path: Path
    stdout_path: Path
    stderr_path: Path
    repo_path: Path
    exit_code: int | None = None

    @property
    def key(self) -> str:
        """Return a stable display key for this node run."""
        return f"{self.role}:{self.iteration:02d}"


class WorkflowState(BaseModel):
    """Durable state for one CTO/developer loop run."""

    task_id: str
    human_request_md: str
    config: RuntimeConfig
    run_dir: Path
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
    status: WorkflowStatus = "running"
    approval_status: Literal["continue", "done"] = "continue"
    loop_count: int = 0
    stopped_by_limit: bool = False
    developer_branch: str = ""
    node_runs: list[NodeRun] = Field(default_factory=list)
    reports: dict[str, str] = Field(
        default_factory=lambda: {
            "cto": "",
            "developer": "",
            "human_response": "",
            "technical_summary": "",
        }
    )
    cto_result: dict[str, JsonValue] = Field(default_factory=dict)
    developer_result: dict[str, JsonValue] = Field(default_factory=dict)
    validation: dict[str, JsonValue] = Field(default_factory=dict)

    @property
    def task_id_short(self) -> str:
        """Return the branch-safe short task identifier."""
        return self.task_id[:8]

    def touch(self) -> None:
        """Refresh the state update timestamp."""
        self.updated_at = utc_now()

    def snapshot(self) -> dict[str, JsonValue]:
        """Return a JSON-compatible state snapshot."""
        return self.model_dump(mode="json")


class RunSummary(BaseModel):
    """Compact metadata used by history and TUI lists."""

    task_id: str
    status: WorkflowStatus
    approval_status: str
    created_at: str
    updated_at: str
    loop_count: int
    developer_branch: str
    request_preview: str
    run_dir: str

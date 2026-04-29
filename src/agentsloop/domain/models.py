"""Typed workflow state and artifact models."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

JsonValue = dict[str, Any] | list[Any] | str | int | float | bool | None
ProviderName = Literal["gemini", "codex", "copilot"]
WorkflowStatus = Literal["running", "stopping", "success", "error", "stopped"]
NodeRole = Literal["cto", "developer", "validation"]
NodeStatus = Literal["running", "success", "error", "stopped"]
ReasoningEffort = Literal["low", "medium", "high", "xhigh"]
GeminiModel = Literal[
    "gemini-3.1-pro-preview",
    "gemini-3-flash-preview",
    "gemini-3.1-flash-lite-preview",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
]
CodexModel = Literal[
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.3-codex",
    "gpt-5.2",
]
CopilotModel = Literal[
    "auto",
    "gpt-5.3-codex",
    "gpt-5.2-codex",
    "gpt-5.2",
    "gpt-5.4-mini",
    "gpt-5-mini",
    "gpt-4.1",
    "claude-haiku-4.5",
]
ProviderModel = str

DEFAULT_PROVIDER: ProviderName = "gemini"
DEFAULT_GEMINI_MODEL: GeminiModel = "gemini-3-flash-preview"
DEFAULT_CODEX_MODEL: CodexModel = "gpt-5.4"
DEFAULT_COPILOT_MODEL: CopilotModel = "gpt-5.3-codex"
DEFAULT_CODEX_REASONING_EFFORT: ReasoningEffort = "medium"
DEFAULT_VALIDATION_COMMAND = 'echo "everything is fine here"'
PROVIDERS: tuple[ProviderName, ...] = ("gemini", "codex", "copilot")
REASONING_EFFORTS: tuple[ReasoningEffort, ...] = ("low", "medium", "high", "xhigh")
GEMINI_MODELS: tuple[GeminiModel, ...] = (
    "gemini-3.1-pro-preview",
    DEFAULT_GEMINI_MODEL,
    "gemini-3.1-flash-lite-preview",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
)
CODEX_MODELS: tuple[CodexModel, ...] = (
    DEFAULT_CODEX_MODEL,
    "gpt-5.4-mini",
    "gpt-5.3-codex",
    "gpt-5.2",
)
COPILOT_MODELS: tuple[CopilotModel, ...] = (
    "auto",
    DEFAULT_COPILOT_MODEL,
    "gpt-5.2-codex",
    "gpt-5.2",
    "gpt-5.4-mini",
    "gpt-5-mini",
    "gpt-4.1",
    "claude-haiku-4.5",
)


def models_for_provider(provider: ProviderName) -> tuple[ProviderModel, ...]:
    """Return the curated model list for one provider."""
    if provider == "gemini":
        return GEMINI_MODELS
    if provider == "copilot":
        return COPILOT_MODELS
    return CODEX_MODELS


def default_model_for_provider(provider: ProviderName) -> ProviderModel:
    """Return the default model for one provider."""
    if provider == "gemini":
        return DEFAULT_GEMINI_MODEL
    if provider == "copilot":
        return DEFAULT_COPILOT_MODEL
    return DEFAULT_CODEX_MODEL


def utc_now() -> str:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(UTC).isoformat()


class RuntimeConfig(BaseModel):
    """User-selected runtime settings."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    provider: ProviderName = DEFAULT_PROVIDER
    cto_model: ProviderModel = DEFAULT_GEMINI_MODEL
    developer_model: ProviderModel = DEFAULT_GEMINI_MODEL
    cto_reasoning_effort: ReasoningEffort = DEFAULT_CODEX_REASONING_EFFORT
    developer_reasoning_effort: ReasoningEffort = DEFAULT_CODEX_REASONING_EFFORT
    repo_url: str
    ssh_key_path: Path | None = None
    base_branch: str = "main"
    loop_limit: int = Field(default=3, ge=1)
    validation_command: str = Field(default=DEFAULT_VALIDATION_COMMAND, min_length=1)

    @model_validator(mode="before")
    @classmethod
    def set_provider_default_models(cls, data: object) -> object:
        """Default node models from the selected provider when omitted."""
        if not isinstance(data, dict):
            return data
        fields = dict(data)
        provider = fields.get("provider", DEFAULT_PROVIDER)
        if provider not in PROVIDERS:
            return fields
        default_model = default_model_for_provider(provider)
        if fields.get("cto_model") is None:
            fields["cto_model"] = default_model
        if fields.get("developer_model") is None:
            fields["developer_model"] = default_model
        return fields


class WorkflowEvent(BaseModel):
    """One append-only workflow event."""

    ts: str = Field(default_factory=utc_now)
    event: str
    fields: dict[str, JsonValue] = Field(default_factory=dict)


class ProviderResult(BaseModel):
    """Normalized result from one provider execution."""

    provider: ProviderName
    role: str
    model: ProviderModel
    reasoning_effort: ReasoningEffort | None = None
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
    provider: ProviderName | None = None
    model: ProviderModel | None = None
    reasoning_effort: ReasoningEffort | None = None
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
    worker_pid: int | None = None
    worker_log_path: Path | None = None
    stop_requested_at: str | None = None
    finished_at: str | None = None
    failure_message: str = ""
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
    application: str
    repo_url: str
    provider: ProviderName
    status: WorkflowStatus
    approval_status: str
    created_at: str
    updated_at: str
    loop_count: int
    developer_branch: str
    request_preview: str
    run_dir: str

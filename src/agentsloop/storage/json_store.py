"""Run persistence using JSON, NDJSON, Markdown reports, and node artifacts."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

import orjson

from agentsloop.domain.models import (
    PROVIDERS,
    JsonValue,
    NodeRole,
    NodeRun,
    NodeStatus,
    ProviderModel,
    ProviderName,
    ReasoningEffort,
    RunSummary,
    WorkflowEvent,
    WorkflowState,
    default_model_for_provider,
    models_for_provider,
    utc_now,
)

type JsonPayload = dict[str, Any] | list[Any]
EventSink = Callable[[WorkflowEvent], None]
LOG_TAIL_BYTES = 64 * 1024
HTTP_429_PATTERN = re.compile(r"(?<!\d)429(?!\d)")


def json_dumps(payload: JsonPayload) -> str:
    """Serialize JSON payloads with stable indentation."""
    return orjson.dumps(payload, option=orjson.OPT_INDENT_2 | orjson.OPT_APPEND_NEWLINE).decode()


def application_name_from_repo_url(repo_url: str) -> str:
    """Return a stable application label from a repository URL."""
    url = repo_url.strip().rstrip("/")
    if not url:
        return "Unknown application"
    if "://" in url:
        path = urlparse(url).path.strip("/")
    elif ":" in url and not url.startswith("/"):
        path = url.split(":", 1)[1].strip("/")
    else:
        path = Path(url).name
    clean = path.removesuffix(".git")
    return clean or url


def load_workflow_state(path: Path) -> WorkflowState:
    """Load persisted workflow state, repairing obsolete display-only model values."""
    payload = orjson.loads(path.read_bytes())
    if isinstance(payload, dict):
        sanitize_workflow_state_payload(payload)
    return WorkflowState.model_validate(payload)


def sanitize_workflow_state_payload(payload: dict[str, Any]) -> None:
    """Normalize obsolete provider model slugs in old run artifacts."""
    config = payload.get("config")
    config_provider = _provider_from_mapping(config)
    if isinstance(config, dict) and config_provider is not None:
        _sanitize_model_field(config, "cto_model", config_provider)
        _sanitize_model_field(config, "developer_model", config_provider)

    node_runs = payload.get("node_runs")
    if not isinstance(node_runs, list):
        return
    for node in node_runs:
        if isinstance(node, dict):
            provider = _provider_from_mapping(node) or config_provider
            if provider is not None:
                _sanitize_model_field(node, "model", provider)


def _provider_from_mapping(value: object) -> ProviderName | None:
    """Read a provider name from a raw persisted object."""
    if not isinstance(value, dict):
        return None
    provider = value.get("provider")
    if provider not in PROVIDERS:
        return None
    return cast(ProviderName, provider)


def _sanitize_model_field(payload: dict[str, Any], field: str, provider: ProviderName) -> None:
    """Replace a stale model slug with the current provider default."""
    model = payload.get(field)
    if model is None or model in models_for_provider(provider):
        return
    payload[field] = default_model_for_provider(provider)


class RunStore:
    """Read and write all artifacts for workflow runs."""

    def __init__(self, runs_dir: Path, event_sink: EventSink | None = None) -> None:
        self.runs_dir = runs_dir
        self.event_sink = event_sink
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def prepare(self, state: WorkflowState) -> None:
        """Create the directory structure for a run."""
        (state.run_dir / "nodes").mkdir(parents=True, exist_ok=True)
        self.save_state(state)

    def event(self, state: WorkflowState, event: str, **fields: JsonValue) -> WorkflowEvent:
        """Append one event and mirror it to the optional live sink."""
        workflow_event = WorkflowEvent(event=event, fields=dict(fields))
        state.run_dir.mkdir(parents=True, exist_ok=True)
        with (state.run_dir / "events.ndjson").open("ab") as handle:
            handle.write(orjson.dumps(workflow_event.model_dump(mode="json")))
            handle.write(b"\n")
        if self.event_sink is not None:
            self.event_sink(workflow_event)
        return workflow_event

    def handoff(self, state: WorkflowState, name: str, payload: dict[str, Any]) -> Path:
        """Write one structured handoff payload."""
        path = state.run_dir / "handoffs" / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json_dumps(payload), encoding="utf-8")
        self.event(state, "handoff_written", name=name, path=str(path))
        return path

    def request_stop(self, state: WorkflowState, reason: str) -> Path:
        """Persist a cooperative workflow stop request."""
        path = self.stop_request_path(state)
        path.write_text(json_dumps({"requested_at": utc_now(), "reason": reason}), encoding="utf-8")
        if state.stop_requested_at is None:
            state.stop_requested_at = utc_now()
        if state.status == "running":
            state.status = "stopping"
        self.save_state(state)
        self.event(state, "stop_requested", task_id=state.task_id, reason=reason, path=str(path))
        return path

    def stop_request_path(self, state: WorkflowState) -> Path:
        """Return the durable stop request path for a workflow."""
        return state.run_dir / "stop-request.json"

    def stop_requested(self, state: WorkflowState) -> bool:
        """Return whether a workflow has been asked to stop."""
        return self.stop_request_path(state).exists() or state.stop_requested_at is not None

    def start_node(
        self,
        state: WorkflowState,
        *,
        role: NodeRole,
        iteration: int,
        provider: ProviderName | None = None,
        model: ProviderModel | None,
        reasoning_effort: ReasoningEffort | None = None,
        prompt_md: str | None = None,
    ) -> NodeRun:
        """Create and record the artifact envelope for one node execution."""
        base = self.node_dir(state, role, iteration)
        logs = base / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        repo_path = base / "repo"
        prompt_path: Path | None = None
        if prompt_md is not None:
            prompt_path = base / "prompt.md"
            prompt_path.write_text(prompt_md.rstrip() + "\n", encoding="utf-8")
        node_run = NodeRun(
            role=role,
            iteration=iteration,
            status="running",
            started_at=utc_now(),
            provider=provider,
            model=model,
            reasoning_effort=reasoning_effort,
            prompt_path=prompt_path,
            report_path=base / "report.md",
            result_path=base / "result.json",
            stdout_path=logs / "stdout.txt",
            stderr_path=logs / "stderr.txt",
            repo_path=repo_path,
        )
        state.node_runs.append(node_run)
        self.save_state(state)
        self.event(
            state,
            "node_started",
            node=role,
            iteration=iteration,
            provider=provider,
            model=model,
            reasoning_effort=reasoning_effort,
            repo_path=str(repo_path),
        )
        return node_run

    def finish_node(
        self,
        state: WorkflowState,
        node_run: NodeRun,
        *,
        status: NodeStatus,
        exit_code: int | None,
        **fields: JsonValue,
    ) -> None:
        """Mark one node as finished and persist the state."""
        stored = self._find_node(state, node_run)
        stored.status = status
        stored.exit_code = exit_code
        stored.finished_at = utc_now()
        self.save_state(state)
        self.event(
            state,
            "node_finished",
            node=stored.role,
            iteration=stored.iteration,
            status=status,
            exit_code=exit_code,
            **fields,
        )

    def finish_running_nodes(
        self,
        state: WorkflowState,
        *,
        status: NodeStatus,
        exit_code: int | None,
        reason: str,
    ) -> None:
        """Mark every still-running node with a terminal status."""
        changed = False
        for node in state.node_runs:
            if node.status != "running":
                continue
            node.status = status
            node.exit_code = exit_code
            node.finished_at = utc_now()
            changed = True
            self.event(
                state,
                "node_finished",
                node=node.role,
                iteration=node.iteration,
                status=status,
                exit_code=exit_code,
                reason=reason,
            )
        if changed:
            self.save_state(state)

    def node_dir(self, state: WorkflowState, role: NodeRole, iteration: int) -> Path:
        """Return the artifact directory for a node execution."""
        return state.run_dir / "nodes" / role / f"{iteration:02d}"

    def write_node_report(self, state: WorkflowState, node_run: NodeRun, content: str) -> Path:
        """Write the Markdown report for one node."""
        stored = self._find_node(state, node_run)
        stored.report_path.parent.mkdir(parents=True, exist_ok=True)
        stored.report_path.write_text(content.rstrip() + "\n", encoding="utf-8")
        self.event(
            state,
            "report_written",
            role=stored.role,
            iteration=stored.iteration,
            path=str(stored.report_path),
        )
        return stored.report_path

    def write_node_result(
        self, state: WorkflowState, node_run: NodeRun, payload: dict[str, Any]
    ) -> Path:
        """Write the structured result for one node."""
        stored = self._find_node(state, node_run)
        stored.result_path.write_text(json_dumps(payload), encoding="utf-8")
        self.event(
            state,
            "result_written",
            role=stored.role,
            iteration=stored.iteration,
            path=str(stored.result_path),
        )
        return stored.result_path

    def write_node_logs(
        self,
        state: WorkflowState,
        node_run: NodeRun,
        *,
        stdout: str,
        stderr: str,
    ) -> None:
        """Write captured stdout and stderr logs for one node."""
        stored = self._find_node(state, node_run)
        stored.stdout_path.write_text(stdout.rstrip() + "\n" if stdout else "", encoding="utf-8")
        stored.stderr_path.write_text(stderr.rstrip() + "\n" if stderr else "", encoding="utf-8")
        self.event(
            state,
            "logs_written",
            role=stored.role,
            iteration=stored.iteration,
            stdout_path=str(stored.stdout_path),
            stderr_path=str(stored.stderr_path),
        )

    def report(self, state: WorkflowState, role: str, iteration: int, content: str) -> Path:
        """Write one rendered node report."""
        path = state.run_dir / "nodes" / role / f"{iteration:02d}" / "report.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content.rstrip() + "\n", encoding="utf-8")
        self.event(state, "report_written", role=role, iteration=iteration, path=str(path))
        return path

    def save_state(self, state: WorkflowState) -> Path:
        """Persist the current workflow state."""
        state.touch()
        path = state.run_dir / "state.json"
        path.write_text(json_dumps(state.snapshot()), encoding="utf-8")
        return path

    def write_summary(self, state: WorkflowState) -> Path:
        """Write the final Markdown summary."""
        node_lines = [
            f"- {node.role} #{node.iteration}: {node.status}"
            + (f" [{node.provider}]" if node.provider else "")
            + (f" {node.model}" if node.model else "")
            + (f" ({node.reasoning_effort})" if node.reasoning_effort else "")
            + (f" (exit {node.exit_code})" if node.exit_code is not None else "")
            for node in state.node_runs
        ]
        path = state.run_dir / "summary.md"
        path.write_text(
            "\n".join(
                [
                    "# Agent Workflow Summary",
                    "",
                    f"- task_id: {state.task_id}",
                    f"- status: {state.status}",
                    f"- approval_status: {state.approval_status}",
                    f"- provider: {state.config.provider}",
                    f"- cto_model: {state.config.cto_model}",
                    f"- cto_reasoning_effort: {state.config.cto_reasoning_effort}",
                    f"- developer_model: {state.config.developer_model}",
                    f"- developer_reasoning_effort: {state.config.developer_reasoning_effort}",
                    f"- loop_count: {state.loop_count}/{state.config.loop_limit}",
                    f"- validation_command: {state.config.validation_command}",
                    f"- developer_branch: {state.developer_branch or '_none_'}",
                    "",
                    "## Timeline",
                    "",
                    *(node_lines or ["_none_"]),
                    "",
                    "## Human Response",
                    "",
                    state.reports.get("human_response") or "_none_",
                    "",
                    "## Technical Summary",
                    "",
                    state.reports.get("technical_summary") or "_none_",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return path

    def load_state(self, task_id: str) -> WorkflowState:
        """Load one workflow state by run identifier."""
        path = self.runs_dir / task_id / "state.json"
        return load_workflow_state(path)

    def list_runs(self) -> list[RunSummary]:
        """Return all known runs, newest first."""
        summaries: list[RunSummary] = []
        for state_path in self.runs_dir.glob("*/state.json"):
            state = load_workflow_state(state_path)
            summaries.append(
                RunSummary(
                    task_id=state.task_id,
                    application=application_name_from_repo_url(state.config.repo_url),
                    repo_url=state.config.repo_url,
                    provider=state.config.provider,
                    status=state.status,
                    approval_status=state.approval_status,
                    created_at=state.created_at,
                    updated_at=state.updated_at,
                    loop_count=state.loop_count,
                    developer_branch=state.developer_branch,
                    request_preview=state.human_request_md[:100],
                    run_dir=str(state.run_dir),
                )
            )
        return sorted(summaries, key=lambda item: item.updated_at, reverse=True)

    def read_events(self, task_id: str) -> list[WorkflowEvent]:
        """Read all persisted events for one run."""
        path = self.runs_dir / task_id / "events.ndjson"
        if not path.exists():
            return []
        events: list[WorkflowEvent] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(WorkflowEvent.model_validate_json(line))
        return events

    def read_node_report(self, node_run: NodeRun) -> str:
        """Read the rendered report for one node."""
        if not node_run.report_path.exists():
            return "_No report written yet._"
        return node_run.report_path.read_text(encoding="utf-8")

    def read_node_log_tail(self, node_run: NodeRun, lines: int = 80) -> str:
        """Read recent stdout/stderr output for one node."""
        parts: list[str] = []
        total_429 = 0
        for label, path in (("stdout", node_run.stdout_path), ("stderr", node_run.stderr_path)):
            content = read_text_tail(path, lines=lines)
            if content:
                if node_run.provider == "gemini":
                    stream_429 = _count_429_lines(content)
                    if stream_429 > 0:
                        total_429 += stream_429
                        continue
                parts.append(f"[{label}]\n{content}")
        if node_run.provider == "gemini" and total_429 > 0:
            parts.insert(
                0,
                (f"[gemini] HTTP 429 count: {total_429} (verbose rate-limit logs hidden)"),
            )
        return "\n\n".join(parts)

    def _find_node(self, state: WorkflowState, node_run: NodeRun) -> NodeRun:
        """Return the matching mutable node run stored in the workflow state."""
        for stored in state.node_runs:
            if stored.role == node_run.role and stored.iteration == node_run.iteration:
                return stored
        state.node_runs.append(node_run)
        return node_run


def read_text_tail(path: Path, *, lines: int = 80, max_bytes: int = LOG_TAIL_BYTES) -> str:
    """Read the last lines of a UTF-8-ish text file without loading large logs."""
    if not path.exists():
        return ""
    with path.open("rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        handle.seek(max(0, size - max_bytes))
        data = handle.read()
    text = data.decode("utf-8", errors="replace")
    if size > max_bytes:
        text = text.split("\n", 1)[-1]
    return "\n".join(text.splitlines()[-lines:])


def _count_429_lines(content: str) -> int:
    """Count log lines that contain an HTTP 429 marker."""
    return sum(1 for line in content.splitlines() if HTTP_429_PATTERN.search(line))

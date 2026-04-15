"""Tests for the Gemini agentic workflow TUI project."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, TextIO

import pytest
from pydantic import ValidationError
from textual.widgets import Select
from typer.testing import CliRunner

from agentic_workflows.cli import cli
from agentic_workflows.domain.models import (
    DEFAULT_GEMINI_MODEL,
    ProviderResult,
    RuntimeConfig,
    WorkflowState,
    utc_now,
)
from agentic_workflows.nodes.cto import ensure_developer_branch
from agentic_workflows.orchestrator import run_workflow
from agentic_workflows.paths import prompts_root, runs_root
from agentic_workflows.runtime.agent_runner import AgentRunSpec
from agentic_workflows.runtime.git_runtime import env_with_agent_ssh
from agentic_workflows.runtime.providers import build_provider_command
from agentic_workflows.runtime.templates import parse_approval_status, render_template, slugify
from agentic_workflows.runtime.workflow_launcher import spawn_workflow_process
from agentic_workflows.storage.json_store import RunStore
from agentic_workflows.tui.app import WorkflowApp


def config() -> RuntimeConfig:
    """Build a minimal Gemini runtime config."""
    return RuntimeConfig(
        repo_url="git@example.com:x/y.git",
        base_branch="main",
        loop_limit=2,
    )


def test_runtime_config_uses_strict_gemini_models() -> None:
    """Validate the default model and reject models outside the curated list."""
    runtime_config = config()
    assert runtime_config.model == DEFAULT_GEMINI_MODEL
    with pytest.raises(ValidationError):
        RuntimeConfig(repo_url="git@example.com:x/y.git", model="gemini-test")


def test_runs_root_defaults_to_home_directory() -> None:
    """Keep durable runs outside the repository."""
    assert runs_root() == Path("~/algosia-agent-workflows").expanduser()


def test_prompt_rendering_and_slug() -> None:
    """Render templates and preserve compact branch slugs."""
    rendered = render_template(prompts_root() / "developer_prompt.md", {"task_id": "abc"})
    assert "abc" in rendered
    assert slugify("Créer `test.md` maintenant!") == "cr-er-test-md"


def test_cto_approval_parser_defaults_to_continue() -> None:
    """Parse CTO decisions from Markdown reports."""
    assert parse_approval_status("# Controller\napproval_status: done\n") == "done"
    assert parse_approval_status("# Controller\nno status\n") == "continue"


def test_provider_command_uses_gemini_headless() -> None:
    """Build the only active provider command."""
    command = build_provider_command("gemini", DEFAULT_GEMINI_MODEL, "prompt")
    assert command.args == [
        "gemini",
        "--model",
        DEFAULT_GEMINI_MODEL,
        "--yolo",
        "--output-format",
        "text",
        "--prompt",
        "prompt",
    ]


def test_env_uses_agents_ssh_before_n8n(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Resolve AGENTS_* SSH settings before N8N_* fallbacks."""
    repo = tmp_path / "repo"
    (repo / "agents").mkdir(parents=True)
    (repo / "agents" / ".env").write_text(
        "\n".join(
            [
                "N8N_GIT_SSH_KEY_PATH=~/n8n_key",
                "AGENTS_GIT_SSH_KEY_PATH=~/agents_key",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("GIT_SSH_COMMAND", raising=False)
    env = env_with_agent_ssh(repo, {})
    assert "agents_key" in env["GIT_SSH_COMMAND"]
    assert "n8n_key" not in env["GIT_SSH_COMMAND"]


def test_store_writes_node_artifacts_and_history(tmp_path: Path) -> None:
    """Persist and reload the new node artifact layout."""
    state = run_state(tmp_path)
    store = RunStore(tmp_path)
    store.prepare(state)
    node = store.start_node(
        state,
        role="cto",
        iteration=0,
        model=DEFAULT_GEMINI_MODEL,
        prompt_md="# Prompt",
    )
    store.write_node_logs(state, node, stdout="stdout", stderr="stderr")
    store.write_node_result(state, node, {"ok": True})
    store.write_node_report(state, node, "# Report")
    store.finish_node(state, node, status="success", exit_code=0)
    store.write_summary(state)
    loaded = store.load_state("run-1")
    assert (
        loaded.node_runs[0].report_path == tmp_path / "run-1" / "nodes" / "cto" / "00" / "report.md"
    )
    assert loaded.node_runs[0].repo_path.name == "repo"
    assert store.read_events("run-1")[0].event == "node_started"
    assert store.list_runs()[0].task_id == "run-1"


def test_workflow_launcher_spawns_detached_worker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Create the run envelope and spawn a detached worker process."""

    class FakePopen:
        """Capture worker launch arguments."""

        pid = 1234
        last_kwargs: dict[str, object] = {}

        def __init__(self, *_args: object, **kwargs: object) -> None:
            self.__class__.last_kwargs = kwargs

    monkeypatch.setattr("agentic_workflows.runtime.workflow_launcher.subprocess.Popen", FakePopen)
    launch = spawn_workflow_process(
        human_request_md="Build the thing",
        config=config(),
        task_id="run-1",
        runs_dir=tmp_path,
    )
    assert launch.pid == 1234
    assert launch.request_path.exists()
    assert launch.worker_log_path.exists()
    assert FakePopen.last_kwargs["start_new_session"] is True
    assert (tmp_path / "run-1" / "events.ndjson").exists()


def test_developer_branch_is_stable(tmp_path: Path) -> None:
    """Create the developer branch only once."""
    state = run_state(tmp_path)
    ensure_developer_branch(state)
    first = state.developer_branch
    state.human_request_md = "another request"
    ensure_developer_branch(state)
    assert state.developer_branch == first
    assert first.startswith("agent/dev/build-the-thing-run-1")


def test_orchestrator_runs_with_stubbed_agents_and_ci(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Exercise orchestration and node metadata without external providers."""
    cto_reports = [
        "# Controller\napproval_status: continue\n\n# Developer Task\nImplement.\n",
        "# Controller\napproval_status: done\n\n# Developer Task\n_none_\n",
    ]

    def fake_run_agent(spec: AgentRunSpec, task_id: str) -> ProviderResult:
        del task_id
        report = cto_reports.pop(0) if spec.role == "cto" else "# Summary\nDone"
        return ProviderResult(
            provider="gemini",
            role=spec.role,
            model=spec.model,
            status="success",
            report_md=report,
            stdout_path=str(spec.stdout_path),
            stderr_path=str(spec.stderr_path),
            exit_code=0,
            started_at=utc_now(),
            finished_at=utc_now(),
            repo_path=str(spec.repo_path),
            branch=spec.working_branch or "main",
        )

    def fake_clone_for_agent(**kwargs: object) -> None:
        repo_path = kwargs["repo_path"]
        assert isinstance(repo_path, Path)
        repo_path.mkdir(parents=True)

    class FakeProcess:
        """Small stand-in for CI subprocesses."""

        returncode = 0

        def __init__(self, *_args: Any, stdout: TextIO, **_kwargs: Any) -> None:
            stdout.write("ok\n")

        def wait(self) -> int:
            """Return the fake exit code."""
            return self.returncode

    monkeypatch.setattr("agentic_workflows.nodes.cto.run_agent", fake_run_agent)
    monkeypatch.setattr("agentic_workflows.nodes.developer.run_agent", fake_run_agent)
    monkeypatch.setattr("agentic_workflows.nodes.ci.clone_for_agent", fake_clone_for_agent)
    monkeypatch.setattr("agentic_workflows.nodes.ci.subprocess.Popen", FakeProcess)
    state = run_workflow(
        human_request_md="Build the thing",
        config=config(),
        task_id="run-1",
        runs_dir=tmp_path,
    )
    assert state.status == "success"
    assert [node.role for node in state.node_runs] == ["cto", "developer", "ci", "cto"]
    assert (
        state.node_runs[1].repo_path == tmp_path / "run-1" / "nodes" / "developer" / "01" / "repo"
    )
    assert (tmp_path / "run-1" / "summary.md").exists()


def test_cli_exposes_only_tui_options() -> None:
    """Remove the old Rich command surface from the user-facing CLI."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "--runs-root" in result.output
    assert "history" not in result.output
    assert "watch" not in result.output


def test_textual_app_launch_screen_contains_model_select(tmp_path: Path) -> None:
    """Instantiate the Textual shell and verify the model selector."""

    async def run_app() -> None:
        app = WorkflowApp(tmp_path)
        async with app.run_test() as pilot:
            await pilot.press("n")
            model_select = app.screen.query_one("#model", Select)
            assert model_select.value == DEFAULT_GEMINI_MODEL

    asyncio.run(run_app())


def run_state(tmp_path: Path) -> WorkflowState:
    """Build a state for persistence tests."""
    from agentic_workflows.orchestrator import create_state

    return create_state(
        human_request_md="Build the thing",
        config=config(),
        task_id="run-1",
        runs_dir=tmp_path,
    )

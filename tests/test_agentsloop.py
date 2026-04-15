"""Tests for the Gemini agentic workflow TUI project."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, ClassVar, TextIO, cast
from unittest.mock import patch

import pytest
from pydantic import ValidationError
from textual.screen import Screen
from textual.widgets import Input, Select
from typer.testing import CliRunner

from agentsloop.cli import cli
from agentsloop.domain.models import (
    DEFAULT_GEMINI_MODEL,
    DEFAULT_VALIDATION_COMMAND,
    ProviderResult,
    RuntimeConfig,
    WorkflowState,
    utc_now,
)
from agentsloop.nodes.cto import ensure_developer_branch
from agentsloop.orchestrator import run_workflow
from agentsloop.paths import prompts_root, runs_root
from agentsloop.project_config import ProjectConfig, ProjectConfigStore, ProjectContext
from agentsloop.runtime.agent_runner import AgentRunSpec
from agentsloop.runtime.git_runtime import env_with_agent_ssh
from agentsloop.runtime.providers import build_provider_command
from agentsloop.runtime.templates import parse_approval_status, render_template, slugify
from agentsloop.runtime.workflow_launcher import spawn_workflow_process
from agentsloop.storage.json_store import RunStore
from agentsloop.tui.app import WorkflowApp
from agentsloop.tui.screens import HomeScreen, ProjectSetupScreen


def config(validation_command: str = DEFAULT_VALIDATION_COMMAND) -> RuntimeConfig:
    """Build a minimal Gemini runtime config."""
    return RuntimeConfig(
        repo_url="git@example.com:x/y.git",
        base_branch="main",
        loop_limit=2,
        validation_command=validation_command,
    )


def test_runtime_config_uses_strict_gemini_models() -> None:
    """Validate the default model and reject models outside the curated list."""
    runtime_config = config()
    assert runtime_config.model == DEFAULT_GEMINI_MODEL
    assert runtime_config.validation_command == DEFAULT_VALIDATION_COMMAND
    with pytest.raises(ValidationError):
        RuntimeConfig(repo_url="git@example.com:x/y.git", model=cast(Any, "gemini-test"))


def test_runs_root_defaults_to_home_directory() -> None:
    """Keep durable runs outside the repository."""
    assert runs_root() == Path("~/agentsloop-runs").expanduser()


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


def test_env_uses_agents_ssh_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Resolve AGENTS_* SSH settings."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    (repo / ".env").write_text(
        "\n".join(
            [
                "AGENTS_GIT_SSH_KEY_PATH=~/agents_key",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("GIT_SSH_COMMAND", raising=False)
    env = env_with_agent_ssh(repo, {})
    assert "agents_key" in env["GIT_SSH_COMMAND"]


def test_project_config_store_persists_validation_command(tmp_path: Path) -> None:
    """Persist local settings outside the current repository."""
    repo = tmp_path / "repo"
    repo.mkdir()
    store = ProjectConfigStore(repo, tmp_path / "config")
    store.save(ProjectConfig(validation_command="npm test"))
    loaded = store.load()
    assert loaded is not None
    assert loaded.validation_command == "npm test"


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
        last_kwargs: ClassVar[dict[str, object]] = {}

        def __init__(self, *_args: object, **kwargs: object) -> None:
            self.__class__.last_kwargs = kwargs

    monkeypatch.setattr("agentsloop.runtime.workflow_launcher.subprocess.Popen", FakePopen)
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


def test_orchestrator_runs_with_stubbed_agents_and_validation(
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
        """Small stand-in for validation subprocesses."""

        returncode = 0
        last_command: ClassVar[list[str]] = []

        def __init__(self, command: list[str], *_args: Any, stdout: TextIO, **_kwargs: Any) -> None:
            self.__class__.last_command = command
            stdout.write("ok\n")

        def wait(self) -> int:
            """Return the fake exit code."""
            return self.returncode

    monkeypatch.setattr("agentsloop.nodes.cto.run_agent", fake_run_agent)
    monkeypatch.setattr("agentsloop.nodes.developer.run_agent", fake_run_agent)
    monkeypatch.setattr("agentsloop.nodes.cto.run_git", lambda *args, **kwargs: None)
    monkeypatch.setattr("agentsloop.nodes.validation.clone_for_agent", fake_clone_for_agent)
    monkeypatch.setattr("agentsloop.nodes.validation.subprocess.Popen", FakeProcess)

    state = run_workflow(
        human_request_md="Build the thing",
        config=config(validation_command="npm test"),
        task_id="run-1",
        runs_dir=tmp_path,
    )
    assert state.status == "success"
    assert [node.role for node in state.node_runs] == ["cto", "developer", "validation", "cto"]
    assert FakeProcess.last_command == ["bash", "-lc", "npm test"]
    validation = state.validation["validation"]
    assert isinstance(validation, dict)
    assert validation["command"] == "npm test"
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


def test_cli_requires_git_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reject launches outside a Git repository."""
    monkeypatch.setattr("agentsloop.cli.find_git_root", lambda _cwd: None)
    runner = CliRunner()
    result = runner.invoke(cli, [])
    assert result.exit_code == 1
    assert "Git repository" in result.output


def test_textual_app_launch_screen_contains_model_select(tmp_path: Path) -> None:
    """Instantiate the Textual shell and verify the model selector."""

    async def run_app() -> None:
        app = WorkflowApp(tmp_path, ProjectContext(repo_root=tmp_path, base_branch="main", ssh_key_path=Path("~/.ssh/id_rsa")))
        original_push_screen = app.push_screen
        with (
            patch("agentsloop.tui.app.LoadingScreen"),
            patch("agentsloop.tui.screens.verify_git_write_access"),
            patch.object(WorkflowApp, "push_screen") as mock_push,
        ):

            def side_effect(screen, **kwargs):
                if not isinstance(screen, (Screen, str)):
                    return None
                return original_push_screen(screen, **kwargs)

            mock_push.side_effect = side_effect

            async with app.run_test() as pilot:
                # Bypass loading
                app.push_screen(HomeScreen(app.store, app.project_context))
                await pilot.pause()
                await pilot.press("n")
                model_select = app.screen.query_one("#model", Select)
                validation_command = app.screen.query_one("#validation_command", Input)
                assert model_select.value == DEFAULT_GEMINI_MODEL
                assert validation_command.value == DEFAULT_VALIDATION_COMMAND

    asyncio.run(run_app())


def test_textual_app_collects_first_run_validation_command(tmp_path: Path) -> None:
    """Show setup before home when a repository has no saved config."""

    async def run_app() -> None:
        store = ProjectConfigStore(tmp_path, tmp_path / "config")
        context = ProjectContext(
            repo_root=tmp_path,
            base_branch="main",
            config_store=store,
            configured=False,
            ssh_key_path=Path("~/.ssh/id_rsa"),
        )
        app = WorkflowApp(tmp_path / "runs", context)
        original_push_screen = app.push_screen
        # Mock LoadingScreen and skip its check to jump directly to Setup
        with (
            patch("agentsloop.tui.app.LoadingScreen"),
            patch("agentsloop.tui.screens.verify_git_write_access"),
            patch.object(WorkflowApp, "push_screen") as mock_push,
        ):

            def side_effect(screen, **kwargs):
                if not isinstance(screen, (Screen, str)):
                    return None  # Skip the mock screen
                return original_push_screen(screen, **kwargs)

            mock_push.side_effect = side_effect

            async with app.run_test() as pilot:
                # Manually push the setup screen
                app.push_screen(ProjectSetupScreen(app.store, context))
                await pilot.pause()
                assert isinstance(app.screen, ProjectSetupScreen)
                app.screen.query_one("#validation_command", Input).value = "npm test"
                await pilot.click("#save")
                assert isinstance(app.screen, HomeScreen)
                assert context.validation_command == "npm test"
                assert store.load() is not None

    asyncio.run(run_app())


def run_state(tmp_path: Path) -> WorkflowState:
    """Build a state for persistence tests."""
    from agentsloop.orchestrator import create_state

    return create_state(
        human_request_md="Build the thing",
        config=config(),
        task_id="run-1",
        runs_dir=tmp_path,
    )

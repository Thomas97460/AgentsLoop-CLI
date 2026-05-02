"""Tests for the AgentsLoop agentic workflow TUI project."""

from __future__ import annotations

import asyncio
import subprocess
from collections.abc import Coroutine
from pathlib import Path
from typing import Any, ClassVar, TextIO, cast
from unittest.mock import patch

import pytest
from pydantic import ValidationError
from textual.screen import Screen
from textual.widgets import Input, Label, Select
from typer.testing import CliRunner

from agentsloop.cli import cli
from agentsloop.domain.models import (
    CODEX_MODELS,
    COPILOT_MODELS,
    DEFAULT_CODEX_MODEL,
    DEFAULT_CODEX_REASONING_EFFORT,
    DEFAULT_COPILOT_MODEL,
    DEFAULT_GEMINI_MODEL,
    DEFAULT_PROVIDER,
    DEFAULT_VALIDATION_COMMAND,
    REASONING_EFFORTS,
    ProviderModel,
    ProviderResult,
    ReasoningEffort,
    RuntimeConfig,
    WorkflowState,
    utc_now,
)
from agentsloop.nodes.cto import ensure_developer_branch
from agentsloop.orchestrator import run_workflow
from agentsloop.paths import prompts_root, runs_root
from agentsloop.project_config import ProjectConfig, ProjectConfigStore, ProjectContext
from agentsloop.runtime.agent_runner import AgentRunSpec
from agentsloop.runtime.git_runtime import (
    GitCommandError,
    env_with_agent_ssh,
    is_ssh_remote_url,
    require_ssh_origin_remote,
    run_git,
    verify_git_write_access,
)
from agentsloop.runtime.providers import build_provider_command
from agentsloop.runtime.templates import parse_approval_status, render_template, slugify
from agentsloop.runtime.workflow_control import reconcile_workflow_state, request_workflow_stop
from agentsloop.runtime.workflow_launcher import spawn_workflow_process
from agentsloop.storage.json_store import RunStore, application_name_from_repo_url, json_dumps
from agentsloop.tui.app import WorkflowApp
from agentsloop.tui.screens import (
    HomeScreen,
    LaunchScreen,
    ProjectSetupScreen,
    SSHKeySelectionScreen,
    WorkflowScreen,
)
from agentsloop.tui.widgets import workflow_events_plain_text


def config(
    validation_command: str = DEFAULT_VALIDATION_COMMAND,
    *,
    cto_model: ProviderModel = DEFAULT_GEMINI_MODEL,
    developer_model: ProviderModel = DEFAULT_GEMINI_MODEL,
) -> RuntimeConfig:
    """Build a minimal runtime config."""
    return RuntimeConfig(
        repo_url="git@example.com:x/y.git",
        cto_model=cto_model,
        developer_model=developer_model,
        ssh_key_path=Path("~/.ssh/id_rsa").expanduser(),
        base_branch="main",
        loop_limit=2,
        validation_command=validation_command,
    )


def test_runtime_config_uses_strict_provider_models() -> None:
    """Validate provider defaults and reject models outside each curated list."""
    runtime_config = config()
    codex_config = RuntimeConfig(provider="codex", repo_url="git@example.com:x/y.git")
    copilot_config = RuntimeConfig(provider="copilot", repo_url="git@example.com:x/y.git")
    assert runtime_config.provider == DEFAULT_PROVIDER
    assert runtime_config.cto_model == DEFAULT_GEMINI_MODEL
    assert runtime_config.developer_model == DEFAULT_GEMINI_MODEL
    assert codex_config.cto_model == DEFAULT_CODEX_MODEL
    assert codex_config.developer_model == DEFAULT_CODEX_MODEL
    assert copilot_config.cto_model == DEFAULT_COPILOT_MODEL
    assert copilot_config.developer_model == DEFAULT_COPILOT_MODEL
    assert codex_config.cto_reasoning_effort == DEFAULT_CODEX_REASONING_EFFORT
    assert codex_config.developer_reasoning_effort == DEFAULT_CODEX_REASONING_EFFORT
    assert copilot_config.cto_reasoning_effort == DEFAULT_CODEX_REASONING_EFFORT
    assert copilot_config.developer_reasoning_effort == DEFAULT_CODEX_REASONING_EFFORT
    assert CODEX_MODELS == (
        "gpt-5.4",
        "gpt-5.4-mini",
        "gpt-5.3-codex",
        "gpt-5.2",
    )
    assert COPILOT_MODELS == (
        "auto",
        "gpt-5.3-codex",
        "gpt-5.2-codex",
        "gpt-5.2",
        "gpt-5.4-mini",
        "gpt-5-mini",
        "gpt-4.1",
        "claude-haiku-4.5",
    )
    assert REASONING_EFFORTS == ("low", "medium", "high", "xhigh")
    assert runtime_config.validation_command == DEFAULT_VALIDATION_COMMAND
    # Model validation is now free-form string
    custom_config = RuntimeConfig(repo_url="git@example.com:x/y.git", cto_model="custom-model")
    assert custom_config.cto_model == "custom-model"
    with pytest.raises(ValidationError):
        RuntimeConfig(
            provider="codex",
            repo_url="git@example.com:x/y.git",
            cto_reasoning_effort=cast(Any, "extreme"),
        )
    copilot_auto_config = RuntimeConfig(
        provider="copilot",
        repo_url="git@example.com:x/y.git",
        cto_model="auto",
        developer_model="auto",
    )
    assert copilot_auto_config.cto_model == "auto"
    assert copilot_auto_config.developer_model == "auto"


def test_runs_root_defaults_to_home_directory() -> None:
    """Keep durable runs outside the repository."""
    assert runs_root() == Path("~/agentsloop-runs").expanduser()


def test_prompt_rendering_and_slug() -> None:
    """Render templates and preserve compact branch slugs."""
    rendered = render_template(prompts_root() / "developer_prompt.md", {"task_id": "abc"})
    assert "abc" in rendered
    assert slugify("Créer `test.md` maintenant!") == "cr-er-test-md"


@pytest.mark.parametrize(
    ("repo_url", "application"),
    [
        ("git@example.com:owner/app.git", "owner/app"),
        ("ssh://git@example.com/owner/app.git", "owner/app"),
        ("/workspace/app", "app"),
    ],
)
def test_application_name_from_repo_url(repo_url: str, application: str) -> None:
    """Derive stable application labels for workflow grouping."""
    assert application_name_from_repo_url(repo_url) == application


def test_cto_approval_parser_defaults_to_continue() -> None:
    """Parse CTO decisions from Markdown reports."""
    assert parse_approval_status("# Controller\napproval_status: done\n") == "done"
    assert parse_approval_status("# Controller\nno status\n") == "continue"


def test_provider_command_uses_gemini_headless() -> None:
    """Build the Gemini provider command."""
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
    assert command.stdin is None


def test_provider_command_uses_codex_exec_danger_mode(tmp_path: Path) -> None:
    """Build the Codex non-interactive provider command."""
    output_path = tmp_path / "last-message.md"
    command = build_provider_command(
        "codex",
        DEFAULT_CODEX_MODEL,
        "prompt",
        reasoning_effort="xhigh",
        output_path=output_path,
    )
    assert command.args == [
        "codex",
        "exec",
        "--dangerously-bypass-approvals-and-sandbox",
        "--model",
        DEFAULT_CODEX_MODEL,
        "-c",
        'model_reasoning_effort="xhigh"',
        "--color",
        "never",
        "--output-last-message",
        str(output_path),
        "-",
    ]
    assert command.stdin == "prompt"


def test_provider_command_uses_copilot_non_interactive_mode() -> None:
    """Build the Copilot non-interactive provider command."""
    command = build_provider_command(
        "copilot",
        DEFAULT_COPILOT_MODEL,
        "prompt",
        reasoning_effort="xhigh",
    )
    assert command.args == [
        "copilot",
        "--model",
        DEFAULT_COPILOT_MODEL,
        "--reasoning-effort",
        "xhigh",
        "--allow-all-tools",
        "--no-ask-user",
        "--no-color",
        "-s",
        "-p",
        "prompt",
    ]
    assert command.stdin is None


def test_provider_command_omits_copilot_auto_model_flag() -> None:
    """Use Copilot automatic model selection when auto is requested."""
    command = build_provider_command(
        "copilot",
        "auto",
        "prompt",
        reasoning_effort="xhigh",
    )
    assert command.args == [
        "copilot",
        "--allow-all-tools",
        "--no-ask-user",
        "--no-color",
        "-s",
        "-p",
        "prompt",
    ]
    assert command.stdin is None


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
    assert "-F /dev/null" in env["GIT_SSH_COMMAND"]


def test_env_explicit_ssh_key_overrides_existing_git_ssh_command(tmp_path: Path) -> None:
    """Use the selected key instead of a stale inherited SSH command."""
    selected_key = tmp_path / "selected_key"
    selected_key.touch()
    env = env_with_agent_ssh(
        tmp_path,
        {"GIT_SSH_COMMAND": "ssh -i /tmp/stale_key"},
        ssh_key_path=selected_key,
    )
    assert str(selected_key) in env["GIT_SSH_COMMAND"]
    assert "stale_key" not in env["GIT_SSH_COMMAND"]


def test_run_git_checked_error_includes_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    """Preserve Git stderr in checked command failures."""

    def fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["git", "push"],
            returncode=128,
            stdout="",
            stderr="ERROR: Permission denied\n",
        )

    monkeypatch.setattr("agentsloop.runtime.git_runtime.subprocess.run", fake_run)
    with pytest.raises(GitCommandError, match="Permission denied"):
        run_git(["push"], None, {}, check=True)


@pytest.mark.parametrize(
    "remote_url",
    [
        "git@example.com:x/y.git",
        "example-alias:x/y.git",
        "ssh://git@example.com/x/y.git",
        "git+ssh://git@example.com/x/y.git",
    ],
)
def test_is_ssh_remote_url_accepts_ssh_forms(remote_url: str) -> None:
    """Accept SSH Git remote URL styles."""
    assert is_ssh_remote_url(remote_url)


@pytest.mark.parametrize(
    "remote_url",
    [
        "https://example.com/x/y.git",
        "http://example.com/x/y.git",
        "/tmp/repo",
        "file:///tmp/repo",
    ],
)
def test_is_ssh_remote_url_rejects_non_ssh_forms(remote_url: str) -> None:
    """Reject origin URLs that will not use the configured SSH key."""
    assert not is_ssh_remote_url(remote_url)


def test_require_ssh_origin_remote_rejects_https(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Fail early when origin is configured with HTTPS."""

    def fake_run_git(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["git"],
            returncode=0,
            stdout="https://example.com/x/y.git\n",
            stderr="",
        )

    monkeypatch.setattr("agentsloop.runtime.git_runtime.run_git", fake_run_git)
    with pytest.raises(PermissionError, match="must use SSH"):
        require_ssh_origin_remote(tmp_path, {})


def test_verify_git_write_access_rejects_read_only_deploy_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Reject GitHub deploy keys that can read but cannot push."""
    results = [
        subprocess.CompletedProcess(
            args=["git"],
            returncode=0,
            stdout="git@example.com:x/y.git\n",
            stderr="",
        ),
        subprocess.CompletedProcess(args=["git"], returncode=0, stdout="", stderr=""),
        subprocess.CompletedProcess(args=["git"], returncode=0, stdout="", stderr=""),
        subprocess.CompletedProcess(
            args=["git"],
            returncode=128,
            stdout="",
            stderr="ERROR: Permission to x/y.git denied to deploy key\n",
        ),
    ]

    def fake_run_git(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return results.pop(0)

    monkeypatch.setattr("agentsloop.runtime.git_runtime.run_git", fake_run_git)
    with pytest.raises(PermissionError, match="denied to deploy key"):
        verify_git_write_access(tmp_path, {})


def test_project_config_store_persists_validation_command(tmp_path: Path) -> None:
    """Persist local settings outside the current repository."""
    repo = tmp_path / "repo"
    repo.mkdir()
    store = ProjectConfigStore(repo, tmp_path / "config")
    store.save(ProjectConfig(validation_command="npm test", ssh_key_path=tmp_path / "id_rsa"))
    loaded = store.load()
    assert loaded is not None
    assert loaded.validation_command == "npm test"
    assert loaded.ssh_key_path == tmp_path / "id_rsa"


def test_store_writes_node_artifacts_and_history(tmp_path: Path) -> None:
    """Persist and reload the new node artifact layout."""
    state = run_state(tmp_path)
    store = RunStore(tmp_path)
    store.prepare(state)
    node = store.start_node(
        state,
        role="cto",
        iteration=0,
        provider=DEFAULT_PROVIDER,
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
    assert "provider=gemini" in workflow_events_plain_text(store.read_events("run-1"))
    assert "stdout" in store.read_node_log_tail(loaded.node_runs[0])
    assert "node_started" in workflow_events_plain_text(store.read_events("run-1"))
    assert store.list_runs()[0].task_id == "run-1"
    assert store.list_runs()[0].application == "x/y"
    assert store.list_runs()[0].provider == DEFAULT_PROVIDER


def test_store_reads_old_runs_with_obsolete_codex_models(tmp_path: Path) -> None:
    """Keep the history screen usable when old run artifacts contain removed Codex slugs."""
    state = run_state(tmp_path)
    store = RunStore(tmp_path)
    store.prepare(state)
    store.start_node(
        state,
        role="cto",
        iteration=0,
        provider="codex",
        model=DEFAULT_CODEX_MODEL,
        reasoning_effort="low",
    )
    payload = cast(dict[str, Any], state.snapshot())
    config_payload = cast(dict[str, Any], payload["config"])
    config_payload["provider"] = "codex"
    config_payload["cto_model"] = "gpt-5.1-codex-mini"
    config_payload["developer_model"] = "gpt-5.1-codex-mini"
    node_payload = cast(dict[str, Any], cast(list[Any], payload["node_runs"])[0])
    node_payload["model"] = "gpt-5.1-codex-mini"
    state_path = tmp_path / "run-1" / "state.json"
    state_path.write_text(json_dumps(payload), encoding="utf-8")

    loaded = store.load_state("run-1")
    assert loaded.config.cto_model == DEFAULT_CODEX_MODEL
    assert loaded.config.developer_model == DEFAULT_CODEX_MODEL
    assert loaded.node_runs[0].model == DEFAULT_CODEX_MODEL
    assert store.list_runs()[0].provider == "codex"


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
    state = RunStore(tmp_path).load_state("run-1")
    assert state.worker_pid == 1234
    assert state.worker_log_path == launch.worker_log_path


def test_request_stop_marks_workflow_stopped_without_worker(tmp_path: Path) -> None:
    """Persist a stop request and finalize runs that do not have a live worker."""
    store = RunStore(tmp_path)
    state = run_state(tmp_path)
    store.prepare(state)
    stopped = request_workflow_stop(store, "run-1")
    loaded = store.load_state("run-1")
    assert stopped.status == "stopped"
    assert loaded.stop_requested_at is not None
    assert store.stop_request_path(loaded).exists()


def test_reconcile_marks_dead_worker_and_running_nodes_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Avoid stale running statuses when a detached worker has died."""
    store = RunStore(tmp_path)
    state = run_state(tmp_path)
    store.prepare(state)
    store.start_node(state, role="cto", iteration=0, model=DEFAULT_GEMINI_MODEL)
    state.worker_pid = 1234
    store.save_state(state)
    monkeypatch.setattr("agentsloop.runtime.workflow_control._process_is_alive", lambda _pid: False)
    reconciled = reconcile_workflow_state(store, "run-1")
    assert reconciled.status == "error"
    assert reconciled.node_runs[0].status == "error"
    assert (tmp_path / "run-1" / "summary.md").exists()


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
    model_calls: list[tuple[str, ProviderModel, ReasoningEffort | None]] = []

    def fake_run_agent(spec: AgentRunSpec, task_id: str) -> ProviderResult:
        del task_id
        model_calls.append((spec.role, spec.model, spec.reasoning_effort))
        if spec.role == "cto":
            report = cto_reports.pop(0)
            # Ensure the branch field is present if needed for parsing
            if "developer_branch:" not in report:
                report = report.replace(
                    "approval_status: continue",
                    f"approval_status: continue\ndeveloper_branch: {spec.working_branch}",
                ).replace(
                    "approval_status: done",
                    f"approval_status: done\ndeveloper_branch: {spec.working_branch}",
                )
        else:
            report = "# Summary\nDone"
        return ProviderResult(
            provider=spec.provider,
            role=spec.role,
            model=spec.model,
            reasoning_effort=spec.reasoning_effort,
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
        config=config(
            validation_command="npm test",
            cto_model="gemini-2.5-pro",
            developer_model="gemini-2.5-flash",
        ),
        task_id="run-1",
        runs_dir=tmp_path,
    )
    assert state.status == "success"
    assert [node.role for node in state.node_runs] == ["cto", "developer", "validation", "cto"]
    assert model_calls == [
        ("cto", "gemini-2.5-pro", None),
        ("developer", "gemini-2.5-flash", None),
        ("cto", "gemini-2.5-pro", None),
    ]
    assert FakeProcess.last_command == ["bash", "-lc", "npm test"]
    validation = state.validation["validation"]
    assert isinstance(validation, dict)
    assert validation["command"] == "npm test"
    assert (
        state.node_runs[1].repo_path == tmp_path / "run-1" / "nodes" / "developer" / "01" / "repo"
    )
    assert (tmp_path / "run-1" / "summary.md").exists()


def test_orchestrator_marks_running_node_error_on_exception(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A node exception must not leave workflow or node state stuck running."""

    def failing_run_agent(_spec: AgentRunSpec, _task_id: str) -> ProviderResult:
        raise RuntimeError("provider crashed")

    monkeypatch.setattr("agentsloop.nodes.cto.run_agent", failing_run_agent)
    with pytest.raises(RuntimeError, match="provider crashed"):
        run_workflow(
            human_request_md="Build the thing",
            config=config(),
            task_id="run-1",
            runs_dir=tmp_path,
        )
    state = RunStore(tmp_path).load_state("run-1")
    assert state.status == "error"
    assert state.node_runs[0].status == "error"
    assert state.failure_message == "provider crashed"


def test_orchestrator_surfaces_provider_error_message(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Expose the provider error summary instead of only the exit code."""

    def failing_run_agent(_spec: AgentRunSpec, _task_id: str) -> ProviderResult:
        return ProviderResult(
            provider="copilot",
            role="cto",
            model="auto",
            reasoning_effort="medium",
            status="error",
            report_md=(
                "Sorry, you've hit a rate limit that restricts the number of "
                "Copilot model requests you can make within a specific time period."
            ),
            stdout_path="stdout.txt",
            stderr_path="stderr.txt",
            exit_code=1,
            started_at=utc_now(),
            finished_at=utc_now(),
            repo_path=str(tmp_path / "repo"),
            branch="main",
        )

    monkeypatch.setattr("agentsloop.nodes.cto.run_agent", failing_run_agent)
    with pytest.raises(RuntimeError, match="rate limit"):
        run_workflow(
            human_request_md="Build the thing",
            config=RuntimeConfig(
                provider="copilot",
                repo_url="git@example.com:x/y.git",
                cto_model="auto",
                developer_model="auto",
                ssh_key_path=tmp_path / "dummy_key",
            ),
            task_id="run-1",
            runs_dir=tmp_path,
        )
    state = RunStore(tmp_path).load_state("run-1")
    assert state.status == "error"
    assert state.failure_message == (
        "CTO node failed: Sorry, you've hit a rate limit that restricts the number of Copilot "
        "model requests you can make within a specific time period."
    )


def test_cli_exposes_only_tui_options() -> None:
    """Remove the old Rich command surface from the user-facing CLI."""
    import click

    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    clean_output = click.unstyle(result.output)
    assert "--runs-root" in clean_output
    assert "history" not in clean_output
    assert "watch" not in clean_output


def test_cli_requires_git_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reject launches outside a Git repository."""
    monkeypatch.setattr("agentsloop.cli.find_git_root", lambda _cwd: None)
    runner = CliRunner()
    result = runner.invoke(cli, [])
    assert result.exit_code == 1
    assert "Git repository" in result.output


def test_cli_requires_ssh_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Reject launches without an SSH key path."""
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr("agentsloop.cli.find_git_root", lambda _cwd: repo)
    monkeypatch.setattr("agentsloop.cli.discover_ssh_key_path", lambda: None)
    runner = CliRunner()
    result = runner.invoke(cli, [])
    assert result.exit_code == 1
    assert "Git SSH key path is mandatory" in result.output


def test_cli_requires_ssh_origin(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Reject launches when origin is not an SSH remote."""
    repo = tmp_path / "repo"
    repo.mkdir()
    ssh_key = tmp_path / "id_rsa"
    ssh_key.touch()

    def reject_https_origin(_repo: Path) -> str:
        raise PermissionError("Git remote 'origin' must use SSH")

    monkeypatch.setattr("agentsloop.cli.find_git_root", lambda _cwd: repo)
    monkeypatch.setattr("agentsloop.cli.current_git_branch", lambda _repo: "main")
    monkeypatch.setattr("agentsloop.cli.require_ssh_origin_remote", reject_https_origin)

    runner = CliRunner()
    result = runner.invoke(cli, ["--ssh-key", str(ssh_key)])
    assert result.exit_code == 1
    assert "must use SSH" in result.output


def test_cli_accepts_ssh_key_option(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Accept the --ssh-key option and skip discovery."""
    repo = tmp_path / "repo"
    repo.mkdir()
    ssh_key = tmp_path / "manual_key"
    ssh_key.touch()

    # Mock discover to return None to ensure we rely on the option
    monkeypatch.setattr("agentsloop.cli.find_git_root", lambda _cwd: repo)
    monkeypatch.setattr("agentsloop.cli.discover_ssh_key_path", lambda: None)
    monkeypatch.setattr("agentsloop.cli.current_git_branch", lambda _repo: "main")
    monkeypatch.setattr(
        "agentsloop.cli.require_ssh_origin_remote",
        lambda _repo: "git@example.com:x/y.git",
    )

    # Mock WorkflowApp to avoid launching the TUI
    with patch("agentsloop.cli.WorkflowApp") as mock_app:
        runner = CliRunner()
        result = runner.invoke(cli, ["--ssh-key", str(ssh_key)])
        assert result.exit_code == 0
        mock_app.assert_called_once()
        context = mock_app.call_args[0][1]
        assert context.ssh_key_path == ssh_key


def test_textual_app_launch_screen_contains_model_select(tmp_path: Path) -> None:
    """Instantiate the Textual shell and verify the model selector."""

    async def run_app() -> None:
        context = ProjectContext(
            repo_root=tmp_path,
            base_branch="main",
            ssh_key_path=tmp_path / "id_rsa",
        )
        app = WorkflowApp(tmp_path, context)

        async with app.run_test() as pilot:
            app.push_screen(LaunchScreen(app.store, context))
            await pilot.pause()
            provider_select = app.screen.query_one("#provider", Select)
            cto_model_input = app.screen.query_one("#cto_model_input", Input)
            developer_model_input = app.screen.query_one("#developer_model_input", Input)
            cto_model_select = app.screen.query_one("#cto_model_select", Select)
            developer_model_select = app.screen.query_one("#developer_model_select", Select)
            cto_reasoning_select = app.screen.query_one("#cto_reasoning_effort", Select)
            cto_reasoning_label = app.screen.query_one("#cto_reasoning_label", Label)
            developer_reasoning_select = app.screen.query_one("#developer_reasoning_effort", Select)
            developer_reasoning_label = app.screen.query_one("#developer_reasoning_label", Label)
            base_branch_select = app.screen.query_one("#base_branch", Select)
            validation_command = app.screen.query_one("#validation_command", Input)
            _assert_reasoning_controls(
                provider_select=provider_select,
                cto_model_select=cto_model_select,
                developer_model_select=developer_model_select,
                cto_reasoning_select=cto_reasoning_select,
                cto_reasoning_label=cto_reasoning_label,
                developer_reasoning_select=developer_reasoning_select,
                developer_reasoning_label=developer_reasoning_label,
                provider=DEFAULT_PROVIDER,
                model=DEFAULT_GEMINI_MODEL,
                hidden=True,
            )
            provider_select.value = "copilot"
            await pilot.pause()
            _assert_reasoning_controls(
                provider_select=provider_select,
                cto_model_select=cto_model_select,
                developer_model_select=developer_model_select,
                cto_reasoning_select=cto_reasoning_select,
                cto_reasoning_label=cto_reasoning_label,
                developer_reasoning_select=developer_reasoning_select,
                developer_reasoning_label=developer_reasoning_label,
                provider="copilot",
                model=DEFAULT_COPILOT_MODEL,
                hidden=False,
            )
            provider_select.value = "codex"
            await pilot.pause()
            _assert_reasoning_controls(
                provider_select=provider_select,
                cto_model_select=cto_model_select,
                developer_model_select=developer_model_select,
                cto_reasoning_select=cto_reasoning_select,
                cto_reasoning_label=cto_reasoning_label,
                developer_reasoning_select=developer_reasoning_select,
                developer_reasoning_label=developer_reasoning_label,
                provider="codex",
                model=DEFAULT_CODEX_MODEL,
                hidden=False,
            )
            assert base_branch_select.value == "main"
            assert validation_command.value == DEFAULT_VALIDATION_COMMAND
            app.exit()

    asyncio.run(run_app())


def _assert_reasoning_controls(
    *,
    provider_select: Select[str],
    cto_model_select: Select[str],
    developer_model_select: Select[str],
    cto_reasoning_select: Select[str],
    cto_reasoning_label: Label,
    developer_reasoning_select: Select[str],
    developer_reasoning_label: Label,
    provider: str,
    model: str,
    hidden: bool,
) -> None:
    """Assert provider-specific model and reasoning UI state."""
    assert provider_select.value == provider
    assert cto_model_select.value == model
    assert developer_model_select.value == model
    assert cto_reasoning_select.value == DEFAULT_CODEX_REASONING_EFFORT
    assert developer_reasoning_select.value == DEFAULT_CODEX_REASONING_EFFORT
    assert cto_reasoning_select.disabled is hidden
    assert developer_reasoning_select.disabled is hidden
    assert cto_reasoning_label.has_class("hidden") is hidden
    assert cto_reasoning_select.has_class("hidden") is hidden
    assert developer_reasoning_label.has_class("hidden") is hidden
    assert developer_reasoning_select.has_class("hidden") is hidden


def test_textual_app_ssh_key_selection_flow(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Verify the SSH key selection screen correctly updates the context."""

    async def run_app() -> None:
        store = ProjectConfigStore(tmp_path, tmp_path / "config")
        context = ProjectContext(
            repo_root=tmp_path,
            base_branch="main",
            ssh_key_path=tmp_path / "old_key",
            config_store=store,
            configured=True,
        )
        app = WorkflowApp(tmp_path / "runs", context)
        new_key = tmp_path / "new_key"
        new_key.touch()
        original_push_screen = app.push_screen

        worker_task: asyncio.Task[None] | None = None

        def fake_run_worker(coro: Coroutine[Any, Any, None], **_kwargs: object) -> None:
            nonlocal worker_task
            worker_task = asyncio.create_task(coro)

        with (
            patch("agentsloop.tui.app.WarningScreen"),
            patch("agentsloop.tui.screens.verify_git_write_access"),
            patch("asyncio.to_thread") as mock_to_thread,
            patch.object(WorkflowApp, "push_screen") as mock_push,
        ):
            mock_to_thread.return_value = None

            def side_effect(screen: object, **_kwargs: object) -> object:
                if not isinstance(screen, (Screen, str)):
                    return None
                return original_push_screen(screen)

            mock_push.side_effect = side_effect

            async with app.run_test() as pilot:
                # Manually push the SSH selection screen
                app.push_screen(SSHKeySelectionScreen(app.store, context))
                await pilot.pause()

                assert isinstance(app.screen, SSHKeySelectionScreen)
                # Mock run_worker on the screen instance
                monkeypatch.setattr(app.screen, "run_worker", fake_run_worker)

                custom_input = app.screen.query_one("#ssh_key_custom", Input)
                custom_input.value = str(new_key)

                app.screen.test_and_save()

                # Wait for the worker task if it exists
                if worker_task:
                    await asyncio.wait_for(worker_task, timeout=2.0)
                await pilot.pause()

                assert context.ssh_key_path == new_key
                # Also verify it saved to store since configured=True
                loaded = store.load()
                assert loaded is not None
                assert loaded.ssh_key_path == new_key
                app.exit()

    asyncio.run(run_app())


def test_textual_app_collects_first_run_validation_command(tmp_path: Path) -> None:
    """Show setup before home when a repository has no saved config."""

    async def run_app() -> None:
        store = ProjectConfigStore(tmp_path, tmp_path / "config")
        context = ProjectContext(
            repo_root=tmp_path,
            base_branch="main",
            ssh_key_path=tmp_path / "id_rsa",
            config_store=store,
            configured=False,
        )
        app = WorkflowApp(tmp_path / "runs", context)
        original_push_screen = app.push_screen
        with (
            patch("agentsloop.tui.screens.verify_git_write_access"),
            patch.object(WorkflowApp, "push_screen") as mock_push,
        ):

            def side_effect(screen: object, **_kwargs: object) -> object:
                if not isinstance(screen, (Screen, str)):
                    return None  # Skip the mock screen
                return original_push_screen(screen)

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
                app.exit()

    asyncio.run(run_app())


def test_workflow_screen_copies_developer_branch(tmp_path: Path) -> None:
    """Copy the developer branch from the workflow screen."""
    state = run_state(tmp_path)
    state.developer_branch = "agent/dev/build-the-thing-run-1"
    store = RunStore(tmp_path)
    store.prepare(state)
    copied: list[str] = []

    class TestWorkflowScreen(WorkflowScreen):
        def _copy_text(self, content: str, notice: str) -> None:
            copied.append(content)
            assert notice == "Developer branch copied"

    screen = TestWorkflowScreen(store, state.task_id)
    screen.action_copy_branch()
    assert copied == ["agent/dev/build-the-thing-run-1"]


def run_state(tmp_path: Path) -> WorkflowState:
    """Build a state for persistence tests."""
    from agentsloop.orchestrator import create_state

    return create_state(
        human_request_md="Build the thing",
        config=config(),
        task_id="run-1",
        runs_dir=tmp_path,
    )

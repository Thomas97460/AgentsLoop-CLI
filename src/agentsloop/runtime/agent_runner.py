"""Provider-independent runner for one agent execution."""

from __future__ import annotations

import shutil
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from agentsloop.domain.models import (
    ProviderModel,
    ProviderName,
    ProviderResult,
    ReasoningEffort,
    utc_now,
)
from agentsloop.runtime.git_runtime import clone_for_agent
from agentsloop.runtime.providers import run_provider


class AgentRunSpec(BaseModel):
    """Provider-independent agent execution request."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    role: str
    provider: ProviderName
    model: ProviderModel
    reasoning_effort: ReasoningEffort | None = None
    prompt_md: str
    repo_url: str
    base_branch: str
    working_branch: str
    repo_path: Path
    stdout_path: Path
    stderr_path: Path
    env: dict[str, str]
    iteration: int


def run_agent(spec: AgentRunSpec, task_id: str) -> ProviderResult:
    """Clone the configured repository, run one provider, and normalize output."""
    del task_id
    started_at = utc_now()
    repo_path = spec.repo_path
    if repo_path.exists():
        shutil.rmtree(repo_path)
    clone_for_agent(
        repo_url=spec.repo_url,
        base_branch=spec.base_branch,
        working_branch=spec.working_branch,
        repo_path=repo_path,
        env=spec.env,
    )
    completed = run_provider(
        provider=spec.provider,
        model=spec.model,
        reasoning_effort=spec.reasoning_effort,
        prompt_md=spec.prompt_md,
        cwd=repo_path,
        env=spec.env,
        stdout_path=spec.stdout_path,
        stderr_path=spec.stderr_path,
    )
    report = completed.report_md or spec.stdout_path.read_text(encoding="utf-8").strip()
    stderr_text = spec.stderr_path.read_text(encoding="utf-8").strip()
    if completed.returncode != 0 and not report and stderr_text:
        report = stderr_text
    return ProviderResult(
        provider=spec.provider,
        role=spec.role,
        model=spec.model,
        reasoning_effort=spec.reasoning_effort,
        status="success" if completed.returncode == 0 and report else "error",
        report_md=report,
        stdout_path=str(spec.stdout_path),
        stderr_path=str(spec.stderr_path),
        exit_code=completed.returncode,
        started_at=started_at,
        finished_at=utc_now(),
        repo_path=str(repo_path),
        branch=spec.working_branch or spec.base_branch,
    )

"""Detached workflow worker entrypoint."""

from __future__ import annotations

import argparse
from pathlib import Path

from agentsloop.domain.models import ContinuationContext, RuntimeConfig
from agentsloop.orchestrator import run_workflow
from agentsloop.runtime.workflow_launcher import workflow_payload_from_file


def main() -> None:
    """Run one workflow from a persisted request file."""
    parser = argparse.ArgumentParser(description="Run one detached agentic workflow.")
    parser.add_argument("--request-file", required=True, type=Path)
    args = parser.parse_args()
    payload = workflow_payload_from_file(args.request_file)
    continuation = payload.get("continuation")
    run_workflow(
        human_request_md=str(payload["human_request_md"]),
        config=RuntimeConfig.model_validate(payload["config"]),
        task_id=str(payload["task_id"]),
        runs_dir=Path(str(payload["runs_dir"])),
        continued_from_task_id=(
            str(continuation["source_task_id"]) if isinstance(continuation, dict) else None
        ),
        continuation_context=(
            ContinuationContext.model_validate(continuation["context"])
            if isinstance(continuation, dict) and isinstance(continuation.get("context"), dict)
            else None
        ),
        developer_branch=(
            str(continuation["developer_branch"]) if isinstance(continuation, dict) else ""
        ),
    )


if __name__ == "__main__":
    main()

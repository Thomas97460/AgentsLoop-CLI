"""Detached workflow worker entrypoint."""

from __future__ import annotations

import argparse
from pathlib import Path

from agentic_workflows.domain.models import RuntimeConfig
from agentic_workflows.orchestrator import run_workflow
from agentic_workflows.runtime.workflow_launcher import workflow_payload_from_file


def main() -> None:
    """Run one workflow from a persisted request file."""
    parser = argparse.ArgumentParser(description="Run one detached agentic workflow.")
    parser.add_argument("--request-file", required=True, type=Path)
    args = parser.parse_args()
    payload = workflow_payload_from_file(args.request_file)
    run_workflow(
        human_request_md=str(payload["human_request_md"]),
        config=RuntimeConfig.model_validate(payload["config"]),
        task_id=str(payload["task_id"]),
        runs_dir=Path(str(payload["runs_dir"])),
    )


if __name__ == "__main__":
    main()

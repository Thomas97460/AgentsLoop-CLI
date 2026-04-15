# Agentic Workflows

Textual TUI for launching, following, and reviewing the CTO -> Developer -> CI agentic loop.

```bash
uv run --project agents agents
uv run --project agents agents --runs-root ~/algosia-agent-workflows
```

Runs are stored outside the repository by default:

```text
~/algosia-agent-workflows/<run-id>/
```

Each workflow keeps its live events, final state, summary, node reports, provider logs, structured
results, and per-node repository clones under that run directory.

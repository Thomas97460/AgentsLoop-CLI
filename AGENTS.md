# AgentsLoop CLI Agent Instructions

AgentsLoop CLI is a Python CLI/TUI for orchestrating agent loops. The first supported
provider is Gemini CLI; the runtime should remain structured so future providers can be
added without rewriting the user-facing workflow.

## Core Product Rules

- Keep the CLI installable and usable without Nix.
- Nix is only an optional development shell.
- The current workflow is a three-node loop: CTO, Developer, Validation / Tests.
- The validation node must stay configurable per repository.
- Gemini is the only active provider for now. Keep provider-specific behavior behind
  `agentsloop.runtime.providers`.
- Prompt changes belong in `src/agentsloop/prompts`.
- TUI changes should preserve clear keyboard navigation, readable labels, and compact
  screens that avoid unnecessary empty space.
- The TUI must remain detached from the backend. It should only observe files (using
  `RunStore`) and launch workflows as detached processes (using `spawn_workflow_process`
  with `start_new_session=True`). Workflows must continue even if the TUI is closed.

## No Backward Compatibility By Default

- Do not preserve old APIs, aliases, fallbacks, file paths, role names, commands, or
  behavior unless the task explicitly asks for compatibility.
- When implementing a change, remove obsolete code paths instead of keeping legacy support
  "just in case".
- If compatibility is explicitly required, document the supported compatibility window in
  the changed code or docs.

## Setup

Use `uv` as the source of truth for Python environments and dependency management:

```bash
uv sync --dev
```

Optional Nix shell:

```bash
nix develop
```

## Local Checks

Run these before opening a pull request:

```bash
uv run ruff format .
uv run ruff check .
uv run mypy src tests
env PYTHONPATH=src uv run pytest
uv build
```

CI runs the same lightweight checks on GitHub Actions.

## Code Style

- Use Python 3.12+.
- Use Ruff for formatting and linting.
- Use Mypy for type checking.
- Keep public runtime code typed.
- Prefer standard library and existing local helpers before adding dependencies.
- Do not add `# noqa` in `src/` unless there is a concrete technical reason and the reason
  is documented in the change.
- Functions should normally stay under 30 lines, excluding docstrings and comments.
- Files should stay under 1000 lines.
- Docstrings in `src/` should use Google style.
- `PLR0913` is ignored globally because orchestration code often has explicit dependency
  boundaries. Do not use that as an excuse for unclear APIs.

## Tests

Add or update tests when behavior changes. Prefer focused tests around:

- provider command construction
- workflow state persistence
- prompt rendering and parsing
- TUI launch behavior that can be exercised without a real provider
- Git/SSH environment behavior
- validation command behavior

Do not require live Gemini calls or network access in unit tests.

Tests may be more pragmatic than runtime code; the project allows common test patterns such
as magic values and local imports in tests.

## Dependency Policy

Runtime dependencies should be justified by direct user value. Development dependencies
belong in the `dev` dependency group in `pyproject.toml`.

After changing dependencies:

```bash
uv lock
uv sync --dev
```

Commit the updated `uv.lock`.

## Release Flow

Releases are tag based:

```bash
git tag vX.Y.Z
git push origin vX.Y.Z
```

The release workflow builds distributions and attaches them to the GitHub release. PyPI
publishing is opt-in through the `PUBLISH_TO_PYPI` repository variable and PyPI trusted
publishing.

## Pull Request Checklist

- The change is scoped to the stated problem.
- README or AGENTS.md is updated when installation, usage, workflow, or agent guidance
  changes.
- `uv.lock` is updated when dependencies change.
- Local checks pass.
- No local-only files are committed, such as `.venv`, `.direnv`, `.env`, build output, or
  run artifacts.

# AgentsLoop CLI

AgentsLoop CLI launches and monitors an agent workflow around Gemini CLI:

```text
CTO controller -> Developer agent -> Validation / tests -> CTO controller
```

The project currently supports Gemini CLI only. The runtime is structured so other agent providers can be added later without changing the user-facing workflow.

## Install

AgentsLoop CLI requires Python 3.12 or newer and a working `gemini` command. Gemini CLI requires Node.js 20 or newer when installed with npm.

Install Gemini CLI first and authenticate it:

```bash
npm install -g @google/gemini-cli
gemini
```

Install AgentsLoop CLI from GitHub:

```bash
uv tool install git+https://github.com/Thomas97460/AgentsLoop-CLI.git
```

Upgrade later with:

```bash
uv tool upgrade agentsloop-cli
```

After the first packaged release, the same CLI can be installed from a GitHub release wheel:

```bash
uv tool install https://github.com/Thomas97460/AgentsLoop-CLI/releases/download/v0.1.0/agentsloop_cli-0.1.0-py3-none-any.whl
```

If PyPI publishing is enabled for the repository:

```bash
uv tool install agentsloop-cli
```

## Use

Start the TUI from inside the Git repository you want AgentsLoop to work on:

```bash
agentsloop
```

AgentsLoop refuses to start outside a Git repository. On first launch in a repository, it
asks for the validation command and stores that local setting under `~/.config/agentsloop`.

Use a custom runs directory:

```bash
agentsloop --runs-root ~/agentsloop-runs
```

Inside the TUI:

- press `n` to create a workflow
- write the request for the agents
- choose a Gemini model
- confirm the current repository branch
- set the validation command for that repository
- press `Run`

Runs are stored outside the source repository by default:

```text
~/agentsloop-runs/<run-id>/
```

Each run stores state, events, node reports, provider logs, structured results, and isolated repository clones.

The validation node runs a configurable shell command in a fresh clone of the developer branch. The default is:

```bash
uv run pytest
```

Change it in the launch screen for non-Python repositories, for example `npm test`, `pnpm test`, `cargo test`, or `go test ./...`.

## SSH Settings

AgentsLoop clones and pushes through Git. If the current repository needs a specific SSH key, copy the example file and edit it:

```bash
cp .env.example .env
```

Supported variables:

```bash
AGENTS_GIT_SSH_KEY_PATH=/home/your-user/.ssh/id_ed25519
AGENTS_GIT_SSH_STRICT_HOST_KEY_CHECKING=accept-new
AGENTS_GIT_SSH_KNOWN_HOSTS=/home/your-user/.ssh/known_hosts
```

Values in `.env` are loaded into the workflow process when `agentsloop` is run from that directory.

## Development

This repository uses `uv` for Python packaging and dependency management:

```bash
uv sync --dev
uv run ruff format .
uv run ruff check .
uv run mypy src tests
uv run pytest
uv build
```

Nix is optional for contributors who want a pinned development shell:

```bash
nix develop
```

Users do not need Nix to install or run AgentsLoop CLI.

## Release

Create a release by pushing a semver tag:

```bash
git tag v0.1.0
git push origin v0.1.0
```

The release workflow builds the wheel and source distribution, uploads them to the GitHub release, and can publish to PyPI when the repository variable `PUBLISH_TO_PYPI` is set to `true` and PyPI trusted publishing is configured.

## License

MIT. See [LICENSE](LICENSE).

<div align="center">
  <img src="assets/demo.gif" width="800" alt="AgentsLoop CLI Demo">
  <p><i>Watch AgentsLoop CLI in action</i></p>

[![CI](https://img.shields.io/github/actions/workflow/status/Thomas97460/AgentsLoop-CLI/ci.yml?branch=main&label=CI)](https://github.com/Thomas97460/AgentsLoop-CLI/actions/workflows/ci.yml)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Testing](https://img.shields.io/github/actions/workflow/status/Thomas97460/AgentsLoop-CLI/ci.yml?job=test&label=tests)](https://github.com/Thomas97460/AgentsLoop-CLI/actions/workflows/ci.yml)
[![Python Version](https://img.shields.io/badge/python-3.12%20%7C%203.13-blue)](https://www.python.org/downloads/)

**Autonomous orchestration for software engineering workflows.**

</div>

AgentsLoop CLI is an orchestrator for autonomous agent loops. It coordinates a three-node loop (CTO, Developer, and Validation) to automate software engineering tasks.

## 🔄 The Loop: How it Works

```mermaid
graph LR
    CTO["<b>CTO</b><br/>CLI Agent"]
    DEV["<b>Developer</b><br/>CLI Agent"]
    VAL["<b>Validation</b><br/>bash command"]

    CTO --> DEV
    DEV --> VAL
    VAL -.->|Feedback| CTO

    classDef agents fill:#e1f5fe,stroke:#01579b,stroke-width:2px,color:#01579b;
    classDef validation fill:#f9f9f9,stroke:#333,stroke-width:1px,color:#333;
    
    class CTO,DEV agents;
    class VAL validation;
```

## Key Features

- **Autonomous Loop**: CTO plans, Developer implements, and Validation tests.
- **Multi-Provider Support**: Seamlessly switch between Gemini, Codex, and Copilot.
- **No API Key Required**: Works with your existing provider subscriptions via their respective CLIs.
- **TUI Interface**: Terminal user interface to monitor workflows in real-time.
- **Git Integration**: Works directly within your repositories, creating isolated branches for safety.
- **Coming Soon**: Support for Claude Code.

## Installation

### With uv

```bash
uv tool install git+https://github.com/Thomas97460/AgentsLoop-CLI.git
```

### Without uv

```bash
curl -fsSL https://raw.githubusercontent.com/Thomas97460/AgentsLoop-CLI/main/install.sh | bash
```

### Prerequisites

- Python 3.12 or newer.
- At least one of `gemini`, `codex`, or `copilot` CLI installed and authenticated.

## Usage

```bash
cd ~/your_git_repository/ && agentsloop
```

## Contributing

We welcome contributions! Please check [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md) for development guidelines.

```bash
uv sync --dev
uv run pytest
```

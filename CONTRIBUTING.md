# Contributing to AgentsLoop CLI

Thank you for your interest in contributing to AgentsLoop CLI! We welcome contributions from everyone.

## Development Setup

This project uses `uv` for dependency management.

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/Thomas97460/AgentsLoop-CLI.git
    cd AgentsLoop-CLI
    ```

2.  **Sync dependencies**:
    ```bash
    uv sync --dev
    ```

## Development Workflow

### Code Style

We use **Ruff** for linting and formatting, and **Mypy** for type checking.

- **Format code**: `uv run ruff format .`
- **Lint code**: `uv run ruff check .`
- **Type check**: `uv run mypy src tests`

### Testing

Always add or update tests when changing behavior.

- **Run tests**: `uv run pytest`

### Architectural Guidelines

- Functions should generally stay under 30 lines.
- Files should stay under 1000 lines.
- Use Python 3.12+ features.
- Public runtime code must be typed.
- Follow Google style for docstrings.

## Submitting Changes

1.  **Create a branch**: Use a descriptive name like `feat/new-provider` or `fix/issue-123`.
2.  **Commit your changes**: Write clear, concise commit messages.
3.  **Run local checks**: Ensure all tests, linting, and type checks pass before submitting.
4.  **Open a Pull Request**: Provide a clear description of your changes and why they are needed.

## Releasing

This project uses Git tags to manage versions. We use `hatch-vcs` to automatically derive the version from the latest tag.

To release a new version:
1.  **Tag the commit**:
    ```bash
    git tag v0.1.0
    git push origin v0.1.0
    ```
2.  **GitHub Actions** will automatically:
    - Build the `.whl` and `.tar.gz` distributions.
    - Create a GitHub Release with the build artifacts.
    - Publish to PyPI (if configured).

Ensure your tag follows Semantic Versioning (e.g., `vX.Y.Z`).

## Security

Please do not report security vulnerabilities through public GitHub issues. See our [Security Policy](SECURITY.md) for more information.

## License

By contributing to AgentsLoop CLI, you agree that your contributions will be licensed under the project's [MIT License](LICENSE).

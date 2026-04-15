"""Per-repository AgentsLoop configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

import orjson
from pydantic import BaseModel, Field

from agentsloop.domain.models import DEFAULT_VALIDATION_COMMAND


class ProjectConfig(BaseModel):
    """Settings collected once for a repository."""

    validation_command: str = Field(default=DEFAULT_VALIDATION_COMMAND, min_length=1)
    ssh_key_path: Path


class ProjectConfigStore:
    """Persist local settings for one Git repository."""

    def __init__(self, repo_root: Path, config_home: Path | None = None) -> None:
        self.repo_root = repo_root.resolve()
        self.config_home = config_home or default_config_home()
        self.path = self.config_home / "projects" / f"{self._repo_key()}.json"

    def load(self) -> ProjectConfig | None:
        """Load saved project settings when they exist."""
        if not self.path.exists():
            return None
        return ProjectConfig.model_validate_json(self.path.read_text(encoding="utf-8"))

    def save(self, config: ProjectConfig) -> None:
        """Write project settings."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = config.model_dump(mode="json") | {"repo_root": str(self.repo_root)}
        self.path.write_bytes(orjson.dumps(payload, option=orjson.OPT_INDENT_2))

    def _repo_key(self) -> str:
        """Return a stable filesystem-safe key for the repository path."""
        return sha256(str(self.repo_root).encode()).hexdigest()[:16]


@dataclass(slots=True)
class ProjectContext:
    """Runtime context for the current repository."""

    repo_root: Path
    base_branch: str
    ssh_key_path: Path
    remote_url: str | None = None
    validation_command: str = DEFAULT_VALIDATION_COMMAND
    config_store: ProjectConfigStore | None = None
    configured: bool = True

    def save_config(self, validation_command: str, ssh_key_path: Path) -> None:
        """Persist and apply project settings."""
        self.validation_command = validation_command
        self.ssh_key_path = ssh_key_path
        self.configured = True
        if self.config_store is not None:
            self.config_store.save(
                ProjectConfig(validation_command=validation_command, ssh_key_path=ssh_key_path)
            )

    def save_validation_command(self, command: str) -> None:
        """Persist and apply the validation command."""
        self.save_config(command, self.ssh_key_path)


def default_config_home() -> Path:
    """Return the directory used for local AgentsLoop settings."""
    configured = os.environ.get("AGENTSLOOP_CONFIG_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path("~/.config/agentsloop").expanduser()

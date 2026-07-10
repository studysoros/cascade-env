"""Cascade runtime configuration."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_data_root() -> Path:
    """Locate scenarios/packs: prefer live repo checkout, else installed package data."""
    pkg = Path(__file__).resolve().parent
    # repo layout: src/cascade_env/config.py -> repo root (dev / editable)
    repo = pkg.parent.parent
    if (repo / "scenarios").is_dir() and (repo / "packs").is_dir():
        return repo
    installed = pkg / "_data"
    if (installed / "scenarios").is_dir():
        return installed
    return repo


class CascadeConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CASCADE_",
        env_file=".env",
        extra="ignore",
    )

    runtime: str = Field(
        default="local",
        description="Runtime backend: 'local' (in-process, no Docker) or 'compose' (Docker).",
    )
    data_root: Path | None = None
    work_root: Path | None = None
    max_parallel_episodes: int = 1
    provision_timeout_s: int = 180
    verify_timeout_s: int = 120
    teardown_timeout_s: int = 60
    max_steps: int = 50
    max_wall_time_s: float = 1200.0
    step_cost: float = 0.001
    dense_public_shaping: bool = False
    allow_network_egress: bool = False
    episode_ttl_s: int = 7200
    keep_failed_artifacts: int = 20
    show_hints: bool = False
    pack: str = "community"
    docker_bin: str = "docker"

    def resolved_data_root(self) -> Path:
        if self.data_root is not None:
            return Path(self.data_root)
        return _default_data_root()

    def resolved_work_root(self) -> Path:
        if self.work_root is not None:
            p = Path(self.work_root)
        else:
            p = Path.home() / ".cascade" / "episodes"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def scenarios_dir(self) -> Path:
        return self.resolved_data_root() / "scenarios"

    def packs_dir(self) -> Path:
        return self.resolved_data_root() / "packs"


def get_config(**overrides: object) -> CascadeConfig:
    cfg = CascadeConfig()
    if overrides:
        cfg = cfg.model_copy(update=overrides)
    return cfg

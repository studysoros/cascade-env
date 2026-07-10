"""Cascade runtime configuration."""

from __future__ import annotations

import os
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


def _split_path_list(raw: str) -> list[Path]:
    """Split CASCADE_* path lists on OS pathsep and (for convenience) commas."""
    if not raw or not raw.strip():
        return []
    parts: list[str] = []
    for chunk in raw.replace(",", os.pathsep).split(os.pathsep):
        chunk = chunk.strip().strip('"').strip("'")
        if chunk:
            parts.append(chunk)
    return [Path(p).expanduser() for p in parts]


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
    # Pathsep/comma-separated pack *directories* (each contains pack.yaml).
    # Used for sealed holdout packs outside the public repo tree.
    extra_packs: str = Field(
        default="",
        description="Extra pack dirs (os.pathsep or comma). Env: CASCADE_EXTRA_PACKS",
    )
    # Convenience: single sealed pack directory (alias of one entry in extra_packs).
    holdout_dir: Path | None = Field(
        default=None,
        description="Path to a sealed holdout pack dir. Env: CASCADE_HOLDOUT_DIR",
    )
    # HTTP rollout server (WP4 / PR11). Serving is opt-in via `cascade serve`.
    enable_http_server: bool = Field(
        default=False,
        description="Feature flag for HTTP rollout server. Env: CASCADE_ENABLE_HTTP_SERVER",
    )
    server_api_key: str = Field(
        default="",
        description="API key for rollout server auth. Env: CASCADE_SERVER_API_KEY",
    )
    server_host: str = Field(default="127.0.0.1", description="Default bind host for cascade serve")
    server_port: int = Field(default=8765, description="Default bind port for cascade serve")

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

    def extra_pack_dirs(self) -> list[Path]:
        """Resolved directories that each contain a pack.yaml (sealed holdouts, etc.)."""
        dirs = _split_path_list(self.extra_packs)
        if self.holdout_dir is not None:
            dirs.append(Path(self.holdout_dir).expanduser())
        # Dedupe while preserving order
        seen: set[str] = set()
        out: list[Path] = []
        for d in dirs:
            key = str(d.resolve()) if d.exists() else str(d)
            if key in seen:
                continue
            seen.add(key)
            out.append(d)
        return out


def get_config(**overrides: object) -> CascadeConfig:
    cfg = CascadeConfig()
    if overrides:
        cfg = cfg.model_copy(update=overrides)
    return cfg

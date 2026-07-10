"""Runtime backend protocol."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from cascade_env.types import ServiceStatus, ToolResult


@dataclass
class EpisodeHandle:
    episode_id: str
    workspace: Path
    project_name: str
    api_base: str
    db_url: str
    meta: dict[str, Any] = field(default_factory=dict)


class RuntimeBackend(Protocol):
    name: str

    def provision(self, episode_id: str, workspace: Path) -> EpisodeHandle: ...

    def wait_healthy(self, handle: EpisodeHandle, timeout_s: float) -> bool: ...

    def service_status(self, handle: EpisodeHandle) -> list[ServiceStatus]: ...

    def restart_services(self, handle: EpisodeHandle, services: list[str]) -> ToolResult: ...

    def exec_tool(self, handle: EpisodeHandle, tool: str, args: dict[str, Any]) -> ToolResult: ...

    def run_sql(self, handle: EpisodeHandle, sql: str, *, writes: bool = False) -> ToolResult: ...

    def teardown(self, handle: EpisodeHandle) -> None: ...

    def apply_pending_sql(self, handle: EpisodeHandle) -> None: ...

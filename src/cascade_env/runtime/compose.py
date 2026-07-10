"""Docker Compose runtime backend (requires Docker daemon)."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any

from cascade_env.runtime.base import EpisodeHandle
from cascade_env.tools.files import FilesTool
from cascade_env.tools.shell import ShellTool
from cascade_env.types import ErrorCode, ServiceStatus, ToolResult


class ComposeRuntimeBackend:
    """
    Per-episode `docker compose -p cascade_{id}` projects.
    Episode compose must not publish host ports; tools use `docker compose exec`.
    """

    name = "compose"

    def __init__(self) -> None:
        self._docker = os.environ.get("CASCADE_DOCKER_BIN", "docker")

    def provision(self, episode_id: str, workspace: Path) -> EpisodeHandle:
        compose_file = self._compose_file(workspace)
        project = f"cascade_{episode_id}"
        self._run(
            [
                self._docker,
                "compose",
                "-p",
                project,
                "-f",
                str(compose_file),
                "up",
                "-d",
                "--wait",
            ],
            cwd=workspace,
            timeout=180,
        )
        # Discover api container IP for host-side HTTP (no host ports)
        api_base = self._service_url(project, compose_file, workspace, "api", 8000)
        db_url = "postgresql://shop:shop@postgres:5432/shop"
        return EpisodeHandle(
            episode_id=episode_id,
            workspace=workspace,
            project_name=project,
            api_base=api_base,
            db_url=db_url,
            meta={"compose_file": str(compose_file)},
        )

    def wait_healthy(self, handle: EpisodeHandle, timeout_s: float) -> bool:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            st = self.service_status(handle)
            by = {s.name: s for s in st}
            if by.get("api") and by["api"].healthy:
                return True
            time.sleep(1)
        return False

    def service_status(self, handle: EpisodeHandle) -> list[ServiceStatus]:
        compose_file = handle.meta.get("compose_file")
        r = self._run(
            [
                self._docker,
                "compose",
                "-p",
                handle.project_name,
                "-f",
                str(compose_file),
                "ps",
                "--format",
                "json",
            ],
            cwd=handle.workspace,
            check=False,
        )
        # Fallback simple parse
        out: list[ServiceStatus] = []
        for name in ("api", "worker", "postgres", "redis"):
            out.append(ServiceStatus(name=name, status="unknown", healthy=None))
        if r.returncode == 0 and r.stdout:
            # best-effort
            for name in ("api", "worker", "postgres", "redis"):
                healthy = name in r.stdout and "running" in r.stdout.lower()
                out = [
                    ServiceStatus(
                        name=s.name,
                        status="running" if s.name in r.stdout else s.status,
                        healthy=healthy if s.name == name else s.healthy,
                    )
                    for s in out
                ]
        return out

    def restart_services(self, handle: EpisodeHandle, services: list[str]) -> ToolResult:
        compose_file = handle.meta.get("compose_file")
        t0 = time.time()
        r = self._run(
            [
                self._docker,
                "compose",
                "-p",
                handle.project_name,
                "-f",
                str(compose_file),
                "restart",
                *services,
            ],
            cwd=handle.workspace,
            check=False,
        )
        return ToolResult(
            ok=r.returncode == 0,
            tool="services.restart",
            exit_code=r.returncode,
            stdout=r.stdout,
            stderr=r.stderr,
            data={"restarted": services},
            duration_ms=int((time.time() - t0) * 1000),
        )

    def exec_tool(self, handle: EpisodeHandle, tool: str, args: dict[str, Any]) -> ToolResult:
        if tool.startswith("files."):
            return FilesTool(handle.workspace).execute(tool, args)
        if tool == "shell.exec":
            return ShellTool(handle.workspace).execute(args)
        if tool in ("services.restart", "services.ps"):
            if tool == "services.ps":
                return ToolResult.success(
                    "services.ps",
                    data={"services": [s.model_dump() for s in self.service_status(handle)]},
                )
            services = args.get("services") or args.get("service") or []
            if isinstance(services, str):
                services = [services]
            return self.restart_services(handle, list(services))
        if tool == "logs.tail":
            return self._logs(handle, args)
        if tool == "http.request":
            # exec curl-less via python in api container is complex; use host URL if set
            from cascade_env.runtime.local import LocalRuntimeBackend

            # reuse local http against api_base (compose may set host-accessible URL in debug)
            return LocalRuntimeBackend()._http(handle, args)  # noqa: SLF001
        if tool in ("db.query", "db.exec"):
            return self.run_sql(handle, args.get("sql", ""), writes=(tool == "db.exec"))
        if tool == "tests.run":
            return ToolResult.failure(
                "tests.run",
                ErrorCode.INTERNAL,
                stderr="tests.run on compose: run from host against published debug profile or use local runtime",
            )
        return ToolResult.failure(tool, ErrorCode.NOT_FOUND, stderr=f"unknown tool {tool}")

    def run_sql(self, handle: EpisodeHandle, sql: str, *, writes: bool = False) -> ToolResult:
        compose_file = handle.meta.get("compose_file")
        t0 = time.time()
        r = self._run(
            [
                self._docker,
                "compose",
                "-p",
                handle.project_name,
                "-f",
                str(compose_file),
                "exec",
                "-T",
                "postgres",
                "psql",
                "-U",
                "shop",
                "-d",
                "shop",
                "-c",
                sql,
            ],
            cwd=handle.workspace,
            check=False,
        )
        return ToolResult(
            ok=r.returncode == 0,
            tool="db.exec" if writes else "db.query",
            exit_code=r.returncode,
            stdout=r.stdout,
            stderr=r.stderr,
            duration_ms=int((time.time() - t0) * 1000),
        )

    def apply_pending_sql(self, handle: EpisodeHandle) -> None:
        pending = handle.workspace / "mutations" / "pending_sql.sql"
        if pending.exists():
            sql = pending.read_text(encoding="utf-8")
            if sql.strip():
                self.run_sql(handle, sql, writes=True)

    def teardown(self, handle: EpisodeHandle) -> None:
        compose_file = handle.meta.get("compose_file")
        self._run(
            [
                self._docker,
                "compose",
                "-p",
                handle.project_name,
                "-f",
                str(compose_file),
                "down",
                "-v",
                "--remove-orphans",
            ],
            cwd=handle.workspace,
            check=False,
            timeout=60,
        )

    def _compose_file(self, workspace: Path) -> Path:
        # Prefer scenario compose next to template copy instructions
        from cascade_env.config import get_config

        scenario_compose = (
            get_config().scenarios_dir() / "shopstack" / "docker-compose.yml"
        )
        if scenario_compose.exists():
            return scenario_compose
        raise FileNotFoundError("docker-compose.yml for shopstack not found")

    def _service_url(
        self,
        project: str,
        compose_file: Path,
        workspace: Path,
        service: str,
        port: int,
    ) -> str:
        # Debug profile may publish ports; default internal-only uses localhost bridge IP
        # For Desktop without published ports, users should use runtime=local.
        return f"http://127.0.0.1:{port}"

    def _logs(self, handle: EpisodeHandle, args: dict[str, Any]) -> ToolResult:
        compose_file = handle.meta.get("compose_file")
        service = args.get("service", "api")
        lines = str(args.get("lines", 100))
        r = self._run(
            [
                self._docker,
                "compose",
                "-p",
                handle.project_name,
                "-f",
                str(compose_file),
                "logs",
                "--no-color",
                "--tail",
                lines,
                service,
            ],
            cwd=handle.workspace,
            check=False,
        )
        return ToolResult(
            ok=r.returncode == 0,
            tool="logs.tail",
            exit_code=r.returncode,
            stdout=r.stdout,
            stderr=r.stderr,
        )

    def _run(
        self,
        cmd: list[str],
        *,
        cwd: Path,
        check: bool = True,
        timeout: float = 120,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=check,
        )

"""Docker Compose runtime backend (requires Docker daemon).

Episode traffic stays on the internal compose network (no fixed host ports).
Host control-plane tools reach services via ``docker compose exec``.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from cascade_env.config import get_config
from cascade_env.runtime.base import EpisodeHandle
from cascade_env.tools.files import FilesTool
from cascade_env.tools.shell import ShellTool
from cascade_env.types import ErrorCode, ServiceStatus, ToolResult
from cascade_env.version import __version__

_SERVICE_NAMES = ("api", "worker", "postgres", "redis")


class ComposeRuntimeBackend:
    """
    Per-episode ``docker compose -p cascade_{id}`` projects.

    - Workspace is bind-mounted from the host episode directory.
    - No fixed host ports; ``http.request`` / verifiers use ``docker compose exec``.
    - Resources labeled ``com.cascade.*`` for GC.
    """

    name = "compose"

    def __init__(self, *, debug_ports: bool = False) -> None:
        cfg = get_config()
        self._docker = os.environ.get("CASCADE_DOCKER_BIN", cfg.docker_bin or "docker")
        self._debug_ports = debug_ports or os.environ.get("CASCADE_COMPOSE_DEBUG", "").lower() in (
            "1",
            "true",
            "yes",
        )
        self._scenario_dir = cfg.scenarios_dir() / "shopstack"
        self._pins = self._load_image_pins()

    # ------------------------------------------------------------------ lifecycle

    def provision(self, episode_id: str, workspace: Path) -> EpisodeHandle:
        if not self.daemon_ok():
            raise RuntimeError(
                "Docker daemon is not running. Start Docker Desktop / dockerd, "
                "or use --runtime local."
            )
        compose_file = self._compose_file()
        if not compose_file.exists():
            raise FileNotFoundError(f"compose file missing: {compose_file}")

        project = f"cascade_{episode_id}"
        if self._debug_ports:
            self._assert_debug_safe()

        workspace = workspace.resolve()
        self._ensure_runtime_helpers(workspace)

        env = self._compose_env(episode_id, workspace)
        files = [str(compose_file)]
        if self._debug_ports:
            debug = self._scenario_dir / "docker-compose.debug.yml"
            if debug.exists():
                files.append(str(debug))

        # Build + start with health wait (Compose v2 --wait).
        up_cmd = self._compose_cmd(project, files, "up", "-d", "--build", "--wait", "--remove-orphans")
        r = self._run(up_cmd, cwd=self._scenario_dir, env=env, check=False, timeout=300)
        if r.returncode != 0:
            # Best-effort cleanup so failed provisions do not leak projects.
            down_cmd = self._compose_cmd(project, files, "down", "-v", "--remove-orphans")
            self._run(down_cmd, cwd=self._scenario_dir, env=env, check=False, timeout=90)
            raise RuntimeError(
                "docker compose up failed:\n"
                f"stdout:\n{r.stdout[-4000:]}\n"
                f"stderr:\n{r.stderr[-4000:]}"
            )

        api_base = "http://127.0.0.1:18000" if self._debug_ports else "http://api:8000"
        api_key = _read_api_key(workspace)
        handle = EpisodeHandle(
            episode_id=episode_id,
            workspace=workspace,
            project_name=project,
            api_base=api_base,
            db_url="postgresql+psycopg://shop:shop@postgres:5432/shop",
            meta={
                "compose_file": str(compose_file),
                "compose_files": files,
                "http_via": "host" if self._debug_ports else "docker_exec",
                "scenario_dir": str(self._scenario_dir),
                "env": {
                    "SHOPSTACK_API_KEY": api_key,
                    "DATABASE_URL": "postgresql+psycopg://shop:shop@postgres:5432/shop",
                    "REDIS_URL": "redis://redis:6379/0",
                },
                "compose_env": {
                    k: env[k]
                    for k in (
                        "CASCADE_WORKSPACE",
                        "CASCADE_EPISODE_ID",
                        "CASCADE_CREATED_AT",
                        "CASCADE_VERSION",
                        "SHOPSTACK_API_KEY",
                        "CASCADE_POSTGRES_IMAGE",
                        "CASCADE_REDIS_IMAGE",
                        "CASCADE_API_IMAGE",
                        "CASCADE_WORKER_IMAGE",
                    )
                    if k in env
                },
            },
        )
        return handle

    def wait_healthy(self, handle: EpisodeHandle, timeout_s: float) -> bool:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if self._ready_via_exec(handle):
                return True
            # Fail fast if containers exited
            statuses = self.service_status(handle)
            by = {s.name: s for s in statuses}
            api = by.get("api")
            if api and api.status in ("exited", "dead"):
                return False
            time.sleep(1.0)
        return False

    def service_status(self, handle: EpisodeHandle) -> list[ServiceStatus]:
        r = self._compose_run(handle, ["ps", "--format", "json"], check=False, timeout=30)
        by_name: dict[str, ServiceStatus] = {
            name: ServiceStatus(name=name, status="unknown", healthy=None)
            for name in _SERVICE_NAMES
        }
        if r.returncode != 0 or not (r.stdout or "").strip():
            return list(by_name.values())

        for obj in _parse_compose_ps_json(r.stdout):
            service = str(obj.get("Service") or "").strip()
            if service not in by_name:
                raw_name = str(obj.get("Name") or obj.get("name") or "")
                for sn in _SERVICE_NAMES:
                    if raw_name == sn or re.search(rf"(?:^|[-_]){re.escape(sn)}(?:[-_]\d+)?$", raw_name):
                        service = sn
                        break
            if service not in by_name:
                continue
            state = str(obj.get("State") or obj.get("Status") or "unknown").lower()
            health = obj.get("Health") or obj.get("health")
            running = "running" in state or state == "up" or state.startswith("up")
            if health:
                healthy = str(health).lower() in ("healthy", "running")
            else:
                healthy = running
            status = "running" if running else (state.split()[0] if state else "unknown")
            by_name[service] = ServiceStatus(name=service, status=status, healthy=healthy)
        return list(by_name.values())

    def restart_services(self, handle: EpisodeHandle, services: list[str]) -> ToolResult:
        t0 = time.time()
        allowed = [s for s in services if s in ("api", "worker", "postgres", "redis")]
        if not allowed:
            return ToolResult.failure(
                "services.restart",
                ErrorCode.SERVICE_UNKNOWN,
                stderr=f"unknown services: {services}",
            )
        r = self._compose_run(handle, ["restart", *allowed], check=False, timeout=120)
        if "api" in allowed:
            self.wait_healthy(handle, timeout_s=45)
        return ToolResult(
            ok=r.returncode == 0,
            tool="services.restart",
            exit_code=r.returncode,
            stdout=r.stdout,
            stderr=r.stderr,
            data={"restarted": allowed},
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
            return self._http(handle, args)
        if tool in ("db.query", "db.exec"):
            return self.run_sql(handle, args.get("sql", ""), writes=(tool == "db.exec"))
        if tool == "tests.run":
            return self._tests(handle, args)
        return ToolResult.failure(tool, ErrorCode.NOT_FOUND, stderr=f"unknown tool {tool}")

    def run_sql(self, handle: EpisodeHandle, sql: str, *, writes: bool = False) -> ToolResult:
        t0 = time.time()
        tool = "db.exec" if writes else "db.query"
        if not sql or not str(sql).strip():
            return ToolResult.failure(tool, ErrorCode.ARG_DENIED, stderr="empty sql")

        helper = handle.workspace / ".cascade_rt" / "sql_once.py"
        self._ensure_runtime_helpers(handle.workspace)
        req = {
            "sql": str(sql),
            "writes": bool(writes),
            "database_url": os.environ.get(
                "DATABASE_URL",
                "postgresql+psycopg://shop:shop@postgres:5432/shop",
            ),
        }
        # Always use in-container DATABASE_URL
        req["database_url"] = "postgresql+psycopg://shop:shop@postgres:5432/shop"
        req_path = handle.workspace / ".cascade_rt" / "sql_req.json"
        req_path.write_text(json.dumps(req), encoding="utf-8")

        r = self._compose_run(
            handle,
            [
                "exec",
                "-T",
                "api",
                "python",
                "/workspace/.cascade_rt/sql_once.py",
                "/workspace/.cascade_rt/sql_req.json",
            ],
            check=False,
            timeout=60,
        )
        ms = int((time.time() - t0) * 1000)
        if r.returncode != 0:
            return ToolResult.failure(
                tool,
                ErrorCode.DB_ERROR,
                stderr=(r.stderr or r.stdout or "sql failed")[-2000:],
                duration_ms=ms,
            )
        try:
            data = json.loads((r.stdout or "").strip().splitlines()[-1])
        except Exception as exc:  # noqa: BLE001
            return ToolResult.failure(
                tool,
                ErrorCode.DB_ERROR,
                stderr=f"bad sql json: {exc}; out={r.stdout[:500]}",
                duration_ms=ms,
            )
        if data.get("error"):
            return ToolResult.failure(
                tool, ErrorCode.DB_ERROR, stderr=str(data["error"]), duration_ms=ms
            )
        return ToolResult.success(tool, data=data, duration_ms=ms)

    def apply_pending_sql(self, handle: EpisodeHandle) -> None:
        pending = handle.workspace / "mutations" / "pending_sql.sql"
        if pending.exists():
            sql = pending.read_text(encoding="utf-8")
            if sql.strip():
                self.run_sql(handle, sql, writes=True)
            pending.unlink(missing_ok=True)

    def teardown(self, handle: EpisodeHandle) -> None:
        self._compose_run(
            handle,
            ["down", "-v", "--remove-orphans"],
            check=False,
            timeout=90,
        )

    def dump_failure_artifacts(self, handle: EpisodeHandle, fail_dir: Path) -> None:
        """Write compose ps/logs into failure/ for debugging provision issues."""
        fail_dir.mkdir(parents=True, exist_ok=True)
        ps = self._compose_run(handle, ["ps", "-a"], check=False, timeout=30)
        (fail_dir / "compose_ps.txt").write_text(
            (ps.stdout or "") + "\n" + (ps.stderr or ""), encoding="utf-8"
        )
        logs = self._compose_run(
            handle, ["logs", "--no-color", "--tail", "200"], check=False, timeout=60
        )
        (fail_dir / "compose_logs.txt").write_text(
            (logs.stdout or "") + "\n" + (logs.stderr or ""), encoding="utf-8"
        )

    # ------------------------------------------------------------------ tools

    def _http(self, handle: EpisodeHandle, args: dict[str, Any]) -> ToolResult:
        t0 = time.time()
        if handle.meta.get("http_via") == "host":
            from cascade_env.runtime.local import LocalRuntimeBackend

            return LocalRuntimeBackend()._http(handle, args)  # noqa: SLF001

        method = str(args.get("method", "GET")).upper()
        path = args.get("path") or args.get("url") or "/"
        headers = dict(args.get("headers") or {})
        body = args.get("json")

        # Normalize URL to in-container localhost (api listens on 8000).
        if isinstance(path, str) and (path.startswith("http://") or path.startswith("https://")):
            # Allow only api/localhost hosts
            host = path.split("/")[2] if "://" in path else ""
            host_only = host.split(":")[0]
            if host_only not in ("api", "localhost", "127.0.0.1"):
                return ToolResult.failure(
                    "http.request",
                    ErrorCode.NETWORK_DENIED,
                    stderr=f"host denied: {host}",
                )
            # strip to path+query
            after = path.split("://", 1)[1]
            path = "/" + after.split("/", 1)[1] if "/" in after else "/"
        path = str(path)
        if not path.startswith("/"):
            path = "/" + path

        query = args.get("params") or args.get("query")
        if query and isinstance(query, dict):
            from urllib.parse import urlencode

            sep = "&" if "?" in path else "?"
            path = path + sep + urlencode(query)

        self._ensure_runtime_helpers(handle.workspace)
        req = {
            "method": method,
            "url": f"http://127.0.0.1:8000{path}",
            "headers": headers,
            "json": body,
            "timeout_s": float(args.get("timeout_s", 10)),
        }
        req_path = handle.workspace / ".cascade_rt" / "http_req.json"
        req_path.write_text(json.dumps(req), encoding="utf-8")

        r = self._compose_run(
            handle,
            [
                "exec",
                "-T",
                "api",
                "python",
                "/workspace/.cascade_rt/http_once.py",
                "/workspace/.cascade_rt/http_req.json",
            ],
            check=False,
            timeout=float(args.get("timeout_s", 10)) + 15,
        )
        ms = int((time.time() - t0) * 1000)
        if r.returncode != 0:
            return ToolResult.failure(
                "http.request",
                ErrorCode.INTERNAL,
                stderr=(r.stderr or r.stdout or "http exec failed")[-2000:],
                duration_ms=ms,
            )
        try:
            line = (r.stdout or "").strip().splitlines()[-1]
            data = json.loads(line)
        except Exception as exc:  # noqa: BLE001
            return ToolResult.failure(
                "http.request",
                ErrorCode.INTERNAL,
                stderr=f"bad http json: {exc}; out={(r.stdout or '')[:500]}",
                duration_ms=ms,
            )
        if data.get("error") and "status_code" not in data:
            return ToolResult.failure(
                "http.request",
                ErrorCode.INTERNAL,
                stderr=str(data["error"]),
                duration_ms=ms,
            )
        status = int(data.get("status_code") or 0)
        text = str(data.get("text") or "")
        truncated = bool(data.get("truncated"))
        out_data: dict[str, Any] = {
            "status_code": status,
            "headers": data.get("headers") or {},
        }
        if "json" in data:
            out_data["json"] = data["json"]
        else:
            out_data["text"] = text[:4000]
        return ToolResult(
            ok=status < 500,
            tool="http.request",
            exit_code=0 if status < 400 else 1,
            stdout=text[:8000],
            data=out_data,
            error_code=ErrorCode.OK.value if status < 500 else ErrorCode.INTERNAL.value,
            truncated=truncated,
            duration_ms=ms,
        )

    def _logs(self, handle: EpisodeHandle, args: dict[str, Any]) -> ToolResult:
        service = str(args.get("service", "api"))
        lines = str(args.get("lines", 100))
        if service not in _SERVICE_NAMES:
            return ToolResult.failure(
                "logs.tail", ErrorCode.SERVICE_UNKNOWN, stderr=f"unknown service {service}"
            )
        r = self._compose_run(
            handle,
            ["logs", "--no-color", "--tail", lines, service],
            check=False,
            timeout=30,
        )
        return ToolResult(
            ok=r.returncode == 0,
            tool="logs.tail",
            exit_code=r.returncode,
            stdout=r.stdout or "",
            stderr=r.stderr or "",
            data={"lines": (r.stdout or "").splitlines()},
        )

    def _tests(self, handle: EpisodeHandle, args: dict[str, Any]) -> ToolResult:
        t0 = time.time()
        public = handle.workspace / "tests" / "public"
        if not public.exists():
            return ToolResult.failure("tests.run", ErrorCode.NOT_FOUND, stderr="no public tests")
        api_key = handle.meta.get("env", {}).get("SHOPSTACK_API_KEY", _read_api_key(handle.workspace))
        r = self._compose_run(
            handle,
            [
                "exec",
                "-T",
                "-e",
                "SHOPSTACK_BASE_URL=http://127.0.0.1:8000",
                "-e",
                f"SHOPSTACK_API_KEY={api_key}",
                "-e",
                "PYTHONPATH=/workspace",
                "api",
                "python",
                "-m",
                "pytest",
                "/workspace/tests/public",
                "-q",
                "--tb=line",
            ],
            check=False,
            timeout=float(args.get("timeout_s", 90)),
        )
        ms = int((time.time() - t0) * 1000)
        ok = r.returncode == 0
        return ToolResult(
            ok=ok,
            tool="tests.run",
            exit_code=r.returncode,
            stdout=r.stdout or "",
            stderr=r.stderr or "",
            data={"passed": ok},
            error_code=ErrorCode.OK.value if ok else ErrorCode.INTERNAL.value,
            duration_ms=ms,
        )

    def _ready_via_exec(self, handle: EpisodeHandle) -> bool:
        tr = self._http(handle, {"method": "GET", "path": "/ready", "timeout_s": 3})
        if not tr.ok or not tr.data:
            return False
        body = tr.data.get("json") or {}
        return tr.data.get("status_code") == 200 and body.get("status") == "ready"

    # ------------------------------------------------------------------ compose helpers

    def daemon_ok(self) -> bool:
        try:
            r = subprocess.run(
                [self._docker, "info"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            return r.returncode == 0
        except Exception:
            return False

    def list_cascade_projects(self) -> list[str]:
        try:
            r = subprocess.run(
                [self._docker, "compose", "ls", "--format", "json"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if r.returncode != 0 or not r.stdout.strip():
                return []
            data = json.loads(r.stdout)
            names = []
            for item in data if isinstance(data, list) else []:
                name = str(item.get("Name") or item.get("Name") or "")
                if name.startswith("cascade_"):
                    names.append(name)
            return names
        except Exception:
            return []

    def gc_projects(self, *, older_than_s: float | None = None, dry_run: bool = False) -> list[str]:
        """Remove labeled cascade compose projects (best-effort)."""
        removed: list[str] = []
        try:
            r = subprocess.run(
                [
                    self._docker,
                    "ps",
                    "-a",
                    "--filter",
                    "label=com.cascade.episode_id",
                    "--format",
                    "{{.Label \"com.cascade.episode_id\"}}|{{.Label \"com.cascade.created_at\"}}|{{.ID}}",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except Exception:
            return removed

        seen_eps: set[str] = set()
        now = time.time()
        for line in (r.stdout or "").splitlines():
            parts = line.split("|")
            if len(parts) < 2:
                continue
            ep_id, created_s = parts[0].strip(), parts[1].strip()
            if not ep_id or ep_id in seen_eps:
                continue
            seen_eps.add(ep_id)
            if older_than_s is not None:
                try:
                    created = float(created_s)
                except ValueError:
                    created = 0.0
                if created and (now - created) < older_than_s:
                    continue
            project = f"cascade_{ep_id}"
            removed.append(project)
            if dry_run:
                continue
            compose_file = self._compose_file()
            subprocess.run(
                [
                    self._docker,
                    "compose",
                    "-p",
                    project,
                    "-f",
                    str(compose_file),
                    "down",
                    "-v",
                    "--remove-orphans",
                ],
                cwd=str(self._scenario_dir),
                capture_output=True,
                text=True,
                timeout=90,
            )
        return removed

    def image_pins_status(self) -> dict[str, Any]:
        """Return pin config and whether images are present locally."""
        status: dict[str, Any] = {"pins": dict(self._pins), "present": {}, "daemon": self.daemon_ok()}
        if not status["daemon"]:
            return status
        for key, image in self._pins.items():
            if key in ("CASCADE_API_IMAGE", "CASCADE_WORKER_IMAGE"):
                # built images optional until first episode
                status["present"][image] = self._image_present(image)
            else:
                status["present"][image] = self._image_present(image)
        return status

    def _image_present(self, image: str) -> bool:
        # Strip digest for inspect if tag@sha256
        ref = image
        try:
            r = subprocess.run(
                [self._docker, "image", "inspect", ref],
                capture_output=True,
                text=True,
                timeout=15,
            )
            return r.returncode == 0
        except Exception:
            return False

    def _assert_debug_safe(self) -> None:
        cfg = get_config()
        max_par = max(1, int(cfg.max_parallel_episodes))
        if max_par > 1:
            raise RuntimeError(
                "compose debug profile publishes host ports and is single-episode only; "
                f"refuse when max_parallel_episodes={max_par} (>1). "
                "Set CASCADE_MAX_PARALLEL_EPISODES=1 or omit CASCADE_COMPOSE_DEBUG."
            )
        existing = [p for p in self.list_cascade_projects()]
        if existing:
            raise RuntimeError(
                "compose debug profile refuses to start while other cascade_* projects "
                f"are active: {existing}. Tear them down or omit debug ports."
            )

    def _compose_file(self) -> Path:
        return self._scenario_dir / "docker-compose.yml"

    def _compose_env(self, episode_id: str, workspace: Path) -> dict[str, str]:
        env = os.environ.copy()
        env["CASCADE_WORKSPACE"] = _docker_path(workspace)
        env["CASCADE_EPISODE_ID"] = episode_id
        env["CASCADE_CREATED_AT"] = str(int(time.time()))
        env["CASCADE_VERSION"] = __version__
        env["SHOPSTACK_API_KEY"] = _read_api_key(workspace)
        for k, v in self._pins.items():
            env.setdefault(k, v)
        return env

    def _compose_cmd(self, project: str, files: list[str], *args: str) -> list[str]:
        cmd = [self._docker, "compose", "-p", project]
        for f in files:
            cmd.extend(["-f", f])
        cmd.extend(args)
        return cmd

    def _compose_run(
        self,
        handle: EpisodeHandle,
        args: list[str],
        *,
        check: bool = True,
        timeout: float = 120,
    ) -> subprocess.CompletedProcess[str]:
        files = handle.meta.get("compose_files") or [handle.meta.get("compose_file")]
        files = [str(f) for f in files if f]
        env = os.environ.copy()
        env.update(handle.meta.get("compose_env") or {})
        # Keep workspace path current
        env["CASCADE_WORKSPACE"] = _docker_path(handle.workspace)
        cmd = self._compose_cmd(handle.project_name, files, *args)
        cwd = Path(handle.meta.get("scenario_dir") or self._scenario_dir)
        return self._run(cmd, cwd=cwd, env=env, check=check, timeout=timeout)

    def _run(
        self,
        cmd: list[str],
        *,
        cwd: Path,
        env: dict[str, str] | None = None,
        check: bool = True,
        timeout: float = 120,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            cmd,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=check,
        )

    def _load_image_pins(self) -> dict[str, str]:
        pins = {
            "CASCADE_POSTGRES_IMAGE": "postgres:16-alpine",
            "CASCADE_REDIS_IMAGE": "redis:7-alpine",
            "CASCADE_API_IMAGE": "cascade/shopstack-api:dev",
            "CASCADE_WORKER_IMAGE": "cascade/shopstack-worker:dev",
        }
        pin_file = self._scenario_dir / "image-pins.env"
        if pin_file.exists():
            for line in pin_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                pins[k.strip()] = v.strip().strip('"').strip("'")
        # Env overrides
        for k in list(pins):
            if k in os.environ and os.environ[k].strip():
                pins[k] = os.environ[k].strip()
        return pins

    def _ensure_runtime_helpers(self, workspace: Path) -> None:
        rt = workspace / ".cascade_rt"
        rt.mkdir(parents=True, exist_ok=True)
        http_py = rt / "http_once.py"
        if not http_py.exists():
            http_py.write_text(_HTTP_ONCE_PY, encoding="utf-8")
        sql_py = rt / "sql_once.py"
        if not sql_py.exists():
            sql_py.write_text(_SQL_ONCE_PY, encoding="utf-8")


def _docker_path(path: Path) -> str:
    """Path form accepted by Docker Desktop bind mounts on Windows and Linux."""
    resolved = path.resolve()
    # Docker Desktop on Windows accepts C:/Users/... form
    return resolved.as_posix()


def _read_api_key(workspace: Path) -> str:
    p = workspace / "configs" / "api_key.txt"
    if p.exists():
        return p.read_text(encoding="utf-8").strip()
    return "sk_test_cascade_demo_key"


def _parse_compose_ps_json(stdout: str) -> list[dict[str, Any]]:
    """Compose v2 may emit a JSON array or NDJSON objects."""
    text = (stdout or "").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        if isinstance(data, dict):
            return [data]
    except json.JSONDecodeError:
        pass
    out: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                out.append(obj)
        except json.JSONDecodeError:
            continue
    return out


_HTTP_ONCE_PY = r'''#!/usr/bin/env python3
"""In-container HTTP helper for Cascade compose runtime."""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request


def main() -> int:
    req_path = sys.argv[1] if len(sys.argv) > 1 else "/workspace/.cascade_rt/http_req.json"
    with open(req_path, encoding="utf-8") as f:
        req = json.load(f)
    method = req.get("method", "GET").upper()
    url = req["url"]
    headers = req.get("headers") or {}
    body = req.get("json")
    timeout = float(req.get("timeout_s", 10))
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers = {**headers, "Content-Type": headers.get("Content-Type", "application/json")}
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            raw = resp.read()
            status = resp.status
            resp_headers = {k: v for k, v in resp.headers.items()}
    except urllib.error.HTTPError as e:
        raw = e.read() if e.fp else b""
        status = e.code
        resp_headers = {k: v for k, v in (e.headers.items() if e.headers else [])}
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": str(exc)}))
        return 1
    text = raw.decode("utf-8", errors="replace")
    truncated = False
    if len(text) > 48000:
        text = text[:48000] + "\n...[truncated]"
        truncated = True
    out = {
        "status_code": status,
        "headers": resp_headers,
        "text": text,
        "truncated": truncated,
    }
    try:
        out["json"] = json.loads(text)
    except Exception:
        pass
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

_SQL_ONCE_PY = r'''#!/usr/bin/env python3
"""In-container SQL helper for Cascade compose runtime."""
from __future__ import annotations

import json
import sys

from sqlalchemy import create_engine, text


def main() -> int:
    req_path = sys.argv[1] if len(sys.argv) > 1 else "/workspace/.cascade_rt/sql_req.json"
    with open(req_path, encoding="utf-8") as f:
        req = json.load(f)
    sql = req["sql"]
    writes = bool(req.get("writes"))
    url = req.get("database_url") or "postgresql+psycopg://shop:shop@postgres:5432/shop"
    try:
        eng = create_engine(url, future=True)
        with eng.connect() as conn:
            result = conn.execute(text(sql))
            if writes:
                conn.commit()
                print(json.dumps({"rowcount": result.rowcount}))
            else:
                rows = [dict(r._mapping) for r in result.fetchmany(100)]
                # JSON-serialize values
                clean = []
                for row in rows:
                    item = {}
                    for k, v in row.items():
                        if hasattr(v, "isoformat"):
                            item[k] = v.isoformat()
                        else:
                            item[k] = v
                    clean.append(item)
                print(json.dumps({"rows": clean, "count": len(clean)}))
        return 0
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
'''

"""Local in-process runtime: real Shopstack API + worker without Docker.

This is the default production-capable training path on developer machines
where Docker may be unavailable. Uses SQLite + in-memory queue, same
workspace bind semantics as Compose (agent edits files; restart reloads code).
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import httpx

from cascade_env.runtime.base import EpisodeHandle
from cascade_env.tools.files import FilesTool
from cascade_env.tools.shell import ShellTool
from cascade_env.types import (
    ErrorCode,
    ServiceStatus,
    ToolResult,
)


class LocalRuntimeBackend:
    name = "local"

    def __init__(self) -> None:
        self._procs: dict[str, dict[str, subprocess.Popen]] = {}
        self._log_files: dict[str, list] = {}
        self._ports: dict[str, int] = {}
        self._lock = threading.Lock()

    def provision(self, episode_id: str, workspace: Path) -> EpisodeHandle:
        port = _pick_free_port()
        db_path = workspace / "data" / "shopstack.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        if db_path.exists():
            db_path.unlink()

        # SQLite URL (4 slashes for absolute path on Unix; Windows needs special form)
        db_url = _sqlite_url(db_path)
        queue_db = workspace / "data" / "queue.db"
        env = os.environ.copy()
        env.update(
            {
                "DATABASE_URL": db_url,
                # Shared cross-process queue (API + worker are separate processes)
                "REDIS_URL": f"file://{queue_db.resolve().as_posix()}",
                "SHOPSTACK_API_KEY": _read_api_key(workspace),
                "WORKER_CONFIG": str(workspace / "configs" / "worker.yaml"),
                "PYTHONPATH": str(workspace),
                "LOG_LEVEL": "INFO",
            }
        )

        log_dir = workspace / ".cascade_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        api_log = open(log_dir / "api.log", "w", encoding="utf-8")  # noqa: SIM115
        worker_log = open(log_dir / "worker.log", "w", encoding="utf-8")  # noqa: SIM115

        api_cmd = [
            sys.executable,
            "-m",
            "uvicorn",
            "app.api.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ]
        worker_cmd = [sys.executable, str(workspace / "app" / "worker" / "handler.py")]

        api_proc = subprocess.Popen(
            api_cmd,
            cwd=str(workspace),
            env=env,
            stdout=api_log,
            stderr=subprocess.STDOUT,
        )
        worker_proc = subprocess.Popen(
            worker_cmd,
            cwd=str(workspace),
            env=env,
            stdout=worker_log,
            stderr=subprocess.STDOUT,
        )

        with self._lock:
            self._procs[episode_id] = {"api": api_proc, "worker": worker_proc}
            self._log_files[episode_id] = [api_log, worker_log]
            self._ports[episode_id] = port

        handle = EpisodeHandle(
            episode_id=episode_id,
            workspace=workspace,
            project_name=f"cascade_{episode_id}",
            api_base=f"http://127.0.0.1:{port}",
            db_url=db_url,
            meta={"port": port, "env": {k: env[k] for k in ("DATABASE_URL", "REDIS_URL", "SHOPSTACK_API_KEY")}},
        )
        return handle

    def wait_healthy(self, handle: EpisodeHandle, timeout_s: float) -> bool:
        deadline = time.time() + timeout_s
        url = f"{handle.api_base}/ready"
        while time.time() < deadline:
            procs = self._procs.get(handle.episode_id, {})
            if any(p.poll() is not None for p in procs.values()):
                return False
            try:
                with urllib.request.urlopen(url, timeout=1.5) as resp:
                    if resp.status == 200:
                        return True
            except Exception:
                time.sleep(0.2)
        return False

    def service_status(self, handle: EpisodeHandle) -> list[ServiceStatus]:
        procs = self._procs.get(handle.episode_id, {})
        out: list[ServiceStatus] = []
        for name, proc in procs.items():
            running = proc.poll() is None
            healthy = None
            if name == "api" and running:
                try:
                    with urllib.request.urlopen(f"{handle.api_base}/health", timeout=1) as r:
                        healthy = r.status == 200
                except Exception:
                    healthy = False
            out.append(
                ServiceStatus(
                    name=name,
                    status="running" if running else "stopped",
                    healthy=healthy if name == "api" else running,
                )
            )
        # virtual services for parity
        for name in ("postgres", "redis"):
            out.append(ServiceStatus(name=name, status="running", healthy=True))
        return out

    def restart_services(self, handle: EpisodeHandle, services: list[str]) -> ToolResult:
        t0 = time.time()
        procs = self._procs.get(handle.episode_id)
        if not procs:
            return ToolResult.failure(
                "services.restart", ErrorCode.SERVICE_UNKNOWN, stderr="episode not found"
            )
        env = os.environ.copy()
        env.update(handle.meta.get("env", {}))
        env["PYTHONPATH"] = str(handle.workspace)
        env["WORKER_CONFIG"] = str(handle.workspace / "configs" / "worker.yaml")
        log_dir = handle.workspace / ".cascade_logs"
        log_dir.mkdir(parents=True, exist_ok=True)

        restarted: list[str] = []
        for svc in services:
            if svc not in ("api", "worker"):
                continue
            old = procs.get(svc)
            if old and old.poll() is None:
                _terminate(old)
            if svc == "api":
                port = handle.meta["port"]
                log = open(log_dir / "api.log", "a", encoding="utf-8")  # noqa: SIM115
                proc = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        "app.api.main:app",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(port),
                        "--log-level",
                        "warning",
                    ],
                    cwd=str(handle.workspace),
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
            else:
                log = open(log_dir / "worker.log", "a", encoding="utf-8")  # noqa: SIM115
                proc = subprocess.Popen(
                    [sys.executable, str(handle.workspace / "app" / "worker" / "handler.py")],
                    cwd=str(handle.workspace),
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
            procs[svc] = proc
            self._log_files.setdefault(handle.episode_id, []).append(log)
            restarted.append(svc)

        # wait briefly for api
        if "api" in restarted:
            self.wait_healthy(handle, timeout_s=15)
        ms = int((time.time() - t0) * 1000)
        return ToolResult.success(
            "services.restart",
            data={"restarted": restarted},
            duration_ms=ms,
        )

    def exec_tool(self, handle: EpisodeHandle, tool: str, args: dict[str, Any]) -> ToolResult:
        if tool.startswith("files."):
            return FilesTool(handle.workspace).execute(tool, args)
        if tool == "http.request":
            return self._http(handle, args)
        if tool == "logs.tail":
            return self._logs(handle, args)
        if tool in ("services.restart", "services.ps"):
            if tool == "services.ps":
                statuses = [s.model_dump() for s in self.service_status(handle)]
                return ToolResult.success("services.ps", data={"services": statuses})
            services = args.get("services") or args.get("service")
            if isinstance(services, str):
                services = [services]
            return self.restart_services(handle, list(services or []))
        if tool in ("db.query", "db.exec"):
            return self.run_sql(handle, args.get("sql", ""), writes=(tool == "db.exec"))
        if tool == "shell.exec":
            return ShellTool(handle.workspace).execute(args)
        if tool == "tests.run":
            return self._tests(handle, args)
        return ToolResult.failure(tool, ErrorCode.NOT_FOUND, stderr=f"unknown tool {tool}")

    def run_sql(self, handle: EpisodeHandle, sql: str, *, writes: bool = False) -> ToolResult:
        t0 = time.time()
        try:
            from sqlalchemy import create_engine, text

            eng = create_engine(handle.db_url, future=True)
            with eng.connect() as conn:
                result = conn.execute(text(sql))
                if writes:
                    conn.commit()
                    ms = int((time.time() - t0) * 1000)
                    return ToolResult.success(
                        "db.exec" if writes else "db.query",
                        data={"rowcount": result.rowcount},
                        duration_ms=ms,
                    )
                rows = [dict(r._mapping) for r in result.fetchmany(100)]
                ms = int((time.time() - t0) * 1000)
                return ToolResult.success(
                    "db.query",
                    data={"rows": rows, "count": len(rows)},
                    duration_ms=ms,
                )
        except Exception as exc:  # noqa: BLE001
            return ToolResult.failure(
                "db.exec" if writes else "db.query",
                ErrorCode.DB_ERROR,
                stderr=str(exc),
                duration_ms=int((time.time() - t0) * 1000),
            )

    def apply_pending_sql(self, handle: EpisodeHandle) -> None:
        pending = handle.workspace / "mutations" / "pending_sql.sql"
        if pending.exists():
            sql = pending.read_text(encoding="utf-8")
            if sql.strip():
                self.run_sql(handle, sql, writes=True)
            pending.unlink(missing_ok=True)

    def teardown(self, handle: EpisodeHandle) -> None:
        procs = self._procs.pop(handle.episode_id, {})
        for p in procs.values():
            _terminate(p)
        for f in self._log_files.pop(handle.episode_id, []):
            try:
                f.close()
            except Exception:
                pass
        self._ports.pop(handle.episode_id, None)

    def _http(self, handle: EpisodeHandle, args: dict[str, Any]) -> ToolResult:
        t0 = time.time()
        method = str(args.get("method", "GET")).upper()
        path = args.get("path") or args.get("url") or "/"
        if path.startswith("http://") or path.startswith("https://"):
            # only allow pointing at our api_base host
            if not path.startswith(handle.api_base):
                host = path.split("/")[2] if "://" in path else ""
                if host not in ("api", "localhost", "127.0.0.1") and not host.startswith(
                    "127.0.0.1:"
                ):
                    return ToolResult.failure(
                        "http.request", ErrorCode.NETWORK_DENIED, stderr=f"host denied: {host}"
                    )
            url = path.replace("http://api", handle.api_base).replace(
                "http://api:8000", handle.api_base
            )
        else:
            if not path.startswith("/"):
                path = "/" + path
            url = handle.api_base + path
        params = args.get("params") or args.get("query")
        if params and isinstance(params, dict):
            from urllib.parse import urlencode

            sep = "&" if "?" in url else "?"
            url = url + sep + urlencode(params)
        headers = dict(args.get("headers") or {})
        body = args.get("json")
        try:
            with httpx.Client(timeout=float(args.get("timeout_s", 10))) as client:
                resp = client.request(method, url, headers=headers, json=body)
            text = resp.text
            truncated = False
            if len(text) > 48_000:
                text = text[:48_000] + "\n...[truncated]"
                truncated = True
            data: dict[str, Any] = {
                "status_code": resp.status_code,
                "headers": dict(resp.headers),
            }
            try:
                data["json"] = resp.json()
            except Exception:
                data["text"] = text[:4000]
            ms = int((time.time() - t0) * 1000)
            return ToolResult(
                ok=resp.status_code < 500,
                tool="http.request",
                exit_code=0 if resp.status_code < 400 else 1,
                stdout=text[:8000],
                data=data,
                error_code=ErrorCode.OK.value if resp.status_code < 500 else ErrorCode.INTERNAL.value,
                truncated=truncated,
                duration_ms=ms,
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult.failure(
                "http.request",
                ErrorCode.INTERNAL,
                stderr=str(exc),
                duration_ms=int((time.time() - t0) * 1000),
            )

    def _logs(self, handle: EpisodeHandle, args: dict[str, Any]) -> ToolResult:
        service = args.get("service", "api")
        lines = int(args.get("lines", 100))
        log_path = handle.workspace / ".cascade_logs" / f"{service}.log"
        if not log_path.exists():
            return ToolResult.success("logs.tail", stdout="", data={"lines": []})
        content = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        tail = content[-lines:]
        text = "\n".join(tail)
        return ToolResult.success("logs.tail", stdout=text, data={"lines": tail})

    def _tests(self, handle: EpisodeHandle, args: dict[str, Any]) -> ToolResult:
        t0 = time.time()
        public = handle.workspace / "tests" / "public"
        if not public.exists():
            return ToolResult.failure("tests.run", ErrorCode.NOT_FOUND, stderr="no public tests")
        env = os.environ.copy()
        env["SHOPSTACK_BASE_URL"] = handle.api_base
        env["SHOPSTACK_API_KEY"] = handle.meta.get("env", {}).get(
            "SHOPSTACK_API_KEY", "sk_test_cascade_demo_key"
        )
        env["PYTHONPATH"] = str(handle.workspace)
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", str(public), "-q", "--tb=line"],
            cwd=str(handle.workspace),
            env=env,
            capture_output=True,
            text=True,
            timeout=float(args.get("timeout_s", 60)),
        )
        ms = int((time.time() - t0) * 1000)
        ok = proc.returncode == 0
        return ToolResult(
            ok=ok,
            tool="tests.run",
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            data={"passed": ok},
            error_code=ErrorCode.OK.value if ok else ErrorCode.INTERNAL.value,
            duration_ms=ms,
        )


def _read_api_key(workspace: Path) -> str:
    p = workspace / "configs" / "api_key.txt"
    if p.exists():
        return p.read_text(encoding="utf-8").strip()
    return "sk_test_cascade_demo_key"


def _sqlite_url(path: Path) -> str:
    # SQLAlchemy wants sqlite:////absolute/path on POSIX; on Windows sqlite:///C:/...
    resolved = path.resolve()
    if os.name == "nt":
        return "sqlite:///" + resolved.as_posix()
    return "sqlite:////" + resolved.as_posix()


def _pick_free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _terminate(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            proc.terminate()
        else:
            os.kill(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass

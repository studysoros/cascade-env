"""Filesystem tools jailed to /workspace."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from cascade_env.types import FILES_READ_MAX, FILES_WRITE_MAX, ErrorCode, ToolResult


class FilesTool:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()

    def execute(self, tool: str, args: dict[str, Any]) -> ToolResult:
        t0 = time.time()
        try:
            if tool == "files.list":
                return self._list(args, t0)
            if tool == "files.read":
                return self._read(args, t0)
            if tool == "files.write":
                return self._write(args, t0)
            return ToolResult.failure(tool, ErrorCode.NOT_FOUND, stderr=f"unknown {tool}")
        except PermissionError as exc:
            return ToolResult.failure(
                tool, ErrorCode.PATH_JAIL, stderr=str(exc), duration_ms=_ms(t0)
            )
        except FileNotFoundError as exc:
            return ToolResult.failure(
                tool, ErrorCode.NOT_FOUND, stderr=str(exc), duration_ms=_ms(t0)
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult.failure(
                tool, ErrorCode.INTERNAL, stderr=str(exc), duration_ms=_ms(t0)
            )

    def _resolve(self, rel: str) -> Path:
        rel = (rel or "").replace("\\", "/").lstrip("/")
        if rel.startswith("workspace/"):
            rel = rel[len("workspace/") :]
        # forbid infra / verifier escapes
        banned_prefixes = ("../", "infra/", "verifier/", ".git/")
        for b in banned_prefixes:
            if rel.startswith(b) or f"/{b}" in f"/{rel}":
                raise PermissionError(f"path jail: {rel}")
        target = (self.workspace / rel).resolve()
        if not str(target).startswith(str(self.workspace)):
            raise PermissionError(f"path jail: {rel}")
        return target

    def _list(self, args: dict[str, Any], t0: float) -> ToolResult:
        path = self._resolve(args.get("path", "."))
        if not path.exists():
            raise FileNotFoundError(str(path))
        if path.is_file():
            entries = [path.name]
        else:
            entries = sorted(p.name + ("/" if p.is_dir() else "") for p in path.iterdir())
        return ToolResult.success(
            "files.list",
            data={"path": str(path.relative_to(self.workspace)), "entries": entries},
            duration_ms=_ms(t0),
        )

    def _read(self, args: dict[str, Any], t0: float) -> ToolResult:
        path = self._resolve(args["path"])
        raw = path.read_bytes()
        truncated = len(raw) > FILES_READ_MAX
        text = raw[:FILES_READ_MAX].decode("utf-8", errors="replace")
        return ToolResult(
            ok=True,
            tool="files.read",
            exit_code=0,
            stdout=text,
            data={"path": args["path"], "size": len(raw)},
            error_code=ErrorCode.OK.value,
            truncated=truncated,
            duration_ms=_ms(t0),
        )

    def _write(self, args: dict[str, Any], t0: float) -> ToolResult:
        path = self._resolve(args["path"])
        content = args.get("content", "")
        if isinstance(content, bytes):
            data = content
        else:
            data = str(content).encode("utf-8")
        if len(data) > FILES_WRITE_MAX:
            return ToolResult.failure(
                "files.write",
                ErrorCode.ARG_DENIED,
                stderr=f"content exceeds {FILES_WRITE_MAX} bytes",
                duration_ms=_ms(t0),
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return ToolResult.success(
            "files.write",
            data={"path": args["path"], "bytes": len(data)},
            duration_ms=_ms(t0),
        )


def _ms(t0: float) -> int:
    return int((time.time() - t0) * 1000)

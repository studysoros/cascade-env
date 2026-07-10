"""Allowlisted shell.exec (argv only)."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any

from cascade_env.types import (
    SHELL_ALLOWLIST,
    SHELL_DEFAULT_TIMEOUT_S,
    SHELL_DENYLIST,
    ErrorCode,
    ToolResult,
)


class ShellTool:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()

    def execute(self, args: dict[str, Any]) -> ToolResult:
        t0 = time.time()
        argv = args.get("argv") or args.get("cmd")
        if isinstance(argv, str):
            return ToolResult.failure(
                "shell.exec",
                ErrorCode.ARG_DENIED,
                stderr="argv array required (no shell string)",
                duration_ms=_ms(t0),
            )
        if not isinstance(argv, list) or not argv:
            return ToolResult.failure(
                "shell.exec",
                ErrorCode.ARG_DENIED,
                stderr="argv must be non-empty list",
                duration_ms=_ms(t0),
            )
        argv = [str(x) for x in argv]
        binary = Path(argv[0]).name.lower()
        if binary.endswith(".exe"):
            binary = binary[:-4]
        if binary in SHELL_DENYLIST:
            return ToolResult.failure(
                "shell.exec",
                ErrorCode.BINARY_DENIED,
                stderr=f"binary denied: {binary}",
                duration_ms=_ms(t0),
            )
        if binary not in SHELL_ALLOWLIST:
            return ToolResult.failure(
                "shell.exec",
                ErrorCode.BINARY_DENIED,
                stderr=f"binary not allowlisted: {binary}",
                duration_ms=_ms(t0),
            )
        # path jail for file args
        for a in argv[1:]:
            if a.startswith("-"):
                continue
            if "/" in a or "\\" in a or a.endswith(".py"):
                try:
                    p = Path(a)
                    if p.is_absolute():
                        resolved = p.resolve()
                    else:
                        resolved = (self.workspace / a).resolve()
                    if not str(resolved).startswith(str(self.workspace)):
                        return ToolResult.failure(
                            "shell.exec",
                            ErrorCode.PATH_JAIL,
                            stderr=f"path outside workspace: {a}",
                            duration_ms=_ms(t0),
                        )
                except Exception:
                    pass

        timeout = float(args.get("timeout_s", SHELL_DEFAULT_TIMEOUT_S))
        env = os.environ.copy()
        env["PYTHONPATH"] = str(self.workspace)
        try:
            proc = subprocess.run(
                argv,
                cwd=str(self.workspace),
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=False,
            )
            return ToolResult(
                ok=proc.returncode == 0,
                tool="shell.exec",
                exit_code=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
                error_code=ErrorCode.OK.value if proc.returncode == 0 else ErrorCode.INTERNAL.value,
                duration_ms=_ms(t0),
            )
        except subprocess.TimeoutExpired:
            return ToolResult.failure(
                "shell.exec", ErrorCode.TIMEOUT, stderr="timeout", duration_ms=_ms(t0)
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult.failure(
                "shell.exec", ErrorCode.INTERNAL, stderr=str(exc), duration_ms=_ms(t0)
            )


def _ms(t0: float) -> int:
    return int((time.time() - t0) * 1000)

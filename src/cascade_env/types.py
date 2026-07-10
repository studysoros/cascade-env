"""Core types, ToolResult contract, and error taxonomy for Cascade."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ErrorCode(str, Enum):
    OK = "OK"
    TIMEOUT = "TIMEOUT"
    PATH_JAIL = "PATH_JAIL"
    ARG_DENIED = "ARG_DENIED"
    BINARY_DENIED = "BINARY_DENIED"
    NETWORK_DENIED = "NETWORK_DENIED"
    SERVICE_UNKNOWN = "SERVICE_UNKNOWN"
    NOT_FOUND = "NOT_FOUND"
    DB_ERROR = "DB_ERROR"
    INTERNAL = "INTERNAL"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    POLICY = "POLICY"


# Payload limits (Key Decision)
STDOUT_STDERR_MAX = 48 * 1024
FILES_READ_MAX = 64 * 1024
FILES_WRITE_MAX = 256 * 1024
DB_QUERY_MAX_ROWS = 100
LOGS_TAIL_MAX_LINES = 2000
SHELL_DEFAULT_TIMEOUT_S = 30

# Shell allowlist — argv only, deny by default
SHELL_ALLOWLIST = frozenset(
    {
        "python",
        "python3",
        "pytest",
        "ls",
        "cat",
        "head",
        "tail",
        "wc",
        "grep",
        "find",
        "sed",
        "awk",
        "true",
        "echo",
    }
)

SHELL_DENYLIST = frozenset(
    {
        "docker",
        "docker-compose",
        "podman",
        "kubectl",
        "curl",
        "wget",
        "ssh",
        "nc",
        "nmap",
        "sudo",
        "su",
        "mount",
        "pip",
        "pip3",
        "bash",
        "sh",
        "zsh",
        "powershell",
        "cmd",
    }
)

HTTP_HOST_ALLOWLIST = frozenset({"api", "worker", "postgres", "redis", "localhost", "127.0.0.1"})


class ToolResult(BaseModel):
    ok: bool
    tool: str
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    data: dict[str, Any] | None = None
    error_code: str | None = None
    truncated: bool = False
    duration_ms: int = 0

    @classmethod
    def success(
        cls,
        tool: str,
        *,
        stdout: str = "",
        stderr: str = "",
        data: dict[str, Any] | None = None,
        exit_code: int = 0,
        duration_ms: int = 0,
    ) -> ToolResult:
        stdout, stderr, truncated = _truncate_io(stdout, stderr)
        return cls(
            ok=True,
            tool=tool,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            data=data,
            error_code=ErrorCode.OK.value,
            truncated=truncated,
            duration_ms=duration_ms,
        )

    @classmethod
    def failure(
        cls,
        tool: str,
        error_code: ErrorCode | str,
        *,
        stderr: str = "",
        stdout: str = "",
        data: dict[str, Any] | None = None,
        exit_code: int | None = 1,
        duration_ms: int = 0,
    ) -> ToolResult:
        stdout, stderr, truncated = _truncate_io(stdout, stderr)
        code = error_code.value if isinstance(error_code, ErrorCode) else error_code
        return cls(
            ok=False,
            tool=tool,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            data=data,
            error_code=code,
            truncated=truncated,
            duration_ms=duration_ms,
        )


def _truncate_io(stdout: str, stderr: str) -> tuple[str, str, bool]:
    total = len(stdout.encode("utf-8", errors="replace")) + len(
        stderr.encode("utf-8", errors="replace")
    )
    if total <= STDOUT_STDERR_MAX:
        return stdout, stderr, False
    # Prefer keeping stderr when truncating
    max_each = STDOUT_STDERR_MAX // 2
    return (
        stdout.encode("utf-8", errors="replace")[:max_each].decode("utf-8", errors="replace")
        + "\n...[truncated]",
        stderr.encode("utf-8", errors="replace")[:max_each].decode("utf-8", errors="replace")
        + "\n...[truncated]",
        True,
    )


class Budget(BaseModel):
    steps_remaining: int
    max_steps: int
    wall_time_remaining_s: float
    max_wall_time_s: float
    step_cost: float = 0.001


class ServiceStatus(BaseModel):
    name: str
    status: str  # running | stopped | unhealthy | unknown
    healthy: bool | None = None


class TaskBrief(BaseModel):
    id: str
    family: str
    tier: str
    title: str
    description: str
    public_success_criteria: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)


class Observation(BaseModel):
    episode_id: str
    step: int
    task: TaskBrief
    budget: Budget
    services: list[ServiceStatus] = Field(default_factory=list)
    hints: list[str] = Field(default_factory=list)
    last_tool_result: ToolResult | None = None
    recent_events: list[dict[str, Any]] = Field(default_factory=list)
    runtime: str = "local"
    phase: str = "AGENT_CONTROL"


class Action(BaseModel):
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)


class VerifierResult(BaseModel):
    id: str
    passed: bool
    weight: float = 0.0
    detail: str = ""
    data: dict[str, Any] | None = None


class EpisodeResult(BaseModel):
    episode_id: str
    success: bool
    terminal_reward: float
    step_cost_accrued: float
    verifiers: list[VerifierResult] = Field(default_factory=list)
    truncated: bool = False
    terminated: bool = False
    trajectory_path: str | None = None


class EpisodePhase(str, Enum):
    PROVISIONING = "PROVISIONING"
    HEALTHY_BASELINE = "HEALTHY_BASELINE"
    TASK_INJECTED = "TASK_INJECTED"
    AGENT_CONTROL = "AGENT_CONTROL"
    VERIFYING = "VERIFYING"
    TEARDOWN = "TEARDOWN"
    DONE = "DONE"

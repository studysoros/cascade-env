"""Cascade tool catalog for LLM function-calling APIs.

OpenAI/Anthropic function names must match ``[a-zA-Z0-9_-]+``, so Cascade
tool ids (``files.read``) are mapped to ``files_read`` for the wire format
and remapped before ``env.step``.
"""

from __future__ import annotations

from typing import Any

# Wire name (API) -> Cascade tool id
_WIRE_TO_CASCADE: dict[str, str] = {
    "files_list": "files.list",
    "files_read": "files.read",
    "files_write": "files.write",
    "http_request": "http.request",
    "logs_tail": "logs.tail",
    "services_ps": "services.ps",
    "services_restart": "services.restart",
    "db_query": "db.query",
    "db_exec": "db.exec",
    "shell_exec": "shell.exec",
    "tests_run": "tests.run",
    "submit_done": "submit.done",
}

_CASCADE_TO_WIRE: dict[str, str] = {v: k for k, v in _WIRE_TO_CASCADE.items()}


def cascade_tool_name(wire_name: str) -> str:
    """Map API function name to Cascade tool id (passthrough if already dotted)."""
    if wire_name in _WIRE_TO_CASCADE:
        return _WIRE_TO_CASCADE[wire_name]
    if wire_name in _CASCADE_TO_WIRE:
        return wire_name
    # tolerate accidental dots vs underscores
    alt = wire_name.replace(".", "_")
    if alt in _WIRE_TO_CASCADE:
        return _WIRE_TO_CASCADE[alt]
    return wire_name


def wire_tool_name(cascade_name: str) -> str:
    return _CASCADE_TO_WIRE.get(cascade_name, cascade_name.replace(".", "_"))


def openai_tools() -> list[dict[str, Any]]:
    """OpenAI Chat Completions ``tools`` list."""
    return [{"type": "function", "function": f} for f in _function_defs()]


def anthropic_tools() -> list[dict[str, Any]]:
    """Anthropic Messages ``tools`` list."""
    out: list[dict[str, Any]] = []
    for f in _function_defs():
        out.append(
            {
                "name": f["name"],
                "description": f["description"],
                "input_schema": f["parameters"],
            }
        )
    return out


def system_prompt() -> str:
    return """You are an SRE / production-systems repair agent inside Cascade.

You operate on a **sandboxed** multi-service commerce stack (Shopstack):
API, worker, database/queue. Your job is to diagnose and repair the
injected fault so public success criteria pass.

## Rules
- Use only the provided tools. One logical repair plan; minimize steps.
- Workspace paths are relative (e.g. `configs/worker.yaml`, `app/api/...`).
- After code or config edits, restart affected services (`api`, `worker`).
- Prefer reading files/logs and probing HTTP before large rewrites.
- When you believe the system is healthy, call `submit_done` to run verifiers.
- Do not invent credentials or contact real external systems.
- Shell is allowlisted (no docker/curl/ssh). Prefer higher-level tools.

## Typical repair loop
1. Read task description and success criteria.
2. Inspect configs, code, logs, and `/ready` / public HTTP routes.
3. Apply the minimal fix (files.write / db.exec).
4. services_restart → optional tests_run → submit_done.
"""


def _function_defs() -> list[dict[str, Any]]:
    return [
        {
            "name": "files_list",
            "description": "List files under a workspace-relative directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative directory path (default '.').",
                    }
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "files_read",
            "description": "Read a text file from the episode workspace (max 64 KiB).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Workspace-relative file path.",
                    }
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
        {
            "name": "files_write",
            "description": "Write/overwrite a text file in the workspace (max 256 KiB).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative path."},
                    "content": {"type": "string", "description": "Full file contents."},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        },
        {
            "name": "http_request",
            "description": "HTTP request to the in-sandbox API (or allowlisted host).",
            "parameters": {
                "type": "object",
                "properties": {
                    "method": {
                        "type": "string",
                        "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"],
                        "description": "HTTP method (default GET).",
                    },
                    "path": {
                        "type": "string",
                        "description": "Request path, e.g. /ready or /products.",
                    },
                    "headers": {
                        "type": "object",
                        "description": "Optional headers (e.g. X-API-Key).",
                        "additionalProperties": {"type": "string"},
                    },
                    "body": {
                        "description": "Optional JSON body for POST/PUT/PATCH.",
                    },
                    "timeout_s": {"type": "number", "description": "Timeout seconds."},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
        {
            "name": "logs_tail",
            "description": "Tail recent logs from a service (api or worker).",
            "parameters": {
                "type": "object",
                "properties": {
                    "service": {
                        "type": "string",
                        "enum": ["api", "worker"],
                        "description": "Service name.",
                    },
                    "lines": {
                        "type": "integer",
                        "description": "Number of lines (default 100).",
                    },
                },
                "required": ["service"],
                "additionalProperties": False,
            },
        },
        {
            "name": "services_ps",
            "description": "List service process/status (api, worker, etc.).",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
        {
            "name": "services_restart",
            "description": "Restart one or more services after code/config changes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "services": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Services to restart, e.g. [\"api\", \"worker\"].",
                    }
                },
                "required": ["services"],
                "additionalProperties": False,
            },
        },
        {
            "name": "db_query",
            "description": "Read-only SQL query (limited rows).",
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "SELECT (or read) SQL."},
                },
                "required": ["sql"],
                "additionalProperties": False,
            },
        },
        {
            "name": "db_exec",
            "description": "SQL write (INSERT/UPDATE/DELETE). Use carefully.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "Write SQL statement."},
                },
                "required": ["sql"],
                "additionalProperties": False,
            },
        },
        {
            "name": "shell_exec",
            "description": (
                "Run an allowlisted argv-only command (python, pytest, ls, cat, "
                "grep, find, …). No shell metacharacters / no docker/curl."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "argv": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Argument vector, e.g. [\"ls\", \"configs\"].",
                    },
                    "timeout_s": {"type": "number"},
                },
                "required": ["argv"],
                "additionalProperties": False,
            },
        },
        {
            "name": "tests_run",
            "description": "Run public pytest suite in the workspace.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
        {
            "name": "submit_done",
            "description": (
                "End the episode and run multi-verifier scoring. "
                "Call only when you believe repairs are complete."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    ]

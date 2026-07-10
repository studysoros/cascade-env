"""Scripted repair agent that solves known community tasks (baseline / demo)."""

from __future__ import annotations

from typing import Any


def scripted_policy(obs: dict[str, Any], info: dict[str, Any]) -> dict[str, Any]:
    """
    Deterministic policy that applies known fixes for community pack tasks,
    then restarts services and submits.
    """
    task_id = obs.get("task", {}).get("id", "")
    step = int(obs.get("step", 0))
    family = obs.get("task", {}).get("family", "")

    # Phase machine by step index
    if step == 0:
        return {"tool": "files.list", "args": {"path": "configs"}}
    if step == 1:
        return {"tool": "logs.tail", "args": {"service": "api", "lines": 50}}

    fix = _fix_for_task(task_id, family)
    if fix is None:
        if step < 5:
            return {"tool": "http.request", "args": {"method": "GET", "path": "/ready"}}
        return {"tool": "submit.done", "args": {}}

    # steps 2.. apply writes, then restart, tests, submit
    writes = fix.get("writes", [])
    if step - 2 < len(writes):
        w = writes[step - 2]
        return {"tool": "files.write", "args": w}

    after = step - 2 - len(writes)
    if after == 0:
        return {"tool": "services.restart", "args": {"services": fix.get("restart", ["api", "worker"])}}
    if after == 1:
        return {"tool": "tests.run", "args": {}}
    if after == 2:
        return {"tool": "http.request", "args": {"method": "GET", "path": "/ready"}}
    return {"tool": "submit.done", "args": {}}


def _fix_for_task(task_id: str, family: str) -> dict[str, Any] | None:
    # Worker retry storm / config
    if "worker_retry" in task_id or task_id.endswith("worker_retry_storm.v1"):
        return {
            "writes": [
                {
                    "path": "configs/worker.yaml",
                    "content": "max_retries: 3\nenabled: true\nwork_seconds: 0.05\n",
                },
                {
                    "path": "app/worker/handler.py",
                    "content": _good_worker_handler(),
                },
            ],
            "restart": ["worker"],
        }
    if "pagination" in task_id:
        return {
            "writes": [
                {
                    "path": "app/api/routes/products.py",
                    "content": _good_products(),
                }
            ],
            "restart": ["api"],
        }
    if "max_retries" in task_id or "worker_disabled" in task_id or family == "config_repair":
        return {
            "writes": [
                {
                    "path": "configs/worker.yaml",
                    "content": "max_retries: 3\nenabled: true\nwork_seconds: 0.05\n",
                }
            ],
            "restart": ["worker"],
        }
    if "auth_bypass" in task_id:
        return {
            "writes": [
                {
                    "path": "app/api/auth.py",
                    "content": _good_auth(),
                }
            ],
            "restart": ["api"],
        }
    if "stock" in task_id:
        return {
            "writes": [
                {
                    "path": "app/api/routes/orders.py",
                    "content": _good_orders(),
                }
            ],
            "restart": ["api"],
        }
    if "idempotency" in task_id:
        return {
            "writes": [
                {
                    "path": "app/api/routes/orders.py",
                    "content": _good_orders(),
                }
            ],
            "restart": ["api"],
        }
    if "null_price" in task_id or "bad_prices" in task_id:
        return {
            "writes": [
                {
                    "path": "app/api/routes/products.py",
                    "content": _good_products(),
                }
            ],
            "restart": ["api"],
        }
    if "discount" in task_id or "feature" in task_id or family == "feature_ship":
        return {
            "writes": [
                {
                    "path": "app/api/routes/products.py",
                    "content": _products_with_discount(),
                }
            ],
            "restart": ["api"],
        }
    return None


def _good_worker_handler() -> str:
    # Read from template is better; keep compact correct version
    from pathlib import Path

    from cascade_env.config import get_config

    p = (
        get_config().scenarios_dir()
        / "shopstack"
        / "workspace_template"
        / "app"
        / "worker"
        / "handler.py"
    )
    if p.exists():
        return p.read_text(encoding="utf-8")
    return "print('missing template')\n"


def _good_products() -> str:
    from cascade_env.config import get_config

    p = (
        get_config().scenarios_dir()
        / "shopstack"
        / "workspace_template"
        / "app"
        / "api"
        / "routes"
        / "products.py"
    )
    return p.read_text(encoding="utf-8")


def _products_with_discount() -> str:
    base = _good_products()
    # inject discount_cents into responses
    base = base.replace(
        '"price_cents": p.price_cents,\n                    "stock": p.stock,',
        '"price_cents": p.price_cents,\n                    "discount_cents": 0,\n                    "stock": p.stock,',
    )
    base = base.replace(
        '"price_cents": p.price_cents,\n            "stock": p.stock,',
        '"price_cents": p.price_cents,\n            "discount_cents": 0,\n            "stock": p.stock,',
    )
    return base


def _good_auth() -> str:
    from cascade_env.config import get_config

    p = (
        get_config().scenarios_dir()
        / "shopstack"
        / "workspace_template"
        / "app"
        / "api"
        / "auth.py"
    )
    return p.read_text(encoding="utf-8")


def _good_orders() -> str:
    from cascade_env.config import get_config

    p = (
        get_config().scenarios_dir()
        / "shopstack"
        / "workspace_template"
        / "app"
        / "api"
        / "routes"
        / "orders.py"
    )
    return p.read_text(encoding="utf-8")

"""Apply task mutations to a materialized workspace."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from cascade_env.tasks.schemas import MutationSpec


class MutationError(RuntimeError):
    pass


def apply_mutations(workspace: Path, mutations: list[MutationSpec]) -> list[str]:
    """Apply mutations in order. Returns human-readable log lines."""
    events: list[str] = []
    for m in mutations:
        events.append(_apply_one(workspace, m))
    return events


def _apply_one(workspace: Path, m: MutationSpec) -> str:
    t = m.type
    if t == "config.set":
        return _config_set(workspace, m)
    if t == "code.patch":
        return _code_patch(workspace, m)
    if t == "file.write":
        return _file_write(workspace, m)
    if t == "file.replace":
        return _file_replace(workspace, m)
    if t == "sql.seed":
        # Applied at DB level by runtime after start; store for later
        path = workspace / "mutations" / "pending_sql.sql"
        path.parent.mkdir(parents=True, exist_ok=True)
        sql = m.sql or ""
        with path.open("a", encoding="utf-8") as f:
            f.write(sql.rstrip() + "\n")
        return f"sql.seed queued ({len(sql)} chars)"
    if t == "env.set":
        env_path = workspace / "configs" / "runtime.env"
        env_path.parent.mkdir(parents=True, exist_ok=True)
        key = m.key or ""
        val = "" if m.value is None else str(m.value)
        existing = ""
        if env_path.exists():
            existing = env_path.read_text(encoding="utf-8")
        lines = [ln for ln in existing.splitlines() if not ln.startswith(f"{key}=")]
        lines.append(f"{key}={val}")
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return f"env.set {key}={val}"
    raise MutationError(f"Unknown mutation type: {t}")


def _config_set(workspace: Path, m: MutationSpec) -> str:
    rel = m.path or "configs/worker.yaml"
    path = _safe_join(workspace, rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if path.exists():
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if isinstance(loaded, dict):
            data = loaded
    key = m.key or ""
    data[key] = m.value
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return f"config.set {rel} {key}={m.value!r}"


def _code_patch(workspace: Path, m: MutationSpec) -> str:
    if m.template:
        return _apply_template(workspace, m)
    if m.find is not None and m.replace is not None:
        return _file_replace(workspace, m)
    if m.patch:
        # unified-ish: treat as find/replace blocks separated by ---
        return _file_write(workspace, MutationSpec(type="file.write", path=m.file, content=m.patch))
    raise MutationError("code.patch requires template, find/replace, or patch content")


def _apply_template(workspace: Path, m: MutationSpec) -> str:
    templates = {
        "infinite_retry_no_jitter": _tpl_infinite_retry,
        "pagination_off_by_one": _tpl_pagination_bug,
        "auth_bypass_debug": _tpl_auth_debug_flag,
        "stock_not_decremented": _tpl_stock_bug,
        "broken_idempotency": _tpl_idempotency_bug,
        "null_price_leak": _tpl_null_price,
    }
    fn = templates.get(m.template or "")
    if fn is None:
        raise MutationError(f"Unknown code patch template: {m.template}")
    return fn(workspace, m)


def _file_write(workspace: Path, m: MutationSpec) -> str:
    rel = m.file or m.path
    if not rel:
        raise MutationError("file.write requires file/path")
    path = _safe_join(workspace, rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = m.content if m.content is not None else (m.patch or "")
    path.write_text(content, encoding="utf-8")
    return f"file.write {rel} ({len(content)} bytes)"


def _file_replace(workspace: Path, m: MutationSpec) -> str:
    rel = m.file or m.path
    if not rel or m.find is None or m.replace is None:
        raise MutationError("file.replace requires file, find, replace")
    path = _safe_join(workspace, rel)
    if not path.exists():
        raise MutationError(f"file.replace target missing: {rel}")
    text = path.read_text(encoding="utf-8")
    if m.find not in text:
        # try regex
        new_text, n = re.subn(m.find, m.replace, text, count=1)
        if n == 0:
            raise MutationError(f"file.replace find not found in {rel}")
        text = new_text
    else:
        text = text.replace(m.find, m.replace, 1)
    path.write_text(text, encoding="utf-8")
    return f"file.replace {rel}"


def _safe_join(workspace: Path, rel: str) -> Path:
    rel = rel.lstrip("/").replace("\\", "/")
    if rel.startswith("workspace/"):
        rel = rel[len("workspace/") :]
    target = (workspace / rel).resolve()
    root = workspace.resolve()
    if not str(target).startswith(str(root)):
        raise MutationError(f"path jail escape: {rel}")
    return target


# --- Fault templates: surgically break known-good code ---


def _tpl_infinite_retry(workspace: Path, m: MutationSpec) -> str:
    path = _safe_join(workspace, m.file or "app/worker/handler.py")
    text = path.read_text(encoding="utf-8")
    # Force pathological retry behavior
    text = text.replace("max_retries = int(cfg.get(\"max_retries\", 3))", "max_retries = 10000")
    text = text.replace(
        "time.sleep(min(2 ** attempt, 8) + random.random())",
        "time.sleep(0)  # CASCADE_FAULT: no jitter / busy retry",
    )
    text = text.replace(
        "if attempt >= max_retries:",
        "if False and attempt >= max_retries:  # CASCADE_FAULT: never dead-letter",
    )
    path.write_text(text, encoding="utf-8")
    return "template infinite_retry_no_jitter"


def _tpl_pagination_bug(workspace: Path, m: MutationSpec) -> str:
    path = _safe_join(workspace, m.file or "app/api/routes/products.py")
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "offset = (page - 1) * page_size",
        "offset = page * page_size  # CASCADE_FAULT: off-by-one",
    )
    path.write_text(text, encoding="utf-8")
    return "template pagination_off_by_one"


def _tpl_auth_debug_flag(workspace: Path, m: MutationSpec) -> str:
    path = _safe_join(workspace, m.file or "app/api/auth.py")
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        'DEBUG_BYPASS_AUTH = os.environ.get("DEBUG_BYPASS_AUTH", "0") == "1"',
        'DEBUG_BYPASS_AUTH = True  # CASCADE_FAULT: auth bypass left on',
    )
    path.write_text(text, encoding="utf-8")
    return "template auth_bypass_debug"


def _tpl_stock_bug(workspace: Path, m: MutationSpec) -> str:
    path = _safe_join(workspace, m.file or "app/api/routes/orders.py")
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "product.stock -= item.qty",
        "pass  # CASCADE_FAULT: stock not decremented\n        # product.stock -= item.qty",
    )
    path.write_text(text, encoding="utf-8")
    return "template stock_not_decremented"


def _tpl_idempotency_bug(workspace: Path, m: MutationSpec) -> str:
    path = _safe_join(workspace, m.file or "app/api/routes/orders.py")
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "if existing is not None:\n        return existing",
        "if False and existing is not None:\n        return existing  # CASCADE_FAULT: idempotency broken",
    )
    path.write_text(text, encoding="utf-8")
    return "template broken_idempotency"


def _tpl_null_price(workspace: Path, m: MutationSpec) -> str:
    path = _safe_join(workspace, m.file or "app/api/routes/products.py")
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        '"price_cents": p.price_cents,',
        '"price_cents": None,  # CASCADE_FAULT: null price leak',
    )
    path.write_text(text, encoding="utf-8")
    return "template null_price_leak"

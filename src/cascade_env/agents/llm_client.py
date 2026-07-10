"""HTTP clients for OpenAI-compatible and Anthropic tool-calling APIs.

No hard dependency on ``openai`` / ``anthropic`` packages — uses ``httpx``.

Environment variables (any of):
  CASCADE_LLM_API_KEY | OPENAI_API_KEY | ANTHROPIC_API_KEY | XAI_API_KEY
  CASCADE_LLM_BASE_URL | OPENAI_BASE_URL
  CASCADE_LLM_MODEL | OPENAI_MODEL
  CASCADE_LLM_PROVIDER  openai | anthropic | openai_compatible | xai  (auto if unset)
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

from cascade_env.agents.tools_schema import anthropic_tools, openai_tools


@dataclass
class UsageStats:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    api_calls: int = 0

    def add(self, prompt: int = 0, completion: int = 0, total: int | None = None) -> None:
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.total_tokens += total if total is not None else (prompt + completion)
        self.api_calls += 1

    def as_dict(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "api_calls": self.api_calls,
        }


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ModelTurn:
    """One model response: optional text + zero or more tool calls."""

    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
    finish_reason: str | None = None


class LLMError(RuntimeError):
    """Provider/API failure."""


def resolve_llm_config(
    *,
    provider: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
) -> dict[str, str]:
    """Resolve provider/model/key/base_url from args and environment."""
    key = (
        api_key
        or os.environ.get("CASCADE_LLM_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("XAI_API_KEY")
        or os.environ.get("GROK_API_KEY")
        or ""
    )
    prov = (provider or os.environ.get("CASCADE_LLM_PROVIDER") or "").strip().lower()
    base = (
        base_url
        or os.environ.get("CASCADE_LLM_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or ""
    ).rstrip("/")
    mdl = (
        model
        or os.environ.get("CASCADE_LLM_MODEL")
        or os.environ.get("OPENAI_MODEL")
        or ""
    )

    if not prov:
        if base and "anthropic" in base:
            prov = "anthropic"
        elif base and ("x.ai" in base or "xai" in base):
            prov = "xai"
        elif os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("OPENAI_API_KEY"):
            prov = "anthropic"
        elif os.environ.get("XAI_API_KEY") or os.environ.get("GROK_API_KEY"):
            prov = "xai"
        else:
            prov = "openai"

    if prov in ("openai_compatible", "compatible"):
        prov = "openai"
    if prov == "xai":
        if not base:
            base = "https://api.x.ai/v1"
        if not mdl:
            mdl = "grok-3"
        prov = "openai"  # OpenAI-compatible wire format
    elif prov == "openai":
        if not base:
            base = "https://api.openai.com/v1"
        if not mdl:
            mdl = "gpt-4o"
    elif prov == "anthropic":
        if not base:
            base = "https://api.anthropic.com"
        if not mdl:
            mdl = "claude-sonnet-4-20250514"
    else:
        raise LLMError(f"Unknown CASCADE_LLM_PROVIDER: {prov!r}")

    return {
        "provider": prov,
        "model": mdl,
        "api_key": key,
        "base_url": base.rstrip("/"),
    }


class LLMClient:
    """Minimal chat+tools client for OpenAI-compatible or Anthropic APIs."""

    def __init__(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_s: float = 120.0,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        http_client: httpx.Client | None = None,
    ) -> None:
        cfg = resolve_llm_config(
            provider=provider, model=model, api_key=api_key, base_url=base_url
        )
        self.provider = cfg["provider"]
        self.model = cfg["model"]
        self.api_key = cfg["api_key"]
        self.base_url = cfg["base_url"]
        self.timeout_s = timeout_s
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.usage = UsageStats()
        self._owns_client = http_client is None
        self._client = http_client or httpx.Client(timeout=timeout_s)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> LLMClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def require_api_key(self) -> None:
        if not self.api_key:
            raise LLMError(
                "No LLM API key. Set CASCADE_LLM_API_KEY, OPENAI_API_KEY, "
                "ANTHROPIC_API_KEY, or XAI_API_KEY."
            )

    def complete(self, messages: list[dict[str, Any]]) -> ModelTurn:
        """Run one chat completion with Cascade tools attached."""
        self.require_api_key()
        if self.provider == "anthropic":
            return self._complete_anthropic(messages)
        return self._complete_openai(messages)

    # ── OpenAI-compatible ────────────────────────────────────────────

    def _complete_openai(self, messages: list[dict[str, Any]]) -> ModelTurn:
        url = f"{self.base_url}/chat/completions"
        body = {
            "model": self.model,
            "messages": messages,
            "tools": openai_tools(),
            "tool_choice": "auto",
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        resp = self._client.post(url, headers=headers, json=body)
        if resp.status_code >= 400:
            raise LLMError(f"OpenAI-compatible API {resp.status_code}: {resp.text[:800]}")
        data = resp.json()
        usage = data.get("usage") or {}
        self.usage.add(
            prompt=int(usage.get("prompt_tokens") or 0),
            completion=int(usage.get("completion_tokens") or 0),
            total=int(usage.get("total_tokens") or 0) or None,
        )
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        tool_calls: list[ToolCall] = []
        for tc in message.get("tool_calls") or []:
            fn = tc.get("function") or {}
            name = fn.get("name") or ""
            raw_args = fn.get("arguments") or "{}"
            args = _parse_args(raw_args)
            tool_calls.append(
                ToolCall(
                    id=tc.get("id") or f"call_{uuid.uuid4().hex[:8]}",
                    name=name,
                    arguments=args,
                )
            )
        return ModelTurn(
            content=message.get("content"),
            tool_calls=tool_calls,
            raw=data,
            finish_reason=choice.get("finish_reason"),
        )

    # ── Anthropic ────────────────────────────────────────────────────

    def _complete_anthropic(self, messages: list[dict[str, Any]]) -> ModelTurn:
        system, anthropic_msgs = _to_anthropic_messages(messages)
        url = f"{self.base_url}/v1/messages"
        body: dict[str, Any] = {
            "model": self.model,
            "messages": anthropic_msgs,
            "tools": anthropic_tools(),
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }
        if system:
            body["system"] = system
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        resp = self._client.post(url, headers=headers, json=body)
        if resp.status_code >= 400:
            raise LLMError(f"Anthropic API {resp.status_code}: {resp.text[:800]}")
        data = resp.json()
        usage = data.get("usage") or {}
        self.usage.add(
            prompt=int(usage.get("input_tokens") or 0),
            completion=int(usage.get("output_tokens") or 0),
        )
        content_blocks = data.get("content") or []
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in content_blocks:
            if block.get("type") == "text":
                text_parts.append(block.get("text") or "")
            elif block.get("type") == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.get("id") or f"toolu_{uuid.uuid4().hex[:8]}",
                        name=block.get("name") or "",
                        arguments=dict(block.get("input") or {}),
                    )
                )
        return ModelTurn(
            content="\n".join(text_parts) if text_parts else None,
            tool_calls=tool_calls,
            raw=data,
            finish_reason=data.get("stop_reason"),
        )


def estimate_cost_usd(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> float | None:
    """Rough USD estimate for common models. Returns None if unknown."""
    # prices per 1M tokens (input, output) — approximate public list prices
    table: dict[str, tuple[float, float]] = {
        "gpt-4o": (2.50, 10.00),
        "gpt-4o-mini": (0.15, 0.60),
        "gpt-4.1": (2.00, 8.00),
        "gpt-4.1-mini": (0.40, 1.60),
        "o4-mini": (1.10, 4.40),
        "claude-sonnet-4-20250514": (3.00, 15.00),
        "claude-3-5-sonnet-latest": (3.00, 15.00),
        "claude-3-5-haiku-latest": (0.80, 4.00),
        "grok-3": (3.00, 15.00),
        "grok-3-mini": (0.30, 0.50),
        "grok-2": (2.00, 10.00),
    }
    key = model.lower().strip()
    rates = table.get(key)
    if rates is None:
        # fuzzy prefix match
        for name, r in table.items():
            if key.startswith(name) or name.startswith(key):
                rates = r
                break
    if rates is None:
        return None
    inp, out = rates
    return (prompt_tokens / 1_000_000.0) * inp + (completion_tokens / 1_000_000.0) * out


def _parse_args(raw: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    text = (raw or "").strip()
    if not text:
        return {}
    try:
        val = json.loads(text)
        return val if isinstance(val, dict) else {"value": val}
    except json.JSONDecodeError:
        # model sometimes wraps JSON in fences
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                val = json.loads(m.group(0))
                return val if isinstance(val, dict) else {"value": val}
            except json.JSONDecodeError:
                pass
        return {"_raw": text}


def _to_anthropic_messages(
    messages: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    """Convert OpenAI-style messages to Anthropic format."""
    system_parts: list[str] = []
    out: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role")
        if role == "system":
            system_parts.append(str(msg.get("content") or ""))
            continue
        if role == "user":
            out.append({"role": "user", "content": msg.get("content") or ""})
            continue
        if role == "assistant":
            content_blocks: list[dict[str, Any]] = []
            text = msg.get("content")
            if text:
                content_blocks.append({"type": "text", "text": text})
            for tc in msg.get("tool_calls") or []:
                fn = tc.get("function") or {}
                args = fn.get("arguments")
                if isinstance(args, str):
                    args = _parse_args(args)
                content_blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc.get("id") or f"toolu_{uuid.uuid4().hex[:8]}",
                        "name": fn.get("name") or "",
                        "input": args or {},
                    }
                )
            if not content_blocks:
                content_blocks = [{"type": "text", "text": ""}]
            out.append({"role": "assistant", "content": content_blocks})
            continue
        if role == "tool":
            # Anthropic expects tool_result as user content blocks.
            block = {
                "type": "tool_result",
                "tool_use_id": msg.get("tool_call_id") or "",
                "content": msg.get("content") or "",
            }
            if out and out[-1].get("role") == "user" and isinstance(out[-1].get("content"), list):
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
            continue
    return "\n\n".join(p for p in system_parts if p), out

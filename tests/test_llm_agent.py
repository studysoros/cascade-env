"""Unit tests for LLM tool schema, client parsing, and agent loop (mocked HTTP)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from cascade_env.agents.llm_agent import (
    append_assistant_turn,
    build_initial_messages,
    tool_call_to_action,
    run_llm_episode,
)
from cascade_env.agents.llm_client import (
    LLMClient,
    ToolCall,
    _parse_args,
    estimate_cost_usd,
    resolve_llm_config,
)
from cascade_env.agents.tools_schema import (
    cascade_tool_name,
    openai_tools,
    wire_tool_name,
)
from cascade_env.agents.eval import format_markdown_table


def test_tool_name_roundtrip():
    assert cascade_tool_name("files_read") == "files.read"
    assert cascade_tool_name("files.read") == "files.read"
    assert wire_tool_name("submit.done") == "submit_done"
    assert cascade_tool_name("submit_done") == "submit.done"


def test_openai_tools_have_valid_names():
    tools = openai_tools()
    assert len(tools) >= 10
    for t in tools:
        name = t["function"]["name"]
        assert name.replace("_", "").isalnum()
        assert "." not in name


def test_tool_call_to_action():
    tc = ToolCall(id="c1", name="http_request", arguments={"path": "/ready"})
    action = tool_call_to_action(tc)
    assert action == {"tool": "http.request", "args": {"path": "/ready", "method": "GET"}}


def test_parse_args_json_and_fenced():
    assert _parse_args('{"path": "a"}') == {"path": "a"}
    assert _parse_args('```json\n{"x": 1}\n```') == {"x": 1}


def test_resolve_llm_config_xai(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("XAI_API_KEY", "xai-test")
    monkeypatch.delenv("CASCADE_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("CASCADE_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("CASCADE_LLM_MODEL", raising=False)
    cfg = resolve_llm_config()
    assert cfg["provider"] == "openai"  # wire format
    assert "x.ai" in cfg["base_url"]
    assert cfg["api_key"] == "xai-test"
    assert cfg["model"]


def test_estimate_cost():
    c = estimate_cost_usd("gpt-4o", 1_000_000, 0)
    assert c is not None and abs(c - 2.5) < 1e-6
    assert estimate_cost_usd("totally-unknown-model-xyz", 100, 100) is None


def test_build_initial_messages():
    obs = {
        "task": {
            "id": "community.T3.worker_disabled_config.v1",
            "family": "config_repair",
            "tier": "L1",
            "title": "Worker disabled",
            "description": "Worker is off.",
            "public_success_criteria": ["worker processes jobs"],
            "constraints": [],
        },
        "budget": {"steps_remaining": 40},
        "services": [{"name": "api", "status": "running"}],
        "runtime": "local",
        "step": 0,
    }
    msgs = build_initial_messages(obs)
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    assert "Worker disabled" in msgs[1]["content"]


def test_openai_client_parses_tool_calls():
    def handler(request: httpx.Request) -> httpx.Response:
        body = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "files_list",
                                    "arguments": '{"path": "configs"}',
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport)
    client = LLMClient(
        provider="openai",
        model="gpt-4o",
        api_key="sk-test",
        base_url="https://api.openai.com/v1",
        http_client=http,
    )
    turn = client.complete([{"role": "user", "content": "hi"}])
    assert len(turn.tool_calls) == 1
    assert turn.tool_calls[0].name == "files_list"
    assert turn.tool_calls[0].arguments == {"path": "configs"}
    assert client.usage.prompt_tokens == 10
    client.close()


def test_anthropic_client_parses_tool_use():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "messages" in str(request.url)
        body = {
            "content": [
                {"type": "text", "text": "looking"},
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "http_request",
                    "input": {"path": "/ready"},
                },
            ],
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 20, "output_tokens": 8},
        }
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport)
    client = LLMClient(
        provider="anthropic",
        model="claude-sonnet-4-20250514",
        api_key="sk-ant-test",
        base_url="https://api.anthropic.com",
        http_client=http,
    )
    turn = client.complete(
        [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "fix it"},
        ]
    )
    assert turn.content and "looking" in turn.content
    assert turn.tool_calls[0].name == "http_request"
    assert turn.tool_calls[0].arguments["path"] == "/ready"
    client.close()


class _FakeEnv:
    """Minimal env that succeeds after http.request then submit.done."""

    def __init__(self) -> None:
        self.n = 0
        self.closed = False

    def reset(self, seed: int = 0, options: dict | None = None) -> tuple[str, dict]:
        obs = {
            "episode_id": "ep_test",
            "step": 0,
            "task": {
                "id": "community.T3.worker_disabled_config.v1",
                "family": "config_repair",
                "tier": "L1",
                "title": "t",
                "description": "d",
                "public_success_criteria": [],
                "constraints": [],
            },
            "budget": {"steps_remaining": 10, "max_steps": 10},
            "services": [],
            "runtime": "local",
            "phase": "AGENT_CONTROL",
        }
        return json.dumps(obs), {"episode_id": "ep_test", "obs": obs}

    def step(self, action: dict[str, Any]):
        self.n += 1
        tool = action.get("tool")
        if tool == "submit.done":
            info = {
                "episode_id": "ep_test",
                "success": True,
                "terminal_reward": 0.99,
                "verifiers": [{"id": "health", "passed": True}],
                "trajectory_path": None,
            }
            obs = {"step": self.n, "task": {"id": "community.T3.worker_disabled_config.v1"}}
            return json.dumps(obs), 0.99, True, False, info
        tr = {"ok": True, "tool": tool, "stdout": "ok", "data": {}}
        info = {
            "episode_id": "ep_test",
            "tool_result": tr,
            "success": False,
        }
        obs = {
            "step": self.n,
            "task": {"id": "community.T3.worker_disabled_config.v1"},
            "budget": {"steps_remaining": 10 - self.n},
            "services": [],
            "runtime": "local",
        }
        return json.dumps(obs), -0.001, False, False, info

    def close(self) -> None:
        self.closed = True


def test_run_llm_episode_with_scripted_tool_sequence():
    """Drive agent loop with a mock model that issues two tool calls."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            msg = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {
                            "name": "http_request",
                            "arguments": '{"path": "/ready"}',
                        },
                    }
                ],
            }
        else:
            msg = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "c2",
                        "type": "function",
                        "function": {"name": "submit_done", "arguments": "{}"},
                    }
                ],
            }
        body = {
            "choices": [{"message": msg, "finish_reason": "tool_calls"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        }
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport)
    client = LLMClient(
        provider="openai",
        model="gpt-4o",
        api_key="sk-test",
        base_url="https://example.test/v1",
        http_client=http,
    )
    env = _FakeEnv()
    outcome = run_llm_episode(env, client, seed=0, verbose=False)
    client.close()
    assert outcome.success is True
    assert outcome.steps == 2
    assert outcome.error is None
    assert client.usage.api_calls == 2


def test_append_assistant_turn_shape():
    from cascade_env.agents.llm_client import ModelTurn

    messages: list[dict] = []
    turn = ModelTurn(
        content=None,
        tool_calls=[ToolCall(id="x", name="files_list", arguments={"path": "."})],
    )
    append_assistant_turn(messages, turn)
    assert messages[0]["role"] == "assistant"
    assert messages[0]["tool_calls"][0]["function"]["name"] == "files_list"


def test_format_markdown_table():
    summary = {
        "meta": {
            "model": "scripted",
            "date": "2026-07-10",
            "pack": "community",
            "runtime": "local",
        },
        "summary": {
            "pass_at_1": 0.8,
            "avg_steps": 10.0,
            "estimated_cost_usd_total": None,
        },
        "tasks": {
            "community.T2.pagination_off_by_one.v1": {
                "pass_at_1": 1.0,
                "n": 1,
                "avg_steps": 8.0,
                "avg_terminal_reward": 0.99,
            }
        },
    }
    md = format_markdown_table(summary)
    assert "pass@1" in md
    assert "0.80" in md
    assert "community.T2" in md

"""
Stub showing how to wire an LLM tool-calling loop to Cascade.

For a **real** OpenAI-compatible / Anthropic client, use:
  uv run python examples/llm_tool_loop.py --task community.T3.worker_disabled_config.v1

Replace `call_model` below with your lab's inference client if you prefer a custom harness.
"""

from __future__ import annotations

import json
from typing import Any

import cascade_env
import gymnasium as gym


def call_model(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a single tool call. Replace with real LLM."""
    # Naive heuristic demo — not a real model
    last = messages[-1]["content"] if messages else ""
    if "submit" in last.lower():
        return {"tool": "submit.done", "args": {}}
    return {"tool": "http.request", "args": {"method": "GET", "path": "/ready"}}


def main() -> None:
    cascade_env.register_envs()
    env = gym.make("Cascade-v0", runtime="local", task_id="community.T3.worker_disabled_config.v1")
    try:
        obs_s, info = env.reset(seed=0)
        obs = json.loads(obs_s)
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": "You are an SRE agent. Use tools to repair the sandbox system.",
            },
            {
                "role": "user",
                "content": obs["task"]["description"],
            },
        ]
        terminated = truncated = False
        while not (terminated or truncated):
            action = call_model(messages)
            # Multi-tool model outputs: serialize into multiple env.step calls
            obs_s, reward, terminated, truncated, info = env.step(action)
            obs = json.loads(obs_s)
            messages.append({"role": "assistant", "content": json.dumps(action)})
            messages.append(
                {
                    "role": "tool",
                    "content": json.dumps(info.get("tool_result") or info.get("success")),
                }
            )
        print("done success=", info.get("success"), "R=", info.get("terminal_reward"))
    finally:
        env.close()


if __name__ == "__main__":
    main()

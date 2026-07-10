#!/usr/bin/env python3
"""
Real LLM tool-calling loop against Cascade-v0.

Supports OpenAI-compatible APIs (OpenAI, xAI/Grok, vLLM, etc.) and Anthropic.

Environment:
  CASCADE_LLM_API_KEY | OPENAI_API_KEY | ANTHROPIC_API_KEY | XAI_API_KEY
  CASCADE_LLM_PROVIDER   openai | anthropic | xai   (auto-detected if unset)
  CASCADE_LLM_BASE_URL   e.g. https://api.openai.com/v1  or  https://api.x.ai/v1
  CASCADE_LLM_MODEL      e.g. gpt-4o, grok-3, claude-sonnet-4-20250514

Examples:
  # OpenAI
  set OPENAI_API_KEY=sk-...
  uv run python examples/llm_tool_loop.py --task community.T3.worker_disabled_config.v1

  # xAI Grok
  set XAI_API_KEY=xai-...
  set CASCADE_LLM_PROVIDER=xai
  uv run python examples/llm_tool_loop.py --task community.T2.pagination_off_by_one.v1

  # Anthropic
  set ANTHROPIC_API_KEY=sk-ant-...
  set CASCADE_LLM_PROVIDER=anthropic
  uv run python examples/llm_tool_loop.py --task community.T3.worker_disabled_config.v1
"""

from __future__ import annotations

import argparse
import json
import sys

import cascade_env
import gymnasium as gym

from cascade_env.agents.llm_agent import run_llm_episode
from cascade_env.agents.llm_client import LLMClient, LLMError


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Cascade LLM tool-calling episode")
    p.add_argument(
        "--task",
        default="community.T3.worker_disabled_config.v1",
        help="Task id (default: T3 config repair)",
    )
    p.add_argument("--pack", default="community")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--runtime", default="local", choices=["local", "compose"])
    p.add_argument("--max-steps", type=int, default=40)
    p.add_argument("--provider", default=None, help="openai | anthropic | xai")
    p.add_argument("--model", default=None)
    p.add_argument("--base-url", default=None)
    p.add_argument("--api-key", default=None, help="Override env API key")
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    cascade_env.register_envs()
    try:
        client = LLMClient(
            provider=args.provider,
            model=args.model,
            api_key=args.api_key,
            base_url=args.base_url,
            temperature=args.temperature,
        )
        client.require_api_key()
    except LLMError as exc:
        print(f"error: {exc}", file=sys.stderr)
        print(
            "Set CASCADE_LLM_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY / XAI_API_KEY.",
            file=sys.stderr,
        )
        return 2

    if not args.quiet:
        print(f"provider={client.provider} model={client.model} base={client.base_url}")

    env = gym.make(
        "Cascade-v0",
        pack=args.pack,
        runtime=args.runtime,
        task_id=args.task,
        max_steps=args.max_steps,
    )
    try:
        outcome = run_llm_episode(
            env,
            client,
            seed=args.seed,
            task_id=args.task,
            verbose=not args.quiet,
        )
    finally:
        env.close()
        client.close()

    print(json.dumps(outcome.as_dict(), indent=2, ensure_ascii=False))
    return 0 if outcome.success and not outcome.error else 1


if __name__ == "__main__":
    raise SystemExit(main())

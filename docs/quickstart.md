# Cascade quickstart

## Install

Use [uv](https://docs.astral.sh/uv/) (not pip):

```bash
uv sync --extra dev
uv run cascade doctor
```

## First episode

```bash
uv run cascade list-tasks
uv run cascade run-episode --task community.T2.pagination_off_by_one.v1 --agent scripted
```

## Compose runtime (Docker)

Default runtime is `local` (no Docker). For Postgres/Redis fidelity:

```bash
# start Docker Desktop / dockerd first
uv run python scripts/pull_images.py
uv run cascade doctor
uv run cascade run-episode --runtime compose --agent scripted \
  --task community.T2.pagination_off_by_one.v1
uv run pytest -q -m docker   # integration test when daemon is up
```

## Python

```bash
uv run python examples/scripted_solve.py
uv run python examples/llm_tool_loop_stub.py   # offline stub
# Real LLM (set OPENAI_API_KEY / ANTHROPIC_API_KEY / XAI_API_KEY):
# uv run python examples/llm_tool_loop.py --task community.T3.worker_disabled_config.v1
```

## Baselines / pass-rate card

```bash
# Scripted T1–T5 card → JSON + markdown under docs/artifacts/
uv run cascade eval-baselines --agent scripted --seeds 0

# Frontier model (API key required)
# uv run cascade eval-baselines --agent llm --provider openai --model gpt-4o --seeds 0
```

See [`baselines.md`](./baselines.md).

## Safety

Cascade is a **sandbox**. Never attach tools to production systems.

## Status / handoff

What is built vs design plan: [`STATUS.md`](./STATUS.md)

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
uv run python examples/llm_tool_loop_stub.py
```

## Safety

Cascade is a **sandbox**. Never attach tools to production systems.

## Status / handoff

What is built vs design plan: [`STATUS.md`](./STATUS.md)

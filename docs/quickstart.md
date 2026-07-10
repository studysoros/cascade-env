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

## Python

```bash
uv run python examples/scripted_solve.py
uv run python examples/llm_tool_loop_stub.py
```

## Safety

Cascade is a **sandbox**. Never attach tools to production systems.

## Status / handoff

What is built vs design plan: [`STATUS.md`](./STATUS.md)

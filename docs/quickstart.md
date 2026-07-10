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

## HTTP rollout server (remote trainers)

Same Gymnasium step semantics over HTTP (API-key auth). OpenAPI at `/docs`.

```bash
# Terminal A — start server (prints generated key if --api-key omitted)
uv run cascade serve --api-key dev-key

# Terminal B — complete one scripted episode remotely
uv run python examples/remote_client.py --api-key dev-key \
  --task community.T2.pagination_off_by_one.v1
```

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/health` | Liveness (no auth) |
| `GET` | `/v1/metrics` | Counters + provision/step/verify histograms (auth) |
| `POST` | `/v1/episodes` | Create / reset episode |
| `POST` | `/v1/episodes/{id}/step` | One tool action |
| `POST` / `DELETE` | `/v1/episodes/{id}/close` or `…/{id}` | Teardown |

Auth: `X-API-Key: <key>` or `Authorization: Bearer <key>` (`CASCADE_SERVER_API_KEY`).

Capacity: `CASCADE_MAX_PARALLEL_EPISODES` (default `1`; Desktop-safe). Over capacity returns **429** `CAPACITY`. Episodes past `CASCADE_EPISODE_TTL_S` (default 2h) are reaped.

## Safety

Cascade is a **sandbox**. Never attach tools to production systems.

## Status / handoff

What is built vs design plan: [`STATUS.md`](./STATUS.md)

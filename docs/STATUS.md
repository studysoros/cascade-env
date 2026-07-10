# Cascade — build status & session handoff

**Last updated:** 2026-07-10 (PR12 concurrency guards & metrics)  
**Package manager:** `uv` only (`uv sync --extra dev`, `uv run …`) — not pip  
**Lockfile:** `uv.lock` (committed)  
**Design source of truth:** [`design-cascade.md`](./design-cascade.md)

Use this file when starting a **new session**. Point the agent at:

> Read `docs/STATUS.md` and `docs/design-cascade.md`. Continue from the highest-priority open work package. Use `uv`, not pip.

---

## Honest answer: what was built vs the plan

We did **not** implement every PR in the design as separate mergeable PRs. We shipped a **working vertical product** in one pass, with several design items only partially done or deferred.

### PR plan tracker (design § PR Plan)

| PR | Title | Status | Notes |
|----|-------|--------|-------|
| PR1 | Repo skeleton & packaging | **Done** | `pyproject.toml`, README, LICENSE, AGENTS.md; use **`uv sync`** |
| PR2 | Types, ToolResult, task schema | **Done** | Pydantic models; no separate `task_schema.json` file |
| PR3a | Shopstack Dockerfiles + compose | **Done** | Bind-mount workspace; internal network; labels; digest pins via `image-pins.env` |
| PR3b | Public tests + golden path | **Done** | `scenarios/shopstack/tests/public` + verifier golden paths |
| PR3c | Hidden tests volume layout | **Partial** | Family/hidden checks live in Python verifiers; no separate hidden test mount tree |
| PR4 | Compose lifecycle | **Done** | `runtime/compose.py` provision/health/tools/teardown via `docker compose exec` |
| PR4b | Image digests / pull script | **Done** | `scripts/pull_images.py` (+ `.sh`); `cascade doctor` image probes |
| PR4c | GC / reaper | **Done** | `cascade gc` cleans episode dirs + labeled compose projects |
| PR4d | Slice 0 smoke script | **Not done** | Gym path covers inject→verify; no dedicated `scripts/smoke_episode.py` |
| PR5 | Tool adapters | **Done** | files/http/logs/services/db/shell/tests/submit (local + compose) |
| PR6 | Verifiers + C1–C7 | **Partial** | Multi-verifier + sparse reward work; cheat checks are lighter than full C1–C7 suite; no `test_cheat_catalog.py` |
| PR7 | Mutators + T1–T3 | **Done** | Plus T4–T8 (L3 multi-fault) |
| PR8 | Gymnasium Cascade-v0 + trajectories | **Done** | Verified with scripted agent |
| PR9 | Example agents | **Done** | scripted + LLM stub + real `llm_tool_loop` + eval harness |
| PR10 | CI Linux + security docs | **Not done** | No GitHub Actions; no `docs/security.md` |
| PR11 | HTTP rollout server | **Done** | `cascade serve` + FastAPI `/v1/episodes`; WP4 |
| PR12 | Concurrency guards & metrics | **Done** | max_parallel 429; provision/step/verify histograms; `/v1/metrics`; episode TTL reaper; debug profile guard |
| PR13 | T4–T5 + sampling | **Mostly done** | Tasks exist; sampling is basic `sample_task_id` |
| PR14 | Licensing / commercial docs | **Done** | [`commercial.md`](./commercial.md) + holdout load path |
| PR15 | Expanded red-team suite | **Not done** | |

### What *is* solid today

- Real Gymnasium env: `Cascade-v0`
- Live Shopstack (API + worker + SQLite/file-queue) under **`runtime=local`**
- Live Shopstack (API + worker + Postgres + Redis) under **`runtime=compose`**
- Multi-verifier terminal reward (HTTP via runtime tools — works without host ports)
- Community tasks **T1–T8** (3× L3 multi-fault with red herrings + `metadata.hidden_checks`)
- Sealed **holdout pack** scaffold (`scripts/scaffold_holdout_pack.py`, gitignored `packs/holdout/`)
- Holdout load via `CASCADE_HOLDOUT_DIR` / `CASCADE_EXTRA_PACKS` / absolute `--pack` path
- Scripted baseline solves several L1–L2 tasks (R≈0.994); L3 scripted pass ~0 (headroom)
- Measured scripted T1–T5 card: **pass@1=0.80** (`docs/artifacts/baseline-scripted-t1-t5.json`)
- Real LLM tool loop (`examples/llm_tool_loop.py`) + `cascade eval-baselines` (OpenAI-compatible / Anthropic / xAI)
- `uv run cascade doctor | list-tasks | run-episode | eval-baselines | gc | serve`
- HTTP metrics: `GET /v1/metrics` (auth) — counters + provision/step/verify histograms
- Docs: [`commercial.md`](./commercial.md), [`baselines.md`](./baselines.md), compose notes in [`windows.md`](./windows.md) / [`quickstart.md`](./quickstart.md)

### Default runtime

| Runtime | Status |
|---------|--------|
| `local` | **Primary / working** — no Docker |
| `compose` | **Working** — Docker Desktop / Engine; internal network; host tools via `docker compose exec` |

---

## Work packages

### WP1 — Harder L3 tasks + private holdout pack — **Done** (2026-07-10)

**Done when (met):**
- ≥3 L3 public tasks (T6–T8)
- Holdout pack loads via path/env (`CASCADE_HOLDOUT_DIR`, `CASCADE_EXTRA_PACKS`)
- README documents holdout SKU
- `docs/commercial.md` + `docs/baselines.md`

### WP2 — Harden `runtime=compose` — **Done** (2026-07-10)

**Goal:** Docker fidelity path works end-to-end on Desktop + Linux.

**Done:**
- Workspace bind-mount (`CASCADE_WORKSPACE` → `/workspace`)
- Host↔stack HTTP without fixed host ports (`docker compose exec` + in-container helpers)
- Image pins + `scripts/pull_images.py` / `pull_images.sh` (+ `--write-digests`)
- `cascade doctor` daemon/compose/image checks; `cascade gc` reaps compose projects
- Integration test `tests/test_compose_runtime.py` (`@pytest.mark.docker`)
- Verified twice: `uv run cascade run-episode --runtime compose --agent scripted --task community.T2.pagination_off_by_one.v1` → success, R=0.994

**Optional remaining (not blocking WP2):**
- Linux CI job for `-m docker`
- Debug profile auto-path in CLI (`CASCADE_COMPOSE_DEBUG=1` already supported)

### WP3 — Real model baseline + pass-rate card — **Code done; frontier numbers pending API key** (2026-07-10)

**Goal:** Lab-facing capability signal.

**Done:**
- `examples/llm_tool_loop.py` — OpenAI-compatible + Anthropic clients via `httpx` (env API key)
- Agent modules: `agents/tools_schema.py`, `llm_client.py`, `llm_agent.py`, `eval.py`
- Eval harness: `cascade eval-baselines` / `scripts/eval_baselines.py` → JSON + markdown card
- CLI: `run-episode --agent llm` with `--provider/--model/--base-url/--api-key`
- Unit tests: `tests/test_llm_agent.py` (mocked HTTP; no network)
- Checked-in measured **scripted** T1–T5 card: pass@1=0.80, avg steps=7.0  
  (`docs/artifacts/baseline-scripted-t1-t5.json`)
- [`docs/baselines.md`](./baselines.md) updated with harness docs + measured table

**Remaining for strict “Done when” (one frontier model T1–T5 table):**
No LLM API key was available in this session. With a key:

```bash
uv run cascade eval-baselines --agent llm --provider xai --model grok-3 --seeds 0 \
  --out docs/artifacts/baseline-grok-3-t1-t5.json
# paste the markdown card into docs/baselines.md Frontier section
```

Then mark WP3 fully **Done**.

### WP4 — HTTP rollout server — **Done** (2026-07-10)

**Goal:** Multi-tenant / remote trainers (design PR11).

**Done:**
- `src/cascade_env/server/` FastAPI: `POST /v1/episodes`, `POST …/step`, `POST|DELETE …/close`
- Auth via `X-API-Key` or `Authorization: Bearer` (`CASCADE_SERVER_API_KEY`)
- Feature flag `CASCADE_ENABLE_HTTP_SERVER` + opt-in CLI `cascade serve` (sets flag on start)
- OpenAPI at `/docs`; health at `/health` (unauthenticated)
- Example: `examples/remote_client.py`
- Tests: `tests/test_server.py` (auth, capacity 429, full scripted episode over HTTP)

**Done when (met):** remote TestClient / `examples/remote_client.py` completes one scripted episode over HTTP.

```bash
# Terminal A
uv run cascade serve --api-key dev-key
# Terminal B
uv run python examples/remote_client.py --api-key dev-key \
  --task community.T2.pagination_off_by_one.v1
```

### PR12 — Concurrency guards & provision metrics — **Done** (2026-07-10)

**Goal:** Desktop-safe parallelism + operability signals (design PR12).

**Done:**
- `max_parallel_episodes` enforced on HTTP create (429 `CAPACITY` + `capacity_rejects` counter)
- Process-local metrics: `src/cascade_env/metrics.py` (counters + fixed-bucket histograms)
- Wired in `EpisodeManager`: `provision_ms`, `step_ms`, `verify_ms` + success/fail counters
- `GET /v1/metrics` (auth) returns snapshot JSON
- Episode TTL reaper on `SessionStore` (`CASCADE_EPISODE_TTL_S`, default 7200s); step on expired → 410 `EXPIRED`
- Compose debug profile refuses when `max_parallel_episodes > 1` (host ports are single-episode only)
- Tests: `tests/test_metrics.py`, extended `tests/test_server.py`

```bash
uv run cascade serve --api-key dev-key
# after some rollouts:
curl -H "X-API-Key: dev-key" http://127.0.0.1:8765/v1/metrics
```

### Suggested next

| Priority | Item | Notes |
|----------|------|-------|
| 1 | WP3 frontier baseline numbers | Needs API key; fill `docs/baselines.md` Frontier section |
| 2 | PR10 CI Linux + security docs | GitHub Actions + `docs/security.md` |
| 3 | PR4d smoke script | `scripts/smoke_episode.py` |
| 4 | PR15 expanded red-team suite | Beyond light C1–C7 |

---

## How to continue in another session (recommended)

1. **Keep this file updated** after each session (status + date).
2. In the new chat, say something like:

```text
Continue Cascade from docs/STATUS.md.
Use uv only (uv sync, uv run …).
Implement the highest-priority open work package.
```

Or finish WP3 frontier row:

```text
Continue Cascade from docs/STATUS.md.
Run frontier baseline: set XAI_API_KEY / OPENAI_API_KEY and
uv run cascade eval-baselines --agent llm --provider xai --model grok-3 --seeds 0
```

3. Optionally attach or `@` mention:
   - `docs/STATUS.md`
   - `docs/design-cascade.md`
   - `AGENTS.md`

**Why markdown > only this chat:** sessions lose context; the repo does not. A status file is the handoff protocol labs/agents actually use.

**When to stay in the current session:** if you are mid-debug on one WP and context is already loaded. Otherwise start fresh with STATUS.md to avoid stale assumptions.

---

## Commands (uv)

```bash
uv sync --extra dev
uv run cascade doctor
uv run cascade list-tasks
uv run cascade list-tasks --pack holdout   # after scaffold / CASCADE_HOLDOUT_DIR
uv run cascade run-episode --task community.T2.pagination_off_by_one.v1 --agent scripted
uv run cascade run-episode --runtime compose --agent scripted --task community.T2.pagination_off_by_one.v1
uv run cascade eval-baselines --agent scripted --seeds 0 --out docs/artifacts/baseline-scripted-t1-t5.json
# LLM (requires API key):
# uv run cascade run-episode --agent llm --task community.T3.worker_disabled_config.v1
# uv run python examples/llm_tool_loop.py --provider xai --model grok-3
uv run python scripts/pull_images.py
uv run python scripts/scaffold_holdout_pack.py
uv run pytest -q
uv run pytest -q -m docker
uv run python examples/scripted_solve.py
# HTTP rollout server (remote trainers):
# uv run cascade serve --api-key dev-key
# uv run python examples/remote_client.py --api-key dev-key
# curl -H "X-API-Key: dev-key" http://127.0.0.1:8765/v1/metrics
```

---

## Safety

Sandbox only. Never attach Cascade tools to real production credentials or networks.

# Cascade — build status & session handoff

**Last updated:** 2026-07-10  
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
| PR3a | Shopstack Dockerfiles + compose | **Partial** | Compose + Dockerfiles exist; **not fully verified** (Docker daemon was down); no digest pins |
| PR3b | Public tests + golden path | **Done** | `scenarios/shopstack/tests/public` + verifier golden paths |
| PR3c | Hidden tests volume layout | **Partial** | Family/hidden checks live in Python verifiers; no separate hidden test mount tree |
| PR4 | Compose lifecycle | **Partial** | Local runtime is production path; `runtime/compose.py` is scaffold only |
| PR4b | Image digests / pull script | **Not done** | |
| PR4c | GC / reaper | **Partial** | `cascade gc` for workspace dirs; no Docker project reaper |
| PR4d | Slice 0 smoke script | **Not done** | Gym path covers inject→verify; no dedicated `scripts/smoke_episode.py` |
| PR5 | Tool adapters | **Done** | files/http/logs/services/db/shell/tests/submit (local runtime) |
| PR6 | Verifiers + C1–C7 | **Partial** | Multi-verifier + sparse reward work; cheat checks are lighter than full C1–C7 suite; no `test_cheat_catalog.py` |
| PR7 | Mutators + T1–T3 | **Done** | Plus T4–T8 (L3 multi-fault) |
| PR8 | Gymnasium Cascade-v0 + trajectories | **Done** | Verified with scripted agent |
| PR9 | Example agents | **Done** | scripted + LLM stub + random rollout |
| PR10 | CI Linux + security docs | **Not done** | No GitHub Actions; no `docs/security.md` |
| PR11 | HTTP rollout server | **Not done** | Post-MVP / suggested next #4 |
| PR12 | Concurrency guards & metrics | **Not done** | |
| PR13 | T4–T5 + sampling | **Mostly done** | Tasks exist; sampling is basic `sample_task_id` |
| PR14 | Licensing / commercial docs | **Done** | [`commercial.md`](./commercial.md) + holdout load path |
| PR15 | Expanded red-team suite | **Not done** | |

### What *is* solid today

- Real Gymnasium env: `Cascade-v0`
- Live Shopstack (API + worker + SQLite/file-queue) under **`runtime=local`**
- Multi-verifier terminal reward
- Community tasks **T1–T8** (3× L3 multi-fault with red herrings + `metadata.hidden_checks`)
- Sealed **holdout pack** scaffold (`scripts/scaffold_holdout_pack.py`, gitignored `packs/holdout/`)
- Holdout load via `CASCADE_HOLDOUT_DIR` / `CASCADE_EXTRA_PACKS` / absolute `--pack` path
- Scripted baseline solves several L1–L2 tasks (R≈0.994); L3 scripted pass ~0 (headroom)
- `uv run cascade doctor | list-tasks | run-episode`
- Docs: [`commercial.md`](./commercial.md), [`baselines.md`](./baselines.md)

### Default runtime

| Runtime | Status |
|---------|--------|
| `local` | **Primary / working** — no Docker |
| `compose` | Scaffold — needs Docker Desktop + hardening |

---

## Work packages

### WP1 — Harder L3 tasks + private holdout pack — **Done** (2026-07-10)

**Done when (met):**
- ≥3 L3 public tasks (T6–T8)
- Holdout pack loads via path/env (`CASCADE_HOLDOUT_DIR`, `CASCADE_EXTRA_PACKS`)
- README documents holdout SKU
- `docs/commercial.md` + `docs/baselines.md`

### WP2 — Harden `runtime=compose`  ← **next priority**

**Goal:** Docker fidelity path works end-to-end on Desktop + Linux.

**Do:**
- Start Docker Desktop / use Linux CI
- Wire workspace volume correctly into compose episodes
- Fix host↔internal network HTTP (no fixed host ports, or debug profile)
- Image digests + `scripts/pull_images.sh`
- `cascade doctor` image/daemon checks
- Integration test marked `@pytest.mark.docker`

**Done when:** `uv run cascade run-episode --runtime compose --agent scripted --task …` succeeds twice in a row.

### WP3 — Real model baseline + pass-rate card

**Goal:** Lab-facing capability signal.

**Do:**
- Implement `examples/llm_tool_loop.py` with OpenAI-compatible or Anthropic client (env API key)
- Eval harness: run N seeds × task set, write JSON summary
- Publish `docs/baselines.md` (model, date, pass@1, avg steps, cost if known)

**Done when:** one frontier model has a checked-in baseline table for T1–T5.

### WP4 — HTTP rollout server

**Goal:** Multi-tenant / remote trainers (design PR11).

**Do:**
- `src/cascade_env/server/` FastAPI: create episode, step, close
- Auth via API key header
- Feature flag / `cascade serve`
- OpenAPI + example remote client

**Done when:** remote client can complete one scripted episode over HTTP.

---

## How to continue in another session (recommended)

1. **Keep this file updated** after each session (status + date).
2. In the new chat, say something like:

```text
Continue Cascade from docs/STATUS.md.
Use uv only (uv sync, uv run …).
Implement work package WP2 (compose runtime).
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
uv run cascade run-episode --task community.T6.checkout_cascade.v1 --agent scripted
uv run python scripts/scaffold_holdout_pack.py
uv run pytest -q
uv run python examples/scripted_solve.py
```

---

## Safety

Sandbox only. Never attach Cascade tools to real production credentials or networks.

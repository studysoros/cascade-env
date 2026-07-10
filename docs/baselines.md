# Cascade baselines

Measured against **Shopstack** with **`runtime=local`** unless noted. Use `uv` only.

**Last updated:** 2026-07-10

## How to measure (eval harness)

```bash
uv sync --extra dev

# Scripted control card (no API key) — default tasks = community T1–T5
uv run cascade eval-baselines --agent scripted --seeds 0 \
  --out docs/artifacts/baseline-scripted-t1-t5.json

# Frontier model (OpenAI-compatible or Anthropic)
# set OPENAI_API_KEY / ANTHROPIC_API_KEY / XAI_API_KEY / CASCADE_LLM_API_KEY
uv run cascade eval-baselines --agent llm --provider openai --model gpt-4o --seeds 0 \
  --out docs/artifacts/baseline-gpt-4o-t1-t5.json

# xAI Grok
uv run cascade eval-baselines --agent llm --provider xai --model grok-3 --seeds 0 \
  --out docs/artifacts/baseline-grok-3-t1-t5.json

# Single interactive LLM episode
uv run python examples/llm_tool_loop.py --task community.T3.worker_disabled_config.v1
# or: uv run cascade run-episode --agent llm --task community.T2.pagination_off_by_one.v1
```

JSON summaries include per-task `pass_at_1`, avg steps, terminal reward, token usage, and rough USD cost when the model price is known. Markdown cards are written next to the JSON (`*.md`).

**Reporting rules:** always state runtime, pack, task ids, seeds, agent/model, and date. Stratify by tier (L1/L2/L3); do not average away L3 headroom.

---

## Scripted repair agent (`cascade_env.agents.scripted`)

Deterministic policy that applies **known single-fault repairs** for community demos. It is a **ceiling for trivial patterns**, not a general agent. Multi-fault L3 tasks are intentionally **not** fully handled.

### Community pack — measured (T1–T5)

**Artifact:** [`artifacts/baseline-scripted-t1-t5.json`](./artifacts/baseline-scripted-t1-t5.json)  
**Date:** 2026-07-10 · **Runtime:** `local` · **Seeds:** `{0}` · **Agent:** `scripted`

| Model | Date | Pack | pass@1 | Avg steps | Runtime | Est. cost |
|-------|------|------|--------|-----------|---------|-----------|
| scripted | 2026-07-10 | community T1–T5 | **0.80** | 7.0 | local | — |

| Task ID | Family | Tier | pass@1 | Avg steps | Avg R | Notes |
|---------|--------|------|--------|-----------|-------|-------|
| `community.T1.worker_retry_storm.v1` | incident_repair | L2 | **1.00** | 8.0 | 0.993 | Config + worker handler restore |
| `community.T2.pagination_off_by_one.v1` | bugfix | L1 | **1.00** | 7.0 | 0.994 | Template restore products route |
| `community.T3.worker_disabled_config.v1` | config_repair | L1 | **1.00** | 7.0 | 0.994 | Re-enable worker config |
| `community.T4.bad_product_prices.v1` | data_repair | L2 | **0.00** | 6.0 | −0.005 | Code null-price fixed; SQL bad row needs `db.exec` |
| `community.T5.discount_field.v1` | feature_ship | L2 | **1.00** | 7.0 | 0.994 | Injects `discount_cents` field |

### L3 qualitative (scripted)

| Task ID | Family | Tier | Scripted pass? | Notes |
|---------|--------|------|----------------|-------|
| `community.T6.checkout_cascade.v1` | multi_fault | L3 | **No** | Dual code faults + red herring |
| `community.T7.security_fulfill_cascade.v1` | multi_fault | L3 | **No** | Auth + worker both broken |
| `community.T8.merch_catalog_cascade.v1` | multi_fault | L3 | **No** | Pagination + price leak + data + red herring |

**Summary (scripted):**

| Split | Approx. pass rate | Intent |
|-------|-------------------|--------|
| L1–L2 (T1–T5) | **0.80** pass@1 (seed 0) | Demo / smoke |
| L3 (T6–T8) | **~0.0** for current scripted policy | Public **headroom** for real agents |

Episode terminal reward on full success is ~`1.0 − step_cost × steps` (default step cost `0.001`).

---

## Frontier model baselines

Real tool-calling agents use `examples/llm_tool_loop.py` / `--agent llm` with an OpenAI-compatible or Anthropic client (`httpx`, no extra vendor SDKs).

| Env var | Purpose |
|---------|---------|
| `CASCADE_LLM_API_KEY` / `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `XAI_API_KEY` | API key |
| `CASCADE_LLM_PROVIDER` | `openai` · `anthropic` · `xai` (auto if unset) |
| `CASCADE_LLM_BASE_URL` | Override base URL (e.g. vLLM) |
| `CASCADE_LLM_MODEL` | Model id |

### Aggregate card (T1–T5)

| Model | Date | Pack | pass@1 | Avg steps | Runtime | Est. cost | Artifact |
|-------|------|------|--------|-----------|---------|-----------|----------|
| _(run with API key to fill)_ | — | community T1–T5 | — | — | local | — | `docs/artifacts/baseline-<model>-t1-t5.json` |

To publish a frontier row: run `cascade eval-baselines --agent llm …`, commit the JSON under `docs/artifacts/`, and paste the markdown table into this section.

### Per-task template (fill after eval)

| Task ID | pass@1 | n | Avg steps | Avg R |
|---------|--------|---|-----------|-------|
| `community.T1.worker_retry_storm.v1` | — | — | — | — |
| `community.T2.pagination_off_by_one.v1` | — | — | — | — |
| `community.T3.worker_disabled_config.v1` | — | — | — | — |
| `community.T4.bad_product_prices.v1` | — | — | — | — |
| `community.T5.discount_field.v1` | — | — | — | — |

---

## Private holdout pack

Sealed tasks (`holdout.H*`) are **not** committed. Scaffold and load:

```bash
uv run python scripts/scaffold_holdout_pack.py
# PowerShell
$env:CASCADE_HOLDOUT_DIR = (Resolve-Path packs/holdout).Path
uv run cascade list-tasks --pack holdout
uv run cascade eval-baselines --agent llm --pack holdout --tasks holdout.H1.stock_retry_compound.v1
```

| Expectation | Scripted | Frontier models |
|-------------|----------|-----------------|
| Holdout H1–H3 (compound L3) | **No** (same policy gaps) | Publish privately; target headroom on sealed set |

Do not publish holdout fault IDs with solution traces in public baselines.

---

## Reporting guidelines

1. Always state **runtime**, **pack version**, **task ids**, **seed**, and **agent/model**.
2. Stratify by **tier** (L1 / L2 / L3); do not average away L3 headroom.
3. Prefer **sealed holdout** numbers for model selection ([`commercial.md`](./commercial.md)).
4. Keep public community scores for open comparison only.
5. Prefer **pass@1** over single-run anecdotes; report **n** and seeds.
6. When available, report **token usage** and **estimated cost** from the JSON summary.

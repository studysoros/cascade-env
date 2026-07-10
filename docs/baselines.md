# Cascade baselines

Measured against **Shopstack** with **`runtime=local`** unless noted. Use `uv` only.

**Last updated:** 2026-07-10

## Scripted repair agent (`cascade_env.agents.scripted`)

Deterministic policy that applies **known single-fault repairs** for community demos. It is a **ceiling for trivial patterns**, not a general agent. Multi-fault L3 tasks are intentionally **not** fully handled.

### Community pack (public)

| Task ID | Family | Tier | Scripted pass? | Notes |
|---------|--------|------|----------------|-------|
| `community.T1.worker_retry_storm.v1` | incident_repair | L2 | **Yes** | Config + worker handler restore |
| `community.T2.pagination_off_by_one.v1` | bugfix | L1 | **Yes** | Template restore products route |
| `community.T3.worker_disabled_config.v1` | config_repair | L1 | **Yes** | Re-enable worker config |
| `community.T4.bad_product_prices.v1` | data_repair | L2 | **Partial → often No** | Code null-price fixed; SQL bad row may remain without `db.exec` |
| `community.T5.discount_field.v1` | feature_ship | L2 | **Yes** | Injects `discount_cents` field |
| `community.T6.checkout_cascade.v1` | multi_fault | L3 | **No** | Dual code faults + red herring; no compound fix |
| `community.T7.security_fulfill_cascade.v1` | multi_fault | L3 | **No** | Auth + worker both broken |
| `community.T8.merch_catalog_cascade.v1` | multi_fault | L3 | **No** | Pagination + price leak + data + red herring |

**Summary (scripted, qualitative):**

| Split | Approx. pass rate | Intent |
|-------|-------------------|--------|
| L1–L2 (T1–T5) | High on single-fault demos (~0.8–1.0 pass@1 where measured) | Demo / smoke |
| L3 (T6–T8) | **~0.0** for current scripted policy | Public **headroom** for real agents |
| Full community | Mid (L1–L2 dominate if uniform sample) | Prefer tier-stratified reporting |

### How to reproduce

```bash
uv sync --extra dev

# Single task
uv run cascade run-episode --task community.T2.pagination_off_by_one.v1 --agent scripted
uv run cascade run-episode --task community.T6.checkout_cascade.v1 --agent scripted

# Integration test (pagination)
uv run pytest tests/test_env_integration.py -q
```

Episode terminal reward on full success is ~`1.0 − step_cost × steps` (default step cost `0.001`).

## Private holdout pack

Sealed tasks (`holdout.H*`) are **not** committed. Scaffold and load:

```bash
uv run python scripts/scaffold_holdout_pack.py
# PowerShell
$env:CASCADE_HOLDOUT_DIR = (Resolve-Path packs/holdout).Path
uv run cascade list-tasks --pack holdout
```

| Expectation | Scripted | Frontier models (TBD) |
|-------------|----------|------------------------|
| Holdout H1–H3 (compound L3) | **No** (same policy gaps) | Publish privately; target headroom on sealed set |

Do not publish holdout fault IDs with solution traces in public baselines.

## Frontier model baselines (placeholder)

| Model | Date | Pack | pass@1 | Avg steps | Runtime | Cost |
|-------|------|------|--------|-----------|---------|------|
| _(none checked in yet)_ | — | community T1–T5 | — | — | local | — |

WP3 will fill this table via `examples/llm_tool_loop.py` + an eval harness.

## Reporting guidelines

1. Always state **runtime**, **pack version**, **task ids**, **seed**, and **agent**.
2. Stratify by **tier** (L1 / L2 / L3); do not average away L3 headroom.
3. Prefer **sealed holdout** numbers for model selection ([`commercial.md`](./commercial.md)).
4. Keep public community scores for open comparison only.

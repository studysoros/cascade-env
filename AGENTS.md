# Cascade agent notes

## Product

Cascade (`cascade_env`) is a production multi-service RL environment: agents repair live sandboxed stacks (Shopstack) with multi-verifier rewards.

## Commands (uv only — not pip)

```bash
uv sync --extra dev
uv run cascade doctor
uv run cascade list-tasks
uv run cascade run-episode --task community.T2.pagination_off_by_one.v1 --agent scripted
uv run pytest -q
```

## Layout

- `src/cascade_env/` — control plane, Gym env, tools, verifiers
- `scenarios/shopstack/` — application under test
- `packs/community/` — public tasks T1–T8 (incl. L3 multi-fault)
- `packs/holdout/` — sealed holdout (gitignored; `scripts/scaffold_holdout_pack.py`)
- `docs/design-cascade.md` — full design
- `docs/STATUS.md` — **build status + session handoff** (read this first in new sessions)
- `docs/commercial.md` / `docs/baselines.md` — holdout SKU + pass-rate notes

## Rules

- Use **`uv`**, never pip, for install/run/test.
- Default runtime is `local` (no Docker).
- Never mid-episode image rebuilds; code edits use workspace + restart.
- Verifiers and compose infra are outside the agent path jail.
- Sandbox only — no real production credentials.
- Before claiming “plan complete”, check `docs/STATUS.md` PR tracker.

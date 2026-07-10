# Cascade

**Production multi-service RL environment for frontier agent training.**

> Train agents that keep software systems alive: diagnose incidents, fix code/config/data, and restore service health—with automatic multi-verifier rewards.

**Positioning:** *SWE-bench for live production systems.*

> **Sandbox only.** Never point Cascade tools at real production credentials, networks, or customer data.

## Why this exists

Frontier labs need RL environments with:

- **Automatic, multi-verifier rewards** (health + golden HTTP + tests + DB invariants + anti-cheat)
- **Live multi-service stacks** (API + DB + queue + worker)—not only static repo diffs
- **Tool-calling agent API** (Gymnasium `Cascade-v0`)
- **Contamination-resistant packaging** (parameterized tasks + sealed holdout packs for commercial licensing)

## Quickstart

Requires [**uv**](https://docs.astral.sh/uv/) (not pip).

```bash
# Python 3.11+ managed by uv
uv sync --extra dev

# Health check
uv run cascade doctor

# List tasks
uv run cascade list-tasks

# Run a full episode with the scripted repair baseline
uv run cascade run-episode --task community.T2.pagination_off_by_one.v1 --agent scripted

# Or via Gymnasium
uv run python examples/random_rollout.py
uv run python examples/scripted_solve.py

# Pass-rate card (scripted control baseline)
uv run cascade eval-baselines --agent scripted --seeds 0

# Real LLM tool loop (requires OPENAI_API_KEY / ANTHROPIC_API_KEY / XAI_API_KEY)
# uv run python examples/llm_tool_loop.py --task community.T3.worker_disabled_config.v1
# uv run cascade eval-baselines --agent llm --provider openai --model gpt-4o --seeds 0

# HTTP rollout server (remote trainers; OpenAPI at /docs)
# uv run cascade serve --api-key dev-key
# uv run python examples/remote_client.py --api-key dev-key
```

### Runtime modes

| Runtime | When to use |
|---------|-------------|
| **`local`** (default) | Real Shopstack API + worker processes, SQLite + file queue. **No Docker required.** Best for training loops on a laptop. |
| **`compose`** | Docker Compose multi-service fidelity (Postgres/Redis). Requires Docker daemon. |

```bash
# Windows PowerShell
$env:CASCADE_RUNTIME = "local"
uv run cascade run-episode --runtime local --task community.T3.worker_disabled_config.v1 --agent scripted
```

### Build status & next work

See [`docs/STATUS.md`](docs/STATUS.md) for what is done vs the design plan, and session handoff for next work packages.

## Gymnasium API

```python
import json
import cascade_env
import gymnasium as gym

cascade_env.register_envs()
env = gym.make("Cascade-v0", pack="community", runtime="local", task_id=None)

obs_json, info = env.reset(seed=42)
terminated = truncated = False
while not (terminated or truncated):
    # One tool call per step (serialize multi-tool model outputs)
    action = {
        "tool": "http.request",
        "args": {"method": "GET", "path": "/ready"},
    }
    obs_json, reward, terminated, truncated, info = env.step(action)

print(info.get("success"), info.get("terminal_reward"))
env.close()
```

**Spaces:** `Text` JSON for observations/actions (tool-calling agents). Structured data is always in `info["obs"]` / `info["tool_result"]`.

**Reward (sparse):** step reward = `−0.001` cost only; terminal reward from multi-verifier success (`+1.0` on full success minus costs).

## Task families (community pack)

| ID | Family | Tier | Example task |
|----|--------|------|----------------|
| T1 | Incident repair | L2 | Worker retry storm |
| T2 | Runtime bugfix | L1 | Pagination off-by-one |
| T3 | Config remediation | L1 | Worker disabled |
| T4 | Data/schema repair | L2 | Bad product prices |
| T5 | Feature ship | L2 | Add `discount_cents` |
| T6 | Multi-fault cascade | L3 | Checkout stock + idempotency (+ red herring) |
| T7 | Multi-fault cascade | L3 | Auth bypass + worker disabled |
| T8 | Multi-fault cascade | L3 | Catalog pagination + price poison |

L3 tasks intentionally leave **scripted-agent headroom** (compound faults + red herrings). See [`docs/baselines.md`](docs/baselines.md).

## HTTP rollout API

Remote trainers can drive the same episode loop over HTTP:

```bash
uv run cascade serve --api-key dev-key
# POST /v1/episodes  →  POST /v1/episodes/{id}/step  →  close
uv run python examples/remote_client.py --api-key dev-key
```

Auth: `X-API-Key` or `Authorization: Bearer`. Config: `CASCADE_SERVER_API_KEY`, `CASCADE_SERVER_HOST`, `CASCADE_SERVER_PORT`, `CASCADE_MAX_PARALLEL_EPISODES`.

## Architecture

```
Trainer / Agent
    → CascadeEnv (Gymnasium)  OR  HTTP /v1/episodes (cascade serve)
        → EpisodeManager
            → RuntimeBackend (local | compose)
            → Tool adapters (files, http, logs, services, db, shell, tests, submit)
            → Multi-verifier orchestrator
            → JSONL trajectories
    → Shopstack CAUT (commerce microservices under test)
```

## Package layout

```
src/cascade_env/     # runtime, env, tools, verifiers
scenarios/shopstack/ # application under test + compose
packs/community/     # public task pack (L1–L3)
packs/holdout/       # sealed holdout (gitignored; scaffold locally)
examples/            # agent harnesses
docs/                # design + guides
scripts/             # pull_images.py, scaffold_holdout_pack.py, etc.
```

## Commercial packaging & sealed holdouts

| Tier | Contents |
|------|----------|
| **Community (free)** | Runtime + Shopstack + public `packs/community` tasks |
| **Lab / Enterprise (holdout SKU)** | Sealed private holdout packs, hosted scoring, custom CAUT porting |

Local “license keys” are not a security boundary; **distribution control** of sealed packs is.

### Holdout SKU (how to load)

Sealed packs are **not** in the public repo. Scaffold a local private pack or install one from enterprise delivery:

```bash
# Create a local sealed pack (gitignored)
uv run python scripts/scaffold_holdout_pack.py

# Point the runtime at it
export CASCADE_HOLDOUT_DIR=$PWD/packs/holdout   # bash
# $env:CASCADE_HOLDOUT_DIR = (Resolve-Path packs/holdout).Path  # PowerShell

uv run cascade doctor
uv run cascade list-tasks --pack holdout
uv run cascade run-episode --pack holdout --task holdout.H1.stock_retry_compound.v1 --agent scripted
```

Also supported: `CASCADE_EXTRA_PACKS` (pathsep/comma-separated pack dirs) or `--pack /absolute/path/to/pack`.

Full distribution notes: [`docs/commercial.md`](docs/commercial.md) · baselines: [`docs/baselines.md`](docs/baselines.md)
## Design & status

- Full product & systems design: [`docs/design-cascade.md`](docs/design-cascade.md)
- Build status / session handoff: [`docs/STATUS.md`](docs/STATUS.md)
- Commercial / holdout: [`docs/commercial.md`](docs/commercial.md)
- Baselines: [`docs/baselines.md`](docs/baselines.md)
## License

Apache-2.0

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

| ID | Family | Example task |
|----|--------|----------------|
| T1 | Incident repair | Worker retry storm |
| T2 | Runtime bugfix | Pagination off-by-one |
| T3 | Config remediation | Worker disabled |
| T4 | Data/schema repair | Bad product prices |
| T5 | Feature ship | Add `discount_cents` |

## Architecture

```
Trainer / Agent
    → CascadeEnv (Gymnasium)
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
packs/community/     # public task pack
examples/            # agent harnesses
docs/                # design + guides
```

## Commercial packaging

| Tier | Contents |
|------|----------|
| Community (free) | Runtime + Shopstack + public tasks |
| Lab / Enterprise | Sealed private holdouts, hosted scoring, custom CAUT porting |

Local “license keys” are not a security boundary; **distribution control** of sealed packs is.

## Design

Full product & systems design: [`docs/design-cascade.md`](docs/design-cascade.md)

## License

Apache-2.0

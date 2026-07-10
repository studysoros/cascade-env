# Cascade commercial packaging

**Sandbox only.** Cascade never attaches tools to real production credentials or networks.

This document describes how **public** and **sealed** task packs are distributed. It is not a license agreement.

## SKUs

| Tier | What you get | Distribution control |
|------|----------------|----------------------|
| **Community (free)** | Runtime (`cascade-env`), Shopstack CAUT, public `packs/community` tasks, docs | Apache-2.0; public git |
| **Lab / Enterprise** | **Sealed holdout packs**, optional hosted scoring, custom CAUT porting services | Private delivery; not in the public repo |
| **Services** | Port customer systems into Cascade-shaped episodes; joint eval reports | Contract + private artifacts |

**Primary commercial wedge:** sealed holdout evaluation reliability (model selection / gated release), not “replace the entire training stack on day one.”

Local “license keys” are **not** a security boundary. Real control is **who receives the sealed YAML/bundle**.

## Public vs sealed packs

| Property | Public community pack | Sealed holdout pack |
|----------|----------------------|---------------------|
| Location | `packs/community/` in this repo | Outside public tree (e.g. private share, `CASCADE_HOLDOUT_DIR`) |
| Contamination risk | Will contaminate over time (web, training traces) | Primary long-term defense |
| Intended use | Training, demos, open baselines | Gated eval, private pass@k cards |
| Task IDs | `community.T*.…` | `holdout.H*.…` (or customer prefix) |
| Git | Committed | **Not committed** (`packs/holdout/` is gitignored) |

Community pack includes L1–L3 tasks. L3 tasks use cascading faults and red herrings so public headroom remains after L1/L2 solve rates rise.

## Installing a sealed holdout pack

### Option A — environment variable (recommended)

Point Cascade at a pack directory that contains `pack.yaml` + `tasks/*.yaml`:

```bash
# bash
export CASCADE_HOLDOUT_DIR=/secure/cascade-holdout
# or multiple pack dirs:
export CASCADE_EXTRA_PACKS=/secure/cascade-holdout:/secure/customer-pack

uv run cascade doctor
uv run cascade list-tasks --pack holdout
uv run cascade run-episode --pack holdout --task holdout.H1.stock_retry_compound.v1 --agent scripted
```

```powershell
# PowerShell
$env:CASCADE_HOLDOUT_DIR = "C:\secure\cascade-holdout"
uv run cascade list-tasks --pack holdout
```

### Option B — under `packs/` (local only)

```bash
uv run python scripts/scaffold_holdout_pack.py
# writes packs/holdout/ (gitignored)
uv run cascade list-tasks --pack holdout
```

Never commit holdout task YAML, golden solutions, or trajectories that reveal faults.

### Option C — absolute pack path

```bash
uv run cascade list-tasks --pack /secure/cascade-holdout
uv run cascade run-episode --pack /secure/cascade-holdout --task holdout.H2.auth_catalog_compound.v1
```

## Scaffold (lab-side)

To mint a **local** sealed pack for integration tests or private delivery dry-runs:

```bash
uv run python scripts/scaffold_holdout_pack.py --out /secure/cascade-holdout
```

Enterprise delivery should replace scaffold content with **unpublished** fault compositions and stronger hidden checks (`metadata.hidden_checks`).

## What labs should report

For gated model selection, prefer **holdout** numbers over public-only:

- model + date + runtime (`local` / `compose`)
- pass@1 (and pass@k if available) on sealed task set
- average steps / wall time
- cost if known

Public scripted and model baselines live in [`baselines.md`](./baselines.md). Sealed scores stay private unless the lab chooses to publish aggregates.

## Courtesy allowlist (optional, non-security)

A future client-side allowlist may **warn** when enterprise pack ids are used without a configured key. That is a courtesy UX layer only—**not** DRM. Distribution control remains the real boundary.

## Related

- Design: [`design-cascade.md`](./design-cascade.md) (commercial model sketch, contamination defense)
- Status / roadmap: [`STATUS.md`](./STATUS.md)
- Baselines: [`baselines.md`](./baselines.md)

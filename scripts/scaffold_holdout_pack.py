#!/usr/bin/env python3
"""Scaffold a sealed private holdout pack (not for public distribution).

Usage:
  uv run python scripts/scaffold_holdout_pack.py
  uv run python scripts/scaffold_holdout_pack.py --out /secure/path/cascade-holdout

By default writes to packs/holdout/ (gitignored). Load with:
  $env:CASCADE_HOLDOUT_DIR = (Resolve-Path packs/holdout).Path   # PowerShell
  export CASCADE_HOLDOUT_DIR=$PWD/packs/holdout                  # bash
  uv run cascade list-tasks --pack holdout
"""

from __future__ import annotations

import argparse
from pathlib import Path

PACK_YAML = """\
api_version: cascade/v1
pack:
  id: holdout
  name: Cascade Private Holdout Pack
  version: 0.1.0
  min_runtime_version: "0.1.0"
  schema_version: 1
  license: Proprietary
  scenario: shopstack
  default_budgets:
    max_steps: 50
    max_wall_time_s: 1200
  splits:
    holdout: { filter: "tier in [L2, L3]" }
"""

# Sealed tasks — different compositions / IDs from the public community pack.
TASKS: dict[str, str] = {
    "h1_stock_retry.yaml": """\
api_version: cascade/v1
task:
  id: holdout.H1.stock_retry_compound.v1
  family: multi_fault
  tier: L3
  scenario: shopstack
  seed_policy: required
  tools:
    allow: [files.*, http.*, logs.*, services.*, db.query, shell.exec, tests.run, submit.done]
  brief:
    title: Inventory drift with fulfillment retry storms
    description: |
      Sealed holdout: stock no longer decrements and the worker is retrying
      without bound. A release-notes file blames the product catalog (red herring).
      Restore inventory correctness and healthy fulfillment.
    public_success_criteria:
      - Golden path and public tests pass
      - Stock decrements on order create
      - Worker retries are sane
    constraints:
      - Do not disable authentication
      - Do not gut tests
  mutations:
    - type: code.patch
      file: app/api/routes/orders.py
      template: stock_not_decremented
    - type: code.patch
      file: app/worker/handler.py
      template: infinite_retry_no_jitter
    - type: config.set
      path: configs/worker.yaml
      key: max_retries
      value: 10000
    - type: file.write
      path: configs/release_notes.md
      content: |
        holdout canary — catalog offset suspected (may be wrong)
  verifiers:
    success_requires:
      all_of: [health.all_healthy, http.golden_paths, pytest.public, invariants.db, invariants.family]
      not_fail: [process.no_cheat, security.auth_still_enforced]
  metadata:
    tags: [holdout, sealed, cascading]
    hidden_checks: [stock_decrement, worker_retries_sane, no_fault_markers]
  budgets:
    max_steps: 50
""",
    "h2_auth_catalog.yaml": """\
api_version: cascade/v1
task:
  id: holdout.H2.auth_catalog_compound.v1
  family: multi_fault
  tier: L3
  scenario: shopstack
  seed_policy: required
  tools:
    allow: [files.*, http.*, logs.*, services.*, db.query, shell.exec, tests.run, submit.done]
  brief:
    title: Auth bypass with empty first catalog page
    description: |
      Sealed holdout: debug auth is left on and page-1 catalog is empty.
      Worker config looks aggressive (red herring). Restore auth and catalog.
    public_success_criteria:
      - Unauthenticated orders return 401
      - Catalog page 1 returns items
      - Golden path and public tests pass
    constraints:
      - Do not leave debug auth enabled
  mutations:
    - type: code.patch
      file: app/api/auth.py
      template: auth_bypass_debug
    - type: code.patch
      file: app/api/routes/products.py
      template: pagination_off_by_one
    - type: config.set
      path: configs/worker.yaml
      key: max_retries
      value: 999
  verifiers:
    success_requires:
      all_of: [health.all_healthy, http.golden_paths, pytest.public, invariants.db, invariants.family]
      not_fail: [process.no_cheat, security.auth_still_enforced]
  metadata:
    tags: [holdout, sealed, cascading]
    hidden_checks: [auth_enforced, pagination, no_fault_markers]
  budgets:
    max_steps: 50
""",
    "h3_idempotency_prices.yaml": """\
api_version: cascade/v1
task:
  id: holdout.H3.idempotency_price_compound.v1
  family: multi_fault
  tier: L3
  scenario: shopstack
  seed_policy: required
  tools:
    allow: [files.*, http.*, logs.*, services.*, db.query, db.exec, shell.exec, tests.run, submit.done]
  brief:
    title: Broken idempotency and poisoned prices
    description: |
      Sealed holdout: duplicate Idempotency-Key creates multiple orders, and
      product prices leak null / negative values. Fix both code and data.
    public_success_criteria:
      - Idempotent order create returns the same order id
      - All product prices valid
      - Golden path and public tests pass
    constraints:
      - Do not drop tables
      - Do not disable authentication
  mutations:
    - type: code.patch
      file: app/api/routes/orders.py
      template: broken_idempotency
    - type: code.patch
      file: app/api/routes/products.py
      template: null_price_leak
    - type: sql.seed
      sql: |
        UPDATE products SET price_cents = -5 WHERE sku = 'SKU-MUG';
  verifiers:
    success_requires:
      all_of: [health.all_healthy, http.golden_paths, pytest.public, invariants.db, invariants.family]
      not_fail: [process.no_cheat, security.auth_still_enforced]
  metadata:
    tags: [holdout, sealed, cascading]
    hidden_checks: [idempotency, prices_valid, no_fault_markers]
  budgets:
    max_steps: 55
""",
}

README = """\
# Cascade private holdout pack

**Proprietary / sealed.** Do not publish task YAML, solutions, or trajectories.

## Load

```bash
# PowerShell
$env:CASCADE_HOLDOUT_DIR = (Resolve-Path .).Path
# bash
export CASCADE_HOLDOUT_DIR=$PWD

uv run cascade list-tasks --pack holdout
uv run cascade run-episode --pack holdout --task holdout.H1.stock_retry_compound.v1 --agent scripted
```

Or via extra packs list:

```bash
export CASCADE_EXTRA_PACKS=/secure/cascade-holdout
```

See docs/commercial.md for distribution and SKU notes.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output pack directory (default: <repo>/packs/holdout)",
    )
    args = parser.parse_args()
    if args.out is None:
        repo = Path(__file__).resolve().parents[1]
        out = repo / "packs" / "holdout"
    else:
        out = args.out.expanduser().resolve()

    tasks_dir = out / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    (out / "pack.yaml").write_text(PACK_YAML, encoding="utf-8")
    (out / "README.md").write_text(README, encoding="utf-8")
    for name, body in TASKS.items():
        (tasks_dir / name).write_text(body, encoding="utf-8")

    print(f"Wrote sealed holdout pack to {out}")
    print(f"  pack id: holdout  tasks: {len(TASKS)}")
    print("Load with CASCADE_HOLDOUT_DIR or place under packs/ (gitignored).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

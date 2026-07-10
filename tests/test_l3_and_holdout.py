"""L3 community tasks + sealed holdout pack loading."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from cascade_env.config import CascadeConfig, get_config
from cascade_env.tasks.loader import TaskLoader, TaskNotFoundError
from cascade_env.tasks.mutators import apply_mutations
from cascade_env.tasks.schemas import MutationSpec


def test_community_has_at_least_three_l3_tasks():
    loader = TaskLoader()
    stems = loader.list_tasks("community")
    l3 = []
    for stem in stems:
        task = loader.load_task("community", stem)
        if task.tier == "L3":
            l3.append(task)
    assert len(l3) >= 3, f"expected ≥3 L3 tasks, got {len(l3)}: {[t.id for t in l3]}"
    for t in l3:
        assert t.family == "multi_fault"
        assert t.metadata.get("hidden_checks"), f"{t.id} missing hidden_checks"
        assert len(t.mutations) >= 2, f"{t.id} should cascade multiple mutations"


def test_l3_task_ids_load():
    loader = TaskLoader()
    for tid in (
        "community.T6.checkout_cascade.v1",
        "community.T7.security_fulfill_cascade.v1",
        "community.T8.merch_catalog_cascade.v1",
    ):
        t = loader.load_task("community", tid)
        assert t.id == tid
        assert t.tier == "L3"


def test_checkout_cascade_mutations_apply(tmp_path: Path):
    src = get_config().scenarios_dir() / "shopstack" / "workspace_template"
    work = tmp_path / "ws"
    shutil.copytree(src, work)
    loader = TaskLoader()
    task = loader.load_task("community", "community.T6.checkout_cascade.v1")
    events = apply_mutations(work, task.mutations)
    assert len(events) == len(task.mutations)
    orders = (work / "app" / "api" / "routes" / "orders.py").read_text(encoding="utf-8")
    assert "CASCADE_FAULT: stock not decremented" in orders
    assert "CASCADE_FAULT: idempotency broken" in orders
    assert (work / "configs" / "feature_flags.yaml").exists()


def test_merch_catalog_cascade_mutations_apply(tmp_path: Path):
    src = get_config().scenarios_dir() / "shopstack" / "workspace_template"
    work = tmp_path / "ws"
    shutil.copytree(src, work)
    task = TaskLoader().load_task("community", "community.T8.merch_catalog_cascade.v1")
    apply_mutations(work, task.mutations)
    products = (work / "app" / "api" / "routes" / "products.py").read_text(encoding="utf-8")
    assert "CASCADE_FAULT: off-by-one" in products
    assert "null price leak" in products
    sql = (work / "mutations" / "pending_sql.sql").read_text(encoding="utf-8")
    assert "SKU-MUG" in sql


def test_holdout_pack_via_extra_packs(tmp_path: Path):
    """Sealed pack loads from CASCADE_EXTRA_PACKS / config.extra_packs path."""
    pack_root = tmp_path / "sealed-holdout"
    pack_root.mkdir()
    (pack_root / "pack.yaml").write_text(
        """
api_version: cascade/v1
pack:
  id: holdout
  name: Test Holdout
  version: 0.1.0
  scenario: shopstack
""".strip()
        + "\n",
        encoding="utf-8",
    )
    tasks = pack_root / "tasks"
    tasks.mkdir()
    (tasks / "h_smoke.yaml").write_text(
        """
api_version: cascade/v1
task:
  id: holdout.H0.smoke.v1
  family: multi_fault
  tier: L3
  brief:
    title: Smoke holdout
    description: test only
  mutations: []
  metadata:
    hidden_checks: [no_fault_markers]
""".strip()
        + "\n",
        encoding="utf-8",
    )

    cfg = CascadeConfig(extra_packs=str(pack_root))
    loader = TaskLoader(cfg)
    assert "holdout" in loader.list_packs()
    task = loader.load_task("holdout", "holdout.H0.smoke.v1")
    assert task.tier == "L3"
    assert loader.list_tasks("holdout") == ["h_smoke"]


def test_holdout_dir_env_alias(tmp_path: Path):
    pack_root = tmp_path / "holdout-dir"
    pack_root.mkdir()
    (pack_root / "pack.yaml").write_text(
        "api_version: cascade/v1\npack:\n  id: holdout\n  name: H\n  version: 0.1.0\n",
        encoding="utf-8",
    )
    (pack_root / "tasks").mkdir()
    (pack_root / "tasks" / "x.yaml").write_text(
        "api_version: cascade/v1\ntask:\n  id: holdout.X.v1\n  family: multi_fault\n"
        "  tier: L3\n  brief:\n    title: x\n    description: x\n  metadata:\n"
        "    hidden_checks: [no_fault_markers]\n",
        encoding="utf-8",
    )
    cfg = CascadeConfig(holdout_dir=pack_root)
    loader = TaskLoader(cfg)
    assert loader.load_task("holdout", "holdout.X.v1").id == "holdout.X.v1"


def test_pack_path_absolute(tmp_path: Path):
    pack_root = tmp_path / "custom"
    pack_root.mkdir()
    (pack_root / "pack.yaml").write_text(
        "api_version: cascade/v1\npack:\n  id: custom\n  name: C\n  version: 0.1.0\n",
        encoding="utf-8",
    )
    (pack_root / "tasks").mkdir()
    (pack_root / "tasks" / "t.yaml").write_text(
        "api_version: cascade/v1\ntask:\n  id: custom.T.v1\n  family: bugfix\n"
        "  tier: L1\n  brief:\n    title: t\n    description: t\n",
        encoding="utf-8",
    )
    loader = TaskLoader()
    task = loader.load_task(str(pack_root), "custom.T.v1")
    assert task.id == "custom.T.v1"


def test_scaffold_holdout_script(tmp_path: Path):
    repo = Path(__file__).resolve().parents[1]
    script = repo / "scripts" / "scaffold_holdout_pack.py"
    out = tmp_path / "out-holdout"
    r = subprocess.run(
        [sys.executable, str(script), "--out", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr + r.stdout
    assert (out / "pack.yaml").exists()
    assert len(list((out / "tasks").glob("*.yaml"))) >= 3
    cfg = CascadeConfig(holdout_dir=out)
    loader = TaskLoader(cfg)
    assert len(loader.list_tasks("holdout")) >= 3
    t = loader.load_task("holdout", "holdout.H1.stock_retry_compound.v1")
    assert t.tier == "L3"


def test_missing_holdout_raises():
    cfg = CascadeConfig(extra_packs="")
    loader = TaskLoader(cfg)
    # holdout may exist if user scaffolded under packs/; only assert pure miss
    with pytest.raises(TaskNotFoundError):
        loader.pack_dir(str(Path("/nonexistent/cascade-holdout-xyz")))

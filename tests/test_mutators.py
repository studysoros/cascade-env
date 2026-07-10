import shutil
from pathlib import Path

from cascade_env.config import get_config
from cascade_env.tasks.mutators import apply_mutations
from cascade_env.tasks.schemas import MutationSpec


def test_pagination_template(tmp_path: Path):
    src = get_config().scenarios_dir() / "shopstack" / "workspace_template"
    work = tmp_path / "ws"
    shutil.copytree(src, work)
    apply_mutations(
        work,
        [MutationSpec(type="code.patch", file="app/api/routes/products.py", template="pagination_off_by_one")],
    )
    text = (work / "app" / "api" / "routes" / "products.py").read_text(encoding="utf-8")
    assert "CASCADE_FAULT" in text
    assert "page * page_size" in text


def test_idempotency_and_stock_templates(tmp_path: Path):
    src = get_config().scenarios_dir() / "shopstack" / "workspace_template"
    work = tmp_path / "ws"
    shutil.copytree(src, work)
    apply_mutations(
        work,
        [
            MutationSpec(
                type="code.patch", file="app/api/routes/orders.py", template="stock_not_decremented"
            ),
            MutationSpec(
                type="code.patch", file="app/api/routes/orders.py", template="broken_idempotency"
            ),
        ],
    )
    text = (work / "app" / "api" / "routes" / "orders.py").read_text(encoding="utf-8")
    assert "CASCADE_FAULT: stock not decremented" in text
    assert "CASCADE_FAULT: idempotency broken" in text

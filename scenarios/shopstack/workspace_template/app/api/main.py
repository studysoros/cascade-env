"""Shopstack API entrypoint."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from fastapi import FastAPI

# Ensure workspace root on path when running from /workspace
_WS = Path(__file__).resolve().parents[2]
if str(_WS) not in sys.path:
    sys.path.insert(0, str(_WS))

from app.api.auth import SEED_API_KEY, hash_key  # noqa: E402
from app.api.routes import orders, products  # noqa: E402
from app.db import Base, get_engine, init_db, ping, session_scope  # noqa: E402
from app.models import Product, User  # noqa: E402
from app.queue import get_queue  # noqa: E402

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger("shopstack.api")

app = FastAPI(title="Shopstack API", version="0.1.0")
app.include_router(products.router)
app.include_router(orders.router)


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    Base.metadata.create_all(get_engine())
    _seed()
    logger.info("shopstack api started")


def _seed() -> None:
    with session_scope() as s:
        if s.query(User).count() == 0:
            s.add(User(api_key_hash=hash_key(SEED_API_KEY), name="demo"))
        if s.query(Product).count() == 0:
            s.add_all(
                [
                    Product(sku="SKU-TEE", name="Cascade Tee", price_cents=2500, stock=100),
                    Product(sku="SKU-MUG", name="Cascade Mug", price_cents=1500, stock=50),
                    Product(sku="SKU-STK", name="Sticker Pack", price_cents=500, stock=200),
                    Product(sku="SKU-HAT", name="Cascade Hat", price_cents=3000, stock=25),
                    Product(sku="SKU-HDY", name="Hoodie", price_cents=5500, stock=15),
                ]
            )


@app.get("/health")
def health():
    return {"status": "ok", "service": "api"}


@app.get("/ready")
def ready():
    from fastapi.responses import JSONResponse

    db_ok = ping()
    try:
        q_ok = get_queue().ping()
    except Exception:
        q_ok = False
    ok = db_ok and q_ok
    body = {
        "status": "ready" if ok else "degraded",
        "db": db_ok,
        "queue": q_ok,
    }
    return JSONResponse(body, status_code=200 if ok else 503)


@app.get("/v1/admin/metrics_stub")
def metrics_stub(x_api_key: str | None = None):
    from fastapi import HTTPException

    from app.api.auth import require_user
    from app.models import Order

    require_user(x_api_key)
    with session_scope() as s:
        return {
            "orders_total": s.query(Order).count(),
            "orders_fulfilled": s.query(Order).filter(Order.status == "fulfilled").count(),
            "orders_failed": s.query(Order).filter(Order.status == "failed").count(),
            "queue_depth": get_queue().qsize(),
        }

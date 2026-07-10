"""Order fulfillment worker loop."""

from __future__ import annotations

import json
import logging
import os
import random
import sys
import time
from pathlib import Path

import yaml

_WS = Path(__file__).resolve().parents[2]
if str(_WS) not in sys.path:
    sys.path.insert(0, str(_WS))

from app.db import Base, get_engine, init_db, session_scope  # noqa: E402
from app.models import FulfillmentEvent, Order  # noqa: E402
from app.queue import get_queue  # noqa: E402

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger("shopstack.worker")


def load_cfg() -> dict:
    cfg_path = Path(os.environ.get("WORKER_CONFIG", str(_WS / "configs" / "worker.yaml")))
    if cfg_path.exists():
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        if isinstance(data, dict):
            return data
    return {"max_retries": 3, "enabled": True}


def process_job(payload: str, cfg: dict) -> None:
    data = json.loads(payload)
    order_id = int(data["order_id"])
    max_retries = int(cfg.get("max_retries", 3))
    attempt = int(data.get("attempt", 0))

    with session_scope() as s:
        order = s.get(Order, order_id)
        if order is None:
            logger.warning("order %s missing", order_id)
            return
        if order.status in ("fulfilled", "cancelled"):
            return
        order.status = "fulfilling"

    try:
        # Simulated fulfillment work
        time.sleep(float(cfg.get("work_seconds", 0.05)))
        with session_scope() as s:
            order = s.get(Order, order_id)
            if order is None:
                return
            order.status = "fulfilled"
            s.add(
                FulfillmentEvent(
                    order_id=order_id,
                    event_type="fulfilled",
                    payload_json=json.dumps({"attempt": attempt}),
                )
            )
        logger.info(json.dumps({"event": "fulfilled", "order_id": order_id}))
    except Exception as exc:  # noqa: BLE001
        logger.exception("fulfill failed order=%s", order_id)
        if attempt >= max_retries:
            get_queue().dead_letter(payload)
            with session_scope() as s:
                order = s.get(Order, order_id)
                if order:
                    order.status = "failed"
                    s.add(
                        FulfillmentEvent(
                            order_id=order_id,
                            event_type="failed",
                            payload_json=json.dumps({"error": str(exc)}),
                        )
                    )
            return
        time.sleep(min(2**attempt, 8) + random.random())
        data["attempt"] = attempt + 1
        get_queue().enqueue(json.dumps(data))


def run_forever() -> None:
    init_db()
    Base.metadata.create_all(get_engine())
    q = get_queue()
    logger.info("worker started")
    while True:
        cfg = load_cfg()
        if not cfg.get("enabled", True):
            time.sleep(0.5)
            continue
        # busy-loop protection: if max_retries absurdly high and no sleep path,
        # still brpop with timeout
        job = q.brpop(timeout=1.0)
        if job is None:
            continue
        process_job(job, cfg)


if __name__ == "__main__":
    run_forever()

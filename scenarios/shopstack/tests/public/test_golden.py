"""Public integration tests for Shopstack (agent-visible)."""

from __future__ import annotations

import os
import time
import uuid

import httpx
import pytest

BASE = os.environ.get("SHOPSTACK_BASE_URL", "http://127.0.0.1:8000")
API_KEY = os.environ.get("SHOPSTACK_API_KEY", "sk_test_cascade_demo_key")
HEADERS = {"X-API-Key": API_KEY}


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10.0) as c:
        # wait ready
        for _ in range(50):
            try:
                r = c.get("/ready")
                if r.status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(0.1)
        yield c


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_ready(client):
    r = client.get("/ready")
    assert r.status_code == 200
    assert r.json()["status"] == "ready"


def test_list_products_page1(client):
    r = client.get("/v1/products", params={"page": 1, "page_size": 10})
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) >= 1
    assert "price_cents" in items[0]
    assert items[0]["price_cents"] is not None


def test_unauth_order_rejected(client):
    r = client.post(
        "/v1/orders",
        json={"items": [{"product_id": 1, "qty": 1}]},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert r.status_code == 401


def test_order_fulfillment_and_idempotency(client):
    products = client.get("/v1/products").json()["items"]
    pid = products[0]["id"]
    key = f"pub-{uuid.uuid4()}"
    r = client.post(
        "/v1/orders",
        json={"items": [{"product_id": pid, "qty": 1}]},
        headers={**HEADERS, "Idempotency-Key": key},
    )
    assert r.status_code in (200, 201), r.text
    order_id = r.json()["id"]

    r2 = client.post(
        "/v1/orders",
        json={"items": [{"product_id": pid, "qty": 1}]},
        headers={**HEADERS, "Idempotency-Key": key},
    )
    assert r2.status_code in (200, 201)
    assert r2.json()["id"] == order_id

    status = r.json()["status"]
    for _ in range(40):
        gr = client.get(f"/v1/orders/{order_id}", headers=HEADERS)
        assert gr.status_code == 200
        status = gr.json()["status"]
        if status == "fulfilled":
            break
        time.sleep(0.25)
    assert status == "fulfilled", f"order stuck in {status}"

"""Order create / get / cancel routes."""

from __future__ import annotations

import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.api.auth import require_user
from app.db import session_scope
from app.models import Order, OrderItem, Product, User
from app.queue import get_queue

logger = logging.getLogger("shopstack.orders")
router = APIRouter(tags=["orders"])


class OrderItemIn(BaseModel):
    product_id: int
    qty: int = Field(ge=1, le=100)


class OrderCreate(BaseModel):
    items: list[OrderItemIn]


def _order_dict(order: Order, items: list[OrderItem] | None = None) -> dict:
    return {
        "id": order.id,
        "user_id": order.user_id,
        "status": order.status,
        "idempotency_key": order.idempotency_key,
        "total_cents": order.total_cents,
        "items": [
            {
                "product_id": i.product_id,
                "qty": i.qty,
                "unit_price_cents": i.unit_price_cents,
            }
            for i in (items or order.items or [])
        ],
    }


@router.post("/v1/orders", status_code=201)
def create_order(
    body: OrderCreate,
    user: Annotated[User, Depends(require_user)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    if not idempotency_key:
        raise HTTPException(status_code=400, detail="Idempotency-Key required")

    with session_scope() as s:
        existing = (
            s.query(Order)
            .filter(Order.idempotency_key == idempotency_key)
            .one_or_none()
        )
        if existing is not None:
            items = list(s.query(OrderItem).filter(OrderItem.order_id == existing.id).all())
            return _order_dict(existing, items)

        total = 0
        resolved: list[tuple[Product, int]] = []
        for item in body.items:
            product = s.get(Product, item.product_id)
            if product is None:
                raise HTTPException(status_code=404, detail=f"product {item.product_id}")
            if product.stock < item.qty:
                raise HTTPException(status_code=409, detail=f"insufficient stock for {product.sku}")
            resolved.append((product, item.qty))
            total += product.price_cents * item.qty

        order = Order(
            user_id=user.id,
            status="paid",
            idempotency_key=idempotency_key,
            total_cents=total,
        )
        s.add(order)
        s.flush()

        for product, qty in resolved:
            product.stock -= qty
            s.add(
                OrderItem(
                    order_id=order.id,
                    product_id=product.id,
                    qty=qty,
                    unit_price_cents=product.price_cents,
                )
            )

        order_id = order.id
        s.flush()
        logger.info(
            json.dumps(
                {
                    "event": "order_created",
                    "order_id": order_id,
                    "user_id": user.id,
                    "total_cents": total,
                }
            )
        )

    # enqueue after commit
    get_queue().enqueue(json.dumps({"order_id": order_id}))
    with session_scope() as s:
        order = s.get(Order, order_id)
        items = list(s.query(OrderItem).filter(OrderItem.order_id == order_id).all())
        return _order_dict(order, items)


@router.get("/v1/orders/{order_id}")
def get_order(
    order_id: int,
    user: Annotated[User, Depends(require_user)],
):
    with session_scope() as s:
        order = s.get(Order, order_id)
        if order is None or order.user_id != user.id:
            raise HTTPException(status_code=404, detail="not found")
        items = list(s.query(OrderItem).filter(OrderItem.order_id == order_id).all())
        return _order_dict(order, items)


@router.post("/v1/orders/{order_id}/cancel")
def cancel_order(
    order_id: int,
    user: Annotated[User, Depends(require_user)],
):
    with session_scope() as s:
        order = s.get(Order, order_id)
        if order is None or order.user_id != user.id:
            raise HTTPException(status_code=404, detail="not found")
        if order.status == "fulfilled":
            raise HTTPException(status_code=409, detail="already fulfilled")
        order.status = "cancelled"
        return _order_dict(order)

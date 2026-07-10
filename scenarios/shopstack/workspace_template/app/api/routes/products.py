"""Product catalog routes."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.db import session_scope
from app.models import Product

router = APIRouter(tags=["products"])


@router.get("/v1/products")
def list_products(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    offset = (page - 1) * page_size
    with session_scope() as s:
        rows = (
            s.query(Product)
            .order_by(Product.id)
            .offset(offset)
            .limit(page_size)
            .all()
        )
        return {
            "page": page,
            "page_size": page_size,
            "items": [
                {
                    "id": p.id,
                    "sku": p.sku,
                    "name": p.name,
                    "price_cents": p.price_cents,
                    "stock": p.stock,
                }
                for p in rows
            ],
        }


@router.get("/v1/products/{product_id}")
def get_product(product_id: int):
    with session_scope() as s:
        p = s.get(Product, product_id)
        if p is None:
            return {"error": "not_found"}
        return {
            "id": p.id,
            "sku": p.sku,
            "name": p.name,
            "price_cents": p.price_cents,
            "stock": p.stock,
        }

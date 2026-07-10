"""API-key authentication for the rollout server."""

from __future__ import annotations

import hmac
import secrets
from typing import Annotated

from fastapi import Header, HTTPException, status


class ApiKeyAuth:
    """Constant-time API key check via ``X-API-Key`` or ``Authorization: Bearer``."""

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("Server API key must be non-empty")
        self.api_key = api_key

    def __call__(
        self,
        x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
        authorization: Annotated[str | None, Header()] = None,
    ) -> str:
        presented = x_api_key
        if not presented and authorization:
            scheme, _, token = authorization.partition(" ")
            if scheme.lower() == "bearer" and token:
                presented = token.strip()
        if not presented or not hmac.compare_digest(presented, self.api_key):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing API key",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return presented


def generate_api_key() -> str:
    """Dev convenience: random key printed on server start when none configured."""
    return f"cascade_{secrets.token_urlsafe(24)}"

"""API key authentication for Shopstack."""

from __future__ import annotations

import hashlib
import os

from fastapi import Header, HTTPException

from app.db import session_scope
from app.models import User

# When True, mutating routes skip auth (fault / misconfig injection target)
DEBUG_BYPASS_AUTH = os.environ.get("DEBUG_BYPASS_AUTH", "0") == "1"

SEED_API_KEY = os.environ.get("SHOPSTACK_API_KEY", "sk_test_cascade_demo_key")


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def require_user(x_api_key: str | None = Header(default=None)) -> User:
    if DEBUG_BYPASS_AUTH:
        with session_scope() as s:
            user = s.query(User).first()
            if user is None:
                raise HTTPException(status_code=500, detail="no seed user")
            s.expunge(user)
            return user
    if not x_api_key:
        raise HTTPException(status_code=401, detail="missing X-API-Key")
    digest = hash_key(x_api_key)
    with session_scope() as s:
        user = s.query(User).filter(User.api_key_hash == digest).one_or_none()
        if user is None:
            raise HTTPException(status_code=401, detail="invalid api key")
        s.expunge(user)
        return user

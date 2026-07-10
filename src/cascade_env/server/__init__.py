"""HTTP rollout server for remote trainers (post-MVP / PR11).

Start with ``cascade serve`` (requires API key). OpenAPI at ``/docs``.
"""

from __future__ import annotations

from cascade_env.server.app import create_app

__all__ = ["create_app"]

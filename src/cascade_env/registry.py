"""Gymnasium registration for Cascade-v0."""

from __future__ import annotations

_REGISTERED = False


def register_cascade_v0() -> None:
    """Entry-point callback for gymnasium.envs."""
    register_envs()


def register_envs() -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    from gymnasium.envs.registration import register

    register(
        id="Cascade-v0",
        entry_point="cascade_env.env:CascadeEnv",
        nondeterministic=True,
    )
    _REGISTERED = True

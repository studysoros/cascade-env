"""Sparse reward: step cost only until terminal multi-verifier score."""

from __future__ import annotations

from cascade_env.types import VerifierResult


def step_reward(step_cost: float = 0.001, violation: float = 0.0) -> float:
    return -abs(step_cost) - abs(violation)


def terminal_reward(
    *,
    success: bool,
    partial: float,
    step_cost_accrued: float,
    violation_accrued: float = 0.0,
) -> float:
    base = 1.0 if success else 0.0
    return base + partial - step_cost_accrued - violation_accrued


def summarize_verifiers(results: list[VerifierResult]) -> dict[str, bool]:
    return {r.id: r.passed for r in results}

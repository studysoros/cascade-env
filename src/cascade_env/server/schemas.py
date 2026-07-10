"""Request/response models for the Cascade rollout HTTP API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CreateEpisodeRequest(BaseModel):
    pack: str = "community"
    task_id: str | None = None
    seed: int = 0
    runtime: str = Field(default="local", pattern="^(local|compose)$")
    max_steps: int | None = Field(default=None, ge=1, le=500)
    show_hints: bool = False


class ActionRequest(BaseModel):
    """Single tool action (same semantics as Gymnasium ``env.step``)."""

    tool: str
    args: dict[str, Any] = Field(default_factory=dict)


class CreateEpisodeResponse(BaseModel):
    episode_id: str
    observation: dict[str, Any]
    info: dict[str, Any]


class StepResponse(BaseModel):
    episode_id: str
    observation: dict[str, Any]
    reward: float
    terminated: bool
    truncated: bool
    info: dict[str, Any]


class CloseResponse(BaseModel):
    episode_id: str
    closed: bool = True


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    active_episodes: int
    max_parallel_episodes: int


class MetricsResponse(BaseModel):
    """Process-local counters and latency histograms (no Prometheus)."""

    uptime_s: float
    active_episodes: int
    max_parallel_episodes: int
    counters: dict[str, int]
    histograms: dict[str, dict[str, Any]]


class ErrorBody(BaseModel):
    detail: str
    error_code: str | None = None

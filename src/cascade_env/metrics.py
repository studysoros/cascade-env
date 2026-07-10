"""In-process counters and latency histograms (PR12).

No Prometheus dependency: snapshots are plain JSON for ``GET /v1/metrics``
and operator debugging. Thread-safe; process-local only.
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field
from typing import Any


# Fixed latency buckets (milliseconds) — enough for provision (~minutes) and steps.
_DEFAULT_BUCKETS_MS: tuple[float, ...] = (
    1,
    5,
    10,
    25,
    50,
    100,
    250,
    500,
    1_000,
    2_500,
    5_000,
    10_000,
    30_000,
    60_000,
    120_000,
    300_000,
)


@dataclass
class Histogram:
    """Simple histogram with fixed upper-bound buckets + overflow."""

    name: str
    buckets_ms: tuple[float, ...] = _DEFAULT_BUCKETS_MS
    _counts: list[int] = field(default_factory=list)
    _overflow: int = 0
    _sum_ms: float = 0.0
    _count: int = 0
    _min_ms: float = math.inf
    _max_ms: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        if not self._counts:
            self._counts = [0] * len(self.buckets_ms)

    def observe(self, value_ms: float) -> None:
        if value_ms < 0 or math.isnan(value_ms):
            return
        with self._lock:
            self._count += 1
            self._sum_ms += value_ms
            if value_ms < self._min_ms:
                self._min_ms = value_ms
            if value_ms > self._max_ms:
                self._max_ms = value_ms
            placed = False
            for i, upper in enumerate(self.buckets_ms):
                if value_ms <= upper:
                    self._counts[i] += 1
                    placed = True
                    break
            if not placed:
                self._overflow += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            count = self._count
            if count == 0:
                return {
                    "count": 0,
                    "sum_ms": 0.0,
                    "avg_ms": 0.0,
                    "min_ms": None,
                    "max_ms": None,
                    "p50_ms": None,
                    "p95_ms": None,
                    "p99_ms": None,
                    "buckets": {},
                }
            buckets: dict[str, int] = {
                f"le_{int(b) if b == int(b) else b}": c
                for b, c in zip(self.buckets_ms, self._counts)
            }
            buckets["le_+Inf"] = self._overflow
            return {
                "count": count,
                "sum_ms": round(self._sum_ms, 3),
                "avg_ms": round(self._sum_ms / count, 3),
                "min_ms": round(self._min_ms, 3),
                "max_ms": round(self._max_ms, 3),
                "p50_ms": self._percentile_unlocked(0.50),
                "p95_ms": self._percentile_unlocked(0.95),
                "p99_ms": self._percentile_unlocked(0.99),
                "buckets": buckets,
            }

    def _percentile_unlocked(self, q: float) -> float | None:
        """Approximate percentile from cumulative buckets (upper bound of target bucket)."""
        if self._count == 0:
            return None
        target = max(1, int(math.ceil(q * self._count)))
        cum = 0
        for upper, c in zip(self.buckets_ms, self._counts):
            cum += c
            if cum >= target:
                return float(upper)
        return float(self.buckets_ms[-1]) if self._overflow == 0 else None

    def reset(self) -> None:
        with self._lock:
            self._counts = [0] * len(self.buckets_ms)
            self._overflow = 0
            self._sum_ms = 0.0
            self._count = 0
            self._min_ms = math.inf
            self._max_ms = 0.0


class MetricsRegistry:
    """Process-local metrics store for Cascade control plane."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, int] = {}
        self._histograms: dict[str, Histogram] = {}
        self._started_at = time.time()
        # Pre-register well-known series so empty snapshots are stable.
        for name in (
            "episodes_created",
            "episodes_closed",
            "episodes_success",
            "episodes_failed",
            "provisions_ok",
            "provisions_failed",
            "steps_total",
            "verifies_total",
            "capacity_rejects",
            "ttl_reaped",
        ):
            self._counters[name] = 0
        for name in ("provision_ms", "step_ms", "verify_ms"):
            self._histograms[name] = Histogram(name=name)

    def inc(self, name: str, delta: int = 1) -> None:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + int(delta)

    def observe(self, histogram: str, value_ms: float) -> None:
        with self._lock:
            hist = self._histograms.get(histogram)
            if hist is None:
                hist = Histogram(name=histogram)
                self._histograms[histogram] = hist
        hist.observe(value_ms)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            counters = dict(self._counters)
            hist_names = list(self._histograms.keys())
        histograms = {n: self._histograms[n].snapshot() for n in hist_names}
        return {
            "uptime_s": round(time.time() - self._started_at, 3),
            "counters": counters,
            "histograms": histograms,
        }

    def reset(self) -> None:
        """Clear all series (tests)."""
        with self._lock:
            for k in self._counters:
                self._counters[k] = 0
            # Drop any ad-hoc counters added after init
            known = {
                "episodes_created",
                "episodes_closed",
                "episodes_success",
                "episodes_failed",
                "provisions_ok",
                "provisions_failed",
                "steps_total",
                "verifies_total",
                "capacity_rejects",
                "ttl_reaped",
            }
            for k in list(self._counters.keys()):
                if k not in known:
                    del self._counters[k]
            for h in self._histograms.values():
                h.reset()
            self._started_at = time.time()


_REGISTRY = MetricsRegistry()
_REGISTRY_LOCK = threading.Lock()


def get_metrics() -> MetricsRegistry:
    return _REGISTRY


def reset_metrics() -> None:
    """Reset the global registry (tests)."""
    with _REGISTRY_LOCK:
        _REGISTRY.reset()


class Timer:
    """Context manager that observes elapsed milliseconds into a histogram."""

    def __init__(self, histogram: str, *, metrics: MetricsRegistry | None = None) -> None:
        self.histogram = histogram
        self.metrics = metrics or get_metrics()
        self._t0 = 0.0
        self.elapsed_ms = 0.0

    def __enter__(self) -> Timer:
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *exc: object) -> None:
        self.elapsed_ms = (time.perf_counter() - self._t0) * 1000.0
        self.metrics.observe(self.histogram, self.elapsed_ms)

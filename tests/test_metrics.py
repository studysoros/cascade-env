"""Unit tests for PR12 metrics registry and histograms."""

from __future__ import annotations

from cascade_env.metrics import Histogram, MetricsRegistry, Timer, get_metrics, reset_metrics


def setup_function() -> None:
    reset_metrics()


def teardown_function() -> None:
    reset_metrics()


def test_counter_inc():
    m = MetricsRegistry()
    m.inc("steps_total", 3)
    m.inc("steps_total")
    snap = m.snapshot()
    assert snap["counters"]["steps_total"] == 4


def test_histogram_observe_and_percentiles():
    h = Histogram(name="t", buckets_ms=(10, 50, 100, 500))
    for v in (5, 20, 40, 80, 200):
        h.observe(v)
    snap = h.snapshot()
    assert snap["count"] == 5
    assert snap["min_ms"] == 5
    assert snap["max_ms"] == 200
    assert snap["avg_ms"] == 69.0
    # p50 lands in bucket le_50 (cumulative covers 3 of 5 samples by 50ms)
    assert snap["p50_ms"] == 50
    assert snap["buckets"]["le_10"] == 1
    assert snap["buckets"]["le_50"] == 2  # 20, 40
    assert snap["buckets"]["le_100"] == 1  # 80
    assert snap["buckets"]["le_500"] == 1  # 200


def test_timer_context_manager():
    m = MetricsRegistry()
    with Timer("step_ms", metrics=m) as t:
        pass
    assert t.elapsed_ms >= 0
    assert m.snapshot()["histograms"]["step_ms"]["count"] == 1


def test_global_registry_reset():
    get_metrics().inc("capacity_rejects", 2)
    assert get_metrics().snapshot()["counters"]["capacity_rejects"] == 2
    reset_metrics()
    assert get_metrics().snapshot()["counters"]["capacity_rejects"] == 0


def test_empty_histogram_snapshot():
    h = Histogram(name="empty")
    snap = h.snapshot()
    assert snap["count"] == 0
    assert snap["p50_ms"] is None
    assert snap["min_ms"] is None

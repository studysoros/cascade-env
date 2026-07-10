"""Tests for HTTP rollout server (auth, capacity, full scripted episode)."""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from cascade_env.agents.scripted import scripted_policy
from cascade_env.config import CascadeConfig
from cascade_env.metrics import reset_metrics
from cascade_env.server.app import create_app
from cascade_env.server.auth import ApiKeyAuth, generate_api_key
from cascade_env.server.session import SessionError, SessionStore
from cascade_env.version import __version__

API_KEY = "test-cascade-server-key"


@pytest.fixture(autouse=True)
def _reset_metrics():
    reset_metrics()
    yield
    reset_metrics()


@pytest.fixture
def server_config(tmp_path) -> CascadeConfig:
    return CascadeConfig(
        enable_http_server=True,
        server_api_key=API_KEY,
        max_parallel_episodes=2,
        work_root=tmp_path / "episodes",
        runtime="local",
        max_steps=40,
    )


@pytest.fixture
def client(server_config: CascadeConfig) -> TestClient:
    app = create_app(api_key=API_KEY, config=server_config)
    with TestClient(app) as c:
        yield c


def _auth_headers(key: str = API_KEY) -> dict[str, str]:
    return {"X-API-Key": key}


def test_generate_api_key_format():
    k = generate_api_key()
    assert k.startswith("cascade_")
    assert len(k) > 20


def test_auth_accepts_bearer():
    auth = ApiKeyAuth("secret")
    assert auth(x_api_key=None, authorization="Bearer secret") == "secret"


def test_auth_rejects_bad_key():
    auth = ApiKeyAuth("secret")
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as ei:
        auth(x_api_key="wrong", authorization=None)
    assert ei.value.status_code == 401


def test_health_unauthenticated(client: TestClient):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
    assert body["active_episodes"] == 0


def test_v1_requires_api_key(client: TestClient):
    r = client.post(
        "/v1/episodes",
        json={"task_id": "community.T2.pagination_off_by_one.v1", "seed": 0},
    )
    assert r.status_code == 401

    r2 = client.post(
        "/v1/episodes",
        json={"task_id": "community.T2.pagination_off_by_one.v1", "seed": 0},
        headers={"X-API-Key": "wrong"},
    )
    assert r2.status_code == 401


def test_create_app_requires_key(server_config: CascadeConfig):
    with pytest.raises(ValueError, match="API key"):
        create_app(api_key="", config=server_config.model_copy(update={"server_api_key": ""}))


def test_unknown_episode_404(client: TestClient):
    r = client.post(
        "/v1/episodes/ep_does_not_exist/step",
        json={"tool": "services.ps", "args": {}},
        headers=_auth_headers(),
    )
    assert r.status_code == 404
    assert r.json().get("error_code") == "NOT_FOUND"


def test_max_parallel_capacity(tmp_path):
    """Capacity guard returns 429 when max_parallel_episodes is saturated."""
    cfg = CascadeConfig(
        enable_http_server=True,
        server_api_key=API_KEY,
        max_parallel_episodes=1,
        work_root=tmp_path / "episodes",
        runtime="local",
        max_steps=40,
    )
    store = SessionStore(cfg)
    app = create_app(api_key=API_KEY, config=cfg, store=store)
    with TestClient(app) as c:
        r1 = c.post(
            "/v1/episodes",
            json={
                "task_id": "community.T2.pagination_off_by_one.v1",
                "seed": 0,
                "max_steps": 40,
            },
            headers=_auth_headers(),
        )
        assert r1.status_code == 201, r1.text
        ep1 = r1.json()["episode_id"]

        r2 = c.post(
            "/v1/episodes",
            json={
                "task_id": "community.T3.worker_disabled_config.v1",
                "seed": 0,
                "max_steps": 40,
            },
            headers=_auth_headers(),
        )
        assert r2.status_code == 429
        assert r2.json().get("error_code") == "CAPACITY"

        # free capacity
        r_close = c.post(f"/v1/episodes/{ep1}/close", headers=_auth_headers())
        assert r_close.status_code == 200

        r3 = c.post(
            "/v1/episodes",
            json={
                "task_id": "community.T3.worker_disabled_config.v1",
                "seed": 0,
                "max_steps": 3,
            },
            headers=_auth_headers(),
        )
        assert r3.status_code == 201, r3.text
        ep3 = r3.json()["episode_id"]
        c.post(f"/v1/episodes/{ep3}/close", headers=_auth_headers())


def test_scripted_episode_over_http(client: TestClient):
    """Done-when: remote client completes one scripted episode over HTTP."""
    r = client.post(
        "/v1/episodes",
        json={
            "pack": "community",
            "task_id": "community.T2.pagination_off_by_one.v1",
            "seed": 0,
            "runtime": "local",
            "max_steps": 40,
        },
        headers=_auth_headers(),
    )
    assert r.status_code == 201, r.text
    created = r.json()
    episode_id = created["episode_id"]
    obs = created["observation"]
    info = created.get("info") or {}
    assert episode_id.startswith("ep_")
    assert obs["task"]["id"] == "community.T2.pagination_off_by_one.v1"

    terminated = truncated = False
    last_info: dict[str, Any] = info
    steps = 0
    while not (terminated or truncated):
        action = scripted_policy(obs, last_info)
        sr = client.post(
            f"/v1/episodes/{episode_id}/step",
            json={"tool": action["tool"], "args": action.get("args") or {}},
            headers=_auth_headers(),
        )
        assert sr.status_code == 200, sr.text
        body = sr.json()
        obs = body["observation"]
        terminated = body["terminated"]
        truncated = body["truncated"]
        last_info = body.get("info") or {}
        steps += 1
        assert steps < 50

    assert terminated or truncated
    assert last_info.get("success") is True
    assert float(last_info.get("terminal_reward", 0)) > 0.5

    # Idempotent close after terminal
    cr = client.post(f"/v1/episodes/{episode_id}/close", headers=_auth_headers())
    assert cr.status_code == 200
    assert cr.json()["closed"] is True

    # Further steps rejected
    bad = client.post(
        f"/v1/episodes/{episode_id}/step",
        json={"tool": "services.ps", "args": {}},
        headers=_auth_headers(),
    )
    assert bad.status_code == 409


def test_openapi_available(client: TestClient):
    r = client.get("/openapi.json")
    assert r.status_code == 200
    spec = r.json()
    assert "/v1/episodes" in spec["paths"]
    assert "/v1/episodes/{episode_id}/step" in spec["paths"]
    assert "Cascade Rollout API" in spec["info"]["title"]


def test_cli_serve_help():
    from cascade_env.cli import main

    with pytest.raises(SystemExit) as ei:
        main(["serve", "--help"])
    assert ei.value.code == 0


def test_bearer_auth_on_create(client: TestClient):
    r = client.post(
        "/v1/episodes",
        json={
            "task_id": "community.T2.pagination_off_by_one.v1",
            "seed": 0,
            "max_steps": 5,
        },
        headers={"Authorization": f"Bearer {API_KEY}"},
    )
    assert r.status_code == 201, r.text
    ep = r.json()["episode_id"]
    # immediate close without solving
    client.delete(f"/v1/episodes/{ep}", headers={"Authorization": f"Bearer {API_KEY}"})


def test_metrics_requires_auth(client: TestClient):
    r = client.get("/v1/metrics")
    assert r.status_code == 401


def test_metrics_after_scripted_episode(client: TestClient):
    """Provision/step/verify histograms and counters update after a real episode."""
    r = client.post(
        "/v1/episodes",
        json={
            "task_id": "community.T2.pagination_off_by_one.v1",
            "seed": 0,
            "max_steps": 40,
        },
        headers=_auth_headers(),
    )
    assert r.status_code == 201, r.text
    created = r.json()
    episode_id = created["episode_id"]
    assert "provision_ms" in created.get("info", {})
    obs = created["observation"]
    info = created.get("info") or {}

    terminated = truncated = False
    while not (terminated or truncated):
        action = scripted_policy(obs, info)
        sr = client.post(
            f"/v1/episodes/{episode_id}/step",
            json={"tool": action["tool"], "args": action.get("args") or {}},
            headers=_auth_headers(),
        )
        assert sr.status_code == 200, sr.text
        body = sr.json()
        obs = body["observation"]
        terminated = body["terminated"]
        truncated = body["truncated"]
        info = body.get("info") or {}

    mr = client.get("/v1/metrics", headers=_auth_headers())
    assert mr.status_code == 200, mr.text
    metrics = mr.json()
    assert metrics["active_episodes"] == 0
    assert metrics["max_parallel_episodes"] == 2
    counters = metrics["counters"]
    assert counters["episodes_created"] >= 1
    assert counters["provisions_ok"] >= 1
    assert counters["steps_total"] >= 1
    assert counters["verifies_total"] >= 1
    assert counters["episodes_success"] >= 1
    hist = metrics["histograms"]
    assert hist["provision_ms"]["count"] >= 1
    assert hist["provision_ms"]["max_ms"] is not None
    assert hist["step_ms"]["count"] >= 1
    assert hist["verify_ms"]["count"] >= 1


def test_capacity_reject_increments_metric(tmp_path):
    cfg = CascadeConfig(
        enable_http_server=True,
        server_api_key=API_KEY,
        max_parallel_episodes=1,
        work_root=tmp_path / "episodes",
        runtime="local",
        max_steps=40,
    )
    store = SessionStore(cfg, enable_ttl_reaper=False)
    app = create_app(api_key=API_KEY, config=cfg, store=store)
    with TestClient(app) as c:
        r1 = c.post(
            "/v1/episodes",
            json={"task_id": "community.T2.pagination_off_by_one.v1", "seed": 0},
            headers=_auth_headers(),
        )
        assert r1.status_code == 201, r1.text
        r2 = c.post(
            "/v1/episodes",
            json={"task_id": "community.T3.worker_disabled_config.v1", "seed": 0},
            headers=_auth_headers(),
        )
        assert r2.status_code == 429
        m = c.get("/v1/metrics", headers=_auth_headers()).json()
        assert m["counters"]["capacity_rejects"] >= 1
        c.post(f"/v1/episodes/{r1.json()['episode_id']}/close", headers=_auth_headers())


def test_session_ttl_reap(tmp_path):
    """Expired sessions are reaped and free capacity."""
    cfg = CascadeConfig(
        enable_http_server=True,
        server_api_key=API_KEY,
        max_parallel_episodes=1,
        episode_ttl_s=1,
        work_root=tmp_path / "episodes",
        runtime="local",
        max_steps=40,
    )
    store = SessionStore(cfg, enable_ttl_reaper=False)
    app = create_app(api_key=API_KEY, config=cfg, store=store)
    with TestClient(app) as c:
        r1 = c.post(
            "/v1/episodes",
            json={
                "task_id": "community.T2.pagination_off_by_one.v1",
                "seed": 0,
                "max_steps": 5,
            },
            headers=_auth_headers(),
        )
        assert r1.status_code == 201, r1.text
        ep1 = r1.json()["episode_id"]
        session = store.get_session(ep1)
        assert session is not None
        # Force age past TTL without sleeping long
        session.created_at = time.time() - 10

        reaped = store.reap_expired()
        assert reaped == 1
        assert session.closed is True

        # Capacity free again
        r2 = c.post(
            "/v1/episodes",
            json={
                "task_id": "community.T3.worker_disabled_config.v1",
                "seed": 0,
                "max_steps": 3,
            },
            headers=_auth_headers(),
        )
        assert r2.status_code == 201, r2.text
        c.post(f"/v1/episodes/{r2.json()['episode_id']}/close", headers=_auth_headers())

        m = c.get("/v1/metrics", headers=_auth_headers()).json()
        assert m["counters"]["ttl_reaped"] >= 1


def test_step_on_expired_returns_410(tmp_path):
    cfg = CascadeConfig(
        enable_http_server=True,
        server_api_key=API_KEY,
        max_parallel_episodes=1,
        episode_ttl_s=1,
        work_root=tmp_path / "episodes",
        runtime="local",
        max_steps=40,
    )
    store = SessionStore(cfg, enable_ttl_reaper=False)
    app = create_app(api_key=API_KEY, config=cfg, store=store)
    with TestClient(app) as c:
        r1 = c.post(
            "/v1/episodes",
            json={
                "task_id": "community.T2.pagination_off_by_one.v1",
                "seed": 0,
                "max_steps": 5,
            },
            headers=_auth_headers(),
        )
        assert r1.status_code == 201, r1.text
        ep = r1.json()["episode_id"]
        session = store.get_session(ep)
        assert session is not None
        session.created_at = time.time() - 10

        bad = c.post(
            f"/v1/episodes/{ep}/step",
            json={"tool": "services.ps", "args": {}},
            headers=_auth_headers(),
        )
        assert bad.status_code == 410
        assert bad.json().get("error_code") == "EXPIRED"


def test_compose_debug_refuses_when_max_parallel_gt_1():
    from cascade_env.runtime.compose import ComposeRuntimeBackend

    backend = ComposeRuntimeBackend.__new__(ComposeRuntimeBackend)
    with patch("cascade_env.runtime.compose.get_config") as gc:
        cfg = MagicMock()
        cfg.max_parallel_episodes = 2
        gc.return_value = cfg
        with pytest.raises(RuntimeError, match="max_parallel_episodes"):
            backend._assert_debug_safe()


def test_session_error_shape():
    err = SessionError("full", status_code=429, error_code="CAPACITY")
    assert err.status_code == 429
    assert err.error_code == "CAPACITY"


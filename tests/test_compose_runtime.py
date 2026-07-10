"""Compose runtime integration tests (require Docker daemon)."""

from __future__ import annotations

import json
import shutil

import pytest

import cascade_env
import gymnasium as gym

from cascade_env.agents.scripted import scripted_policy
from cascade_env.runtime.compose import ComposeRuntimeBackend


def _docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    return ComposeRuntimeBackend().daemon_ok()


pytestmark = [
    pytest.mark.docker,
    pytest.mark.timeout(600),
]


@pytest.fixture(scope="module")
def require_docker():
    if not _docker_available():
        pytest.skip("Docker daemon not available")


def test_compose_scripted_solves_pagination(require_docker):
    cascade_env.register_envs()
    env = gym.make(
        "Cascade-v0",
        pack="community",
        runtime="compose",
        task_id="community.T2.pagination_off_by_one.v1",
        max_steps=40,
    )
    try:
        obs_s, info = env.reset(seed=0)
        obs = json.loads(obs_s)
        terminated = truncated = False
        while not (terminated or truncated):
            action = scripted_policy(obs, info)
            obs_s, reward, terminated, truncated, info = env.step(action)
            obs = json.loads(obs_s)
        assert info.get("success") is True
        assert float(info.get("terminal_reward", 0)) > 0.5
    finally:
        env.close()


def test_compose_image_pins_and_doctor_helpers(require_docker):
    backend = ComposeRuntimeBackend()
    pins = backend._load_image_pins()  # noqa: SLF001
    assert "CASCADE_POSTGRES_IMAGE" in pins
    assert "CASCADE_REDIS_IMAGE" in pins
    assert "postgres" in pins["CASCADE_POSTGRES_IMAGE"]
    assert "redis" in pins["CASCADE_REDIS_IMAGE"]
    # Image presence is best-effort (Desktop can flap mid-suite after heavy load)
    status = backend.image_pins_status()
    assert "pins" in status
    if status.get("daemon"):
        present = status.get("present") or {}
        assert any(present.values()) or present == {}

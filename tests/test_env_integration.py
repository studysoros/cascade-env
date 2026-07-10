"""Integration tests against local runtime (no Docker)."""

from __future__ import annotations

import json

import pytest

import cascade_env
import gymnasium as gym

from cascade_env.agents.scripted import scripted_policy


@pytest.fixture
def env_pagination():
    cascade_env.register_envs()
    env = gym.make(
        "Cascade-v0",
        pack="community",
        runtime="local",
        task_id="community.T2.pagination_off_by_one.v1",
        max_steps=40,
    )
    yield env
    env.close()


def test_scripted_solves_pagination(env_pagination):
    obs_s, info = env_pagination.reset(seed=0)
    obs = json.loads(obs_s)
    terminated = truncated = False
    while not (terminated or truncated):
        action = scripted_policy(obs, info)
        obs_s, reward, terminated, truncated, info = env_pagination.step(action)
        obs = json.loads(obs_s)
    assert info.get("success") is True
    assert float(info.get("terminal_reward", 0)) > 0.5


def test_unsolved_config_task_fails():
    cascade_env.register_envs()
    env = gym.make(
        "Cascade-v0",
        pack="community",
        runtime="local",
        task_id="community.T3.worker_disabled_config.v1",
        max_steps=3,
    )
    try:
        obs_s, info = env.reset(seed=0)
        # immediately submit without fixing
        for _ in range(3):
            obs_s, reward, term, trunc, info = env.step({"tool": "submit.done", "args": {}})
            if term or trunc:
                break
        assert info.get("success") is False
    finally:
        env.close()

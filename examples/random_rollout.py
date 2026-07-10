"""Short random tool rollout (does not attempt to solve)."""

from __future__ import annotations

import json

import cascade_env
import gymnasium as gym


def main() -> None:
    cascade_env.register_envs()
    env = gym.make(
        "Cascade-v0",
        pack="community",
        runtime="local",
        task_id="community.T3.worker_disabled_config.v1",
        max_steps=5,
    )
    try:
        obs_s, info = env.reset(seed=1)
        print("episode", info["episode_id"])
        actions = [
            {"tool": "services.ps", "args": {}},
            {"tool": "http.request", "args": {"method": "GET", "path": "/health"}},
            {"tool": "files.list", "args": {"path": "configs"}},
            {"tool": "logs.tail", "args": {"service": "api", "lines": 20}},
            {"tool": "submit.done", "args": {}},
        ]
        for action in actions:
            obs_s, reward, term, trunc, info = env.step(action)
            print(action["tool"], "r=", reward, "term=", term, "success=", info.get("success"))
            if term or trunc:
                break
    finally:
        env.close()


if __name__ == "__main__":
    main()

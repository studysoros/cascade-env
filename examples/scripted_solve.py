"""Solve a community task with the scripted baseline agent."""

from __future__ import annotations

import json
import sys

import cascade_env
import gymnasium as gym

from cascade_env.agents.scripted import scripted_policy


def main() -> int:
    cascade_env.register_envs()
    task = sys.argv[1] if len(sys.argv) > 1 else "community.T2.pagination_off_by_one.v1"
    env = gym.make("Cascade-v0", pack="community", runtime="local", task_id=task, max_steps=40)
    try:
        obs_s, info = env.reset(seed=0)
        obs = json.loads(obs_s)
        print("task:", obs["task"]["id"], "-", obs["task"]["title"])
        terminated = truncated = False
        while not (terminated or truncated):
            action = scripted_policy(obs, info)
            obs_s, reward, terminated, truncated, info = env.step(action)
            obs = json.loads(obs_s)
            print(f"step={obs['step']} tool={action['tool']} reward={reward:.4f}")
        print("success:", info.get("success"))
        print("terminal_reward:", info.get("terminal_reward"))
        print("verifiers:", {v["id"]: v["passed"] for v in info.get("verifiers", [])})
        print("trajectory:", info.get("trajectory_path"))
        return 0 if info.get("success") else 1
    finally:
        env.close()


if __name__ == "__main__":
    raise SystemExit(main())

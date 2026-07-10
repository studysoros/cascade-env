"""Complete one scripted Cascade episode over the HTTP rollout server.

Prerequisites:
  Terminal A:
    uv run cascade serve --api-key dev-key

  Terminal B:
    uv run python examples/remote_client.py --api-key dev-key

Or set CASCADE_SERVER_API_KEY in both terminals and omit --api-key.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import httpx

from cascade_env.agents.scripted import scripted_policy


class RolloutClient:
    """Minimal HTTP client for Cascade ``/v1/episodes`` APIs."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8765",
        api_key: str = "",
        timeout_s: float = 300.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._client = httpx.Client(
            base_url=self.base_url,
            headers={"X-API-Key": api_key},
            timeout=timeout_s,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> RolloutClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def health(self) -> dict:
        r = self._client.get("/health")
        r.raise_for_status()
        return r.json()

    def create_episode(
        self,
        *,
        pack: str = "community",
        task_id: str | None = None,
        seed: int = 0,
        runtime: str = "local",
        max_steps: int | None = 40,
    ) -> dict:
        body = {
            "pack": pack,
            "task_id": task_id,
            "seed": seed,
            "runtime": runtime,
            "max_steps": max_steps,
        }
        r = self._client.post("/v1/episodes", json=body)
        r.raise_for_status()
        return r.json()

    def step(self, episode_id: str, action: dict) -> dict:
        r = self._client.post(
            f"/v1/episodes/{episode_id}/step",
            json={"tool": action["tool"], "args": action.get("args") or {}},
        )
        r.raise_for_status()
        return r.json()

    def close_episode(self, episode_id: str) -> dict:
        r = self._client.post(f"/v1/episodes/{episode_id}/close")
        r.raise_for_status()
        return r.json()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Remote scripted episode via Cascade HTTP API")
    p.add_argument(
        "--base-url",
        default=os.environ.get("CASCADE_SERVER_URL", "http://127.0.0.1:8765"),
    )
    p.add_argument(
        "--api-key",
        default=os.environ.get("CASCADE_SERVER_API_KEY")
        or os.environ.get("CASCADE_API_KEY")
        or "",
    )
    p.add_argument("--pack", default="community")
    p.add_argument("--task", default="community.T2.pagination_off_by_one.v1")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--runtime", default="local", choices=["local", "compose"])
    p.add_argument("--max-steps", type=int, default=40)
    args = p.parse_args(argv)

    if not args.api_key:
        print(
            "error: set CASCADE_SERVER_API_KEY or pass --api-key",
            file=sys.stderr,
        )
        return 2

    with RolloutClient(base_url=args.base_url, api_key=args.api_key) as client:
        try:
            h = client.health()
            print(f"server ok version={h.get('version')} active={h.get('active_episodes')}")
        except httpx.HTTPError as exc:
            print(f"error: cannot reach server at {args.base_url}: {exc}", file=sys.stderr)
            print("start with: uv run cascade serve --api-key <key>", file=sys.stderr)
            return 2

        created = client.create_episode(
            pack=args.pack,
            task_id=args.task,
            seed=args.seed,
            runtime=args.runtime,
            max_steps=args.max_steps,
        )
        episode_id = created["episode_id"]
        obs = created["observation"]
        info = created.get("info") or {}
        print(f"episode={episode_id} task={obs.get('task', {}).get('id')}")
        print(f"title: {obs.get('task', {}).get('title')}")

        terminated = truncated = False
        total_r = 0.0
        try:
            while not (terminated or truncated):
                action = scripted_policy(obs, info)
                result = client.step(episode_id, action)
                obs = result["observation"]
                reward = float(result["reward"])
                terminated = bool(result["terminated"])
                truncated = bool(result["truncated"])
                info = result.get("info") or {}
                total_r += reward
                tr = info.get("tool_result") or {}
                print(
                    f"step={obs.get('step')} tool={action.get('tool')} "
                    f"r={reward:.4f} ok={tr.get('ok')} term={terminated} trunc={truncated}"
                )
        finally:
            try:
                client.close_episode(episode_id)
            except httpx.HTTPError:
                pass

        out = {
            "success": info.get("success"),
            "terminal_reward": info.get("terminal_reward", total_r),
            "total_step_reward": total_r,
            "verifiers": {
                v["id"]: v["passed"] for v in info.get("verifiers", []) if isinstance(v, dict)
            },
            "episode_id": episode_id,
        }
        print(json.dumps(out, indent=2))
        return 0 if info.get("success") else 2


if __name__ == "__main__":
    raise SystemExit(main())

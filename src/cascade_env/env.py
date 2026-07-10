"""Gymnasium environment: Cascade-v0 (tool-calling agent env)."""

from __future__ import annotations

import json
import string
from typing import Any, SupportsFloat

import gymnasium as gym
from gymnasium import spaces

from cascade_env.config import CascadeConfig, get_config
from cascade_env.episode import EpisodeManager
from cascade_env.types import Action, Observation

# JSON observations include whitespace/control chars outside Gymnasium's default charset
_JSON_CHARSET = (
    string.printable
    + "".join(chr(c) for c in range(0xA0, 0x100))
    + "\u2013\u2014\u2018\u2019\u201c\u201d\u2026"
)


class CascadeEnv(gym.Env):
    """
    Tool-calling production systems RL environment.

    observation_space / action_space are Text(JSON) for LLM agent trainers.
    Structured objects are always available in info['obs'] and via typed APIs.
    """

    metadata = {"render_modes": []}

    def __init__(
        self,
        pack: str = "community",
        task_id: str | None = None,
        runtime: str = "local",
        seed: int | None = None,
        max_steps: int | None = None,
        show_hints: bool = False,
        config: CascadeConfig | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__()
        overrides: dict[str, Any] = {
            "pack": pack,
            "runtime": runtime,
            "show_hints": show_hints,
        }
        if max_steps is not None:
            overrides["max_steps"] = max_steps
        self.config = (config or get_config()).model_copy(update=overrides)
        self.default_task_id = task_id
        self.default_seed = seed
        self.manager = EpisodeManager(self.config)

        # Opaque JSON text spaces for tool-calling agents
        self.observation_space = spaces.Text(max_length=200_000, charset=_JSON_CHARSET)
        self.action_space = spaces.Text(max_length=100_000, charset=_JSON_CHARSET)

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        super().reset(seed=seed)
        options = options or {}
        pack = options.get("pack", self.config.pack)
        task_id = options.get("task_id", self.default_task_id)
        use_seed = seed if seed is not None else self.default_seed
        obs, info = self.manager.reset(pack=pack, task_id=task_id, seed=use_seed)
        return self._encode_obs(obs), info

    def step(
        self, action: str | dict[str, Any] | Action
    ) -> tuple[str, SupportsFloat, bool, bool, dict[str, Any]]:
        parsed = self._parse_action(action)
        obs, reward, terminated, truncated, info = self.manager.step(parsed)
        return self._encode_obs(obs), reward, terminated, truncated, info

    def close(self) -> None:
        self.manager.close()
        super().close()

    def _encode_obs(self, obs: Observation) -> str:
        return json.dumps(obs.model_dump(mode="json"), ensure_ascii=False)

    def _parse_action(self, action: str | dict[str, Any] | Action) -> Action:
        if isinstance(action, Action):
            return action
        if isinstance(action, dict):
            return Action.model_validate(action)
        if isinstance(action, str):
            data = json.loads(action)
            return Action.model_validate(data)
        raise TypeError(f"Unsupported action type: {type(action)}")

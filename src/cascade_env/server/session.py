"""In-process episode session store for the HTTP rollout server."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from cascade_env.config import CascadeConfig, get_config
from cascade_env.env import CascadeEnv
from cascade_env.server.schemas import CreateEpisodeRequest
from cascade_env.types import Action


class SessionError(Exception):
    def __init__(self, message: str, *, status_code: int = 400, error_code: str = "SESSION") -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code


@dataclass
class EpisodeSession:
    episode_id: str
    env: CascadeEnv | None
    created_at: float = field(default_factory=time.time)
    closed: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def is_placeholder(self) -> bool:
        return self.env is None


class SessionStore:
    """Thread-safe multi-episode store with max-parallel enforcement."""

    def __init__(self, config: CascadeConfig | None = None) -> None:
        self.config = config or get_config()
        self._sessions: dict[str, EpisodeSession] = {}
        self._lock = threading.Lock()

    @property
    def active_count(self) -> int:
        with self._lock:
            return sum(1 for s in self._sessions.values() if not s.closed)

    def create(self, req: CreateEpisodeRequest) -> tuple[str, dict[str, Any], dict[str, Any]]:
        # Reserve a slot before slow provision so concurrent creates cannot oversubscribe.
        with self._lock:
            active = sum(1 for s in self._sessions.values() if not s.closed)
            max_par = max(1, int(self.config.max_parallel_episodes))
            if active >= max_par:
                raise SessionError(
                    f"max_parallel_episodes={max_par} reached ({active} active)",
                    status_code=429,
                    error_code="CAPACITY",
                )
            placeholder_id = f"pending_{id(req)}_{active}"
            self._sessions[placeholder_id] = EpisodeSession(
                episode_id=placeholder_id,
                env=None,  # type: ignore[arg-type]
            )

        env: CascadeEnv | None = None
        try:
            env = CascadeEnv(
                pack=req.pack,
                task_id=req.task_id,
                runtime=req.runtime,
                seed=req.seed,
                max_steps=req.max_steps,
                show_hints=req.show_hints,
                config=self.config,
            )
            obs_s, info = env.reset(seed=req.seed)
            episode_id = str(info.get("episode_id") or "")
            if not episode_id:
                raise SessionError(
                    "reset did not return episode_id",
                    status_code=500,
                    error_code="INTERNAL",
                )

            observation = json.loads(obs_s) if isinstance(obs_s, str) else dict(obs_s)
            # Drop nested obs from wire info to keep payloads lean (observation is top-level)
            wire_info = {k: v for k, v in info.items() if k != "obs"}

            session = EpisodeSession(episode_id=episode_id, env=env)
            with self._lock:
                self._sessions.pop(placeholder_id, None)
                self._sessions[episode_id] = session
            env = None  # ownership transferred to store
            return episode_id, observation, wire_info
        except Exception:
            with self._lock:
                self._sessions.pop(placeholder_id, None)
            if env is not None:
                env.close()
            raise

    def step(
        self, episode_id: str, action: Action | dict[str, Any]
    ) -> tuple[dict[str, Any], float, bool, bool, dict[str, Any]]:
        session = self._get_active(episode_id)
        with session.lock:
            if session.closed or session.env is None:
                raise SessionError("episode already closed", status_code=409, error_code="CLOSED")
            try:
                obs_s, reward, terminated, truncated, info = session.env.step(action)
            except RuntimeError as exc:
                raise SessionError(str(exc), status_code=409, error_code="INACTIVE") from exc
            observation = json.loads(obs_s) if isinstance(obs_s, str) else dict(obs_s)
            wire_info = {k: v for k, v in info.items() if k != "obs"}
            if terminated or truncated:
                # Env already tore down stack on terminal; mark session closed
                session.closed = True
            return observation, float(reward), bool(terminated), bool(truncated), wire_info

    def close(self, episode_id: str) -> bool:
        with self._lock:
            session = self._sessions.get(episode_id)
            if session is None:
                raise SessionError(
                    f"unknown episode_id: {episode_id}",
                    status_code=404,
                    error_code="NOT_FOUND",
                )
        with session.lock:
            if not session.closed:
                if session.env is not None:
                    session.env.close()
                session.closed = True
            return True

    def get_session(self, episode_id: str) -> EpisodeSession | None:
        with self._lock:
            return self._sessions.get(episode_id)

    def close_all(self) -> int:
        with self._lock:
            ids = list(self._sessions.keys())
        n = 0
        for eid in ids:
            try:
                self.close(eid)
                n += 1
            except SessionError:
                pass
        return n

    def _get_active(self, episode_id: str) -> EpisodeSession:
        with self._lock:
            session = self._sessions.get(episode_id)
        if session is None or session.is_placeholder:
            raise SessionError(
                f"unknown episode_id: {episode_id}",
                status_code=404,
                error_code="NOT_FOUND",
            )
        if session.closed:
            raise SessionError("episode already closed", status_code=409, error_code="CLOSED")
        return session

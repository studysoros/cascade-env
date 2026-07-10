"""FastAPI application: create episode / step / close for remote trainers."""

from __future__ import annotations

from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from cascade_env.config import CascadeConfig, get_config
from cascade_env.server.auth import ApiKeyAuth
from cascade_env.server.schemas import (
    ActionRequest,
    CloseResponse,
    CreateEpisodeRequest,
    CreateEpisodeResponse,
    HealthResponse,
    StepResponse,
)
from cascade_env.server.session import SessionError, SessionStore
from cascade_env.version import __version__


def create_app(
    *,
    api_key: str | None = None,
    config: CascadeConfig | None = None,
    store: SessionStore | None = None,
) -> FastAPI:
    """
    Build the rollout API.

    Auth: every ``/v1/*`` route requires ``X-API-Key`` or ``Authorization: Bearer``.
    ``GET /health`` is unauthenticated for load balancers.
    """
    cfg = config or get_config()
    key = (api_key or cfg.server_api_key or "").strip()
    if not key:
        raise ValueError(
            "Server API key required. Pass api_key=... or set CASCADE_SERVER_API_KEY "
            "(cascade serve generates one if omitted)."
        )
    auth = ApiKeyAuth(key)
    sessions = store or SessionStore(cfg)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.store = sessions
        app.state.config = cfg
        app.state.api_key = key
        yield
        sessions.close_all()

    app = FastAPI(
        title="Cascade Rollout API",
        description=(
            "Remote Gymnasium-compatible episode API for Cascade. "
            "Same step semantics as Cascade-v0; authenticate with X-API-Key. "
            "Sandbox only — never attach to real production systems."
        ),
        version=__version__,
        lifespan=lifespan,
    )

    @app.exception_handler(SessionError)
    async def _session_error(_request: Request, exc: SessionError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.message, "error_code": exc.error_code},
        )

    @app.get("/health", response_model=HealthResponse, tags=["ops"])
    def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            version=__version__,
            active_episodes=sessions.active_count,
            max_parallel_episodes=max(1, int(cfg.max_parallel_episodes)),
        )

    @app.get("/v1/health", response_model=HealthResponse, tags=["ops"])
    def health_v1(_: str = Depends(auth)) -> HealthResponse:
        return health()

    @app.post(
        "/v1/episodes",
        response_model=CreateEpisodeResponse,
        status_code=201,
        tags=["episodes"],
        summary="Create (reset) a new episode",
    )
    def create_episode(
        body: CreateEpisodeRequest,
        _: str = Depends(auth),
    ) -> CreateEpisodeResponse:
        try:
            episode_id, observation, info = sessions.create(body)
        except SessionError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"failed to create episode: {exc}") from exc
        return CreateEpisodeResponse(
            episode_id=episode_id,
            observation=observation,
            info=info,
        )

    @app.post(
        "/v1/episodes/{episode_id}/step",
        response_model=StepResponse,
        tags=["episodes"],
        summary="Take one tool-calling step",
    )
    def step_episode(
        episode_id: str,
        body: ActionRequest,
        _: str = Depends(auth),
    ) -> StepResponse:
        observation, reward, terminated, truncated, info = sessions.step(
            episode_id,
            {"tool": body.tool, "args": body.args},
        )
        return StepResponse(
            episode_id=episode_id,
            observation=observation,
            reward=reward,
            terminated=terminated,
            truncated=truncated,
            info=info,
        )

    @app.post(
        "/v1/episodes/{episode_id}/close",
        response_model=CloseResponse,
        tags=["episodes"],
        summary="Close episode and tear down sandbox",
    )
    def close_episode_post(
        episode_id: str,
        _: str = Depends(auth),
    ) -> CloseResponse:
        sessions.close(episode_id)
        return CloseResponse(episode_id=episode_id, closed=True)

    @app.delete(
        "/v1/episodes/{episode_id}",
        response_model=CloseResponse,
        tags=["episodes"],
        summary="Close episode (DELETE alias)",
    )
    def close_episode_delete(
        episode_id: str,
        _: str = Depends(auth),
    ) -> CloseResponse:
        sessions.close(episode_id)
        return CloseResponse(episode_id=episode_id, closed=True)

    return app


def run_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    api_key: str | None = None,
    config: CascadeConfig | None = None,
    log_level: str = "info",
) -> None:
    """Block and serve with uvicorn (used by ``cascade serve``)."""
    import uvicorn

    cfg = config or get_config()
    app = create_app(api_key=api_key, config=cfg)
    uvicorn.run(app, host=host, port=port, log_level=log_level)

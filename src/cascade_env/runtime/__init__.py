from cascade_env.runtime.base import EpisodeHandle, RuntimeBackend
from cascade_env.runtime.local import LocalRuntimeBackend

__all__ = ["EpisodeHandle", "RuntimeBackend", "LocalRuntimeBackend"]


def get_runtime(name: str = "local"):
    if name == "local":
        return LocalRuntimeBackend()
    if name == "compose":
        from cascade_env.runtime.compose import ComposeRuntimeBackend

        return ComposeRuntimeBackend()
    raise ValueError(f"Unknown runtime: {name}")

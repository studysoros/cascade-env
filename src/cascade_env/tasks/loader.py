"""Load task packs and task YAML instances."""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from cascade_env.config import CascadeConfig, get_config
from cascade_env.tasks.schemas import PackManifest, TaskDocument, TaskSpec


class TaskNotFoundError(KeyError):
    pass


class TaskLoader:
    def __init__(self, config: CascadeConfig | None = None) -> None:
        self.config = config or get_config()

    def packs_root(self) -> Path:
        return self.config.packs_dir()

    def list_packs(self) -> list[str]:
        root = self.packs_root()
        if not root.is_dir():
            return []
        return sorted(p.name for p in root.iterdir() if p.is_dir() and (p / "pack.yaml").exists())

    def load_pack(self, pack_id: str) -> PackManifest:
        path = self.packs_root() / pack_id / "pack.yaml"
        if not path.exists():
            raise TaskNotFoundError(f"Pack not found: {pack_id} ({path})")
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return PackManifest.model_validate(data)

    def list_tasks(self, pack_id: str) -> list[str]:
        tasks_dir = self.packs_root() / pack_id / "tasks"
        if not tasks_dir.is_dir():
            return []
        return sorted(p.stem for p in tasks_dir.glob("*.yaml"))

    def load_task(self, pack_id: str, task_id: str) -> TaskSpec:
        # allow bare stem or full id
        tasks_dir = self.packs_root() / pack_id / "tasks"
        candidates = [
            tasks_dir / f"{task_id}.yaml",
            tasks_dir / f"{task_id}.yml",
        ]
        # also search by task.id inside files
        path: Path | None = None
        for c in candidates:
            if c.exists():
                path = c
                break
        if path is None and tasks_dir.is_dir():
            for p in tasks_dir.glob("*.yaml"):
                data = yaml.safe_load(p.read_text(encoding="utf-8"))
                doc = TaskDocument.model_validate(data)
                if doc.task.id == task_id or p.stem == task_id:
                    path = p
                    break
        if path is None:
            raise TaskNotFoundError(f"Task not found: pack={pack_id} task={task_id}")
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return TaskDocument.model_validate(data).task

    def sample_task_id(
        self,
        pack_id: str,
        *,
        seed: int | None = None,
        tier: str | None = None,
        family: str | None = None,
    ) -> str:
        ids = self.list_tasks(pack_id)
        if not ids:
            raise TaskNotFoundError(f"No tasks in pack {pack_id}")
        filtered: list[str] = []
        for stem in ids:
            task = self.load_task(pack_id, stem)
            if tier and task.tier != tier:
                continue
            if family and task.family != family:
                continue
            filtered.append(task.id)
        pool = filtered or [self.load_task(pack_id, s).id for s in ids]
        if seed is None:
            return pool[0]
        idx = int(hashlib.sha256(f"{pack_id}:{seed}".encode()).hexdigest(), 16) % len(pool)
        return pool[idx]


def episode_seed(pack_id: str, task_id: str, user_seed: int, version: str = "0.1.0") -> str:
    raw = f"{pack_id}|{task_id}|{user_seed}|{version}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]

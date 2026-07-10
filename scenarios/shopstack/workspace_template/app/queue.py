"""Order queue abstraction: Redis lists, file-backed, or in-process deque."""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from collections import deque
from pathlib import Path
from urllib.parse import urlparse


class QueueBackend:
    def enqueue(self, payload: str) -> None:
        raise NotImplementedError

    def brpop(self, timeout: float = 1.0) -> str | None:
        raise NotImplementedError

    def dead_letter(self, payload: str) -> None:
        raise NotImplementedError

    def ping(self) -> bool:
        raise NotImplementedError

    def qsize(self) -> int:
        raise NotImplementedError


class MemoryQueue(QueueBackend):
    def __init__(self) -> None:
        self._q: deque[str] = deque()
        self._dead: deque[str] = deque()
        self._cv = threading.Condition()

    def enqueue(self, payload: str) -> None:
        with self._cv:
            self._q.append(payload)
            self._cv.notify()

    def brpop(self, timeout: float = 1.0) -> str | None:
        deadline = time.time() + timeout
        with self._cv:
            while not self._q:
                remaining = deadline - time.time()
                if remaining <= 0:
                    return None
                self._cv.wait(timeout=remaining)
            return self._q.popleft()

    def dead_letter(self, payload: str) -> None:
        with self._cv:
            self._dead.append(payload)

    def ping(self) -> bool:
        return True

    def qsize(self) -> int:
        with self._cv:
            return len(self._q)


class FileQueue(QueueBackend):
    """Cross-process queue using SQLite (WAL). Used by local multi-process runtime."""

    def __init__(self, path: str) -> None:
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init(self) -> None:
        with self._conn() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS queue (id INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS dead (id INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL)"
            )

    def enqueue(self, payload: str) -> None:
        with self._lock, self._conn() as conn:
            conn.execute("INSERT INTO queue(payload) VALUES (?)", (payload,))

    def brpop(self, timeout: float = 1.0) -> str | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock, self._conn() as conn:
                row = conn.execute(
                    "SELECT id, payload FROM queue ORDER BY id ASC LIMIT 1"
                ).fetchone()
                if row:
                    conn.execute("DELETE FROM queue WHERE id = ?", (row[0],))
                    return str(row[1])
            time.sleep(0.05)
        return None

    def dead_letter(self, payload: str) -> None:
        with self._lock, self._conn() as conn:
            conn.execute("INSERT INTO dead(payload) VALUES (?)", (payload,))

    def ping(self) -> bool:
        try:
            with self._conn() as conn:
                conn.execute("SELECT 1")
            return True
        except Exception:
            return False

    def qsize(self) -> int:
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) FROM queue").fetchone()
            return int(row[0]) if row else 0


class RedisQueue(QueueBackend):
    def __init__(self, url: str) -> None:
        import redis

        self._r = redis.Redis.from_url(url, decode_responses=True)
        self.queue_key = "orders:queue"
        self.dead_key = "orders:dead"

    def enqueue(self, payload: str) -> None:
        self._r.lpush(self.queue_key, payload)

    def brpop(self, timeout: float = 1.0) -> str | None:
        item = self._r.brpop(self.queue_key, timeout=max(1, int(timeout)))
        if item is None:
            return None
        return item[1]

    def dead_letter(self, payload: str) -> None:
        self._r.lpush(self.dead_key, payload)

    def ping(self) -> bool:
        return bool(self._r.ping())

    def qsize(self) -> int:
        return int(self._r.llen(self.queue_key))


_QUEUE: QueueBackend | None = None


def get_queue() -> QueueBackend:
    global _QUEUE
    if _QUEUE is not None:
        return _QUEUE
    url = os.environ.get("REDIS_URL", "memory://")
    if url.startswith("memory"):
        _QUEUE = MemoryQueue()
    elif url.startswith("file://"):
        parsed = urlparse(url)
        path = parsed.path
        # Windows file:///C:/...
        if os.name == "nt" and path.startswith("/") and len(path) > 2 and path[2] == ":":
            path = path[1:]
        _QUEUE = FileQueue(path)
    else:
        _QUEUE = RedisQueue(url)
    return _QUEUE


def reset_queue_for_tests() -> None:
    global _QUEUE
    _QUEUE = None

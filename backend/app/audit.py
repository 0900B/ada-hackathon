"""Audit log: every event, field message, AI recommendation and operator decision, with timestamps.

record() is synchronous and never waits: the entry goes into an in-memory buffer (shown on the
Audit page straight away) and a queue. A background writer batches the queue into Postgres
(DATABASE_URL). Without a database, or while it is down, the log keeps working in memory and
the writer retries, so nothing is lost while the app keeps running.
"""
from __future__ import annotations

import asyncio
import itertools
import json
import logging
import os
from collections import deque
from datetime import datetime
from typing import Any

from .models import utcnow

log = logging.getLogger(__name__)

TABLE = os.getenv("AUDIT_TABLE", "audit_log")
MEMORY_LIMIT = 2000
BATCH = 100

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    id BIGSERIAL PRIMARY KEY,
    at TIMESTAMPTZ NOT NULL,
    world TEXT NOT NULL,
    kind TEXT NOT NULL,
    ref TEXT,
    summary TEXT NOT NULL,
    payload JSONB
);
CREATE INDEX IF NOT EXISTS {TABLE}_at_idx ON {TABLE} (at DESC);
"""


def _jsonable(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    return obj


class AuditLog:
    def __init__(self) -> None:
        self.recent: deque[dict[str, Any]] = deque(maxlen=MEMORY_LIMIT)
        self.queue: asyncio.Queue[dict[str, Any]] | None = None
        self.pool: Any = None
        self.status = "memory only (no DATABASE_URL)"
        self.written = 0
        self._seq = itertools.count(1)

    @property
    def database_url(self) -> str | None:
        return os.getenv("DATABASE_URL") or None

    def record(self, world: str, kind: str, summary: str, ref: str | None = None, payload: Any = None) -> None:
        entry = {
            "id": f"m{next(self._seq)}",
            "at": utcnow().isoformat(),
            "world": world,
            "kind": kind,
            "ref": ref,
            "summary": summary[:500],
            "payload": _jsonable(payload),
        }
        self.recent.append(entry)
        if self.queue is not None:
            self.queue.put_nowait(entry)

    # --- background writer ------------------------------------------------------------

    async def run(self) -> None:
        if not self.database_url:
            return  # memory only
        import asyncpg  # only needed with a database

        self.queue = asyncio.Queue()
        for entry in self.recent:  # anything recorded before the writer started
            self.queue.put_nowait(entry)
        backoff = 2.0
        while True:
            try:
                if self.pool is None:
                    self.pool = await asyncpg.create_pool(self.database_url, min_size=1, max_size=3, timeout=10)
                    async with self.pool.acquire() as conn:
                        await conn.execute(SCHEMA)
                    self.status = "connected"
                    backoff = 2.0
                    log.info("audit log: connected to Postgres (table %s)", TABLE)
                batch = [await self.queue.get()]
                while len(batch) < BATCH and not self.queue.empty():
                    batch.append(self.queue.get_nowait())
                try:
                    async with self.pool.acquire() as conn:
                        await conn.executemany(
                            f"INSERT INTO {TABLE} (at, world, kind, ref, summary, payload) "
                            "VALUES ($1, $2, $3, $4, $5, $6::jsonb)",
                            [
                                (
                                    datetime.fromisoformat(e["at"]),
                                    e["world"],
                                    e["kind"],
                                    e["ref"],
                                    e["summary"],
                                    json.dumps(e["payload"], ensure_ascii=False) if e["payload"] is not None else None,
                                )
                                for e in batch
                            ],
                        )
                    self.written += len(batch)
                except BaseException:
                    for e in batch:  # keep them for the next attempt
                        self.queue.put_nowait(e)
                    raise
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - the database must never break the app
                self.status = f"database unavailable ({type(e).__name__}); keeping entries in memory"
                log.warning("audit log: %s", e)
                if self.pool is not None:
                    try:
                        await self.pool.close()
                    except Exception:  # noqa: BLE001
                        pass
                    self.pool = None
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    # --- reading ------------------------------------------------------------------------

    async def query(self, world: str | None = None, kind: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 2000))
        if self.pool is not None and self.status == "connected":
            try:
                conds, args = [], []
                for col, val in (("world", world), ("kind", kind)):
                    if val:
                        args.append(val)
                        conds.append(f"{col} = ${len(args)}")
                where = f"WHERE {' AND '.join(conds)}" if conds else ""
                args.append(limit)
                async with self.pool.acquire() as conn:
                    rows = await conn.fetch(
                        f"SELECT id, at, world, kind, ref, summary, payload FROM {TABLE} {where} "
                        f"ORDER BY at DESC, id DESC LIMIT ${len(args)}",
                        *args,
                    )
                pending = [] if self.queue is None else list(self.queue._queue)  # not yet written
                db_rows = [
                    {
                        "id": str(r["id"]),
                        "at": r["at"].isoformat(),
                        "world": r["world"],
                        "kind": r["kind"],
                        "ref": r["ref"],
                        "summary": r["summary"],
                        "payload": json.loads(r["payload"]) if r["payload"] else None,
                    }
                    for r in rows
                ]
                fresh = [e for e in pending if (not world or e["world"] == world) and (not kind or e["kind"] == kind)]
                return sorted(fresh, key=lambda e: e["at"], reverse=True) + db_rows[: max(0, limit - len(fresh))]
            except Exception as e:  # noqa: BLE001 - fall back to memory
                log.warning("audit query failed, serving memory: %s", e)
        items = [e for e in reversed(self.recent) if (not world or e["world"] == world) and (not kind or e["kind"] == kind)]
        return items[:limit]

    def summary(self) -> dict[str, Any]:
        return {
            "status": self.status if self.database_url else "memory only (no DATABASE_URL)",
            "written_to_db": self.written,
            "in_memory": len(self.recent),
            "pending": self.queue.qsize() if self.queue is not None else 0,
        }


AUDIT = AuditLog()

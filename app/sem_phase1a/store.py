"""Explicit local SQLite only; replaceable unit of work, no application configuration.

Objects live only inside one transaction. CAS also covers audit-only writes, whose
planning version intentionally stays unchanged. Preview consumption and plan writes
commit together; a failure rolls back both. No module-level cache or service lock.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager, closing
from pathlib import Path
from typing import ContextManager, Protocol

from app.sem_phase0.store import RevisionConflict


class Records(Protocol):
    def get(self, key: str) -> dict | None: ...
    def __setitem__(self, key: str, value: dict) -> None: ...


class Transaction(Protocol):
    plans: Records
    previews: Records


class ShadowStore(Protocol):
    def transaction(self) -> ContextManager[Transaction]: ...
    def cleanup_previews(self, now: float) -> int: ...


class _Records:
    def __init__(self, db, table):
        self.db, self.table = db, table  # table is an internal constant
        self.loaded = {}

    def get(self, key):
        if key not in self.loaded:
            row = self.db.execute(f"SELECT revision,payload FROM {self.table} WHERE id=?", (key,)).fetchone()
            if row is None:
                return None
            self.loaded[key] = [row[0], row[1], json.loads(row[1])]
        return self.loaded[key][2]

    def __setitem__(self, key, value):
        if key not in self.loaded:
            self.get(key)
        if key in self.loaded:
            self.loaded[key][2] = value
        else:
            self.loaded[key] = [None, None, value]

    def flush(self):
        for key, (revision, original, value) in self.loaded.items():
            payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            if payload == original:
                continue
            expiry = value["preview"]["expires_at"] if self.table == "shadow_previews" else None
            if revision is None:
                try:
                    self.db.execute(f"INSERT INTO {self.table}(id,revision,payload,expires_at) VALUES (?,1,?,?)",
                                    (key, payload, expiry))
                except sqlite3.IntegrityError:
                    raise RevisionConflict("存储版本冲突") from None
            elif self.db.execute(
                f"UPDATE {self.table} SET revision=revision+1,payload=?,expires_at=? WHERE id=? AND revision=?",
                (payload, expiry, key, revision),
            ).rowcount != 1:
                raise RevisionConflict("存储版本冲突")


class SQLiteShadowStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db, db:
            for table in ("shadow_plans", "shadow_previews"):
                db.execute(f"CREATE TABLE IF NOT EXISTS {table} (id TEXT PRIMARY KEY, revision INTEGER NOT NULL, "
                           "payload TEXT NOT NULL, expires_at REAL)")
            db.execute("CREATE INDEX IF NOT EXISTS shadow_preview_expiry ON shadow_previews(expires_at)")

    def _connect(self):
        return sqlite3.connect(self.path, timeout=20)

    @contextmanager
    def transaction(self):
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            tx = _Transaction(db)
            yield tx
            tx.plans.flush()
            tx.previews.flush()

    def cleanup_previews(self, now):
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            return db.execute("DELETE FROM shadow_previews WHERE expires_at<=?", (now,)).rowcount


class _Transaction:
    def __init__(self, db):
        self.plans = _Records(db, "shadow_plans")
        self.previews = _Records(db, "shadow_previews")

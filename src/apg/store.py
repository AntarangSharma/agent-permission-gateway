"""Application tables. Checkpoints live in a separate SQLite file."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
 id TEXT PRIMARY KEY, case_id TEXT NOT NULL, mode TEXT NOT NULL, variant TEXT NOT NULL,
 permissions TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'running', error TEXT,
 created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
 session_id TEXT NOT NULL REFERENCES sessions(id), id TEXT NOT NULL,
 title TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY(session_id,id)
);
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
 tool TEXT NOT NULL, arguments TEXT NOT NULL, decision TEXT NOT NULL,
 reason TEXT NOT NULL, result TEXT NOT NULL, forbidden INTEGER NOT NULL DEFAULT 0,
 created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS approvals (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
 action TEXT NOT NULL, action_hash TEXT NOT NULL, policy_version TEXT NOT NULL,
 expires REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0,
 UNIQUE(session_id,action_hash)
);
CREATE TABLE IF NOT EXISTS outbox (
 execution_key TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
 recipient_id TEXT NOT NULL, body TEXT NOT NULL, action_hash TEXT NOT NULL,
 created REAL NOT NULL
);
"""


class Store:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "application.sqlite"
        with self.connection() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def rows(self, sql: str, values: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.connection() as db:
            return [dict(row) for row in db.execute(sql, values)]

    def session(self, session_id: str) -> dict[str, Any]:
        rows = self.rows("SELECT * FROM sessions WHERE id=?", (session_id,))
        if not rows:
            raise KeyError("SESSION_NOT_FOUND")
        return rows[0]

    def status(self, session_id: str, status: str, error: str | None = None) -> None:
        with self.connection() as db:
            db.execute(
                "UPDATE sessions SET status=?,error=? WHERE id=?", (status, error, session_id)
            )

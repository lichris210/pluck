"""SQLite-backed schema cache store.

DB file: pluck_cache.db, placed at the project root (next to pluck_adaptive.db).
Path is derived from __file__ at import time — Windows-compatible absolute path.
"""

import os
import sqlite3
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))          # pluck/storage/
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_HERE))     # project root
DEFAULT_DB_PATH = os.path.join(_PROJECT_ROOT, "pluck_cache.db")

_CREATE_SCHEMA_CACHE = """
CREATE TABLE IF NOT EXISTS schema_cache (
    schema_pattern  TEXT PRIMARY KEY,
    schema_json     TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    last_used_at    TEXT NOT NULL,
    use_count       INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'active'
        CHECK(status IN ('active', 'invalidated'))
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SchemaCacheStore:
    """Data-access layer for the schema_cache table.

    Pass *db_path* to override the default location (useful in tests).
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute(_CREATE_SCHEMA_CACHE)
        self._conn.commit()

    # ── public API ────────────────────────────────────────────────────────────

    def get_schema(self, pattern: str) -> str | None:
        """Return schema_json for *pattern* if active, else None."""
        row = self._conn.execute(
            "SELECT schema_json, status FROM schema_cache WHERE schema_pattern = ?",
            (pattern,),
        ).fetchone()
        if row is None or row["status"] != "active":
            return None
        return row["schema_json"]

    def put_schema(self, pattern: str, schema_json: str) -> None:
        """Insert or replace the schema for *pattern*, resetting status to active."""
        now = _now()
        self._conn.execute(
            """
            INSERT INTO schema_cache
                (schema_pattern, schema_json, created_at, last_used_at, use_count, status)
            VALUES (?, ?, ?, ?, 0, 'active')
            ON CONFLICT(schema_pattern) DO UPDATE SET
                schema_json  = excluded.schema_json,
                last_used_at = excluded.last_used_at,
                use_count    = 0,
                status       = 'active'
            """,
            (pattern, schema_json, now, now),
        )
        self._conn.commit()

    def touch_schema(self, pattern: str) -> None:
        """Bump last_used_at and use_count for *pattern*."""
        self._conn.execute(
            """
            UPDATE schema_cache
               SET last_used_at = ?,
                   use_count    = use_count + 1
             WHERE schema_pattern = ?
            """,
            (_now(), pattern),
        )
        self._conn.commit()

    def invalidate_schema(self, pattern: str) -> None:
        """Mark *pattern* as invalidated so get_schema returns None."""
        self._conn.execute(
            "UPDATE schema_cache SET status = 'invalidated' WHERE schema_pattern = ?",
            (pattern,),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

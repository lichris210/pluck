"""SQLite-backed cache store (schema cache, results cache, per-domain TTL).

DB file: pluck_cache.db, placed at the project root (next to pluck_adaptive.db).
Path is derived from __file__ at import time — Windows-compatible absolute path.
"""

import os
import sqlite3
from datetime import datetime, timezone
from urllib.parse import urlparse

from pluck.url_keys import results_key

_HERE = os.path.dirname(os.path.abspath(__file__))          # pluck/storage/
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_HERE))     # project root
DEFAULT_DB_PATH = os.path.join(_PROJECT_ROOT, "pluck_cache.db")

DEFAULT_TTL_SECONDS = 3600  # 1 hour

# ── DDL ───────────────────────────────────────────────────────────────────────

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

_CREATE_RESULTS_CACHE = """
CREATE TABLE IF NOT EXISTS results_cache (
    url_key     TEXT PRIMARY KEY,
    result_json TEXT NOT NULL,
    cached_at   TEXT NOT NULL
);
"""

_CREATE_DOMAIN_TTL = """
CREATE TABLE IF NOT EXISTS domain_ttl (
    domain      TEXT PRIMARY KEY,
    ttl_seconds INTEGER NOT NULL
);
"""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Bare (www-stripped) domains → default TTL seconds.
# Keys must match _domain_for() output so _resolve_ttl() finds them.
# Edit this dict to tune defaults; existing DB rows are never overwritten.
_DEFAULT_DOMAIN_TTLS: dict[str, int] = {
    "linkedin.com": 1800,
    "stockx.com": 1800,
}


class SchemaCacheStore:
    """Data-access layer for schema_cache, results_cache, and domain_ttl tables.

    Pass *db_path* to override the default location (useful in tests).
    Pass *clock* (a zero-arg callable returning a timezone-aware datetime) to
    control time in tests.
    Pass *default_ttl_seconds* to override the global results-cache TTL.
    """

    def __init__(
        self,
        db_path: str = DEFAULT_DB_PATH,
        clock=None,
        default_ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> None:
        self._clock = clock or _utcnow
        self._default_ttl = default_ttl_seconds
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute(_CREATE_SCHEMA_CACHE)
        self._conn.execute(_CREATE_RESULTS_CACHE)
        self._conn.execute(_CREATE_DOMAIN_TTL)
        for _domain, _ttl in _DEFAULT_DOMAIN_TTLS.items():
            self._conn.execute(
                "INSERT INTO domain_ttl (domain, ttl_seconds)"
                " VALUES (?, ?) ON CONFLICT(domain) DO NOTHING",
                (_domain, _ttl),
            )
        self._conn.commit()

    # ── internal helpers ──────────────────────────────────────────────────────

    def _now_str(self) -> str:
        return self._clock().isoformat()

    def _domain_for(self, url: str) -> str:
        host = (urlparse(url).hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        return host

    def _resolve_ttl(self, domain: str) -> int:
        row = self._conn.execute(
            "SELECT ttl_seconds FROM domain_ttl WHERE domain = ?",
            (domain,),
        ).fetchone()
        return int(row["ttl_seconds"]) if row else self._default_ttl

    # ── schema_cache ──────────────────────────────────────────────────────────

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
        now = self._now_str()
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
            (self._now_str(), pattern),
        )
        self._conn.commit()

    def invalidate_schema(self, pattern: str) -> None:
        """Mark *pattern* as invalidated so get_schema returns None."""
        self._conn.execute(
            "UPDATE schema_cache SET status = 'invalidated' WHERE schema_pattern = ?",
            (pattern,),
        )
        self._conn.commit()

    # ── results_cache ─────────────────────────────────────────────────────────

    def get_cached_result(self, url: str) -> str | None:
        """Return cached result_json for *url* if within TTL, else None.

        TTL is resolved from domain_ttl for the URL's domain; falls back to
        *default_ttl_seconds* if no per-domain row exists.
        """
        key = results_key(url)
        row = self._conn.execute(
            "SELECT result_json, cached_at FROM results_cache WHERE url_key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None

        cached_at = datetime.fromisoformat(row["cached_at"])
        now = self._clock()
        # Ensure both sides are timezone-aware for safe subtraction
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        if cached_at.tzinfo is None:
            cached_at = cached_at.replace(tzinfo=timezone.utc)

        ttl = self._resolve_ttl(self._domain_for(url))
        age_seconds = (now - cached_at).total_seconds()
        if age_seconds >= ttl:
            return None

        return row["result_json"]

    def put_cached_result(self, url: str, result_json: str) -> None:
        """Insert or replace the cached result for *url*."""
        key = results_key(url)
        self._conn.execute(
            """
            INSERT INTO results_cache (url_key, result_json, cached_at)
            VALUES (?, ?, ?)
            ON CONFLICT(url_key) DO UPDATE SET
                result_json = excluded.result_json,
                cached_at   = excluded.cached_at
            """,
            (key, result_json, self._now_str()),
        )
        self._conn.commit()

    # ── domain_ttl ────────────────────────────────────────────────────────────

    def set_domain_ttl(self, domain: str, ttl_seconds: int) -> None:
        """Insert or replace the TTL for *domain* (e.g. 'linkedin.com')."""
        self._conn.execute(
            """
            INSERT INTO domain_ttl (domain, ttl_seconds)
            VALUES (?, ?)
            ON CONFLICT(domain) DO UPDATE SET ttl_seconds = excluded.ttl_seconds
            """,
            (domain, ttl_seconds),
        )
        self._conn.commit()

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def close(self) -> None:
        self._conn.close()

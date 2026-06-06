"""SQLite-backed cache store (schema cache, results cache, per-domain TTL).

DB file: pluck_cache.db, placed at the project root (next to pluck_adaptive.db).
Path is derived from __file__ at import time — Windows-compatible absolute path.
"""

import json
import os
import sqlite3
from datetime import datetime, timezone
from urllib.parse import urlparse

from pluck.url_keys import results_key

_HERE = os.path.dirname(os.path.abspath(__file__))          # pluck/storage/
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_HERE))     # project root
DEFAULT_DB_PATH = os.path.join(_PROJECT_ROOT, "pluck_cache.db")

DEFAULT_TTL_SECONDS = 3600  # 1 hour
PLAN_CACHE_TTL_SECONDS = 7 * 24 * 3600  # 7 days
DISCOVERED_ACTOR_TTL_SECONDS = 30 * 24 * 3600  # 30 days

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

_CREATE_PLAN_CACHE = """
CREATE TABLE IF NOT EXISTS plan_cache (
    cache_key    TEXT PRIMARY KEY,
    plan_json    TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    last_used_at TEXT NOT NULL,
    use_count    INTEGER NOT NULL DEFAULT 0
);
"""

_CREATE_DISCOVERED_ACTORS = """
CREATE TABLE IF NOT EXISTS discovered_actors (
    domain_pattern  TEXT NOT NULL,
    actor_id        TEXT NOT NULL,
    entry_json      TEXT NOT NULL,
    source          TEXT NOT NULL DEFAULT 'discovered'
        CHECK(source IN ('discovered', 'hardcoded')),
    successful_runs INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    last_used_at    TEXT NOT NULL,
    use_count       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (domain_pattern, actor_id)
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
        self._conn.execute(_CREATE_PLAN_CACHE)
        self._conn.execute(_CREATE_DISCOVERED_ACTORS)
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

    # ── plan_cache ────────────────────────────────────────────────────────────

    def get_plan(self, cache_key: str) -> str | None:
        """Return cached plan_json for *cache_key* if within the 7-day TTL, else None.

        On a fresh hit, bumps last_used_at and use_count (mirrors touch_schema).
        The TTL is the module-level PLAN_CACHE_TTL_SECONDS — not per-domain.
        """
        row = self._conn.execute(
            "SELECT plan_json, created_at FROM plan_cache WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()
        if row is None:
            return None

        created_at = datetime.fromisoformat(row["created_at"])
        now = self._clock()
        # Ensure both sides are timezone-aware for safe subtraction
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        age_seconds = (now - created_at).total_seconds()
        if age_seconds >= PLAN_CACHE_TTL_SECONDS:
            return None

        self._conn.execute(
            """
            UPDATE plan_cache
               SET last_used_at = ?,
                   use_count    = use_count + 1
             WHERE cache_key = ?
            """,
            (self._now_str(), cache_key),
        )
        self._conn.commit()
        return row["plan_json"]

    def put_plan(self, cache_key: str, plan_json: str) -> None:
        """Insert or replace the cached plan for *cache_key*, resetting use_count."""
        now = self._now_str()
        self._conn.execute(
            """
            INSERT INTO plan_cache
                (cache_key, plan_json, created_at, last_used_at, use_count)
            VALUES (?, ?, ?, ?, 0)
            ON CONFLICT(cache_key) DO UPDATE SET
                plan_json    = excluded.plan_json,
                created_at   = excluded.created_at,
                last_used_at = excluded.last_used_at,
                use_count    = 0
            """,
            (cache_key, plan_json, now, now),
        )
        self._conn.commit()

    def clear_plan_cache(self) -> int:
        """Delete all cached plans; return the number of rows removed."""
        cur = self._conn.execute("DELETE FROM plan_cache")
        self._conn.commit()
        return cur.rowcount

    # ── discovered_actors (tier 2) ────────────────────────────────────────────

    def get_discovered(self, domain_pattern: str) -> list[dict]:
        """Return non-expired discovered entries for *domain_pattern* as dicts.

        Bumps last_used_at/use_count on each returned row. Each dict is the stored
        registry entry with ``successful_runs`` folded in (for confidence scoring).
        """
        rows = self._conn.execute(
            """
            SELECT actor_id, entry_json, successful_runs, created_at
              FROM discovered_actors
             WHERE domain_pattern = ?
            """,
            (domain_pattern,),
        ).fetchall()

        now = self._clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        out: list[dict] = []
        fresh_ids: list[str] = []
        for row in rows:
            created_at = datetime.fromisoformat(row["created_at"])
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            if (now - created_at).total_seconds() >= DISCOVERED_ACTOR_TTL_SECONDS:
                continue
            entry = json.loads(row["entry_json"])
            entry["successful_runs"] = row["successful_runs"]
            out.append(entry)
            fresh_ids.append(row["actor_id"])

        if fresh_ids:
            now_str = self._now_str()
            self._conn.executemany(
                """
                UPDATE discovered_actors
                   SET last_used_at = ?, use_count = use_count + 1
                 WHERE domain_pattern = ? AND actor_id = ?
                """,
                [(now_str, domain_pattern, aid) for aid in fresh_ids],
            )
            self._conn.commit()
        return out

    def put_discovered(self, domain_pattern: str, entry: dict) -> None:
        """Upsert a discovered entry by (domain_pattern, actor_id).

        On conflict, refreshes entry_json/created_at but preserves successful_runs
        and use_count (the counter survives re-discovery).
        """
        now = self._now_str()
        actor_id = entry.get("actor_id")
        self._conn.execute(
            """
            INSERT INTO discovered_actors
                (domain_pattern, actor_id, entry_json, source,
                 successful_runs, created_at, last_used_at, use_count)
            VALUES (?, ?, ?, 'discovered', 0, ?, ?, 0)
            ON CONFLICT(domain_pattern, actor_id) DO UPDATE SET
                entry_json = excluded.entry_json,
                created_at = excluded.created_at,
                last_used_at = excluded.last_used_at
            """,
            (domain_pattern, actor_id, json.dumps(entry), now, now),
        )
        self._conn.commit()

    def increment_successful_runs(self, domain_pattern: str, actor_id: str) -> None:
        """Bump the successful_runs counter for a discovered entry."""
        self._conn.execute(
            """
            UPDATE discovered_actors
               SET successful_runs = successful_runs + 1
             WHERE domain_pattern = ? AND actor_id = ?
            """,
            (domain_pattern, actor_id),
        )
        self._conn.commit()

    def get_discovered_for_review(self, min_runs: int = 10) -> list[dict]:
        """Return all discovered rows with successful_runs >= *min_runs*.

        Each dict carries domain_pattern, actor_id, successful_runs, source — the
        manual-promotion report (Decision 3); no auto-promotion happens here.
        """
        rows = self._conn.execute(
            """
            SELECT domain_pattern, actor_id, successful_runs, source
              FROM discovered_actors
             WHERE successful_runs >= ?
             ORDER BY successful_runs DESC
            """,
            (min_runs,),
        ).fetchall()
        return [dict(r) for r in rows]

    def clear_discovered(self) -> int:
        """Delete all discovered entries; return the number of rows removed."""
        cur = self._conn.execute("DELETE FROM discovered_actors")
        self._conn.commit()
        return cur.rowcount

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

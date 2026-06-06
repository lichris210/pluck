"""Tests for the plan_cache table in SchemaCacheStore (Phase 2, Prompt 1)."""

import pytest
from datetime import datetime, timedelta, timezone

from pluck.storage.cache_store import SchemaCacheStore, PLAN_CACHE_TTL_SECONDS


# ── fixture ───────────────────────────────────────────────────────────────────

@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test_plan_cache.db")


def _store(db_path, t):
    """Create a store whose clock is frozen at datetime *t*."""
    return SchemaCacheStore(db_path=db_path, clock=lambda: t)


T0 = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

KEY = "instagram.com|abc123def4567890"
PLAN = '{"actor_id": "apify/instagram-post-scraper", "actor_input": {"resultsLimit": 50}}'


# ── put / get round-trip ──────────────────────────────────────────────────────

def test_put_then_get_roundtrip(db_path):
    s = _store(db_path, T0)
    s.put_plan(KEY, PLAN)
    s.close()

    t30 = T0 + timedelta(seconds=30)
    s2 = _store(db_path, t30)
    result = s2.get_plan(KEY)
    s2.close()

    assert result == PLAN


def test_get_missing_returns_none(db_path):
    s = _store(db_path, T0)
    result = s.get_plan("never-written|0000")
    s.close()
    assert result is None


# ── TTL behaviour ─────────────────────────────────────────────────────────────

def test_expired_plan_returns_none(db_path):
    s = _store(db_path, T0)
    s.put_plan(KEY, PLAN)
    s.close()

    t_expired = T0 + timedelta(seconds=PLAN_CACHE_TTL_SECONDS + 1)
    s2 = _store(db_path, t_expired)
    result = s2.get_plan(KEY)
    s2.close()

    assert result is None


def test_ttl_exact_boundary_is_miss(db_path):
    # age == ttl (not strictly less than) → expired
    s = _store(db_path, T0)
    s.put_plan(KEY, PLAN)
    s.close()

    t_exact = T0 + timedelta(seconds=PLAN_CACHE_TTL_SECONDS)
    s2 = _store(db_path, t_exact)
    result = s2.get_plan(KEY)
    s2.close()

    assert result is None


# ── use_count bumping ─────────────────────────────────────────────────────────

def test_get_bumps_use_count(db_path):
    s = _store(db_path, T0)
    s.put_plan(KEY, PLAN)

    t10 = T0 + timedelta(seconds=10)
    s2 = _store(db_path, t10)
    s2.get_plan(KEY)
    s2.get_plan(KEY)

    row = s2._conn.execute(
        "SELECT use_count FROM plan_cache WHERE cache_key = ?", (KEY,)
    ).fetchone()
    s2.close()

    assert row["use_count"] == 2


# ── put overwrites and resets ─────────────────────────────────────────────────

def test_put_overwrites_and_resets_use_count(db_path):
    s = _store(db_path, T0)
    s.put_plan(KEY, PLAN)
    s.get_plan(KEY)
    s.get_plan(KEY)

    new_plan = '{"actor_id": "apify/instagram-profile-scraper"}'
    s.put_plan(KEY, new_plan)

    row = s._conn.execute(
        "SELECT use_count FROM plan_cache WHERE cache_key = ?", (KEY,)
    ).fetchone()
    result = s.get_plan(KEY)
    s.close()

    assert row["use_count"] == 0
    assert result == new_plan


# ── clear ─────────────────────────────────────────────────────────────────────

def test_clear_plan_cache_returns_deleted_count(db_path):
    s = _store(db_path, T0)
    s.put_plan("k1|aaaa", PLAN)
    s.put_plan("k2|bbbb", PLAN)

    deleted = s.clear_plan_cache()

    assert deleted == 2
    assert s.get_plan("k1|aaaa") is None
    assert s.get_plan("k2|bbbb") is None
    s.close()

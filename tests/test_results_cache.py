"""Tests for results_cache and domain_ttl tables in SchemaCacheStore."""

import pytest
from datetime import datetime, timedelta, timezone

from pluck.storage.cache_store import SchemaCacheStore


# ── fixture ───────────────────────────────────────────────────────────────────

@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test_results.db")


def _store(db_path, t, default_ttl=3600):
    """Create a store whose clock is frozen at datetime *t*."""
    return SchemaCacheStore(db_path=db_path, clock=lambda: t, default_ttl_seconds=default_ttl)


T0 = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


# ── results_cache: TTL behaviour ──────────────────────────────────────────────

def test_fresh_write_returned_within_ttl(db_path):
    s = _store(db_path, T0, default_ttl=3600)
    s.put_cached_result("https://example.com/page", '{"x": 1}')
    s.close()

    t30 = T0 + timedelta(seconds=30)
    s2 = _store(db_path, t30, default_ttl=3600)
    result = s2.get_cached_result("https://example.com/page")
    s2.close()

    assert result == '{"x": 1}'


def test_expired_entry_returns_none(db_path):
    s = _store(db_path, T0, default_ttl=3600)
    s.put_cached_result("https://example.com/page", '{"x": 1}')
    s.close()

    t_expired = T0 + timedelta(seconds=3601)
    s2 = _store(db_path, t_expired, default_ttl=3600)
    result = s2.get_cached_result("https://example.com/page")
    s2.close()

    assert result is None


def test_stale_row_at_exact_ttl_boundary_is_miss(db_path):
    # age == ttl (not strictly less than) → expired
    s = _store(db_path, T0, default_ttl=60)
    s.put_cached_result("https://example.com/page", '{"x": 1}')
    s.close()

    t_exact = T0 + timedelta(seconds=60)
    s2 = _store(db_path, t_exact, default_ttl=60)
    result = s2.get_cached_result("https://example.com/page")
    s2.close()

    assert result is None


def test_missing_url_returns_none(db_path):
    s = _store(db_path, T0)
    result = s.get_cached_result("https://example.com/never-written")
    s.close()
    assert result is None


# ── domain_ttl: override and fallback ────────────────────────────────────────

def test_domain_ttl_overrides_global_default(db_path):
    # Global TTL = 3600, domain TTL = 60
    s = _store(db_path, T0, default_ttl=3600)
    s.set_domain_ttl("example.com", 60)
    s.put_cached_result("https://example.com/page", '{"x": 1}')
    s.close()

    # 90s later — within global TTL but past domain TTL
    t90 = T0 + timedelta(seconds=90)
    s2 = _store(db_path, t90, default_ttl=3600)
    s2.set_domain_ttl("example.com", 60)  # domain TTL persisted in DB already, but re-set for clarity
    result = s2.get_cached_result("https://example.com/page")
    s2.close()

    assert result is None


def test_domain_ttl_allows_read_within_short_ttl(db_path):
    s = _store(db_path, T0, default_ttl=3600)
    s.set_domain_ttl("example.com", 120)
    s.put_cached_result("https://example.com/page", '{"x": 1}')
    s.close()

    t30 = T0 + timedelta(seconds=30)
    s2 = _store(db_path, t30, default_ttl=3600)
    result = s2.get_cached_result("https://example.com/page")
    s2.close()

    assert result == '{"x": 1}'


def test_unknown_domain_uses_global_default(db_path):
    # No domain_ttl row for example.com → falls back to default_ttl=3600
    s = _store(db_path, T0, default_ttl=3600)
    s.put_cached_result("https://example.com/page", '{"x": 1}')
    s.close()

    t1800 = T0 + timedelta(seconds=1800)
    s2 = _store(db_path, t1800, default_ttl=3600)
    result = s2.get_cached_result("https://example.com/page")
    s2.close()

    assert result == '{"x": 1}'


def test_www_subdomain_maps_to_same_domain_ttl(db_path):
    # set_domain_ttl("example.com", 60); www.example.com should resolve the same TTL
    s = _store(db_path, T0, default_ttl=3600)
    s.set_domain_ttl("example.com", 60)
    s.put_cached_result("https://www.example.com/page", '{"x": 1}')
    s.close()

    t90 = T0 + timedelta(seconds=90)
    s2 = _store(db_path, t90, default_ttl=3600)
    result = s2.get_cached_result("https://www.example.com/page")
    s2.close()

    assert result is None  # expired via domain TTL of 60s


# ── put overwrites ────────────────────────────────────────────────────────────

def test_put_overwrites_old_entry(db_path):
    s = _store(db_path, T0)
    s.put_cached_result("https://example.com/page", '{"v": 1}')

    t10 = T0 + timedelta(seconds=10)
    s2 = _store(db_path, t10)
    s2.put_cached_result("https://example.com/page", '{"v": 2}')

    t20 = T0 + timedelta(seconds=20)
    s3 = _store(db_path, t20)
    result = s3.get_cached_result("https://example.com/page")
    s3.close()

    assert result == '{"v": 2}'


# ── schema_cache unaffected ───────────────────────────────────────────────────

def test_schema_cache_table_still_works_after_migration(db_path):
    """Adding new tables must not disturb schema_cache reads/writes."""
    s = _store(db_path, T0)
    s.put_schema("example.com/jobs/*", '{"fields": []}')
    assert s.get_schema("example.com/jobs/*") == '{"fields": []}'
    s.invalidate_schema("example.com/jobs/*")
    assert s.get_schema("example.com/jobs/*") is None
    s.close()

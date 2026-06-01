"""Tests for the _DEFAULT_DOMAIN_TTLS seed in SchemaCacheStore.__init__."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from pluck.storage.cache_store import (
    DEFAULT_TTL_SECONDS,
    SchemaCacheStore,
    _DEFAULT_DOMAIN_TTLS,
)

T0 = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "seed_test.db")


# ── 1. Fresh store has seeded domains at the correct TTL values ───────────────

def test_fresh_store_seeds_all_default_domains(db_path):
    store = SchemaCacheStore(db_path=db_path)
    for domain, expected_ttl in _DEFAULT_DOMAIN_TTLS.items():
        row = store._conn.execute(
            "SELECT ttl_seconds FROM domain_ttl WHERE domain = ?",
            (domain,),
        ).fetchone()
        assert row is not None, f"seed row missing for {domain!r}"
        assert int(row["ttl_seconds"]) == expected_ttl
    store.close()


def test_fresh_store_linkedin_ttl_is_1800(db_path):
    store = SchemaCacheStore(db_path=db_path)
    row = store._conn.execute(
        "SELECT ttl_seconds FROM domain_ttl WHERE domain = 'linkedin.com'"
    ).fetchone()
    assert row is not None
    assert int(row["ttl_seconds"]) == 1800
    store.close()


def test_fresh_store_stockx_ttl_is_1800(db_path):
    store = SchemaCacheStore(db_path=db_path)
    row = store._conn.execute(
        "SELECT ttl_seconds FROM domain_ttl WHERE domain = 'stockx.com'"
    ).fetchone()
    assert row is not None
    assert int(row["ttl_seconds"]) == 1800
    store.close()


# ── 2. _resolve_ttl uses seeded value / global default correctly ──────────────

def test_resolve_ttl_returns_seeded_value_for_seeded_domain(db_path):
    store = SchemaCacheStore(db_path=db_path)
    assert store._resolve_ttl("linkedin.com") == 1800
    assert store._resolve_ttl("stockx.com") == 1800
    store.close()


def test_resolve_ttl_returns_global_default_for_unseeded_domain(db_path):
    store = SchemaCacheStore(db_path=db_path)
    assert store._resolve_ttl("example.com") == DEFAULT_TTL_SECONDS
    store.close()


# ── 3. Pre-existing row survives re-init — seed does NOT overwrite ────────────

def test_reinit_does_not_overwrite_existing_row(db_path):
    # First store: override linkedin TTL to a custom value
    s1 = SchemaCacheStore(db_path=db_path)
    s1.set_domain_ttl("linkedin.com", 300)
    s1.close()

    # Second store on the same DB: __init__ runs again with the seed
    s2 = SchemaCacheStore(db_path=db_path)
    assert s2._resolve_ttl("linkedin.com") == 300  # custom value preserved
    s2.close()


def test_reinit_does_not_overwrite_stockx_either(db_path):
    s1 = SchemaCacheStore(db_path=db_path)
    s1.set_domain_ttl("stockx.com", 60)
    s1.close()

    s2 = SchemaCacheStore(db_path=db_path)
    assert s2._resolve_ttl("stockx.com") == 60
    s2.close()


# ── 4. Seeded TTL governs cache expiry (clock-injected integration test) ──────

def test_seeded_ttl_expires_result_before_global_default(db_path):
    linkedin_ttl = _DEFAULT_DOMAIN_TTLS["linkedin.com"]  # 1800

    # Sanity: seeded TTL must be less than global default for this test to be meaningful
    assert linkedin_ttl < DEFAULT_TTL_SECONDS

    # Write a cached result at T0
    store_write = SchemaCacheStore(db_path=db_path, clock=lambda: T0)
    store_write.put_cached_result(
        "https://linkedin.com/jobs/123",
        json.dumps({"items": [{"title": "Engineer"}]}),
    )
    store_write.close()

    # Read at T0 + linkedin_ttl + 1  → past seeded TTL, but still under global default
    t_past_seeded = T0 + timedelta(seconds=linkedin_ttl + 1)
    store_read = SchemaCacheStore(db_path=db_path, clock=lambda: t_past_seeded)
    result = store_read.get_cached_result("https://linkedin.com/jobs/123")
    store_read.close()

    assert result is None  # expired by the seeded 1800 s TTL


def test_seeded_ttl_serves_result_within_window(db_path):
    linkedin_ttl = _DEFAULT_DOMAIN_TTLS["linkedin.com"]  # 1800

    store_write = SchemaCacheStore(db_path=db_path, clock=lambda: T0)
    store_write.put_cached_result(
        "https://linkedin.com/jobs/456",
        json.dumps({"items": [{"title": "Manager"}]}),
    )
    store_write.close()

    # Read at T0 + half TTL → should still be valid
    t_within = T0 + timedelta(seconds=linkedin_ttl // 2)
    store_read = SchemaCacheStore(db_path=db_path, clock=lambda: t_within)
    result = store_read.get_cached_result("https://linkedin.com/jobs/456")
    store_read.close()

    assert result is not None


def test_www_linkedin_url_uses_seeded_ttl(db_path):
    """www. is stripped by _domain_for, so www.linkedin.com resolves the seed."""
    linkedin_ttl = _DEFAULT_DOMAIN_TTLS["linkedin.com"]

    store_write = SchemaCacheStore(db_path=db_path, clock=lambda: T0)
    store_write.put_cached_result(
        "https://www.linkedin.com/jobs/789",
        json.dumps({"items": []}),
    )
    store_write.close()

    t_past_seeded = T0 + timedelta(seconds=linkedin_ttl + 1)
    store_read = SchemaCacheStore(db_path=db_path, clock=lambda: t_past_seeded)
    result = store_read.get_cached_result("https://www.linkedin.com/jobs/789")
    store_read.close()

    assert result is None  # expired via seeded TTL of bare linkedin.com

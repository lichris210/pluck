"""Tests for the discovered_actors (tier 2) table in SchemaCacheStore (Phase 3, Prompt 4)."""

from datetime import datetime, timedelta, timezone

import pytest

from pluck.storage.cache_store import SchemaCacheStore, DISCOVERED_ACTOR_TTL_SECONDS


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test_discovered.db")


def _store(db_path, t):
    return SchemaCacheStore(db_path=db_path, clock=lambda: t)


T0 = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
HOST = "mountainproject.com"


def _entry(actor_id="x/y"):
    return {
        "domain_patterns": [HOST],
        "actor_id": actor_id,
        "intent_description": "scrapes routes",
        "input_template": {"url": "{url}"},
        "default_columns": ["name"],
        "all_columns": ["name", "grade"],
        "is_default": True,
        "source": "discovered",
        "reasoning": "best match",
    }


def test_put_then_get_roundtrip(db_path):
    s = _store(db_path, T0)
    s.put_discovered(HOST, _entry())
    got = s.get_discovered(HOST)
    s.close()
    assert len(got) == 1
    assert got[0]["actor_id"] == "x/y"
    assert got[0]["source"] == "discovered"
    assert got[0]["successful_runs"] == 0


def test_expired_discovered_returns_none(db_path):
    s = _store(db_path, T0)
    s.put_discovered(HOST, _entry())
    s.close()

    t_expired = T0 + timedelta(seconds=DISCOVERED_ACTOR_TTL_SECONDS + 1)
    s2 = _store(db_path, t_expired)
    assert s2.get_discovered(HOST) == []
    s2.close()


def test_get_bumps_use_count(db_path):
    s = _store(db_path, T0)
    s.put_discovered(HOST, _entry())
    s.get_discovered(HOST)
    s.get_discovered(HOST)
    row = s._conn.execute(
        "SELECT use_count FROM discovered_actors WHERE domain_pattern = ? AND actor_id = ?",
        (HOST, "x/y"),
    ).fetchone()
    s.close()
    assert row["use_count"] == 2


def test_increment_successful_runs(db_path):
    s = _store(db_path, T0)
    s.put_discovered(HOST, _entry())
    s.increment_successful_runs(HOST, "x/y")
    got = s.get_discovered(HOST)
    s.close()
    assert got[0]["successful_runs"] == 1


def test_put_preserves_successful_runs_on_conflict(db_path):
    s = _store(db_path, T0)
    s.put_discovered(HOST, _entry())
    s.increment_successful_runs(HOST, "x/y")
    # Re-discover the same actor — counter must survive.
    s.put_discovered(HOST, _entry())
    got = s.get_discovered(HOST)
    s.close()
    assert got[0]["successful_runs"] == 1


def test_get_for_review_filters_by_min_runs(db_path):
    s = _store(db_path, T0)
    s.put_discovered(HOST, _entry("popular/actor"))
    s.put_discovered(HOST, _entry("rare/actor"))
    for _ in range(10):
        s.increment_successful_runs(HOST, "popular/actor")
    s.increment_successful_runs(HOST, "rare/actor")  # only 1

    review = s.get_discovered_for_review(min_runs=10)
    s.close()
    assert len(review) == 1
    assert review[0]["actor_id"] == "popular/actor"
    assert review[0]["successful_runs"] == 10


def test_clear_discovered_returns_count(db_path):
    s = _store(db_path, T0)
    s.put_discovered(HOST, _entry("a/1"))
    s.put_discovered(HOST, _entry("b/2"))
    assert s.clear_discovered() == 2
    assert s.get_discovered(HOST) == []
    s.close()

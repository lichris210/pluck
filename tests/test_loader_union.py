"""Tests for the two-tier (JSON + SQLite) loader union (Phase 3, Prompt 4)."""

import pytest

from pluck.registry.discovery_planner import DISCOVERY_LOGIC_VERSION
from pluck.registry.loader import candidates_for_url, get_candidates
from pluck.registry.planner import _DYNAMIC_LIMIT_KEYS
from pluck.storage.cache_store import SchemaCacheStore


@pytest.fixture
def store(tmp_path):
    s = SchemaCacheStore(db_path=str(tmp_path / "loader_union.db"))
    yield s
    s.close()


def _discovered_entry(host, actor_id, *, logic_version=DISCOVERY_LOGIC_VERSION, limit_field=None):
    return {
        "domain_patterns": [host],
        "actor_id": actor_id,
        "intent_description": "discovered",
        "input_template": {"url": "{url}"},
        "default_columns": ["a"],
        "all_columns": ["a"],
        "is_default": True,
        "source": "discovered",
        "limit_field": limit_field,
        "logic_version": logic_version,
    }


def test_tier2_entry_appears_in_candidates(store):
    host = "mountainproject.com"
    store.put_discovered(host, _discovered_entry(host, "climber/mp"))

    cands = candidates_for_url(f"https://{host}/route/123", store=store)

    assert len(cands) == 1
    assert cands[0]["actor_id"] == "climber/mp"
    assert cands[0]["source"] == "discovered"


def test_tier1_wins_on_actor_id_conflict(store):
    store.put_discovered(
        "instagram.com", _discovered_entry("instagram.com", "apify/instagram-post-scraper")
    )

    cands = get_candidates("instagram.com", store=store)

    assert len(cands) == 2
    conflict = next(c for c in cands if c["actor_id"] == "apify/instagram-post-scraper")
    assert conflict.get("source") != "discovered"


def test_tier1_only_host_unchanged(store):
    cands = get_candidates("instagram.com", store=store)
    assert len(cands) == 2
    assert {c["actor_id"] for c in cands} == {
        "apify/instagram-post-scraper",
        "apify/instagram-profile-scraper",
    }


# ── logic_version gating ──────────────────────────────────────────────────────

def test_old_logic_version_row_is_ignored(store):
    host = "oldcache.com"
    store.put_discovered(host, _discovered_entry(host, "old/actor", logic_version=0))

    # logic_version=0 < DISCOVERY_LOGIC_VERSION → invisible to the loader.
    assert get_candidates(host, store=store) == []


def test_current_logic_version_row_is_returned(store):
    host = "newcache.com"
    store.put_discovered(
        host, _discovered_entry(host, "new/actor", logic_version=DISCOVERY_LOGIC_VERSION)
    )

    cands = get_candidates(host, store=store)
    assert [c["actor_id"] for c in cands] == ["new/actor"]


def test_limit_field_registered_on_load(store):
    host = "limitcache.com"
    store.put_discovered(
        host, _discovered_entry(host, "lim/actor", limit_field="resultsPerProfile")
    )

    get_candidates(host, store=store)

    assert "resultsPerProfile" in _DYNAMIC_LIMIT_KEYS

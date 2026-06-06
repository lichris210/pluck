"""Tests for the two-tier (JSON + SQLite) loader union (Phase 3, Prompt 4)."""

import pytest

from pluck.registry.loader import candidates_for_url, get_candidates
from pluck.storage.cache_store import SchemaCacheStore


@pytest.fixture
def store(tmp_path):
    s = SchemaCacheStore(db_path=str(tmp_path / "loader_union.db"))
    yield s
    s.close()


def _discovered_entry(host, actor_id):
    return {
        "domain_patterns": [host],
        "actor_id": actor_id,
        "intent_description": "discovered",
        "input_template": {"url": "{url}"},
        "default_columns": ["a"],
        "all_columns": ["a"],
        "is_default": True,
        "source": "discovered",
    }


def test_tier2_entry_appears_in_candidates(store):
    host = "mountainproject.com"
    store.put_discovered(host, _discovered_entry(host, "climber/mp"))

    cands = candidates_for_url(f"https://{host}/route/123", store=store)

    assert len(cands) == 1
    assert cands[0]["actor_id"] == "climber/mp"
    assert cands[0]["source"] == "discovered"


def test_tier1_wins_on_actor_id_conflict(store):
    # Plant a discovered row reusing a hardcoded Instagram actor_id.
    store.put_discovered(
        "instagram.com", _discovered_entry("instagram.com", "apify/instagram-post-scraper")
    )

    cands = get_candidates("instagram.com", store=store)

    # Still exactly the 2 hardcoded Instagram entries; no duplicate actor_id.
    assert len(cands) == 2
    conflict = next(c for c in cands if c["actor_id"] == "apify/instagram-post-scraper")
    # The surviving entry is tier 1 (no discovered marker).
    assert conflict.get("source") != "discovered"


def test_tier1_only_host_unchanged(store):
    cands = get_candidates("instagram.com", store=store)
    assert len(cands) == 2
    assert {c["actor_id"] for c in cands} == {
        "apify/instagram-post-scraper",
        "apify/instagram-profile-scraper",
    }

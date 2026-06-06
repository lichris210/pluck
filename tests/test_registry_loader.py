"""Tests for the host-based registry loader."""

import pytest

from pluck.registry.loader import (
    candidates_for_url,
    find_entry,
    get_candidates,
    load_registry,
)
from pluck.storage.cache_store import SchemaCacheStore


@pytest.fixture
def empty_store(tmp_path):
    """A fresh tier-2 store so candidates_for_url returns only hardcoded entries."""
    s = SchemaCacheStore(db_path=str(tmp_path / "reg_test.db"))
    yield s
    s.close()


def test_instagram_host_returns_both_entries():
    candidates = candidates_for_url("https://instagram.com/someuser/")
    actor_ids = {entry["actor_id"] for entry in candidates}
    assert actor_ids == {
        "apify/instagram-post-scraper",
        "apify/instagram-profile-scraper",
    }


def test_www_prefix_stripped():
    with_www = candidates_for_url("https://www.instagram.com/someuser/")
    without_www = candidates_for_url("https://instagram.com/someuser/")
    assert with_www == without_www


def test_unknown_domain_returns_empty():
    assert candidates_for_url("https://nytimes.com/section/world") == []


def test_get_candidates_is_host_based():
    candidates = get_candidates("linkedin.com")
    actor_ids = {entry["actor_id"] for entry in candidates}
    assert actor_ids == {"curious_coder/linkedin-jobs-scraper"}


def test_find_entry_by_actor_id():
    candidates = candidates_for_url("https://instagram.com/someuser/")
    found = find_entry("apify/instagram-profile-scraper", candidates)
    assert found is not None
    assert found["actor_id"] == "apify/instagram-profile-scraper"
    assert find_entry("nonexistent/actor", candidates) is None


# ── new registry entries: YouTube, Google Maps, Reddit ────────────────────────

@pytest.mark.parametrize("url, actor_id", [
    ("https://www.youtube.com/@MrBeast", "streamers/youtube-scraper"),
    ("https://www.reddit.com/r/python", "trudax/reddit-scraper-lite"),
])
def test_new_entry_routes_correctly(url, actor_id, empty_store):
    candidates = candidates_for_url(url, store=empty_store)
    assert [e["actor_id"] for e in candidates] == [actor_id]


@pytest.mark.parametrize("actor_id, limit_field", [
    ("streamers/youtube-scraper", "maxResults"),
    ("trudax/reddit-scraper-lite", "maxItems"),
])
def test_new_entry_loads_with_valid_template(actor_id, limit_field):
    entry = next(e for e in load_registry() if e["actor_id"] == actor_id)
    template = entry["input_template"]
    assert entry["limit_field"] == limit_field
    # startUrls uses the object-array form, and the limit field carries {max_items}.
    assert template["startUrls"] == [{"url": "{url}"}]
    assert template[limit_field] == "{max_items}"
    assert entry["default_columns"] and entry["all_columns"]
    # every default column is a real captured column
    assert set(entry["default_columns"]) <= set(entry["all_columns"])


def test_reddit_entry_fills_required_proxy():
    entry = next(e for e in load_registry() if e["actor_id"] == "trudax/reddit-scraper-lite")
    assert entry["input_template"]["proxy"] == {"useApifyProxy": True}

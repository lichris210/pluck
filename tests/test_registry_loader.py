"""Tests for the host-based registry loader."""

from pluck.registry.loader import (
    candidates_for_url,
    find_entry,
    get_candidates,
)


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

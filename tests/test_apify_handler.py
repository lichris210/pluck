"""Tests for fetchers/apify_handler.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pluck.fetchers.apify_handler import (
    _GENERIC_ACTOR,
    fetch_via_apify,
    fetch_via_apify_plan,
    resolve_actor,
)


# ── resolve_actor ─────────────────────────────────────────────────────────────


def test_resolve_actor_linkedin_jobs():
    assert resolve_actor("https://www.linkedin.com/jobs/search/?keywords=python") == "curious_coder/linkedin-jobs-scraper"


def test_resolve_actor_linkedin_profile():
    assert resolve_actor("https://www.linkedin.com/in/john-doe/") == "anchor/linkedin-profile-scraper"


def test_resolve_actor_linkedin_company():
    assert resolve_actor("https://www.linkedin.com/company/anthropic/") == "anchor/linkedin-company-scraper"


def test_resolve_actor_linkedin_default_unknown_path():
    assert resolve_actor("https://www.linkedin.com/feed/") == "anchor/linkedin-profile-scraper"


def test_resolve_actor_instagram():
    assert resolve_actor("https://www.instagram.com/anthropic/") == "apify/instagram-profile-scraper"


def test_resolve_actor_twitter():
    assert resolve_actor("https://twitter.com/AnthropicAI") == "apify/twitter-scraper"


def test_resolve_actor_x_com():
    assert resolve_actor("https://x.com/AnthropicAI") == "apify/twitter-scraper"


def test_resolve_actor_amazon():
    assert resolve_actor("https://www.amazon.com/dp/B09V3KXJPB") == "junglee/amazon-crawler"


def test_resolve_actor_stockx():
    assert resolve_actor("https://stockx.com/nike-dunk-low") == "misceres/stockx-scraper"


def test_resolve_actor_unknown_domain_returns_generic():
    assert resolve_actor("https://www.nytimes.com/section/tech") == _GENERIC_ACTOR


def test_resolve_actor_strips_www_prefix():
    with_www = resolve_actor("https://www.linkedin.com/in/alice/")
    without_www = resolve_actor("https://linkedin.com/in/alice/")
    assert with_www == without_www == "anchor/linkedin-profile-scraper"


def test_resolve_actor_path_pattern_takes_priority_over_default():
    # /jobs/ path should beat the _default for linkedin.com
    jobs = resolve_actor("https://linkedin.com/jobs/view/123")
    default = resolve_actor("https://linkedin.com/notifications/")
    assert jobs == "curious_coder/linkedin-jobs-scraper"
    assert default == "anchor/linkedin-profile-scraper"


# ── fetch_via_apify ───────────────────────────────────────────────────────────


def _make_apify_client(items: list[dict], run_id: str = "run-123", dataset_id: str = "ds-456"):
    """Build a fully-mocked ApifyClientAsync tree."""
    page = MagicMock()
    page.items = items

    dataset_client = AsyncMock()
    dataset_client.list_items = AsyncMock(return_value=page)

    run_dict = {"id": run_id, "defaultDatasetId": dataset_id, "status": "SUCCEEDED"}

    actor_client = AsyncMock()
    actor_client.call = AsyncMock(return_value=run_dict)

    client = MagicMock()
    client.actor = MagicMock(return_value=actor_client)
    client.dataset = MagicMock(return_value=dataset_client)
    return client


@pytest.mark.asyncio
async def test_fetch_via_apify_success_returns_structured_data():
    items = [{"title": "Senior Python Dev", "company": "Anthropic"}]
    client = _make_apify_client(items)

    with patch("pluck.fetchers.apify_handler.ApifyClientAsync", return_value=client):
        result = await fetch_via_apify(
            "https://www.linkedin.com/jobs/search/?keywords=python",
            "tok-fake",
        )

    assert result.success is True
    assert result.structured_data == items


@pytest.mark.asyncio
async def test_fetch_via_apify_has_empty_html():
    client = _make_apify_client([{"x": 1}])
    with patch("pluck.fetchers.apify_handler.ApifyClientAsync", return_value=client):
        result = await fetch_via_apify("https://linkedin.com/jobs/", "tok")
    assert result.html == ""


@pytest.mark.asyncio
async def test_fetch_via_apify_fetcher_used_contains_actor_id():
    client = _make_apify_client([])
    with patch("pluck.fetchers.apify_handler.ApifyClientAsync", return_value=client):
        result = await fetch_via_apify("https://www.linkedin.com/in/alice/", "tok")
    assert "ApifyActor:" in result.fetcher_used
    assert "anchor/linkedin-profile-scraper" in result.fetcher_used


@pytest.mark.asyncio
async def test_fetch_via_apify_metadata_contains_actor_and_run_ids():
    client = _make_apify_client([], run_id="run-xyz", dataset_id="ds-abc")
    with patch("pluck.fetchers.apify_handler.ApifyClientAsync", return_value=client):
        result = await fetch_via_apify("https://linkedin.com/in/bob/", "tok")
    assert result.metadata["actor_id"] == "anchor/linkedin-profile-scraper"
    assert result.metadata["run_id"] == "run-xyz"
    assert result.metadata["dataset_id"] == "ds-abc"


@pytest.mark.asyncio
async def test_fetch_via_apify_item_count_in_metadata():
    items = [{"a": 1}, {"b": 2}, {"c": 3}]
    client = _make_apify_client(items)
    with patch("pluck.fetchers.apify_handler.ApifyClientAsync", return_value=client):
        result = await fetch_via_apify("https://linkedin.com/in/bob/", "tok")
    assert result.metadata["item_count"] == 3


@pytest.mark.asyncio
async def test_fetch_via_apify_none_run_returns_failure():
    actor_client = AsyncMock()
    actor_client.call = AsyncMock(return_value=None)

    client = MagicMock()
    client.actor = MagicMock(return_value=actor_client)

    with patch("pluck.fetchers.apify_handler.ApifyClientAsync", return_value=client):
        result = await fetch_via_apify("https://linkedin.com/in/nobody/", "tok")

    assert result.success is False
    assert result.error is not None
    assert "timed out" in result.error.lower() or "no run" in result.error.lower()


@pytest.mark.asyncio
async def test_fetch_via_apify_api_exception_returns_failure():
    actor_client = AsyncMock()
    actor_client.call = AsyncMock(side_effect=RuntimeError("rate limited"))

    client = MagicMock()
    client.actor = MagicMock(return_value=actor_client)

    with patch("pluck.fetchers.apify_handler.ApifyClientAsync", return_value=client):
        result = await fetch_via_apify("https://linkedin.com/in/nobody/", "tok")

    assert result.success is False
    assert "rate limited" in result.error


@pytest.mark.asyncio
async def test_fetch_via_apify_actor_id_in_failure_metadata():
    actor_client = AsyncMock()
    actor_client.call = AsyncMock(side_effect=RuntimeError("err"))

    client = MagicMock()
    client.actor = MagicMock(return_value=actor_client)

    with patch("pluck.fetchers.apify_handler.ApifyClientAsync", return_value=client):
        result = await fetch_via_apify("https://x.com/someone", "tok")

    assert result.metadata["actor_id"] == "apify/twitter-scraper"


@pytest.mark.asyncio
async def test_fetch_via_apify_empty_items_is_still_success():
    client = _make_apify_client([])
    with patch("pluck.fetchers.apify_handler.ApifyClientAsync", return_value=client):
        result = await fetch_via_apify("https://amazon.com/dp/XYZ", "tok")
    assert result.success is True
    assert result.structured_data == []


@pytest.mark.asyncio
async def test_fetch_via_apify_failed_run_returns_failure():
    """actor.call() returns run dict with status=FAILED — not treated as success."""
    failed_run = {"id": "run-fail", "defaultDatasetId": "ds-fail", "status": "FAILED"}

    actor_client = AsyncMock()
    actor_client.call = AsyncMock(return_value=failed_run)

    client = MagicMock()
    client.actor = MagicMock(return_value=actor_client)

    with patch("pluck.fetchers.apify_handler.ApifyClientAsync", return_value=client):
        result = await fetch_via_apify("https://linkedin.com/in/nobody/", "tok")

    assert result.success is False
    assert "FAILED" in result.error
    assert result.metadata.get("run_status") == "FAILED"


@pytest.mark.asyncio
async def test_fetch_via_apify_timed_out_run_returns_partial_items():
    """TIMED-OUT runs still have dataset items — return them as partial success."""
    items = [{"title": "Python Dev"}, {"title": "ML Eng"}]
    client = _make_apify_client(items, run_id="run-timeout")
    # Override run status to TIMED-OUT
    client.actor.return_value.call.return_value["status"] = "TIMED-OUT"

    with patch("pluck.fetchers.apify_handler.ApifyClientAsync", return_value=client):
        result = await fetch_via_apify("https://linkedin.com/jobs/", "tok")

    assert result.success is True
    assert result.structured_data == items
    assert result.metadata.get("run_status") == "TIMED-OUT"


@pytest.mark.asyncio
async def test_fetch_via_apify_passes_token_to_client():
    client = _make_apify_client([])
    with patch("pluck.fetchers.apify_handler.ApifyClientAsync", return_value=client) as MockClient:
        await fetch_via_apify("https://linkedin.com/in/alice/", "my-secret-token")
    MockClient.assert_called_once_with("my-secret-token")


# ── fetch_via_apify_plan ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_via_apify_plan_passes_actor_input():
    """The run_input handed to actor().call must equal plan[actor_input]."""
    client = _make_apify_client([{"x": 1}])
    plan = {
        "actor_id": "anchor/linkedin-profile-scraper",
        "actor_input": {"profileUrls": ["https://linkedin.com/in/alice"], "maxItems": 25},
        "output_shape": {"explode_field": None, "columns": ["x"], "rename": {}},
    }

    with patch("pluck.fetchers.apify_handler.ApifyClientAsync", return_value=client):
        await fetch_via_apify_plan(plan, "tok")

    _, call_kwargs = client.actor.return_value.call.call_args
    assert call_kwargs["run_input"] == plan["actor_input"]


@pytest.mark.asyncio
async def test_fetch_via_apify_plan_applies_shape():
    """A nested/explode plan -> structured_data is the shaped rows."""
    items = [
        {
            "username": "anthropic",
            "latestPosts": [
                {"caption": "hello", "likes": 10, "extra": "drop me"},
                {"caption": "world", "likes": 20, "extra": "drop me too"},
            ],
        }
    ]
    client = _make_apify_client(items)
    plan = {
        "actor_id": "apify/instagram-profile-scraper",
        "actor_input": {"usernames": ["anthropic"], "resultsLimit": 50},
        "output_shape": {
            "explode_field": "latestPosts",
            "columns": ["caption", "likes"],
            "rename": {},
        },
    }

    with patch("pluck.fetchers.apify_handler.ApifyClientAsync", return_value=client):
        result = await fetch_via_apify_plan(plan, "tok")

    assert result.success is True
    assert result.structured_data == [
        {"caption": "hello", "likes": 10},
        {"caption": "world", "likes": 20},
    ]


@pytest.mark.asyncio
async def test_fetch_via_apify_plan_preserves_metadata():
    """actor_id / run_id / dataset_id are present in the result metadata."""
    client = _make_apify_client([{"x": 1}], run_id="run-plan", dataset_id="ds-plan")
    plan = {
        "actor_id": "anchor/linkedin-profile-scraper",
        "actor_input": {"profileUrls": ["https://linkedin.com/in/bob"], "maxItems": 10},
        "output_shape": {"explode_field": None, "columns": ["x"], "rename": {}},
    }

    with patch("pluck.fetchers.apify_handler.ApifyClientAsync", return_value=client):
        result = await fetch_via_apify_plan(plan, "tok")

    assert result.metadata["actor_id"] == "anchor/linkedin-profile-scraper"
    assert result.metadata["run_id"] == "run-plan"
    assert result.metadata["dataset_id"] == "ds-plan"

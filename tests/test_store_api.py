"""Tests for the Apify Store API client + query builder (Phase 3, Prompt 1)."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from pluck.registry.store_api import build_search_query, search_store


def _resp(body, status=200):
    resp = MagicMock()
    resp.json.return_value = body
    if status >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "err", request=MagicMock(), response=MagicMock()
        )
    else:
        resp.raise_for_status.return_value = None
    return resp


def _client(resp=None, *, get_side_effect=None):
    client = MagicMock()
    client.get = AsyncMock(return_value=resp, side_effect=get_side_effect)
    return client


# ── search_store ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_search_parses_items():
    body = {"data": {"items": [
        {"id": "apify/insta", "username": "apify", "name": "insta",
         "title": "Instagram Scraper", "readmeSummary": "scrapes insta",
         "stats": {"totalUsers30Days": 1200, "lastRunStartedAt": "2026-05-01"}},
    ]}}
    client = _client(_resp(body))

    out = await search_store("instagram", client=client)

    assert len(out) == 1
    assert out[0]["actor_id"] == "apify/insta"
    assert out[0]["title"] == "Instagram Scraper"
    assert out[0]["totalUsers30Days"] == 1200
    assert out[0]["lastRunStartedAt"] == "2026-05-01"


@pytest.mark.asyncio
async def test_search_http_error_returns_empty():
    client = _client(get_side_effect=httpx.RequestError("boom"))
    assert await search_store("x", client=client) == []


@pytest.mark.asyncio
async def test_search_malformed_body_returns_empty():
    client = _client(_resp({"unexpected": True}))
    assert await search_store("x", client=client) == []


@pytest.mark.asyncio
async def test_search_respects_limit():
    client = _client(_resp({"data": {"items": []}}))
    await search_store("instagram", limit=5, client=client)
    assert client.get.call_args.kwargs["params"]["limit"] == 5
    assert client.get.call_args.kwargs["params"]["sortBy"] == "relevance"


# ── build_search_query (Decision 2) ───────────────────────────────────────────

def test_build_query_domain_plus_path():
    assert build_search_query("https://www.linkedin.com/jobs/view/123") == "linkedin jobs"


def test_build_query_strips_prefixes():
    # dp is stripped; the ASIN that follows is not an intent word → stem only.
    assert build_search_query("https://www.amazon.com/dp/B0XXTEST") == "amazon"


def test_build_query_handle_only_returns_stem():
    assert build_search_query("https://instagram.com/natgeo") == "instagram"

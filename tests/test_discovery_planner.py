"""Tests for discovery ranking + schema capture (Phase 3, Prompt 3)."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pluck.registry.discovery_planner import (
    apply_captured_schema,
    capture_output_schema,
    discover_actor,
)

CANDIDATES = [
    {"actor_id": "apify/insta", "title": "Instagram Scraper",
     "readmeSummary": "Scrapes Instagram posts and profiles."},
    {"actor_id": "other/thing", "title": "Other", "readmeSummary": "Unrelated."},
]
URL = "https://mountainproject.com/route/123"


def _set_response(client, payload):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    client.messages.create.return_value = client._make_response(text)


# ── discover_actor ────────────────────────────────────────────────────────────

def test_ranks_and_shapes_entry(mock_anthropic_client):
    _set_response(mock_anthropic_client, {
        "actor_id": "apify/insta",
        "intent_description": "Scrapes posts.",
        "input_template": {"directUrls": ["{url}"], "resultsLimit": "{max_items}"},
        "input_notes": "directUrls is an array.",
        "row_unit": "post",
        "default_columns": ["caption"],
        "all_columns": ["caption", "likesCount"],
        "reasoning": "Best match for posts.",
    })

    entry = discover_actor(URL, "get posts", CANDIDATES, mock_anthropic_client)

    assert entry["actor_id"] == "apify/insta"
    assert entry["source"] == "discovered"
    assert entry["domain_patterns"] == ["mountainproject.com"]
    assert entry["is_default"] is True
    assert entry["input_template"]["directUrls"] == ["{url}"]
    mock_anthropic_client.messages.create.assert_called_once()


def test_unparseable_retries_then_none(mock_anthropic_client):
    bad = mock_anthropic_client._make_response("not json {{{")
    mock_anthropic_client.messages.create.side_effect = [bad, bad]

    entry = discover_actor(URL, "get posts", CANDIDATES, mock_anthropic_client)

    assert entry is None
    assert mock_anthropic_client.messages.create.call_count == 2


def test_empty_candidates_returns_none(mock_anthropic_client):
    entry = discover_actor(URL, "get posts", [], mock_anthropic_client)
    assert entry is None
    mock_anthropic_client.messages.create.assert_not_called()


# ── capture_output_schema / apply_captured_schema ─────────────────────────────

def _apify_client(items, *, call_side_effect=None):
    run = {"status": "SUCCEEDED", "defaultDatasetId": "ds1", "id": "r1"}
    actor_obj = MagicMock()
    actor_obj.call = AsyncMock(return_value=run, side_effect=call_side_effect)
    page = MagicMock()
    page.items = items
    dataset_obj = MagicMock()
    dataset_obj.list_items = AsyncMock(return_value=page)
    client = MagicMock()
    client.actor.return_value = actor_obj
    client.dataset.return_value = dataset_obj
    return client


@pytest.mark.asyncio
async def test_capture_output_schema_returns_row_keys():
    entry = {
        "actor_id": "apify/insta",
        "input_template": {"directUrls": ["{url}"], "resultsLimit": "{max_items}"},
        "default_columns": ["guess"],
        "all_columns": ["guess"],
    }
    client = _apify_client([{"caption": "hi", "likesCount": 5}])

    with patch("pluck.registry.discovery_planner.ApifyClientAsync", return_value=client):
        cols = await capture_output_schema(entry, "tok", URL)

    assert cols == ["caption", "likesCount"]
    applied = apply_captured_schema(entry, cols)
    assert applied["all_columns"] == ["caption", "likesCount"]
    assert applied["default_columns"] == ["caption", "likesCount"]


@pytest.mark.asyncio
async def test_capture_output_schema_failure_returns_empty():
    entry = {
        "actor_id": "apify/insta",
        "input_template": {"directUrls": ["{url}"]},
        "default_columns": ["guess"],
        "all_columns": ["guess"],
    }
    client = _apify_client([], call_side_effect=RuntimeError("boom"))

    with patch("pluck.registry.discovery_planner.ApifyClientAsync", return_value=client):
        cols = await capture_output_schema(entry, "tok", URL)

    assert cols == []
    # apply leaves the readme-guessed columns intact
    applied = apply_captured_schema(entry, cols)
    assert applied["default_columns"] == ["guess"]

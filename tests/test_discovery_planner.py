"""Tests for discovery ranking + schema capture (Phase 3, Prompt 3)."""

import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pluck.registry.discovery_planner import (
    DISCOVERY_LOGIC_VERSION,
    DISCOVERY_SYSTEM,
    _fetch_schemas_parallel,
    _normalize_input_template,
    _simplify_schema,
    apply_captured_schema,
    capture_output_schema,
    discover_actor,
    fetch_actor_input_schema,
)
from pluck.registry.planner import _validate_plan, register_limit_key

CANDIDATES = [
    {"actor_id": "apify/insta", "title": "Instagram Scraper",
     "readmeSummary": "Scrapes Instagram posts and profiles."},
    {"actor_id": "other/thing", "title": "Other", "readmeSummary": "Unrelated."},
]
URL = "https://mountainproject.com/route/123"


def _set_response(client, payload):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    client.messages.create.return_value = client._make_response(text)


# ── _simplify_schema ──────────────────────────────────────────────────────────

def test_simplify_schema_keeps_core_keys_and_truncates_description():
    schema = {
        "required": ["startUrls"],
        "properties": {
            "startUrls": {
                "type": "array", "title": "URLs", "editor": "requestListSources",
                "description": "x" * 200, "prefill": [1, 2], "example": "noise",
                "sectionCaption": "drop me",
            },
        },
    }
    out = _simplify_schema(schema)
    p = out["properties"]["startUrls"]
    assert out["required"] == ["startUrls"]
    assert set(p) == {"type", "title", "editor", "description"}
    assert len(p["description"]) == 120  # truncated
    assert "prefill" not in p and "example" not in p and "sectionCaption" not in p


def test_simplify_schema_returns_empty_on_garbage():
    assert _simplify_schema("not a dict") == {}
    assert _simplify_schema({"no": "properties"}) == {}


# ── _fetch_schemas_parallel ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_schemas_parallel_omits_failures(caplog):
    good = {"properties": {"maxItems": {"type": "integer"}}, "required": []}

    async def fake_fetch(actor_id, token):
        if actor_id == "b/2":
            raise RuntimeError("boom")
        return good

    with patch(
        "pluck.registry.discovery_planner.fetch_actor_input_schema",
        side_effect=fake_fetch,
    ):
        with caplog.at_level("WARNING"):
            out = await _fetch_schemas_parallel(["a/1", "b/2", "c/3"], "tok")

    assert set(out) == {"a/1", "c/3"}  # the raiser is omitted
    assert any("b/2" in r.message for r in caplog.records)


# ── discover_actor (single-pass) ──────────────────────────────────────────────

INSTA_SCHEMA = {
    "required": ["directUrls"],
    "properties": {
        "directUrls": {"type": "array"},
        "resultsLimit": {"type": "integer"},
    },
}


def _schemas_patch(mapping):
    return patch(
        "pluck.registry.discovery_planner._fetch_schemas_parallel",
        new=AsyncMock(return_value=mapping),
    )


@pytest.mark.asyncio
async def test_discover_actor_single_pass_returns_entry(mock_anthropic_client):
    _set_response(mock_anthropic_client, {
        "actor_id": "apify/insta",
        "rationale": "Best fit for posts.",
        "input_template": {"directUrls": ["{url}"], "resultsLimit": "{max_items}"},
        "limit_field": "resultsLimit",
    })
    with _schemas_patch({"apify/insta": INSTA_SCHEMA}):
        entry = await discover_actor(URL, "get posts", CANDIDATES, mock_anthropic_client, apify_token="t")

    assert entry["actor_id"] == "apify/insta"
    assert entry["source"] == "discovered"
    assert entry["domain_patterns"] == ["mountainproject.com"]
    assert entry["limit_field"] == "resultsLimit"
    assert entry["logic_version"] == DISCOVERY_LOGIC_VERSION
    assert entry["input_template"]["resultsLimit"] == "{max_items}"
    mock_anthropic_client.messages.create.assert_called_once()


@pytest.mark.asyncio
async def test_discover_actor_drops_keys_absent_from_schema(mock_anthropic_client):
    _set_response(mock_anthropic_client, {
        "actor_id": "apify/insta",
        "rationale": "x",
        "input_template": {"directUrls": ["{url}"], "bogusField": "nope"},
        "limit_field": None,
    })
    with _schemas_patch({"apify/insta": INSTA_SCHEMA}):
        entry = await discover_actor(URL, "p", CANDIDATES, mock_anthropic_client, apify_token="t")

    assert "bogusField" not in entry["input_template"]
    assert "directUrls" in entry["input_template"]


@pytest.mark.asyncio
async def test_discover_actor_missing_required_nonproxy_returns_none(mock_anthropic_client):
    _set_response(mock_anthropic_client, {
        "actor_id": "apify/insta",
        "rationale": "x",
        "input_template": {"resultsLimit": "{max_items}"},  # missing required directUrls
        "limit_field": "resultsLimit",
    })
    with _schemas_patch({"apify/insta": INSTA_SCHEMA}):
        entry = await discover_actor(URL, "p", CANDIDATES, mock_anthropic_client, apify_token="t")

    assert entry is None


@pytest.mark.asyncio
async def test_discover_actor_autofills_required_proxy(mock_anthropic_client):
    schema = {
        "required": ["startUrls", "proxyConfiguration"],
        "properties": {
            "startUrls": {"type": "array"},
            "proxyConfiguration": {"type": "object", "editor": "proxy"},
        },
    }
    _set_response(mock_anthropic_client, {
        "actor_id": "reddit/scraper",
        "rationale": "x",
        "input_template": {"startUrls": [{"url": "{url}"}]},  # omits required proxy
        "limit_field": None,
    })
    cands = [{"actor_id": "reddit/scraper", "title": "Reddit", "readmeSummary": "posts"}]
    with _schemas_patch({"reddit/scraper": schema}):
        entry = await discover_actor(URL, "p", cands, mock_anthropic_client, apify_token="t")

    assert entry is not None
    assert entry["input_template"]["proxyConfiguration"] == {"useApifyProxy": True}


@pytest.mark.asyncio
async def test_discover_actor_empty_candidates_returns_none(mock_anthropic_client):
    entry = await discover_actor(URL, "p", [], mock_anthropic_client, apify_token="t")
    assert entry is None
    mock_anthropic_client.messages.create.assert_not_called()


@pytest.mark.asyncio
async def test_discover_actor_all_schemas_fail_returns_none(mock_anthropic_client):
    with _schemas_patch({}):  # no schemas fetched
        entry = await discover_actor(URL, "p", CANDIDATES, mock_anthropic_client, apify_token="t")
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
    client = _apify_client([{"caption": "hi", "likesCount": 5, "timestamp": "2026"}])

    with patch("pluck.registry.discovery_planner.ApifyClientAsync", return_value=client):
        cols = await capture_output_schema(entry, "tok", URL)

    assert cols == ["caption", "likesCount", "timestamp"]
    applied = apply_captured_schema(entry, cols)
    assert applied["all_columns"] == ["caption", "likesCount", "timestamp"]
    assert applied["default_columns"] == ["caption", "likesCount", "timestamp"]


@pytest.mark.asyncio
async def test_capture_returns_empty_on_thin_row():
    # A row with only one key is not real content → treat as failed capture.
    entry = {"actor_id": "apify/insta", "input_template": {"url": "{url}"}}
    client = _apify_client([{"error": "blocked"}])

    with patch("pluck.registry.discovery_planner.ApifyClientAsync", return_value=client):
        cols = await capture_output_schema(entry, "tok", URL)

    assert cols == []


@pytest.mark.asyncio
async def test_capture_returns_columns_on_real_row():
    entry = {"actor_id": "apify/insta", "input_template": {"url": "{url}"}}
    row = {"id": 1, "text": "hi", "likes": 5, "url": "u", "author": "a"}
    client = _apify_client([row])

    with patch("pluck.registry.discovery_planner.ApifyClientAsync", return_value=client):
        cols = await capture_output_schema(entry, "tok", URL)

    assert cols == ["id", "text", "likes", "url", "author"]


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


# ── fetch_actor_input_schema ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_actor_input_schema_follows_build():
    """Actor object has no inline schema → follow taggedBuilds.latest to the build."""
    inner = json.dumps({"properties": {"maxItems": {"type": "integer"}}, "required": []})

    async def fake_get(url, params=None):
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        if "/builds/" in url:
            resp.json.return_value = {"data": {"inputSchema": inner}}
        else:
            resp.json.return_value = {"data": {"taggedBuilds": {"latest": {"buildId": "B1"}}}}
        return resp

    client = MagicMock()
    client.get = AsyncMock(side_effect=fake_get)

    schema = await fetch_actor_input_schema("apify/tiktok-scraper", "tok", client=client)

    assert "maxItems" in schema["properties"]


def test_register_limit_key_enables_clamp():
    """A runtime-registered limit field is clamped to the ceiling like a static one."""
    register_limit_key("resultsPerPage")
    candidate = {
        "actor_id": "x/y",
        "input_template": {"resultsPerPage": "{max_items}"},
        "all_columns": ["a"],
        "default_columns": ["a"],
    }
    plan = {
        "actor_id": "x/y",
        "actor_input": {"resultsPerPage": 10000},
        "output_shape": {"columns": ["a"]},
    }
    validated = _validate_plan(plan, [candidate], 50)
    assert validated["actor_input"]["resultsPerPage"] == 50


# ── Issue 1: input-template normalization against the real schema ─────────────

def test_normalize_string_array_to_object_array():
    # requestListSources field: Haiku gave a string array; schema wants object array.
    schema = {"properties": {"startUrls": {"type": "array", "editor": "requestListSources"}}}
    out = _normalize_input_template({"startUrls": ["https://x.com/y"]}, schema)
    assert out["startUrls"] == [{"url": "https://x.com/y"}]


def test_normalize_uses_schema_item_key():
    # items.properties names the key ("link", not "url") → use it.
    schema = {"properties": {"sources": {
        "type": "array", "items": {"type": "object", "properties": {"link": {"type": "string"}}}}}}
    out = _normalize_input_template({"sources": ["u1", "u2"]}, schema)
    assert out["sources"] == [{"link": "u1"}, {"link": "u2"}]


def test_normalize_already_correct_shape():
    schema = {"properties": {"startUrls": {"type": "array", "editor": "requestListSources"}}}
    template = {"startUrls": [{"url": "https://x.com/y"}]}
    out = _normalize_input_template(template, schema)
    assert out == template


def test_normalize_object_to_array_of_objects():
    # schema expects a proxy object; Haiku gave a string → wrap to the proxy object.
    schema = {"properties": {"proxyConfiguration": {"type": "object", "editor": "proxy"}}}
    out = _normalize_input_template({"proxyConfiguration": "RESIDENTIAL"}, schema)
    assert out["proxyConfiguration"] == {"useApifyProxy": True}


def test_normalize_logs_transformations(caplog):
    schema = {"properties": {"startUrls": {"type": "array", "editor": "requestListSources"}}}
    with caplog.at_level(logging.INFO, logger="pluck.registry.discovery_planner"):
        _normalize_input_template({"startUrls": ["x"]}, schema)
    assert any("Normalized input field startUrls" in r.message for r in caplog.records)


# ── Issue 2: ranking guidance in the discovery system prompt ──────────────────
# Behavioural verification (a video scraper is chosen for "get videos") is a live
# concern of a real model, exercised by the tiktok smoke test; here we assert the
# steering rules are present in the prompt.

def test_ranking_prompt_prefers_per_item_for_list_intents():
    sys = DISCOVERY_SYSTEM.lower()
    assert "one row per item" in sys
    assert "video scraper" in sys
    assert "profile scraper" in sys


def test_ranking_prompt_keeps_profile_for_aggregate_intents():
    sys = DISCOVERY_SYSTEM.lower()
    assert "get bio" in sys or "follower count" in sys


def test_prompt_includes_object_array_example():
    assert '[{"url": "{url}"}]' in DISCOVERY_SYSTEM

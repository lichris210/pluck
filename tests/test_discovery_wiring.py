"""Tests for discovery fall-through wiring in /api/extract (Phase 3, Prompt 5).

When USE_PLANNER is on and a host has no tier-1/tier-2 candidate, the handler runs
the discovery pipeline (search → filter → rank → capture schema → cache), emits a
"discovery" SSE event, and plans against the discovered actor. A repeat request is
served from tier 2 (loader union) without re-searching the Store.

temp_store uses default_ttl_seconds=0 so the results cache never short-circuits a
repeat request before it reaches the discovery/planner block.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.main import app
from pluck.models import FetchResult, SiteGroup, SiteProfile
from pluck.storage.cache_store import SchemaCacheStore

UNKNOWN_URL = "https://mountainproject.com/route/123"
HOST = "mountainproject.com"


# ── helpers ──────────────────────────────────────────────────────────────────

def _site_profile(url, site_group=SiteGroup.STATIC_HTML):
    return SiteProfile(
        url=url, final_url=url, status_code=200, headers={},
        content_type="text/html", html="<html><body>page</body></html>",
        site_group=site_group, classification_reasons=["test"],
        response_time_ms=100.0,
    )


def _discovered_entry():
    return {
        "domain_patterns": [HOST],
        "actor_id": "climber/mp",
        "intent_description": "scrapes routes",
        "input_template": {"startUrls": [{"url": "{url}"}], "maxItems": "{max_items}"},
        "default_columns": ["name"],
        "all_columns": ["name", "grade"],
        "is_default": True,
        "source": "discovered",
        "reasoning": "Best match for climbing routes.",
    }


def _plan():
    return {
        "actor_id": "climber/mp",
        "actor_input": {"startUrls": [{"url": UNKNOWN_URL}], "maxItems": 100},
        "output_shape": {"explode_field": None, "columns": ["name"], "rename": {}},
        "reasoning": "Best match for climbing routes.",
    }


def _apify_result():
    return FetchResult(
        url=UNKNOWN_URL, html="", fetcher_used="apify", fetch_time_ms=300.0,
        success=True, structured_data=[{"name": "The Nose"}],
        metadata={"apify_cost_usd": 0.01},
    )


def _html_result():
    return FetchResult(
        url=UNKNOWN_URL, html="<html><body>x</body></html>",
        fetcher_used="scrapling_static", fetch_time_ms=120.0, success=True,
    )


def _parse_sse(text: str) -> list[dict]:
    out = []
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            out.append(json.loads(line[6:]))
    return out


# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def temp_store(tmp_path):
    s = SchemaCacheStore(db_path=str(tmp_path / "discovery_wiring.db"), default_ttl_seconds=0)
    yield s
    s.close()


@pytest.fixture
def client(temp_store):
    with patch("api.routes._schema_cache", temp_store):
        yield TestClient(app)


def _token(client) -> str:
    resp = client.post("/api/auth", json={"password": "pluck"})
    assert resp.status_code == 200
    return resp.json()["token"]


_ENV = {"USE_PLANNER": "true", "APIFY_TOKEN": "test-token", "ANTHROPIC_API_KEY": "test-key"}


# ── test 1: unknown host triggers discovery ──────────────────────────────────

def test_unknown_host_triggers_discovery(client, temp_store):
    tok = _token(client)
    with (
        patch.dict("os.environ", _ENV),
        patch("api.routes.ingest", new_callable=AsyncMock) as mock_ingest,
        patch("api.routes.search_store", new_callable=AsyncMock) as mock_search,
        patch("api.routes.discover_actor") as mock_discover,
        patch("api.routes.capture_output_schema", new_callable=AsyncMock) as mock_capture,
        patch("api.routes.plan_extraction") as mock_plan,
        patch("pluck.fetchers.router.fetch_via_apify_plan", new_callable=AsyncMock) as mock_apify,
    ):
        mock_ingest.return_value = _site_profile(UNKNOWN_URL)
        mock_search.return_value = [{"actor_id": "climber/mp", "title": "MP",
                                     "readmeSummary": "routes",
                                     "totalUsers30Days": 999, "lastRunStartedAt": "2026-06-01"}]
        mock_discover.return_value = _discovered_entry()
        mock_capture.return_value = ["name", "grade"]
        mock_plan.return_value = _plan()
        mock_apify.return_value = _apify_result()

        resp = client.get("/api/extract", params={
            "url": UNKNOWN_URL, "prompt": "list routes", "token": tok,
        })

    assert resp.status_code == 200
    events = _parse_sse(resp.text)

    mock_search.assert_called_once()
    mock_discover.assert_called_once()
    disc = next(
        e for e in events
        if e.get("step") == "discovery" and e.get("source") == "discovered"
    )
    assert disc["actor_id"] == "climber/mp"
    assert disc["confidence"] == "low"

    # The discovered entry was persisted to tier 2 and its counter incremented.
    cached = temp_store.get_discovered(HOST)
    assert len(cached) == 1
    assert cached[0]["actor_id"] == "climber/mp"
    assert cached[0]["successful_runs"] == 1


# ── test 2: second request served from tier 2 ────────────────────────────────

def test_second_request_uses_tier2_cache(client, temp_store):
    tok = _token(client)
    with (
        patch.dict("os.environ", _ENV),
        patch("api.routes.ingest", new_callable=AsyncMock) as mock_ingest,
        patch("api.routes.search_store", new_callable=AsyncMock) as mock_search,
        patch("api.routes.discover_actor") as mock_discover,
        patch("api.routes.capture_output_schema", new_callable=AsyncMock) as mock_capture,
        patch("api.routes.plan_extraction") as mock_plan,
        patch("pluck.fetchers.router.fetch_via_apify_plan", new_callable=AsyncMock) as mock_apify,
    ):
        mock_ingest.return_value = _site_profile(UNKNOWN_URL)
        mock_search.return_value = [{"actor_id": "climber/mp", "title": "MP",
                                     "readmeSummary": "routes",
                                     "totalUsers30Days": 999, "lastRunStartedAt": "2026-06-01"}]
        mock_discover.return_value = _discovered_entry()
        mock_capture.return_value = ["name"]
        mock_plan.return_value = _plan()
        mock_apify.return_value = _apify_result()

        params = {"url": UNKNOWN_URL, "prompt": "list routes", "token": tok}
        client.get("/api/extract", params=params)   # first: discovers
        client.get("/api/extract", params=params)   # second: tier-2 hit

    # Store searched only on the first request.
    assert mock_search.call_count == 1
    # Counter bumped on both successful scrapes.
    cached = temp_store.get_discovered(HOST)
    assert cached[0]["successful_runs"] == 2


# ── test 3: discovery finds nothing → legacy fall-through, no crash ───────────

def test_discovery_finds_nothing_falls_back(client):
    tok = _token(client)
    with (
        patch.dict("os.environ", _ENV),
        patch("api.routes.ingest", new_callable=AsyncMock) as mock_ingest,
        patch("api.routes.search_store", new_callable=AsyncMock) as mock_search,
        patch("api.routes.discover_actor") as mock_discover,
        patch("api.routes.plan_extraction") as mock_plan,
        patch("api.routes.route_fetch", new_callable=AsyncMock) as mock_fetch,
        patch("api.routes.extract", new_callable=AsyncMock) as mock_extract,
    ):
        mock_ingest.return_value = _site_profile(UNKNOWN_URL)
        mock_search.return_value = []
        mock_discover.return_value = None  # nothing suitable
        mock_fetch.return_value = _html_result()
        mock_extract.return_value = MagicMock(
            items=[{"name": "x"}], error=None, schema_cache_hit=False,
            total_input_tokens=10, total_output_tokens=5,
            extraction_time_ms=50.0, model_used="claude-haiku-4-5",
        )

        resp = client.get("/api/extract", params={
            "url": UNKNOWN_URL, "prompt": "list routes", "token": tok,
        })

    assert resp.status_code == 200
    events = _parse_sse(resp.text)

    mock_plan.assert_not_called()                      # planned_path stayed False
    mock_fetch.assert_called_once()
    assert mock_fetch.call_args.kwargs.get("plan") is None
    # No resolved discovery event (only the "active" probe, no source=discovered).
    assert not any(e.get("source") == "discovered" for e in events)
    assert any(e.get("step") == "done" for e in events)

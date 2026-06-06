"""Tests for plan-cache wiring in the /api/extract SSE handler (Phase 2, Prompt 2).

On the planned path the handler checks the plan cache before the Haiku planner and
writes to it after a successful plan: a (host, prompt_hash) hit skips plan_extraction
entirely and emits a {"step": "plan_cache", "status": "hit"} event. refresh=true
bypasses the read but still recomputes + writes.

The temp_store uses default_ttl_seconds=0 so the *results* cache (a separate cache
keyed differently) never short-circuits a repeat request before it reaches the
planner; the plan_cache uses its own 7-day TTL and is unaffected.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from api.main import app
from pluck.models import FetchResult, SiteGroup, SiteProfile
from pluck.storage.cache_store import SchemaCacheStore

REGISTRY_URL = "https://www.instagram.com/nasa/"


# ── shared helpers ───────────────────────────────────────────────────────────

def _site_profile(url, site_group=SiteGroup.AUTH_GATED):
    return SiteProfile(
        url=url, final_url=url, status_code=200, headers={},
        content_type="text/html",
        html="<html><body>page</body></html>",
        site_group=site_group,
        classification_reasons=["test"],
        response_time_ms=100.0,
    )


def _plan():
    return {
        "actor_id": "apify/instagram-profile-scraper",
        "actor_input": {"usernames": ["nasa"], "resultsLimit": 100},
        "output_shape": {"explode_field": None, "columns": ["caption"], "rename": {}},
        "reasoning": "Profile scraper best matches the prompt.",
    }


def _apify_fetch_result(url=REGISTRY_URL):
    return FetchResult(
        url=url,
        html="",
        fetcher_used="apify",
        fetch_time_ms=300.0,
        success=True,
        structured_data=[{"caption": "Hello from orbit"}],
        metadata={"apify_cost_usd": 0.05},
    )


def _parse_sse(text: str) -> list[dict]:
    events = []
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def temp_store(tmp_path):
    # default_ttl_seconds=0 → results cache always misses, so a repeat request
    # still reaches the planner block; plan_cache uses its own 7-day TTL.
    s = SchemaCacheStore(db_path=str(tmp_path / "plan_cache_wiring.db"), default_ttl_seconds=0)
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


# ── test 1: miss then hit ─────────────────────────────────────────────────────

def test_plan_cache_miss_then_hit(client):
    tok = _token(client)

    with (
        patch.dict("os.environ", {
            "USE_PLANNER": "true",
            "APIFY_TOKEN": "test-token",
            "ANTHROPIC_API_KEY": "test-key",
        }),
        patch("api.routes.ingest", new_callable=AsyncMock) as mock_ingest,
        patch("api.routes.plan_extraction") as mock_plan,
        patch(
            "pluck.fetchers.router.fetch_via_apify_plan", new_callable=AsyncMock
        ) as mock_apify_plan,
    ):
        mock_ingest.return_value = _site_profile(REGISTRY_URL)
        mock_plan.return_value = _plan()
        mock_apify_plan.return_value = _apify_fetch_result()

        params = {"url": REGISTRY_URL, "prompt": "latest captions", "token": tok}

        # First request — cache miss: planner runs once, no plan_cache hit event.
        resp1 = client.get("/api/extract", params=params)
        assert resp1.status_code == 200
        events1 = _parse_sse(resp1.text)
        assert mock_plan.call_count == 1
        assert not any(
            e.get("step") == "plan_cache" and e.get("status") == "hit"
            for e in events1
        )

        # Second request — cache hit: planner NOT called again, hit event present.
        resp2 = client.get("/api/extract", params=params)
        assert resp2.status_code == 200
        events2 = _parse_sse(resp2.text)

        assert mock_plan.call_count == 1  # still one — Haiku skipped
        assert any(
            e.get("step") == "plan_cache" and e.get("status") == "hit"
            for e in events2
        )
        planning_done = next(
            e for e in events2 if e["step"] == "planning" and e["status"] == "done"
        )
        assert planning_done["actor_id"] == "apify/instagram-profile-scraper"


# ── test 2: refresh bypasses the plan cache ───────────────────────────────────

def test_refresh_bypasses_plan_cache(client):
    tok = _token(client)

    with (
        patch.dict("os.environ", {
            "USE_PLANNER": "true",
            "APIFY_TOKEN": "test-token",
            "ANTHROPIC_API_KEY": "test-key",
        }),
        patch("api.routes.ingest", new_callable=AsyncMock) as mock_ingest,
        patch("api.routes.plan_extraction") as mock_plan,
        patch(
            "pluck.fetchers.router.fetch_via_apify_plan", new_callable=AsyncMock
        ) as mock_apify_plan,
    ):
        mock_ingest.return_value = _site_profile(REGISTRY_URL)
        mock_plan.return_value = _plan()
        mock_apify_plan.return_value = _apify_fetch_result()

        params = {"url": REGISTRY_URL, "prompt": "latest captions", "token": tok}

        # Prime the cache.
        client.get("/api/extract", params=params)
        assert mock_plan.call_count == 1

        # refresh=true bypasses the plan-cache read → planner runs again.
        client.get("/api/extract", params={**params, "refresh": "true"})
        assert mock_plan.call_count == 2


# ── test 3: a different prompt is a different key (miss) ───────────────────────

def test_different_prompt_misses_cache(client):
    tok = _token(client)

    with (
        patch.dict("os.environ", {
            "USE_PLANNER": "true",
            "APIFY_TOKEN": "test-token",
            "ANTHROPIC_API_KEY": "test-key",
        }),
        patch("api.routes.ingest", new_callable=AsyncMock) as mock_ingest,
        patch("api.routes.plan_extraction") as mock_plan,
        patch(
            "pluck.fetchers.router.fetch_via_apify_plan", new_callable=AsyncMock
        ) as mock_apify_plan,
    ):
        mock_ingest.return_value = _site_profile(REGISTRY_URL)
        mock_plan.return_value = _plan()
        mock_apify_plan.return_value = _apify_fetch_result()

        client.get("/api/extract", params={
            "url": REGISTRY_URL, "prompt": "latest captions", "token": tok,
        })
        assert mock_plan.call_count == 1

        # Same URL, different prompt → different key → planner runs again.
        client.get("/api/extract", params={
            "url": REGISTRY_URL, "prompt": "follower count", "token": tok,
        })
        assert mock_plan.call_count == 2

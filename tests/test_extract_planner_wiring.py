"""Tests for planner wiring in the /api/extract SSE handler (Prompt 7).

The planner runs only behind USE_PLANNER and only for registry hosts; when it
runs it forces the Apify branch (plan gotcha 2), bills its tokens, emits a
planning SSE event, threads the plan into route_fetch, and skips derive_columns.

ingest / plan_extraction / fetch_via_apify_plan are mocked; a temp-DB
SchemaCacheStore is injected so the real pluck_cache.db is never touched.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.main import app
from pluck.models import FetchResult, SiteGroup, SiteProfile
from pluck.storage.cache_store import SchemaCacheStore

REGISTRY_URL = "https://www.instagram.com/nasa/"
PLAIN_URL = "https://example.com/products"


# ── shared helpers ───────────────────────────────────────────────────────────

def _site_profile(url, site_group=SiteGroup.STATIC_HTML):
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


def _html_fetch_result(url=PLAIN_URL):
    return FetchResult(
        url=url,
        html="<html><body>Products</body></html>",
        fetcher_used="scrapling_static",
        fetch_time_ms=200.0,
        success=True,
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
    s = SchemaCacheStore(db_path=str(tmp_path / "planner_wiring.db"))
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


# ── test 1: planner runs for a registry host when the flag is on ──────────────

def test_planner_invoked_for_registry_host(client):
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
        # STATIC_HTML proves gotcha 2: a registry host that would classify into a
        # live-fetch group is still forced down the Apify branch.
        mock_ingest.return_value = _site_profile(REGISTRY_URL, SiteGroup.STATIC_HTML)
        mock_plan.return_value = _plan()
        mock_apify_plan.return_value = _apify_fetch_result()

        resp = client.get("/api/extract", params={
            "url": REGISTRY_URL, "prompt": "latest captions", "token": tok,
        })

    assert resp.status_code == 200
    events = _parse_sse(resp.text)

    mock_plan.assert_called_once()
    # route_fetch (real) forwarded the plan to the planned Apify path.
    mock_apify_plan.assert_called_once()
    assert mock_apify_plan.call_args.args[0] == _plan()

    planning_done = next(
        e for e in events if e["step"] == "planning" and e["status"] == "done"
    )
    assert planning_done["actor_id"] == "apify/instagram-profile-scraper"
    assert planning_done["reasoning"] == "Profile scraper best matches the prompt."
    assert any(e["step"] == "planning" and e["status"] == "active" for e in events)
    assert any(e["step"] == "done" for e in events)


# ── test 2: flag off → legacy path, planner never consulted ───────────────────

def test_planner_skipped_when_flag_off(client):
    tok = _token(client)

    with (
        patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}, clear=False),
        patch("api.routes.ingest", new_callable=AsyncMock) as mock_ingest,
        patch("api.routes.plan_extraction") as mock_plan,
        patch("api.routes.route_fetch", new_callable=AsyncMock) as mock_fetch,
        patch("api.routes.extract", new_callable=AsyncMock) as mock_extract,
    ):
        # Ensure the flag is unset for this request.
        import os
        os.environ.pop("USE_PLANNER", None)

        mock_ingest.return_value = _site_profile(REGISTRY_URL, SiteGroup.STATIC_HTML)
        mock_fetch.return_value = _html_fetch_result(REGISTRY_URL)
        mock_extract.return_value = MagicMock(
            items=[{"name": "x"}], error=None, schema_cache_hit=False,
            total_input_tokens=10, total_output_tokens=5,
            extraction_time_ms=50.0, model_used="claude-haiku-4-5",
        )

        resp = client.get("/api/extract", params={"url": REGISTRY_URL, "token": tok})

    assert resp.status_code == 200
    events = _parse_sse(resp.text)

    mock_plan.assert_not_called()
    mock_fetch.assert_called_once()
    assert not any(e["step"] == "planning" for e in events)
    assert any(e["step"] == "done" for e in events)


# ── test 3: out-of-registry domain falls through even with the flag on ────────

def test_out_of_registry_falls_through(client):
    tok = _token(client)

    with (
        patch.dict("os.environ", {
            "USE_PLANNER": "true", "ANTHROPIC_API_KEY": "test-key",
        }),
        patch("api.routes.ingest", new_callable=AsyncMock) as mock_ingest,
        patch("api.routes.plan_extraction") as mock_plan,
        patch("api.routes.route_fetch", new_callable=AsyncMock) as mock_fetch,
        patch("api.routes.extract", new_callable=AsyncMock) as mock_extract,
    ):
        mock_ingest.return_value = _site_profile(PLAIN_URL, SiteGroup.STATIC_HTML)
        mock_fetch.return_value = _html_fetch_result(PLAIN_URL)
        mock_extract.return_value = MagicMock(
            items=[{"name": "x"}], error=None, schema_cache_hit=False,
            total_input_tokens=10, total_output_tokens=5,
            extraction_time_ms=50.0, model_used="claude-haiku-4-5",
        )

        resp = client.get("/api/extract", params={"url": PLAIN_URL, "token": tok})

    assert resp.status_code == 200
    events = _parse_sse(resp.text)

    mock_plan.assert_not_called()
    mock_fetch.assert_called_once()
    # Legacy path uses use_apify=force_apify (False) and no plan.
    assert mock_fetch.call_args.kwargs.get("plan") is None
    assert not any(e["step"] == "planning" for e in events)


# ── test 4: planned path skips the derive_columns column step ─────────────────

def test_planned_path_skips_derive_columns(client):
    tok = _token(client)

    with (
        patch.dict("os.environ", {
            "USE_PLANNER": "true",
            "APIFY_TOKEN": "test-token",
            "ANTHROPIC_API_KEY": "test-key",
        }),
        patch("api.routes.ingest", new_callable=AsyncMock) as mock_ingest,
        patch("api.routes.plan_extraction") as mock_plan,
        patch("api.routes.derive_columns") as mock_derive,
        patch(
            "pluck.fetchers.router.fetch_via_apify_plan", new_callable=AsyncMock
        ) as mock_apify_plan,
    ):
        mock_ingest.return_value = _site_profile(REGISTRY_URL, SiteGroup.AUTH_GATED)
        mock_plan.return_value = _plan()
        mock_apify_plan.return_value = _apify_fetch_result()

        # A prompt is supplied — derive_columns WOULD run on the legacy path.
        resp = client.get("/api/extract", params={
            "url": REGISTRY_URL, "prompt": "only captions", "token": tok,
        })

    assert resp.status_code == 200
    mock_plan.assert_called_once()
    mock_derive.assert_not_called()

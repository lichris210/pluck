"""No-network mirror of the Phase 1 live cases (1 & 2).

These prove the end-to-end /api/extract wiring for the planned Apify path
without hitting Anthropic or Apify: ``ingest``, ``plan_extraction`` and
``fetch_via_apify_plan`` are mocked, and a temp-DB SchemaCacheStore is injected
so the real pluck_cache.db is never touched. The live equivalents live in
tests/integration/test_planner_e2e.py.

Mock patterns mirror tests/test_extract_planner_wiring.py.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from api.main import app
from pluck.models import FetchResult, SiteGroup, SiteProfile
from pluck.registry.loader import candidates_for_url, find_entry
from pluck.storage.cache_store import SchemaCacheStore

NATGEO_URL = "https://www.instagram.com/natgeo/"

POST_ACTOR = "apify/instagram-post-scraper"
PROFILE_ACTOR = "apify/instagram-profile-scraper"


# ── helpers ──────────────────────────────────────────────────────────────────

def _default_columns(actor_id: str) -> list[str]:
    entry = find_entry(actor_id, candidates_for_url(NATGEO_URL))
    assert entry is not None, f"{actor_id} missing from registry"
    return list(entry["default_columns"])


def _site_profile(url=NATGEO_URL, site_group=SiteGroup.STATIC_HTML):
    return SiteProfile(
        url=url, final_url=url, status_code=200, headers={},
        content_type="text/html",
        html="<html><body>profile</body></html>",
        site_group=site_group,
        classification_reasons=["test"],
        response_time_ms=100.0,
    )


def _post_plan():
    cols = _default_columns(POST_ACTOR)
    return {
        "actor_id": POST_ACTOR,
        "actor_input": {"username": ["natgeo"], "resultsLimit": 100},
        "output_shape": {"explode_field": None, "columns": cols, "rename": {}},
        "reasoning": "Post scraper best matches a request to scrape the postings.",
    }


def _profile_plan():
    cols = _default_columns(PROFILE_ACTOR)
    return {
        "actor_id": PROFILE_ACTOR,
        "actor_input": {"usernames": ["natgeo"]},
        "output_shape": {"explode_field": None, "columns": cols, "rename": {}},
        "reasoning": "Profile scraper returns the bio and follower count.",
    }


def _shaped_post_rows(n: int) -> list[dict]:
    cols = _default_columns(POST_ACTOR)
    rows = []
    for i in range(n):
        rows.append({c: f"{c}-{i}" for c in cols})
    return rows


def _shaped_profile_row() -> list[dict]:
    cols = _default_columns(PROFILE_ACTOR)
    return [{c: f"{c}-val" for c in cols}]


def _apify_result(rows: list[dict]) -> FetchResult:
    return FetchResult(
        url=NATGEO_URL,
        html="",
        fetcher_used="apify",
        fetch_time_ms=300.0,
        success=True,
        structured_data=rows,
        metadata={"apify_cost_usd": 0.05},
    )


def _parse_sse(text: str) -> list[dict]:
    events = []
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


# ── fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def temp_store(tmp_path):
    s = SchemaCacheStore(db_path=str(tmp_path / "planner_e2e_mocked.db"))
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


# ── case 1: "scrape the postings" → post-scraper, shaped rows streamed ────────

def test_posts_intent_mocked(client):
    tok = _token(client)
    rows = _shaped_post_rows(12)

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
        mock_ingest.return_value = _site_profile()
        mock_plan.return_value = _post_plan()
        mock_apify_plan.return_value = _apify_result(rows)

        resp = client.get("/api/extract", params={
            "url": NATGEO_URL, "prompt": "scrape the postings", "token": tok,
        })

    assert resp.status_code == 200
    events = _parse_sse(resp.text)

    mock_plan.assert_called_once()
    mock_apify_plan.assert_called_once()
    # route_fetch forwarded the planner's plan to the planned Apify path.
    assert mock_apify_plan.call_args.args[0]["actor_id"] == POST_ACTOR

    planning_done = next(
        e for e in events if e["step"] == "planning" and e["status"] == "done"
    )
    assert planning_done["actor_id"] == POST_ACTOR

    done = next(e for e in events if e["step"] == "done")
    assert done["total_rows"] == 12
    post_cols = set(_default_columns(POST_ACTOR))
    for item in done["items"]:
        assert set(item.keys()) <= post_cols
    assert done["model_used"] == "none"  # structured path skips extraction


# ── case 2: "bio and follower count" → profile-scraper, single shaped row ─────

def test_profile_intent_mocked(client):
    tok = _token(client)
    rows = _shaped_profile_row()

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
        mock_ingest.return_value = _site_profile()
        mock_plan.return_value = _profile_plan()
        mock_apify_plan.return_value = _apify_result(rows)

        resp = client.get("/api/extract", params={
            "url": NATGEO_URL,
            "prompt": "get the bio and follower count",
            "token": tok,
        })

    assert resp.status_code == 200
    events = _parse_sse(resp.text)

    mock_plan.assert_called_once()
    mock_apify_plan.assert_called_once()
    assert mock_apify_plan.call_args.args[0]["actor_id"] == PROFILE_ACTOR

    planning_done = next(
        e for e in events if e["step"] == "planning" and e["status"] == "done"
    )
    assert planning_done["actor_id"] == PROFILE_ACTOR

    done = next(e for e in events if e["step"] == "done")
    assert done["total_rows"] == 1
    profile_cols = set(_default_columns(PROFILE_ACTOR))
    assert set(done["items"][0].keys()) <= profile_cols

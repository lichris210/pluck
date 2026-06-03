"""Live end-to-end tests for the Phase 1 planned Apify path.

These exercise /api/extract with USE_PLANNER on against real Anthropic + Apify.
They make network calls and spend tokens, so they carry @pytest.mark.integration
and are deselected by default. Run with:

    .venv\\Scripts\\python.exe -m pytest tests/integration/test_planner_e2e.py -v -m integration

Required env: ANTHROPIC_API_KEY, APIFY_TOKEN (USE_PLANNER is set per-test).
The no-network mirror of cases 1-2 lives in tests/test_planner_e2e_mocked.py.
"""

import json
import os

import pytest
from fastapi.testclient import TestClient

from api.main import app
from pluck.registry.loader import candidates_for_url, find_entry

NATGEO_URL = "https://www.instagram.com/natgeo/"
OUT_OF_REGISTRY_URL = "https://news.ycombinator.com/"

POST_ACTOR = "apify/instagram-post-scraper"
PROFILE_ACTOR = "apify/instagram-profile-scraper"

_HAVE_ANTHROPIC = bool(os.environ.get("ANTHROPIC_API_KEY"))
_HAVE_APIFY = bool(os.environ.get("APIFY_TOKEN"))

requires_apify = pytest.mark.skipif(
    not (_HAVE_ANTHROPIC and _HAVE_APIFY),
    reason="needs ANTHROPIC_API_KEY and APIFY_TOKEN",
)
requires_anthropic = pytest.mark.skipif(
    not _HAVE_ANTHROPIC, reason="needs ANTHROPIC_API_KEY",
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _default_columns(actor_id: str) -> list[str]:
    entry = find_entry(actor_id, candidates_for_url(NATGEO_URL))
    assert entry is not None, f"{actor_id} missing from registry"
    return list(entry["default_columns"])


def _parse_sse(text: str) -> list[dict]:
    events = []
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def planner_on(monkeypatch):
    monkeypatch.setenv("USE_PLANNER", "true")


def _token(client) -> str:
    resp = client.post("/api/auth", json={"password": "pluck"})
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


# ── case 1: posts intent → post-scraper, >= 12 rows, post default_columns ─────

@pytest.mark.integration
@requires_apify
def test_natgeo_posts_intent(client, planner_on):
    tok = _token(client)
    resp = client.get("/api/extract", params={
        "url": NATGEO_URL,
        "prompt": "scrape the postings",
        "max_items": 100,
        "token": tok,
    })
    assert resp.status_code == 200, resp.text
    events = _parse_sse(resp.text)

    planning = next(
        e for e in events if e["step"] == "planning" and e["status"] == "done"
    )
    assert planning["actor_id"] == POST_ACTOR

    done = next(e for e in events if e["step"] == "done")
    assert done["total_rows"] >= 12, f"expected >=12 posts, got {done['total_rows']}"

    post_cols = set(_default_columns(POST_ACTOR))
    for item in done["items"]:
        assert set(item.keys()) <= post_cols, (
            f"unexpected columns {set(item.keys()) - post_cols}"
        )


# ── case 2: profile intent → profile-scraper, exactly 1 row ───────────────────

@pytest.mark.integration
@requires_apify
def test_natgeo_profile_intent(client, planner_on):
    tok = _token(client)
    resp = client.get("/api/extract", params={
        "url": NATGEO_URL,
        "prompt": "get the bio and follower count",
        "max_items": 100,
        "token": tok,
    })
    assert resp.status_code == 200, resp.text
    events = _parse_sse(resp.text)

    planning = next(
        e for e in events if e["step"] == "planning" and e["status"] == "done"
    )
    assert planning["actor_id"] == PROFILE_ACTOR

    done = next(e for e in events if e["step"] == "done")
    assert done["total_rows"] == 1, f"expected exactly 1 profile, got {done['total_rows']}"


# ── case 3: out-of-registry URL → no planner, falls through to groups 1-6 ──────

@pytest.mark.integration
@requires_anthropic
def test_out_of_registry_fallthrough(client, planner_on):
    tok = _token(client)
    resp = client.get("/api/extract", params={
        "url": OUT_OF_REGISTRY_URL,
        "prompt": "list the stories",
        "token": tok,
    })
    assert resp.status_code == 200, resp.text
    events = _parse_sse(resp.text)

    # Flag is on, but the host is not in the registry: the planner never runs.
    assert not any(e["step"] == "planning" for e in events)

    # The legacy path still classifies, fetches, extracts and emits a done event.
    assert any(e["step"] == "classifying" and e["status"] == "done" for e in events)
    done = next(e for e in events if e["step"] == "done")
    assert done["status"] == "done"
    assert "items" in done

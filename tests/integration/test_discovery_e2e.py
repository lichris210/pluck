"""Live end-to-end test for Phase 3 Store-API discovery.

Exercises /api/extract with USE_PLANNER on against a NON-registry host, so the
discovery fall-through runs for real: Apify Store search → filter → Haiku ranking →
maxItems=1 schema capture → tier-2 cache write → planned scrape.

Network + tokens + a small Apify spend (~$0.003 schema probe plus the scrape), so it
carries @pytest.mark.integration and is deselected by default. Run with:

    .venv\\Scripts\\python.exe -m pytest tests/integration/test_discovery_e2e.py -v -m integration

Required env: ANTHROPIC_API_KEY, APIFY_TOKEN (USE_PLANNER is set per-test). A temp
SchemaCacheStore is patched in so the real pluck_cache.db is left untouched.
"""

import json
import os
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient

from api.main import app
from pluck.storage.cache_store import SchemaCacheStore

# A host that is NOT in apify_actors.json but has good Apify Store coverage.
DISCOVERY_URL = "https://www.tiktok.com/@nasa"

_HAVE_ANTHROPIC = bool(os.environ.get("ANTHROPIC_API_KEY"))
_HAVE_APIFY = bool(os.environ.get("APIFY_TOKEN"))

requires_apify = pytest.mark.skipif(
    not (_HAVE_ANTHROPIC and _HAVE_APIFY),
    reason="needs ANTHROPIC_API_KEY and APIFY_TOKEN",
)


def _host(url: str) -> str:
    h = (urlparse(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def _parse_sse(text: str) -> list[dict]:
    events = []
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


@pytest.fixture
def temp_store(tmp_path):
    s = SchemaCacheStore(db_path=str(tmp_path / "discovery_e2e.db"), default_ttl_seconds=0)
    yield s
    s.close()


@pytest.fixture
def client(temp_store, monkeypatch):
    monkeypatch.setenv("USE_PLANNER", "true")
    monkeypatch.setattr("api.routes._schema_cache", temp_store)
    return TestClient(app)


def _token(client) -> str:
    resp = client.post("/api/auth", json={"password": "pluck"})
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


@pytest.mark.integration
@requires_apify
def test_unknown_host_is_discovered_and_cached(client, temp_store):
    tok = _token(client)
    resp = client.get("/api/extract", params={
        "url": DISCOVERY_URL,
        "prompt": "list recent videos",
        "max_items": 5,
        "token": tok,
    })
    assert resp.status_code == 200, resp.text
    events = _parse_sse(resp.text)

    # Discovery resolved to a real actor and surfaced it on the stream.
    discovery = [
        e for e in events
        if e.get("step") == "discovery" and e.get("source") == "discovered"
    ]
    assert discovery, "no discovery event — Store returned no usable actor"
    assert discovery[0]["actor_id"]
    assert discovery[0]["confidence"] == "low"  # first sighting, 0 prior runs

    # A done event with items was produced.
    done = next(e for e in events if e.get("step") == "done")
    assert "items" in done

    # The discovered actor was persisted to tier 2 for this host.
    cached = temp_store.get_discovered(_host(DISCOVERY_URL))
    assert len(cached) >= 1
    assert cached[0]["successful_runs"] >= 1

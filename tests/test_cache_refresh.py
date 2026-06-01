"""Tests for the refresh=true query parameter on /api/extract.

Pattern mirrors test_results_cache_wiring.py: mocked pipeline, temp-DB
store injected via patch("api.routes._schema_cache", store).
"""

import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from api.main import app
from pluck.models import (
    ExtractionResult,
    ExtractionSchema,
    FetchResult,
    FieldDef,
    SiteGroup,
    SiteProfile,
)
from pluck.storage.cache_store import SchemaCacheStore

# ── shared helpers ────────────────────────────────────────────────────────────

URL = "https://example.com/jobs/123"


def _site_profile(url=URL):
    return SiteProfile(
        url=url, final_url=url, status_code=200, headers={},
        content_type="text/html",
        html="<html><body>Jobs</body></html>",
        site_group=SiteGroup.STATIC_HTML,
        classification_reasons=["static"],
        response_time_ms=50.0,
    )


def _fetch_result(url=URL):
    return FetchResult(
        url=url,
        html="<html><body>Jobs</body></html>",
        fetcher_used="scrapling_static",
        fetch_time_ms=100.0,
        success=True,
    )


def _extraction_result(item_name: str = "Widget"):
    schema = ExtractionSchema(
        fields=[FieldDef("name", "string", "Name")],
        description="Jobs",
    )
    return ExtractionResult(
        items=[{"name": item_name}],
        schema_used=schema,
        source_url=URL,
        total_input_tokens=300,
        total_output_tokens=60,
        extraction_time_ms=400.0,
        model_used="claude-haiku-4-5",
    )


def _stale_done_payload(item_name: str = "StaleWidget") -> dict:
    """A minimal done-payload dict as stored by put_cached_result."""
    return {
        "step": "done",
        "status": "done",
        "items": [{"name": item_name}],
        "total_rows": 1,
        "total_columns": 1,
        "cost_usd": 0.0,
        "rows_before_curation": 1,
        "dropped_columns": [],
        "extraction_time_ms": 0.0,
        "total_time_ms": 5.0,
        "model_used": "claude-haiku-4-5",
    }


def _parse_sse(text: str) -> list[dict]:
    events = []
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def temp_store(tmp_path):
    s = SchemaCacheStore(db_path=str(tmp_path / "refresh_test.db"))
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


# ── test 1: refresh=true bypasses stale cache and runs full pipeline ──────────

def test_refresh_bypasses_cache_and_runs_pipeline(client, temp_store):
    tok = _token(client)

    # Pre-populate with stale data
    temp_store.put_cached_result(URL, json.dumps(_stale_done_payload("StaleWidget")))

    with (
        patch("api.routes.ingest", new_callable=AsyncMock) as mock_ingest,
        patch("api.routes.route_fetch", new_callable=AsyncMock) as mock_fetch,
        patch("api.routes.extract", new_callable=AsyncMock) as mock_extract,
    ):
        mock_ingest.return_value = _site_profile()
        mock_fetch.return_value = _fetch_result()
        mock_extract.return_value = _extraction_result("FreshWidget")

        resp = client.get("/api/extract", params={"url": URL, "token": tok, "refresh": "true"})

    assert resp.status_code == 200
    events = _parse_sse(resp.text)

    # Pipeline was invoked
    mock_ingest.assert_called_once()
    mock_fetch.assert_called_once()
    mock_extract.assert_called_once()

    # Must NOT have returned the stale cached payload
    assert not any(e.get("step") == "cache" for e in events)

    # Must have a live done event with fresh data
    done = next(e for e in events if e["step"] == "done")
    assert done.get("from_cache") is not True
    assert done["items"] == [{"name": "FreshWidget"}]


# ── test 2: refresh overwrites cache so next normal request gets fresh data ───

def test_refresh_overwrites_cache_for_subsequent_requests(client, temp_store):
    tok = _token(client)

    # Pre-populate with stale data
    temp_store.put_cached_result(URL, json.dumps(_stale_done_payload("StaleWidget")))

    # Refresh request writes fresh data into the cache
    with (
        patch("api.routes.ingest", new_callable=AsyncMock) as mock_ingest,
        patch("api.routes.route_fetch", new_callable=AsyncMock) as mock_fetch,
        patch("api.routes.extract", new_callable=AsyncMock) as mock_extract,
    ):
        mock_ingest.return_value = _site_profile()
        mock_fetch.return_value = _fetch_result()
        mock_extract.return_value = _extraction_result("FreshWidget")
        client.get("/api/extract", params={"url": URL, "token": tok, "refresh": "true"})

    # Follow-up request WITHOUT refresh — must serve the new cached value
    with (
        patch("api.routes.ingest", new_callable=AsyncMock) as mock_ingest2,
        patch("api.routes.route_fetch", new_callable=AsyncMock) as mock_fetch2,
        patch("api.routes.extract", new_callable=AsyncMock) as mock_extract2,
    ):
        resp2 = client.get("/api/extract", params={"url": URL, "token": tok})

    assert resp2.status_code == 200
    events = _parse_sse(resp2.text)

    # Pipeline was NOT re-invoked
    mock_ingest2.assert_not_called()
    mock_fetch2.assert_not_called()
    mock_extract2.assert_not_called()

    # Served from cache with fresh, not stale, value
    done = next(e for e in events if e["step"] == "done")
    assert done["from_cache"] is True
    assert done["items"] == [{"name": "FreshWidget"}]
    assert done["items"] != [{"name": "StaleWidget"}]


# ── test 3: refresh with validation failure does NOT overwrite the cache ──────

def test_refresh_validation_failure_leaves_stale_cache_intact(client, temp_store):
    tok = _token(client)

    stale_payload = _stale_done_payload("StaleWidget")
    temp_store.put_cached_result(URL, json.dumps(stale_payload))

    bad_result = _extraction_result("DoesNotMatter")
    bad_result.error = "Validation failed after re-inference: zero rows extracted"

    with (
        patch("api.routes.ingest", new_callable=AsyncMock) as mock_ingest,
        patch("api.routes.route_fetch", new_callable=AsyncMock) as mock_fetch,
        patch("api.routes.extract", new_callable=AsyncMock) as mock_extract,
    ):
        mock_ingest.return_value = _site_profile()
        mock_fetch.return_value = _fetch_result()
        mock_extract.return_value = bad_result

        resp = client.get("/api/extract", params={"url": URL, "token": tok, "refresh": "true"})

    assert resp.status_code == 200
    events = _parse_sse(resp.text)

    # Stream must have ended with an extraction error
    assert any(e.get("status") == "error" and e["step"] == "extracting" for e in events)

    # Stale cache row must be unchanged
    cached_raw = temp_store.get_cached_result(URL)
    assert cached_raw is not None
    cached = json.loads(cached_raw)
    assert cached["items"] == [{"name": "StaleWidget"}]


# ── test 4: refresh=false / omitted still serves from cache (regression) ──────

def test_no_refresh_still_serves_from_cache(client, temp_store):
    tok = _token(client)

    temp_store.put_cached_result(URL, json.dumps(_stale_done_payload("CachedWidget")))

    with (
        patch("api.routes.ingest", new_callable=AsyncMock) as mock_ingest,
        patch("api.routes.route_fetch", new_callable=AsyncMock) as mock_fetch,
        patch("api.routes.extract", new_callable=AsyncMock) as mock_extract,
    ):
        # Explicit refresh=false
        resp = client.get("/api/extract", params={"url": URL, "token": tok, "refresh": "false"})

    assert resp.status_code == 200
    events = _parse_sse(resp.text)

    # Pipeline must NOT have been called
    mock_ingest.assert_not_called()
    mock_fetch.assert_not_called()
    mock_extract.assert_not_called()

    # Cache hit event present
    assert any(e.get("step") == "cache" and e.get("status") == "hit" for e in events)

    # Done payload served from cache
    done = next(e for e in events if e["step"] == "done")
    assert done["from_cache"] is True
    assert done["items"] == [{"name": "CachedWidget"}]

"""Tests for results-cache wiring in the extract_endpoint request handler.

The full pipeline (ingest / route_fetch / extract) is mocked; a temp-DB
SchemaCacheStore is injected by patching api.routes._schema_cache so the
real pluck_cache.db is never touched.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

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


# ── shared helpers (mirror test_api.py conventions) ──────────────────────────

def _site_profile(url="https://example.com/products"):
    return SiteProfile(
        url=url, final_url=url, status_code=200, headers={},
        content_type="text/html",
        html="<html><body>Products</body></html>",
        site_group=SiteGroup.STATIC_HTML,
        classification_reasons=["static"],
        response_time_ms=100.0,
    )


def _fetch_result(url="https://example.com/products"):
    return FetchResult(
        url=url,
        html="<html><body>Products</body></html>",
        fetcher_used="scrapling_static",
        fetch_time_ms=200.0,
        success=True,
    )


def _extraction_result():
    schema = ExtractionSchema(
        fields=[FieldDef("name", "string", "Product name")],
        description="Products",
    )
    return ExtractionResult(
        items=[{"name": "Widget", "price": 9.99}],
        schema_used=schema,
        source_url="https://example.com/products",
        total_input_tokens=500,
        total_output_tokens=100,
        extraction_time_ms=800.0,
        model_used="claude-haiku-4-5",
    )


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
    s = SchemaCacheStore(db_path=str(tmp_path / "wiring.db"))
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


URL = "https://example.com/products"


# ── test 1: cache miss runs the full pipeline and writes to cache ─────────────

def test_cache_miss_runs_pipeline_and_populates_cache(client, temp_store):
    tok = _token(client)

    with (
        patch("api.routes.ingest", new_callable=AsyncMock) as mock_ingest,
        patch("api.routes.route_fetch", new_callable=AsyncMock) as mock_fetch,
        patch("api.routes.extract", new_callable=AsyncMock) as mock_extract,
    ):
        mock_ingest.return_value = _site_profile()
        mock_fetch.return_value = _fetch_result()
        mock_extract.return_value = _extraction_result()

        resp = client.get("/api/extract", params={"url": URL, "token": tok})

    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    assert any(e["step"] == "done" for e in events)

    # Pipeline was invoked
    mock_ingest.assert_called_once()
    mock_fetch.assert_called_once()
    mock_extract.assert_called_once()

    # Cache should now be populated
    cached = temp_store.get_cached_result(URL)
    assert cached is not None
    payload = json.loads(cached)
    assert payload["step"] == "done"
    assert payload["total_rows"] == 1


# ── test 2: second request serves from cache, pipeline not invoked ────────────

def test_second_request_serves_from_cache_and_skips_pipeline(client, temp_store):
    tok = _token(client)

    # First request — populate the cache
    with (
        patch("api.routes.ingest", new_callable=AsyncMock) as m_ingest,
        patch("api.routes.route_fetch", new_callable=AsyncMock) as m_fetch,
        patch("api.routes.extract", new_callable=AsyncMock) as m_extract,
    ):
        m_ingest.return_value = _site_profile()
        m_fetch.return_value = _fetch_result()
        m_extract.return_value = _extraction_result()
        client.get("/api/extract", params={"url": URL, "token": tok})

    # Second request — cache hit: pipeline must NOT be called
    with (
        patch("api.routes.ingest", new_callable=AsyncMock) as mock_ingest2,
        patch("api.routes.route_fetch", new_callable=AsyncMock) as mock_fetch2,
        patch("api.routes.extract", new_callable=AsyncMock) as mock_extract2,
    ):
        resp2 = client.get("/api/extract", params={"url": URL, "token": tok})

    assert resp2.status_code == 200

    mock_ingest2.assert_not_called()
    mock_fetch2.assert_not_called()
    mock_extract2.assert_not_called()

    events = _parse_sse(resp2.text)
    steps = [e["step"] for e in events]

    # Must include the cache-hit signal event
    assert "cache" in steps
    cache_ev = next(e for e in events if e["step"] == "cache")
    assert cache_ev["status"] == "hit"

    # Must include the done payload in the same shape as a live response
    assert "done" in steps
    done_ev = next(e for e in events if e["step"] == "done")
    assert done_ev["status"] == "done"
    assert done_ev["from_cache"] is True
    assert done_ev["total_rows"] == 1


# ── test 3: failed extraction does NOT write to results cache ─────────────────

def test_failed_extraction_does_not_populate_results_cache(client, temp_store):
    tok = _token(client)

    bad_result = _extraction_result()
    bad_result.error = "Validation failed after re-inference: zero rows extracted"

    with (
        patch("api.routes.ingest", new_callable=AsyncMock) as mock_ingest,
        patch("api.routes.route_fetch", new_callable=AsyncMock) as mock_fetch,
        patch("api.routes.extract", new_callable=AsyncMock) as mock_extract,
    ):
        mock_ingest.return_value = _site_profile()
        mock_fetch.return_value = _fetch_result()
        mock_extract.return_value = bad_result

        resp = client.get("/api/extract", params={"url": URL, "token": tok})

    assert resp.status_code == 200
    events = _parse_sse(resp.text)

    # Stream should have ended with an extraction error, not a done event
    assert any(e.get("status") == "error" and e["step"] == "extracting" for e in events)
    assert not any(e["step"] == "done" for e in events)

    # Results cache must be empty — nothing was stored
    assert temp_store.get_cached_result(URL) is None

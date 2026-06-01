"""API layer tests — all pipeline calls are mocked; no real network traffic."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.auth import verify_token
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


# ── Helpers ──────────────────────────────────────────────────────────────────

def _site_profile(url="https://example.com", error=None):
    return SiteProfile(
        url=url,
        final_url=url,
        status_code=200,
        headers={},
        content_type="text/html",
        html="<html><body>Test</body></html>",
        site_group=SiteGroup.STATIC_HTML,
        classification_reasons=["static page"],
        response_time_ms=100.0,
        error=error,
    )


def _fetch_result(url="https://example.com", success=True, structured=False):
    return FetchResult(
        url=url,
        html="<html><body>Products</body></html>",
        fetcher_used="scrapling_static",
        fetch_time_ms=200.0,
        success=success,
        structured_data=[{"name": "item1", "price": 10.0}] if structured else None,
        error=None if success else "Fetch error",
    )


def _extraction_result():
    schema = ExtractionSchema(
        fields=[FieldDef("name", "string", "Product name")],
        description="Products",
    )
    return ExtractionResult(
        items=[{"name": "Widget", "price": 9.99}],
        schema_used=schema,
        source_url="https://example.com",
        total_input_tokens=1000,
        total_output_tokens=200,
        extraction_time_ms=1500.0,
        model_used="claude-haiku-4-5",
    )


def _parse_sse(text: str) -> list[dict]:
    events = []
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


# ── Fixtures ─────────────────────────────────────────────────────────────────



@pytest.fixture
def client(tmp_path):
    store = SchemaCacheStore(db_path=str(tmp_path / "api_test.db"))
    with patch("api.routes._schema_cache", store):
        yield TestClient(app)
    store.close()


def _get_token(client) -> str:
    resp = client.post("/api/auth", json={"password": "pluck"})
    assert resp.status_code == 200
    return resp.json()["token"]


# ── Auth tests ────────────────────────────────────────────────────────────────

def test_auth_correct_password_returns_token(client):
    resp = client.post("/api/auth", json={"password": "pluck"})
    assert resp.status_code == 200
    data = resp.json()
    assert "token" in data
    assert len(data["token"]) == 64  # 32 bytes → 64 hex chars


def test_auth_wrong_password_returns_401(client):
    resp = client.post("/api/auth", json={"password": "wrong"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid password"


def test_auth_token_is_deterministic(client):
    r1 = client.post("/api/auth", json={"password": "pluck"}).json()["token"]
    r2 = client.post("/api/auth", json={"password": "pluck"}).json()["token"]
    assert r1 == r2
    assert verify_token(r1)


# ── Health test ───────────────────────────────────────────────────────────────

def test_health_returns_ok(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "version": "1.0.0"}


# ── Classify tests ────────────────────────────────────────────────────────────

def test_classify_without_auth_returns_401(client):
    resp = client.post("/api/classify", json={"url": "https://example.com"})
    assert resp.status_code == 401


def test_classify_with_auth_returns_result(client):
    token = _get_token(client)
    with patch("api.routes.ingest", new_callable=AsyncMock) as mock_ingest:
        mock_ingest.return_value = _site_profile()
        resp = client.post(
            "/api/classify",
            json={"url": "https://example.com"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["url"] == "https://example.com"
    assert data["site_group"] == "STATIC_HTML"
    assert data["site_group_number"] == 1
    assert data["classification_reasons"] == ["static page"]
    assert data["error"] is None


def test_classify_invalid_url_returns_200_with_error(client):
    token = _get_token(client)
    with patch("api.routes.ingest", new_callable=AsyncMock) as mock_ingest:
        mock_ingest.return_value = _site_profile(url="not-a-url", error="Connection error: invalid host")
        resp = client.post(
            "/api/classify",
            json={"url": "not-a-url"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["error"] is not None
    assert "Connection error" in data["error"]


# ── Extract tests ─────────────────────────────────────────────────────────────

def test_extract_without_auth_returns_401(client):
    resp = client.get("/api/extract", params={"url": "https://example.com"})
    assert resp.status_code == 401


def test_extract_sse_events_in_order(client):
    token = _get_token(client)
    with (
        patch("api.routes.ingest", new_callable=AsyncMock) as mock_ingest,
        patch("api.routes.route_fetch", new_callable=AsyncMock) as mock_fetch,
        patch("api.routes.extract", new_callable=AsyncMock) as mock_extract,
    ):
        mock_ingest.return_value = _site_profile()
        mock_fetch.return_value = _fetch_result()
        mock_extract.return_value = _extraction_result()

        resp = client.get(
            "/api/extract",
            params={"url": "https://example.com", "token": token},
        )

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    events = _parse_sse(resp.text)
    step_order = [(e["step"], e["status"]) for e in events]

    assert step_order.index(("classifying", "active")) < step_order.index(("classifying", "done"))
    assert step_order.index(("classifying", "done")) < step_order.index(("fetching", "active"))
    assert step_order.index(("fetching", "active")) < step_order.index(("fetching", "done"))
    assert step_order.index(("fetching", "done")) < step_order.index(("extracting", "active"))
    assert step_order.index(("extracting", "active")) < step_order.index(("extracting", "done"))
    assert step_order.index(("extracting", "done")) < step_order.index(("done", "done"))


def test_extract_done_event_has_items(client):
    token = _get_token(client)
    with (
        patch("api.routes.ingest", new_callable=AsyncMock) as mock_ingest,
        patch("api.routes.route_fetch", new_callable=AsyncMock) as mock_fetch,
        patch("api.routes.extract", new_callable=AsyncMock) as mock_extract,
    ):
        mock_ingest.return_value = _site_profile()
        mock_fetch.return_value = _fetch_result()
        mock_extract.return_value = _extraction_result()

        resp = client.get(
            "/api/extract",
            params={"url": "https://example.com", "token": token},
        )

    events = _parse_sse(resp.text)
    done = next(e for e in events if e["step"] == "done")
    assert done["total_rows"] == 1
    assert done["model_used"] == "claude-haiku-4-5"
    assert isinstance(done["cost_usd"], float)
    assert isinstance(done["items"], list)


def test_extract_schema_passed_to_extractor(client):
    token = _get_token(client)
    schema_dict = {
        "description": "Products",
        "fields": [{"name": "title", "field_type": "string", "description": "Product title"}],
    }
    with (
        patch("api.routes.ingest", new_callable=AsyncMock) as mock_ingest,
        patch("api.routes.route_fetch", new_callable=AsyncMock) as mock_fetch,
        patch("api.routes.extract", new_callable=AsyncMock) as mock_extract,
    ):
        mock_ingest.return_value = _site_profile()
        mock_fetch.return_value = _fetch_result()
        mock_extract.return_value = _extraction_result()

        client.get(
            "/api/extract",
            params={
                "url": "https://example.com",
                "token": token,
                "schema": json.dumps(schema_dict),
            },
        )

    passed_schema = mock_extract.call_args[0][1]
    assert passed_schema is not None
    assert passed_schema.fields[0].name == "title"


def test_extract_skip_extraction_when_structured_data(client):
    """Apify path: structured_data present → no extracting step."""
    token = _get_token(client)
    with (
        patch("api.routes.ingest", new_callable=AsyncMock) as mock_ingest,
        patch("api.routes.route_fetch", new_callable=AsyncMock) as mock_fetch,
    ):
        mock_ingest.return_value = _site_profile()
        mock_fetch.return_value = _fetch_result(structured=True)

        resp = client.get(
            "/api/extract",
            params={"url": "https://example.com", "token": token},
        )

    events = _parse_sse(resp.text)
    steps = [e["step"] for e in events]
    assert "extracting" not in steps
    done = next(e for e in events if e["step"] == "done")
    assert done["total_rows"] == 1
    assert done["model_used"] == "none"
    assert done["cost_usd"] == 0.0


def test_extract_classify_error_closes_stream(client):
    token = _get_token(client)
    with patch("api.routes.ingest", new_callable=AsyncMock) as mock_ingest:
        mock_ingest.return_value = _site_profile(error="Connection refused")

        resp = client.get(
            "/api/extract",
            params={"url": "https://example.com", "token": token},
        )

    events = _parse_sse(resp.text)
    error_events = [e for e in events if e.get("status") == "error"]
    assert len(error_events) == 1
    assert error_events[0]["step"] == "classifying"
    assert "Connection refused" in error_events[0]["error"]


def test_extract_fetch_error_closes_stream(client):
    token = _get_token(client)
    with (
        patch("api.routes.ingest", new_callable=AsyncMock) as mock_ingest,
        patch("api.routes.route_fetch", new_callable=AsyncMock) as mock_fetch,
    ):
        mock_ingest.return_value = _site_profile()
        mock_fetch.return_value = _fetch_result(success=False)

        resp = client.get(
            "/api/extract",
            params={"url": "https://example.com", "token": token},
        )

    events = _parse_sse(resp.text)
    error_events = [e for e in events if e.get("status") == "error"]
    assert len(error_events) == 1
    assert error_events[0]["step"] == "fetching"


def test_token_as_query_param_authenticates(client):
    """EventSource cannot set headers — token must work as ?token= query param."""
    token = _get_token(client)
    with patch("api.routes.ingest", new_callable=AsyncMock) as mock_ingest:
        mock_ingest.return_value = _site_profile(error="stopped early")

        resp = client.get(
            "/api/extract",
            params={"url": "https://example.com", "token": token},
        )
    # Would be 401 if query-param auth didn't work
    assert resp.status_code == 200


def _mock_anthropic_returning_columns(columns, input_tokens=120, output_tokens=15):
    """A MagicMock Anthropic client whose messages.create returns a
    column-selection JSON response with usage, for the prompt path."""
    block = MagicMock()
    block.type = "text"
    block.text = json.dumps({"columns": columns})
    resp = MagicMock()
    resp.content = [block]
    resp.usage = MagicMock(input_tokens=input_tokens, output_tokens=output_tokens)

    mock_client = MagicMock()
    mock_client.messages.create.return_value = resp
    return mock_client


def test_extract_with_prompt_projects_to_requested_columns(client):
    token = _get_token(client)
    mock_client = _mock_anthropic_returning_columns(["name"])
    with (
        patch("api.routes.ingest", new_callable=AsyncMock) as mock_ingest,
        patch("api.routes.route_fetch", new_callable=AsyncMock) as mock_fetch,
        patch("api.routes.extract", new_callable=AsyncMock) as mock_extract,
        patch("api.routes.anthropic.Anthropic", return_value=mock_client),
    ):
        mock_ingest.return_value = _site_profile()
        mock_fetch.return_value = _fetch_result()
        mock_extract.return_value = _extraction_result()  # items: name + price

        resp = client.get(
            "/api/extract",
            params={
                "url": "https://example.com",
                "token": token,
                "prompt": "just the product names",
            },
        )

    events = _parse_sse(resp.text)
    done = next(e for e in events if e["step"] == "done")
    # Projected to exactly the requested column.
    assert done["items"] == [{"name": "Widget"}]
    assert done["total_columns"] == 1
    # One Haiku column-selection call was made.
    assert mock_client.messages.create.call_count == 1
    # Its tokens were billed on top of the extraction cost (0.0016 for 1000/200).
    assert done["cost_usd"] == pytest.approx(0.001756)


def test_extract_without_prompt_keeps_all_columns(client):
    token = _get_token(client)
    with (
        patch("api.routes.ingest", new_callable=AsyncMock) as mock_ingest,
        patch("api.routes.route_fetch", new_callable=AsyncMock) as mock_fetch,
        patch("api.routes.extract", new_callable=AsyncMock) as mock_extract,
        patch("api.routes.derive_columns") as mock_derive,
    ):
        mock_ingest.return_value = _site_profile()
        mock_fetch.return_value = _fetch_result()
        mock_extract.return_value = _extraction_result()

        resp = client.get(
            "/api/extract",
            params={"url": "https://example.com", "token": token},
        )

    events = _parse_sse(resp.text)
    done = next(e for e in events if e["step"] == "done")
    # Unchanged: all columns retained, no column-selection call.
    assert done["items"] == [{"name": "Widget", "price": 9.99}]
    assert done["total_columns"] == 2
    assert done["cost_usd"] == pytest.approx(0.0016)
    mock_derive.assert_not_called()


def test_extract_done_event_includes_total_time_ms(client):
    token = _get_token(client)
    with (
        patch("api.routes.ingest", new_callable=AsyncMock) as mock_ingest,
        patch("api.routes.route_fetch", new_callable=AsyncMock) as mock_fetch,
        patch("api.routes.extract", new_callable=AsyncMock) as mock_extract,
    ):
        mock_ingest.return_value = _site_profile()
        mock_fetch.return_value = _fetch_result()
        mock_extract.return_value = _extraction_result()

        resp = client.get(
            "/api/extract",
            params={"url": "https://example.com", "token": token},
        )

    events = _parse_sse(resp.text)
    done = next(e for e in events if e["step"] == "done")
    assert isinstance(done["total_time_ms"], (int, float))
    assert done["total_time_ms"] >= 0


def test_extract_force_apify_passes_use_apify_to_route_fetch(client):
    token = _get_token(client)
    with (
        patch("api.routes.ingest", new_callable=AsyncMock) as mock_ingest,
        patch("api.routes.route_fetch", new_callable=AsyncMock) as mock_fetch,
        patch("api.routes.extract", new_callable=AsyncMock) as mock_extract,
    ):
        mock_ingest.return_value = _site_profile()
        mock_fetch.return_value = _fetch_result()
        mock_extract.return_value = _extraction_result()

        client.get(
            "/api/extract",
            params={"url": "https://example.com", "token": token, "force_apify": "true"},
        )

    assert mock_fetch.call_args.kwargs["use_apify"] is True


def test_extract_force_apify_defaults_false(client):
    token = _get_token(client)
    with (
        patch("api.routes.ingest", new_callable=AsyncMock) as mock_ingest,
        patch("api.routes.route_fetch", new_callable=AsyncMock) as mock_fetch,
        patch("api.routes.extract", new_callable=AsyncMock) as mock_extract,
    ):
        mock_ingest.return_value = _site_profile()
        mock_fetch.return_value = _fetch_result()
        mock_extract.return_value = _extraction_result()

        client.get(
            "/api/extract",
            params={"url": "https://example.com", "token": token},
        )

    assert mock_fetch.call_args.kwargs["use_apify"] is False


def test_extract_fetching_event_includes_fetcher_label(client):
    token = _get_token(client)
    with (
        patch("api.routes.ingest", new_callable=AsyncMock) as mock_ingest,
        patch("api.routes.route_fetch", new_callable=AsyncMock) as mock_fetch,
        patch("api.routes.extract", new_callable=AsyncMock) as mock_extract,
    ):
        mock_ingest.return_value = _site_profile()
        mock_fetch.return_value = _fetch_result()
        mock_extract.return_value = _extraction_result()

        resp = client.get(
            "/api/extract",
            params={"url": "https://example.com", "token": token},
        )

    events = _parse_sse(resp.text)
    fetching_active = next(e for e in events if e["step"] == "fetching" and e["status"] == "active")
    assert fetching_active["fetcher"] == "scrapling_static"

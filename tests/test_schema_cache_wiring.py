"""Tests for schema cache wiring inside extract().

infer_schema and the Anthropic client are mocked; a temp-DB store is
injected via fixture so the real pluck_cache.db is never touched.
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from pluck.extraction.extractor import extract
from pluck.models import ExtractionSchema, FieldDef, FetchResult
from pluck.storage.cache_store import SchemaCacheStore
from pluck.url_keys import schema_key


@pytest.fixture
def store(tmp_path):
    db = tmp_path / "wiring_test.db"
    s = SchemaCacheStore(db_path=str(db))
    yield s
    s.close()


def _fake_schema() -> ExtractionSchema:
    return ExtractionSchema(
        description="Test schema",
        fields=[FieldDef(name="title", field_type="string", description="Title", required=True)],
    )


def _make_fetch_result(url: str) -> FetchResult:
    return FetchResult(
        url=url,
        html="<html><body><h1>Job Listing</h1></body></html>",
        fetcher_used="test",
        fetch_time_ms=0.0,
        success=True,
    )


def _make_client() -> MagicMock:
    """Minimal Anthropic client mock returning a parseable extraction response."""
    block = MagicMock()
    block.type = "text"
    block.text = '[{"title": "Software Engineer"}]'

    usage = MagicMock()
    usage.input_tokens = 100
    usage.output_tokens = 50

    response = MagicMock()
    response.content = [block]
    response.usage = usage

    client = MagicMock()
    client.messages.create.return_value = response
    return client


# ── first call: inference runs, cache is written ──────────────────────────────

async def test_first_call_invokes_infer_schema(store):
    with patch("pluck.extraction.extractor.infer_schema", new_callable=AsyncMock) as mock_infer:
        mock_infer.return_value = (_fake_schema(), 10, 5)
        result = await extract(
            _make_fetch_result("https://linkedin.com/jobs/11111"),
            None,
            _make_client(),
            cache_store=store,
        )

    mock_infer.assert_called_once()
    assert result.schema_cache_hit is False


async def test_first_call_writes_cache(store):
    with patch("pluck.extraction.extractor.infer_schema", new_callable=AsyncMock) as mock_infer:
        mock_infer.return_value = (_fake_schema(), 10, 5)
        await extract(
            _make_fetch_result("https://linkedin.com/jobs/11111"),
            None,
            _make_client(),
            cache_store=store,
        )

    cached = store.get_schema("linkedin.com/jobs/*")
    assert cached is not None
    parsed = json.loads(cached)
    assert parsed["fields"][0]["name"] == "title"


# ── second call same pattern: inference skipped, cache hit ────────────────────

async def test_second_call_same_pattern_skips_infer_schema(store):
    # Prime the cache with first URL
    with patch("pluck.extraction.extractor.infer_schema", new_callable=AsyncMock) as mock_infer:
        mock_infer.return_value = (_fake_schema(), 10, 5)
        await extract(
            _make_fetch_result("https://linkedin.com/jobs/11111"),
            None,
            _make_client(),
            cache_store=store,
        )

    # Second call on a different job ID — same schema_key pattern
    with patch("pluck.extraction.extractor.infer_schema", new_callable=AsyncMock) as mock_infer2:
        mock_infer2.return_value = (_fake_schema(), 10, 5)
        result = await extract(
            _make_fetch_result("https://linkedin.com/jobs/99999"),
            None,
            _make_client(),
            cache_store=store,
        )

    mock_infer2.assert_not_called()
    assert result.schema_cache_hit is True


async def test_cache_hit_event_emitted_on_second_call(store):
    with patch("pluck.extraction.extractor.infer_schema", new_callable=AsyncMock) as mock_infer:
        mock_infer.return_value = (_fake_schema(), 10, 5)
        first = await extract(
            _make_fetch_result("https://linkedin.com/jobs/11111"),
            None,
            _make_client(),
            cache_store=store,
        )

    with patch("pluck.extraction.extractor.infer_schema", new_callable=AsyncMock) as mock_infer2:
        mock_infer2.return_value = (_fake_schema(), 10, 5)
        second = await extract(
            _make_fetch_result("https://linkedin.com/jobs/99999"),
            None,
            _make_client(),
            cache_store=store,
        )

    assert first.schema_cache_hit is False
    assert second.schema_cache_hit is True


# ── explicit schema passed: cache is never consulted ─────────────────────────

async def test_explicit_schema_bypasses_cache(store):
    """When caller provides a schema, the cache path is not entered at all."""
    with patch("pluck.extraction.extractor.infer_schema", new_callable=AsyncMock) as mock_infer:
        mock_infer.return_value = (_fake_schema(), 10, 5)
        result = await extract(
            _make_fetch_result("https://linkedin.com/jobs/11111"),
            _fake_schema(),   # explicit schema provided
            _make_client(),
            cache_store=store,
        )

    mock_infer.assert_not_called()
    assert result.schema_cache_hit is False
    # Nothing written to cache
    assert store.get_schema("linkedin.com/jobs/*") is None

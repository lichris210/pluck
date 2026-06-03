"""Tests for pluck/pipeline.py — mocked dependencies, no network."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pluck.config import Config
from pluck.models import (
    ExtractionResult,
    ExtractionSchema,
    FetchResult,
    SiteGroup,
    SiteProfile,
)
from pluck.pipeline import PluckPipeline


# ── Factories ─────────────────────────────────────────────────────────────────


def _config(anthropic_key: str | None = "test-key", apify_token: str | None = None) -> Config:
    return Config(anthropic_api_key=anthropic_key, apify_token=apify_token)


def _profile(
    site_group: SiteGroup = SiteGroup.STATIC_HTML,
    url: str = "https://example.com/",
    error: str | None = None,
) -> SiteProfile:
    return SiteProfile(
        url=url,
        final_url=url,
        status_code=200,
        headers={},
        content_type="text/html",
        html="<html>ok</html>",
        site_group=site_group,
        classification_reasons=["test fixture"],
        response_time_ms=10.0,
        error=error,
    )


def _fetch_ok(structured_data: list[dict] | None = None) -> FetchResult:
    return FetchResult(
        url="https://example.com/",
        html="<html>ok</html>",
        fetcher_used="AsyncFetcher",
        fetch_time_ms=50.0,
        success=True,
        structured_data=structured_data,
        metadata={},
    )


def _fetch_fail(error: str = "Fetch failed") -> FetchResult:
    return FetchResult(
        url="https://example.com/",
        html="",
        fetcher_used="none",
        fetch_time_ms=5.0,
        success=False,
        error=error,
        metadata={},
    )


def _extraction_ok(items: list[dict] | None = None, error: str | None = None) -> ExtractionResult:
    schema = ExtractionSchema(description="test", fields=[])
    return ExtractionResult(
        items=items or [{"title": "Item 1"}, {"title": "Item 2"}],
        schema_used=schema,
        source_url="https://example.com/",
        total_input_tokens=500,
        total_output_tokens=80,
        extraction_time_ms=200.0,
        model_used="claude-haiku-4-5",
        error=error,
    )


# ── Happy path ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_successful_run_populates_all_fields():
    pipeline = PluckPipeline(_config())
    with patch("pluck.pipeline.ingest", new_callable=AsyncMock) as mock_ingest, \
         patch("pluck.pipeline.router") as mock_router, \
         patch("pluck.pipeline.extract", new_callable=AsyncMock) as mock_extract:
        mock_ingest.return_value = _profile()
        mock_router.fetch = AsyncMock(return_value=_fetch_ok())
        mock_extract.return_value = _extraction_ok()

        result = await pipeline.run("https://example.com/", output_format="json")

    assert result.error is None
    assert result.site_profile is not None
    assert result.fetch_result is not None
    assert result.extraction_result is not None
    assert result.formatted_output  # JSON string
    assert result.output_format == "json"
    assert result.total_time_ms >= 0


@pytest.mark.asyncio
async def test_successful_run_steps_completed():
    pipeline = PluckPipeline(_config())
    with patch("pluck.pipeline.ingest", new_callable=AsyncMock) as mock_ingest, \
         patch("pluck.pipeline.router") as mock_router, \
         patch("pluck.pipeline.extract", new_callable=AsyncMock) as mock_extract:
        mock_ingest.return_value = _profile()
        mock_router.fetch = AsyncMock(return_value=_fetch_ok())
        mock_extract.return_value = _extraction_ok()

        result = await pipeline.run("https://example.com/")

    assert result.steps_completed == ["ingest", "fetch", "extract", "format"]


# ── Partial failures ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_error_steps_completed_only_ingest():
    pipeline = PluckPipeline(_config())
    with patch("pluck.pipeline.ingest", new_callable=AsyncMock) as mock_ingest, \
         patch("pluck.pipeline.router") as mock_router:
        mock_ingest.return_value = _profile()
        mock_router.fetch = AsyncMock(return_value=_fetch_fail("Connection refused"))

        result = await pipeline.run("https://example.com/")

    assert result.steps_completed == ["ingest"]
    assert "Connection refused" in result.error
    assert result.fetch_result is not None


@pytest.mark.asyncio
async def test_extraction_error_steps_completed_ingest_and_fetch():
    pipeline = PluckPipeline(_config())
    with patch("pluck.pipeline.ingest", new_callable=AsyncMock) as mock_ingest, \
         patch("pluck.pipeline.router") as mock_router, \
         patch("pluck.pipeline.extract", new_callable=AsyncMock) as mock_extract:
        mock_ingest.return_value = _profile()
        mock_router.fetch = AsyncMock(return_value=_fetch_ok())
        mock_extract.return_value = _extraction_ok(error="API down")

        result = await pipeline.run("https://example.com/")

    assert result.steps_completed == ["ingest", "fetch"]
    assert "API down" in result.error
    assert result.extraction_result is not None


@pytest.mark.asyncio
async def test_ingest_error_returns_empty_steps():
    pipeline = PluckPipeline(_config())
    with patch("pluck.pipeline.ingest", new_callable=AsyncMock) as mock_ingest:
        mock_ingest.return_value = _profile(error="DNS resolution failed")

        result = await pipeline.run("https://example.com/")

    assert result.steps_completed == []
    assert "DNS resolution failed" in result.error


# ── Skip-extraction (Apify / XHR structured data) ────────────────────────────


@pytest.mark.asyncio
async def test_skip_extraction_path_uses_structured_data():
    pipeline = PluckPipeline(_config())
    items = [{"title": "Python Dev", "company": "Anthropic"}]
    with patch("pluck.pipeline.ingest", new_callable=AsyncMock) as mock_ingest, \
         patch("pluck.pipeline.router") as mock_router, \
         patch("pluck.pipeline.extract", new_callable=AsyncMock) as mock_extract:
        mock_ingest.return_value = _profile()
        mock_router.fetch = AsyncMock(return_value=_fetch_ok(structured_data=items))

        result = await pipeline.run("https://example.com/", output_format="json")

    assert result.error is None
    assert result.extraction_result is None  # skipped
    assert "Python Dev" in result.formatted_output
    mock_extract.assert_not_called()


@pytest.mark.asyncio
async def test_skip_extraction_steps_do_not_include_extract():
    pipeline = PluckPipeline(_config())
    with patch("pluck.pipeline.ingest", new_callable=AsyncMock) as mock_ingest, \
         patch("pluck.pipeline.router") as mock_router:
        mock_ingest.return_value = _profile()
        mock_router.fetch = AsyncMock(return_value=_fetch_ok(structured_data=[{"a": 1}]))

        result = await pipeline.run("https://example.com/")

    assert "extract" not in result.steps_completed
    assert "format" in result.steps_completed


# ── Parameter threading ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_schema_parameter_passed_to_extractor():
    pipeline = PluckPipeline(_config())
    custom_schema = ExtractionSchema(description="My schema", fields=[])
    with patch("pluck.pipeline.ingest", new_callable=AsyncMock) as mock_ingest, \
         patch("pluck.pipeline.router") as mock_router, \
         patch("pluck.pipeline.extract", new_callable=AsyncMock) as mock_extract:
        mock_ingest.return_value = _profile()
        mock_router.fetch = AsyncMock(return_value=_fetch_ok())
        mock_extract.return_value = _extraction_ok()

        await pipeline.run("https://example.com/", schema=custom_schema)

    _, kwargs = mock_extract.call_args
    # extract(fetch_result, schema, client) — schema is 2nd positional arg
    call_args = mock_extract.call_args[0]
    assert call_args[1] is custom_schema


@pytest.mark.asyncio
async def test_use_apify_parameter_passed_to_router():
    pipeline = PluckPipeline(_config())
    with patch("pluck.pipeline.ingest", new_callable=AsyncMock) as mock_ingest, \
         patch("pluck.pipeline.router") as mock_router, \
         patch("pluck.pipeline.extract", new_callable=AsyncMock) as mock_extract:
        mock_ingest.return_value = _profile()
        mock_router.fetch = AsyncMock(return_value=_fetch_ok())
        mock_extract.return_value = _extraction_ok()

        await pipeline.run("https://example.com/", use_apify=True)

    _, kwargs = mock_router.fetch.call_args
    assert kwargs.get("use_apify") is True


@pytest.mark.asyncio
async def test_max_items_caps_output():
    pipeline = PluckPipeline(_config())
    many_items = [{"n": i} for i in range(50)]
    with patch("pluck.pipeline.ingest", new_callable=AsyncMock) as mock_ingest, \
         patch("pluck.pipeline.router") as mock_router, \
         patch("pluck.pipeline.extract", new_callable=AsyncMock) as mock_extract:
        mock_ingest.return_value = _profile()
        mock_router.fetch = AsyncMock(return_value=_fetch_ok())
        mock_extract.return_value = _extraction_ok(items=many_items)

        result = await pipeline.run("https://example.com/", output_format="json", max_items=10)

    import json
    data = json.loads(result.formatted_output)
    assert len(data) == 10


# ── Dry run ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dry_run_stops_after_ingest():
    pipeline = PluckPipeline(_config())
    with patch("pluck.pipeline.ingest", new_callable=AsyncMock) as mock_ingest, \
         patch("pluck.pipeline.router") as mock_router:
        mock_ingest.return_value = _profile()

        result = await pipeline.run("https://example.com/", dry_run=True)

    mock_router.fetch.assert_not_called()
    assert result.fetch_result is None
    assert result.steps_completed == ["ingest"]


# ── Missing API key ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_anthropic_key_returns_error():
    pipeline = PluckPipeline(_config(anthropic_key=None))
    with patch("pluck.pipeline.ingest", new_callable=AsyncMock) as mock_ingest, \
         patch("pluck.pipeline.router") as mock_router:
        mock_ingest.return_value = _profile()
        mock_router.fetch = AsyncMock(return_value=_fetch_ok())  # non-skip path

        result = await pipeline.run("https://example.com/")

    assert result.error is not None
    assert "ANTHROPIC_API_KEY" in result.error


# ── Timing ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_total_time_ms_is_non_negative():
    pipeline = PluckPipeline(_config())
    with patch("pluck.pipeline.ingest", new_callable=AsyncMock) as mock_ingest, \
         patch("pluck.pipeline.router") as mock_router, \
         patch("pluck.pipeline.extract", new_callable=AsyncMock) as mock_extract:
        mock_ingest.return_value = _profile()
        mock_router.fetch = AsyncMock(return_value=_fetch_ok())
        mock_extract.return_value = _extraction_ok()

        result = await pipeline.run("https://example.com/")

    assert isinstance(result.total_time_ms, float)
    assert result.total_time_ms >= 0


# ── Logging ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pipeline_logs_step_names(caplog):
    pipeline = PluckPipeline(_config())
    with patch("pluck.pipeline.ingest", new_callable=AsyncMock) as mock_ingest, \
         patch("pluck.pipeline.router") as mock_router, \
         patch("pluck.pipeline.extract", new_callable=AsyncMock) as mock_extract, \
         caplog.at_level(logging.INFO, logger="pluck.pipeline"):
        mock_ingest.return_value = _profile()
        mock_router.fetch = AsyncMock(return_value=_fetch_ok())
        mock_extract.return_value = _extraction_ok()

        await pipeline.run("https://example.com/")

    messages = " ".join(r.message for r in caplog.records)
    assert "ingest" in messages
    assert "fetch" in messages
    assert "extract" in messages

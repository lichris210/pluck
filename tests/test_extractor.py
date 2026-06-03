"""Tests for extractor.extract."""

import pytest

from pluck.extraction.extractor import DEFAULT_MODEL, extract
from pluck.models import ExtractionSchema, FetchResult, FieldDef


pytestmark = pytest.mark.asyncio


def _fetch_result(html: str, url: str = "https://example.com/") -> FetchResult:
    return FetchResult(
        url=url,
        html=html,
        fetcher_used="AsyncFetcher",
        fetch_time_ms=100.0,
        success=True,
    )


def _simple_schema() -> ExtractionSchema:
    return ExtractionSchema(
        description="A list of items",
        fields=[
            FieldDef(name="title", field_type="string", description="Title", required=True),
            FieldDef(name="price", field_type="number", description="Price USD", required=True),
        ],
    )


VALID_ITEMS_JSON = '[{"title": "A", "price": 1.0}, {"title": "B", "price": 2.5}]'


# ── Happy path ───────────────────────────────────────────────────────────────


async def test_returns_extraction_result_with_items(mock_anthropic_client):
    mock_anthropic_client.messages.create.return_value = (
        mock_anthropic_client._make_response(VALID_ITEMS_JSON, 1500, 100)
    )

    result = await extract(
        _fetch_result("<html><body><p>x</p></body></html>"),
        _simple_schema(),
        mock_anthropic_client,
    )

    assert result.error is None
    assert len(result.items) == 2
    assert result.items[0]["title"] == "A"
    assert result.source_url == "https://example.com/"


async def test_calls_noise_filter_before_sending(mock_anthropic_client, noisy_html_fixture):
    """The HTML sent to Claude should be the cleaned version, not raw."""
    mock_anthropic_client.messages.create.return_value = (
        mock_anthropic_client._make_response(VALID_ITEMS_JSON)
    )

    await extract(
        _fetch_result(noisy_html_fixture),
        _simple_schema(),
        mock_anthropic_client,
    )

    user_message = mock_anthropic_client.messages.create.call_args.kwargs[
        "messages"
    ][0]["content"]
    assert "Real article headline" in user_message
    # Stripped noise
    assert "Cookie" not in user_message
    assert "ad-container" not in user_message
    assert "Hidden tracker" not in user_message


async def test_uses_provided_schema(mock_anthropic_client):
    """When a schema is given, infer_schema must not be called."""
    mock_anthropic_client.messages.create.return_value = (
        mock_anthropic_client._make_response(VALID_ITEMS_JSON)
    )
    schema = _simple_schema()

    result = await extract(
        _fetch_result("<html>x</html>"), schema, mock_anthropic_client
    )

    assert result.schema_used is schema
    # Only one API call: the extraction call
    assert mock_anthropic_client.messages.create.call_count == 1


async def test_calls_infer_schema_when_schema_is_none(mock_anthropic_client):
    """When schema is None, infer_schema runs first, then extraction."""
    inferred_schema_json = (
        '{"description": "Posts", "fields": ['
        '{"name": "title", "field_type": "string", "description": "x", "required": true}'
        "]}"
    )
    mock_anthropic_client.messages.create.side_effect = [
        mock_anthropic_client._make_response(inferred_schema_json, 200, 50),
        mock_anthropic_client._make_response('[{"title": "Hello"}]', 1000, 30),
    ]

    result = await extract(
        _fetch_result("<html>x</html>"), None, mock_anthropic_client
    )

    assert mock_anthropic_client.messages.create.call_count == 2
    assert result.schema_used.description == "Posts"
    assert result.items == [{"title": "Hello"}]
    # Tokens accumulated from BOTH calls
    assert result.total_input_tokens == 1200
    assert result.total_output_tokens == 80


async def test_handles_malformed_json_via_repair(mock_anthropic_client):
    """A response wrapped in markdown fences with trailing commas should still parse."""
    fenced = '```json\n[{"title": "A", "price": 1,},]\n```'
    mock_anthropic_client.messages.create.return_value = (
        mock_anthropic_client._make_response(fenced)
    )

    result = await extract(
        _fetch_result("<html>x</html>"),
        _simple_schema(),
        mock_anthropic_client,
    )

    assert result.error is None
    assert result.items == [{"title": "A", "price": 1}]


async def test_handles_unparseable_response_returns_empty_items(mock_anthropic_client):
    mock_anthropic_client.messages.create.return_value = (
        mock_anthropic_client._make_response("I cannot extract anything.")
    )

    result = await extract(
        _fetch_result("<html>x</html>"),
        _simple_schema(),
        mock_anthropic_client,
    )

    # No exception, no items, no error string (the API call succeeded)
    assert result.items == []
    assert result.error is None


# ── Error handling ───────────────────────────────────────────────────────────


async def test_api_error_returns_result_with_error(mock_anthropic_client):
    mock_anthropic_client.messages.create.side_effect = RuntimeError("API down")

    result = await extract(
        _fetch_result("<html>x</html>"),
        _simple_schema(),
        mock_anthropic_client,
    )

    assert result.error is not None
    assert "API down" in result.error
    assert result.items == []
    assert result.source_url == "https://example.com/"


async def test_api_error_after_inference_returns_result_with_error(mock_anthropic_client):
    """If schema inference succeeds but extraction fails, both token counts roll up."""
    inferred = (
        '{"description": "x", "fields": ['
        '{"name": "a", "field_type": "string", "description": "x", "required": true}'
        "]}"
    )
    mock_anthropic_client.messages.create.side_effect = [
        mock_anthropic_client._make_response(inferred, 100, 20),
        RuntimeError("rate limited"),
    ]

    result = await extract(
        _fetch_result("<html>x</html>"), None, mock_anthropic_client
    )

    assert result.error is not None
    assert "rate limited" in result.error
    # Inference tokens are still attributed
    assert result.total_input_tokens == 100
    assert result.total_output_tokens == 20


# ── Metadata: tokens, timing, model ──────────────────────────────────────────


async def test_token_counts_tracked_from_response(mock_anthropic_client):
    mock_anthropic_client.messages.create.return_value = (
        mock_anthropic_client._make_response(VALID_ITEMS_JSON, 2500, 150)
    )

    result = await extract(
        _fetch_result("<html>x</html>"),
        _simple_schema(),
        mock_anthropic_client,
    )

    assert result.total_input_tokens == 2500
    assert result.total_output_tokens == 150


async def test_extraction_time_ms_measured(mock_anthropic_client):
    mock_anthropic_client.messages.create.return_value = (
        mock_anthropic_client._make_response(VALID_ITEMS_JSON)
    )

    result = await extract(
        _fetch_result("<html>x</html>"),
        _simple_schema(),
        mock_anthropic_client,
    )

    assert result.extraction_time_ms >= 0
    # Sanity: a mocked call shouldn't take more than a few seconds
    assert result.extraction_time_ms < 5_000


async def test_model_used_reflects_parameter(mock_anthropic_client):
    mock_anthropic_client.messages.create.return_value = (
        mock_anthropic_client._make_response(VALID_ITEMS_JSON)
    )

    result = await extract(
        _fetch_result("<html>x</html>"),
        _simple_schema(),
        mock_anthropic_client,
        model="claude-sonnet-4-6",
    )

    assert result.model_used == "claude-sonnet-4-6"
    assert (
        mock_anthropic_client.messages.create.call_args.kwargs["model"]
        == "claude-sonnet-4-6"
    )


async def test_default_model_is_haiku(mock_anthropic_client):
    mock_anthropic_client.messages.create.return_value = (
        mock_anthropic_client._make_response(VALID_ITEMS_JSON)
    )

    result = await extract(
        _fetch_result("<html>x</html>"),
        _simple_schema(),
        mock_anthropic_client,
    )

    assert result.model_used == DEFAULT_MODEL
    assert DEFAULT_MODEL == "claude-haiku-4-5"


async def test_prompt_contains_schema_and_url(mock_anthropic_client):
    mock_anthropic_client.messages.create.return_value = (
        mock_anthropic_client._make_response(VALID_ITEMS_JSON)
    )

    await extract(
        _fetch_result("<html>x</html>", url="https://example.com/products"),
        _simple_schema(),
        mock_anthropic_client,
    )

    user_message = mock_anthropic_client.messages.create.call_args.kwargs[
        "messages"
    ][0]["content"]
    assert "https://example.com/products" in user_message
    assert "title" in user_message
    assert "price" in user_message


async def test_empty_items_returned_when_claude_returns_empty_array(mock_anthropic_client):
    mock_anthropic_client.messages.create.return_value = (
        mock_anthropic_client._make_response("[]", 800, 5)
    )

    result = await extract(
        _fetch_result("<html>x</html>"),
        _simple_schema(),
        mock_anthropic_client,
    )

    assert result.items == []
    assert result.error is None

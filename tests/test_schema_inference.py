"""Tests for schema_inference.infer_schema."""

import pytest

from pluck.extraction.prompts import MAX_HTML_CHARS
from pluck.extraction.schema_inference import (
    SCHEMA_INFERENCE_MODEL,
    infer_schema,
)


pytestmark = pytest.mark.asyncio


VALID_SCHEMA_JSON = (
    '{"description": "Product listings",'
    ' "fields": ['
    '{"name": "title", "field_type": "string", "description": "Product name", "required": true},'
    '{"name": "price", "field_type": "number", "description": "USD price", "required": true},'
    '{"name": "url", "field_type": "url", "description": "Product page URL", "required": false}'
    "]}"
)


async def test_parses_valid_response_into_schema(mock_anthropic_client):
    mock_anthropic_client.messages.create.return_value = (
        mock_anthropic_client._make_response(VALID_SCHEMA_JSON, 250, 80)
    )

    schema, in_tok, out_tok = await infer_schema(
        "<html>...</html>", "https://example.com/", mock_anthropic_client
    )

    assert schema.description == "Product listings"
    assert len(schema.fields) == 3
    names = [f.name for f in schema.fields]
    assert names == ["title", "price", "url"]
    assert schema.fields[0].field_type == "string"
    assert schema.fields[2].required is False
    assert in_tok == 250
    assert out_tok == 80


async def test_malformed_response_returns_default_schema(mock_anthropic_client):
    mock_anthropic_client.messages.create.return_value = (
        mock_anthropic_client._make_response(
            "I'm sorry, I cannot determine the schema.", 200, 20
        )
    )

    schema, in_tok, out_tok = await infer_schema(
        "<html>...</html>", "https://example.com/", mock_anthropic_client
    )

    assert len(schema.fields) == 1
    assert schema.fields[0].name == "content"
    assert schema.fields[0].field_type == "string"
    # Tokens are still reported even on fallback
    assert in_tok == 200
    assert out_tok == 20


async def test_empty_response_returns_default_schema(mock_anthropic_client):
    mock_anthropic_client.messages.create.return_value = (
        mock_anthropic_client._make_response("", 50, 0)
    )

    schema, _, _ = await infer_schema(
        "<html>...</html>", "https://example.com/", mock_anthropic_client
    )

    assert len(schema.fields) == 1
    assert schema.fields[0].name == "content"


async def test_response_missing_fields_key_returns_default(mock_anthropic_client):
    mock_anthropic_client.messages.create.return_value = (
        mock_anthropic_client._make_response(
            '{"description": "Some data, but no fields key"}', 100, 10
        )
    )

    schema, _, _ = await infer_schema(
        "<html>...</html>", "https://example.com/", mock_anthropic_client
    )

    assert len(schema.fields) == 1
    assert schema.fields[0].name == "content"


async def test_response_with_empty_fields_returns_default(mock_anthropic_client):
    mock_anthropic_client.messages.create.return_value = (
        mock_anthropic_client._make_response(
            '{"description": "Empty schema", "fields": []}', 100, 10
        )
    )

    schema, _, _ = await infer_schema(
        "<html>...</html>", "https://example.com/", mock_anthropic_client
    )

    assert len(schema.fields) == 1
    assert schema.fields[0].name == "content"


async def test_prompt_includes_cleaned_html(mock_anthropic_client):
    html = "<html><body><h1>Marker abc123</h1></body></html>"
    mock_anthropic_client.messages.create.return_value = (
        mock_anthropic_client._make_response(VALID_SCHEMA_JSON)
    )

    await infer_schema(html, "https://example.com/", mock_anthropic_client)

    call_kwargs = mock_anthropic_client.messages.create.call_args.kwargs
    user_message = call_kwargs["messages"][0]["content"]
    assert "Marker abc123" in user_message


async def test_prompt_includes_source_url(mock_anthropic_client):
    mock_anthropic_client.messages.create.return_value = (
        mock_anthropic_client._make_response(VALID_SCHEMA_JSON)
    )

    await infer_schema(
        "<html>x</html>", "https://example.com/products", mock_anthropic_client
    )

    user_message = mock_anthropic_client.messages.create.call_args.kwargs[
        "messages"
    ][0]["content"]
    assert "https://example.com/products" in user_message


async def test_html_truncated_when_too_long(mock_anthropic_client):
    long_html = "x" * (MAX_HTML_CHARS + 10_000)
    mock_anthropic_client.messages.create.return_value = (
        mock_anthropic_client._make_response(VALID_SCHEMA_JSON)
    )

    await infer_schema(long_html, "https://example.com/", mock_anthropic_client)

    user_message = mock_anthropic_client.messages.create.call_args.kwargs[
        "messages"
    ][0]["content"]
    assert "[truncated]" in user_message
    assert len(user_message) < len(long_html)


async def test_uses_haiku_model(mock_anthropic_client):
    mock_anthropic_client.messages.create.return_value = (
        mock_anthropic_client._make_response(VALID_SCHEMA_JSON)
    )

    await infer_schema(
        "<html>x</html>", "https://example.com/", mock_anthropic_client
    )

    assert (
        mock_anthropic_client.messages.create.call_args.kwargs["model"]
        == SCHEMA_INFERENCE_MODEL
    )
    assert SCHEMA_INFERENCE_MODEL == "claude-haiku-4-5"


async def test_api_error_returns_default_schema(mock_anthropic_client):
    mock_anthropic_client.messages.create.side_effect = RuntimeError("network down")

    schema, in_tok, out_tok = await infer_schema(
        "<html>x</html>", "https://example.com/", mock_anthropic_client
    )

    assert len(schema.fields) == 1
    assert schema.fields[0].name == "content"
    assert in_tok == 0
    assert out_tok == 0


async def test_response_with_markdown_fences_handled(mock_anthropic_client):
    """The repair_and_parse layer should strip markdown fences."""
    fenced = f"```json\n{VALID_SCHEMA_JSON}\n```"
    mock_anthropic_client.messages.create.return_value = (
        mock_anthropic_client._make_response(fenced, 200, 80)
    )

    schema, _, _ = await infer_schema(
        "<html>x</html>", "https://example.com/", mock_anthropic_client
    )

    assert len(schema.fields) == 3
    assert schema.description == "Product listings"

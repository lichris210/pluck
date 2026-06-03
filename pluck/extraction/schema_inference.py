"""Auto-detect what to extract from an HTML page using Claude Haiku 4.5."""

import asyncio
import logging

from pluck.extraction.json_repair import repair_and_parse
from pluck.extraction.prompts import (
    SCHEMA_INFERENCE_SYSTEM,
    build_schema_inference_prompt,
)
from pluck.models import ExtractionSchema, FieldDef

logger = logging.getLogger(__name__)

SCHEMA_INFERENCE_MODEL = "claude-haiku-4-5"
_MAX_TOKENS = 1024


def _default_schema() -> ExtractionSchema:
    return ExtractionSchema(
        description="Page content (fallback schema — inference failed)",
        fields=[
            FieldDef(
                name="content",
                field_type="string",
                description="Main text content of the page",
                required=True,
            )
        ],
    )


async def infer_schema(
    cleaned_html: str, source_url: str, anthropic_client
) -> tuple[ExtractionSchema, int, int]:
    """Ask Claude what fields to extract from a page.

    Returns (schema, input_tokens, output_tokens). Falls back to a minimal
    one-field "content" schema on any error or malformed response.
    """
    prompt = build_schema_inference_prompt(cleaned_html, source_url)

    try:
        response = await asyncio.to_thread(
            anthropic_client.messages.create,
            model=SCHEMA_INFERENCE_MODEL,
            max_tokens=_MAX_TOKENS,
            system=SCHEMA_INFERENCE_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        logger.warning("Schema inference API call failed: %s", exc)
        return _default_schema(), 0, 0

    text = ""
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            text += block.text

    input_tokens = getattr(response.usage, "input_tokens", 0) if getattr(response, "usage", None) else 0
    output_tokens = getattr(response.usage, "output_tokens", 0) if getattr(response, "usage", None) else 0

    parsed = repair_and_parse(text)
    if not parsed:
        logger.warning("Schema inference returned no parseable JSON")
        return _default_schema(), input_tokens, output_tokens

    schema_dict = parsed[0]
    if not isinstance(schema_dict, dict) or not schema_dict.get("fields"):
        logger.warning("Schema inference response missing 'fields' key")
        return _default_schema(), input_tokens, output_tokens

    schema = ExtractionSchema.from_dict(schema_dict)
    if not schema.fields:
        logger.warning("Schema inference produced empty fields list")
        return _default_schema(), input_tokens, output_tokens

    return schema, input_tokens, output_tokens

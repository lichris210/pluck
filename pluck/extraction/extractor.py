"""Claude API extraction engine.

Cleans HTML with the noise filter, asks Claude to extract structured items
matching a schema, and parses the response with `repair_and_parse`.
"""

import asyncio
import json
import logging
import time

from pluck.extraction.json_repair import repair_and_parse
from pluck.extraction.noise_filter import filter_noise
from pluck.extraction.prompts import EXTRACTION_SYSTEM, build_extraction_prompt
from pluck.extraction.schema_inference import infer_schema
from pluck.extraction.validator import validate_extraction
from pluck.models import ExtractionResult, ExtractionSchema, FetchResult
from pluck.url_keys import schema_key

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-haiku-4-5"
_MAX_TOKENS = 8192


async def _call_extraction_api(
    cleaned_html: str,
    schema: ExtractionSchema,
    url: str,
    anthropic_client,
    model: str,
) -> tuple[list[dict], int, int, str | None]:
    """Run one extraction API call.

    Returns (items, input_tokens, output_tokens, error_or_None).
    """
    prompt = build_extraction_prompt(cleaned_html, schema, url)
    try:
        response = await asyncio.to_thread(
            anthropic_client.messages.create,
            model=model,
            max_tokens=_MAX_TOKENS,
            system=EXTRACTION_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        logger.error("Extraction API call failed: %s", exc)
        return [], 0, 0, f"{type(exc).__name__}: {exc}"

    text = ""
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            text += block.text

    in_tok, out_tok = 0, 0
    if getattr(response, "usage", None):
        in_tok = getattr(response.usage, "input_tokens", 0) or 0
        out_tok = getattr(response.usage, "output_tokens", 0) or 0

    return repair_and_parse(text), in_tok, out_tok, None


async def extract(
    fetch_result: FetchResult,
    schema: ExtractionSchema | None,
    anthropic_client,
    model: str = DEFAULT_MODEL,
    cache_store=None,
) -> ExtractionResult:
    """Extract structured items from `fetch_result.html` using Claude.

    If `schema` is None, runs schema inference first (using Haiku).
    Pass `cache_store` (a SchemaCacheStore) to enable schema caching with
    automatic invalidation when validation fails.
    """
    start = time.perf_counter()
    cleaned_html, _stats = filter_noise(fetch_result.html)

    total_input = 0
    total_output = 0
    _schema_cache_hit = False
    _inferred = schema is None   # True when we own schema resolution
    pattern: str | None = None

    if schema is None:
        pattern = schema_key(fetch_result.url)
        cached_json = cache_store.get_schema(pattern) if cache_store else None

        if cached_json is not None:
            schema = ExtractionSchema.from_dict(json.loads(cached_json))
            cache_store.touch_schema(pattern)
            _schema_cache_hit = True
        else:
            schema, infer_in, infer_out = await infer_schema(
                cleaned_html, fetch_result.url, anthropic_client
            )
            total_input += infer_in
            total_output += infer_out
            if cache_store:
                cache_store.put_schema(pattern, json.dumps(schema.to_dict()))

    # ── first extraction attempt ───────────────────────────────────────────────
    items, ext_in, ext_out, api_error = await _call_extraction_api(
        cleaned_html, schema, fetch_result.url, anthropic_client, model
    )
    total_input += ext_in
    total_output += ext_out

    if api_error:
        elapsed = (time.perf_counter() - start) * 1000
        return ExtractionResult(
            items=[],
            schema_used=schema,
            source_url=fetch_result.url,
            total_input_tokens=total_input,
            total_output_tokens=total_output,
            extraction_time_ms=elapsed,
            model_used=model,
            error=api_error,
            schema_cache_hit=_schema_cache_hit,
        )

    # ── validation + single retry (cache-hit path only) ────────────────────────
    # Fresh inferences and explicit schemas are returned as-is on failure.
    if _inferred and _schema_cache_hit and cache_store and pattern:
        vr = validate_extraction(schema, items)
        if not vr.ok:
            logger.info(
                "Cached schema invalid (%s); invalidating and re-inferring for %s",
                vr.reason, pattern,
            )
            cache_store.invalidate_schema(pattern)

            schema, infer_in, infer_out = await infer_schema(
                cleaned_html, fetch_result.url, anthropic_client
            )
            total_input += infer_in
            total_output += infer_out
            _schema_cache_hit = False

            items, ext_in2, ext_out2, api_error2 = await _call_extraction_api(
                cleaned_html, schema, fetch_result.url, anthropic_client, model
            )
            total_input += ext_in2
            total_output += ext_out2
            elapsed = (time.perf_counter() - start) * 1000

            if api_error2:
                return ExtractionResult(
                    items=[],
                    schema_used=schema,
                    source_url=fetch_result.url,
                    total_input_tokens=total_input,
                    total_output_tokens=total_output,
                    extraction_time_ms=elapsed,
                    model_used=model,
                    error=api_error2,
                    schema_cache_hit=False,
                )

            vr2 = validate_extraction(schema, items)
            if not vr2.ok:
                return ExtractionResult(
                    items=[],
                    schema_used=schema,
                    source_url=fetch_result.url,
                    total_input_tokens=total_input,
                    total_output_tokens=total_output,
                    extraction_time_ms=elapsed,
                    model_used=model,
                    error=f"Validation failed after re-inference: {vr2.reason}",
                    schema_cache_hit=False,
                )

            # New schema passed — persist it
            cache_store.put_schema(pattern, json.dumps(schema.to_dict()))

    elapsed = (time.perf_counter() - start) * 1000
    return ExtractionResult(
        items=items,
        schema_used=schema,
        source_url=fetch_result.url,
        total_input_tokens=total_input,
        total_output_tokens=total_output,
        extraction_time_ms=elapsed,
        model_used=model,
        schema_cache_hit=_schema_cache_hit,
    )

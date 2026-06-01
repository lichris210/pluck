import json
import os
import time

import anthropic
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.auth import PLUCK_PASSWORD, check_auth, generate_token, require_auth
from pluck.curation.curator import curate
from pluck.curation.prompt_spec import derive_columns
from pluck.extraction.extractor import extract
from pluck.fetchers.router import fetch as route_fetch
from pluck.ingester import ingest
from pluck.models import ExtractionSchema, SiteGroup
from pluck.storage.cache_store import SchemaCacheStore

_schema_cache = SchemaCacheStore()

router = APIRouter()

_FETCHER_LABELS = {
    SiteGroup.STATIC_HTML: "scrapling_static",
    SiteGroup.SERVER_RENDERED_PAGINATED: "scrapling_static",
    SiteGroup.JS_RENDERED_CLEAN_API: "scrapling_dynamic",
    SiteGroup.JS_RENDERED_MESSY_DOM: "scrapling_dynamic",
    SiteGroup.INTERACTIVE_GATED: "scrapling_stealth",
    SiteGroup.AUTH_GATED: "apify",
    SiteGroup.FORTRESS: "apify",
}


class AuthRequest(BaseModel):
    password: str


class ClassifyRequest(BaseModel):
    url: str


@router.post("/api/auth")
async def auth_endpoint(body: AuthRequest):
    if body.password != PLUCK_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid password")
    return {"token": generate_token()}


@router.post("/api/classify")
async def classify_endpoint(body: ClassifyRequest, _token: str = Depends(require_auth)):
    profile = await ingest(body.url)
    return {
        "url": profile.url,
        "final_url": profile.final_url,
        "site_group": profile.site_group.name,
        "site_group_number": profile.site_group.value,
        "classification_reasons": profile.classification_reasons,
        "response_time_ms": profile.response_time_ms,
        "error": profile.error,
    }


def _sse(payload: dict) -> str:
    return "data: " + json.dumps(payload) + "\n\n"


def _token_cost(input_tokens: int, output_tokens: int) -> float:
    # Haiku 4.5 pricing: $0.80/MTok input, $4.00/MTok output
    input_cost = (input_tokens / 1_000_000) * 0.80
    output_cost = (output_tokens / 1_000_000) * 4.00
    return input_cost + output_cost


def _estimate_cost(result) -> float:
    return round(_token_cost(result.total_input_tokens, result.total_output_tokens), 6)


class _UsageTrackingClient:
    """Wraps an Anthropic client, accumulating token usage from each
    `messages.create` response. Lets us bill the `derive_columns` call, which
    returns column names but not its own token counts."""

    def __init__(self, client):
        self._client = client
        self.input_tokens = 0
        self.output_tokens = 0

    @property
    def messages(self):
        return self

    def create(self, *args, **kwargs):
        resp = self._client.messages.create(*args, **kwargs)
        usage = getattr(resp, "usage", None)
        if usage:
            self.input_tokens += getattr(usage, "input_tokens", 0) or 0
            self.output_tokens += getattr(usage, "output_tokens", 0) or 0
        return resp


@router.get("/api/extract")
async def extract_endpoint(
    url: str = Query(...),
    schema: str | None = Query(default=None),
    prompt: str | None = Query(default=None),
    max_items: int = Query(default=100, ge=1, le=1000),
    force_apify: bool = Query(default=False),
    token: str | None = Query(None),
    authorization: str | None = Header(default=None),
):
    check_auth(authorization, token)

    async def stream():
        t0 = time.perf_counter()

        # ── results cache check ───────────────────────────────────────────
        _cached = _schema_cache.get_cached_result(url)
        if _cached is not None:
            payload = json.loads(_cached)
            payload["total_time_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            payload["from_cache"] = True
            yield _sse({"step": "cache", "status": "hit"})
            yield _sse(payload)
            return

        yield _sse({"step": "classifying", "status": "active"})

        profile = await ingest(url)
        if profile.error:
            yield _sse({"step": "classifying", "status": "error", "error": profile.error})
            return

        yield _sse({
            "step": "classifying",
            "status": "done",
            "site_group": profile.site_group.name,
            "site_group_number": profile.site_group.value,
        })

        fetcher_label = _FETCHER_LABELS.get(profile.site_group, "scrapling_static")
        yield _sse({"step": "fetching", "status": "active", "fetcher": fetcher_label})

        fetch_result = await route_fetch(profile, use_apify=force_apify, max_items=max_items)
        if not fetch_result.success:
            yield _sse({"step": "fetching", "status": "error", "error": fetch_result.error or "Fetch failed"})
            return

        yield _sse({"step": "fetching", "status": "done", "html_length": len(fetch_result.html)})

        extraction_result = None
        if not fetch_result.skip_extraction:
            parsed_schema = None
            if schema:
                try:
                    parsed_schema = ExtractionSchema.from_dict(json.loads(schema))
                except Exception:
                    parsed_schema = None

            field_count = len(parsed_schema.fields) if parsed_schema else 0
            yield _sse({"step": "extracting", "status": "active", "fields": field_count})

            try:
                client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
                extraction_result = await extract(fetch_result, parsed_schema, client, cache_store=_schema_cache)
            except Exception as exc:
                yield _sse({"step": "extracting", "status": "error", "error": str(exc)})
                return

            if extraction_result.error:
                yield _sse({"step": "extracting", "status": "error", "error": extraction_result.error})
                return

            if extraction_result.schema_cache_hit:
                yield _sse({"step": "schema_cache", "status": "hit"})

            yield _sse({"step": "extracting", "status": "done"})

        apify_cost = float(fetch_result.metadata.get("apify_cost_usd") or 0.0)

        if fetch_result.skip_extraction:
            items = fetch_result.structured_data or []
            cost_usd = round(apify_cost, 6)
            extraction_time_ms = 0.0
            model_used = "none"
        else:
            items = extraction_result.items if extraction_result else []
            haiku_cost = _estimate_cost(extraction_result) if extraction_result else 0.0
            cost_usd = round(haiku_cost + apify_cost, 6)
            extraction_time_ms = extraction_result.extraction_time_ms if extraction_result else 0.0
            model_used = extraction_result.model_used if extraction_result else ""

        # ── optional prompt-driven column selection (one extra Haiku call)
        keep_columns = None
        if prompt:
            col_list: list[str] = []
            sample_row: dict = {}
            for item in items:
                if isinstance(item, dict):
                    if not sample_row:
                        sample_row = item
                    for key in item:
                        if key not in col_list:
                            col_list.append(key)
            if col_list:
                tracker = _UsageTrackingClient(
                    anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
                )
                keep_columns = derive_columns(prompt, col_list, sample_row, tracker)
                cost_usd = round(
                    cost_usd + _token_cost(tracker.input_tokens, tracker.output_tokens), 6
                )

        # ── curation: dedupe, project (keep_columns / structured), relevance, cap
        items, cstats = curate(
            items,
            source_url=url,
            is_structured=fetch_result.skip_extraction,
            max_items=max_items,
            keep_columns=keep_columns,
        )

        columns: set[str] = set()
        for item in items:
            if isinstance(item, dict):
                columns.update(item.keys())

        _done = {
            "step": "done",
            "status": "done",
            "items": items,
            "total_rows": len(items),
            "total_columns": len(columns),
            "cost_usd": cost_usd,
            "rows_before_curation": cstats.rows_in,
            "dropped_columns": cstats.dropped_columns,
            "extraction_time_ms": extraction_time_ms,
            "total_time_ms": round((time.perf_counter() - t0) * 1000, 1),
            "model_used": model_used,
        }
        _schema_cache.put_cached_result(url, json.dumps(_done))
        yield _sse(_done)

    return StreamingResponse(stream(), media_type="text/event-stream")

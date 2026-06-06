import hashlib
import json
import logging
import os
import time
from urllib.parse import urlparse

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
from pluck.registry.discovery_filter import filter_candidates
from pluck.registry.discovery_planner import (
    apply_captured_schema,
    capture_output_schema,
    discover_actor,
)
from pluck.registry.loader import candidates_for_url, find_entry
from pluck.registry.planner import plan_extraction
from pluck.registry.store_api import build_search_query, search_store
from pluck.storage.cache_store import SchemaCacheStore

_schema_cache = SchemaCacheStore()

logger = logging.getLogger(__name__)

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


@router.post("/api/admin/plan-cache/clear")
async def clear_plan_cache_endpoint(_token: str = Depends(require_auth)):
    """Bulk-clear the planner plan cache. Returns the number of rows removed."""
    cleared = _schema_cache.clear_plan_cache()
    return {"cleared": cleared}


_PLANNER_TRUTHY = {"1", "true", "yes", "on"}


def _planner_enabled() -> bool:
    return (os.environ.get("USE_PLANNER") or "").strip().lower() in _PLANNER_TRUTHY


def _planned_cache_key(url: str, prompt: str | None, max_items: int) -> str:
    """Results-cache key for the planned path: URL + prompt hash + max_items.

    The planner shapes output from the prompt, so the same URL with a different
    prompt must not serve a stale shaped result (plan gotcha 3). ``max_items`` is
    folded in too (Issue 1): a max_items=5 result must not be served to a later
    max_items=100 request. Appended as query params because ``results_key`` keeps
    (and sorts) the query but drops the fragment.
    """
    digest = hashlib.sha256((prompt or "").encode("utf-8")).hexdigest()[:16]
    sep = "&" if urlparse(url).query else "?"
    return f"{url}{sep}_pluck_phash={digest}&_pluck_n={max_items}"


def _plan_cache_key(url: str, prompt: str | None) -> str:
    """Plan-cache key for the planned path: normalised host plus a prompt hash.

    Host normalisation mirrors the registry loader (lowercase netloc, strip a
    leading ``www.``) so the same site reuses one plan regardless of www. The
    prompt hash reuses ``_planned_cache_key``'s sha256[:16] digest because the
    plan is shaped from the prompt.
    """
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    phash = hashlib.sha256((prompt or "").encode("utf-8")).hexdigest()[:16]
    return f"{host}|{phash}"


def _discovery_host(url: str) -> str:
    """Normalised host (lowercase, no www.) — the tier-2 cache's domain_pattern key."""
    host = (urlparse(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def _discovery_confidence(successful_runs: int) -> str:
    """Decision 4 confidence band from a discovered actor's run count."""
    if successful_runs >= 10:
        return "high"
    if successful_runs >= 1:
        return "medium"
    return "low"


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
    refresh: bool = Query(default=False),
    token: str | None = Query(None),
    authorization: str | None = Header(default=None),
):
    check_auth(authorization, token)

    async def stream():
        t0 = time.perf_counter()

        # Accumulates which cache/discovery events fired, for the final done log.
        cache_events: list[str] = []

        # ── planner gate: registry host + USE_PLANNER forces the Apify branch
        # (plan gotcha 2) regardless of how the host would otherwise classify.
        candidates = candidates_for_url(url) if _planner_enabled() else []
        planned_path = bool(candidates)

        logger.info(
            "Request received: url=%s prompt=%r max_items=%d refresh=%s planned_path=%s",
            url, (prompt or "")[:100], max_items, refresh, planned_path,
        )

        # The planned path shapes output from the prompt, so its results cache
        # key folds in a prompt hash (plan gotcha 3); the legacy path is unchanged.
        cache_key = _planned_cache_key(url, prompt, max_items) if planned_path else url

        # ── results cache check (skipped when refresh=true) ──────────────
        _cached = None if refresh else _schema_cache.get_cached_result(cache_key)
        if _cached is not None:
            logger.info("Results cache hit: key=%s — serving cached response", cache_key)
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

        logger.info(
            "Classifier done: url=%s site_group=%d (%s)",
            url, profile.site_group.value, profile.site_group.name,
        )
        yield _sse({
            "step": "classifying",
            "status": "done",
            "site_group": profile.site_group.name,
            "site_group_number": profile.site_group.value,
        })

        # ── discovery fall-through: planner on, but no tier-1/tier-2 candidate ──
        # Search the Apify Store, rank with Haiku, capture the real schema, and cache
        # the winner in tier 2 so future requests for this host skip discovery (they
        # arrive here already planned via the loader union). Never crashes the request:
        # on no-result or error we fall back to the legacy non-planned path.
        plan = None
        planner_cost = 0.0
        if not planned_path and _planner_enabled():
            yield _sse({"step": "discovery", "status": "active"})
            disc_client = _UsageTrackingClient(
                anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
            )
            apify_token = os.environ.get("APIFY_TOKEN")
            entry = None
            try:
                query = build_search_query(url)
                store_items = await search_store(query)
                cands = filter_candidates(store_items)
                logger.info(
                    "Discovery triggered: query=%r candidates_after_filter=%d names=%s",
                    query, len(cands), [c.get("actor_id") for c in cands],
                )
                # Single-pass: discover_actor fetches the top candidates' live input
                # schemas and returns a schema-validated entry in one Haiku call.
                entry = await discover_actor(
                    url, prompt or "", cands, disc_client, apify_token=apify_token
                )
            except Exception as exc:
                logger.warning(
                    "Discovery failed for %s: %s — falling back to legacy path", url, exc
                )
                entry = None
            planner_cost += _token_cost(
                disc_client.input_tokens, disc_client.output_tokens
            )

            # A discovered actor is only trustworthy once its maxItems=1 probe
            # returns real content. An empty capture (no row / thin row / bad input)
            # means we do NOT cache it — fall through to the legacy path. With no
            # APIFY_TOKEN there is nothing to probe and the apify fetch would fail
            # anyway, so we skip caching in that case too.
            if entry is not None:
                logger.info(
                    "Discovery actor chosen: actor_id=%s reasoning=%r source=discovered",
                    entry.get("actor_id"), (entry.get("reasoning") or "")[:100],
                )

            captured: list[str] = []
            if entry is not None and apify_token:
                captured = await capture_output_schema(entry, apify_token, url)
                logger.info(
                    "Schema capture: actor_id=%s keys=%d sample=%s accepted=%s",
                    entry.get("actor_id"), len(captured), captured[:5], bool(captured),
                )
                entry = apply_captured_schema(entry, captured)

            if entry is not None and captured:
                host = _discovery_host(url)
                _schema_cache.put_discovered(host, entry)
                logger.info(
                    "Tier 2 cache write: domain_pattern=%s actor_id=%s columns=%d",
                    host, entry["actor_id"], len(captured),
                )
                candidates = [entry]
                planned_path = True
                cache_key = _planned_cache_key(url, prompt, max_items)
                cache_events.append("discovery")
                runs = entry.get("successful_runs", 0)
                logger.info(
                    "Discovery complete: actor_id=%s source=discovered confidence=%s",
                    entry["actor_id"], _discovery_confidence(runs),
                )
                yield _sse({
                    "step": "discovery",
                    "actor_id": entry["actor_id"],
                    "reasoning": entry.get("reasoning", ""),
                    "source": "discovered",
                    "confidence": _discovery_confidence(runs),
                })
            elif entry is not None:
                logger.warning(
                    "Discovery schema capture failed for %s; falling back to legacy path",
                    url,
                )
            # KNOWN LIMITATION (Issue 3): when discovery yields nothing and the site is
            # JavaScript-heavy, the legacy fallback uses the Group-1 static fetcher, which
            # can't render JS — so the user may get thin/empty results (e.g. Reddit). A
            # real fix (route JS sites to a dynamic fetcher) is a future task.

        # ── intent-aware planner (registry hosts only, behind USE_PLANNER) ──
        if planned_path:
            yield _sse({"step": "planning", "status": "active"})

            # Plan cache: a (host, prompt_hash) hit skips the Haiku call entirely
            # (no tokens billed). refresh=true bypasses the read but still writes.
            plan_key = _plan_cache_key(url, prompt)
            cached_plan_json = None if refresh else _schema_cache.get_plan(plan_key)
            if cached_plan_json is not None:
                logger.info("Plan cache hit: key=%s — skipping Haiku planner", plan_key)
                cache_events.append("plan_cache_hit")
                plan = json.loads(cached_plan_json)
                planner_cost = 0.0
                yield _sse({"step": "plan_cache", "status": "hit"})
            else:
                logger.info("Plan cache miss: key=%s — calling Haiku planner", plan_key)
                tracker = _UsageTrackingClient(
                    anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
                )
                plan = plan_extraction(url, prompt or "", max_items, candidates, tracker)
                planner_cost = _token_cost(tracker.input_tokens, tracker.output_tokens)
                _schema_cache.put_plan(plan_key, json.dumps(plan))
                logger.info(
                    "Planner result: actor_id=%s reasoning=%r planner_cost=$%.6f",
                    plan.get("actor_id"), (plan.get("reasoning") or "")[:100], planner_cost,
                )

            yield _sse({
                "step": "planning",
                "status": "done",
                "actor_id": plan.get("actor_id"),
                "reasoning": plan.get("reasoning", ""),
            })

        fetcher_label = "apify" if planned_path else _FETCHER_LABELS.get(
            profile.site_group, "scrapling_static"
        )
        if planned_path and plan:
            # Log input KEYS only — never the values (URLs/handles stay out of logs).
            logger.info(
                "Invoking actor: actor_id=%s input_keys=%s fetcher=%s",
                plan.get("actor_id"), list((plan.get("actor_input") or {}).keys()), fetcher_label,
            )
        else:
            logger.info("Fetching via %s: url=%s", fetcher_label, url)
        yield _sse({"step": "fetching", "status": "active", "fetcher": fetcher_label})

        fetch_result = await route_fetch(
            profile,
            use_apify=force_apify or planned_path,
            max_items=max_items,
            plan=plan,
        )
        if not fetch_result.success:
            yield _sse({"step": "fetching", "status": "error", "error": fetch_result.error or "Fetch failed"})
            return

        yield _sse({"step": "fetching", "status": "done", "html_length": len(fetch_result.html)})

        # Decision 3: a successful scrape on a discovered (tier-2) actor bumps its
        # successful_runs counter — the signal the review CLI uses for promotion.
        if planned_path and plan:
            chosen = find_entry(plan.get("actor_id"), candidates)
            if chosen and chosen.get("source") == "discovered":
                _schema_cache.increment_successful_runs(
                    _discovery_host(url), plan["actor_id"]
                )

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
                cache_events.append("schema_cache_hit")
                yield _sse({"step": "schema_cache", "status": "hit"})

            yield _sse({"step": "extracting", "status": "done"})

        apify_cost = float(fetch_result.metadata.get("apify_cost_usd") or 0.0)

        if fetch_result.skip_extraction:
            items = fetch_result.structured_data or []
            cost_usd = round(apify_cost + planner_cost, 6)
            extraction_time_ms = 0.0
            model_used = "none"
        else:
            items = extraction_result.items if extraction_result else []
            haiku_cost = _estimate_cost(extraction_result) if extraction_result else 0.0
            cost_usd = round(haiku_cost + apify_cost + planner_cost, 6)
            extraction_time_ms = extraction_result.extraction_time_ms if extraction_result else 0.0
            model_used = extraction_result.model_used if extraction_result else ""

        # ── optional prompt-driven column selection (one extra Haiku call) ──
        # Skipped on the planned path: the plan's output_shape already chose columns.
        keep_columns = None
        if prompt and not planned_path:
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
        _schema_cache.put_cached_result(cache_key, json.dumps(_done))
        logger.info(
            "Done: url=%s total_rows=%d total_columns=%d cost_usd=%.6f "
            "(planner=%.6f apify=%.6f) cache_events=%s",
            url, len(items), len(columns), cost_usd, planner_cost, apify_cost,
            cache_events or ["none"],
        )
        yield _sse(_done)

    return StreamingResponse(stream(), media_type="text/event-stream")

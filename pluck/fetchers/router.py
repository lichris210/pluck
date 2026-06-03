"""
Routes a SiteProfile to the right fetcher and returns a FetchResult.

Routing table:
  STATIC_HTML              → AsyncFetcher  (fast, no browser)
  SERVER_RENDERED_PAGINATED→ AsyncFetcher  (paginated handling deferred)
  JS_RENDERED_CLEAN_API    → DynamicFetcher with capture_xhr="/api/"
  JS_RENDERED_MESSY_DOM    → DynamicFetcher (full DOM, no XHR)
  INTERACTIVE_GATED        → StealthyFetcher with dismiss_cookie_banners page_action
  AUTH_GATED               → ApifyActor (requires APIFY_TOKEN env var)
  FORTRESS                 → ApifyActor (requires APIFY_TOKEN env var)

Fallback: if AsyncFetcher fails for a STATIC_HTML site, retry with DynamicFetcher.
"""

import asyncio
import logging
import os
import time

from pluck.fetchers.apify_handler import fetch_via_apify, fetch_via_apify_plan
from pluck.fetchers.page_actions import dismiss_cookie_banners
from pluck.fetchers.scrapling_wrapper import (
    fetch_dynamic,
    fetch_static_async,
    fetch_stealth,
)
from pluck.models import FetchResult, SiteGroup, SiteProfile

logger = logging.getLogger(__name__)

_AUTH_GATED_ERROR = (
    "Auth-gated sites require Apify integration. Set APIFY_TOKEN to enable."
)
_FORTRESS_ERROR = (
    "Fortress sites require Apify actors. Set APIFY_TOKEN to enable."
)


def _error_result(url: str, msg: str, elapsed_ms: float) -> FetchResult:
    return FetchResult(
        url=url,
        html="",
        fetcher_used="none",
        fetch_time_ms=elapsed_ms,
        success=False,
        error=msg,
        metadata={},
    )


async def fetch(
    profile: SiteProfile,
    use_apify: bool = False,
    max_items: int = 100,
    plan: dict | None = None,
) -> FetchResult:
    """Dispatch to the appropriate fetcher based on SiteGroup classification.

    When *plan* is supplied, the Apify branch runs the planner-produced execution
    plan via ``fetch_via_apify_plan``; otherwise it uses the legacy
    ``fetch_via_apify`` path.
    """
    start = time.perf_counter()
    url = profile.final_url

    # ── Apify: AUTH_GATED, FORTRESS, or forced via use_apify ─────────────────
    is_fortress = profile.site_group in (SiteGroup.AUTH_GATED, SiteGroup.FORTRESS)
    if is_fortress or use_apify:
        apify_token = os.environ.get("APIFY_TOKEN")
        if not apify_token:
            if use_apify:
                msg = "Apify path requested (--use-apify) but APIFY_TOKEN is not set."
            elif profile.site_group == SiteGroup.AUTH_GATED:
                msg = _AUTH_GATED_ERROR
            else:
                msg = _FORTRESS_ERROR
            return _error_result(url, msg, (time.perf_counter() - start) * 1000)
        if plan is not None:
            result = await fetch_via_apify_plan(plan, apify_token, max_items=max_items)
        else:
            result = await fetch_via_apify(url, apify_token, max_items=max_items)
        result.fetch_time_ms = (time.perf_counter() - start) * 1000
        return result

    # ── Live fetching ────────────────────────────────────────────────────────
    try:
        if profile.site_group in (SiteGroup.STATIC_HTML, SiteGroup.SERVER_RENDERED_PAGINATED):
            result = await fetch_static_async(url)
            # Fallback to DynamicFetcher only on hard failure (not success with empty HTML)
            if not result.success:
                logger.info("Static fetch failed for %s, retrying with DynamicFetcher", url)
                result = await asyncio.to_thread(fetch_dynamic, url)

        elif profile.site_group == SiteGroup.JS_RENDERED_CLEAN_API:
            result = await asyncio.to_thread(fetch_dynamic, url, 30.0, "/api/")

        elif profile.site_group == SiteGroup.JS_RENDERED_MESSY_DOM:
            result = await asyncio.to_thread(fetch_dynamic, url)

        elif profile.site_group == SiteGroup.INTERACTIVE_GATED:
            result = await asyncio.to_thread(fetch_stealth, url, 30.0, dismiss_cookie_banners)

        else:
            # Unknown group — safe fallback
            result = await fetch_static_async(url)

    except Exception as exc:
        elapsed = (time.perf_counter() - start) * 1000
        logger.error("Router error for %s: %s", url, exc)
        return _error_result(url, f"Router error: {exc}", elapsed)

    result.fetch_time_ms = (time.perf_counter() - start) * 1000
    return result

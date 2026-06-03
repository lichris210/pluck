"""
Routes fortress/auth-gated URLs to Apify actors and returns a FetchResult.

Actor routing:
  1. Path-pattern match within a known domain (e.g. /jobs/ on linkedin.com)
  2. Domain _default actor
  3. Generic web-scraper fallback for unknown domains
"""

import logging
from urllib.parse import urlparse

from apify_client import ApifyClientAsync

from pluck.models import FetchResult
from pluck.registry.shaper import apply_shape

logger = logging.getLogger(__name__)

_DEFAULT_MAX_ITEMS = 100
_DEFAULT_TIMEOUT_SECS = 300

# { bare_domain: { path_pattern | "_default": actor_id } }
_ACTOR_MAP: dict[str, dict[str, str]] = {
    "linkedin.com": {
        "/jobs/": "curious_coder/linkedin-jobs-scraper",
        "/in/": "anchor/linkedin-profile-scraper",
        "/company/": "anchor/linkedin-company-scraper",
        "_default": "anchor/linkedin-profile-scraper",
    },
    "instagram.com": {
        "_default": "apify/instagram-profile-scraper",
    },
    "twitter.com": {
        "_default": "apify/twitter-scraper",
    },
    "x.com": {
        "_default": "apify/twitter-scraper",
    },
    "facebook.com": {
        "_default": "apify/facebook-posts-scraper",
    },
    "amazon.com": {
        "_default": "junglee/amazon-crawler",
    },
    "stockx.com": {
        "_default": "misceres/stockx-scraper",
    },
}

_GENERIC_ACTOR = "apify/web-scraper"


def _run_cost_usd(run: dict) -> float | None:
    """Best-effort read of the run's billed cost in USD.

    Apify run objects expose this under one of a few keys depending on
    client/account; check them in order. Returns None if none are present
    (callers should treat that as 'unknown', not zero).
    """
    for key in ("usageTotalUsd", "usageUsd"):
        val = run.get(key)
        if isinstance(val, (int, float)):
            return float(val)
    usage = run.get("usage")
    if isinstance(usage, dict):
        for key in ("USD_TOTAL", "totalUsd", "usageTotalUsd"):
            val = usage.get(key)
            if isinstance(val, (int, float)):
                return float(val)
    return None


def resolve_actor(url: str) -> str:
    """Return the Apify actor ID best suited for *url*."""
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]

    domain_actors = _ACTOR_MAP.get(domain)
    if not domain_actors:
        return _GENERIC_ACTOR

    for pattern, actor_id in domain_actors.items():
        if pattern != "_default" and pattern in parsed.path:
            return actor_id

    return domain_actors.get("_default", _GENERIC_ACTOR)


def _build_actor_input(url: str, actor_id: str, max_items: int) -> dict:
    """Build the run_input dict for the given actor and URL."""
    if actor_id == "anchor/linkedin-profile-scraper":
        return {"profileUrls": [url], "maxItems": max_items}
    if actor_id == "curious_coder/linkedin-jobs-scraper":
        return {"urls": [url], "maxItems": max_items}
    if actor_id == "anchor/linkedin-company-scraper":
        return {"companyUrls": [url], "maxItems": max_items}
    if actor_id == "apify/instagram-profile-scraper":
        parts = urlparse(url).path.strip("/").split("/")
        username = parts[0] if parts and parts[0] else "unknown"
        return {"usernames": [username], "resultsLimit": max_items}
    if actor_id in ("apify/twitter-scraper", "apify/facebook-posts-scraper"):
        return {"startUrls": [{"url": url}], "maxItems": max_items}
    if actor_id == "junglee/amazon-crawler":
        return {"startUrls": [{"url": url}], "maxItems": max_items}
    if actor_id == "misceres/stockx-scraper":
        parts = urlparse(url).path.strip("/").split("/")
        search = parts[-1].replace("-", " ") if parts and parts[-1] else ""
        return {"search": search, "maxItems": max_items}
    # Generic web-scraper fallback
    return {"startUrls": [{"url": url}], "maxPagesPerCrawl": 5}


async def _run_actor(
    url: str,
    actor_id: str,
    run_input: dict,
    apify_token: str,
    max_items: int,
    timeout_secs: int,
    shape: dict | None = None,
) -> FetchResult:
    """Call *actor_id* with *run_input*, read its dataset, return a FetchResult.

    Shared body for both the legacy (resolve_actor) and plan-driven paths. When
    *shape* is provided, dataset rows are passed through ``apply_shape`` before
    becoming ``structured_data``; otherwise the raw items are returned as-is.
    """
    try:
        client = ApifyClientAsync(apify_token)
        run = await client.actor(actor_id).call(
            run_input=run_input,
            max_items=max_items,
            timeout_secs=timeout_secs,
        )

        if run is None:
            return FetchResult(
                url=url,
                html="",
                fetcher_used=f"ApifyActor:{actor_id}",
                fetch_time_ms=0.0,
                success=False,
                error=f"Apify actor {actor_id!r} timed out or returned no run",
                metadata={"actor_id": actor_id},
            )

        run_status = run.get("status", "")
        # Hard failures — dataset will be empty or unusable
        if run_status in ("FAILED", "ABORTED", "ABORTING"):
            return FetchResult(
                url=url,
                html="",
                fetcher_used=f"ApifyActor:{actor_id}",
                fetch_time_ms=0.0,
                success=False,
                error=f"Apify actor {actor_id!r} run ended with status {run_status!r}",
                metadata={"actor_id": actor_id, "run_id": run.get("id"), "run_status": run_status},
            )

        # SUCCEEDED or TIMED-OUT — read whatever items are in the dataset
        dataset_id = run["defaultDatasetId"]
        page = await client.dataset(dataset_id).list_items(limit=max_items)
        items = page.items
        structured_data = apply_shape(items, shape) if shape is not None else items

        return FetchResult(
            url=url,
            html="",
            fetcher_used=f"ApifyActor:{actor_id}",
            fetch_time_ms=0.0,
            success=True,
            structured_data=structured_data,
            metadata={
                "actor_id": actor_id,
                "run_id": run["id"],
                "dataset_id": dataset_id,
                "item_count": len(items),
                "run_status": run_status,
                "apify_cost_usd": _run_cost_usd(run),
            },
        )

    except Exception as exc:
        logger.error("Apify fetch failed for %s: %s", url, exc)
        return FetchResult(
            url=url,
            html="",
            fetcher_used=f"ApifyActor:{actor_id}",
            fetch_time_ms=0.0,
            success=False,
            error=f"Apify error: {exc}",
            metadata={"actor_id": actor_id},
        )


async def fetch_via_apify(
    url: str,
    apify_token: str,
    max_items: int = _DEFAULT_MAX_ITEMS,
    timeout_secs: int = _DEFAULT_TIMEOUT_SECS,
) -> FetchResult:
    """Call the appropriate Apify actor for *url* and return a FetchResult."""
    actor_id = resolve_actor(url)
    run_input = _build_actor_input(url, actor_id, max_items)
    logger.info("Apify actor=%s url=%s", actor_id, url)
    return await _run_actor(
        url, actor_id, run_input, apify_token, max_items, timeout_secs
    )


async def fetch_via_apify_plan(
    plan: dict,
    apify_token: str,
    max_items: int = _DEFAULT_MAX_ITEMS,
    timeout_secs: int = _DEFAULT_TIMEOUT_SECS,
) -> FetchResult:
    """Run a planner-produced *plan* and return its shaped rows as a FetchResult.

    Uses ``plan[actor_id]`` + ``plan[actor_input]`` verbatim (the planner already
    substituted URL/username/max_items and clamped the item count), reads the
    dataset, then applies ``plan[output_shape]`` to produce ``structured_data``.
    Metadata mirrors ``fetch_via_apify``.
    """
    actor_id = plan["actor_id"]
    run_input = plan["actor_input"]
    shape = plan.get("output_shape") or {}
    logger.info("Apify (planned) actor=%s", actor_id)
    return await _run_actor(
        url="",
        actor_id=actor_id,
        run_input=run_input,
        apify_token=apify_token,
        max_items=max_items,
        timeout_secs=timeout_secs,
        shape=shape,
    )

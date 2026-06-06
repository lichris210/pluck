"""Apify Store API client + search-query builder for actor discovery (Phase 3).

``search_store`` wraps the public ``GET /v2/store`` endpoint (relevance-sorted,
no auth) and returns normalised actor records. ``build_search_query`` turns a URL
into a search string by pure regex — no LLM call (Decision 2).

Both are tolerant: ``search_store`` never raises, returning ``[]`` on any HTTP or
parse failure, mirroring the never-raise contract of ``registry.planner``.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

_STORE_URL = "https://api.apify.com/v2/store"
_TIMEOUT_SECS = 30.0

# Path prefixes that precede IDs/handles rather than carrying intent (Decision 2).
_STRIP_SEGMENTS = {"p", "view", "search", "dp", "user", "users"}
# An "intent" path word: letters only, 3+ chars (drops IDs like B0XXTEST, 123).
_INTENT_RE = re.compile(r"^[a-z]{3,}$")


def _normalize_item(item: dict) -> dict:
    """Defensively pull the fields discovery cares about from a Store record.

    Store records vary by actor; read each key with .get and keep what's present.
    """
    stats = item.get("stats") if isinstance(item.get("stats"), dict) else {}
    username = item.get("username")
    name = item.get("name")
    # actor_id is conventionally "username/name"
    actor_id = item.get("id")
    if not actor_id and username and name:
        actor_id = f"{username}/{name}"
    return {
        "actor_id": actor_id,
        "name": name,
        "username": username,
        "title": item.get("title"),
        "readme": item.get("readme"),
        "readmeSummary": item.get("readmeSummary"),
        "totalUsers30Days": (
            item.get("totalUsers30Days") or stats.get("totalUsers30Days")
        ),
        "lastRunStartedAt": (
            item.get("lastRunStartedAt") or stats.get("lastRunStartedAt")
        ),
        "pricingInfo": item.get("pricingInfo"),
    }


async def search_store(query: str, *, limit: int = 10, client=None) -> list[dict]:
    """Return up to *limit* relevance-ranked actor records for *query*.

    No auth header — the Store endpoint is public. Returns ``[]`` on any HTTP
    error or malformed body; never raises. Pass *client* (an httpx.AsyncClient or
    a test double exposing async ``get``) to inject a connection.
    """
    params = {"search": query, "sortBy": "relevance", "limit": limit}
    try:
        if client is None:
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECS) as c:
                resp = await c.get(_STORE_URL, params=params)
        else:
            resp = await client.get(_STORE_URL, params=params)
        resp.raise_for_status()
        body = resp.json()
    except Exception as exc:  # httpx errors, JSON decode, anything
        logger.warning("Store API search failed for %r: %s", query, exc)
        return []

    items = (body or {}).get("data", {}).get("items")
    if not isinstance(items, list):
        return []
    return [_normalize_item(it) for it in items if isinstance(it, dict)]


def build_search_query(url: str) -> str:
    """Build a Store search query from *url* by pure regex (Decision 2).

    Domain stem (``linkedin`` from linkedin.com) plus, for multi-segment paths,
    the first non-stripped intent-bearing path segment (``jobs`` from
    linkedin.com/jobs/view/123). A bare single-segment path is treated as a handle
    (instagram.com/natgeo → ``instagram``), and ID-like segments after a stripped
    prefix contribute nothing (amazon.com/dp/B0XXTEST → ``amazon``).
    """
    if "://" not in url:
        url = "https://" + url
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    labels = [p for p in host.split(".") if p]
    stem = labels[-2] if len(labels) >= 2 else (labels[0] if labels else "")

    terms = [stem] if stem else []

    segments = [s for s in parsed.path.strip("/").split("/") if s]
    # Only a multi-segment path signals a section (intent); a lone segment is a handle.
    if len(segments) >= 2:
        for seg in segments:
            low = seg.lower()
            if low in _STRIP_SEGMENTS:
                continue
            if _INTENT_RE.match(low):
                terms.append(low)
            break  # only the first non-stripped segment is considered

    return " ".join(terms)

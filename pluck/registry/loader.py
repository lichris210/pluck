"""Load and host-filter the curated Apify actor registry.

The planner is shown only the registry entries whose ``domain_patterns`` match
the URL host: code does the filtering, the LLM does the intent matching.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

_REGISTRY_PATH = Path(__file__).with_name("apify_actors.json")


@lru_cache(maxsize=1)
def load_registry() -> list[dict]:
    """Return the parsed registry, loaded from disk once and cached."""
    with _REGISTRY_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def _normalize_host(host: str) -> str:
    """Lowercase the host and strip a leading ``www.`` (mirrors resolve_actor)."""
    host = host.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def _tier1_candidates(host: str) -> list[dict]:
    """Hardcoded-registry (tier 1) entries whose domain_patterns match *host*."""
    return [
        entry
        for entry in load_registry()
        if any(
            _normalize_host(pattern) == host
            for pattern in entry.get("domain_patterns", [])
        )
    ]


def _get_store():
    """Return the shared SchemaCacheStore singleton used by the API.

    Imported lazily so the loader has no import-time dependency on the store (and
    so tests that never touch tier 2 don't open the real pluck_cache.db).
    """
    from api.routes import _schema_cache

    return _schema_cache


def get_candidates(host: str, store=None) -> list[dict]:
    """Return the union of tier 1 (hardcoded JSON) and tier 2 (discovered SQLite).

    *host* is expected to be already normalized (lowercase, no ``www.``). Tier-2
    entries are read live from *store* (default: the shared singleton); on any
    error tier 2 is skipped so tier-1 routing never breaks. De-duped by actor_id
    with tier 1 winning on conflict.
    """
    tier1 = _tier1_candidates(host)

    try:
        store = store if store is not None else _get_store()
        tier2 = store.get_discovered(host)
    except Exception:  # missing store, DB error — tier 1 must still work
        tier2 = []

    seen = {e.get("actor_id") for e in tier1}
    union = list(tier1)
    for entry in tier2:
        if entry.get("actor_id") not in seen:
            union.append(entry)
            seen.add(entry.get("actor_id"))
    return union


def candidates_for_url(url: str, store=None) -> list[dict]:
    """Extract and normalize the host from *url*, then return its candidates."""
    host = _normalize_host(urlparse(url).netloc)
    return get_candidates(host, store=store)


def find_entry(actor_id: str, candidates: list[dict]) -> dict | None:
    """Return the candidate matching *actor_id*, or None if absent."""
    for entry in candidates:
        if entry.get("actor_id") == actor_id:
            return entry
    return None

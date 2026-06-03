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


def get_candidates(host: str) -> list[dict]:
    """Return registry entries whose domain_patterns match *host*.

    *host* is expected to be already normalized (lowercase, no ``www.``).
    """
    return [
        entry
        for entry in load_registry()
        if any(
            _normalize_host(pattern) == host
            for pattern in entry.get("domain_patterns", [])
        )
    ]


def candidates_for_url(url: str) -> list[dict]:
    """Extract and normalize the host from *url*, then return its candidates."""
    host = _normalize_host(urlparse(url).netloc)
    return get_candidates(host)


def find_entry(actor_id: str, candidates: list[dict]) -> dict | None:
    """Return the candidate matching *actor_id*, or None if absent."""
    for entry in candidates:
        if entry.get("actor_id") == actor_id:
            return entry
    return None

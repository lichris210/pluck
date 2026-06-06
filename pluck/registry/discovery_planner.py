"""Rank discovered Store candidates with Haiku and capture a real output schema.

``discover_actor`` mirrors ``registry.planner``'s discipline (one Haiku call,
content-block iteration, ``repair_and_parse``, retry-once-strict, never raise): it
turns filtered Store candidates into a single registry-shaped entry the existing
planner can consume. ``capture_output_schema`` then runs the chosen actor once with
``maxItems=1`` to read the real column names (Decision 1), and
``apply_captured_schema`` folds them into the entry.
"""

from __future__ import annotations

import json
import logging
from urllib.parse import urlparse

from apify_client import ApifyClientAsync

from pluck.extraction.json_repair import repair_and_parse
from pluck.registry.planner import _substitute_template

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-haiku-4-5"
_MAX_TOKENS = 1024

DISCOVERY_SYSTEM = (
    "You are an actor-discovery planner for Pluck.ai. Given a URL, a user's "
    "natural-language prompt, and a list of Apify Store actors (each with an "
    "actor_id, title, and readme summary), pick the single best actor for the "
    "task and write a registry entry for it.\n\n"
    "Output a single JSON object:\n"
    "{\n"
    '  "actor_id": "<one of the candidates\' actor_id values, verbatim>",\n'
    '  "intent_description": "<one sentence: what this actor returns>",\n'
    '  "input_template": {<actor input with {url}, {username}, or {max_items} '
    "placeholders>},\n"
    '  "input_notes": "<short note on the input shape>",\n'
    '  "row_unit": "<what one output row represents, e.g. post, product, job>",\n'
    '  "default_columns": [<best-guess column names>],\n'
    '  "all_columns": [<best-guess column names>],\n'
    '  "reasoning": "<one sentence: why this actor matches the prompt>"\n'
    "}\n\n"
    "Rules:\n"
    "- actor_id MUST be copied verbatim from one of the candidates.\n"
    "- Use {url} for a full-URL input, {username} for a handle, {max_items} for a "
    "result cap. The real values are substituted later by code.\n"
    "- Columns are a best guess; the real schema is captured separately.\n"
    "- Return ONLY the JSON object: no prose, no markdown fences."
)

_STRICT_SUFFIX = (
    "\n\nIMPORTANT: your previous response could not be parsed. Return ONLY a "
    "single, strictly valid JSON object — no prose, no fences. Copy actor_id "
    "verbatim from the candidates."
)


def _candidate_view(candidates: list[dict]) -> list[dict]:
    keep = ("actor_id", "title", "readmeSummary", "readme")
    view = []
    for c in candidates:
        entry = {k: c[k] for k in keep if c.get(k)}
        # Trim long readmes so the prompt stays small.
        if isinstance(entry.get("readme"), str) and len(entry["readme"]) > 600:
            entry["readme"] = entry["readme"][:600]
        view.append(entry)
    return view


def _host(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def _request(client, model, url, prompt, candidates, strict):
    system = DISCOVERY_SYSTEM + (_STRICT_SUFFIX if strict else "")
    user = (
        f"url: {url}\n"
        f"prompt: {prompt}\n\n"
        "candidates:\n"
        f"{json.dumps(_candidate_view(candidates), indent=2)}\n\n"
        "Return the registry entry as a single JSON object."
    )
    try:
        response = client.messages.create(
            model=model,
            max_tokens=_MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
    except Exception as exc:
        logger.warning("Discovery planner API call failed: %s", exc)
        return None

    text = ""
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            text += block.text
    parsed = repair_and_parse(text)
    return parsed[0] if parsed else None


def discover_actor(
    url: str,
    prompt: str,
    candidates: list[dict],
    client,
    model: str = DEFAULT_MODEL,
) -> dict | None:
    """Rank *candidates* with Haiku, returning a registry-shaped entry or None.

    One Haiku call; parse; validate the chosen actor_id is a real candidate. Retry
    once with a stricter prompt, then give up (None). Never raises. The returned
    entry carries ``source="discovered"`` and code-derived ``domain_patterns``.
    """
    if not candidates:
        return None

    valid_ids = {c.get("actor_id") for c in candidates}
    host = _host(url)

    for strict in (False, True):
        raw = _request(client, model, url, prompt, candidates, strict)
        if not isinstance(raw, dict):
            continue
        actor_id = raw.get("actor_id")
        if actor_id not in valid_ids:
            continue
        template = raw.get("input_template")
        if not isinstance(template, dict) or not template:
            continue
        return {
            "domain_patterns": [host],
            "actor_id": actor_id,
            "intent_description": raw.get("intent_description", ""),
            "input_template": template,
            "input_notes": raw.get("input_notes", ""),
            "row_unit": raw.get("row_unit", "item"),
            "default_columns": list(raw.get("default_columns") or []),
            "all_columns": list(raw.get("all_columns") or []),
            "is_default": True,
            "source": "discovered",
            "reasoning": raw.get("reasoning", ""),
        }

    return None


async def capture_output_schema(
    entry: dict,
    apify_token: str,
    url: str,
    *,
    timeout_secs: int = 120,
) -> list[str]:
    """Run the entry's actor once with maxItems=1 and return the row's keys.

    Decision 1: pay ~$0.003 once to learn the real output schema. Returns [] on any
    failure (no run, empty dataset, error) — never raises; the caller keeps the
    readme-guessed columns in that case.
    """
    actor_id = entry.get("actor_id")
    template = entry.get("input_template") or {}
    run_input = _substitute_template(template, url, 1)
    try:
        client = ApifyClientAsync(apify_token)
        run = await client.actor(actor_id).call(
            run_input=run_input, max_items=1, timeout_secs=timeout_secs
        )
        if not run or run.get("status") in ("FAILED", "ABORTED", "ABORTING"):
            return []
        page = await client.dataset(run["defaultDatasetId"]).list_items(limit=1)
        items = page.items
        if items and isinstance(items[0], dict):
            return list(items[0].keys())
        return []
    except Exception as exc:
        logger.warning("Schema capture failed for %s: %s", actor_id, exc)
        return []


def apply_captured_schema(entry: dict, columns: list[str]) -> dict:
    """Fill default_columns/all_columns from captured *columns* (if any).

    Returns a shallow copy with the columns set when *columns* is non-empty;
    otherwise the entry's readme-guessed columns are left untouched.
    """
    if not columns:
        return entry
    updated = dict(entry)
    updated["all_columns"] = list(columns)
    updated["default_columns"] = list(columns)
    return updated

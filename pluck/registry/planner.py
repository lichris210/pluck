"""Intent-aware Apify routing: one Haiku call that turns a URL + prompt into a
validated execution Plan.

Given the URL, the user's natural-language prompt, a hard ``max_items`` ceiling,
and the registry candidates whose ``domain_patterns`` already match the host
(filtered by the caller — see ``registry.loader``), the planner asks Haiku to
pick the best actor and shape the output, then validates the result before
returning ``{actor_id, actor_input, output_shape, reasoning}``.

Locked decisions baked in here:
  1. Ambiguous prompt or failed validation -> fall back to the candidate with
     ``is_default`` true for the host.
  2. ``max_items`` from the caller is a hard ceiling. The planner may LOWER it
     when the prompt is explicit ("top 5"); any value above the ceiling is
     clamped back down during validation.
  3. Unparseable / invalid JSON -> retry once with a stricter prompt, then fall
     back to the default candidate. Never raise.
  4. ``output_shape.columns`` default to the candidate's ``default_columns``;
     ``rename`` is optional.

The URL/username/max_items placeholder substitution is done deterministically
in Python (``_substitute_template``) — the model is never trusted to edit URL
strings. It only chooses the actor, the columns, and (optionally) a lower item
count.

Style mirrors ``pluck/curation/prompt_spec.py``: a module-level system constant,
``_build_prompt``, ``messages.create``, content-block iteration, and
``repair_and_parse``. Like that module, ``plan_extraction`` never raises.
"""

from __future__ import annotations

import json
import logging
from urllib.parse import urlparse

from pluck.extraction.json_repair import repair_and_parse
from pluck.registry.loader import find_entry

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-haiku-4-5"
_MAX_TOKENS = 1024

# Actor-input keys that cap the number of returned rows. Clamped to the ceiling.
_LIMIT_KEYS = ("maxItems", "resultsLimit", "max_items", "count", "maxItemsPerStartUrl")

# Limit-field names discovered at runtime from real actor input schemas (Issue 2).
# Discovered actors can use non-standard limit fields (e.g. ``resultsPerPage``);
# registering one here lets the proposed-limit read and the ceiling clamp recognise it.
_DYNAMIC_LIMIT_KEYS: set[str] = set()


def register_limit_key(name: str) -> None:
    """Register *name* as a row-count limit field for clamp/LOWER-only handling."""
    if name and name not in _LIMIT_KEYS:
        _DYNAMIC_LIMIT_KEYS.add(name)


def _limit_keys() -> tuple[str, ...]:
    """All known limit-field names: the static set plus runtime-registered ones."""
    return _LIMIT_KEYS + tuple(_DYNAMIC_LIMIT_KEYS)


PLANNER_SYSTEM = (
    "You are a routing planner for Pluck.ai. Given a URL and a user's "
    "natural-language prompt, you select the best Apify actor from a provided "
    "registry and produce a complete execution plan.\n\n"
    "You will receive:\n"
    "- url: the URL to scrape\n"
    "- prompt: the user's intent in natural language\n"
    "- max_items: the hard ceiling on result count\n"
    "- candidates: registry entries whose domain_patterns match the URL\n\n"
    "Output a single JSON object:\n"
    "{\n"
    '  "actor_id": "<one of candidates[].actor_id>",\n'
    '  "actor_input": <filled-in input_template from the chosen candidate>,\n'
    '  "output_shape": {\n'
    '    "explode_field": <null or a field name to promote to rows>,\n'
    '    "columns": [<ordered column names to keep>],\n'
    '    "rename": {<optional old_name: new_name map>}\n'
    "  },\n"
    '  "reasoning": "<one sentence: why this actor matches the prompt>"\n'
    "}\n\n"
    "Rules:\n"
    "- Pick the actor whose intent_description best matches the prompt.\n"
    "- For columns, start from the candidate's default_columns; add or remove "
    "based on what the user asked for. If the user says 'all fields', use "
    "all_columns. Choose column names verbatim from the candidate.\n"
    "- explode_field is null unless the actor returns a nested array that must "
    "be promoted to rows (e.g. instagram-profile-scraper's latestPosts).\n"
    "- max_items is a ceiling: keep it, or LOWER it when the prompt is explicit "
    "(e.g. 'top 5'). Never raise it above the ceiling.\n"
    "- Never invent actor_ids or column names not present in a candidate.\n"
    "- Return ONLY the JSON object: no prose, no markdown fences."
)

_STRICT_SUFFIX = (
    "\n\nIMPORTANT: your previous response could not be parsed. Return ONLY a "
    "single, strictly valid JSON object — no prose, no markdown fences, no "
    "trailing commas. Choose actor_id verbatim from the candidates."
)


def _candidate_view(candidates: list[dict]) -> list[dict]:
    """Trim registry entries to the fields the planner needs to decide.

    Drops routing-only fields (``domain_patterns``, ``is_default``) so the model
    sees just intent, input shape, and column vocabulary.
    """
    keep = (
        "actor_id",
        "intent_description",
        "input_template",
        "input_notes",
        "row_unit",
        "default_columns",
        "all_columns",
    )
    return [{k: entry[k] for k in keep if k in entry} for entry in candidates]


def _build_prompt(
    url: str, prompt: str, max_items: int, candidates: list[dict]
) -> str:
    return (
        f"url: {url}\n"
        f"prompt: {prompt}\n"
        f"max_items: {max_items}\n\n"
        "candidates:\n"
        f"{json.dumps(_candidate_view(candidates), indent=2)}\n\n"
        "Return the execution plan as a single JSON object — no prose, no "
        "markdown fences."
    )


def _strip_url(url: str) -> str:
    """Strip trailing slashes; the model is never asked to edit URL strings."""
    return url.rstrip("/") if url else url


def _extract_username(url: str) -> str:
    """First path segment of *url* — the handle for usernames[] actors.

    Mirrors the extraction in ``fetchers.apify_handler._build_actor_input``.
    """
    path = urlparse(url).path.strip("/")
    if not path:
        return "unknown"
    return path.split("/")[0]


def _substitute_template(template: dict, url: str, max_items: int) -> dict:
    """Recursively fill ``{url}``, ``{username}``, ``{max_items}`` placeholders.

    ``{max_items}`` becomes an int; the others become strings. Substitution is
    deterministic and code-controlled — the model's own ``actor_input`` is never
    trusted to carry the real URL.
    """
    clean_url = _strip_url(url)
    username = _extract_username(url)

    def sub(value):
        if isinstance(value, dict):
            return {k: sub(v) for k, v in value.items()}
        if isinstance(value, list):
            return [sub(v) for v in value]
        if isinstance(value, str):
            if value == "{max_items}":
                return max_items
            if value == "{url}":
                return clean_url
            if value == "{username}":
                return username
            return (
                value.replace("{url}", clean_url)
                .replace("{username}", username)
                .replace("{max_items}", str(max_items))
            )
        return value

    return sub(template)


def _proposed_limit(actor_input) -> int | None:
    """Return the item-count the model proposed, if any (for LOWER-only intent)."""
    if not isinstance(actor_input, dict):
        return None
    for key in _limit_keys():
        val = actor_input.get(key)
        if isinstance(val, bool):
            continue
        if isinstance(val, int):
            return val
        if isinstance(val, str) and val.lstrip("-").isdigit():
            return int(val)
    return None


def _assemble_plan(
    raw: dict, url: str, candidates: list[dict], max_items: int
) -> dict:
    """Turn the model's raw JSON into a plan with a code-built ``actor_input``.

    The actor choice, columns, rename, and any LOWERED item count come from the
    model; the URL/username substitution is deterministic. When ``actor_id`` is
    not a real candidate the raw plan is returned untouched so validation rejects
    it (triggering retry / fallback).
    """
    actor_id = raw.get("actor_id")
    entry = find_entry(actor_id, candidates)
    if entry is None:
        return raw

    # The model may lower the count; fill the template with its value (NOT yet
    # clamped — validation does the clamping, per Decision 2).
    proposed = _proposed_limit(raw.get("actor_input"))
    fill = proposed if proposed is not None else max_items
    actor_input = _substitute_template(entry.get("input_template", {}), url, fill)

    raw_shape = raw.get("output_shape") or {}
    columns = raw_shape.get("columns") or list(entry.get("default_columns", []))
    shape = {
        "explode_field": raw_shape.get("explode_field"),
        "columns": columns,
        "rename": raw_shape.get("rename") or {},
    }
    return {
        "actor_id": actor_id,
        "actor_input": actor_input,
        "output_shape": shape,
        "reasoning": raw.get("reasoning", ""),
    }


def _validate_plan(
    plan: dict, candidates: list[dict], max_items: int
) -> dict | None:
    """Validate an assembled plan in place; return it, or None to trigger fallback.

    - ``actor_id`` must name a real candidate.
    - ``actor_input`` must populate every key in that candidate's input_template.
    - Item-count keys are clamped down to ``max_items`` (the hard ceiling).
    - ``output_shape.columns`` are intersected with the candidate's all_columns;
      unknown names are dropped (and logged). Empty -> default_columns.
    """
    if not isinstance(plan, dict):
        return None

    entry = find_entry(plan.get("actor_id"), candidates)
    if entry is None:
        logger.info(
            "Plan validation: actor_id=%r not in candidates -> reject (fallback)",
            plan.get("actor_id"),
        )
        return None

    actor_input = plan.get("actor_input")
    if not isinstance(actor_input, dict):
        return None

    template = entry.get("input_template", {})
    for key in template:
        if key not in actor_input:
            logger.warning(
                "Planner actor_input missing required key %r for %s",
                key,
                entry.get("actor_id"),
            )
            return None

    # Decision 2: clamp any item count above the ceiling back down.
    clamped = False
    limit_keys = _limit_keys()
    for key, value in actor_input.items():
        if (
            key in limit_keys
            and isinstance(value, int)
            and not isinstance(value, bool)
            and value > max_items
        ):
            logger.info(
                "Clamping %s from %d to ceiling %d", key, value, max_items
            )
            actor_input[key] = max_items
            clamped = True

    all_columns = entry.get("all_columns", [])
    shape = plan.get("output_shape") or {}
    proposed_cols = shape.get("columns") or []
    valid = [c for c in proposed_cols if c in all_columns]
    extras = [c for c in proposed_cols if c not in all_columns]
    if extras:
        logger.warning("Dropping unknown planner columns: %s", extras)
    if not valid:
        valid = list(entry.get("default_columns", []))
    shape["columns"] = valid
    plan["output_shape"] = shape

    logger.info(
        "Plan validation passed: actor_id=%s in_candidates=True valid_columns=%d "
        "dropped_columns=%d clamped=%s",
        entry.get("actor_id"), len(valid), len(extras), clamped,
    )
    return plan


def _default_plan(
    candidates: list[dict], url: str, max_items: int
) -> dict | None:
    """Decision 1: deterministic plan from the ``is_default`` candidate.

    Falls back to the first candidate if none is flagged default. Returns None
    only when there are no candidates at all.
    """
    entry = next((c for c in candidates if c.get("is_default")), None)
    if entry is None:
        entry = candidates[0] if candidates else None
    if entry is None:
        return None

    actor_input = _substitute_template(
        entry.get("input_template", {}), url, max_items
    )
    return {
        "actor_id": entry["actor_id"],
        "actor_input": actor_input,
        "output_shape": {
            "explode_field": None,
            "columns": list(entry.get("default_columns", [])),
            "rename": {},
        },
        "reasoning": "Defaulted to this domain's primary actor.",
    }


def _request_plan(
    client,
    model: str,
    url: str,
    prompt: str,
    max_items: int,
    candidates: list[dict],
    strict: bool,
) -> dict | None:
    """One Haiku call -> parsed plan dict, or None on API/parse failure."""
    system = PLANNER_SYSTEM + (_STRICT_SUFFIX if strict else "")
    user_prompt = _build_prompt(url, prompt, max_items, candidates)

    try:
        response = client.messages.create(
            model=model,
            max_tokens=_MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except Exception as exc:
        logger.warning("Planner API call failed: %s", exc)
        return None

    text = ""
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            text += block.text

    parsed = repair_and_parse(text)
    if not parsed:
        return None
    return parsed[0]


def plan_extraction(
    url: str,
    prompt: str,
    max_items: int,
    candidates: list[dict],
    client,
    model: str = DEFAULT_MODEL,
) -> dict | None:
    """Plan the Apify run for *url* + *prompt* against *candidates*.

    One Haiku call; parse; assemble a code-built actor_input; validate. On any
    failure retry once with a stricter prompt, then fall back to the host's
    ``is_default`` candidate (Decisions 1 & 3). Never raises.

    Returns the Plan dict ``{actor_id, actor_input, output_shape, reasoning}``,
    or None only when *candidates* is empty (no Apify route for this host).
    """
    if not candidates:
        return None

    for strict in (False, True):
        raw = _request_plan(
            client, model, url, prompt, max_items, candidates, strict
        )
        if raw is None:
            continue
        assembled = _assemble_plan(raw, url, candidates, max_items)
        validated = _validate_plan(assembled, candidates, max_items)
        if validated is not None:
            return validated

    return _default_plan(candidates, url, max_items)

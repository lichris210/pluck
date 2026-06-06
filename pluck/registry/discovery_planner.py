"""Single-pass actor discovery: fetch live input schemas, then one Haiku call.

``discover_actor`` fetches the real input JSON-schemas of the top candidates in
parallel, passes them (simplified) into a single Haiku call, and returns a
validated entry whose ``input_template`` uses only real schema fields with every
required field present. ``capture_output_schema`` then runs the chosen actor once
with ``maxItems=1`` to read the real column names, and ``apply_captured_schema``
folds them into the entry.
"""

from __future__ import annotations

import asyncio
import json
import logging
from urllib.parse import urlparse

import httpx
from apify_client import ApifyClientAsync

from pluck.extraction.json_repair import repair_and_parse
from pluck.registry.planner import _substitute_template, register_limit_key

logger = logging.getLogger(__name__)

_APIFY_API = "https://api.apify.com/v2"
_SCHEMA_TIMEOUT = 15.0

DEFAULT_MODEL = "claude-haiku-4-5"
_MAX_TOKENS = 1024

# Bump when discover_actor's logic changes in a way that invalidates cached entries.
DISCOVERY_LOGIC_VERSION = 2

DISCOVERY_SYSTEM = (
    "You are an actor-discovery planner for Pluck.ai. You are given a URL, the "
    "user's intent, and up to three candidate Apify actors. Each candidate has an "
    "actor_id, a title, a README excerpt, and its real input JSON-schema (or the "
    "string '[schema unavailable]').\n\n"
    "Pick the single candidate whose input schema and README best fit the URL shape "
    "and the user's intent, then build a valid input_template for it.\n\n"
    "Output ONE JSON object:\n"
    "{\n"
    '  "actor_id": "<chosen candidate actor_id, verbatim>",\n'
    '  "rationale": "<one sentence: why this actor and schema fit>",\n'
    '  "input_template": {<field: value, using ONLY property names from the chosen '
    "candidate's schema.properties>},\n"
    '  "limit_field": "<the schema property that caps the number of returned rows, '
    'or null>"\n'
    "}\n\n"
    "Rules:\n"
    "- Use ONLY property names that appear in the chosen candidate's "
    "schema.properties. Do not invent fields.\n"
    "- Include EVERY field listed in the chosen schema's 'required' array.\n"
    "- Placeholders are substituted later by code: {url} = the full URL, {username} = "
    "the handle / first path segment, {max_items} = the row cap. Each placeholder MUST "
    'be written as a JSON string in double quotes — "{url}", "{username}", '
    '"{max_items}". NEVER write a bare {max_items}; that is invalid JSON.\n'
    '- Put "{max_items}" (the quoted string) on the field named by limit_field (the '
    "one that caps total returned rows).\n"
    '- For a proxy / proxyConfiguration field use {"useApifyProxy": true}.\n'
    "- Choose the placeholder that matches each field's purpose: a profile/account "
    'field gets "{url}" or ["{username}"]; a search field gets the search term; a '
    'start-URL field gets "{url}".\n'
    '- Example input_template: {"profiles": ["{username}"], "resultsPerPage": '
    '"{max_items}", "proxyConfiguration": {"useApifyProxy": true}}\n'
    "- Return ONLY the JSON object: no prose, no markdown fences."
)


def _host(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


# ── live input-schema fetch ───────────────────────────────────────────────────

def _coerce_schema(value) -> dict:
    """Return a schema dict from a JSON string or dict; {} otherwise."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return {}
    return value if isinstance(value, dict) else {}


async def _get_json(client, url: str, params: dict):
    try:
        if client is None:
            async with httpx.AsyncClient(timeout=_SCHEMA_TIMEOUT) as c:
                resp = await c.get(url, params=params)
        else:
            resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("Actor schema GET %s failed: %s", url, exc)
        return None


async def fetch_actor_input_schema(actor_id: str, token: str | None = None, client=None) -> dict:
    """Fetch *actor_id*'s input JSON-schema (``{properties, required, ...}``).

    Reads the actor object; if the schema isn't inline, follows the latest build.
    Auth is optional (public actors), but a token raises rate limits. Returns {} on
    any failure — never raises.
    """
    path_id = (actor_id or "").replace("/", "~")
    params = {"token": token} if token else {}

    actor = await _get_json(client, f"{_APIFY_API}/acts/{path_id}", params)
    data = (actor or {}).get("data", {}) if isinstance(actor, dict) else {}

    schema = _coerce_schema(data.get("inputSchema"))
    if schema:
        return schema

    build_id = ((data.get("taggedBuilds") or {}).get("latest") or {}).get("buildId")
    if not build_id:
        return {}
    build = await _get_json(client, f"{_APIFY_API}/acts/{path_id}/builds/{build_id}", params)
    bdata = (build or {}).get("data", {}) if isinstance(build, dict) else {}
    return _coerce_schema(bdata.get("inputSchema"))


def _simplify_schema(schema: dict) -> dict:
    """Trim an input schema to ``{required, properties:{name:{type,title?,...}}}``.

    Keeps only type/title/description/editor per property (description truncated to
    120 chars); drops examples, prefill, defaults, sectionCaptions, etc. Returns {}
    for malformed input. Pure function, no I/O.
    """
    if not isinstance(schema, dict):
        return {}
    props = schema.get("properties")
    if not isinstance(props, dict):
        return {}

    simple_props: dict = {}
    for name, spec in props.items():
        if not isinstance(spec, dict):
            continue
        kept: dict = {}
        if "type" in spec:
            kept["type"] = spec["type"]
        if spec.get("title"):
            kept["title"] = spec["title"]
        desc = spec.get("description")
        if isinstance(desc, str) and desc:
            kept["description"] = desc[:120]
        if spec.get("editor"):
            kept["editor"] = spec["editor"]
        simple_props[name] = kept

    required = schema.get("required")
    required = list(required) if isinstance(required, list) else []
    return {"required": required, "properties": simple_props}


async def _fetch_schemas_parallel(actor_ids: list[str], token: str | None) -> dict[str, dict]:
    """Fetch and simplify the input schemas of *actor_ids* concurrently.

    Returns ``{actor_id: simplified_schema}``; actors whose fetch failed or returned
    an unusable schema are omitted (with a warning).
    """
    results = await asyncio.gather(
        *[fetch_actor_input_schema(aid, token) for aid in actor_ids],
        return_exceptions=True,
    )
    out: dict[str, dict] = {}
    for aid, res in zip(actor_ids, results):
        if isinstance(res, Exception):
            logger.warning("Schema fetch for %s raised: %s; omitting", aid, res)
            continue
        simplified = _simplify_schema(res)
        if not simplified:
            logger.warning("Schema fetch for %s returned no usable schema; omitting", aid)
            continue
        out[aid] = simplified
    return out


# ── single-pass Haiku discovery ───────────────────────────────────────────────

def _discovery_payload(candidates: list[dict], schemas: dict[str, dict]) -> list[dict]:
    """Per-candidate payload for the Haiku call: id, title, README excerpt, schema."""
    payload = []
    for c in candidates:
        aid = c.get("actor_id")
        readme = c.get("readmeSummary") or c.get("readme") or ""
        if isinstance(readme, str) and len(readme) > 800:  # ~200 tokens
            readme = readme[:800]
        payload.append({
            "actor_id": aid,
            "title": c.get("title"),
            "readme": readme,
            "schema": schemas.get(aid, "[schema unavailable]"),
        })
    return payload


def _request_single(client, model, url, prompt, payload):
    """One Haiku call → parsed dict, or None on API/parse failure."""
    user = (
        f"url: {url}\n"
        f"prompt: {prompt}\n\n"
        "candidates:\n"
        f"{json.dumps(payload, indent=2)}\n\n"
        "Return the single JSON object described in the system prompt."
    )
    try:
        response = client.messages.create(
            model=model,
            max_tokens=_MAX_TOKENS,
            system=DISCOVERY_SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
    except Exception as exc:
        logger.warning("Discovery Haiku call failed: %s", exc)
        return None

    text = ""
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            text += block.text
    parsed = repair_and_parse(text)
    logger.info(
        "Discovery ranking call: candidates_in=%d json_parsed=%s",
        len(payload), bool(parsed),
    )
    if not parsed:
        logger.warning(
            "Discovery Haiku response unparseable (len=%d): %r", len(text), text[:600]
        )
    return parsed[0] if parsed else None


async def discover_actor(
    url: str,
    prompt: str,
    candidates: list[dict],
    client,
    model: str = DEFAULT_MODEL,
    apify_token: str | None = None,
) -> dict | None:
    """Pick the best actor and build a schema-valid input_template in one Haiku call.

    Fetches the top-3 candidates' live input schemas in parallel, passes them into a
    single Haiku call, then validates the chosen actor's input_template against its
    real schema. Never raises. Returns a discovered entry (with ``limit_field`` and
    ``logic_version``) or None when discovery should be abandoned.
    """
    if not candidates:
        return None

    top3 = candidates[:3]
    actor_ids = [c.get("actor_id") for c in top3]
    schemas = await _fetch_schemas_parallel(actor_ids, apify_token)
    if not schemas:
        logger.warning(
            "Discovery: all candidate schema fetches failed for %s; abandoning", url
        )
        return None

    raw = _request_single(client, model, url, prompt, _discovery_payload(top3, schemas))
    if not isinstance(raw, dict):
        return None

    actor_id = raw.get("actor_id")
    chosen = schemas.get(actor_id)
    if chosen is None:
        logger.warning(
            "Discovery: chosen actor_id=%r has no usable schema; abandoning", actor_id
        )
        return None

    template = raw.get("input_template")
    if not isinstance(template, dict) or not template:
        return None

    properties = chosen.get("properties", {})
    required = chosen.get("required", [])

    # Drop any field the model invented that isn't a real schema property.
    template = {k: v for k, v in template.items() if k in properties}

    # Every required field must be present; auto-fill only proxy fields.
    for field in required:
        if field in template:
            continue
        spec = properties.get(field, {})
        if "proxy" in field.lower() or spec.get("editor") == "proxy":
            template[field] = {"useApifyProxy": True}
        else:
            logger.warning(
                "Discovery: required field %r missing for %s; abandoning", field, actor_id
            )
            return None

    limit_field = raw.get("limit_field")
    if limit_field and limit_field in properties:
        register_limit_key(limit_field)
        if limit_field not in template:
            template[limit_field] = "{max_items}"
    else:
        limit_field = None

    logger.info(
        "Discovery single-pass: actor_id=%s limit_field=%s template_keys=%s",
        actor_id, limit_field, list(template.keys()),
    )
    return {
        "domain_patterns": [_host(url)],
        "actor_id": actor_id,
        "input_template": template,
        "limit_field": limit_field,
        "intent_description": "",
        "input_notes": "",
        "row_unit": "item",
        # Filled by capture_output_schema after the maxItems=1 probe.
        "default_columns": [],
        "all_columns": [],
        "is_default": True,
        "source": "discovered",
        "reasoning": raw.get("rationale", ""),
        "logic_version": DISCOVERY_LOGIC_VERSION,
    }


# ── output-schema capture (maxItems=1 probe) ──────────────────────────────────

async def capture_output_schema(
    entry: dict,
    apify_token: str,
    url: str,
    *,
    timeout_secs: int = 120,
) -> list[str]:
    """Run the entry's actor once with maxItems=1 and return the row's keys.

    Pay ~$0.003 once to learn the real output schema. Returns [] on any failure (no
    run, thin/empty row, error) — never raises.
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
            logger.info(
                "Schema capture: actor_id=%s run_id=%s status=%s -> rejected",
                actor_id, (run or {}).get("id"), (run or {}).get("status"),
            )
            return []
        page = await client.dataset(run["defaultDatasetId"]).list_items(limit=1)
        items = page.items
        content_ok = bool(items) and isinstance(items[0], dict) and _looks_like_content(items[0])
        logger.info(
            "Schema capture: actor_id=%s run_id=%s items=%d looks_like_content=%s",
            actor_id, run.get("id"), len(items), content_ok,
        )
        if content_ok:
            return list(items[0].keys())
        return []
    except Exception as exc:
        logger.warning("Schema capture failed for %s: %s", actor_id, exc)
        return []


def _looks_like_content(row: dict) -> bool:
    """True when *row* has at least 3 keys with non-empty values."""
    non_empty = [
        k for k, v in row.items()
        if v is not None and v != "" and v != [] and v != {}
    ]
    return len(non_empty) >= 3


def apply_captured_schema(entry: dict, columns: list[str]) -> dict:
    """Fill default_columns/all_columns from captured *columns* (if any)."""
    if not columns:
        return entry
    updated = dict(entry)
    updated["all_columns"] = list(columns)
    updated["default_columns"] = list(columns)
    return updated

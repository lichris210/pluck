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
DISCOVERY_LOGIC_VERSION = 4

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
    "Ranking (which actor to pick):\n"
    "- When the user's prompt implies a LIST of items (verbs like 'list', 'get all', "
    "'scrape'; plurals like 'posts', 'videos', 'reviews', 'jobs'), prefer actors whose "
    "output is ONE ROW PER ITEM over profile-level or aggregate scrapers. Inspect the "
    "actor title/README: phrases like 'per profile', 'profile metadata', 'channel "
    "info' suggest a profile scraper (one aggregate row); phrases like 'each video', "
    "'individual posts', 'list of items' suggest a per-item scraper. For 'get videos' "
    "pick a video scraper, not a profile scraper.\n"
    "- When the prompt asks for profile/account/aggregate info (e.g. 'get bio', "
    "'follower count', 'channel info'), prefer the profile scraper instead.\n\n"
    "Rules:\n"
    "- Use ONLY property names that appear in the chosen candidate's "
    "schema.properties. Do not invent fields.\n"
    "- Match each field's value to its schema shape. For an array field whose items "
    "are objects (schema items.type == 'object', or editor 'requestListSources'), "
    'return [{KEY: "{url}"}], NOT ["{url}"]. Read the field\'s items.properties to find '
    'KEY (usually "url"). Example: a startUrls field with editor "requestListSources" '
    'takes {"startUrls": [{"url": "{url}"}]}, never {"startUrls": ["{url}"]}.\n'
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
        # Keep a minimal items shape for array fields so both the prompt and the
        # input normalizer know whether items are objects (and the object key).
        if spec.get("type") == "array" and isinstance(spec.get("items"), dict):
            items = spec["items"]
            kept_items: dict = {}
            if items.get("type"):
                kept_items["type"] = items["type"]
            iprops = items.get("properties")
            if isinstance(iprops, dict) and iprops:
                kept_items["properties"] = {
                    k: {"type": (v or {}).get("type")} for k, v in iprops.items()
                }
            if kept_items:
                kept["items"] = kept_items
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


# ── user-code filter ──────────────────────────────────────────────────────────

_USER_CODE_EDITORS = {"javascript", "code"}
_USER_CODE_FIELDS = {"pageFunction", "pageFunctionString"}


def _user_code_field(schema: dict) -> tuple[str, str | None] | None:
    """The first REQUIRED field that demands user-written code, or None.

    A field demands user code when its editor is javascript/code or its name is
    pageFunction/pageFunctionString. Optional code fields don't disqualify.
    """
    properties = (schema or {}).get("properties") or {}
    for name in (schema or {}).get("required") or []:
        spec = properties.get(name) or {}
        editor = spec.get("editor") if isinstance(spec, dict) else None
        if editor in _USER_CODE_EDITORS or name in _USER_CODE_FIELDS:
            return name, editor
    return None


def _requires_user_code(schema: dict) -> bool:
    """True when the actor needs human-written extraction code (e.g. pageFunction).

    Generic scrapers (apify/web-scraper, apify/cheerio-scraper, ...) require a
    pageFunction that Pluck cannot template; they must never be selected.
    """
    return _user_code_field(schema) is not None


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


# ── input-template normalization against the real schema (Issue 1) ────────────

def _expects_object_array(schema_entry: dict) -> bool:
    if schema_entry.get("type") != "array":
        return False
    if schema_entry.get("editor") == "requestListSources":
        return True
    items = schema_entry.get("items") or {}
    return isinstance(items, dict) and items.get("type") == "object"


def _expects_string_array(schema_entry: dict) -> bool:
    if schema_entry.get("type") != "array":
        return False
    items = schema_entry.get("items") or {}
    return isinstance(items, dict) and items.get("type") == "string"


def _expects_object(schema_entry: dict) -> bool:
    return schema_entry.get("type") == "object" or schema_entry.get("editor") == "proxy"


def _array_item_key(schema_entry: dict) -> str:
    """The object key for an array-of-objects field; 'url' unless the schema says otherwise."""
    items = schema_entry.get("items") or {}
    props = items.get("properties") if isinstance(items, dict) else None
    if isinstance(props, dict) and props:
        return "url" if "url" in props else next(iter(props))
    return "url"


def _is_proxy_field(name: str, schema_entry: dict) -> bool:
    return "proxy" in (name or "").lower() or schema_entry.get("editor") == "proxy"


def _coerce_field(name: str, value, schema_entry: dict):
    """Reshape *value* to match *schema_entry*. Returns (value, change_desc_or_None)."""
    se = schema_entry or {}

    if _expects_object_array(se):
        if isinstance(value, list) and value and all(isinstance(v, str) for v in value):
            key = _array_item_key(se)
            return [{key: v} for v in value], "string array -> object array"
        return value, None

    if _expects_string_array(se):
        if isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
            out = []
            for v in value:
                s = v.get("url") if "url" in v else next(
                    (x for x in v.values() if isinstance(x, str)), None
                )
                if s is not None:
                    out.append(s)
            if out:
                return out, "object array -> string array"
        return value, None

    if _expects_object(se):
        if isinstance(value, str) and _is_proxy_field(name, se):
            return {"useApifyProxy": True}, "string -> proxy object"
        return value, None

    return value, None


def _normalize_input_template(template: dict, schema: dict) -> dict:
    """Reshape each input_template field to its real schema shape (Issue 1).

    Fixes the common Haiku mismatch of building ``["{url}"]`` for an object-array
    field (``[{"url": "{url}"}]``), and similar. Additive: fields already in the
    right shape, or with no schema entry, pass through unchanged.
    """
    properties = (schema or {}).get("properties", {}) or {}
    out: dict = {}
    for name, value in template.items():
        coerced, change = _coerce_field(name, value, properties.get(name, {}))
        if change:
            logger.info("Normalized input field %s: %s", name, change)
        out[name] = coerced
    return out


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

    # Drop candidates whose schema requires user-written code (pageFunction etc.).
    # Candidates whose schema fetch failed are kept — the capture probe vets them.
    usable = []
    for c in top3:
        aid = c.get("actor_id")
        hit = _user_code_field(schemas[aid]) if aid in schemas else None
        if hit:
            field, editor = hit
            logger.info(
                "Filtered candidate requires user code: actor_id=%s required_field=%s editor=%s",
                aid, field, editor,
            )
            schemas.pop(aid, None)
            continue
        usable.append(c)
    if not usable:
        logger.warning(
            "Discovery: all candidates for %s require user-written code; "
            "cannot proceed, falling back to legacy", url
        )
        return None
    top3 = usable

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

    # Issue 1: reshape fields to match the real schema (e.g. ["{url}"] ->
    # [{"url": "{url}"}]) before the capture probe runs.
    template = _normalize_input_template(template, chosen)

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

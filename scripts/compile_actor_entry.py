"""Compile a draft Apify registry entry for human editing.

Given an actor_id and a sample URL, this tool fetches the actor's input schema
from the Apify API, runs the actor once (maxItems=1), and prints a draft
registry entry to stdout. The draft uses {url}/{username}/{max_items}
placeholders in input_template and copies the sample row's keys into
all_columns. A human trims default_columns, writes intent_description /
input_notes / row_unit, and sets is_default before pasting into
pluck/registry/apify_actors.json.

This is tooling only. It is never imported by application code.

Usage:
    .venv\\Scripts\\python.exe scripts/compile_actor_entry.py \\
        --actor-id apify/instagram-post-scraper \\
        --url https://www.instagram.com/natgeo/

Requires APIFY_TOKEN (read from the environment or a local .env file).
Only the draft JSON object goes to stdout; notes and warnings go to stderr,
so the output pipes cleanly into a JSON parser.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from urllib.parse import urlparse

from dotenv import load_dotenv

# URL-array input fields, in preference order. The first one present in the
# actor's input schema wins. startUrls uses the request-list object shape;
# the others take plain string arrays.
_URL_ARRAY_FIELDS = ["directUrls", "startUrls", "urls", "profileUrls", "companyUrls"]
_OBJECT_URL_FIELDS = {"startUrls"}
_USERNAME_FIELDS = ["usernames", "username"]
_LIMIT_FIELDS = ["resultsLimit", "maxItems", "maxResults", "maxPosts", "limit"]

_URL_PLACEHOLDER = "{url}"
_USERNAME_PLACEHOLDER = "{username}"
_MAX_ITEMS_PLACEHOLDER = "{max_items}"


def _note(msg: str) -> None:
    """Write an informational line to stderr (keeps stdout pure JSON)."""
    print(msg, file=sys.stderr)


def _bare_host(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def _domain_patterns(url: str) -> list[str]:
    bare = _bare_host(url)
    if not bare:
        return []
    return [bare, f"www.{bare}"]


def _username_from_url(url: str) -> str:
    parts = [p for p in urlparse(url).path.strip("/").split("/") if p]
    return parts[0] if parts else "unknown"


def _fetch_input_schema(client, actor_id: str) -> dict | None:
    """Best-effort fetch of the actor's input schema. Returns the schema dict
    (with a "properties" key) or None when unavailable."""
    try:
        build = client.actor(actor_id).default_build().get()
    except Exception as exc:  # network / permissions / no default build
        _note(f"note: could not fetch input schema ({exc}); using fallback template")
        return None

    raw = (build or {}).get("inputSchema")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    if isinstance(raw, dict) and isinstance(raw.get("properties"), dict):
        return raw
    return None


def _build_input_template(schema: dict | None) -> dict:
    """Build a draft input_template with placeholder values. Schema-driven when
    available, otherwise a generic startUrls fallback for human editing."""
    if not schema:
        return {"startUrls": [{"url": _URL_PLACEHOLDER}], "maxItems": _MAX_ITEMS_PLACEHOLDER}

    props = schema.get("properties", {})
    template: dict = {}

    # Username-based actors (e.g. instagram-profile-scraper) take handles, not URLs.
    username_field = next((f for f in _USERNAME_FIELDS if f in props), None)
    url_field = next((f for f in _URL_ARRAY_FIELDS if f in props), None)

    if username_field:
        template[username_field] = [_USERNAME_PLACEHOLDER]
    elif url_field:
        if url_field in _OBJECT_URL_FIELDS:
            template[url_field] = [{"url": _URL_PLACEHOLDER}]
        else:
            template[url_field] = [_URL_PLACEHOLDER]
    else:
        # No recognizable URL/username field — fall back so the human has a base.
        template["startUrls"] = [{"url": _URL_PLACEHOLDER}]

    limit_field = next((f for f in _LIMIT_FIELDS if f in props), None)
    if limit_field:
        template[limit_field] = _MAX_ITEMS_PLACEHOLDER

    return template


def _concretize(template: dict, url: str, max_items: int) -> dict:
    """Substitute placeholders in a draft template with real values so the
    actor can actually run once."""
    username = _username_from_url(url)

    def sub(value):
        if isinstance(value, str):
            if value == _URL_PLACEHOLDER:
                return url
            if value == _USERNAME_PLACEHOLDER:
                return username
            if value == _MAX_ITEMS_PLACEHOLDER:
                return max_items
            return value
        if isinstance(value, list):
            return [sub(v) for v in value]
        if isinstance(value, dict):
            return {k: sub(v) for k, v in value.items()}
        return value

    return sub(template)


def _all_columns(items: list[dict]) -> list[str]:
    columns: list[str] = []
    for item in items:
        if isinstance(item, dict):
            for key in item:
                if key not in columns:
                    columns.append(key)
    return columns


def compile_entry(actor_id: str, url: str, max_items: int, token: str) -> dict:
    from apify_client import ApifyClient

    client = ApifyClient(token)

    schema = _fetch_input_schema(client, actor_id)
    template = _build_input_template(schema)
    run_input = _concretize(template, url, max_items)

    _note(f"note: running {actor_id} once (max_items={max_items}) - this may take a minute...")
    run = client.actor(actor_id).call(
        run_input=run_input,
        max_items=max_items,
        timeout_secs=300,
    )
    if run is None:
        raise RuntimeError(f"actor {actor_id!r} returned no run (timed out?)")
    status = run.get("status", "")
    if status in ("FAILED", "ABORTED", "ABORTING"):
        raise RuntimeError(f"actor {actor_id!r} run ended with status {status!r}")

    dataset_id = run["defaultDatasetId"]
    items = client.dataset(dataset_id).list_items(limit=max_items).items
    columns = _all_columns(items)
    if not columns:
        _note("warning: sample run produced no rows — all_columns is empty; edit by hand")

    return {
        "domain_patterns": _domain_patterns(url),
        "actor_id": actor_id,
        "intent_description": "TODO: one sentence - what this actor returns and its row unit.",
        "input_template": template,
        "input_notes": "TODO: note required fields and any caps/quirks.",
        "row_unit": "TODO: e.g. post / profile / job / product.",
        # Per Prompt 1 scope: copy all_columns for the human to trim, don't auto-classify.
        "default_columns": list(columns),
        "all_columns": columns,
        "is_default": False,
    }


def main(argv: list[str] | None = None) -> int:
    # Force UTF-8 on stdout so the JSON pipes cleanly even when redirected on
    # Windows (where the default file encoding would otherwise be cp1252).
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    load_dotenv()

    parser = argparse.ArgumentParser(
        prog="compile_actor_entry.py",
        description=(
            "Fetch an Apify actor's input schema, run it once, and print a draft "
            "registry entry (JSON) to stdout for hand-editing."
        ),
    )
    parser.add_argument("--actor-id", required=True, help="Apify actor ID, e.g. apify/instagram-post-scraper")
    parser.add_argument("--url", required=True, help="Sample URL to scrape")
    parser.add_argument("--max-items", type=int, default=1, help="Items to pull for the sample run (default: 1)")
    args = parser.parse_args(argv)

    token = os.environ.get("APIFY_TOKEN")
    if not token:
        _note("error: APIFY_TOKEN is not set. Export it or add it to .env, then retry.")
        return 1

    try:
        entry = compile_entry(args.actor_id, args.url, args.max_items, token)
    except Exception as exc:
        _note(f"error: {exc}")
        return 1

    print(json.dumps(entry, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

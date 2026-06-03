"""Deterministic, LLM-free output-shape application for Apify dataset rows.

The planner emits an ``output_shape`` dict alongside its actor choice; this
module applies it after the actor runs. Three operations, all pure data
transformation — no model load, no network call:

  1. explode  — when ``explode_field`` is set, promote that nested array to
                rows: one output row per element (e.g. profile-scraper's
                ``latestPosts``).
  2. project  — keep only ``columns``, in order; missing keys become None.
  3. rename   — apply the optional ``rename`` map to output keys only. This is
                the ONLY place actor-native camelCase names get prettified
                (Decision 4); the registry and projection stay actor-native.

Tolerant by design: never raises on missing fields, and non-dict rows are
skipped rather than crashing the run.
"""

from __future__ import annotations


def apply_shape(rows: list[dict], shape: dict) -> list[dict]:
    """Reshape raw Apify dataset *rows* per the planner's *shape* dict.

    *shape* keys:
      - ``explode_field``: optional str. If set, each row's value at that key
        (expected to be a list) is flattened so the output has one row per
        element. Rows lacking the field, or whose value is not a list,
        contribute nothing.
      - ``columns``: ordered list of column names to keep. Absent keys -> None.
      - ``rename``: optional ``{old_name: new_name}`` map applied to output keys.

    Non-dict entries are dropped without raising.
    """
    explode_field = shape.get("explode_field")
    columns = shape.get("columns") or []
    rename = shape.get("rename") or {}

    if explode_field:
        exploded: list = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            nested = row.get(explode_field)
            if isinstance(nested, list):
                exploded.extend(nested)
        rows = exploded

    out: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        out.append({rename.get(c, c): row.get(c) for c in columns})
    return out

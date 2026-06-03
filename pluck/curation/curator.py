"""
Deterministic curation pass. Runs after fetch/extract, before formatting.

Three operations, all deterministic — no model load, no network call, so it
adds no Apify/Railway memory pressure and stays debuggable:

  1. dedupe   — collapse rows that share an identity key (e.g. same job title +
                company fanned across locations), merging the location field.
  2. project  — drop empty and known-noise columns. Structured (Apify) data only;
                Haiku output is already shaped, so it is left untouched.
  3. relevance— optional keyword filter sourced from the URL query string
                (?keywords=, ?q=, ...). OFF by default (min_relevance=0).

Returns (rows, CurationStats). Stats give you the "100 raw -> 60 kept" number
for cost reporting and your RMF Measure evidence.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse

# Tracking / media columns that are noise for the common site-specific actors.
# Compared case-insensitively against column names.
_NOISE_COLUMNS = {
    "trackingid", "refid", "companylogo", "jobposterphoto",
    "jobposterprofileurl", "salaryinsights",
}

# Identity keys tried in order; first combo fully present on a row wins.
_IDENTITY_KEYS: list[tuple[str, ...]] = [
    ("title", "companyname"),
    ("title", "company"),
    ("name", "brand"),
    ("title",),
    ("name",),
]

_MERGE_FIELD = "location"  # collapsed duplicates merge this into a unique list


@dataclass
class CurationStats:
    rows_in: int = 0
    rows_after_dedupe: int = 0
    rows_out: int = 0
    columns_in: int = 0
    columns_out: int = 0
    dropped_columns: list[str] = field(default_factory=list)


def _norm(v) -> str:
    return re.sub(r"\s+", " ", str(v if v is not None else "").strip().lower())


def _lower_map(item: dict) -> dict[str, str]:
    """lowercased key -> original key, last-wins on collision."""
    return {k.lower(): k for k in item}


def _has_value(v) -> bool:
    if v is None:
        return False
    if isinstance(v, str):
        return v.strip() != ""
    if isinstance(v, (list, dict, tuple, set)):
        return len(v) > 0
    return True


def _columns(items: list) -> list[str]:
    cols: list[str] = []
    for it in items:
        if isinstance(it, dict):
            for k in it:
                if k not in cols:
                    cols.append(k)
    return cols


def _identity(item: dict, lower: dict[str, str]) -> tuple | None:
    for combo in _IDENTITY_KEYS:
        if all(c in lower for c in combo):
            return tuple(_norm(item[lower[c]]) for c in combo)
    return None


def _dedupe(items: list) -> list:
    seen: dict = {}
    order: list = []

    for item in items:
        if not isinstance(item, dict):
            # non-dict rows: keep, keyed by exact content
            key = ("__raw__", _norm(json.dumps(item, sort_keys=True, default=str)))
            if key not in seen:
                seen[key] = item
                order.append(key)
            continue

        lower = _lower_map(item)
        key = _identity(item, lower)
        if key is None:
            key = ("__exact__", json.dumps(item, sort_keys=True, default=str))

        if key not in seen:
            seen[key] = dict(item)
            order.append(key)
        else:
            # merge the location field into a unique, comma-joined string
            orig = seen[key]
            if not isinstance(orig, dict):
                continue
            o_lower = _lower_map(orig)
            if _MERGE_FIELD in lower and _MERGE_FIELD in o_lower:
                existing = str(orig.get(o_lower[_MERGE_FIELD], "") or "")
                addition = str(item.get(lower[_MERGE_FIELD], "") or "")
                parts = [p.strip() for p in (existing + "," + addition).split(",") if p.strip()]
                uniq = list(dict.fromkeys(parts))  # order-preserving unique
                orig[o_lower[_MERGE_FIELD]] = ", ".join(uniq)

    return [seen[k] for k in order]


def _project(items: list, *, min_fill: float = 0.10) -> tuple[list, list[str]]:
    if not items:
        return items, []
    cols = _columns(items)
    dict_rows = [it for it in items if isinstance(it, dict)]
    n = len(dict_rows) or 1

    keep: list[str] = []
    dropped: list[str] = []
    for c in cols:
        if c.lower() in _NOISE_COLUMNS:
            dropped.append(c)
            continue
        filled = sum(1 for it in dict_rows if _has_value(it.get(c)))
        if filled / n < min_fill:
            dropped.append(c)
            continue
        keep.append(c)

    projected = [
        {k: it.get(k) for k in keep} if isinstance(it, dict) else it
        for it in items
    ]
    return projected, dropped


def _project_to(items: list, keep_columns: list[str]) -> tuple[list, list[str]]:
    """Project rows down to an explicit column list, ignoring fill rate and
    noise heuristics. Columns in `keep_columns` absent from the data are
    skipped; data columns not requested are dropped. Original column order is
    preserved."""
    if not items:
        return items, []
    keep_set = set(keep_columns)
    cols = _columns(items)
    keep = [c for c in cols if c in keep_set]
    dropped = [c for c in cols if c not in keep_set]

    projected = [
        {k: it.get(k) for k in keep} if isinstance(it, dict) else it
        for it in items
    ]
    return projected, dropped


def _keywords_from_url(url: str) -> list[str]:
    try:
        qs = parse_qs(urlparse(url).query)
    except Exception:
        return []
    for key in ("keywords", "q", "query", "search", "k"):
        vals = qs.get(key)
        if vals and vals[0].strip():
            return [w for w in _norm(vals[0]).split() if w]
    return []


def _relevance_filter(items: list, keywords: list[str], min_hits: int) -> list:
    if not keywords or min_hits <= 0:
        return items
    out = []
    for it in items:
        if isinstance(it, dict):
            blob = _norm(" ".join(str(v) for v in it.values()))
        else:
            blob = _norm(it)
        if sum(1 for kw in keywords if kw in blob) >= min_hits:
            out.append(it)
    return out


def curate(
    items: list,
    *,
    source_url: str = "",
    is_structured: bool = False,
    max_items: int = 100,
    min_relevance: int = 0,
    keep_columns: list[str] | None = None,
) -> tuple[list, CurationStats]:
    """Dedupe, optionally project + relevance-filter, then cap. See module doc.

    `keep_columns`, when a non-empty list, projects to exactly those columns
    and overrides the noise/fill-rate heuristic (regardless of
    `is_structured`). When None/empty, projection falls back to the heuristic,
    which runs only for structured data.
    """
    items = items or []
    stats = CurationStats(rows_in=len(items), columns_in=len(_columns(items)))

    rows = _dedupe(items)
    stats.rows_after_dedupe = len(rows)

    if keep_columns:
        rows, dropped = _project_to(rows, keep_columns)
        stats.dropped_columns = dropped
    elif is_structured:
        rows, dropped = _project(rows)
        stats.dropped_columns = dropped

    if min_relevance > 0:
        rows = _relevance_filter(rows, _keywords_from_url(source_url), min_relevance)

    rows = rows[:max_items]
    stats.rows_out = len(rows)
    stats.columns_out = len(_columns(rows))
    return rows, stats

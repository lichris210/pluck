"""Model-assisted column selection for curation.

A single Haiku call that, given the user's extraction prompt, the column names
present in the data, and one sample row, decides which columns are worth
keeping. This narrows wide structured (Apify) datasets down to the fields the
user actually asked about, complementing the deterministic projection in
`curator._project`.

`derive_columns` never trusts the model blindly: the names it returns are
intersected with the real columns, so anything the model invents is dropped.
It returns None when the model gives nothing usable, signalling callers to
fall back to keeping all columns.
"""

from __future__ import annotations

import json
import logging

from pluck.extraction.json_repair import repair_and_parse

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-haiku-4-5"
_MAX_TOKENS = 1024


COLUMN_SELECTION_SYSTEM = (
    "You decide which columns of a tabular dataset are relevant to a user's "
    "data-extraction request. You are given the user's request, the full list "
    "of available column names, and one sample row. You return only a JSON "
    "object with a single key `columns` whose value is an array of the column "
    "names to keep — chosen verbatim from the provided list. You return only "
    "the JSON object: no prose, no markdown fences."
)


def _build_prompt(prompt: str, columns: list[str], sample_row: dict) -> str:
    return (
        "User request:\n"
        f"{prompt}\n\n"
        "Available columns:\n"
        f"{json.dumps(list(columns))}\n\n"
        "Sample row:\n"
        f"{json.dumps(sample_row, default=str, indent=2)}\n\n"
        "Return a JSON object naming the columns to keep — only those relevant "
        "to the user request, chosen verbatim from the available columns:\n"
        '{"columns": ["<column_name>", ...]}\n\n'
        "Return ONLY the JSON object — no prose, no markdown fences."
    )


def derive_columns(
    prompt: str,
    columns: list[str],
    sample_row: dict,
    client,
    model: str = DEFAULT_MODEL,
) -> list[str] | None:
    """Ask Haiku which columns to keep for the user's request.

    Returns the kept column names (a subset of `columns`, in their original
    order) or None when the model returns nothing usable. Column names the
    model invents are dropped via intersection with `columns`. Never raises.
    """
    if not columns:
        return None

    user_prompt = _build_prompt(prompt, columns, sample_row)

    try:
        response = client.messages.create(
            model=model,
            max_tokens=_MAX_TOKENS,
            system=COLUMN_SELECTION_SYSTEM,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except Exception as exc:
        logger.warning("Column selection API call failed: %s", exc)
        return None

    text = ""
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            text += block.text

    parsed = repair_and_parse(text)
    if not parsed:
        return None

    selected = parsed[0].get("columns")
    if not isinstance(selected, list):
        return None

    chosen = {c for c in selected if isinstance(c, str)}
    keep = [c for c in columns if c in chosen]
    return keep or None

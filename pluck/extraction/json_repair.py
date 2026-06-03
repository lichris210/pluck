"""Robust JSON parsing for Claude responses.

Claude generally returns clean JSON, but occasionally wraps it in markdown
fences, adds prose, leaves trailing commas, or uses Python-style dicts.
`repair_and_parse` handles each case and never raises — always returns
list[dict] (possibly empty).
"""

import json
import re

_FENCE_RE = re.compile(r"^\s*```(?:json|JSON)?\s*\n?(.*?)\n?```\s*$", re.DOTALL)
_TRAILING_COMMA_RE = re.compile(r",(\s*[\]}])")
# Match unquoted keys: { key: value  →  { "key": value
# Look for word chars before a colon, after { or , (with optional whitespace)
_UNQUOTED_KEY_RE = re.compile(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*:)")


def _strip_fences(text: str) -> str:
    match = _FENCE_RE.match(text)
    if match:
        return match.group(1)
    return text


def _extract_json_substring(text: str) -> str:
    """Find the outermost JSON array or object in `text` by scanning for
    matching brackets. Falls back to original text if no balanced range
    is found."""
    text = text.strip()
    if not text:
        return text

    first_open = -1
    open_char = None
    for i, ch in enumerate(text):
        if ch in "[{":
            first_open = i
            open_char = ch
            break
    if first_open < 0:
        return text

    close_char = "]" if open_char == "[" else "}"
    depth = 0
    in_string = False
    escape = False
    for i in range(first_open, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == open_char:
            depth += 1
        elif ch == close_char:
            depth -= 1
            if depth == 0:
                return text[first_open : i + 1]
    return text[first_open:]


def _fix_trailing_commas(text: str) -> str:
    return _TRAILING_COMMA_RE.sub(r"\1", text)


def _quote_unquoted_keys(text: str) -> str:
    return _UNQUOTED_KEY_RE.sub(r'\1"\2"\3', text)


def _single_to_double_quotes(text: str) -> str:
    """Convert Python-style single-quoted strings to double-quoted, leaving
    apostrophes inside double-quoted strings alone. Walks the string once
    tracking which quote (if any) we're currently inside."""
    out: list[str] = []
    in_single = False
    in_double = False
    escape = False
    for ch in text:
        if escape:
            out.append(ch)
            escape = False
            continue
        if ch == "\\":
            out.append(ch)
            escape = True
            continue
        if in_double:
            out.append(ch)
            if ch == '"':
                in_double = False
            continue
        if in_single:
            if ch == "'":
                out.append('"')
                in_single = False
            elif ch == '"':
                out.append('\\"')
            else:
                out.append(ch)
            continue
        # Not currently in a string
        if ch == '"':
            in_double = True
            out.append(ch)
        elif ch == "'":
            in_single = True
            out.append('"')
        else:
            out.append(ch)
    return "".join(out)


def _coerce_to_list_of_dicts(parsed) -> list[dict]:
    if isinstance(parsed, dict):
        return [parsed]
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    return []


def repair_and_parse(text) -> list[dict]:
    """Best-effort JSON parse. Always returns list[dict] — possibly empty."""
    if not text or not isinstance(text, str):
        return []

    candidate = _strip_fences(text)
    candidate = _extract_json_substring(candidate)

    # Attempt 1: direct parse
    try:
        return _coerce_to_list_of_dicts(json.loads(candidate))
    except (json.JSONDecodeError, ValueError):
        pass

    # Attempt 2: fix trailing commas
    repaired = _fix_trailing_commas(candidate)
    try:
        return _coerce_to_list_of_dicts(json.loads(repaired))
    except (json.JSONDecodeError, ValueError):
        pass

    # Attempt 3: also quote unquoted keys
    repaired = _quote_unquoted_keys(repaired)
    try:
        return _coerce_to_list_of_dicts(json.loads(repaired))
    except (json.JSONDecodeError, ValueError):
        pass

    # Attempt 4: convert single quotes to double quotes
    repaired = _single_to_double_quotes(repaired)
    repaired = _fix_trailing_commas(repaired)
    try:
        return _coerce_to_list_of_dicts(json.loads(repaired))
    except (json.JSONDecodeError, ValueError):
        return []

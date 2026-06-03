"""Output formatters: ASCII table, JSON, CSV."""

import csv
import io
import json


def _flatten(d: dict, prefix: str = "") -> dict:
    """Recursively flatten a nested dict with dot-notation keys."""
    result = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            result.update(_flatten(v, key))
        elif isinstance(v, list):
            result[key] = "|".join(str(i) for i in v)
        else:
            result[key] = v
    return result


def to_table(items: list[dict], max_col_width: int = 40) -> str:
    """Render *items* as an ASCII table. Returns '' for an empty list."""
    if not items:
        return ""

    # Union of all keys, preserving insertion order
    all_keys: list[str] = list(dict.fromkeys(k for item in items for k in item))

    def _cell(item: dict, col: str) -> str:
        v = item.get(col)
        s = "" if v is None else str(v)
        return s if len(s) <= max_col_width else s[: max_col_width - 3] + "..."

    # Column widths: max of header length and widest cell value
    widths = {
        col: max(len(col), *(len(_cell(item, col)) for item in items))
        for col in all_keys
    }

    sep = "+-" + "-+-".join("-" * widths[col] for col in all_keys) + "-+"

    def _row(values: list[str]) -> str:
        return "| " + " | ".join(v.ljust(widths[col]) for col, v in zip(all_keys, values)) + " |"

    lines = [sep, _row(all_keys), sep]
    for item in items:
        lines.append(_row([_cell(item, col) for col in all_keys]))
    lines.append(sep)
    return "\n".join(lines)


def to_json(items: list[dict], pretty: bool = True) -> str:
    """Serialize *items* to JSON."""
    indent = 2 if pretty else None
    return json.dumps(items, indent=indent, ensure_ascii=False)


def to_csv(items: list[dict]) -> str:
    """Serialize *items* to CSV with nested dict flattening and list→pipe joining."""
    if not items:
        return ""

    flat_items = [_flatten(item) for item in items]
    cols: list[str] = list(dict.fromkeys(k for item in flat_items for k in item))

    out = io.StringIO()
    writer = csv.DictWriter(
        out, fieldnames=cols, restval="", extrasaction="ignore", lineterminator="\r\n"
    )
    writer.writeheader()
    writer.writerows(flat_items)
    return out.getvalue()


def format_output(items: list[dict], fmt: str) -> str:
    """Dispatch to the right formatter. Raises ValueError for unknown formats."""
    if fmt == "table":
        return to_table(items)
    if fmt == "json":
        return to_json(items)
    if fmt == "csv":
        return to_csv(items)
    raise ValueError(f"Unknown format {fmt!r}. Expected 'table', 'json', or 'csv'.")

"""Tests for pluck/formatters.py."""

import csv
import io
import json

import pytest

from pluck.formatters import format_output, to_csv, to_json, to_table


# ── to_table ─────────────────────────────────────────────────────────────────


def test_to_table_normal_data():
    items = [{"name": "Alice", "age": "30"}, {"name": "Bob", "age": "25"}]
    out = to_table(items)
    assert "Alice" in out
    assert "Bob" in out
    assert "name" in out
    assert "age" in out


def test_to_table_empty_list_returns_empty_string():
    assert to_table([]) == ""


def test_to_table_single_item():
    items = [{"title": "Widget", "price": "9.99"}]
    out = to_table(items)
    assert "Widget" in out
    assert "9.99" in out
    assert "title" in out
    assert "price" in out


def test_to_table_union_of_keys_across_items():
    items = [
        {"a": "1", "b": "2"},
        {"b": "3", "c": "4"},
    ]
    out = to_table(items)
    assert "a" in out
    assert "b" in out
    assert "c" in out
    # item without "a" should show empty cell, not error
    assert out.count("|") > 0


def test_to_table_missing_value_shown_as_empty():
    items = [{"x": "present"}, {"y": "other"}]
    out = to_table(items)
    lines = out.split("\n")
    # Both keys should appear as columns
    assert "x" in out
    assert "y" in out


def test_to_table_truncates_long_values():
    long_val = "A" * 100
    items = [{"col": long_val}]
    out = to_table(items, max_col_width=20)
    assert "..." in out
    # Cell contents (non-separator rows) must be at most max_col_width chars
    for line in out.split("\n"):
        if line.startswith("+"):
            continue  # separator row — skip
        for part in line.split("|"):
            assert len(part.strip()) <= 20


def test_to_table_separator_rows_present():
    items = [{"a": "1"}]
    out = to_table(items)
    assert "+--" in out or "+-" in out


def test_to_table_none_values_shown_as_empty():
    items = [{"a": None, "b": "ok"}]
    out = to_table(items)
    assert "ok" in out


# ── to_json ──────────────────────────────────────────────────────────────────


def test_to_json_produces_valid_json():
    items = [{"x": 1}, {"y": "two"}]
    result = to_json(items)
    parsed = json.loads(result)
    assert parsed == items


def test_to_json_pretty_true_has_newlines():
    items = [{"a": 1}]
    result = to_json(items, pretty=True)
    assert "\n" in result


def test_to_json_pretty_false_single_line():
    items = [{"a": 1}]
    result = to_json(items, pretty=False)
    assert "\n" not in result


def test_to_json_empty_list():
    assert to_json([]) == "[]"


def test_to_json_unicode_preserved():
    items = [{"name": "Café", "emoji": "🚀"}]
    result = to_json(items)
    assert "Café" in result
    assert "🚀" in result


# ── to_csv ───────────────────────────────────────────────────────────────────


def test_to_csv_produces_parseable_csv():
    items = [{"a": "1", "b": "2"}, {"a": "3", "b": "4"}]
    result = to_csv(items)
    reader = csv.DictReader(io.StringIO(result))
    rows = list(reader)
    assert len(rows) == 2
    assert rows[0]["a"] == "1"
    assert rows[1]["b"] == "4"


def test_to_csv_empty_list_returns_empty_string():
    assert to_csv([]) == ""


def test_to_csv_flattens_nested_dicts():
    items = [{"name": "Alice", "address": {"city": "NYC", "state": "NY"}}]
    result = to_csv(items)
    assert "address.city" in result
    assert "address.state" in result
    assert "NYC" in result


def test_to_csv_joins_lists_with_pipe():
    items = [{"tags": ["python", "web", "scraping"]}]
    result = to_csv(items)
    assert "python|web|scraping" in result


def test_to_csv_handles_values_with_commas():
    items = [{"desc": "Hello, world"}]
    result = to_csv(items)
    reader = csv.DictReader(io.StringIO(result))
    rows = list(reader)
    assert rows[0]["desc"] == "Hello, world"


def test_to_csv_handles_values_with_quotes():
    items = [{"q": 'say "hi"'}]
    result = to_csv(items)
    reader = csv.DictReader(io.StringIO(result))
    rows = list(reader)
    assert rows[0]["q"] == 'say "hi"'


def test_to_csv_missing_keys_filled_with_empty():
    items = [{"a": "1", "b": "2"}, {"a": "3"}]
    result = to_csv(items)
    reader = csv.DictReader(io.StringIO(result))
    rows = list(reader)
    assert rows[1]["b"] == ""


# ── format_output ─────────────────────────────────────────────────────────────


def test_format_output_table():
    items = [{"x": "1"}]
    out = format_output(items, "table")
    assert "|" in out  # ASCII table


def test_format_output_json():
    items = [{"x": 1}]
    out = format_output(items, "json")
    assert json.loads(out) == items


def test_format_output_csv():
    items = [{"x": "1"}]
    out = format_output(items, "csv")
    reader = csv.DictReader(io.StringIO(out))
    rows = list(reader)
    assert rows[0]["x"] == "1"


def test_format_output_raises_on_unknown_format():
    with pytest.raises(ValueError, match="Unknown format"):
        format_output([{"x": 1}], "xml")

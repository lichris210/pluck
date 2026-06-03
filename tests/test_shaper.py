"""Tests for the deterministic output-shape layer (pluck/registry/shaper.py)."""

from pluck.registry.shaper import apply_shape


def test_simple_projection():
    rows = [
        {"caption": "hi", "likesCount": 5, "extra": "drop me"},
        {"caption": "yo", "likesCount": 9, "extra": "drop me too"},
    ]
    shape = {"explode_field": None, "columns": ["likesCount", "caption"]}

    out = apply_shape(rows, shape)

    assert out == [
        {"likesCount": 5, "caption": "hi"},
        {"likesCount": 9, "caption": "yo"},
    ]
    # column order preserved as requested (likesCount before caption)
    assert list(out[0].keys()) == ["likesCount", "caption"]


def test_missing_column_is_none():
    rows = [{"caption": "hi"}]
    shape = {"columns": ["caption", "likesCount"]}

    out = apply_shape(rows, shape)

    assert out == [{"caption": "hi", "likesCount": None}]


def test_explode_field_promotes_nested_rows():
    rows = [
        {
            "username": "natgeo",
            "latestPosts": [
                {"caption": "post 1", "likesCount": 1},
                {"caption": "post 2", "likesCount": 2},
            ],
        }
    ]
    shape = {"explode_field": "latestPosts", "columns": ["caption", "likesCount"]}

    out = apply_shape(rows, shape)

    assert out == [
        {"caption": "post 1", "likesCount": 1},
        {"caption": "post 2", "likesCount": 2},
    ]


def test_rename_map_applied():
    rows = [{"likesCount": 12, "caption": "hi"}]
    shape = {
        "columns": ["likesCount", "caption"],
        "rename": {"likesCount": "likes"},
    }

    out = apply_shape(rows, shape)

    assert out == [{"likes": 12, "caption": "hi"}]


def test_no_explode_when_field_null():
    rows = [{"caption": "hi", "tags": ["a", "b"]}]
    shape = {"explode_field": None, "columns": ["caption", "tags"]}

    out = apply_shape(rows, shape)

    assert out == [{"caption": "hi", "tags": ["a", "b"]}]


def test_non_dict_rows_skipped():
    rows = [
        {"caption": "real"},
        "junk",
        None,
        42,
        ["also", "junk"],
    ]
    shape = {"columns": ["caption"]}

    out = apply_shape(rows, shape)

    assert out == [{"caption": "real"}]

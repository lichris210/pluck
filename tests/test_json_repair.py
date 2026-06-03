"""Tests for the robust JSON repair-and-parse helper."""

from pluck.extraction.json_repair import repair_and_parse


def test_clean_json_array_parses_unchanged():
    text = '[{"a": 1}, {"b": 2}]'
    assert repair_and_parse(text) == [{"a": 1}, {"b": 2}]


def test_single_object_wrapped_in_list():
    text = '{"a": 1, "b": 2}'
    assert repair_and_parse(text) == [{"a": 1, "b": 2}]


def test_markdown_fences_with_json_label_stripped():
    text = '```json\n[{"x": 1}]\n```'
    assert repair_and_parse(text) == [{"x": 1}]


def test_markdown_fences_without_label_stripped():
    text = '```\n[{"x": 1}]\n```'
    assert repair_and_parse(text) == [{"x": 1}]


def test_leading_prose_stripped():
    text = 'Here is the data:\n[{"x": 1}]'
    assert repair_and_parse(text) == [{"x": 1}]


def test_trailing_prose_stripped():
    text = '[{"x": 1}]\nLet me know if you need more.'
    assert repair_and_parse(text) == [{"x": 1}]


def test_leading_and_trailing_prose_stripped():
    text = 'The result is:\n[{"x": 1}, {"x": 2}]\n\nThanks!'
    assert repair_and_parse(text) == [{"x": 1}, {"x": 2}]


def test_trailing_comma_in_array_fixed():
    text = '[{"x": 1}, {"x": 2},]'
    assert repair_and_parse(text) == [{"x": 1}, {"x": 2}]


def test_trailing_comma_in_object_fixed():
    text = '[{"x": 1, "y": 2,}]'
    assert repair_and_parse(text) == [{"x": 1, "y": 2}]


def test_multiple_trailing_commas():
    text = '[{"x": 1,}, {"y": 2,},]'
    assert repair_and_parse(text) == [{"x": 1}, {"y": 2}]


def test_unquoted_keys_fixed():
    text = '[{name: "Alice", age: 30}]'
    assert repair_and_parse(text) == [{"name": "Alice", "age": 30}]


def test_single_quoted_strings_converted():
    text = "[{'name': 'Alice', 'role': 'admin'}]"
    result = repair_and_parse(text)
    assert result == [{"name": "Alice", "role": "admin"}]


def test_python_style_dict_with_single_quotes_and_unquoted_keys():
    text = "[{name: 'Alice', age: 30}]"
    assert repair_and_parse(text) == [{"name": "Alice", "age": 30}]


def test_mixed_json_in_garbage_extracted():
    text = (
        "Sure! Here's what I found.\n\n"
        '```json\n[{"id": 1, "title": "Post"}]\n```\n'
        "Hope that helps!"
    )
    assert repair_and_parse(text) == [{"id": 1, "title": "Post"}]


def test_garbage_input_returns_empty_list():
    assert repair_and_parse("this is not json at all") == []


def test_only_prose_returns_empty():
    assert repair_and_parse("I'm sorry, I cannot extract data from this page.") == []


def test_empty_string_returns_empty_list():
    assert repair_and_parse("") == []


def test_none_input_returns_empty_list():
    assert repair_and_parse(None) == []


def test_non_string_input_returns_empty_list():
    assert repair_and_parse(123) == []
    assert repair_and_parse([]) == []


def test_deeply_nested_valid_json():
    text = '[{"meta": {"tags": ["a", "b"], "info": {"deep": true}}}]'
    assert repair_and_parse(text) == [
        {"meta": {"tags": ["a", "b"], "info": {"deep": True}}}
    ]


def test_unicode_characters_parsed():
    text = '[{"name": "Café", "city": "São Paulo", "emoji": "🚀"}]'
    assert repair_and_parse(text) == [
        {"name": "Café", "city": "São Paulo", "emoji": "🚀"}
    ]


def test_empty_array_parsed():
    assert repair_and_parse("[]") == []


def test_array_with_non_dict_filtered():
    """Coercion: arrays mixing dicts and non-dicts keep only the dicts."""
    text = '[{"a": 1}, "not a dict", 42, {"b": 2}]'
    assert repair_and_parse(text) == [{"a": 1}, {"b": 2}]


def test_returns_list_dict_type_invariant():
    """Whatever happens inside, the return type is list[dict]."""
    for text in ["", None, "garbage", "[]", '[1, 2, 3]', '"a string"']:
        result = repair_and_parse(text)
        assert isinstance(result, list)
        assert all(isinstance(item, dict) for item in result)


def test_apostrophe_inside_double_quoted_string_preserved():
    """A literal apostrophe inside a JSON string should not be touched."""
    text = '[{"text": "it\'s working"}]'
    assert repair_and_parse(text) == [{"text": "it's working"}]


def test_combined_fences_and_trailing_comma():
    text = '```json\n[{"x": 1,},]\n```'
    assert repair_and_parse(text) == [{"x": 1}]

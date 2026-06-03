"""Tests for prompt_spec.derive_columns.

All Anthropic calls are mocked via the `mock_anthropic_client` fixture in
conftest.py — no real API calls are made.
"""

from pluck.curation.prompt_spec import DEFAULT_MODEL, derive_columns


COLUMNS = ["title", "company", "location", "trackingId", "salary"]
SAMPLE_ROW = {
    "title": "Senior Engineer",
    "company": "Acme",
    "location": "NYC",
    "trackingId": "xyz123",
    "salary": "$180k",
}


def _resp(client, text: str):
    return client._make_response(text)


# ── Normal case ──────────────────────────────────────────────────────────────


def test_normal_case_returns_selected_subset(mock_anthropic_client):
    mock_anthropic_client.messages.create.return_value = _resp(
        mock_anthropic_client, '{"columns": ["title", "company", "salary"]}'
    )

    result = derive_columns(
        "job titles with pay", COLUMNS, SAMPLE_ROW, mock_anthropic_client
    )

    # Subset of the real columns, preserved in original order.
    assert result == ["title", "company", "salary"]
    assert mock_anthropic_client.messages.create.call_count == 1


def test_call_includes_prompt_columns_sample_row_and_model(mock_anthropic_client):
    mock_anthropic_client.messages.create.return_value = _resp(
        mock_anthropic_client, '{"columns": ["title"]}'
    )

    derive_columns(
        "find jobs with salary", COLUMNS, SAMPLE_ROW, mock_anthropic_client
    )

    kwargs = mock_anthropic_client.messages.create.call_args.kwargs
    content = kwargs["messages"][0]["content"]
    assert "find jobs with salary" in content  # the prompt
    assert "trackingId" in content  # a column name
    assert "Senior Engineer" in content  # a value from the sample row
    assert kwargs["model"] == DEFAULT_MODEL


def test_model_param_is_forwarded(mock_anthropic_client):
    mock_anthropic_client.messages.create.return_value = _resp(
        mock_anthropic_client, '{"columns": ["title"]}'
    )

    derive_columns(
        "jobs", COLUMNS, SAMPLE_ROW, mock_anthropic_client, model="claude-sonnet-4-6"
    )

    assert (
        mock_anthropic_client.messages.create.call_args.kwargs["model"]
        == "claude-sonnet-4-6"
    )


# ── Hallucinated columns are dropped ─────────────────────────────────────────


def test_hallucinated_columns_are_dropped(mock_anthropic_client):
    mock_anthropic_client.messages.create.return_value = _resp(
        mock_anthropic_client,
        '{"columns": ["title", "made_up_field", "salary"]}',
    )

    result = derive_columns(
        "jobs with pay", COLUMNS, SAMPLE_ROW, mock_anthropic_client
    )

    assert result == ["title", "salary"]
    assert "made_up_field" not in result


def test_all_invented_columns_returns_none(mock_anthropic_client):
    mock_anthropic_client.messages.create.return_value = _resp(
        mock_anthropic_client, '{"columns": ["foo", "bar"]}'
    )

    assert (
        derive_columns("jobs", COLUMNS, SAMPLE_ROW, mock_anthropic_client) is None
    )


# ── Empty / garbage responses → None ─────────────────────────────────────────


def test_garbage_prose_response_returns_none(mock_anthropic_client):
    mock_anthropic_client.messages.create.return_value = _resp(
        mock_anthropic_client, "I'm not sure which columns you mean."
    )

    assert (
        derive_columns("jobs", COLUMNS, SAMPLE_ROW, mock_anthropic_client) is None
    )


def test_empty_string_response_returns_none(mock_anthropic_client):
    mock_anthropic_client.messages.create.return_value = _resp(
        mock_anthropic_client, ""
    )

    assert (
        derive_columns("jobs", COLUMNS, SAMPLE_ROW, mock_anthropic_client) is None
    )


def test_empty_columns_array_returns_none(mock_anthropic_client):
    mock_anthropic_client.messages.create.return_value = _resp(
        mock_anthropic_client, '{"columns": []}'
    )

    assert (
        derive_columns("jobs", COLUMNS, SAMPLE_ROW, mock_anthropic_client) is None
    )


def test_missing_columns_key_returns_none(mock_anthropic_client):
    mock_anthropic_client.messages.create.return_value = _resp(
        mock_anthropic_client, '{"fields": ["title"]}'
    )

    assert (
        derive_columns("jobs", COLUMNS, SAMPLE_ROW, mock_anthropic_client) is None
    )


# ── Malformed JSON: repaired or None ─────────────────────────────────────────


def test_fenced_with_trailing_comma_is_repaired(mock_anthropic_client):
    fenced = '```json\n{"columns": ["title", "company",]}\n```'
    mock_anthropic_client.messages.create.return_value = _resp(
        mock_anthropic_client, fenced
    )

    result = derive_columns(
        "jobs", COLUMNS, SAMPLE_ROW, mock_anthropic_client
    )

    assert result == ["title", "company"]


def test_prose_wrapped_json_object_is_extracted(mock_anthropic_client):
    wrapped = 'Here are the columns: {"columns": ["salary"]} — hope that helps!'
    mock_anthropic_client.messages.create.return_value = _resp(
        mock_anthropic_client, wrapped
    )

    result = derive_columns(
        "pay info", COLUMNS, SAMPLE_ROW, mock_anthropic_client
    )

    assert result == ["salary"]


def test_unrepairable_json_returns_none(mock_anthropic_client):
    # Unbalanced/truncated object — no repair pass can recover it.
    mock_anthropic_client.messages.create.return_value = _resp(
        mock_anthropic_client, '{"columns": ['
    )

    assert (
        derive_columns("jobs", COLUMNS, SAMPLE_ROW, mock_anthropic_client) is None
    )


# ── Guards ───────────────────────────────────────────────────────────────────


def test_empty_input_columns_returns_none_without_api_call(mock_anthropic_client):
    result = derive_columns("jobs", [], {}, mock_anthropic_client)

    assert result is None
    mock_anthropic_client.messages.create.assert_not_called()


def test_api_error_returns_none(mock_anthropic_client):
    mock_anthropic_client.messages.create.side_effect = RuntimeError("API down")

    assert (
        derive_columns("jobs", COLUMNS, SAMPLE_ROW, mock_anthropic_client) is None
    )

"""Tests for extraction validation and cache auto-invalidation."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from pluck.extraction.extractor import extract
from pluck.extraction.validator import ValidationResult, validate_extraction
from pluck.models import ExtractionSchema, FieldDef, FetchResult
from pluck.storage.cache_store import SchemaCacheStore


# ── fixtures & helpers ────────────────────────────────────────────────────────

@pytest.fixture
def store(tmp_path):
    db = tmp_path / "val_test.db"
    s = SchemaCacheStore(db_path=str(db))
    yield s
    s.close()


def _schema_with_required(*names: str) -> ExtractionSchema:
    return ExtractionSchema(
        description="test",
        fields=[FieldDef(name=n, field_type="string", description=n, required=True) for n in names],
    )


def _schema_optional(*names: str) -> ExtractionSchema:
    return ExtractionSchema(
        description="test",
        fields=[FieldDef(name=n, field_type="string", description=n, required=False) for n in names],
    )


def _make_fetch_result(url: str = "https://linkedin.com/jobs/11111") -> FetchResult:
    return FetchResult(
        url=url,
        html="<html><body><h1>Job</h1></body></html>",
        fetcher_used="test",
        fetch_time_ms=0.0,
        success=True,
    )


def _resp(text: str) -> MagicMock:
    """Build a minimal Anthropic response mock for the given text."""
    block = MagicMock()
    block.type = "text"
    block.text = text
    usage = MagicMock()
    usage.input_tokens = 50
    usage.output_tokens = 20
    resp = MagicMock()
    resp.content = [block]
    resp.usage = usage
    return resp


def _client(*texts: str) -> MagicMock:
    """Mock Anthropic client returning each text on successive create() calls."""
    client = MagicMock()
    client.messages.create.side_effect = [_resp(t) for t in texts]
    return client


def _prime_cache(store: SchemaCacheStore, pattern: str, schema: ExtractionSchema) -> None:
    store.put_schema(pattern, json.dumps(schema.to_dict()))


# ── validate_extraction unit tests ────────────────────────────────────────────

def test_validate_zero_rows_fails():
    vr = validate_extraction(_schema_with_required("title"), [])
    assert not vr.ok
    assert "zero rows" in vr.reason


def test_validate_all_required_present_passes():
    vr = validate_extraction(
        _schema_with_required("title"),
        [{"title": "Engineer"}, {"title": "Manager"}],
    )
    assert vr.ok


def test_validate_high_null_required_fails():
    # 2 out of 3 rows have null title → 67 % → fail
    vr = validate_extraction(
        _schema_with_required("title"),
        [{"title": None}, {"title": None}, {"title": "Engineer"}],
    )
    assert not vr.ok


def test_validate_exactly_50_percent_passes():
    # Exactly 50 % is NOT above 50 %, so it should pass
    vr = validate_extraction(
        _schema_with_required("title"),
        [{"title": None}, {"title": "Engineer"}],
    )
    assert vr.ok


def test_validate_optional_nulls_not_counted():
    schema = ExtractionSchema(
        description="test",
        fields=[
            FieldDef("title", "string", "Title", required=True),
            FieldDef("salary", "string", "Salary", required=False),
        ],
    )
    # salary is always null but it's optional — should not trigger failure
    rows = [{"title": "Engineer", "salary": None}] * 5
    vr = validate_extraction(schema, rows)
    assert vr.ok


def test_validate_no_required_fields_always_passes():
    vr = validate_extraction(_schema_optional("note"), [{"note": None}] * 10)
    assert vr.ok


def test_validate_empty_string_counts_as_null():
    vr = validate_extraction(
        _schema_with_required("title"),
        [{"title": ""}, {"title": ""}, {"title": ""}],
    )
    assert not vr.ok


# ── integration: cache + validation + retry ───────────────────────────────────

PATTERN = "linkedin.com/jobs/*"
CACHED_SCHEMA = _schema_with_required("title")


async def test_cached_zero_rows_triggers_exactly_one_re_inference(store):
    _prime_cache(store, PATTERN, CACHED_SCHEMA)
    fresh_schema = _schema_with_required("title")

    with patch("pluck.extraction.extractor.infer_schema", new_callable=AsyncMock) as mock_infer:
        mock_infer.return_value = (fresh_schema, 10, 5)
        result = await extract(
            _make_fetch_result(),
            None,
            # first call: empty rows → triggers re-infer; second call: valid rows
            _client("[]", '[{"title": "Engineer"}]'),
            cache_store=store,
        )

    mock_infer.assert_called_once()
    assert result.error is None
    assert result.schema_cache_hit is False


async def test_cached_high_null_triggers_re_inference(store):
    _prime_cache(store, PATTERN, CACHED_SCHEMA)
    fresh_schema = _schema_with_required("title")

    # 3 rows, title null in all 3 → 100% null → invalid
    bad_rows = '[{"title": null}, {"title": null}, {"title": null}]'
    good_rows = '[{"title": "Engineer"}]'

    with patch("pluck.extraction.extractor.infer_schema", new_callable=AsyncMock) as mock_infer:
        mock_infer.return_value = (fresh_schema, 10, 5)
        result = await extract(
            _make_fetch_result(),
            None,
            _client(bad_rows, good_rows),
            cache_store=store,
        )

    mock_infer.assert_called_once()
    assert result.error is None
    assert len(result.items) == 1


async def test_cached_passing_validation_no_re_inference(store):
    _prime_cache(store, PATTERN, CACHED_SCHEMA)

    with patch("pluck.extraction.extractor.infer_schema", new_callable=AsyncMock) as mock_infer:
        mock_infer.return_value = (CACHED_SCHEMA, 10, 5)
        result = await extract(
            _make_fetch_result(),
            None,
            _client('[{"title": "Engineer"}, {"title": "Manager"}]'),
            cache_store=store,
        )

    mock_infer.assert_not_called()
    assert result.error is None
    assert result.schema_cache_hit is True


async def test_double_failure_surfaces_error_no_loop(store):
    """Cache hit fails → re-infer → second extraction also fails → error, no third call."""
    _prime_cache(store, PATTERN, CACHED_SCHEMA)
    fresh_schema = _schema_with_required("title")

    with patch("pluck.extraction.extractor.infer_schema", new_callable=AsyncMock) as mock_infer:
        mock_infer.return_value = (fresh_schema, 10, 5)
        result = await extract(
            _make_fetch_result(),
            None,
            # both extraction calls return zero rows
            _client("[]", "[]"),
            cache_store=store,
        )

    # infer_schema called exactly once (the retry), not twice
    mock_infer.assert_called_once()
    assert result.error is not None
    assert "re-inference" in result.error


async def test_cache_invalidated_after_validation_failure(store):
    _prime_cache(store, PATTERN, CACHED_SCHEMA)
    fresh_schema = _schema_with_required("title")

    with patch("pluck.extraction.extractor.infer_schema", new_callable=AsyncMock) as mock_infer:
        mock_infer.return_value = (fresh_schema, 10, 5)
        await extract(
            _make_fetch_result(),
            None,
            _client("[]", '[{"title": "Engineer"}]'),
            cache_store=store,
        )

    # After successful retry, new schema should be in cache (active)
    assert store.get_schema(PATTERN) is not None


async def test_fresh_inference_failure_not_retried(store):
    """Cache miss: fresh inference + bad results is returned as-is with no retry."""
    # store is empty — no cache entry
    fresh_schema = _schema_with_required("title")

    with patch("pluck.extraction.extractor.infer_schema", new_callable=AsyncMock) as mock_infer:
        mock_infer.return_value = (fresh_schema, 10, 5)
        result = await extract(
            _make_fetch_result(),
            None,
            _client("[]"),   # empty rows
            cache_store=store,
        )

    # infer_schema called once (normal inference), NOT twice
    mock_infer.assert_called_once()
    # reported as-is: no error, just empty items
    assert result.error is None
    assert result.items == []

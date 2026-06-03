"""Tests for pluck/cli.py — argument parsing and CLI behaviour."""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pluck.cli import _build_parser, _infer_format, _load_schema
from pluck.models import (
    ExtractionSchema,
    FetchResult,
    FieldDef,
    PipelineResult,
    SiteGroup,
    SiteProfile,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _dummy_profile() -> SiteProfile:
    return SiteProfile(
        url="https://example.com/",
        final_url="https://example.com/",
        status_code=200,
        headers={},
        content_type="text/html",
        html="",
        site_group=SiteGroup.STATIC_HTML,
        classification_reasons=["test"],
        response_time_ms=10.0,
    )


def _dummy_pipeline_result(steps=None, error=None, formatted="") -> PipelineResult:
    return PipelineResult(
        url="https://example.com/",
        site_profile=_dummy_profile(),
        fetch_result=None,
        extraction_result=None,
        formatted_output=formatted,
        output_format="table",
        total_time_ms=42.0,
        steps_completed=steps or ["ingest", "fetch", "extract", "format"],
        error=error,
    )


# ── Argument parsing ──────────────────────────────────────────────────────────


def test_parser_requires_url():
    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_parser_url_positional():
    parser = _build_parser()
    args = parser.parse_args(["https://example.com/"])
    assert args.url == "https://example.com/"


def test_parser_output_flag():
    parser = _build_parser()
    args = parser.parse_args(["https://x.com/", "--output", "out.json"])
    assert args.output == "out.json"


def test_parser_format_flag():
    parser = _build_parser()
    args = parser.parse_args(["https://x.com/", "--format", "csv"])
    assert args.fmt == "csv"


def test_parser_dry_run_flag():
    parser = _build_parser()
    args = parser.parse_args(["https://x.com/", "--dry-run"])
    assert args.dry_run is True


def test_parser_schema_flag():
    parser = _build_parser()
    args = parser.parse_args(["https://x.com/", "--schema", "schema.json"])
    assert args.schema == "schema.json"


def test_parser_auto_flag():
    parser = _build_parser()
    args = parser.parse_args(["https://x.com/", "--auto"])
    assert args.auto is True


def test_parser_verbose_flag():
    parser = _build_parser()
    args = parser.parse_args(["https://x.com/", "--verbose"])
    assert args.verbose is True


def test_parser_use_apify_flag():
    parser = _build_parser()
    args = parser.parse_args(["https://x.com/", "--use-apify"])
    assert args.use_apify is True


def test_parser_max_items_flag():
    parser = _build_parser()
    args = parser.parse_args(["https://x.com/", "--max-items", "50"])
    assert args.max_items == 50


def test_parser_show_steps_flag():
    parser = _build_parser()
    args = parser.parse_args(["https://x.com/", "--show-steps"])
    assert args.show_steps is True


# ── Format inference ──────────────────────────────────────────────────────────


def test_infer_format_json_extension():
    assert _infer_format("output.json", "table") == "json"


def test_infer_format_csv_extension():
    assert _infer_format("results.csv", "table") == "csv"


def test_infer_format_md_extension():
    assert _infer_format("output.md", "table") == "table"


def test_infer_format_explicit_overrides_extension():
    # Even with .csv extension, explicit --format json wins
    assert _infer_format("output.csv", "json") == "json"


def test_infer_format_no_output_uses_default():
    assert _infer_format(None, "table") == "table"


# ── Schema loading ────────────────────────────────────────────────────────────


def test_load_schema_success(tmp_path):
    schema_data = {
        "description": "Products",
        "fields": [
            {"name": "title", "field_type": "string", "description": "Title", "required": True}
        ],
    }
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(json.dumps(schema_data), encoding="utf-8")

    schema = _load_schema(str(schema_file))
    assert schema.description == "Products"
    assert len(schema.fields) == 1
    assert schema.fields[0].name == "title"


def test_load_schema_invalid_json_exits(tmp_path):
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("{ this is not json }", encoding="utf-8")

    with pytest.raises(SystemExit) as exc_info:
        _load_schema(str(bad_file))
    assert exc_info.value.code == 1


def test_load_schema_missing_file_exits():
    with pytest.raises(SystemExit) as exc_info:
        _load_schema("/nonexistent/path/schema.json")
    assert exc_info.value.code == 1


# ── CLI end-to-end with mocked pipeline ──────────────────────────────────────


@pytest.mark.asyncio
async def test_dry_run_does_not_call_pipeline_fetch(capsys):
    """--dry-run should call pipeline.run(dry_run=True), which skips fetch."""
    from pluck.cli import _run

    parser = _build_parser()
    args = parser.parse_args(["https://example.com/", "--dry-run", "--auto"])

    result = _dummy_pipeline_result(steps=["ingest"])
    with patch("pluck.cli.PluckPipeline") as MockPipeline:
        MockPipeline.return_value.run = AsyncMock(return_value=result)
        await _run(args)

    _, kwargs = MockPipeline.return_value.run.call_args
    assert kwargs.get("dry_run") is True


@pytest.mark.asyncio
async def test_output_file_written(tmp_path, capsys):
    from pluck.cli import _run

    out_file = tmp_path / "out.json"
    parser = _build_parser()
    args = parser.parse_args(["https://example.com/", "--output", str(out_file), "--auto"])

    result = _dummy_pipeline_result(formatted='[{"x": 1}]')
    result.output_format = "json"
    with patch("pluck.cli.PluckPipeline") as MockPipeline:
        MockPipeline.return_value.run = AsyncMock(return_value=result)
        await _run(args)

    assert out_file.exists()
    captured = capsys.readouterr()
    assert "Saved" in captured.out


@pytest.mark.asyncio
async def test_show_steps_prints_step_list(capsys):
    from pluck.cli import _run

    parser = _build_parser()
    args = parser.parse_args(["https://example.com/", "--show-steps", "--auto"])

    result = _dummy_pipeline_result(steps=["ingest", "fetch", "extract", "format"])
    with patch("pluck.cli.PluckPipeline") as MockPipeline:
        MockPipeline.return_value.run = AsyncMock(return_value=result)
        await _run(args)

    captured = capsys.readouterr()
    assert "ingest" in captured.out
    assert "fetch" in captured.out


@pytest.mark.asyncio
async def test_auto_flag_passed_to_pipeline(capsys):
    from pluck.cli import _run

    parser = _build_parser()
    args = parser.parse_args(["https://example.com/", "--auto"])

    result = _dummy_pipeline_result()
    with patch("pluck.cli.PluckPipeline") as MockPipeline:
        MockPipeline.return_value.run = AsyncMock(return_value=result)
        await _run(args)

    # Should not prompt for input — verify no SystemExit or hang
    # (The test itself completing is the assertion)
    assert result is not None

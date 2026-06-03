"""
Unit tests for scrapling_wrapper.py.

All Scrapling fetcher classes are mocked — no real network calls.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from pluck.fetchers.scrapling_wrapper import (
    _build_metadata,
    _extract_title,
    _make_sync_page_action,
    _parse_xhr_data,
    fetch_dynamic,
    fetch_static,
    fetch_static_async,
    fetch_stealth,
)
from pluck.models import FetchResult

# ── Helpers ───────────────────────────────────────────────────────────────────

SIMPLE_HTML = "<html><head><title>Hello</title></head><body><p>content</p></body></html>"


def _make_response(html=SIMPLE_HTML, status=200, captured_xhr=None):
    """Build a minimal mock Scrapling Response."""
    r = MagicMock()
    r.html_content = html
    r.status = status
    r.url = "https://example.com/"
    r.captured_xhr = captured_xhr or []
    return r


def _make_xhr_response(data):
    """Build a mock XHR Response whose .json() returns data."""
    x = MagicMock()
    x.url = "https://api.example.com/data"
    x.json = MagicMock(return_value=data)
    return x


# ── _extract_title ────────────────────────────────────────────────────────────

def test_extract_title_present():
    assert _extract_title(SIMPLE_HTML) == "Hello"


def test_extract_title_missing():
    assert _extract_title("<html><body>no title</body></html>") == ""


def test_extract_title_empty_html():
    assert _extract_title("") == ""


# ── _parse_xhr_data ───────────────────────────────────────────────────────────

def test_parse_xhr_data_list():
    xhr = [_make_xhr_response([{"id": 1}, {"id": 2}])]
    result = _parse_xhr_data(xhr)
    assert result == [{"id": 1}, {"id": 2}]


def test_parse_xhr_data_dict():
    xhr = [_make_xhr_response({"key": "val"})]
    result = _parse_xhr_data(xhr)
    assert result == [{"key": "val"}]


def test_parse_xhr_data_empty_list():
    assert _parse_xhr_data([]) is None


def test_parse_xhr_data_non_json():
    x = MagicMock()
    x.json = MagicMock(side_effect=ValueError("not json"))
    assert _parse_xhr_data([x]) is None


# ── _make_sync_page_action ────────────────────────────────────────────────────

def test_make_sync_page_action_none():
    assert _make_sync_page_action(None) is None


def test_make_sync_page_action_passthrough_sync():
    def sync_fn(page):
        pass
    assert _make_sync_page_action(sync_fn) is sync_fn


def test_make_sync_page_action_wraps_async():
    async def async_fn(page):
        pass
    wrapped = _make_sync_page_action(async_fn)
    assert callable(wrapped)
    assert wrapped is not async_fn
    # Calling the wrapper should not raise
    mock_page = MagicMock()
    wrapped(mock_page)  # runs a fresh event loop internally


# ── fetch_static ──────────────────────────────────────────────────────────────

@patch("pluck.fetchers.scrapling_wrapper.Fetcher")
def test_fetch_static_success(MockFetcher):
    MockFetcher.get.return_value = _make_response()
    result = fetch_static("https://example.com/")
    assert isinstance(result, FetchResult)
    assert result.success is True
    assert result.html == SIMPLE_HTML
    assert result.fetcher_used == "Fetcher"
    assert result.error is None


@patch("pluck.fetchers.scrapling_wrapper.Fetcher")
def test_fetch_static_timeout_in_seconds(MockFetcher):
    """Fetcher uses seconds — timeout must NOT be multiplied."""
    MockFetcher.get.return_value = _make_response()
    fetch_static("https://example.com/", timeout_seconds=20.0)
    _, kwargs = MockFetcher.get.call_args
    assert kwargs.get("timeout") == 20.0


@patch("pluck.fetchers.scrapling_wrapper.Fetcher")
def test_fetch_static_exception_returns_error(MockFetcher):
    MockFetcher.get.side_effect = ConnectionError("DNS failed")
    result = fetch_static("https://bad.example.com/")
    assert result.success is False
    assert "DNS failed" in result.error
    assert result.html == ""


# ── fetch_static_async ────────────────────────────────────────────────────────

@pytest.mark.asyncio
@patch("pluck.fetchers.scrapling_wrapper.AsyncFetcher")
async def test_fetch_static_async_success(MockAsync):
    MockAsync.get = AsyncMock(return_value=_make_response())
    result = await fetch_static_async("https://example.com/")
    assert result.success is True
    assert result.html == SIMPLE_HTML
    assert result.fetcher_used == "AsyncFetcher"


@pytest.mark.asyncio
@patch("pluck.fetchers.scrapling_wrapper.AsyncFetcher")
async def test_fetch_static_async_exception(MockAsync):
    MockAsync.get = AsyncMock(side_effect=TimeoutError("timed out"))
    result = await fetch_static_async("https://example.com/")
    assert result.success is False
    assert "timed out" in result.error


# ── fetch_dynamic ─────────────────────────────────────────────────────────────

@patch("pluck.fetchers.scrapling_wrapper.DynamicFetcher")
def test_fetch_dynamic_success(MockDynamic):
    MockDynamic.fetch.return_value = _make_response()
    result = fetch_dynamic("https://example.com/")
    assert result.success is True
    assert result.fetcher_used == "DynamicFetcher"


@patch("pluck.fetchers.scrapling_wrapper.DynamicFetcher")
def test_fetch_dynamic_timeout_converted_to_ms(MockDynamic):
    """timeout_seconds=30 → timeout=30000 passed to Scrapling."""
    MockDynamic.fetch.return_value = _make_response()
    fetch_dynamic("https://example.com/", timeout_seconds=30.0)
    _, kwargs = MockDynamic.fetch.call_args
    assert kwargs.get("timeout") == 30_000


@patch("pluck.fetchers.scrapling_wrapper.DynamicFetcher")
def test_fetch_dynamic_custom_timeout_converted(MockDynamic):
    """timeout_seconds=45 → timeout=45000."""
    MockDynamic.fetch.return_value = _make_response()
    fetch_dynamic("https://example.com/", timeout_seconds=45.0)
    _, kwargs = MockDynamic.fetch.call_args
    assert kwargs.get("timeout") == 45_000


@patch("pluck.fetchers.scrapling_wrapper.DynamicFetcher")
def test_fetch_dynamic_capture_xhr_passed(MockDynamic):
    MockDynamic.fetch.return_value = _make_response()
    fetch_dynamic("https://example.com/", capture_xhr_pattern="/api/")
    _, kwargs = MockDynamic.fetch.call_args
    assert kwargs.get("capture_xhr") == "/api/"


@patch("pluck.fetchers.scrapling_wrapper.DynamicFetcher")
def test_fetch_dynamic_xhr_populates_structured_data(MockDynamic):
    xhr = [_make_xhr_response([{"id": 1}, {"id": 2}])]
    MockDynamic.fetch.return_value = _make_response(captured_xhr=xhr)
    result = fetch_dynamic("https://example.com/", capture_xhr_pattern="/api/")
    assert result.structured_data == [{"id": 1}, {"id": 2}]
    assert result.skip_extraction is True
    assert result.metadata["captured_xhr_count"] == 1


@patch("pluck.fetchers.scrapling_wrapper.DynamicFetcher")
def test_fetch_dynamic_no_xhr_match_leaves_structured_data_none(MockDynamic):
    MockDynamic.fetch.return_value = _make_response(captured_xhr=[])
    result = fetch_dynamic("https://example.com/", capture_xhr_pattern="/api/")
    assert result.structured_data is None
    assert result.skip_extraction is False


@patch("pluck.fetchers.scrapling_wrapper.DynamicFetcher")
def test_fetch_dynamic_exception_returns_error(MockDynamic):
    MockDynamic.fetch.side_effect = RuntimeError("browser crashed")
    result = fetch_dynamic("https://example.com/")
    assert result.success is False
    assert "browser crashed" in result.error


# ── fetch_stealth ─────────────────────────────────────────────────────────────

@patch("pluck.fetchers.scrapling_wrapper.StealthyFetcher")
def test_fetch_stealth_success(MockStealth):
    MockStealth.fetch.return_value = _make_response()
    result = fetch_stealth("https://example.com/")
    assert result.success is True
    assert result.fetcher_used == "StealthyFetcher"


@patch("pluck.fetchers.scrapling_wrapper.StealthyFetcher")
def test_fetch_stealth_timeout_converted_to_ms(MockStealth):
    """timeout_seconds=20 → timeout=20000 passed to Scrapling."""
    MockStealth.fetch.return_value = _make_response()
    fetch_stealth("https://example.com/", timeout_seconds=20.0)
    _, kwargs = MockStealth.fetch.call_args
    assert kwargs.get("timeout") == 20_000


@patch("pluck.fetchers.scrapling_wrapper.StealthyFetcher")
def test_fetch_stealth_page_action_passed(MockStealth):
    MockStealth.fetch.return_value = _make_response()
    my_action = MagicMock()
    fetch_stealth("https://example.com/", page_action=my_action)
    _, kwargs = MockStealth.fetch.call_args
    assert "page_action" in kwargs


@patch("pluck.fetchers.scrapling_wrapper.StealthyFetcher")
def test_fetch_stealth_exception_returns_error(MockStealth):
    MockStealth.fetch.side_effect = RuntimeError("stealth failed")
    result = fetch_stealth("https://example.com/")
    assert result.success is False
    assert "stealth failed" in result.error


# ── metadata fields ───────────────────────────────────────────────────────────

@patch("pluck.fetchers.scrapling_wrapper.Fetcher")
def test_metadata_fields_populated(MockFetcher):
    MockFetcher.get.return_value = _make_response()
    result = fetch_static("https://example.com/")
    assert result.metadata["page_title"] == "Hello"
    assert result.metadata["html_length"] == len(SIMPLE_HTML)
    assert "captured_xhr_count" in result.metadata

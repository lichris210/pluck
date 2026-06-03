"""
Live integration tests for Phase 2 fetchers.

These tests make real network requests and may launch a browser.
Run with:  pytest -m integration

NOT included in the default test run.
"""

import pytest

from pluck.fetchers.scrapling_wrapper import fetch_dynamic, fetch_static


@pytest.mark.integration
def test_fetch_static_pypi_scrapling():
    """Fetcher.get() against a real page should return non-empty HTML."""
    result = fetch_static("https://pypi.org/project/scrapling/", timeout_seconds=20)
    assert result.success, f"fetch_static failed: {result.error}"
    assert len(result.html) > 1_000, "Expected substantial HTML from PyPI"
    assert result.metadata["page_title"] != ""
    assert result.fetch_time_ms > 0


@pytest.mark.integration
def test_fetch_dynamic_pypi_search_more_content_than_static():
    """DynamicFetcher should return more HTML than static on JS-rendered search page."""
    static = fetch_static("https://pypi.org/search/?q=scrapling", timeout_seconds=20)
    dynamic = fetch_dynamic(
        "https://pypi.org/search/?q=scrapling",
        timeout_seconds=45,
    )
    assert dynamic.success, f"fetch_dynamic failed: {dynamic.error}"
    assert len(dynamic.html) > 1_000

    # The JS-rendered page should have more content than the plain HTTP response.
    # (Static may still return non-trivial HTML from PyPI's SSR fallback, but
    # DynamicFetcher should be >= static in all cases.)
    assert len(dynamic.html) >= len(static.html), (
        f"Expected dynamic ({len(dynamic.html)}) >= static ({len(static.html)})"
    )

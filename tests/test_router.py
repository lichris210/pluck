"""
Unit tests for fetchers/router.py.

All wrapper functions are mocked — no real network or browser calls.
"""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pluck.fetchers.router import fetch
from pluck.models import FetchResult, SiteGroup, SiteProfile


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _profile(site_group: SiteGroup, url: str = "https://example.com/") -> SiteProfile:
    return SiteProfile(
        url=url,
        final_url=url,
        status_code=200,
        headers={},
        content_type="text/html",
        html="<html><body>ok</body></html>",
        site_group=site_group,
        classification_reasons=["test"],
        response_time_ms=10.0,
    )


def _ok_result(fetcher="AsyncFetcher") -> FetchResult:
    return FetchResult(
        url="https://example.com/",
        html="<html><body>fetched</body></html>",
        fetcher_used=fetcher,
        fetch_time_ms=50.0,
        success=True,
        metadata={"page_title": "Test", "html_length": 30, "captured_xhr_count": 0, "captured_xhr_urls": []},
    )


def _fail_result(fetcher="AsyncFetcher") -> FetchResult:
    return FetchResult(
        url="https://example.com/",
        html="",
        fetcher_used=fetcher,
        fetch_time_ms=5.0,
        success=False,
        error="TimeoutError: timed out",
        metadata={},
    )


# ── AUTH_GATED / FORTRESS: no token ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_auth_gated_returns_error_when_no_token():
    profile = _profile(SiteGroup.AUTH_GATED)
    with patch.dict(os.environ, {}, clear=True), \
         patch("pluck.fetchers.router.fetch_static_async") as mock_s, \
         patch("pluck.fetchers.router.fetch_dynamic") as mock_d, \
         patch("pluck.fetchers.router.fetch_stealth") as mock_st:
        result = await fetch(profile)
    assert result.success is False
    assert "APIFY_TOKEN" in result.error
    mock_s.assert_not_called()
    mock_d.assert_not_called()
    mock_st.assert_not_called()


@pytest.mark.asyncio
async def test_fortress_returns_error_when_no_token():
    profile = _profile(SiteGroup.FORTRESS)
    with patch.dict(os.environ, {}, clear=True), \
         patch("pluck.fetchers.router.fetch_static_async") as mock_s, \
         patch("pluck.fetchers.router.fetch_dynamic") as mock_d, \
         patch("pluck.fetchers.router.fetch_stealth") as mock_st:
        result = await fetch(profile)
    assert result.success is False
    assert "APIFY_TOKEN" in result.error
    mock_s.assert_not_called()
    mock_d.assert_not_called()
    mock_st.assert_not_called()


# ── AUTH_GATED / FORTRESS: with token ─────────────────────────────────────────

def _apify_ok_result() -> FetchResult:
    return FetchResult(
        url="https://linkedin.com/in/alice/",
        html="",
        fetcher_used="ApifyActor:anchor/linkedin-profile-scraper",
        fetch_time_ms=0.0,
        success=True,
        structured_data=[{"name": "Alice", "headline": "Engineer"}],
        metadata={"actor_id": "anchor/linkedin-profile-scraper"},
    )


@pytest.mark.asyncio
async def test_auth_gated_calls_apify_when_token_set():
    profile = _profile(SiteGroup.AUTH_GATED, url="https://www.linkedin.com/in/alice/")
    with patch.dict(os.environ, {"APIFY_TOKEN": "tok-123"}), \
         patch("pluck.fetchers.router.fetch_via_apify", new_callable=AsyncMock) as mock_apify:
        mock_apify.return_value = _apify_ok_result()
        result = await fetch(profile)
    mock_apify.assert_called_once_with(profile.final_url, "tok-123", max_items=100)
    assert result.success is True
    assert result.structured_data is not None


@pytest.mark.asyncio
async def test_fortress_calls_apify_when_token_set():
    profile = _profile(SiteGroup.FORTRESS, url="https://www.linkedin.com/in/bob/")
    with patch.dict(os.environ, {"APIFY_TOKEN": "tok-456"}), \
         patch("pluck.fetchers.router.fetch_via_apify", new_callable=AsyncMock) as mock_apify:
        mock_apify.return_value = _apify_ok_result()
        result = await fetch(profile)
    mock_apify.assert_called_once_with(profile.final_url, "tok-456", max_items=100)
    assert result.success is True


@pytest.mark.asyncio
async def test_apify_max_items_propagates():
    """A non-default max_items must reach fetch_via_apify."""
    profile = _profile(SiteGroup.AUTH_GATED, url="https://www.linkedin.com/in/carol/")
    with patch.dict(os.environ, {"APIFY_TOKEN": "tok-789"}), \
         patch("pluck.fetchers.router.fetch_via_apify", new_callable=AsyncMock) as mock_apify:
        mock_apify.return_value = _apify_ok_result()
        result = await fetch(profile, max_items=25)
    mock_apify.assert_called_once_with(profile.final_url, "tok-789", max_items=25)
    assert result.success is True


@pytest.mark.asyncio
async def test_apify_branch_uses_plan_when_provided():
    """When a plan is passed, fetch_via_apify_plan runs and the legacy path does not."""
    profile = _profile(SiteGroup.AUTH_GATED, url="https://www.linkedin.com/in/dave/")
    plan = {
        "actor_id": "anchor/linkedin-profile-scraper",
        "actor_input": {"profileUrls": ["https://linkedin.com/in/dave"], "maxItems": 100},
        "output_shape": {"explode_field": None, "columns": ["name"], "rename": {}},
    }
    with patch.dict(os.environ, {"APIFY_TOKEN": "tok-plan"}), \
         patch("pluck.fetchers.router.fetch_via_apify_plan", new_callable=AsyncMock) as mock_plan, \
         patch("pluck.fetchers.router.fetch_via_apify", new_callable=AsyncMock) as mock_legacy:
        mock_plan.return_value = _apify_ok_result()
        result = await fetch(profile, plan=plan)
    mock_plan.assert_called_once_with(plan, "tok-plan", max_items=100)
    mock_legacy.assert_not_called()
    assert result.success is True


@pytest.mark.asyncio
async def test_apify_branch_uses_legacy_when_no_plan():
    """With plan=None (the default), the legacy fetch_via_apify path is used."""
    profile = _profile(SiteGroup.AUTH_GATED, url="https://www.linkedin.com/in/erin/")
    with patch.dict(os.environ, {"APIFY_TOKEN": "tok-legacy"}), \
         patch("pluck.fetchers.router.fetch_via_apify_plan", new_callable=AsyncMock) as mock_plan, \
         patch("pluck.fetchers.router.fetch_via_apify", new_callable=AsyncMock) as mock_legacy:
        mock_legacy.return_value = _apify_ok_result()
        result = await fetch(profile)
    mock_legacy.assert_called_once_with(profile.final_url, "tok-legacy", max_items=100)
    mock_plan.assert_not_called()
    assert result.success is True


@pytest.mark.asyncio
async def test_apify_fetch_time_is_stamped_by_router():
    profile = _profile(SiteGroup.AUTH_GATED)
    with patch.dict(os.environ, {"APIFY_TOKEN": "tok"}), \
         patch("pluck.fetchers.router.fetch_via_apify", new_callable=AsyncMock) as mock_apify:
        mock_apify.return_value = _apify_ok_result()
        result = await fetch(profile)
    assert result.fetch_time_ms >= 0


# ── Routing ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_static_html_routes_to_fetch_static_async():
    profile = _profile(SiteGroup.STATIC_HTML)
    with patch("pluck.fetchers.router.fetch_static_async", new_callable=AsyncMock) as mock_s, \
         patch("pluck.fetchers.router.fetch_dynamic") as mock_d:
        mock_s.return_value = _ok_result()
        result = await fetch(profile)
    mock_s.assert_called_once_with(profile.final_url)
    mock_d.assert_not_called()
    assert result.success is True


@pytest.mark.asyncio
async def test_server_rendered_paginated_routes_to_fetch_static_async():
    profile = _profile(SiteGroup.SERVER_RENDERED_PAGINATED)
    with patch("pluck.fetchers.router.fetch_static_async", new_callable=AsyncMock) as mock_s, \
         patch("pluck.fetchers.router.fetch_dynamic") as mock_d:
        mock_s.return_value = _ok_result()
        result = await fetch(profile)
    mock_s.assert_called_once()
    mock_d.assert_not_called()


@pytest.mark.asyncio
async def test_js_rendered_clean_api_uses_capture_xhr():
    profile = _profile(SiteGroup.JS_RENDERED_CLEAN_API)
    with patch("pluck.fetchers.router.fetch_dynamic") as mock_d:
        mock_d.return_value = _ok_result("DynamicFetcher")
        result = await fetch(profile)
    args, kwargs = mock_d.call_args
    # Third positional arg is capture_xhr_pattern
    assert args[2] == "/api/"


@pytest.mark.asyncio
async def test_js_rendered_messy_dom_routes_to_fetch_dynamic_no_xhr():
    profile = _profile(SiteGroup.JS_RENDERED_MESSY_DOM)
    with patch("pluck.fetchers.router.fetch_dynamic") as mock_d:
        mock_d.return_value = _ok_result("DynamicFetcher")
        result = await fetch(profile)
    args, _ = mock_d.call_args
    # Only url and timeout_seconds — no capture_xhr_pattern
    assert len(args) == 1  # only url (defaults for the rest)
    assert args[0] == profile.final_url


@pytest.mark.asyncio
async def test_interactive_gated_routes_to_fetch_stealth():
    profile = _profile(SiteGroup.INTERACTIVE_GATED)
    with patch("pluck.fetchers.router.fetch_stealth") as mock_st:
        mock_st.return_value = _ok_result("StealthyFetcher")
        result = await fetch(profile)
    mock_st.assert_called_once()
    args, _ = mock_st.call_args
    assert args[0] == profile.final_url


@pytest.mark.asyncio
async def test_interactive_gated_passes_page_action():
    profile = _profile(SiteGroup.INTERACTIVE_GATED)
    with patch("pluck.fetchers.router.fetch_stealth") as mock_st:
        mock_st.return_value = _ok_result("StealthyFetcher")
        await fetch(profile)
    _, kwargs = mock_st.call_args
    # page_action should be the dismiss_cookie_banners coroutine function
    assert kwargs.get("page_action") is not None or mock_st.call_args[0][2] is not None


# ── Fallback logic ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_static_html_fallback_on_failure():
    """If AsyncFetcher fails (success=False), router retries with DynamicFetcher."""
    profile = _profile(SiteGroup.STATIC_HTML)
    dynamic_result = _ok_result("DynamicFetcher")
    with patch("pluck.fetchers.router.fetch_static_async", new_callable=AsyncMock) as mock_s, \
         patch("pluck.fetchers.router.fetch_dynamic") as mock_d:
        mock_s.return_value = _fail_result()
        mock_d.return_value = dynamic_result
        result = await fetch(profile)
    mock_s.assert_called_once()
    mock_d.assert_called_once()
    assert result.success is True
    assert result.fetcher_used == "DynamicFetcher"


@pytest.mark.asyncio
async def test_static_html_no_fallback_when_success_with_empty_html():
    """success=True + empty html is not a failure — fallback must NOT trigger."""
    profile = _profile(SiteGroup.STATIC_HTML)
    empty_but_ok = FetchResult(
        url="https://example.com/",
        html="",
        fetcher_used="AsyncFetcher",
        fetch_time_ms=10.0,
        success=True,
        metadata={},
    )
    with patch("pluck.fetchers.router.fetch_static_async", new_callable=AsyncMock) as mock_s, \
         patch("pluck.fetchers.router.fetch_dynamic") as mock_d:
        mock_s.return_value = empty_but_ok
        result = await fetch(profile)
    mock_d.assert_not_called()
    assert result.success is True


# ── Timing ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_time_ms_is_captured():
    profile = _profile(SiteGroup.STATIC_HTML)
    with patch("pluck.fetchers.router.fetch_static_async", new_callable=AsyncMock) as mock_s:
        mock_s.return_value = _ok_result()
        result = await fetch(profile)
    assert isinstance(result.fetch_time_ms, float)
    assert result.fetch_time_ms >= 0


@pytest.mark.asyncio
async def test_auth_gated_fetch_time_ms_populated():
    profile = _profile(SiteGroup.AUTH_GATED)
    result = await fetch(profile)
    assert isinstance(result.fetch_time_ms, float)
    assert result.fetch_time_ms >= 0

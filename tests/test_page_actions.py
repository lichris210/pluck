"""
Unit tests for fetchers/page_actions.py.

Page objects are mocked — no real browser.
"""

from unittest.mock import MagicMock, call

import pytest

from pluck.fetchers.page_actions import dismiss_cookie_banners, scroll_to_bottom, wait_for_idle


def _make_page(button_texts: list[str] | None = None):
    """Build a minimal mock Playwright sync Page.

    Caches button mocks so repeated calls to .nth(i) return the same object,
    allowing click-assertion checks after the function under test runs.
    """
    page = MagicMock()
    if button_texts is None:
        button_texts = []

    btn_mocks: dict[int, MagicMock] = {}

    def _make_btn(i: int) -> MagicMock:
        if i not in btn_mocks:
            btn = MagicMock()
            btn.inner_text.return_value = button_texts[i] if i < len(button_texts) else ""
            btn_mocks[i] = btn
        return btn_mocks[i]

    buttons_locator = MagicMock()
    buttons_locator.count.return_value = len(button_texts)
    buttons_locator.nth.side_effect = _make_btn
    page.locator.return_value = buttons_locator
    # Expose the btn_mocks cache so tests can look up buttons by index
    page._btn_mocks = btn_mocks
    return page


# ── dismiss_cookie_banners ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dismiss_no_buttons_does_not_raise():
    page = _make_page([])
    await dismiss_cookie_banners(page)  # must not raise


@pytest.mark.asyncio
async def test_dismiss_no_matching_text_does_not_click():
    page = _make_page(["Share", "Subscribe", "Learn more"])
    await dismiss_cookie_banners(page)
    # click should never have been called
    for call_args in page.locator.return_value.nth.call_args_list:
        btn_mock = page.locator.return_value.nth.side_effect(call_args[0][0])
        btn_mock.click.assert_not_called()


@pytest.mark.asyncio
async def test_dismiss_clicks_accept_button():
    page = _make_page(["Decline", "Accept"])
    await dismiss_cookie_banners(page)
    # btn_mocks[1] is the "Accept" button — it must have been clicked once
    assert page._btn_mocks[1].click.call_count == 1


@pytest.mark.asyncio
async def test_dismiss_clicks_accept_all():
    page = _make_page(["Accept all"])
    await dismiss_cookie_banners(page)
    assert page._btn_mocks[0].click.call_count == 1


@pytest.mark.asyncio
async def test_dismiss_page_locator_raises_does_not_propagate():
    page = MagicMock()
    page.locator.side_effect = RuntimeError("page crashed")
    await dismiss_cookie_banners(page)  # must not raise


# ── scroll_to_bottom ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_scroll_to_bottom_calls_evaluate():
    page = MagicMock()
    await scroll_to_bottom(page)
    page.evaluate.assert_called_once()
    script = page.evaluate.call_args[0][0]
    assert "scrollTo" in script or "scrollHeight" in script


@pytest.mark.asyncio
async def test_scroll_to_bottom_evaluate_raises_does_not_propagate():
    page = MagicMock()
    page.evaluate.side_effect = RuntimeError("eval failed")
    await scroll_to_bottom(page)  # must not raise


# ── wait_for_idle ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_wait_for_idle_calls_wait_for_load_state():
    page = MagicMock()
    await wait_for_idle(page, timeout_ms=2000)
    page.wait_for_load_state.assert_called_once_with("networkidle", timeout=2000)


@pytest.mark.asyncio
async def test_wait_for_idle_timeout_raises_does_not_propagate():
    page = MagicMock()
    page.wait_for_load_state.side_effect = TimeoutError("idle timeout")
    await wait_for_idle(page)  # must not raise

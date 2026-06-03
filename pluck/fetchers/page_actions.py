"""
Reusable page_action callbacks for StealthyFetcher.

These are `async def` so they can be tested with pytest-asyncio and used with
Scrapling's async-controller path.  When passed to the *sync* StealthyFetcher,
scrapling_wrapper.py wraps them with _make_sync_page_action() so they run in a
fresh event loop inside the worker thread.

All functions swallow exceptions silently — a failed banner dismissal must never
abort the scrape.
"""

import asyncio
import logging
import re

logger = logging.getLogger(__name__)

_CONSENT_RE = re.compile(
    r"^(accept(\s+all)?|agree|got\s+it|ok|i\s+accept|allow(\s+(all|cookies))?|continue)$",
    re.IGNORECASE,
)


async def dismiss_cookie_banners(page) -> None:
    """Click the first visible consent / GDPR accept button found on the page."""
    try:
        buttons = page.locator("button")
        count = buttons.count()
        for i in range(count):
            try:
                btn = buttons.nth(i)
                text = btn.inner_text().strip()
                if _CONSENT_RE.match(text):
                    btn.click()
                    page.wait_for_timeout(500)
                    return
            except Exception:
                continue
    except Exception as exc:
        logger.debug("dismiss_cookie_banners: %s", exc)


async def scroll_to_bottom(page) -> None:
    """Scroll to the bottom of the page to trigger lazy-loaded content."""
    try:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(800)
    except Exception as exc:
        logger.debug("scroll_to_bottom: %s", exc)


async def wait_for_idle(page, timeout_ms: int = 3000) -> None:
    """Wait for network to be idle for up to timeout_ms milliseconds."""
    try:
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception as exc:
        logger.debug("wait_for_idle: %s", exc)

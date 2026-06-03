"""
Thin wrappers around Scrapling fetchers.  All return FetchResult.

Timeout units (README gotcha):
  Fetcher / AsyncFetcher  → seconds   (plain HTTP via curl_cffi)
  DynamicFetcher          → milliseconds  (Playwright)
  StealthyFetcher         → milliseconds  (Patchright / Camoufox)
"""

import asyncio
import json
import logging
import time
from typing import Callable

from bs4 import BeautifulSoup
from scrapling import AsyncFetcher, Fetcher
from scrapling import DynamicFetcher, StealthyFetcher

from pluck.models import FetchResult

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_title(html: str) -> str:
    try:
        soup = BeautifulSoup(html, "lxml")
        tag = soup.find("title")
        return tag.get_text(strip=True) if tag else ""
    except Exception:
        return ""


def _parse_xhr_data(captured_xhr: list) -> list[dict] | None:
    """Parse JSON from captured XHR responses.  Returns None if nothing useful."""
    results: list[dict] = []
    for xhr in captured_xhr:
        try:
            data = xhr.json()
            if isinstance(data, list):
                results.extend(d for d in data if isinstance(d, dict))
            elif isinstance(data, dict):
                results.append(data)
        except Exception:
            pass
    return results if results else None


def _make_sync_page_action(page_action: Callable) -> Callable:
    """Wrap an async page_action so it can be passed to sync StealthyFetcher.

    StealthyFetcher.fetch() calls page_action(page) synchronously inside the
    browser thread.  This wrapper runs a fresh event loop in that same thread,
    which works because asyncio.to_thread() gives us a bare worker thread with
    no event loop installed.
    """
    if page_action is None:
        return None
    if not asyncio.iscoroutinefunction(page_action):
        return page_action

    def _sync(page):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(page_action(page))
        except Exception as exc:
            logger.debug("page_action raised: %s", exc)
        finally:
            loop.close()
            asyncio.set_event_loop(None)

    return _sync


def _build_metadata(html: str, captured_xhr: list | None = None) -> dict:
    return {
        "page_title": _extract_title(html),
        "html_length": len(html),
        "captured_xhr_count": len(captured_xhr) if captured_xhr else 0,
        "captured_xhr_urls": [getattr(x, "url", "") for x in (captured_xhr or [])],
    }


# ── Sync static fetcher ───────────────────────────────────────────────────────

def fetch_static(url: str, timeout_seconds: float = 15.0) -> FetchResult:
    """Plain HTTP via curl_cffi (Fetcher).  Timeout is in seconds."""
    start = time.perf_counter()
    try:
        response = Fetcher.get(url, stealthy_headers=True, timeout=timeout_seconds)
        html = str(response.html_content)
        elapsed = (time.perf_counter() - start) * 1000
        return FetchResult(
            url=url,
            html=html,
            fetcher_used="Fetcher",
            fetch_time_ms=elapsed,
            success=True,
            metadata=_build_metadata(html),
        )
    except Exception as exc:
        elapsed = (time.perf_counter() - start) * 1000
        return FetchResult(
            url=url,
            html="",
            fetcher_used="Fetcher",
            fetch_time_ms=elapsed,
            success=False,
            error=f"{type(exc).__name__}: {exc}",
            metadata={},
        )


# ── Async static fetcher ──────────────────────────────────────────────────────

async def fetch_static_async(url: str, timeout_seconds: float = 15.0) -> FetchResult:
    """Async HTTP via curl_cffi (AsyncFetcher).  Timeout is in seconds."""
    start = time.perf_counter()
    try:
        response = await AsyncFetcher.get(url, stealthy_headers=True, timeout=timeout_seconds)
        html = str(response.html_content)
        elapsed = (time.perf_counter() - start) * 1000
        return FetchResult(
            url=url,
            html=html,
            fetcher_used="AsyncFetcher",
            fetch_time_ms=elapsed,
            success=True,
            metadata=_build_metadata(html),
        )
    except Exception as exc:
        elapsed = (time.perf_counter() - start) * 1000
        return FetchResult(
            url=url,
            html="",
            fetcher_used="AsyncFetcher",
            fetch_time_ms=elapsed,
            success=False,
            error=f"{type(exc).__name__}: {exc}",
            metadata={},
        )


# ── Dynamic (Playwright) fetcher ──────────────────────────────────────────────

def fetch_dynamic(
    url: str,
    timeout_seconds: float = 30.0,
    capture_xhr_pattern: str | None = None,
) -> FetchResult:
    """JS-rendering via DynamicFetcher (Playwright).

    CRITICAL: Scrapling browser timeouts are in MILLISECONDS.
    timeout_seconds is converted: timeout_ms = int(timeout_seconds * 1000)
    """
    start = time.perf_counter()
    timeout_ms = int(timeout_seconds * 1000)
    try:
        kwargs: dict = dict(
            headless=True,
            network_idle=True,
            timeout=timeout_ms,
        )
        if capture_xhr_pattern:
            kwargs["capture_xhr"] = capture_xhr_pattern

        response = DynamicFetcher.fetch(url, **kwargs)
        html = str(response.html_content)
        captured = getattr(response, "captured_xhr", [])
        structured_data = _parse_xhr_data(captured) if capture_xhr_pattern else None
        elapsed = (time.perf_counter() - start) * 1000

        meta = _build_metadata(html, captured)
        if capture_xhr_pattern:
            meta["captured_xhr_url"] = kwargs.get("capture_xhr")

        return FetchResult(
            url=url,
            html=html,
            fetcher_used="DynamicFetcher",
            fetch_time_ms=elapsed,
            success=True,
            structured_data=structured_data,
            metadata=meta,
        )
    except Exception as exc:
        elapsed = (time.perf_counter() - start) * 1000
        return FetchResult(
            url=url,
            html="",
            fetcher_used="DynamicFetcher",
            fetch_time_ms=elapsed,
            success=False,
            error=f"{type(exc).__name__}: {exc}",
            metadata={},
        )


# ── Stealth (Patchright/Camoufox) fetcher ────────────────────────────────────

def fetch_stealth(
    url: str,
    timeout_seconds: float = 30.0,
    page_action: Callable | None = None,
) -> FetchResult:
    """Anti-bot bypass via StealthyFetcher (Patchright/Camoufox).

    CRITICAL: Scrapling browser timeouts are in MILLISECONDS.
    timeout_seconds is converted: timeout_ms = int(timeout_seconds * 1000)

    If page_action is an async coroutine function it is wrapped so it runs in a
    fresh event loop inside the worker thread (see _make_sync_page_action).
    """
    start = time.perf_counter()
    timeout_ms = int(timeout_seconds * 1000)
    try:
        kwargs: dict = dict(
            headless=True,
            network_idle=True,
            timeout=timeout_ms,
        )
        if page_action is not None:
            kwargs["page_action"] = _make_sync_page_action(page_action)

        response = StealthyFetcher.fetch(url, **kwargs)
        html = str(response.html_content)
        elapsed = (time.perf_counter() - start) * 1000
        return FetchResult(
            url=url,
            html=html,
            fetcher_used="StealthyFetcher",
            fetch_time_ms=elapsed,
            success=True,
            metadata=_build_metadata(html),
        )
    except Exception as exc:
        elapsed = (time.perf_counter() - start) * 1000
        return FetchResult(
            url=url,
            html="",
            fetcher_used="StealthyFetcher",
            fetch_time_ms=elapsed,
            success=False,
            error=f"{type(exc).__name__}: {exc}",
            metadata={},
        )

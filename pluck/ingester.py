import re
import time
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import httpx

from pluck.classifiers.site_classifier import classify
from pluck.models import SiteGroup, SiteProfile

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

_TRACKING_PARAMS = re.compile(
    r"^(utm_|fbclid|gclid|mc_|msclkid|igshid|ref_src|ref_url)",
    re.IGNORECASE,
)


def _strip_tracking_params(url: str) -> str:
    parsed = urlparse(url)
    qs = parse_qs(parsed.query, keep_blank_values=True)
    filtered = {k: v for k, v in qs.items() if not _TRACKING_PARAMS.match(k)}
    clean_query = urlencode(filtered, doseq=True)
    return urlunparse(parsed._replace(query=clean_query))


def _normalize_url(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    url = _strip_tracking_params(url)
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    return urlunparse(parsed._replace(path=path))


async def ingest(url: str, timeout: float = 30.0) -> SiteProfile:
    normalized = _normalize_url(url)

    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            max_redirects=5,
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
        ) as client:
            response = await client.get(normalized)
    except httpx.TimeoutException as exc:
        elapsed = (time.perf_counter() - start) * 1000
        return SiteProfile(
            url=url,
            final_url=normalized,
            status_code=0,
            headers={},
            content_type="",
            html="",
            site_group=SiteGroup.STATIC_HTML,
            classification_reasons=[],
            response_time_ms=elapsed,
            error=f"Request timed out: {exc}",
        )
    except httpx.ConnectError as exc:
        elapsed = (time.perf_counter() - start) * 1000
        return SiteProfile(
            url=url,
            final_url=normalized,
            status_code=0,
            headers={},
            content_type="",
            html="",
            site_group=SiteGroup.STATIC_HTML,
            classification_reasons=[],
            response_time_ms=elapsed,
            error=f"Connection error: {exc}",
        )
    except httpx.RequestError as exc:
        elapsed = (time.perf_counter() - start) * 1000
        return SiteProfile(
            url=url,
            final_url=normalized,
            status_code=0,
            headers={},
            content_type="",
            html="",
            site_group=SiteGroup.STATIC_HTML,
            classification_reasons=[],
            response_time_ms=elapsed,
            error=f"Request error: {exc}",
        )

    elapsed = (time.perf_counter() - start) * 1000
    final_url = str(response.url)
    status_code = response.status_code
    headers = dict(response.headers)
    content_type = response.headers.get("content-type", "")
    ct_base = content_type.split(";")[0].strip().lower()

    non_html_types = (
        "image/",
        "video/",
        "audio/",
        "application/octet-stream",
        "application/pdf",
        "application/zip",
        "application/x-",
    )
    if ct_base and not ct_base.startswith("text/") and not "html" in ct_base:
        if any(ct_base.startswith(t) for t in non_html_types) or (
            ct_base.startswith("application/") and "html" not in ct_base and "xml" not in ct_base
        ):
            return SiteProfile(
                url=url,
                final_url=final_url,
                status_code=status_code,
                headers=headers,
                content_type=content_type,
                html="",
                site_group=SiteGroup.STATIC_HTML,
                classification_reasons=[],
                response_time_ms=elapsed,
                error=f"Non-HTML content type: {content_type}",
            )

    html = response.text
    site_group, classification_reasons = classify(final_url, status_code, headers, html)

    return SiteProfile(
        url=url,
        final_url=final_url,
        status_code=status_code,
        headers=headers,
        content_type=content_type,
        html=html,
        site_group=site_group,
        classification_reasons=classification_reasons,
        response_time_ms=elapsed,
    )

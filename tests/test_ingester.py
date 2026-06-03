import pytest
import respx
import httpx

from pluck.ingester import ingest, _normalize_url
from pluck.models import SiteGroup


SIMPLE_HTML = """<!DOCTYPE html><html><head><title>Test</title></head>
<body><p>Hello world, this is a simple test page with enough content to be classified.</p></body>
</html>"""


# ── URL normalization ─────────────────────────────────────────────────────────

def test_normalize_strips_utm_params():
    url = _normalize_url("https://example.com/?utm_source=google&utm_medium=cpc&q=python")
    assert "utm_source" not in url
    assert "utm_medium" not in url
    assert "q=python" in url


def test_normalize_strips_fbclid():
    url = _normalize_url("https://example.com/page?fbclid=IwAR123abc")
    assert "fbclid" not in url


def test_normalize_strips_gclid():
    url = _normalize_url("https://example.com/?gclid=Cj0KCQxxx&ref=home")
    assert "gclid" not in url
    assert "ref=home" in url


def test_normalize_strips_mc_params():
    url = _normalize_url("https://example.com/?mc_cid=abc123&mc_eid=xyz")
    assert "mc_cid" not in url
    assert "mc_eid" not in url


def test_normalize_trailing_slash_removed():
    url = _normalize_url("https://example.com/about/")
    assert not url.endswith("/about/")
    assert url.endswith("/about")


def test_normalize_adds_https_scheme():
    url = _normalize_url("example.com/page")
    assert url.startswith("https://")


# ── Successful fetch ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_successful_fetch_returns_profile():
    respx.get("https://example.com/page").mock(
        return_value=httpx.Response(200, text=SIMPLE_HTML, headers={"content-type": "text/html"})
    )
    profile = await ingest("https://example.com/page")
    assert profile.status_code == 200
    assert profile.html == SIMPLE_HTML
    assert profile.error is None
    assert profile.site_group is not None
    assert isinstance(profile.classification_reasons, list)


@pytest.mark.asyncio
@respx.mock
async def test_user_agent_sent():
    request_headers = {}

    def capture(request):
        request_headers.update(dict(request.headers))
        return httpx.Response(200, text=SIMPLE_HTML, headers={"content-type": "text/html"})

    respx.get("https://example.com/").mock(side_effect=capture)
    await ingest("https://example.com/")
    assert "mozilla" in request_headers.get("user-agent", "").lower()


# ── Redirect following ────────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_redirect_sets_final_url():
    respx.get("https://example.com/old").mock(
        return_value=httpx.Response(
            301,
            headers={"location": "https://example.com/new", "content-type": "text/html"},
            text="",
        )
    )
    respx.get("https://example.com/new").mock(
        return_value=httpx.Response(200, text=SIMPLE_HTML, headers={"content-type": "text/html"})
    )
    profile = await ingest("https://example.com/old")
    assert profile.final_url == "https://example.com/new"


# ── Error cases ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_timeout_returns_error_profile():
    respx.get("https://example.com/slow").mock(side_effect=httpx.ReadTimeout("timed out", request=None))
    profile = await ingest("https://example.com/slow")
    assert profile.error is not None
    assert "timeout" in profile.error.lower() or "timed out" in profile.error.lower()
    assert profile.status_code == 0


@pytest.mark.asyncio
@respx.mock
async def test_connection_error_returns_error_profile():
    respx.get("https://unreachable.example.com/").mock(
        side_effect=httpx.ConnectError("Connection refused")
    )
    profile = await ingest("https://unreachable.example.com/")
    assert profile.error is not None
    assert "connection" in profile.error.lower()
    assert profile.status_code == 0


# ── HTTP error status codes ───────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_404_status_code_populated():
    respx.get("https://example.com/missing").mock(
        return_value=httpx.Response(404, text="<html><body>Not Found</body></html>", headers={"content-type": "text/html"})
    )
    profile = await ingest("https://example.com/missing")
    assert profile.status_code == 404
    assert profile.error is None  # 404 is not an error, just a status


@pytest.mark.asyncio
@respx.mock
async def test_500_status_code_populated():
    respx.get("https://example.com/error").mock(
        return_value=httpx.Response(500, text="<html><body>Server Error</body></html>", headers={"content-type": "text/html"})
    )
    profile = await ingest("https://example.com/error")
    assert profile.status_code == 500
    assert profile.error is None


# ── Non-HTML content ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_non_html_content_type_sets_error():
    respx.get("https://example.com/image.png").mock(
        return_value=httpx.Response(
            200,
            content=b"\x89PNG\r\n",
            headers={"content-type": "image/png"},
        )
    )
    profile = await ingest("https://example.com/image.png")
    assert profile.error is not None
    assert "non-html" in profile.error.lower()
    # Classification was skipped
    assert profile.classification_reasons == []


@pytest.mark.asyncio
@respx.mock
async def test_non_html_skips_classification():
    respx.get("https://example.com/file.pdf").mock(
        return_value=httpx.Response(
            200,
            content=b"%PDF-1.4",
            headers={"content-type": "application/pdf"},
        )
    )
    profile = await ingest("https://example.com/file.pdf")
    assert profile.error is not None
    assert profile.site_group == SiteGroup.STATIC_HTML
    assert profile.classification_reasons == []


# ── Response time captured ────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_response_time_ms_populated():
    respx.get("https://example.com/fast").mock(
        return_value=httpx.Response(200, text=SIMPLE_HTML, headers={"content-type": "text/html"})
    )
    profile = await ingest("https://example.com/fast")
    assert profile.response_time_ms >= 0
    assert isinstance(profile.response_time_ms, float)

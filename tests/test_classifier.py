import pytest

from pluck.classifiers.site_classifier import classify
from pluck.models import SiteGroup


# ── Fortress: domain list ─────────────────────────────────────────────────────

@pytest.mark.parametrize("url", [
    "https://www.linkedin.com/jobs/",
    "https://linkedin.com/in/someone",
    "https://m.linkedin.com/feed/",
    "https://www.facebook.com/",
    "https://instagram.com/user",
    "https://twitter.com/home",
    "https://x.com/home",
    "https://www.tiktok.com/@user",
])
def test_fortress_domain(url, static_article_html):
    group, reasons = classify(url, 200, {}, static_article_html)
    assert group == SiteGroup.FORTRESS
    assert any("fortress list" in r.lower() for r in reasons)


# ── Fortress: Cloudflare challenge ────────────────────────────────────────────

def test_fortress_cloudflare_challenge(cloudflare_challenge_html):
    group, reasons = classify("https://example.com/", 200, {}, cloudflare_challenge_html)
    assert group == SiteGroup.FORTRESS
    assert any("cloudflare" in r.lower() for r in reasons)


def test_fortress_cf_chl_jschl(cloudflare_challenge_html):
    # __cf_chl_jschl marker is present in the fixture
    group, _ = classify("https://somesite.org/", 200, {}, cloudflare_challenge_html)
    assert group == SiteGroup.FORTRESS


def test_fortress_perimeter_x():
    html = '<html><body><script>window._pxhd="abc";</script></body></html>'
    group, reasons = classify("https://example.com/", 200, {}, html)
    assert group == SiteGroup.FORTRESS
    assert any("perimeterx" in r.lower() or "human" in r.lower() for r in reasons)


# ── Auth-gated: HTTP status ───────────────────────────────────────────────────

def test_auth_gated_401():
    group, reasons = classify("https://api.example.com/data", 401, {}, "")
    assert group == SiteGroup.AUTH_GATED
    assert any("401" in r for r in reasons)


def test_auth_gated_403():
    group, reasons = classify("https://example.com/admin", 403, {}, "")
    assert group == SiteGroup.AUTH_GATED
    assert any("403" in r for r in reasons)


def test_auth_gated_login_form(login_form_html):
    group, reasons = classify("https://example.com/login", 200, {}, login_form_html)
    assert group == SiteGroup.AUTH_GATED
    assert any("password" in r.lower() for r in reasons)


def test_auth_gated_meta_refresh(meta_login_redirect_html):
    group, reasons = classify("https://example.com/dashboard", 200, {}, meta_login_redirect_html)
    assert group == SiteGroup.AUTH_GATED
    assert any("login" in r.lower() or "signin" in r.lower() for r in reasons)


# ── Interactive-gated ─────────────────────────────────────────────────────────

def test_interactive_cookie_banner(cookie_banner_html):
    group, reasons = classify("https://news.example.com/", 200, {}, cookie_banner_html)
    assert group == SiteGroup.INTERACTIVE_GATED
    assert any("cookie" in r.lower() for r in reasons)


def test_interactive_age_verification(age_verification_html):
    group, reasons = classify("https://adult.example.com/", 200, {}, age_verification_html)
    assert group == SiteGroup.INTERACTIVE_GATED
    assert any("age" in r.lower() for r in reasons)


def test_interactive_captcha(captcha_html):
    group, reasons = classify("https://example.com/verify", 200, {}, captcha_html)
    assert group == SiteGroup.INTERACTIVE_GATED
    assert any("captcha" in r.lower() or "recaptcha" in r.lower() for r in reasons)


def test_interactive_hcaptcha():
    html = '<html><body><div class="h-captcha" data-sitekey="xxx"></div></body></html>'
    group, reasons = classify("https://example.com/", 200, {}, html)
    assert group == SiteGroup.INTERACTIVE_GATED


def test_interactive_paywall():
    html = (
        "<html><body>"
        "<div class='paywall'>Subscribe to continue reading.</div>"
        "<article><p>" + ("x " * 300) + "</p></article>"
        "</body></html>"
    )
    group, reasons = classify("https://news.example.com/article", 200, {}, html)
    assert group == SiteGroup.INTERACTIVE_GATED
    assert any("paywall" in r.lower() for r in reasons)


# ── JS-rendered clean API ─────────────────────────────────────────────────────

def test_js_rendered_clean_api(react_spa_clean_html):
    group, reasons = classify("https://jobs.example.com/", 200, {}, react_spa_clean_html)
    assert group == SiteGroup.JS_RENDERED_CLEAN_API
    assert any("spa" in r.lower() or "minimal" in r.lower() for r in reasons)


def test_js_rendered_clean_next_js(next_js_html):
    # __NEXT_DATA__ + application/ld+json → clean API
    html = next_js_html.replace(
        "<title>Next.js App</title>",
        '<title>Next.js App</title>'
        '<script type="application/ld+json">{"@context":"https://schema.org"}</script>',
    )
    group, _ = classify("https://shop.example.com/", 200, {}, html)
    assert group == SiteGroup.JS_RENDERED_CLEAN_API


# ── JS-rendered messy DOM ─────────────────────────────────────────────────────

def test_js_rendered_messy_dom(react_spa_messy_html):
    group, reasons = classify("https://app.example.com/", 200, {}, react_spa_messy_html)
    assert group == SiteGroup.JS_RENDERED_MESSY_DOM
    assert any("spa" in r.lower() or "minimal" in r.lower() for r in reasons)


def test_js_rendered_nuxt():
    html = '<html><body><div id="__nuxt"></div><script>window.__nuxt__={}</script></body></html>'
    group, _ = classify("https://nuxt-app.example.com/", 200, {}, html)
    assert group == SiteGroup.JS_RENDERED_MESSY_DOM


# ── Server-rendered paginated ─────────────────────────────────────────────────

def test_paginated_link_rel(paginated_blog_html):
    group, reasons = classify("https://blog.example.com/", 200, {}, paginated_blog_html)
    assert group == SiteGroup.SERVER_RENDERED_PAGINATED
    assert any("next" in r.lower() or "pagination" in r.lower() for r in reasons)


def test_paginated_page_query_param():
    html = (
        "<html><body>"
        "<p>" + ("word " * 200) + "</p>"
        '<nav><a href="/posts?page=2">Next</a></nav>'
        "</body></html>"
    )
    group, reasons = classify("https://blog.example.com/posts", 200, {}, html)
    assert group == SiteGroup.SERVER_RENDERED_PAGINATED
    assert any("page=" in r for r in reasons)


# ── Static HTML fallback ──────────────────────────────────────────────────────

def test_static_html_fallback(static_article_html):
    group, reasons = classify("https://en.wikipedia.org/wiki/Python", 200, {}, static_article_html)
    assert group == SiteGroup.STATIC_HTML
    assert any("static" in r.lower() or "no special" in r.lower() for r in reasons)


def test_static_html_404():
    html = "<html><body><h1>404 Not Found</h1></body></html>"
    group, _ = classify("https://example.com/missing", 404, {}, html)
    # 404 is not in (401, 403) — should not be auth-gated
    assert group == SiteGroup.STATIC_HTML


# ── Classification reasons are populated ─────────────────────────────────────

def test_reasons_are_non_empty(static_article_html):
    _, reasons = classify("https://example.com/", 200, {}, static_article_html)
    assert len(reasons) >= 1
    assert all(isinstance(r, str) and len(r) > 0 for r in reasons)


def test_reasons_human_readable_fortress(static_article_html):
    _, reasons = classify("https://linkedin.com/jobs", 200, {}, static_article_html)
    assert any("linkedin.com" in r for r in reasons)


# ── Edge cases ────────────────────────────────────────────────────────────────

def test_empty_html():
    group, reasons = classify("https://example.com/", 200, {}, "")
    assert group in SiteGroup.__members__.values()
    assert isinstance(reasons, list)


def test_malformed_html():
    html = "<html><body><div class='cookie-banner'>Accept cookies</div><<<<</body>"
    group, reasons = classify("https://example.com/", 200, {}, html)
    # lxml handles malformed HTML gracefully
    assert group == SiteGroup.INTERACTIVE_GATED


def test_empty_body_tag():
    html = "<html><body></body></html>"
    group, _ = classify("https://example.com/", 200, {}, html)
    assert group == SiteGroup.STATIC_HTML


def test_gdpr_consent_class():
    html = (
        "<html><body>"
        '<div class="gdpr-consent"><button>Accept</button></div>'
        "<p>Content</p>"
        "</body></html>"
    )
    group, reasons = classify("https://eu-site.example.com/", 200, {}, html)
    assert group == SiteGroup.INTERACTIVE_GATED


def test_fortress_subdomain_not_in_list():
    # subdomain of a non-fortress domain should not be fortress
    group, _ = classify("https://linkedin.fakejobs.com/", 200, {}, "<html><body><p>hello</p></body></html>")
    # root domain is fakejobs.com, not linkedin.com
    assert group == SiteGroup.STATIC_HTML


def test_pagination_requires_substantial_content():
    # If content < 500 chars AND has pagination, should still check SPA first then paginate
    html = '<html><head><link rel="next" href="/page/2"/></head><body><p>Short</p></body></html>'
    group, _ = classify("https://blog.example.com/", 200, {}, html)
    # Minimal content without SPA markers → static (not paginated because content is too short)
    assert group == SiteGroup.STATIC_HTML

import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from pluck.models import SiteGroup

FORTRESS_DOMAINS = {
    "linkedin.com",
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "tiktok.com",
}


def _extract_root_domain(url: str) -> str:
    """Return the registered domain (e.g. 'linkedin.com') from a URL or hostname."""
    hostname = urlparse(url).hostname or url
    parts = hostname.lower().split(".")
    if len(parts) >= 2:
        return f"{parts[-2]}.{parts[-1]}"
    return hostname.lower()


def _is_fortress_domain(url: str) -> tuple[bool, str | None]:
    root = _extract_root_domain(url)
    if root in FORTRESS_DOMAINS:
        return True, root
    return False, None


def _visible_text_length(soup: BeautifulSoup) -> int:
    body = soup.find("body")
    if not body:
        return 0
    for tag in body.find_all(["script", "style", "noscript"]):
        tag.decompose()
    return len(body.get_text(separator=" ", strip=True))


def classify(
    url: str,
    status_code: int,
    headers: dict,
    html: str,
) -> tuple[SiteGroup, list[str]]:
    reasons: list[str] = []
    soup = BeautifulSoup(html, "lxml")
    lower_html = html.lower()

    # ── Group 7: FORTRESS ───────────────────────────────────────────────────
    is_fortress, matched_domain = _is_fortress_domain(url)
    if is_fortress:
        reasons.append(f"Domain matches fortress list: {matched_domain}")
        return SiteGroup.FORTRESS, reasons

    cloudflare_signals = [
        "cf-challenge" in lower_html,
        "__cf_chl_jschl" in lower_html,
        "cf_chl_prog" in lower_html,
    ]
    if any(cloudflare_signals):
        reasons.append("Cloudflare challenge page detected")
        return SiteGroup.FORTRESS, reasons

    perimeter_signals = [
        "_pxhd" in lower_html,
        "px-captcha" in lower_html,
        "human.security" in lower_html,
        "perimeterx" in lower_html,
    ]
    if any(perimeter_signals):
        reasons.append("PerimeterX/HUMAN anti-bot marker detected")
        return SiteGroup.FORTRESS, reasons

    # Fastly Smart Shield challenge — asset paths start with /_fs-ch-<nonce>/
    if "/_fs-ch-" in html:
        reasons.append("Fastly bot challenge page detected")
        return SiteGroup.FORTRESS, reasons

    # ── Group 6: AUTH_GATED ─────────────────────────────────────────────────
    if status_code in (401, 403):
        reasons.append(f"HTTP {status_code} response indicates authentication required")
        return SiteGroup.AUTH_GATED, reasons

    if soup.find("input", {"type": "password"}):
        reasons.append("Login form detected (input[type=password])")
        return SiteGroup.AUTH_GATED, reasons

    for meta in soup.find_all("meta", {"http-equiv": re.compile(r"refresh", re.I)}):
        content = (meta.get("content") or "").lower()
        if "/login" in content or "/signin" in content:
            reasons.append("Meta refresh redirects to login/signin page")
            return SiteGroup.AUTH_GATED, reasons

    # ── Group 5: INTERACTIVE_GATED ──────────────────────────────────────────
    cookie_patterns = re.compile(
        r"cookie[_-]?banner|cookie[_-]?consent|gdpr[_-]?banner|gdpr[_-]?consent|"
        r"cookiewall|cookie_notice",
        re.I,
    )
    for tag in soup.find_all(True):
        tag_id = tag.get("id") or ""
        tag_class = " ".join(tag.get("class") or [])
        if cookie_patterns.search(tag_id) or cookie_patterns.search(tag_class):
            reasons.append(f"Cookie consent overlay detected (id={tag_id!r} class={tag_class!r})")
            return SiteGroup.INTERACTIVE_GATED, reasons

    age_patterns = re.compile(r"age[_-]?verif|age[_-]?gate|age[_-]?check", re.I)
    for tag in soup.find_all(True):
        tag_id = tag.get("id") or ""
        tag_class = " ".join(tag.get("class") or [])
        if age_patterns.search(tag_id) or age_patterns.search(tag_class):
            reasons.append("Age verification gate detected")
            return SiteGroup.INTERACTIVE_GATED, reasons

    captcha_signals = [
        bool(soup.find(id=re.compile(r"g-recaptcha|h-captcha", re.I))),
        bool(soup.find(class_=re.compile(r"g-recaptcha|h-captcha", re.I))),
        "g-recaptcha" in lower_html,
        "hcaptcha" in lower_html,
        "data-sitekey" in lower_html,
    ]
    if any(captcha_signals):
        reasons.append("CAPTCHA marker detected (reCAPTCHA or hCaptcha)")
        return SiteGroup.INTERACTIVE_GATED, reasons

    paywall_patterns = re.compile(r"paywall|subscription[_-]?overlay|subscribe[_-]?wall", re.I)
    for tag in soup.find_all(True):
        tag_id = tag.get("id") or ""
        tag_class = " ".join(tag.get("class") or [])
        if paywall_patterns.search(tag_id) or paywall_patterns.search(tag_class):
            reasons.append("Subscription paywall overlay detected")
            return SiteGroup.INTERACTIVE_GATED, reasons

    # ── JS rendering signals ────────────────────────────────────────────────
    spa_markers = [
        bool(soup.find(id="root")),
        bool(soup.find(id="app")),
        bool(soup.find(id="__nuxt")),
        "__next_data__" in lower_html,
        "window.__nuxt__" in lower_html,
    ]
    has_spa_markers = any(spa_markers)
    visible_text = _visible_text_length(soup)
    minimal_content = visible_text < 500

    has_json_ld = bool(soup.find("script", {"type": "application/ld+json"}))
    has_schema_org = bool(soup.find(attrs={"itemtype": re.compile(r"schema\.org", re.I)}))
    has_structured_data = has_json_ld or has_schema_org

    # ── Group 3: JS_RENDERED_CLEAN_API ──────────────────────────────────────
    if minimal_content and has_spa_markers and has_structured_data:
        spa_detail = [m for m, v in zip(
            ["#root", "#app", "#__nuxt", "__NEXT_DATA__", "window.__nuxt__"],
            spa_markers,
        ) if v]
        reasons.append(f"Minimal visible text ({visible_text} chars), SPA markers {spa_detail}, structured data present")
        return SiteGroup.JS_RENDERED_CLEAN_API, reasons

    # ── Group 4: JS_RENDERED_MESSY_DOM ──────────────────────────────────────
    if minimal_content and has_spa_markers:
        spa_detail = [m for m, v in zip(
            ["#root", "#app", "#__nuxt", "__NEXT_DATA__", "window.__nuxt__"],
            spa_markers,
        ) if v]
        reasons.append(f"Minimal visible text ({visible_text} chars), SPA markers {spa_detail}, no structured data")
        return SiteGroup.JS_RENDERED_MESSY_DOM, reasons

    # ── Group 2: SERVER_RENDERED_PAGINATED ──────────────────────────────────
    pagination_signals: list[str] = []

    if soup.find("link", {"rel": "next"}) or soup.find("link", {"rel": "prev"}):
        pagination_signals.append("link[rel=next/prev] present")

    pagination_class = re.compile(r"\bpaginat", re.I)
    for tag in soup.find_all(True):
        tag_class = " ".join(tag.get("class") or [])
        tag_role = tag.get("role") or ""
        if pagination_class.search(tag_class) or tag_role.lower() == "navigation" and pagination_class.search(str(tag)):
            pagination_signals.append(f"Pagination element found (class={tag_class!r})")
            break

    for a in soup.find_all("a", href=True):
        if re.search(r"[?&]page=", a["href"], re.I):
            pagination_signals.append("?page= parameter in anchor href")
            break

    if pagination_signals and visible_text >= 500:
        reasons.extend(pagination_signals)
        return SiteGroup.SERVER_RENDERED_PAGINATED, reasons

    # ── Group 1: STATIC_HTML (default) ──────────────────────────────────────
    reasons.append("No special signals detected — treating as static HTML")
    return SiteGroup.STATIC_HTML, reasons

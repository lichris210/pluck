"""HTML noise filter — strips scripts, navigation, ads, hidden elements, cookie banners.

Reduces token cost and improves Claude extraction accuracy by removing content
that won't contribute to structured data extraction.
"""

import re
from collections import Counter

from bs4 import BeautifulSoup

# Tags removed unconditionally
_REMOVE_TAGS_HARD = ("script", "style", "noscript", "iframe")

# Tags removed (semantic role: not content)
_REMOVE_TAGS_SEMANTIC = ("nav", "footer", "aside")

# Tags whose content is preserved even if their class/id matches a noise pattern
_PRESERVE_TAGS = frozenset(
    {"main", "article", "section", "table", "ul", "ol", "dl", "form", "figure", "header"}
)

# Class/id substrings (normalized) that signal noise
_NOISE_PATTERNS = (
    "cookie-banner",
    "cookie-consent",
    "cookieconsent",
    "gdpr-banner",
    "ad-container",
    "advertisement",
    "sidebar",
    "social-share",
    "social-media",
    "newsletter-signup",
    "popup",
    "overlay",
    "modal",
    "sticky-header",
    "sticky-nav",
    "breadcrumb",
)


def _normalize(value: str) -> str:
    """Lowercase + strip hyphens/underscores so 'cookie-banner', 'cookie_banner',
    and 'cookieBanner' all collapse to 'cookiebanner'."""
    return re.sub(r"[-_]", "", value.lower())


_NORMALIZED_NOISE_PATTERNS = tuple(_normalize(p) for p in _NOISE_PATTERNS)


def class_or_id_matches(element, patterns: tuple[str, ...]) -> bool:
    """Return True if any of the element's class names or id contains any
    pattern, after normalizing across hyphens/underscores/camelCase."""
    classes = element.get("class") or []
    element_id = element.get("id") or ""

    candidates = list(classes) + [element_id]
    for candidate in candidates:
        if not candidate:
            continue
        normalized = _normalize(candidate)
        for pattern in patterns:
            if pattern in normalized:
                return True
    return False


def _is_hidden(element) -> bool:
    if element.has_attr("hidden"):
        return True
    if element.get("aria-hidden") == "true":
        return True
    style = element.get("style") or ""
    if style:
        compact = re.sub(r"\s+", "", style.lower())
        if "display:none" in compact or "visibility:hidden" in compact:
            return True
    return False


def filter_noise(html: str) -> tuple[str, dict]:
    """Strip noise from HTML and return (cleaned_html, stats).

    stats keys:
      - original_size: int
      - cleaned_size: int
      - reduction_pct: float (0–100)
      - removed_tags: dict[str, int] (tag name → count)
      - removed_classes: int (count of class/id pattern matches removed)
    """
    original_size = len(html)
    removed_tags: Counter = Counter()
    removed_classes = 0

    if not html.strip():
        return "", {
            "original_size": original_size,
            "cleaned_size": 0,
            "reduction_pct": 0.0,
            "removed_tags": {},
            "removed_classes": 0,
        }

    soup = BeautifulSoup(html, "lxml")

    # Hard removals — always strip
    for tag_name in _REMOVE_TAGS_HARD:
        for tag in soup.find_all(tag_name):
            removed_tags[tag_name] += 1
            tag.decompose()

    # SVG: remove only if no text content
    for tag in soup.find_all("svg"):
        if not tag.get_text(strip=True):
            removed_tags["svg"] += 1
            tag.decompose()

    # Semantic non-content
    for tag_name in _REMOVE_TAGS_SEMANTIC:
        for tag in soup.find_all(tag_name):
            removed_tags[tag_name] += 1
            tag.decompose()

    # Class/id pattern removal — skip preserved tags
    for tag in list(soup.find_all(True)):
        if not tag.parent:
            continue  # already detached
        if tag.name in _PRESERVE_TAGS:
            continue
        if class_or_id_matches(tag, _NORMALIZED_NOISE_PATTERNS):
            removed_classes += 1
            tag.decompose()

    # Hidden elements — skip preserved tags
    for tag in list(soup.find_all(True)):
        if not tag.parent:
            continue
        if tag.name in _PRESERVE_TAGS:
            continue
        if _is_hidden(tag):
            removed_tags["__hidden__"] += 1
            tag.decompose()

    cleaned = str(soup)
    cleaned_size = len(cleaned)
    reduction_pct = (
        ((original_size - cleaned_size) / original_size) * 100 if original_size else 0.0
    )

    return cleaned, {
        "original_size": original_size,
        "cleaned_size": cleaned_size,
        "reduction_pct": reduction_pct,
        "removed_tags": dict(removed_tags),
        "removed_classes": removed_classes,
    }

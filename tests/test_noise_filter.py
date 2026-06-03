"""Tests for the HTML noise filter."""

from bs4 import BeautifulSoup

from pluck.extraction.noise_filter import (
    class_or_id_matches,
    filter_noise,
)

# The matcher works with normalized patterns — pre-normalize for the helper tests
from pluck.extraction.noise_filter import _NORMALIZED_NOISE_PATTERNS, _normalize


def _has_tag(html: str, tag: str) -> bool:
    return BeautifulSoup(html, "lxml").find(tag) is not None


def _has_text(html: str, text: str) -> bool:
    return text in html


# ── Tag-based removal ────────────────────────────────────────────────────────


def test_removes_script_tags():
    html = "<html><body><p>Keep</p><script>alert(1);</script></body></html>"
    cleaned, stats = filter_noise(html)
    assert not _has_tag(cleaned, "script")
    assert stats["removed_tags"].get("script") == 1


def test_removes_style_tags():
    html = "<html><head><style>.x{color:red}</style></head><body><p>Keep</p></body></html>"
    cleaned, stats = filter_noise(html)
    assert not _has_tag(cleaned, "style")
    assert stats["removed_tags"].get("style") == 1


def test_removes_noscript_tags():
    html = "<html><body><noscript>Enable JS</noscript><p>Keep</p></body></html>"
    cleaned, stats = filter_noise(html)
    assert not _has_tag(cleaned, "noscript")
    assert stats["removed_tags"].get("noscript") == 1


def test_removes_iframe_tags():
    html = '<html><body><iframe src="x"></iframe><p>Keep</p></body></html>'
    cleaned, stats = filter_noise(html)
    assert not _has_tag(cleaned, "iframe")
    assert stats["removed_tags"].get("iframe") == 1


def test_removes_nav_footer_aside():
    html = """<html><body>
      <nav>Menu</nav>
      <main><p>Real content</p></main>
      <aside>Sidebar</aside>
      <footer>Foot</footer>
    </body></html>"""
    cleaned, stats = filter_noise(html)
    assert not _has_tag(cleaned, "nav")
    assert not _has_tag(cleaned, "footer")
    assert not _has_tag(cleaned, "aside")
    assert _has_text(cleaned, "Real content")
    assert stats["removed_tags"].get("nav") == 1
    assert stats["removed_tags"].get("footer") == 1
    assert stats["removed_tags"].get("aside") == 1


# ── Class/id pattern removal ─────────────────────────────────────────────────


def test_removes_cookie_banner_class():
    html = '<html><body><div class="cookie-banner">Cookie</div><p>Keep</p></body></html>'
    cleaned, stats = filter_noise(html)
    assert not _has_text(cleaned, "Cookie")
    assert _has_text(cleaned, "Keep")
    assert stats["removed_classes"] >= 1


def test_removes_ad_container_class():
    html = '<html><body><div class="ad-container">Ad</div><p>Keep</p></body></html>'
    cleaned, stats = filter_noise(html)
    assert not _has_text(cleaned, "Ad")
    assert stats["removed_classes"] >= 1


def test_flexible_class_matching_camel_case():
    html = '<html><body><div class="cookieBanner">Cookie</div><p>Keep</p></body></html>'
    cleaned, _ = filter_noise(html)
    assert not _has_text(cleaned, "Cookie")


def test_flexible_class_matching_underscore():
    html = '<html><body><div class="cookie_banner">Cookie</div><p>Keep</p></body></html>'
    cleaned, _ = filter_noise(html)
    assert not _has_text(cleaned, "Cookie")


def test_flexible_class_matching_hyphen():
    html = '<html><body><div class="cookie-banner">Cookie</div><p>Keep</p></body></html>'
    cleaned, _ = filter_noise(html)
    assert not _has_text(cleaned, "Cookie")


def test_id_pattern_matching():
    html = '<html><body><div id="cookie-banner">Cookie</div><p>Keep</p></body></html>'
    cleaned, stats = filter_noise(html)
    assert not _has_text(cleaned, "Cookie")
    assert stats["removed_classes"] >= 1


def test_class_or_id_matches_helper():
    soup = BeautifulSoup(
        '<div class="newsletter-signup">x</div><div id="popup">y</div><div class="other">z</div>',
        "lxml",
    )
    el1, el2, el3 = soup.find_all("div")
    assert class_or_id_matches(el1, _NORMALIZED_NOISE_PATTERNS)
    assert class_or_id_matches(el2, _NORMALIZED_NOISE_PATTERNS)
    assert not class_or_id_matches(el3, _NORMALIZED_NOISE_PATTERNS)


def test_normalize_collapses_separators():
    assert _normalize("cookie-banner") == "cookiebanner"
    assert _normalize("cookieBanner") == "cookiebanner"
    assert _normalize("cookie_banner") == "cookiebanner"
    assert _normalize("COOKIE-BANNER") == "cookiebanner"


# ── Hidden element removal ───────────────────────────────────────────────────


def test_removes_display_none_elements():
    html = '<html><body><div style="display:none">Hidden</div><p>Keep</p></body></html>'
    cleaned, _ = filter_noise(html)
    assert not _has_text(cleaned, "Hidden")
    assert _has_text(cleaned, "Keep")


def test_removes_display_none_with_spaces():
    html = '<html><body><div style="display: none; color: red;">Hidden</div><p>Keep</p></body></html>'
    cleaned, _ = filter_noise(html)
    assert not _has_text(cleaned, "Hidden")


def test_removes_visibility_hidden_elements():
    html = '<html><body><div style="visibility:hidden">Hidden</div><p>Keep</p></body></html>'
    cleaned, _ = filter_noise(html)
    assert not _has_text(cleaned, "Hidden")


def test_removes_aria_hidden_elements():
    html = '<html><body><div aria-hidden="true">Hidden</div><p>Keep</p></body></html>'
    cleaned, _ = filter_noise(html)
    assert not _has_text(cleaned, "Hidden")


def test_removes_hidden_attribute_elements():
    html = "<html><body><div hidden>Hidden</div><p>Keep</p></body></html>"
    cleaned, _ = filter_noise(html)
    assert not _has_text(cleaned, "Hidden")


# ── Preservation ─────────────────────────────────────────────────────────────


def test_preserves_main_article_section():
    html = """<html><body>
      <main><article><section>
        <h1>Title</h1>
        <p>Body content here.</p>
      </section></article></main>
    </body></html>"""
    cleaned, _ = filter_noise(html)
    assert _has_tag(cleaned, "main")
    assert _has_tag(cleaned, "article")
    assert _has_tag(cleaned, "section")
    assert _has_text(cleaned, "Body content here.")


def test_preserves_table_lists_form_figure_header():
    html = """<html><body>
      <header><h1>Title</h1></header>
      <table><tr><td>cell</td></tr></table>
      <ul><li>item</li></ul>
      <ol><li>item</li></ol>
      <dl><dt>k</dt><dd>v</dd></dl>
      <form><input/></form>
      <figure>fig</figure>
    </body></html>"""
    cleaned, _ = filter_noise(html)
    for tag in ["header", "table", "ul", "ol", "dl", "form", "figure"]:
        assert _has_tag(cleaned, tag), f"missing {tag}"


def test_preserved_tag_with_noise_class_is_kept():
    """A `main` element that happens to have a class matching a noise pattern
    should still be preserved (preservation wins over class matching)."""
    html = (
        '<html><body><main class="modal">'
        "<p>Important content</p></main></body></html>"
    )
    cleaned, _ = filter_noise(html)
    assert _has_tag(cleaned, "main")
    assert _has_text(cleaned, "Important content")


def test_preserves_svg_with_text_content():
    html = (
        "<html><body><svg><text>Chart label</text></svg>"
        "<p>Body</p></body></html>"
    )
    cleaned, stats = filter_noise(html)
    assert _has_tag(cleaned, "svg")
    assert "svg" not in stats["removed_tags"]


def test_removes_empty_svg():
    html = '<html><body><svg><circle r="5"/></svg><p>Body</p></body></html>'
    cleaned, stats = filter_noise(html)
    assert not _has_tag(cleaned, "svg")
    assert stats["removed_tags"].get("svg") == 1


# ── Stats and edge cases ─────────────────────────────────────────────────────


def test_stats_dict_populated_correctly():
    html = """<html><body>
      <script>x</script>
      <script>y</script>
      <nav>nav</nav>
      <div class="ad-container">ad</div>
      <p>Keep</p>
    </body></html>"""
    cleaned, stats = filter_noise(html)
    assert stats["original_size"] == len(html)
    assert stats["cleaned_size"] == len(cleaned)
    assert 0 < stats["reduction_pct"] < 100
    assert stats["removed_tags"]["script"] == 2
    assert stats["removed_tags"]["nav"] == 1
    assert stats["removed_classes"] >= 1


def test_handles_malformed_html():
    html = "<html><body><div><p>unclosed<span>nested<script>x"
    cleaned, stats = filter_noise(html)
    # lxml fixes up malformed input; main thing is no exception and script is gone
    assert "script" not in cleaned.lower() or "<script" not in cleaned.lower()
    assert stats["original_size"] == len(html)


def test_handles_empty_html():
    cleaned, stats = filter_noise("")
    assert cleaned == ""
    assert stats["original_size"] == 0
    assert stats["cleaned_size"] == 0
    assert stats["reduction_pct"] == 0.0


def test_handles_whitespace_only_html():
    cleaned, stats = filter_noise("   \n\t  ")
    assert cleaned == ""
    assert stats["cleaned_size"] == 0


def test_html_with_only_noise_returns_minimal_output():
    html = """<html><body>
      <script>x</script>
      <nav>Nav</nav>
      <footer>Foot</footer>
      <div class="ad-container">Ad</div>
    </body></html>"""
    cleaned, stats = filter_noise(html)
    # Body should be effectively empty of noise
    for noise_text in ("Nav", "Foot", "Ad", "x"):
        assert noise_text not in cleaned
    assert stats["cleaned_size"] < stats["original_size"]


def test_reduction_pct_calculation():
    html = "<html><body>" + "<script>x</script>" * 100 + "<p>Keep</p></body></html>"
    cleaned, stats = filter_noise(html)
    expected_pct = ((stats["original_size"] - stats["cleaned_size"]) / stats["original_size"]) * 100
    assert abs(stats["reduction_pct"] - expected_pct) < 0.001
    assert stats["reduction_pct"] > 50  # script soup should reduce significantly


def test_full_noisy_fixture_keeps_real_content(noisy_html_fixture):
    cleaned, stats = filter_noise(noisy_html_fixture)
    assert "Real article headline" in cleaned
    assert "Real article body text" in cleaned
    # Noise gone
    assert "Cookie" not in cleaned
    assert "Hidden tracker" not in cleaned
    assert "Aria-hidden block" not in cleaned
    assert "Sign up!" not in cleaned
    assert "© 2026" not in cleaned
    assert stats["reduction_pct"] > 20

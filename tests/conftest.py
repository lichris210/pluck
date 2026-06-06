from unittest.mock import MagicMock

import pytest


# USE_PLANNER now defaults to true (loaded from .env), which makes /api/extract take
# the planner path and, for unknown hosts, the Phase 3 discovery fall-through — which
# hits the live Apify Store + Haiku. Unit tests that exercise the legacy
# classify→fetch→extract path don't mock that, so pin the flag off by default. Tests
# that need the planner/discovery path opt in by setting USE_PLANNER=true themselves
# (via patch.dict / monkeypatch in the test body or their own fixture), which runs
# after this autouse fixture and therefore wins.
@pytest.fixture(autouse=True)
def _planner_off_by_default(monkeypatch):
    monkeypatch.setenv("USE_PLANNER", "false")


def _make_response(text: str, input_tokens: int = 100, output_tokens: int = 50):
    """Build a fake `messages.create` response with one text content block."""
    block = MagicMock()
    block.type = "text"
    block.text = text

    response = MagicMock()
    response.content = [block]
    response.usage = MagicMock()
    response.usage.input_tokens = input_tokens
    response.usage.output_tokens = output_tokens
    return response


@pytest.fixture
def mock_anthropic_client():
    """A MagicMock anthropic client with a configurable `.messages.create` response.

    Default response returns an empty JSON array. Tests can override by setting
    `client.messages.create.return_value = _make_response(...)` or supplying
    a `side_effect` (e.g. an iterable of responses, or an Exception).
    """
    client = MagicMock()
    client.messages.create.return_value = _make_response("[]", 100, 10)
    # Expose the helper for tests that want to build custom responses
    client._make_response = _make_response
    return client


@pytest.fixture
def realistic_product_listing_html():
    return """<!DOCTYPE html><html><head><title>Best Headphones 2026</title></head>
<body>
  <header><h1>Top Headphones</h1></header>
  <main>
    <article class="product-card">
      <h2>Sony WH-1000XM5</h2>
      <p class="price">$398.00</p>
      <p class="rating">4.7 / 5</p>
      <p class="desc">Industry-leading noise cancellation with crystal-clear hands-free calling.</p>
    </article>
    <article class="product-card">
      <h2>Bose QuietComfort Ultra</h2>
      <p class="price">$429.00</p>
      <p class="rating">4.6 / 5</p>
      <p class="desc">Immersive audio with world-class noise cancellation.</p>
    </article>
    <article class="product-card">
      <h2>Apple AirPods Max</h2>
      <p class="price">$549.00</p>
      <p class="rating">4.5 / 5</p>
      <p class="desc">High-fidelity audio in a stunning over-ear design.</p>
    </article>
    <article class="product-card">
      <h2>Sennheiser Momentum 4</h2>
      <p class="price">$349.95</p>
      <p class="rating">4.4 / 5</p>
      <p class="desc">Exceptional sound, adaptive noise cancellation, 60-hour battery.</p>
    </article>
    <article class="product-card">
      <h2>Beats Studio Pro</h2>
      <p class="price">$349.99</p>
      <p class="rating">4.3 / 5</p>
      <p class="desc">Custom-built acoustic platform with personalized spatial audio.</p>
    </article>
  </main>
</body></html>"""


@pytest.fixture
def realistic_article_html():
    return """<!DOCTYPE html><html><head><title>Understanding Web Scraping</title></head>
<body>
  <header><h1>Understanding Web Scraping</h1></header>
  <main>
    <article>
      <h1>Understanding Web Scraping</h1>
      <p class="byline">By Alice Chen — January 15, 2026</p>
      <section>
        <h2>Introduction</h2>
        <p>Web scraping is the automated extraction of data from websites. Modern
        scrapers handle JavaScript rendering, anti-bot measures, and pagination.</p>
      </section>
      <section>
        <h2>Static vs Dynamic Pages</h2>
        <p>Static pages return complete HTML on first request. Dynamic pages render
        content after JavaScript execution and require a headless browser.</p>
      </section>
      <section>
        <h2>Anti-Bot Measures</h2>
        <p>Modern sites deploy fingerprinting, rate limiting, and CAPTCHAs. Stealth
        browsers spoof signals to bypass detection.</p>
      </section>
      <section>
        <h2>Conclusion</h2>
        <p>Choose the simplest tool that works. Escalate to browsers only when needed.</p>
      </section>
    </article>
  </main>
</body></html>"""


@pytest.fixture
def noisy_html_fixture():
    return """<!DOCTYPE html><html><head>
  <title>News Article</title>
  <style>.foo { color: red; }</style>
  <script src="/tracker.js"></script>
</head>
<body>
  <nav class="site-nav">
    <a href="/">Home</a><a href="/about">About</a>
  </nav>
  <div id="cookie-banner" class="cookie-banner">
    <p>We use cookies. Accept?</p>
    <button>Accept all</button>
  </div>
  <div class="ad-container">
    <iframe src="https://ads.example.com/banner"></iframe>
  </div>
  <aside class="sidebar">
    <h3>Related</h3>
    <ul><li>Other story</li></ul>
  </aside>
  <main>
    <article>
      <h1>Real article headline</h1>
      <p>Real article body text that should survive noise filtering.</p>
    </article>
  </main>
  <div class="newsletter-signup">
    <h3>Sign up!</h3><input type="email" />
  </div>
  <div style="display: none">Hidden tracker</div>
  <div aria-hidden="true">Aria-hidden block</div>
  <footer>© 2026 News Site</footer>
  <script>analytics.track();</script>
</body></html>"""


@pytest.fixture
def linkedin_html():
    return """<!DOCTYPE html><html><head><title>LinkedIn</title></head>
<body>
  <div class="main-content">Sign in to LinkedIn</div>
  <p>Connect with professionals around the world.</p>
  <p>Join now to see what your connections are up to.</p>
</body></html>"""


@pytest.fixture
def cloudflare_challenge_html():
    return """<!DOCTYPE html><html><head><title>Just a moment...</title></head>
<body>
  <div id="cf-challenge-running">
    <div class="cf-challenge" data-type="managed">
      Checking your browser before accessing the site.
    </div>
    <script>window.__cf_chl_jschl_tk__='abc123';</script>
  </div>
</body></html>"""


@pytest.fixture
def login_form_html():
    return """<!DOCTYPE html><html><head><title>Login</title></head>
<body>
  <form method="post" action="/login">
    <label>Email <input type="email" name="email" /></label>
    <label>Password <input type="password" name="password" /></label>
    <button type="submit">Sign in</button>
  </form>
</body></html>"""


@pytest.fixture
def meta_login_redirect_html():
    return """<!DOCTYPE html><html>
<head>
  <meta http-equiv="refresh" content="0; url=/login?next=/dashboard" />
  <title>Redirecting...</title>
</head>
<body>Redirecting to login...</body>
</html>"""


@pytest.fixture
def cookie_banner_html():
    return """<!DOCTYPE html><html><head><title>News Site</title></head>
<body>
  <div id="cookie-banner" class="cookie-banner">
    <p>We use cookies to improve your experience.</p>
    <button>Accept all</button>
    <button>Reject</button>
  </div>
  <main>
    <article><h1>Breaking News</h1><p>Story content here with lots of text...</p></article>
  </main>
</body></html>"""


@pytest.fixture
def age_verification_html():
    return """<!DOCTYPE html><html><head><title>Adult Site</title></head>
<body>
  <div id="age-gate" class="age-verification">
    <h2>Are you 18 or older?</h2>
    <button>Yes, enter</button>
    <button>No, leave</button>
  </div>
</body></html>"""


@pytest.fixture
def captcha_html():
    return """<!DOCTYPE html><html><head><title>Verify</title></head>
<body>
  <form>
    <div class="g-recaptcha" data-sitekey="6LcXXXXXX"></div>
    <button type="submit">Submit</button>
  </form>
</body></html>"""


@pytest.fixture
def react_spa_clean_html():
    return """<!DOCTYPE html><html><head>
  <title>JobBoard App</title>
  <script type="application/ld+json">{"@context":"https://schema.org","@type":"JobPosting"}</script>
</head>
<body>
  <div id="root"></div>
  <script src="/static/js/main.abc123.js"></script>
</body></html>"""


@pytest.fixture
def react_spa_messy_html():
    return """<!DOCTYPE html><html><head>
  <title>Dashboard</title>
</head>
<body>
  <div id="root"></div>
  <script src="/bundle.js"></script>
</body></html>"""


@pytest.fixture
def next_js_html():
    return """<!DOCTYPE html><html><head><title>Next.js App</title></head>
<body>
  <div id="__next"></div>
  <script id="__NEXT_DATA__" type="application/json">{"props":{},"page":"/"}</script>
</body></html>"""


@pytest.fixture
def paginated_blog_html():
    return """<!DOCTYPE html><html><head>
  <title>Blog</title>
  <link rel="next" href="/blog?page=2" />
</head>
<body>
  <main>
    <article>
      <h2>Post 1: Introduction to Web Scraping</h2>
      <p>Web scraping is the automated extraction of data from websites. It involves sending HTTP
      requests, parsing HTML responses, and extracting structured data from the document tree.
      Modern scrapers handle JavaScript rendering, anti-bot measures, and pagination automatically.</p>
    </article>
    <article>
      <h2>Post 2: Handling Pagination</h2>
      <p>Paginated sites split their content across multiple pages. Common patterns include query
      parameters like ?page=2, link elements with rel=next, and navigation components with class
      names containing "pagination". A robust scraper must detect and follow these patterns to
      retrieve all available data from a multi-page listing.</p>
    </article>
    <article>
      <h2>Post 3: Choosing the Right Tool</h2>
      <p>Choosing between plain HTTP requests and a headless browser depends on the site. Static
      HTML sites respond well to simple GET requests. JavaScript-heavy single-page applications
      require a real browser engine to render content before it can be extracted. Always start
      with the simplest approach and escalate only when needed.</p>
    </article>
    <nav class="pagination"><a href="?page=2">Next</a></nav>
  </main>
</body></html>"""


@pytest.fixture
def static_article_html():
    return """<!DOCTYPE html><html><head><title>Wikipedia Article</title></head>
<body>
  <article>
    <h1>Python (programming language)</h1>
    <p>Python is a high-level, general-purpose programming language. Its design philosophy emphasizes
    code readability with the use of significant indentation. Python is dynamically typed and
    garbage-collected. It supports multiple programming paradigms, including structured, object-oriented
    and functional programming. It is often described as a "batteries included" language due to its
    comprehensive standard library. Guido van Rossum began working on Python in the late 1980s as a
    successor to the ABC programming language and first released it in 1991.</p>
  </article>
</body></html>"""

# Pluck.ai — Phased build plan

Five phases. Each one leaves the project at a working, testable state with a clear input and output. Run each prompt in Claude Code with the recommended model. After each phase, run the test command and verify the smoke test before moving on.

## Before you start

Open Claude Code in your project folder:

```
cd %USERPROFILE%\pluck
.venv\Scripts\activate.bat
claude
```

The `README.md` already lives in the project root. Claude Code will read it automatically when you start a session — that's the project context for every phase.

You also need pytest:

```
pip install pytest pytest-asyncio
```

---

## Phase 1 — Models, config, URL ingester, classifier

**Input:** A URL string passed via CLI.
**Output:** Console prints a `SiteProfile` showing classification, headers, status code, and HTML preview.

### Model: Sonnet 4.6

`claude-sonnet-4-6`

The work here is dataclasses, an HTTP call, and heuristic classification. Well-defined logic with no architectural judgment required. Sonnet handles this without difficulty.

### Prompt

```
Read README.md for project context.

Build Phase 1 of Pluck.ai. This phase ingests a URL, makes an initial HTTP request, classifies the site into one of seven groups, and prints the result.

Create these files:

1. pluck/__init__.py — empty
2. pluck/models.py — Define these dataclasses:
   - SiteGroup (Enum): STATIC_HTML=1, SERVER_RENDERED_PAGINATED=2, JS_RENDERED_CLEAN_API=3, JS_RENDERED_MESSY_DOM=4, INTERACTIVE_GATED=5, AUTH_GATED=6, FORTRESS=7
   - SiteProfile: url (str), final_url (str), status_code (int), headers (dict), content_type (str), html (str), site_group (SiteGroup), classification_reasons (list[str]), response_time_ms (float), error (str | None) = None

3. pluck/config.py — Load configuration:
   - Use python-dotenv to load .env file
   - ANTHROPIC_API_KEY (required for later phases, optional now — log a warning if missing)
   - APIFY_TOKEN (optional)
   - Provide a Config dataclass with these as attributes
   - Function get_config() returns the Config

4. pluck/classifiers/__init__.py — empty
5. pluck/classifiers/site_classifier.py — The classifier:
   - classify(url: str, status_code: int, headers: dict, html: str) -> tuple[SiteGroup, list[str]]
   - Returns (group, list of reasons explaining the classification)
   - Apply these heuristics in order:
     a. FORTRESS: domain matches linkedin.com, facebook.com, instagram.com, twitter.com, x.com, tiktok.com (handle www. and subdomains), OR Cloudflare challenge page detected (cf-challenge, __cf_chl_jschl), OR PerimeterX/HUMAN markers
     b. AUTH_GATED: status_code in (401, 403) AND not a fortress site, OR HTML contains login form (input[type=password]) at the body level, OR meta refresh redirects to /login or /signin
     c. INTERACTIVE_GATED: HTML contains cookie consent overlay (class/id matching cookie-banner, cookie-consent, gdpr), age verification, CAPTCHA markers (g-recaptcha, hcaptcha), subscription paywall overlay
     d. JS_RENDERED_CLEAN_API: minimal body content (less than 500 chars of visible text in body) AND has SPA markers (#root, #app, __NEXT_DATA__, #__nuxt) AND has structured data (application/ld+json script tags OR meta itemtype attributes)
     e. JS_RENDERED_MESSY_DOM: minimal body content AND has SPA markers but NO structured data
     f. SERVER_RENDERED_PAGINATED: substantial body content AND has pagination signals (link[rel=next], link[rel=prev], pagination class/role, ?page= in href attributes)
     g. STATIC_HTML: default fallback
   - Use BeautifulSoup with lxml for parsing
   - Return a list of human-readable reasons for each classification (e.g., "Domain matches fortress list: linkedin.com")

6. pluck/ingester.py — The URL ingester:
   - async def ingest(url: str, timeout: float = 30.0) -> SiteProfile
   - Use httpx.AsyncClient with follow_redirects=True, max_redirects=5
   - Set realistic User-Agent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
   - Normalize the URL: strip tracking params (utm_*, fbclid, gclid, mc_*), normalize trailing slashes
   - Capture response time
   - Handle errors gracefully: timeouts, connection errors, DNS failures, SSL errors, non-HTML content-types — return SiteProfile with error field set and site_group=STATIC_HTML as default
   - For non-HTML content (image, video, application/octet-stream), set error="Non-HTML content type: {content_type}" and skip classification
   - Otherwise call the classifier and populate site_group and classification_reasons

7. pluck/cli.py — Simple CLI:
   - Accept a URL as positional argument
   - Run ingest(url) async
   - Print formatted output:
     - Final URL (after redirects)
     - Status code
     - Response time
     - Site group with classification reasons
     - HTML preview (first 500 chars)
     - Error if any
   - Use argparse
   - Allow running with: python -m pluck.cli <url>

8. tests/__init__.py — empty
9. tests/conftest.py — Shared fixtures:
   - Provide sample HTML strings for each site group as fixtures
   - linkedin_html, cloudflare_challenge_html, login_form_html, cookie_banner_html, react_spa_clean_html, react_spa_messy_html, paginated_blog_html, static_article_html

10. tests/test_classifier.py — Test the classifier:
    - Test each SiteGroup classification with the corresponding fixture HTML
    - Test fortress detection with linkedin.com, www.linkedin.com, m.linkedin.com URLs
    - Test fortress detection with Cloudflare challenge page HTML regardless of domain
    - Test auth gate detection with 401, 403, login form, redirect to /login
    - Test interactive gate detection with cookie banner, age verification, CAPTCHA markers
    - Test JS-rendered classification (clean vs messy)
    - Test pagination detection with rel=next, ?page= URLs
    - Test static HTML fallback for normal pages
    - Test classification reasons are populated and human-readable
    - At least 25 test cases covering edge cases (empty HTML, malformed HTML, missing headers)

11. tests/test_ingester.py — Test the ingester (use httpx mocking via respx or unittest.mock):
    - Test successful fetch returns populated SiteProfile
    - Test URL normalization strips utm_*, fbclid, gclid params
    - Test redirect following sets final_url correctly
    - Test timeout returns SiteProfile with error set
    - Test connection error returns SiteProfile with error set
    - Test 404 returns SiteProfile with status_code=404 (not error — page exists, just missing)
    - Test 500 returns SiteProfile with status_code=500
    - Test non-HTML content-type sets error and skips classification
    - Test User-Agent header is sent on requests
    - At least 12 test cases

Add these to requirements (or just install): httpx, beautifulsoup4, lxml, python-dotenv, pytest, pytest-asyncio, respx
```

### Verify

```
pip install httpx beautifulsoup4 lxml python-dotenv pytest pytest-asyncio respx
pytest tests/ -v
python -m pluck.cli https://pypi.org/project/scrapling/
python -m pluck.cli https://www.linkedin.com/in/someone/
python -m pluck.cli https://news.ycombinator.com
```

The first URL should classify as STATIC_HTML or SERVER_RENDERED_PAGINATED. The second should classify as FORTRESS. The third as STATIC_HTML.

---

## Phase 2 — Scrapling fetcher layer

**Input:** A `SiteProfile` from Phase 1.
**Output:** A `FetchResult` containing fully-rendered HTML (or intercepted JSON for Group 3 with XHR success), with the fetcher tier chosen by site group.

### Model: Sonnet 4.6

`claude-sonnet-4-6`

Library wrapping with conditional dispatch. The interesting parts are the timeout-in-milliseconds gotcha and the XHR capture path. Well within Sonnet's range.

### Prompt

```
Read README.md for project context. Phase 1 is built (models, config, classifier, ingester).

Build Phase 2 of Pluck.ai: the Scrapling fetcher layer.

Create these files:

1. Update pluck/models.py — Add to existing models:
   - FetchResult: url (str), html (str), structured_data (list[dict] | None) — populated when XHR or Apify path returns structured data, fetcher_used (str), fetch_time_ms (float), success (bool), error (str | None), metadata (dict) — flexible storage for things like detected framework, page title, intercepted XHR URL count, captured_xhr_url
   - Add property: skip_extraction (bool) — returns True if structured_data is populated (signals downstream to skip Claude)

2. pluck/fetchers/__init__.py — empty
3. pluck/fetchers/scrapling_wrapper.py — Thin wrappers around Scrapling fetchers:
   - All wrappers return FetchResult
   - fetch_static(url: str, timeout_seconds: float = 15) -> FetchResult — wraps Fetcher.get(), pass timeout in seconds (Fetcher uses seconds, not ms)
   - async fetch_static_async(url: str, timeout_seconds: float = 15) -> FetchResult — wraps AsyncFetcher.get()
   - fetch_dynamic(url: str, timeout_seconds: float = 30, capture_xhr_pattern: str | None = None) -> FetchResult — wraps DynamicFetcher.fetch(). CRITICAL: timeout in browser fetchers is in MILLISECONDS, not seconds. Convert: pass timeout=int(timeout_seconds * 1000) to Scrapling. Set network_idle=True, headless=True. If capture_xhr_pattern is provided, pass capture_xhr=pattern.
   - fetch_stealth(url: str, timeout_seconds: float = 30, page_action: callable | None = None) -> FetchResult — wraps StealthyFetcher.fetch(). Same timeout-in-milliseconds gotcha. Set headless=True, network_idle=True. If page_action provided, pass it.
   - Each wrapper handles Scrapling-specific exceptions (TimeoutError, anything from playwright) and returns FetchResult with success=False and meaningful error message
   - For dynamic fetcher: if capture_xhr_pattern was provided AND response.captured_xhr is non-empty, parse the XHR responses as JSON and populate FetchResult.structured_data instead of (or in addition to) html
   - Set metadata fields: page_title (extract from HTML <title>), html_length, captured_xhr_count, captured_xhr_urls

4. pluck/fetchers/router.py — Routes SiteProfile to the right fetcher:
   - async def fetch(profile: SiteProfile) -> FetchResult
   - Route by profile.site_group:
     - STATIC_HTML → fetch_static_async (no browser needed)
     - SERVER_RENDERED_PAGINATED → fetch_static_async (paginated handling deferred)
     - JS_RENDERED_CLEAN_API → fetch_dynamic with capture_xhr_pattern derived from URL pattern. For now, use a generic pattern of "/api/" — this catches most internal API calls. If the FetchResult ends up with structured_data populated, return it. Otherwise return the HTML.
     - JS_RENDERED_MESSY_DOM → fetch_dynamic without capture_xhr (need full DOM)
     - INTERACTIVE_GATED → fetch_stealth with a default page_action that dismisses common consent buttons (clicks button with text matching "Accept", "Agree", "Got it", "OK", "I accept")
     - AUTH_GATED → return FetchResult with success=False, error="Auth-gated sites require Apify integration (Phase 4). Set APIFY_TOKEN to enable."
     - FORTRESS → return FetchResult with success=False, error="Fortress sites require Apify actors (Phase 4). Set APIFY_TOKEN to enable."
   - Add fallback logic: if STATIC_HTML fails (timeout or empty HTML), retry with fetch_dynamic
   - Wrap all calls with try/except and timing measurement

5. pluck/fetchers/page_actions.py — Reusable page_action callbacks for StealthyFetcher:
   - async def dismiss_cookie_banners(page) — Tries to find and click common consent buttons. Use page.locator() to find buttons with text matching consent words. Wait 500ms after click. Don't fail if no banner found.
   - async def scroll_to_bottom(page) — Scroll the page to trigger lazy loading
   - async def wait_for_idle(page, timeout_ms: int = 3000) — Wait for network idle

6. Update pluck/cli.py — Extend the CLI:
   - After ingestion, if site_group is not AUTH_GATED or FORTRESS, run the fetcher router
   - Print: fetcher used, fetch time, HTML length (or structured_data length if XHR captured), success/error
   - Show a comparison: ingestion HTML length vs final fetched HTML length (demonstrates JS rendering benefit)
   - Add --skip-fetch flag to stop after classification (useful for debugging)

7. tests/test_scrapling_wrapper.py — Tests:
   - Mock Scrapling Fetcher, AsyncFetcher, DynamicFetcher, StealthyFetcher at the API level (don't make real network calls in unit tests)
   - Test fetch_static returns FetchResult with html populated and success=True on mock success
   - Test fetch_static returns FetchResult with success=False and error on mock exception
   - Test fetch_dynamic converts timeout_seconds=30 to timeout=30000 when calling Scrapling
   - Test fetch_stealth converts timeout_seconds=20 to timeout=20000 when calling Scrapling
   - Test fetch_dynamic with capture_xhr_pattern populates structured_data when XHR returns JSON
   - Test fetch_dynamic with capture_xhr_pattern leaves structured_data=None when no XHR matches
   - Test metadata fields are populated: page_title, html_length, captured_xhr_count
   - Test all wrappers handle Scrapling exceptions gracefully (no uncaught exceptions)
   - At least 15 tests

8. tests/test_router.py — Tests:
   - Mock the scrapling_wrapper functions
   - Test each SiteGroup routes to the correct wrapper
   - Test AUTH_GATED returns error FetchResult without calling any wrapper
   - Test FORTRESS returns error FetchResult without calling any wrapper
   - Test fallback: STATIC_HTML wrapper fails → fetch_dynamic is called as fallback
   - Test fallback does NOT trigger when FetchResult.success=True with empty HTML (different failure mode)
   - Test JS_RENDERED_CLEAN_API uses capture_xhr_pattern
   - Test INTERACTIVE_GATED passes page_action callback
   - Test timing is captured in fetch_time_ms
   - At least 12 tests

9. tests/test_page_actions.py — Tests:
   - Mock Playwright page object
   - Test dismiss_cookie_banners doesn't fail when no banner present
   - Test dismiss_cookie_banners clicks button when text matches
   - Test scroll_to_bottom calls page.evaluate
   - At least 5 tests

10. tests/integration/__init__.py and tests/integration/test_phase2_live.py — Live integration tests (marked @pytest.mark.integration):
    - Test Fetcher against pypi.org/project/scrapling/ — should return non-empty HTML
    - Test DynamicFetcher against pypi.org/search/?q=scrapling — should return more content than static fetcher
    - These won't run in normal test runs; only with: pytest -m integration

CRITICAL reminders from README:
- Browser fetcher timeouts are in MILLISECONDS (multiply seconds by 1000)
- Apify is Phase 4, not this phase — return errors for AUTH_GATED and FORTRESS
- Use the existing models.py and config.py from Phase 1, don't recreate them
```

### Verify

```
pytest tests/ -v --ignore=tests/integration
pytest tests/integration -v -m integration
python -m pluck.cli https://pypi.org/project/scrapling/
python -m pluck.cli https://pypi.org/search/?q=scrapling
python -m pluck.cli https://www.linkedin.com/in/someone/
```

The first URL should fetch via static and return ~159K HTML. The second should classify as JS-rendered, route to dynamic fetcher, and return ~50K+ HTML (search results actually populated). The third should classify as FORTRESS and return an error suggesting Apify.

---

## Phase 3 — Noise filter and Claude extraction

**Input:** A `FetchResult` with HTML content (Path 1 from README).
**Output:** An `ExtractionResult` containing structured data extracted by Claude.

### Model: Opus 4.6

`claude-opus-4-6`

This phase is the architecturally-demanding one. The prompt design needs to handle malformed JSON, missing fields, ambiguous content, and schema inference. The noise filter has many edge cases. The JSON repair logic needs careful handling of common LLM output mistakes. Opus produces more robust code for this kind of work, and a bug here silently degrades all downstream output.

### Prompt

```
Read README.md for project context. Phases 1-2 are built (classification + Scrapling fetching).

Build Phase 3 of Pluck.ai: noise filter, Claude extraction, and schema inference. This is Path 1 from the README — the HTML → Claude extraction path used for Groups 1, 2, 4, 5.

Create these files:

1. Update pluck/models.py — Add:
   - FieldDef: name (str), field_type (str — one of "string", "number", "boolean", "url", "date", "list"), description (str), required (bool, default True)
   - ExtractionSchema: fields (list[FieldDef]), description (str — what this data represents). Add classmethods: from_dict(d: dict) — parse from a dict like {"fields": [{"name": "title", ...}], "description": "..."}, to_dict() — serialize back
   - ExtractionResult: items (list[dict]), schema_used (ExtractionSchema), source_url (str), total_input_tokens (int), total_output_tokens (int), extraction_time_ms (float), model_used (str), error (str | None) = None

2. pluck/extraction/__init__.py — empty
3. pluck/extraction/noise_filter.py — HTML cleaning before Claude:
   - filter_noise(html: str) -> tuple[str, dict] — returns (cleaned_html, stats dict)
   - stats dict contains: original_size, cleaned_size, reduction_pct, removed_tags (count by tag name), removed_classes (count of class-matched removals)
   - Use BeautifulSoup with lxml
   - Remove by tag: script, style, noscript, iframe, svg (only if has no text content)
   - Remove by tag: nav, footer, aside
   - Remove by class/id pattern (case-insensitive, flexible matching across hyphens/underscores/camelCase): cookie-banner, cookie-consent, cookieconsent, gdpr-banner, ad-container, advertisement, sidebar, social-share, social-media, newsletter-signup, popup, overlay, modal, sticky-header, sticky-nav, breadcrumb
   - Remove hidden elements: style attribute contains display:none or visibility:hidden, aria-hidden=true, hidden attribute present
   - Preserve: main, article, section, table, ul, ol, dl, form, figure, header (page header is OK)
   - Use a helper function class_or_id_matches(element, patterns) that handles flexible matching
   - Return cleaned HTML as string (use str(soup), not soup.prettify() — preserve original formatting)

4. pluck/extraction/json_repair.py — Robust JSON parsing:
   - repair_and_parse(text: str) -> list[dict]
   - Handle these cases in order:
     a. Strip markdown code fences: ```json ... ``` or ``` ... ```
     b. Strip leading/trailing whitespace and prose (find the first [ or { and the last ] or })
     c. Try json.loads directly
     d. Fix trailing commas before ] and } using regex
     e. Fix unquoted keys (Python-style dicts) using regex
     f. Fix single quotes to double quotes (carefully — only for keys and string values)
     g. Try json.loads again
     h. If it parses to a single dict, wrap in a list
     i. If still failing, return empty list
   - Add specific tests for each repair case
   - Function should never raise — always returns list[dict], possibly empty

5. pluck/extraction/prompts.py — Prompt templates:
   - SCHEMA_INFERENCE_SYSTEM = "You analyze HTML pages and identify what structured data can be extracted from them..."
   - EXTRACTION_SYSTEM = "You extract structured data from HTML and return it as JSON..."
   - build_schema_inference_prompt(cleaned_html: str, source_url: str) -> str — Asks Claude to identify the data on the page and return a JSON schema definition. Include the URL for context. Limit HTML to first 30K chars (truncate if longer with "...[truncated]" marker).
   - build_extraction_prompt(cleaned_html: str, schema: ExtractionSchema, source_url: str) -> str — Asks Claude to extract items matching the schema. Include explicit instructions: return JSON array, use null for missing required fields rather than guessing, return [] if no matching items found, do not include any prose before or after the JSON.

6. pluck/extraction/schema_inference.py — Auto-detect what to extract:
   - async def infer_schema(cleaned_html: str, source_url: str, anthropic_client) -> ExtractionSchema
   - Send prompt to Claude (use claude-haiku-4-5-20251001 — schema inference is a simple classification task)
   - Parse response with repair_and_parse, expecting a single dict with "fields" and "description" keys
   - Build ExtractionSchema from the response
   - If Claude's response is malformed or doesn't match expected structure, return a minimal default schema with one "content" field of type "string"
   - Track tokens used (return tuple of schema, input_tokens, output_tokens)

7. pluck/extraction/extractor.py — The extraction engine:
   - async def extract(fetch_result: FetchResult, schema: ExtractionSchema, anthropic_client, model: str = "claude-haiku-4-5-20251001") -> ExtractionResult
   - First, run noise_filter on fetch_result.html
   - Build extraction prompt with cleaned HTML and schema
   - Call Claude API with the prompt
   - Parse response with repair_and_parse
   - Build ExtractionResult with items, schema_used, source_url=fetch_result.url, token counts, timing, model_used
   - Handle API errors gracefully — return ExtractionResult with error set and items=[]
   - If schema is None, call infer_schema first

8. Update pluck/cli.py — Add extraction step:
   - After fetch (if not skip_extraction), run extraction
   - Add --schema FILE flag — load schema from JSON file
   - If no schema provided, run schema inference and print the inferred schema, ask user to confirm (y/n) before extraction
   - Add --auto flag — skip the confirmation prompt
   - Print extraction results: number of items, fields, first 3 items as preview, token usage, cost estimate (Haiku: $1/MTok input, $5/MTok output)
   - Add --skip-extract flag to stop after fetch

9. tests/test_noise_filter.py — Comprehensive tests:
   - Test removes script, style, noscript tags
   - Test removes nav, footer, aside tags
   - Test removes elements with class containing "cookie-banner", "ad-container", etc.
   - Test flexible class matching: "cookieBanner", "cookie_banner", "cookie-banner" all match
   - Test removes display:none elements
   - Test removes aria-hidden="true" elements
   - Test removes hidden attribute elements
   - Test preserves main, article, section, table content
   - Test preserves SVG elements that contain text data
   - Test removes empty SVG elements
   - Test stats dict is populated correctly with counts
   - Test handles malformed HTML without raising
   - Test handles empty HTML returns empty cleaned HTML
   - Test handles HTML with only noise returns minimal cleaned HTML
   - Test reduction_pct calculation
   - At least 20 tests

10. tests/test_json_repair.py — Tests for every repair case:
    - Test clean JSON array parses unchanged
    - Test single object wrapped in list correctly
    - Test markdown fences stripped: ```json ... ```
    - Test markdown fences stripped: ``` ... ```
    - Test leading/trailing prose stripped
    - Test trailing comma in array fixed
    - Test trailing comma in object fixed
    - Test single-quoted strings converted to double-quoted
    - Test Python-style dict (unquoted keys) parsed
    - Test mixed valid JSON in surrounding garbage extracted
    - Test garbage input returns empty list (no exception)
    - Test empty string returns empty list
    - Test None input returns empty list
    - Test deeply nested valid JSON parsed
    - Test JSON with unicode characters parsed
    - At least 20 tests

11. tests/test_schema_inference.py — Tests:
    - Mock anthropic_client.messages.create
    - Test infer_schema parses valid Claude response into ExtractionSchema
    - Test infer_schema with malformed Claude response returns default schema
    - Test infer_schema with empty Claude response returns default schema
    - Test prompt sent to Claude includes the cleaned HTML (truncated if >30K)
    - Test prompt includes the source URL
    - Test token counts are returned correctly
    - Test API errors are handled (raise -> return default schema with error)
    - At least 8 tests

12. tests/test_extractor.py — Tests:
    - Mock anthropic_client
    - Test extract returns ExtractionResult with items populated on valid Claude response
    - Test extract calls noise_filter before sending to Claude
    - Test extract uses provided schema
    - Test extract calls infer_schema when schema is None
    - Test extract handles malformed JSON response (uses repair_and_parse)
    - Test extract handles API errors gracefully (returns ExtractionResult with error)
    - Test token counts are tracked from API response
    - Test extraction_time_ms is measured
    - Test model_used field reflects the model parameter
    - At least 12 tests

Add to conftest.py:
- mock_anthropic_client fixture — returns a MagicMock with configurable response
- realistic_product_listing_html fixture — HTML with 5 product cards
- realistic_article_html fixture — HTML with title, sections, paragraphs
- noisy_html_fixture — HTML wrapped in nav, footer, ads, cookie banners

Install: anthropic
```

### Verify

```
pip install anthropic
pytest tests/ -v --ignore=tests/integration
python -m pluck.cli https://pypi.org/project/scrapling/ --auto
python -m pluck.cli https://news.ycombinator.com --auto
```

The first should infer a schema (likely something like {name, version, description, dependencies}), then extract that data from the page. The second should infer a schema for HN stories ({title, points, author, comments_count, url}) and extract them.

Costs about $0.01-0.05 per page for the extraction step.

---

## Phase 4 — Apify integration

**Input:** A URL classified as AUTH_GATED or FORTRESS, OR an explicit `--use-apify` CLI flag.
**Output:** Either structured data directly from a specialized Apify actor (Path 3) or markdown text run through Claude extraction (Path 4).

### Model: Sonnet 4.6

`claude-sonnet-4-6`

SDK wrapping with domain-to-actor lookup logic. The gotchas (run ID vs dataset ID, permission errors) are documented in the README. Sonnet handles this kind of integration work.

### Prompt

```
Read README.md for project context. Phases 1-3 are built (classification, fetching, noise filter, Claude extraction).

Build Phase 4 of Pluck.ai: Apify integration for fortress and auth-gated sites. This implements Paths 3 and 4 from the README.

Create these files:

1. Update pluck/models.py — Add:
   - ApifyActorMapping: domain (str), path_pattern (str | None), actor_id (str), actor_type (str — "structured" or "markdown"), notes (str). The actor_type determines whether output goes through Claude extraction or not.

2. pluck/fetchers/apify_handler.py — The Apify integration:
   - class ApifyHandler:
     - __init__(self, token: str)
     - Initialize ApifyClient with token
     - Maintain ACTOR_MAP — a list of ApifyActorMapping objects covering:
       * linkedin.com/jobs/ → "hMvNSpz3JnHgl5jkh" (structured)
       * linkedin.com/in/ → "anchor/linkedin-profile-scraper" (structured)
       * linkedin.com/company/ → "anchor/linkedin-company-scraper" (structured)
       * instagram.com → "apify/instagram-scraper" (structured)
       * facebook.com → "apify/facebook-posts-scraper" (structured)
       * twitter.com / x.com → "apify/twitter-scraper" (structured)
       * tiktok.com → "clockworks/tiktok-scraper" (structured)
       * amazon.com → "junglee/amazon-crawler" (structured)
       * stockx.com → "misceres/stockx-scraper" (structured)
       * Default fallback: "apify/website-content-crawler" (markdown)
     - get_actor_for_url(self, url: str) -> ApifyActorMapping
       - Parse domain from URL (handle www., m. subdomains)
       - Check path-specific actors first
       - Fall back to domain default
       - Final fallback to website-content-crawler
     - async def fetch(self, url: str, max_items: int = 100, max_charge_usd: float = 1.0) -> FetchResult
       - Use get_actor_for_url to pick actor
       - Build run_input based on actor type:
         - For LinkedIn jobs actor: {"searchUrl": url, "maxItems": max_items}
         - For LinkedIn profile/company actors: appropriate URL list field
         - For website-content-crawler: {"startUrls": [{"url": url}], "maxCrawlPages": 1}
         - For Instagram/Twitter/etc.: parse username/query from URL and build appropriate input
         - Each actor needs its own input shape — implement input builders per actor or use a dict mapping
       - Call ApifyClientAsync.actor(actor_id).call(run_input=..., timeout_secs=300, max_items=max_items, max_total_charge_usd=Decimal(str(max_charge_usd)))
       - CRITICAL gotcha from README: result is a "run" object, not a dataset. Get dataset ID via run["defaultDatasetId"], then call client.dataset(dataset_id).list_items()
       - Convert ApifyApiError exceptions to FetchResult.error (especially "permission required" errors — return helpful message telling user to approve actor in console)
       - Build FetchResult:
         - For structured actors: structured_data=items list, html="" (or JSON serialize for debugging), fetcher_used="apify_structured", metadata includes actor_id, run_id, dataset_id
         - For markdown actor: html=item["markdown"] (or item["text"] as fallback), structured_data=None, fetcher_used="apify_markdown"
       - This naturally drives the right path: structured_data triggers skip_extraction (already in models from Phase 2), markdown goes through Claude extraction

3. Update pluck/fetchers/router.py:
   - Import ApifyHandler
   - In fetch(), check config for APIFY_TOKEN
   - If site_group is AUTH_GATED or FORTRESS:
     - If APIFY_TOKEN not set: keep existing error behavior with helpful message
     - If APIFY_TOKEN set: instantiate ApifyHandler and call its fetch method
   - Add optional parameter use_apify: bool = False to force Apify path even for non-fortress URLs

4. Update pluck/cli.py:
   - Add --use-apify flag — force Apify path regardless of classification
   - When result.skip_extraction is True (structured data from Apify), skip Phase 3 extraction and go directly to formatting
   - When Apify markdown path is taken, run normal Phase 3 extraction on the markdown (Claude handles markdown well)
   - Print Apify-specific info: actor used, dataset ID, run cost if available

5. tests/test_apify_handler.py — Tests:
   - Mock ApifyClient and ApifyClientAsync
   - Test get_actor_for_url:
     - linkedin.com/jobs/search/?keywords=python → LinkedIn jobs actor
     - linkedin.com/in/john-doe → LinkedIn profile actor
     - linkedin.com/company/anthropic → LinkedIn company actor
     - www.linkedin.com (no path) → default LinkedIn actor
     - m.linkedin.com/in/someone → handles m. subdomain
     - instagram.com/anthropic → Instagram actor
     - x.com/AnthropicAI → Twitter actor (handles x.com -> twitter mapping)
     - amazon.com/dp/B12345 → Amazon actor
     - unknown-site.com → website-content-crawler fallback
   - Test fetch with structured actor returns FetchResult with structured_data populated and skip_extraction=True
   - Test fetch with markdown actor returns FetchResult with html populated (markdown text) and skip_extraction=False
   - Test ApifyApiError "permission required" returns FetchResult with helpful error message
   - Test timeout handling
   - Test gotcha from README: dataset ID is fetched from run["defaultDatasetId"], not run["id"]
   - Test max_items and max_charge_usd are passed to actor.call
   - At least 18 tests

6. tests/test_router_apify.py — Integration with router:
   - Mock both scrapling_wrapper and ApifyHandler
   - Test FORTRESS site with APIFY_TOKEN routes to ApifyHandler
   - Test FORTRESS site without APIFY_TOKEN returns error
   - Test AUTH_GATED with APIFY_TOKEN routes to ApifyHandler
   - Test --use-apify flag overrides classification
   - Test non-fortress sites without --use-apify use Scrapling path
   - At least 8 tests

7. Add an integration test (tests/integration/test_phase4_live.py, marked @pytest.mark.integration):
   - Test website-content-crawler against pypi.org (only runs with APIFY_TOKEN env var set)
   - Skip with pytest.skip() if APIFY_TOKEN not set
   - Verify FetchResult has html (markdown) populated

CRITICAL gotchas from README to implement:
- run["defaultDatasetId"] is different from run["id"] — fetch results from defaultDatasetId
- Apify actors require permission approval first time — surface this as a clear error message
- max_total_charge_usd should be passed as Decimal, not float
- ApifyClientAsync is the async version — use it for the async fetch method
```

### Verify

```
pytest tests/ -v --ignore=tests/integration
pytest tests/integration -v -m integration  # if APIFY_TOKEN set
python -m pluck.cli https://www.linkedin.com/jobs/search/?keywords=python --auto
python -m pluck.cli https://pypi.org/project/scrapling/ --use-apify --auto
```

The first should route to the LinkedIn jobs actor and return structured job data directly (no Claude extraction). The second forces the Apify path on a normal URL — should use website-content-crawler and run the markdown through Claude.

You'll need to approve the LinkedIn actor permissions at console.apify.com first (one-time per actor).

---

## Phase 5 — Pipeline orchestrator, formatters, and polished CLI

**Input:** A URL (and optionally a schema and output format).
**Output:** Structured data displayed as a table or saved to a file.

### Model: Sonnet 4.6

`claude-sonnet-4-6`

Wiring and polish. No new architectural decisions, just connecting the existing pieces with good error handling and a clean CLI surface.

### Prompt

```
Read README.md for project context. Phases 1-4 are built (classification, fetching, extraction, Apify).

Build Phase 5 of Pluck.ai: the pipeline orchestrator, output formatters, and polished CLI. This is the final phase — after this Pluck is a complete tool.

Create these files:

1. Update pluck/models.py — Add:
   - PipelineResult: url (str), site_profile (SiteProfile), fetch_result (FetchResult | None), extraction_result (ExtractionResult | None), formatted_output (str), output_format (str), total_time_ms (float), steps_completed (list[str]), error (str | None) = None

2. pluck/pipeline.py — The orchestrator:
   - class PluckPipeline:
     - __init__(self, config: Config)
     - Initialize Anthropic client and (if APIFY_TOKEN set) ApifyHandler
     - async def run(self, url: str, schema: ExtractionSchema | None = None, output_format: str = "table", max_items: int = 100, use_apify: bool = False) -> PipelineResult
     - Steps:
       1. ingest(url) → SiteProfile (track step "ingest")
       2. router.fetch(profile, use_apify=use_apify) → FetchResult (track step "fetch")
       3. If fetch_result.skip_extraction: skip step 4 (Apify structured data path)
          Else: extract(fetch_result, schema, anthropic_client) → ExtractionResult (track step "extract")
       4. format the data (track step "format") → formatted string
     - At each step, capture errors and return partial PipelineResult with steps_completed up to the failure
     - Track total time across all steps
     - Add logging at INFO level for each step start/end

3. pluck/formatters.py — Output formatters:
   - to_table(items: list[dict], max_col_width: int = 40) -> str — ASCII table with column headers, row separators, truncated long values. Handle empty list, single item, mismatched keys across items (union of all keys as columns).
   - to_json(items: list[dict], pretty: bool = True) -> str — JSON serialization
   - to_csv(items: list[dict]) -> str — CSV with header row, handle nested dicts by flattening with dot notation (e.g., "address.city"), handle lists by joining with "|", quote properly
   - format_output(items: list[dict], format: str) -> str — dispatcher that calls the right formatter

4. Update pluck/cli.py — Final CLI:
   - Replace existing CLI with a polished version using argparse subcommands or just better flag handling
   - Required: <url> as positional
   - Flags:
     - --output / -o FILE — save to file (auto-detect format from extension: .json, .csv, .md, .txt)
     - --format / -f [table|json|csv] — explicit format (default: table)
     - --schema FILE — load schema from JSON file
     - --use-apify — force Apify path
     - --max-items N — cap returned items (default 100)
     - --auto — skip confirmation prompts
     - --show-steps — print each pipeline step with timing
     - --dry-run — only run ingest + classify, don't fetch or extract
     - --verbose / -v — debug logging
   - Load .env file at startup
   - Show clear error if ANTHROPIC_API_KEY missing
   - Show warning if APIFY_TOKEN missing (but don't fail)
   - When --output points to a file, also print a one-line summary to terminal (e.g., "Saved 45 items to output.json")
   - Show cost estimate at end (Claude tokens used × rate)
   - Use the existing PluckPipeline class — don't rebuild logic

5. tests/test_formatters.py — Tests:
   - Test to_table with normal data
   - Test to_table with empty list returns empty/header-only output
   - Test to_table with single item
   - Test to_table with items having different keys (union of keys as columns, missing values shown as empty)
   - Test to_table truncates long values per max_col_width
   - Test to_json produces valid parseable JSON
   - Test to_json pretty=True vs pretty=False
   - Test to_csv produces valid CSV (parseable by csv module)
   - Test to_csv flattens nested dicts with dot notation
   - Test to_csv joins lists with pipe
   - Test to_csv handles values with commas (quoted)
   - Test to_csv handles values with quotes (escaped)
   - Test format_output dispatches correctly
   - Test format_output raises on unknown format
   - At least 16 tests

6. tests/test_pipeline.py — Integration tests with mocked dependencies:
   - Mock ingester, router, extractor, formatter
   - Test successful run through all steps populates PipelineResult correctly
   - Test fetch error returns partial PipelineResult with steps_completed=["ingest"]
   - Test extraction error returns partial PipelineResult with steps_completed=["ingest", "fetch"]
   - Test skip_extraction path: Apify returns structured data, extraction step is skipped, format is called directly on fetch_result.structured_data
   - Test schema parameter is passed through to extractor
   - Test use_apify parameter is passed to router
   - Test logging output for --show-steps
   - Test total_time_ms is captured
   - Test ANTHROPIC_API_KEY missing raises clear error
   - At least 12 tests

7. tests/test_cli.py — CLI tests:
   - Test argparse parses all flags correctly
   - Test --output with .json extension sets format=json
   - Test --output with .csv extension sets format=csv
   - Test --format overrides extension-inferred format
   - Test --dry-run only runs ingest, doesn't call fetch/extract
   - Test --schema loads schema from JSON file
   - Test invalid schema file produces clear error
   - Test --auto skips confirmation prompts
   - Test --verbose enables debug logging
   - At least 10 tests

8. Add a Phase 5 integration test (tests/integration/test_phase5_live.py):
   - Full end-to-end test: python -m pluck.cli https://pypi.org/project/scrapling/ --auto --output /tmp/test_output.json
   - Verify the output file exists and contains valid JSON
   - Marked @pytest.mark.integration

After this phase, the project is complete. Update README.md with a "Usage" section showing common CLI commands.
```

### Verify

```
pytest tests/ -v --ignore=tests/integration
pytest tests/integration -v -m integration

# Smoke tests
python -m pluck.cli https://pypi.org/project/scrapling/ --auto
python -m pluck.cli https://pypi.org/project/scrapling/ --auto --output scrapling.json
python -m pluck.cli https://pypi.org/project/scrapling/ --auto --output scrapling.csv
python -m pluck.cli https://news.ycombinator.com --auto --show-steps
python -m pluck.cli https://news.ycombinator.com --dry-run
```

After this phase Pluck is a finished tool. You can point it at any URL and get a table back.

---

## Summary

| Phase | What you get | Model | Tests |
|---|---|---|---|
| 1 | URL → SiteProfile (classification) | Sonnet 4.6 | 37+ |
| 2 | SiteProfile → FetchResult (HTML or XHR JSON) | Sonnet 4.6 | 32+ |
| 3 | FetchResult → ExtractionResult (Claude path) | Opus 4.6 | 60+ |
| 4 | Apify integration for fortress sites | Sonnet 4.6 | 26+ |
| 5 | Full pipeline + formatters + polished CLI | Sonnet 4.6 | 38+ |

Total estimated build cost across all phases: ~$2-4 in Claude API usage.

Each phase ends with a working CLI you can test against real URLs. You can stop at any phase and still have something useful.

The README.md in your project root is the source of truth for architectural decisions. Each phase prompt starts with "Read README.md for project context" because Claude Code will use it as the foundation for implementation choices.

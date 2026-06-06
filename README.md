# Pluck.ai

Pluck is a personal web scraping tool. Give it a URL, get back structured data as a table.

It targets sites that don't offer easy data export: job boards, product listings, search results, price trackers. The user pastes a URL, Pluck figures out how to scrape it, extracts the data, and returns rows and columns.

This is a personal tool, not a product. There is no user management, no multi-tenancy, no public API. One user, one machine, one URL at a time.

## Usage

```bash
# Quick start — paste a URL, get a table
python -m pluck.cli https://news.ycombinator.com --auto

# Save to JSON
python -m pluck.cli https://pypi.org/project/scrapling/ --auto --output results.json

# Save to CSV
python -m pluck.cli https://pypi.org/project/scrapling/ --auto --output results.csv

# Explicit format (overrides extension)
python -m pluck.cli https://example.com/ --format json --auto

# Bring your own schema (skip inference)
python -m pluck.cli https://example.com/products --schema schema.json --auto

# Classify only — no fetch, no extraction
python -m pluck.cli https://linkedin.com/jobs/search/?keywords=python --dry-run

# Fortress sites via Apify (requires APIFY_TOKEN)
python -m pluck.cli https://www.linkedin.com/jobs/search/?keywords=python --auto

# Force Apify path for any site
python -m pluck.cli https://example.com/ --use-apify --auto

# Limit results
python -m pluck.cli https://example.com/products --max-items 20 --auto

# Show step timing
python -m pluck.cli https://example.com/ --show-steps --auto

# Debug logging
python -m pluck.cli https://example.com/ --verbose --auto
```

### Flags

| Flag | Short | Description |
|---|---|---|
| `--output FILE` | `-o` | Save output to file. Format inferred from `.json`/`.csv`/`.md` extension. |
| `--format FORMAT` | `-f` | Explicit format: `table`, `json`, `csv`. Overrides extension. Default: `table`. |
| `--schema FILE` | | Load schema from JSON file, skip inference. |
| `--use-apify` | | Force Apify fetch path for any site (requires `APIFY_TOKEN`). |
| `--max-items N` | | Cap returned items. Default: 100. |
| `--auto` | | Skip confirmation prompts. |
| `--show-steps` | | Print pipeline steps and total time. |
| `--dry-run` | | Classify only — skip fetch and extraction. |
| `--verbose` | `-v` | Enable debug logging. |

### Environment variables

```bash
ANTHROPIC_API_KEY=sk-...         # Required for Claude extraction
APIFY_TOKEN=apify_api_...        # Required for fortress sites (LinkedIn, Instagram, etc.)
```

Both can be set in a `.env` file in the working directory.

## Web Interface

### Local development

```bash
make install
make dev
```

Open http://localhost:5173

`make dev` starts the FastAPI backend on port 8000 and the Vite dev server on port 5173. All `/api` calls are proxied automatically — no CORS issues, no hardcoded URLs.

### Deploy to Railway

1. Push to GitHub
2. Connect repo to Railway (railway.app)
3. Set environment variables: `ANTHROPIC_API_KEY`, `APIFY_TOKEN`, `PLUCK_PASSWORD`
4. Railway builds and deploys automatically

The Dockerfile builds the React frontend and serves it as static files from the FastAPI process — single container, single port.

### Environment variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Claude API access for extraction |
| `APIFY_TOKEN` | No | Enables fortress site support |
| `PLUCK_PASSWORD` | No | Web UI password (default: `pluck`) |
| `USE_PLANNER` | No | Intent-aware Apify planner + discovery fall-through (default: `true`). Set to `false` to disable. |

## How it works

Pluck has four stages: classify, fetch, extract, format.

**Classify.** Pluck takes the URL, makes an initial HTTP request, and examines the response to determine what kind of site it's dealing with. The classifier assigns the URL to one of seven site groups (detailed below) based on signals in the HTTP headers, HTML content, and domain name.

**Fetch.** Based on the classification, Pluck routes the URL to the right fetcher. Simple sites get plain HTTP requests. JavaScript-rendered sites get a headless browser. Anti-bot-protected sites get a stealth browser with fingerprint spoofing. Fortress sites (LinkedIn, Instagram, etc.) get routed to Apify's pre-built scrapers running on their cloud. The output of this stage is either raw HTML or structured JSON, depending on the fetcher used.

**Extract.** If the fetcher returned HTML, Pluck cleans it (strips scripts, nav, footers, ads) and sends the full cleaned page to Claude's API, asking it to pull out structured data matching a schema. If the fetcher returned structured JSON (from Apify or from XHR interception), extraction is skipped because the data is already structured.

**Format.** The extracted data gets formatted as a table for terminal display, or exported as JSON/CSV to a file.

## Site taxonomy

Every URL Pluck processes gets classified into one of seven groups. Each group maps to a fetching strategy.

**Group 1 — Static HTML.** The server returns complete HTML with content in the body. No JavaScript rendering needed. Examples: Wikipedia, government sites, blogs, documentation pages. Fetcher: `Fetcher.get()` (plain HTTP via curl_cffi, ~80ms).

**Group 2 — Server-rendered with pagination.** Same as Group 1, but the content spans multiple pages. Signals: `rel=next/prev` links, `?page=` query params, pagination nav elements. Fetcher: `Fetcher.get()` with sequential page requests via `AsyncFetcher`.

**Group 3 — JS-rendered with clean APIs.** The page loads a minimal HTML shell, then JavaScript fetches data from internal APIs and renders it. Signals: near-empty body with React/Vue/Next.js markers, JSON-LD or schema.org markup, `__NEXT_DATA__` script tags. The internal API responses contain clean, structured data. Fetcher: `DynamicFetcher.fetch()` with `capture_xhr` to intercept the API calls and grab the JSON directly. If XHR capture succeeds, Claude extraction is skipped.

**Group 4 — JS-rendered with messy DOM.** Same as Group 3, but without clean internal APIs. The data is rendered into a complex DOM with inline scripts, dynamically generated class names, and no structured data markup. Fetcher: `DynamicFetcher.fetch()` or `StealthyFetcher.fetch()` with `network_idle=True` to wait for rendering to complete, then pass the rendered HTML to Claude.

**Group 5 — Interactive-gated.** The content exists on the page but is hidden behind an interaction barrier: cookie consent walls, age verification modals, "load more" buttons, infinite scroll, subscription overlays. Fetcher: `StealthyFetcher.fetch()` with a `page_action` callback that dismisses the barrier (clicks the accept button, scrolls down, closes the modal) before extracting content.

**Group 6 — Auth-gated.** The site requires login credentials to access the content. Signals: 401/403 status codes, redirect to login page, login form detection. Fetcher: Apify actor (the user provides credentials to the Apify actor, which handles the authenticated session on Apify's servers).

**Group 7 — Fortress.** Sites with aggressive anti-bot systems that detect and block automated access regardless of stealth measures. LinkedIn, Facebook, Instagram, X/Twitter, Amazon (at scale). Fetcher: Apify pre-built actors maintained by the community, which stay updated as these platforms change their defenses.

## The three tools

### Scrapling

Scrapling is an open-source Python library (BSD-3 license, free, runs locally) that handles fetching and parsing for Groups 1–5. It has four fetcher classes that form an escalation ladder:

`Fetcher` — Plain HTTP via curl_cffi. Impersonates real browser TLS fingerprints (Chrome, Firefox, Safari) at the protocol level without launching a browser. Fast (~80ms), lightweight, no browser binary needed. Returns a `Response` object with CSS/XPath selectors, text search, regex search, and DOM traversal.

`AsyncFetcher` — Same engine as `Fetcher`, but async. Fetches multiple pages concurrently. Used for paginated sites.

`StealthyFetcher` — Launches an actual browser via Patchright (a patched Playwright fork) using Camoufox (a modified Firefox). Spoofs canvas, WebGL, WebRTC, and other browser fingerprinting vectors. Can solve Cloudflare Turnstile challenges. Supports `page_action` callbacks for interacting with the page before extraction. Timeout parameter is in milliseconds (e.g., `timeout=30000` for 30 seconds).

`DynamicFetcher` — Launches a standard Playwright browser. Less stealth than `StealthyFetcher`, but supports `capture_xhr` — a URL pattern parameter that intercepts XHR/fetch API calls matching the pattern and returns their responses. When a JS-rendered site loads data from an internal API, `capture_xhr` grabs that JSON directly, skipping HTML parsing and Claude extraction. Timeout is also in milliseconds.

All four fetchers return the same `Response` object type, which extends Scrapling's `Selector` class. The `Response` includes: `.status`, `.reason`, `.headers`, `.cookies`, `.history` (redirects), `.html_content`, `.text`, `.url`, plus the full selector API (`.css()`, `.xpath()`, `.find()`, `.find_all()`, `.find_by_text()`, `.find_by_regex()`, `.find_similar()`).

**Adaptive selection.** Scrapling can fingerprint HTML elements and relocate them after site redesigns. On the first scrape, you pass `auto_save=True` to a selector call, and Scrapling stores a fingerprint (tag, attributes, text, DOM path, parent info, siblings) in a local SQLite database. On subsequent scrapes, passing `adaptive=True` makes Scrapling compare the stored fingerprint against every element in the current DOM using Python's SequenceMatcher, returning the closest match even if class names, IDs, or positions changed. This is useful for repeated scraping of the same site over time. For Pluck's one-shot use case, the more relevant feature is `find_similar`, which discovers repeating elements on a page without knowing their selector.

**Cost: Free.** No API keys, no usage limits. Runs on the local machine.

### Claude API

Claude's API is the intelligence layer for structured data extraction. When Scrapling returns raw HTML from a page, Pluck cleans the HTML (removes script, style, nav, footer, ad containers, hidden elements, cookie banners) and sends the full cleaned page to Claude in a single API call with a prompt asking it to extract structured data.

The prompt includes: the cleaned HTML, a schema defining what fields to extract (field names, types, descriptions), and the parent context (where on the page this content came from). Claude returns a JSON array of extracted items.

If no schema is provided, Pluck first runs a schema inference call: it sends a sample of the page content to Claude and asks it to identify what structured data can be extracted, returning field definitions. The user can confirm or modify this inferred schema before extraction proceeds.

For most web pages, the cleaned HTML fits within Claude's context window in a single call. A typical page produces 30K–50K tokens of cleaned HTML. Haiku (200K context) handles this for extraction; Sonnet or Opus handle it with room to spare.

**Model routing:**
- Schema inference: Haiku 4.5 (classification task, low complexity)
- Data extraction: Haiku 4.5 (structured data pulling from HTML, well-defined task)
- Complex or ambiguous pages: Sonnet 4.6 (fallback when Haiku extraction quality is poor)

**Cost: Pay per token.** Roughly $0.01–0.05 per page using Haiku, depending on page size.

### Apify

Apify is a cloud platform with 20,000+ pre-built scraping actors. Pluck uses it for Group 6 (auth-gated) and Group 7 (fortress) sites where local scraping fails.

An Apify actor is a Docker container that accepts JSON input, runs a scraping job on Apify's servers (with managed proxies, browser infrastructure, and anti-bot handling), and writes structured results to a dataset. The Python client call is `client.actor("actor-id").call(run_input={...})`, which starts the container, waits for completion, and returns a run object. Results are fetched with `client.dataset(run["defaultDatasetId"]).list_items()`.

Apify actors return structured data (list of dicts), not HTML. Each actor has its own output schema. A LinkedIn jobs actor returns `{title, company, location, salary, postedAt, ...}`. An Amazon product actor returns `{title, price, rating, reviewsCount, ...}`. Pluck auto-detects the schema from the output fields and formats the results directly. Claude extraction is skipped for the Apify path.

**Domain-to-actor routing.** Pluck maintains a mapping of known domains to their best Apify actors. The mapping is path-aware: `linkedin.com/jobs/` routes to a jobs actor, `linkedin.com/in/` routes to a profile actor, `linkedin.com/company/` routes to a company actor. Unknown domains fall back to `apify/website-content-crawler`, a generic actor that returns page text and markdown.

**Cost control.** Every `actor.call()` accepts `max_items` (cap on returned results) and `max_total_charge_usd` (hard spending limit per run). Apify's free plan includes $5/month in credits. A compute unit (CU) = 1 GB RAM × 1 hour. Most scraping runs consume 0.01–0.5 CU at $0.30/CU on the free plan. Some actors add per-result fees on top of CU costs — check the actor's Pricing tab before use.

**Cost: Free tier $5/month**, then pay-per-use. For Pluck's personal, occasional fortress-site use, the free tier covers it.

## Data flow paths

Pluck has four paths through the pipeline. The classifier picks the path; the user doesn't choose.

### Path 1: HTML → Claude

For Groups 1, 2, 4, 5. The standard path.

```
URL → classify → Scrapling fetch (HTTP or browser)
    → noise filter (strip scripts, nav, ads, hidden elements)
    → Claude API (send full cleaned HTML + schema → JSON array)
    → format as table/JSON/CSV
```

### Path 2: XHR intercept → direct JSON

For Group 3 sites where the browser intercepts clean API responses.

```
URL → classify → DynamicFetcher with capture_xhr
    → intercepted JSON from internal API
    → auto-detect schema from JSON fields
    → format as table/JSON/CSV
```

Claude is skipped. The data arrives structured.

### Path 3: Apify → direct JSON

For Groups 6 and 7. Fortress and auth-gated sites.

```
URL → classify → route to Apify actor (domain + path mapping)
    → actor.call() on Apify's cloud
    → structured dataset (list of dicts)
    → auto-detect schema from output fields
    → format as table/JSON/CSV
```

Claude is skipped. The actor returns structured data.

### Path 4: Apify markdown → Claude

For Group 6–7 sites where the Apify actor returns markdown/text instead of structured fields (e.g., the generic `website-content-crawler`).

```
URL → classify → Apify website-content-crawler
    → markdown text of page content
    → Claude API (send markdown + schema → JSON array)
    → format as table/JSON/CSV
```

This is the fallback when no specialized actor exists for the domain.

## Noise filtering

Before sending HTML to Claude, Pluck removes elements that waste tokens and confuse extraction:

Remove by tag: `script`, `style`, `noscript`, `iframe`, `svg` (unless it contains text data).

Remove by semantic role: `nav`, `footer`, `aside`.

Remove by class/ID pattern: cookie-banner, cookie-consent, ad-container, sidebar, social-share, newsletter-signup, popup, overlay, modal. Match flexibly across hyphens, underscores, and camelCase.

Remove hidden elements: `style="display:none"`, `style="visibility:hidden"`, `aria-hidden="true"`, `hidden` attribute.

Preserve: `main`, `article`, `section`, `table`, `ul`, `ol`, `dl`, `form`, `figure`.

On a typical page, this reduces HTML size by 15–50%, saving tokens and improving extraction accuracy.

## Configuration

Pluck reads configuration from environment variables and a `.env` file:

```
ANTHROPIC_API_KEY=sk-...          # Required. Claude API access.
APIFY_TOKEN=apify_api_...         # Optional. Enables fortress site support.
PLUCK_MAX_CHUNK_CHARS=3000        # Max size for fallback chunking (edge case).
PLUCK_MAX_CONCURRENT=5            # Max parallel Claude API calls.
PLUCK_DEFAULT_FORMAT=table        # Output format: table, json, csv.
USE_PLANNER=true                  # Intent-aware Apify planner + discovery. Default true.
```

**`USE_PLANNER` (default `true`).** When on, requests to a registry host (Instagram,
LinkedIn, Amazon, plus any tier-2 discovered host) are routed through the intent-aware
planner: one Haiku call reads the prompt and picks the best Apify actor and output
columns. For hosts not in the registry, the discovery fall-through searches the Apify
Store, ranks candidates with Haiku, captures the real output schema, and caches the
winner. Set `USE_PLANNER=false` to disable both and use only the legacy
classify → fetch → extract path.

If `APIFY_TOKEN` is missing, Pluck still works for Groups 1–5. Group 6–7 URLs return an error message suggesting the user set the token.

## Dependencies

```
scrapling[all]          # Fetching + parsing + browser automation
apify-client            # Apify API client (optional)
anthropic               # Claude API client
beautifulsoup4          # Noise filtering
lxml                    # HTML parsing (Scrapling dependency)
python-dotenv           # .env file loading
httpx                   # Async HTTP (Scrapling dependency)
```

## Gotchas discovered during exploration

These were found by running both tools on a Windows machine and should be accounted for in the implementation:

**Scrapling browser fetcher timeouts are in milliseconds.** `StealthyFetcher.fetch(..., timeout=30)` means 30ms, not 30 seconds. Use `timeout=30000` for a 30-second timeout. This applies to `StealthyFetcher` and `DynamicFetcher`. The plain `Fetcher` uses seconds.

**Scrapling adaptive mode requires SQLite storage setup.** You must pass a `selector_config` dict with `adaptive=True`, `storage=SQLiteStorageSystem` (the class itself, not an instance — it must have the `__wrapped__` attribute from `lru_cache`), and `storage_args` with `storage_file` (an absolute path to a writable location) and `url` (the domain). On Windows, use `os.path.join(os.path.dirname(__file__), "pluck_adaptive.db")` or similar. `/tmp/` paths don't exist on Windows.

**Apify actors require permission approval.** The first time you use a Store actor, you may need to approve its permissions in the Apify web console before the API call succeeds. This is a one-time per-actor action.

**Apify dataset IDs differ from run IDs.** The run log shows a `runId`. To fetch results, you need the `defaultDatasetId` from the run object: `run = client.actor(...).call(...)`, then `client.dataset(run["defaultDatasetId"]).list_items()`.

**Apify billing has two layers.** Platform compute units (GB RAM × hours) plus optional per-result fees from individual actors. Check the actor's Pricing tab before use.

**PyPI search pages are JS-rendered.** `Fetcher.get()` returns an almost-empty page for JS-rendered sites. `DynamicFetcher.fetch()` or `StealthyFetcher.fetch()` with a real browser returns the full rendered content. This validates the site taxonomy: the classifier must detect JS-rendered pages and route them to a browser fetcher.

**`StealthyFetcher` returns more HTML than `Fetcher` on the same URL.** On pypi.org/project/scrapling/, `Fetcher` returned 159K chars and `StealthyFetcher` returned 182K chars. The 23K difference is JS-rendered content. For Claude extraction, more HTML means more complete data but more tokens.

## Project structure

```
pluck/
    __init__.py
    models.py               # SiteGroup enum, SiteProfile, FetchResult,
                             # ExtractionSchema, FieldDef, ExtractionResult,
                             # PipelineResult dataclasses
    config.py                # Load .env, validate keys, defaults
    pipeline.py              # PluckPipeline orchestrator
    cli.py                   # CLI entry point

    classifiers/
        __init__.py
        site_classifier.py   # URL → SiteGroup classification

    fetchers/
        __init__.py
        router.py            # SiteGroup → fetcher dispatch
        scrapling_wrapper.py # Thin wrappers around Scrapling fetchers
        apify_handler.py     # Apify actor routing and execution

    extraction/
        __init__.py
        noise_filter.py      # HTML cleaning before Claude
        schema_inference.py   # Auto-detect extraction schema
        prompts.py            # Claude prompt templates
        extractor.py          # Claude API extraction engine
        json_repair.py        # Fix malformed JSON from Claude

    formatters.py             # JSON, CSV, ASCII table output

tests/
    conftest.py              # Shared fixtures, mock Anthropic client
    fixtures/
        sample_pages.py      # Realistic HTML test pages
    test_classifier.py
    test_fetchers.py
    test_noise_filter.py
    test_extraction.py
    test_pipeline.py
    test_formatters.py

.env                         # API keys (not committed)
README.md                    # This file
```

# Follow-ups

Tracked items deferred from completed work. Not yet scheduled.

## 1. Actor-ranking quality for one-row-per-item intents

For prompts like "get videos" / "get posts" that imply a one-row-per-item output
shape, the discovery Haiku call sometimes picks a **profile** scraper (one row per
profile, videos/posts nested or empty) instead of a **per-item** scraper. Observed
live: `tiktok.com/@nasa` + "get videos" → `clockworks/tiktok-profile-scraper`
(1 profile row, "No videos to scrape") rather than a video scraper.

Fix: tighten `DISCOVERY_SYSTEM` in `pluck/registry/discovery_planner.py` with an
explicit rule that output granularity should match intent — when the prompt asks for
items (videos/posts/products), prefer an actor that returns one row per item over a
profile/account scraper. Related: the Reddit run produced `startUrls: ["{url}"]` for a
`requestListSources`-style field that wants `[{"url": ...}]`; the prompt could also
show array-of-object input examples.

## 2. plan_cache has no logic versioning

`logic_version` invalidates stale tier-2 `discovered_actors` rows when discovery code
is upgraded, but `plan_cache` keeps serving old plans for `(host, prompt_hash)` until
the 7-day TTL expires — masking the improved discovery. Observed live: a fresh, correct
discovery was overridden by a stale cached plan from a prior logic version.

Fix: either add a `logic_version` column to `plan_cache` (filter reads by current
version, like `discovered_actors`) or fold the version into the plan-cache key. Until
then, clearing `plan_cache` is required after a discovery-logic bump.

## 3. Fortress-site reliability (TikTok, Reddit, etc.)

Discovered scrapers for fortress sites return uneven/thin results due to anti-bot
defenses (TikTok "No videos to scrape"; Reddit blocked / JS-rendered). Some community
actors also require account permission approval.

Fix idea: track per-actor empty-result counts and blacklist (or down-rank) a discovered
actor after N consecutive empty/thin outputs, so discovery stops re-selecting an actor
that reliably fails for a given host.

## 4. Actor minimum-cost floors vs small max_items

Some actors (e.g. the hardcoded `trudax/reddit-scraper-lite`) enforce a minimum cost
per run: a request with `max_items` below ~15 fails with "Maximum cost per run is lower
than actor start cost" (observed at `max_items=10`). The Apify `.call(max_items=N)` cost
cap is what trips it. The registry entry's `input_notes` documents this, but nothing
enforces a per-entry floor at request time.

Fix idea: add an optional `min_items` field to registry/discovered entries and clamp
`max_items` up to it (or surface a clearer error) so these actors don't hard-fail on
small requests.

## 5. Conditional runtime requirements not in schema `required` (Indeed smoke, 2026-06-12)

Discovery for `indeed.com/jobs?q=data+analyst&l=Remote` + "get job listings" correctly
chose a real Indeed scraper (`borderline/indeed-scraper` — no generic scraper even
reached the top-3, so the new user-code filter had nothing to remove). But the
capture probe FAILED with `Missing 'country' input`: the actor requires *either*
`query`+`country` *or* a URL list, a conditional rule its JSON-schema does not express
in `required`, so the Haiku template sent `query`+`location`+`maxRows` only. Discovery
then fell back to legacy as designed.

Fix idea: feed capture-probe failure messages back into a single retry of the
discovery call ("the actor rejected this input with: <error>; fix the template"),
or down-rank an actor after a failed probe and try the next candidate.

## 6. Legacy fallback for unknown auth-gated domains always fails (pageFunction)

When discovery falls back to legacy for a domain not in `_ACTOR_MAP`
(`pluck/fetchers/apify_handler.py`), `resolve_actor` returns the generic
`apify/web-scraper` and `_build_actor_input` sends input with **no `pageFunction`**,
so every such run fails with `Field input.pageFunction is required`. Observed live on
the Indeed smoke: discovery's graceful fallback landed here and the request ended in
error. Pre-existing legacy behavior (out of scope for the discovery filter change —
"do not change the legacy fetcher").

Fix idea: give the generic fallback a trivial generic `pageFunction` (e.g. return
`document.body.innerText` / structured DOM dump), or skip Apify entirely for unknown
domains and use the non-Apify fetch path.

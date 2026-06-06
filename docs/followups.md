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

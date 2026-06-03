# Phase 1 verification — intent-aware Apify planner

Date: 2026-06-02
Branch: `phase1-apify-planned-path`

This document is the proof that the planner reads **intent**, not just the
domain. Same URL (`https://www.instagram.com/natgeo/`), two different prompts,
two different actors and output shapes — and an out-of-registry URL that the
planner leaves untouched.

---

## TL;DR

| | OLD (`USE_PLANNER` off) | NEW (`USE_PLANNER` on) |
|---|---|---|
| Routing input | domain only | domain **+ prompt** |
| natgeo, "scrape the postings" | profile-scraper, 1 profile row | **post-scraper, 100 post rows** |
| natgeo, "get the bio and follower count" | profile-scraper, 1 profile row | profile-scraper, 1 profile row (columns narrowed to intent) |
| out-of-registry (`news.ycombinator.com`) | legacy classify → fetch → extract | unchanged — planner never runs |

The OLD path routes Instagram to one actor regardless of what the user asked
for. For "scrape the postings" it returns a single profile row — the posts are
buried inside a nested `latestPosts` array — which is unusable as a postings
table. The NEW path reads the prompt, picks `instagram-post-scraper`, and
returns one row per post.

---

## Test results

### Non-integration suite — green

```powershell
.venv\Scripts\python.exe -m pytest -q -m "not integration"
```

```
419 passed, 8 deselected in ~10s
```

### Integration suite — 3/3 green (live Anthropic + Apify)

```powershell
.venv\Scripts\python.exe -m pytest tests/integration/test_planner_e2e.py -v -m integration
```

```
test_natgeo_posts_intent          PASSED   # posts intent  → post-scraper, >=12 rows, post columns
test_natgeo_profile_intent        PASSED   # profile intent → profile-scraper, exactly 1 row
test_out_of_registry_fallthrough  PASSED   # flag on but host not in registry → no planner
3 passed in ~114s
```

> **Cold-cache caveat.** The integration tests share the real `pluck_cache.db`
> results cache and do **not** pass `refresh=true`. A cache hit returns only the
> `cache` + `done` SSE events and *skips* the `planning`/`classifying` events the
> tests assert on, so a second back-to-back run fails on cached cases. Clear the
> results cache (or run with a cold cache) before the integration suite:
>
> ```powershell
> .venv\Scripts\python.exe -c "import sqlite3; from pluck.storage.cache_store import DEFAULT_DB_PATH; c=sqlite3.connect(DEFAULT_DB_PATH); c.execute('DELETE FROM results_cache'); c.commit()"
> ```
>
> Within a single run each case uses a distinct cache key (per-prompt hash, or a
> different URL), so one cold run passes all three.

---

## Before / after — the natgeo failure case

All rows below were captured live against Anthropic + Apify with `refresh=true`
to bypass the results cache. `model_used: none` throughout — the Apify path is
structured, so Claude extraction is skipped.

### OLD — `USE_PLANNER` off (legacy domain routing)

`resolve_actor("instagram.com")` → `_default` → `apify/instagram-profile-scraper`,
regardless of prompt. No `planning` step.

- **actor_id:** `apify/instagram-profile-scraper`
- **rows:** `1`
- **columns:** 25 raw profile fields — `username, fullName, biography,
  followersCount, followsCount, postsCount, verified, profilePicUrl, …,
  latestPosts, latestIgtvVideos, relatedProfiles, …`
- **shape:** profile-shaped. The posts are nested inside `latestPosts`, not
  promoted to rows. **Unusable as a postings table.**
- **cost_usd:** `0.0` (Apify run reported no billable usage; no planner call)

### NEW — `USE_PLANNER` on, prompt = "scrape the postings"

The planner reads the prompt and picks the post-scraper.

- **actor_id:** `apify/instagram-post-scraper`
- **reasoning** (from the planner): *"The user wants to scrape postings from an
  Instagram profile; instagram-post-scraper is purpose-built to return one row
  per post with engagement metrics and content details."*
- **rows:** `100` (one row per post)
- **columns:** 7, shaped to the actor's `default_columns` —
  `timestamp, type, caption, likesCount, commentsCount, hashtags, url`
- **cost_usd:** `0.268914` (Apify post-scraper run for 100 posts + one planner
  Haiku call)

### NEW — `USE_PLANNER` on, prompt = "get the bio and follower count"

Same URL, profile intent → profile-scraper, with columns narrowed to the ask.

- **actor_id:** `apify/instagram-profile-scraper`
- **reasoning** (from the planner): *"The instagram-profile-scraper actor is
  purpose-built for retrieving profile-level metadata like bio and follower
  count, which directly matches the user's request."*
- **rows:** `1`
- **columns:** 3 — `biography, followersCount, username` (the planner trimmed
  the 8 default profile columns down to what the prompt asked for)
- **cost_usd:** `0.001419` (Apify profile run reported ~$0, so this is
  effectively just the planner Haiku call)

### The proof

Same `natgeo` URL, two prompts:

```
"scrape the postings"            → apify/instagram-post-scraper    → 100 rows, post columns
"get the bio and follower count" → apify/instagram-profile-scraper →   1 row, bio/follower columns
```

The domain is identical; only the intent differs. The planner routes on intent.

---

## Exact commands run

```powershell
# 1. Non-integration suite
.venv\Scripts\python.exe -m pytest -q -m "not integration"

# 2. Clear the results cache for a clean cold-cache integration run
.venv\Scripts\python.exe -c "import sqlite3; from pluck.storage.cache_store import DEFAULT_DB_PATH; c=sqlite3.connect(DEFAULT_DB_PATH); c.execute('DELETE FROM results_cache'); c.commit()"

# 3. Live integration suite (USE_PLANNER set per-test inside the tests)
.venv\Scripts\python.exe -m pytest tests/integration/test_planner_e2e.py -v -m integration
```

Required env: `ANTHROPIC_API_KEY`, `APIFY_TOKEN` (both read from `.env`).
`USE_PLANNER` is toggled per test/run, not globally.

---

## Cost delta

The planner adds **one Haiku call per request** on the planned path. Measured
from the profile case (where the Apify run reported ~$0 billable usage), that
call costs **≈ $0.0014 per request**. The planner *replaces* the legacy
`derive_columns` Haiku call on this path (the plan's `output_shape` already
chose the columns), so the net added LLM cost over the prior Apify path is
roughly one small Haiku call.

Apify run cost dominates the total and is unchanged in nature — it depends on
the actor and row count (the 100-post run reported `0.268914`; profile runs
reported ~$0).

---

## Bug found and fixed during verification

The first live run of `test_natgeo_posts_intent` failed:

```
Apify fetch failed: Input is not valid: Field input.username is required
```

Root cause: the registry `input_template` for `apify/instagram-post-scraper`
used `directUrls`, but the **live actor has no `directUrls` field** — its input
schema requires `username` (an array of handles or profile URLs). Confirmed
directly against the actor's build input schema:

```
required:   ['username']
properties: ['username', 'resultsLimit', 'skipPinnedPosts', 'onlyPostsNewerThan', 'dataDetailLevel']
```

Fix (`pluck/registry/apify_actors.json`):

```diff
   "input_template": {
-    "directUrls": ["{url}"],
+    "username": ["{username}"],
     "resultsLimit": "{max_items}"
   },
```

This mirrors the profile-scraper's `{username}` substitution (which is why the
profile case worked and the posts case did not). After the fix, all three
integration cases pass on a cold cache.

# Pluck.ai — Intent-Aware Apify Routing (Phase 1)

## Scope

**In:** Planner LLM at `/api/classify`. Hardcoded registry of curated actors for high-demand platforms. Code-side output shape application after the actor runs.

**Out (phase 2):** SQLite cache for planner decisions. URL-pattern memoization across runs.

**Out (phase 3):** Apify Store API discovery for unknown domains. Schema fetching for newly-discovered actors.

Goal: when a user submits `https://instagram.com/natgeo/` with prompt "scrape the postings," the pipeline picks `apify/instagram-post-scraper`, returns 12 posts as 12 rows, and ships a clean CSV.

---

## Architecture

```
URL + prompt
    │
    ▼
/api/classify  ──── Haiku planner ──── outputs Plan JSON
    │                                    {fetcher_group, actor_id,
    │                                     actor_input, output_shape}
    ▼
/api/extract
    │
    ├── Group 1-6: existing fetcher chain → Haiku extraction → shape
    │
    └── Group 7 (Apify):
          │
          ├── Run actor with actor_input
          ├── Pull dataset
          ├── Apply output_shape (deterministic Python)
          └── Stream rows via SSE
```

One LLM call total for Apify path. Shape application is pure pandas/jq logic.

---

## Registry schema

Single JSON file: `backend/registry/apify_actors.json`. Loaded at startup into memory.

```json
[
  {
    "domain_patterns": ["instagram.com", "www.instagram.com"],
    "actor_id": "apify/instagram-post-scraper",
    "intent_description": "List posts from an Instagram profile, hashtag, or location URL. Returns one row per post with caption, engagement counts, timestamp, media URLs, hashtags, mentions.",
    "input_template": {
      "directUrls": ["{url}"],
      "resultsLimit": "{max_items}"
    },
    "input_notes": "directUrls is an array even for one URL. resultsLimit caps post count, default 50, hard ceiling around 1000 per Apify docs.",
    "row_unit": "post",
    "default_columns": ["timestamp", "type", "caption", "likesCount", "commentsCount", "hashtags", "url"],
    "all_columns": ["id", "type", "shortCode", "caption", "hashtags", "mentions", "url", "commentsCount", "likesCount", "videoViewCount", "timestamp", "ownerUsername", "displayUrl", "videoUrl", "isPinned"]
  },
  {
    "domain_patterns": ["instagram.com", "www.instagram.com"],
    "actor_id": "apify/instagram-profile-scraper",
    "intent_description": "Get profile-level info for one or more Instagram accounts: bio, follower count, post count, profile picture, verification status. Returns one row per profile. Recent posts come nested inside latestPosts and should not be flattened by default.",
    "input_template": {
      "usernames": ["{username}"]
    },
    "input_notes": "Takes usernames (strings), not URLs. Extract the username from the URL path before passing.",
    "row_unit": "profile",
    "default_columns": ["username", "fullName", "biography", "followersCount", "followsCount", "postsCount", "verified", "profilePicUrl"],
    "all_columns": ["username", "id", "fullName", "biography", "followersCount", "followsCount", "postsCount", "verified", "private", "profilePicUrl", "externalUrl", "businessCategory"]
  }
]
```

Seed phase 1 with: Instagram (post + profile), Amazon products, LinkedIn Jobs, Google Maps places, TikTok profiles. Five platforms covers the bulk of likely testing. Add more as you hit them.

---

## Planner prompt

System prompt for Haiku call inside `/api/classify`:

```
You are a routing planner for Pluck.ai. Given a URL and a user's natural-language
prompt, you select the best Apify actor from a provided registry and produce a
complete execution plan.

You will receive:
- url: the URL to scrape
- prompt: the user's intent in natural language
- max_items: cap on result count
- candidates: array of registry entries whose domain_patterns match the URL

Output a single JSON object:
{
  "actor_id": "<one of candidates[].actor_id>",
  "actor_input": <filled-in input_template from chosen candidate>,
  "output_shape": {
    "explode_field": <null or string field name to promote to rows>,
    "columns": [<ordered list of column names to keep>],
    "rename": {<optional old_name: new_name map>}
  },
  "reasoning": "<one sentence: why this actor matches the prompt>"
}

Rules:
- Pick the actor whose intent_description best matches the user's prompt.
- Fill input_template by substituting {url}, {username}, {max_items}. Strip
  trailing slashes from URLs. Extract usernames from path segments.
- For columns, start from the candidate's default_columns. Add or remove based
  on what the user asked for. If user says "all fields" use all_columns.
- explode_field is null unless the actor returns nested arrays that need
  promoting to rows (e.g. instagram-profile-scraper's latestPosts).
- Never invent actor_ids or column names not in the registry entry.
```

Pass only candidates whose `domain_patterns` match the URL host. Code filters before LLM. The LLM sees 1-3 entries, not the whole registry.

---

## Output shape application

After actor run completes, deterministic Python:

```python
def apply_shape(dataset_rows: list[dict], shape: dict) -> list[dict]:
    rows = dataset_rows
    if shape.get("explode_field"):
        rows = [item for row in rows for item in row.get(shape["explode_field"], [])]
    columns = shape["columns"]
    rename = shape.get("rename", {})
    out = []
    for row in rows:
        flat = {rename.get(c, c): row.get(c) for c in columns}
        out.append(flat)
    return out
```

That's the whole shaping layer. No LLM call, no surprises. Test it independently with the natgeo dataset you already have in `pluck_export.csv`.

---

## Implementation order

1. **Create the registry file.** Five platforms. Hand-verify each actor_id against Apify Store. Confirm input parameter names match current actor docs (Apify sometimes renames). 30 min.
2. **Write the registry loader** that filters by URL host. Returns matching entries. 15 min.
3. **Refactor `/api/classify`** to call Haiku with the planner prompt. Return Plan JSON instead of just actor_id. 1 hr.
4. **Refactor `/api/extract`** Group 7 path to consume Plan JSON: run actor with `actor_input`, pull dataset, apply `output_shape`. 1 hr.
5. **Add Plan JSON to the SSE event stream** so the frontend can show the planner's reasoning ("Using post-scraper because you asked for posts"). Optional but useful for debugging. 30 min.
6. **Backward compatibility:** keep the old domain-only classify path available behind a feature flag until the planner is proven. 15 min.

Total: ~3-4 hours focused.

---

## Testing

Three test cases, in order:

1. **The natgeo case.** Same URL, same prompt. Expected: 12 rows, columns matching default_columns for post-scraper. This proves the planner reads the prompt.
2. **Profile intent on same URL.** URL `https://instagram.com/natgeo/`, prompt "get the follower count and bio." Expected: 1 row, profile-scraper output. This proves the planner switches actor based on prompt, not URL.
3. **Out-of-registry domain.** Any URL that doesn't match registry. Expected: graceful fallback to existing groups 1-6 (HTML fetcher chain). This proves nothing breaks for non-Apify paths.

Add each case to your test suite. You're at 269 tests, this brings you to 272.

---

## Decisions you need to make

1. **What's the fallback when the planner gets multiple registry hits and the prompt is ambiguous?** Pick the first? Ask the user? Default to a "safest most-common-intent" entry flagged in registry? I'd default to a `is_default: true` flag per domain.
2. **Where does max_items come from when the user doesn't specify?** Currently in the URL query string. Keep that, but also let the planner override (e.g. "give me the top 5" → planner sets max_items=5).
3. **What happens if Haiku returns invalid JSON?** Retry once with stricter prompt, then fall back to domain-only routing? Hard fail? I'd retry once, then fall back.
4. **Column naming.** Registry uses actor's native field names (`likesCount`, `commentsCount`). Pretty for CSV would be `likes`, `comments`. Decide whether the planner emits camelCase or whether you map in the frontend. Either is fine, pick one.

---

## Phase 2 preview (do not build yet)

After phase 1 works for a week:

- Cache `(url_host, prompt_hash) → Plan JSON` in SQLite. Skip the Haiku call when a known-good plan exists.
- Add a "regenerate plan" button in the frontend for when cached plans go stale (actor deprecated, schema changed).
- Cache TTL: 7 days. Apify actors don't change input schemas often, but they do change.

## Phase 3 preview

When a user hits a domain with no registry entry and no cache hit:

- Call Apify Store API `search?query={domain}`.
- Pull top 10 results with metadata (run count, last modified, pricing).
- Feed candidates + their `input_schema` to a Haiku discovery call.
- Cache the chosen actor as a new SQLite registry entry with confidence flag.
- After N successful runs, promote to hardcoded registry (manual review).

# Claude Code Prompt: Pluck.ai Intent-Aware Apify Routing (Phase 1)

## Mode
Plan mode. Produce a detailed implementation plan before writing any code. Do not modify files until I approve the plan.

## Background

Pluck.ai currently routes URLs to Apify actors by domain alone. The `/api/classify` endpoint looks at the URL host and picks a hardcoded actor. The user's prompt is captured in the request but ignored by routing.

This causes intent mismatches. Recent failure case: a user submitted `https://www.instagram.com/natgeo/` with prompt "scrape the postings from this account." The classifier routed to `apify/instagram-profile-scraper` (profile-shape: one row per profile with posts nested in a `latestPosts` array). The user wanted post-shape (one row per post). The actor ran successfully but the output was unusable because the shape didn't match intent.

Phase 1 fixes this by introducing a planner LLM call inside `/api/classify` that reads URL + prompt + a small curated registry, then returns a Plan JSON specifying actor_id, actor_input, and output_shape.

## Architecture summary

Request flow:
1. `/api/classify` receives URL + prompt + max_items
2. Code extracts domain from URL
3. Code filters a hardcoded registry to entries matching that domain (1-3 candidates per platform)
4. Filtered candidates + user prompt go to a single Haiku call
5. Haiku returns Plan JSON: `{actor_id, actor_input, output_shape, reasoning}`
6. Plan JSON validated against registry, then returned (or passed to `/api/extract`)
7. `/api/extract` Group 7 path consumes Plan JSON: runs actor, pulls dataset, applies output_shape (pure Python, no LLM), streams rows via SSE

The "planner" is one Haiku call. Not an agent, no loop, no tool use during the call. Deterministic post-processing on its output.

## Investigate first

Before proposing changes, read and summarize:

1. The existing `/api/classify` endpoint handler. How does it currently pick actors? Where is the domain-to-actor mapping defined?
2. The `/api/extract` Group 7 path. How does it currently call Apify actors? Where is the Apify client wrapper? How are dataset items pulled and serialized?
3. The current SSE event format. What fields stream to the frontend? We may want to surface the planner's `reasoning` field.
4. The existing test suite for these endpoints (currently 269 passing tests). What patterns are used for mocking Apify calls?
5. Where Anthropic API keys are configured. The planner needs Haiku access.
6. Any existing prompt files or LLM call patterns in the codebase that we should match for consistency.

Output a short summary of findings before proposing changes.

## Phase 1 scope

**In scope:**
- New hardcoded registry file with 4 entries: `apify/instagram-post-scraper`, `apify/instagram-profile-scraper`, one LinkedIn Jobs actor, one Amazon product actor
- Helper script (`scripts/compile_actor_entry.py`) that takes an actor_id + sample URL, fetches the actor's input schema from the Apify API, runs the actor with maxItems=1, and emits a draft registry entry for human editing
- Registry loader that filters by URL host
- Planner function: calls Haiku with system prompt + filtered candidates, parses and validates Plan JSON
- Refactor `/api/classify` to use the planner. Keep old behavior behind `USE_PLANNER` env var feature flag
- Refactor `/api/extract` Group 7 path to consume Plan JSON and apply output shapes
- Three integration tests:
  - natgeo URL + "scrape the postings" → expects post-scraper, ~12+ rows
  - natgeo URL + "get the bio and follower count" → expects profile-scraper, 1 row
  - Out-of-registry domain → expects fall-through to existing groups 1-6
- SSE event for planner output so the frontend can show reasoning (optional, only if existing SSE patterns make this easy)

**Out of scope (do not build):**
- SQLite cache for planner decisions (this is phase 2)
- Apify Store API discovery for unknown domains (this is phase 3)
- Schema drift detection (add once registry exceeds ~10 entries)
- Registry entries beyond the initial 4
- Frontend changes beyond optionally consuming a new SSE field

## Registry entry schema

Each entry is a JSON object with these fields:

```json
{
  "domain_patterns": ["instagram.com", "www.instagram.com"],
  "actor_id": "apify/instagram-post-scraper",
  "intent_description": "List posts from an Instagram profile, hashtag, or location URL. Returns one row per post.",
  "input_template": {"directUrls": ["{url}"], "resultsLimit": "{max_items}"},
  "input_notes": "directUrls is an array. resultsLimit caps at ~1000.",
  "row_unit": "post",
  "default_columns": ["timestamp", "type", "caption", "likesCount", "commentsCount", "url"],
  "all_columns": ["id", "type", "shortCode", "caption", "hashtags", "mentions", "url", "commentsCount", "likesCount", "videoViewCount", "timestamp", "ownerUsername", "displayUrl", "videoUrl", "isPinned"]
}
```

The planner is shown only entries matching the URL host. Code does the filtering, LLM does the intent matching.

## Plan JSON schema (what the planner returns)

```json
{
  "actor_id": "apify/instagram-post-scraper",
  "actor_input": {"directUrls": ["https://www.instagram.com/natgeo/"], "resultsLimit": 100},
  "output_shape": {
    "explode_field": null,
    "columns": ["timestamp", "type", "caption", "likesCount", "commentsCount", "url"],
    "rename": {}
  },
  "reasoning": "User asked for 'postings' which maps to per-post results."
}
```

`explode_field` is non-null when the actor returns nested arrays that need promoting to rows (e.g., profile-scraper's `latestPosts`).

## Validation requirements

After parsing Plan JSON:
- `actor_id` must be in the filtered candidates list. Otherwise hallucination. Retry once with stricter prompt. If still bad, fall back to first candidate and log.
- All entries in `output_shape.columns` must be in the matching registry entry's `all_columns`. Strip invalid columns, log mismatch.
- `actor_input` must populate every required parameter from the registry entry's `input_template`. Validate before calling Apify.

## Decisions to surface in the plan (do not decide unilaterally)

Flag these in the plan output for me to answer:

1. When multiple registry entries match a domain and the user prompt is ambiguous, what's the fallback? My preference: an `is_default: true` flag in the registry, one default per domain.
2. Where does `max_items` come from when unspecified? Currently URL query string. Should the planner be allowed to override based on user prompt ("give me the top 5")?
3. On invalid JSON from Haiku, retry once with stricter prompt, then fall back. Confirm.
4. Column naming: keep actor's native camelCase (`likesCount`) or transform to user-friendly (`likes`) somewhere in the pipeline? Where?

## Constraints

- Do not write any code until the plan is approved
- Do not build phase 2 or phase 3 features even if they seem easy
- Do not compile more than 4 registry entries in this phase
- Keep all changes behind the `USE_PLANNER` feature flag so the old path stays available
- Match existing code style and patterns. Read at least 3 similar files before writing new ones
- Existing tests must continue passing. New tests must use existing mocking patterns
- The Anthropic API key is already configured. Use the same client wrapper the rest of the codebase uses

## Deliverables in the plan

The plan should include:

1. Summary of findings from the investigation step
2. File-by-file change list with line-level specificity where possible
3. New files to create with their purposes
4. Test plan: which tests to add, where they go, what they verify
5. Verification commands: how to run the natgeo test case end-to-end after implementation
6. Rough time estimates per step
7. Answers requested for the four decision questions above
8. Anything in the codebase that makes phase 1 harder than expected (surprises, gotchas, refactors needed before this can land cleanly)

## Reference

A more detailed design doc exists at `pluck_apify_phase1.md`. Read it if present in the workspace, but treat this prompt as the source of truth for scope and constraints.

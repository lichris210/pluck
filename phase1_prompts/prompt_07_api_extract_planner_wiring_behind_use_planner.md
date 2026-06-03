## Prompt 7: /api/extract planner wiring behind USE_PLANNER

```text
TASK
Wire the planner into the /api/extract SSE stream behind the USE_PLANNER feature flag. When the
flag is on, the URL host has registry candidates, and the Apify branch will be taken, call the
planner (billing its tokens like derive_columns), emit a "planning" SSE event with the chosen
actor_id and reasoning, pass the plan into route_fetch, and skip the derive_columns column step
for that path (the plan's output_shape already decided columns). The old path stays the default
when USE_PLANNER is off. /api/classify is NOT changed.

PREREQUISITES
- COMMIT CURRENT STATE TO A BRANCH BEFORE STARTING (this refactors the /api/extract handler).
- Files from previous prompts that must exist: pluck/registry/planner.py (Prompt 5),
  pluck/registry/loader.py (Prompt 3), router plan param + fetch_via_apify_plan (Prompt 6)
- Files to read for context before starting:
  - api/routes.py:101-244 (extract_endpoint.stream; _UsageTrackingClient at 78-99; _sse at 63;
    results cache get/put at 118 and 241; derive_columns call at 193-212)
  - pluck/fetchers/router.py (the new plan parameter)
  - pluck/config.py (Config dataclass + get_config)
- Environment variables required: ANTHROPIC_API_KEY, APIFY_TOKEN, USE_PLANNER (new)

FILES TO CREATE
- none

FILES TO MODIFY
- .env.example: add USE_PLANNER=false with a one-line comment.
- pluck/config.py: add use_planner: bool to Config, read from USE_PLANNER (truthy parse).
- api/routes.py (inside extract_endpoint.stream):
  - Read USE_PLANNER (same os.environ style as ANTHROPIC_API_KEY).
  - Determine whether the Apify branch applies: SiteGroup in {AUTH_GATED, FORTRESS} OR force_apify.
    GOTCHA (plan gotcha 2): if a registry host classifies into a live-fetch group, the planner
    would never run; when USE_PLANNER is on and candidates_for_url(url) is non-empty, force the
    Apify branch for that request (set use_apify=True for route_fetch).
  - When planner applies: emit _sse({"step":"planning","status":"active"}); call
    plan_extraction(...) with a _UsageTrackingClient (add its token cost to cost_usd like
    derive_columns); emit _sse({"step":"planning","status":"done","actor_id":...,"reasoning":...});
    call route_fetch(profile, use_apify=True, max_items=max_items, plan=plan); then SKIP the
    derive_columns block for this path.
  - GOTCHA (plan gotcha 3): the results cache (lines 118/241) is keyed by URL only. For the
    planned path, include a prompt hash in the cache key so a different prompt on the same URL
    does not serve a stale shaped result. Leave the non-planner cache key unchanged.
  - When USE_PLANNER is off OR candidates is empty: behavior is byte-for-byte the existing path
    (out-of-registry domains fall through to groups 1-6 untouched).

TESTS TO ADD (mocked; no live network)
- tests/test_extract_planner_wiring.py (TestClient SSE; patch ingest, plan_extraction,
  fetch_via_apify_plan; set USE_PLANNER=true)
  - test_planner_invoked_for_registry_host: planning SSE event emitted with actor_id+reasoning;
    plan_extraction called once.
  - test_planner_skipped_when_flag_off: USE_PLANNER unset -> plan_extraction not called; existing
    path runs.
  - test_out_of_registry_falls_through: unknown domain + flag on -> plan_extraction not called.
  - test_planned_path_skips_derive_columns: derive_columns not called when a plan is used.

SUCCESS CRITERIA (run from project root)
1. .venv\Scripts\python.exe -m pytest tests/test_extract_planner_wiring.py -v
   Expected: 4 passed.
2. .venv\Scripts\python.exe -m pytest -q -m "not integration"
   Expected: all green, 0 failed (USE_PLANNER defaults off -> no regressions).
3. Manual smoke:
   $env:USE_PLANNER="true"; .venv\Scripts\python.exe -m uvicorn api.main:app --reload --port 8000
   then GET /api/extract?url=https://www.instagram.com/natgeo/&prompt=scrape the postings&max_items=100&token=...
   Expected: an SSE "planning" event with actor_id apify/instagram-post-scraper before "fetching".

OUT OF SCOPE
- Do not modify /api/classify or ClassifyRequest.
- Do not add plan caching to SQLite (phase 2).
- Do not change the SSE format beyond adding the "planning" step event.

COMMIT CHECKPOINT
Yes — branch + commit current state before starting (refactor of the /api/extract handler).
```

---

# Phase 1 — Sequential Implementation Prompts

> Source of truth: the approved Phase 1 plan (planner LLM at the Apify branch, hardcoded
> registry, deterministic output-shape application, all behind `USE_PLANNER`). Each prompt
> below is independently verifiable and ordered by dependency. Execute them one at a time.

## Prelude — how this breakdown differs from the suggested chunking

The suggested chunk list had a `/api/classify` refactor (chunk 5) and an `/api/extract`
"Group 7" refactor (chunk 6). The approved plan's **Decision 0** changed this based on the
actual codebase:

- `/api/classify` (`api/routes.py:49-60`) only reports the `SiteGroup`. It does **not** route
  actors and never receives the user `prompt` (`ClassifyRequest` has only `url`). It is a
  separate HTTP call from the SSE `/api/extract` stream.
- Actor routing lives in `pluck/fetchers/apify_handler.py` and runs inside `/api/extract`'s
  Apify branch (the `skip_extraction` path, taken when `SiteGroup` is `AUTH_GATED`/`FORTRESS`
  or `force_apify=true`). `/api/extract` already has `url + prompt + max_items` together.

So **there is no `/api/classify` refactor.** All planner wiring happens in `/api/extract`.
Two other adjustments: the output **shaper** is split into its own prompt (it is pure Python
and independently testable, and the handler/extract refactors depend on it), and the registry
JSON and loader are kept as separate prompts so each is verified on its own. Net result: 9
prompts. The registry-compilation prompt and the planner-code prompt remain strictly separate,
as required.

The four locked decisions are embedded in the relevant prompts:
1. **Ambiguity fallback** → `is_default: true`, one per domain (Prompts 2, 5).
2. **`max_items`** → query string is the source and the hard ceiling; planner may only lower
   it, clamped in validation (Prompt 5).
3. **Invalid JSON** → retry once with a stricter prompt, then fall back to the `is_default`
   candidate (Prompt 5).
4. **Column naming** → keep actor-native camelCase; the only prettify point is the optional
   `output_shape.rename` map (Prompts 4, 5).

---

## Prompt 1: Apify actor-entry compiler script

```text
TASK
Build a standalone helper CLI, scripts/compile_actor_entry.py, that takes an Apify actor_id
and a sample URL, fetches the actor's input schema from the Apify API, runs the actor once
with maxItems=1, and prints a draft registry entry (JSON) to stdout for a human to hand-edit
before pasting into the registry. This is tooling only — it is never imported by app code.

PREREQUISITES
- Files to read for context before starting:
  - pluck/fetchers/apify_handler.py  (ApifyClientAsync usage: actor().call(run_input=...),
    dataset().list_items(); cost/run-status handling at lines 53-190)
  - pluck/registry/apify_actors.json is NOT yet created — base the emitted draft on the
    registry schema documented in this prompt (domain_patterns, actor_id, intent_description,
    input_template, input_notes, row_unit, default_columns, all_columns, is_default).
- Environment variables required: APIFY_TOKEN
- Python entry point: .venv\Scripts\python.exe (python is not on PATH)

FILES TO CREATE
- scripts/__init__.py            : package marker so the script can share project imports
- scripts/compile_actor_entry.py : CLI; argparse for --actor-id and --url (and optional
                                    --max-items, default 1); fetches input schema, runs actor,
                                    derives all_columns from the sample row's keys, prints a
                                    draft registry entry with input_template placeholders
                                    ({url}, {username}, {max_items}) left for human editing.

FILES TO MODIFY
- none

TESTS TO ADD
- none. This is out-of-hot-path tooling. Verify manually via Success Criteria.

SUCCESS CRITERIA (run from project root)
1. Help text works without network:
   .venv\Scripts\python.exe scripts/compile_actor_entry.py --help
   Expected: usage text listing --actor-id and --url.
2. With APIFY_TOKEN set, a real run emits parseable JSON:
   .venv\Scripts\python.exe scripts/compile_actor_entry.py --actor-id apify/instagram-post-scraper --url https://www.instagram.com/natgeo/
   Expected: a single JSON object printed to stdout containing keys actor_id, input_template,
   all_columns (non-empty), and placeholder values for input_template. Piping to a JSON parser
   succeeds.
3. Missing token fails clearly:
   running without APIFY_TOKEN prints a readable error mentioning APIFY_TOKEN and exits non-zero.

OUT OF SCOPE
- Do not write the registry JSON file here (that is Prompt 2).
- Do not auto-classify columns into default_columns; leave default_columns empty or a copy of
  all_columns for the human to trim.
- Do not import this script from any app module.

COMMIT CHECKPOINT
No (new files only, no existing code touched).
```

---

## Prompt 2: Registry JSON with 4 curated entries

```text
TASK
Create the hardcoded actor registry as a single JSON file with exactly 4 entries:
apify/instagram-post-scraper, apify/instagram-profile-scraper, one LinkedIn Jobs actor
(curious_coder/linkedin-jobs-scraper), and one Amazon product actor (junglee/amazon-crawler).
Compile 3 of them with the helper script from Prompt 1; hand-derive the Instagram post-scraper
columns from the existing natgeo CSV in the workspace. Each Instagram domain gets exactly one
entry flagged is_default: true (Decision 1).

PREREQUISITES
- Files from previous prompts that must exist: scripts/compile_actor_entry.py (Prompt 1)
- Files to read for context before starting:
  - pluck/fetchers/apify_handler.py:91-112 (_build_actor_input — confirm real input param names:
    instagram-profile-scraper takes usernames[], not URLs; linkedin-jobs takes urls[];
    junglee/amazon-crawler takes startUrls[{url}])
  - hn.csv / any natgeo export present in the workspace (to hand-derive post columns)
- Environment variables required: APIFY_TOKEN (only for the compile step; not for verification)

FILES TO CREATE
- pluck/registry/__init__.py        : package marker
- pluck/registry/apify_actors.json  : JSON array of 4 entries; each entry has:
    domain_patterns (list), actor_id (str), intent_description (str), input_template (dict with
    {url}/{username}/{max_items} placeholders), input_notes (str), row_unit (str),
    default_columns (list), all_columns (list), is_default (bool).
  Instagram post-scraper: row_unit "post", is_default true for instagram.com.
  Instagram profile-scraper: row_unit "profile", is_default false; intent_description must note
    recent posts are nested in latestPosts and should not be flattened by default.
  LinkedIn Jobs: domain_patterns linkedin.com/www.linkedin.com, is_default true for linkedin.
  Amazon: domain_patterns amazon.com/www.amazon.com, is_default true for amazon.

FILES TO MODIFY
- none

TESTS TO ADD
- tests/test_registry_json.py
  - test_registry_parses_and_has_four_entries: json.loads succeeds, len == 4.
  - test_every_entry_has_required_keys: each entry contains all 9 schema keys.
  - test_exactly_one_default_per_domain: for each domain_pattern, at most one entry has
    is_default true (instagram.com has exactly one).
  - test_default_columns_subset_of_all_columns: default_columns ⊆ all_columns for every entry.

SUCCESS CRITERIA (run from project root)
1. .venv\Scripts\python.exe -m pytest tests/test_registry_json.py -v
   Expected: 4 passed.
2. JSON is well-formed:
   .venv\Scripts\python.exe -c "import json; print(len(json.load(open('pluck/registry/apify_actors.json'))))"
   Expected: prints 4.

OUT OF SCOPE
- Do not write the loader module (Prompt 3).
- Do not add a 5th entry or any TikTok/Google-Maps entries (phase 1 is 4 entries only).
- Do not modify pluck/fetchers/apify_handler.py — the old _ACTOR_MAP path stays as-is.

COMMIT CHECKPOINT
No (new files only).
```

---

## Prompt 3: Registry loader module

```text
TASK
Write a small loader that reads pluck/registry/apify_actors.json once into memory and exposes
host-based candidate lookup. The planner is shown only entries whose domain_patterns match the
URL host — code does the filtering, the LLM does the intent matching.

PREREQUISITES
- Files from previous prompts that must exist: pluck/registry/apify_actors.json (Prompt 2),
  pluck/registry/__init__.py
- Files to read for context before starting:
  - pluck/fetchers/apify_handler.py:73-88 (resolve_actor host normalization: lowercase netloc,
    strip leading "www.") — mirror this normalization exactly for consistency.

FILES TO CREATE
- pluck/registry/loader.py with:
    load_registry() -> list[dict]            : cached module-level load of the JSON.
    get_candidates(host: str) -> list[dict]  : entries whose domain_patterns match the (already
                                               normalized) host.
    candidates_for_url(url: str) -> list[dict]: thin wrapper that extracts+normalizes the host
                                               from url (lowercase, strip www.) then calls
                                               get_candidates.
    find_entry(actor_id, candidates) -> dict | None : locate a candidate by actor_id.

FILES TO MODIFY
- none

TESTS TO ADD
- tests/test_registry_loader.py
  - test_instagram_host_returns_both_entries: candidates_for_url for an instagram.com URL
    returns the 2 Instagram entries.
  - test_www_prefix_stripped: www.instagram.com and instagram.com return identical candidates.
  - test_unknown_domain_returns_empty: candidates_for_url for nytimes.com returns [].
  - test_get_candidates_is_host_based: get_candidates("linkedin.com") returns the LinkedIn entry.
  - test_find_entry_by_actor_id: find_entry returns the matching dict, None when absent.

SUCCESS CRITERIA (run from project root)
1. .venv\Scripts\python.exe -m pytest tests/test_registry_loader.py -v
   Expected: 5 passed.
2. The full non-integration suite still passes:
   .venv\Scripts\python.exe -m pytest -q -m "not integration"
   Expected: all green (prior count + the new loader tests), 0 failed.

OUT OF SCOPE
- Do not call any LLM here. Pure filtering only.
- Do not import or modify the planner, router, or routes.

COMMIT CHECKPOINT
No (new files only).
```

---

## Prompt 4: Output-shape application (shaper)

```text
TASK
Write the deterministic, LLM-free output-shape layer. apply_shape takes the raw Apify dataset
rows plus an output_shape dict and returns reshaped rows: optionally exploding a nested array
field into one row per element, projecting to an ordered column list, and applying an optional
rename map. Column names stay actor-native camelCase; the rename map is the ONLY place names are
prettified (Decision 4).

PREREQUISITES
- Files to read for context before starting:
  - The approved plan's "Output shape application" section (explode_field, columns, rename).
  - pluck/curation/curator.py (how projected rows flow downstream — match dict-of-str shape).
- Environment variables required: none

FILES TO CREATE
- pluck/registry/shaper.py with:
    apply_shape(rows: list[dict], shape: dict) -> list[dict]
      - if shape["explode_field"] is set: flatten that nested array to one row per element.
      - project each row to shape["columns"] (missing keys -> None), preserving column order.
      - apply shape.get("rename", {}) to output keys.
      - never raises on missing fields; tolerate non-dict rows by skipping them.

FILES TO MODIFY
- none

TESTS TO ADD
- tests/test_shaper.py
  - test_simple_projection: keeps only requested columns, in order.
  - test_missing_column_is_none: requested column absent in row -> value None.
  - test_explode_field_promotes_nested_rows: rows with latestPosts -> one output row per post.
  - test_rename_map_applied: rename {"likesCount": "likes"} renames the output key only.
  - test_no_explode_when_field_null: explode_field null -> rows pass through unflattened.
  - test_non_dict_rows_skipped: junk entries are dropped without raising.

SUCCESS CRITERIA (run from project root)
1. .venv\Scripts\python.exe -m pytest tests/test_shaper.py -v
   Expected: 6 passed.
2. .venv\Scripts\python.exe -m pytest -q -m "not integration"
   Expected: all green, 0 failed.

OUT OF SCOPE
- No LLM calls, no Apify calls. Pure data transformation.
- Do not wire this into apify_handler or routes yet (Prompts 6 and 7).

COMMIT CHECKPOINT
No (new files only).
```

---

## Prompt 5: Planner module with validation

```text
TASK
Write the planner: one Haiku call that, given url + prompt + max_items + the filtered registry
candidates, returns a validated Plan JSON {actor_id, actor_input, output_shape, reasoning}.
Match the existing single-call LLM style in pluck/curation/prompt_spec.py (module-level system
constant, _build_prompt, messages.create, iterate content text blocks, repair_and_parse).

Embed the locked decisions:
- Decision 1: when the prompt is ambiguous or validation fails, fall back to the candidate with
  is_default true for that host.
- Decision 2: max_items from the caller is the hard ceiling. The planner may LOWER it when the
  prompt is explicit ("top 5"); clamp any value above the ceiling back down in validation.
- Decision 3: on invalid/unparseable JSON, retry once with a stricter prompt, then fall back to
  the is_default candidate. Never raise.
- Decision 4: output_shape.columns default to the candidate's default_columns; rename is optional.
Also: do the {url}/{username}/{max_items} substitution deterministically in code (do not trust
the model to edit URL strings); for profile-scraper extract the username from the URL path.

PREREQUISITES
- Files from previous prompts that must exist: pluck/registry/loader.py (Prompt 3),
  pluck/registry/apify_actors.json (Prompt 2)
- Files to read for context before starting:
  - pluck/curation/prompt_spec.py (style to match: DEFAULT_MODEL "claude-haiku-4-5", system
    constant, _build_prompt, content-block parsing, repair_and_parse, never-raise contract)
  - pluck/extraction/json_repair.py (repair_and_parse returns list[dict], never raises)
  - pluck/fetchers/apify_handler.py:91-112 (real input_template param names per actor)
- Environment variables required: ANTHROPIC_API_KEY (for live use; tests mock the client)

FILES TO CREATE
- pluck/registry/planner.py with:
    PLANNER_SYSTEM (module-level constant; the planner system prompt from the approved plan).
    _build_prompt(url, prompt, max_items, candidates) -> str
    _substitute_template(template, url, max_items) -> dict   (deterministic placeholder fill,
        username extraction for usernames[] actors, trailing-slash strip)
    _validate_plan(plan, candidates, max_items) -> dict | None
        - actor_id must be in candidates (else None -> triggers retry/fallback)
        - output_shape.columns intersected with the chosen entry's all_columns (strip+log extras)
        - actor_input must populate every required key in the entry's input_template
        - clamp actor_input max_items / resultsLimit to the ceiling
    plan_extraction(url, prompt, max_items, candidates, client, model="claude-haiku-4-5") -> dict
        - one Haiku call; parse; validate; on failure retry once (stricter); then fall back to the
          is_default candidate built deterministically from its input_template + default_columns.

FILES TO MODIFY
- none

TESTS TO ADD (use the mock_anthropic_client fixture in tests/conftest.py)
- tests/test_planner.py
  - test_valid_plan_parses_and_validates: well-formed JSON -> returned unchanged after validation.
  - test_hallucinated_actor_id_falls_back_to_default: actor_id not in candidates -> retry ->
    falls back to is_default entry.
  - test_invalid_columns_stripped: columns not in all_columns are removed, valid ones kept.
  - test_invalid_json_retries_once_then_falls_back: first response unparseable (side_effect),
    second still bad -> returns is_default plan; create called exactly twice.
  - test_max_items_clamped_to_ceiling: planner-proposed resultsLimit above ceiling is clamped down.
  - test_profile_scraper_username_extracted: instagram profile URL -> actor_input usernames=[handle].

SUCCESS CRITERIA (run from project root)
1. .venv\Scripts\python.exe -m pytest tests/test_planner.py -v
   Expected: 6 passed.
2. .venv\Scripts\python.exe -m pytest -q -m "not integration"
   Expected: all green, 0 failed.

OUT OF SCOPE
- Do not wire the planner into routes or the fetcher yet (Prompts 6 and 7).
- Do not add caching of plans (that is phase 2).
- Do not touch /api/classify.

COMMIT CHECKPOINT
No (new files only).
```

---

## Prompt 6: Apify handler — planned execution path

```text
TASK
Add a plan-driven execution path to the Apify fetcher that runs plan["actor_id"] with
plan["actor_input"], pulls the dataset, applies apply_shape(items, plan["output_shape"]), and
returns a FetchResult whose structured_data is the shaped rows. The existing resolve_actor /
_build_actor_input / fetch_via_apify path stays untouched so the flag-off behavior and all
current tests keep passing. Thread an optional plan through the router.

PREREQUISITES
- COMMIT CURRENT STATE TO A BRANCH BEFORE STARTING (this refactors existing fetcher code).
  e.g. git checkout -b phase1-apify-planned-path && git add -A && git commit
- Files from previous prompts that must exist: pluck/registry/shaper.py (Prompt 4),
  pluck/registry/planner.py (Prompt 5)
- Files to read for context before starting:
  - pluck/fetchers/apify_handler.py (full file; reuse run/dataset/cost/status logic at 115-190)
  - pluck/fetchers/router.py:52-71 (the Apify branch dispatch)
  - tests/test_apify_handler.py:74-90 (_make_apify_client mock tree to reuse)
  - tests/test_router.py:102-134 (how plan/max_items propagation is asserted)
- Environment variables required: APIFY_TOKEN (for live use; tests mock the client)

FILES TO CREATE
- none

FILES TO MODIFY
- pluck/fetchers/apify_handler.py
  - Refactor the shared run+dataset+error+cost body of fetch_via_apify into a private helper.
  - Add async fetch_via_apify_plan(plan, apify_token, max_items, timeout_secs) that uses
    plan["actor_id"] + plan["actor_input"], reads the dataset, then sets
    structured_data = apply_shape(items, plan["output_shape"]). fetcher_used / metadata keep the
    same shape as fetch_via_apify (actor_id, run_id, dataset_id, item_count, run_status,
    apify_cost_usd).
- pluck/fetchers/router.py
  - fetch(profile, use_apify=False, max_items=100, plan: dict | None = None). In the Apify branch,
    when plan is not None call fetch_via_apify_plan, else call the existing fetch_via_apify.
    Default plan=None keeps every existing router test call valid.

TESTS TO ADD
- tests/test_apify_handler.py (append)
  - test_fetch_via_apify_plan_passes_actor_input: run_input received by actor().call equals
    plan["actor_input"].
  - test_fetch_via_apify_plan_applies_shape: nested/explode plan -> structured_data is the shaped
    rows (one row per exploded element, projected columns only).
  - test_fetch_via_apify_plan_preserves_metadata: actor_id/run_id/dataset_id present in metadata.
- tests/test_router.py (append)
  - test_apify_branch_uses_plan_when_provided: patch fetch_via_apify_plan; assert it is called
    (and fetch_via_apify is not) when plan is passed.
  - test_apify_branch_uses_legacy_when_no_plan: with plan=None, fetch_via_apify is called.

SUCCESS CRITERIA (run from project root)
1. .venv\Scripts\python.exe -m pytest tests/test_apify_handler.py tests/test_router.py -v
   Expected: all prior tests still pass + the new ones; 0 failed.
2. .venv\Scripts\python.exe -m pytest -q -m "not integration"
   Expected: all green, 0 failed (no regressions in the existing 269).

OUT OF SCOPE
- Do not modify api/routes.py here (Prompt 7).
- Do not remove or change resolve_actor / _build_actor_input / fetch_via_apify behavior.
- Do not call the planner from inside the fetcher — it receives a ready plan dict.

COMMIT CHECKPOINT
Yes — branch + commit current state before starting (refactor of existing fetcher code).
```

---

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

## Prompt 8: Integration tests (the three Phase 1 cases)

```text
TASK
Add the three Phase 1 integration tests that exercise /api/extract end-to-end with USE_PLANNER
on, plus a mocked (no-network) mirror of cases 1-2 so CI proves the wiring without hitting Apify.
Live cases carry @pytest.mark.integration and are deselected by default.

PREREQUISITES
- Files from previous prompts that must exist: all planner wiring from Prompt 7.
- Files to read for context before starting:
  - tests/test_integration_web.py (existing integration style: TestClient, auth, marker)
  - tests/test_extract_planner_wiring.py (Prompt 7 mock patterns to reuse for the mocked mirror)
  - pytest.ini / conftest.py (integration marker config; mock_anthropic_client fixture)
- Environment variables required for LIVE run: ANTHROPIC_API_KEY, APIFY_TOKEN, USE_PLANNER=true

FILES TO CREATE
- tests/integration/test_planner_e2e.py (or extend tests/integration/ if it already holds files)
  Live (@pytest.mark.integration):
  - test_natgeo_posts_intent: url natgeo + prompt "scrape the postings" -> actor
    apify/instagram-post-scraper, >= 12 rows, columns match post default_columns.
  - test_natgeo_profile_intent: url natgeo + prompt "get the bio and follower count" -> actor
    apify/instagram-profile-scraper, exactly 1 row.
  - test_out_of_registry_fallthrough: a non-registry URL -> no planner, falls through to groups
    1-6 and still returns a normal done event.
- tests/test_planner_e2e_mocked.py (NOT marked integration; planner + fetch_via_apify_plan mocked)
  - test_posts_intent_mocked: mocked plan -> post-scraper actor_id surfaced, shaped rows streamed.
  - test_profile_intent_mocked: mocked plan -> profile-scraper, single shaped row.

FILES TO MODIFY
- none (add new test files only)

SUCCESS CRITERIA (run from project root)
1. Mocked mirror runs in CI without network:
   .venv\Scripts\python.exe -m pytest tests/test_planner_e2e_mocked.py -v
   Expected: 2 passed.
2. Default suite stays green and does NOT run the live tests:
   .venv\Scripts\python.exe -m pytest -q -m "not integration"
   Expected: all green, 0 failed; live planner tests deselected.
3. Live cases (network + tokens):
   .venv\Scripts\python.exe -m pytest tests/integration/test_planner_e2e.py -v -m integration
   Expected: 3 passed (natgeo posts >=12 rows; natgeo profile 1 row; fallthrough OK).

OUT OF SCOPE
- Do not add a 4th platform or extra registry entries to satisfy a test.
- Do not modify app code to make a test pass — if a test reveals a wiring bug, fix it in the
  owning module's prompt scope and note it, do not patch around it in the test.

COMMIT CHECKPOINT
No (new test files only).
```

---

## Prompt 9: End-to-end verification and before/after writeup

```text
TASK
Run the full verification pass and document the before/after for the natgeo failure case. Capture
the OLD behavior (USE_PLANNER off -> profile-scraper, profile-shaped, unusable for "postings") and
the NEW behavior (USE_PLANNER on -> post-scraper, one row per post), and record the test results
and rough cost delta. This is the proof the planner reads intent, not just the domain.

PREREQUISITES
- Files from previous prompts that must exist: everything through Prompt 8.
- Files to read for context before starting:
  - CLAUDE.md (run commands), README.md (if it documents endpoints)
- Environment variables required: ANTHROPIC_API_KEY, APIFY_TOKEN (USE_PLANNER toggled per run)

FILES TO CREATE
- docs/phase1_verification.md (or VERIFICATION.md at root): before/after table for the natgeo
  case, the exact commands run, observed row counts/columns/actor_id for each, and the test
  summary (unit count green, 3 integration cases). Note the added per-request planner cost.

FILES TO MODIFY
- none (documentation only; optionally update README with a one-line USE_PLANNER note if a
  config section already exists)

TESTS TO ADD
- none. This prompt runs existing suites and records outcomes.

SUCCESS CRITERIA (run from project root)
1. Full non-integration suite green:
   .venv\Scripts\python.exe -m pytest -q -m "not integration"
   Expected: all green, 0 failed.
2. Integration suite green:
   .venv\Scripts\python.exe -m pytest -m integration -v
   Expected: the 3 planner cases pass.
3. OLD vs NEW captured manually:
   - $env:USE_PLANNER="false"; GET /api/extract?url=...natgeo...&prompt=scrape the postings
     -> record actor + shape (expected: profile-scraper, profile shape).
   - $env:USE_PLANNER="true";  same request
     -> record actor + shape (expected: post-scraper, >=12 post rows).
   docs/phase1_verification.md contains both captures and a one-line conclusion.

OUT OF SCOPE
- Do not start phase 2 (no SQLite plan cache, no Apify Store discovery, no schema drift).
- Do not expand the registry.
- Do not change default behavior — USE_PLANNER stays off by default after this prompt.

COMMIT CHECKPOINT
No (documentation only). Commit the docs when satisfied.
```

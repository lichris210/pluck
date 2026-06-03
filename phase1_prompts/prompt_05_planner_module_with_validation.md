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

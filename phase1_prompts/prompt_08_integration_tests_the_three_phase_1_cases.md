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

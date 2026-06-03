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

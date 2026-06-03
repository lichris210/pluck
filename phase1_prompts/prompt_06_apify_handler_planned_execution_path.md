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

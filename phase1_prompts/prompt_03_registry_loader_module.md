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

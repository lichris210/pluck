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

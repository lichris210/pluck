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

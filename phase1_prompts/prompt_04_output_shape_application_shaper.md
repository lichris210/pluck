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

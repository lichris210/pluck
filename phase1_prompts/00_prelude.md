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


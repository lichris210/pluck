# Claude Code Prompt: Decompose Phase 1 Plan Into Sequential Prompts

## Mode
Planning/output only. Do not modify any project files. The single deliverable is a new markdown file at `phase1_prompts.md` containing the decomposed prompts.

## Context
The phase 1 plan you produced and I approved (the one with the planner LLM, hardcoded registry, output shape application) is the source of truth. Treat it as already locked. Your job now is to decompose that plan into a sequence of smaller prompts that I can execute one at a time.

If you do not have the approved plan in your current context, stop and tell me. Do not infer it from this prompt alone.

## Output format

Produce one markdown file: `phase1_prompts.md`. Each prompt is a top-level section:

```
## Prompt N: <Short title>

<prompt body in a code block so I can copy-paste cleanly>
```

Each prompt body, inside its code block, must contain these sections:

1. **Task**: one-paragraph description of what this prompt builds.
2. **Prerequisites**: 
   - Files from previous prompts that must exist in the workspace
   - Files to read for context before starting (paths)
   - Environment variables required
3. **Files to create**: paths with one-line purposes
4. **Files to modify**: paths with what changes and where
5. **Tests to add**: file paths, test function names, what each test verifies
6. **Success criteria**: specific, runnable verification steps from the project root (commands to run, expected outputs)
7. **Out of scope**: things NOT to touch even if they seem related
8. **Commit checkpoint**: yes/no - whether to require a git commit before starting (yes for any refactor of existing code)

## Prompt-level constraints

- Each prompt is independently verifiable. After running its success criteria, I should know whether the step worked without reading the next prompt.
- Each prompt fits in 15-45 minutes of focused execution.
- Prompts are ordered by dependency. Earlier prompts produce artifacts later prompts consume.
- No prompt assumes context held in your head from a previous prompt. All needed information is in the prompt body or in files specified in Prerequisites.
- Where a prompt refactors existing code (specifically `/api/classify` and `/api/extract`), the prompt must include "commit current state to a branch before starting" in Prerequisites.

## Decomposition guidance

The plan has roughly these chunks. Use this as a starting point and adjust if the codebase suggests a better grouping:

1. Helper script (`scripts/compile_actor_entry.py`) for fetching actor metadata and emitting draft registry entries
2. Registry JSON with 4 entries (execute the helper script for 3 actors, hand-derive the 4th from existing natgeo CSV)
3. Registry loader module with `get_candidates(host)` function
4. Planner system prompt (separate file) + planner function with validation
5. `/api/classify` refactor: wire planner in behind `USE_PLANNER` feature flag, preserve old path
6. `/api/extract` Group 7 refactor: consume Plan JSON, apply output_shape, stream rows
7. Three integration tests (natgeo + posts, natgeo + profile, out-of-registry fallthrough)
8. End-to-end verification: capture baseline, run the test cases, document before/after

If you propose a different breakdown based on the actual structure of the codebase, explain your reasoning in a short prelude above Prompt 1.

## What to preserve from the plan

Every decision and constraint we settled. Specifically:

- Registry shape (the JSON schema with `domain_patterns`, `intent_description`, `input_template`, `default_columns`, `all_columns`)
- Plan JSON shape (`actor_id`, `actor_input`, `output_shape`, `reasoning`)
- Validation rules (actor_id must be in candidates, columns must be in all_columns, retry on bad JSON, fall back gracefully)
- Feature flag (`USE_PLANNER`) so the old path stays available
- The four decision answers I gave you during plan approval. Embed them in the relevant prompts so I don't have to re-derive.

## What not to do

- Do not write any code in this output. The deliverable is prompts, not implementation.
- Do not skip the success criteria sections. Vague verification means I cannot tell if a step finished.
- Do not let prompt bodies sprawl. Each prompt should be tight enough that I can read it in under two minutes.
- Do not include "and also tackle phase 2" anywhere. Phase 1 only.
- Do not collapse the registry compilation and the planner code into one prompt. They are separate concerns and benefit from separate verification.

## After producing the file

Print a one-paragraph summary listing the prompts by title and estimated time per prompt, so I can see the full sequence at a glance before opening the file.

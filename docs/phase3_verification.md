# Phase 3 verification — Apify Store discovery for unknown domains

Date: 2026-06-05
Branch: `phase3-prompt6` (merged to `main`)

This document is the proof that Pluck can now route hosts it has **never seen**.
Phase 1 routed only the four hardcoded registry domains; Phase 2 cached planner
decisions. Phase 3 adds a discovery fall-through: for an unknown host the planner
searches the Apify Store, ranks candidates with Haiku, captures the real output
schema with a one-row probe, caches the winner in a tier-2 SQLite table, and plans
against it — so the *second* request for that host skips discovery entirely.

---

## TL;DR

| | Phase 1/2 (`USE_PLANNER` on) | Phase 3 (`USE_PLANNER` on) |
|---|---|---|
| Registry host (instagram, linkedin, amazon) | intent-aware planned scrape | unchanged |
| **Unknown host, 1st request** | legacy classify → fetch → extract | **Store search → Haiku rank → maxItems=1 schema capture → tier-2 cache → planned scrape** |
| **Unknown host, repeat request** | legacy path again | served from tier-2 cache (no Store call, no re-discovery) |
| Discovery transparency | n/a | `discovery` SSE event with `source` + `confidence` |

---

## How it works

1. **Gate (`api/routes.py`).** `candidates_for_url` now unions tier 1 (hardcoded
   `apify_actors.json`) and tier 2 (discovered SQLite). If both are empty and
   `USE_PLANNER` is on, the discovery fall-through runs.
2. **Query (Decision 2).** `build_search_query(url)` — pure regex, no LLM: domain
   stem plus the first intent-bearing path segment (`linkedin jobs`), stem-only for
   bare handles (`instagram`).
3. **Search + filter.** `store_api.search_store` hits the public `/v2/store`
   endpoint (relevance, limit 10, no auth). `discovery_filter.filter_candidates`
   drops actors with `< 50` 30-day users or a last run older than 90 days.
4. **Rank (Haiku).** `discovery_planner.discover_actor` picks one actor and shapes a
   registry entry, reusing the planner's never-raise + retry-once discipline.
5. **Schema capture (Decision 1).** `capture_output_schema` runs the chosen actor
   once with `maxItems=1` (~$0.003, paid once and cached) to read the real column
   names; `apply_captured_schema` folds them into `default_columns`/`all_columns`.
6. **Cache (Decision 3).** `put_discovered` writes the entry to the `discovered_actors`
   table (30-day TTL, `source='discovered'`, `successful_runs` counter). On every
   successful scrape `increment_successful_runs` bumps the counter. No auto-promotion:
   `python -m pluck.registry.review_discovered` lists entries with
   `successful_runs >= 10` for a human to promote into the JSON registry by hand.
7. **Transparency (Decision 4).** A `discovery` SSE event fires with
   `{actor_id, reasoning, source: "discovered", confidence}` where confidence is
   `low` (0 runs), `medium` (1–9), or `high` (≥10).

---

## Test results

### Non-integration suite — green

```powershell
.venv\Scripts\python.exe -m pytest -q -m "not integration"
```

```
462 passed, 8 deselected
```

New Phase 3 unit tests:

| File | Tests | Covers |
|---|---|---|
| `test_store_api.py` | 7 | Store client + `build_search_query` (Decision 2) |
| `test_discovery_filter.py` | 4 | user/staleness thresholds |
| `test_discovery_planner.py` | 5 | Haiku ranking + maxItems=1 schema capture (Decision 1) |
| `test_discovered_cache.py` | 7 | tier-2 table, `successful_runs`, review filter (Decision 3) |
| `test_loader_union.py` | 3 | tier-1 + tier-2 union, tier-1 wins on conflict |
| `test_discovery_wiring.py` | 3 | fall-through, tier-2 reuse, no-result fallback (Decision 4) |

### Integration (live, deselected by default)

```powershell
.venv\Scripts\python.exe -m pytest tests/integration/test_discovery_e2e.py -v -m integration
```

`test_unknown_host_is_discovered_and_cached` drives a real unknown host
(`tiktok.com/@nasa`) end-to-end: asserts a `discovery` event with `source=discovered`,
a `done` event with items, and a tier-2 cache write with `successful_runs >= 1`.
Requires `ANTHROPIC_API_KEY` + `APIFY_TOKEN`; spends ~$0.003 on the schema probe plus
the scrape.

---

## Cost model

| Event | Cost | Frequency |
|---|---|---|
| Store search | free (public endpoint) | once per unknown host (then cached) |
| Haiku ranking | ~Haiku tokens for one call | once per unknown host |
| maxItems=1 schema probe | ~$0.003 | once per unknown host (cached 30 days) |
| Repeat request for a known host | $0 discovery | every subsequent request |

Discovery is paid once per host and amortised by the tier-2 cache.

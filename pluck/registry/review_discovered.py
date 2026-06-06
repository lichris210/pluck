"""Manual-promotion review CLI for discovered actors (Phase 3, Decision 3).

Run: ``python -m pluck.registry.review_discovered [--min-runs N]``

Read-only report of tier-2 discovered actors that have proven themselves
(``successful_runs >= N``, default 10), for a human to consider promoting into the
hardcoded ``apify_actors.json``. There is NO auto-promotion.
"""

from __future__ import annotations

import argparse

from pluck.storage.cache_store import SchemaCacheStore


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="pluck.registry.review_discovered",
        description="List discovered actors with enough successful runs for review.",
    )
    parser.add_argument(
        "--min-runs",
        type=int,
        default=10,
        metavar="N",
        help="Minimum successful_runs to include (default: 10)",
    )
    args = parser.parse_args()

    store = SchemaCacheStore()
    rows = store.get_discovered_for_review(min_runs=args.min_runs)
    store.close()

    if not rows:
        print(f"No discovered actors with successful_runs >= {args.min_runs}.")
        return

    print(f"Discovered actors with successful_runs >= {args.min_runs} (for manual review):\n")
    print(f"{'runs':>5}  {'source':<11}  {'domain':<28}  actor_id")
    print(f"{'-' * 5}  {'-' * 11}  {'-' * 28}  {'-' * 20}")
    for r in rows:
        print(
            f"{r['successful_runs']:>5}  {r['source']:<11}  "
            f"{r['domain_pattern']:<28}  {r['actor_id']}"
        )


if __name__ == "__main__":
    main()

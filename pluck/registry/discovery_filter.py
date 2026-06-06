"""Quality filter for raw Apify Store candidates (Phase 3, Prompt 2).

Drops actors that are too unpopular or stale to trust, before the (paid) Haiku
ranking step ever sees them. Pure function over the normalised dicts produced by
``store_api.search_store``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Tunable thresholds.
_DEFAULT_MIN_USERS_30D = 50
_DEFAULT_MAX_AGE_DAYS = 90


def _parse_dt(value) -> datetime | None:
    """Parse an ISO timestamp (tolerating a trailing 'Z'); None if unparseable."""
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def filter_candidates(
    items: list[dict],
    *,
    min_users_30d: int = _DEFAULT_MIN_USERS_30D,
    max_age_days: int = _DEFAULT_MAX_AGE_DAYS,
    now: datetime | None = None,
) -> list[dict]:
    """Return only candidates with enough recent users and a fresh last run.

    Conservative: an actor missing either stat is dropped. *now* is injectable for
    deterministic tests.
    """
    now = now or datetime.now(timezone.utc)
    kept: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue

        users = item.get("totalUsers30Days")
        if not isinstance(users, (int, float)) or users < min_users_30d:
            continue

        last_run = _parse_dt(item.get("lastRunStartedAt"))
        if last_run is None:
            continue
        age_days = (now - last_run).total_seconds() / 86400.0
        if age_days > max_age_days:
            continue

        kept.append(item)
    return kept

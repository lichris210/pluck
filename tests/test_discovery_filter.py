"""Tests for the Store candidate quality filter (Phase 3, Prompt 2)."""

from datetime import datetime, timedelta, timezone

from pluck.registry.discovery_filter import filter_candidates

NOW = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)


def _actor(users, days_ago):
    last_run = (NOW - timedelta(days=days_ago)).isoformat()
    return {"actor_id": "x/y", "totalUsers30Days": users, "lastRunStartedAt": last_run}


def test_drops_low_user_actor():
    items = [_actor(users=10, days_ago=1)]  # below default 50
    assert filter_candidates(items, now=NOW) == []


def test_drops_stale_last_run():
    items = [_actor(users=5000, days_ago=200)]  # popular but stale (> 90 days)
    assert filter_candidates(items, now=NOW) == []


def test_keeps_healthy_actor():
    items = [_actor(users=5000, days_ago=3)]
    kept = filter_candidates(items, now=NOW)
    assert len(kept) == 1
    assert kept[0]["actor_id"] == "x/y"


def test_missing_stats_dropped():
    items = [
        {"actor_id": "a", "lastRunStartedAt": NOW.isoformat()},          # no users
        {"actor_id": "b", "totalUsers30Days": 9999},                      # no last run
        {"actor_id": "c", "totalUsers30Days": 9999, "lastRunStartedAt": "garbage"},
    ]
    assert filter_candidates(items, now=NOW) == []

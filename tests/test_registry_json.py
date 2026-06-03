"""Tests for the hardcoded Apify actor registry JSON (pluck/registry/apify_actors.json).

These tests validate the data file's shape only — the loader module is a later
prompt. They run with no network and no APIFY_TOKEN.
"""

import json
from pathlib import Path

import pytest

REGISTRY_PATH = Path(__file__).resolve().parent.parent / "pluck" / "registry" / "apify_actors.json"

REQUIRED_KEYS = {
    "domain_patterns",
    "actor_id",
    "intent_description",
    "input_template",
    "input_notes",
    "row_unit",
    "default_columns",
    "all_columns",
    "is_default",
}


@pytest.fixture(scope="module")
def registry():
    with REGISTRY_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def test_registry_parses_and_has_four_entries(registry):
    assert isinstance(registry, list)
    assert len(registry) == 4


def test_every_entry_has_required_keys(registry):
    for entry in registry:
        assert REQUIRED_KEYS == set(entry.keys()), f"key mismatch in {entry.get('actor_id')!r}"


def test_exactly_one_default_per_domain(registry):
    # For each domain_pattern, at most one entry may be flagged is_default.
    defaults_by_domain: dict[str, int] = {}
    for entry in registry:
        if not entry["is_default"]:
            continue
        for domain in entry["domain_patterns"]:
            defaults_by_domain[domain] = defaults_by_domain.get(domain, 0) + 1

    for domain, count in defaults_by_domain.items():
        assert count <= 1, f"{domain} has {count} default entries"

    # instagram.com specifically must have exactly one default.
    assert defaults_by_domain.get("instagram.com") == 1


def test_default_columns_subset_of_all_columns(registry):
    for entry in registry:
        default = set(entry["default_columns"])
        allcols = set(entry["all_columns"])
        missing = default - allcols
        assert not missing, f"{entry['actor_id']!r} default_columns not in all_columns: {missing}"

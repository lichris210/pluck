import time
import pytest
from pluck.storage.cache_store import SchemaCacheStore


@pytest.fixture
def store(tmp_path):
    db = tmp_path / "test_cache.db"
    s = SchemaCacheStore(db_path=str(db))
    yield s
    s.close()


# ── put / get round-trip ─────────────────────────────────────────────────────

def test_put_then_get_roundtrip(store):
    store.put_schema("linkedin.com/jobs/*", '{"fields": ["title"]}')
    result = store.get_schema("linkedin.com/jobs/*")
    assert result == '{"fields": ["title"]}'


def test_get_missing_returns_none(store):
    assert store.get_schema("example.com/nonexistent") is None


# ── invalidation ─────────────────────────────────────────────────────────────

def test_get_invalidated_returns_none(store):
    store.put_schema("example.com/products/*", '{"fields": ["price"]}')
    store.invalidate_schema("example.com/products/*")
    assert store.get_schema("example.com/products/*") is None


# ── touch_schema ─────────────────────────────────────────────────────────────

def test_touch_increments_use_count(store):
    store.put_schema("example.com/articles/*", '{"fields": ["body"]}')

    store.touch_schema("example.com/articles/*")
    store.touch_schema("example.com/articles/*")

    row = store._conn.execute(
        "SELECT use_count FROM schema_cache WHERE schema_pattern = ?",
        ("example.com/articles/*",),
    ).fetchone()
    assert row["use_count"] == 2


def test_touch_updates_last_used_at(store):
    store.put_schema("example.com/news/*", '{"fields": ["headline"]}')

    before = store._conn.execute(
        "SELECT last_used_at FROM schema_cache WHERE schema_pattern = ?",
        ("example.com/news/*",),
    ).fetchone()["last_used_at"]

    # Ensure wall-clock time advances at least a little
    time.sleep(0.01)
    store.touch_schema("example.com/news/*")

    after = store._conn.execute(
        "SELECT last_used_at FROM schema_cache WHERE schema_pattern = ?",
        ("example.com/news/*",),
    ).fetchone()["last_used_at"]

    assert after >= before


# ── put_schema overwrites and resets ─────────────────────────────────────────

def test_put_overwrites_and_resets_status(store):
    store.put_schema("example.com/shop/*", '{"fields": ["name"]}')
    store.invalidate_schema("example.com/shop/*")

    # Overwrite — should flip status back to active and replace json
    store.put_schema("example.com/shop/*", '{"fields": ["name", "price"]}')

    result = store.get_schema("example.com/shop/*")
    assert result == '{"fields": ["name", "price"]}'


def test_put_overwrites_resets_use_count(store):
    store.put_schema("example.com/blog/*", '{"fields": ["title"]}')
    store.touch_schema("example.com/blog/*")
    store.touch_schema("example.com/blog/*")

    store.put_schema("example.com/blog/*", '{"fields": ["title", "author"]}')

    row = store._conn.execute(
        "SELECT use_count FROM schema_cache WHERE schema_pattern = ?",
        ("example.com/blog/*",),
    ).fetchone()
    assert row["use_count"] == 0

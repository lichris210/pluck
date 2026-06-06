"""Tests for the plan-cache admin clear endpoint (Phase 2, Prompt 3)."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.main import app
from pluck.storage.cache_store import SchemaCacheStore


@pytest.fixture
def temp_store(tmp_path):
    s = SchemaCacheStore(db_path=str(tmp_path / "plan_cache_admin.db"))
    yield s
    s.close()


@pytest.fixture
def client(temp_store):
    with patch("api.routes._schema_cache", temp_store):
        yield TestClient(app)


def _token(client) -> str:
    resp = client.post("/api/auth", json={"password": "pluck"})
    assert resp.status_code == 200
    return resp.json()["token"]


def test_clear_requires_auth(client):
    resp = client.post("/api/admin/plan-cache/clear")
    assert resp.status_code == 401


def test_clear_empties_plan_cache(client, temp_store):
    tok = _token(client)
    temp_store.put_plan("instagram.com|aaaa", '{"actor_id": "a"}')
    temp_store.put_plan("amazon.com|bbbb", '{"actor_id": "b"}')

    resp = client.post("/api/admin/plan-cache/clear", params={"token": tok})

    assert resp.status_code == 200
    assert resp.json() == {"cleared": 2}
    assert temp_store.get_plan("instagram.com|aaaa") is None
    assert temp_store.get_plan("amazon.com|bbbb") is None

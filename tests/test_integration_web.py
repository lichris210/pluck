"""
End-to-end web integration tests.

Run with:  pytest -m integration
Skipped by default (makes real network calls).
"""

import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.mark.integration
def test_auth_classify_hn(client):
    """Login → classify Hacker News → expect STATIC_HTML."""
    # 1. Authenticate
    auth_resp = client.post("/api/auth", json={"password": "pluck"})
    assert auth_resp.status_code == 200, auth_resp.text
    token = auth_resp.json()["token"]
    assert len(token) == 64

    # 2. Classify a known static site
    classify_resp = client.post(
        "/api/classify",
        json={"url": "https://news.ycombinator.com"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert classify_resp.status_code == 200, classify_resp.text

    data = classify_resp.json()
    assert data["site_group"] == "STATIC_HTML"
    assert data["site_group_number"] == 1
    assert data["error"] is None
    assert data["response_time_ms"] > 0
    assert "news.ycombinator.com" in data["final_url"]

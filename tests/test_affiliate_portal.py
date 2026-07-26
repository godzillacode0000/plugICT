from pathlib import Path

from fastapi.testclient import TestClient

import store.affiliate_portal as portal
from scripts.affiliate_ledger import AffiliateLedger


def test_portal_click_ingest_and_private_stats(tmp_path: Path):
    portal.DB_FILE = tmp_path / "affiliate.sqlite3"
    portal.CLICK_HASH_SALT = "test-only-salt"
    ledger = AffiliateLedger(portal.DB_FILE)
    ledger.initialize()
    ledger.add_affiliate("api_001", "API Test")
    token = ledger.issue_access_token("api_001")
    client = TestClient(portal.build_app())

    assert client.get("/health").json()["ok"] is True
    assert client.get("/api/affiliate/stats").status_code == 401
    assert client.post(
        "/api/affiliate/click",
        json={
            "code": "api_001",
            "click_id": "click-api-1",
            "visitor_id": "visitor-api-123",
            "path": "/",
            "referrer": "https://example.com",
        },
    ).status_code == 204
    assert client.post(
        "/api/affiliate/click",
        json={
            "code": "api_001",
            "click_id": "click-api-1",
            "visitor_id": "visitor-api-123",
        },
    ).status_code == 204

    response = client.get(
        "/api/affiliate/stats",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["affiliate"] == {"code": "api_001", "name": "API Test"}
    assert data["clicks"] == 1
    assert data["unique_clicks"] == 1
    assert "buyer_email" not in data
    assert "email" not in data

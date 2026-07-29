"""Isolated Stripe sandbox webhook acceptance and concurrency tests.

All secrets, Stripe objects, seller artefacts, and AgentMail calls are synthetic.
No test sends email or contacts Stripe/AgentMail.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sys
import threading
import time
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "store"))
sys.path.insert(0, str(ROOT / "scripts"))

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import issue_license  # noqa: E402
import webhook_server  # noqa: E402


SANDBOX_ENV_KEYS = (
    "PLUGICT_ENV",
    "WEBHOOK_SECRET",
    "STRIPE_EXPECTED_LIVEMODE",
    "STRIPE_PAYMENT_LINK_ID",
    "STRIPE_EXPECTED_AMOUNT",
    "STRIPE_EXPECTED_CURRENCY",
    "STRIPE_ALLOWED_BUYER_EMAILS",
    "PLUGICT_EMAIL_PROVIDER",
    "AGENTMAIL_API_KEY",
    "AGENTMAIL_INBOX",
    "ICT_SOURCE_DIR",
    "ICT_VERIFY_SOURCE_VAULT",
)


@pytest.fixture
def sandbox_env(monkeypatch, tmp_path):
    source = tmp_path / "seller-artifacts"
    source.mkdir()
    (source / ".vault_key").write_bytes(b"x" * 32)
    (source / ".vault_sha256").write_text("0" * 64, encoding="utf-8")
    (source / "ict-vault.kevin").write_bytes(b"synthetic-encrypted-vault")

    values = {
        "PLUGICT_ENV": "sandbox",
        "WEBHOOK_SECRET": "whsec_test_only_not_real",
        "STRIPE_EXPECTED_LIVEMODE": "false",
        "STRIPE_PAYMENT_LINK_ID": "plink_test_controlled",
        "STRIPE_EXPECTED_AMOUNT": "1899",
        "STRIPE_EXPECTED_CURRENCY": "usd",
        "STRIPE_ALLOWED_BUYER_EMAILS": "kevingenautry@gmail.com",
        "PLUGICT_EMAIL_PROVIDER": "agentmail",
        "AGENTMAIL_API_KEY": "agentmail_test_only_not_real",
        "AGENTMAIL_INBOX": "sandbox-test@agentmail.invalid",
        "ICT_SOURCE_DIR": str(source),
        "ICT_VERIFY_SOURCE_VAULT": "false",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    return values


@pytest.fixture(autouse=True)
def clean_sandbox_environment(monkeypatch):
    for key in SANDBOX_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def valid_event(**session_overrides):
    session = {
        "id": "cs_test_controlled_001",
        "livemode": False,
        "status": "complete",
        "payment_status": "paid",
        "payment_link": "plink_test_controlled",
        "amount_total": 1899,
        "currency": "usd",
        "customer_details": {"email": "kevingenautry@gmail.com"},
    }
    session.update(session_overrides)
    return {
        "id": "evt_test_controlled_001",
        "livemode": False,
        "type": "checkout.session.completed",
        "data": {"object": session},
    }


def signed_post(client, payload, provider="stripe"):
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    timestamp = "1700000000"
    digest = hmac.new(
        b"whsec_test_only_not_real",
        timestamp.encode("ascii") + b"." + raw,
        hashlib.sha256,
    ).hexdigest()
    return client.post(
        f"/webhook/{provider}",
        content=raw,
        headers={
            "content-type": "application/json",
            "Stripe-Signature": f"t={timestamp},v1={digest}",
        },
    )


@pytest.mark.parametrize("missing", SANDBOX_ENV_KEYS[1:])
def test_sandbox_startup_fails_closed_when_required_env_is_missing(sandbox_env, monkeypatch, missing):
    monkeypatch.delenv(missing)
    with pytest.raises(RuntimeError, match=missing):
        webhook_server._build_app()


@pytest.mark.parametrize(
    ("name", "bad_value"),
    [
        ("STRIPE_EXPECTED_LIVEMODE", "true"),
        ("STRIPE_EXPECTED_LIVEMODE", "FALSE"),
        ("STRIPE_EXPECTED_AMOUNT", "1900"),
        ("STRIPE_EXPECTED_CURRENCY", "eur"),
        ("STRIPE_EXPECTED_CURRENCY", "USD"),
        ("STRIPE_PAYMENT_LINK_ID", "not-a-payment-link"),
        ("STRIPE_ALLOWED_BUYER_EMAILS", "someone-else@example.com"),
        ("PLUGICT_EMAIL_PROVIDER", "smtp"),
        ("PLUGICT_EMAIL_PROVIDER", "AgentMail"),
    ],
)
def test_sandbox_startup_rejects_non_controlled_configuration(sandbox_env, monkeypatch, name, bad_value):
    monkeypatch.setenv(name, bad_value)
    with pytest.raises(RuntimeError, match=name):
        webhook_server._build_app()


@pytest.mark.parametrize("artifact", [".vault_key", ".vault_sha256"])
def test_sandbox_startup_requires_seller_artifacts_from_ict_source_dir(sandbox_env, artifact):
    (Path(sandbox_env["ICT_SOURCE_DIR"]) / artifact).unlink()
    with pytest.raises(RuntimeError, match=artifact):
        webhook_server._build_app()


def test_non_sandbox_local_mode_remains_backward_compatible():
    assert webhook_server._build_app() is not None


def test_sandbox_health_is_safe_and_minimal(sandbox_env):
    response = TestClient(webhook_server._build_app()).get("/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


@pytest.mark.parametrize(
    ("event_change", "session_change", "reason"),
    [
        ({"livemode": True}, {}, "event_livemode_mismatch"),
        ({}, {"livemode": True}, "livemode_mismatch"),
        ({}, {"payment_link": "plink_wrong"}, "payment_link_mismatch"),
        ({}, {"amount_total": 1800}, "amount_mismatch"),
        ({}, {"currency": "eur"}, "currency_mismatch"),
        ({}, {"customer_details": {"email": "other@example.com"}}, "buyer_not_allowed"),
        ({}, {"status": "open"}, "checkout_not_complete"),
        ({}, {"payment_status": "unpaid"}, "payment_not_paid"),
    ],
)
def test_sandbox_rejects_mismatched_stripe_checkout(
    sandbox_env, event_change, session_change, reason
):
    payload = valid_event(**session_change)
    payload.update(event_change)
    client = TestClient(webhook_server._build_app())

    with mock.patch.object(issue_license, "issue") as issue:
        response = signed_post(client, payload)

    assert response.status_code == 200
    assert response.json() == {"status": "ignored", "reason": reason}
    issue.assert_not_called()


def test_sandbox_rejects_wrong_event_type(sandbox_env):
    payload = valid_event()
    payload["type"] = "payment_intent.succeeded"
    client = TestClient(webhook_server._build_app())

    with mock.patch.object(issue_license, "issue") as issue:
        response = signed_post(client, payload)

    assert response.status_code == 200
    assert response.json() == {"status": "ignored", "reason": "event_type_mismatch"}
    issue.assert_not_called()


def test_sandbox_accepts_only_stripe_provider(sandbox_env):
    client = TestClient(webhook_server._build_app())
    with mock.patch.object(issue_license, "issue") as issue:
        response = signed_post(client, valid_event(), provider="gumroad")
    assert response.status_code == 404
    issue.assert_not_called()


def test_sandbox_successfully_calls_mocked_issuance(sandbox_env):
    client = TestClient(webhook_server._build_app())
    with mock.patch.object(issue_license, "find_issued", return_value=None), mock.patch.object(
        issue_license, "issue"
    ) as issue:
        response = signed_post(client, valid_event())

    assert response.status_code == 200
    assert response.json() == {"status": "issued"}
    issue.assert_called_once_with(
        "kevingenautry@gmail.com",
        "cs_test_controlled_001",
        email_it=True,
        method="stripe",
    )


def test_sandbox_sequential_duplicate_is_suppressed(sandbox_env):
    fulfilled = set()

    def find_issued(order_id):
        return {"order_id": order_id} if order_id in fulfilled else None

    def issue(_email, order_id, **_kwargs):
        fulfilled.add(order_id)

    client = TestClient(webhook_server._build_app())
    with mock.patch.object(issue_license, "find_issued", side_effect=find_issued), mock.patch.object(
        issue_license, "issue", side_effect=issue
    ) as issue_mock:
        first = signed_post(client, valid_event())
        second = signed_post(client, valid_event())

    assert first.json() == {"status": "issued"}
    assert second.json() == {"status": "duplicate", "order_id": "cs_test_controlled_001"}
    assert issue_mock.call_count == 1


def test_sandbox_concurrent_duplicate_is_suppressed_on_one_instance(sandbox_env):
    fulfilled = set()
    state_lock = threading.Lock()
    start = threading.Barrier(3)
    results = []
    errors = []

    def find_issued(order_id):
        with state_lock:
            return {"order_id": order_id} if order_id in fulfilled else None

    def issue(_email, order_id, **_kwargs):
        time.sleep(0.1)  # Hold the fulfilment critical section while the peer arrives.
        with state_lock:
            fulfilled.add(order_id)

    app = webhook_server._build_app()

    def worker():
        try:
            start.wait(timeout=2)
            response = signed_post(TestClient(app), valid_event())
            results.append(response.json())
        except Exception as exc:  # pragma: no cover - surfaced by assertion below
            errors.append(exc)

    with mock.patch.object(issue_license, "find_issued", side_effect=find_issued), mock.patch.object(
        issue_license, "issue", side_effect=issue
    ) as issue_mock:
        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        start.wait(timeout=2)
        for thread in threads:
            thread.join(timeout=3)

    assert not errors
    assert all(not thread.is_alive() for thread in threads)
    assert sorted(item["status"] for item in results) == ["duplicate", "issued"]
    assert issue_mock.call_count == 1


def test_issued_paths_are_environment_configurable_with_legacy_defaults(tmp_path):
    default_issued, default_ledger = issue_license.resolve_issued_paths({})
    assert default_issued == issue_license.STORE_DIR / "issued"
    assert default_ledger == issue_license.STORE_DIR / "issued_licenses.csv"

    issued, ledger = issue_license.resolve_issued_paths(
        {
            "ICT_ISSUED_DIR": str(tmp_path / "issued"),
            "ICT_ISSUED_LEDGER": str(tmp_path / "ledger" / "issued.csv"),
        }
    )
    assert issued == tmp_path / "issued"
    assert ledger == tmp_path / "ledger" / "issued.csv"

from pathlib import Path

import pytest

from scripts.affiliate_ledger import AffiliateLedger, process_session


def make_ledger(tmp_path: Path) -> AffiliateLedger:
    ledger = AffiliateLedger(tmp_path / "affiliate.sqlite3")
    ledger.initialize()
    return ledger


def test_affiliate_registry_and_idempotent_sale(tmp_path):
    ledger = make_ledger(tmp_path)
    ledger.add_affiliate("amir_001", "Amir", contact="@amir")

    session = {
        "id": "cs_test_001",
        "status": "complete",
        "payment_status": "paid",
        "payment_link": "plink_plugict",
        "client_reference_id": "amir_001",
        "amount_total": 1899,
        "currency": "usd",
        "created": 1760000000,
        "customer_details": {"email": "amir@example.com"},
        "payment_intent": "pi_test_001",
    }

    result = process_session(
        ledger,
        session,
        expected_payment_link="plink_plugict",
        payment_state={"refunded": False, "disputed": False},
    )
    duplicate = process_session(
        ledger,
        session,
        expected_payment_link="plink_plugict",
        payment_state={"refunded": False, "disputed": False},
    )

    assert result == {"event": "sale", "code": "amir_001", "commission_cents": 500}
    assert duplicate is None
    assert ledger.pending_summary() == [
        {"code": "amir_001", "name": "Amir", "sales": 1, "commission_cents": 500}
    ]

    sale = ledger.get_sale("cs_test_001")
    assert sale["buyer_email_masked"] == "a***@example.com"
    assert sale["payout_status"] == "pending"


def test_unpaid_wrong_product_unknown_and_disqualified_sessions_are_not_credited(tmp_path):
    ledger = make_ledger(tmp_path)
    ledger.add_affiliate("valid_001", "Valid")

    base = {
        "id": "cs_test_002",
        "status": "complete",
        "payment_status": "paid",
        "payment_link": "plink_plugict",
        "client_reference_id": "valid_001",
        "amount_total": 1899,
        "currency": "usd",
        "created": 1760000000,
        "customer_details": {},
        "payment_intent": "pi_test_002",
    }

    unpaid = dict(base, id="cs_unpaid", payment_status="unpaid")
    wrong_product = dict(base, id="cs_wrong", payment_link="plink_other")
    unknown = dict(base, id="cs_unknown", client_reference_id="not_registered")
    refunded = dict(base, id="cs_refunded")

    assert process_session(ledger, unpaid, expected_payment_link="plink_plugict", payment_state={}) is None
    assert process_session(ledger, wrong_product, expected_payment_link="plink_plugict", payment_state={}) == {"event": "ignored_wrong_product", "code": "valid_001"}
    assert process_session(ledger, unknown, expected_payment_link="plink_plugict", payment_state={}) == {"event": "unknown_affiliate", "code": "not_registered"}
    assert process_session(ledger, refunded, expected_payment_link="plink_plugict", payment_state={"refunded": True, "disputed": False}) == {"event": "disqualified", "code": "valid_001", "reason": "refunded"}
    assert ledger.pending_summary() == []


def test_manual_payout_lifecycle(tmp_path):
    ledger = make_ledger(tmp_path)
    ledger.add_affiliate("sarah_001", "Sarah", payout_method="bank")
    session = {
        "id": "cs_test_003",
        "status": "complete",
        "payment_status": "paid",
        "payment_link": "plink_plugict",
        "client_reference_id": "sarah_001",
        "amount_total": 1899,
        "currency": "usd",
        "created": 1760000000,
        "customer_details": {},
        "payment_intent": "pi_test_003",
    }
    process_session(ledger, session, expected_payment_link="plink_plugict", payment_state={})

    payout_id = ledger.create_payout("sarah_001", note="September batch")
    assert ledger.get_payout(payout_id)["status"] == "pending"
    assert ledger.pending_summary() == []

    ledger.mark_payout_paid(payout_id, reference="bank-ref-001")
    payout = ledger.get_payout(payout_id)
    assert payout["status"] == "paid"
    assert payout["reference"] == "bank-ref-001"
    assert ledger.get_sale("cs_test_003")["payout_status"] == "paid"


def test_later_refund_voids_pending_commission(tmp_path):
    ledger = make_ledger(tmp_path)
    ledger.add_affiliate("refund_001", "Refund Test")
    session = {
        "id": "cs_test_refund",
        "status": "complete",
        "payment_status": "paid",
        "payment_link": "plink_plugict",
        "client_reference_id": "refund_001",
        "amount_total": 1899,
        "currency": "usd",
        "created": 1760000000,
        "customer_details": {},
        "payment_intent": "pi_test_refund",
    }
    assert process_session(ledger, session, expected_payment_link="plink_plugict", payment_state={})["event"] == "sale"

    result = process_session(
        ledger,
        session,
        expected_payment_link="plink_plugict",
        payment_state={"refunded": True, "disputed": False},
    )
    assert result == {
        "event": "disqualified_after_credit",
        "code": "refund_001",
        "reason": "refunded",
        "payout_status": "void",
    }
    assert ledger.pending_summary() == []


def test_duplicate_affiliate_codes_are_rejected(tmp_path):
    ledger = make_ledger(tmp_path)
    ledger.add_affiliate("same_code", "First")
    with pytest.raises(ValueError, match="already exists"):
        ledger.add_affiliate("same_code", "Second")


def test_clicks_tokens_and_aggregate_stats_are_private(tmp_path):
    ledger = make_ledger(tmp_path)
    ledger.add_affiliate("dash_001", "Dashboard Test")
    token = ledger.issue_access_token("dash_001")

    assert ledger.authenticate_access_token(token)["code"] == "dash_001"
    assert ledger.authenticate_access_token("wrong-token") is None
    assert ledger.record_click(
        affiliate_code="dash_001", click_id="click-1", visitor_hash="visitor-a", landing_path="/"
    ) is True
    assert ledger.record_click(
        affiliate_code="dash_001", click_id="click-1", visitor_hash="visitor-a", landing_path="/"
    ) is False
    assert ledger.record_click(
        affiliate_code="dash_001", click_id="click-2", visitor_hash="visitor-b", landing_path="/affiliate"
    ) is True

    session = {
        "id": "cs_dashboard_001",
        "status": "complete",
        "payment_status": "paid",
        "payment_link": "plink_plugict",
        "client_reference_id": "dash_001",
        "amount_total": 1899,
        "currency": "usd",
        "created": 1760000000,
        "customer_details": {"email": "buyer@example.com"},
    }
    process_session(ledger, session, expected_payment_link="plink_plugict", payment_state={})
    stats = ledger.affiliate_stats("dash_001")

    assert stats["clicks"] == 2
    assert stats["unique_clicks"] == 2
    assert stats["purchases"] == 1
    assert stats["conversion_rate"] == 50.0
    assert stats["pending_commission_cents"] == 500
    assert "buyer" not in str(stats).lower()
    assert "email" not in stats

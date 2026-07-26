from scripts.check_affiliate_sales import format_event, payment_state


def test_monitor_output_is_redacted_and_payout_ready():
    session = {
        "id": "cs_test_100",
        "amount_total": 1899,
        "currency": "usd",
        "customer_details": {"email": "buyer@example.com"},
    }
    output = format_event(
        {"event": "sale", "code": "amir_001", "commission_cents": 500},
        session,
    )
    assert output == "AFFILIATE_SALE|amir_001|18.99 USD|5.00 USD|cs_test_100"
    assert "buyer@example.com" not in output


def test_payment_state_detects_refund_and_dispute_from_expanded_charge():
    session = {
        "payment_intent": {
            "latest_charge": {
                "refunded": False,
                "amount_refunded": 100,
                "disputed": True,
            }
        }
    }
    assert payment_state(session) == {"refunded": True, "disputed": True}

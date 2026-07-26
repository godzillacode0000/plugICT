#!/usr/bin/env python3
"""Read-only Stripe reconciliation for PlugICT affiliate commissions.

The monitor never calls a Stripe write endpoint. It records durable state in
SQLite and emits only redacted operational events for Telegram/cron delivery.

Required environment:
  STRIPE_API_KEY=sk_live_...       restricted read-only Stripe key
  STRIPE_PAYMENT_LINK_ID=plink_... exact PlugICT live Payment Link ID

Optional environment:
  AFFILIATE_DB=store/affiliate_ledger.sqlite3
  AFFILIATE_LOOKBACK=3600
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

try:
    from scripts.affiliate_ledger import AffiliateLedger, process_session
except ModuleNotFoundError:  # direct `python scripts/check_affiliate_sales.py`
    from affiliate_ledger import AffiliateLedger, process_session

STRIPE_API_KEY = os.environ.get("STRIPE_API_KEY", "").strip()
EXPECTED_PAYMENT_LINK = os.environ.get("STRIPE_PAYMENT_LINK_ID", "").strip()
DB_FILE = Path(os.environ.get("AFFILIATE_DB", "store/affiliate_ledger.sqlite3"))
LOOKBACK = int(os.environ.get("AFFILIATE_LOOKBACK", "3600"))
STRIPE_API = "https://api.stripe.com/v1"


def stripe_get(path: str, params: list[tuple[str, str]] | None = None) -> dict:
    url = f"{STRIPE_API}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"
    req = Request(url, headers={
        "Authorization": f"Bearer {STRIPE_API_KEY}",
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "PlugICT-affiliate-monitor/1.0",
    })
    try:
        with urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError) as exc:
        print(f"ERROR: Stripe read failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def payment_state(session: dict) -> dict[str, bool]:
    """Read refund/dispute state from the expanded PaymentIntent/Charge."""
    intent = session.get("payment_intent")
    if not isinstance(intent, dict) and intent:
        intent = stripe_get(
            f"/payment_intents/{intent}",
            [("expand[]", "latest_charge")],
        )
    intent = intent if isinstance(intent, dict) else {}
    charge = intent.get("latest_charge")
    charge = charge if isinstance(charge, dict) else {}
    return {
        "refunded": bool(charge.get("refunded") or int(charge.get("amount_refunded") or 0) > 0),
        "disputed": bool(charge.get("disputed")),
    }


def fetch_sessions(cutoff: int):
    has_more = True
    starting_after = ""
    while has_more:
        params = [
            ("limit", "100"),
            ("created[gte]", str(cutoff)),
            ("expand[]", "data.customer_details"),
            ("expand[]", "data.payment_intent.latest_charge"),
        ]
        if starting_after:
            params.append(("starting_after", starting_after))
        data = stripe_get("/checkout/sessions", params)
        sessions = data.get("data") or []
        yield from sessions
        has_more = bool(data.get("has_more"))
        if sessions:
            starting_after = sessions[-1].get("id", "")
        else:
            has_more = False


def format_event(event: dict, session: dict) -> str | None:
    sid = session.get("id", "")
    code = event.get("code", "")
    if event["event"] == "sale":
        amount = int(session.get("amount_total") or 0) / 100
        currency = (session.get("currency") or "usd").upper()
        commission = int(event["commission_cents"]) / 100
        return f"AFFILIATE_SALE|{code}|{amount:.2f} {currency}|{commission:.2f} USD|{sid}"
    if event["event"] == "unknown_affiliate":
        return f"AFFILIATE_UNKNOWN|{code}|{sid}"
    if event["event"] in {"disqualified", "disqualified_after_credit"}:
        return f"AFFILIATE_DISQUALIFIED|{code}|{event['reason']}|{event.get('payout_status', 'void')}|{sid}"
    if event["event"] == "ignored_wrong_product":
        return f"AFFILIATE_IGNORED_PRODUCT|{code}|{sid}"
    return None


def main() -> int:
    if not STRIPE_API_KEY:
        print("ERROR: STRIPE_API_KEY not set", file=sys.stderr)
        return 1
    if not EXPECTED_PAYMENT_LINK:
        print("ERROR: STRIPE_PAYMENT_LINK_ID not set; refusing to credit unverified products", file=sys.stderr)
        return 1

    ledger = AffiliateLedger(DB_FILE)
    ledger.initialize()
    cutoff = int(time.time()) - LOOKBACK
    for session in fetch_sessions(cutoff):
        if not (session.get("client_reference_id") or "").strip():
            continue
        if session.get("status") != "complete" or session.get("payment_status") != "paid":
            continue
        state = payment_state(session)
        event = process_session(
            ledger,
            session,
            expected_payment_link=EXPECTED_PAYMENT_LINK,
            payment_state=state,
        )
        if event:
            output = format_event(event, session)
            if output:
                print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

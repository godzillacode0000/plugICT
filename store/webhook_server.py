# LEGACY — no longer in production use.
"""
webhook_server.py — Automated license delivery on purchase
==========================================================
The scale-up path for the delivery flow: your payment processor calls this
endpoint on every sale; it issues the buyer's license.key and emails it.

Until you wire this up, `issue_license.py` (run manually per sale) does the same
job with zero infrastructure — start there, graduate to this when volume grows.

Supported processors (payload shapes differ; parse_event handles each):
  * Billplz         (form-encoded callback — Malaysia FPX / DuitNow)
  * Stripe          (JSON checkout.session.completed — international cards)
  * Lemon Squeezy   (JSON 'order_created' webhook)
  * Gumroad         (form-encoded 'sale' ping)

DuitNow QR (static/bank) and USDT (direct wallet) have no webhook — confirm the
payment, then issue manually with issue_license.py --method duitnow|usdt.

Run:
  pip install fastapi uvicorn
  ICT_SOURCE_DIR=/path/to/seller/secrets \
  WEBHOOK_SECRET=[REDACTED] \
  PLUGICT_EMAIL_PROVIDER=agentmail \
  AGENTMAIL_API_KEY=[REDACTED] AGENTMAIL_INBOX=orders-test@agentmail.to \
  AGENTMAIL_REPLY_TO=support@plugict.com \
  uvicorn store.webhook_server:app --host 0.0.0.0 --port 8000

Security notes are in store/README.md — verify signatures, never expose
.vault_key, run behind HTTPS.
"""

import os
import sys
import json
import time
import hmac
import hashlib
import logging
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue_license  # noqa: E402

logger = logging.getLogger(__name__)

SANDBOX_CONTROLLED_BUYER_EMAIL = "kevingenautry@gmail.com"
_FULFILMENT_LOCK = threading.Lock()


def _required_sandbox_value(environ, name):
    value = (environ.get(name) or "").strip()
    if not value:
        raise RuntimeError(f"{name} is required when PLUGICT_ENV=sandbox")
    return value


def _sandbox_config(environ=None):
    """Validate and return the isolated public-sandbox configuration.

    Outside explicit ``PLUGICT_ENV=sandbox`` this returns None and leaves the
    legacy/dev behaviour unchanged.
    """
    env = os.environ if environ is None else environ
    if (env.get("PLUGICT_ENV") or "").strip().lower() != "sandbox":
        return None

    required = (
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
    values = {name: _required_sandbox_value(env, name) for name in required}

    exact = {
        "STRIPE_EXPECTED_LIVEMODE": "false",
        "STRIPE_EXPECTED_AMOUNT": "1899",
        "STRIPE_EXPECTED_CURRENCY": "usd",
        "PLUGICT_EMAIL_PROVIDER": "agentmail",
        "ICT_VERIFY_SOURCE_VAULT": "false",
    }
    for name, expected in exact.items():
        if values[name] != expected:
            raise RuntimeError(
                f"{name} must be {expected!r} when PLUGICT_ENV=sandbox"
            )
    if not values["STRIPE_PAYMENT_LINK_ID"].startswith("plink_"):
        raise RuntimeError(
            "STRIPE_PAYMENT_LINK_ID must be a Stripe Payment Link ID when PLUGICT_ENV=sandbox"
        )

    allowed_buyers = {
        item.strip().lower()
        for item in values["STRIPE_ALLOWED_BUYER_EMAILS"].split(",")
        if item.strip()
    }
    if SANDBOX_CONTROLLED_BUYER_EMAIL not in allowed_buyers:
        raise RuntimeError(
            "STRIPE_ALLOWED_BUYER_EMAILS must contain the controlled sandbox buyer"
        )

    source_dir = Path(values["ICT_SOURCE_DIR"])
    for artifact in (".vault_key", ".vault_sha256"):
        if not (source_dir / artifact).is_file():
            raise RuntimeError(
                f"ICT_SOURCE_DIR is missing required seller artifact {artifact}"
            )
    if len((source_dir / ".vault_key").read_bytes()) != 32:
        raise RuntimeError("ICT_SOURCE_DIR .vault_key must be exactly 32 bytes")
    vault_hash = (source_dir / ".vault_sha256").read_text(encoding="utf-8").strip().lower()
    if len(vault_hash) != 64 or any(c not in "0123456789abcdef" for c in vault_hash):
        raise RuntimeError("ICT_SOURCE_DIR .vault_sha256 must contain one SHA-256 digest")

    # Explicitly bind sandbox issuance to ICT_SOURCE_DIR, even if a parent
    # process inherited ICT_BUILD_DIR or imported issue_license earlier.
    issue_license.SOURCE_DIR = source_dir
    return {
        "allowed_buyers": allowed_buyers,
        "expected_livemode": False,
        "expected_link": values["STRIPE_PAYMENT_LINK_ID"],
        "expected_amount": 1899,
        "expected_currency": "usd",
    }


def parse_event(provider, payload):
    """Extract (email, order_id) from a processor payload. Pure + unit-tested.

    `payload` is a dict (already-parsed JSON, or form fields as a dict).
    Returns (email, order_id) or (None, None) if this event isn't a completed
    sale we should fulfil.
    """
    provider = (provider or "").lower()

    if provider == "billplz":
        # Billplz posts form fields; a paid bill has paid=true / state=paid.
        paid = str(payload.get("paid", "false")).lower() == "true" or payload.get("state") == "paid"
        if not paid:
            return None, None
        return payload.get("email"), payload.get("transaction_id") or payload.get("id")

    if provider == "gumroad":
        # Gumroad posts form fields; a refund/dispute ping sets these flags.
        if str(payload.get("refunded", "false")).lower() == "true":
            return None, None
        return payload.get("email"), payload.get("sale_id") or payload.get("order_number")

    if provider == "lemonsqueezy":
        if payload.get("meta", {}).get("event_name") != "order_created":
            return None, None
        attrs = payload.get("data", {}).get("attributes", {})
        return attrs.get("user_email"), str(payload.get("data", {}).get("id", "")) or attrs.get("identifier")

    if provider == "stripe":
        if payload.get("type") != "checkout.session.completed":
            return None, None
        obj = payload.get("data", {}).get("object", {})
        email = (obj.get("customer_details") or {}).get("email") or obj.get("customer_email")
        return email, obj.get("id")

    return None, None


def validate_stripe_checkout(obj, payload=None, sandbox_config=None):
    """Return (True, None) only for an explicitly accepted Stripe Session."""
    if obj.get("status") != "complete":
        return False, "checkout_not_complete"
    if obj.get("payment_status") != "paid":
        return False, "payment_not_paid"

    if sandbox_config is not None:
        if not isinstance(payload, dict) or payload.get("livemode") is not False:
            return False, "event_livemode_mismatch"
        if obj.get("livemode") is not False:
            return False, "livemode_mismatch"
        if obj.get("payment_link") != sandbox_config["expected_link"]:
            return False, "payment_link_mismatch"
        if obj.get("amount_total") != sandbox_config["expected_amount"]:
            return False, "amount_mismatch"
        if obj.get("currency") != sandbox_config["expected_currency"]:
            return False, "currency_mismatch"
        email = ((obj.get("customer_details") or {}).get("email")
                 or obj.get("customer_email") or "").strip().lower()
        if email not in sandbox_config["allowed_buyers"]:
            return False, "buyer_not_allowed"
        if not str(obj.get("id") or "").strip():
            return False, "session_id_missing"
        return True, None

    # Legacy optional checks remain unchanged outside explicit sandbox mode.
    expected_livemode = os.environ.get("STRIPE_EXPECTED_LIVEMODE", "").strip().lower()
    if expected_livemode in ("true", "false"):
        if bool(obj.get("livemode")) != (expected_livemode == "true"):
            return False, "livemode_mismatch"

    expected_link = os.environ.get("STRIPE_PAYMENT_LINK_ID", "").strip()
    if expected_link and obj.get("payment_link") != expected_link:
        return False, "payment_link_mismatch"

    expected_amount = os.environ.get("STRIPE_EXPECTED_AMOUNT", "").strip()
    if expected_amount:
        try:
            if int(obj.get("amount_total")) != int(expected_amount):
                return False, "amount_mismatch"
        except (TypeError, ValueError):
            return False, "amount_mismatch"

    expected_currency = os.environ.get("STRIPE_EXPECTED_CURRENCY", "").strip().lower()
    if expected_currency and str(obj.get("currency", "")).lower() != expected_currency:
        return False, "currency_mismatch"

    return True, None


def _fulfil_once(email, order_id, provider):
    """Atomically duplicate-check and issue within this Python process.

    This dependency-free lock suppresses concurrent delivery on one running
    instance. It is not crash/restart or multi-instance durable: a crash after
    send but before ledger append can still redeliver on a later request.
    """
    with _FULFILMENT_LOCK:
        if order_id and issue_license.find_issued(order_id):
            return {"status": "duplicate", "order_id": order_id}
        issue_license.issue(email, order_id, email_it=True, method=provider.lower())
        return {"status": "issued"}


def billplz_source_string(payload):
    """Billplz signs the sorted 'key+value' pairs (excluding x_signature)."""
    parts = [f"{k}{v}" for k, v in payload.items() if k != "x_signature"]
    parts.sort()
    return "|".join(parts)


def verify_billplz(secret, payload):
    """Verify a Billplz callback's x_signature (HMAC-SHA256 over sorted fields)."""
    if not secret:
        return True  # dev mode
    expected = hmac.new(secret.encode(), billplz_source_string(payload).encode(),
                        hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, str(payload.get("x_signature", "")))


def _sig_pairs(header_sig):
    """Yield (key, value) pairs from a 't=..,v1=..,v1=..' signature header.

    A bare hex string (no '=', as LemonSqueezy/Gumroad send) yields a single
    ('v1', hex) pair so those providers flow through the same parser.
    """
    if "=" not in header_sig:
        yield "v1", header_sig
        return
    for part in header_sig.split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            yield k.strip(), v.strip()


def verify_stripe(secret, raw_body, header_sig, tolerance=0):
    """Verify a Stripe webhook signature.

    Stripe signs `HMAC-SHA256(secret, f"{t}.{body}")` and sends
    `Stripe-Signature: t=<unix>,v1=<hexdigest>[,v1=<older>]`. The signed payload
    is the timestamp, a literal dot, then the raw body — reconstructing that is
    the fix: the previous code hashed the body alone, so every real Stripe
    webhook failed verification (401) once WEBHOOK_SECRET was set.

    `tolerance` (seconds) optionally rejects timestamps too far from now to blunt
    replay attacks; 0 disables it. Idempotency on order_id is the real replay
    guard, so this defaults off to avoid clock-skew false rejects on a fresh host.
    A header may carry several v1 values during secret rotation — any match wins.
    """
    if not secret:
        return True  # dev mode; configure WEBHOOK_SECRET in production
    if not header_sig:
        return False
    pairs = list(_sig_pairs(header_sig))
    t = next((v for k, v in pairs if k == "t"), None)
    if not t:
        return False
    if tolerance:
        try:
            if abs(time.time() - int(t)) > tolerance:
                return False
        except (TypeError, ValueError):
            return False
    signed = t.encode() + b"." + raw_body
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, v) for k, v in pairs if k == "v1")


def verify_signature(provider, secret, raw_body, header_sig):
    """Best-effort HMAC check. Returns True if valid or if no secret configured."""
    if not secret:
        return True  # dev mode; configure WEBHOOK_SECRET in production
    if not header_sig:
        return False
    provider = (provider or "").lower()
    if provider == "stripe":
        tol = int(os.environ.get("STRIPE_SIG_TOLERANCE", "0") or 0)
        return verify_stripe(secret, raw_body, header_sig, tolerance=tol)
    if provider in ("lemonsqueezy", "gumroad"):
        # These sign the raw body directly; header is a bare hex HMAC.
        digest = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(digest, header_sig)
    return False


# ── FastAPI app (imported lazily so the module unit-tests without fastapi) ────
def _build_app():
    from fastapi import FastAPI, Request, HTTPException

    app = FastAPI(title="ICT Vault license webhook")
    sandbox_config = _sandbox_config()
    secret = os.environ.get("WEBHOOK_SECRET", "")

    # B1 — production guard: on a real deploy, refuse to run signature-less.
    # With no secret, verify_* returns True for ANY request, so anyone could POST
    # a forged sale and mint a free license. Render sets $RENDER; treat any
    # recognised deploy env as production.
    is_prod = any(os.environ.get(v) for v in ("RENDER", "FLY_APP_NAME", "DYNO", "K_SERVICE"))
    if is_prod and not secret:
        raise RuntimeError(
            "WEBHOOK_SECRET is not set in a production environment. Refusing to "
            "start: without it the webhook accepts forged events and mints free "
            "licenses. Set WEBHOOK_SECRET (the whsec_… from your Stripe webhook).")

    @app.get("/health")
    async def health():
        return {"ok": True}

    @app.post("/webhook/{provider}")
    async def webhook(provider: str, request: Request):
        provider = provider.lower()
        if sandbox_config is not None and provider != "stripe":
            raise HTTPException(status_code=404, detail="provider not enabled")

        raw = await request.body()
        ctype = request.headers.get("content-type", "")
        # B2 — a malformed body is the caller's fault: return 400 (permanent) so
        # the processor stops retrying, instead of a 500 it hammers for days.
        try:
            if "application/json" in ctype:
                payload = json.loads(raw or b"{}")
            else:
                payload = dict(await request.form())
        except (ValueError, json.JSONDecodeError):
            raise HTTPException(status_code=400, detail="unparseable body")

        # Billplz signs its payload fields; everyone else signs the raw body.
        if provider == "billplz":
            ok = verify_billplz(secret, payload)
        else:
            sig = (request.headers.get("X-Signature")
                   or request.headers.get("Stripe-Signature")
                   or request.headers.get("X-Gumroad-Signature"))
            ok = verify_signature(provider, secret, raw, sig)
        if not ok:
            raise HTTPException(status_code=401, detail="bad signature")

        if provider == "stripe":
            if sandbox_config is not None and payload.get("type") != "checkout.session.completed":
                return {"status": "ignored", "reason": "event_type_mismatch"}
            stripe_obj = payload.get("data", {}).get("object", {})
            valid, reason = validate_stripe_checkout(
                stripe_obj, payload=payload, sandbox_config=sandbox_config
            )
            if not valid:
                return {"status": "ignored", "reason": reason}

        email, order_id = parse_event(provider, payload)
        if not email:
            return {"status": "ignored"}  # not a fulfilable sale

        # B2 — issuance can fail transiently (e.g. SMTP hiccup). Let it surface
        # as 500 so the processor RETRIES. issue_license emails BEFORE writing
        # the ledger, so a failed send leaves no ledger row and the retry
        # re-delivers cleanly (rather than being skipped as a false duplicate).
        try:
            result = _fulfil_once(email, order_id, provider)
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001 — 500 => processor retries
            logger.exception(
                "License issuance failed for provider=%s order_id=%s email=%s",
                provider, order_id, email)
            raise HTTPException(status_code=500, detail="issuance failed; will retry") from e
        if sandbox_config is None and result["status"] == "issued":
            # Preserve the legacy response outside explicit sandbox mode.
            return {"status": "issued", "email": email}
        return result

    return app


# Exposed for `uvicorn store.webhook_server:app`
try:  # pragma: no cover - only when fastapi is installed
    app = _build_app()
except ModuleNotFoundError as e:  # fastapi not installed — helpers still importable
    if e.name != "fastapi":
        raise
    app = None

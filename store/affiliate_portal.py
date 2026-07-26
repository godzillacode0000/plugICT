"""Secure affiliate click ingestion and aggregate analytics API.

This is intentionally separate from Stripe writes and buyer fulfilment. The API
only records referral clicks and reads aggregate affiliate stats from the local
SQLite ledger. Affiliate access tokens are hashed in SQLite and must be issued
manually with:

    python scripts/affiliate_ledger.py --db store/affiliate_ledger.sqlite3 issue-token CODE

Required production environment:
  AFFILIATE_DB=store/affiliate_ledger.sqlite3
  CLICK_HASH_SALT=<long random value kept outside the repository>
  AFFILIATE_ALLOWED_ORIGINS=https://plugict.com,https://godzillacode0000.github.io

Run locally:
  uvicorn store.affiliate_portal:app --host 127.0.0.1 --port 8787
"""
import hashlib
import hmac
import os
from pathlib import Path

from scripts.affiliate_ledger import AffiliateLedger

try:
    from pydantic import BaseModel, Field
except ModuleNotFoundError:  # pragma: no cover - seller API dependency only
    BaseModel = object
    Field = lambda *args, **kwargs: None  # type: ignore[assignment]


class ClickEvent(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    click_id: str = Field(min_length=1, max_length=128)
    visitor_id: str = Field(min_length=8, max_length=128)
    path: str = Field(default="/", max_length=200)
    referrer: str = Field(default="", max_length=300)

DB_FILE = Path(os.environ.get("AFFILIATE_DB", "store/affiliate_ledger.sqlite3"))
CLICK_HASH_SALT = os.environ.get("CLICK_HASH_SALT", "dev-only-change-this-salt")
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "AFFILIATE_ALLOWED_ORIGINS",
        "https://plugict.com,https://godzillacode0000.github.io",
    ).split(",")
    if origin.strip()
]


def visitor_hash(visitor_id: str) -> str:
    """Hash a browser-generated anonymous visitor id without storing raw ids."""
    return hmac.new(
        CLICK_HASH_SALT.encode("utf-8"),
        visitor_id.strip().encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _bearer_token(authorization: str | None) -> str:
    value = (authorization or "").strip()
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return ""
    return token.strip()


def build_app():
    from fastapi import FastAPI, Header, HTTPException, Request, Response
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPI(title="PlugICT Affiliate Analytics", version="1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
    ledger = AffiliateLedger(DB_FILE)
    ledger.initialize()

    @app.get("/health")
    def health():
        return {"ok": True, "service": "affiliate-analytics"}

    @app.post("/api/affiliate/click", status_code=204)
    def record_click(event: ClickEvent, request: Request):
        # No raw IP or user-agent is persisted. The visitor id is HMAC-hashed
        # with a server-side salt before it reaches SQLite.
        ledger.record_click(
            affiliate_code=event.code,
            click_id=event.click_id,
            visitor_hash=visitor_hash(event.visitor_id),
            landing_path=event.path,
            referrer=event.referrer or request.headers.get("referer", ""),
        )
        # Unknown/paused codes intentionally receive the same empty response;
        # this endpoint must not become an affiliate-code enumeration oracle.
        return Response(status_code=204)

    @app.get("/api/affiliate/stats")
    def stats(authorization: str | None = Header(default=None)):
        token = _bearer_token(authorization)
        affiliate = ledger.authenticate_access_token(token)
        if not affiliate:
            raise HTTPException(status_code=401, detail="affiliate authorization required")
        payload = ledger.affiliate_stats(affiliate["code"])
        if not payload:
            raise HTTPException(status_code=404, detail="affiliate not found")
        response = Response(
            content=__import__("json").dumps(payload),
            media_type="application/json",
            headers={"Cache-Control": "no-store"},
        )
        return response

    return app


try:
    app = build_app()
except ModuleNotFoundError as exc:  # allow ledger-only imports without FastAPI installed
    if exc.name != "fastapi":
        raise
    app = None

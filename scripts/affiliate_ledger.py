#!/usr/bin/env python3
"""Durable affiliate registry, commission ledger, and manual payout state.

The ledger is intentionally deterministic and local. Stripe remains read-only:
this module never calls a Stripe write endpoint and never moves money.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import secrets
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

AFFILIATE_CODE_RE = re.compile(r"^[a-z0-9_-]{1,64}$", re.IGNORECASE)
COMMISSION_CENTS = 500


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def mask_email(email: str | None) -> str:
    value = (email or "").strip()
    if "@" not in value:
        return ""
    local, domain = value.split("@", 1)
    if not local or not domain:
        return ""
    return f"{local[0]}***@{domain}"


def hash_access_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AffiliateLedger:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS affiliates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    name TEXT NOT NULL,
                    contact TEXT NOT NULL DEFAULT '',
                    payout_method TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'paused', 'closed')),
                    created_at TEXT NOT NULL,
                    access_token_hash TEXT
                );

                CREATE TABLE IF NOT EXISTS sales (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL UNIQUE,
                    affiliate_id INTEGER,
                    affiliate_code TEXT NOT NULL,
                    stripe_payment_link TEXT NOT NULL,
                    amount_cents INTEGER NOT NULL,
                    currency TEXT NOT NULL,
                    commission_cents INTEGER NOT NULL,
                    buyer_email_masked TEXT NOT NULL DEFAULT '',
                    session_created INTEGER,
                    status TEXT NOT NULL
                        CHECK (status IN ('credited', 'unknown_affiliate', 'disqualified')),
                    disqualification_reason TEXT NOT NULL DEFAULT '',
                    payout_status TEXT NOT NULL DEFAULT 'pending'
                        CHECK (payout_status IN ('pending', 'batched', 'paid', 'void')),
                    payout_id TEXT,
                    recorded_at TEXT NOT NULL,
                    FOREIGN KEY (affiliate_id) REFERENCES affiliates(id)
                );

                CREATE INDEX IF NOT EXISTS idx_sales_affiliate_pending
                    ON sales (affiliate_id, status, payout_status);

                CREATE TABLE IF NOT EXISTS payouts (
                    id TEXT PRIMARY KEY,
                    affiliate_id INTEGER NOT NULL,
                    affiliate_code TEXT NOT NULL,
                    amount_cents INTEGER NOT NULL,
                    currency TEXT NOT NULL,
                    sale_count INTEGER NOT NULL,
                    method TEXT NOT NULL DEFAULT '',
                    note TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'paid', 'cancelled')),
                    reference TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    paid_at TEXT,
                    FOREIGN KEY (affiliate_id) REFERENCES affiliates(id)
                );

                CREATE TABLE IF NOT EXISTS clicks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    affiliate_code TEXT NOT NULL,
                    click_id TEXT NOT NULL,
                    visitor_hash TEXT NOT NULL DEFAULT '',
                    landing_path TEXT NOT NULL DEFAULT '/',
                    referrer TEXT NOT NULL DEFAULT '',
                    recorded_at TEXT NOT NULL,
                    UNIQUE (affiliate_code, click_id)
                );

                CREATE INDEX IF NOT EXISTS idx_clicks_affiliate
                    ON clicks (affiliate_code, recorded_at);
                """
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info(affiliates)")}
            if "access_token_hash" not in columns:
                conn.execute("ALTER TABLE affiliates ADD COLUMN access_token_hash TEXT")

    def add_affiliate(
        self,
        code: str,
        name: str,
        *,
        contact: str = "",
        payout_method: str = "",
    ) -> int:
        code = code.strip().lower()
        name = name.strip()
        if not AFFILIATE_CODE_RE.fullmatch(code):
            raise ValueError("affiliate code must be 1-64 letters, numbers, '_' or '-'")
        if not name:
            raise ValueError("affiliate name is required")
        with self._connect() as conn:
            try:
                cur = conn.execute(
                    """
                    INSERT INTO affiliates(code, name, contact, payout_method, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (code, name, contact.strip(), payout_method.strip(), utc_now()),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"affiliate code already exists: {code}") from exc
            return int(cur.lastrowid)

    def set_affiliate_status(self, code: str, status: str) -> None:
        if status not in {"active", "paused", "closed"}:
            raise ValueError("status must be active, paused, or closed")
        with self._connect() as conn:
            cur = conn.execute("UPDATE affiliates SET status=? WHERE code=?", (status, code.lower()))
            if cur.rowcount != 1:
                raise ValueError(f"affiliate not found: {code}")

    def get_affiliate(self, code: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM affiliates WHERE code=?", (code.lower(),)).fetchone()
            return dict(row) if row else None

    def issue_access_token(self, code: str) -> str:
        token = secrets.token_urlsafe(32)
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE affiliates SET access_token_hash=? WHERE code=? AND status != 'closed'",
                (hash_access_token(token), code.strip().lower()),
            )
            if cur.rowcount != 1:
                raise ValueError(f"active affiliate not found: {code}")
        return token

    def authenticate_access_token(self, token: str) -> dict[str, Any] | None:
        token = token.strip()
        if not token:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM affiliates WHERE access_token_hash=? AND status='active'",
                (hash_access_token(token),),
            ).fetchone()
            return dict(row) if row else None

    def record_click(
        self,
        *,
        affiliate_code: str,
        click_id: str,
        visitor_hash: str,
        landing_path: str = "/",
        referrer: str = "",
    ) -> bool:
        code = affiliate_code.strip().lower()
        click_id = click_id.strip()
        if not AFFILIATE_CODE_RE.fullmatch(code):
            return False
        if not click_id or len(click_id) > 128:
            return False
        with self._connect() as conn:
            affiliate = conn.execute(
                "SELECT 1 FROM affiliates WHERE code=? AND status='active'", (code,)
            ).fetchone()
            if not affiliate:
                return False
            try:
                conn.execute(
                    """
                    INSERT INTO clicks(
                        affiliate_code, click_id, visitor_hash, landing_path, referrer, recorded_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        code,
                        click_id,
                        visitor_hash[:128],
                        (landing_path or "/")[:200],
                        (referrer or "")[:300],
                        utc_now(),
                    ),
                )
                return True
            except sqlite3.IntegrityError:
                return False

    def affiliate_stats(self, code: str) -> dict[str, Any] | None:
        code = code.strip().lower()
        with self._connect() as conn:
            affiliate = conn.execute(
                "SELECT code, name, status, created_at FROM affiliates WHERE code=?",
                (code,),
            ).fetchone()
            if not affiliate:
                return None
            clicks = conn.execute(
                """
                SELECT COUNT(*) AS total_clicks,
                       COUNT(DISTINCT NULLIF(visitor_hash, '')) AS unique_clicks
                FROM clicks WHERE affiliate_code=?
                """,
                (code,),
            ).fetchone()
            sales = conn.execute(
                """
                SELECT
                    SUM(CASE WHEN status='credited' THEN 1 ELSE 0 END) AS purchases,
                    COALESCE(SUM(CASE WHEN status='credited' AND payout_status IN ('pending','batched')
                                      THEN commission_cents ELSE 0 END), 0) AS pending_cents,
                    COALESCE(SUM(CASE WHEN status='credited' AND payout_status='paid'
                                      THEN commission_cents ELSE 0 END), 0) AS paid_cents,
                    SUM(CASE WHEN status='disqualified' OR payout_status='void' THEN 1 ELSE 0 END) AS voided
                FROM sales WHERE affiliate_code=?
                """,
                (code,),
            ).fetchone()
            total_clicks = int(clicks["total_clicks"] or 0)
            unique_clicks = int(clicks["unique_clicks"] or 0)
            purchases = int(sales["purchases"] or 0)
            return {
                "affiliate": {"code": affiliate["code"], "name": affiliate["name"]},
                "referral_url": f"https://go.plugict.com/r/{affiliate['code']}",
                "clicks": total_clicks,
                "unique_clicks": unique_clicks,
                "purchases": purchases,
                "conversion_rate": round((purchases / unique_clicks) * 100, 2) if unique_clicks else 0.0,
                "pending_commission_cents": int(sales["pending_cents"] or 0),
                "paid_commission_cents": int(sales["paid_cents"] or 0),
                "voided_purchases": int(sales["voided"] or 0),
            }

    def list_affiliates(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM affiliates ORDER BY code")]

    def has_sale(self, session_id: str) -> bool:
        with self._connect() as conn:
            return conn.execute("SELECT 1 FROM sales WHERE session_id=?", (session_id,)).fetchone() is not None

    def record_sale(
        self,
        *,
        session_id: str,
        affiliate_code: str,
        stripe_payment_link: str,
        amount_cents: int,
        currency: str,
        buyer_email: str = "",
        session_created: int | None = None,
        status: str = "credited",
        disqualification_reason: str = "",
    ) -> bool:
        affiliate = self.get_affiliate(affiliate_code)
        affiliate_id = affiliate["id"] if affiliate else None
        commission = COMMISSION_CENTS if status == "credited" and affiliate else 0
        payout_status = "pending" if status == "credited" and affiliate else "void"
        with self._connect() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO sales(
                        session_id, affiliate_id, affiliate_code, stripe_payment_link,
                        amount_cents, currency, commission_cents, buyer_email_masked,
                        session_created, status, disqualification_reason, payout_status, recorded_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        affiliate_id,
                        affiliate_code.lower(),
                        stripe_payment_link,
                        int(amount_cents),
                        currency.lower(),
                        commission,
                        mask_email(buyer_email),
                        session_created,
                        status,
                        disqualification_reason,
                        payout_status,
                        utc_now(),
                    ),
                )
                return True
            except sqlite3.IntegrityError as exc:
                if "sales.session_id" in str(exc) or "UNIQUE constraint failed: sales.session_id" in str(exc):
                    return False
                raise

    def get_sale(self, session_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM sales WHERE session_id=?", (session_id,)).fetchone()
            return dict(row) if row else None

    def disqualify_sale(self, session_id: str, reason: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM sales WHERE session_id=?", (session_id,)).fetchone()
            if not row or row["status"] != "credited":
                return dict(row) if row else None
            payout_status = "void" if row["payout_status"] in {"pending", "batched"} else row["payout_status"]
            conn.execute(
                """
                UPDATE sales
                SET status='disqualified', disqualification_reason=?, payout_status=?
                WHERE session_id=?
                """,
                (reason, payout_status, session_id),
            )
            updated = conn.execute("SELECT * FROM sales WHERE session_id=?", (session_id,)).fetchone()
            return dict(updated)

    def pending_summary(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT a.code, a.name, COUNT(s.id) AS sales,
                       COALESCE(SUM(s.commission_cents), 0) AS commission_cents
                FROM affiliates a
                JOIN sales s ON s.affiliate_id = a.id
                WHERE s.status='credited' AND s.payout_status='pending'
                GROUP BY a.id, a.code, a.name
                ORDER BY a.code
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def create_payout(self, code: str, *, method: str = "", note: str = "") -> str:
        with self._connect() as conn:
            affiliate = conn.execute(
                "SELECT * FROM affiliates WHERE code=? AND status != 'closed'", (code.lower(),)
            ).fetchone()
            if not affiliate:
                raise ValueError(f"active affiliate not found: {code}")
            sales = conn.execute(
                """
                SELECT id, commission_cents, currency FROM sales
                WHERE affiliate_id=? AND status='credited' AND payout_status='pending'
                ORDER BY id
                """,
                (affiliate["id"],),
            ).fetchall()
            if not sales:
                raise ValueError(f"no pending commission for: {code}")
            currencies = {row["currency"] for row in sales}
            if len(currencies) != 1:
                raise ValueError("pending sales contain multiple currencies")
            payout_id = f"payout_{uuid.uuid4().hex[:16]}"
            amount = sum(int(row["commission_cents"]) for row in sales)
            conn.execute(
                """
                INSERT INTO payouts(
                    id, affiliate_id, affiliate_code, amount_cents, currency, sale_count,
                    method, note, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payout_id,
                    affiliate["id"],
                    affiliate["code"],
                    amount,
                    next(iter(currencies)),
                    len(sales),
                    method.strip(),
                    note.strip(),
                    utc_now(),
                ),
            )
            conn.executemany(
                "UPDATE sales SET payout_status='batched', payout_id=? WHERE id=?",
                [(payout_id, row["id"]) for row in sales],
            )
            return payout_id

    def mark_payout_paid(self, payout_id: str, *, reference: str) -> None:
        reference = reference.strip()
        if not reference:
            raise ValueError("payout reference is required")
        with self._connect() as conn:
            payout = conn.execute("SELECT * FROM payouts WHERE id=?", (payout_id,)).fetchone()
            if not payout:
                raise ValueError(f"payout not found: {payout_id}")
            if payout["status"] != "pending":
                raise ValueError(f"payout is not pending: {payout_id}")
            conn.execute(
                "UPDATE payouts SET status='paid', reference=?, paid_at=? WHERE id=?",
                (reference, utc_now(), payout_id),
            )
            conn.execute(
                "UPDATE sales SET payout_status='paid' WHERE payout_id=?",
                (payout_id,),
            )

    def get_payout(self, payout_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM payouts WHERE id=?", (payout_id,)).fetchone()
            return dict(row) if row else None


def process_session(
    ledger: AffiliateLedger,
    session: dict[str, Any],
    *,
    expected_payment_link: str,
    payment_state: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Process one Stripe Checkout Session without making any Stripe writes."""
    session_id = (session.get("id") or "").strip()
    if not session_id:
        return None
    ref = (session.get("client_reference_id") or "").strip().lower()
    if not ref:
        return None
    if session.get("status") != "complete" or session.get("payment_status") != "paid":
        return None
    payment_link = (session.get("payment_link") or "").strip()
    if not expected_payment_link or payment_link != expected_payment_link:
        return {"event": "ignored_wrong_product", "code": ref}

    state = payment_state or {}
    reason = "refunded" if state.get("refunded") else "disputed" if state.get("disputed") else ""
    existing = ledger.get_sale(session_id)
    if existing:
        if reason and existing["status"] == "credited":
            updated = ledger.disqualify_sale(session_id, reason)
            return {
                "event": "disqualified_after_credit",
                "code": existing["affiliate_code"],
                "reason": reason,
                "payout_status": updated["payout_status"] if updated else "void",
            }
        return None
    if reason:
        ledger.record_sale(
            session_id=session_id,
            affiliate_code=ref,
            stripe_payment_link=payment_link,
            amount_cents=int(session.get("amount_total") or 0),
            currency=(session.get("currency") or "usd"),
            buyer_email=((session.get("customer_details") or {}).get("email") or ""),
            session_created=session.get("created"),
            status="disqualified",
            disqualification_reason=reason,
        )
        return {"event": "disqualified", "code": ref, "reason": reason}

    affiliate = ledger.get_affiliate(ref)
    if not affiliate or affiliate["status"] != "active":
        ledger.record_sale(
            session_id=session_id,
            affiliate_code=ref,
            stripe_payment_link=payment_link,
            amount_cents=int(session.get("amount_total") or 0),
            currency=(session.get("currency") or "usd"),
            buyer_email=((session.get("customer_details") or {}).get("email") or ""),
            session_created=session.get("created"),
            status="unknown_affiliate",
            disqualification_reason="unknown_or_inactive_affiliate",
        )
        return {"event": "unknown_affiliate", "code": ref}

    inserted = ledger.record_sale(
        session_id=session_id,
        affiliate_code=ref,
        stripe_payment_link=payment_link,
        amount_cents=int(session.get("amount_total") or 0),
        currency=(session.get("currency") or "usd"),
        buyer_email=((session.get("customer_details") or {}).get("email") or ""),
        session_created=session.get("created"),
    )
    if not inserted:
        return None
    return {"event": "sale", "code": ref, "commission_cents": COMMISSION_CENTS}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PlugICT affiliate ledger operations")
    parser.add_argument("--db", default="store/affiliate_ledger.sqlite3", help="SQLite ledger path")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init")
    add = sub.add_parser("add-affiliate")
    add.add_argument("code")
    add.add_argument("name")
    add.add_argument("--contact", default="")
    add.add_argument("--payout-method", default="")

    status = sub.add_parser("affiliate-status")
    status.add_argument("code")
    status.add_argument("status", choices=["active", "paused", "closed"])
    token = sub.add_parser("issue-token")
    token.add_argument("code")
    sub.add_parser("list-affiliates")
    sub.add_parser("pending")

    payout = sub.add_parser("create-payout")
    payout.add_argument("code")
    payout.add_argument("--method", default="")
    payout.add_argument("--note", default="")

    paid = sub.add_parser("mark-payout-paid")
    paid.add_argument("payout_id")
    paid.add_argument("--reference", required=True)
    return parser


def cli(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    ledger = AffiliateLedger(args.db)
    ledger.initialize()
    if args.command == "init":
        print(f"LEDGER_READY|{ledger.path}")
    elif args.command == "add-affiliate":
        affiliate_id = ledger.add_affiliate(
            args.code, args.name, contact=args.contact, payout_method=args.payout_method
        )
        print(f"AFFILIATE_ADDED|{args.code.lower()}|{affiliate_id}")
    elif args.command == "affiliate-status":
        ledger.set_affiliate_status(args.code, args.status)
        print(f"AFFILIATE_STATUS|{args.code.lower()}|{args.status}")
    elif args.command == "issue-token":
        print(f"AFFILIATE_TOKEN|{args.code.lower()}|{ledger.issue_access_token(args.code)}")
    elif args.command == "list-affiliates":
        for row in ledger.list_affiliates():
            print(f"AFFILIATE|{row['code']}|{row['name']}|{row['status']}")
    elif args.command == "pending":
        for row in ledger.pending_summary():
            print(
                f"PENDING|{row['code']}|{row['name']}|{row['sales']}|"
                f"{row['commission_cents'] / 100:.2f} USD"
            )
    elif args.command == "create-payout":
        payout_id = ledger.create_payout(args.code, method=args.method, note=args.note)
        payout = ledger.get_payout(payout_id)
        print(f"PAYOUT_CREATED|{payout_id}|{payout['amount_cents'] / 100:.2f} {payout['currency'].upper()}")
    elif args.command == "mark-payout-paid":
        ledger.mark_payout_paid(args.payout_id, reference=args.reference)
        print(f"PAYOUT_PAID|{args.payout_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())

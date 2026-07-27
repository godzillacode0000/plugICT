#!/usr/bin/env python3
"""Fail-closed mirror of the private SQLite affiliate registry into preview D1.

This script mirrors only code, display name, status, and token hashes. It never
mirrors buyer, Stripe, payout, contact, or raw visitor data. Remote execution
is preview-only and requires explicit --remote --confirm-preview flags.

Examples:
  python scripts/sync_affiliate_to_d1.py --ledger C:/private/affiliate.sqlite3 \
    --database plugict-affiliate-analytics-preview --dry-run
  python scripts/sync_affiliate_to_d1.py --ledger C:/private/affiliate.sqlite3 \
    --database plugict-affiliate-analytics-preview --remote --confirm-preview
  python scripts/sync_affiliate_to_d1.py --ledger C:/private/affiliate.sqlite3 \
    --database plugict-affiliate-analytics-preview --rotate test_001 \
    --remote --confirm-preview
"""
from __future__ import annotations

import argparse
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Sequence

from scripts.affiliate_ledger import AffiliateLedger

Runner = Callable[..., subprocess.CompletedProcess[str]]


def require_ledger(path_value: str | Path) -> Path:
    path = Path(path_value).expanduser().resolve()
    if not path.exists() or not path.is_file():
        raise ValueError(f"ledger path does not exist or is not a file: {path}")
    return path


def sql_literal(value: object) -> str:
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def build_sync_sql(rows: Sequence[dict], now: int | None = None) -> str:
    timestamp = int(time.time() if now is None else now)
    statements = ["BEGIN;"]
    for row in rows:
        code = str(row["code"]).strip().lower()
        name = str(row["name"]).strip()
        status = str(row["status"]).strip().lower()
        token_hash = row.get("access_token_hash")
        statements.append(
            "INSERT INTO affiliate_codes(code, display_name, status, token_hash, created_at, updated_at) "
            f"VALUES ({sql_literal(code)}, {sql_literal(name)}, {sql_literal(status)}, "
            f"{sql_literal(token_hash)}, {timestamp}, {timestamp}) "
            "ON CONFLICT(code) DO UPDATE SET "
            "display_name=excluded.display_name, status=excluded.status, "
            "token_hash=COALESCE(excluded.token_hash, affiliate_codes.token_hash), "
            "updated_at=excluded.updated_at;"
        )
    statements.append("COMMIT;")
    return "\n".join(statements) + "\n"


def validate_remote(database: str, confirm_preview: bool) -> None:
    lowered = database.lower()
    if not confirm_preview:
        raise ValueError("remote sync requires --confirm-preview")
    if "preview" not in lowered or "prod" in lowered or "production" in lowered:
        raise ValueError("remote sync is restricted to a database name containing preview")


def run_wrangler(
    database: str,
    sql: str,
    *,
    remote: bool,
    runner: Runner = subprocess.run,
) -> subprocess.CompletedProcess[str]:
    command = [
        "npx", "wrangler", "d1", "execute", database,
        "--config", "wrangler.toml",
        "--command", sql,
        "--remote" if remote else "--local",
    ]
    result = runner(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Wrangler D1 sync failed with exit code {result.returncode}")
    return result


def sync_affiliates(
    ledger_path: str | Path,
    database: str,
    *,
    remote: bool = False,
    confirm_preview: bool = False,
    dry_run: bool = False,
    runner: Runner = subprocess.run,
) -> str:
    path = require_ledger(ledger_path)
    if remote:
        validate_remote(database, confirm_preview)
    ledger = AffiliateLedger(path)
    ledger.initialize()
    rows = ledger.list_affiliates()
    sql = build_sync_sql(rows)
    if dry_run:
        return sql
    run_wrangler(database, sql, remote=remote, runner=runner)
    return sql


def restore_token_hash(path: Path, code: str, previous_hash: str | None) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE affiliates SET access_token_hash=? WHERE code=?",
            (previous_hash, code.strip().lower()),
        )


def rotate_and_sync(
    ledger_path: str | Path,
    database: str,
    code: str,
    *,
    remote: bool,
    confirm_preview: bool,
    runner: Runner = subprocess.run,
) -> str:
    path = require_ledger(ledger_path)
    if not remote:
        raise ValueError("token rotation requires explicit remote preview sync")
    validate_remote(database, confirm_preview)
    ledger = AffiliateLedger(path)
    ledger.initialize()
    affiliate = ledger.get_affiliate(code)
    if not affiliate or affiliate["status"] == "closed":
        raise ValueError(f"active affiliate not found: {code}")
    previous_hash = affiliate.get("access_token_hash")
    token = ledger.issue_access_token(code)
    try:
        sync_affiliates(path, database, remote=True, confirm_preview=True, runner=runner)
    except Exception:
        restore_token_hash(path, code, previous_hash)
        raise
    return token


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mirror affiliate registry to preview D1")
    parser.add_argument("--ledger", required=True, help="exact existing SQLite ledger path")
    parser.add_argument("--database", required=True, help="D1 database name")
    parser.add_argument("--remote", action="store_true", help="use remote D1; preview confirmation required")
    parser.add_argument("--confirm-preview", action="store_true", help="confirm remote database is preview-only")
    parser.add_argument("--dry-run", action="store_true", help="print generated SQL without executing Wrangler")
    parser.add_argument("--rotate", metavar="CODE", help="rotate one affiliate token before preview sync")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.rotate:
            token = rotate_and_sync(
                args.ledger, args.database, args.rotate,
                remote=args.remote, confirm_preview=args.confirm_preview,
            )
            print(f"AFFILIATE_TOKEN|{args.rotate.strip().lower()}|{token}")
        else:
            sql = sync_affiliates(
                args.ledger, args.database,
                remote=args.remote, confirm_preview=args.confirm_preview, dry_run=args.dry_run,
            )
            print(f"D1_SYNC|database={args.database}|mode={'remote-preview' if args.remote else 'local'}|rows={sql.count('INSERT INTO affiliate_codes')}")
            if args.dry_run:
                print(sql, end="")
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"ERROR|{exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

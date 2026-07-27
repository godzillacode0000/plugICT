from pathlib import Path
import sqlite3
import subprocess

import pytest

from scripts.affiliate_ledger import AffiliateLedger
from scripts.sync_affiliate_to_d1 import (
    build_sync_sql,
    require_ledger,
    rotate_and_sync,
    sync_affiliates,
)


def make_ledger(tmp_path: Path):
    path = tmp_path / "ledger.sqlite3"
    ledger = AffiliateLedger(path)
    ledger.initialize()
    ledger.add_affiliate("test_001", "Test Affiliate", contact="private-contact")
    token = ledger.issue_access_token("test_001")
    return path, ledger, token


def test_exact_existing_ledger_is_required(tmp_path: Path):
    with pytest.raises(ValueError, match="does not exist"):
        require_ledger(tmp_path / "missing.sqlite3")


def test_sql_contains_hashes_only_and_no_private_contact_or_raw_token(tmp_path: Path):
    path, ledger, token = make_ledger(tmp_path)
    row = ledger.get_affiliate("test_001")
    sql = build_sync_sql([row], now=123)
    assert row["access_token_hash"] in sql
    assert token not in sql
    assert "private-contact" not in sql
    assert "buyer_email" not in sql
    assert "stripe" not in sql.lower()


def test_remote_preview_confirmation_is_fail_closed(tmp_path: Path):
    path, _, _ = make_ledger(tmp_path)
    with pytest.raises(ValueError, match="confirm-preview"):
        sync_affiliates(path, "plugict-affiliate-analytics-preview", remote=True)
    with pytest.raises(ValueError, match="preview"):
        sync_affiliates(path, "plugict-affiliate-production", remote=True, confirm_preview=True)


def test_rotation_rolls_back_local_hash_when_d1_sync_fails(tmp_path: Path):
    path, ledger, _ = make_ledger(tmp_path)
    before = ledger.get_affiliate("test_001")["access_token_hash"]

    def failed_runner(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 1, "", "failure")

    with pytest.raises(RuntimeError, match="Wrangler D1 sync failed"):
        rotate_and_sync(
            path,
            "plugict-affiliate-analytics-preview",
            "test_001",
            remote=True,
            confirm_preview=True,
            runner=failed_runner,
        )
    assert AffiliateLedger(path).get_affiliate("test_001")["access_token_hash"] == before


def test_rotation_sync_never_places_raw_token_in_wrangler_command(tmp_path: Path):
    path, ledger, _ = make_ledger(tmp_path)
    commands = []

    def successful_runner(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "ok", "")

    token = rotate_and_sync(
        path,
        "plugict-affiliate-analytics-preview",
        "test_001",
        remote=True,
        confirm_preview=True,
        runner=successful_runner,
    )
    assert token
    command_text = " ".join(commands[0])
    assert token not in command_text
    assert "--remote" in commands[0]
    assert "--local" not in commands[0]

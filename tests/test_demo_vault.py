"""Demo-vault watermark: metadata flag -> vault_core.demo_info -> query output."""

import os
import sys
import sqlite3
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import vault_core as vc  # noqa: E402
from test_vault_core import _make_db_bytes, _make_chroma_bytes  # noqa: E402
from cryptography.fernet import Fernet  # noqa: E402


def _demo_fixture(tmp):
    """Fixture vault stamped exactly like build.py does for ICT_DEMO=1."""
    db_bytes = _make_db_bytes(tmp)
    db_path = Path(tmp) / "stamped.db"
    db_path.write_bytes(db_bytes)
    con = sqlite3.connect(db_path)
    for k, v in [("demo", "1"), ("demo_count", "5"), ("demo_total", "576"),
                 ("demo_cta", "https://example.com/#pricing")]:
        con.execute("INSERT OR REPLACE INTO vault_metadata VALUES (?,?)", (k, v))
    con.commit(); con.close()
    blob, key, vhash = vc.pack_and_encrypt(db_path.read_bytes(), _make_chroma_bytes(), compress=True)
    vault = Path(tmp) / "ict-vault.kevin"
    vault.write_bytes(blob)
    buyer_key = Fernet.generate_key()
    lic = Path(tmp) / "license.key"
    lic.write_text("LICENSED_TO=demo@ict-vault.free\n"
                   f"BUYER_KEY={buyer_key.decode()}\n"
                   f"ENCRYPTED_VAULT_KEY={Fernet(buyer_key).encrypt(key).decode()}\n"
                   f"VAULT_HASH={vhash}\n")
    return vault, lic


def test_demo_info_detects_stamp(tmp_path):
    vault, lic = _demo_fixture(str(tmp_path))
    db, _, _ = vc.open_vault(vault_file=vault, license_file=lic)
    try:
        d = vc.demo_info(db)
        assert d == {"count": "5", "total": "576", "cta": "https://example.com/#pricing"}
    finally:
        db.close()


def test_demo_info_none_for_full_vault(tmp_path):
    from test_vault_core import _write_fixture_vault
    vault, lic = _write_fixture_vault(str(tmp_path), compress=True)
    db, _, _ = vc.open_vault(vault_file=vault, license_file=lic)
    try:
        assert vc.demo_info(db) is None
    finally:
        db.close()


def test_query_output_shows_watermark(tmp_path):
    vault, lic = _demo_fixture(str(tmp_path))
    env = dict(os.environ, ICT_VAULT_FILE=str(vault), ICT_VAULT_LICENSE=str(lic),
               NO_COLOR="1")
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "query.py"),
                        "fair value gap"],
                       env=env, capture_output=True, text=True, timeout=120,
                       cwd=str(tmp_path))  # cwd isolated so no cache file lands in repo
    out = r.stdout
    assert r.returncode == 0, r.stderr
    assert "DEMO" in out and "5/576" in out, out
    assert "https://example.com/#pricing" in out
    assert "Fair Value Gap Explained" in out  # search still works

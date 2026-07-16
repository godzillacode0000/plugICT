import hashlib
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from refresh_license_hash import refresh_license_hash  # noqa: E402


def _fixture(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    encrypted = b"encrypted-v3-artifact"
    (vault / "ict-vault.kevin").write_bytes(encrypted)
    new_hash = hashlib.sha256(encrypted).hexdigest()
    (vault / ".vault_sha256").write_text(new_hash, encoding="utf-8")
    vault_key = b"k" * 32
    (vault / ".vault_key").write_bytes(vault_key)
    buyer_key = Fernet.generate_key()
    wrapped = Fernet(buyer_key).encrypt(vault_key)
    source = tmp_path / "license.key"
    source.write_text(
        "LICENSED_TO=test@example.com\n"
        f"BUYER_KEY={buyer_key.decode()}\n"
        f"ENCRYPTED_VAULT_KEY={wrapped.decode()}\n"
        f"VAULT_HASH={'a' * 64}\n",
        encoding="utf-8",
    )
    return source, vault, new_hash


def test_refresh_license_verifies_then_changes_only_vault_hash(tmp_path):
    source, vault, new_hash = _fixture(tmp_path)
    output = tmp_path / "refreshed.key"
    original = source.read_text(encoding="utf-8")

    refresh_license_hash(source, vault, output)

    refreshed = output.read_text(encoding="utf-8")
    assert f"VAULT_HASH={new_hash}" in refreshed
    assert next(line for line in original.splitlines() if line.startswith("BUYER_KEY=")) in refreshed
    assert next(line for line in original.splitlines() if line.startswith("ENCRYPTED_VAULT_KEY=")) in refreshed
    assert source.read_text(encoding="utf-8") == original


def test_refresh_rejects_hash_not_matching_encrypted_artifact(tmp_path):
    source, vault, _ = _fixture(tmp_path)
    (vault / ".vault_sha256").write_text("b" * 64, encoding="utf-8")
    with pytest.raises(ValueError, match="actual encrypted vault"):
        refresh_license_hash(source, vault, tmp_path / "out.key")


def test_refresh_rejects_wrapped_key_for_different_build(tmp_path):
    source, vault, _ = _fixture(tmp_path)
    (vault / ".vault_key").write_bytes(b"z" * 32)
    with pytest.raises(ValueError, match="does not open this build"):
        refresh_license_hash(source, vault, tmp_path / "out.key")


def test_in_place_refresh_succeeds_after_all_checks(tmp_path):
    source, vault, new_hash = _fixture(tmp_path)
    refresh_license_hash(source, vault, source)
    assert f"VAULT_HASH={new_hash}" in source.read_text(encoding="utf-8")
    assert not list(tmp_path.glob(".*.tmp"))

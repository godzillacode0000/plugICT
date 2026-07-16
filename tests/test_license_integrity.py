import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import vault_core as vc  # noqa: E402
from generate_key import generate_license  # noqa: E402
from test_vault_core import _write_fixture_vault  # noqa: E402


def _seller_fixture(tmp_path):
    vault_dir = tmp_path / "build"
    vault_dir.mkdir()
    artifact = b"authenticated encrypted artifact"
    (vault_dir / "ict-vault.kevin").write_bytes(artifact)
    (vault_dir / ".vault_key").write_bytes(b"k" * 32)
    return vault_dir, hashlib.sha256(artifact).hexdigest()


def test_generate_license_requires_hash_file(tmp_path):
    vault_dir, _ = _seller_fixture(tmp_path)

    with pytest.raises(FileNotFoundError, match=r"\.vault_sha256"):
        generate_license("buyer@example.com", "ORDER-1", vault_dir=vault_dir)


def test_generate_license_rejects_invalid_or_mismatched_hash(tmp_path):
    vault_dir, actual_hash = _seller_fixture(tmp_path)
    hash_file = vault_dir / ".vault_sha256"

    hash_file.write_text("not-a-sha256", encoding="utf-8")
    with pytest.raises(ValueError, match="valid SHA-256"):
        generate_license("buyer@example.com", "ORDER-1", vault_dir=vault_dir)

    hash_file.write_text("a" * 64, encoding="utf-8")
    assert actual_hash != "a" * 64
    with pytest.raises(ValueError, match="actual encrypted vault"):
        generate_license("buyer@example.com", "ORDER-1", vault_dir=vault_dir)


def test_generate_license_requires_exact_artifact_hash(tmp_path):
    vault_dir, actual_hash = _seller_fixture(tmp_path)
    (vault_dir / ".vault_sha256").write_text(actual_hash, encoding="utf-8")

    output, _ = generate_license("buyer@example.com", "ORDER-1", vault_dir=vault_dir)

    assert f"VAULT_HASH={actual_hash}" in output.read_text(encoding="utf-8")


def test_open_vault_rejects_missing_hash_before_decrypt(tmp_path, monkeypatch):
    vault, license_file = _write_fixture_vault(tmp_path, compress=True)
    lines = [line for line in license_file.read_text().splitlines()
             if not line.startswith("VAULT_HASH=")]
    license_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    called = False

    def forbidden_decrypt(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("decrypt must not run before authentication")

    monkeypatch.setattr(vc, "_decrypt_stream", forbidden_decrypt)
    with pytest.raises(vc.VaultError, match="valid VAULT_HASH"):
        vc.open_vault(vault, license_file)
    assert called is False


def test_open_vault_rejects_hash_mismatch_before_decrypt(tmp_path, monkeypatch):
    vault, license_file = _write_fixture_vault(tmp_path, compress=True)
    vault.write_bytes(vault.read_bytes() + b"tampered")
    called = False

    def forbidden_decrypt(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("decrypt must not run before authentication")

    monkeypatch.setattr(vc, "_decrypt_stream", forbidden_decrypt)
    with pytest.raises(vc.VaultError, match="integrity check"):
        vc.open_vault(vault, license_file)
    assert called is False

#!/usr/bin/env python3
"""Atomically refresh only the VAULT_HASH binding in a buyer license.

The preserved wrapped vault key is verified against the build's raw `.vault_key`
and the hash is verified against the actual encrypted artifact before any output
is replaced.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _license_fields(text: str) -> dict[str, str]:
    fields = {}
    for line in text.splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        fields[key.strip()] = value.strip()
    return fields


def refresh_license_hash(license_file: Path, vault_dir: Path, output: Path) -> Path:
    license_file = Path(license_file)
    vault_dir = Path(vault_dir)
    output = Path(output)
    vault_file = vault_dir / "ict-vault.kevin"
    hash_file = vault_dir / ".vault_sha256"
    key_file = vault_dir / ".vault_key"
    for required in (vault_file, hash_file, key_file):
        if not required.is_file():
            raise FileNotFoundError(f"required build artifact missing: {required}")

    new_hash = hash_file.read_text(encoding="utf-8").strip().lower()
    if not _HASH_RE.fullmatch(new_hash):
        raise ValueError(".vault_sha256 must contain exactly one SHA-256 hex digest")
    actual_hash = _sha256_file(vault_file)
    if actual_hash != new_hash:
        raise ValueError(".vault_sha256 does not match the actual encrypted vault")

    text = license_file.read_text(encoding="utf-8")
    fields = _license_fields(text)
    if not fields.get("ENCRYPTED_VAULT_KEY") or not fields.get("BUYER_KEY"):
        raise ValueError("license is missing wrapped-key fields")
    try:
        unwrapped_key = Fernet(fields["BUYER_KEY"].encode("ascii")).decrypt(
            fields["ENCRYPTED_VAULT_KEY"].encode("ascii")
        )
    except (ValueError, InvalidToken) as exc:
        raise ValueError("license wrapped vault key is invalid") from exc
    build_key = key_file.read_bytes()
    if len(build_key) != 32 or unwrapped_key != build_key:
        raise ValueError("license wrapped key does not open this build's .vault_key")

    lines = text.splitlines()
    replaced = False
    out_lines = []
    for line in lines:
        if line.startswith("VAULT_HASH="):
            out_lines.append(f"VAULT_HASH={new_hash}")
            replaced = True
        else:
            out_lines.append(line)
    if not replaced:
        out_lines.append(f"VAULT_HASH={new_hash}")

    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".tmp", dir=str(output.parent)
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(out_lines) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(temp_path, 0o600)
        except OSError:
            pass
        os.replace(temp_path, output)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--license", required=True, type=Path)
    parser.add_argument("--vault-dir", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--in-place", action="store_true")
    args = parser.parse_args()
    if args.in_place and args.output:
        parser.error("choose --output or --in-place, not both")
    if not args.in_place and not args.output:
        parser.error("--output is required unless --in-place is used")
    output = args.license if args.in_place else args.output
    refresh_license_hash(args.license, args.vault_dir, output)
    print(f"Refreshed license written: {output}")
    print("Vault hash and preserved wrapped key verified before atomic replacement.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Fail-closed path and atomic-write helpers for encrypted vault builds."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def _resolved(path):
    return Path(path).expanduser().resolve(strict=False)


def _inside(path, root):
    path = _resolved(path)
    root = _resolved(root)
    return path == root or root in path.parents


def resolve_build_paths(source_dir, environ=None):
    """Resolve an isolated build, output, key, and hash path or fail closed."""
    env = os.environ if environ is None else environ
    source = _resolved(source_dir)
    build_raw = env.get("ICT_BUILD_DIR")
    allow_in_place = env.get("ICT_ALLOW_IN_PLACE_BUILD") == "1"
    if not build_raw and not allow_in_place:
        raise ValueError("ICT_BUILD_DIR is required; in-place production builds are disabled")
    build = _resolved(build_raw or source)
    if build == source and not allow_in_place:
        raise ValueError("ICT_BUILD_DIR must differ from ICT_SOURCE_DIR")

    output = _resolved(env.get("ICT_OUTPUT_FILE") or (build / "ict-vault.kevin"))
    key = _resolved(env.get("ICT_VAULT_KEY_FILE") or (build / ".vault_key"))
    hash_file = build / ".vault_sha256"
    for label, path in (("ICT_OUTPUT_FILE", output), ("ICT_VAULT_KEY_FILE", key),
                        ("hash file", hash_file)):
        if not _inside(path, build):
            raise ValueError(f"{label} must stay inside ICT_BUILD_DIR")
    if len({_resolved(output), _resolved(key), _resolved(hash_file)}) != 3:
        raise ValueError("vault output, key, and hash paths must be distinct")
    return source, build, output, key, hash_file


def atomic_write_bytes(path, data, mode=None):
    """Write and fsync a complete file, then atomically replace its target."""
    target = _resolved(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp",
                                     dir=str(target.parent))
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            try:
                os.chmod(temp_path, mode)
            except OSError:
                pass
        os.replace(temp_path, target)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return target


def atomic_write_text(path, text, mode=None):
    return atomic_write_bytes(path, text.encode("utf-8"), mode=mode)

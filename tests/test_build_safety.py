from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from build_safety import atomic_write_bytes, resolve_build_paths


def test_build_dir_is_mandatory_by_default(tmp_path):
    with pytest.raises(ValueError, match="ICT_BUILD_DIR is required"):
        resolve_build_paths(tmp_path / "source", {})


def test_build_cannot_equal_source_without_explicit_legacy_override(tmp_path):
    source = tmp_path / "source"
    with pytest.raises(ValueError, match="must differ"):
        resolve_build_paths(source, {"ICT_BUILD_DIR": str(source)})


def test_output_and_key_cannot_escape_isolated_build(tmp_path):
    source = tmp_path / "source"
    build = tmp_path / "build"
    with pytest.raises(ValueError, match="ICT_OUTPUT_FILE must stay"):
        resolve_build_paths(source, {
            "ICT_BUILD_DIR": str(build),
            "ICT_OUTPUT_FILE": str(source / "ict-vault.kevin"),
        })
    with pytest.raises(ValueError, match="ICT_VAULT_KEY_FILE must stay"):
        resolve_build_paths(source, {
            "ICT_BUILD_DIR": str(build),
            "ICT_VAULT_KEY_FILE": str(source / ".vault_key"),
        })


def test_isolated_defaults_all_live_inside_build(tmp_path):
    source = tmp_path / "source"
    build = tmp_path / "build"
    src, root, output, key, hash_file = resolve_build_paths(
        source, {"ICT_BUILD_DIR": str(build)}
    )
    assert src == source.resolve()
    assert root == build.resolve()
    assert output == build.resolve() / "ict-vault.kevin"
    assert key == build.resolve() / ".vault_key"
    assert hash_file == build.resolve() / ".vault_sha256"


def test_atomic_write_replaces_complete_target_and_cleans_temp(tmp_path):
    target = tmp_path / "artifact"
    target.write_bytes(b"old")
    atomic_write_bytes(target, b"new")
    assert target.read_bytes() == b"new"
    assert not list(tmp_path.glob(".artifact.*.tmp"))

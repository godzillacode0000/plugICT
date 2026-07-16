from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from artifact_paths import resolve_artifact_dir


def test_isolated_build_dir_wins_over_legacy_source_dir():
    env = {"ICT_SOURCE_DIR": "C:/old-v2", "ICT_BUILD_DIR": "D:/candidate-v3"}
    assert resolve_artifact_dir("C:/fallback", env) == Path("D:/candidate-v3")


def test_source_dir_remains_backward_compatible_without_build_dir():
    env = {"ICT_SOURCE_DIR": "C:/legacy"}
    assert resolve_artifact_dir("C:/fallback", env) == Path("C:/legacy")


def test_default_is_used_when_no_override_exists():
    assert resolve_artifact_dir("C:/fallback", {}) == Path("C:/fallback")

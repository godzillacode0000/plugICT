import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from build_integrity import (  # noqa: E402
    finalize_ingestion_attestation,
    verify_completed_ingestion,
)
from ingest_resume import make_resume_manifest, write_manifest_atomic  # noqa: E402


class FakeCollection:
    def __init__(self, ids, metadata):
        self.ids = list(ids)
        self.metadata = dict(metadata)

    def count(self):
        return len(self.ids)

    def get(self, include=None):
        return {"ids": list(self.ids)}

    def modify(self, metadata):
        self.metadata = dict(metadata)


def _fixture(tmp_path, completed=True):
    build = tmp_path / "build"
    build.mkdir()
    (build / "_vectors").mkdir()
    db = sqlite3.connect(build / "kg.db")
    db.execute("CREATE VIRTUAL TABLE transcripts_fts USING fts5(chunk_id, content)")
    db.executemany("INSERT INTO transcripts_fts VALUES (?, ?)", [("a", "one"), ("b", "two")])
    db.execute("CREATE TABLE vault_metadata(key TEXT PRIMARY KEY, value TEXT)")
    db.executemany(
        "INSERT INTO vault_metadata VALUES (?, ?)",
        [("corpus_manifest_hash", "c" * 64), ("chunk_count", "2")],
    )
    db.commit()
    build_id = "build-123"
    manifest = {
        "schema_version": 2,
        "build_id": build_id,
        "corpus_manifest_hash": "c" * 64,
        "chunker_config": {},
        "embedding_meta": {},
        "expected_final_chunks": 2,
    }
    if completed:
        manifest.update({"ingestion_state": "complete", "final_chunk_count": 2})
        db.executemany(
            "INSERT OR REPLACE INTO vault_metadata VALUES (?, ?)",
            [("build_id", build_id), ("ingestion_state", "complete"),
             ("final_chunk_count", "2")],
        )
        db.commit()
    db.close()
    write_manifest_atomic(build / ".ict-v3-resume-manifest.json", manifest)
    collection = FakeCollection(
        ["a", "b"],
        {"build_id": build_id,
         "ingestion_state": "complete" if completed else "building",
         "final_chunk_count": 2 if completed else 0},
    )
    return build, collection, manifest


def test_build_verifier_accepts_only_exact_completed_identity(tmp_path):
    build, collection, _ = _fixture(tmp_path)

    result = verify_completed_ingestion(build, collection=collection)

    assert result["build_id"] == "build-123"
    assert result["final_chunk_count"] == 2


def test_build_verifier_rejects_incomplete_manifest(tmp_path):
    build, collection, _ = _fixture(tmp_path, completed=False)

    with pytest.raises(RuntimeError, match="manifest is not complete"):
        verify_completed_ingestion(build, collection=collection)


def test_build_verifier_rejects_mixed_build_identity(tmp_path):
    build, collection, _ = _fixture(tmp_path)
    collection.metadata["build_id"] = "stale-vectors"

    with pytest.raises(RuntimeError, match="build_id"):
        verify_completed_ingestion(build, collection=collection)


def test_build_verifier_rejects_fts_chroma_id_mismatch(tmp_path):
    build, collection, _ = _fixture(tmp_path)
    collection.ids = ["a", "different"]

    with pytest.raises(RuntimeError, match="ID parity"):
        verify_completed_ingestion(build, collection=collection)


def test_final_attestation_stamps_all_three_artifacts_last(tmp_path):
    build, collection, manifest = _fixture(tmp_path, completed=False)
    db = sqlite3.connect(build / "kg.db")

    finalized = finalize_ingestion_attestation(
        db, collection, build / ".ict-v3-resume-manifest.json",
        manifest, expected_ids={"a", "b"},
    )
    db.close()

    assert finalized["ingestion_state"] == "complete"
    verify_completed_ingestion(build, collection=collection)

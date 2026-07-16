"""Fail-closed identity and parity checks for V3 ingestion artifacts."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

from ingest_resume import MANIFEST_SCHEMA, write_manifest_atomic

MANIFEST_NAME = ".ict-v3-resume-manifest.json"
COMPLETE = "complete"
_TRANSCRIPT_EXCLUDES = {"index.md", "README.md", "CATALOG.md"}


def snapshot_source_corpus(source_dir):
    """Read the exact transcript bytes once and derive the ingestion manifest hash."""
    paths = [
        path for path in sorted(Path(source_dir).glob("*.md"))
        if path.name not in _TRANSCRIPT_EXCLUDES
    ]
    if not paths:
        raise RuntimeError("source corpus contains no transcript Markdown files")
    digest = hashlib.sha256()
    snapshot = []
    for path in paths:
        content = path.read_bytes()
        digest.update(path.name.encode("utf-8"))
        digest.update(hashlib.sha256(content).digest())
        snapshot.append((path, content))
    return snapshot, digest.hexdigest()


def verify_source_corpus(source_dir, expected_hash):
    snapshot, actual_hash = snapshot_source_corpus(source_dir)
    if actual_hash != expected_hash:
        raise RuntimeError("source corpus hash does not match the completed ingestion attestation")
    return snapshot


def _read_manifest(build_dir):
    path = Path(build_dir) / MANIFEST_NAME
    if not path.is_file():
        raise RuntimeError(f"completed ingestion manifest is missing: {path}")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"completed ingestion manifest is unreadable: {exc}") from exc
    if manifest.get("schema_version") != MANIFEST_SCHEMA:
        raise RuntimeError("completed ingestion manifest has the wrong schema")
    if not manifest.get("build_id"):
        raise RuntimeError("completed ingestion manifest has no build_id")
    return path, manifest


def _metadata(db):
    try:
        return dict(db.execute("SELECT key, value FROM vault_metadata").fetchall())
    except sqlite3.Error as exc:
        raise RuntimeError(f"kg.db has no readable vault_metadata: {exc}") from exc


def _fts_ids(db):
    try:
        rows = [str(row[0]) for row in db.execute("SELECT chunk_id FROM transcripts_fts")]
    except sqlite3.Error as exc:
        raise RuntimeError(f"kg.db has no readable transcripts_fts: {exc}") from exc
    if len(rows) != len(set(rows)):
        raise RuntimeError("kg.db contains duplicate chunk IDs")
    return set(rows)


def _open_collection(build_dir):
    try:
        import chromadb
        from chromadb.config import Settings
        client = chromadb.PersistentClient(
            path=str(Path(build_dir) / "_vectors"),
            settings=Settings(anonymized_telemetry=False),
        )
        return client.get_collection("ict_vault")
    except Exception as exc:
        raise RuntimeError(f"Chroma collection is unreadable: {exc}") from exc


def _collection_ids(collection):
    try:
        rows = [str(value) for value in (collection.get(include=[]).get("ids") or [])]
    except Exception as exc:
        raise RuntimeError(f"Chroma chunk IDs are unreadable: {exc}") from exc
    if len(rows) != len(set(rows)):
        raise RuntimeError("Chroma contains duplicate chunk IDs")
    return set(rows)


def _positive_int(value, label):
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{label} is not a valid integer") from exc
    if parsed <= 0:
        raise RuntimeError(f"{label} must be positive")
    return parsed


def verify_completed_ingestion(build_dir, collection=None):
    """Require one completed build identity across manifest, kg.db, and Chroma."""
    build_dir = Path(build_dir)
    _, manifest = _read_manifest(build_dir)
    if manifest.get("ingestion_state") != COMPLETE:
        raise RuntimeError("ingestion manifest is not complete")
    final_count = _positive_int(manifest.get("final_chunk_count"), "manifest final_chunk_count")
    expected = int(manifest.get("expected_final_chunks") or 0)
    if expected and expected != final_count:
        raise RuntimeError("manifest expected/final chunk counts do not match")

    db_path = build_dir / "kg.db"
    if not db_path.is_file():
        raise RuntimeError("kg.db is missing")
    db = sqlite3.connect(str(db_path))
    try:
        metadata = _metadata(db)
        fts_ids = _fts_ids(db)
    finally:
        db.close()

    build_id = str(manifest["build_id"])
    if metadata.get("build_id") != build_id:
        raise RuntimeError("kg.db build_id does not match the manifest build_id")
    if metadata.get("ingestion_state") != COMPLETE:
        raise RuntimeError("kg.db ingestion state is not complete")
    if _positive_int(metadata.get("final_chunk_count"), "kg.db final_chunk_count") != final_count:
        raise RuntimeError("kg.db final chunk count does not match the manifest")
    if metadata.get("corpus_manifest_hash") != manifest.get("corpus_manifest_hash"):
        raise RuntimeError("kg.db corpus identity does not match the manifest")

    collection = collection or _open_collection(build_dir)
    collection_meta = dict(collection.metadata or {})
    if str(collection_meta.get("build_id") or "") != build_id:
        raise RuntimeError("Chroma build_id does not match the manifest build_id")
    if collection_meta.get("ingestion_state") != COMPLETE:
        raise RuntimeError("Chroma ingestion state is not complete")
    if _positive_int(collection_meta.get("final_chunk_count"), "Chroma final_chunk_count") != final_count:
        raise RuntimeError("Chroma final chunk count does not match the manifest")
    chroma_ids = _collection_ids(collection)
    if len(fts_ids) != final_count or len(chroma_ids) != final_count:
        raise RuntimeError("completed chunk counts do not match actual indexes")
    if fts_ids != chroma_ids:
        raise RuntimeError("FTS/Chroma chunk-ID parity failed")

    return {
        "build_id": build_id,
        "final_chunk_count": final_count,
        "corpus_manifest_hash": manifest.get("corpus_manifest_hash"),
    }


def finalize_ingestion_attestation(db, collection, manifest_path, manifest, expected_ids):
    """Publish completion markers after exact FTS/Chroma parity succeeds."""
    manifest_path = Path(manifest_path)
    manifest = dict(manifest)
    if manifest.get("schema_version") != MANIFEST_SCHEMA or not manifest.get("build_id"):
        raise RuntimeError("cannot attest an invalid ingestion manifest")
    build_id = str(manifest["build_id"])
    metadata = _metadata(db)
    if metadata.get("corpus_manifest_hash") != manifest.get("corpus_manifest_hash"):
        raise RuntimeError("cannot attest mismatched corpus identities")

    expected_ids = {str(value) for value in expected_ids}
    fts_ids = _fts_ids(db)
    chroma_ids = _collection_ids(collection)
    if not expected_ids or fts_ids != expected_ids or chroma_ids != expected_ids:
        raise RuntimeError("cannot attest without exact FTS/Chroma ID parity")
    collection_meta = dict(collection.metadata or {})
    if str(collection_meta.get("build_id") or "") != build_id:
        raise RuntimeError("cannot attest a Chroma collection with a different build_id")

    final_count = len(expected_ids)
    completed_collection_meta = dict(collection_meta)
    completed_collection_meta.update({
        "build_id": build_id,
        "ingestion_state": COMPLETE,
        "final_chunk_count": final_count,
    })
    collection.modify(metadata=completed_collection_meta)

    db.executemany(
        "INSERT OR REPLACE INTO vault_metadata(key, value) VALUES (?, ?)",
        [("build_id", build_id), ("ingestion_state", COMPLETE),
         ("final_chunk_count", str(final_count))],
    )
    db.commit()

    completed_manifest = dict(manifest)
    completed_manifest.update({
        "expected_final_chunks": final_count,
        "ingestion_state": COMPLETE,
        "final_chunk_count": final_count,
    })
    write_manifest_atomic(manifest_path, completed_manifest)
    return completed_manifest


def attest_existing_build(build_dir):
    """Explicitly attest an already-verified pre-schema build; never called by build.py."""
    build_dir = Path(build_dir)
    manifest_path, manifest = _read_manifest(build_dir)
    collection = _open_collection(build_dir)
    db = sqlite3.connect(str(build_dir / "kg.db"))
    try:
        expected_ids = _fts_ids(db)
        finalized = finalize_ingestion_attestation(
            db, collection, manifest_path, manifest, expected_ids,
        )
    finally:
        db.close()
    verify_completed_ingestion(build_dir, collection=collection)
    return finalized


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "--attest-existing":
        raise SystemExit("Usage: python build_integrity.py --attest-existing <build_dir>")
    result = attest_existing_build(Path(sys.argv[2]))
    print(f"INGESTION_ATTESTATION=PASS build_id={result['build_id']} chunks={result['final_chunk_count']}")

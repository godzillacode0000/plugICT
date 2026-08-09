#!/usr/bin/env python3
"""Export and migrate PlugICT's *existing* vault index.

This is deliberately an exporter, not a re-embedding pipeline. The encrypted
vault already contains:

* 21,899 semantic-v3.0.0 chunks in SQLite/FTS5;
* an existing BAAI/bge-small-en-v1.5 (384-dimensional) Chroma index.

The exporter preserves the vault's chunk IDs, text, timestamps, metadata, and
active Chroma vectors. It writes migration artifacts locally first:

  export/chunks.ndjson       all FTS chunks (21,899 expected)
  export/vectors.ndjson      active Chroma vectors (21,376 in the current vault)
  export/transcripts.ndjson  exact full transcript snapshot used for R2
  export/export-report.json  parity/count report, including missing vectors

Only ``--stage upload`` performs Cloudflare writes. It is resumable by ID:
Vectorize upserts, D1 rows are deleted/reinserted per chunk, and R2 keys are
immutable content-addressed paths derived from each authoritative source file.

Environment for the local vault:
  ICT_OPEN_VAULT_BYPASS=1
  HF_HOME=D:/PlugICT/plugICT-install-test/.hf-home
  ICT_TEMP_DIR=D:/PlugICT/plugICT-install-test/.tmp

Examples:
  export_existing_vault.py --stage export
  export_existing_vault.py --stage verify --export-dir cloudflare/ingest-existing
  export_existing_vault.py --stage upload --r2-only  # R2 objects first
  export_existing_vault.py --stage upload            # R2 -> Vectorize -> D1
"""

from __future__ import annotations

import argparse
import json
import os
import pickle
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Iterable

from vault_export_integrity import (
    finalize_manifest,
    r2_key_for_transcript,
    validate_export,
    validate_r2_credentials,
)

VAULT_DIR = Path(os.environ.get("PLUGICT_VAULT_DIR", r"D:/PlugICT/plugICT-install-test"))
REPO_DIR = Path(os.environ.get("PLUGICT_REPO_DIR", r"D:/PlugICT/landing-repo-coderabbit"))
DEFAULT_EXPORT_DIR = REPO_DIR / "cloudflare" / "ingest-existing"
DEFAULT_DIMENSION = 384
EXPECTED_CHUNKS = 21_899
R2_FREE_TIER_BYTES = 10_000_000_000
# Keep one decimal GB of account-level headroom for object metadata/anything
# else that may be stored in the account. This is a hard cap, not a warning.
R2_UPLOAD_SAFETY_CAP_BYTES = 9_000_000_000

NPX = str(Path(r"C:/Program Files/nodejs/npx.cmd")) if os.name == "nt" else "npx"


def _json_value(string_value: Any, int_value: Any, float_value: Any, bool_value: Any) -> Any:
    if string_value is not None:
        return string_value
    if int_value is not None:
        return int_value
    if float_value is not None:
        return float_value
    if bool_value is not None:
        return bool(bool_value)
    return None


def _as_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _metadata_for_vector(meta: dict[str, Any]) -> dict[str, Any]:
    """Return Vectorize-safe metadata while preserving source provenance."""
    names = (
        "video_id",
        "title",
        "playlist",
        "chunk_index",
        "start_ts",
        "end_ts",
        "start_seconds",
        "end_seconds",
        "source_file",
        "timing_precision",
        "chunker_version",
        "content_hash",
    )
    out: dict[str, Any] = {"contentType": "transcript_chunk"}
    for name in names:
        value = meta.get(name)
        if value is not None and value != "":
            if name in {"chunk_index", "start_seconds", "end_seconds"}:
                value = _as_int(value)
            if value is not None:
                out[name] = value
    return out


def _open_vault():
    os.environ.setdefault("ICT_OPEN_VAULT_BYPASS", "1")
    os.environ.setdefault("HF_HOME", str(VAULT_DIR / ".hf-home"))
    os.environ.setdefault("ICT_TEMP_DIR", str(VAULT_DIR / ".tmp"))
    sys.path.insert(0, str(VAULT_DIR))
    import vault_core  # type: ignore

    db, chroma_dir, licensed_to = vault_core.open_vault()
    return vault_core, db, Path(chroma_dir), licensed_to


class _DataOnlyUnpickler(pickle.Unpickler):
    def find_class(self, module: str, name: str):
        raise pickle.UnpicklingError(f"Executable pickle global rejected: {module}.{name}")

    def persistent_load(self, pid):
        raise pickle.UnpicklingError(f"Persistent pickle reference rejected: {pid!r}")


def _find_hnsw_segment(chroma_dir: Path) -> tuple[Path, dict[str, Any]]:
    candidates = sorted(chroma_dir.rglob("index_metadata.pickle"))
    candidates = [p for p in candidates if (p.parent / "data_level0.bin").exists()]
    if len(candidates) != 1:
        raise RuntimeError(f"Expected exactly one persisted HNSW segment; found {len(candidates)}")
    path = candidates[0]
    with path.open("rb") as handle:
        metadata = _DataOnlyUnpickler(handle).load()
    if not isinstance(metadata, dict) or not metadata.get("id_to_label"):
        raise RuntimeError(f"HNSW metadata is missing id_to_label: {path}")
    return path.parent, metadata


def _read_fts_rows(db: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    columns = [row[1] for row in db.execute("PRAGMA table_info(transcripts_fts)").fetchall()]
    required = {"chunk_id", "content", "video_id", "title", "playlist", "start_ts", "end_ts"}
    missing = required - set(columns)
    if missing:
        raise RuntimeError(f"Vault FTS schema missing required columns: {sorted(missing)}")

    wanted = [
        "chunk_id",
        "title",
        "video_id",
        "playlist",
        "start_ts",
        "end_ts",
        "source_file",
        "content",
        "chunk_index",
        "start_seconds",
        "end_seconds",
        "timing_precision",
        "chunker_version",
        "content_hash",
    ]
    selected = [name for name in wanted if name in columns]
    rows = db.execute(
        "SELECT " + ", ".join(selected) + " FROM transcripts_fts"
    ).fetchall()
    ids = [str(row[selected.index("chunk_id")]) for row in rows]
    if len(set(ids)) != len(ids):
        duplicates = sorted({chunk_id for chunk_id in ids if ids.count(chunk_id) > 1})[:5]
        raise RuntimeError(f"Duplicate chunk_id rows in transcripts_fts: {duplicates}")
    return {
        chunk_id: dict(zip(selected, row))
        for chunk_id, row in zip(ids, rows)
    }


def _read_chroma_metadata(chroma_dir: Path) -> dict[str, dict[str, Any]]:
    """Read Chroma's SQLite metadata without relying on an incompatible client."""
    chroma_db = sqlite3.connect(str(chroma_dir / "chroma.sqlite3"))
    try:
        rows = chroma_db.execute(
            """
            SELECT e.embedding_id, m.key, m.string_value, m.int_value,
                   m.float_value, m.bool_value
              FROM embeddings AS e
              JOIN embedding_metadata AS m ON m.id = e.id
             ORDER BY e.id, m.key
            """
        ).fetchall()
    finally:
        chroma_db.close()

    out: dict[str, dict[str, Any]] = {}
    for embedding_id, key, string_value, int_value, float_value, bool_value in rows:
        out.setdefault(str(embedding_id), {})[key] = _json_value(
            string_value, int_value, float_value, bool_value
        )
    return out


def _load_hnsw(chroma_dir: Path, hnsw_metadata: dict[str, Any], dimension: int):
    try:
        import hnswlib  # type: ignore
    except ImportError as exc:
        raise RuntimeError("The vault venv must provide hnswlib to export existing vectors") from exc

    index = hnswlib.Index(space="l2", dim=dimension)
    # Chroma loads with a resized capacity; using 2x is safe for this persisted index.
    capacity = max(int(hnsw_metadata.get("total_elements_added", 0)) * 2, 1_000)
    index.load_index(
        str(chroma_dir),
        is_persistent_index=True,
        max_elements=capacity,
    )
    return index


def _iter_active_records(
    db: sqlite3.Connection,
    chroma_dir: Path,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, Any]]:
    """Build deterministic active-vector records and complete chunk lookup."""
    fts = _read_fts_rows(db)
    chroma_meta = _read_chroma_metadata(chroma_dir)
    hnsw_dir, hnsw_metadata = _find_hnsw_segment(chroma_dir)

    db_meta = dict(db.execute(
        "SELECT key, value FROM vault_metadata WHERE key IN "
        "('embedding_model_name', 'embedding_dimension', 'embedding_normalize', "
        "'embedding_revision', 'query_instruction_version', 'vector_schema_version')"
    ).fetchall())
    dimension = int(db_meta.get("embedding_dimension", DEFAULT_DIMENSION))
    index = _load_hnsw(hnsw_dir, hnsw_metadata, dimension)

    active: list[dict[str, Any]] = []
    missing_metadata: list[str] = []
    missing_fts: list[str] = []
    text_mismatches: list[str] = []
    missing_chroma_document: list[str] = []

    for embedding_id, label in hnsw_metadata["id_to_label"].items():
        embedding_id = str(embedding_id)
        meta = chroma_meta.get(embedding_id)
        if not meta or not meta.get("chunk_id"):
            missing_metadata.append(embedding_id)
            continue
        chunk_id = str(meta["chunk_id"])
        row = fts.get(chunk_id)
        if row is None:
            missing_fts.append(chunk_id)
            continue
        # The original Chroma document binding must be exact whenever it
        # exists. A vector whose stored document differs from the FTS text is
        # a parity break, not an exportable record.
        if meta.get("chroma:document") is not None and meta["chroma:document"] != row["content"]:
            text_mismatches.append(chunk_id)
        if meta.get("chroma:document") is None:
            missing_chroma_document.append(embedding_id)
        merged = dict(row)
        merged["embedding_id"] = embedding_id
        merged["label"] = int(label)
        merged["vector_metadata"] = _metadata_for_vector(merged)
        active.append(merged)

    active.sort(key=lambda row: str(row["chunk_id"]))
    lookup = {str(row["chunk_id"]): row for row in fts.values()}
    report = {
        "chunk_count": len(fts),
        "expected_chunk_count": EXPECTED_CHUNKS,
        "hnsw_active_vector_count": len(hnsw_metadata["id_to_label"]),
        "chroma_embedding_row_count": len(chroma_meta),
        "exportable_vector_count": len(active),
        "chunks_without_active_vector": len(fts) - len(active),
        "missing_vector_metadata_count": len(missing_metadata),
        "active_vectors_without_fts_row_count": len(missing_fts),
        "missing_chroma_document_count": len(missing_chroma_document),
        "text_mismatch_count": len(text_mismatches),
        "embedding_metadata": db_meta,
        "chunker_version_counts": dict(db.execute(
            "SELECT chunker_version, COUNT(*) FROM transcripts_fts GROUP BY chunker_version"
        ).fetchall()),
        "missing_vector_samples": sorted(set(fts) - {str(row["chunk_id"]) for row in active})[:20],
        "missing_metadata_samples": missing_metadata[:20],
        "missing_fts_samples": missing_fts[:20],
        "missing_chroma_document_samples": missing_chroma_document[:20],
        "text_mismatch_samples": text_mismatches[:20],
        "hnsw_segment": hnsw_dir.name,
        "hnsw_total_elements_added": hnsw_metadata.get("total_elements_added"),
        "hnsw_index": index,
    }
    return active, lookup, report


def _write_export(
    db: sqlite3.Connection,
    chroma_dir: Path,
    export_dir: Path,
) -> dict[str, Any]:
    active, all_chunks, report = _iter_active_records(db, chroma_dir)
    index = report.pop("hnsw_index")
    hnsw_meta = report.pop("hnsw_segment")
    export_dir.mkdir(parents=True, exist_ok=True)

    # All chunk text/metadata, including the 523 chunks that currently have no
    # active HNSW vector. These remain available to D1/FTS fallback.
    active_ids = {str(item["chunk_id"]) for item in active}
    chunks_path = export_dir / "chunks.ndjson"
    with chunks_path.open("w", encoding="utf-8") as handle:
        for chunk_id in sorted(all_chunks):
            row = all_chunks[chunk_id]
            handle.write(json.dumps({
                "id": chunk_id,
                "text": row["content"],
                "metadata": _metadata_for_vector(row),
                "has_vector": chunk_id in active_ids,
            }, ensure_ascii=False, separators=(",", ":")) + "\n")

    # Existing active Chroma vectors only. No model is loaded and no text is
    # re-embedded here.
    vectors_path = export_dir / "vectors.ndjson"
    labels = [int(row["label"]) for row in active]
    with vectors_path.open("w", encoding="utf-8") as handle:
        batch_size = 512
        for start in range(0, len(active), batch_size):
            batch = active[start:start + batch_size]
            vectors = index.get_items(labels[start:start + batch_size])
            for row, vector in zip(batch, vectors):
                handle.write(json.dumps({
                    "id": str(row["chunk_id"]),
                    "values": [float(value) for value in vector],
                    "metadata": row["vector_metadata"],
                }, ensure_ascii=False, separators=(",", ":")) + "\n")

    # R2 is populated from this immutable export snapshot, never by reopening a
    # potentially changed live vault during the upload stage.
    transcripts_path = export_dir / "transcripts.ndjson"
    transcript_rows = db.execute(
        "SELECT filename, video_id, content FROM transcript_files ORDER BY filename"
    ).fetchall()
    with transcripts_path.open("w", encoding="utf-8") as handle:
        for source_file, video_id, content in transcript_rows:
            source_file = str(source_file)
            content = str(content or "")
            handle.write(json.dumps({
                "source_file": source_file,
                "video_id": str(video_id),
                "r2_key": r2_key_for_transcript(source_file, content),
                "content": content,
            }, ensure_ascii=False, separators=(",", ":")) + "\n")

    # Keep a compact parity report, not the licence or any credential. The
    # manifest is hash-bound and written only after every artifact is complete.
    report["exported_chunks_path"] = str(chunks_path)
    report["exported_vectors_path"] = str(vectors_path)
    report["exported_transcripts_path"] = str(transcripts_path)
    report["transcript_count"] = len(transcript_rows)
    report["exported_at"] = int(time.time())
    report["active_vector_ids_are_chunk_ids"] = True
    return finalize_manifest(export_dir, report)


def _run_wrangler(args: list[str]) -> None:
    result = subprocess.run(
        [NPX, "wrangler", *args],
        cwd=str(REPO_DIR),
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode:
        raise RuntimeError(
            f"wrangler {' '.join(args[:4])} failed:\n{result.stderr[-1200:]}"
        )


def _sql(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def _read_ndjson(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def _load_snapshot(export_dir: Path) -> dict[str, list[dict[str, Any]]]:
    """Read every artifact exactly once into a private in-memory snapshot.

    All uploads run against this snapshot. Nothing after this point ever
    re-opens the mutable artifacts on disk, so a file changed mid-run cannot
    reach Cloudflare. The snapshot is read BEFORE disk validation; any
    mutation that lands between the read and validation is caught by
    ``validate_export``'s manifest hash bindings, and any mutation after
    validation cannot affect the in-memory rows.
    """
    return {
        "chunks": list(_read_ndjson(export_dir / "chunks.ndjson")),
        "vectors": list(_read_ndjson(export_dir / "vectors.ndjson")),
        "transcripts": list(_read_ndjson(export_dir / "transcripts.ndjson")),
    }


def _verify_snapshot(snapshot: dict[str, list[dict[str, Any]]], manifest: dict[str, Any]) -> None:
    """Re-derive the critical cross-artifact bindings from the in-memory rows.

    This is the upload-stage gate: it runs against the exact rows that will
    be uploaded, so a mutation between validation and upload is impossible to
    smuggle past it (content-addressed keys, counts, and source bindings are
    all re-derived from the snapshot itself).
    """
    transcripts = snapshot["transcripts"]
    chunks = snapshot["chunks"]
    vectors = snapshot["vectors"]
    if not transcripts or not chunks or not vectors:
        raise RuntimeError("Upload snapshot is empty; refusing all uploads")

    transcript_sources: dict[str, str] = {}
    transcript_keys: set[str] = set()
    for row in transcripts:
        source_file = str(row.get("source_file", ""))
        r2_key = str(row.get("r2_key", ""))
        content = str(row.get("content", ""))
        if not source_file or not content or not r2_key:
            raise RuntimeError("Transcript snapshot row is missing source_file/content/r2_key")
        if source_file in transcript_sources:
            raise RuntimeError(f"Duplicate transcript source_file in snapshot: {source_file}")
        if r2_key != r2_key_for_transcript(source_file, content):
            raise RuntimeError(f"Transcript snapshot key does not match its content: {source_file}")
        if r2_key in transcript_keys:
            raise RuntimeError(f"Duplicate transcript r2_key in snapshot: {r2_key}")
        transcript_sources[source_file] = r2_key
        transcript_keys.add(r2_key)

    chunk_sources: set[str] = set()
    chunk_ids: set[str] = set()
    vector_id_set = {str(v.get("id", "")) for v in vectors if v.get("id")}
    vector_ids: set[str] = set()
    for row in chunks:
        chunk_id = str(row.get("id", ""))
        source_file = str(row.get("metadata", {}).get("source_file", ""))
        if not chunk_id or chunk_id in chunk_ids:
            raise RuntimeError(f"Chunk snapshot has a missing or duplicate id: {chunk_id}")
        if source_file not in transcript_sources:
            raise RuntimeError(f"Chunk source has no snapshot R2 object: {source_file}")
        chunk_ids.add(chunk_id)
        chunk_sources.add(source_file)
        if row.get("has_vector") and chunk_id not in vector_id_set:
            raise RuntimeError(f"Chunk {chunk_id} claims a vector that is absent from the snapshot")
    for row in vectors:
        vector_id = str(row.get("id", ""))
        if not vector_id or vector_id in vector_ids:
            raise RuntimeError(f"Vector snapshot has a missing or duplicate id: {vector_id}")
        if vector_id not in chunk_ids:
            raise RuntimeError(f"Vector snapshot references an unknown chunk: {vector_id}")
        vector_ids.add(vector_id)
    if chunk_sources != set(transcript_sources):
        raise RuntimeError("Chunk snapshot sources do not exactly match transcript snapshot sources")

    counts = {
        "chunk_count": len(chunk_ids),
        "vector_count": len(vector_ids),
        "transcript_count": len(transcript_sources),
    }
    for key, actual in counts.items():
        expected = int(manifest.get("artifact_counts", {}).get(key, -1))
        if actual != expected:
            raise RuntimeError(f"Snapshot {key}={actual}; validated manifest expects {expected}")


def _upload_vectors(vectors: list[dict[str, Any]], batch_size: int = 500,
                    scratch_dir: Path | None = None) -> int:
    batch: list[dict[str, Any]] = []
    uploaded = 0
    scratch = scratch_dir or Path(tempfile.gettempdir())
    for row in vectors:
        batch.append(row)
        if len(batch) == batch_size:
            path = scratch / f"_upload-vectors-{os.getpid()}-{threading.get_ident()}.ndjson"
            path.write_text(
                "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in batch),
                encoding="utf-8",
            )
            _run_wrangler(["vectorize", "upsert", "plugict-vault-index", "--file", str(path)])
            path.unlink(missing_ok=True)
            uploaded += len(batch)
            batch.clear()
    if batch:
        path = scratch / f"_upload-vectors-{os.getpid()}-{threading.get_ident()}.ndjson"
        path.write_text(
            "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in batch),
            encoding="utf-8",
        )
        _run_wrangler(["vectorize", "upsert", "plugict-vault-index", "--file", str(path)])
        path.unlink(missing_ok=True)
        uploaded += len(batch)
    return uploaded


def _upload_d1_chunks(transcript_rows: list[dict[str, Any]], chunk_rows: list[dict[str, Any]],
                      batch_size: int = 100, scratch_dir: Path | None = None) -> int:
    batch: list[dict[str, Any]] = []
    uploaded = 0
    scratch = scratch_dir or Path(tempfile.gettempdir())
    transcript_keys: dict[str, str] = {}
    for transcript in transcript_rows:
        source_file = str(transcript.get("source_file", ""))
        r2_key = str(transcript.get("r2_key", ""))
        if not source_file or not r2_key or source_file in transcript_keys:
            raise RuntimeError("Transcript source/R2 index is incomplete or duplicated")
        transcript_keys[source_file] = r2_key

    # Fail before the first cloud write if any chunk cannot be mapped to its
    # exact immutable transcript object.
    for row in chunk_rows:
        source_file = str(row.get("metadata", {}).get("source_file", ""))
        if source_file not in transcript_keys:
            raise RuntimeError(f"Chunk source has no validated R2 object: {source_file}")

    def flush(rows: list[dict[str, Any]], batch_number: int) -> None:
        if not rows:
            return
        statements = []
        ids = ", ".join(_sql(row["id"]) for row in rows)
        statements.append(f"DELETE FROM vault_fts WHERE chunk_id IN ({ids});")
        for row in rows:
            meta = row["metadata"]
            r2_key = transcript_keys[str(meta.get("source_file", ""))]
            statements.append(
                "INSERT INTO vault_fts (chunk_id, title, video_id, playlist, start_ts, end_ts, "
                "start_seconds, end_seconds, source_file, timing_precision, chunker_version, "
                "content_hash, content) VALUES ("
                + ", ".join(_sql(value) for value in (
                    row["id"], meta.get("title", ""), meta.get("video_id", ""),
                    meta.get("playlist", ""), meta.get("start_ts", ""), meta.get("end_ts", ""),
                    meta.get("start_seconds"), meta.get("end_seconds"), meta.get("source_file", ""),
                    meta.get("timing_precision", ""), meta.get("chunker_version", ""),
                    meta.get("content_hash", ""), row["text"],
                ))
                + ");"
            )
            statements.append(
                "INSERT OR REPLACE INTO vault_chunks "
                "(id, video_id, chunk_idx, r2_key, title, playlist, char_count, start_ts, end_ts, "
                "start_seconds, end_seconds, source_file, timing_precision, chunker_version, "
                "content_hash, has_vector, created_at) VALUES ("
                + ", ".join(_sql(value) for value in (
                    row["id"], meta.get("video_id", ""), meta.get("chunk_index", 0),
                    r2_key, meta.get("title", ""),
                    meta.get("playlist", ""), len(row["text"]), meta.get("start_ts", ""),
                    meta.get("end_ts", ""), meta.get("start_seconds"), meta.get("end_seconds"),
                    meta.get("source_file", ""), meta.get("timing_precision", ""),
                    meta.get("chunker_version", ""), meta.get("content_hash", ""),
                    1 if row.get("has_vector") else 0, int(time.time()),
                ))
                + ");"
            )
        path = scratch / f"_upload-d1-{os.getpid()}-{batch_number:04d}.sql"
        path.write_text("\n".join(statements), encoding="utf-8")
        _run_wrangler(["d1", "execute", "plugict-chat-db", "--remote", "--file", str(path)])
        path.unlink(missing_ok=True)

    for row in chunk_rows:
        batch.append(row)
        if len(batch) == batch_size:
            flush(batch, uploaded // batch_size)
            uploaded += len(batch)
            batch.clear()
    if batch:
        flush(batch, uploaded // batch_size)
        uploaded += len(batch)
    return uploaded


def _upload_r2(transcript_rows: list[dict[str, Any]], workers: int = 1,
               s3_creds_file: Path | None = None,
               scratch_dir: Path | None = None) -> int:
    """Upload transcript files only after a hard account-size preflight.

    ``workers`` spawns that many parallel uploads; each object is uploaded
    exactly once and keys are stable, so re-running after a partial run simply
    re-puts the same keys. The cumulative byte gate is enforced thread-safely
    and can never let the upload cross the cap. Rows come from the validated
    in-memory snapshot; the mutable artifacts are never re-opened.

    Two transports:
    * ``s3_creds_file`` given -> direct S3-compatible API via boto3
      (fast, recommended; the JSON file holds endpoint/access_key_id/
      secret_access_key/bucket).
    * otherwise -> ``wrangler r2 object put --remote`` (MUST pass --remote;
      without it wrangler silently writes to the LOCAL miniflare simulator).
    """
    scratch = scratch_dir or Path(tempfile.gettempdir())
    rows = [
        (str(row["r2_key"]), str(row["content"]))
        for row in transcript_rows
    ]
    if len({key for key, _content in rows}) != len(rows):
        raise RuntimeError("R2 upload refused: duplicate object keys in transcript snapshot")
    sizes = [len((content or "").encode("utf-8")) for _key, content in rows]
    total_bytes = sum(sizes)
    print(json.dumps({
        "r2_preflight_files": len(rows),
        "r2_source_bytes": total_bytes,
        "r2_source_decimal_gb": total_bytes / 1_000_000_000,
        "r2_free_tier_bytes": R2_FREE_TIER_BYTES,
        "r2_hard_safety_cap_bytes": R2_UPLOAD_SAFETY_CAP_BYTES,
        "r2_workers": workers,
        "r2_transport": "s3" if s3_creds_file else "wrangler",
    }, indent=2), flush=True)
    if total_bytes > R2_UPLOAD_SAFETY_CAP_BYTES:
        raise RuntimeError(
            f"R2 upload refused: source is {total_bytes} bytes, above the hard "
            f"{R2_UPLOAD_SAFETY_CAP_BYTES}-byte safety cap"
        )

    s3 = None
    bucket = "plugict-vault"
    if s3_creds_file:
        import boto3  # noqa: PLC0415
        from botocore.config import Config as BotoConfig  # noqa: PLC0415
        cred = validate_r2_credentials(Path(s3_creds_file))
        s3 = boto3.client(
            "s3",
            endpoint_url=cred["endpoint"],
            aws_access_key_id=cred["access_key_id"],
            aws_secret_access_key=cred["secret_access_key"],
            region_name="auto",
            config=BotoConfig(s3={"addressing_style": "path"}, signature_version="s3v4"),
        )
        bucket = cred.get("bucket", bucket)

    lock = threading.Lock()
    uploaded_bytes = 0
    done = 0
    total = len(rows)

    def put_one(item: tuple[tuple[str, str], int]) -> None:
        nonlocal uploaded_bytes, done
        (key, content), size = item
        with lock:
            if uploaded_bytes + size > R2_UPLOAD_SAFETY_CAP_BYTES:
                raise RuntimeError("R2 upload stopped before crossing the hard safety cap")
            uploaded_bytes += size
        data = (content or "").encode("utf-8")
        if s3 is not None:
            s3.put_object(Bucket=bucket, Key=key, Body=data)
        else:
            path = scratch / f"_raw-transcript-{os.getpid()}-{threading.get_ident()}.md"
            try:
                path.write_bytes(data)
                _run_wrangler([
                    "r2", "object", "put", f"plugict-vault/{key}",
                    "--file", str(path), "--remote",
                ])
            finally:
                path.unlink(missing_ok=True)
        with lock:
            done += 1
            if done % 50 == 0 or done == total:
                print(f"R2 upload progress: {done}/{total} objects", flush=True)

    items = list(zip(rows, sizes))
    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(put_one, items))
    else:
        for item in items:
            put_one(item)
    print(f"R2 upload byte gate passed: {uploaded_bytes} bytes across {done} objects", flush=True)
    return done


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("verify", "export", "validate", "upload"), default="verify")
    parser.add_argument("--export-dir", type=Path, default=DEFAULT_EXPORT_DIR)
    parser.add_argument("--r2-only", action="store_true", help="Upload only original transcript files to R2")
    parser.add_argument("--r2-workers", type=int, default=1, help="Parallel R2 put processes (default 1)")
    parser.add_argument("--r2-s3-creds", type=Path, default=None,
                        help="JSON file with R2 S3 credentials (endpoint/access_key_id/secret_access_key/bucket) for fast boto3 upload")
    args = parser.parse_args()
    if args.r2_only and args.stage != "upload":
        raise SystemExit("--r2-only requires --stage upload")
    if args.r2_workers < 1:
        raise SystemExit("--r2-workers must be at least 1")

    if args.stage == "validate":
        try:
            manifest = validate_export(args.export_dir)
        except RuntimeError as exc:
            raise SystemExit(f"Export integrity validation failed: {exc}") from exc
        print(json.dumps({
            "export_manifest_validated": True,
            "artifact_counts": manifest["artifact_counts"],
        }, indent=2))
        return 0

    if args.stage in {"verify", "export"}:
        vault_core, db, chroma_dir, licensed_to = _open_vault()
        del vault_core
        print(f"✅ vault opened; licensed_to_present={bool(licensed_to)}")
        report = _write_export(db, chroma_dir, args.export_dir)
        print(json.dumps({
            key: report[key]
            for key in (
                "chunk_count",
                "hnsw_active_vector_count",
                "exportable_vector_count",
                "chunks_without_active_vector",
                "text_mismatch_count",
                "embedding_metadata",
            )
        }, indent=2))
        if report["text_mismatch_count"] or report["missing_metadata_samples"] or report["missing_fts_samples"]:
            raise SystemExit("Existing vault parity checks failed; refusing upload")
        missing_docs = report.get("missing_chroma_document_count", 0)
        if missing_docs and missing_docs != report.get("exportable_vector_count", 0):
            raise SystemExit(
                "Mixed Chroma document binding detected; every vector must carry "
                "the original document or none may (equivalent content-hash binding)"
            )
        return 0

    # Single private snapshot: every upload below uses ONLY these in-memory
    # rows. The snapshot is read BEFORE disk validation so any mutation that
    # lands before the read is caught by the manifest hash bindings; any
    # mutation after validation cannot influence the in-memory rows.
    snapshot = _load_snapshot(args.export_dir)
    try:
        manifest = validate_export(args.export_dir)
    except RuntimeError as exc:
        raise SystemExit(f"Export integrity validation failed; refusing all uploads: {exc}") from exc
    print(json.dumps({
        "export_manifest_validated": True,
        "artifact_counts": manifest["artifact_counts"],
    }, indent=2))

    _verify_snapshot(snapshot, manifest)

    if args.r2_only:
        count = _upload_r2(snapshot["transcripts"], workers=args.r2_workers, s3_creds_file=args.r2_s3_creds)
        if count != manifest["artifact_counts"]["transcript_count"]:
            raise RuntimeError("R2 upload count differs from validated manifest")
        print(json.dumps({"r2_transcripts_uploaded": count}, indent=2))
        return 0

    # Hard ordering: R2 -> Vectorize -> D1. Each stage verifies its own count
    # BEFORE the dependent stage may start; any shortfall aborts with zero
    # writes to the next service.
    print("R2 upload is enabled for this run; failures are fatal.")
    r2_count = _upload_r2(snapshot["transcripts"], workers=args.r2_workers, s3_creds_file=args.r2_s3_creds)
    if r2_count != manifest["artifact_counts"]["transcript_count"]:
        raise RuntimeError("R2 upload count differs from validated manifest; refusing Vectorize/D1")
    vector_count = _upload_vectors(snapshot["vectors"])
    if vector_count != manifest["artifact_counts"]["vector_count"]:
        raise RuntimeError("Vectorize upload count differs from validated manifest; refusing D1")
    # Publish D1 pointers last, only after every referenced immutable R2 object
    # and vector has been uploaded successfully.
    chunk_count = _upload_d1_chunks(snapshot["transcripts"], snapshot["chunks"])
    if chunk_count != manifest["artifact_counts"]["chunk_count"]:
        raise RuntimeError("D1 upload loop count differs from validated manifest")
    print(json.dumps({
        "vectorize_upserted": vector_count,
        "d1_chunks_uploaded": chunk_count,
        "r2_transcripts_uploaded": r2_count,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

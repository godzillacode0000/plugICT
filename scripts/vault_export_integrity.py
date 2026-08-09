"""Fail-closed integrity checks for PlugICT vault migration artifacts."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

FORMAT_VERSION = 1
DEFAULT_EXPECTATIONS: dict[str, Any] = {
    "chunk_count": 21_899,
    "vector_count": 21_376,
    "transcript_count": 775,
    "r2_object_count": 775,
    "unique_video_count": 774,
    "dimension": 384,
    "chunker_version": "semantic-v3.0.0",
    "embedding_model_name": "BAAI/bge-small-en-v1.5",
    "embedding_normalize": "true",
    "embedding_revision": "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a",
    "query_instruction_version": "bge-v1.5-no-query-instruction-v1",
    "vector_schema_version": "2",
}
ARTIFACTS = ("chunks.ndjson", "vectors.ndjson", "transcripts.ndjson")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _records(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"{path.name}:{line_number} is not valid JSON") from exc
            if not isinstance(row, dict):
                raise RuntimeError(f"{path.name}:{line_number} must contain a JSON object")
            yield line_number, row


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def r2_key_for_transcript(source_file: str, content: str) -> str:
    """Return an immutable key for one exact source-file/content pair."""
    digest = hashlib.sha256(
        source_file.encode("utf-8") + b"\0" + content.encode("utf-8")
    ).hexdigest()
    return f"transcripts/by-source/{digest}.md"


def _scan(export_dir: Path, expected: dict[str, Any]) -> dict[str, Any]:
    chunks_path = export_dir / "chunks.ndjson"
    vectors_path = export_dir / "vectors.ndjson"
    transcripts_path = export_dir / "transcripts.ndjson"
    for path in (chunks_path, vectors_path, transcripts_path):
        _require(path.is_file(), f"Missing required export artifact: {path.name}")

    chunk_meta: dict[str, tuple[str, bool, str, str]] = {}
    chunk_provenance: dict[str, dict[str, Any]] = {}
    chunk_videos: set[str] = set()
    chunk_sources: dict[str, str] = {}
    for line_number, row in _records(chunks_path):
        chunk_id = row.get("id")
        text = row.get("text")
        metadata = row.get("metadata")
        has_vector = row.get("has_vector")
        _require(isinstance(chunk_id, str) and chunk_id, f"chunks.ndjson:{line_number} has no id")
        _require(chunk_id not in chunk_meta, f"Duplicate chunk id: {chunk_id}")
        _require(isinstance(text, str) and text.strip(), f"Chunk {chunk_id} has no text")
        _require(isinstance(metadata, dict), f"Chunk {chunk_id} has no metadata")
        _require(isinstance(has_vector, bool), f"Chunk {chunk_id} has invalid has_vector")
        video_id = metadata.get("video_id")
        source_file = metadata.get("source_file")
        content_hash = metadata.get("content_hash")
        _require(isinstance(video_id, str) and video_id, f"Chunk {chunk_id} has no video_id")
        _require(isinstance(source_file, str) and source_file, f"Chunk {chunk_id} has no source_file")
        _require(metadata.get("chunker_version") == expected["chunker_version"], f"Chunk {chunk_id} has unexpected chunker_version")
        calculated_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        _require(content_hash == calculated_hash, f"Chunk {chunk_id} content hash mismatch")
        for field in ("title", "playlist", "start_ts", "end_ts"):
            _require(isinstance(metadata.get(field), str), f"Chunk {chunk_id} has invalid {field}")
        previous_video = chunk_sources.setdefault(source_file, video_id)
        _require(previous_video == video_id, f"Source {source_file} maps to multiple video IDs")
        chunk_meta[chunk_id] = (content_hash, has_vector, video_id, source_file)
        chunk_provenance[chunk_id] = metadata
        chunk_videos.add(video_id)

    vector_ids: set[str] = set()
    dimension = int(expected["dimension"])
    for line_number, row in _records(vectors_path):
        vector_id = row.get("id")
        values = row.get("values")
        metadata = row.get("metadata")
        _require(isinstance(vector_id, str) and vector_id, f"vectors.ndjson:{line_number} has no id")
        _require(vector_id not in vector_ids, f"Duplicate vector id: {vector_id}")
        _require(vector_id in chunk_meta, f"Vector {vector_id} has no chunk")
        _require(chunk_meta[vector_id][1] is True, f"Vector {vector_id} points to has_vector=false")
        _require(isinstance(values, list) and len(values) == dimension, f"Vector {vector_id} has wrong dimension")
        _require(all(isinstance(value, (int, float)) and math.isfinite(value) for value in values), f"Vector {vector_id} contains invalid values")
        norm = math.sqrt(sum(float(value) * float(value) for value in values))
        _require(abs(norm - 1.0) <= 1e-4, f"Vector {vector_id} is not unit-normalized")
        _require(isinstance(metadata, dict), f"Vector {vector_id} has no metadata")
        _require(metadata.get("content_hash") == chunk_meta[vector_id][0], f"Vector {vector_id} metadata hash mismatch")
        _require(metadata.get("contentType") == "transcript_chunk", f"Vector {vector_id} has invalid contentType")
        for field in (
            "video_id", "title", "playlist", "chunk_index", "start_ts", "end_ts",
            "start_seconds", "end_seconds", "source_file", "timing_precision",
            "chunker_version", "content_hash",
        ):
            expected_value = chunk_provenance[vector_id].get(field)
            if expected_value not in (None, ""):
                _require(
                    metadata.get(field) == expected_value,
                    f"Vector {vector_id} provenance mismatch: {field}",
                )
        vector_ids.add(vector_id)

    declared_vector_ids = {
        chunk_id for chunk_id, (_hash, has_vector, _video, _source) in chunk_meta.items()
        if has_vector
    }
    _require(vector_ids == declared_vector_ids, "Vector IDs do not exactly match chunks marked has_vector")

    transcript_sources: dict[str, str] = {}
    transcript_videos: set[str] = set()
    r2_keys: set[str] = set()
    for line_number, row in _records(transcripts_path):
        source_file = row.get("source_file")
        video_id = row.get("video_id")
        r2_key = row.get("r2_key")
        content = row.get("content")
        _require(isinstance(source_file, str) and source_file, f"transcripts.ndjson:{line_number} has no source_file")
        _require(isinstance(video_id, str) and video_id, f"transcripts.ndjson:{line_number} has no video_id")
        _require(isinstance(content, str) and content.strip(), f"Transcript {video_id} has no content")
        _require(source_file not in transcript_sources, f"Duplicate transcript source_file: {source_file}")
        _require(r2_key == r2_key_for_transcript(source_file, content), f"Transcript {source_file} has invalid r2_key")
        _require(r2_key not in r2_keys, f"Duplicate transcript r2_key: {r2_key}")
        transcript_sources[source_file] = video_id
        transcript_videos.add(video_id)
        r2_keys.add(r2_key)
    _require(set(transcript_sources) == set(chunk_sources), "Transcript sources do not exactly match chunk sources")
    for source_file, video_id in chunk_sources.items():
        _require(transcript_sources[source_file] == video_id, f"Source/video mismatch: {source_file}")
    _require(transcript_videos == chunk_videos, "Transcript video IDs do not exactly match chunk video IDs")

    counts = {
        "chunk_count": len(chunk_meta),
        "vector_count": len(vector_ids),
        "transcript_count": len(transcript_sources),
        "r2_object_count": len(r2_keys),
        "unique_video_count": len(transcript_videos),
    }
    for key, actual in counts.items():
        _require(actual == int(expected[key]), f"{key}={actual}; expected {expected[key]}")
    return counts


def finalize_manifest(export_dir: Path, report: dict[str, Any], expected: dict[str, Any] | None = None) -> dict[str, Any]:
    """Hash-bind a complete export, write the manifest last, then self-validate."""
    expected = dict(expected or DEFAULT_EXPECTATIONS)
    counts = _scan(export_dir, expected)
    manifest = dict(report)
    manifest.update({
        "format_version": FORMAT_VERSION,
        "complete": True,
        "expected_invariants": expected,
        "artifact_counts": counts,
        "artifacts": {
            name: {
                "bytes": (export_dir / name).stat().st_size,
                "sha256": _sha256(export_dir / name),
            }
            for name in ARTIFACTS
        },
    })
    path = export_dir / "export-report.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
    validate_export(export_dir, expected)
    return manifest


def validate_export(export_dir: Path, expected: dict[str, Any] | None = None) -> dict[str, Any]:
    """Reject stale, partial, modified, or wrong-model exports before any write."""
    expected = dict(expected or DEFAULT_EXPECTATIONS)
    path = export_dir / "export-report.json"
    _require(path.is_file(), "Missing export-report.json")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise RuntimeError("export-report.json is unreadable") from exc
    _require(isinstance(manifest, dict), "export-report.json must contain an object")
    _require(manifest.get("complete") is True, "Export manifest is not marked complete")
    _require(manifest.get("format_version") == FORMAT_VERSION, "Unsupported export manifest version")
    _require(manifest.get("expected_invariants") == expected, "Export invariants differ from the release contract")

    artifacts = manifest.get("artifacts")
    _require(isinstance(artifacts, dict) and set(artifacts) == set(ARTIFACTS), "Manifest artifact set is incomplete")
    for name in ARTIFACTS:
        file_path = export_dir / name
        entry = artifacts[name]
        _require(file_path.is_file(), f"Missing required export artifact: {name}")
        _require(isinstance(entry, dict), f"Invalid manifest entry for {name}")
        _require(entry.get("bytes") == file_path.stat().st_size, f"{name} size differs from manifest")
        _require(entry.get("sha256") == _sha256(file_path), f"{name} SHA-256 differs from manifest")

    _require(manifest.get("chunk_count") == expected["chunk_count"], "Report chunk count mismatch")
    _require(manifest.get("hnsw_active_vector_count") == expected["vector_count"], "Report HNSW count mismatch")
    _require(manifest.get("exportable_vector_count") == expected["vector_count"], "Report vector count mismatch")
    _require(manifest.get("chunks_without_active_vector") == expected["chunk_count"] - expected["vector_count"], "Report missing-vector count mismatch")
    for key in ("missing_vector_metadata_count", "active_vectors_without_fts_row_count", "text_mismatch_count"):
        _require(manifest.get(key) == 0, f"Report {key} must be zero")
    missing_docs = manifest.get("missing_chroma_document_count")
    _require(isinstance(missing_docs, int), "Report missing_chroma_document_count must be an integer")
    _require(
        missing_docs == 0 or missing_docs == expected["vector_count"],
        "Report chroma-document binding must be uniform (all vectors carry the original "
        "document, or none do with the equivalent content-hash binding)",
    )
    _require(manifest.get("active_vector_ids_are_chunk_ids") is True, "Vector IDs are not attested as chunk IDs")
    _require(manifest.get("chunker_version_counts") == {expected["chunker_version"]: expected["chunk_count"]}, "Chunker version/count mismatch")
    embedding = manifest.get("embedding_metadata")
    _require(isinstance(embedding, dict), "Missing embedding metadata")
    for key in ("embedding_model_name", "embedding_normalize", "embedding_revision", "query_instruction_version", "vector_schema_version"):
        _require(str(embedding.get(key)) == str(expected[key]), f"Embedding invariant mismatch: {key}")
    _require(int(embedding.get("embedding_dimension", -1)) == int(expected["dimension"]), "Embedding dimension mismatch")

    counts = _scan(export_dir, expected)
    _require(manifest.get("artifact_counts") == counts, "Manifest record counts differ from artifacts")
    return manifest


def validate_r2_credentials(credentials_path: Path) -> dict[str, Any]:
    """Pin direct uploads to PlugICT's HTTPS Cloudflare R2 endpoint and bucket."""
    try:
        credentials = json.loads(credentials_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise RuntimeError("R2 credentials file is unreadable") from exc
    _require(isinstance(credentials, dict), "R2 credentials must be a JSON object")
    for key in ("endpoint", "access_key_id", "secret_access_key"):
        _require(isinstance(credentials.get(key), str) and credentials[key], f"R2 credentials missing {key}")
    endpoint = urlparse(credentials["endpoint"])
    host = (endpoint.hostname or "").lower()
    account = host.removesuffix(".r2.cloudflarestorage.com")
    _require(endpoint.scheme == "https", "R2 endpoint must use HTTPS")
    _require(endpoint.port in (None, 443), "R2 endpoint must use the default HTTPS port")
    _require(not endpoint.username and not endpoint.password and not endpoint.query and not endpoint.fragment, "R2 endpoint must not contain credentials, query, or fragment")
    _require(host.endswith(".r2.cloudflarestorage.com") and len(account) == 32 and all(char in "0123456789abcdef" for char in account), "R2 endpoint must be an account-scoped Cloudflare R2 hostname")
    _require(credentials.get("bucket", "plugict-vault") == "plugict-vault", "R2 bucket must be plugict-vault")
    credentials["bucket"] = "plugict-vault"
    return credentials

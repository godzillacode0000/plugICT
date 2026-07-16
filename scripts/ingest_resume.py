"""Fail-closed resume helpers for the V3 ingestion pipeline."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

MANIFEST_SCHEMA = 2


def corpus_manifest_hash(transcripts):
    digest = hashlib.sha256()
    for path in transcripts:
        path = Path(path)
        digest.update(path.name.encode("utf-8"))
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def make_resume_manifest(transcripts, chunker_config, embedding_meta,
                         expected_final_chunks=0, build_id=None):
    manifest = {
        "schema_version": MANIFEST_SCHEMA,
        "corpus_manifest_hash": corpus_manifest_hash(transcripts),
        "chunker_config": dict(sorted(chunker_config.items())),
        "embedding_meta": dict(sorted(embedding_meta.items())),
        "expected_final_chunks": int(expected_final_chunks or 0),
    }
    if build_id:
        manifest["build_id"] = str(build_id)
    return manifest


def write_manifest_atomic(path, manifest):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)


def validate_resume_manifest(path, current_manifest, requested_expected=0):
    path = Path(path)
    if not path.exists():
        raise RuntimeError(
            "resume manifest is missing; run a clean non-resume build"
        )
    saved = json.loads(path.read_text(encoding="utf-8"))
    if not saved.get("build_id"):
        raise RuntimeError(
            "resume manifest has no index-bound build_id; run a clean non-resume build"
        )
    for key in ("schema_version", "corpus_manifest_hash", "chunker_config",
                "embedding_meta"):
        if saved.get(key) != current_manifest.get(key):
            raise RuntimeError(
                f"resume manifest mismatch for {key}; run a clean non-resume build"
            )
    saved_expected = int(saved.get("expected_final_chunks") or 0)
    requested_expected = int(requested_expected or 0)
    if saved_expected and requested_expected and saved_expected != requested_expected:
        raise RuntimeError(
            "ICT_EXPECTED_FINAL_CHUNKS conflicts with the resume manifest"
        )
    expected = requested_expected or saved_expected
    if expected <= 0:
        raise RuntimeError(
            "resume requires a positive ICT_EXPECTED_FINAL_CHUNKS or a completed manifest"
        )
    return expected


def read_resume_manifest(path):
    saved = json.loads(Path(path).read_text(encoding="utf-8"))
    if saved.get("schema_version") != MANIFEST_SCHEMA or not saved.get("build_id"):
        raise RuntimeError("resume manifest is not bound to a valid collection build")
    return saved


def validate_embedding_dimension(existing_dim, current_dim):
    if existing_dim is not None and int(existing_dim) != int(current_dim):
        raise RuntimeError(
            f"embedding dimension changed ({existing_dim} != {current_dim}); "
            "run a clean non-resume build"
        )


def _stable_id(metadata):
    identity = (
        f"{metadata['source_file']}|{metadata['chunker_version']}|"
        f"{int(metadata['start_seconds'])}|{int(metadata['end_seconds'])}|"
        f"{metadata['content_hash']}"
    )
    return hashlib.sha1(identity.encode("utf-8")).hexdigest()[:20]


def plan_resume(transcripts, existing_ids, existing_metadatas, existing_documents,
                chunker_version):
    """Fail closed on corrupt rows; rebuild from before the first unsafe source."""
    names = [Path(path).name for path in transcripts]
    source_index = {name: index for index, name in enumerate(names)}
    ids = list(existing_ids or [])
    metadatas = list(existing_metadatas or [])
    documents = list(existing_documents or [])
    if not (len(ids) == len(metadatas) == len(documents)):
        raise RuntimeError("resume collection returned mismatched IDs, metadata, and documents")
    if not ids:
        return 0, (names[0] if names else None), set(), set()

    valid_pairs = []
    stale_ids = set()
    invalid_source_indexes = []
    for chunk_id, raw_metadata, document in zip(ids, metadatas, documents):
        metadata = raw_metadata or {}
        source = metadata.get("source_file")
        try:
            valid = (
                source in source_index
                and metadata.get("chunk_id") == chunk_id
                and metadata.get("chunker_version") == chunker_version
                and metadata.get("content_hash") == hashlib.sha256(
                    str(document or "").encode("utf-8")
                ).hexdigest()
                and _stable_id(metadata) == chunk_id
            )
        except (KeyError, TypeError, ValueError):
            valid = False
        if valid:
            valid_pairs.append((chunk_id, metadata))
        else:
            stale_ids.add(chunk_id)
            if source in source_index:
                invalid_source_indexes.append(source_index[source])

    existing_sources = {metadata["source_file"] for _, metadata in valid_pairs}
    first_missing = next(
        (index for index, name in enumerate(names) if name not in existing_sources),
        len(names),
    )
    boundary = min([first_missing, *invalid_source_indexes]) if invalid_source_indexes else first_missing
    cutoff_index = max(0, boundary - 1)
    cutoff_source = names[cutoff_index] if names else None

    preserved_ids = set()
    for chunk_id, metadata in valid_pairs:
        index = source_index[metadata["source_file"]]
        if index >= cutoff_index:
            stale_ids.add(chunk_id)
        else:
            preserved_ids.add(chunk_id)
    return cutoff_index, cutoff_source, stale_ids, preserved_ids

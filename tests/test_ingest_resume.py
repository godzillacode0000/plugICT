import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from ingest_resume import (
    make_resume_manifest,
    plan_resume,
    validate_embedding_dimension,
    validate_resume_manifest,
    write_manifest_atomic,
)


def _transcripts(tmp_path, texts=("one", "two", "three")):
    paths = []
    for index, text in enumerate(texts):
        path = tmp_path / f"{index:02d}.md"
        path.write_text(text, encoding="utf-8")
        paths.append(path)
    return paths


def _manifest(paths, target=240, expected=0):
    return make_resume_manifest(
        paths,
        {"chunker_version": "semantic-v3.0.0", "target_tokens": target},
        {"model": "bge-small", "dimension": 384},
        expected_final_chunks=expected,
        build_id="test-build-id",
    )


def _row(source, text, start=0, end=10):
    content_hash = hashlib.sha256(text.encode()).hexdigest()
    identity = f"{source}|semantic-v3.0.0|{start}|{end}|{content_hash}"
    chunk_id = hashlib.sha1(identity.encode()).hexdigest()[:20]
    return chunk_id, {
        "source_file": source,
        "chunk_id": chunk_id,
        "chunker_version": "semantic-v3.0.0",
        "content_hash": content_hash,
        "start_seconds": start,
        "end_seconds": end,
    }, text


def test_resume_manifest_rejects_changed_source_and_chunker(tmp_path):
    paths = _transcripts(tmp_path)
    manifest_path = tmp_path / "resume.json"
    write_manifest_atomic(manifest_path, _manifest(paths, expected=12))

    paths[1].write_text("changed", encoding="utf-8")
    with pytest.raises(RuntimeError, match="corpus_manifest_hash"):
        validate_resume_manifest(manifest_path, _manifest(paths), 12)

    paths[1].write_text("two", encoding="utf-8")
    with pytest.raises(RuntimeError, match="chunker_config"):
        validate_resume_manifest(manifest_path, _manifest(paths, target=300), 12)


def test_resume_manifest_requires_and_validates_expected_count(tmp_path):
    paths = _transcripts(tmp_path)
    manifest_path = tmp_path / "resume.json"
    write_manifest_atomic(manifest_path, _manifest(paths))
    with pytest.raises(RuntimeError, match="positive ICT_EXPECTED_FINAL_CHUNKS"):
        validate_resume_manifest(manifest_path, _manifest(paths), 0)

    write_manifest_atomic(manifest_path, _manifest(paths, expected=12))
    assert validate_resume_manifest(manifest_path, _manifest(paths), 0) == 12
    with pytest.raises(RuntimeError, match="conflicts"):
        validate_resume_manifest(manifest_path, _manifest(paths), 13)


def test_resume_manifest_rejects_unbound_build(tmp_path):
    paths = _transcripts(tmp_path)
    manifest = _manifest(paths, expected=12)
    manifest.pop("build_id")
    manifest_path = tmp_path / "resume.json"
    write_manifest_atomic(manifest_path, manifest)
    with pytest.raises(RuntimeError, match="build_id"):
        validate_resume_manifest(manifest_path, _manifest(paths), 12)


def test_resume_plan_deletes_cutoff_partial_and_obsolete_ids(tmp_path):
    paths = _transcripts(tmp_path)
    rows = [_row("00.md", "a"), _row("01.md", "b1"),
            _row("01.md", "b2", 11, 20), _row("removed.md", "obsolete")]
    ids, metadata, documents = map(list, zip(*rows))
    cutoff, source, stale, preserved = plan_resume(
        paths, ids, metadata, documents, "semantic-v3.0.0")
    assert cutoff == 1
    assert source == "01.md"
    assert stale == {ids[1], ids[2], ids[3]}
    assert preserved == {ids[0]}


def test_resume_plan_rebuilds_final_source_when_all_sources_present(tmp_path):
    paths = _transcripts(tmp_path)
    rows = [_row("00.md", "a"), _row("01.md", "b"), _row("02.md", "c-partial")]
    ids, metadata, documents = map(list, zip(*rows))
    cutoff, source, stale, preserved = plan_resume(
        paths, ids, metadata, documents, "semantic-v3.0.0")
    assert (cutoff, source) == (2, "02.md")
    assert stale == {ids[2]}
    assert preserved == {ids[0], ids[1]}


def test_resume_plan_rejects_corrupt_document_and_stable_id(tmp_path):
    paths = _transcripts(tmp_path)
    rows = [_row("00.md", "valid"), _row("01.md", "corrupt")]
    ids, metadata, documents = map(list, zip(*rows))
    documents[1] = "tampered document"
    cutoff, source, stale, preserved = plan_resume(
        paths, ids, metadata, documents, "semantic-v3.0.0")
    assert (cutoff, source) == (0, "00.md")
    assert ids[1] in stale
    assert not preserved


def test_embedding_dimension_change_fails_closed():
    with pytest.raises(RuntimeError, match="clean non-resume"):
        validate_embedding_dimension(384, 768)
    validate_embedding_dimension(384, 384)

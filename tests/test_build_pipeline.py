"""
Seller-pipeline integration test: build.py -> generate_key.py -> open_vault.

Runs the real scripts as subprocesses against a tiny fixture source tree, so a
wiring mistake in the refactor (imports, classify_playlist, pack_and_encrypt)
fails here instead of on the seller's machine at 2am.
"""

import os
import runpy
import sys
import sqlite3

import pytest
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import vault_core as vc  # noqa: E402
from build_integrity import snapshot_source_corpus
from ingest_resume import write_manifest_atomic  # noqa: E402


def _make_source_tree(src):
    src = Path(src)
    # kg.db with the tables build.py expects to copy forward.
    kg = sqlite3.connect(src / "kg.db")
    kg.execute("CREATE VIRTUAL TABLE transcripts_fts USING fts5("
               "chunk_id, chunk_index, title, video_id, playlist, start_ts, end_ts, source_file, content, "
               "tokenize='porter unicode61')")
    chunk_id = vc.stable_chunk_id("a.md", 0, "0:00")
    kg.execute("INSERT INTO transcripts_fts VALUES (?,?,?,?,?,?,?,?,?)",
               (chunk_id, 0, "Order Blocks 101", "vid1", "2022 ICT Mentorship", "0:00", "0:10", "a.md",
                "An order block is where institutional orders rest."))
    kg.execute("CREATE TABLE entities (id INTEGER PRIMARY KEY, name TEXT UNIQUE, type TEXT,"
               " description TEXT, source_file TEXT, source_count INTEGER)")
    kg.execute("INSERT INTO entities (name,type,description,source_count) VALUES "
               "('OB','ICT Concept','Order Block',9)")
    kg.execute("CREATE TABLE relations (id INTEGER PRIMARY KEY, from_entity TEXT, to_entity TEXT,"
               " relation_type TEXT, evidence TEXT, source_file TEXT)")
    kg.execute("CREATE TABLE vault_metadata(key TEXT PRIMARY KEY, value TEXT)")
    transcript_text = (
        '---\ntitle: "Order Blocks 101"\nvideo_id: "vid1"\n---\n'
        '0:00 An order block is where orders rest.\n'
    )
    (src / "2022 ICT Mentorship - Order Blocks.md").write_text(transcript_text)
    _, corpus_hash = snapshot_source_corpus(src)
    build_id = "fixture-build-id"
    kg.executemany(
        "INSERT INTO vault_metadata VALUES (?, ?)",
        [("build_id", build_id), ("ingestion_state", "complete"),
         ("final_chunk_count", "1"), ("chunk_count", "1"),
         ("corpus_manifest_hash", corpus_hash)],
    )
    kg.commit()
    kg.close()

    import chromadb
    from chromadb.config import Settings
    vector_dir = src / "_vectors"
    client = chromadb.PersistentClient(
        path=str(vector_dir), settings=Settings(anonymized_telemetry=False))
    collection = client.create_collection(
        "ict_vault",
        metadata={"build_id": build_id, "ingestion_state": "complete",
                  "final_chunk_count": 1},
    )
    collection.add(
        ids=[chunk_id], documents=["An order block is where institutional orders rest."],
        metadatas=[{"chunk_id": chunk_id}], embeddings=[[0.0] * 384],
    )
    client._system.stop()
    from chromadb.api.client import SharedSystemClient
    SharedSystemClient.clear_system_cache()
    write_manifest_atomic(
        src / ".ict-v3-resume-manifest.json",
        {"schema_version": 2, "build_id": build_id,
         "corpus_manifest_hash": corpus_hash, "chunker_config": {},
         "embedding_meta": {}, "expected_final_chunks": 1,
         "ingestion_state": "complete", "final_chunk_count": 1},
    )


def test_build_rejects_unattested_ingestion(tmp_path):
    src = tmp_path / "source"
    build = tmp_path / "build"
    src.mkdir()
    _make_source_tree(src)
    build.mkdir()
    (src / "kg.db").replace(build / "kg.db")
    (src / "_vectors").replace(build / "_vectors")
    env = dict(os.environ, ICT_SOURCE_DIR=str(src), ICT_BUILD_DIR=str(build))

    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "build.py")],
        env=env, capture_output=True, text=True,
    )

    assert result.returncode != 0
    assert "completed ingestion" in (result.stdout + result.stderr).lower()
    assert not (build / "ict-vault.kevin").exists()


def _move_attested_artifacts(src, build):
    (src / "kg.db").replace(build / "kg.db")
    (src / "_vectors").replace(build / "_vectors")
    (src / ".ict-v3-resume-manifest.json").replace(
        build / ".ict-v3-resume-manifest.json")


def test_build_rejects_source_changed_after_ingestion_attestation(tmp_path):
    src = tmp_path / "source"
    build = tmp_path / "build"
    src.mkdir()
    _make_source_tree(src)
    build.mkdir()
    _move_attested_artifacts(src, build)
    transcript = src / "2022 ICT Mentorship - Order Blocks.md"
    transcript.write_text(transcript.read_text() + "\n0:10 mutated after ingestion\n")
    env = dict(os.environ, ICT_SOURCE_DIR=str(src), ICT_BUILD_DIR=str(build))

    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "build.py")],
        env=env, capture_output=True, text=True,
    )

    assert result.returncode != 0
    assert "source corpus" in (result.stdout + result.stderr).lower()
    assert not (build / "ict-vault.kevin").exists()


def test_build_rejects_source_mutation_during_encryption_before_publication(tmp_path, monkeypatch):
    src = tmp_path / "source"
    build = tmp_path / "build"
    src.mkdir()
    _make_source_tree(src)
    build.mkdir()
    _move_attested_artifacts(src, build)
    transcript = src / "2022 ICT Mentorship - Order Blocks.md"
    original_pack = vc.pack_and_encrypt

    def mutate_during_pack(*args, **kwargs):
        packed = original_pack(*args, **kwargs)
        transcript.write_text(transcript.read_text() + "\n0:20 concurrent mutation\n")
        return packed

    monkeypatch.setattr(vc, "pack_and_encrypt", mutate_during_pack)
    monkeypatch.setenv("ICT_SOURCE_DIR", str(src))
    monkeypatch.setenv("ICT_BUILD_DIR", str(build))
    monkeypatch.setattr(sys, "argv", [str(SCRIPTS / "build.py")])

    with pytest.raises(SystemExit, match="source corpus changed during build"):
        runpy.run_path(str(SCRIPTS / "build.py"), run_name="__main__")

    assert not (build / "ict-vault.kevin").exists()
    assert not (build / ".vault_sha256").exists()


def test_build_supports_separate_source_and_output_dirs(tmp_path):
    src = tmp_path / "source"
    src.mkdir()
    _make_source_tree(src)
    build = tmp_path / "build"
    build.mkdir()
    _move_attested_artifacts(src, build)

    env = dict(os.environ, ICT_SOURCE_DIR=str(src), ICT_BUILD_DIR=str(build))
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "build.py")],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert (build / "ict-vault.kevin").exists()
    assert (build / ".vault_key").exists()
    assert not (src / "ict-vault.kevin").exists()


def test_build_generate_open(tmp_path):
    src = tmp_path / "source"
    build = tmp_path / "build"
    src.mkdir()
    _make_source_tree(src)
    build.mkdir()
    _move_attested_artifacts(src, build)

    env = dict(os.environ, ICT_SOURCE_DIR=str(src), ICT_BUILD_DIR=str(build))
    env.pop("ICT_VAULT_KEY_FILE", None)

    r1 = subprocess.run([sys.executable, str(SCRIPTS / "build.py")],
                        env=env, capture_output=True, text=True)
    assert r1.returncode == 0, r1.stdout + r1.stderr
    assert (build / "ict-vault.kevin").exists()
    assert (build / ".vault_key").exists()
    assert not (src / "ict-vault.kevin").exists()

    r2 = subprocess.run([sys.executable, str(SCRIPTS / "generate_key.py"), "t@e.com", "ID1"],
                        env=env, capture_output=True, text=True)
    assert r2.returncode == 0, r2.stdout + r2.stderr
    lic = build / "license_t_at_e_com.key"
    assert lic.exists()

    db, chroma_dir, who = vc.open_vault(vault_file=build / "ict-vault.kevin", license_file=lic)
    try:
        assert who == "t@e.com"
        row = db.execute("SELECT title FROM transcripts_fts WHERE content MATCH ?",
                        (vc.sanitize_fts("order block"),)).fetchone()
        assert row and row[0] == "Order Blocks 101"
        assert (Path(chroma_dir) / "chroma.sqlite3").exists()
        n = db.execute("SELECT COUNT(*) FROM transcript_files").fetchone()[0]
        assert n == 1
    finally:
        db.close()

#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import pickle
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import export_existing_vault as exporter
from vault_export_integrity import finalize_manifest, validate_export, validate_r2_credentials


def _pickle_marker_payload() -> dict[str, object]:
    Path(os.environ["PLUGICT_TEST_PICKLE_MARKER"]).write_text("executed", encoding="utf-8")
    return {"id_to_label": {"chunk-0": 1}}


class _ExecutablePickle:
    def __reduce__(self):
        return (_pickle_marker_payload, ())


def r2_key(source_file: str, content: str) -> str:
    digest = hashlib.sha256(source_file.encode("utf-8") + b"\0" + content.encode("utf-8")).hexdigest()
    return f"transcripts/by-source/{digest}.md"


class VaultExportIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.expected = {
            "chunk_count": 2,
            "vector_count": 1,
            "transcript_count": 2,
            "r2_object_count": 2,
            "unique_video_count": 2,
            "dimension": 3,
            "chunker_version": "semantic-test",
            "embedding_model_name": "test/model",
            "embedding_normalize": "true",
            "embedding_revision": "rev",
            "query_instruction_version": "query-v1",
            "vector_schema_version": "2",
        }
        chunks = []
        for index, video_id in enumerate(("video-a", "video-b")):
            text = f"chunk {index}"
            chunks.append({
                "id": f"chunk-{index}",
                "text": text,
                "metadata": {
                    "video_id": video_id,
                    "title": "Lesson",
                    "playlist": "Core",
                    "source_file": f"source-{index}.md",
                    "start_ts": "0:00",
                    "end_ts": "0:10",
                    "chunker_version": "semantic-test",
                    "content_hash": hashlib.sha256(text.encode()).hexdigest(),
                },
                "has_vector": index == 0,
            })
        vector = {
            "id": "chunk-0",
            "values": [1.0, 0.0, 0.0],
            "metadata": {
                "contentType": "transcript_chunk",
                **chunks[0]["metadata"],
            },
        }
        transcripts = []
        for source_file, video_id, content in (
            ("source-0.md", "video-a", "0:00 first transcript"),
            ("source-1.md", "video-b", "0:00 second transcript"),
        ):
            transcripts.append({
                "source_file": source_file,
                "video_id": video_id,
                "r2_key": r2_key(source_file, content),
                "content": content,
            })
        for name, rows in (("chunks.ndjson", chunks), ("vectors.ndjson", [vector]), ("transcripts.ndjson", transcripts)):
            (self.root / name).write_text("".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")
        self.report = {
            "chunk_count": 2,
            "hnsw_active_vector_count": 1,
            "exportable_vector_count": 1,
            "chunks_without_active_vector": 1,
            "missing_vector_metadata_count": 0,
            "active_vectors_without_fts_row_count": 0,
            "missing_chroma_document_count": 0,
            "text_mismatch_count": 0,
            "active_vector_ids_are_chunk_ids": True,
            "chunker_version_counts": {"semantic-test": 2},
            "embedding_metadata": {
                "embedding_dimension": "3",
                "embedding_model_name": "test/model",
                "embedding_normalize": "true",
                "embedding_revision": "rev",
                "query_instruction_version": "query-v1",
                "vector_schema_version": "2",
            },
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_manifest_binds_complete_export(self) -> None:
        finalize_manifest(self.root, self.report, self.expected)
        manifest = validate_export(self.root, self.expected)
        self.assertTrue(manifest["complete"])
        self.assertEqual(manifest["artifact_counts"]["chunk_count"], 2)

    def test_modified_artifact_fails_closed(self) -> None:
        finalize_manifest(self.root, self.report, self.expected)
        with (self.root / "chunks.ndjson").open("a", encoding="utf-8") as handle:
            handle.write(" ")
        with self.assertRaisesRegex(RuntimeError, "size differs|SHA-256 differs"):
            validate_export(self.root, self.expected)

    def test_non_unit_vector_cannot_be_attested_as_normalized(self) -> None:
        vectors_path = self.root / "vectors.ndjson"
        vector = json.loads(vectors_path.read_text(encoding="utf-8"))
        vector["values"] = [0.1, 0.2, 0.3]
        vectors_path.write_text(json.dumps(vector, separators=(",", ":")) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "unit-normalized"):
            finalize_manifest(self.root, self.report, self.expected)

    def test_vector_metadata_must_match_chunk_provenance(self) -> None:
        vectors_path = self.root / "vectors.ndjson"
        vector = json.loads(vectors_path.read_text(encoding="utf-8"))
        vector["metadata"]["video_id"] = "wrong-video"
        vectors_path.write_text(json.dumps(vector, separators=(",", ":")) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "provenance mismatch"):
            finalize_manifest(self.root, self.report, self.expected)

    def test_distinct_sources_with_one_video_id_keep_distinct_r2_objects(self) -> None:
        chunks_path = self.root / "chunks.ndjson"
        chunks = [json.loads(line) for line in chunks_path.read_text(encoding="utf-8").splitlines()]
        chunks[1]["metadata"]["video_id"] = "video-a"
        chunks_path.write_text(
            "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in chunks),
            encoding="utf-8",
        )

        transcripts_path = self.root / "transcripts.ndjson"
        transcripts = [json.loads(line) for line in transcripts_path.read_text(encoding="utf-8").splitlines()]
        transcripts[1]["video_id"] = "video-a"
        transcripts_path.write_text(
            "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in transcripts),
            encoding="utf-8",
        )

        duplicate_expected = {**self.expected, "unique_video_count": 1}
        manifest = finalize_manifest(self.root, self.report, duplicate_expected)
        self.assertEqual(manifest["artifact_counts"]["transcript_count"], 2)
        self.assertEqual(len({row["r2_key"] for row in transcripts}), 2)

    def test_d1_chunks_reference_their_source_specific_r2_objects(self) -> None:
        transcripts = [
            json.loads(line)
            for line in (self.root / "transcripts.ndjson").read_text(encoding="utf-8").splitlines()
        ]
        captured_sql: list[str] = []
        snapshot = exporter._load_snapshot(self.root)

        def capture_wrangler(arguments: list[str]) -> None:
            file_index = arguments.index("--file") + 1
            captured_sql.append(Path(arguments[file_index]).read_text(encoding="utf-8"))

        with patch.object(exporter, "_run_wrangler", capture_wrangler):
            count = exporter._upload_d1_chunks(
                snapshot["transcripts"], snapshot["chunks"], batch_size=10
            )

        sql = "\n".join(captured_sql)
        self.assertEqual(count, 2)
        for transcript in transcripts:
            self.assertIn(transcript["r2_key"], sql)
        self.assertNotIn("transcripts/video-a.md", sql)
        self.assertNotIn("transcripts/video-b.md", sql)

    def test_unmapped_chunk_source_blocks_d1_before_first_write(self) -> None:
        chunks_path = self.root / "chunks.ndjson"
        chunks = [json.loads(line) for line in chunks_path.read_text(encoding="utf-8").splitlines()]
        chunks[1]["metadata"]["source_file"] = "missing-source.md"
        chunks_path.write_text(
            "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in chunks),
            encoding="utf-8",
        )
        snapshot = exporter._load_snapshot(self.root)
        run_wrangler = Mock()
        with patch.object(exporter, "_run_wrangler", run_wrangler):
            with self.assertRaisesRegex(RuntimeError, "no validated R2 object"):
                exporter._upload_d1_chunks(
                    snapshot["transcripts"], snapshot["chunks"], batch_size=1
                )
        run_wrangler.assert_not_called()

    def test_r2_upload_uses_validated_content_addressed_keys(self) -> None:
        transcripts = [
            json.loads(line)
            for line in (self.root / "transcripts.ndjson").read_text(encoding="utf-8").splitlines()
        ]
        targets: list[str] = []
        snapshot = exporter._load_snapshot(self.root)

        def capture_wrangler(arguments: list[str]) -> None:
            targets.append(arguments[3])

        with patch.object(exporter, "_run_wrangler", capture_wrangler):
            count = exporter._upload_r2(snapshot["transcripts"])

        self.assertEqual(count, 2)
        self.assertEqual(
            set(targets),
            {f"plugict-vault/{row['r2_key']}" for row in transcripts},
        )

    def test_every_upload_mode_validates_manifest_before_cloud_calls(self) -> None:
        upload_vectors = Mock()
        upload_chunks = Mock()
        upload_r2 = Mock()
        argument_sets = (
            ["export_existing_vault.py", "--stage", "upload", "--export-dir", str(self.root)],
            ["export_existing_vault.py", "--stage", "upload", "--r2-only", "--export-dir", str(self.root)],
        )
        for arguments in argument_sets:
            upload_vectors.reset_mock()
            upload_chunks.reset_mock()
            upload_r2.reset_mock()
            with self.subTest(arguments=arguments), patch.object(sys, "argv", arguments), patch.object(
                exporter, "_upload_vectors", upload_vectors
            ), patch.object(exporter, "_upload_d1_chunks", upload_chunks), patch.object(
                exporter, "_upload_r2", upload_r2
            ):
                with self.assertRaisesRegex(SystemExit, "integrity validation failed"):
                    exporter.main()
            upload_vectors.assert_not_called()
            upload_chunks.assert_not_called()
            upload_r2.assert_not_called()

    def test_full_upload_publishes_r2_before_d1_pointers(self) -> None:
        calls: list[str] = []
        manifest = {
            "artifact_counts": {
                "vector_count": 1,
                "chunk_count": 2,
                "transcript_count": 2,
            },
        }

        def upload_vectors(*_args, **_kwargs) -> int:
            calls.append("vectors")
            return 1

        def upload_chunks(*_args, **_kwargs) -> int:
            calls.append("d1")
            return 2

        def upload_r2(*_args, **_kwargs) -> int:
            calls.append("r2")
            return 2

        arguments = ["export_existing_vault.py", "--stage", "upload", "--export-dir", str(self.root)]
        with patch.object(sys, "argv", arguments), patch.object(
            exporter, "validate_export", return_value=manifest
        ), patch.object(exporter, "_upload_vectors", upload_vectors), patch.object(
            exporter, "_upload_d1_chunks", upload_chunks
        ), patch.object(exporter, "_upload_r2", upload_r2):
            self.assertEqual(exporter.main(), 0)

        self.assertEqual(calls, ["r2", "vectors", "d1"])

    def test_validate_stage_opens_neither_vault_nor_cloud(self) -> None:
        manifest = {"artifact_counts": {"chunk_count": 2}}
        arguments = ["export_existing_vault.py", "--stage", "validate", "--export-dir", str(self.root)]
        open_vault = Mock()
        upload_vectors = Mock()
        upload_chunks = Mock()
        upload_r2 = Mock()
        with patch.object(sys, "argv", arguments), patch.object(
            exporter, "validate_export", return_value=manifest
        ) as validate, patch.object(exporter, "_open_vault", open_vault), patch.object(
            exporter, "_upload_vectors", upload_vectors
        ), patch.object(exporter, "_upload_d1_chunks", upload_chunks), patch.object(
            exporter, "_upload_r2", upload_r2
        ):
            self.assertEqual(exporter.main(), 0)

        validate.assert_called_once_with(self.root)
        open_vault.assert_not_called()
        upload_vectors.assert_not_called()
        upload_chunks.assert_not_called()
        upload_r2.assert_not_called()

    def test_skip_r2_flag_is_rejected(self) -> None:
        arguments = [
            "export_existing_vault.py", "--stage", "upload",
            "--skip-r2", "--export-dir", str(self.root),
        ]
        upload_vectors = Mock()
        upload_chunks = Mock()
        upload_r2 = Mock()
        with patch.object(sys, "argv", arguments), patch.object(
            exporter, "_upload_vectors", upload_vectors
        ), patch.object(exporter, "_upload_d1_chunks", upload_chunks), patch.object(
            exporter, "_upload_r2", upload_r2
        ):
            with self.assertRaises(SystemExit):
                exporter.main()
        upload_vectors.assert_not_called()
        upload_chunks.assert_not_called()
        upload_r2.assert_not_called()

    def test_upload_uses_snapshot_rows_even_after_artifact_mutation(self) -> None:
        """Artifacts changed AFTER the snapshot is taken never reach uploads."""
        finalize_manifest(self.root, self.report, self.expected)
        manifest = validate_export(self.root, self.expected)
        snapshot = exporter._load_snapshot(self.root)
        exporter._verify_snapshot(snapshot, manifest)

        mutated = [
            dict(row, content=str(row["content"]) + " MUTATED")
            for row in snapshot["transcripts"]
        ]
        (self.root / "transcripts.ndjson").write_text(
            "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in mutated),
            encoding="utf-8",
        )

        captured: list[str] = []

        def capture_wrangler(arguments: list[str]) -> None:
            file_index = arguments.index("--file") + 1
            captured.append(Path(arguments[file_index]).read_text(encoding="utf-8"))

        with patch.object(exporter, "_run_wrangler", capture_wrangler):
            count = exporter._upload_r2(snapshot["transcripts"])

        self.assertEqual(count, 2)
        uploaded = "\n".join(captured)
        self.assertNotIn("MUTATED", uploaded)
        for row in snapshot["transcripts"]:
            self.assertIn(str(row["content"]), uploaded)

    def test_main_upload_refuses_mutated_artifacts_with_zero_cloud_writes(self) -> None:
        finalize_manifest(self.root, self.report, self.expected)
        arguments = ["export_existing_vault.py", "--stage", "upload", "--export-dir", str(self.root)]
        upload_r2 = Mock(return_value=2)
        upload_vectors = Mock(return_value=1)
        upload_chunks = Mock(return_value=2)
        # main() always validates against DEFAULT_EXPECTATIONS, so bind the
        # real validator to this fixture's smaller test invariants.
        def validate_fixture(export_dir: Path, expected=None):
            return validate_export(export_dir, self.expected)

        with patch.object(sys, "argv", arguments), patch.object(
            exporter, "validate_export", side_effect=validate_fixture
        ), patch.object(exporter, "_upload_vectors", upload_vectors), patch.object(
            exporter, "_upload_d1_chunks", upload_chunks
        ), patch.object(exporter, "_upload_r2", upload_r2):
            self.assertEqual(exporter.main(), 0)
        upload_r2.assert_called_once()
        upload_vectors.assert_called_once()
        upload_chunks.assert_called_once()

        upload_r2.reset_mock()
        upload_vectors.reset_mock()
        upload_chunks.reset_mock()
        with (self.root / "transcripts.ndjson").open("a", encoding="utf-8") as handle:
            handle.write(" ")
        with patch.object(sys, "argv", arguments), patch.object(
            exporter, "validate_export", side_effect=validate_fixture
        ), patch.object(exporter, "_upload_vectors", upload_vectors), patch.object(
            exporter, "_upload_d1_chunks", upload_chunks
        ), patch.object(exporter, "_upload_r2", upload_r2):
            with self.assertRaises(SystemExit):
                exporter.main()
        upload_r2.assert_not_called()
        upload_vectors.assert_not_called()
        upload_chunks.assert_not_called()

    def test_snapshot_verify_rejects_stale_or_incomplete_bindings(self) -> None:
        finalize_manifest(self.root, self.report, self.expected)
        manifest = validate_export(self.root, self.expected)

        snapshot = exporter._load_snapshot(self.root)
        snapshot["transcripts"][0]["content"] += " REWRITTEN"
        with self.assertRaisesRegex(RuntimeError, "key does not match"):
            exporter._verify_snapshot(snapshot, manifest)

        snapshot = exporter._load_snapshot(self.root)
        snapshot["chunks"][1]["metadata"]["source_file"] = "ghost.md"
        with self.assertRaisesRegex(RuntimeError, "no snapshot R2 object"):
            exporter._verify_snapshot(snapshot, manifest)

        snapshot = exporter._load_snapshot(self.root)
        snapshot["vectors"][0]["id"] = "ghost-vector"
        with self.assertRaisesRegex(RuntimeError, "absent from the snapshot"):
            exporter._verify_snapshot(snapshot, manifest)

    def test_mixed_chroma_document_binding_is_rejected(self) -> None:
        finalize_manifest(self.root, self.report, self.expected)
        manifest_path = self.root / "export-report.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        # vector_count is 1, so any value other than 0 or 1 is a mixed binding
        # state (some vectors carry the original Chroma document, others do
        # not) and must fail the uniform-binding contract.
        manifest["missing_chroma_document_count"] = 2
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "uniform"):
            validate_export(self.root, self.expected)

    def test_hnsw_metadata_rejects_executable_pickle_globals(self) -> None:
        hnsw = self.root / "segment"
        hnsw.mkdir()
        (hnsw / "data_level0.bin").write_bytes(b"placeholder")
        marker = self.root / "pickle-executed.txt"
        with (hnsw / "index_metadata.pickle").open("wb") as handle:
            pickle.dump(_ExecutablePickle(), handle)

        with patch.dict(os.environ, {"PLUGICT_TEST_PICKLE_MARKER": str(marker)}):
            with self.assertRaises(pickle.UnpicklingError):
                exporter._find_hnsw_segment(self.root)
        self.assertFalse(marker.exists())

    def test_r2_endpoint_and_bucket_are_pinned(self) -> None:
        valid = {
            "endpoint": "https://" + ("a" * 32) + ".r2.cloudflarestorage.com",
            "access_key_id": "id",
            "secret_access_key": "secret",
            "bucket": "plugict-vault",
        }
        path = self.root / "r2.json"
        path.write_text(json.dumps(valid), encoding="utf-8")
        self.assertEqual(validate_r2_credentials(path)["bucket"], "plugict-vault")
        for endpoint, bucket in (
            (valid["endpoint"].replace("https://", "http://"), "plugict-vault"),
            ("https://evil.example.com", "plugict-vault"),
            (valid["endpoint"], "wrong-bucket"),
        ):
            path.write_text(json.dumps({**valid, "endpoint": endpoint, "bucket": bucket}), encoding="utf-8")
            with self.assertRaises(RuntimeError):
                validate_r2_credentials(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)

from pathlib import Path
import copy
import sqlite3
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import compare_benchmark_reports as comparator
import run_benchmark as benchmark


METRICS = {
    "lexical_hit_at_1": 1.0,
    "lexical_hit_at_5": 1.0,
    "mrr": 1.0,
    "ndcg_at_5": 1.0,
    "timestamp_accuracy": 1.0,
    "timestamp_provenance_coverage": 1.0,
    "no_answer_accuracy": 1.0,
    "duplicate_rate": 0.0,
    "p50_latency_ms": 10.0,
    "p95_latency_ms": 10.0,
}


def _report(artifact_char):
    queries = ["holdout query", "development query"]
    splits = {"holdout query": "holdout", "development query": "development"}
    cases = []
    for query in queries:
        cases.append({
            "q": query,
            "split": splits[query],
            "metrics": dict(METRICS),
            "latency_ms": 10.0,
            "results": [],
        })
    holdout = dict(METRICS, n=1, avg_latency_ms=10.0)
    overall = dict(METRICS, n=2, avg_latency_ms=10.0)
    return {
        "schema_version": 2,
        "benchmark_spec_sha256": "a" * 64,
        "runtime_source_sha256": "b" * 64,
        "encrypted_artifact_sha256": artifact_char * 64,
        "corpus_inventory_sha256": "9" * 64,
        "corpus_inventory_count": 581,
        "corpus_identity_basis": "opened_vault_source_file_video_id_inventory_v1",
        "corpus_manifest_sha256": "c" * 64,
        "query_set": queries,
        "split_assignments": splits,
        "strategies": {"single": overall},
        "splits": {"single": {"holdout": holdout, "development": holdout}},
        "per_case": {"single": cases},
    }


def test_compare_accepts_exact_paired_identified_reports():
    result = comparator.compare(_report("d"), _report("e"))
    assert result["promotion_pass"] is True
    assert result["paired_queries"]["single"]["holdout_n"] == 1


def test_compare_rejects_stale_precomputed_aggregates():
    v2 = _report("d")
    v3 = _report("e")
    v3["per_case"]["single"][0]["metrics"]["ndcg_at_5"] = 0.0
    with pytest.raises(ValueError, match="stale aggregate"):
        comparator.compare(v2, v3)


@pytest.mark.parametrize("mutation", ["disjoint", "split", "runtime", "corpus_inventory", "same_artifact", "zero_holdout"])
def test_compare_fails_closed_for_invalid_pairing_or_identity(mutation):
    v2 = _report("d")
    v3 = _report("e")
    if mutation == "disjoint":
        v3["query_set"] = ["other one", "other two"]
    elif mutation == "split":
        v3["split_assignments"]["holdout query"] = "development"
    elif mutation == "runtime":
        v3["runtime_source_sha256"] = "f" * 64
    elif mutation == "corpus_inventory":
        v3["corpus_inventory_sha256"] = "8" * 64
    elif mutation == "same_artifact":
        v3["encrypted_artifact_sha256"] = v2["encrypted_artifact_sha256"]
    elif mutation == "zero_holdout":
        for report in (v2, v3):
            report["split_assignments"] = {q: "development" for q in report["query_set"]}
            for case in report["per_case"]["single"]:
                case["split"] = "development"
    with pytest.raises(ValueError, match="invalid benchmark comparison"):
        comparator.compare(v2, v3)


def test_lexical_hit_requires_coherent_term_coverage_in_one_result():
    case = {"q": "concept", "expect_terms": ["alpha", "beta", "gamma"]}
    metrics = benchmark.evaluate(case, [
        {"snippet": "alpha only"},
        {"snippet": "beta only"},
        {"snippet": "gamma only"},
    ])
    assert metrics["lexical_hit_at_1"] == 0.0
    assert metrics["lexical_hit_at_5"] == 0.0


def test_no_answer_case_uses_conservative_evidence_gate_and_not_lexical_metrics():
    case = {"q": "photosynthesis chloroplast", "expect_terms": [], "no_answer": True}
    passed = benchmark.evaluate(case, [{"snippet": "ICT market structure"}])
    failed = benchmark.evaluate(case, [{"snippet": "photosynthesis chloroplast"}])
    assert passed["no_answer_accuracy"] == 1.0
    assert failed["no_answer_accuracy"] == 0.0
    assert passed["lexical_hit_at_1"] is None
    assert passed["mrr"] is None


def test_zero_second_timestamp_provenance_accepts_canonical_plain_youtube_url():
    assert benchmark._valid_timestamp_provenance({
        "video_id": "abc", "timing_precision": "unknown",
        "start_seconds": 0, "timestamp": "0:00",
        "video_url": "https://youtu.be/abc",
    }) is True


@pytest.mark.parametrize("bad_url", [
    "https://youtu.be/wrong?t=60",
    "https://evil.invalid/?t=60",
    "https://youtu.be/expected?t=600",
])
def test_nonzero_timestamp_provenance_rejects_noncanonical_urls(bad_url):
    assert benchmark._valid_timestamp_provenance({
        "video_id": "expected", "timing_precision": "unknown",
        "start_seconds": 60, "timestamp": "1:00", "video_url": bad_url,
    }) is False
    assert benchmark._valid_timestamp_provenance({
        "video_id": "expected", "timing_precision": "unknown",
        "start_seconds": 60, "timestamp": "1:00",
        "video_url": "https://youtu.be/expected?t=60",
    }) is True


def test_corpus_identity_is_derived_from_opened_vault_inventory_and_metadata():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE vault_metadata(key TEXT, value TEXT)")
    db.execute("CREATE TABLE transcripts_fts(source_file TEXT, video_id TEXT)")
    db.execute("INSERT INTO vault_metadata VALUES ('corpus_manifest_hash', ?)", ("c" * 64,))
    db.executemany("INSERT INTO transcripts_fts VALUES (?, ?)", [
        ("b.md", "video-b"), ("a.md", "video-a"), ("a.md", "video-a"),
    ])
    identity = benchmark._vault_corpus_identity(db)
    assert identity["corpus_manifest_sha256"] == "c" * 64
    assert identity["corpus_inventory_count"] == 2
    assert len(identity["corpus_inventory_sha256"]) == 64


def test_comparator_accepts_legacy_v2_without_content_manifest_when_inventory_matches():
    v2 = _report("d")
    v3 = _report("e")
    v2["corpus_manifest_sha256"] = None
    result = comparator.compare(v2, v3)
    assert result["promotion_pass"] is True
    assert result["identities"]["v2_corpus_manifest_sha256"] is None


def test_multi_only_strategy_exit_does_not_index_single():
    report = {"strategies": {"multi": {"lexical_hit_at_5": 0.9}}}
    assert benchmark._quality_exit_code(report, ["multi"]) == 0

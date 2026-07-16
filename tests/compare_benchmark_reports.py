#!/usr/bin/env python3
"""Fail-closed comparison of independently produced V2/V3 benchmark reports."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

REPORT_SCHEMA_VERSION = 2
METRICS = (
    "lexical_hit_at_1", "lexical_hit_at_5", "mrr", "ndcg_at_5",
    "timestamp_accuracy", "timestamp_provenance_coverage", "duplicate_rate",
    "no_answer_accuracy",
    "p50_latency_ms", "p95_latency_ms",
)
IDENTITY_FIELDS = (
    "benchmark_spec_sha256", "runtime_source_sha256",
    "encrypted_artifact_sha256", "corpus_inventory_sha256",
)


def _delta(old, new):
    if old is None or new is None:
        return None
    return new - old


def _valid_sha(value):
    return isinstance(value, str) and len(value) == 64 and all(
        char in "0123456789abcdef" for char in value.lower()
    )


def _percentile(values, p):
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((p / 100) * (len(ordered) - 1))))
    return ordered[index]


def _summarize_cases(cases, split=None):
    selected = [case for case in cases if split is None or case.get("split") == split]
    metrics = [case["metrics"] for case in selected]
    def avg(key):
        values = [row.get(key) for row in metrics if row.get(key) is not None]
        return sum(values) / len(values) if values else None
    latencies = [float(case["latency_ms"]) for case in selected]
    n = len(selected) or 1
    return {
        "n": len(selected),
        "lexical_hit_at_1": avg("lexical_hit_at_1"),
        "lexical_hit_at_5": avg("lexical_hit_at_5"),
        "mrr": avg("mrr"),
        "ndcg_at_5": avg("ndcg_at_5"),
        "timestamp_accuracy": avg("timestamp_accuracy"),
        "timestamp_provenance_coverage": avg("timestamp_provenance_coverage"),
        "no_answer_accuracy": avg("no_answer_accuracy"),
        "duplicate_rate": avg("duplicate_rate"),
        "avg_latency_ms": sum(latencies) / n,
        "p50_latency_ms": _percentile(latencies, 50),
        "p95_latency_ms": _percentile(latencies, 95),
    }


def _same_metric(left, right, tolerance=1e-9):
    if left is None or right is None:
        return left is right
    return abs(float(left) - float(right)) <= tolerance


def _validate_reports(v2, v3):
    errors = []
    for label, report in (("v2", v2), ("v3", v3)):
        if report.get("schema_version") != REPORT_SCHEMA_VERSION:
            errors.append(f"{label} schema_version must be {REPORT_SCHEMA_VERSION}")
        for field in IDENTITY_FIELDS:
            if not _valid_sha(report.get(field)):
                errors.append(f"{label} missing valid {field}")
        if report.get("corpus_identity_basis") != "opened_vault_source_file_video_id_inventory_v1":
            errors.append(f"{label} has unsupported corpus_identity_basis")
        if not isinstance(report.get("corpus_inventory_count"), int) or report["corpus_inventory_count"] <= 0:
            errors.append(f"{label} corpus_inventory_count must be positive")
        manifest = report.get("corpus_manifest_sha256")
        if manifest is not None and not _valid_sha(manifest):
            errors.append(f"{label} has malformed optional corpus_manifest_sha256")
        query_set = report.get("query_set")
        if not isinstance(query_set, list) or not query_set:
            errors.append(f"{label} query_set must be nonempty")
        elif len(query_set) != len(set(query_set)):
            errors.append(f"{label} query_set contains duplicates")
        if not isinstance(report.get("split_assignments"), dict):
            errors.append(f"{label} split_assignments must be an object")

    for field in ("benchmark_spec_sha256", "runtime_source_sha256",
                  "corpus_inventory_sha256", "corpus_inventory_count",
                  "corpus_identity_basis"):
        if v2.get(field) != v3.get(field):
            errors.append(f"report identity mismatch: {field}")
    manifest2 = v2.get("corpus_manifest_sha256")
    manifest3 = v3.get("corpus_manifest_sha256")
    if manifest2 is not None and manifest3 is not None and manifest2 != manifest3:
        errors.append("report identity mismatch: corpus_manifest_sha256")
    if v2.get("encrypted_artifact_sha256") == v3.get("encrypted_artifact_sha256"):
        errors.append("V2 and V3 encrypted artifact identities must differ")
    if v2.get("query_set") != v3.get("query_set"):
        errors.append("query sets or query order differ")
    if v2.get("split_assignments") != v3.get("split_assignments"):
        errors.append("split assignments differ")

    query_set = v2.get("query_set") or []
    split_assignments = v2.get("split_assignments") or {}
    if set(split_assignments) != set(query_set):
        errors.append("split assignments do not exactly cover query_set")
    if not any(split_assignments.get(q) == "holdout" for q in query_set):
        errors.append("holdout split must contain at least one query")

    strategies2 = set((v2.get("strategies") or {}).keys())
    strategies3 = set((v3.get("strategies") or {}).keys())
    if strategies2 != strategies3 or not strategies2:
        errors.append("strategy sets must be identical and nonempty")
    if "single" not in strategies2:
        errors.append("promotion comparison requires the single strategy")

    for strategy in sorted(strategies2 & strategies3):
        for label, report in (("v2", v2), ("v3", v3)):
            cases = (report.get("per_case") or {}).get(strategy)
            if not isinstance(cases, list):
                errors.append(f"{label} {strategy} per_case must be a list")
                continue
            queries = [case.get("q") for case in cases]
            if queries != query_set:
                errors.append(f"{label} {strategy} cases do not exactly match query_set")
            for case in cases:
                q = case.get("q")
                if case.get("split") != split_assignments.get(q):
                    errors.append(f"{label} {strategy} split mismatch for {q!r}")
            holdout_n = sum(1 for case in cases if case.get("split") == "holdout")
            if holdout_n <= 0:
                errors.append(f"{label} {strategy} has zero paired holdout cases")
            summary = ((report.get("splits") or {}).get(strategy) or {}).get("holdout") or {}
            if summary.get("n") != holdout_n:
                errors.append(f"{label} {strategy} holdout summary count mismatch")
            for scope_name, scope in (
                ("overall", (report.get("strategies") or {}).get(strategy) or {}),
                ("holdout", summary),
            ):
                for metric in METRICS:
                    if metric not in scope:
                        errors.append(f"{label} {strategy} {scope_name} missing {metric}")
            try:
                recomputed_scopes = {
                    "overall": _summarize_cases(cases),
                    "holdout": _summarize_cases(cases, "holdout"),
                }
                supplied_scopes = {
                    "overall": (report.get("strategies") or {}).get(strategy) or {},
                    "holdout": summary,
                }
                for scope_name, expected in recomputed_scopes.items():
                    supplied = supplied_scopes[scope_name]
                    for metric, expected_value in expected.items():
                        if not _same_metric(supplied.get(metric), expected_value):
                            errors.append(
                                f"{label} {strategy} {scope_name} stale aggregate {metric}"
                            )
            except (KeyError, TypeError, ValueError) as exc:
                errors.append(f"{label} {strategy} cannot recompute aggregates: {exc}")

    if errors:
        raise ValueError("invalid benchmark comparison: " + "; ".join(errors))


def compare(v2, v3):
    _validate_reports(v2, v3)
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "baseline": "A2-v2 independent encrypted index",
        "candidate": "semantic-v3 independent encrypted index",
        "identities": {
            "benchmark_spec_sha256": v2["benchmark_spec_sha256"],
            "runtime_source_sha256": v2["runtime_source_sha256"],
            "corpus_identity_basis": v2["corpus_identity_basis"],
            "corpus_inventory_sha256": v2["corpus_inventory_sha256"],
            "corpus_inventory_count": v2["corpus_inventory_count"],
            "v2_corpus_manifest_sha256": v2.get("corpus_manifest_sha256"),
            "v3_corpus_manifest_sha256": v3.get("corpus_manifest_sha256"),
            "v2_encrypted_artifact_sha256": v2["encrypted_artifact_sha256"],
            "v3_encrypted_artifact_sha256": v3["encrypted_artifact_sha256"],
        },
        "strategies": {},
        "paired_queries": {},
        "quality_gates": {},
        "limitations": [
            "Lexical metrics require coherent expected-term coverage within one result.",
            "This proves independent-index retrieval behavior, not human-reviewed claim correctness.",
            "Timestamp accuracy uses only explicitly frozen video_id + timestamp labels.",
            "Corpus pairing is exact at opened-vault source_file/video_id inventory level; legacy V2 has no content-manifest hash, so exact transcript-byte equality cannot be claimed.",
            "Do not tune V3 against the deterministic holdout split.",
        ],
    }
    for strategy in sorted(v2["strategies"]):
        old_strategy_cases = v2["per_case"][strategy]
        new_strategy_cases = v3["per_case"][strategy]
        whole2 = _summarize_cases(old_strategy_cases)
        whole3 = _summarize_cases(new_strategy_cases)
        h2 = _summarize_cases(old_strategy_cases, "holdout")
        h3 = _summarize_cases(new_strategy_cases, "holdout")
        report["strategies"][strategy] = {
            "overall": {m: {"v2": whole2.get(m), "v3": whole3.get(m),
                             "delta": _delta(whole2.get(m), whole3.get(m))}
                        for m in METRICS},
            "holdout": {m: {"v2": h2.get(m), "v3": h3.get(m),
                             "delta": _delta(h2.get(m), h3.get(m))}
                        for m in METRICS},
        }
        old_cases = {case["q"]: case for case in v2["per_case"][strategy]}
        new_cases = {case["q"]: case for case in v3["per_case"][strategy]}
        paired = []
        for q in v2["query_set"]:
            old = old_cases[q]
            new = new_cases[q]
            paired.append({
                "q": q,
                "split": old["split"],
                "lexical_hit_at_1_delta": _delta(
                    old["metrics"]["lexical_hit_at_1"], new["metrics"]["lexical_hit_at_1"]),
                "lexical_hit_at_5_delta": _delta(
                    old["metrics"]["lexical_hit_at_5"], new["metrics"]["lexical_hit_at_5"]),
                "mrr_delta": _delta(old["metrics"]["mrr"], new["metrics"]["mrr"]),
                "ndcg_at_5_delta": _delta(
                    old["metrics"]["ndcg_at_5"], new["metrics"]["ndcg_at_5"]),
            })
        report["paired_queries"][strategy] = {
            "n": len(paired),
            "holdout_n": sum(1 for p in paired if p["split"] == "holdout"),
            "improved": sum(1 for p in paired if (p["ndcg_at_5_delta"] or 0) > 0),
            "same": sum(1 for p in paired if (p["ndcg_at_5_delta"] or 0) == 0),
            "worse": sum(1 for p in paired if (p["ndcg_at_5_delta"] or 0) < 0),
            "cases": paired,
        }

    v2_single_cases = v2["per_case"]["single"]
    v3_single_cases = v3["per_case"]["single"]
    h2 = _summarize_cases(v2_single_cases, "holdout")
    h3 = _summarize_cases(v3_single_cases, "holdout")
    overall2 = _summarize_cases(v2_single_cases)
    overall3 = _summarize_cases(v3_single_cases)
    gates = {
        "holdout_lexical_hit_at_1_no_regression":
            h3["lexical_hit_at_1"] >= h2["lexical_hit_at_1"],
        "holdout_lexical_hit_at_5_no_regression":
            h3["lexical_hit_at_5"] >= h2["lexical_hit_at_5"],
        "holdout_mrr_within_0_02": h3["mrr"] >= h2["mrr"] - 0.02,
        "holdout_ndcg_at_5_within_0_02": h3["ndcg_at_5"] >= h2["ndcg_at_5"] - 0.02,
        "timestamp_accuracy_labeled_and_no_regression":
            overall2["timestamp_accuracy"] is not None
            and overall3["timestamp_accuracy"] is not None
            and overall3["timestamp_accuracy"] >= overall2["timestamp_accuracy"],
        "timestamp_provenance_coverage_no_regression":
            h3["timestamp_provenance_coverage"] >= h2["timestamp_provenance_coverage"],
        "no_answer_accuracy_labeled_and_no_regression":
            overall2["no_answer_accuracy"] is not None
            and overall3["no_answer_accuracy"] is not None
            and overall3["no_answer_accuracy"] >= overall2["no_answer_accuracy"],
        "duplicate_rate_within_0_01":
            h3["duplicate_rate"] <= h2["duplicate_rate"] + 0.01,
        "nonzero_paired_holdout": report["paired_queries"]["single"]["holdout_n"] > 0,
    }
    report["quality_gates"] = gates
    report["promotion_pass"] = all(gates.values())
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--v2", required=True, type=Path)
    parser.add_argument("--v3", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    v2 = json.loads(args.v2.read_text(encoding="utf-8"))
    v3 = json.loads(args.v3.read_text(encoding="utf-8"))
    result = compare(v2, v3)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"promotion_pass": result["promotion_pass"],
                      "quality_gates": result["quality_gates"]}, indent=2))
    return 0 if result["promotion_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

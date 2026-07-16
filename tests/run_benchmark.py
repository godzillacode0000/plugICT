"""
Retrieval-quality eval harness for the ICT Vault.

Compares:
  1. normal single search
  2. multi-search
  3. multi-search plus selective context expansion

Run seller-side against a real vault:

    ICT_VAULT_FILE=/path/ict-vault.kevin \
    ICT_VAULT_LICENSE=/path/license.key \
    python tests/run_benchmark.py --json benchmark.json
"""

import hashlib
import json
import math
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import vault_core as vc  # noqa: E402
from vault_core import VaultSession  # noqa: E402

BENCH = Path(__file__).resolve().parent / "benchmark_queries.json"
REPORT_SCHEMA_VERSION = 2


def result_text(r):
    return ((r.get("title", "") or "") + " " + (r.get("text") or r.get("snippet") or "")).lower()


def _relevance(case, result):
    terms = [t.lower() for t in case.get("expect_terms", [])]
    if not terms:
        return 0
    blob = result_text(result)
    return sum(1 for t in terms if t in blob)


def _is_lexical_hit(case, result, default_threshold=0.66):
    terms = case.get("expect_terms", [])
    if not terms:
        return False
    threshold = float(case.get("min_term_coverage", default_threshold))
    return _relevance(case, result) / len(terms) >= threshold


def _valid_timestamp_provenance(result):
    precision = result.get("timing_precision")
    seconds = result.get("start_seconds")
    timestamp = result.get("timestamp") or result.get("start_ts")
    url = result.get("video_url", "")
    if precision not in {"next_segment_inferred", "unknown"}:
        return False
    if not isinstance(seconds, int) or seconds < 0:
        return False
    expected_link = f"https://youtu.be/{result.get('video_id', '')}"
    canonical_link = expected_link if seconds == 0 else f"{expected_link}?t={seconds}"
    return vc.timestamp_seconds(timestamp) == seconds and url == canonical_link


def _dcg(rels):
    return sum(rel / math.log2(i + 2) for i, rel in enumerate(rels))


def evaluate(case, ranked, min_results=1):
    """Pure lexical-coverage telemetry for one frozen query."""
    terms = [t.lower() for t in case.get("expect_terms", [])]
    no_answer = bool(case.get("no_answer"))
    enough = len(ranked) >= min_results
    top1 = bool(ranked) and _is_lexical_hit(case, ranked[0])
    top5 = bool(terms) and any(_is_lexical_hit(case, r) for r in ranked[:5])

    if no_answer:
        evidence_gate = vc.assess_answerability(case["q"], ranked)
        no_answer_accuracy = 1.0 if evidence_gate["status"] in {
            "no_retrieved_evidence", "no_lexical_coverage",
        } else 0.0
    else:
        no_answer_accuracy = None

    first_hit = None
    rels = []
    for i, r in enumerate(ranked[:5], 1):
        rel = _relevance(case, r)
        rels.append(rel)
        if _is_lexical_hit(case, r) and first_hit is None:
            first_hit = i
    mrr = (1.0 / first_hit) if first_hit else 0.0
    ideal = sorted(rels, reverse=True)
    ndcg5 = (_dcg(rels) / _dcg(ideal)) if _dcg(ideal) else 0.0

    expected_ts = case.get("expected_timestamp")
    expected_video_id = case.get("expected_video_id")
    if expected_ts:
        timestamp_accuracy = 1.0 if any(
            (r.get("timestamp") or r.get("start_ts")) == expected_ts
            and (not expected_video_id or r.get("video_id") == expected_video_id)
            for r in ranked[:5]
        ) else 0.0
    else:
        timestamp_accuracy = None

    ids = [(r.get("video_id"), r.get("timestamp") or r.get("start_ts"), r.get("title"))
           for r in ranked]
    timestamp_provenance_coverage = (
        sum(1 for r in ranked[:5] if _valid_timestamp_provenance(r)) / len(ranked[:5])
        if ranked[:5] else 0.0
    )
    duplicate_rate = 0.0
    if ids:
        duplicate_rate = 1.0 - (len(set(ids)) / len(ids))

    return {
        "enough": enough,
        "top1": top1 and enough,
        "top5": top5 and enough,
        "lexical_hit_at_1": None if no_answer else (1.0 if (top1 and enough) else 0.0),
        "lexical_hit_at_5": None if no_answer else (1.0 if (top5 and enough) else 0.0),
        "mrr": None if no_answer else mrr,
        "ndcg_at_5": None if no_answer else ndcg5,
        "timestamp_accuracy": timestamp_accuracy,
        "timestamp_provenance_coverage": timestamp_provenance_coverage,
        "no_answer_accuracy": no_answer_accuracy,
        "duplicate_rate": duplicate_rate,
    }


def _pct(values, p):
    if not values:
        return 0.0
    s = sorted(values)
    i = min(len(s) - 1, int(round((p / 100) * (len(s) - 1))))
    return s[i]


def _variants(q):
    out = [q]
    expanded, changed = vc.expand_query(q)
    if changed and expanded.lower() != q.lower():
        out.append(expanded)
    compact = q.replace("what is ", "").replace("how does ict ", "").strip()
    if compact and compact.lower() not in {x.lower() for x in out}:
        out.append(compact)
    return out[:vc.MAX_QUERY_VARIANTS]


def _rss_mb():
    try:
        import psutil
        return psutil.Process().memory_info().rss / 1024 / 1024
    except Exception:
        return 0.0


def _run_strategy(session, case, strategy):
    q = case["q"]
    if strategy == "single":
        ranked, _, _ = session.search(q, top_k=5)
        return ranked
    if strategy == "multi":
        ranked, _ = session.multi_search(q, _variants(q), top_k=5)
        return ranked
    if strategy == "multi_context":
        internal, _ = vc.collect_multi_search_candidates(
            session.db, session._semantic_candidates, q, _variants(q), top_k=5)
        if internal:
            try:
                vc.expand_result_context(session.db, internal[0], before=1, after=1)
            except Exception:
                pass
        return vc.finalize_ranked_results(internal)
    raise ValueError(strategy)


def _summarize(rows, times):
    n = len(rows) or 1
    def avg(key):
        vals = [r[key] for r in rows if r[key] is not None]
        return (sum(vals) / len(vals)) if vals else None
    return {
        "n": len(rows),
        "lexical_hit_at_1": avg("lexical_hit_at_1"),
        "lexical_hit_at_5": avg("lexical_hit_at_5"),
        "mrr": avg("mrr"),
        "ndcg_at_5": avg("ndcg_at_5"),
        "timestamp_accuracy": avg("timestamp_accuracy"),
        "timestamp_provenance_coverage": avg("timestamp_provenance_coverage"),
        "no_answer_accuracy": avg("no_answer_accuracy"),
        "duplicate_rate": avg("duplicate_rate"),
        "avg_latency_ms": 1000 * sum(times) / n,
        "p50_latency_ms": 1000 * _pct(times, 50),
        "p95_latency_ms": 1000 * _pct(times, 95),
    }


def _summarize_cases(cases, split):
    selected = [c for c in cases if c["split"] == split]
    return _summarize(
        [c["metrics"] for c in selected],
        [c["latency_ms"] / 1000.0 for c in selected],
    )


def _sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _runtime_source_sha256():
    digest = hashlib.sha256()
    for path in (Path(__file__).resolve(), Path(vc.__file__).resolve()):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _vault_corpus_identity(db):
    """Derive corpus identity only from the opened encrypted vault.

    Legacy V2 predates content-manifest metadata, so the paired gate uses a
    canonical source/video inventory hash available in both generations. Newer
    vaults additionally report their stronger content-manifest hash.
    """
    rows = db.execute(
        "SELECT DISTINCT source_file, video_id FROM transcripts_fts "
        "ORDER BY source_file, video_id"
    ).fetchall()
    if not rows or any(not row[0] or not row[1] for row in rows):
        raise RuntimeError("opened vault has no valid source/video corpus inventory")
    inventory_bytes = json.dumps(rows, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    inventory_hash = hashlib.sha256(inventory_bytes).hexdigest()
    row = db.execute(
        "SELECT value FROM vault_metadata WHERE key = 'corpus_manifest_hash'"
    ).fetchone()
    manifest = (row[0] if row else "").lower()
    if manifest and (
        len(manifest) != 64
        or any(char not in "0123456789abcdef" for char in manifest)
    ):
        raise RuntimeError("opened vault has malformed corpus_manifest_hash metadata")
    return {
        "corpus_inventory_sha256": inventory_hash,
        "corpus_inventory_count": len(rows),
        "corpus_manifest_sha256": manifest or None,
        "corpus_identity_basis": "opened_vault_source_file_video_id_inventory_v1",
    }


def _split_for_query(query):
    return "holdout" if hashlib.sha256(query.encode("utf-8")).digest()[0] < 64 else "development"


def _quality_exit_code(report, selected_strategies):
    gate_strategy = "single" if "single" in report["strategies"] else selected_strategies[0]
    lexical_hit_5 = report["strategies"][gate_strategy]["lexical_hit_at_5"] or 0
    return 0 if lexical_hit_5 >= 0.80 else 1


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    json_out = None
    if "--json" in argv:
        json_out = argv[argv.index("--json") + 1]
    selected_strategies = ["single", "multi", "multi_context"]
    if "--strategies" in argv:
        selected_strategies = [
            value.strip() for value in argv[argv.index("--strategies") + 1].split(",")
            if value.strip()
        ]
        invalid = set(selected_strategies) - {"single", "multi", "multi_context"}
        if invalid:
            raise ValueError(f"Unknown benchmark strategies: {sorted(invalid)}")
        if not selected_strategies:
            raise ValueError("At least one benchmark strategy is required")

    spec_bytes = BENCH.read_bytes()
    spec = json.loads(spec_bytes)
    min_results = spec.get("min_results", 1)
    query_set = [case["q"] for case in spec["queries"]]
    split_assignments = {q: _split_for_query(q) for q in query_set}
    requested_corpus_manifest = os.environ.get("ICT_CORPUS_MANIFEST_SHA256", "").strip().lower()
    if requested_corpus_manifest and (
        len(requested_corpus_manifest) != 64
        or any(char not in "0123456789abcdef" for char in requested_corpus_manifest)
    ):
        raise RuntimeError("ICT_CORPUS_MANIFEST_SHA256 must be a 64-character SHA-256")
    artifact_sha256 = _sha256_file(vc.VAULT_FILE)
    runtime_sha256 = _runtime_source_sha256()

    peak_ram = _rss_mb()
    t0 = time.perf_counter()
    session = VaultSession().open()
    corpus_identity = _vault_corpus_identity(session.db)
    corpus_manifest = corpus_identity["corpus_manifest_sha256"]
    if requested_corpus_manifest and requested_corpus_manifest != corpus_manifest:
        session.close()
        raise RuntimeError("ICT_CORPUS_MANIFEST_SHA256 does not match the opened vault")
    cold_start = time.perf_counter() - t0
    peak_ram = max(peak_ram, _rss_mb())
    print(f"Vault unlocked in {cold_start:.1f}s (one-time)\n")

    strategies = selected_strategies
    data = {s: {"rows": [], "times": [], "cases": []} for s in strategies}

    try:
        for case in spec["queries"]:
            print(case["q"])
            for strategy in strategies:
                qt = time.perf_counter()
                ranked = _run_strategy(session, case, strategy)
                dt = time.perf_counter() - qt
                peak_ram = max(peak_ram, _rss_mb())
                metrics = evaluate(case, ranked, min_results)
                data[strategy]["rows"].append(metrics)
                data[strategy]["times"].append(dt)
                split = split_assignments[case["q"]]
                data[strategy]["cases"].append({
                    "q": case["q"],
                    "category": case.get("category"),
                    "split": split,
                    "metrics": metrics,
                    "latency_ms": 1000 * dt,
                    "results": [{
                        "rank": i,
                        "video_id": r.get("video_id"),
                        "timestamp": r.get("timestamp") or r.get("start_ts"),
                        "title": r.get("title"),
                        "relevance": _relevance(case, r),
                    } for i, r in enumerate(ranked[:5], 1)],
                })
                l1 = "NA" if metrics["lexical_hit_at_1"] is None else f"{metrics['lexical_hit_at_1']:.0f}"
                l5 = "NA" if metrics["lexical_hit_at_5"] is None else f"{metrics['lexical_hit_at_5']:.0f}"
                print(f"  {strategy:13s} L@1={l1} L@5={l5} {1000*dt:.0f}ms")
    finally:
        session.close()

    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "benchmark_spec_sha256": hashlib.sha256(spec_bytes).hexdigest(),
        "runtime_source_sha256": runtime_sha256,
        "encrypted_artifact_sha256": artifact_sha256,
        **corpus_identity,
        "query_set": query_set,
        "split_assignments": split_assignments,
        "cold_start_seconds": cold_start,
        "peak_ram_mb": peak_ram or None,
        "strategies": {
            s: _summarize(data[s]["rows"], data[s]["times"]) for s in strategies
        },
        "splits": {
            s: {
                "development": _summarize_cases(data[s]["cases"], "development"),
                "holdout": _summarize_cases(data[s]["cases"], "holdout"),
            } for s in strategies
        },
        "per_case": {s: data[s]["cases"] for s in strategies},
        "limitations": {
            "relevance": "lexical coverage against frozen expected terms (default 66% within one result); not human claim-quality review",
            "timestamp_accuracy": "exact video_id + timestamp match, reported only for explicitly labeled cases; field coverage is telemetry only",
            "no_answer_accuracy": "reported only for cases with no_answer=true",
            "split": "deterministic SHA-256 query split; threshold and retrieval settings must not be tuned on holdout",
            "peak_ram_mb": "uses psutil RSS when available",
            "corpus_identity": "paired identity is the source_file/video_id inventory derived from each opened vault; legacy V2 lacks content-manifest metadata, while V3 reports it separately",
        },
    }

    print("\n" + "=" * 64)
    print(f"Cold start: {report['cold_start_seconds']:.2f}s")
    print(f"Peak RAM: {report['peak_ram_mb'] or 'unavailable'} MB")
    for name, summary in report["strategies"].items():
        print(f"\n{name}")
        for k, v in summary.items():
            if k == "n":
                continue
            print(f"  {k}: {'n/a' if v is None else round(v, 4)}")

    if json_out:
        Path(json_out).write_text(json.dumps(report, indent=2))
        print(f"\nWrote {json_out}")

    return _quality_exit_code(report, selected_strategies)


if __name__ == "__main__":
    sys.exit(main())

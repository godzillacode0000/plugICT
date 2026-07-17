import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import vault_core as vc  # noqa: E402
import mcp_server as mcp  # noqa: E402


class _ScoreByText:
    def __init__(self, scores=None):
        self.pairs = None
        self.scores = scores

    def predict(self, pairs):
        self.pairs = pairs
        if self.scores is not None:
            return self.scores
        out = []
        for query, text in pairs:
            q_words = set(query.lower().split())
            out.append(sum(w in text.lower() for w in q_words))
        return out


def _agent_db():
    db = sqlite3.connect(":memory:")
    db.execute("""CREATE VIRTUAL TABLE transcripts_fts USING fts5(
        chunk_id, chunk_index, title, video_id, playlist, start_ts, end_ts, source_file, content,
        tokenize='porter unicode61')""")
    rows = [
        ("ck0", 0, "FVG Lesson", "v1", "P", "0:00", "0:10", "a.md",
         "0:00 before context " + ("b " * 400)),
        ("ck1", 1, "FVG Lesson", "v1", "P", "0:20", "0:35", "a.md",
         "0:20 fair value gap imbalance original answer " + ("x " * 700)),
        ("ck2", 2, "FVG Lesson", "v1", "P", "0:40", "0:55", "a.md",
         "0:40 after context " + ("a " * 400)),
        ("ck3", 0, "Silver Lesson", "v2", "P", "1:00", "1:20", "b.md",
         "1:00 silver bullet timing only"),
    ]
    db.executemany("INSERT INTO transcripts_fts VALUES (?,?,?,?,?,?,?,?,?)", rows)
    db.execute("CREATE TABLE entities(name,type,description,source_count)")
    db.execute("CREATE TABLE relations(from_entity,to_entity,relation_type,evidence)")
    db.commit()
    return db


def test_multi_search_fuses_variants_sources_and_dedups(monkeypatch):
    db = _agent_db()

    def semantic(query, limit, playlist, rrf_source, matched_query):
        return [{
            "source": "semantic", "method": "semantic", "chunk_id": "ck1",
            "title": "FVG Lesson", "video_id": "v1", "start_ts": "0:20",
            "timestamp": "0:20", "playlist": "P", "source_file": "a.md",
            "chunk_index": 1, "end_ts": "0:35",
            "_full_text": "semantic fair value gap original answer",
            "_rank_in_source": 0, "_rrf_source": rrf_source,
            "matched_queries": [matched_query], "retrieval_sources": ["semantic"],
        }]

    monkeypatch.setattr(vc, "_reranker", _ScoreByText())
    ranked, meta = vc.collect_multi_search_candidates(
        db, semantic, "what is the fair value gap original answer",
        ["fair value gap", "imbalance"], top_k=3)

    assert meta["queries"] == ["fair value gap", "imbalance"]
    assert ranked[0]["chunk_id"] == "ck1"
    assert set(ranked[0]["matched_queries"]) == {"fair value gap", "imbalance"}
    assert {"keyword", "semantic"} <= set(ranked[0]["retrieval_sources"])


def test_variant_coverage_reserves_one_result_per_query():
    ranked = [
        {"chunk_id": "global", "video_id": "v1", "start_ts": "0:00", "_variant_scores": {"q1": 0.04}},
        {"chunk_id": "also-q1", "video_id": "v2", "start_ts": "1:00", "_variant_scores": {"q1": 0.03}},
        {"chunk_id": "time", "video_id": "v1", "start_ts": "12:00", "_variant_scores": {"q2": 0.025}},
        {"chunk_id": "rules", "video_id": "v3", "start_ts": "2:00", "_variant_scores": {"q3": 0.02}},
        {"chunk_id": "filler", "video_id": "v4", "_variant_scores": {}},
    ]
    out = vc._prioritize_query_variant_coverage(
        ranked, ["definition", "time", "rules"], top_k=4)
    assert [c["chunk_id"] for c in out[:3]] == ["global", "time", "rules"]
    selected, _ = vc.diversify_by_video(out, top_k=4)
    assert [c["chunk_id"] for c in selected[:3]] == ["global", "time", "rules"]


def test_multi_search_reranks_against_original_question(monkeypatch):
    db = _agent_db()
    fake = _ScoreByText([1.0, 10.0])
    monkeypatch.setattr(vc, "_reranker", fake)
    vc.collect_multi_search_candidates(
        db, None, "original fair value gap", ["silver bullet", "fair value gap"], top_k=2)

    assert fake.pairs
    assert all(pair[0] == "original fair value gap" for pair in fake.pairs)


def test_stable_chunk_id_dedup_is_primary():
    cands = [
        {"chunk_id": "same", "video_id": "v1", "timestamp": "0:00", "_full_text": "short"},
        {"chunk_id": "same", "video_id": "v2", "timestamp": "9:00", "_full_text": "longer text"},
    ]
    out = vc.dedup_candidates(cands)
    assert len(out) == 1
    assert vc._cand_text(out[0]) == "longer text"


def test_result_refs_are_opaque_expiring_and_single_use():
    store = vc.ResultRefStore(ttl_seconds=10, max_uses=1)
    ref = store.issue({
        "chunk_id": "ck1", "source_file": "a.md", "chunk_index": 1,
        "start_ts": "9:59", "start_seconds": 7, "end_seconds": 10,
        "timing_precision": "exact",
    }, now=100)
    assert "ck1" not in ref
    resolved = store.resolve(ref, now=101)
    assert resolved["chunk_id"] == "ck1"
    assert resolved["start_seconds"] == 7
    assert resolved["end_seconds"] == 10
    assert resolved["timing_precision"] == "exact"
    with pytest.raises(vc.VaultError):
        store.resolve(ref, now=102)

    expired = store.issue({"chunk_id": "ck2"}, now=100)
    with pytest.raises(vc.VaultError):
        store.resolve(expired, now=111)


def test_expand_result_context_adjacency_timestamps_and_caps():
    db = _agent_db()
    payload = vc.expand_result_context(
        db, {"chunk_id": "ck1", "source_file": "a.md", "chunk_index": 1},
        before=1, after=1)

    assert [s["position"] for s in payload["sections"]] == ["before", "current", "after"]
    assert [s["timestamp"] for s in payload["sections"]] == ["0:00", "0:20", "0:40"]
    assert [s["end_ts"] for s in payload["sections"]] == ["0:10", "0:35", "0:55"]
    assert len(payload["sections"][0]["text"]) <= 500
    assert len(payload["sections"][1]["text"]) <= 1000
    assert len(payload["sections"][2]["text"]) <= 500
    assert payload["total_chars"] <= 2000


def test_search_vault_honours_rerank_flag(monkeypatch):
    db = _agent_db()
    monkeypatch.setattr(mcp, "ensure_vault", lambda: None)
    monkeypatch.setattr(mcp, "_db", db)
    monkeypatch.setattr(mcp, "_chroma_dir", "missing")
    monkeypatch.setattr(mcp, "_fts_candidates", lambda *args, **kwargs: [
        {"chunk_id": "ck3", "title": "Silver Lesson", "video_id": "v2",
         "start_ts": "1:00", "timestamp": "1:00", "source_file": "b.md",
         "chunk_index": 0, "_full_text": "silver bullet timing", "_rank_in_source": 0,
         "_rrf_source": "keyword"},
        {"chunk_id": "ck1", "title": "FVG Lesson", "video_id": "v1",
         "start_ts": "0:20", "timestamp": "0:20", "source_file": "a.md",
         "chunk_index": 1, "_full_text": "fair value gap", "_rank_in_source": 1,
         "_rrf_source": "keyword"},
    ])
    calls = []

    def fake_rerank(question, results, top_k):
        calls.append(question)
        return list(reversed(results))[:top_k]

    monkeypatch.setattr(vc, "rerank", fake_rerank)
    mcp.search_vault("fair value gap", top_k=2, kg=False, rerank=False)
    assert calls == []
    mcp.search_vault("fair value gap", top_k=2, kg=False, rerank=True)
    assert calls == ["fair value gap"]


def test_answerability_gate_is_structured_and_conservative():
    assert vc.assess_answerability("fair value gap", [])["status"] == "no_retrieved_evidence"
    partial = vc.assess_answerability("fair value gap entry", [
        {"video_id": "v1", "snippet": "This explains a fair value gap."}
    ])
    assert partial["status"] == "partial_lexical_coverage"
    supported = vc.assess_answerability("fair value gap entry", [
        {"video_id": "v1", "snippet": "Fair value gap entry rules."},
        {"video_id": "v2", "snippet": "More evidence."},
    ])
    assert supported["status"] == "full_lexical_coverage"
    assert supported["query_term_coverage"] == 1.0
    assert supported["claim_support"] is False
    conflict = vc.assess_answerability("fair value gap", [
        {"video_id": "v1", "snippet": "evidence", "evidence_conflict": True}
    ])
    assert conflict["status"] == "conflicting"
    assert conflict["heuristic"] is True


def test_adjacent_merge_never_moves_text_across_citation_provenance():
    cited = {
        "chunk_id": "a", "video_id": "v", "start_ts": "0:00",
        "_full_text": "short cited text", "rrf_score": 1.0,
    }
    adjacent = {
        "chunk_id": "b", "video_id": "v", "start_ts": "0:30",
        "_full_text": "different adjacent evidence " * 20, "rrf_score": 0.5,
    }
    merged = vc._merge_two_candidates(cited, adjacent)
    assert merged["chunk_id"] == "a"
    assert merged["start_ts"] == "0:00"
    assert merged["_full_text"] == "short cited text"


def test_adjacent_multi_query_facets_keep_distinct_citations():
    time_evidence = {
        "chunk_id": "time", "video_id": "v", "start_ts": "10:27",
        "_full_text": "10 a.m. to 11 a.m. New York", "rrf_score": 1.0,
        "matched_queries": ["silver bullet time window"],
    }
    entry_evidence = {
        "chunk_id": "entry", "video_id": "v", "start_ts": "12:21",
        "_full_text": "fair value gap entry", "rrf_score": 0.9,
        "matched_queries": ["silver bullet fair value gap entry"],
    }
    kept, merges = vc._merge_adjacent_same_video([time_evidence, entry_evidence])
    assert merges == 0
    assert {item["chunk_id"] for item in kept} == {"time", "entry"}
    selected, _ = vc.diversify_by_video(
        [time_evidence, entry_evidence], top_k=2, max_per_video=2,
    )
    assert {item["chunk_id"] for item in selected} == {"time", "entry"}


def test_adjacent_same_query_duplicates_still_merge():
    first = {
        "chunk_id": "a", "video_id": "v", "start_ts": "0:00",
        "_full_text": "first", "rrf_score": 1.0, "matched_queries": ["same query"],
    }
    second = {
        "chunk_id": "b", "video_id": "v", "start_ts": "0:30",
        "_full_text": "second", "rrf_score": 0.5, "matched_queries": ["same query"],
    }
    kept, merges = vc._merge_adjacent_same_video([first, second])
    assert merges == 1
    assert len(kept) == 1
    assert kept[0]["chunk_id"] == "a"


def test_timestamp_precision_survives_fts_hydration_and_finalization():
    db = sqlite3.connect(":memory:")
    db.execute("""CREATE VIRTUAL TABLE transcripts_fts USING fts5(
        chunk_id, chunk_index UNINDEXED, title, video_id, playlist, start_ts,
        end_ts, start_seconds UNINDEXED, end_seconds UNINDEXED,
        timing_precision UNINDEXED, source_file, content)""")
    db.execute(
        "INSERT INTO transcripts_fts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        ("cid", 0, "Lesson", "vid", "P", "0:05", "0:09", 5, 9,
         "unknown", "lesson.md", "fair value gap evidence"),
    )
    candidate = vc.fts_candidates(db, "fair value gap", 1)[0]
    final = vc.finalize_ranked_results([candidate])[0]
    assert final["timing_precision"] == "unknown"
    assert final["start_seconds"] == 5
    assert final["end_seconds"] == 9
    assert "chunk_id" not in final
    assert "source_file" not in final


def test_finalize_deeplink_uses_stored_start_seconds_not_display_timestamp():
    final = vc.finalize_ranked_results([{
        "title": "Lesson", "video_id": "vid", "playlist": "P",
        "timestamp": "9:59", "start_seconds": 7, "end_seconds": 10,
        "timing_precision": "exact", "text": "evidence",
        "_full_text": "evidence", "matched_queries": ["evidence"],
    }])[0]
    assert final["video_url"] == "https://youtu.be/vid?t=7"


def test_finalize_prefers_matched_variant_for_multifacet_snippet():
    text = (
        "This is the ICT Silver Bullet time based trading model. "
        "The second setup is the a.m. session. "
        "It focuses on 10 a.m. to 11 a.m. New York local time. "
        "Wait for a fair value gap and trade toward liquidity. "
        + ("Additional explanation. " * 40)
    )
    out = vc.finalize_ranked_results([{
        "_full_text": text,
        "matched_queries": [
            "ICT Silver Bullet time based trading model",
            "Silver Bullet 10am to 11am New York",
        ],
    }], query="What is the strategy and how do you trade it?")
    assert "10 a.m. to 11 a.m." in out[0]["snippet"]


def test_finalize_caps_and_no_hidden_text_leakage():
    out = vc.finalize_ranked_results([{
        "chunk_id": "ck1",
        "_full_text": "secret " + ("x" * 1500),
        "_debug": "hide",
        "title": "T",
        "video_id": "v",
        "start_ts": "0:00",
        "result_ref": "opaque",
    }])
    assert len(out[0]["snippet"]) == 500
    assert "chunk_id" not in out[0]
    assert "_full_text" not in out[0]
    assert "_debug" not in out[0]
    assert out[0]["result_ref"] == "opaque"

    capped = vc.finalize_ranked_results([{"_full_text": "x" * 1500}], snippet_chars=5000)
    assert len(capped[0]["snippet"]) == 1000


def test_work_unit_rate_limit(monkeypatch):
    mcp._query_timestamps.clear()
    monkeypatch.setattr(mcp, "_RATE_LIMIT_WORK_UNITS_PER_MINUTE", 3)
    assert mcp._rate_limit_exceeded(2) is False
    assert mcp._rate_limit_exceeded(2) is True
    mcp._query_timestamps.clear()


# ── SQL-first retrieval ────────────────────────────────────────────────────

def _sql_first_db():
    """In-memory vault with known entities and a modest row count so
    corpus_count-based discriminative-token extraction works."""
    db = sqlite3.connect(":memory:")
    db.execute("""CREATE VIRTUAL TABLE transcripts_fts USING fts5(
        chunk_id, chunk_index, title, video_id, playlist, start_ts, end_ts, start_seconds UNINDEXED,
        end_seconds UNINDEXED, source_file, content,
        tokenize='porter unicode61')""")
    rows = [
        ("ck0", 0, "FVG Lesson", "v1", "P", "0:00", "0:10", 0, 10, "a.md",
         "fair value gap definition and imbalance explanation"),
        ("ck1", 1, "FVG Lesson", "v1", "P", "0:20", "0:35", 20, 35, "a.md",
         "second stage reaccumulation or redistribution which is the unicorn of the market"),
        ("ck2", 2, "FVG Lesson", "v1", "P", "0:40", "0:55", 40, 55, "a.md",
         "after context fair value gap delivery to equilibrium"),
        ("ck3", 0, "Silver Lesson", "v2", "P", "1:00", "1:20", 60, 80, "b.md",
         "silver bullet time based trading model using displacement"),
        ("ck4", 1, "Silver Lesson", "v2", "P", "1:25", "1:40", 85, 100, "b.md",
         "silver bullet failure on news days without context"),
        ("ck5", 0, "Gap Theory", "v3", "P", "2:00", "2:20", 120, 140, "c.md",
         "new week opening gap provides directional bias for the week"),
        ("ck6", 1, "Gap Theory", "v3", "P", "2:25", "2:40", 145, 160, "c.md",
         "nwog can act as resistance or support for silver bullet entries"),
    ]
    db.executemany("INSERT INTO transcripts_fts VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    db.execute("CREATE TABLE entities(name,type,description,source_count)")
    db.execute("INSERT INTO entities VALUES (?,?,?,?)",
               ("Silver Bullet", "ict_model", "ICT time-based trading model", 50))
    db.execute("INSERT INTO entities VALUES (?,?,?,?)",
               ("NWOG", "ict_model", "New Week Opening Gap", 30))
    db.execute("CREATE TABLE relations(from_entity,to_entity,relation_type,evidence)")
    db.commit()
    return db


def test_sql_first_prefers_direct_lexical_match():
    """A query containing a known entity + rare discriminative token should
    return direct SQL results rather than falling back to hybrid."""
    db = _sql_first_db()
    results = vc.search_sql_first(db, "silver bullet unicorn", top_k=3)

    assert results is not None, "SQL-first should find direct lexical matches"
    assert len(results) >= 1
    snippets = " ".join(r["snippet"] for r in results).lower()
    assert "unicorn" in snippets
    assert "silver" in snippets or "bullet" in snippets


def test_sql_first_falls_back_when_evidence_weak():
    """A vague/generic query with no discriminative terms returns None
    so the hybrid fallback path can take over."""
    db = _sql_first_db()
    results = vc.search_sql_first(db, "how do I know when to enter a trade", top_k=3)

    assert results is None, "Generic query should fall back, not return SQL results"


def test_sql_first_multi_facet_reserves_evidence():
    """A multi-concept question (silver bullet + NWOG) should yield evidence
    for each facet, not just the first one that matched."""
    db = _sql_first_db()
    results = vc.search_sql_first(db, "how do I utilise Silver Bullet with NWOG", top_k=4)

    assert results is not None
    snippets = "\n".join(r["snippet"] for r in results).lower()
    assert "silver" in snippets or "bullet" in snippets
    assert "nwog" in snippets or "new week opening gap" in snippets


def test_sql_first_adjacent_context_expands_direct_hits():
    """When a direct SQL hit comes from chunk_index > 0, the returned
    result should include adjacent context from the same video."""
    db = _sql_first_db()
    results = vc.search_sql_first(db, "unicorn market", top_k=3)

    assert results is not None
    # row ck1 (chunk_index=1) is the Unicorn mention.
    unicorn_results = [r for r in results if "unicorn" in r["snippet"].lower()]
    assert unicorn_results, "Unicorn should appear in at least one result"

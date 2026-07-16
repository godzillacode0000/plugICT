from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import metadata_enricher as me
import vault_core as vc


def test_content_metadata_extraction_supports_buyer_shaped_input():
    result = me.enrich({
        "title": "PM Session Definition Example Warning Rule",
        "playlist": "2022 ICT Mentorship",
        "start_ts": "0:05",
        "snippet": (
            "FVG is defined as an imbalance. For example, price may revisit it. "
            "Be careful around news; the key principle is confirmation."
        ),
    })
    assert "FVG" in result["primary_concept"]
    assert result["is_definition"] is True
    assert result["is_example"] is True
    assert result["is_warning"] is True
    assert result["is_rule"] is True
    assert "pm-session" in result["session_tag"]
    assert "am-session" not in result["session_tag"]


def test_elapsed_video_timestamp_never_implies_market_session():
    early = me.enrich({"title": "Generic lesson", "start_ts": "0:05", "snippet": "text"})
    late = me.enrich({"title": "Generic lesson", "start_ts": "13:30:00", "snippet": "text"})
    assert early["session_tag"] == []
    assert late["session_tag"] == []


def test_content_precedence_supports_raw_and_finalized_candidates():
    raw = me.enrich({"_full_text": "MSS refers to a structural shift."})
    finalized = me.enrich({"snippet": "MSS refers to a structural shift."})
    assert raw["primary_concept"] == finalized["primary_concept"]
    assert raw["is_definition"] is True
    assert finalized["is_definition"] is True


def test_raw_enrichment_survives_query_dependent_snippet_finalization():
    raw = {
        "title": "Lesson", "playlist": "2022 ICT Mentorship",
        "start_ts": "0:00", "video_id": "abc",
        "_full_text": "opening context " + ("filler " * 100) + "FVG refers to an imbalance.",
    }
    enriched = me.enrich(raw)
    first = vc.finalize_ranked_results([enriched], query="opening context")[0]
    second = vc.finalize_ranked_results([enriched], query="FVG imbalance")[0]
    assert first["primary_concept"] == second["primary_concept"]
    assert "FVG" in first["primary_concept"]
    assert first["is_definition"] is second["is_definition"] is True


def test_lesson_type_order_is_deterministic():
    result = me.enrich({
        "title": "Rule Story Warning Example Definition",
        "snippet": "content",
    })
    assert result["lesson_type"] == [
        "Definition", "Example", "Warning", "Story", "Rule",
    ]

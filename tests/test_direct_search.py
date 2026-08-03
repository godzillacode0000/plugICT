from __future__ import annotations

import json

import plugict_search


def test_clean_result_exposes_citation_fields_only():
    result = plugict_search._clean_result(
        {
            "title": "FVG lesson",
            "video_id": "abc123",
            "playlist": "2022 ICT Mentorship",
            "timestamp": "1:59:25",
            "start_seconds": 7165,
            "snippet": "A fair value gap is three candles.",
            "source_file": r"C:\seller\private\transcript.md",
            "chunk_id": "ck_secret",
            "_full_text": "private full text",
        }
    )

    assert result["url"] == "https://youtu.be/abc123?t=7165"
    assert result["excerpt"] == "A fair value gap is three candles."
    assert "source_file" not in result
    assert "chunk_id" not in result
    assert "_full_text" not in result


def test_fast_search_uses_local_engine(monkeypatch):
    monkeypatch.setattr(
        plugict_search._engine,
        "search_vault",
        lambda *args, **kwargs: [
            {
                "title": "FVG lesson",
                "video_id": "abc123",
                "timestamp": "1:59:25",
                "start_seconds": 7165,
                "snippet": "A fair value gap is three candles.",
                "method": "keyword+sql_first",
            }
        ],
    )
    monkeypatch.setattr(plugict_search._engine, "_licensed_to", "buyer@example.com")

    payload = plugict_search.search(["What is FVG in ICT?"])

    assert payload["retrieval_method"] == "direct_local_sql_first"
    assert payload["licensed_to"] == "buyer@example.com"
    assert payload["glossary"][0]["term"] == "FVG"
    assert payload["results"][0]["url"].endswith("?t=7165")


def test_multi_query_uses_direct_multi_search(monkeypatch):
    calls = {}

    def fake_multi(question, queries, **kwargs):
        calls["question"] = question
        calls["queries"] = queries
        return {
            "results": [
                {
                    "title": "Silver Bullet",
                    "video_id": "sb123",
                    "timestamp": "10:00",
                    "start_seconds": 36000,
                    "snippet": "Fair value gap inside the time window.",
                }
            ],
            "answerability": {"status": "supported"},
        }

    monkeypatch.setattr(plugict_search._engine, "multi_search_vault", fake_multi)
    monkeypatch.setattr(plugict_search._engine, "_licensed_to", "buyer@example.com")

    payload = plugict_search.search(
        ["Silver Bullet timing", "Silver Bullet entry"],
        question="Create a Silver Bullet plan",
    )

    assert calls["question"] == "Create a Silver Bullet plan"
    assert payload["retrieval_method"] == "direct_local_multi_search"
    assert payload["answerability"]["status"] == "supported"


def test_markdown_output_is_readable():
    markdown = plugict_search.as_markdown(
        {
            "query": "What is FVG?",
            "retrieval_method": "direct_local_sql_first",
            "licensed_to": "buyer@example.com",
            "results": [
                {
                    "title": "FVG lesson",
                    "timestamp": "1:59:25",
                    "excerpt": "A fair value gap is three candles.",
                    "url": "https://youtu.be/abc123?t=7165",
                }
            ],
        }
    )

    assert "## PlugICT Direct Local Search" in markdown
    assert "A fair value gap is three candles." in markdown
    assert "https://youtu.be/abc123?t=7165" in markdown


def test_cli_json_is_valid(monkeypatch, capsys):
    monkeypatch.setattr(
        plugict_search,
        "search",
        lambda queries, **kwargs: {
            "product": "PlugICT",
            "licensed_to": "buyer@example.com",
            "query": queries[0],
            "queries": queries,
            "retrieval_method": "direct_local_search",
            "results": [],
        },
    )

    assert plugict_search.main(["--query", "What is FVG?"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["product"] == "PlugICT"
    assert payload["query"] == "What is FVG?"

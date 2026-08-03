#!/usr/bin/env python3
"""PlugICT direct local search runner.

This is the buyer-facing non-MCP entry point. It imports the existing local
vault/search engine, opens the encrypted vault only after license validation,
and emits capped source evidence as JSON or Markdown for the buyer's AI agent.
It never starts an MCP server and never sends a network retrieval request.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

import mcp_server as _engine
import vault_core as _vault
from vault_core import VaultError

MAX_QUERIES = 4
MAX_TOP_K = 25
MAX_DEEP_TOP_K = 10
MAX_SNIPPET_CHARS = 1000


def _url_for(result: dict[str, Any]) -> str:
    url = str(result.get("video_url") or result.get("source_link") or "").strip()
    if url:
        return url
    video_id = str(result.get("video_id") or "").strip()
    seconds = result.get("start_seconds")
    if video_id and isinstance(seconds, (int, float)):
        return f"https://youtu.be/{video_id}?t={int(seconds)}"
    return ""


def _clean_result(result: dict[str, Any]) -> dict[str, Any]:
    """Expose citation/evidence fields only; never leak internal paths or IDs."""
    allowed = (
        "title",
        "video_id",
        "playlist",
        "timestamp",
        "start_ts",
        "end_ts",
        "start_seconds",
        "end_seconds",
        "timing_precision",
        "method",
        "retrieval_sources",
        "matched_queries",
    )
    cleaned = {key: result[key] for key in allowed if result.get(key) not in (None, "", [])}
    excerpt = result.get("snippet") or result.get("text") or result.get("excerpt") or ""
    cleaned["excerpt"] = str(excerpt)[:MAX_SNIPPET_CHARS]
    url = _url_for(result)
    if url:
        cleaned["url"] = url
    return cleaned


def _retrieval_method(results: list[dict[str, Any]], deep: bool) -> str:
    if deep:
        return "direct_local_multi_search"
    if any("sql_first" in str(item.get("method", "")) for item in results):
        return "direct_local_sql_first"
    return "direct_local_search"


def _glossary_hits(queries: list[str]) -> list[dict[str, Any]]:
    text = " ".join(queries)
    hits = []
    for term, definition in _vault.ICT_SHORTFORMS.items():
        if re.search(rf"\b{re.escape(term)}\b", text, flags=re.IGNORECASE):
            hits.append(
                {
                    "term": term,
                    "definition": definition,
                    "related_terms": _vault.related_terms(term),
                }
            )
    return hits[:4]


def search(
    queries: list[str],
    *,
    question: str | None = None,
    mode: str = "auto",
    top_k: int = 5,
    playlist: str | None = None,
    snippet_chars: int = 750,
) -> dict[str, Any]:
    if not queries:
        raise ValueError("At least one --query is required.")
    if len(queries) > MAX_QUERIES:
        raise ValueError(f"A maximum of {MAX_QUERIES} query variants is supported per call.")

    top_k = max(1, min(int(top_k), MAX_TOP_K))
    snippet_chars = max(1, min(int(snippet_chars), MAX_SNIPPET_CHARS))
    deep = mode == "deep" or (mode == "auto" and len(queries) > 1)
    original_question = (question or queries[0]).strip()

    if deep:
        payload = _engine.multi_search_vault(
            original_question,
            queries,
            top_k=min(top_k, MAX_DEEP_TOP_K),
            playlist=playlist,
            snippet_chars=snippet_chars,
            research_mode=False,
            debug=False,
        )
        raw_results = payload.get("results", [])
        answerability = payload.get("answerability")
    else:
        raw_results = _engine.search_vault(
            queries[0],
            top_k=top_k,
            playlist=playlist,
            kg=True,
            rerank=False,
        )
        answerability = None

    results = [_clean_result(item) for item in raw_results if isinstance(item, dict)]
    licensed_to = str(getattr(_engine, "_licensed_to", "unknown") or "unknown")
    output: dict[str, Any] = {
        "product": "PlugICT",
        "licensed_to": licensed_to,
        "query": original_question,
        "queries": queries,
        "retrieval_method": _retrieval_method(raw_results, deep),
        "results": results,
    }
    glossary = _glossary_hits(queries)
    if glossary:
        output["glossary"] = glossary
    if playlist:
        output["playlist"] = playlist
    if answerability is not None:
        output["answerability"] = answerability
    return output


def doctor() -> dict[str, Any]:
    """Open and validate the local vault through the approved engine path."""
    _engine.ensure_vault()
    stats = _engine.vault_stats()
    return {
        "product": "PlugICT",
        "status": "ok",
        "licensed_to": stats.get("licensed_to", "unknown"),
        "transcripts": stats.get("transcripts"),
        "chunks": stats.get("chunks"),
        "playlists": stats.get("playlists"),
    }


def as_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "## PlugICT Direct Local Search",
        "",
        f"**Query:** {payload['query']}",
        f"**Retrieval:** `{payload['retrieval_method']}`",
        f"**Licensed to:** `{payload['licensed_to']}`",
        "",
    ]
    if payload.get("glossary"):
        lines.extend(["### Local glossary", ""])
        for item in payload["glossary"]:
            related = ", ".join(item.get("related_terms", []))
            lines.append(f"**{item['term']}:** {item['definition']}")
            if related:
                lines.append(f"**Related:** {related}")
        lines.append("")
    results = payload.get("results", [])
    if not results:
        lines.append("No relevant vault evidence found.")
        return "\n".join(lines) + "\n"
    for index, result in enumerate(results, 1):
        title = result.get("title", "Untitled")
        lines.extend(
            [
                f"### {index}. {title}",
                "",
                f"> {result.get('excerpt', '').replace(chr(10), ' ')}",
                "",
            ]
        )
        if result.get("timestamp"):
            lines.append(f"**Timestamp:** {result['timestamp']}")
        if result.get("playlist"):
            lines.append(f"**Playlist:** {result['playlist']}")
        if result.get("url"):
            lines.append(f"**Source:** {result['url']}")
        lines.append("")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Search the licensed PlugICT vault locally without MCP."
    )
    parser.add_argument(
        "--query",
        action="append",
        dest="queries",
        help="Search query; repeat up to four times for a multi-facet search.",
    )
    parser.add_argument(
        "--question",
        help="Original question used as the synthesis/rerank target in deep mode.",
    )
    parser.add_argument("--mode", choices=("auto", "fast", "deep"), default="auto")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--playlist")
    parser.add_argument("--snippet-chars", type=int, default=750)
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--doctor", action="store_true", help="Validate the local licensed vault.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.doctor:
            payload = doctor()
        else:
            payload = search(
                args.queries or [],
                question=args.question,
                mode=args.mode,
                top_k=args.top_k,
                playlist=args.playlist,
                snippet_chars=args.snippet_chars,
            )
        if args.format == "markdown" and not args.doctor:
            print(as_markdown(payload))
        else:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    except (ValueError, VaultError, RuntimeError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

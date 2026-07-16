"""
metadata_enricher.py — Deterministic metadata enrichment for PlugICT transcript chunks.

Takes a transcript chunk dict (from transcripts_fts) and returns the same dict
with additional metadata fields added. No LLM calls. Pure string parsing +
glossary matching. Fast (<1 ms per chunk). Safe for any input.

Typical chunk keys:
    chunk_id, chunk_index, title, video_id, playlist,
    start_ts, end_ts, source_file, content

Added keys:
    year               int | None    — extracted from playlist name
    playlist_family    str | None    — normalized playlist name (no 'ICT', 'Mentorship')
    video_number       str | None    — parsed from title (e.g. 'Month 01', 'Video 5')
    lesson_type        list[str]     — keywords found in title (Definition, Example, etc.)
    primary_concept    list[str]     — glossary acronyms (from ICT_SHORTFORMS) found in content
    session_tag        list[str]     — session/time tags explicitly present in title
    is_definition      bool          — content contains definition-like phrasing
    is_example         bool          — content contains example-like phrasing
    is_warning         bool          — content contains warning-like phrasing
    is_rule            bool          — content contains rule-like phrasing
"""

from __future__ import annotations

import re
from typing import Any

import vault_core as vc

# ── Playlist normalisation ────────────────────────────────────────────────────

# Words stripped from playlist names when deriving playlist_family.
_PLAYLIST_STOP_WORDS = {"ict", "mentorship", "mentorship", "series", "lecture", "lecture"}

# Regex: find a 4-digit year anywhere in a string.
_YEAR_PATTERN = re.compile(r"\b(19\d{2}|20\d{2})\b")

# ── Video number extraction ───────────────────────────────────────────────────

# Order matters: more specific patterns first.
_VIDEO_NUM_PATTERNS: list[re.Pattern] = [
    re.compile(r"(?:Month|Module)\s*[-:]?\s*(\d{1,2})", re.IGNORECASE),
    re.compile(r"(?:Video|Episode|Part|Lesson|Section|Chapter)\s*[-:]?\s*(\d{1,3})", re.IGNORECASE),
    re.compile(r"(?:Week|Day)\s*[-:]?\s*(\d{1,2})", re.IGNORECASE),
    re.compile(r"^(\d{1,2})[:\s]", re.IGNORECASE),   # leading number
]

# ── Lesson-type keywords (from title) ─────────────────────────────────────────

_LESSON_TYPE_KEYWORDS = (
    "Definition",
    "Example",
    "Warning",
    "Story",
    "Rule",
)

# ── Content boolean-flag patterns ─────────────────────────────────────────────

# is_definition patterns
_DEFINITION_PATTERNS = [
    re.compile(r"\bis defined as\b", re.IGNORECASE),
    re.compile(r"\brefers to\b", re.IGNORECASE),
    re.compile(r"\bmeans that\b", re.IGNORECASE),
    re.compile(r"\bis called\b", re.IGNORECASE),
    re.compile(r"\bcan be defined\b", re.IGNORECASE),
]

# is_example patterns
_EXAMPLE_PATTERNS = [
    re.compile(r"\bfor example\b", re.IGNORECASE),
    re.compile(r"\bfor instance\b", re.IGNORECASE),
    re.compile(r"\be\.g\.\b"),
    re.compile(r"\bsuch as\b", re.IGNORECASE),
    re.compile(r"\blike this\b", re.IGNORECASE),
    re.compile(r"\blet's look at\b", re.IGNORECASE),
    re.compile(r"\bhere's an example\b", re.IGNORECASE),
]

# is_warning patterns
_WARNING_PATTERNS = [
    re.compile(r"\bbe careful\b", re.IGNORECASE),
    re.compile(r"\bwatch out\b", re.IGNORECASE),
    re.compile(r"\bthis is important\b", re.IGNORECASE),
    re.compile(r"\bdon[\u2019']t\s+fall\s+for\b", re.IGNORECASE),
    re.compile(r"\bbeware\b", re.IGNORECASE),
    re.compile(r"\bcritical\s+to\s+understand\b", re.IGNORECASE),
    re.compile(r"\bpay attention\b", re.IGNORECASE),
]

# is_rule patterns
_RULE_PATTERNS = [
    re.compile(r"\bleading rule\b", re.IGNORECASE),
    re.compile(r"\brule number\b", re.IGNORECASE),
    re.compile(r"\brole\s+of\s+thumb\b", re.IGNORECASE),
    re.compile(r"\byou must always\b", re.IGNORECASE),
    re.compile(r"\byou should never\b", re.IGNORECASE),
    re.compile(r"\bthe first rule\b", re.IGNORECASE),
    re.compile(r"\bkey principle\b", re.IGNORECASE),
]

# ── Session / time tags (from title + timestamps) ─────────────────────────────

_SESSION_TIME_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("am-session", re.compile(r"\bAM\s+Session\b", re.IGNORECASE)),
    ("pm-session", re.compile(r"\bPM\s+Session\b", re.IGNORECASE)),
    ("kill-zone-am", re.compile(r"\b(AM\s+Kill\s*Zone|Kill\s*Zone\s+AM)\b", re.IGNORECASE)),
    ("kill-zone-pm", re.compile(r"\b(PM\s+Kill\s*Zone|Kill\s*Zone\s+PM)\b", re.IGNORECASE)),
    ("kill-zone", re.compile(r"\bKill\s*Zone\b", re.IGNORECASE)),
    ("london-open", re.compile(r"\bLondon\s+Open\b", re.IGNORECASE)),
    ("ny-open", re.compile(r"\b(New\s+York\s+Open|NY\s+Open)\b", re.IGNORECASE)),
    ("silver-bullet", re.compile(r"\bSilver\s+Bullet\b", re.IGNORECASE)),
    ("power-of-3", re.compile(r"\b(Power\s+of\s+3|PO3)\b", re.IGNORECASE)),
]

# ── Public API ────────────────────────────────────────────────────────────────


def enrich(chunk: dict[str, Any]) -> dict[str, Any]:
    """Return *chunk* with metadata fields added.

    The original chunk dict is NOT mutated; a new dict is returned.
    Guaranteed safe for any input — no exceptions raised.
    """
    result = dict(chunk)  # shallow copy

    title = _safe_str(result.get("title", ""))
    # Buyer search results expose ``snippet`` after finalization. Raw retrieval
    # candidates may instead carry ``content`` or ``_full_text``.
    content = _safe_str(
        result.get("content") or result.get("_full_text") or result.get("snippet") or ""
    )
    playlist = _safe_str(result.get("playlist", ""))
    start_ts = _safe_str(result.get("start_ts", ""))

    result["year"] = _extract_year(playlist)
    result["playlist_family"] = _extract_playlist_family(playlist)
    result["video_number"] = _extract_video_number(title)
    result["lesson_type"] = _extract_lesson_type(title)
    result["primary_concept"] = _extract_primary_concept(content)
    result["session_tag"] = _extract_session_tags(title, start_ts)
    result["is_definition"] = _any_match(content, _DEFINITION_PATTERNS)
    result["is_example"] = _any_match(content, _EXAMPLE_PATTERNS)
    result["is_warning"] = _any_match(content, _WARNING_PATTERNS)
    result["is_rule"] = _any_match(content, _RULE_PATTERNS)

    return result


# ── Internal helpers ──────────────────────────────────────────────────────────


def _safe_str(value: Any) -> str:
    """Convert arbitrary value to str, returning '' on any error."""
    try:
        if value is None:
            return ""
        return str(value)
    except Exception:
        return ""


def _extract_year(playlist: str) -> int | None:
    """Extract first 4-digit year from playlist name."""
    m = _YEAR_PATTERN.search(playlist)
    if m:
        try:
            return int(m.group(1))
        except (ValueError, TypeError):
            return None
    return None


def _extract_playlist_family(playlist: str) -> str | None:
    """Normalize playlist name by stripping ICT/Mentorship/Series/Lecture noise.

    Examples:
        '2022 ICT Mentorship'   → '2022'
        'ICT 2024 Mentorship'   → '2024'
        '2025 Lecture Series'   → '2025'
        'Forex Series'          → 'Forex'
        'Other / Misc'          → None
    """
    if not playlist or playlist == "Other / Misc":
        return None

    # Lowercase for word-by-word filtering, but preserve original tokens for
    # case-insensitive comparison.
    words = playlist.split()
    family_words = [
        w for w in words
        if w.lower() not in _PLAYLIST_STOP_WORDS
           and w.lower().rstrip("s") not in _PLAYLIST_STOP_WORDS  # handle "Lectures"
    ]
    family = " ".join(family_words).strip()
    return family if family else None


def _extract_video_number(title: str) -> str | None:
    """Parse a video number from the title.

    Tries patterns in priority order: Month/Module, Video/Episode, Week/Day,
    leading number. Returns the first match as a string (e.g. '01', '5').
    """
    for pattern in _VIDEO_NUM_PATTERNS:
        m = pattern.search(title)
        if m:
            return m.group(1)
    return None


def _extract_lesson_type(title: str) -> list[str]:
    """Return list of lesson-type tags found in the title.

    Checks for: Definition, Example, Warning, Story, Rule (case-insensitive
    but emitted in the canonical keyword order).
    """
    found: list[str] = []
    for kw in _LESSON_TYPE_KEYWORDS:
        # Word-boundary match so 'Rule' doesn't hit 'PrudentialRule'
        if re.search(rf"\b{re.escape(kw)}\b", title, re.IGNORECASE):
            found.append(kw)
    return found


def _extract_primary_concept(content: str) -> list[str]:
    """Scan chunk content for glossary acronyms from ICT_SHORTFORMS.

    Returns acronyms in order they appear (not deduped — duplicates reflect
    multiple mentions). Matching is word-boundary case-insensitive, with
    special handling for case-insensitive shortforms like FVG, IFVG, BISI, SIBI.
    """
    if not content:
        return []

    low = content.lower()
    hits: list[str] = []

    for name, desc in vc.ICT_SHORTFORMS.items():
        # Determine if this term is case-insensitive
        if name in vc.CASE_INSENSITIVE_SHORTFORMS:
            # Full lower-case matching (the word boundary dots already handle case)
            pattern = r"(?<![a-z0-9])" + re.escape(name.lower()) + r"(?![a-z0-9])"
            if re.search(pattern, low):
                hits.append(name)
        else:
            # Uppercase-only matching (standard acronyms like MS, MSS, OB)
            pattern = r"(?<![A-Za-z0-9])" + re.escape(name) + r"(?![A-Za-z0-9])"
            if re.search(pattern, content):
                hits.append(name)

    return hits


def _extract_session_tags(title: str, start_ts: str) -> list[str]:
    """Extract explicit session/time tags from title text only.

    ``start_ts`` is elapsed video time, not wall-clock time, so it must never be
    interpreted as an AM/PM market-session signal.
    """
    _ = start_ts
    tags: list[str] = []

    # Title-based patterns
    for tag, pattern in _SESSION_TIME_PATTERNS:
        if pattern.search(title):
            if tag not in tags:
                tags.append(tag)

    return tags


def _any_match(text: str, patterns: list[re.Pattern]) -> bool:
    """Return True if any pattern matches in *text*."""
    return any(p.search(text) for p in patterns)


# ── Batch convenience ─────────────────────────────────────────────────────────


def enrich_batch(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Enrich every chunk in a list. Always returns same-length list."""
    return [enrich(c) for c in chunks]


# ── CLI smoke test ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Quick self-test
    sample = {
        "chunk_id": "test_001",
        "chunk_index": 0,
        "title": "Month 01 — ICT 2022 Mentorship — Example: Market Structure Shift",
        "video_id": "abc123",
        "playlist": "2022 ICT Mentorship",
        "start_ts": "0:05:30",
        "end_ts": "0:07:15",
        "source_file": "abc123_test.md",
        "content": (
            "Market Structure Shift (MSS) is defined as a change from bullish to "
            "bearish. For example, when price breaks a key structural level, that's "
            "an MSS. Be careful not to confuse this with a simple retracement. "
            "The leading rule here is to wait for confirmation. FVG plays a role too."
        ),
    }
    enriched = enrich(sample)
    for k, v in enriched.items():
        if k in ("chunk_id", "chunk_index", "video_id", "source_file", "end_ts"):
            continue
        print(f"  {k:20s} = {v}")

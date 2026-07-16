"""Timestamp-preserving transcript parsing and semantic chunk construction."""
from __future__ import annotations

from dataclasses import dataclass
import re

_TIMESTAMP_RE = re.compile(r"^(\d+:\d{2}(?::\d{2})?)\s+(.+?)\s*$")
_LINK_RE = re.compile(
    r"\s*\[[^\]]*\]\(https?://(?:www\.)?(?:youtu\.be|youtube\.com)/[^)]+\)\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TranscriptSegment:
    start_ts: str
    start_seconds: int
    text: str
    end_ts: str | None = None
    end_seconds: int | None = None
    ordinal: int = 0
    timing_precision: str = "unknown"


@dataclass(frozen=True)
class SemanticChunk:
    text: str
    video_id: str
    start_ts: str
    end_ts: str
    start_seconds: int
    end_seconds: int
    timing_precision: str

    @property
    def video_url(self) -> str:
        if not self.video_id:
            return ""
        if self.start_seconds <= 0:
            return f"https://youtu.be/{self.video_id}"
        return f"https://youtu.be/{self.video_id}?t={self.start_seconds}"


@dataclass(frozen=True)
class SemanticUnit:
    text: str
    start_ts: str
    end_ts: str
    start_seconds: int
    end_seconds: int


def timestamp_to_seconds(value: str) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"\d+:\d{2}(?::\d{2})?", value):
        raise ValueError(f"invalid timestamp: {value}")
    parts = [int(p) for p in value.split(":")]
    if parts[-1] >= 60:
        raise ValueError(f"invalid timestamp: {value}")
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        if parts[1] >= 60:
            raise ValueError(f"invalid timestamp: {value}")
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    raise ValueError(f"invalid timestamp: {value}")


def seconds_to_timestamp(seconds: int) -> str:
    if seconds < 0:
        raise ValueError("seconds cannot be negative")
    hours, remainder = divmod(int(seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _clean_caption(text: str) -> str:
    text = _LINK_RE.sub("", text)
    text = text.replace("▶️", "").replace("\\u25b6\\ufe0f", "")
    return re.sub(r"\s+", " ", text).strip()


def _caption_quality(text: str) -> tuple[int, int, str]:
    words = re.findall(r"[A-Za-z0-9']+", text)
    return len(set(w.lower() for w in words)), len(text), text


def parse_markdown_transcript(markdown: str) -> list[TranscriptSegment]:
    """Parse only detailed transcript rows, preserving exact source timing.

    Exact duplicate rows are removed. Distinct utterances sharing a timestamp
    survive in source order. Since legacy Markdown has no duration field, each
    row ends at the next distinct timestamp and records that precision honestly.
    """
    marker = re.search(r"(?mi)^##\s+Transcript\s*$", markdown or "")
    body = (markdown or "")[marker.end():] if marker else (markdown or "")
    raw_segments: list[TranscriptSegment] = []
    seen: set[tuple[int, str]] = set()

    for ordinal, raw in enumerate(body.splitlines()):
        match = _TIMESTAMP_RE.match(raw.strip())
        if not match:
            continue
        start_ts, caption = match.groups()
        caption = _clean_caption(caption)
        if not caption:
            continue
        try:
            seconds = timestamp_to_seconds(start_ts)
        except ValueError:
            continue
        dedup_key = (seconds, re.sub(r"\s+", " ", caption).strip().casefold())
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        raw_segments.append(TranscriptSegment(
            start_ts=start_ts,
            start_seconds=seconds,
            text=caption,
            ordinal=ordinal,
        ))

    ordered = sorted(raw_segments, key=lambda s: (s.start_seconds, s.ordinal))
    result: list[TranscriptSegment] = []
    for index, segment in enumerate(ordered):
        next_second = next(
            (s.start_seconds for s in ordered[index + 1:] if s.start_seconds > segment.start_seconds),
            segment.start_seconds,
        )
        precision = "next_segment_inferred" if next_second > segment.start_seconds else "unknown"
        result.append(TranscriptSegment(
            start_ts=segment.start_ts,
            start_seconds=segment.start_seconds,
            text=segment.text,
            end_ts=seconds_to_timestamp(next_second),
            end_seconds=next_second,
            ordinal=segment.ordinal,
            timing_precision=precision,
        ))
    return result


def _token_count(text: str) -> int:
    return len(re.findall(r"\S+", text))


def build_semantic_units(
    segments: list[TranscriptSegment], target_tokens: int = 80
) -> list[SemanticUnit]:
    """Group short captions into stable windows for adjacent similarity checks."""
    if target_tokens <= 0:
        raise ValueError("target_tokens must be positive")
    units: list[SemanticUnit] = []
    current: list[TranscriptSegment] = []
    current_tokens = 0
    for segment in sorted(segments, key=lambda s: s.start_seconds):
        current.append(segment)
        current_tokens += _token_count(segment.text)
        if current_tokens >= target_tokens:
            units.append(SemanticUnit(
                text=" ".join(s.text for s in current),
                start_ts=current[0].start_ts,
                end_ts=current[-1].end_ts or current[-1].start_ts,
                start_seconds=current[0].start_seconds,
                end_seconds=(current[-1].end_seconds
                             if current[-1].end_seconds is not None
                             else current[-1].start_seconds),
            ))
            current = []
            current_tokens = 0
    if current:
        units.append(SemanticUnit(
            text=" ".join(s.text for s in current),
            start_ts=current[0].start_ts,
            end_ts=current[-1].end_ts or current[-1].start_ts,
            start_seconds=current[0].start_seconds,
            end_seconds=(current[-1].end_seconds
                         if current[-1].end_seconds is not None
                         else current[-1].start_seconds),
        ))
    return units


def _cosine(a, b) -> float:
    if len(a) != len(b) or not a:
        raise ValueError("embeddings must have the same non-zero dimension")
    dot = sum(float(x) * float(y) for x, y in zip(a, b))
    na = sum(float(x) * float(x) for x in a) ** 0.5
    nb = sum(float(y) * float(y) for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def detect_semantic_breaks(
    units: list[SemanticUnit], embeddings, similarity_threshold: float = 0.55
) -> set[int]:
    """Return exact segment start-seconds where adjacent meaning changes sharply."""
    if len(units) != len(embeddings):
        raise ValueError("one embedding is required per semantic unit")
    breaks: set[int] = set()
    for index in range(1, len(units)):
        if _cosine(embeddings[index - 1], embeddings[index]) < similarity_threshold:
            breaks.add(units[index].start_seconds)
    return breaks


def _is_transition(text: str) -> bool:
    lower = text.lower().lstrip()
    return lower.startswith((
        "now let", "let me", "so now", "okay so", "alright", "all right",
        "moving on", "next thing", "i want to", "let's talk",
    ))


def chunk_segments(
    segments: list[TranscriptSegment],
    *,
    video_id: str,
    target_tokens: int = 240,
    hard_max_tokens: int = 350,
    min_split_tokens: int = 80,
    semantic_break_seconds: set[int] | None = None,
    overlap_units: int = 1,
) -> list[SemanticChunk]:
    """Group chronological transcript segments without guessing timestamps."""
    if target_tokens <= 0 or hard_max_tokens <= 0 or target_tokens > hard_max_tokens:
        raise ValueError("token limits must satisfy 0 < target <= hard max")
    if min_split_tokens < 0:
        raise ValueError("min_split_tokens cannot be negative")
    semantic_break_seconds = semantic_break_seconds or set()

    ordered = sorted(segments, key=lambda s: s.start_seconds)
    expanded: list[TranscriptSegment] = []
    for segment in ordered:
        words = segment.text.split()
        if len(words) <= hard_max_tokens:
            expanded.append(segment)
            continue
        for start in range(0, len(words), hard_max_tokens):
            expanded.append(TranscriptSegment(
                start_ts=segment.start_ts,
                start_seconds=segment.start_seconds,
                text=" ".join(words[start:start + hard_max_tokens]),
                end_ts=segment.end_ts,
                end_seconds=segment.end_seconds,
                ordinal=segment.ordinal,
                timing_precision=segment.timing_precision,
            ))

    chunks: list[SemanticChunk] = []
    current: list[TranscriptSegment] = []

    def emit(items: list[TranscriptSegment]) -> None:
        if not items:
            return
        chunks.append(SemanticChunk(
            text=" ".join(s.text for s in items).strip(),
            video_id=video_id,
            start_ts=items[0].start_ts,
            end_ts=items[-1].end_ts or items[-1].start_ts,
            start_seconds=items[0].start_seconds,
            end_seconds=(items[-1].end_seconds
                         if items[-1].end_seconds is not None
                         else items[-1].start_seconds),
            timing_precision=items[-1].timing_precision,
        ))

    for segment in expanded:
        current_tokens = sum(_token_count(s.text) for s in current)
        segment_tokens = _token_count(segment.text)
        semantic_split = (
            segment.start_seconds in semantic_break_seconds
            and current_tokens >= min_split_tokens
        )
        should_soft_split = current_tokens >= target_tokens and _is_transition(segment.text)
        should_hard_split = bool(current) and current_tokens + segment_tokens > hard_max_tokens
        if semantic_split or should_soft_split or should_hard_split:
            emit(current)
            overlap = current[-overlap_units:] if overlap_units > 0 else []
            current = list(overlap)
            while current and sum(_token_count(s.text) for s in current) + segment_tokens > hard_max_tokens:
                current.pop(0)
        current.append(segment)

    emit(current)
    return chunks

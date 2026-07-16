from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from semantic_chunking import (
    TranscriptSegment,
    build_semantic_units,
    chunk_segments,
    detect_semantic_breaks,
    parse_markdown_transcript,
    timestamp_to_seconds,
)


def test_parser_uses_transcript_section_and_preserves_distinct_same_time_captions():
    raw = """---
title: "Example"
video_id: "vid123"
---
## Key Moments
| Timestamp | Context | Jump |
| 0:00 | truncated summary | [▶️](https://youtu.be/vid123?t=0) |
| 5:00 | another summary | [▶️](https://youtu.be/vid123?t=300) |

## Transcript
0:10 short [▶️](https://youtu.be/vid123?t=10)
0:10 The complete detailed sentence. [▶️](https://youtu.be/vid123?t=10)
0:03 Earlier caption. [▶️](https://youtu.be/vid123?t=3)
0:10 The complete detailed sentence. [▶️](https://youtu.be/vid123?t=10)
"""

    segments = parse_markdown_transcript(raw)

    assert [(s.start_ts, s.text) for s in segments] == [
        ("0:03", "Earlier caption."),
        ("0:10", "short"),
        ("0:10", "The complete detailed sentence."),
    ]
    assert segments[0].end_seconds == 10
    assert segments[0].timing_precision == "next_segment_inferred"


def _seg(ts, seconds, text):
    return TranscriptSegment(start_ts=ts, start_seconds=seconds, text=text)


def test_chunks_carry_exact_monotonic_timestamps_and_clickable_deeplinks():
    segments = [
        _seg("0:03", 3, "A fair value gap starts here."),
        _seg("0:08", 8, "It is explained with another complete sentence."),
        _seg("0:15", 15, "Now let us discuss order blocks."),
        _seg("0:20", 20, "The order block explanation continues here."),
    ]

    chunks = chunk_segments(
        segments,
        video_id="abc123",
        target_tokens=10,
        hard_max_tokens=20,
        overlap_units=0,
    )

    assert chunks
    assert [c.start_seconds for c in chunks] == sorted(c.start_seconds for c in chunks)
    assert all(c.end_seconds >= c.start_seconds for c in chunks)
    assert chunks[0].start_ts == "0:03"
    assert chunks[0].video_url == "https://youtu.be/abc123?t=3"
    assert all(c.video_id == "abc123" for c in chunks)


def test_chunk_preserves_unknown_precision_from_final_source_segment():
    segments = [
        TranscriptSegment(
            start_ts="0:03", start_seconds=3, text="First caption.",
            end_ts="0:15", end_seconds=15,
            timing_precision="next_segment_inferred",
        ),
        TranscriptSegment(
            start_ts="0:15", start_seconds=15, text="Final caption.",
            end_ts="0:15", end_seconds=15, timing_precision="unknown",
        ),
    ]
    chunks = chunk_segments(
        segments, video_id="vid", target_tokens=100, hard_max_tokens=100,
        overlap_units=0,
    )
    assert chunks[0].end_seconds > chunks[0].start_seconds
    assert chunks[0].timing_precision == "unknown"


def test_hard_limit_splits_at_word_boundaries_without_losing_text():
    words = [f"word{i}" for i in range(25)]
    chunks = chunk_segments(
        [_seg("1:00", 60, " ".join(words))],
        video_id="vid",
        target_tokens=8,
        hard_max_tokens=10,
        overlap_units=0,
    )

    assert all(len(c.text.split()) <= 10 for c in chunks)
    assert " ".join(c.text for c in chunks).split() == words
    assert all(c.start_ts == "1:00" and c.end_ts == "1:00" for c in chunks)


def test_timestamp_parser_rejects_malformed_values():
    for bad in ("1:60", "-1:20", "abc", "", "1:-2", "1:02:60"):
        try:
            timestamp_to_seconds(bad)
            assert False, f"expected rejection: {bad}"
        except ValueError:
            pass
    assert timestamp_to_seconds("0:59") == 59
    assert timestamp_to_seconds("1:00") == 60
    assert timestamp_to_seconds("1:02:03") == 3723


def test_embedding_similarity_marks_real_topic_change_and_chunker_uses_it():
    segments = [
        _seg("0:00", 0, "Fair value gap definition and imbalance."),
        _seg("0:10", 10, "The same fair value gap explanation continues."),
        _seg("0:20", 20, "Risk management and stop loss placement."),
        _seg("0:30", 30, "The risk management explanation continues."),
    ]
    units = build_semantic_units(segments, target_tokens=5)
    # First two units are similar; unit three changes topic sharply.
    embeddings = [[1.0, 0.0], [0.95, 0.05], [0.0, 1.0], [0.05, 0.95]]

    breaks = detect_semantic_breaks(units, embeddings, similarity_threshold=0.50)
    chunks = chunk_segments(
        segments,
        video_id="vid",
        target_tokens=100,
        hard_max_tokens=100,
        min_split_tokens=5,
        semantic_break_seconds=breaks,
        overlap_units=0,
    )

    assert breaks == {20}
    assert len(chunks) == 2
    assert chunks[0].end_ts == "0:10"
    assert chunks[1].start_ts == "0:20"

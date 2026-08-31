"""Subtitle cue mapping: script onto ASR char/word timeline."""

from workflow.publish import (
    _allocate_span_counts,
    _char_spans_from_segments,
    _map_units_onto_char_spans,
    map_script_to_segment_timeline,
)


def test_allocate_span_counts_covers_all():
    counts = _allocate_span_counts([3, 5, 2], 20)
    assert sum(counts) == 20
    assert all(c >= 1 for c in counts)


def test_char_spans_prefer_words():
    segs = [
        {
            "start": 0.0,
            "end": 1.0,
            "text": "你好世界",
            "words": [
                {"word": "你好", "start": 0.0, "end": 0.4},
                {"word": "世界", "start": 0.5, "end": 1.0},
            ],
        }
    ]
    spans = _char_spans_from_segments(segs)
    assert len(spans) == 4
    assert spans[0][0] == 0.0
    assert spans[-1][1] == 1.0
    # Gap between words preserved in span boundaries
    assert spans[1][1] == 0.4
    assert spans[2][0] == 0.5


def test_map_units_follow_asr_pacing():
    # Slow first half, fast second half — char spans keep ASR pacing.
    segs = [
        {"start": 0.0, "end": 4.0, "text": "甲乙"},
        {"start": 4.0, "end": 5.0, "text": "丙丁"},
    ]
    spans = _char_spans_from_segments(segs)
    cues = _map_units_onto_char_spans(["甲乙", "丙丁"], spans)
    assert len(cues) == 2
    assert cues[0].end == 4.0
    assert cues[1].start == 4.0
    assert cues[1].end == 5.0


def test_map_script_uses_session_text():
    segs = [{"start": 0.0, "end": 2.0, "text": "错别字乱码"}]
    cues = map_script_to_segment_timeline("正确文案内容", segs, max_chars=20)
    assert len(cues) >= 1
    assert "正确" in cues[0].text
    assert "错别" not in cues[0].text


def test_map_units_onto_char_spans_order():
    spans = [(0.0, 0.5), (0.5, 1.0), (1.0, 1.5), (1.5, 2.0)]
    cues = _map_units_onto_char_spans(["一二", "三四"], spans)
    assert len(cues) == 2
    assert cues[0].start == 0.0
    assert cues[0].end == 1.0
    assert cues[1].start == 1.0
    assert cues[1].end == 2.0

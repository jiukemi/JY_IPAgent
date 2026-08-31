"""ASR subtitle extract helpers."""

from workflow.publish import asr_transcript_from_segments, cues_from_asr_segments


def test_cues_from_asr_keeps_recognized_text():
    segs = [
        {"start": 0.0, "end": 1.2, "text": "\u4eca\u5929\u6211\u4eec\u8bb2\u4e09\u4e2a\u8981\u70b9"},
        {"start": 1.3, "end": 2.5, "text": "\u7b2c\u4e00\u662f\u6548\u7387\u7b2c\u4e8c\u662f\u8d28\u91cf"},
    ]
    cues = cues_from_asr_segments(segs, max_chars=10)
    assert cues
    joined = "".join(c.text for c in cues)
    assert "\u4eca\u5929\u6211\u4eec" in joined
    assert cues[0].start == 0.0
    assert cues[-1].end >= 2.0


def test_cues_from_asr_word_timestamps():
    segs = [
        {
            "start": 0.0,
            "end": 2.0,
            "text": "\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341",
            "words": [
                {"word": "\u4e00\u4e8c\u4e09\u56db\u4e94", "start": 0.0, "end": 1.0},
                {"word": "\u516d\u4e03\u516b\u4e5d\u5341", "start": 1.0, "end": 2.0},
            ],
        }
    ]
    cues = cues_from_asr_segments(segs, max_chars=5)
    assert len(cues) >= 2
    assert cues[0].text == "\u4e00\u4e8c\u4e09\u56db\u4e94"
    assert cues[1].text == "\u516d\u4e03\u516b\u4e5d\u5341"


def test_asr_transcript_join():
    segs = [
        {"text": "\u4f60\u597d"},
        {"text": "\u4e16\u754c"},
        {"text": "\ufffd\u574f"},
    ]
    assert asr_transcript_from_segments(segs) == "\u4f60\u597d\u4e16\u754c"

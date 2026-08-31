"""Font-aware subtitle split / wrap for large on-screen text."""

from workflow.publish import (
    SubCue,
    max_chars_per_line,
    prepare_burn_cues,
    resolve_subtitle_split_chars,
    split_cue_for_display,
    subtitle_text_for_preview,
    wrap_cue_text,
)


def test_large_font_fewer_chars_per_line():
    small = max_chars_per_line(12, 1080, video_height=1920)
    large = max_chars_per_line(26, 1080, video_height=1920)
    assert large < small


def test_resolve_subtitle_split_chars_shrinks_with_font():
    small = resolve_subtitle_split_chars(12, 1080, 1920, config_max=18)
    large = resolve_subtitle_split_chars(26, 1080, 1920, config_max=18)
    assert large < small
    assert large >= 6


def test_split_cue_preserves_window():
    cue = SubCue(1, 1.0, 5.0, "这是一段很长的口播字幕需要按字号自动切分才能完整显示在屏幕上")
    parts = split_cue_for_display(cue, max_unit_chars=8)
    assert len(parts) >= 2
    assert parts[0].start == 1.0
    assert parts[-1].end == 5.0
    assert sum(len(p.text) for p in parts) >= len(cue.text) - 4


def test_prepare_burn_cues_splits_long_cue():
    cues = [
        SubCue(
            1,
            0.0,
            4.0,
            "超大字号时这句字幕明显过长需要拆成多条时间轴字幕才能完整显示不溢出屏幕",
        )
    ]
    out = prepare_burn_cues(
        cues,
        ui_font_size=26,
        video_width=1080,
        video_height=1920,
        max_lines=2,
    )
    assert len(out) >= 2
    per_line = max_chars_per_line(26, 1080, video_height=1920)
    for c in out:
        for line in c.text.split("\n"):
            assert len(line) <= per_line + 1


def test_wrap_cue_truncates_overflow_last_line():
    long = "甲" * 40
    wrapped = wrap_cue_text(long, max_chars=8, max_lines=2)
    lines = wrapped.split("\n")
    assert len(lines) <= 2
    assert lines[-1].endswith("…") or len(lines[-1]) <= 8


def test_subtitle_text_for_preview_picks_active_chunk():
    text = "甲" * 12 + "，" + "乙" * 24
    start, end = 0.0, 8.0
    first = subtitle_text_for_preview(
        text,
        start=start,
        end=end,
        time_sec=0.3,
        ui_font=26,
        width=1080,
        height=1920,
    )
    later = subtitle_text_for_preview(
        text,
        start=start,
        end=end,
        time_sec=7.5,
        ui_font=26,
        width=1080,
        height=1920,
    )
    assert first
    assert later

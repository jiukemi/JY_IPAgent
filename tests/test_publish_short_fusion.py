"""Unit tests for short / 口播混剪 publish fusion helpers."""

from workflow.pip_overlay import _pip_face_filter
from workflow.publish import _is_short_lipsync_mix, _short_side_ass_position


def test_is_short_lipsync_mix_default():
    assert _is_short_lipsync_mix("short", "none") is True
    assert _is_short_lipsync_mix("short", "timed") is True


def test_is_short_skips_education_branches():
    assert _is_short_lipsync_mix("short", "education") is False
    assert _is_short_lipsync_mix("short", "education_timed") is False
    assert _is_short_lipsync_mix("education", "none") is False


def test_short_side_ass_position():
    assert _short_side_ass_position("left") == "side_left"
    assert _short_side_ass_position("right") == "side_right"
    assert _short_side_ass_position("bogus") == "side_right"


def test_pip_face_filter_key_black():
    expr = _pip_face_filter("center", 0.55, key_black=True, key_white=False)
    assert "colorkey=0x000000" in expr
    assert "0xFFFFFF" not in expr

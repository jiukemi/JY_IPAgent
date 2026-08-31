"""HyperFrames scene text wrapping helpers."""

from workflow.hyperframes_scenes import _split_lines, _title_size_for_text


def test_split_lines_hard_wraps_long_cjk():
    text = "这是一句没有任何标点的特别特别特别特别特别长的文案内容会溢出"
    lines = _split_lines(text, 10, landscape=False)
    assert len(lines) >= 2
    assert all(len(x) <= 12 for x in lines)


def test_title_size_shrinks_for_long_text():
    short = _title_size_for_text("短句", False)
    long = _title_size_for_text("这是一句非常非常非常非常非常长的竖屏标题文案", False)
    assert "48px" in long or "62px" in long
    assert short != long or "78px" in short

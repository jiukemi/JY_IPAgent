from workflow.publish import build_subtitle_force_style


def test_side_right_alignment():
    s = build_subtitle_force_style(
        position="side_right", video_width=1080, video_height=1920, font_size=48
    )
    assert "Alignment=6" in s
    assert "MarginR=" in s


def test_side_left_alignment():
    s = build_subtitle_force_style(
        position="side_left", video_width=1080, video_height=1920, font_size=48
    )
    assert "Alignment=4" in s

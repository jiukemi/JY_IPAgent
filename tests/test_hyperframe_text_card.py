"""Smoke tests for the transparent text_card HyperFrames layout."""

from workflow import hyperframes_scenes as hs
from workflow.hyperframes_scenes import _title_size_for_text


def test_text_card_layout_registered():
    assert "text_card" in hs.SCENE_LAYOUTS


def test_text_card_meta():
    meta = hs.SCENE_LAYOUTS["text_card"]
    assert meta["label"]
    assert meta.get("css") is True


def test_text_card_builds_html():
    theme = {
        "top": (26, 27, 38),
        "bottom": (36, 40, 59),
        "text": (192, 202, 245),
        "accent_bar": (122, 162, 247),
        "outline": (187, 154, 247),
    }
    html = hs.build_scene_html("口播要点示例", "text_card", theme)
    assert "text-card" in html
    assert "background: #000000" in html
    assert "口播要点示例" in html


def test_text_card_title_bullets():
    theme = {
        "top": (26, 27, 38),
        "bottom": (36, 40, 59),
        "text": (192, 202, 245),
        "accent_bar": (122, 162, 247),
        "outline": (187, 154, 247),
    }
    html = hs.build_scene_html("剪辑要点\n• 时间线\n• 调色 — LUT", "text_card", theme)
    assert "剪辑要点" in html
    assert "<ul>" in html
    assert "时间线" in html
    assert "LUT" in html


def test_fusion_title_larger_than_scene():
    short = _title_size_for_text("HyperFrames", False, fusion=True)
    scene = _title_size_for_text("HyperFrames", False, fusion=False)
    assert "72px" in short or "118px" in short
    assert short != scene


def test_resolve_scene_aspect_from_video():
    assert hs.resolve_scene_aspect("portrait_9_16", video_width=1920, video_height=1080) == "landscape_16_9"
    assert hs.resolve_scene_aspect("landscape_16_9", video_width=1080, video_height=1920) == "portrait_9_16"


def test_font_scale_applied_in_fusion_html():
    theme = {
        "top": (26, 27, 38),
        "bottom": (36, 40, 59),
        "text": (192, 202, 245),
        "accent_bar": (122, 162, 247),
        "outline": (187, 154, 247),
    }
    base = hs.build_scene_html("测试字号", "glass_card", theme, aspect="landscape_16_9", font_scale=1.0)
    large = hs.build_scene_html("测试字号", "glass_card", theme, aspect="landscape_16_9", font_scale=1.6)
    assert large != base
    assert "115px" in large or "12.48vw" in large


def test_text_card_centered_layout():
    theme = {
        "top": (26, 27, 38),
        "bottom": (36, 40, 59),
        "text": (192, 202, 245),
        "accent_bar": (122, 162, 247),
        "outline": (187, 154, 247),
    }
    html = hs.build_scene_html(
        "HyperFrames 画中画",
        "text_card",
        theme,
        aspect="landscape_16_9",
    )
    assert "text-align: center" in html
    assert "justify-content: center" in html
    assert "fusion=True" not in html
    theme = {
        "top": (26, 27, 38),
        "bottom": (36, 40, 59),
        "text": (192, 202, 245),
        "accent_bar": (122, 162, 247),
        "outline": (187, 154, 247),
    }
    assert "glass_card" in hs.SCENE_LAYOUTS
    assert "plain_text" in hs.SCENE_LAYOUTS
    assert hs.is_fusion_layout("glass_card")
    assert hs.is_fusion_layout("plain_text")
    glass = hs.build_scene_html("玻璃标题", "glass_card", theme)
    assert "text-card" in glass
    plain = hs.build_scene_html("纯文字标题\n• 要点一", "plain_text", theme)
    assert "plain-text" in plain
    assert "backdrop-filter" not in plain
    assert "纯文字标题" in plain

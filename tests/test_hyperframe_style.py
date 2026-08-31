"""Tests for persisted HyperFrames / Scene Style Pack."""

from pathlib import Path

import pytest

from workflow import hyperframe_style as hs


@pytest.fixture()
def style_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "assets"
    path = root / "active_hyperframe_style.json"
    monkeypatch.setattr(hs, "ASSET_ROOT", root)
    monkeypatch.setattr(hs, "STYLE_PATH", path)
    return root, path


def test_default_when_missing(style_paths):
    out = hs.get_active_style()
    assert out["theme"] == "tokyo_night"
    assert out["layout"] == "kinetic"
    assert out["aspect"] == "portrait_9_16"
    assert out["font_id"] == "noto_sc"
    assert out["bg_mode"] == "generative"
    assert out["remotion_theme"] == "off"
    assert out["updated_at"] == 0


def test_round_trip(style_paths):
    saved = hs.set_active_style(
        "dracula",
        "Title_Card",
        "landscape-16-9",
        font_id="display",
        bg_mode="texture",
        bg_prompt="暖色课堂",
        remotion_theme="kinetic",
    )
    assert saved["theme"] == "dracula"
    assert saved["layout"] == "title_card"
    assert saved["aspect"] == "landscape_16_9"
    assert saved["font_id"] == "display"
    assert saved["bg_mode"] == "texture"
    assert saved["bg_prompt"] == "暖色课堂"
    assert saved["remotion_theme"] == "kinetic"
    assert saved["updated_at"] > 0
    loaded = hs.get_active_style()
    assert loaded["font_id"] == "display"
    assert loaded["remotion_theme"] == "kinetic"


def test_reject_empty(style_paths):
    with pytest.raises(ValueError):
        hs.set_active_style("", "kinetic", "portrait_9_16")
    with pytest.raises(ValueError):
        hs.set_active_style("tokyo_night", "  ", "portrait_9_16")


def test_corrupt_file_falls_back(style_paths):
    _, path = style_paths
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    out = hs.get_active_style()
    assert out["theme"] == "tokyo_night"


def test_ai_still_maps_to_generative(style_paths):
    saved = hs.set_active_style(
        "tokyo_night",
        "kinetic",
        "portrait_9_16",
        bg_mode="ai_still",
    )
    assert saved["bg_mode"] == "generative"

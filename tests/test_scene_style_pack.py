"""Scene Style Pack catalogs + generative background."""

from pathlib import Path

from workflow.scene_style_pack import (
    generate_background_png,
    list_style_pack_options,
    normalize_style_pack,
)


def test_normalize_defaults():
    p = normalize_style_pack({})
    assert p["font_id"] == "noto_sc"
    assert p["bg_mode"] == "generative"
    assert p["remotion_theme"] == "off"


def test_list_options_has_pack_fields():
    opts = list_style_pack_options()
    assert opts["fonts"]
    assert opts["bg_modes"]
    assert opts["remotion_themes"]
    ids = {x["id"] for x in opts["layouts"]}
    assert "editorial" in ids
    assert "spotlight" in ids


def test_prompt_grid_style(tmp_path: Path):
    from workflow.scene_style_pack import _prompt_style, generate_background_png

    assert _prompt_style("科技网格") == "grid"
    assert _prompt_style("冷色粒子") == "particle"
    theme = {
        "top": (26, 27, 38),
        "bottom": (36, 40, 59),
        "accent_bar": (122, 162, 247),
        "outline": (187, 154, 247),
        "id": "tokyo_night",
    }
    out = tmp_path / "grid.png"
    generate_background_png(
        out,
        theme=theme,
        width=320,
        height=560,
        mode="generative",
        prompt="科技网格",
    )
    assert out.is_file()
    assert out.stat().st_size > 800


def test_font_scale_clamped():
    p = normalize_style_pack({"font_scale": 3})
    assert p["font_scale"] == 2.0
    p2 = normalize_style_pack({"font_scale": 0.2})
    assert p2["font_scale"] == 0.7

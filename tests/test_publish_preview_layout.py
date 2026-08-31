"""Layout helpers for publish preview (content PiP slot geometry)."""

from pathlib import Path

import pytest
from PIL import Image

from workflow.publish import (
    _augment_hyperframe_cue_assignments,
    _content_slot_rect,
    _pip_slot_rect,
    composite_content_and_lecturer_preview_pil,
    SubCue,
)


def test_pip_slot_rect_bottom_right():
    x, y, w, h = _pip_slot_rect(1920, 1080, "bottom_right", 0.2, 24)
    assert w == 384
    assert x == 1920 - w - 24
    assert y == 1080 - h - 24


def test_content_slot_rect_keeps_source_aspect():
    # 16:9 source into 9:16 canvas at 32% width
    x, y, w, h = _content_slot_rect(
        1080, 1920, "bottom_left", 0.32, 24, src_w=1280, src_h=720
    )
    assert w == pytest.approx(1080 * 0.32, abs=2)
    assert h == pytest.approx(w * 720 / 1280, abs=2)
    assert x == 24
    assert y == 1920 - h - 24


def test_content_slot_fullscreen_is_canvas():
    x, y, w, h = _content_slot_rect(
        1080, 1920, "fullscreen", 1.0, 24, src_w=800, src_h=600
    )
    assert (x, y, w, h) == (0, 0, 1080, 1920)


def test_composite_places_content_before_lecturer(tmp_path: Path):
    w, h = 400, 700
    bg = tmp_path / "bg.png"
    content = tmp_path / "content.png"
    lecturer = tmp_path / "lec.png"
    out = tmp_path / "out.jpg"
    Image.new("RGB", (w, h), (20, 24, 32)).save(bg)
    Image.new("RGB", (320, 180), (0, 200, 0)).save(content)  # green 16:9
    Image.new("RGB", (200, 280), (255, 255, 255)).save(lecturer)

    composite_content_and_lecturer_preview_pil(
        bg,
        out,
        width=w,
        height=h,
        content_path=content,
        content_position="top_left",
        content_scale=0.4,
        content_margin=10,
        lecturer_path=lecturer,
        has_lecturer_video=True,
        pip_position="bottom_right",
        pip_scale=0.25,
        pip_margin=10,
    )
    assert out.is_file()
    img = Image.open(out).convert("RGB")
    # content top-left should be green-ish
    px = img.getpixel((20, 20))
    assert px[1] > px[0] and px[1] > px[2]


def test_augment_respects_target_indices(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cues = [
        SubCue(1, 0.0, 1.0, "一"),
        SubCue(2, 1.0, 2.0, "二"),
        SubCue(3, 2.0, 3.0, "三"),
    ]

    def fake_generate(cues_in, work_dir, **kwargs):
        target = kwargs.get("target_indices")
        out = []
        for c in cues_in:
            if target is not None and c.index not in target:
                continue
            if c.index in (kwargs.get("skip_indices") or set()):
                continue
            p = Path(work_dir) / f"hf_{c.index}.png"
            p.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (64, 64), (10, 10, 10)).save(p)
            out.append(
                {
                    "cue_indices": [c.index],
                    "start": c.start,
                    "end": c.end,
                    "media_path": str(p),
                    "auto_hyperframe": True,
                }
            )
        return out

    monkeypatch.setattr(
        "workflow.hyperframes.generate_cue_scene_assets",
        fake_generate,
    )
    merged = _augment_hyperframe_cue_assignments(
        [],
        cues,
        tmp_path / "hf",
        theme="tokyo_night",
        target_indices={2},
    )
    assert len(merged) == 1
    assert merged[0]["cue_indices"] == [2]
    assert merged[0].get("position") == "fullscreen"
    assert merged[0].get("scale") == 1

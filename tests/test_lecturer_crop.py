"""Tests for lecturer auto crop (正方向区域)."""

from PIL import Image, ImageDraw

from workflow.lecturer_crop import (
    NormCrop,
    detect_lecturer_norm_crop,
    apply_norm_crop_image,
    nudge_norm_crop,
)


def test_detect_square_box_on_white_studio():
    # Landscape-ish source with tall person silhouette on white
    im = Image.new("RGB", (1280, 720), (255, 255, 255))
    draw = ImageDraw.Draw(im)
    # Person blob near center
    draw.ellipse((560, 80, 720, 260), fill=(40, 40, 50))  # head
    draw.rectangle((580, 240, 700, 620), fill=(50, 50, 60))  # body
    crop = detect_lecturer_norm_crop(im)
    x, y, w, h = crop.pixel_box(1280, 720)
    assert abs(w - h) <= 2  # square pixels even on 16:9 source
    assert 0.12 < (w / 1280) < 0.7
    cut = apply_norm_crop_image(im, crop)
    assert abs(cut.size[0] - cut.size[1]) <= 2


def test_norm_crop_ffmpeg_even():
    c = NormCrop(0.1, 0.1, 0.3, 0.5)
    x, y, w, h = c.pixel_box(1920, 1080)
    assert w % 2 == 0 and h % 2 == 0 and x % 2 == 0 and y % 2 == 0
    assert "crop=" in c.ffmpeg_crop(1920, 1080)


def test_nudge_zoom_in():
    base = NormCrop(0.2, 0.1, 0.4, 0.6)
    z = nudge_norm_crop(base, zoom=1.2)
    assert z.w < base.w and z.h < base.h

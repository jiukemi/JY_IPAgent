# tests/test_face_caption_side.py
from pathlib import Path
from PIL import Image

from workflow.face_caption_side import decide_caption_side_from_image, CAPTION_SIDE_RIGHT


def test_blob_on_left_puts_caption_on_right(tmp_path: Path):
    im = Image.new("RGB", (200, 200), (255, 255, 255))
    for x in range(10, 60):
        for y in range(40, 160):
            im.putpixel((x, y), (20, 20, 20))
    assert decide_caption_side_from_image(im) == "right"


def test_blob_on_right_puts_caption_on_left():
    im = Image.new("RGB", (200, 200), (255, 255, 255))
    for x in range(140, 190):
        for y in range(40, 160):
            im.putpixel((x, y), (20, 20, 20))
    assert decide_caption_side_from_image(im) == "left"


def test_empty_frame_defaults_right():
    im = Image.new("RGB", (100, 100), (250, 250, 250))
    assert decide_caption_side_from_image(im) == CAPTION_SIDE_RIGHT

"""Decide which side of the frame is free for captions (short / 口播混剪)."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Literal

from PIL import Image

log = logging.getLogger(__name__)

CaptionSide = Literal["left", "right"]
CAPTION_SIDE_RIGHT: CaptionSide = "right"
CAPTION_SIDE_LEFT: CaptionSide = "left"


def decide_caption_side_from_image(im: Image.Image) -> CaptionSide:
    """Return the empty side for text. Face/content on left → caption right."""
    rgb = im.convert("RGB")
    w, h = rgb.size
    if w < 8 or h < 8:
        return CAPTION_SIDE_RIGHT

    cx = _face_center_x_opencv(rgb)
    if cx is None:
        cx = _content_center_x(rgb)
    if cx is None:
        return CAPTION_SIDE_RIGHT
    return CAPTION_SIDE_RIGHT if cx < (w * 0.5) else CAPTION_SIDE_LEFT


def _content_center_x(rgb: Image.Image) -> float | None:
    """Non-near-white mass centroid (white-studio aware)."""
    w, h = rgb.size
    thr = 242
    sx = n = 0
    step = max(1, min(w, h) // 120)
    px = rgb.load()
    for y in range(0, h, step):
        for x in range(0, w, step):
            r, g, b = px[x, y]
            if r < thr or g < thr or b < thr:
                sx += x
                n += 1
    if n < 8:
        return None
    return sx / n


def _face_center_x_opencv(rgb: Image.Image) -> float | None:
    try:
        import cv2  # type: ignore
        import numpy as np
    except Exception:
        return None
    arr = np.array(rgb)[:, :, ::-1]
    gray = cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)
    cascade_path = getattr(cv2.data, "haarcascades", "") + "haarcascade_frontalface_default.xml"
    cascade = cv2.CascadeClassifier(cascade_path)
    if cascade.empty():
        return None
    faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(40, 40))
    if faces is None or len(faces) == 0:
        return None
    x, _y, fw, fh = max(faces, key=lambda f: f[2] * f[3])
    return float(x + fw / 2)


def probe_caption_side_from_video(
    ffmpeg_bin: str,
    video_path: Path,
    *,
    at_sec: float | None = None,
    work_dir: Path | None = None,
) -> CaptionSide:
    """Extract one mid-frame and decide caption side. Never raises."""
    try:
        from workflow.publish import media_duration
        from pipeline import ffprobe_bin

        video_path = Path(video_path)
        probe = ffprobe_bin(ffmpeg_bin)
        dur = float(media_duration(probe, video_path) or 1.0)
        t = float(at_sec) if at_sec is not None else max(0.05, dur * 0.45)
        t = min(t, max(0.0, dur - 0.05))
        out_dir = Path(work_dir) if work_dir else video_path.parent
        out_dir.mkdir(parents=True, exist_ok=True)
        frame = out_dir / "caption_side_probe.jpg"
        subprocess.run(
            [
                ffmpeg_bin, "-y", "-ss", f"{t:.3f}", "-i", str(video_path),
                "-frames:v", "1", "-q:v", "3", str(frame),
            ],
            check=True,
            capture_output=True,
        )
        with Image.open(frame) as im:
            return decide_caption_side_from_image(im)
    except Exception:
        log.exception("caption side probe failed; default right")
        return CAPTION_SIDE_RIGHT

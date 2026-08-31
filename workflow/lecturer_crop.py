"""Auto / normalized crop for lecturer (口播) region in education PiP."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image


@dataclass(frozen=True)
class NormCrop:
    """Normalized crop in source frame coords (0..1)."""

    x: float
    y: float
    w: float
    h: float

    def clamp(self) -> "NormCrop":
        w = max(0.08, min(1.0, float(self.w)))
        h = max(0.08, min(1.0, float(self.h)))
        x = max(0.0, min(1.0 - w, float(self.x)))
        y = max(0.0, min(1.0 - h, float(self.y)))
        return NormCrop(x=x, y=y, w=w, h=h)

    def to_dict(self) -> dict[str, float]:
        c = self.clamp()
        return {
            "x": round(c.x, 4),
            "y": round(c.y, 4),
            "w": round(c.w, 4),
            "h": round(c.h, 4),
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "NormCrop | None":
        if not data or not isinstance(data, dict):
            return None
        try:
            return cls(
                x=float(data["x"]),
                y=float(data["y"]),
                w=float(data["w"]),
                h=float(data["h"]),
            ).clamp()
        except (KeyError, TypeError, ValueError):
            return None

    def pixel_box(self, src_w: int, src_h: int) -> tuple[int, int, int, int]:
        """Return even x,y,w,h suitable for ffmpeg yuv420 crop."""
        c = self.clamp()
        x = int(round(c.x * src_w))
        y = int(round(c.y * src_h))
        w = int(round(c.w * src_w))
        h = int(round(c.h * src_h))
        w = max(2, w - (w % 2))
        h = max(2, h - (h % 2))
        x = max(0, min(src_w - w, x - (x % 2)))
        y = max(0, min(src_h - h, y - (y % 2)))
        return x, y, w, h

    def ffmpeg_crop(self, src_w: int, src_h: int) -> str:
        x, y, w, h = self.pixel_box(src_w, src_h)
        return f"crop={w}:{h}:{x}:{y}"


def _content_mask_bbox(
    im: "Image.Image",
    *,
    white_threshold: int = 242,
) -> tuple[int, int, int, int] | None:
    """Bounding box of non-near-white pixels. Returns left, top, right, bottom."""
    from PIL import Image

    rgb = im.convert("RGB")
    w, h = rgb.size
    px = rgb.load()
    min_x, min_y = w, h
    max_x, max_y = -1, -1
    # Sample for speed on large frames
    step = 2 if max(w, h) > 900 else 1
    for y in range(0, h, step):
        for x in range(0, w, step):
            r, g, b = px[x, y]
            if r < white_threshold or g < white_threshold or b < white_threshold:
                if x < min_x:
                    min_x = x
                if y < min_y:
                    min_y = y
                if x > max_x:
                    max_x = x
                if y > max_y:
                    max_y = y
    if max_x < min_x or max_y < min_y:
        return None
    # Expand for skipped samples
    min_x = max(0, min_x - step)
    min_y = max(0, min_y - step)
    max_x = min(w - 1, max_x + step)
    max_y = min(h - 1, max_y + step)
    return min_x, min_y, max_x + 1, max_y + 1


def _fit_aspect_box(
    left: int,
    top: int,
    right: int,
    bottom: int,
    src_w: int,
    src_h: int,
    *,
    aspect_h_over_w: float = 1.0,
    pad: float = 0.08,
) -> tuple[int, int, int, int]:
    """Grow content bbox to target aspect (default 1:1 square), center on subject."""
    aspect = max(0.5, float(aspect_h_over_w))
    cw = max(1, right - left)
    ch = max(1, bottom - top)
    pad_x = int(round(cw * pad))
    pad_y = int(round(ch * pad))
    left = max(0, left - pad_x)
    top = max(0, top - pad_y)
    right = min(src_w, right + pad_x)
    bottom = min(src_h, bottom + pad_y)
    cw = max(1, right - left)
    ch = max(1, bottom - top)
    cx = left + cw / 2
    cy = top + ch / 2

    target_w = max(cw, int(round(ch / aspect)))
    target_h = int(round(target_w * aspect))
    if target_h < ch:
        target_h = ch
        target_w = max(1, int(round(target_h / aspect)))

    max_w = src_w - (src_w % 2)
    max_h = src_h - (src_h % 2)
    if target_w > max_w or target_h > max_h:
        scale = min(max_w / max(1, target_w), max_h / max(1, target_h))
        target_w = max(2, int(round(target_w * scale)))
        target_h = max(2, int(round(target_h * scale)))
    target_w -= target_w % 2
    target_h -= target_h % 2
    if abs(aspect - 1.0) < 1e-6:
        side = min(target_w, target_h, max_w, max_h)
        side -= side % 2
        target_w = target_h = max(2, side)

    x = int(round(cx - target_w / 2))
    y = int(round(cy - target_h / 2))
    y = max(0, y - int(round(target_h * 0.05)))
    x = max(0, min(src_w - target_w, x))
    y = max(0, min(src_h - target_h, y))
    x -= x % 2
    y -= y % 2
    return x, y, max(2, target_w), max(2, target_h)


def detect_lecturer_norm_crop(
    im: "Image.Image",
    *,
    aspect_h_over_w: float = 1.0,
    white_threshold: int = 242,
) -> NormCrop:
    """Detect upright lecturer region from one frame (white-studio aware)."""
    rgb = im.convert("RGB")
    src_w, src_h = rgb.size
    bbox = _content_mask_bbox(rgb, white_threshold=white_threshold)
    if bbox is None:
        target_w = int(round(min(src_w, src_h / aspect_h_over_w)))
        target_h = int(round(target_w * aspect_h_over_w))
        target_w -= target_w % 2
        target_h -= target_h % 2
        x = max(0, (src_w - target_w) // 2)
        y = max(0, int((src_h - target_h) * 0.12))
        x -= x % 2
        y -= y % 2
        return NormCrop(
            x=x / src_w,
            y=y / src_h,
            w=target_w / src_w,
            h=target_h / src_h,
        ).clamp()

    x, y, w, h = _fit_aspect_box(
        *bbox,
        src_w,
        src_h,
        aspect_h_over_w=aspect_h_over_w,
    )
    return NormCrop(
        x=x / src_w,
        y=y / src_h,
        w=w / src_w,
        h=h / src_h,
    ).clamp()


def apply_norm_crop_image(im: "Image.Image", crop: NormCrop) -> "Image.Image":
    w, h = im.size
    x, y, cw, ch = crop.pixel_box(w, h)
    return im.crop((x, y, x + cw, y + ch))


def nudge_norm_crop(
    crop: NormCrop,
    *,
    dx: float = 0.0,
    dy: float = 0.0,
    zoom: float = 1.0,
) -> NormCrop:
    """Fine-tune: dx/dy shift center, zoom>1 zooms in (smaller window)."""
    c = crop.clamp()
    zoom = max(0.7, min(1.4, float(zoom)))
    nw = max(0.08, min(1.0, c.w / zoom))
    nh = max(0.08, min(1.0, c.h / zoom))
    cx = c.x + c.w / 2 + float(dx)
    cy = c.y + c.h / 2 + float(dy)
    return NormCrop(x=cx - nw / 2, y=cy - nh / 2, w=nw, h=nh).clamp()

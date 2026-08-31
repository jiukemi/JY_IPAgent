"""Portrait cutout for cover templates (rembg), with disk cache."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "data" / "cover_subject_cache"
log = logging.getLogger("cover.subject")

_SESSION = None


def _hex_rgb(s: str) -> tuple[int, int, int]:
    s = (s or "").strip()
    if len(s) == 7 and s.startswith("#"):
        try:
            return (int(s[1:3], 16), int(s[3:5], 16), int(s[5:7], 16))
        except ValueError:
            pass
    return (255, 255, 255)


def _cache_key(image: Image.Image, tag: str) -> str:
    # Hash pixels + size (avoid huge tobytes on every call when stem given)
    raw = image.resize((64, 64), Image.BILINEAR).tobytes()
    h = hashlib.sha1(raw + tag.encode("utf-8")).hexdigest()[:20]
    return h


def _get_session():
    global _SESSION
    if _SESSION is not None:
        return _SESSION
    from rembg import new_session

    # u2netp ≈ 4MB；首装友好
    _SESSION = new_session("u2netp")
    return _SESSION


def _transparent_ratio(rgba: Image.Image) -> float:
    alpha = rgba.split()[-1]
    # Count pixels that are meaningfully transparent
    hist = alpha.histogram()
    soft = sum(hist[:240])
    total = max(1, rgba.width * rgba.height)
    return soft / total


def _bbox_crop(rgba: Image.Image, pad_ratio: float = 0.04) -> Image.Image:
    """Crop to non-transparent bounding box with padding."""
    alpha = rgba.split()[-1]
    bbox = alpha.getbbox()
    if not bbox:
        return rgba
    l, t, r, b = bbox
    w, h = rgba.size
    pad = int(max(w, h) * pad_ratio)
    l = max(0, l - pad)
    t = max(0, t - pad)
    r = min(w, r + pad)
    b = min(h, b + pad)
    return rgba.crop((l, t, r, b))


def cutout_rgba(base_rgba: Image.Image, *, cache_stem: str | None = None) -> Image.Image:
    """Return RGBA with background removed. Same size as input. Raises RuntimeError on failure."""
    from io import BytesIO

    if base_rgba.mode != "RGBA":
        base_rgba = base_rgba.convert("RGBA")

    key = cache_stem or _cache_key(base_rgba, f"{base_rgba.size[0]}x{base_rgba.size[1]}-u2netp-v2")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"{key}.png"
    if cache_path.is_file() and cache_path.stat().st_size > 64:
        try:
            cached = Image.open(cache_path).convert("RGBA")
            if cached.size == base_rgba.size and _transparent_ratio(cached) >= 0.05:
                return cached
        except Exception:
            pass

    try:
        from rembg import remove
    except ImportError as exc:
        raise RuntimeError('未安装 rembg。请执行: py -3.11 -m pip install "rembg[cpu]"') from exc

    try:
        session = _get_session()
        buf = BytesIO()
        base_rgba.save(buf, format="PNG")
        out_bytes = remove(buf.getvalue(), session=session)
        out = Image.open(BytesIO(out_bytes)).convert("RGBA")
        if out.size != base_rgba.size:
            out = out.resize(base_rgba.size, Image.LANCZOS)
        ratio = _transparent_ratio(out)
        if ratio < 0.05:
            raise RuntimeError("抠像未检测到清晰人像，请换正脸/半身帧后重试")
        out.save(cache_path, format="PNG")
        return out
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"抠像失败: {exc}") from exc


def _expand_alpha(alpha: Image.Image, width: int) -> Image.Image:
    from PIL import ImageFilter

    if width <= 0:
        return alpha
    m = alpha
    steps = max(1, min(28, int(width)))
    for _ in range(steps):
        m = m.filter(ImageFilter.MaxFilter(3))
    return m


def compose_subject_scene(base_rgba: Image.Image, subject_cfg: dict[str, Any]):
    """Blur background + cutout subject (shrunk sticker) with outline.

    Reference 图2: person ≈ half canvas height, left-biased, strong gaussian blur.
    """
    from PIL import ImageChops, ImageDraw, ImageFilter

    cfg = subject_cfg or {}
    if not cfg.get("enabled"):
        return base_rgba, None

    w, h = base_rgba.size
    cut = cutout_rgba(base_rgba)

    bg_mode = str(cfg.get("bg_mode") or "blur").lower()
    canvas = base_rgba.copy()
    if bg_mode == "blur":
        radius = int(cfg.get("blur_radius", 56))
        radius = max(24, min(100, radius))
        canvas = canvas.filter(ImageFilter.GaussianBlur(radius=radius))
        canvas = canvas.filter(ImageFilter.GaussianBlur(radius=max(12, radius // 2)))
        canvas = canvas.filter(ImageFilter.GaussianBlur(radius=8))
    elif bg_mode == "white":
        canvas = Image.new("RGBA", (w, h), (255, 255, 255, 255))
    elif bg_mode == "black":
        canvas = Image.new("RGBA", (w, h), (12, 12, 14, 255))

    subject = _bbox_crop(cut, pad_ratio=0.04)
    # 图2：人像整体缩小，约占画布高度 45%~55%
    base_fill = float(cfg.get("fill_ratio", 0.5))
    scale = float(cfg.get("scale", 1.0))
    fill_ratio = max(0.28, min(0.85, base_fill * max(0.5, min(1.4, scale))))
    target_h = max(32, int(h * fill_ratio))
    aspect = subject.width / max(subject.height, 1)
    target_w = max(32, int(target_h * aspect))
    if target_w > int(w * 0.72):
        target_w = int(w * 0.72)
        target_h = max(32, int(target_w / max(aspect, 0.01)))
    subject = subject.resize((target_w, target_h), Image.LANCZOS)

    x_off = max(-0.25, min(0.25, float(cfg.get("x_offset", -0.06))))
    y_off = max(-0.15, min(0.2, float(cfg.get("y_offset", 0.08))))
    paste_x = (w - target_w) // 2 + int(w * x_off)
    paste_y = (h - target_h) // 2 + int(h * y_off)
    paste_x = max(0, min(w - target_w, paste_x))
    paste_y = max(0, min(h - target_h, paste_y))

    outline = str(cfg.get("outline") or "none").lower()
    outline_color = str(cfg.get("outline_color") or "#FFFFFF")
    outline_width = max(0, int(cfg.get("outline_width", 10)))
    # 描边宽度相对人像高度，避免缩放过细/过粗
    outline_px = max(outline_width, int(target_h * 0.012)) if outline_width else 0
    glow_color = str(cfg.get("glow_color") or outline_color)

    decorated = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    alpha = subject.split()[-1]

    if outline in ("solid", "glow", "dashed") and outline_px > 0:
        expanded = _expand_alpha(alpha, outline_px)
        rgb = _hex_rgb(glow_color if outline == "glow" else outline_color)
        band = ImageChops.subtract(expanded, alpha)

        if outline == "glow":
            ring = Image.new("RGBA", subject.size, (*rgb, 0))
            ring.putalpha(expanded)
            ring = ring.filter(ImageFilter.GaussianBlur(radius=max(3, outline_px // 2)))
            decorated.paste(ring, (paste_x, paste_y), ring)
            soft = ring.filter(ImageFilter.GaussianBlur(radius=max(6, outline_px)))
            decorated.paste(soft, (paste_x, paste_y), soft)
        elif outline == "dashed":
            period = max(14, outline_px * 3)
            gap = max(5, outline_px)
            stripe = Image.new("L", subject.size, 0)
            sdraw = ImageDraw.Draw(stripe)
            for y in range(0, subject.size[1], period):
                sdraw.rectangle(
                    [0, y, subject.size[0], min(y + period - gap, subject.size[1])],
                    fill=255,
                )
            dashed = ImageChops.multiply(band, stripe)
            ring = Image.new("RGBA", subject.size, (*rgb, 0))
            ring.putalpha(dashed)
            decorated.paste(ring, (paste_x, paste_y), ring)
        else:
            ring = Image.new("RGBA", subject.size, (*rgb, 0))
            ring.putalpha(band)
            decorated.paste(ring, (paste_x, paste_y), ring)

    decorated.paste(subject, (paste_x, paste_y), subject)
    return canvas, decorated


def prepare_subject_preview_assets(
    base_rgba: Image.Image,
    subject_cfg: dict[str, Any],
    out_dir: Path,
) -> dict[str, Any]:
    """Build interactive preview assets: blurred/solid bg + centered cutout sticker.

    Frontend places the sticker with x_offset/y_offset so drag is instant;
    rembg still runs only when this is called (cutout disk-cached).
    """
    cfg = dict(subject_cfg or {})
    cfg["enabled"] = True
    # Center sticker; client applies offsets
    cfg["x_offset"] = 0.0
    cfg["y_offset"] = 0.0

    bg, layer = compose_subject_scene(base_rgba, cfg)
    if layer is None:
        raise RuntimeError("人像抠图未启用")

    out_dir.mkdir(parents=True, exist_ok=True)
    bg_path = out_dir / "cover_cutout_bg.jpg"
    sticker_path = out_dir / "cover_cutout_sticker.png"
    bg.convert("RGB").save(bg_path, quality=90)

    alpha = layer.split()[-1]
    bbox = alpha.getbbox()
    if not bbox:
        raise RuntimeError("抠像结果为空，请换一帧重试")
    sticker = layer.crop(bbox)
    sticker.save(sticker_path, format="PNG")

    w, h = bg.size
    base_fill = float(cfg.get("fill_ratio", 0.5))
    scale = float(cfg.get("scale", 1.0))
    fill_ratio = max(0.28, min(0.85, base_fill * max(0.5, min(1.4, scale))))

    return {
        "bg_path": str(bg_path.resolve()),
        "sticker_path": str(sticker_path.resolve()),
        "sticker_w_ratio": sticker.width / max(w, 1),
        "sticker_h_ratio": sticker.height / max(h, 1),
        "fill_ratio": fill_ratio,
        "canvas_w": w,
        "canvas_h": h,
    }

"""PIL renderer for cover templates — text effects + background overlay."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from cover.templates import get_template, normalize_template

_HEX_RE = re.compile(r"^#([0-9A-Fa-f]{2})([0-9A-Fa-f]{2})([0-9A-Fa-f]{2})$")


def _hex_rgb(s: str) -> tuple[int, int, int]:
    m = _HEX_RE.match(s or "")
    if not m:
        return (255, 255, 255)
    return (int(m.group(1), 16), int(m.group(2), 16), int(m.group(3), 16))


def _load_font(size: int, bold: bool = False):
    from PIL import ImageFont

    candidates = ["msyhbd.ttc", "simhei.ttf", "msyh.ttc"] if bold else ["msyh.ttc", "simhei.ttf"]
    for name in candidates:
        win = Path("C:/Windows/Fonts") / name
        if win.exists():
            try:
                return ImageFont.truetype(str(win), max(8, size))
            except Exception:
                continue
    return ImageFont.load_default()


def _wrap_text(text: str, font, draw, max_width: int) -> list[str]:
    if not text:
        return []
    lines: list[str] = []
    buf = ""
    for ch in text:
        candidate = buf + ch
        if draw.textlength(candidate, font=font) > max_width and buf:
            lines.append(buf)
            buf = ch
        else:
            buf = candidate
    if buf:
        lines.append(buf)
    return lines or [text]


def _anchor_offset(anchor: str, tw: float, th: float) -> tuple[float, float]:
    """Return offset to subtract from text box top-left for given anchor."""
    ax = ay = 0.0
    if "center" in anchor:
        ax = tw / 2
    elif "right" in anchor:
        ax = tw
    if "center" in anchor and anchor.startswith("center"):
        ay = th / 2
    elif anchor.startswith("bottom"):
        ay = th
    return ax, ay


def _apply_background(base, bg: dict):
    from PIL import Image, ImageDraw

    w, h = base.size
    overlay_kind = (bg.get("overlay") or "none").lower()
    alpha = int(bg.get("overlay_alpha", 160))
    if overlay_kind == "none" or alpha <= 0:
        return base, ImageDraw.Draw(base)

    if overlay_kind == "dark_flat":
        layer = Image.new("RGBA", (w, h), (0, 0, 0, alpha))
        base = Image.alpha_composite(base, layer)
    elif overlay_kind == "light_flat":
        layer = Image.new("RGBA", (w, h), (255, 255, 255, alpha))
        base = Image.alpha_composite(base, layer)
    elif overlay_kind == "bottom_gradient":
        layer = _gradient_overlay(w, h, alpha, top_alpha=0, bottom_alpha=alpha, from_top=0.6)
        base = Image.alpha_composite(base, layer)
    elif overlay_kind == "top_gradient":
        layer = _gradient_overlay(w, h, alpha, top_alpha=alpha, bottom_alpha=0, from_top=0.4)
        base = Image.alpha_composite(base, layer)
    return base, ImageDraw.Draw(base)


def _gradient_overlay(
    w: int, h: int, peak: int, *, top_alpha: int, bottom_alpha: int, from_top: float
):
    from PIL import Image, ImageDraw

    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    start_y = int(h * from_top)
    for y in range(start_y, h):
        ratio = (y - start_y) / max(h - start_y, 1)
        a = int(top_alpha * (1 - ratio) + bottom_alpha * ratio)
        draw.line([(0, y), (w, y)], fill=(0, 0, 0, a))
    return layer


def _draw_text_layer(
    canvas,
    draw,
    layer: dict,
    width: int,
    height: int,
    context: dict[str, str],
):
    from PIL import Image, ImageDraw, ImageFilter

    text = _interpolate(layer.get("text", ""), context) or ""
    if not text.strip():
        return

    # 倾斜：先画到临时层再绕锚点旋转
    rot = float(layer.get("rotation") or 0.0)
    if abs(rot) >= 0.3 and not layer.get("_rotating"):
        tmp = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        tdraw = ImageDraw.Draw(tmp)
        nested = dict(layer)
        nested["_rotating"] = True
        _draw_text_layer(tmp, tdraw, nested, width, height, context)
        cx = float(layer.get("x", 0.5)) * width
        cy = float(layer.get("y", 0.5)) * height
        tmp = tmp.rotate(-rot, center=(cx, cy), resample=Image.BICUBIC)
        canvas.alpha_composite(tmp)
        return

    writing = str(layer.get("writing_mode") or "horizontal").lower()
    if writing in ("vertical", "vertical-rl", "tb"):
        _draw_vertical_text(canvas, draw, layer, width, height, text)
        return

    bold = layer.get("font_weight") == "bold"
    max_w = max(32, int(width * float(layer.get("max_width_ratio", 0.88))))
    max_lines = max(1, min(8, int(layer.get("max_lines") or 3)))
    band_ratio = float(layer.get("band_height_ratio") or 0)
    band_h = int(height * band_ratio) if band_ratio > 0 else int(height * 0.18)

    # 字号由用户设定；超宽换行、超高裁切，不自动缩小字体
    base_ratio = float(layer.get("font_size_ratio", 0.048))
    font_size = max(14, int(height * base_ratio))
    font = _load_font(font_size, bold=bold)
    lines = _wrap_text(text, font, draw, max_w)
    line_h = font_size + int(font_size * 0.22)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        if len(last) > 1:
            lines[-1] = last[:-1] + "…"
    # 展示区域高度不够时裁掉多余行（字号不变）
    while len(lines) > 1 and line_h * len(lines) > band_h:
        lines = lines[:-1]
        if lines:
            last = lines[-1]
            if len(last) > 1 and not last.endswith("…"):
                lines[-1] = last[:-1] + "…"
    total_h = line_h * len(lines)

    cx = float(layer.get("x", 0.5)) * width
    cy = float(layer.get("y", 0.5)) * height
    anchor = layer.get("anchor", "center")
    ax, ay = _anchor_offset(anchor, max_w, total_h)
    box_x = cx - ax
    box_y = cy - ay

    color = _hex_rgb(layer.get("color"))
    stroke_color = _hex_rgb(layer.get("stroke_color"))
    stroke_w = int(layer.get("stroke_width", 0))
    effect = layer.get("effect", "none")
    glow_color = _hex_rgb(layer.get("glow_color", "#22D3EE"))

    def _line_x(line: str) -> float:
        lw = draw.textlength(line, font=font)
        if anchor in ("top_center", "bottom_center", "center") or (
            "center" in anchor and "left" not in anchor and "right" not in anchor
        ):
            return cx - lw / 2
        if "right" in anchor:
            return cx - lw
        return box_x

    # Pill background (drawn first behind text)
    if effect == "pill":
        pill = _hex_rgb(layer.get("pill_color", "#000000"))
        pill_alpha = int(layer.get("pill_alpha", 170))
        widest = max((draw.textlength(line, font=font) for line in lines), default=0)
        pad_x = int(font_size * 0.4)
        pad_y = int(font_size * 0.25)
        # Align pill with text block
        if "center" in anchor and "left" not in anchor and "right" not in anchor:
            left = cx - widest / 2
        elif "right" in anchor:
            left = cx - widest
        else:
            left = box_x
        rect = (
            int(left - pad_x),
            int(box_y - pad_y),
            int(left + widest + pad_x),
            int(box_y + total_h + pad_y),
        )
        overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        odraw = ImageDraw.Draw(overlay)
        odraw.rounded_rectangle(rect, radius=int(font_size * 0.4), fill=(*pill, pill_alpha))
        canvas.paste(overlay, (0, 0), overlay)
        draw = ImageDraw.Draw(canvas)

    # Glow / neon: render text to separate layer, blur, composite
    if effect in ("glow", "neon"):
        glow_rgba = (*glow_color, 220 if effect == "neon" else 160)
        glow_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        gdraw = ImageDraw.Draw(glow_layer)
        for i, line in enumerate(lines):
            y = int(box_y + i * line_h)
            gdraw.text((int(_line_x(line)), y), line, font=font, fill=glow_rgba, stroke_width=0)
        glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=font_size // 6 + 2))
        canvas.paste(glow_layer, (0, 0), glow_layer)
        draw = ImageDraw.Draw(canvas)

    # Drop shadow — 偏右下硬阴影，贴近短视频黄字封面
    if effect == "shadow":
        shadow_offset = max(3, font_size // 12)
        shadow_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        sdraw = ImageDraw.Draw(shadow_layer)
        for i, line in enumerate(lines):
            y = int(box_y + i * line_h)
            sdraw.text(
                (int(_line_x(line) + shadow_offset), y + shadow_offset),
                line,
                font=font,
                fill=(0, 0, 0, 220),
                stroke_width=max(0, stroke_w),
                stroke_fill=(0, 0, 0, 220),
            )
        canvas.paste(shadow_layer, (0, 0), shadow_layer)
        draw = ImageDraw.Draw(canvas)

    # Outline / stroke
    if effect == "outline":
        stroke_w = max(stroke_w, 3)

    for i, line in enumerate(lines):
        y = int(box_y + i * line_h)
        x = int(_line_x(line))
        if stroke_w > 0:
            draw.text(
                (x, y),
                line,
                font=font,
                fill=color,
                stroke_width=stroke_w,
                stroke_fill=stroke_color,
            )
        else:
            draw.text((x, y), line, font=font, fill=color)


def _draw_vertical_text(canvas, draw, layer: dict, width: int, height: int, text: str):
    """Top-to-bottom CJK title (竖排), optionally multiple columns right-to-left."""
    from PIL import Image, ImageDraw, ImageFilter

    # Drop spaces/newlines for 竖排；保留标点
    chars = [ch for ch in text.replace("\n", "").replace(" ", "") if ch]
    if not chars:
        return

    bold = layer.get("font_weight") == "bold"
    max_chars = max(2, min(16, int(layer.get("max_lines", 8)) * 2))
    band_ratio = float(layer.get("band_height_ratio") or 0.55)
    band_h = int(height * band_ratio)
    base_ratio = float(layer.get("font_size_ratio", 0.07))
    font_size = max(18, int(height * base_ratio))
    min_size = max(14, int(height * 0.028))
    font = _load_font(font_size, bold=bold)

    # Fit: one column preferred; wrap to extra columns if too tall
    for _ in range(30):
        font = _load_font(font_size, bold=bold)
        line_h = int(font_size * 1.12)
        cols_needed = max(1, (len(chars) + max_chars - 1) // max_chars) if False else 1
        # Prefer single column until exceeds band
        if len(chars) * line_h <= band_h or font_size <= min_size:
            break
        # try smaller font first
        if font_size > min_size:
            font_size = max(min_size, font_size - 2)
            continue
        break

    line_h = int(font_size * 1.12)
    per_col = max(1, band_h // max(line_h, 1))
    columns: list[list[str]] = []
    for i in range(0, len(chars), per_col):
        columns.append(chars[i : i + per_col])
    # Cap columns
    if len(columns) > 3:
        columns = columns[:3]
        flat = [c for col in columns for c in col]
        if len(flat) < len(chars):
            columns[-1][-1] = "…"

    col_gap = int(font_size * 1.25)
    col_w = font_size
    total_w = col_w * len(columns) + col_gap * (len(columns) - 1)
    tallest = max((len(col) * line_h for col in columns), default=line_h)

    cx = float(layer.get("x", 0.5)) * width
    cy = float(layer.get("y", 0.2)) * height
    anchor = layer.get("anchor", "top_center")
    ax, ay = _anchor_offset(anchor, total_w, tallest)
    origin_x = cx - ax
    origin_y = cy - ay

    color = _hex_rgb(layer.get("color"))
    stroke_color = _hex_rgb(layer.get("stroke_color"))
    stroke_w = int(layer.get("stroke_width", 0))
    effect = layer.get("effect", "none")
    glow_color = _hex_rgb(layer.get("glow_color", "#22D3EE"))
    if effect == "outline":
        stroke_w = max(stroke_w, 3)

    # columns right-to-left (traditional 竖排)
    def iter_glyphs():
        for ci, col in enumerate(reversed(columns)):
            x = origin_x + ci * (col_w + col_gap)
            for ri, ch in enumerate(col):
                y = origin_y + ri * line_h
                yield x, y, ch

    if effect in ("glow", "neon"):
        glow_rgba = (*glow_color, 220 if effect == "neon" else 160)
        glow_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        gdraw = ImageDraw.Draw(glow_layer)
        for x, y, ch in iter_glyphs():
            gdraw.text((int(x), int(y)), ch, font=font, fill=glow_rgba)
        glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=font_size // 5 + 2))
        canvas.paste(glow_layer, (0, 0), glow_layer)
        draw = ImageDraw.Draw(canvas)

    if effect == "shadow":
        off = max(2, font_size // 16)
        shadow_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        sdraw = ImageDraw.Draw(shadow_layer)
        for x, y, ch in iter_glyphs():
            sdraw.text((int(x + off), int(y + off)), ch, font=font, fill=(0, 0, 0, 170))
        shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=2))
        canvas.paste(shadow_layer, (0, 0), shadow_layer)
        draw = ImageDraw.Draw(canvas)

    for x, y, ch in iter_glyphs():
        if stroke_w > 0:
            draw.text(
                (int(x), int(y)),
                ch,
                font=font,
                fill=color,
                stroke_width=stroke_w,
                stroke_fill=stroke_color,
            )
        else:
            draw.text((int(x), int(y)), ch, font=font, fill=color)


def _resolve_layer_image(src: str, *, cache_dir: Path | None = None) -> Path | None:
    """Resolve local path or http(s) URL to a readable image file."""
    raw = (src or "").strip()
    if not raw:
        return None
    if raw.startswith(("http://", "https://")):
        import hashlib
        import urllib.request

        folder = cache_dir or Path("data/cover_url_cache")
        folder.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
        # Keep extension hint for gif/png
        ext = ".jpg"
        lower = raw.lower().split("?", 1)[0]
        for cand in (".gif", ".png", ".webp", ".jpeg", ".jpg"):
            if lower.endswith(cand):
                ext = ".jpg" if cand == ".jpeg" else cand
                break
        dest = folder / f"url_{digest}{ext}"
        if not dest.is_file() or dest.stat().st_size < 32:
            try:
                req = urllib.request.Request(
                    raw,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; CoverBot/1.0)"},
                )
                with urllib.request.urlopen(req, timeout=20) as resp:
                    dest.write_bytes(resp.read())
            except Exception:
                return None
        return dest if dest.is_file() else None
    path = Path(raw)
    return path if path.is_file() else None


def _draw_image_layer(canvas, layer: dict, width: int, height: int, *, cache_dir: Path | None = None):
    from PIL import Image

    src = str(layer.get("image_src") or "").strip()
    if not src:
        return
    path = _resolve_layer_image(src, cache_dir=cache_dir)
    if path is None:
        return
    try:
        img = Image.open(path)
        # GIF / animated: use first frame for static cover export
        img.seek(0)
        img = img.convert("RGBA")
    except Exception:
        return

    w_ratio = float(layer.get("width_ratio", 0.2))
    target_w = max(8, int(width * w_ratio))
    aspect = img.height / max(img.width, 1)
    target_h = max(8, int(target_w * aspect))
    img = img.resize((target_w, target_h), Image.LANCZOS)

    cx = float(layer.get("x", 0.5)) * width
    cy = float(layer.get("y", 0.5)) * height
    anchor = layer.get("anchor", "top_left")
    ax, ay = _anchor_offset(anchor, target_w, target_h)
    paste_x = int(cx - ax)
    paste_y = int(cy - ay)
    canvas.paste(img, (paste_x, paste_y), img)


def _interpolate(text: str, context: dict[str, str]) -> str:
    def repl(m: re.Match) -> str:
        key = m.group(1)
        return context.get(key, m.group(0))

    return re.sub(r"\{\{\s*(\w+)\s*\}\}", repl, text)


def cover_canvas_size(aspect: str | None = None) -> tuple[int, int]:
    """Export canvas size. Default portrait 9:16; landscape when publish is 16:9."""
    a = (aspect or "").strip().lower()
    if a in ("landscape_16_9", "16:9", "16_9", "landscape"):
        return 1920, 1080
    return 1080, 1920


def render_cover(
    base_image_path: Path,
    output_path: Path,
    template: dict,
    *,
    context: dict[str, str] | None = None,
    aspect: str | None = None,
    canvas_size: tuple[int, int] | None = None,
) -> Path:
    """Render a cover template onto a base image; writes to output_path."""
    from PIL import Image, ImageDraw

    from cover.subject import compose_subject_scene

    base = Image.open(base_image_path).convert("RGBA")
    # Match publish aspect (default 9:16); crop-center to fit
    target_w, target_h = canvas_size or cover_canvas_size(aspect)
    if base.size != (target_w, target_h):
        base = _fit_crop(base, target_w, target_h)

    template = normalize_template(template)
    subject_cfg = template.get("subject") or {}
    bg_canvas, subject_layer = compose_subject_scene(base, subject_cfg)

    layers = template.get("layers") or []
    behind = [l for l in layers if str(l.get("depth") or "front") == "behind"]
    front = [l for l in layers if str(l.get("depth") or "front") != "behind"]

    ctx = context or {}
    cache_dir = output_path.parent / "cover_url_cache"
    draw = ImageDraw.Draw(bg_canvas)

    for layer in behind:
        if layer.get("type") == "image":
            _draw_image_layer(bg_canvas, layer, target_w, target_h, cache_dir=cache_dir)
        elif layer.get("type") == "text":
            _draw_text_layer(bg_canvas, draw, layer, target_w, target_h, ctx)

    if subject_layer is not None:
        bg_canvas.paste(subject_layer, (0, 0), subject_layer)

    bg_canvas, draw = _apply_background(bg_canvas, template.get("background", {}))

    for layer in front:
        if layer.get("type") == "image":
            _draw_image_layer(bg_canvas, layer, target_w, target_h, cache_dir=cache_dir)
        elif layer.get("type") == "text":
            _draw_text_layer(bg_canvas, draw, layer, target_w, target_h, ctx)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    bg_canvas.convert("RGB").save(output_path, quality=92)
    return output_path


def _fit_crop(img, target_w: int, target_h: int):
    from PIL import Image

    src_w, src_h = img.size
    src_ratio = src_w / src_h
    dst_ratio = target_w / target_h
    if src_ratio > dst_ratio:
        new_w = int(src_h * dst_ratio)
        left = (src_w - new_w) // 2
        img = img.crop((left, 0, left + new_w, src_h))
    else:
        new_h = int(src_w / dst_ratio)
        top = (src_h - new_h) // 2
        img = img.crop((0, top, src_w, top + new_h))
    return img.resize((target_w, target_h), Image.LANCZOS)


def render_with_template_id(
    base_image_path: Path,
    output_path: Path,
    template_id: str,
    *,
    context: dict[str, str] | None = None,
    aspect: str | None = None,
) -> Path:
    tpl = get_template(template_id)
    if not tpl:
        raise ValueError(f"未找到封面模板: {template_id}")
    return render_cover(base_image_path, output_path, tpl, context=context, aspect=aspect)


def make_placeholder(width: int = 1080, height: int = 1920, *, aspect: str | None = None) -> Path:
    """Generate a gradient placeholder for preview when no base image exists."""
    if aspect is not None:
        width, height = cover_canvas_size(aspect)
    from PIL import Image, ImageDraw

    out = Path(__file__).resolve().parent.parent / "data" / "cover_placeholder.jpg"
    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)
    for y in range(height):
        t = y / max(height - 1, 1)
        r = int(30 * (1 - t) + 80 * t)
        g = int(41 * (1 - t) + 40 * t)
        b = int(59 * (1 - t) + 120 * t)
        draw.line([(0, y), (width, y)], fill=(r, g, b))
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, quality=88)
    return out

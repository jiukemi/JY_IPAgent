"""Unified Scene Style Pack catalogs + generative backgrounds (asset center ↔ publish)."""

from __future__ import annotations

import hashlib
import math
import random
import re
from pathlib import Path
from typing import Any

FONT_CATALOG: list[dict[str, str]] = [
    {"id": "noto_sc", "label": "Noto 黑体（清晰）", "css": '"Noto Sans SC", sans-serif', "remotion": "NotoSansSC"},
    {"id": "source_han", "label": "思源黑体（稳重）", "css": '"Noto Sans SC", "Source Han Sans SC", sans-serif', "remotion": "NotoSansSC"},
    {"id": "display", "label": "展示粗体（冲击）", "css": '"Noto Sans SC", sans-serif', "remotion": "NotoSansSC"},
    {"id": "serif_edu", "label": "衬线讲解（书卷）", "css": '"Noto Serif SC", "Noto Sans SC", serif', "remotion": "NotoSerifSC"},
]

BG_MODES: list[dict[str, str]] = [
    {"id": "transparent", "label": "透明底（融合抠图）"},
    {"id": "gradient", "label": "纯渐变"},
    {"id": "texture", "label": "纹理叠层"},
    {"id": "generative", "label": "生成式底图（按提示词）"},
    {"id": "library", "label": "素材库图片"},
]

REMOTION_THEMES: list[dict[str, str]] = [
    {"id": "auto", "label": "智能自动（按内容）"},
    {"id": "glass", "label": "毛玻璃底牌"},
    {"id": "pill", "label": "胶囊强调"},
    {"id": "bar", "label": "底部字幕条"},
    {"id": "kinetic", "label": "居中动感字"},
    {"id": "pop", "label": "弹跳强调"},
    {"id": "off", "label": "关闭 Remotion"},
]

EXTRA_LAYOUTS: dict[str, dict] = {
    "editorial": {"label": "杂志分栏", "animated": True, "css": True},
    "spotlight": {"label": "聚光强调", "animated": True, "css": True},
}

_GRID_WORDS = ("网格", "格子", "grid", "科技", "tech", "电路", "数码", "赛博", "cyber", "矩阵")
_AURORA_WORDS = ("光晕", "极光", "aurora", "柔光", "渐变光", "氛围")
_PARTICLE_WORDS = ("粒子", "星点", "particle", "点阵", "尘埃")
_WARM_WORDS = ("暖", "阳光", "课堂", "橙", "金")
_COOL_WORDS = ("冷", "蓝", "青", "夜", "深空")


def list_style_pack_options() -> dict:
    from workflow.hyperframes import list_card_themes
    from workflow.hyperframes_scenes import (
        SCENE_LAYOUTS,
        list_aspect_ratios,
        list_scene_layouts,
        list_smart_color_rules,
    )

    ensure_extra_layouts_registered()
    layouts = list_scene_layouts()
    seen = {str(x.get("id")) for x in layouts}
    for key, meta in EXTRA_LAYOUTS.items():
        if key in seen:
            continue
        layouts.append(
            {
                "id": key,
                "label": meta["label"],
                "animated": meta["animated"],
                "width": 1080,
                "height": 1920,
            }
        )
    for key, meta in EXTRA_LAYOUTS.items():
        SCENE_LAYOUTS.setdefault(key, meta)
    return {
        "themes": list_card_themes(),
        "layouts": layouts,
        "aspects": list_aspect_ratios(),
        "smart_color": list_smart_color_rules(),
        "fonts": FONT_CATALOG,
        "bg_modes": BG_MODES,
        "remotion_themes": REMOTION_THEMES,
    }


def normalize_style_pack(data: dict[str, Any] | None = None, **kwargs: Any) -> dict:
    raw = {**(data or {}), **kwargs}
    theme = str(raw.get("theme") or "tokyo_night").strip() or "tokyo_night"
    layout = str(raw.get("layout") or raw.get("template_id") or "kinetic").strip().lower().replace("-", "_")
    aspect = str(raw.get("aspect") or "portrait_9_16").strip().lower().replace("-", "_")
    font_ids = {f["id"] for f in FONT_CATALOG}
    bg_ids = {b["id"] for b in BG_MODES}
    rem_ids = {r["id"] for r in REMOTION_THEMES}
    font_id = str(raw.get("font_id") or "noto_sc").strip().lower()
    if font_id not in font_ids:
        font_id = "noto_sc"
    bg_mode = str(raw.get("bg_mode") or "generative").strip().lower()
    if bg_mode in ("ai_still", "ai"):
        bg_mode = "generative"
    if bg_mode in ("none", "off", "clear", "colorkey", "key"):
        bg_mode = "transparent"
    if bg_mode not in bg_ids:
        bg_mode = "generative"
    remotion_theme = str(raw.get("remotion_theme") or "off").strip().lower()
    if remotion_theme not in rem_ids:
        remotion_theme = "off"
    try:
        font_scale = float(raw.get("font_scale") if raw.get("font_scale") is not None else 1.0)
    except (TypeError, ValueError):
        font_scale = 1.0
    font_scale = max(0.7, min(2.0, font_scale))
    return {
        "theme": theme,
        "layout": layout,
        "template_id": layout,
        "aspect": aspect,
        "font_id": font_id,
        "font_scale": font_scale,
        "bg_mode": bg_mode,
        "bg_asset": str(raw.get("bg_asset") or "").strip(),
        "bg_prompt": str(raw.get("bg_prompt") or "").strip(),
        "remotion_theme": remotion_theme,
    }


def font_css(font_id: str) -> str:
    for f in FONT_CATALOG:
        if f["id"] == font_id:
            return f["css"]
    return FONT_CATALOG[0]["css"]


def ensure_extra_layouts_registered() -> None:
    from workflow.hyperframes_scenes import SCENE_LAYOUTS

    for key, meta in EXTRA_LAYOUTS.items():
        SCENE_LAYOUTS.setdefault(key, meta)


def _seed_from(theme: str, prompt: str, width: int, height: int) -> int:
    h = hashlib.sha256(f"{theme}|{prompt}|{width}x{height}".encode("utf-8")).hexdigest()
    return int(h[:8], 16)


def _prompt_style(prompt: str) -> str:
    p = (prompt or "").strip().lower()
    if any(w in p for w in _GRID_WORDS):
        return "grid"
    if any(w in p for w in _PARTICLE_WORDS):
        return "particle"
    if any(w in p for w in _AURORA_WORDS):
        return "aurora"
    # default generative: prefer subtle mesh, not big color blobs
    if p:
        return "mesh"
    return "aurora"


def _tint_rgb(rgb: tuple[int, int, int], prompt: str) -> tuple[int, int, int]:
    p = (prompt or "").lower()
    r, g, b = rgb
    if any(w in p for w in _WARM_WORDS):
        return (min(255, r + 18), min(255, g + 8), max(0, b - 12))
    if any(w in p for w in _COOL_WORDS) or any(w in p for w in _GRID_WORDS):
        return (max(0, r - 10), min(255, g + 6), min(255, b + 18))
    return rgb


def generate_background_png(
    output_path: Path,
    *,
    theme: dict,
    width: int,
    height: int,
    mode: str = "generative",
    prompt: str = "",
    library_path: str | Path | None = None,
) -> Path:
    """Build a premium still background. Prompt keywords drive pattern (grid/tech/…)."""
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    mode = (mode or "generative").lower()
    if mode == "library" and library_path and Path(library_path).is_file():
        img = Image.open(library_path).convert("RGB")
        img = img.resize((width, height), Image.Resampling.LANCZOS)
        img = ImageEnhance.Brightness(img).enhance(0.72)
        img = ImageEnhance.Contrast(img).enhance(1.08)
        img.save(output_path, quality=92)
        return output_path

    top = _tint_rgb(tuple(int(x) for x in theme["top"][:3]), prompt)
    bottom = _tint_rgb(tuple(int(x) for x in theme["bottom"][:3]), prompt)
    accent = _tint_rgb(tuple(int(x) for x in theme["accent_bar"][:3]), prompt)
    outline = _tint_rgb(
        tuple(int(x) for x in (theme.get("outline") or theme["accent_bar"])[:3]),
        prompt,
    )

    img = Image.new("RGB", (width, height), top)
    draw = ImageDraw.Draw(img, "RGBA")
    for y in range(height):
        t = y / max(height - 1, 1)
        # Slight diagonal feel for tech looks
        r = int(top[0] * (1 - t) + bottom[0] * t)
        g = int(top[1] * (1 - t) + bottom[1] * t)
        b = int(top[2] * (1 - t) + bottom[2] * t)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    style = _prompt_style(prompt) if mode == "generative" else ("texture" if mode == "texture" else "aurora")
    rng = random.Random(_seed_from(str(theme.get("id", "")), prompt, width, height))

    if style == "grid":
        # Darken base a bit for tech grid readability
        dark = Image.new("RGBA", (width, height), (0, 0, 0, 55))
        img = Image.alpha_composite(img.convert("RGBA"), dark).convert("RGB")
        layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        step = max(36, min(width, height) // 18)
        line_a = 38
        for x in range(0, width, step):
            ld.line([(x, 0), (x, height)], fill=(*accent, line_a), width=1)
        for y in range(0, height, step):
            ld.line([(0, y), (width, y)], fill=(*outline, line_a), width=1)
        # Major lines every 4 cells
        for x in range(0, width, step * 4):
            ld.line([(x, 0), (x, height)], fill=(*accent, 70), width=2)
        for y in range(0, height, step * 4):
            ld.line([(0, y), (width, y)], fill=(*accent, 70), width=2)
        # Intersection nodes
        for x in range(0, width, step * 2):
            for y in range(0, height, step * 2):
                if rng.random() < 0.35:
                    r = max(2, step // 14)
                    ld.ellipse([x - r, y - r, x + r, y + r], fill=(*accent, 110))
        # Soft scan glow (not a solid color block)
        glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        cy = int(height * (0.28 + 0.08 * rng.random()))
        gd.ellipse(
            [-width * 0.2, cy - height * 0.12, width * 1.2, cy + height * 0.12],
            fill=(*accent, 28),
        )
        glow = glow.filter(ImageFilter.GaussianBlur(radius=min(width, height) // 10))
        img = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")
        img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")

    elif style == "particle":
        layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        n = width * height // 900
        for _ in range(n):
            x = rng.randint(0, width - 1)
            y = rng.randint(0, height - 1)
            r = rng.randint(1, 3)
            col = accent if rng.random() > 0.4 else outline
            ld.ellipse([x - r, y - r, x + r, y + r], fill=(*col, rng.randint(60, 140)))
        img = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")

    elif style in ("aurora", "mesh", "texture"):
        # Soft accents only — avoid large opaque color blocks
        n_blobs = 3 if style == "texture" else 4
        for _ in range(n_blobs):
            cx = rng.randint(0, width)
            cy = rng.randint(0, height)
            rad = rng.randint(int(min(width, height) * 0.12), int(min(width, height) * 0.28))
            col = accent if rng.random() > 0.5 else outline
            layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            ld = ImageDraw.Draw(layer)
            ld.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], fill=(*col, 28 if style != "texture" else 22))
            layer = layer.filter(ImageFilter.GaussianBlur(radius=max(24, rad // 2)))
            img = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")
        if style == "mesh":
            layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            ld = ImageDraw.Draw(layer)
            for i in range(4):
                pts = []
                amp = height * (0.03 + 0.015 * i)
                phase = rng.random() * math.pi * 2
                for x in range(0, width, 16):
                    y = int(height * (0.3 + 0.1 * i) + math.sin(x / 80 + phase) * amp)
                    pts.append((x, y))
                if len(pts) >= 2:
                    ld.line(pts, fill=(*accent, 32), width=max(3, width // 160))
            layer = layer.filter(ImageFilter.GaussianBlur(radius=14))
            img = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")

    # Light vignette (keep edges readable, not two big slabs)
    vig = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    vd = ImageDraw.Draw(vig)
    margin = int(min(width, height) * 0.06)
    for i in range(margin):
        a = int(48 * (1 - i / margin))
        vd.rectangle([i, i, width - 1 - i, height - 1 - i], outline=(0, 0, 0, a))
    vig = vig.filter(ImageFilter.GaussianBlur(radius=max(8, margin // 2)))
    img = Image.alpha_composite(img.convert("RGBA"), vig).convert("RGB")

    # Optional prompt watermark for debug? skip — keep clean
    img.save(output_path, quality=93)
    return output_path


def resolve_background_for_job(
    work_dir: Path,
    *,
    pack: dict,
    theme: dict,
    width: int,
    height: int,
) -> Path | None:
    """Return a PNG path for HF bg layer, or None for pure CSS gradient / transparent fusion."""
    mode = pack.get("bg_mode") or "generative"
    if mode in ("gradient", "transparent", "none", "off"):
        return None
    # Include prompt in filename so regenerating with new prompt doesn't reuse stale bg
    slug = re.sub(r"[^\w\u4e00-\u9fff]+", "_", str(pack.get("bg_prompt") or "none"))[:24] or "none"
    out = work_dir / f"bg_{mode}_{slug}_{width}x{height}.png"
    lib = pack.get("bg_asset") or None
    generate_background_png(
        out,
        theme=theme,
        width=width,
        height=height,
        mode=mode,
        prompt=str(pack.get("bg_prompt") or ""),
        library_path=lib,
    )
    return out

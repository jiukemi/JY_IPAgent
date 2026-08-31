"""Cover template registry — built-in + user JSON templates."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from cover.builtin_templates import BUILTIN_TEMPLATES, _subject

ROOT = Path(__file__).resolve().parent.parent
USER_DIR = ROOT / "data" / "cover_templates"

_ID_RE = re.compile(r"[^a-zA-Z0-9_\-]+")


def _slug(name: str) -> str:
    s = _ID_RE.sub("_", name.strip()).strip("_").lower()
    return s or "custom"


def _user_dir() -> Path:
    USER_DIR.mkdir(parents=True, exist_ok=True)
    return USER_DIR


def list_templates() -> list[dict]:
    builtins = [dict(t) for t in BUILTIN_TEMPLATES]
    out = builtins
    for fp in sorted(_user_dir().glob("*.json")):
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("id"):
                data["builtin"] = False
                out.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return out


def get_template(tid: str) -> dict | None:
    for t in BUILTIN_TEMPLATES:
        if t["id"] == tid:
            return dict(t)
    legacy = {
        "hot_yellow": "dy_hook_yellow",
        "classic_bottom": "dy_bottom",
        "bold_center": "dy_soft_center",
        "vertical_hook": "dy_bottom",
        "minimal_tag": "dy_hot_tag",
        "neon_top": "dy_soft_center",
        "yellow_outline": "dy_hook_yellow",
        "cut_dy_white": "cut_cyan_dash",
        "cut_white_stroke": "cut_big_yellow",
        "cut_portrait_center": "cut_blur_bg",
        "cut_white_dash": "cut_cyan_dash",
        "cut_white_glow": "cut_blur_bg",
    }
    mapped = legacy.get(tid)
    if mapped:
        return get_template(mapped)
    fp = _user_dir() / f"{_slug(tid)}.json"
    if fp.is_file():
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
            data["builtin"] = False
            return data
        except (json.JSONDecodeError, OSError):
            return None
    return None


def save_template(template: dict) -> dict:
    name = (template.get("name") or "自定义").strip()
    tid = template.get("id") or _slug(name)
    tid = _slug(tid)
    template = dict(template)
    template["id"] = tid
    template["name"] = name
    template["builtin"] = False
    fp = _user_dir() / f"{tid}.json"
    fp.write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")
    return template


def delete_template(tid: str) -> bool:
    fp = _user_dir() / f"{_slug(tid)}.json"
    if fp.is_file():
        fp.unlink()
        return True
    return False


VALID_EFFECTS = frozenset({"none", "shadow", "outline", "glow", "neon", "pill"})
VALID_ANCHORS = frozenset(
    {
        "top_left",
        "top_center",
        "top_right",
        "center",
        "bottom_left",
        "bottom_center",
        "bottom_right",
    }
)
VALID_OUTLINES = frozenset({"none", "solid", "dashed", "glow"})
VALID_BG_MODES = frozenset({"blur", "original", "white", "black"})


def normalize_layer(layer: dict) -> dict:
    layer_type = str(layer.get("type") or "text").lower()
    depth = "behind" if str(layer.get("depth") or "") == "behind" else "front"
    if layer_type == "image":
        return {
            "id": str(layer.get("id") or "image"),
            "type": "image",
            "label": str(layer.get("label") or "图片装饰"),
            "text": "",
            "depth": depth,
            "image_src": str(layer.get("image_src") or ""),
            "width_ratio": _clamp(float(layer.get("width_ratio", 0.2)), 0.05, 1.0),
            "x": _clamp(float(layer.get("x", 0.08)), 0.0, 1.0),
            "y": _clamp(float(layer.get("y", 0.06)), 0.0, 1.0),
            "anchor": layer.get("anchor") if layer.get("anchor") in VALID_ANCHORS else "top_left",
            "font_size_ratio": 0.05,
            "font_weight": "normal",
            "color": "#FFFFFF",
            "stroke_color": "#000000",
            "stroke_width": 0,
            "effect": "none",
            "max_width_ratio": 1.0,
            "rotation": float(layer.get("rotation", 0.0)),
        }
    return {
        "id": str(layer.get("id") or "layer"),
        "type": "text",
        "label": str(layer.get("label") or "文字层"),
        "text": str(layer.get("text") or "{{title}}"),
        "depth": depth,
        "x": _clamp(float(layer.get("x", 0.5)), 0.0, 1.0),
        "y": _clamp(float(layer.get("y", 0.5)), 0.0, 1.0),
        "anchor": layer.get("anchor") if layer.get("anchor") in VALID_ANCHORS else "center",
        "font_size_ratio": _clamp(float(layer.get("font_size_ratio", 0.048)), 0.018, 0.18),
        "font_weight": "bold" if layer.get("font_weight") == "bold" else "normal",
        "color": _hex(layer.get("color"), "#FFFFFF"),
        "stroke_color": _hex(layer.get("stroke_color"), "#000000"),
        "stroke_width": _clamp(int(layer.get("stroke_width", 2)), 0, 16),
        "effect": layer.get("effect") if layer.get("effect") in VALID_EFFECTS else "none",
        "glow_color": _hex(layer.get("glow_color"), "#22D3EE"),
        "pill_color": _hex(layer.get("pill_color"), "#F97316"),
        "pill_alpha": _clamp(int(layer.get("pill_alpha", 220)), 0, 255),
        "max_width_ratio": _clamp(float(layer.get("max_width_ratio", 0.86)), 0.1, 1.0),
        "max_lines": _clamp(int(layer.get("max_lines", 3)), 1, 8),
        "band_height_ratio": _clamp(float(layer.get("band_height_ratio", 0.12)), 0.03, 0.7),
        "rotation": _clamp(float(layer.get("rotation", 0.0)), -45.0, 45.0),
        "writing_mode": (
            "vertical"
            if str(layer.get("writing_mode") or "").lower() in ("vertical", "vertical-rl", "tb")
            else "horizontal"
        ),
    }


def _clamp(v: float, lo: float, hi: float) -> float:
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return lo


def _hex(v: Any, default: str) -> str:
    s = str(v or "").strip()
    if re.match(r"^#[0-9A-Fa-f]{6}$", s):
        return s
    return default


def normalize_subject(raw: Any) -> dict:
    if not isinstance(raw, dict):
        return _subject(enabled=False)
    outline = str(raw.get("outline") or "none").lower()
    if outline not in VALID_OUTLINES:
        outline = "none"
    bg_mode = str(raw.get("bg_mode") or "blur").lower()
    if bg_mode not in VALID_BG_MODES:
        bg_mode = "blur"
    return {
        "enabled": bool(raw.get("enabled")),
        "bg_mode": bg_mode,
        "blur_radius": int(_clamp(raw.get("blur_radius", 48), 8, 90)),
        "outline": outline,
        "outline_color": _hex(raw.get("outline_color"), "#FFFFFF"),
        "outline_width": int(_clamp(raw.get("outline_width", 10), 0, 28)),
        "glow_color": _hex(raw.get("glow_color"), "#FFFFFF"),
        "scale": _clamp(raw.get("scale", 1.0), 0.5, 1.4),
        "fill_ratio": _clamp(raw.get("fill_ratio", 0.5), 0.28, 0.85),
        "x_offset": _clamp(raw.get("x_offset", -0.06), -0.25, 0.25),
        "y_offset": _clamp(raw.get("y_offset", 0.08), -0.15, 0.2),
    }


def normalize_template(template: dict) -> dict:
    layers = template.get("layers") or []
    if not isinstance(layers, list):
        layers = []
    return {
        "id": str(template.get("id") or ""),
        "name": str(template.get("name") or "自定义"),
        "builtin": bool(template.get("builtin")),
        "subject": normalize_subject(template.get("subject")),
        "background": {
            "overlay": (
                template.get("background", {}).get("overlay", "none")
                if isinstance(template.get("background"), dict)
                and template.get("background", {}).get("overlay")
                in ("none", "dark_flat", "light_flat", "bottom_gradient", "top_gradient")
                else "none"
            ),
            "overlay_alpha": _clamp(
                (template.get("background", {}) or {}).get("overlay_alpha", 160)
                if isinstance(template.get("background"), dict)
                else 160,
                0,
                255,
            ),
        },
        "layers": [normalize_layer(l) for l in layers if isinstance(l, dict)],
    }

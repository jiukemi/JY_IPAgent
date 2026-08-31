"""Persisted Scene Style Pack used by asset center + education publish."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from workflow.scene_style_pack import normalize_style_pack

ASSET_ROOT = Path("data/assets")
STYLE_PATH = ASSET_ROOT / "active_hyperframe_style.json"

DEFAULT_STYLE = normalize_style_pack(
    {
        "theme": "tokyo_night",
        "layout": "kinetic",
        "aspect": "portrait_9_16",
        "font_id": "noto_sc",
        "bg_mode": "generative",
        "bg_asset": "",
        "bg_prompt": "",
        "remotion_theme": "off",
    }
)


def default_active_style() -> dict:
    return {**DEFAULT_STYLE, "updated_at": 0}


def get_active_style() -> dict:
    if not STYLE_PATH.is_file():
        return default_active_style()
    try:
        data = json.loads(STYLE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default_active_style()
    if not isinstance(data, dict):
        return default_active_style()
    out = normalize_style_pack(data)
    try:
        out["updated_at"] = int(data.get("updated_at") or 0)
    except (TypeError, ValueError):
        out["updated_at"] = 0
    return out


def set_active_style(
    theme: str,
    layout: str,
    aspect: str,
    *,
    font_id: str = "noto_sc",
    font_scale: float = 1.0,
    bg_mode: str = "generative",
    bg_asset: str = "",
    bg_prompt: str = "",
    remotion_theme: str = "off",
    **_extra: Any,
) -> dict:
    theme_s = (theme or "").strip()
    layout_s = (layout or "").strip()
    aspect_s = (aspect or "").strip()
    if not theme_s or not layout_s or not aspect_s:
        raise ValueError("theme、layout、aspect 均不能为空")
    out = normalize_style_pack(
        {
            "theme": theme_s,
            "layout": layout_s,
            "aspect": aspect_s,
            "font_id": font_id,
            "font_scale": font_scale,
            "bg_mode": bg_mode,
            "bg_asset": bg_asset,
            "bg_prompt": bg_prompt,
            "remotion_theme": remotion_theme,
        }
    )
    out["updated_at"] = int(time.time() * 1000)
    ASSET_ROOT.mkdir(parents=True, exist_ok=True)
    STYLE_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def set_active_style_pack(pack: dict[str, Any]) -> dict:
    p = normalize_style_pack(pack)
    return set_active_style(
        p["theme"],
        p["layout"],
        p["aspect"],
        font_id=p["font_id"],
        font_scale=float(p.get("font_scale") or 1.0),
        bg_mode=p["bg_mode"],
        bg_asset=p["bg_asset"],
        bg_prompt=p["bg_prompt"],
        remotion_theme=p["remotion_theme"],
    )

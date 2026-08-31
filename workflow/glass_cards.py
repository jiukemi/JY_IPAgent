"""Glass overlay cards for short / 口播混剪 (transparent PiP over lipsync)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

log = logging.getLogger(__name__)

CARD_POSITIONS = (
    "auto",
    "top_right",
    "top_left",
    "bottom_right",
    "bottom_left",
    "center",
)


def normalize_position(pos: str | None) -> str:
    p = (pos or "auto").strip().lower()
    if p in CARD_POSITIONS:
        return p
    if p in ("side_right", "right"):
        return "top_right"
    if p in ("side_left", "left"):
        return "top_left"
    return "auto"


def heuristic_card_from_text(text: str) -> dict[str, Any]:
    """Rule-based title + bullets when LLM unavailable."""
    raw = re.sub(r"\s+", " ", (text or "").strip())
    if not raw:
        return {"title": "要点", "bullets": []}
    # Split on Chinese / common punctuation
    parts = [p.strip() for p in re.split(r"[，,。！？；;\n]+", raw) if p.strip()]
    if not parts:
        return {"title": raw[:18], "bullets": []}
    title = parts[0][:22]
    bullets: list[str] = []
    for p in parts[1:]:
        if len(bullets) >= 4:
            break
        chunk = p[:28]
        if chunk and chunk != title:
            bullets.append(chunk)
    if not bullets and len(raw) > len(title):
        rest = raw[len(parts[0]) :].strip(" ，,。")
        if rest:
            bullets.append(rest[:28])
    return {"title": title, "bullets": bullets}


def llm_card_from_text(cfg: dict, text: str) -> dict[str, Any]:
    """Ask rewrite LLM for a short glass-card payload. Falls back to heuristic."""
    from script.llm_client import chat_completion, has_llm_key

    if not has_llm_key(cfg, "rewrite"):
        return heuristic_card_from_text(text)
    user = (
        "把下面口播片段压成「屏幕玻璃字卡」文案，赛博科技感、短、可扫读。\n"
        "只输出 JSON：{\"title\":\"主标题≤14字\",\"bullets\":[\"要点1\",\"要点2\"]}，bullets 最多 4 条，每条≤16字。\n"
        "不要字幕跟读全文，要提炼信息点。可夹少量英文术语。\n\n"
        f"口播：\n{text[:400]}"
    )
    try:
        raw = chat_completion(
            cfg,
            block="rewrite",
            system="你是短视频包装设计师，擅长把口播提炼成屏幕字卡。",
            user=user,
            temperature=0.4,
        )
        blob = (raw or "").strip()
        if "```" in blob:
            blob = re.sub(r"^```(?:json)?\s*", "", blob)
            blob = re.sub(r"\s*```$", "", blob)
        data = json.loads(blob)
        title = str(data.get("title") or "").strip()[:22] or "要点"
        bullets_raw = data.get("bullets") or []
        bullets = [str(b).strip()[:28] for b in bullets_raw if str(b).strip()][:4]
        return {"title": title, "bullets": bullets}
    except Exception:
        log.exception("glass card LLM failed; using heuristic")
        return heuristic_card_from_text(text)


def format_card_display_text(card: dict[str, Any]) -> str:
    """Serialize card for HyperFrames text_card HTML parser."""
    title = str(card.get("title") or "要点").strip()
    bullets = card.get("bullets") or []
    lines = [title]
    for b in bullets:
        t = str(b).strip()
        if t:
            lines.append(f"• {t}")
    return "\n".join(lines)


def parse_card_display_text(text: str) -> dict[str, Any]:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return {"title": "要点", "bullets": []}
    title = lines[0].lstrip("•·- ").strip()[:22] or "要点"
    bullets: list[str] = []
    for ln in lines[1:]:
        t = re.sub(r"^[•·\-\*]\s*", "", ln).strip()
        if t:
            bullets.append(t[:28])
    return {"title": title, "bullets": bullets[:4]}


def resolve_card_position(
    preferred: str,
    *,
    face_empty_side: str | None = None,
) -> str:
    """Map auto → corner away from face (face left → card top_right)."""
    pref = normalize_position(preferred)
    if pref != "auto":
        return pref
    side = (face_empty_side or "right").strip().lower()
    if side == "left":
        return "top_left"
    return "top_right"

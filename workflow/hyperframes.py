"""HyperFrames: CSS scene compositions + cards from script (local, no cloud)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from workflow.publish import SubCue, build_subtitle_cues, split_script_for_subtitles

CARD_W = 960
CARD_H = 540

# 社区主流 IDE/设计配色（Tokyo Night / Catppuccin / Nord / Dracula / Gruvbox / Rosé Pine）
CARD_THEMES: dict[str, dict] = {
    "tokyo_night": {
        "label": "Tokyo Night",
        "top": (26, 27, 38),
        "bottom": (36, 40, 59),
        "text": (192, 202, 245),
        "shadow": (0, 0, 0),
        "outline": (122, 162, 247),
        "accent_bar": (122, 162, 247),
    },
    "catppuccin": {
        "label": "Catppuccin Mocha",
        "top": (30, 30, 46),
        "bottom": (49, 50, 68),
        "text": (205, 214, 244),
        "shadow": (17, 17, 27),
        "outline": (137, 180, 250),
        "accent_bar": (166, 227, 161),
    },
    "nord": {
        "label": "Nord",
        "top": (46, 52, 64),
        "bottom": (59, 66, 82),
        "text": (236, 239, 244),
        "shadow": (0, 0, 0),
        "outline": (136, 192, 208),
        "accent_bar": (129, 161, 193),
    },
    "dracula": {
        "label": "Dracula",
        "top": (40, 42, 54),
        "bottom": (68, 71, 90),
        "text": (248, 248, 242),
        "shadow": (0, 0, 0),
        "outline": (189, 147, 249),
        "accent_bar": (255, 121, 198),
    },
    "gruvbox": {
        "label": "Gruvbox Dark",
        "top": (40, 40, 40),
        "bottom": (60, 56, 54),
        "text": (235, 219, 178),
        "shadow": (0, 0, 0),
        "outline": (250, 189, 47),
        "accent_bar": (184, 187, 38),
    },
    "rose_pine": {
        "label": "Rosé Pine Moon",
        "top": (35, 33, 54),
        "bottom": (42, 39, 63),
        "text": (224, 222, 244),
        "shadow": (0, 0, 0),
        "outline": (196, 167, 231),
        "accent_bar": (235, 188, 186),
    },
}

DEFAULT_CARD_THEME = "tokyo_night"


def list_card_themes() -> list[dict]:
    out: list[dict] = []
    for k, v in CARD_THEMES.items():
        out.append(
            {
                "id": k,
                "label": v["label"],
                "top": _rgb_hex(v["top"]),
                "bottom": _rgb_hex(v["bottom"]),
                "text": _rgb_hex(v["text"]),
                "accent": _rgb_hex(v["accent_bar"]),
                "outline": _rgb_hex(v["outline"]),
            }
        )
    return out


def list_hyperframe_options() -> dict:
    from workflow.scene_style_pack import list_style_pack_options

    return list_style_pack_options()


def suggest_hyperframe_style(text: str, *, aspect: str = "portrait_9_16") -> dict:
    """Heuristic theme + layout from subtitle text (keyword / length / punctuation)."""
    from workflow.hyperframes_scenes import (
        _SMART_EMO_WORDS,
        _SMART_HOOK_WORDS,
        _SMART_TRUST_WORDS,
        _SMART_URGENT_WORDS,
    )

    raw = (text or "").strip()
    compact = raw.replace("\n", "").replace(" ", "")
    n = len(compact)
    reasons: list[str] = []

    # --- layout ---
    layout = "kinetic"
    if any(m in raw for m in ("「", "」", "“", "”", '"')) or raw.startswith(("“", "「")):
        layout = "quote"
        reasons.append("含引用语气 → 金句版式")
    elif any(x in raw for x in ("1.", "2.", "一、", "二、", "①", "②", "要点", "第一", "第二", "；")) or raw.count("、") >= 2:
        layout = "bullets"
        reasons.append("列举/要点结构 → 要点列表")
    elif n <= 12 and (raw.endswith(("！", "!", "？", "?")) or any(w in raw for w in _SMART_HOOK_WORDS[:12])):
        layout = "kinetic"
        reasons.append("短句强钩子 → 动感大字")
    elif n >= 28 or raw.count("。") >= 2:
        layout = "glass"
        reasons.append("较长讲解 → 毛玻璃正文")
    elif any(w in raw for w in ("重点", "注意", "记住", "核心", "关键")):
        layout = "hero"
        reasons.append("强调开场 → 标题开场")
    else:
        layout = "kinetic"
        reasons.append("默认动感大字")

    # --- theme ---
    theme = "tokyo_night"
    urgent_hits = sum(1 for w in _SMART_URGENT_WORDS if w in raw)
    trust_hits = sum(1 for w in _SMART_TRUST_WORDS if w in raw)
    emo_hits = sum(1 for w in _SMART_EMO_WORDS if w in raw)
    hook_hits = sum(1 for w in _SMART_HOOK_WORDS if w in raw)
    if urgent_hits >= 1 or any(c in raw for c in ("% ", "%", "马上", "立刻")):
        theme = "dracula"
        reasons.append("紧迫/数字感 → Dracula")
    elif emo_hits >= 1:
        theme = "rose_pine"
        reasons.append("情绪词 → Rosé Pine")
    elif trust_hits >= 1:
        theme = "nord"
        reasons.append("信任/权威 → Nord")
    elif hook_hits >= 2:
        theme = "gruvbox"
        reasons.append("强钩子 → Gruvbox")
    elif n >= 36:
        theme = "catppuccin"
        reasons.append("长文阅读 → Catppuccin")
    else:
        theme = "tokyo_night"
        reasons.append("默认 Tokyo Night")

    return {
        "theme": theme,
        "layout": layout,
        "aspect": aspect or "portrait_9_16",
        "reasons": reasons,
        "color_keywords": True,
        "auto_background": True,
        "sample": compact[:48] or "…",
        **suggest_fusion_motion(raw, index=0),
    }


def suggest_fusion_motion(text: str, *, index: int = 0) -> dict:
    """Auto-pick fusion enter motion from cue text — no manual UI knobs.

    Motions: slide_ltr / slide_rtl / slide_scale / pop_scale / rise_soft / pulse / drift
    """
    from workflow.hyperframes_scenes import (
        _SMART_EMO_WORDS,
        _SMART_HOOK_WORDS,
        _SMART_TRUST_WORDS,
        _SMART_URGENT_WORDS,
    )

    raw = (text or "").strip()
    compact = raw.replace("\n", "").replace(" ", "")
    n = len(compact)
    reasons: list[str] = []
    idx = max(0, int(index or 0))

    urgent_hits = sum(1 for w in _SMART_URGENT_WORDS if w in raw)
    # Soft time words like「今天」are too common in education scripts — don't force pulse
    hard_urgent = (
        "立刻",
        "马上",
        "抓紧",
        "仅剩",
        "倒计时",
        "仅限",
        "名额",
        "抢",
        "速来",
        "别错过",
        "不容错过",
        "就现在",
    )
    hard_urgent_hits = sum(1 for w in hard_urgent if w in raw)
    trust_hits = sum(1 for w in _SMART_TRUST_WORDS if w in raw)
    emo_hits = sum(1 for w in _SMART_EMO_WORDS if w in raw)
    hook_hits = sum(1 for w in _SMART_HOOK_WORDS if w in raw)
    is_q = raw.endswith(("？", "?")) or "吗" in raw[-3:]
    is_bang = raw.endswith(("！", "!"))
    is_quote = any(m in raw for m in ("「", "」", "“", "”"))
    is_list = any(x in raw for x in ("1.", "2.", "一、", "二、", "①", "要点", "第一")) or raw.count("、") >= 2
    mix = (sum(ord(c) for c in compact[:12]) + idx * 7) % 5

    if hard_urgent_hits >= 1 or (n <= 10 and is_bang):
        motion = "pulse"
        reasons.append("紧迫/短促强调 → 脉冲放大")
    elif n <= 14 and (is_q or is_bang or hook_hits >= 1):
        motion = "pop_scale"
        reasons.append("短钩子/问句 → 弹跳缩放")
    elif is_quote or emo_hits >= 1:
        motion = "drift"
        reasons.append("金句/情绪 → 轻漂移")
    elif is_list or n >= 28:
        motion = "rise_soft"
        reasons.append("列举/长句 → 柔和上浮")
    elif n <= 18:
        motion = "pop_scale" if (idx + n) % 2 else "rise_soft"
        reasons.append("短句 → 居中弹入/上浮")
    else:
        motion = "pop_scale" if mix % 2 else "rise_soft"
        reasons.append("默认居中动效（避免侧向漂移）")

    if motion == "slide_scale" and mix == 0:
        motion = "pop_scale"
    elif motion == "slide_scale" and mix == 1:
        motion = "rise_soft"
    elif motion == "rise_soft" and mix == 2 and n < 40:
        motion = "pop_scale"

    return {
        "motion": motion,
        "motion_reasons": reasons,
        "urgent_hits": urgent_hits,
    }


def render_scene_preview_image(
    text: str,
    output_path: Path,
    *,
    theme: str = DEFAULT_CARD_THEME,
    layout: str = "kinetic",
    aspect: str = "portrait_9_16",
    font_scale: float = 1.0,
    compose_mode: str = "",
) -> Path:
    from workflow.hyperframes_scenes import DEFAULT_SCENE_LAYOUT, render_scene_still

    pal = _resolve_theme(theme)
    key = (layout or DEFAULT_SCENE_LAYOUT).lower().replace("-", "_")
    sample, eff_layout = _prepare_compose_display_text(
        text,
        compose_mode=compose_mode or "cover",
        layout=key,
        aspect=aspect,
        font_scale=font_scale,
    )
    return render_scene_still(
        sample,
        output_path,
        layout=eff_layout if compose_mode == "fusion" else key,
        theme=pal,
        aspect=aspect,
        font_scale=font_scale,
    )


def render_scene_preview_motion(
    text: str,
    output_path: Path,
    *,
    theme: str = DEFAULT_CARD_THEME,
    layout: str = "kinetic",
    aspect: str = "portrait_9_16",
    duration_sec: float = 1.6,
    font_scale: float = 1.0,
    compose_mode: str = "",
) -> Path:
    """Short looping preview clip (~1.5s) for theme/layout picker — not full export quality."""
    from pipeline import ensure_ffmpeg
    from workflow.app_config import load_cfg
    from workflow.hyperframes_scenes import DEFAULT_SCENE_LAYOUT, generate_scene_video

    sample, eff_layout = _prepare_compose_display_text(
        (text or "").strip()[:160] or "HyperFrames 预览",
        compose_mode=compose_mode or "cover",
        layout=(layout or DEFAULT_SCENE_LAYOUT).lower().replace("-", "_"),
        aspect=aspect,
        font_scale=font_scale,
    )
    pal = _resolve_theme(theme)
    key = eff_layout if compose_mode == "fusion" else (
        (layout or DEFAULT_SCENE_LAYOUT).lower().replace("-", "_")
    )
    cfg = load_cfg()
    ffmpeg_bin = ensure_ffmpeg((cfg.get("paths") or {}).get("ffmpeg", "ffmpeg"))
    # Prefer PIL frames for speed in the picker; few frames, short intro.
    # Picker: CSS frames (same HTML as still preview). Export: official HF when available.
    return generate_scene_video(
        sample,
        output_path,
        duration_sec=max(1.0, min(float(duration_sec), 2.5)),
        layout=key,
        theme=pal,
        ffmpeg_bin=ffmpeg_bin,
        fps=8,
        aspect=aspect,
        prefer_pil=False,
        max_frames=7,
        style_pack={"font_scale": font_scale, "picker_preview": True, "compose_mode": compose_mode or "cover"},
    )


def _rgb_hex(rgb: tuple[int, int, int]) -> str:
    r, g, b = rgb
    return f"#{r:02x}{g:02x}{b:02x}"


def _resolve_theme(theme: str) -> dict:
    key = (theme or DEFAULT_CARD_THEME).lower().replace("-", "_")
    return CARD_THEMES.get(key, CARD_THEMES[DEFAULT_CARD_THEME])


def _load_font(size: int):
    from PIL import ImageFont

    for name in ("msyhbd.ttc", "msyh.ttc", "simhei.ttf"):
        win = Path("C:/Windows/Fonts") / name
        if win.exists():
            return ImageFont.truetype(str(win), size)
    return ImageFont.load_default()


def render_hyperframe_card(
    text: str,
    index: int,
    output_path: Path,
    *,
    theme: str = DEFAULT_CARD_THEME,
) -> Path:
    from PIL import Image, ImageDraw

    pal = _resolve_theme(theme)
    img = Image.new("RGB", (CARD_W, CARD_H))
    draw = ImageDraw.Draw(img)
    r1, g1, b1 = pal["top"]
    r2, g2, b2 = pal["bottom"]
    for y in range(CARD_H):
        t = y / max(CARD_H - 1, 1)
        color = (
            int(r1 * (1 - t) + r2 * t),
            int(g1 * (1 - t) + g2 * t),
            int(b1 * (1 - t) + b2 * t),
        )
        draw.line([(0, y), (CARD_W, y)], fill=color)

    ar, ag, ab = pal["accent_bar"]
    draw.rectangle((0, 0, CARD_W, 10), fill=(ar, ag, ab))

    font = _load_font(max(36, CARD_W // 18))
    lines = split_script_for_subtitles(text, max_chars=10) or [text]
    if len(lines) > 3:
        lines = lines[:3]
        lines[-1] = lines[-1][:9] + "…"

    line_h = font.size + 12
    block_h = len(lines) * line_h
    y0 = (CARD_H - block_h) // 2
    tr, tg, tb = pal["text"]
    sr, sg, sb = pal["shadow"]
    or_, og, ob = pal["outline"]
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        tw = bbox[2] - bbox[0]
        x = (CARD_W - tw) // 2
        y = y0 + i * line_h
        draw.text((x + 2, y + 2), line, font=font, fill=(sr, sg, sb))
        draw.text((x, y), line, font=font, fill=(tr, tg, tb))

    draw.rectangle((0, 0, CARD_W - 1, CARD_H - 1), outline=(or_, og, ob), width=3)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, quality=92)
    return output_path


def generate_card_image(
    text: str,
    output_path: Path,
    *,
    theme: str = DEFAULT_CARD_THEME,
) -> Path:
    text = (text or "").strip() or "文案卡片"
    return render_hyperframe_card(text, 0, output_path, theme=theme)


def generate_card_video(
    text: str,
    output_path: Path,
    *,
    duration_sec: float = 5.0,
    theme: str = DEFAULT_CARD_THEME,
    ffmpeg_bin: str = "ffmpeg",
) -> Path:
    work = output_path.parent / "hf_card_work"
    work.mkdir(parents=True, exist_ok=True)
    card = work / "card.png"
    generate_card_image(text, card, theme=theme)
    duration_sec = max(1.0, min(float(duration_sec), 120.0))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            ffmpeg_bin,
            "-y",
            "-loop",
            "1",
            "-i",
            str(card),
            "-t",
            f"{duration_sec:.3f}",
            "-vf",
            "scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p",
            "-r",
            "25",
            "-c:v",
            "libx264",
            "-crf",
            "20",
            "-an",
            str(output_path),
        ],
        check=True,
    )
    return output_path


def generate_hyperframes_video(
    script: str,
    duration: float,
    output_path: Path,
    *,
    pause_sec: float = 0.35,
    max_chars: int = 16,
    ffmpeg_bin: str = "ffmpeg",
    theme: str = DEFAULT_CARD_THEME,
    layout: str = "kinetic",
    aspect: str = "portrait_9_16",
) -> Path:
    cues = build_subtitle_cues(
        script,
        duration,
        pause_sec=pause_sec,
        max_chars=max_chars,
    )
    if not cues:
        lines = split_script_for_subtitles(script, max_chars=max_chars) or [
            (script[:20] or "…")
        ]
        seg = max(duration / max(len(lines), 1), 1.0)
        cues = [
            SubCue(i + 1, i * seg, (i + 1) * seg, t) for i, t in enumerate(lines)
        ]

    work = output_path.parent / "hyperframes_scenes"
    work.mkdir(parents=True, exist_ok=True)
    from workflow.hyperframes_scenes import DEFAULT_SCENE_LAYOUT, resolve_layout, generate_scene_video, render_scene_still

    meta = resolve_layout(layout)
    pal = _resolve_theme(theme)
    key = (layout or "kinetic").lower().replace("-", "_")
    segments: list[Path] = []

    for i, cue in enumerate(cues):
        seg = max(float(cue.end - cue.start), 0.8)
        if key == "card" or not meta.get("animated"):
            card = work / f"hf_{i:03d}.png"
            render_scene_still(cue.text, card, layout=key, theme=pal, aspect=aspect)
            clip = work / f"hf_{i:03d}.mp4"
            subprocess.run(
                [
                    ffmpeg_bin,
                    "-y",
                    "-loop",
                    "1",
                    "-i",
                    str(card),
                    "-t",
                    f"{seg:.3f}",
                    "-vf",
                    "scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p",
                    "-r",
                    "25",
                    "-c:v",
                    "libx264",
                    "-crf",
                    "20",
                    "-an",
                    str(clip),
                ],
                check=True,
            )
        else:
            clip = work / f"hf_{i:03d}.mp4"
            generate_scene_video(
                cue.text,
                clip,
                duration_sec=seg,
                layout=key,
                theme=pal,
                ffmpeg_bin=ffmpeg_bin,
                aspect=aspect,
            )
        segments.append(clip)

    list_path = work / "concat.txt"
    lines: list[str] = []
    for clip in segments:
        lines.append(f"file '{clip.resolve().as_posix()}'")
    list_path.write_text("\n".join(lines), encoding="utf-8")

    raw = work / "hyperframes_raw.mp4"
    subprocess.run(
        [
            ffmpeg_bin,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_path),
            "-vf",
            "fps=25,format=yuv420p",
            "-c:v",
            "libx264",
            "-crf",
            "20",
            str(raw),
        ],
        check=True,
    )

    subprocess.run(
        [
            ffmpeg_bin,
            "-y",
            "-stream_loop",
            "-1",
            "-i",
            str(raw),
            "-t",
            f"{duration:.3f}",
            "-vf",
            "scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p",
            "-c:v",
            "libx264",
            "-crf",
            "20",
            "-an",
            str(output_path),
        ],
        check=True,
    )
    return output_path


def _cue_field(cue, name: str, default=None):
    if hasattr(cue, name):
        return getattr(cue, name)
    if isinstance(cue, dict):
        return cue.get(name, default)
    return default


def _ends_sentence(text: str) -> bool:
    t = (text or "").rstrip()
    return bool(t) and t[-1] in "。！？….!?;；"


def _sort_cues_timeline(cues: list) -> list:
    return sorted(
        cues,
        key=lambda c: (
            float(_cue_field(c, "start", 0) or 0),
            int(_cue_field(c, "index", 0) or 0),
        ),
    )


def group_cues_contiguous(
    cues: list,
    *,
    max_gap: float = 1.25,
) -> list[list]:
    """Merge timeline-adjacent cues into islands (gap only).

    Used when the user explicitly selects a continuous timeline range so one
    spoken stretch ≈ one HyperFrames overlay (avoids multi-splice flicker).
    """
    groups: list[list] = []
    current: list = []
    for cue in _sort_cues_timeline(cues):
        text = str(_cue_field(cue, "text", "") or "").strip()
        if not text:
            continue
        start = float(_cue_field(cue, "start", 0) or 0)
        if not current:
            current = [cue]
            continue
        prev_end = float(_cue_field(current[-1], "end", 0) or 0)
        if start - prev_end <= max_gap:
            current.append(cue)
        else:
            groups.append(current)
            current = [cue]
    if current:
        groups.append(current)
    return groups


def group_cues_for_scenes(
    cues: list,
    *,
    max_group_sec: float = 8.0,
    max_gap: float = 0.85,
) -> list[list]:
    """Merge short adjacent subtitle fragments so one spoken sentence ≈ one scene."""
    groups: list[list] = []
    current: list = []
    for cue in _sort_cues_timeline(cues):
        text = str(_cue_field(cue, "text", "") or "").strip()
        if not text:
            continue
        start = float(_cue_field(cue, "start", 0) or 0)
        end = float(_cue_field(cue, "end", start + 1) or start + 1)
        if not current:
            current = [cue]
            continue
        prev = current[-1]
        prev_text = str(_cue_field(prev, "text", "") or "").strip()
        prev_end = float(_cue_field(prev, "end", 0) or 0)
        group_start = float(_cue_field(current[0], "start", 0) or 0)
        gap = start - prev_end
        projected = end - group_start
        if (
            gap <= max_gap
            and not _ends_sentence(prev_text)
            and projected <= max_group_sec
            and len(current) < 8
        ):
            current.append(cue)
        else:
            groups.append(current)
            current = [cue]
    if current:
        groups.append(current)
    return groups


def _join_cue_text(group: list) -> str:
    parts = [str(_cue_field(c, "text", "") or "").strip() for c in group]
    parts = [p for p in parts if p]
    if not parts:
        return ""
    # Chinese fragments join without spaces; keep space if Latin-heavy
    latin = sum(1 for p in parts for ch in p if ("a" <= ch.lower() <= "z"))
    if latin >= max(1, sum(len(p) for p in parts) // 3):
        return " ".join(parts)
    return "".join(parts)


def _cover_max_chars(
    aspect: str,
    font_scale: float,
    layout: str = "kinetic",
) -> int:
    from workflow.hyperframes_scenes import resolve_dimensions

    w, h = resolve_dimensions(layout, aspect)
    landscape = w > h
    fs = max(0.7, min(2.0, float(font_scale or 1.0)))
    base = 16 if landscape else 12
    return max(6, int(base / fs))


def _cover_beat_chunks(text: str, max_chars: int, *, max_beats: int = 5) -> list[str]:
    """Split long cover copy into timed beats so lines stay on screen."""
    raw = (text or "").strip()
    if not raw:
        return []
    parts = split_script_for_subtitles(raw, max_chars=max(6, int(max_chars))) or [raw]
    out: list[str] = []
    for p in parts:
        s = (p or "").strip()
        if not s:
            continue
        if len(s) <= max_chars + 4:
            out.append(s)
        else:
            for i in range(0, len(s), max_chars):
                chunk = s[i : i + max_chars].strip()
                if chunk:
                    out.append(chunk)
        if len(out) >= max_beats:
            break
    return out[:max_beats] or [raw[:max_chars]]


def _synthetic_phrase_windows(
    group: list,
    chunks: list[str],
) -> list[tuple[list, float, float, str]]:
    if not group or not chunks:
        return []
    start = float(_cue_field(group[0], "start", 0) or 0)
    end = float(_cue_field(group[-1], "end", start + 1) or start + 1)
    span = max(0.8, end - start)
    n = len(chunks)
    out: list[tuple[list, float, float, str]] = []
    for i, chunk in enumerate(chunks):
        t0 = start + (span * i / max(n, 1))
        t1 = start + (span * (i + 1) / max(n, 1))
        out.append((group, t0, max(t0 + 0.8, t1), chunk.strip()))
    return out


def _prepare_compose_display_text(
    text: str,
    *,
    compose_mode: str,
    layout: str = "kinetic",
    aspect: str = "portrait_9_16",
    font_scale: float = 1.0,
    use_llm: bool = False,
    cfg: dict | None = None,
) -> tuple[str, str]:
    """Shape on-screen copy: fusion → short glass card; cover → wrapped lines."""
    from workflow.glass_cards import (
        format_card_display_text,
        heuristic_card_from_text,
        llm_card_from_text,
    )
    from workflow.hyperframes_scenes import (
        _pick_fusion_layout,
        _split_lines,
        is_fusion_layout,
        resolve_dimensions,
    )

    raw = (text or "").strip()
    if not raw:
        return "…", layout or "kinetic"

    mode = (compose_mode or "").lower()
    if mode == "fusion" or is_fusion_layout(layout):
        if use_llm and cfg:
            card = llm_card_from_text(cfg, raw)
        else:
            card = heuristic_card_from_text(raw)
        display = format_card_display_text(card)
        eff = _pick_fusion_layout(display, layout)
        return display, eff

    w, h = resolve_dimensions(layout or "kinetic", aspect)
    landscape = w > h
    cap = _cover_max_chars(aspect, font_scale, layout)
    lines = _split_lines(raw, cap, landscape=landscape)
    return "\n".join(lines), layout or "kinetic"


def _phrase_windows(group: list) -> list[tuple[list, float, float, str]]:
    """Split a contiguous group into spoken phrases (smart) for on-screen text beats."""
    phrases = group_cues_for_scenes(group)
    if not phrases:
        phrases = [group]
    out: list[tuple[list, float, float, str]] = []
    for phrase in phrases:
        text = _join_cue_text(phrase)
        if not text:
            continue
        start = float(_cue_field(phrase[0], "start", 0) or 0)
        end = float(_cue_field(phrase[-1], "end", start + 1) or start + 1)
        out.append((phrase, start, max(start + 0.8, end), text))
    return out


def _ffmpeg_concat_videos(ffmpeg_bin: str, parts: list[Path], output: Path) -> Path:
    """Concat clips into one mp4 (filter_complex; Windows-safe)."""
    import shutil

    output.parent.mkdir(parents=True, exist_ok=True)
    if not parts:
        raise ValueError("no clips to concat")
    if len(parts) == 1:
        shutil.copy2(parts[0], output)
        return output
    inputs: list[str] = []
    for p in parts:
        inputs.extend(["-i", str(p)])
    n = len(parts)
    prep = "".join(
        f"[{i}:v]scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p,setsar=1,fps=8[v{i}];"
        for i in range(n)
    )
    concat = "".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[v]"
    subprocess.run(
        [
            ffmpeg_bin,
            "-y",
            *inputs,
            "-filter_complex",
            prep + concat,
            "-map",
            "[v]",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            str(output),
        ],
        check=True,
    )
    return output


def _phrase_beats_relative(
    phrases: list[tuple[list, float, float, str]],
    *,
    target_span: float,
) -> tuple[list[dict], float]:
    """Convert absolute phrase windows to composition-relative beats."""
    t0_abs = float(phrases[0][1])
    last_end = float(phrases[-1][2])
    total = max(0.8, float(target_span), last_end - t0_abs)
    beats: list[dict] = []
    for i, (_phrase, ps, pe, text) in enumerate(phrases):
        rel0 = max(0.0, float(ps) - t0_abs)
        if i + 1 < len(phrases):
            rel1 = max(rel0 + 0.8, float(phrases[i + 1][1]) - t0_abs)
        else:
            rel1 = max(rel0 + 0.8, float(pe) - t0_abs, total)
        beats.append({"t0": rel0, "t1": min(rel1, total + 0.01), "text": text})
    if beats:
        beats[-1]["t1"] = max(beats[-1]["t1"], total)
    return beats, total


def _render_progressive_scene_video(
    group: list,
    output_path: Path,
    *,
    layout: str,
    theme: dict,
    aspect: str,
    ffmpeg_bin: str,
    target_span: float,
    smart_style: bool = False,
    style_pack: dict | None = None,
) -> Path:
    """One overlay file for the whole window; text changes phrase-by-phrase with motion."""
    import logging

    from workflow.hyperframes_scenes import generate_scene_video, is_fusion_layout, resolve_dimensions

    log = logging.getLogger(__name__)
    phrases = _phrase_windows(group)
    if not phrases:
        raise ValueError("empty phrase windows")
    # If only one phrase of wall-text would jam, further split by individual cues
    if len(phrases) == 1 and len(group) > 1:
        phrases = []
        for cue in group:
            text = str(_cue_field(cue, "text", "") or "").strip()
            if not text:
                continue
            start = float(_cue_field(cue, "start", 0) or 0)
            end = float(_cue_field(cue, "end", start + 1) or start + 1)
            phrases.append(([cue], start, max(start + 0.8, end), text))

    use_layout = layout
    use_theme = theme
    compose_mode = str((style_pack or {}).get("compose_mode") or "").lower()
    fusion = is_fusion_layout(layout) or compose_mode == "fusion" or (
        style_pack
        and str(style_pack.get("bg_mode") or "").lower() in ("transparent", "none", "off")
    )
    compose_cover = compose_mode == "cover"
    smart_layout_flag = bool(
        (style_pack or {}).get("smart_layout")
        if (style_pack or {}).get("smart_layout") is not None
        else smart_style
    )
    if fusion and phrases:
        fs = float((style_pack or {}).get("font_scale") or 1.0)
        _, use_layout = _prepare_compose_display_text(
            phrases[0][3],
            compose_mode="fusion",
            layout=use_layout,
            aspect=aspect,
            font_scale=fs,
        )
    # Fusion: never let smart_style rewrite layout to kinetic/cover scenes
    if smart_layout_flag and phrases and not fusion and not compose_cover:
        sug = suggest_hyperframe_style(phrases[0][3], aspect=aspect)
        use_layout = sug["layout"]
        use_theme = _resolve_theme(sug["theme"])
    elif smart_style and phrases and fusion:
        sug = suggest_hyperframe_style(phrases[0][3], aspect=aspect)
        use_theme = _resolve_theme(sug["theme"])

    beats, total = _phrase_beats_relative(phrases, target_span=target_span)
    width, height = resolve_dimensions(use_layout, aspect)

    # Cover + picker use CSS HTML (matches modal preview). Official bridge layout drifts.
    try:
        from workflow.hf_official import is_available, render_scene_beats

        if (not fusion) and not compose_cover and is_available() and len(beats) >= 1:
            return render_scene_beats(
                beats,
                Path(output_path),
                layout=use_layout,
                theme=use_theme,
                duration_sec=total,
                width=width,
                height=height,
                style_pack=style_pack,
            )
    except Exception:
        log.exception("official multi-beat HyperFrames failed; falling back to concat")

    work = output_path.parent / f"{output_path.stem}_parts"
    work.mkdir(parents=True, exist_ok=True)
    parts: list[Path] = []
    for i, (_phrase, _ps, _pe, text) in enumerate(phrases):
        if i + 1 < len(phrases):
            dur = max(0.8, phrases[i + 1][1] - phrases[i][1])
        else:
            dur = max(0.8, phrases[i][2] - phrases[i][1])
        part = work / f"part_{i:02d}.mp4"
        part_layout, part_theme = use_layout, use_theme
        part_text = text
        if fusion:
            fs = float((style_pack or {}).get("font_scale") or 1.0)
            part_text, part_layout = _prepare_compose_display_text(
                text,
                compose_mode="fusion",
                layout=use_layout,
                aspect=aspect,
                font_scale=fs,
            )
        elif compose_cover:
            fs = float((style_pack or {}).get("font_scale") or 1.0)
            part_text, _ = _prepare_compose_display_text(
                text,
                compose_mode="cover",
                layout=use_layout,
                aspect=aspect,
                font_scale=fs,
            )
        if smart_layout_flag and not fusion and not compose_cover:
            sug = suggest_hyperframe_style(text, aspect=aspect)
            part_layout = sug["layout"]
            part_theme = _resolve_theme(sug["theme"])
        elif smart_style and fusion:
            sug = suggest_hyperframe_style(text, aspect=aspect)
            part_theme = _resolve_theme(sug["theme"])
        part_motion = None
        if fusion:
            part_motion = suggest_fusion_motion(text, index=i).get("motion")
        generate_scene_video(
            part_text,
            part,
            duration_sec=min(dur, 30.0),
            layout=part_layout,
            theme=part_theme,
            ffmpeg_bin=ffmpeg_bin,
            aspect=aspect,
            fps=8,
            prefer_pil=False,
            max_frames=10,
            style_pack=style_pack,
            motion=part_motion,
            motion_index=i,
        )
        parts.append(part)

    _ffmpeg_concat_videos(ffmpeg_bin, parts, output_path)
    return output_path

def _relative_caption_cues(group: list, *, duration_sec: float) -> list[dict]:
    """Cue windows relative to group start, for Remotion caption bar timing."""
    if not group:
        return []
    t0 = float(_cue_field(group[0], "start", 0) or 0)
    out: list[dict] = []
    for cue in group:
        text = str(_cue_field(cue, "text", "") or "").strip()
        if not text:
            continue
        start = max(0.0, float(_cue_field(cue, "start", 0) or 0) - t0)
        end = max(start + 0.4, float(_cue_field(cue, "end", start + 1) or start + 1) - t0)
        out.append({"start": start, "end": min(end, duration_sec + 0.05), "text": text})
    if out:
        out[-1]["end"] = max(out[-1]["end"], duration_sec)
    return out


def generate_glass_card_assets(
    cards: list[dict],
    work_dir: Path,
    *,
    theme: str = DEFAULT_CARD_THEME,
    aspect: str = "portrait_9_16",
    ffmpeg_bin: str = "ffmpeg",
    default_position: str = "top_right",
    default_scale: float = 0.42,
) -> list[dict]:
    """Render structured glass cards (title+bullets) for short-mode PiP overlay."""
    from workflow.glass_cards import format_card_display_text, normalize_position
    from workflow.hyperframes_scenes import generate_scene_video, render_scene_still

    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    pal = _resolve_theme(theme)
    out: list[dict] = []
    for i, card in enumerate(cards or []):
        if not isinstance(card, dict):
            continue
        indices = [int(x) for x in (card.get("cue_indices") or []) if int(x) > 0]
        start = float(card.get("start") or 0)
        end = float(card.get("end") or start + 1.5)
        if end <= start:
            end = start + 1.5
        display = format_card_display_text(card)
        if not display.strip():
            continue
        span = max(0.8, end - start)
        stem = f"glass_{indices[0] if indices else i:03d}_{i:02d}"
        clip = work_dir / f"{stem}.mp4"
        try:
            generate_scene_video(
                display,
                clip,
                duration_sec=min(span, 12.0),
                layout="text_card",
                theme=pal,
                ffmpeg_bin=ffmpeg_bin,
                aspect=aspect,
                fps=8,
                prefer_pil=True,
                max_frames=8,
            )
            media = str(clip.resolve())
        except Exception:
            still = work_dir / f"{stem}.png"
            render_scene_still(display, still, layout="text_card", theme=pal, aspect=aspect)
            media = str(still.resolve())
        pos = normalize_position(card.get("position") or default_position)
        if pos == "auto":
            pos = default_position if default_position != "auto" else "top_right"
        scale = float(card.get("scale") or default_scale or 0.42)
        out.append(
            {
                "cue_indices": indices,
                "start": start,
                "end": end,
                "media_path": media,
                "display_duration_sec": span,
                "auto_hyperframe": True,
                "scene_layout": "text_card",
                "scene_aspect": aspect,
                "position": pos,
                "scale": max(0.22, min(0.72, scale)),
                "title": card.get("title"),
                "bullets": card.get("bullets") or [],
            }
        )
    return out


def generate_cue_scene_assets(
    cues: list,
    work_dir: Path,
    *,
    theme: str = DEFAULT_CARD_THEME,
    layout: str = "kinetic",
    aspect: str = "portrait_9_16",
    skip_indices: set[int] | None = None,
    target_indices: set[int] | None = None,
    smart_merge: bool = True,
    force_contiguous: bool = False,
    smart_style: bool = False,
    remotion_captions: bool = False,
    style_pack: dict | None = None,
    ffmpeg_bin: str = "ffmpeg",
    text_overrides: dict[int, str] | None = None,
) -> list[dict]:
    """Generate HyperFrames scenes.

    Grouping:
    - force_contiguous: one overlay job per timeline island (timing), text still
      phrase-beat inside the video (not all cues dumped on one static frame)
    - smart_merge: sentence-aware soft merge
    - else: one scene per cue
    - smart_style: per-phrase theme/layout suggestion (keyword color + bg always on)
    - remotion_captions: optional Remotion bottom caption bar overlay
    - style_pack: unified Scene Style Pack (font / bg / remotion theme)
    """
    import logging

    from workflow.hyperframes_scenes import (
        DEFAULT_SCENE_LAYOUT,
        is_fusion_layout,
        normalize_layout_key,
        resolve_dimensions,
        resolve_layout,
        resolve_scene_aspect,
        _pick_fusion_layout,
        generate_scene_video,
        render_scene_still,
    )
    from workflow.scene_style_pack import ensure_extra_layouts_registered, normalize_style_pack

    ensure_extra_layouts_registered()
    log = logging.getLogger(__name__)
    skip = skip_indices or set()
    target = target_indices
    work_dir.mkdir(parents=True, exist_ok=True)
    pack = normalize_style_pack(
        {
            "theme": theme,
            "layout": layout,
            "aspect": aspect,
            **(style_pack or {}),
        }
    )
    theme = pack["theme"]
    layout = pack["layout"]
    aspect = pack["aspect"]
    compose_mode = str((style_pack or {}).get("compose_mode") or pack.get("compose_mode") or "").lower()
    if compose_mode not in ("fusion", "cover"):
        compose_mode = "fusion" if is_fusion_layout(layout) else "cover"
    smart_layout_flag = bool(
        pack.get("smart_layout") if pack.get("smart_layout") is not None else smart_style
    )
    smart_theme_flag = bool(
        pack.get("smart_theme") if pack.get("smart_theme") is not None else smart_style
    )
    # Fusion styles must not be rewritten to kinetic by smart_style
    allow_smart_layout = (
        smart_layout_flag and compose_mode != "fusion" and not is_fusion_layout(layout)
    )
    # Seed theme/layout: if smart_style and empty filter later, still need defaults
    seed_text = ""
    for cue in cues:
        idx = int(_cue_field(cue, "index", 0) or 0)
        if target is not None and idx not in target:
            continue
        seed_text += str(_cue_field(cue, "text", "") or "")
        if len(seed_text) > 80:
            break
    if allow_smart_layout and seed_text.strip():
        sug0 = suggest_hyperframe_style(seed_text, aspect=aspect)
        theme = sug0["theme"]
        layout = sug0["layout"]
        if compose_mode == "cover" and is_fusion_layout(layout):
            layout = "kinetic"
        if compose_mode != "cover":
            pack = normalize_style_pack({**pack, "theme": theme, "layout": layout})
        else:
            pack = normalize_style_pack({**pack, "theme": theme})
        if compose_mode not in ("fusion", "cover"):
            compose_mode = "fusion" if is_fusion_layout(layout) else "cover"
    elif smart_theme_flag and seed_text.strip():
        sug0 = suggest_hyperframe_style(seed_text, aspect=aspect)
        theme = _resolve_theme(sug0["theme"])
        pack = normalize_style_pack({**pack, "theme": sug0["theme"]})
    elif smart_style and compose_mode == "fusion" and seed_text.strip():
        # Theme only
        sug0 = suggest_hyperframe_style(seed_text, aspect=aspect)
        theme = sug0["theme"]
        pack = normalize_style_pack({**pack, "theme": theme, "layout": layout})
    if compose_mode == "cover" and is_fusion_layout(layout):
        layout = "kinetic"
        pack = normalize_style_pack({**pack, "layout": layout})
    if compose_mode == "fusion":
        layout = _pick_fusion_layout("", pack.get("layout"))
        pack = normalize_style_pack({**pack, "layout": layout, "bg_mode": "transparent"})
    pal = _resolve_theme(theme)
    want_remotion = False  # Remotion captions belong to publish burn-in, not scene cards

    meta = resolve_layout(layout)
    key = (layout or DEFAULT_SCENE_LAYOUT).lower().replace("-", "_")
    render_key = normalize_layout_key(key)
    animated = bool(meta.get("animated")) and render_key != "card"
    fusion_pos = str((style_pack or {}).get("fusion_position") or "top_right")
    fusion_scale = float((style_pack or {}).get("fusion_scale") or 0.42)

    filtered = []
    for cue in cues:
        idx = int(_cue_field(cue, "index", 0) or 0)
        if idx <= 0 or idx in skip:
            continue
        if target is not None and idx not in target:
            continue
        text = str(_cue_field(cue, "text", "") or "").strip()
        if not text:
            continue
        filtered.append(cue)

    if force_contiguous:
        groups = group_cues_contiguous(filtered)
    elif smart_merge:
        groups = group_cues_for_scenes(filtered)
    else:
        groups = [[c] for c in _sort_cues_timeline(filtered)]
    out: list[dict] = []
    for gi, group in enumerate(groups):
        indices = [int(_cue_field(c, "index", 0) or 0) for c in group]
        if not indices:
            continue
        start = float(_cue_field(group[0], "start", 0) or 0)
        end = float(_cue_field(group[-1], "end", start + 1) or start + 1)
        span = max(0.8, end - start)
        clip_dur = max(1.0, min(span, 120.0))
        stem = f"hf_grp_{indices[0]:03d}_{indices[-1]:03d}_{gi:02d}"
        # Still / single-phrase: use first smart phrase only (never dump whole island text)
        phrases = _phrase_windows(group)
        lead_text = phrases[0][3] if phrases else _join_cue_text(group)
        if text_overrides:
            for idx in indices:
                ov = text_overrides.get(int(idx))
                if ov and str(ov).strip():
                    lead_text = str(ov).strip()
                    break
        if not lead_text:
            continue

        font_scale = float(pack.get("font_scale") or 1.0)
        display_text, eff_layout = _prepare_compose_display_text(
            lead_text,
            compose_mode=compose_mode,
            layout=key,
            aspect=aspect,
            font_scale=font_scale,
        )
        compact_len = len(lead_text.replace("\n", "").replace(" ", ""))
        if compose_mode == "cover" and len(phrases) == 1 and compact_len > 22:
            cap = _cover_max_chars(aspect, font_scale, key)
            chunks = _cover_beat_chunks(lead_text, cap)
            if len(chunks) > 1:
                phrases = _synthetic_phrase_windows(group, chunks)

        try:
            if not animated:
                card = work_dir / f"{stem}.png"
                render_scene_still(
                    display_text,
                    card,
                    layout=eff_layout if compose_mode == "fusion" else key,
                    theme=pal,
                    aspect=aspect,
                    font_scale=font_scale,
                )
                out.append(
                    {
                        "cue_indices": indices,
                        "start": start,
                        "end": end,
                        "media_path": str(card.resolve()),
                        "display_duration_sec": span,
                        "auto_hyperframe": True,
                        "scene_layout": key,
                        "scene_aspect": aspect,
                    }
                )
            else:
                clip = work_dir / f"{stem}.mp4"
                need_progressive = (
                    len(group) > 1
                    or len(phrases) > 1
                    or (compose_mode == "cover" and compact_len > 22)
                    or (compose_mode == "fusion" and compact_len > 18)
                )
                if need_progressive:
                    _render_progressive_scene_video(
                        group,
                        clip,
                        layout=eff_layout if compose_mode == "fusion" else key,
                        theme=pal,
                        aspect=aspect,
                        ffmpeg_bin=ffmpeg_bin,
                        target_span=clip_dur,
                        smart_style=allow_smart_layout,
                        style_pack=pack,
                    )
                else:
                    use_layout, use_theme = key, pal
                    if compose_mode == "fusion":
                        use_layout = eff_layout
                    if allow_smart_layout and compose_mode != "cover":
                        sug = suggest_hyperframe_style(lead_text, aspect=aspect)
                        use_layout = sug["layout"]
                        if is_fusion_layout(use_layout):
                            use_layout = "kinetic"
                        use_theme = _resolve_theme(sug["theme"])
                    elif smart_theme_flag:
                        sug = suggest_hyperframe_style(lead_text, aspect=aspect)
                        use_theme = _resolve_theme(sug["theme"])
                        use_layout = key
                    elif smart_style and compose_mode == "fusion":
                        sug = suggest_hyperframe_style(display_text, aspect=aspect)
                        use_theme = _resolve_theme(sug["theme"])
                        use_layout = _pick_fusion_layout(
                            display_text, pack.get("layout") or sug.get("layout")
                        )
                    cue_motion = None
                    if compose_mode == "fusion" or is_fusion_layout(use_layout):
                        cue_motion = suggest_fusion_motion(
                            display_text, index=indices[0] + gi
                        ).get("motion")
                    generate_scene_video(
                        display_text,
                        clip,
                        duration_sec=clip_dur,
                        layout=use_layout,
                        theme=use_theme,
                        ffmpeg_bin=ffmpeg_bin,
                        aspect=aspect,
                        fps=8,
                        prefer_pil=False,
                        max_frames=10,
                        style_pack=pack,
                        motion=cue_motion,
                        motion_index=indices[0] + gi,
                    )
                if want_remotion:
                    try:
                        from workflow.remotion_captions import maybe_overlay_timed_captions

                        w, _h = resolve_dimensions(key, aspect)
                        accent = "#%02x%02x%02x" % tuple(int(x) for x in pal["accent_bar"][:3])
                        maybe_overlay_timed_captions(
                            clip,
                            _relative_caption_cues(group, duration_sec=clip_dur),
                            accent=accent,
                            duration_sec=clip_dur,
                            width=w,
                            ffmpeg_bin=ffmpeg_bin,
                            remotion_theme=str(pack.get("remotion_theme") or "bar"),
                        )
                    except Exception:
                        log.exception("Remotion overlay failed for cues %s", indices)
                out.append(
                    {
                        "cue_indices": indices,
                        "start": start,
                        "end": end,
                        "media_path": str(clip.resolve()),
                        "play_full_video": True,
                        "display_duration_sec": span,
                        "auto_hyperframe": True,
                        "scene_layout": key,
                        "scene_aspect": aspect,
                        "remotion_captions": bool(want_remotion),
                        "style_pack": {
                            "font_id": pack.get("font_id"),
                            "font_scale": pack.get("font_scale"),
                            "bg_mode": pack.get("bg_mode"),
                            "remotion_theme": pack.get("remotion_theme"),
                        },
                    }
                )
        except Exception:
            log.exception("HyperFrames scene failed for cues %s; trying single clip", indices)
            try:
                clip = work_dir / f"{stem}.mp4"
                generate_scene_video(
                    lead_text,
                    clip,
                    duration_sec=min(clip_dur, 8.0),
                    layout=key if animated else "kinetic",
                    theme=pal,
                    ffmpeg_bin=ffmpeg_bin,
                    aspect=aspect,
                    fps=8,
                    prefer_pil=True,
                    max_frames=10,
                    style_pack=pack,
                )
                out.append(
                    {
                        "cue_indices": indices,
                        "start": start,
                        "end": end,
                        "media_path": str(clip.resolve()),
                        "play_full_video": True,
                        "display_duration_sec": span,
                        "auto_hyperframe": True,
                        "scene_layout": key,
                        "scene_aspect": aspect,
                    }
                )
            except Exception:
                log.exception("HyperFrames fallback still for cues %s", indices)
                card = work_dir / f"{stem}.png"
                try:
                    render_scene_still(lead_text, card, layout=key, theme=pal, aspect=aspect)
                    out.append(
                        {
                            "cue_indices": indices,
                            "start": start,
                            "end": end,
                            "media_path": str(card.resolve()),
                            "display_duration_sec": span,
                            "auto_hyperframe": True,
                            "scene_layout": key,
                            "scene_aspect": aspect,
                        }
                    )
                except Exception:
                    continue
    for item in out:
        item["compose_mode"] = compose_mode
        item["content_style"] = key
        if compose_mode == "fusion":
            # Full-canvas transparent overlay — do not store PiP shrink scale
            item["position"] = "fullscreen"
            item["scale"] = 1.0
            item["fusion_anchor"] = fusion_pos if fusion_pos != "fullscreen" else "top_right"
        else:
            item.setdefault("position", "fullscreen")
            item.setdefault("scale", 1.0)
    return out


def restyle_cue_scene_assets(
    cues: list,
    assignments: list[dict],
    work_dir: Path,
    *,
    style_pack: dict | None = None,
    theme: str | None = None,
    layout: str | None = None,
    aspect: str | None = None,
    remotion_captions: bool = True,
    smart_style: bool = False,
    ffmpeg_bin: str = "ffmpeg",
) -> list[dict]:
    """Re-render existing auto HyperFrames assignments with a new Style Pack (keep cue timing)."""
    from workflow.scene_style_pack import normalize_style_pack

    pack = normalize_style_pack(
        {
            "theme": theme or "tokyo_night",
            "layout": layout or "kinetic",
            "aspect": aspect or "portrait_9_16",
            **(style_pack or {}),
        }
    )
    target: set[int] = set()
    for a in assignments:
        if not a.get("auto_hyperframe", True):
            continue
        for i in a.get("cue_indices") or []:
            try:
                target.add(int(i))
            except (TypeError, ValueError):
                continue
    if not target:
        return []
    return generate_cue_scene_assets(
        cues,
        work_dir,
        theme=pack["theme"],
        layout=pack["layout"],
        aspect=pack["aspect"],
        target_indices=target,
        smart_merge=True,
        force_contiguous=True,
        smart_style=smart_style,
        remotion_captions=remotion_captions,
        style_pack=pack,
        ffmpeg_bin=ffmpeg_bin,
    )


def generate_cue_card_assets(
    cues: list,
    work_dir: Path,
    *,
    theme: str = DEFAULT_CARD_THEME,
    layout: str = "kinetic",
    aspect: str = "portrait_9_16",
    skip_indices: set[int] | None = None,
    ffmpeg_bin: str = "ffmpeg",
) -> list[dict]:
    """Backward-compatible alias — now supports scene layouts, not only cards."""
    return generate_cue_scene_assets(
        cues,
        work_dir,
        theme=theme,
        layout=layout,
        aspect=aspect,
        skip_indices=skip_indices,
        ffmpeg_bin=ffmpeg_bin,
    )

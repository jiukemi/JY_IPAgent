"""Stage 3: subtitles, cover frame, cover templates, publish mux."""

from __future__ import annotations

import logging
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

FINAL_VIDEO_CANDIDATES = (
    "final_publish.mp4",
    "final_lipsync.mp4",
    "real_lipsync.mp4",
    "digital_lipsync.mp4",
    "latentsync_raw.mp4",
    "sadtalker_raw.mp4",
    "video_25fps.mp4",
)

LIPSYNC_VIDEO_CANDIDATES = (
    "final_lipsync.mp4",
    "real_lipsync.mp4",
    "digital_lipsync.mp4",
    "latentsync_raw.mp4",
    "sadtalker_raw.mp4",
    "video_25fps.mp4",
)

_INPUT_VIDEO_EXTS = (".mp4", ".mov", ".webm", ".mkv", ".m4v", ".avi")

SENTENCE_SPLIT = re.compile(r"(?<=[。！？；!?;])\s*|[\r\n]+")
CLAUSE_SPLIT = re.compile(r"(?<=[，,、])\s*")

SUBTITLE_STYLES: dict[str, str] = {
    "bottom_clean": (
        "FontName=Microsoft YaHei,FontSize=26,Bold=-1,PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H80000000,Outline=1,Shadow=0,MarginV=52,Alignment=2"
    ),
    "bottom_white": (
        "FontName=Microsoft YaHei,FontSize=26,Bold=-1,PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H80000000,Outline=2,Shadow=1,MarginV=52,Alignment=2"
    ),
    "bottom_yellow": (
        "FontName=Microsoft YaHei,FontSize=26,Bold=-1,PrimaryColour=&H0000FFFF,"
        "OutlineColour=&H80000000,Outline=1,Shadow=0,MarginV=52,Alignment=2"
    ),
    "top_tag": (
        "FontName=Microsoft YaHei,FontSize=22,Bold=-1,PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H80000000,Outline=1,Shadow=0,MarginV=28,Alignment=8"
    ),
}


def probe_video_dimensions(probe_bin: str, path: Path) -> tuple[int, int]:
    from workflow.pip_overlay import _video_size

    try:
        w, h = _video_size(probe_bin, path)
        return max(w, 1), max(h, 1)
    except Exception:
        return 1080, 1920


def ass_font_size_from_ui(ui_size: int, video_width: int, video_height: int) -> int:
    """Map CapCut-like UI size (min≈5) to ASS FontSize when PlayRes == video pixels.

    Must be paired with an .ass that sets PlayResX/Y to the video size; otherwise
    libass scales FontSize from the default 384x288 and text looks huge vs preview.
    """
    ui = max(5, min(48, int(ui_size)))
    short = float(min(max(video_width, 1), max(video_height, 1)))
    # CapCut-ish: UI5≈1.8% short edge, UI8≈2.4%, UI16≈4.0%
    pct = 0.018 + (ui - 5) * 0.002
    return max(14, min(int(short * 0.08), int(round(short * pct))))


def max_chars_per_line(
    ui_font: int,
    video_width: int = 1080,
    *,
    video_height: int | None = None,
    max_lines: int = 2,
) -> int:
    """Estimate CJK chars per line from the same pixel FontSize used for burn/preview."""
    h = int(video_height) if video_height else max(video_width, 1080)
    px = ass_font_size_from_ui(ui_font, video_width, h)
    margin_lr = max(24, int(video_width * 0.06))
    usable = max(120, video_width - 2 * margin_lr)
    char_w = max(px * 0.92, 12.0)
    per_line = int(usable / char_w)
    return max(4, min(28, per_line))


def max_chars_per_cue(
    ui_font: int,
    video_width: int,
    video_height: int,
    *,
    max_lines: int = 2,
) -> int:
    """Max characters that fit on screen for one timeline cue (all lines)."""
    return max(8, max_chars_per_line(ui_font, video_width, video_height=video_height, max_lines=max_lines) * max_lines)


def resolve_subtitle_split_chars(
    ui_font: int,
    video_width: int,
    video_height: int,
    *,
    config_max: int = 18,
    max_lines: int = 1,
) -> int:
    """Pick ASR/TTS cue unit length from font size — large font → shorter cues."""
    per_line = max_chars_per_line(ui_font, video_width, video_height=video_height, max_lines=max_lines)
    return max(6, min(int(config_max or 18), per_line))


def split_cue_for_display(cue: SubCue, max_unit_chars: int) -> list[SubCue]:
    """Split an over-long cue into shorter units; preserve timing inside the original window."""
    text = (cue.text or "").strip()
    flat = re.sub(r"\s*\n\s*", "", text)
    max_unit_chars = max(4, int(max_unit_chars))
    if len(flat) <= max_unit_chars:
        return [cue]

    parts = split_script_for_subtitles(flat, max_chars=max_unit_chars)
    if len(parts) <= 1:
        parts = _chunk_line(flat, max_unit_chars)
    if len(parts) <= 1:
        return [cue]

    start = float(cue.start)
    end = float(cue.end)
    dur = max(0.22, end - start)
    weights = [max(1, len(_norm_timing_text(p)) or len(p.strip()) or 1) for p in parts]
    total_w = float(sum(weights))
    out: list[SubCue] = []
    t = start
    for i, part in enumerate(parts):
        seg = dur * weights[i] / total_w
        seg = max(0.12, seg)
        part_end = end if i == len(parts) - 1 else min(end, t + seg)
        if part_end <= t:
            part_end = min(end, t + 0.12)
        out.append(SubCue(0, round(t, 3), round(part_end, 3), part.strip()))
        t = part_end
    if out:
        out[-1] = SubCue(out[-1].index, out[-1].start, round(end, 3), out[-1].text)
    return out


def subtitle_text_for_preview(
    text: str,
    *,
    start: float,
    end: float,
    time_sec: float,
    ui_font: int,
    width: int,
    height: int,
    max_lines: int = 2,
) -> str:
    """Split/wrap like final burn; pick the sub-cue active at preview time."""
    cue = SubCue(1, float(start), float(end), (text or "").strip())
    if not cue.text:
        return ""
    prepared = prepare_burn_cues(
        [cue],
        ui_font_size=ui_font,
        video_width=width,
        video_height=height,
        max_lines=max_lines,
    )
    t = float(time_sec)
    for c in prepared:
        if c.start - 0.02 <= t <= c.end + 0.02:
            return c.text
    return prepared[0].text if prepared else cue.text


def wrap_cue_text(text: str, max_chars: int, max_lines: int = 2) -> str:
    """Soft-wrap ONE cue for display (\\N). Does not create new timeline entries."""
    text = (text or "").strip().replace("\r\n", "\n")
    if not text:
        return text
    # Flatten accidental multi-line from editor into one phrase first
    flat = re.sub(r"\s*\n\s*", "", text) if "\n" in text else text
    if len(flat) <= max_chars:
        return flat

    # Prefer break after punctuation near the middle
    target = min(max_chars, max(6, (len(flat) + 1) // 2))
    best = -1
    for i, ch in enumerate(flat):
        if ch in "，,、；;：: ":
            if abs(i + 1 - target) < abs(best - target) or best < 0:
                if 4 <= i + 1 <= len(flat) - 2:
                    best = i + 1
    if best > 0 and max_lines >= 2:
        left, right = flat[:best].strip(), flat[best:].strip()
        if len(right) > max_chars and max_lines >= 2:
            right = wrap_cue_text(right, max_chars, max_lines=1)
        return f"{left}\n{right}" if right else left

    # Hard chunk as last resort (keep at most max_lines)
    chunks = _chunk_line(flat, max_chars)
    if len(chunks) <= max_lines:
        return "\n".join(chunks)
    head = chunks[: max_lines - 1]
    tail = "".join(chunks[max_lines - 1 :])
    if len(tail) > max_chars:
        tail = tail[: max(1, max_chars - 1)] + "…"
    return "\n".join(head + [tail])


def prepare_burn_cues(
    cues: list[SubCue],
    *,
    ui_font_size: int,
    video_width: int,
    video_height: int,
    max_lines: int = 2,
) -> list[SubCue]:
    per_line = max_chars_per_line(
        ui_font_size, video_width, video_height=video_height, max_lines=max_lines
    )
    max_unit = max_chars_per_cue(
        ui_font_size, video_width, video_height, max_lines=max_lines
    )
    expanded: list[SubCue] = []
    for c in cues:
        flat = re.sub(r"\s*\n\s*", "", (c.text or "").strip())
        if len(flat) <= max_unit:
            expanded.append(c)
        else:
            expanded.extend(split_cue_for_display(c, max(4, per_line)))

    out: list[SubCue] = []
    for i, c in enumerate(expanded):
        wrapped = wrap_cue_text(c.text, per_line, max_lines)
        out.append(SubCue(i + 1, c.start, c.end, wrapped))
    return out


def _hex_to_ass_primary(hex_color: str) -> str:
    """#RRGGBB → ASS PrimaryColour &H00BBGGRR."""
    raw = (hex_color or "#FFFFFF").strip().lstrip("#")
    if len(raw) != 6:
        return "&H00FFFFFF"
    r, g, b = int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)
    return f"&H00{b:02X}{g:02X}{r:02X}"


def build_subtitle_force_style(
    *,
    font_size: int = 18,
    color_hex: str = "#FFFFFF",
    outline: int = 1,
    shadow: int = 0,
    position: str = "bottom",
    video_width: int = 1080,
    video_height: int = 1920,
) -> str:
    primary = _hex_to_ass_primary(color_hex)
    pos = (position or "bottom").strip().lower()
    if pos in ("side_right", "right"):
        align = 6
        margin_l = max(24, int(video_width * 0.42))
        margin_r = max(28, int(video_width * 0.04))
        margin_v = max(40, int(video_height * 0.28))
    elif pos in ("side_left", "left"):
        align = 4
        margin_l = max(28, int(video_width * 0.04))
        margin_r = max(24, int(video_width * 0.42))
        margin_v = max(40, int(video_height * 0.28))
    elif pos == "top":
        align = 8
        margin_l = margin_r = max(32, int(video_width * 0.07))
        margin_v = max(20, int(video_height * 0.025))
    else:
        align = 2
        margin_l = margin_r = max(32, int(video_width * 0.07))
        margin_v = max(36, int(video_height * 0.045))
    outline = max(0, min(int(outline), 4))
    shadow = max(0, min(int(shadow), 4))
    return (
        f"FontName=Microsoft YaHei,FontSize={int(font_size)},PrimaryColour={primary},"
        f"BackColour=&H00000000,BorderStyle=1,Bold=-1,"
        f"OutlineColour=&H80000000,Outline={outline},Shadow={shadow},"
        f"MarginL={margin_l},MarginR={margin_r},MarginV={margin_v},"
        f"Alignment={align},WrapStyle=2,ScaleX=100,ScaleY=100"
    )


def subtitle_style_string(
    style_key: str,
    *,
    font_size: int | None = None,
    color_hex: str | None = None,
    outline: int | None = None,
    shadow: int | None = None,
    position: str | None = None,
    video_width: int = 1080,
    video_height: int = 1920,
) -> str:
    pos = position if position is not None else ("top" if style_key == "top_tag" else "bottom")
    ui_font = int(font_size) if font_size and font_size > 0 else 8
    ass_font = ass_font_size_from_ui(ui_font, video_width, video_height)

    if (
        font_size is not None
        or color_hex is not None
        or outline is not None
        or shadow is not None
        or position is not None
    ):
        return build_subtitle_force_style(
            font_size=ass_font,
            color_hex=color_hex or "#FFFFFF",
            outline=outline if outline is not None else 1,
            shadow=shadow if shadow is not None else 0,
            position=pos,
            video_width=video_width,
            video_height=video_height,
        )
    base = SUBTITLE_STYLES.get(style_key, SUBTITLE_STYLES["bottom_clean"])
    preset_ui = 10 if style_key == "top_tag" else 8
    preset_ass = ass_font_size_from_ui(preset_ui, video_width, video_height)
    styled = re.sub(r"FontSize=\d+", f"FontSize={preset_ass}", base)
    margin_lr = max(32, int(video_width * 0.07))
    if "MarginL=" not in styled:
        styled = styled.replace(
            "Alignment=",
            f"MarginL={margin_lr},MarginR={margin_lr},WrapStyle=2,Alignment=",
        )
    return styled


@dataclass
class SubCue:
    index: int
    start: float
    end: float
    text: str


def resolve_lipsync_video(session_dir: Path) -> Path | None:
    """口播/对口型成片（不含已烧录字幕的 final_publish.mp4）。

    Prefers the user-selected take (including lipsync_takes/), else newest canonical.
    """
    if not session_dir.is_dir():
        return None
    try:
        from workflow.session import resolve_selected_lipsync_path

        selected = resolve_selected_lipsync_path(session_dir)
        if selected:
            sp = Path(selected)
            if sp.is_file() and sp.stat().st_size > 0:
                return sp
    except Exception:
        pass
    cands = [
        session_dir / name
        for name in LIPSYNC_VIDEO_CANDIDATES
        if (session_dir / name).is_file() and (session_dir / name).stat().st_size > 0
    ]
    if cands:
        return max(cands, key=lambda p: p.stat().st_mtime)
    for ext in _INPUT_VIDEO_EXTS:
        p = session_dir / f"input_video{ext}"
        if p.is_file() and p.stat().st_size > 0:
            return p
    mp4s = [
        p
        for p in session_dir.glob("*.mp4")
        if p.is_file()
        and p.stat().st_size > 0
        and p.parent == session_dir
        and p.name != "final_publish.mp4"
    ]
    if mp4s:
        return max(mp4s, key=lambda p: p.stat().st_mtime)
    return None


def resolve_session_video(session_dir: Path) -> Path | None:
    """发布烧录优先对口型原片，避免对已发布成片二次烧字幕。"""
    lipsync = resolve_lipsync_video(session_dir)
    if lipsync is not None:
        return lipsync
    if not session_dir.is_dir():
        return None
    for name in FINAL_VIDEO_CANDIDATES:
        p = session_dir / name
        if p.is_file() and p.stat().st_size > 0:
            return p
    for ext in _INPUT_VIDEO_EXTS:
        p = session_dir / f"input_video{ext}"
        if p.is_file() and p.stat().st_size > 0:
            return p
    mp4s = [
        p
        for p in session_dir.glob("*.mp4")
        if p.is_file() and p.stat().st_size > 0 and p.parent == session_dir
    ]
    if mp4s:
        return max(mp4s, key=lambda p: p.stat().st_mtime)
    return None


def make_placeholder_cover_frame(
    output_path: Path,
    width: int = 1080,
    height: int = 1920,
    *,
    hint: str | None = "封面模板预览",
) -> Path:
    """9:16 placeholder when lipsync video is not ready."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)
    for y in range(height):
        t = y / max(height - 1, 1)
        r = int(30 * (1 - t) + 15 * t)
        g = int(41 * (1 - t) + 23 * t)
        b = int(59 * (1 - t) + 42 * t)
        draw.line([(0, y), (width, y)], fill=(r, g, b))
    if hint:
        font = _load_font(max(32, width // 16))
        bbox = draw.textbbox((0, 0), hint, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(
            ((width - tw) // 2, (height - th) // 2),
            hint,
            font=font,
            fill=(148, 163, 184),
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, quality=90)
    return output_path


def resolve_session_dub_audio(session_dir: Path) -> Path | None:
    from workflow.session import resolve_selected_dub_path

    selected = resolve_selected_dub_path(session_dir)
    if selected and Path(selected).is_file():
        return Path(selected)
    fallback = session_dir / "dubbing_16k.wav"
    if fallback.is_file():
        return fallback
    return None


def resolve_timing_duration(session_dir: Path, video: Path, probe_bin: str) -> tuple[float, str]:
    """Use dubbing audio length for subtitle alignment when available."""
    dub = resolve_session_dub_audio(session_dir)
    if dub is not None:
        dur = media_duration(probe_bin, dub)
        return dur, f"配音时长 {dur:.1f}s"
    dur = media_duration(probe_bin, video)
    return dur, f"视频时长 {dur:.1f}s"


def load_session_script(session_dir: Path) -> str:
    script_p = session_dir / "script.txt"
    if script_p.exists():
        return script_p.read_text(encoding="utf-8").strip()
    return ""


def default_title_from_script(script: str, max_len: int = 18) -> str:
    text = script.strip()
    if not text:
        return "未命名"
    first = SENTENCE_SPLIT.split(text, maxsplit=1)[0].strip()
    first = first or text
    first = re.sub(r"\s+", "", first)
    if len(first) <= max_len:
        return first
    return first[: max_len - 1] + "…"


def _chunk_line(text: str, max_chars: int) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    parts: list[str] = []
    buf = ""
    for ch in text:
        buf += ch
        if len(buf) >= max_chars:
            parts.append(buf)
            buf = ""
    if buf:
        parts.append(buf)
    return parts


def _ends_hard(text: str) -> bool:
    t = (text or "").rstrip()
    return bool(t) and t[-1] in "。！？….!?"


def _ends_soft(text: str) -> bool:
    t = (text or "").rstrip()
    return bool(t) and t[-1] in "，,、；;：:"


def _coalesce_cue_units(parts: list[str], *, min_chars: int = 4, max_chars: int = 14) -> list[str]:
    """Fold only tiny scraps; keep phrase-level cues (finer than sentence-long blocks)."""
    punct_only = re.compile(r"^[\s，,、。！？!?；;：:·…/\-—_~]+$")
    cleaned: list[str] = []
    for part in parts:
        part = (part or "").strip()
        if not part:
            continue
        if punct_only.match(part):
            if cleaned:
                cleaned[-1] = cleaned[-1] + part
            continue
        cleaned.append(part)

    merged: list[str] = []
    for part in cleaned:
        if not merged:
            merged.append(part)
            continue
        # Only absorb scraps shorter than min_chars (avoid gluing whole clauses)
        if len(part) < min_chars:
            if len(merged[-1]) + len(part) <= max_chars:
                merged[-1] = merged[-1] + part
                continue
        if len(merged[-1]) < min_chars and len(merged[-1]) + len(part) <= max_chars:
            merged[-1] = merged[-1] + part
            continue
        if len(part) > max_chars * 1.8:
            for chunk in _chunk_line(part, max_chars):
                if merged and len(chunk) < min_chars and len(merged[-1]) + len(chunk) <= max_chars:
                    merged[-1] = merged[-1] + chunk
                else:
                    merged.append(chunk)
            continue
        merged.append(part)

    if len(merged) >= 2 and len(merged[-1]) < min_chars:
        merged[-2] = merged[-2] + merged[-1]
        merged.pop()
    return [m for m in merged if m.strip()]


def split_script_for_subtitles(script: str, max_chars: int = 12) -> list[str]:
    """Split into short timeline cue units — prefer clause breaks over long sentences."""
    script = (script or "").strip()
    if not script:
        return []

    script = re.sub(r"[ \t]+", " ", script)
    script = re.sub(r"\s*\n+\s*", "\n", script)
    max_chars = max(6, int(max_chars or 12))
    min_chars = max(3, min(5, max_chars // 3))

    raw_parts: list[str] = []
    for block in SENTENCE_SPLIT.split(script):
        block = block.strip()
        if not block:
            continue
        # Keep only short sentences intact; longer ones split on commas/顿号
        if len(block) <= max_chars:
            raw_parts.append(block)
            continue
        buf = ""
        for clause in CLAUSE_SPLIT.split(block):
            clause = clause.strip()
            if not clause:
                continue
            if not buf:
                buf = clause
            elif len(buf) + len(clause) <= max_chars:
                buf += clause
            else:
                raw_parts.append(buf)
                buf = clause
        if buf:
            if len(buf) > max_chars:
                raw_parts.extend(_chunk_line(buf, max_chars))
            else:
                raw_parts.append(buf)

    if not raw_parts:
        raw_parts = _chunk_line(script.replace("\n", ""), max_chars)

    return _coalesce_cue_units(raw_parts, min_chars=min_chars, max_chars=max_chars)


def _norm_timing_text(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").strip())


def _merge_speech_windows(
    segments: list[dict],
    *,
    max_gap: float = 0.12,
) -> list[tuple[float, float]]:
    """Collapse only tiny ASR gaps; keep real pauses as timing boundaries."""
    windows: list[tuple[float, float]] = []
    for seg in segments:
        try:
            start = float(seg["start"])
            end = float(seg["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if end <= start:
            continue
        if windows and start - windows[-1][1] <= max_gap:
            windows[-1] = (windows[-1][0], max(windows[-1][1], end))
        else:
            windows.append((start, end))
    return windows


def _char_spans_from_segments(segments: list[dict]) -> list[tuple[float, float]]:
    """ASR/TTS time → per-character spans (prefer word timestamps when present).

    Session script text is mapped onto these spans; ASR transcript is timing-only.
    """
    spans: list[tuple[float, float]] = []
    for seg in segments:
        try:
            start = float(seg["start"])
            end = float(seg["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if end <= start:
            continue

        words = seg.get("words")
        if isinstance(words, list) and words:
            for w in words:
                if not isinstance(w, dict):
                    continue
                try:
                    ws, we = float(w["start"]), float(w["end"])
                except (KeyError, TypeError, ValueError):
                    continue
                if we <= ws:
                    continue
                wtext = _norm_timing_text(str(w.get("word") or w.get("text") or ""))
                if not wtext:
                    spans.append((ws, we))
                    continue
                n = len(wtext)
                for i in range(n):
                    spans.append((ws + (we - ws) * i / n, ws + (we - ws) * (i + 1) / n))
            continue

        text = _norm_timing_text(str(seg.get("text") or ""))
        if not text:
            spans.append((start, end))
            continue
        n = len(text)
        for i in range(n):
            spans.append((start + (end - start) * i / n, start + (end - start) * (i + 1) / n))
    return spans


def _allocate_span_counts(weights: list[int], n: int) -> list[int]:
    """Largest-remainder allocation of n spans across units (each gets ≥1 when possible)."""
    k = len(weights)
    if k == 0 or n <= 0:
        return [0] * k
    if n < k:
        return [1 if i < n else 0 for i in range(k)]
    total_w = float(sum(max(1, w) for w in weights))
    exact = [n * max(1, w) / total_w for w in weights]
    floors = [max(1, int(x)) for x in exact]
    # Cap overshoot from the floor≥1 rule
    while sum(floors) > n:
        order = sorted(range(k), key=lambda i: (floors[i], exact[i]), reverse=True)
        trimmed = False
        for i in order:
            if floors[i] > 1:
                floors[i] -= 1
                trimmed = True
                break
        if not trimmed:
            break
    rem = n - sum(floors)
    order = sorted(range(k), key=lambda i: exact[i] - int(exact[i]), reverse=True)
    for i in order:
        if rem <= 0:
            break
        floors[i] += 1
        rem -= 1
    return floors


def _map_units_onto_char_spans(units: list[str], spans: list[tuple[float, float]]) -> list[SubCue]:
    """Map cue units onto ASR char/word timeline — preserves spoken pacing."""
    if not units or not spans:
        return []
    weights = [max(1, len(_norm_timing_text(u)) or len(u.strip()) or 1) for u in units]
    counts = _allocate_span_counts(weights, len(spans))
    cues: list[SubCue] = []
    idx = 0
    for unit, cnt in zip(units, counts):
        if cnt <= 0:
            t0 = cues[-1].end if cues else spans[0][0]
            cues.append(SubCue(len(cues) + 1, round(t0, 3), round(t0 + 0.2, 3), unit))
            continue
        chunk = spans[idx : idx + cnt]
        idx += cnt
        start = chunk[0][0]
        end = max(start + 0.12, chunk[-1][1])
        cues.append(SubCue(len(cues) + 1, round(start, 3), round(end, 3), unit))
    return cues


def _map_units_onto_windows(units: list[str], windows: list[tuple[float, float]]) -> list[SubCue]:
    """Fallback: place cue units across speech windows by character weight."""
    if not units or not windows:
        return []
    weights = [max(1, len(u)) for u in units]
    total_w = float(sum(weights))
    total_speech = sum(max(0.05, e - s) for s, e in windows)
    if total_speech <= 0 or total_w <= 0:
        return []

    unit_durs = [total_speech * (w / total_w) for w in weights]
    cues: list[SubCue] = []
    win_i = 0
    t = windows[0][0]

    for unit, dur in zip(units, unit_durs):
        remaining = float(dur)
        start: float | None = None
        while remaining > 1e-4 and win_i < len(windows):
            w0, w1 = windows[win_i]
            if t < w0:
                t = w0
            if t >= w1 - 1e-4:
                win_i += 1
                if win_i < len(windows):
                    t = windows[win_i][0]
                continue
            if start is None:
                start = t
            take = min(remaining, w1 - t)
            t += take
            remaining -= take
            if t >= w1 - 1e-4:
                win_i += 1
                if win_i < len(windows):
                    t = windows[win_i][0]
        if start is None:
            start = cues[-1].end if cues else windows[0][0]
            t = start + max(0.2, dur)
        end = max(start + 0.18, t)
        cues.append(SubCue(len(cues) + 1, round(start, 3), round(end, 3), unit))

    return cues


def _pause_after_line(line: str, clause_pause: float, sentence_pause: float) -> float:
    if _ends_hard(line):
        return sentence_pause
    if _ends_soft(line):
        return clause_pause
    return max(0.12, clause_pause * 0.45)


def build_subtitle_cues(
    script: str,
    duration: float,
    *,
    pause_sec: float = 0.35,
    max_chars: int = 18,
    auto_punctuation_pause: bool = True,
) -> list[SubCue]:
    lines = split_script_for_subtitles(script, max_chars=max_chars)
    if not lines:
        return []

    duration = max(duration, 0.5)
    n = len(lines)
    if auto_punctuation_pause:
        pauses = [
            _pause_after_line(lines[i], pause_sec * 0.55, pause_sec * 1.15)
            for i in range(n - 1)
        ]
        total_pause = sum(pauses)
    else:
        pauses = [pause_sec] * max(0, n - 1)
        total_pause = pause_sec * max(0, n - 1)

    speech_time = max(0.3, duration - total_pause)
    weights = [max(len(line), 1) for line in lines]
    weight_sum = sum(weights)

    cues: list[SubCue] = []
    t = 0.0
    for i, line in enumerate(lines):
        seg = speech_time * weights[i] / weight_sum
        cues.append(SubCue(i + 1, t, t + seg, line))
        t += seg
        if i < n - 1:
            t += pauses[i]
    return cues


def map_script_to_segment_timeline(
    script: str,
    segments: list[dict],
    *,
    max_chars: int = 18,
) -> list[SubCue]:
    """Map session script onto ASR/TTS time anchors (timing-only; keep script text).

    Preferred path: per-character (or word) spans from Whisper — follows spoken pacing.
    Fallback: speech windows by character weight when ASR has no usable text/words.
    """
    units = split_script_for_subtitles(script, max_chars=max_chars)
    if not units:
        return []
    spans = _char_spans_from_segments(segments)
    if len(spans) >= max(3, len(units)):
        cues = _map_units_onto_char_spans(units, spans)
    else:
        windows = _merge_speech_windows(segments)
        if not windows:
            return []
        cues = _map_units_onto_windows(units, windows)
    # Close tiny holes so the next phrase appears on time (no blank flash)
    fixed: list[SubCue] = []
    for i, c in enumerate(cues):
        end = c.end
        if i + 1 < len(cues):
            nxt = cues[i + 1].start
            if 0 < nxt - end < 0.45:
                end = nxt
        fixed.append(SubCue(c.index, c.start, end, c.text))
    return fixed


def cues_from_asr_segments(
    segments: list[dict],
    *,
    max_chars: int = 18,
) -> list[SubCue]:
    """Build burn-in cues from ASR transcript text (source of truth when audio ≠ script)."""
    max_chars = max(4, min(40, int(max_chars or 18)))
    raw: list[tuple[float, float, str]] = []
    for seg in segments or []:
        if not isinstance(seg, dict):
            continue
        try:
            start = float(seg.get("start") or 0)
            end = float(seg.get("end") or start)
        except (TypeError, ValueError):
            continue
        text = re.sub(r"\s+", "", str(seg.get("text") or "").strip())
        if not text or end <= start:
            continue
        # Prefer word-level timing when available
        words = seg.get("words") if isinstance(seg.get("words"), list) else None
        if words and len(words) >= 2:
            buf = ""
            buf_start = None
            buf_end = start
            for w in words:
                if not isinstance(w, dict):
                    continue
                wtext = re.sub(r"\s+", "", str(w.get("word") or "").strip())
                if not wtext:
                    continue
                try:
                    ws = float(w.get("start") or buf_end)
                    we = float(w.get("end") or ws)
                except (TypeError, ValueError):
                    continue
                if buf_start is None:
                    buf_start = ws
                buf += wtext
                buf_end = we
                if len(buf) >= max_chars:
                    raw.append((float(buf_start), float(buf_end), buf))
                    buf = ""
                    buf_start = None
            if buf and buf_start is not None:
                raw.append((float(buf_start), float(buf_end), buf))
            continue
        # Segment-level: hard-split long lines and allocate time by char weight
        parts = split_script_for_subtitles(text, max_chars=max_chars) or [text]
        if len(parts) == 1:
            raw.append((start, end, parts[0]))
            continue
        total_w = sum(max(1, len(p)) for p in parts) or 1
        cursor = start
        span = max(0.05, end - start)
        for i, part in enumerate(parts):
            share = max(1, len(part)) / total_w
            piece_end = end if i == len(parts) - 1 else cursor + span * share
            raw.append((cursor, max(cursor + 0.2, piece_end), part))
            cursor = piece_end

    cues: list[SubCue] = []
    for i, (s, e, t) in enumerate(raw):
        end = e
        if i + 1 < len(raw):
            nxt = raw[i + 1][0]
            if 0 < nxt - end < 0.45:
                end = nxt
        cues.append(SubCue(i + 1, round(s, 3), round(end, 3), t))
    return cues


def asr_transcript_from_segments(segments: list[dict]) -> str:
    """Join ASR segment texts into a single script body."""
    parts: list[str] = []
    for seg in segments or []:
        if not isinstance(seg, dict):
            continue
        text = re.sub(r"\s+", "", str(seg.get("text") or "").strip())
        if text and "\ufffd" not in text:
            parts.append(text)
    return "".join(parts)


def resolve_subtitle_cues(
    session_dir: Path,
    script: str,
    duration: float,
    *,
    cfg: dict | None = None,
    pause_sec: float = 0.35,
    max_chars: int = 18,
    auto_align_audio: bool = True,
    prefer_asr_text: bool = False,
) -> tuple[list[SubCue], str, str]:
    from tts.dubbing_timing import ensure_subtitle_timing_manifest

    session_dir = Path(session_dir)
    has_audio = (
        resolve_lipsync_video(session_dir) is not None
        or resolve_session_dub_audio(session_dir) is not None
    )

    manifest = None
    if cfg and auto_align_audio and has_audio:
        try:
            manifest = ensure_subtitle_timing_manifest(cfg, session_dir)
        except Exception as exc:
            raise RuntimeError(
                f"口播音频语音识别失败，无法生成字幕时间轴：{exc}"
            ) from exc
    elif has_audio:
        from tts.dubbing_timing import load_timing_manifest

        manifest = load_timing_manifest(session_dir, prefer_asr=True)

    if manifest and manifest.get("segments"):
        align_from = str(manifest.get("align_from") or "")
        source = str(manifest.get("source") or "")
        segs = manifest["segments"]
        asr_cues = cues_from_asr_segments(segs, max_chars=max_chars) if prefer_asr_text else []
        if prefer_asr_text and asr_cues:
            if align_from == "lipsync_video":
                note = f"口播成片识别文案 · {len(asr_cues)} 条（以音频为准）"
            elif source == "dubbing_asr":
                note = f"配音识别文案 · {len(asr_cues)} 条（以音频为准）"
            else:
                note = f"识别文案 · {len(asr_cues)} 条（以音频为准）"
            mode = "lipsync_asr_text" if align_from == "lipsync_video" else (
                "dubbing_asr_text" if source == "dubbing_asr" else "asr_text"
            )
            return asr_cues, note, mode
        # Default: map session script onto ASR/TTS time anchors (timing-only).
        cues = map_script_to_segment_timeline(script, segs, max_chars=max_chars)
        if cues:
            if align_from == "lipsync_video":
                note = f"口播成片 Whisper 锚点 · {len(segs)} 段 · 文案按字映射（非词级强制对齐）"
            elif source == "dubbing_asr":
                note = f"配音 Whisper 锚点 · {len(segs)} 段 · 文案按字映射（非词级强制对齐）"
            else:
                note = f"TTS 分段锚点 · {len(segs)} 段 · 文案映射"
            mode = "lipsync_asr" if align_from == "lipsync_video" else (
                "dubbing_asr" if source == "dubbing_asr" else "tts_segments"
            )
            return cues, note, mode

    if has_audio:
        raise RuntimeError("有口播/配音音频但未生成有效字幕时间轴，请检查 Whisper 是否可用")

    cues = build_subtitle_cues(
        script,
        duration,
        pause_sec=pause_sec,
        max_chars=max_chars,
        auto_punctuation_pause=True,
    )
    return cues, "无音频，按文案字数比例估算", "proportional"


def format_ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    if cs >= 100:
        cs = 0
        s += 1
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def write_ass(
    cues: list[SubCue],
    path: Path,
    *,
    video_width: int,
    video_height: int,
    font_size: int,
    color_hex: str = "#FFFFFF",
    outline: int = 1,
    shadow: int = 0,
    position: str = "bottom",
) -> Path:
    """Write ASS with PlayRes matching the burn canvas (keeps FontSize = on-screen px)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    primary = _hex_to_ass_primary(color_hex)
    align = 8 if position == "top" else 2
    margin_lr = max(24, int(video_width * 0.06))
    margin_v = (
        max(16, int(video_height * 0.02))
        if position == "top"
        else max(28, int(video_height * 0.04))
    )
    outline = max(0, min(int(outline), 4))
    shadow = max(0, min(int(shadow), 4))
    size = max(10, int(font_size))
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {int(video_width)}",
        f"PlayResY: {int(video_height)}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        (
            f"Style: Default,Microsoft YaHei,{size},{primary},&H000000FF,&H80000000,"
            f"&H00000000,-1,0,0,0,100,100,0,0,1,{outline},{shadow},{align},"
            f"{margin_lr},{margin_lr},{margin_v},1"
        ),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for cue in cues:
        body = (cue.text or "").replace("\n", r"\N").replace("{", "(").replace("}", ")")
        if not body.strip():
            continue
        lines.append(
            f"Dialogue: 0,{format_ass_time(cue.start)},{format_ass_time(cue.end)},"
            f"Default,,0,0,0,,{body}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    return path


def format_srt_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(cues: list[SubCue], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    blocks: list[str] = []
    for cue in cues:
        blocks.append(
            f"{cue.index}\n"
            f"{format_srt_time(cue.start)} --> {format_srt_time(cue.end)}\n"
            f"{cue.text}\n"
        )
    path.write_text("\n".join(blocks), encoding="utf-8")
    return path


_SRT_TIME = re.compile(
    r"(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})"
)


def _srt_ts(h: int, m: int, s: int, ms: int) -> float:
    return h * 3600 + m * 60 + s + ms / 1000.0


def parse_srt(text: str) -> list[SubCue]:
    cues: list[SubCue] = []
    blocks = re.split(r"\n\s*\n", text.strip())
    for block in blocks:
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if len(lines) < 2:
            continue
        idx_line = 0
        if lines[0].isdigit():
            idx_line = 1
        if idx_line >= len(lines):
            continue
        m = _SRT_TIME.match(lines[idx_line])
        if not m:
            continue
        start = _srt_ts(*(int(x) for x in m.groups()[:4]))
        end = _srt_ts(*(int(x) for x in m.groups()[4:]))
        body = "\n".join(lines[idx_line + 1 :]).strip()
        if not body:
            continue
        cues.append(SubCue(len(cues) + 1, start, max(end, start + 0.2), body))
    return cues


def read_srt(path: Path) -> list[SubCue]:
    if not path.is_file():
        return []
    return parse_srt(path.read_text(encoding="utf-8"))


def media_duration(probe_bin: str, path: Path) -> float:
    result = subprocess.run(
        [
            probe_bin,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


def _has_audio_stream(probe_bin: str, path: Path) -> bool:
    result = subprocess.run(
        [
            probe_bin,
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    return "audio" in (result.stdout or "")


def mix_bgm_into_video(
    ffmpeg_bin: str,
    probe_bin: str,
    video_path: Path,
    bgm_path: Path,
    output_path: Path,
    *,
    bgm_volume: float = 0.18,
    bgm_start: float = 0.0,
    voice_volume: float = 1.0,
    dub_audio: Path | None = None,
) -> Path:
    """Mix background music under voiceover; keeps video stream copy."""
    duration = media_duration(probe_bin, video_path)
    duration = max(duration, 0.5)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    voice_has_audio = _has_audio_stream(probe_bin, video_path)
    if not voice_has_audio and not (dub_audio and dub_audio.is_file()):
        raise ValueError("成片无音轨且未找到配音，无法混 BGM")

    vol_bgm = max(0.0, min(float(bgm_volume), 1.0))
    vol_voice = max(0.0, min(float(voice_volume), 2.0))
    start = max(0.0, float(bgm_start))

    if voice_has_audio:
        inputs = [ffmpeg_bin, "-y", "-i", str(video_path), "-i", str(bgm_path)]
        voice_label = "[0:a]"
    else:
        inputs = [
            ffmpeg_bin,
            "-y",
            "-i",
            str(video_path),
            "-i",
            str(bgm_path),
            "-i",
            str(dub_audio),
        ]
        voice_label = "[2:a]"

    filt = (
        f"[1:a]atrim=start={start:.3f},asetpts=PTS-STARTPTS,"
        f"volume={vol_bgm},atrim=0:{duration:.3f},asetpts=PTS-STARTPTS,"
        f"aloop=loop=-1:size=2e+09[bgm];"
        f"{voice_label}volume={vol_voice}[voice];"
        f"[voice][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]"
    )
    cmd = inputs + [
        "-filter_complex",
        filt,
        "-map",
        "0:v",
        "-map",
        "[aout]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        str(output_path),
    ]
    subprocess.run(cmd, check=True)
    return output_path


def extract_cover_frame(
    ffmpeg_bin: str,
    video_path: Path,
    time_sec: float,
    output_path: Path,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    t = max(0.0, time_sec)
    subprocess.run(
        [
            ffmpeg_bin,
            "-y",
            "-ss",
            f"{t:.3f}",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-update",
            "1",
            "-q:v",
            "2",
            str(output_path),
        ],
        check=True,
    )
    if not output_path.exists():
        raise FileNotFoundError(f"封面截取失败: {output_path}")
    return output_path


def _escape_sub_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace(":", "\\:")


def _ffprobe_from_ffmpeg(ffmpeg_bin: str) -> str:
    p = Path(ffmpeg_bin)
    name = p.name.lower()
    if name.startswith("ffmpeg"):
        return str(p.with_name(p.name.replace("ffmpeg", "ffprobe", 1).replace("FFMPEG", "ffprobe")))
    return "ffprobe"


def burn_subtitle_text_pil(
    image_path: Path,
    output_path: Path,
    text: str,
    *,
    font_size: int = 8,
    color_hex: str = "#FFFFFF",
    outline: int = 1,
    shadow: int = 0,
    position: str = "bottom",
    video_width: int = 1080,
    video_height: int = 1920,
) -> Path:
    """Draw preview subtitles with the same pixel FontSize as ASS PlayRes burn."""
    from PIL import Image, ImageDraw

    base = Image.open(image_path).convert("RGBA")
    if base.size != (video_width, video_height):
        base = base.resize((video_width, video_height), Image.LANCZOS)
    draw = ImageDraw.Draw(base)
    # Same mapping as write_ass / burn_subtitles (PlayRes == canvas px)
    px = ass_font_size_from_ui(font_size, video_width, video_height)
    font = _load_font(px, bold=True)
    lines = [ln for ln in (text or "").splitlines() if ln.strip()] or ["字幕预览"]
    line_gap = max(2, int(px * 0.22))
    heights = []
    widths = []
    for ln in lines:
        bbox = draw.textbbox((0, 0), ln, font=font)
        widths.append(bbox[2] - bbox[0])
        heights.append(bbox[3] - bbox[1])
    block_h = sum(heights) + line_gap * max(0, len(lines) - 1)
    margin_v = (
        max(16, int(video_height * 0.02))
        if position == "top"
        else max(28, int(video_height * 0.04))
    )
    y = margin_v if position == "top" else video_height - margin_v - block_h
    try:
        color = tuple(int(color_hex.strip().lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        color = (255, 255, 255)
    outline = max(0, min(int(outline), 4))
    for i, ln in enumerate(lines):
        tw = widths[i]
        x = (video_width - tw) // 2
        if outline > 0:
            for ox, oy in (
                (-outline, 0),
                (outline, 0),
                (0, -outline),
                (0, outline),
                (-outline, -outline),
                (outline, outline),
            ):
                draw.text((x + ox, y + oy), ln, font=font, fill=(0, 0, 0, 220))
        draw.text((x, y), ln, font=font, fill=(*color, 255))
        y += heights[i] + line_gap
    output_path.parent.mkdir(parents=True, exist_ok=True)
    base.convert("RGB").save(output_path, quality=92)
    return output_path


def _subtitle_burn_vf(ass_or_srt: Path, style: str, width: int, height: int) -> str:
    """Prefer ASS (PlayRes-accurate); fall back to SRT + force_style."""
    esc = _escape_sub_path(ass_or_srt)
    if ass_or_srt.suffix.lower() == ".ass":
        return f"ass='{esc}'"
    return (
        f"subtitles='{esc}:charenc=UTF-8':"
        f"force_style='{style}':original_size={width}x{height}"
    )


def burn_subtitles(
    ffmpeg_bin: str,
    video_path: Path,
    srt_path: Path,
    output_path: Path,
    style_key: str = "bottom_clean",
    *,
    font_size: int | None = None,
    color_hex: str | None = None,
    outline: int | None = None,
    shadow: int | None = None,
    position: str | None = None,
    probe_bin: str | None = None,
    ass_path: Path | None = None,
) -> Path:
    probe = probe_bin or _ffprobe_from_ffmpeg(ffmpeg_bin)
    width, height = probe_video_dimensions(probe, video_path)
    ui_font = int(font_size) if font_size and font_size > 0 else 8
    ass_font = ass_font_size_from_ui(ui_font, width, height)
    pos = position or ("top" if style_key == "top_tag" else "bottom")
    burn_file = ass_path
    if burn_file is None or not Path(burn_file).is_file():
        # Build ASS from SRT so FontSize is relative to PlayRes == video size
        cues = parse_srt(Path(srt_path).read_text(encoding="utf-8"))
        burn_file = Path(srt_path).with_suffix(".ass")
        write_ass(
            cues,
            burn_file,
            video_width=width,
            video_height=height,
            font_size=ass_font,
            color_hex=color_hex or "#FFFFFF",
            outline=outline if outline is not None else 1,
            shadow=shadow if shadow is not None else 0,
            position=pos,
        )
    style = subtitle_style_string(
        style_key,
        font_size=ui_font,
        color_hex=color_hex,
        outline=outline,
        shadow=shadow,
        position=pos,
        video_width=width,
        video_height=height,
    )
    vf = _subtitle_burn_vf(Path(burn_file), style, width, height)
    subprocess.run(
        [
            ffmpeg_bin,
            "-y",
            "-i",
            str(video_path),
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-crf",
            "20",
            "-c:a",
            "copy",
            str(output_path),
        ],
        check=True,
    )
    return output_path


def burn_subtitles_on_image(
    ffmpeg_bin: str,
    image_path: Path,
    srt_path: Path,
    output_path: Path,
    style_key: str = "bottom_clean",
    *,
    font_size: int | None = None,
    color_hex: str | None = None,
    outline: int | None = None,
    shadow: int | None = None,
    position: str | None = None,
    probe_bin: str | None = None,
) -> Path:
    """Burn ASS subtitles onto a still frame (same filter as video burn)."""
    probe = probe_bin or _ffprobe_from_ffmpeg(ffmpeg_bin)
    width, height = probe_video_dimensions(probe, image_path)
    style = subtitle_style_string(
        style_key,
        font_size=font_size,
        color_hex=color_hex,
        outline=outline,
        shadow=shadow,
        position=position,
        video_width=width,
        video_height=height,
    )
    vf = _subtitle_burn_vf(srt_path, style, width, height)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            ffmpeg_bin,
            "-y",
            "-i",
            str(image_path),
            "-vf",
            vf,
            "-frames:v",
            "1",
            "-update",
            "1",
            "-q:v",
            "2",
            str(output_path),
        ],
        check=True,
    )
    return output_path


def resolve_preview_dimensions(
    output_aspect: str,
    *,
    layout_mode: str,
    video: Path | None,
    probe_bin: str,
) -> tuple[int, int]:
    from workflow.hyperframes_scenes import ASPECT_PRESETS

    mode = (layout_mode or "short").lower()
    if mode == "education":
        preset = ASPECT_PRESETS.get(output_aspect) or ASPECT_PRESETS["portrait_9_16"]
        return int(preset["width"]), int(preset["height"])
    if video and video.is_file():
        return probe_video_dimensions(probe_bin, video)
    preset = ASPECT_PRESETS["portrait_9_16"]
    return int(preset["width"]), int(preset["height"])


def _scale_still_cover(
    ffmpeg_bin: str,
    src: Path,
    width: int,
    height: int,
    dest: Path,
    *,
    time_sec: float = 0.0,
) -> Path:
    from workflow.pip_overlay import _cover_scale_filter

    cover = _cover_scale_filter(width, height)
    dest.parent.mkdir(parents=True, exist_ok=True)
    ext = src.suffix.lower()
    cmd = [ffmpeg_bin, "-y"]
    if ext in {".mp4", ".mov", ".webm", ".mkv"}:
        cmd += ["-ss", f"{max(0.0, time_sec):.3f}"]
    cmd += [
        "-i",
        str(src),
        "-vf",
        cover,
        "-frames:v",
        "1",
        "-update",
        "1",
        "-q:v",
        "2",
        str(dest),
    ]
    subprocess.run(cmd, check=True)
    return dest


def _solid_color_still(
    ffmpeg_bin: str,
    width: int,
    height: int,
    dest: Path,
    *,
    color: str = "0x141820",
) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            ffmpeg_bin,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s={width}x{height}",
            "-frames:v",
            "1",
            "-update",
            "1",
            "-q:v",
            "2",
            str(dest),
        ],
        check=True,
    )
    return dest


def _slot_xy(
    canvas_w: int,
    canvas_h: int,
    position: str,
    pip_w: int,
    pip_h: int,
    margin: int,
) -> tuple[int, int]:
    margin = max(0, int(margin))
    if position == "top_left":
        return margin, margin
    if position == "top_right":
        return canvas_w - pip_w - margin, margin
    if position == "bottom_left":
        return margin, canvas_h - pip_h - margin
    if position == "center":
        return (canvas_w - pip_w) // 2, (canvas_h - pip_h) // 2
    # bottom_right default
    return canvas_w - pip_w - margin, canvas_h - pip_h - margin


def _pip_slot_rect(
    canvas_w: int,
    canvas_h: int,
    position: str,
    scale: float,
    margin: int,
) -> tuple[int, int, int, int]:
    """Return x, y, pip_w, pip_h for lecturer PiP slot."""
    scale = max(0.08, min(0.55, float(scale)))
    margin = max(0, int(margin))
    pip_w = max(48, int(canvas_w * scale))
    # 1:1 square mouth window (education PiP)
    pip_h = pip_w
    if position == "fullscreen":
        return 0, 0, canvas_w, canvas_h
    x, y = _slot_xy(canvas_w, canvas_h, position, pip_w, pip_h, margin)
    return x, y, pip_w, pip_h


def _content_slot_rect(
    canvas_w: int,
    canvas_h: int,
    position: str,
    scale: float,
    margin: int,
    *,
    src_w: int = 16,
    src_h: int = 9,
) -> tuple[int, int, int, int]:
    """Return x, y, w, h for content PiP (keeps source aspect; fullscreen = canvas)."""
    pos = (position or "bottom_left").strip() or "bottom_left"
    if pos == "fullscreen":
        return 0, 0, int(canvas_w), int(canvas_h)
    scale = max(0.08, min(0.55, float(scale)))
    margin = max(0, int(margin))
    pip_w = max(48, int(round(canvas_w * scale)))
    ratio = max(1, int(src_h)) / max(1, int(src_w))
    pip_h = max(48, int(round(pip_w * ratio)))
    if pip_h + 2 * margin > canvas_h:
        pip_h = max(48, canvas_h - 2 * margin)
        pip_w = max(48, int(round(pip_h / ratio)))
    x, y = _slot_xy(canvas_w, canvas_h, pos, pip_w, pip_h, margin)
    return x, y, pip_w, pip_h


def _key_white_rgba(im: "Image.Image", *, threshold: int = 238) -> "Image.Image":
    from PIL import Image

    im = im.convert("RGBA")
    px = im.load()
    w, h = im.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if r >= threshold and g >= threshold and b >= threshold:
                px[x, y] = (r, g, b, 0)
    return im


def _key_black_rgba(im: "Image.Image", *, threshold: int = 12) -> "Image.Image":
    """Make near-black pixels transparent (fusion glass/plain text cards)."""
    im = im.convert("RGBA")
    px = im.load()
    w, h = im.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if r <= threshold and g <= threshold and b <= threshold:
                px[x, y] = (r, g, b, 0)
    return im


def _crop_bust_portrait(im: "Image.Image") -> "Image.Image":
    """Fallback square crop toward upper body when auto crop is not set."""
    w, h = im.size
    side = max(32, min(w, int(h * 0.72)))
    left = max(0, (w - side) // 2)
    top = max(0, int(h * 0.08))
    if top + side > h:
        top = max(0, h - side)
    return im.crop((left, top, left + side, top + side))


def _make_pip_placeholder_tile(pip_w: int, pip_h: int) -> "Image.Image":
    from PIL import Image, ImageDraw

    tile = Image.new("RGB", (pip_w, pip_h))
    draw = ImageDraw.Draw(tile)
    for y in range(pip_h):
        t = y / max(pip_h - 1, 1)
        r = int(42 * (1 - t) + 26 * t)
        g = int(58 * (1 - t) + 32 * t)
        b = int(78 * (1 - t) + 48 * t)
        draw.line([(0, y), (pip_w, y)], fill=(r, g, b))
    draw.rounded_rectangle(
        [1, 1, max(2, pip_w - 2), max(2, pip_h - 2)],
        radius=min(12, pip_w // 8),
        outline=(90, 110, 140),
        width=2,
    )
    return tile.convert("RGBA")


def composite_education_preview_pil(
    bg_path: Path,
    output_path: Path,
    *,
    width: int,
    height: int,
    lecturer_path: Path | None = None,
    has_lecturer_video: bool = False,
    pip_position: str = "bottom_right",
    pip_scale: float = 0.28,
    pip_margin: int = 24,
) -> Path:
    """PIL compositing avoids ffmpeg JPEG/yuvj420p overlay glitches in preview."""
    return composite_content_and_lecturer_preview_pil(
        bg_path,
        output_path,
        width=width,
        height=height,
        lecturer_path=lecturer_path,
        has_lecturer_video=has_lecturer_video,
        pip_position=pip_position,
        pip_scale=pip_scale,
        pip_margin=pip_margin,
    )


def _cover_paste(src: "Image.Image", box_w: int, box_h: int) -> "Image.Image":
    from PIL import Image

    src = src.convert("RGBA")
    sw, sh = src.size
    if sw <= 0 or sh <= 0:
        return Image.new("RGBA", (box_w, box_h), (40, 40, 48, 255))
    scale = max(box_w / sw, box_h / sh)
    nw, nh = max(1, int(round(sw * scale))), max(1, int(round(sh * scale)))
    resized = src.resize((nw, nh), Image.LANCZOS)
    left = max(0, (nw - box_w) // 2)
    top = max(0, (nh - box_h) // 2)
    return resized.crop((left, top, left + box_w, top + box_h))


def _contain_paste(src: "Image.Image", box_w: int, box_h: int) -> "Image.Image":
    """Fit inside box without stretch; transparent letterbox."""
    from PIL import Image

    src = src.convert("RGBA")
    sw, sh = src.size
    if sw <= 0 or sh <= 0:
        return Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    scale = min(box_w / sw, box_h / sh)
    nw, nh = max(1, int(round(sw * scale))), max(1, int(round(sh * scale)))
    resized = src.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    canvas.paste(resized, ((box_w - nw) // 2, (box_h - nh) // 2), resized)
    return canvas


def composite_content_and_lecturer_preview_pil(
    bg_path: Path,
    output_path: Path,
    *,
    width: int,
    height: int,
    content_path: Path | None = None,
    content_position: str = "fullscreen",
    content_scale: float = 0.32,
    content_margin: int = 24,
    lecturer_path: Path | None = None,
    has_lecturer_video: bool = False,
    pip_position: str = "bottom_right",
    pip_scale: float = 0.28,
    pip_margin: int = 24,
    overlay_lecturer: bool = True,
    lecturer_crop: object | None = None,
    content_key_black: bool = False,
) -> Path:
    """Compose base + optional content PiP slot + optional lecturer PiP (matches export order)."""
    from PIL import Image

    bg = Image.open(bg_path).convert("RGBA")
    if bg.size != (width, height):
        bg = _cover_paste(bg, width, height)

    content_pos = (content_position or "fullscreen").strip() or "fullscreen"
    if content_path and Path(content_path).is_file():
        content = Image.open(content_path).convert("RGBA")
        if content_key_black:
            content = _key_black_rgba(content)
        if content_pos == "fullscreen":
            if content_key_black:
                tile = _cover_paste(content, width, height)
                tile = _key_black_rgba(tile)
                bg.paste(tile, (0, 0), tile)
            else:
                # Opaque cover: replace canvas (match export timed fullscreen overlay)
                bg = _cover_paste(content, width, height)
        else:
            cx, cy, cw, ch = _content_slot_rect(
                width,
                height,
                content_pos,
                content_scale,
                content_margin,
                src_w=content.size[0],
                src_h=content.size[1],
            )
            tile = _cover_paste(content, cw, ch)
            if content_key_black:
                tile = _key_black_rgba(tile)
            bg.paste(tile, (cx, cy), tile)

    if overlay_lecturer:
        x, y, pw, ph = _pip_slot_rect(width, height, pip_position, pip_scale, pip_margin)
        if lecturer_path and Path(lecturer_path).is_file() and has_lecturer_video:
            face = Image.open(lecturer_path).convert("RGB")
            if lecturer_crop is not None:
                from workflow.lecturer_crop import NormCrop, apply_norm_crop_image

                crop = lecturer_crop if isinstance(lecturer_crop, NormCrop) else NormCrop.from_dict(lecturer_crop)
                if crop is not None:
                    face = apply_norm_crop_image(face, crop)
            # No auto-crop unless user chose a region — cover-fit full frame into square slot
            face = _cover_paste(face.convert("RGBA"), pw, ph)
            face = _key_white_rgba(face, threshold=248)
        else:
            face = _make_pip_placeholder_tile(pw, ph)
        bg.paste(face, (x, y), face)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    bg.convert("RGB").save(output_path, quality=92)
    return output_path


def composite_lecturer_overlay_still(
    ffmpeg_bin: str,
    bg_path: Path,
    lecturer_path: Path,
    output_path: Path,
    *,
    width: int,
    height: int,
    pip_position: str = "bottom_right",
    pip_scale: float = 0.28,
    pip_margin: int = 24,
    key_white: bool = True,
) -> Path:
    from workflow.pip_overlay import _cover_scale_filter, _pip_face_filter, _pip_xy

    cover = _cover_scale_filter(width, height)
    face_filter = _pip_face_filter(pip_position, pip_scale, key_white=key_white)
    xy = _pip_xy(pip_position, pip_margin)
    filt = (
        f"[0:v]{cover},format=yuv420p[bg];"
        f"[1:v]{face_filter},format=rgba[face];"
        f"[bg][face]overlay={xy}"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            ffmpeg_bin,
            "-y",
            "-i",
            str(bg_path),
            "-i",
            str(lecturer_path),
            "-filter_complex",
            filt,
            "-frames:v",
            "1",
            "-update",
            "1",
            "-q:v",
            "2",
            str(output_path),
        ],
        check=True,
    )
    return output_path


def _resolve_preview_background(
    ffmpeg_bin: str,
    preview_dir: Path,
    width: int,
    height: int,
    text: str,
    *,
    education_bg: Path | None = None,
    hyperframes_consent: bool = False,
    hyperframes_theme: str = "tokyo_night",
    hyperframes_layout: str = "kinetic",
    hyperframes_aspect: str = "portrait_9_16",
) -> Path:
    out = preview_dir / "_preview_bg.jpg"
    if education_bg and education_bg.is_file():
        return _scale_still_cover(ffmpeg_bin, education_bg, width, height, out)
    if hyperframes_consent:
        hf_path = preview_dir / "_preview_hyperframe.png"
        try:
            from workflow.hyperframes import render_scene_preview_image

            render_scene_preview_image(
                text,
                hf_path,
                theme=hyperframes_theme,
                layout=hyperframes_layout,
                aspect=hyperframes_aspect,
            )
            if hf_path.is_file():
                return _scale_still_cover(ffmpeg_bin, hf_path, width, height, out)
        except Exception:
            pass
    return _solid_color_still(ffmpeg_bin, width, height, out)


def _extract_preview_still(
    ffmpeg_bin: str,
    src: Path,
    dest: Path,
    width: int,
    height: int,
    *,
    time_sec: float = 0.0,
    cover: bool = True,
) -> Path:
    """Extract a still from image/video; cover-scale to canvas when cover=True."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if cover:
        return _scale_still_cover(ffmpeg_bin, src, width, height, dest, time_sec=time_sec)
    ext = src.suffix.lower()
    cmd = [ffmpeg_bin, "-y"]
    if ext in {".mp4", ".mov", ".webm", ".mkv"}:
        cmd += ["-ss", f"{max(0.0, time_sec):.3f}"]
    cmd += ["-i", str(src), "-frames:v", "1", "-update", "1", "-q:v", "2", str(dest)]
    subprocess.run(cmd, check=True)
    return dest


def render_subtitle_preview_frame(
    ffmpeg_bin: str,
    probe_bin: str,
    session_dir: Path,
    text: str,
    *,
    time_sec: float = 0.5,
    font_size: int = 8,
    color_hex: str = "#FFFFFF",
    outline: int = 1,
    shadow: int = 0,
    position: str = "bottom",
    subtitle_style: str = "bottom_clean",
    layout_mode: str = "short",
    output_aspect: str = "portrait_9_16",
    pip_position: str = "bottom_right",
    pip_scale: float = 0.28,
    pip_margin: int = 24,
    pip_bg_media: str | None = None,
    content_pip_position: str = "fullscreen",
    content_pip_scale: float = 0.32,
    content_key_black: bool = False,
    education_bg: Path | None = None,
    hyperframes_consent: bool = False,
    hyperframes_theme: str = "tokyo_night",
    hyperframes_layout: str = "kinetic",
    hyperframes_aspect: str = "portrait_9_16",
    hide_subtitles: bool = False,
    hide_lecturer: bool = False,
    lecturer_crop: dict | None = None,
    remotion_theme: str = "off",
    smart_keywords: bool = True,
    cue_start: float | None = None,
    cue_end: float | None = None,
) -> Path:
    """Compose layout + burn subtitles for publish preview (matches export styling)."""
    preview_dir = session_dir / "publish" / "preview"
    preview_dir.mkdir(parents=True, exist_ok=True)
    video = resolve_lipsync_video(session_dir)
    used_placeholder = video is None or not video.is_file()
    mode = (layout_mode or "short").lower()
    rem_theme = (remotion_theme or "off").strip().lower()
    use_remotion = rem_theme not in ("", "off", "none", "0", "false", "ass", "classic")
    width, height = resolve_preview_dimensions(
        output_aspect,
        layout_mode=mode,
        video=video,
        probe_bin=probe_bin,
    )

    lecturer_frame = preview_dir / "_subtitle_lecturer.jpg"
    if not used_placeholder:
        extract_cover_frame(ffmpeg_bin, video, max(0.0, time_sec), lecturer_frame)
    else:
        make_placeholder_cover_frame(lecturer_frame, width=width, height=height, hint=None)

    content_pos = (content_pip_position or "fullscreen").strip() or "fullscreen"
    content_media = Path(pip_bg_media) if pip_bg_media else None
    if content_media and not content_media.is_file():
        content_media = None

    content_still = preview_dir / "_preview_content.jpg"
    if content_media is not None:
        # Non-fullscreen: keep native aspect for slot sizing; fullscreen: canvas cover.
        _extract_preview_still(
            ffmpeg_bin,
            content_media,
            content_still,
            width,
            height,
            time_sec=time_sec,
            cover=(content_pos == "fullscreen"),
        )

    composited = preview_dir / "_subtitle_composited.jpg"
    if mode == "education":
        # Base layer: solid / fixed bg / HF style — content overlays unless fullscreen
        if content_media is not None and content_pos == "fullscreen":
            bg_frame = content_still
        else:
            bg_frame = _resolve_preview_background(
                ffmpeg_bin,
                preview_dir,
                width,
                height,
                (text or "字幕预览").strip(),
                education_bg=education_bg,
                hyperframes_consent=hyperframes_consent,
                hyperframes_theme=hyperframes_theme,
                hyperframes_layout=hyperframes_layout,
                hyperframes_aspect=hyperframes_aspect or output_aspect,
            )
        composite_content_and_lecturer_preview_pil(
            bg_frame,
            composited,
            width=width,
            height=height,
            content_path=content_still if content_media is not None and content_pos != "fullscreen" else None,
            content_position=content_pos,
            content_scale=float(content_pip_scale or 0.32),
            content_margin=int(pip_margin),
            lecturer_path=lecturer_frame if lecturer_frame.is_file() else None,
            has_lecturer_video=not used_placeholder,
            pip_position=pip_position,
            pip_scale=pip_scale,
            pip_margin=pip_margin,
            overlay_lecturer=not hide_lecturer,
            lecturer_crop=lecturer_crop,
            content_key_black=content_key_black,
        )
        raw_frame = composited
    else:
        # Short: lecturer full-frame as base; content PiP on top when not fullscreen
        if hide_lecturer and content_media is not None:
            if content_pos == "fullscreen":
                from PIL import Image

                src = Image.open(content_still).convert("RGB")
                if src.size != (width, height):
                    src = _cover_paste(src.convert("RGBA"), width, height).convert("RGB")
                src.save(composited, quality=92)
            else:
                bg_frame = _solid_color_still(ffmpeg_bin, width, height, preview_dir / "_preview_bg.jpg")
                composite_content_and_lecturer_preview_pil(
                    bg_frame,
                    composited,
                    width=width,
                    height=height,
                    content_path=content_still,
                    content_position=content_pos,
                    content_scale=float(content_pip_scale or 0.32),
                    content_margin=int(pip_margin),
                    overlay_lecturer=False,
                    content_key_black=content_key_black,
                )
        else:
            _scale_still_cover(ffmpeg_bin, lecturer_frame, width, height, composited)
            if content_media is not None:
                if content_pos == "fullscreen" and content_key_black:
                    # Fusion: lipsync base + full-canvas keyed overlay (match burn font size)
                    composite_content_and_lecturer_preview_pil(
                        composited,
                        composited,
                        width=width,
                        height=height,
                        content_path=content_still,
                        content_position="fullscreen",
                        content_scale=1.0,
                        content_margin=int(pip_margin),
                        overlay_lecturer=False,
                        content_key_black=True,
                    )
                elif content_pos == "fullscreen":
                    composite_content_and_lecturer_preview_pil(
                        composited,
                        composited,
                        width=width,
                        height=height,
                        content_path=content_still,
                        content_position="fullscreen",
                        content_scale=1.0,
                        overlay_lecturer=False,
                        content_key_black=False,
                    )
                else:
                    composite_content_and_lecturer_preview_pil(
                        composited,
                        composited,
                        width=width,
                        height=height,
                        content_path=content_still,
                        content_position=content_pos,
                        content_scale=float(content_pip_scale or 0.32),
                        content_margin=int(pip_margin),
                        overlay_lecturer=False,
                        content_key_black=content_key_black,
                    )
        raw_frame = composited

    cue_text = (text or "字幕预览").strip()
    if cue_text:
        c0 = float(cue_start if cue_start is not None else max(0.0, time_sec - 0.6))
        c1 = float(cue_end if cue_end is not None else time_sec + 0.6)
        if c1 <= c0:
            c1 = c0 + 1.0
        wrapped = subtitle_text_for_preview(
            cue_text,
            start=c0,
            end=c1,
            time_sec=max(0.0, float(time_sec)),
            ui_font=int(font_size),
            width=width,
            height=height,
        )
    else:
        wrapped = ""
    srt_path = preview_dir / "_subtitle_preview.srt"
    write_srt([SubCue(1, 0.0, 10.0, wrapped)], srt_path)

    out_path = preview_dir / "subtitle_preview.jpg"
    from PIL import Image

    if hide_subtitles or not cue_text:
        Image.open(raw_frame).convert("RGB").save(out_path, quality=92)
    elif use_remotion:
        # Layout without ASS, then Remotion overlay (same look as final burn-in)
        layout_only = preview_dir / "_subtitle_layout_only.jpg"
        Image.open(raw_frame).convert("RGB").save(layout_only, quality=92)
        remotion_ok = False
        try:
            from workflow.remotion_captions import compose_remotion_on_layout_still, is_available

            if is_available():
                caption_side = "right"
                if mode == "short" and rem_theme in ("side", "side_kinetic"):
                    try:
                        from workflow.face_caption_side import probe_caption_side_from_video

                        if video and video.is_file():
                            caption_side = probe_caption_side_from_video(
                                ffmpeg_bin,
                                video,
                                at_sec=max(0.0, float(time_sec)),
                                work_dir=preview_dir,
                            )
                    except Exception:
                        caption_side = "right"
                compose_remotion_on_layout_still(
                    layout_only,
                    out_path,
                    text=cue_text,
                    remotion_theme=rem_theme,
                    accent=color_hex or "#FFFFFF",
                    ffmpeg_bin=ffmpeg_bin,
                    width=width,
                    height=height,
                    video_path=video if video and video.is_file() else None,
                    time_sec=max(0.0, float(time_sec)),
                    caption_side=caption_side,
                    subtitle_font_size=int(font_size) if font_size else 16,
                    smart_keywords=smart_keywords,
                )
                remotion_ok = out_path.is_file()
        except Exception:
            remotion_ok = False
        if not remotion_ok:
            burn_subtitle_text_pil(
                raw_frame,
                out_path,
                wrapped,
                font_size=font_size,
                color_hex=color_hex,
                outline=outline,
                position=position,
                video_width=width,
                video_height=height,
            )
        layout_only.unlink(missing_ok=True)
    else:
        burn_subtitle_text_pil(
            raw_frame,
            out_path,
            wrapped,
            font_size=font_size,
            color_hex=color_hex,
            outline=outline,
            position=position,
            video_width=width,
            video_height=height,
        )
    for tmp in (
        lecturer_frame,
        composited,
        preview_dir / "_preview_bg.jpg",
        srt_path,
    ):
        if tmp.is_file() and tmp != out_path:
            tmp.unlink(missing_ok=True)
    return out_path


def attach_cover_thumbnail(
    ffmpeg_bin: str,
    video_path: Path,
    cover_path: Path,
    output_path: Path,
) -> Path:
    subprocess.run(
        [
            ffmpeg_bin,
            "-y",
            "-i",
            str(video_path),
            "-i",
            str(cover_path),
            "-map",
            "0",
            "-map",
            "1",
            "-c",
            "copy",
            "-disposition:v:1",
            "attached_pic",
            str(output_path),
        ],
        check=True,
    )
    return output_path


def _load_font(size: int, *, bold: bool = True):
    from PIL import ImageFont

    # Prefer bold YaHei so preview matches ASS Bold=-1 / Microsoft YaHei Bold
    names = (
        ("msyhbd.ttc", "msyh.ttc", "simhei.ttf", "arialbd.ttf", "arial.ttf")
        if bold
        else ("msyh.ttc", "msyhbd.ttc", "simhei.ttf", "arial.ttf")
    )
    for name in names:
        win = Path("C:/Windows/Fonts") / name
        if win.exists():
            return ImageFont.truetype(str(win), size)
    return ImageFont.load_default()


def _gradient_bar(xy, color_top, color_bottom):
    from PIL import Image, ImageDraw

    x0, y0, x1, y1 = xy
    h = y1 - y0
    bar = Image.new("RGBA", (x1 - x0, h))
    bdraw = ImageDraw.Draw(bar)
    for y in range(h):
        ratio = y / max(h - 1, 1)
        r = int(color_top[0] * (1 - ratio) + color_bottom[0] * ratio)
        g = int(color_top[1] * (1 - ratio) + color_bottom[1] * ratio)
        b = int(color_top[2] * (1 - ratio) + color_bottom[2] * ratio)
        a = int(color_top[3] * (1 - ratio) + color_bottom[3] * ratio)
        bdraw.line([(0, y), (x1 - x0, y)], fill=(r, g, b, a))
    return bar


def apply_cover_template(
    image_path: Path,
    output_path: Path,
    template_id: str,
    title: str,
    *,
    subtitle: str = "",
) -> Path:
    from PIL import Image, ImageDraw

    base = Image.open(image_path).convert("RGBA")
    w, h = base.size
    canvas = base.copy()
    draw = ImageDraw.Draw(canvas)
    title = (title or "未命名").strip()
    subtitle = (subtitle or "").strip()

    # Mainstream short-video cover sizes: ~4.5–5.5% of short edge (not 8%+)
    title_px = max(22, min(int(min(w, h) * 0.05), int(w * 0.07)))
    sub_px = max(16, int(title_px * 0.62))

    if template_id in ("bold_center", "dy_soft_center"):
        overlay = Image.new("RGBA", (w, h), (0, 0, 0, 72))
        canvas = Image.alpha_composite(canvas, overlay)
        draw = ImageDraw.Draw(canvas)
        font = _load_font(title_px)
        bbox = draw.textbbox((0, 0), title, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x = (w - tw) // 2
        y = int(h * 0.46 - th / 2)
        draw.text((x + 1, y + 1), title, font=font, fill=(0, 0, 0, 160))
        draw.text((x, y), title, font=font, fill=(255, 255, 255, 255))
        if subtitle:
            sf = _load_font(sub_px)
            sb = draw.textbbox((0, 0), subtitle, font=sf)
            sw, sh = sb[2] - sb[0], sb[3] - sb[1]
            draw.text(((w - sw) // 2, y + th + int(h * 0.02)), subtitle, font=sf, fill=(243, 244, 246, 255))

    elif template_id in ("minimal_tag", "dy_hot_tag"):
        font = _load_font(max(16, int(min(w, h) * 0.028)))
        pad = max(10, w // 48)
        tag = "干货"
        bbox = draw.textbbox((0, 0), tag, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        box = (pad, pad, pad + tw + pad * 2, pad + th + int(pad * 0.9))
        draw.rounded_rectangle(box, radius=999, fill=(249, 115, 22, 235))
        draw.text((pad * 2, pad + 1), tag, font=font, fill=(255, 255, 255, 255))
        bar_h = int(h * 0.22)
        bar = _gradient_bar((0, h - bar_h, w, h), (0, 0, 0, 0), (0, 0, 0, 175))
        canvas.paste(bar, (0, h - bar_h), bar)
        draw = ImageDraw.Draw(canvas)
        tf = _load_font(title_px)
        margin = max(16, w // 22)
        y = h - bar_h + margin
        draw.text((margin + 1, y + 1), title, font=tf, fill=(0, 0, 0, 150))
        draw.text((margin, y), title, font=tf, fill=(255, 255, 255, 255))
        if subtitle:
            draw.text((margin, y + tf.size + 8), subtitle, font=_load_font(sub_px), fill=(255, 237, 213, 255))

    elif template_id in ("vertical_hook", "dy_bottom", "dy_clean_left"):
        bar_h = int(h * 0.24)
        bar = _gradient_bar((0, h - bar_h, w, h), (0, 0, 0, 0), (0, 0, 0, 180))
        canvas.paste(bar, (0, h - bar_h), bar)
        draw = ImageDraw.Draw(canvas)
        title_font = _load_font(title_px)
        sub_font = _load_font(sub_px)
        margin = max(16, w // 22)
        y = h - bar_h + int(margin * 0.9)
        draw.text((margin + 1, y + 1), title, font=title_font, fill=(0, 0, 0, 150))
        draw.text((margin, y), title, font=title_font, fill=(255, 255, 255, 255))
        if subtitle:
            y2 = y + title_font.size + 8
            draw.text((margin, y2), subtitle, font=sub_font, fill=(229, 231, 235, 255))

    else:  # classic_bottom / dy_center_bottom (default)
        bar_h = int(h * 0.22)
        bar = _gradient_bar((0, h - bar_h, w, h), (0, 0, 0, 0), (0, 0, 0, 175))
        canvas.paste(bar, (0, h - bar_h), bar)
        draw = ImageDraw.Draw(canvas)
        font = _load_font(title_px)
        bbox = draw.textbbox((0, 0), title, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x = (w - tw) // 2
        y = h - bar_h + (bar_h - th) // 2 - (sub_px if subtitle else 0) // 2
        draw.text((x + 1, y + 1), title, font=font, fill=(0, 0, 0, 150))
        draw.text((x, y), title, font=font, fill=(255, 255, 255, 255))
        if subtitle:
            sf = _load_font(sub_px)
            sb = draw.textbbox((0, 0), subtitle, font=sf)
            sw = sb[2] - sb[0]
            draw.text(((w - sw) // 2, y + th + 6), subtitle, font=sf, fill=(229, 231, 235, 255))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(output_path, quality=92)
    return output_path


def _build_timed_pip_jobs(
    pip_cue_assignments: list[dict] | None,
    cues: list[SubCue],
    *,
    pip_position: str,
    pip_scale: float,
    pip_margin: int,
) -> list:
    from workflow.pip_overlay import TimedPipJob

    jobs: list[TimedPipJob] = []
    cue_by_index = {c.index: c for c in cues}
    for item in pip_cue_assignments or []:
        media = str(item.get("media_path") or "").strip()
        if not media or not Path(media).is_file():
            continue

        start = item.get("start")
        end = item.get("end")
        indices = item.get("cue_indices")
        if not isinstance(indices, list):
            idx = int(item.get("cue_index") or 0)
            indices = [idx] if idx else []
        indices = sorted({int(i) for i in indices if int(i) > 0})
        selected = [cue_by_index[i] for i in indices if i in cue_by_index]
        if not selected and not (start is not None and end is not None):
            continue
        if start is None and selected:
            start = selected[0].start
        if end is None and selected:
            end = selected[-1].end
        if start is None or end is None:
            continue

        pos = str(item.get("position") or pip_position or "center")
        is_fusion = _assignment_compose_mode(item) == "fusion"
        if is_fusion:
            pos = "fullscreen"
        jobs.append(
            TimedPipJob(
                start=float(start),
                end=float(end),
                media_path=Path(media),
                position=pos,
                scale=1.0 if is_fusion else float(item.get("scale") or pip_scale or 0.28),
                margin=int(item.get("margin") or pip_margin or 24),
                play_full_video=bool(item.get("play_full_video")),
                display_duration=(
                    float(item["display_duration_sec"])
                    if item.get("display_duration_sec") not in (None, "")
                    else None
                ),
                source_start=float(item.get("source_start_sec") or item.get("source_start") or 0),
                crop=item.get("crop") if isinstance(item.get("crop"), dict) else None,
                key_black=is_fusion,
            )
        )
    return jobs


def _covered_cue_indices(assignments: list[dict]) -> set[int]:
    covered: set[int] = set()
    for item in assignments:
        indices = item.get("cue_indices")
        if isinstance(indices, list):
            for i in indices:
                if int(i) > 0:
                    covered.add(int(i))
        else:
            idx = int(item.get("cue_index") or 0)
            if idx > 0:
                covered.add(idx)
    return covered


def _is_short_lipsync_mix(layout_mode: str, pip_mode: str) -> bool:
    """True for 口播混剪 (short) when not on education layout branches."""
    layout = (layout_mode or "short").strip().lower()
    mode = (pip_mode or "none").strip().lower()
    return layout == "short" and mode not in ("education", "education_timed")


def _assignment_compose_mode(item: dict) -> str:
    """Return fusion | cover for a pip assignment."""
    from workflow.hyperframes_scenes import is_fusion_layout

    mode = str(item.get("compose_mode") or "").strip().lower()
    if mode in ("fusion", "cover"):
        return mode
    layout = str(item.get("content_style") or item.get("scene_layout") or "").strip()
    if is_fusion_layout(layout):
        return "fusion"
    if item.get("auto_hyperframe"):
        return "cover"
    return "cover"


def _split_fusion_assignments(
    assignments: list[dict] | None,
) -> tuple[list[dict], list[dict]]:
    opaque: list[dict] = []
    fusion: list[dict] = []
    for item in assignments or []:
        if not isinstance(item, dict):
            continue
        if _assignment_compose_mode(item) == "fusion":
            fusion.append(item)
        else:
            opaque.append(item)
    return opaque, fusion


def _short_side_ass_position(caption_side: str) -> str:
    side = (caption_side or "right").strip().lower()
    if side not in ("left", "right"):
        side = "right"
    return f"side_{side}"


def _augment_hyperframe_cue_assignments(
    assignments: list[dict],
    cues: list[SubCue],
    work_dir: Path,
    *,
    theme: str,
    layout: str = "kinetic",
    ffmpeg_bin: str = "ffmpeg",
    aspect: str = "portrait_9_16",
    target_indices: set[int] | None = None,
) -> list[dict]:
    from workflow.hyperframes import generate_cue_scene_assets

    covered = _covered_cue_indices(assignments)
    auto = generate_cue_scene_assets(
        cues,
        work_dir,
        theme=theme,
        layout=layout,
        skip_indices=covered,
        target_indices=target_indices,
        force_contiguous=bool(target_indices),
        ffmpeg_bin=ffmpeg_bin,
        aspect=aspect,
    )
    stamped: list[dict] = []
    for item in auto:
        row = dict(item)
        row.setdefault("position", "fullscreen")
        row.setdefault("scale", 1)
        stamped.append(row)
    return list(assignments) + stamped


def run_publish(
    session_dir: Path,
    *,
    script: str,
    title: str,
    cover_time: float,
    template_id: str,
    do_burn_subtitles: bool,
    subtitle_style: str,
    subtitle_pause: float,
    subtitle_max_chars: int,
    do_embed_cover: bool,
    ffmpeg_bin: str,
    probe_bin: str,
    source_video: Path | None = None,
    pip_mode: str = "none",
    pip_source: Path | None = None,
    pip_position: str = "top_right",
    pip_scale: float = 0.28,
    pip_margin: int = 24,
    hyperframes_consent: bool = False,
    hyperframes_theme: str = "tokyo_night",
    hyperframes_layout: str = "kinetic",
    hyperframes_aspect: str = "portrait_9_16",
    hyperframes_target_indices: set[int] | list[int] | None = None,
    pip_cue_assignments: list[dict] | None = None,
    lecturer_crop: dict | None = None,
    subtitle_font_size: int | None = None,
    subtitle_color: str | None = None,
    subtitle_outline: int | None = None,
    subtitle_shadow: int | None = None,
    subtitle_position: str | None = None,
    bgm_path: Path | None = None,
    bgm_volume: float = 0.18,
    bgm_start: float = 0.0,
    cues_override: list[SubCue] | None = None,
    on_progress: Callable[[float, str | None], None] | None = None,
    remotion_theme: str = "off",
    layout_mode: str = "short",
    remotion_smart_keywords: bool = True,
    hf_text_cards: bool = False,
    cover_image_path: str | Path | None = None,
    glass_cards: list[dict] | None = None,
    hf_card_position: str = "auto",
    hf_card_scale: float = 0.58,
) -> dict[str, Path | str]:
    def tick(p: float, msg: str) -> None:
        if on_progress:
            on_progress(p, msg)

    session_dir.mkdir(parents=True, exist_ok=True)
    publish_dir = session_dir / "publish"
    publish_dir.mkdir(parents=True, exist_ok=True)

    tick(0.02, "准备发布…")
    video = source_video or resolve_session_video(session_dir)
    if video is None or not video.exists():
        raise FileNotFoundError("未找到成片视频，请先完成阶段二对口型")

    width, height = probe_video_dimensions(probe_bin, video)
    ui_font = int(subtitle_font_size or 16)
    from workflow.hyperframes_scenes import resolve_scene_aspect

    hf_scene_aspect = resolve_scene_aspect(
        hyperframes_aspect,
        video_width=width,
        video_height=height,
    )

    duration, timing_note = resolve_timing_duration(session_dir, video, probe_bin)
    tick(0.08, "生成字幕时间轴…")
    try:
        from workflow.app_config import load_cfg

        cfg = load_cfg()
    except Exception:
        cfg = None
    split_chars = resolve_subtitle_split_chars(
        ui_font,
        width,
        height,
        config_max=int(subtitle_max_chars or 18),
    )
    cues, timing_note, timing_mode = resolve_subtitle_cues(
        session_dir,
        script,
        duration,
        cfg=cfg,
        pause_sec=subtitle_pause,
        max_chars=split_chars,
        auto_align_audio=True,
    )
    if cues_override:
        cues = cues_override
    # Placeholder SRT for early stages; rewritten at burn time against final canvas size
    burn_cues = list(cues) if cues else []
    srt_path = publish_dir / "subtitles.srt"
    write_srt(burn_cues, srt_path)
    tick(0.16, "写入字幕文件…")

    cover_raw = publish_dir / "cover_raw.jpg"
    cover_out = publish_dir / "cover.jpg"
    custom = Path(str(cover_image_path)) if cover_image_path else None
    if custom is not None and custom.is_file():
        import shutil

        shutil.copy2(custom, cover_out)
        if not cover_raw.is_file():
            shutil.copy2(custom, cover_raw)
        tick(0.22, "使用自定义封面…")
    else:
        extract_cover_frame(ffmpeg_bin, video, cover_time, cover_raw)
        tick(0.22, "截取封面…")
        apply_cover_template(
            cover_raw,
            cover_out,
            template_id,
            title,
            subtitle=default_title_from_script(script, 30) if template_id == "vertical_hook" else "",
        )

    working_video = video

    pip_mode = (pip_mode or "none").lower()
    is_short = _is_short_lipsync_mix(layout_mode, pip_mode)

    if pip_mode == "timed":
        tick(0.28, "合成画中画…")
        from workflow.pip_overlay import apply_timed_pip_overlays

        opaque_asgn, fusion_asgn = _split_fusion_assignments(pip_cue_assignments)
        pip_work = publish_dir / "pip"
        pip_work.mkdir(parents=True, exist_ok=True)
        # Opaque / cover-style PiP first (no colorkey)
        jobs = _build_timed_pip_jobs(
            opaque_asgn,
            cues,
            pip_position=pip_position,
            pip_scale=pip_scale,
            pip_margin=pip_margin,
        )
        if jobs:
            pip_out = publish_dir / "with_pip.mp4"
            apply_timed_pip_overlays(
                ffmpeg_bin,
                probe_bin,
                working_video,
                jobs,
                pip_out,
                work_dir=pip_work,
                default_position=pip_position,
                default_scale=pip_scale,
                default_margin=pip_margin,
            )
            working_video = pip_out
        # Short fusion burns later (face-aware). Non-short timed fusion keys here.
        if fusion_asgn and not is_short:
            tick(0.4, "融合透明特效…")
            f_jobs = _build_timed_pip_jobs(
                fusion_asgn,
                cues,
                pip_position=pip_position or "top_right",
                pip_scale=float(hf_card_scale or 0.42),
                pip_margin=pip_margin,
            )
            if f_jobs:
                pip_out = publish_dir / "with_fusion.mp4"
                apply_timed_pip_overlays(
                    ffmpeg_bin,
                    probe_bin,
                    working_video,
                    f_jobs,
                    pip_out,
                    work_dir=pip_work / "fusion",
                    default_position=pip_position or "top_right",
                    default_scale=float(hf_card_scale or 0.42),
                    default_margin=pip_margin,
                    key_black=True,
                )
                working_video = pip_out
    elif pip_mode in ("education", "education_timed"):
        tick(0.28, "合成网课布局…")
        from workflow.pip_overlay import (
            apply_education_layout,
            apply_education_timed_layout,
            prepare_pip_source,
            solid_color_video,
            _video_size,
        )

        pip_work = publish_dir / "pip"
        pip_work.mkdir(parents=True, exist_ok=True)
        lecturer_video = working_video
        edu_position = pip_position or "bottom_right"
        from workflow.hyperframes_scenes import ASPECT_PRESETS, resolve_scene_aspect

        try:
            width, height = _video_size(probe_bin, lecturer_video)
        except (OSError, subprocess.CalledProcessError, ValueError):
            aspect_preset = ASPECT_PRESETS.get(hyperframes_aspect or "portrait_9_16") or ASPECT_PRESETS[
                "portrait_9_16"
            ]
            width, height = int(aspect_preset["width"]), int(aspect_preset["height"])
        hf_scene_aspect = resolve_scene_aspect(
            hyperframes_aspect,
            video_width=width,
            video_height=height,
        )

        assignments = list(pip_cue_assignments or [])
        if hyperframes_consent:
            target_set: set[int] = set()
            if hyperframes_target_indices is not None:
                target_set = {int(i) for i in hyperframes_target_indices if int(i) > 0}
            # Require explicit cue selection — never fill the whole film when unselected
            if target_set:
                assignments = _augment_hyperframe_cue_assignments(
                    assignments,
                    cues,
                    pip_work / "hf_auto",
                    theme=hyperframes_theme or "tokyo_night",
                    layout=hyperframes_layout or "kinetic",
                    ffmpeg_bin=ffmpeg_bin,
                    aspect=hf_scene_aspect,
                    target_indices=target_set,
                )

        if pip_source is not None and pip_source.exists():
            base_prepared = prepare_pip_source(
                ffmpeg_bin, probe_bin, pip_source, duration, pip_work / "bg"
            )
        else:
            base_prepared = pip_work / "solid_bg.mp4"
            solid_color_video(ffmpeg_bin, width, height, duration, base_prepared)

        opaque_asgn, fusion_asgn = _split_fusion_assignments(assignments)
        lecturer_for_layout = lecturer_video
        jobs = _build_timed_pip_jobs(
            opaque_asgn,
            cues,
            pip_position=edu_position,
            pip_scale=pip_scale,
            pip_margin=pip_margin,
        )
        if fusion_asgn:
            from workflow.pip_overlay import apply_timed_pip_overlays

            fusion_jobs = _build_timed_pip_jobs(
                fusion_asgn,
                cues,
                pip_position="fullscreen",
                pip_scale=1.0,
                pip_margin=pip_margin,
            )
            if fusion_jobs:
                fusion_on_lecturer = pip_work / "lecturer_with_fusion.mp4"
                apply_timed_pip_overlays(
                    ffmpeg_bin,
                    probe_bin,
                    lecturer_video,
                    fusion_jobs,
                    fusion_on_lecturer,
                    work_dir=pip_work / "fusion_on_lecturer",
                    default_position="fullscreen",
                    default_scale=1.0,
                    default_margin=pip_margin,
                    key_black=True,
                )
                lecturer_for_layout = fusion_on_lecturer

        from workflow.lecturer_crop import NormCrop

        lec_crop = NormCrop.from_dict(lecturer_crop) if lecturer_crop else None
        lec_crop_filter = None
        if lec_crop is not None:
            src_w, src_h = probe_video_dimensions(probe_bin, lecturer_video)
            lec_crop_filter = lec_crop.ffmpeg_crop(src_w, src_h)

        pip_out = publish_dir / "with_education_layout.mp4"
        if jobs:
            apply_education_timed_layout(
                ffmpeg_bin,
                probe_bin,
                lecturer_for_layout,
                jobs,
                pip_out,
                work_dir=pip_work,
                base_video=base_prepared,
                position=edu_position,
                scale=pip_scale,
                margin=pip_margin,
                canvas_width=width,
                canvas_height=height,
                lecturer_crop_filter=lec_crop_filter,
            )
        else:
            apply_education_layout(
                ffmpeg_bin,
                probe_bin,
                base_prepared,
                lecturer_for_layout,
                pip_out,
                position=edu_position,
                scale=pip_scale,
                margin=pip_margin,
                canvas_width=width,
                canvas_height=height,
                lecturer_crop_filter=lec_crop_filter,
            )
        working_video = pip_out
    elif pip_mode in ("upload", "hyperframes"):
        tick(0.28, "合成画中画…")
        pip_work = publish_dir / "pip"
        pip_work.mkdir(parents=True, exist_ok=True)
        pip_clip = pip_work / "pip_clip.mp4"

        if pip_mode == "hyperframes":
            if not hyperframes_consent:
                raise ValueError("使用 HyperFrames 需勾选同意根据文案生成画中画素材")
            from workflow.hyperframes import generate_hyperframes_video

            hf_src = pip_work / "hyperframes_source.mp4"
            pub_cfg_pause = subtitle_pause
            generate_hyperframes_video(
                script,
                duration,
                hf_src,
                pause_sec=pub_cfg_pause,
                max_chars=subtitle_max_chars,
                ffmpeg_bin=ffmpeg_bin,
                theme=hyperframes_theme,
                layout=hyperframes_layout or "kinetic",
                aspect=hyperframes_aspect or "portrait_9_16",
            )
            pip_src = hf_src
        elif pip_source is not None and pip_source.exists():
            pip_src = pip_source
        else:
            raise ValueError("画中画：请上传图片或视频素材")

        from workflow.pip_overlay import apply_picture_in_picture, prepare_pip_source

        prepared = prepare_pip_source(
            ffmpeg_bin, probe_bin, pip_src, duration, pip_work
        )
        pip_out = publish_dir / "with_pip.mp4"
        apply_picture_in_picture(
            ffmpeg_bin,
            working_video,
            prepared,
            pip_out,
            position=pip_position,
            scale=pip_scale,
            margin=pip_margin,
        )
        working_video = pip_out

    # Short / 口播混剪: fusion content effects (transparent key; never fullscreen)
    _, fusion_from_pip = _split_fusion_assignments(pip_cue_assignments if is_short else [])
    glass_specs = list(glass_cards or []) if glass_cards else []
    target_set: set[int] = set()
    if hyperframes_target_indices is not None:
        target_set = {int(i) for i in hyperframes_target_indices if int(i) > 0}
    want_fusion = is_short and (
        bool(fusion_from_pip) or bool(glass_specs) or (bool(hf_text_cards) and bool(target_set))
    )
    if want_fusion:
        tick(0.45, "融合透明特效…")
        try:
            from workflow.face_caption_side import probe_caption_side_from_video
            from workflow.glass_cards import resolve_card_position
            from workflow.hyperframes import generate_glass_card_assets
            from workflow.pip_overlay import apply_timed_pip_overlays

            hf_work = publish_dir / "hf_fusion"
            hf_work.mkdir(parents=True, exist_ok=True)
            face_side = probe_caption_side_from_video(
                ffmpeg_bin,
                working_video,
                work_dir=hf_work / "side_probe",
            )
            card_pos = resolve_card_position(
                hf_card_position or "auto",
                face_empty_side=face_side,
            )
            # Fusion burns full-canvas + colorkey (not PiP shrink) — keeps preview font size
            card_scale = 1.0

            card_assignments: list[dict] = []
            if glass_specs:
                card_assignments = generate_glass_card_assets(
                    glass_specs,
                    hf_work,
                    theme=hyperframes_theme or "tokyo_night",
                    aspect=hf_scene_aspect,
                    ffmpeg_bin=ffmpeg_bin,
                    default_position="fullscreen",
                    default_scale=1.0,
                )
            elif fusion_from_pip:
                for item in fusion_from_pip:
                    patched = dict(item)
                    patched["position"] = "fullscreen"
                    patched["scale"] = 1.0
                    patched["compose_mode"] = "fusion"
                    # Keep face side as hint for future re-render; burn ignores PiP slot
                    patched["fusion_anchor"] = card_pos
                    card_assignments.append(patched)
            else:
                layout_key = hyperframes_layout or "glass_card"
                if layout_key not in ("text_card", "glass_card", "plain_text"):
                    layout_key = "glass_card"
                card_assignments = _augment_hyperframe_cue_assignments(
                    [],
                    cues,
                    hf_work,
                    theme=hyperframes_theme or "tokyo_night",
                    layout=layout_key,
                    ffmpeg_bin=ffmpeg_bin,
                    aspect=hf_scene_aspect,
                    target_indices=target_set,
                )
                for item in card_assignments:
                    if item.get("auto_hyperframe"):
                        item["position"] = "fullscreen"
                        item["scale"] = 1.0
                        item["compose_mode"] = "fusion"
                        item["fusion_anchor"] = card_pos
            jobs = _build_timed_pip_jobs(
                card_assignments,
                cues,
                pip_position="fullscreen",
                pip_scale=1.0,
                pip_margin=pip_margin,
            )
            if jobs:
                pip_out = publish_dir / "with_fusion.mp4"
                apply_timed_pip_overlays(
                    ffmpeg_bin,
                    probe_bin,
                    working_video,
                    jobs,
                    pip_out,
                    work_dir=hf_work / "pip",
                    default_position="fullscreen",
                    default_scale=1.0,
                    default_margin=pip_margin,
                    key_black=True,
                )
                working_video = pip_out
            _ = card_pos  # face side reserved for HTML-anchor re-render
        except Exception:
            log.exception("HF fusion overlay failed; continuing without fusion layer")

    if do_burn_subtitles and burn_cues:
        tick(0.58, "字幕刻录…")
        # Always size against the FINAL canvas (education 16:9 vs lipsync 9:16 must match preview)
        width, height = probe_video_dimensions(probe_bin, working_video)
        burn_cues = prepare_burn_cues(
            burn_cues,
            ui_font_size=ui_font,
            video_width=width,
            video_height=height,
        )
        write_srt(burn_cues, srt_path)

        caption_side = "right"
        burn_position = subtitle_position or "bottom"
        rem_theme = (remotion_theme or "off").strip().lower()
        if is_short:
            from workflow.face_caption_side import probe_caption_side_from_video

            caption_side = probe_caption_side_from_video(
                ffmpeg_bin,
                working_video,
                work_dir=publish_dir / "side_probe",
            )
            burn_position = _short_side_ass_position(caption_side)

        use_remotion = rem_theme not in ("", "off", "none", "0", "false", "ass", "classic")
        # Legacy: map removed「侧向动效」to bottom bar fusion on lipsync
        if is_short and use_remotion and rem_theme in ("side", "side_kinetic"):
            rem_theme = "bar"
        subtitled = publish_dir / "with_subtitles.mp4"
        remotion_ok = False
        if use_remotion:
            try:
                from workflow.remotion_captions import burn_remotion_on_video, is_available as remotion_ok_fn

                if remotion_ok_fn():
                    tick(0.6, "Remotion 动效字幕…")
                    cue_dicts = [
                        {"start": c.start, "end": c.end, "text": c.text}
                        for c in burn_cues
                    ]
                    burn_kwargs: dict = {
                        "ffmpeg_bin": ffmpeg_bin,
                        "remotion_theme": rem_theme,
                        "accent": subtitle_color or "#FFFFFF",
                        "duration_sec": float(duration),
                        "probe_bin": probe_bin,
                        "subtitle_font_size": ui_font,
                        "smart_keywords": remotion_smart_keywords,
                    }
                    if is_short:
                        burn_kwargs["caption_side"] = caption_side
                    burn_remotion_on_video(
                        working_video,
                        cue_dicts,
                        subtitled,
                        **burn_kwargs,
                    )
                    remotion_ok = True
            except Exception:
                log.exception("Remotion burn failed; falling back to ASS")
                remotion_ok = False
        if not remotion_ok:
            ass_position = burn_position if is_short else (subtitle_position or "bottom")
            ass_font = ass_font_size_from_ui(ui_font, width, height)
            ass_path = publish_dir / "subtitles.ass"
            write_ass(
                burn_cues,
                ass_path,
                video_width=width,
                video_height=height,
                font_size=ass_font,
                color_hex=subtitle_color or "#FFFFFF",
                outline=subtitle_outline if subtitle_outline is not None else 1,
                shadow=subtitle_shadow if subtitle_shadow is not None else 0,
                position=ass_position,
            )
            burn_subtitles(
                ffmpeg_bin,
                working_video,
                srt_path,
                subtitled,
                subtitle_style,
                font_size=subtitle_font_size,
                color_hex=subtitle_color,
                outline=subtitle_outline,
                shadow=subtitle_shadow,
                position=ass_position,
                probe_bin=probe_bin,
                ass_path=ass_path,
            )
        working_video = subtitled

    if bgm_path and bgm_path.is_file() and bgm_volume > 0:
        tick(0.78, "混入 BGM…")
        dub_audio = resolve_session_dub_audio(session_dir)
        bgm_out = publish_dir / "with_bgm.mp4"
        mix_bgm_into_video(
            ffmpeg_bin,
            probe_bin,
            working_video,
            bgm_path,
            bgm_out,
            bgm_volume=bgm_volume,
            bgm_start=bgm_start,
            dub_audio=dub_audio,
        )
        working_video = bgm_out

    tick(0.9, "写入成片…")
    final = session_dir / "final_publish.mp4"
    if do_embed_cover:
        attach_cover_thumbnail(ffmpeg_bin, working_video, cover_out, final)
    else:
        import shutil

        shutil.copy2(working_video, final)

    tick(1.0, "完成")
    return {
        "video": final,
        "srt": srt_path,
        "cover_raw": cover_raw,
        "cover": cover_out,
        "cue_count": str(len(burn_cues)),
        "duration": f"{duration:.1f}s",
        "timing_note": timing_note,
        "timing_mode": timing_mode,
        "pip": pip_mode if pip_mode != "none" else "",
        "bgm": bgm_path.name if bgm_path and bgm_path.is_file() and bgm_volume > 0 else "",
    }

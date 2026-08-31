"""Bridge to Remotion caption renderer (tools/remotion-captions)."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
REMOTION_DIR = REPO_ROOT / "tools" / "remotion-captions"
RENDER_JS = REMOTION_DIR / "render.mjs"


def _engine_mode() -> str:
    return (os.environ.get("AGENT_REMOTION_ENGINE") or "auto").strip().lower()


def _bar_height_for_theme(width: int, theme: str) -> int:
    t = (theme or "bar").strip().lower()
    if t in ("kinetic", "pop"):
        return max(160, int(round(width * 0.42)))
    if t in ("glass", "pill"):
        return max(180, int(round(width * 0.32)))
    return max(160, int(round(width * 0.28)))


def suggest_remotion_caption_theme(text: str) -> dict[str, Any]:
    """Heuristic Remotion caption theme from cue text (bar | glass | pill | kinetic | pop)."""
    from workflow.hyperframes_scenes import (
        _SMART_EMO_WORDS,
        _SMART_HOOK_WORDS,
        _SMART_URGENT_WORDS,
    )

    raw = (text or "").strip()
    compact = raw.replace("\n", "").replace(" ", "")
    n = len(compact)
    reasons: list[str] = []
    hook_hits = sum(1 for w in _SMART_HOOK_WORDS if w in raw)
    urgent_hits = sum(1 for w in _SMART_URGENT_WORDS if w in raw)
    emo_hits = sum(1 for w in _SMART_EMO_WORDS if w in raw)

    if hook_hits >= 1 and n <= 16:
        theme = "pop"
        reasons.append("短句钩子 → 弹跳强调")
    elif urgent_hits >= 1 or raw.endswith(("!", "！")) or "%" in raw:
        theme = "pill"
        reasons.append("紧迫/数字感 → 胶囊强调")
    elif n >= 24 or raw.count("。") >= 2 or raw.count("，") >= 2:
        theme = "glass"
        reasons.append("较长讲解 → 毛玻璃底牌")
    elif n <= 14 and (raw.endswith(("？", "?")) or emo_hits >= 1):
        theme = "kinetic"
        reasons.append("短句情绪 → 居中动感")
    elif n <= 20:
        theme = "pill"
        reasons.append("短句强调 → 胶囊")
    else:
        theme = "glass"
        reasons.append("默认 → 毛玻璃底牌")

    return {"theme": theme, "reasons": reasons, "sample": compact[:48] or "…"}


def resolve_remotion_theme(theme: str, text: str = "") -> str:
    t = (theme or "bar").strip().lower()
    if t in ("auto", "smart", "ai"):
        return str(suggest_remotion_caption_theme(text).get("theme") or "glass")
    return t


def _remotion_font_px(ui_size: int, width: int, height: int) -> int:
    from workflow.publish import ass_font_size_from_ui

    return ass_font_size_from_ui(int(ui_size or 16), int(width), int(height))


def _enrich_remotion_cues(
    cues: list[dict[str, Any]],
    *,
    smart_keywords: bool = True,
) -> list[dict[str, Any]]:
    """Attach smart keyword spans (same rules as HyperFrames scene cards)."""
    from workflow.hyperframes_scenes import analyze_smart_spans

    out: list[dict[str, Any]] = []
    for c in cues:
        text = str(c.get("text") or "").strip()
        if not text:
            continue
        start = max(0.0, float(c.get("start") or 0))
        end = max(start + 0.4, float(c.get("end") or start + 1))
        entry: dict[str, Any] = {"start": start, "end": end, "text": text}
        if smart_keywords:
            spans = analyze_smart_spans(text)
            if spans:
                entry["spans"] = [
                    {"start": a, "end": b, "cls": cls} for a, b, cls in spans
                ]
        out.append(entry)
    return out


@contextmanager
def _remotion_smart_keywords_scope(enabled: bool = True):
    from workflow.hyperframes_scenes import smart_keywords_scope

    with smart_keywords_scope(enabled):
        yield


def _normalize_burn_mode(theme: str) -> str:
    """Map remotion theme strings to burn overlay mode."""
    t = (theme or "bar").strip().lower()
    if t in ("off", "none", "0", "false"):
        return "off"
    if t in ("side", "side_kinetic"):
        return "side"
    if t == "pop":
        return "pop"
    return "bar"


def is_available() -> bool:
    mode = _engine_mode()
    if mode in ("off", "0", "false", "pil", "legacy"):
        return False
    if mode == "on" or mode == "remotion":
        return RENDER_JS.is_file()
    if not RENDER_JS.is_file():
        return False
    return shutil.which("node") is not None and shutil.which("npx") is not None


def _run_job(job: dict[str, Any], output_path: Path, *, timeout_sec: float) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    job = {**job, "output": str(output_path.resolve())}
    with tempfile.TemporaryDirectory(prefix="remotion_job_") as tmp:
        job_path = Path(tmp) / "job.json"
        job_path.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
        cmd = ["node", str(RENDER_JS), str(job_path)]
        log.info("remotion_captions render: %s", " ".join(cmd))
        proc = subprocess.run(
            cmd,
            cwd=str(REMOTION_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
        )
        if proc.stdout:
            log.debug(proc.stdout[-2000:])
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "")[-2500:]
            raise RuntimeError(f"remotion-captions render failed ({proc.returncode}): {err}")
        if not output_path.is_file():
            raise RuntimeError("remotion-captions finished but output missing")
    return output_path


def render_caption(
    lines: list[str] | str,
    output_path: Path,
    *,
    accent: str = "#7aa2f7",
    duration_sec: float = 3.0,
    width: int = 1080,
    height: int = 1920,
    timeout_sec: float = 300.0,
) -> Path:
    """Render a kinetic caption MP4 via tools/remotion-captions/render.mjs."""
    if not is_available():
        raise RuntimeError("Remotion caption bridge unavailable")

    if isinstance(lines, str):
        line_list = [ln.strip() for ln in lines.splitlines() if ln.strip()]
    else:
        line_list = [str(x).strip() for x in lines if str(x).strip()]
    if not line_list:
        line_list = ["…"]

    job = {
        "composition": "CaptionSample",
        "lines": line_list[:6],
        "accent": accent,
        "duration": float(duration_sec),
        "width": int(width),
        "height": int(height),
    }
    return _run_job(job, Path(output_path), timeout_sec=timeout_sec)


def render_timed_caption_bar(
    cues: list[dict[str, Any]],
    output_path: Path,
    *,
    accent: str = "#7aa2f7",
    duration_sec: float,
    width: int = 1080,
    height: int | None = None,
    theme: str = "bar",
    font_size_px: int | None = None,
    smart_keywords: bool = True,
    timeout_sec: float = 300.0,
) -> Path:
    """Render a bottom caption strip timed to relative cue windows."""
    if not is_available():
        raise RuntimeError("Remotion caption bridge unavailable")
    raw = [c for c in cues if isinstance(c, dict)]
    sample = str(raw[0].get("text") or "").strip() if raw else ""
    theme_resolved = resolve_remotion_theme(theme, sample)
    bar_h = int(height) if height else _bar_height_for_theme(int(width), theme_resolved)
    prepared = _enrich_remotion_cues(raw, smart_keywords=smart_keywords)
    if not prepared:
        prepared = [{"start": 0.0, "end": float(duration_sec), "text": "…"}]
    font_px = int(font_size_px or _remotion_font_px(16, int(width), bar_h))
    out = Path(output_path)
    # H.264 bar + black matte; overlay uses colorkey (reliable vs WebM alpha on Windows)
    if out.suffix.lower() not in (".mp4", ".mov"):
        out = out.with_suffix(".mp4")
    job = {
        "composition": "TimedCaptionBar",
        "cues": prepared,
        "accent": accent,
        "theme": theme_resolved,
        "fontSize": font_px,
        "duration": float(duration_sec),
        "width": int(width),
        "height": bar_h,
        "matteBlack": True,
    }
    return _run_job(job, out, timeout_sec=timeout_sec)


def render_timed_side_caption(
    cues: list[dict[str, Any]],
    output_path: Path,
    *,
    accent: str = "#7aa2f7",
    duration_sec: float,
    width: int = 1080,
    height: int = 1920,
    side: str = "right",
    timeout_sec: float = 300.0,
) -> Path:
    """Legacy side strip (unused by short fusion). Prefer render_lipsync_fusion."""
    if not is_available():
        raise RuntimeError("Remotion caption bridge unavailable")
    prepared = _enrich_remotion_cues([c for c in cues if isinstance(c, dict)])
    if not prepared:
        prepared = [{"start": 0.0, "end": float(duration_sec), "text": "…"}]
    side_norm = "left" if (side or "right").strip().lower() == "left" else "right"
    job = {
        "composition": "TimedSideCaption",
        "cues": prepared,
        "accent": accent,
        "side": side_norm,
        "duration": float(duration_sec),
        "width": int(width),
        "height": int(height),
    }
    return _run_job(job, Path(output_path), timeout_sec=timeout_sec)


def render_lipsync_fusion(
    video_path: Path,
    cues: list[dict[str, Any]],
    output_path: Path,
    *,
    accent: str = "#7aa2f7",
    duration_sec: float,
    width: int = 1080,
    height: int = 1920,
    side: str = "right",
    timeout_sec: float | None = None,
) -> Path:
    """One-shot Remotion: lipsync video as Background + side captions. No ffmpeg overlay."""
    if not is_available():
        raise RuntimeError("Remotion caption bridge unavailable")
    video_path = Path(video_path).resolve()
    if not video_path.is_file():
        raise FileNotFoundError(f"lipsync fusion source missing: {video_path}")
    prepared = _enrich_remotion_cues([c for c in cues if isinstance(c, dict)])
    if not prepared:
        prepared = [{"start": 0.0, "end": float(duration_sec), "text": "…"}]
    side_norm = "left" if (side or "right").strip().lower() == "left" else "right"
    # Full-film Remotion can be slow; scale timeout with duration
    if timeout_sec is None:
        timeout_sec = max(300.0, min(3600.0, float(duration_sec) * 45.0 + 120.0))
    job = {
        "composition": "LipsyncFusion",
        "theme": "side",
        "videoSrc": str(video_path),
        "cues": prepared,
        "accent": accent,
        "side": side_norm,
        "duration": float(duration_sec),
        "width": int(width),
        "height": int(height),
    }
    return _run_job(job, Path(output_path), timeout_sec=float(timeout_sec))


def render_timed_caption_still(
    text: str,
    output_path: Path,
    *,
    accent: str = "#FFFFFF",
    theme: str = "bar",
    width: int = 720,
    height: int | None = None,
    timeout_sec: float = 120.0,
    video_src: str | Path | None = None,
    time_sec: float = 0.5,
    caption_side: str = "right",
    subtitle_font_size: int | None = None,
    font_size_px: int | None = None,
    smart_keywords: bool = True,
) -> Path:
    """Render one Remotion caption frame (PNG) for UI preview."""
    if not is_available():
        raise RuntimeError("Remotion caption bridge unavailable")
    theme_raw = (theme or "bar").strip().lower()
    if theme_raw in ("off", "none", "ass", "classic"):
        raise ValueError("remotion theme is off")
    sample = (text or "").strip() or "字幕预览"
    theme_resolved = resolve_remotion_theme(theme_raw, sample)
    fps = 30
    frame_at = max(0, int(round(max(0.0, float(time_sec)) * fps)))
    if _normalize_burn_mode(theme_raw) == "side":
        preview_w = int(width)
        preview_h = int(height) if height else max(320, int(round(preview_w * 16 / 9)))
        side_norm = "left" if (caption_side or "right").strip().lower() == "left" else "right"
        src = str(Path(video_src).resolve()) if video_src and Path(video_src).is_file() else ""
        font_px = int(
            font_size_px
            or _remotion_font_px(subtitle_font_size or 16, preview_w, preview_h)
        )
        preview_cues = _enrich_remotion_cues(
            [{"start": 0, "end": 3, "text": sample[:80]}],
            smart_keywords=smart_keywords,
        )
        job = {
            "composition": "LipsyncFusion",
            "still": True,
            "frame": frame_at if src else 8,
            "cues": preview_cues,
            "accent": accent or "#FFFFFF",
            "theme": "side",
            "side": side_norm,
            "videoSrc": src,
            "fontSize": font_px,
            "duration": max(3.0, float(time_sec) + 2.0),
            "width": preview_w,
            "height": preview_h,
        }
    else:
        bar_h = int(height) if height else _bar_height_for_theme(int(width), theme_resolved)
        font_px = int(
            font_size_px
            or _remotion_font_px(subtitle_font_size or 16, int(width), bar_h)
        )
        preview_cues = _enrich_remotion_cues(
            [{"start": 0, "end": 3, "text": sample[:80]}],
            smart_keywords=smart_keywords,
        )
        job = {
            "composition": "TimedCaptionBar",
            "still": True,
            "frame": 8,
            "cues": preview_cues,
            "accent": accent or "#FFFFFF",
            "theme": theme_resolved,
            "fontSize": font_px,
            "duration": 3,
            "width": int(width),
            "height": bar_h,
        }
    return _run_job(job, Path(output_path), timeout_sec=timeout_sec)


def _overlay_still_png(
    base_still: Path,
    overlay_png: Path,
    output_jpg: Path,
    *,
    ffmpeg_bin: str,
    mode: str = "bar",
    caption_side: str = "right",
) -> Path:
    """Composite a Remotion PNG onto a layout still → JPEG (phone preview)."""
    base_still = Path(base_still)
    overlay_png = Path(overlay_png)
    output_jpg = Path(output_jpg)
    output_jpg.parent.mkdir(parents=True, exist_ok=True)
    burn_mode = _normalize_burn_mode(mode)
    if burn_mode == "side":
        side = "left" if (caption_side or "right").strip().lower() == "left" else "right"
        x_expr = "0" if side == "left" else "main_w-overlay_w"
        vf = f"[0:v][1:v]overlay={x_expr}:0:format=auto"
    else:
        vf = "[0:v][1:v]overlay=0:main_h-overlay_h:format=auto"
    cmd = [
        ffmpeg_bin,
        "-y",
        "-i",
        str(base_still),
        "-i",
        str(overlay_png),
        "-filter_complex",
        vf,
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(output_jpg),
    ]
    subprocess.run(
        cmd,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if not output_jpg.is_file():
        raise RuntimeError("remotion still overlay failed")
    return output_jpg


def compose_remotion_on_layout_still(
    layout_still: Path,
    output_path: Path,
    *,
    text: str,
    remotion_theme: str,
    accent: str = "#FFFFFF",
    ffmpeg_bin: str = "ffmpeg",
    width: int,
    height: int,
    video_path: Path | None = None,
    time_sec: float = 0.5,
    caption_side: str = "right",
    timeout_sec: float = 120.0,
    subtitle_font_size: int | None = None,
    smart_keywords: bool = True,
) -> Path:
    """Put Remotion burn-in look onto the same layout frame used by ASS preview."""
    theme_raw = (remotion_theme or "bar").strip().lower()
    burn_mode = _normalize_burn_mode(theme_raw)
    if burn_mode == "off":
        raise ValueError("remotion theme is off")
    theme_resolved = resolve_remotion_theme(theme_raw, text)
    layout_still = Path(layout_still)
    output_path = Path(output_path)
    work = output_path.parent
    rem_png = work / f"_remotion_preview_{theme_resolved}.png"

    if burn_mode == "side" and video_path and Path(video_path).is_file():
        render_timed_caption_still(
            text,
            rem_png,
            accent=accent,
            theme="side",
            width=width,
            height=height,
            video_src=video_path,
            time_sec=time_sec,
            caption_side=caption_side,
            timeout_sec=timeout_sec,
            subtitle_font_size=subtitle_font_size,
            smart_keywords=smart_keywords,
        )
        from PIL import Image

        Image.open(rem_png).convert("RGB").save(output_path, quality=92)
        return output_path

    # bar / kinetic / pop (or side without video): strip/bar over layout
    bar_h = None if burn_mode == "side" else _bar_height_for_theme(width, theme_resolved)
    render_timed_caption_still(
        text,
        rem_png,
        accent=accent,
        theme=theme_raw if burn_mode != "side" else "side",
        width=width,
        height=height if burn_mode == "side" else bar_h,
        caption_side=caption_side,
        timeout_sec=timeout_sec,
        subtitle_font_size=subtitle_font_size,
        smart_keywords=smart_keywords,
    )
    if burn_mode == "side":
        # Full canvas PNG from fusion placeholder — use as preview directly if no video
        from PIL import Image

        Image.open(rem_png).convert("RGB").save(output_path, quality=92)
        return output_path
    return _overlay_still_png(
        layout_still,
        rem_png,
        output_path,
        ffmpeg_bin=ffmpeg_bin,
        mode=theme_resolved,
        caption_side=caption_side,
    )


def overlay_caption_bar(
    scene_path: Path,
    bar_path: Path,
    output_path: Path,
    *,
    ffmpeg_bin: str = "ffmpeg",
    keep_audio: bool = False,
) -> Path:
    """Stack Remotion caption bar onto the bottom of a video.

    keep_audio=True preserves the main input's audio (final film burn-in).
    Scene cards are usually silent — keep_audio=False strips audio.
    """
    scene_path = Path(scene_path)
    bar_path = Path(bar_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Colorkey remotion black matte so burn matches transparent still preview
    vf = (
        "[1:v]format=rgba,colorkey=0x000000:0.06:0.12[ovr];"
        "[0:v][ovr]overlay=0:main_h-overlay_h:format=auto:shortest=1"
    )
    cmd = [
        ffmpeg_bin,
        "-y",
        "-i",
        str(scene_path),
        "-i",
        str(bar_path),
        "-filter_complex",
        vf,
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "copy" if keep_audio else "aac",
        "-shortest",
        str(output_path),
    ]
    if not keep_audio:
        # Drop audio for silent scene cards
        cmd = [
            ffmpeg_bin,
            "-y",
            "-i",
            str(scene_path),
            "-i",
            str(bar_path),
            "-filter_complex",
            vf,
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            str(output_path),
        ]
    subprocess.run(
        cmd,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if not output_path.is_file():
        raise RuntimeError("caption overlay failed: output missing")
    return output_path


def overlay_caption_side(
    scene_path: Path,
    strip_path: Path,
    output_path: Path,
    *,
    caption_side: str = "right",
    ffmpeg_bin: str = "ffmpeg",
    keep_audio: bool = False,
) -> Path:
    """Stack a side caption strip onto a video (left or right edge).

    keep_audio=True preserves the main input's audio (final film burn-in).
    """
    scene_path = Path(scene_path)
    strip_path = Path(strip_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    side = "left" if (caption_side or "right").strip().lower() == "left" else "right"
    x_expr = "0" if side == "left" else "main_w-overlay_w"
    vf = f"[0:v][1:v]overlay={x_expr}:0:format=auto:shortest=1"
    if keep_audio:
        cmd = [
            ffmpeg_bin,
            "-y",
            "-i",
            str(scene_path),
            "-i",
            str(strip_path),
            "-filter_complex",
            vf,
            "-map",
            "0:a?",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            "-shortest",
            str(output_path),
        ]
    else:
        cmd = [
            ffmpeg_bin,
            "-y",
            "-i",
            str(scene_path),
            "-i",
            str(strip_path),
            "-filter_complex",
            vf,
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            str(output_path),
        ]
    subprocess.run(
        cmd,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if not output_path.is_file():
        raise RuntimeError("caption overlay failed: output missing")
    return output_path


def burn_remotion_on_video(
    video_path: Path,
    cues: list[dict[str, Any]],
    output_path: Path,
    *,
    ffmpeg_bin: str = "ffmpeg",
    remotion_theme: str = "bar",
    accent: str = "#FFFFFF",
    duration_sec: float | None = None,
    probe_bin: str | None = None,
    caption_side: str = "right",
    subtitle_font_size: int | None = None,
    smart_keywords: bool = True,
) -> Path:
    """Burn Remotion timed captions onto a full film (keeps audio)."""
    from pipeline import ffprobe_bin
    from workflow.publish import media_duration, probe_video_dimensions

    theme_raw = (remotion_theme or "bar").strip().lower()
    burn_mode = _normalize_burn_mode(theme_raw)
    if burn_mode == "off":
        raise ValueError("remotion theme is off")
    if not is_available():
        raise RuntimeError("Remotion caption bridge unavailable")

    video_path = Path(video_path)
    output_path = Path(output_path)
    probe = probe_bin or ffprobe_bin(ffmpeg_bin)
    width, height = probe_video_dimensions(probe, video_path)
    dur = float(duration_sec) if duration_sec and duration_sec > 0 else float(media_duration(probe, video_path) or 1.0)

    work = output_path.parent / f"{output_path.stem}_remotion_burn"
    work.mkdir(parents=True, exist_ok=True)
    raw_cues: list[dict[str, Any]] = []
    for c in cues:
        if isinstance(c, dict):
            text = str(c.get("text") or "").strip()
            start = max(0.0, float(c.get("start") or 0))
            end = max(start + 0.35, float(c.get("end") or start + 1))
        else:
            text = str(getattr(c, "text", "") or "").strip()
            start = max(0.0, float(getattr(c, "start", 0) or 0))
            end = max(start + 0.35, float(getattr(c, "end", start + 1) or start + 1))
        if not text:
            continue
        raw_cues.append({"start": start, "end": end, "text": text})
    sample = " ".join(c["text"] for c in raw_cues[:3])
    theme_resolved = resolve_remotion_theme(theme_raw, sample)
    prepared = _enrich_remotion_cues(raw_cues, smart_keywords=smart_keywords)
    if not prepared:
        raise ValueError("no cues for remotion burn")
    font_px = _remotion_font_px(subtitle_font_size or 16, width, height)

    if burn_mode == "side":
        # One Composition: OffthreadVideo background + AbsoluteFill captions (no side-strip overlay)
        return render_lipsync_fusion(
            video_path,
            prepared,
            output_path,
            accent=accent or "#FFFFFF",
            duration_sec=dur,
            width=width,
            height=height,
            side=caption_side,
        )

    # WebM alpha was unreliable on Windows — black matte MP4 + colorkey
    bar = work / "caption_bar.mp4"
    bar_h = _bar_height_for_theme(width, theme_resolved)
    render_timed_caption_bar(
        prepared,
        bar,
        accent=accent or "#FFFFFF",
        duration_sec=dur,
        width=width,
        height=bar_h,
        theme=theme_raw,
        font_size_px=font_px,
        smart_keywords=smart_keywords,
    )
    return overlay_caption_bar(video_path, bar, output_path, ffmpeg_bin=ffmpeg_bin, keep_audio=True)


def maybe_overlay_timed_captions(
    scene_path: Path,
    cues: list[dict[str, Any]],
    *,
    accent: str = "#7aa2f7",
    duration_sec: float,
    width: int,
    ffmpeg_bin: str = "ffmpeg",
    remotion_theme: str = "bar",
    subtitle_font_size: int | None = None,
    smart_keywords: bool = True,
) -> Path:
    """If Remotion is available, overlay a timed caption bar; else return scene unchanged."""
    theme_raw = (remotion_theme or "bar").strip().lower()
    if theme_raw in ("off", "none", "0", "false"):
        return Path(scene_path)
    if not is_available() or not cues:
        return Path(scene_path)
    scene_path = Path(scene_path)
    work = scene_path.parent / f"{scene_path.stem}_remotion"
    work.mkdir(parents=True, exist_ok=True)
    bar = work / "caption_bar.mp4"
    out = work / f"{scene_path.stem}_with_captions.mp4"
    theme_resolved = resolve_remotion_theme(
        theme_raw,
        str(cues[0].get("text") or "") if isinstance(cues[0], dict) else "",
    )
    bar_h = _bar_height_for_theme(width, theme_resolved)
    font_px = _remotion_font_px(subtitle_font_size or 16, width, bar_h)
    try:
        render_timed_caption_bar(
            cues,
            bar,
            accent=accent,
            duration_sec=duration_sec,
            width=width,
            height=bar_h,
            theme=theme_raw,
            font_size_px=font_px,
            smart_keywords=smart_keywords,
        )
        overlay_caption_bar(scene_path, bar, out, ffmpeg_bin=ffmpeg_bin)
        shutil.copy2(out, scene_path)
        return scene_path
    except Exception:
        log.exception("Remotion caption overlay skipped; keeping HyperFrames scene")
        return scene_path

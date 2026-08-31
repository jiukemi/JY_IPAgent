"""Bridge to official HeyGen HyperFrames CLI (tools/hf-bridge)."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
HF_BRIDGE = REPO_ROOT / "tools" / "hf-bridge"
RENDER_JS = HF_BRIDGE / "render.mjs"


def _engine_mode() -> str:
    return (os.environ.get("AGENT_HF_ENGINE") or "auto").strip().lower()


def _quality() -> str:
    q = (os.environ.get("AGENT_HF_QUALITY") or "standard").strip().lower()
    return q if q in ("draft", "standard", "high") else "standard"


def is_available() -> bool:
    mode = _engine_mode()
    if mode in ("pil", "legacy", "off", "0", "false"):
        return False
    if mode == "official":
        return RENDER_JS.is_file()
    if not RENDER_JS.is_file():
        return False
    return shutil.which("node") is not None and shutil.which("npx") is not None


def _rgb_hex(rgb: tuple[int, int, int] | list[int]) -> str:
    r, g, b = (int(rgb[0]), int(rgb[1]), int(rgb[2]))
    return f"#{r:02x}{g:02x}{b:02x}"


def _title_html(text: str) -> str:
    from workflow.hyperframes_scenes import colorize_line_html, _split_lines

    lines = _split_lines(text, 12, landscape=False)
    if not lines:
        return "…"
    parts = [colorize_line_html(ln, i) for i, ln in enumerate(lines[:3])]
    return "<br/>".join(parts)


def _theme_colors(theme: dict) -> dict[str, str]:
    return {
        "top": _rgb_hex(theme["top"]),
        "bottom": _rgb_hex(theme["bottom"]),
        "textColor": _rgb_hex(theme["text"]),
        "accent": _rgb_hex(theme["accent_bar"]),
        "outline": _rgb_hex(theme.get("outline") or theme["accent_bar"]),
    }


def _run_job(job: dict[str, Any], output_path: Path, *, timeout_sec: float) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    job = {**job, "output": str(output_path.resolve()), "quality": job.get("quality") or _quality()}
    with tempfile.TemporaryDirectory(prefix="hf_job_") as tmp:
        job_path = Path(tmp) / "job.json"
        # Copy bg image into temp so Node can read a stable path
        bg = job.get("bgImage")
        if bg and Path(bg).is_file():
            dest = Path(tmp) / "bg.png"
            shutil.copy2(bg, dest)
            job["bgImage"] = str(dest.resolve())
        job_path.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
        cmd = ["node", str(RENDER_JS), str(job_path)]
        log.info("hf_official render: %s (quality=%s)", " ".join(cmd), job["quality"])
        proc = subprocess.run(
            cmd,
            cwd=str(HF_BRIDGE),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
            env={**os.environ, "HYPERFRAMES_SKIP_SKILLS": "1"},
        )
        if proc.stdout:
            log.debug(proc.stdout[-2000:])
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "")[-2500:]
            raise RuntimeError(f"hf-bridge render failed ({proc.returncode}): {err}")
        if not output_path.is_file():
            raise RuntimeError("hf-bridge finished but output missing")
    return output_path


def _pack_extras(
    theme: dict,
    *,
    width: int,
    height: int,
    style_pack: dict | None,
    work: Path,
) -> dict[str, Any]:
    from workflow.scene_style_pack import font_css, normalize_style_pack, resolve_background_for_job

    pack = normalize_style_pack(style_pack or {})
    extras: dict[str, Any] = {
        "fontFamily": font_css(pack["font_id"]),
        "fontId": pack["font_id"],
        "fontScale": float(pack.get("font_scale") or 1.0),
        "bgMode": pack["bg_mode"],
    }
    bg = resolve_background_for_job(
        work,
        pack=pack,
        theme={**theme, "id": pack.get("theme", "")},
        width=width,
        height=height,
    )
    if bg and bg.is_file():
        extras["bgImage"] = str(bg.resolve())
    return extras


def render_scene(
    text: str,
    output_path: Path,
    *,
    layout: str = "kinetic",
    theme: dict,
    duration_sec: float = 4.0,
    width: int = 1080,
    height: int = 1920,
    timeout_sec: float = 240.0,
    quality: str | None = None,
    style_pack: dict | None = None,
) -> Path:
    if not is_available():
        raise RuntimeError("official HyperFrames bridge unavailable")

    colors = _theme_colors(theme)
    with tempfile.TemporaryDirectory(prefix="hf_bg_") as bg_tmp:
        extras = _pack_extras(theme, width=width, height=height, style_pack=style_pack, work=Path(bg_tmp))
        job = {
            "text": text,
            "textHtml": _title_html(text),
            "layout": (layout or "kinetic").lower().replace("-", "_"),
            "duration": float(duration_sec),
            "width": int(width),
            "height": int(height),
            "quality": quality or _quality(),
            **colors,
            **extras,
        }
        return _run_job(job, Path(output_path), timeout_sec=timeout_sec)


def render_scene_beats(
    beats: list[dict[str, Any]],
    output_path: Path,
    *,
    layout: str = "kinetic",
    theme: dict,
    duration_sec: float,
    width: int = 1080,
    height: int = 1920,
    timeout_sec: float = 360.0,
    quality: str | None = None,
    style_pack: dict | None = None,
) -> Path:
    if not is_available():
        raise RuntimeError("official HyperFrames bridge unavailable")
    if not beats:
        raise ValueError("beats required")

    prepared: list[dict[str, Any]] = []
    for b in beats:
        text = str(b.get("text") or "").strip() or "…"
        prepared.append(
            {
                "t0": float(b.get("t0") or 0),
                "t1": float(b.get("t1") or 0),
                "text": text,
                "html": b.get("html") or _title_html(text),
            }
        )
    colors = _theme_colors(theme)
    with tempfile.TemporaryDirectory(prefix="hf_bg_") as bg_tmp:
        extras = _pack_extras(theme, width=width, height=height, style_pack=style_pack, work=Path(bg_tmp))
        job = {
            "text": prepared[0]["text"],
            "textHtml": prepared[0]["html"],
            "beats": prepared,
            "layout": (layout or "kinetic").lower().replace("-", "_"),
            "duration": float(duration_sec),
            "width": int(width),
            "height": int(height),
            "quality": quality or _quality(),
            **colors,
            **extras,
        }
        return _run_job(job, Path(output_path), timeout_sec=timeout_sec)

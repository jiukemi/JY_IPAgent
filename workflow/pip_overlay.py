"""Picture-in-picture overlay for publish pipeline."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from pipeline import IMAGE_EXTENSIONS, is_image_path

PIP_POSITIONS = {
    "top_right": "W-w-{m}:{m}",
    "top_left": "{m}:{m}",
    "bottom_right": "W-w-{m}:H-h-{m}",
    "bottom_left": "{m}:H-h-{m}",
    "center": "(W-w)/2:(H-h)/2",
    "fullscreen": "0:0",
}


@dataclass
class TimedPipJob:
    start: float
    end: float
    media_path: Path
    position: str = "center"
    scale: float = 0.28
    margin: int = 24
    play_full_video: bool = False
    display_duration: float | None = None
    source_start: float = 0.0
    crop: dict | None = None  # normalized {x,y,w,h} in 0..1
    key_black: bool = False  # fusion: colorkey black before overlay


def _is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS or is_image_path(path)


def _crop_vf(crop: dict | None) -> str:
    """Build ffmpeg crop filter from normalized box {x,y,w,h} (0..1)."""
    if not isinstance(crop, dict):
        return ""
    try:
        x = max(0.0, min(1.0, float(crop.get("x", 0))))
        y = max(0.0, min(1.0, float(crop.get("y", 0))))
        w = max(0.05, min(1.0 - x, float(crop.get("w", 1))))
        h = max(0.05, min(1.0 - y, float(crop.get("h", 1))))
    except (TypeError, ValueError):
        return ""
    return (
        f"crop=trunc(iw*{w}/2)*2:trunc(ih*{h}/2)*2:"
        f"trunc(iw*{x}/2)*2:trunc(ih*{y}/2)*2"
    )


def _scale_vf(crop: dict | None = None) -> str:
    crop_part = _crop_vf(crop)
    base = "scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p"
    return f"{crop_part},{base}" if crop_part else base


def image_to_video(
    ffmpeg_bin: str,
    image_path: Path,
    duration: float,
    output_path: Path,
    fps: int = 25,
    *,
    crop: dict | None = None,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            ffmpeg_bin,
            "-y",
            "-loop",
            "1",
            "-i",
            str(image_path),
            "-t",
            f"{max(duration, 0.35):.3f}",
            "-r",
            str(fps),
            "-vf",
            _scale_vf(crop),
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


def fit_video_duration(
    ffmpeg_bin: str,
    video_path: Path,
    duration: float,
    output_path: Path,
    *,
    source_start: float = 0.0,
    crop: dict | None = None,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ss = max(0.0, float(source_start or 0))
    subprocess.run(
        [
            ffmpeg_bin,
            "-y",
            "-ss",
            f"{ss:.3f}",
            "-stream_loop",
            "-1",
            "-i",
            str(video_path),
            "-t",
            f"{max(duration, 0.35):.3f}",
            "-vf",
            _scale_vf(crop),
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


def video_to_standard(
    ffmpeg_bin: str,
    video_path: Path,
    output_path: Path,
    *,
    source_start: float = 0.0,
    crop: dict | None = None,
) -> Path:
    """Re-encode video from source_start keeping remaining natural duration."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ss = max(0.0, float(source_start or 0))
    subprocess.run(
        [
            ffmpeg_bin,
            "-y",
            "-ss",
            f"{ss:.3f}",
            "-i",
            str(video_path),
            "-vf",
            _scale_vf(crop),
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


def prepare_pip_source(
    ffmpeg_bin: str,
    probe_bin: str,
    pip_path: Path,
    main_duration: float,
    work_dir: Path,
) -> Path:
    ext = pip_path.suffix.lower()
    out = work_dir / "pip_source.mp4"
    if ext in IMAGE_EXTENSIONS or is_image_path(pip_path):
        return image_to_video(ffmpeg_bin, pip_path, main_duration, out)
    return fit_video_duration(ffmpeg_bin, pip_path, main_duration, out)


def _media_duration(probe_bin: str, path: Path) -> float:
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


def _pip_scale_expr(position: str, scale: float) -> str:
    if position == "fullscreen":
        return "scale=iw:ih"
    scale = max(0.08, min(0.55, float(scale)))
    scale_w = f"trunc(iw*{scale}/2)*2"
    return f"scale={scale_w}:-2"


def _pip_scale_on_canvas(scale: float, canvas_w: int) -> str:
    """Scale lecturer to a fraction of canvas width (predictable 20% on landscape)."""
    scale = max(0.08, min(0.55, float(scale)))
    tw = max(2, int(round(max(canvas_w, 2) * scale) / 2) * 2)
    return f"scale={tw}:-2"


def _pip_face_filter(
    position: str,
    scale: float,
    *,
    key_white: bool = True,
    key_black: bool = False,
    canvas_width: int | None = None,
    crop_filter: str | None = None,
) -> str:
    """Scale stream; optionally crop first, then key near-white/black backgrounds."""
    parts: list[str] = []
    if crop_filter:
        parts.append(crop_filter)
    if position == "fullscreen":
        # Cover-fit onto main canvas when W/H known; else keep stream size
        if canvas_width:
            # scale handled by caller with cover filter; keep passthrough here
            parts.append("scale=iw:ih")
        else:
            parts.append("scale=iw:ih")
    elif canvas_width:
        parts.append(_pip_scale_on_canvas(scale, canvas_width))
    else:
        parts.append(_pip_scale_expr(position, scale))
    parts.append("format=rgba")
    # Fusion overlays: colorkey even when fullscreen (black canvas → transparent)
    if key_black:
        # Tight key — loose similarity eats frosted glass / text anti-alias → 掉色掉漆
        parts.append("colorkey=0x000000:0.012:0.04")
        parts.append("unsharp=5:5:0.7:5:5:0.0")
    elif position != "fullscreen" and key_white:
        parts.append("colorkey=0xFFFFFF:0.10:0.05")
    return ",".join(parts)


def _pip_xy(position: str, margin: int) -> str:
    margin = max(0, int(margin))
    return PIP_POSITIONS.get(position, PIP_POSITIONS["top_right"]).format(m=margin)


def _video_size(probe_bin: str, path: Path) -> tuple[int, int]:
    result = subprocess.run(
        [
            probe_bin,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0:s=x",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    w, h = result.stdout.strip().split("x")
    return int(w), int(h)


def _cover_scale_filter(width: int, height: int) -> str:
    w, h = int(width), int(height)
    return (
        f"scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h}:(iw-{w})/2:(ih-{h})/2"
    )


def solid_color_video(
    ffmpeg_bin: str,
    width: int,
    height: int,
    duration: float,
    output_path: Path,
    *,
    color: str = "0x141820",
    fps: int = 25,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            ffmpeg_bin,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s={width}x{height}:r={fps}",
            "-t",
            f"{max(duration, 0.35):.3f}",
            "-pix_fmt",
            "yuv420p",
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


def _fit_video_cover(
    ffmpeg_bin: str,
    src: Path,
    dest: Path,
    width: int,
    height: int,
) -> Path:
    """Re-encode clip to canvas with centered cover-fit (opaque fullscreen PiP)."""
    cover = _cover_scale_filter(width, height)
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            ffmpeg_bin,
            "-y",
            "-i",
            str(src),
            "-vf",
            f"{cover},format=yuv420p",
            "-c:v",
            "libx264",
            "-crf",
            "20",
            "-an",
            str(dest),
        ],
        check=True,
    )
    return dest


def _prepare_timed_clip(
    ffmpeg_bin: str,
    probe_bin: str,
    job: TimedPipJob,
    work_dir: Path,
    index: int,
) -> tuple[Path, float, float]:
    """Return prepared clip, overlay start, overlay end."""
    prep_dir = work_dir / f"job_{index}"
    prep_dir.mkdir(parents=True, exist_ok=True)
    out = prep_dir / "clip.mp4"
    window = max(0.35, float(job.end) - float(job.start))
    is_image = _is_image(job.media_path)

    if is_image:
        show_dur = float(job.display_duration) if job.display_duration else window
        show_dur = max(0.35, min(show_dur, window))
        # Prefer covering the cue window so scenes don't vanish mid-sentence
        if show_dur + 0.05 < window:
            show_dur = window
        image_to_video(ffmpeg_bin, job.media_path, show_dur, out, crop=job.crop)
        return out, float(job.start), float(job.start) + show_dur

    src_start = max(0.0, float(job.source_start or 0))
    # PiP videos: no spatial crop — only scale by position/size (keep aspect). Crop is image-only.
    if job.play_full_video:
        src_dur = max(0.0, _media_duration(probe_bin, job.media_path) - src_start)
        # Short HyperFrame clips (~1–2.5s) must cover the full cue span, or scenes look incomplete
        if src_dur + 0.08 < window:
            fit_video_duration(
                ffmpeg_bin,
                job.media_path,
                window,
                out,
                source_start=src_start,
                crop=None,
            )
            return out, float(job.start), float(job.end)
        video_to_standard(
            ffmpeg_bin,
            job.media_path,
            out,
            source_start=src_start,
            crop=None,
        )
        src_dur = _media_duration(probe_bin, out)
        return out, float(job.start), float(job.start) + src_dur

    fit_video_duration(
        ffmpeg_bin,
        job.media_path,
        window,
        out,
        source_start=src_start,
        crop=None,
    )
    return out, float(job.start), float(job.end)


def apply_picture_in_picture(
    ffmpeg_bin: str,
    main_video: Path,
    pip_video: Path,
    output_path: Path,
    *,
    position: str = "top_right",
    scale: float = 0.28,
    margin: int = 24,
) -> Path:
    scale_expr = _pip_face_filter(position, scale)
    xy = _pip_xy(position, margin)
    filt = f"[1:v]{scale_expr}[pip];[0:v][pip]overlay={xy}:shortest=1"
    subprocess.run(
        [
            ffmpeg_bin,
            "-y",
            "-i",
            str(main_video),
            "-i",
            str(pip_video),
            "-filter_complex",
            filt,
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


def apply_timed_pip_overlays(
    ffmpeg_bin: str,
    probe_bin: str,
    main_video: Path,
    jobs: list[TimedPipJob],
    output_path: Path,
    *,
    work_dir: Path,
    default_position: str = "top_right",
    default_scale: float = 0.28,
    default_margin: int = 24,
    key_black: bool = False,
) -> Path:
    """Overlay PiP clips during configurable time windows."""
    if not jobs:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(main_video, output_path)
        return output_path

    main_w, main_h = _video_size(probe_bin, main_video)

    inputs = [str(main_video)]
    prepared: list[tuple[Path, float, float, TimedPipJob]] = []
    for i, job in enumerate(jobs):
        clip, o_start, o_end = _prepare_timed_clip(ffmpeg_bin, probe_bin, job, work_dir, i)
        pos = (job.position or default_position).strip() or default_position
        use_key = bool(key_black or getattr(job, "key_black", False))
        if use_key:
            pos = "fullscreen"
        if pos == "fullscreen":
            fit_dir = work_dir / f"job_{i}"
            fitted = fit_dir / "canvas_fit.mp4"
            try:
                clip = _fit_video_cover(ffmpeg_bin, clip, fitted, main_w, main_h)
            except subprocess.CalledProcessError:
                pass
        prepared.append((clip, o_start, o_end, job))
        inputs.append(str(clip))

    filter_parts: list[str] = []
    current = "[0:v]"
    for i, (_, o_start, o_end, job) in enumerate(prepared):
        pos = job.position or default_position
        scale = job.scale if job.scale else default_scale
        margin = job.margin if job.margin is not None else default_margin
        use_key = bool(key_black or getattr(job, "key_black", False))
        # Fusion: full-frame colorkey so designed font size is preserved
        if use_key:
            pos = "fullscreen"
            scale = 1.0
            scale_expr = "format=rgba,colorkey=0x000000:0.012:0.04,unsharp=5:5:0.7:5:5:0.0"
        elif pos == "fullscreen":
            scale_expr = "format=yuv420p"
        else:
            scale_expr = _pip_face_filter(pos, scale, key_white=not use_key, key_black=use_key)
        xy = _pip_xy(pos, margin)
        pip_label = f"[pip{i}]"
        out_label = "[vout]" if i == len(prepared) - 1 else f"[v{i}]"
        enable = f"enable='between(t,{o_start:.3f},{o_end:.3f})'"
        filter_parts.append(f"[{i + 1}:v]{scale_expr}{pip_label}")
        filter_parts.append(f"{current}{pip_label}overlay={xy}:{enable}{out_label}")
        current = out_label

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg_bin, "-y"]
    for inp in inputs:
        cmd += ["-i", inp]
    cmd += [
        "-filter_complex",
        ";".join(filter_parts),
        "-map",
        "[vout]",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-crf",
        "20",
        "-c:a",
        "copy",
        str(output_path),
    ]
    subprocess.run(cmd, check=True)
    return output_path


def apply_education_layout(
    ffmpeg_bin: str,
    probe_bin: str,
    background_video: Path,
    lecturer_video: Path,
    output_path: Path,
    *,
    position: str = "bottom_right",
    scale: float = 0.28,
    margin: int = 24,
    canvas_width: int | None = None,
    canvas_height: int | None = None,
    lecturer_crop_filter: str | None = None,
) -> Path:
    """网课布局：讲解素材全屏，口播缩到角落；音频取自口播。"""
    if canvas_width and canvas_height:
        width, height = int(canvas_width), int(canvas_height)
    else:
        width, height = _video_size(probe_bin, lecturer_video)
    cover = _cover_scale_filter(width, height)
    # Studio white BG keyed carefully so HyperFrame scene shows around avatar (not punched face)
    scale_expr = _pip_face_filter(
        position,
        scale,
        key_white=True,
        canvas_width=width,
        crop_filter=lecturer_crop_filter,
    )
    xy = _pip_xy(position, margin)
    filt = (
        f"[0:v]{cover}[bg];"
        f"[1:v]{scale_expr}[face];"
        f"[bg][face]overlay={xy}:shortest=1[out]"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            ffmpeg_bin,
            "-y",
            "-i",
            str(background_video),
            "-i",
            str(lecturer_video),
            "-filter_complex",
            filt,
            "-map",
            "[out]",
            "-map",
            "1:a?",
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


def apply_education_timed_layout(
    ffmpeg_bin: str,
    probe_bin: str,
    lecturer_video: Path,
    jobs: list[TimedPipJob],
    output_path: Path,
    *,
    work_dir: Path,
    base_video: Path | None = None,
    position: str = "bottom_right",
    scale: float = 0.28,
    margin: int = 24,
    canvas_width: int | None = None,
    canvas_height: int | None = None,
    lecturer_crop_filter: str | None = None,
) -> Path:
    """网课分镜：讲解页按时间轴叠层（全屏或画中画槽位）。

    层序硬约束（cover）：底图 → 主体内容 jobs → 人物口播画中画置顶（最后 overlay）。
    全屏内容也不得压过口播角窗。
    """
    if not jobs:
        if base_video is not None:
            return apply_education_layout(
                ffmpeg_bin,
                probe_bin,
                base_video,
                lecturer_video,
                output_path,
                position=position,
                scale=scale,
                margin=margin,
                canvas_width=canvas_width,
                canvas_height=canvas_height,
                lecturer_crop_filter=lecturer_crop_filter,
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(lecturer_video, output_path)
        return output_path

    if canvas_width and canvas_height:
        width, height = int(canvas_width), int(canvas_height)
    else:
        width, height = _video_size(probe_bin, lecturer_video)
    cover = _cover_scale_filter(width, height)
    duration = _media_duration(probe_bin, lecturer_video)

    inputs: list[str] = []
    filter_parts: list[str] = []

    if base_video is not None:
        inputs.append(str(base_video))
        filter_parts.append(f"[0:v]{cover}[base]")
        current = "[base]"
        lecturer_input = 1
    else:
        placeholder = work_dir / "education_base.mp4"
        solid_color_video(ffmpeg_bin, width, height, duration, placeholder)
        inputs.append(str(placeholder))
        filter_parts.append(f"[0:v]{cover}[base]")
        current = "[base]"
        lecturer_input = 1

    inputs.append(str(lecturer_video))

    prepared: list[tuple[Path, float, float, TimedPipJob]] = []
    for i, job in enumerate(jobs):
        clip, o_start, o_end = _prepare_timed_clip(ffmpeg_bin, probe_bin, job, work_dir, i)
        prepared.append((clip, o_start, o_end, job))
        inputs.append(str(clip))

    for i, (_, o_start, o_end, job) in enumerate(prepared):
        content_idx = lecturer_input + 1 + i
        out_label = "[vout]" if i == len(prepared) - 1 else f"[v{i}]"
        enable = f"enable='between(t,{o_start:.3f},{o_end:.3f})'"
        job_pos = (job.position or "fullscreen").strip() or "fullscreen"
        use_key = bool(getattr(job, "key_black", False))
        # Fusion: full-canvas transparent overlay (font size matches design); never shrink as PiP
        if use_key:
            job_pos = "fullscreen"
        if job_pos == "fullscreen":
            if use_key:
                filter_parts.append(
                    f"[{content_idx}:v]{cover},format=rgba,"
                    f"colorkey=0x000000:0.012:0.04,unsharp=5:5:0.7:5:5:0.0[full{i}]"
                )
            else:
                filter_parts.append(f"[{content_idx}:v]{cover}[full{i}]")
            filter_parts.append(f"{current}[full{i}]overlay=0:0:{enable}{out_label}")
        else:
            job_scale = float(job.scale) if job.scale else 0.32
            job_margin = int(job.margin) if job.margin is not None else margin
            content_scale = _pip_face_filter(
                job_pos,
                job_scale,
                key_white=False,
                key_black=use_key,
                canvas_width=width,
            )
            content_xy = _pip_xy(job_pos, job_margin)
            filter_parts.append(f"[{content_idx}:v]{content_scale}[pip{i}]")
            filter_parts.append(
                f"{current}[pip{i}]overlay={content_xy}:{enable}{out_label}"
            )
        current = out_label

    # Lecturer PiP always last → topmost (网课 cover 硬约束)
    scale_expr = _pip_face_filter(
        position,
        scale,
        key_white=True,
        canvas_width=width,
        crop_filter=lecturer_crop_filter,
    )
    xy = _pip_xy(position, margin)
    filter_parts.append(
        f"[{lecturer_input}:v]{scale_expr}[face];"
        f"{current}[face]overlay={xy}[vo]"
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg_bin, "-y"]
    for inp in inputs:
        cmd += ["-i", inp]
    cmd += [
        "-filter_complex",
        ";".join(filter_parts),
        "-map",
        "[vo]",
        "-map",
        f"{lecturer_input}:a?",
        "-c:v",
        "libx264",
        "-crf",
        "20",
        "-c:a",
        "copy",
        str(output_path),
    ]
    subprocess.run(cmd, check=True)
    return output_path

"""Avatar step: HeyGem (旗博士同款) with SadTalker fallback."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from avatar.catalog import get_avatar
from avatar.heygem import generate_video as heygem_generate
from pipeline import apply_lipsync_quality, run_pipeline, run_sadtalker
from workflow.deployment import is_cloud

ProgressFn = Callable[[float, str], None]


def _prepare_audio_16k(cfg: dict, audio_path: Path, work_dir: Path, name: str) -> Path:
    from pipeline import ensure_ffmpeg, normalize_audio

    out = work_dir / name
    ffmpeg = ensure_ffmpeg(cfg.get("paths", {}).get("ffmpeg", "ffmpeg"))
    normalize_audio(ffmpeg, audio_path, out)
    return out


def run_avatar_video(
    cfg: dict,
    *,
    audio_path: Path,
    work_dir: Path,
    backend: str,
    source_image: Path | None = None,
    avatar_id: str | None = None,
    output_name: str = "digital_lipsync.mp4",
    quality: str | None = None,
    sadtalker_overrides: dict | None = None,
    on_progress: ProgressFn | None = None,
) -> Path:
    if is_cloud(cfg, "avatar"):
        raise NotImplementedError(
            "云端数字人尚未接入。请使用本地 HeyGem/SadTalker，"
            "或等待火山单图音频驱动 API 接入。"
        )

    cfg = apply_lipsync_quality(cfg, quality)
    backend = (backend or cfg.get("lipsync", {}).get("digital_backend") or "heygem").lower()
    work_dir.mkdir(parents=True, exist_ok=True)
    final_path = work_dir / output_name

    if backend == "heygem":
        model_video: Path | None = None
        if avatar_id:
            entry = get_avatar(avatar_id)
            if entry:
                if entry.source_kind == "portrait":
                    raise ValueError(
                        f"形象「{entry.name}」是 AI/肖像类型，请改用 SadTalker，"
                        "或注册约 10 秒 HeyGem 参考视频。"
                    )
                if entry.reference_video and Path(entry.reference_video).exists():
                    model_video = Path(entry.reference_video)
        if model_video is None and source_image is not None:
            raise ValueError(
                "HeyGem 需要约 10 秒参考视频（非静态图）。"
                "请在数字人库注册参考视频，或改用 SadTalker + 肖像。"
            )
        if model_video is None:
            raise ValueError("请选择 HeyGem 数字人（参考视频类型），或上传参考视频到形象库")

        audio_use = _prepare_audio_16k(cfg, audio_path, work_dir, "heygem_audio_16k.wav")
        raw = work_dir / "heygem_raw.mp4"
        heygem_generate(cfg, audio_use, model_video, raw, on_progress=on_progress)
        import shutil

        shutil.copy2(raw, final_path)
        return final_path

    if backend == "sadtalker":
        prog = on_progress or (lambda _p, _m: None)
        prog(0.08, "SadTalker 准备…")
        if source_image is None and avatar_id:
            entry = get_avatar(avatar_id)
            if entry and entry.reference_image and Path(entry.reference_image).exists():
                source_image = Path(entry.reference_image)
            elif entry and entry.source_kind == "video":
                raise ValueError(
                    f"形象「{entry.name}」是视频类型，HeyGem 专用；"
                    "SadTalker 请选择肖像形象，或上传肖像图片。"
                )
        if source_image is None:
            raise ValueError("SadTalker 需要肖像图：请选择肖像数字人或上传图片")

        from pipeline import load_config

        cfg_full = cfg if "paths" in cfg else load_config(Path("config.yaml"))
        audio_wav = _prepare_audio_16k(cfg_full, audio_path, work_dir, "sadtalker_audio_16k.wav")

        st_dir = Path(cfg_full["paths"].get("sadtalker_dir", "tools/SadTalker"))
        raw_out = work_dir / "sadtalker_raw.mp4"
        run_sadtalker(
            st_dir,
            source_image,
            audio_wav,
            raw_out,
            cfg_full,
            on_progress=on_progress,
            overrides=sadtalker_overrides,
        )
        import shutil

        shutil.copy2(raw_out, final_path)
        return final_path

    return run_pipeline(
        None,
        audio_path,
        work_dir=work_dir,
        backend=backend,
        source_image=source_image,
        output_name=output_name,
        quality=quality,
        sadtalker_overrides=sadtalker_overrides,
        on_progress=on_progress,
    )

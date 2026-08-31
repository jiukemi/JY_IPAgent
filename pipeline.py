"""
Core lip-sync pipeline: video/image + local audio -> final mp4.

Backends: LatentSync 1.6 | SadTalker | HeyGem (via providers).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from tts.progress import emit, run_cmd_with_progress, stage_label
from workflow.bundle_paths import normalize_config_paths, project_root

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv", ".m4v", ".avi"}


def media_kind(path: Path | str) -> str:
    ext = Path(path).suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    raise ValueError(f"不支持的素材格式: {ext}（支持图片 jpg/png/webp 或视频 mp4/mov 等）")


def is_image_path(path: Path | str) -> bool:
    return media_kind(path) == "image"


def default_backend_for_media(path: Path | str) -> str:
    """Image → digital (SadTalker); video → real footage (LatentSync)."""
    return "sadtalker" if is_image_path(path) else "latentsync"


def load_config(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(
            f"Missing {path}. Copy config.example.yaml to config.yaml first."
        )
    with path.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return normalize_config_paths(cfg, project_root())


def run(cmd: list[str], cwd: Path | None = None, env: dict | None = None) -> None:
    print("$", " ".join(str(c) for c in cmd))
    subprocess.run(cmd, check=True, cwd=cwd, env=env)


def ensure_ffmpeg(ffmpeg_bin: str) -> str:
    resolved = shutil.which(ffmpeg_bin)
    if resolved is None:
        raise RuntimeError("ffmpeg not found in PATH")
    return resolved


def normalize_audio(ffmpeg_bin: str, audio_path: Path, wav_path: Path) -> None:
    if audio_path.resolve() == wav_path.resolve():
        return
    run(
        [
            ffmpeg_bin,
            "-y",
            "-i",
            str(audio_path),
            "-ac",
            "1",
            "-ar",
            "16000",
            str(wav_path),
        ]
    )


def ffprobe_bin(ffmpeg_bin: str) -> str:
    if Path(ffmpeg_bin).name.lower().startswith("ffmpeg"):
        candidate = str(Path(ffmpeg_bin).with_name("ffprobe.exe"))
        if Path(candidate).exists():
            return candidate
        candidate = str(Path(ffmpeg_bin).with_name("ffprobe"))
        if Path(candidate).exists():
            return candidate
    resolved = shutil.which("ffprobe")
    if resolved:
        return resolved
    raise RuntimeError("ffprobe not found in PATH")


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


def transcode_to_web_mp4(ffmpeg_bin: str, src: Path, dst: Path) -> Path:
    """SadTalker/OpenCV 默认 mp4v，浏览器常只播音频；转为 H.264+AAC 便于预览。"""
    ffmpeg = ensure_ffmpeg(ffmpeg_bin)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(".web.tmp.mp4")
    run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(src),
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(tmp),
        ]
    )
    if dst.exists() and dst.resolve() != tmp.resolve():
        dst.unlink()
    tmp.replace(dst)
    return dst


def prepare_video_for_lipsync(
    ffmpeg_bin: str,
    video_path: Path,
    audio_path: Path,
    out_path: Path,
    fps: int,
) -> dict:
    """Match video length to audio and normalize fps (avoids LatentSync loop-artifacts)."""
    probe = ffprobe_bin(ffmpeg_bin)
    audio_dur = media_duration(probe, audio_path)
    video_dur = media_duration(probe, video_path)
    margin = 0.08
    note = ""
    cmd = [ffmpeg_bin, "-y", "-i", str(video_path)]
    if video_dur + margin < audio_dur:
        pad = max(0.0, audio_dur - video_dur)
        cmd += ["-vf", f"tpad=stop_mode=clone:stop_duration={pad:.3f}"]
        note = f"视频偏短（{video_dur:.1f}s < 配音 {audio_dur:.1f}s），已定格延长"
    elif video_dur - margin > audio_dur:
        cmd += ["-t", f"{audio_dur:.6f}"]
        note = f"视频偏长（{video_dur:.1f}s > 配音 {audio_dur:.1f}s），已裁剪对齐"
    else:
        note = f"音视频时长已对齐（约 {audio_dur:.1f}s）"
    cmd += [
        "-r",
        str(fps),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-an",
        str(out_path),
    ]
    run(cmd)
    return {
        "audio_sec": audio_dur,
        "video_sec": video_dur,
        "note": note,
    }


def venv_python(root: Path) -> str:
    win = root / "venv" / "Scripts" / "python.exe"
    if win.exists():
        return str(win)
    unix = root / "venv" / "bin" / "python"
    if unix.exists():
        return str(unix)
    return sys.executable


def _apply_cuda_alloc_conf(env: dict, *, legacy_torch: bool = False) -> None:
    """PyTorch 2.0.x (SadTalker) rejects expandable_segments.

    Only newer stacks (e.g. LatentSync torch 2.7+) understand that option.
    """
    key = "PYTORCH_CUDA_ALLOC_CONF"
    if legacy_torch:
        raw = env.get(key, "")
        if raw:
            parts = [
                p.strip()
                for p in raw.split(",")
                if p.strip() and not p.strip().startswith("expandable_segments")
            ]
            if parts:
                env[key] = ",".join(parts)
            else:
                env.pop(key, None)
        else:
            env.pop(key, None)
        return
    env.setdefault(key, "expandable_segments:True")


def hf_env(*, legacy_torch: bool = False) -> dict:
    env = os.environ.copy()
    _apply_cuda_alloc_conf(env, legacy_torch=legacy_torch)
    if os.environ.get("AGENT_OFFLINE", "").strip() in ("1", "true", "yes"):
        env["HF_HUB_OFFLINE"] = "1"
        env["TRANSFORMERS_OFFLINE"] = "1"
    else:
        env.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    return env


def run_latentsync(
    ls_dir: Path,
    video_path: Path,
    audio_path: Path,
    output_path: Path,
    cfg: dict,
    on_progress=None,
) -> Path:
    ls_cfg = cfg.get("latentsync", {})
    ckpt = ls_dir / ls_cfg.get("checkpoint", "checkpoints/latentsync_unet.pt")
    unet_cfg = ls_dir / ls_cfg.get("unet_config", "configs/unet/stage2.yaml")
    if not ckpt.exists():
        raise FileNotFoundError(f"LatentSync checkpoint missing: {ckpt}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    py = venv_python(ls_dir)
    video_abs = video_path.resolve()
    audio_abs = audio_path.resolve()
    output_abs = output_path.resolve()

    cmd = [
        py,
        "-m",
        "scripts.inference",
        "--unet_config_path",
        str(unet_cfg.resolve()),
        "--inference_ckpt_path",
        str(ckpt.resolve()),
        "--video_path",
        str(video_abs),
        "--audio_path",
        str(audio_abs),
        "--video_out_path",
        str(output_abs),
        "--inference_steps",
        str(ls_cfg.get("inference_steps", 20)),
        "--guidance_scale",
        str(ls_cfg.get("guidance_scale", 1.5)),
        "--seed",
        str(ls_cfg.get("seed", 1247)),
    ]
    if ls_cfg.get("enable_deepcache", True):
        cmd.append("--enable_deepcache")
        cmd.extend(
            [
                "--deepcache_interval",
                str(ls_cfg.get("deepcache_interval", 3)),
            ]
        )

    run_cmd_with_progress(
        cmd,
        cwd=ls_dir,
        env=hf_env(),
        on_progress=on_progress,
        span=(0.0, 1.0),
    )
    if not output_path.exists():
        raise FileNotFoundError(f"LatentSync output missing: {output_path}")
    return output_path


def apply_lipsync_quality(cfg: dict, quality: str | None) -> dict:
    """Return cfg copy with per-engine quality preset overrides."""
    import copy

    out = copy.deepcopy(cfg)
    lipsync = out.get("lipsync", {})
    presets = lipsync.get("quality_presets", {})
    q = (quality or lipsync.get("default_quality") or "balanced").lower()
    preset = presets.get(q)
    if not preset:
        return out
    for engine in ("latentsync", "sadtalker", "heygem"):
        section = preset.get(engine)
        if isinstance(section, dict):
            out.setdefault(engine, {}).update(section)
    # Legacy flat keys (inference_steps etc.) → latentsync only
    legacy = {k: v for k, v in preset.items() if k not in ("latentsync", "sadtalker", "heygem")}
    if legacy:
        out.setdefault("latentsync", {}).update(legacy)
    return out


def extract_first_frame(ffmpeg_bin: str, video_path: Path, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            ffmpeg_bin,
            "-y",
            "-i",
            str(video_path),
            "-vframes",
            "1",
            "-q:v",
            "2",
            str(out_path),
        ]
    )
    return out_path


def find_newest_mp4(root: Path) -> Path | None:
    files = [p for p in root.rglob("*.mp4") if p.is_file()]
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def find_best_sadtalker_mp4(root: Path) -> Path | None:
    """Prefer SadTalker *_full.mp4 (pre-enhancer) when enhancer step fails."""
    files = [p for p in root.rglob("*.mp4") if p.is_file()]
    if not files:
        return None
    full = [p for p in files if p.name.endswith("_full.mp4")]
    pool = full if full else files
    return max(pool, key=lambda p: (p.stat().st_size, p.stat().st_mtime))


def run_sadtalker(
    st_dir: Path,
    source_path: Path,
    audio_path: Path,
    output_path: Path,
    cfg: dict,
    on_progress=None,
    overrides: dict | None = None,
) -> Path:
    st_cfg = dict(cfg.get("sadtalker", {}))
    if overrides:
        st_cfg.update({k: v for k, v in overrides.items() if v is not None})
    if not (st_dir / "inference.py").exists():
        raise FileNotFoundError(
            f"SadTalker 未安装: {st_dir}\n请运行 .\\scripts\\setup\\setup_sadtalker.ps1"
        )
    ckpt = st_dir / "checkpoints"
    if not ckpt.exists() or not any(ckpt.iterdir()):
        raise FileNotFoundError(
            f"SadTalker checkpoints 未找到: {ckpt}\n"
            "请运行 scripts/setup/setup_sadtalker.ps1 或手动下载模型到 checkpoints/"
        )

    work_dir = output_path.parent / "sadtalker_work"
    if work_dir.exists():
        shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    py = venv_python(st_dir)
    cmd = [
        py,
        "inference.py",
        "--driven_audio",
        str(audio_path.resolve()),
        "--source_image",
        str(source_path.resolve()),
        "--result_dir",
        str(work_dir.resolve()),
        "--preprocess",
        st_cfg.get("preprocess", "full"),
        "--size",
        str(st_cfg.get("size", 256)),
        "--batch_size",
        str(st_cfg.get("batch_size", 2)),
        "--expression_scale",
        str(st_cfg.get("expression_scale", 1.0)),
        "--pose_style",
        str(int(st_cfg.get("pose_style", 0))),
    ]
    if st_cfg.get("still", False):
        cmd.append("--still")
    ref_pose = (st_cfg.get("ref_pose") or "").strip()
    if ref_pose:
        ref_path = Path(ref_pose)
        if ref_path.is_file():
            cmd.extend(["--ref_pose", str(ref_path.resolve())])
    enhancer = (st_cfg.get("enhancer") or "").strip()
    if enhancer:
        cmd.extend(["--enhancer", enhancer])

    emit(0.05, "sadtalker_prep")
    try:
        run_cmd_with_progress(
            cmd,
            cwd=st_dir,
            env=hf_env(legacy_torch=True),
            on_progress=on_progress,
            span=(0.05, 1.0),
        )
    except subprocess.CalledProcessError as exc:
        produced = find_best_sadtalker_mp4(work_dir)
        if produced is None or produced.stat().st_size < 50_000:
            raise exc
        emit(0.98, "sadtalker_done")
        if on_progress:
            on_progress(
                0.98,
                "SadTalker 主视频已生成（面部增强失败已跳过；可选「快速」画质避免 GFPGAN 下载）",
            )
    else:
        produced = find_best_sadtalker_mp4(work_dir)
        if produced is None:
            raise FileNotFoundError(f"SadTalker output missing under {work_dir}")
    shutil.copy2(produced, output_path)
    ffmpeg_bin = cfg.get("paths", {}).get("ffmpeg", "ffmpeg")
    transcode_to_web_mp4(ffmpeg_bin, output_path, output_path)
    return output_path


def run_pipeline(
    video: Path | None,
    audio: Path,
    config_path: Path = Path("config.yaml"),
    work_dir: Path | None = None,
    quality: str | None = None,
    backend: str | None = None,
    source_image: Path | None = None,
    output_name: str = "final_lipsync.mp4",
    on_progress=None,
    sadtalker_overrides: dict | None = None,
) -> Path:
    def prog(p: float, msg: str) -> None:
        if on_progress:
            on_progress(p, msg)

    prog(0.02, stage_label("config"))
    cfg = apply_lipsync_quality(load_config(config_path), quality)
    paths = cfg["paths"]
    lipsync = cfg.get("lipsync", {})
    out_root = Path(cfg.get("output", {}).get("dir", "./output"))

    ffmpeg_bin = ensure_ffmpeg(paths.get("ffmpeg", "ffmpeg"))
    stem_source = video or source_image or audio
    work_dir = work_dir or (out_root / Path(stem_source).stem)
    work_dir.mkdir(parents=True, exist_ok=True)

    prog(0.08, stage_label("norm_audio"))
    audio_wav = work_dir / "dubbing_16k.wav"
    if audio.resolve() != audio_wav.resolve():
        normalize_audio(ffmpeg_bin, audio.resolve(), audio_wav)

    backend = (backend or lipsync.get("backend", "latentsync")).lower()
    final_path = work_dir / output_name
    align_note = ""

    if backend == "sadtalker":
        prog(0.12, stage_label("sadtalker"))
        src = source_image
        if src is None:
            if video is None:
                raise ValueError("SadTalker 需要肖像图，或提供视频以提取首帧")
            frame_path = work_dir / "sadtalker_source.jpg"
            extract_first_frame(ffmpeg_bin, video.resolve(), frame_path)
            src = frame_path
            align_note = "已从视频提取首帧作为 SadTalker 输入"
        elif not src.exists():
            raise FileNotFoundError(f"肖像图不存在: {src}")

        def st_prog(p: float, msg: str) -> None:
            prog(0.12 + p * 0.86, msg)

        st_dir = Path(paths.get("sadtalker_dir", "tools/SadTalker"))
        raw_out = work_dir / "sadtalker_raw.mp4"
        run_sadtalker(
            st_dir,
            src,
            audio_wav,
            raw_out,
            cfg,
            on_progress=st_prog,
            overrides=sadtalker_overrides,
        )
        prog(0.98, stage_label("save_out"))
        shutil.copy2(raw_out, final_path)
        prog(1.0, f"{stage_label('lipsync_done')} | SadTalker | {align_note}")
        return final_path

    if video is None:
        if source_image is not None and source_image.exists():
            raise ValueError(
                f"{backend} 需要视频素材；当前为图片，请改选 SadTalker"
            )
        raise ValueError(f"{backend} 需要上传或录制视频")

    fps = int(lipsync.get("fps", 25))
    prog(0.15, stage_label("video_fps"))
    video_25fps = work_dir / "video_25fps.mp4"
    align_info = prepare_video_for_lipsync(
        ffmpeg_bin, video.resolve(), audio_wav, video_25fps, fps
    )
    align_note = align_info["note"]

    if backend == "latentsync":
        prog(0.18, stage_label("lipsync"))

        def lipsync_prog(p: float, msg: str) -> None:
            prog(0.18 + p * 0.80, msg)

        ls_dir = Path(paths["latentsync_dir"])
        raw_out = work_dir / "latentsync_raw.mp4"
        ls_cfg = cfg.get("latentsync", {})
        run_latentsync(ls_dir, video_25fps, audio_wav, raw_out, cfg, on_progress=lipsync_prog)
        prog(0.98, stage_label("save_out"))
        shutil.copy2(raw_out, final_path)
        done_msg = (
            f"{stage_label('lipsync_done')} | LatentSync | {align_note} | "
            f"steps={ls_cfg.get('inference_steps')} guidance={ls_cfg.get('guidance_scale')}"
        )
        prog(1.0, done_msg)
        return final_path

    raise ValueError(
        f"未知对口型引擎 '{backend}'，可选: heygem / latentsync / sadtalker"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Video + local audio lip-sync")
    parser.add_argument("--video", required=True)
    parser.add_argument("--audio", required=True)
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    final = run_pipeline(Path(args.video), Path(args.audio), Path(args.config))
    print("\nDone.")
    print(f"Output: {final}")


if __name__ == "__main__":
    main()

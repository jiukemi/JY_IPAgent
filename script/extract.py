"""Extract spoken script from reference video/audio via Whisper (local)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Callable

ProgressFn = Callable[[float, str], None]


def _emit(on_progress: ProgressFn | None, p: float, msg: str) -> None:
    if on_progress:
        on_progress(p, msg)


def extract_audio_for_asr(
    ffmpeg_bin: str,
    media_path: Path,
    wav_path: Path,
) -> None:
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg_bin,
        "-y",
        "-i",
        str(media_path),
        "-ac",
        "1",
        "-ar",
        "16000",
        str(wav_path),
    ]
    subprocess.run(cmd, check=True)


def whisper_python(cfg: dict) -> str:
    root = Path(cfg.get("paths", {}).get("whisper_dir", "tools/Whisper"))
    for sub in (".venv", "venv"):
        win = root / sub / "Scripts" / "python.exe"
        if win.exists():
            return str(win)
        unix = root / sub / "bin" / "python"
        if unix.exists():
            return str(unix)
    return sys.executable


def transcribe_whisper(
    cfg: dict,
    wav_path: Path,
    *,
    on_progress: ProgressFn | None = None,
) -> str:
    script_cfg = cfg.get("script") or {}
    model = script_cfg.get("whisper_model", "small")
    language = script_cfg.get("language", "zh")
    whisper_dir = Path(cfg.get("paths", {}).get("whisper_dir", "tools/Whisper"))
    runner = whisper_dir / "run_asr.py"
    if not runner.exists():
        raise FileNotFoundError(
            f"Whisper 未安装: {whisper_dir}\n请运行 .\\scripts\\setup\\setup_whisper.ps1"
        )

    _emit(on_progress, 0.35, "Whisper 转写中…")
    py = whisper_python(cfg)
    env = os.environ.copy()
    env.setdefault("HF_ENDPOINT", cfg.get("hf_endpoint", "https://hf-mirror.com"))
    cmd = [
        py,
        str(runner),
        "--audio",
        str(wav_path.resolve()),
        "--model",
        model,
        "--language",
        language,
    ]
    result = subprocess.run(
        cmd,
        cwd=whisper_dir,
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"Whisper 转写失败:\n{err}")
    text = (result.stdout or "").strip()
    if not text:
        raise RuntimeError("Whisper 未识别到有效口播文案")
    _emit(on_progress, 0.95, "转写完成")
    return text


def _funasr_python(cfg: dict) -> str:
    """Prefer a dedicated FunASR venv; fall back to the main python."""
    root = Path(cfg.get("paths", {}).get("funasr_dir", "tools/FunASR"))
    for sub in (".venv", "venv"):
        win = root / sub / "Scripts" / "python.exe"
        if win.exists():
            return str(win)
        unix = root / sub / "bin" / "python"
        if unix.exists():
            return str(unix)
    return sys.executable


def _funasr_available(cfg: dict) -> bool:
    py = _funasr_python(cfg)
    try:
        result = subprocess.run(
            [py, "-c", "import funasr"],
            capture_output=True,
            timeout=8,
        )
        return result.returncode == 0
    except Exception:
        return False


def transcribe_funasr(
    cfg: dict,
    wav_path: Path,
    *,
    on_progress: ProgressFn | None = None,
) -> str:
    script_cfg = cfg.get("script") or {}
    funasr_dir = Path(cfg.get("paths", {}).get("funasr_dir", "tools/FunASR"))
    runner = funasr_dir / "run_asr.py"
    if not runner.exists():
        raise FileNotFoundError(f"FunASR runner 缺失: {runner}")
    if not _funasr_available(cfg):
        raise RuntimeError(
            "FunASR 未安装。请运行:\n"
            "  py -3.11 -m pip install funasr modelscope torchaudio"
        )

    model = script_cfg.get("funasr_model", "sensevoice")
    _emit(on_progress, 0.35, f"FunASR 转写中（模型: {model}）…")

    # Fast path: warm worker (model already loaded in memory).
    try:
        from script.funasr_client import try_worker_transcribe

        text = try_worker_transcribe(cfg, wav_path)
        if text:
            _emit(on_progress, 0.95, "FunASR 转写完成（常驻 worker）")
            return text
    except Exception:
        pass

    # Fallback: one-shot subprocess (reloads model each call).
    _emit(on_progress, 0.4, "FunASR 转写中（首次加载模型，约 10-30 秒）…")
    py = _funasr_python(cfg)
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    cmd = [
        py,
        str(runner.resolve()),
        "--audio",
        str(wav_path.resolve()),
        "--model",
        model,
    ]
    result = subprocess.run(
        cmd,
        cwd=str(funasr_dir.resolve()),
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"FunASR 转写失败:\n{err}")
    text = (result.stdout or "").strip()
    if not text:
        raise RuntimeError("FunASR 未识别到有效口播文案")
    _emit(on_progress, 0.95, "FunASR 转写完成")
    return text


def extract_script_from_media(
    cfg: dict,
    media_path: Path,
    work_dir: Path,
    ffmpeg_bin: str,
    *,
    on_progress: ProgressFn | None = None,
) -> str:
    media_path = media_path.resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    _emit(on_progress, 0.05, "提取音频…")
    wav = work_dir / "reference_16k.wav"
    extract_audio_for_asr(ffmpeg_bin, media_path, wav)
    _emit(on_progress, 0.2, "语音识别…")
    provider = ((cfg.get("script") or {}).get("cloud") or {}).get("transcript", {}).get("provider")
    return transcribe_local(cfg, wav, provider=provider, on_progress=on_progress)


def transcribe_local(
    cfg: dict,
    wav_path: Path,
    *,
    provider: str | None = None,
    on_progress: ProgressFn | None = None,
) -> str:
    """Dispatch to FunASR or Whisper based on the transcript provider.

    Falls back to Whisper when FunASR isn't installed.
    """
    provider = (provider or "funasr").strip().lower()
    if provider == "funasr":
        if _funasr_available(cfg):
            try:
                return transcribe_funasr(cfg, wav_path, on_progress=on_progress)
            except Exception as exc:
                _emit(on_progress, 0.25, f"FunASR 失败，回退 Whisper：{exc}")
        else:
            _emit(on_progress, 0.25, "FunASR 未安装，回退 Whisper")
    return transcribe_whisper(cfg, wav_path, on_progress=on_progress)

"""TTS engines: IndexTTS2, CosyVoice, Piper, edge-tts."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import yaml

from tts.progress import run_cmd_with_progress, stage_label, estimate_speech_seconds, format_hms
from tts.speed import get_speed_preset
from tts.voices import get_voice
from workflow.bundle_paths import project_root, resolve_path

PRESETS_PATH = Path(__file__).with_name("presets.yaml")
ProgressFn = Callable[[float, str], None]

# IndexTTS2 built-in examples: voice_01 ≈ 男声, voice_02/03 ≈ 女声（相对基频）
INDEXTTS_DEFAULT_PRESET_REFS: dict[str, str] = {
    "mandarin_female_warm": "examples/voice_02.wav",
    "mandarin_female_energetic": "examples/voice_03.wav",
    "mandarin_male_steady": "examples/voice_01.wav",
    "mandarin_male_friendly": "examples/voice_01.wav",
    "en_female_clear": "examples/voice_02.wav",
    "en_female_energetic": "examples/voice_03.wav",
    "en_male_warm": "examples/voice_01.wav",
    "en_male_narrator": "examples/voice_01.wav",
    "cantonese": "examples/voice_02.wav",
    "sichuan": "examples/voice_02.wav",
    "northeast": "examples/voice_01.wav",
    "shanghai": "examples/voice_03.wav",
}


def load_presets() -> dict:
    with PRESETS_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def venv_python(cfg: dict, key: str) -> str:
    root = Path(cfg["paths"][key])
    # uv / modern installs use .venv; legacy scripts used venv
    for sub in (".venv", "venv"):
        win = root / sub / "Scripts" / "python.exe"
        if win.exists():
            return str(win)
        unix = root / sub / "bin" / "python"
        if unix.exists():
            return str(unix)
    return sys.executable


def build_tts_text(
    text: str,
    mode: str,
    preset_id: str,
    style_extra: str,
    presets: dict,
) -> str:
    text = text.strip()
    if not text:
        raise ValueError("文案不能为空")

    prefix = ""
    if mode == "preset":
        preset = presets["presets"].get(preset_id)
        if not preset:
            preset = presets.get("english_presets", {}).get(preset_id)
        if not preset:
            raise ValueError(f"未知预设音色: {preset_id}")
        prefix = preset["style_prefix"]
    elif mode == "dialect":
        dialect = presets["dialects"].get(preset_id)
        if not dialect:
            raise ValueError(f"未知方言: {preset_id}")
        prefix = dialect["style_prefix"]
    elif mode == "clone":
        extra = (style_extra or "").strip()
        if extra:
            prefix = f"({extra})"
    elif mode == "custom":
        extra = (style_extra or "").strip()
        if extra:
            prefix = f"({extra})"
    elif mode == "english":
        eng = presets.get("english_presets", {}).get(preset_id)
        if not eng:
            raise ValueError(f"未知英文预设: {preset_id}")
        prefix = eng["style_prefix"]
    else:
        raise ValueError(f"未知 TTS 模式: {mode}")

    if prefix and not prefix.endswith(" "):
        prefix += " "
    return f"{prefix}{text}"


def _ensure_edge_tts() -> None:
    """Install edge-tts into the current interpreter if missing (Aliyun mirror)."""
    import subprocess
    import sys

    mirrors = [
        ["-i", "https://mirrors.aliyun.com/pypi/simple/", "--trusted-host", "mirrors.aliyun.com"],
        [],
    ]
    last_err = ""
    for extra in mirrors:
        cmd = [sys.executable, "-m", "pip", "install", "edge-tts>=6.1.0", *extra]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            if r.returncode == 0:
                return
            last_err = (r.stderr or r.stdout or "").strip()[-400:]
        except Exception as exc:
            last_err = str(exc)
    raise RuntimeError(
        "未安装 edge-tts（在线 Edge 配音依赖）。自动安装失败：\n"
        f"{last_err or 'unknown'}\n"
        "请在运行时 Python 执行：python -m pip install edge-tts\n"
        "或清除运行时后重开软件（会重装核心依赖）。"
    )


def run_edge_tts(text: str, output_mp3: Path, voice: str) -> Path:
    import asyncio

    try:
        import edge_tts
    except ImportError:
        _ensure_edge_tts()
        import edge_tts

    async def _run() -> None:
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(str(output_mp3))

    asyncio.run(_run())
    return output_mp3


def convert_to_wav(ffmpeg: str, src: Path, dst: Path, sample_rate: int = 16000) -> Path:
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(src),
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            str(dst),
        ],
        check=True,
        capture_output=True,
    )
    return dst


def _hf_env(cfg: dict) -> dict:
    env = os.environ.copy()
    env.setdefault("HF_ENDPOINT", cfg.get("hf_endpoint", "https://hf-mirror.com"))
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    return env


def _run_backend_subprocess(
    cfg: dict,
    cmd: list[str],
    *,
    on_progress: ProgressFn | None = None,
    span: tuple[float, float] = (0.15, 0.88),
    progress_text: str = "",
    fake_creep: bool = True,
) -> None:
    run_cmd_with_progress(
        cmd,
        cwd=Path.cwd(),
        env=_hf_env(cfg),
        on_progress=on_progress,
        span=span,
        progress_text=progress_text,
        fake_creep=fake_creep,
    )


def resolve_indextts_install_dir(cfg: dict) -> Path:
    """Prefer configured path; fall back to writable runtime engines dir if present."""
    import os

    raw = Path(cfg.get("paths", {}).get("indextts_dir", "tools/IndexTTS"))
    primary = raw if raw.is_absolute() else (project_root() / raw)
    candidates = [primary]
    rt = (os.environ.get("AGENT_RUNTIME_DIR") or "").strip()
    if rt:
        candidates.append(Path(rt).expanduser().resolve() / "engines" / "IndexTTS")

    def _usable(p: Path) -> bool:
        return (p / "checkpoints" / "config.yaml").is_file() or (
            p / ".venv" / "Scripts" / "python.exe"
        ).is_file() or (p / "venv" / "Scripts" / "python.exe").is_file()

    for c in candidates:
        try:
            if _usable(c):
                return c.resolve()
        except OSError:
            continue
    return primary.resolve()


def find_indextts_reference(cfg: dict) -> Path | None:
    """First usable speaker reference: bundled examples, then voice library."""
    it_cfg = cfg.get("indextts") or {}
    install = resolve_indextts_install_dir(cfg)

    for rel in (
        it_cfg.get("default_spk_wav"),
        "checkpoints/examples/voice_01.wav",
        "examples/voice_01.wav",
    ):
        if not rel:
            continue
        candidate = install / rel if not Path(rel).is_absolute() else Path(rel)
        if candidate.is_file() and candidate.stat().st_size > 100:
            return candidate.resolve()

    from tts.voices import list_voices

    for voice in list_voices():
        ref = Path(voice.get("reference_wav", ""))
        if ref.is_file() and ref.stat().st_size > 100:
            return ref.resolve()
    return None


def resolve_indextts_reference(
    cfg: dict,
    *,
    mode: str,
    preset_id: str,
    reference_wav: str | None,
) -> str:
    """Pick speaker reference wav for IndexTTS2 (always required)."""
    mode = (mode or "preset").lower()
    if reference_wav:
        ref = Path(reference_wav)
        if ref.is_file() and ref.stat().st_size > 100:
            return str(ref.resolve())
        if mode == "clone":
            raise FileNotFoundError(f"克隆参考音不存在或无效: {reference_wav}")

    if mode == "clone":
        raise FileNotFoundError(
            "IndexTTS2 克隆模式需要参考音频。\n"
            "请在 ② 配音页上方保存克隆音色，并选择「克隆音色」。"
        )

    it_cfg = cfg.get("indextts", {})
    install = resolve_indextts_install_dir(cfg)

    preset_refs = {**INDEXTTS_DEFAULT_PRESET_REFS, **(it_cfg.get("preset_refs") or {})}
    if preset_id and preset_id in preset_refs:
        rel = preset_refs[preset_id]
        candidate = install / rel if not Path(rel).is_absolute() else Path(rel)
        if not candidate.is_file():
            candidate = resolve_path(rel, project_root())
        if candidate.is_file() and candidate.stat().st_size > 100:
            return str(candidate.resolve())

    found = find_indextts_reference(cfg)
    if found:
        return str(found)

    raise FileNotFoundError(
        "IndexTTS2 需要参考音频（wav/mp3/m4a 等均可，会自动转换）。\n"
        "可选：① 一键安装下载内置示例；② 在配音页保存任一条参考音到音色库。"
    )


def _indextts_subprocess(
    cfg: dict,
    text: str,
    raw_wav: Path,
    *,
    reference_wav: str | None,
    prompt_text: str,
    mode: str,
    preset_id: str,
    style_extra: str,
    speed: str,
    on_progress: ProgressFn | None,
) -> None:
    text_file = raw_wav.parent / "tts_input.txt"
    text_file.write_text(text, encoding="utf-8")
    job = {
        "text_file": str(text_file.resolve()),
        "output": str(raw_wav.resolve()),
        "mode": mode,
        "preset": preset_id or "mandarin_female_warm",
        "style": style_extra or "",
        "speed": speed or "balanced",
    }
    if reference_wav:
        job["reference"] = reference_wav

    from tts.indextts_client import try_worker_synthesize

    if try_worker_synthesize(cfg, job, on_progress=on_progress):
        return

    py = venv_python(cfg, "indextts_dir")
    cmd = [
        py,
        str(Path(__file__).resolve().parent / "run_indextts.py"),
        "--config",
        str(Path("config.yaml").resolve()),
        "--text-file",
        str(text_file.resolve()),
        "--output",
        str(raw_wav.resolve()),
        "--mode",
        mode,
        "--preset",
        preset_id or "mandarin_female_warm",
        "--style",
        style_extra or "",
        "--speed",
        speed or "balanced",
    ]
    if reference_wav:
        cmd.extend(["--reference", reference_wav])
    _run_backend_subprocess(cfg, cmd, on_progress=on_progress, progress_text=text)


def _cosyvoice_subprocess(
    cfg: dict,
    text: str,
    raw_wav: Path,
    *,
    reference_wav: str | None,
    prompt_text: str,
    mode: str,
    preset_id: str,
    style_extra: str,
    on_progress: ProgressFn | None,
) -> None:
    py = venv_python(cfg, "cosyvoice_dir")
    text_file = raw_wav.parent / "tts_input.txt"
    text_file.write_text(text, encoding="utf-8")
    cmd = [
        py,
        str(Path(__file__).resolve().parent / "run_cosyvoice.py"),
        "--config",
        str(Path("config.yaml").resolve()),
        "--text-file",
        str(text_file.resolve()),
        "--output",
        str(raw_wav.resolve()),
        "--mode",
        mode,
        "--preset",
        preset_id or "",
        "--style",
        style_extra or "",
        "--prompt-text",
        prompt_text or "",
    ]
    if reference_wav:
        cmd.extend(["--reference", reference_wav])

    install = Path(cfg["paths"]["cosyvoice_dir"])
    if not install.is_absolute():
        install = Path.cwd() / install
    path_parts = [
        str(install.resolve()),
        str((install / "third_party" / "Matcha-TTS").resolve()),
        str((install / "third_party" / "Matcha-TTS-main").resolve()),
    ]
    env = _hf_env(cfg)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join([p for p in path_parts if Path(p).is_dir()] + ([existing] if existing else []))

    run_cmd_with_progress(
        cmd,
        cwd=install.resolve() if install.is_dir() else Path.cwd(),
        env=env,
        on_progress=on_progress,
        span=(0.15, 0.88),
        progress_text=text,
        fake_creep=True,
    )


def _qwen3_local_subprocess(
    cfg: dict,
    text: str,
    raw_wav: Path,
    *,
    reference_wav: str | None,
    prompt_text: str,
    mode: str,
    preset_id: str,
    style_extra: str,
    on_progress: ProgressFn | None,
) -> None:
    py = venv_python(cfg, "qwen3_local_dir")
    text_file = raw_wav.parent / "tts_input.txt"
    text_file.write_text(text, encoding="utf-8")
    cmd = [
        py,
        str(Path(__file__).resolve().parent / "run_qwen3_local.py"),
        "--config",
        str(Path("config.yaml").resolve()),
        "--text-file",
        str(text_file.resolve()),
        "--output",
        str(raw_wav.resolve()),
        "--mode",
        mode,
        "--preset",
        preset_id or "vivian",
        "--style",
        style_extra or "",
        "--prompt-text",
        prompt_text or "",
    ]
    if reference_wav:
        cmd.extend(["--reference", reference_wav])
    _run_backend_subprocess(cfg, cmd, on_progress=on_progress, progress_text=text)


def _wav_ready(path: Path, sample_rate: int) -> bool:
    """True if path is already mono PCM wav at the requested rate."""
    if path.suffix.lower() != ".wav" or not path.is_file():
        return False
    try:
        import wave

        with wave.open(str(path), "rb") as wf:
            return (
                wf.getnchannels() == 1
                and wf.getframerate() == sample_rate
                and wf.getsampwidth() in (2, 3, 4)
                and wf.getnframes() > 0
            )
    except Exception:
        return False


def _prepare_reference_wav(
    ffmpeg: str,
    ref_path: str,
    work_dir: Path,
    sample_rate: int = 22050,
    *,
    force: bool = False,
) -> str:
    """Reuse saved wav when already correct — do NOT re-ffmpeg every clone run."""
    src = Path(ref_path)
    if not force and _wav_ready(src, sample_rate):
        return str(src.resolve())
    if not force and src.suffix.lower() == ".wav" and src.is_file():
        # Already wav (any rate): IndexTTS/Cosy usually accept it; skip convert to stay fast
        return str(src.resolve())
    dst = work_dir / f"ref_{sample_rate}.wav"
    convert_to_wav(ffmpeg, src, dst, sample_rate=sample_rate)
    return str(dst.resolve())


def _piper_subprocess(
    cfg: dict,
    text: str,
    raw_wav: Path,
    on_progress: ProgressFn | None,
    *,
    model_path: Path | None = None,
) -> None:
    py = venv_python(cfg, "piper_dir")
    cmd = [
        py,
        str(Path(__file__).resolve().parent / "run_piper.py"),
        "--config",
        str(Path("config.yaml").resolve()),
        "--text",
        text,
        "--output",
        str(raw_wav.resolve()),
    ]
    if model_path:
        cmd.extend(["--model", str(model_path.resolve())])
    _run_backend_subprocess(cfg, cmd, on_progress=on_progress)


def resolve_clone_reference(
    reference_wav: str | None,
    saved_voice_id: str | None,
) -> tuple[str | None, str]:
    """Return (wav_path, saved prompt_text if any)."""
    if saved_voice_id:
        entry = get_voice(saved_voice_id)
        if entry:
            return entry["reference_wav"], entry.get("prompt_text", "")
    return reference_wav, ""


def _audio_duration_sec(path: Path) -> float:
    import wave

    with wave.open(str(path), "rb") as wf:
        rate = wf.getframerate() or 1
        return wf.getnframes() / float(rate)


def _try_dialect_edge_synth(
    *,
    presets: dict,
    preset_id: str,
    text: str,
    output_dir: Path,
    raw_wav: Path,
    ffmpeg_bin: str,
    prog: ProgressFn,
) -> bool:
    """If dialect maps to an Edge Neural voice, synthesize with it. Returns True if handled."""
    dialect = presets.get("dialects", {}).get(preset_id) or {}
    edge_voice = (dialect.get("edge_voice") or "").strip()
    if not edge_voice:
        return False
    prog(0.2, f"方言「{dialect.get('label', preset_id)}」使用神经音色精确合成…")
    prog(0.3, stage_label("cpu_synth"))
    raw_mp3 = output_dir / "tts_raw.mp3"
    run_edge_tts(text, raw_mp3, edge_voice)
    convert_to_wav(ffmpeg_bin, raw_mp3, raw_wav)
    return True


def synthesize(
    cfg: dict,
    text: str,
    output_dir: Path,
    *,
    mode: str = "preset",
    preset_id: str = "mandarin_female_warm",
    style_extra: str = "",
    reference_wav: str | None = None,
    saved_voice_id: str | None = None,
    prompt_text: str = "",
    backend: str | None = None,
    speed: str = "balanced",
    on_progress: ProgressFn | None = None,
) -> dict:
    def prog(p: float, msg: str) -> None:
        if on_progress:
            on_progress(p, msg)

    from tts.text_normalize import normalize_speech_text

    text = normalize_speech_text(text, backend=backend)
    presets = load_presets()
    output_dir.mkdir(parents=True, exist_ok=True)
    backend = backend or cfg.get("tts", {}).get("backend", "indextts")
    speed = speed or cfg.get("tts", {}).get("default_speed", "balanced")
    style_extra = style_extra or ""

    # Normalized text goes to tts_input.txt (per backend); never overwrite script.txt —
    # that would permanently replace user copy (e.g. VibeCoding → old phonetic fixes).

    if backend == "upload":
        raise ValueError("upload 模式请直接在 UI 上传音频")

    est_note = ""
    if backend in ("indextts", "cosyvoice"):
        est = estimate_speech_seconds(text)
        est_note = (
            f" · 预估音频 {format_hms(est)} · "
            f"合成约需 {format_hms(est)}~{format_hms(est * 1.15)}（长文案正常）"
        )
    prog(0.06, f"{stage_label('prep')}{est_note}")
    # Edge / Piper / Qwen：preset_id 是说话人 ID，不走 VoxCPM 风格前缀校验
    if backend in ("edge", "piper", "qwen3_local", "qwen3_tts"):
        tts_text = text.strip()
    elif backend in ("indextts", "cosyvoice"):
        tts_text = text.strip()
        if style_extra.strip():
            tts_text = f"[emo:{style_extra.strip()}]\n{text.strip()}"
    else:
        tts_text = build_tts_text(text, mode, preset_id, style_extra, presets)
    meta_path = output_dir / "tts_prompt.txt"
    meta_path.write_text(tts_text, encoding="utf-8")

    ref, _saved_prompt = resolve_clone_reference(reference_wav, saved_voice_id)

    raw_wav = output_dir / "tts_raw.wav"
    ffmpeg_bin = cfg["paths"].get("ffmpeg", "ffmpeg")

    if backend == "indextts":
        # IndexTTS 无法靠文字可靠出方言：有 Edge 神经音色的方言改走精确口音
        if mode == "dialect" and _try_dialect_edge_synth(
            presets=presets,
            preset_id=preset_id,
            text=text,
            output_dir=output_dir,
            raw_wav=raw_wav,
            ffmpeg_bin=ffmpeg_bin,
            prog=prog,
        ):
            pass  # raw_wav ready → shared convert below
        else:
            if venv_python(cfg, "indextts_dir") == sys.executable:
                raise RuntimeError("IndexTTS2 未安装，请运行 .\\scripts\\setup\\setup_indextts.ps1")
            if mode == "clone" and not ref:
                raise ValueError("克隆需要上传参考音或选择已保存音色")
            ref_prepared = None
            if ref:
                ref_prepared = _prepare_reference_wav(
                    ffmpeg_bin, ref, output_dir, sample_rate=22050
                )
            clone_prompt = prompt_text or _saved_prompt
            _indextts_subprocess(
                cfg,
                text,
                raw_wav,
                reference_wav=ref_prepared,
                prompt_text=clone_prompt,
                mode=mode,
                preset_id=preset_id,
                style_extra=style_extra,
                speed=speed,
                on_progress=on_progress,
            )
    elif backend == "cosyvoice":
        if mode == "dialect" and _try_dialect_edge_synth(
            presets=presets,
            preset_id=preset_id,
            text=text,
            output_dir=output_dir,
            raw_wav=raw_wav,
            ffmpeg_bin=ffmpeg_bin,
            prog=prog,
        ):
            pass
        else:
            if venv_python(cfg, "cosyvoice_dir") == sys.executable:
                raise RuntimeError("CosyVoice 未安装，请运行 .\\scripts\\setup\\setup_cosyvoice.ps1")
            if mode == "clone" and not ref:
                raise ValueError("克隆需要上传参考音或选择已保存音色")
            ref_prepared = None
            if ref:
                ref_prepared = _prepare_reference_wav(ffmpeg_bin, ref, output_dir, sample_rate=16000)
            clone_prompt = (prompt_text or _saved_prompt or "").strip()
            if mode == "clone" and not clone_prompt:
                raise ValueError(
                    "CosyVoice 克隆需要参考文案：请在 ② 配音页填写「参考音里说的内容」后重新保存音色"
                )
            _cosyvoice_subprocess(
                cfg,
                text,
                raw_wav,
                reference_wav=ref_prepared if mode == "clone" else None,
                prompt_text=clone_prompt,
                mode=mode,
                preset_id=preset_id,
                style_extra=style_extra,
                on_progress=on_progress,
            )
    elif backend == "piper":
        from tts.backend_presets import resolve_piper_model

        if venv_python(cfg, "piper_dir") == sys.executable:
            raise RuntimeError("Piper 未安装，请运行 scripts/setup/setup_piper.ps1")
        model_path = resolve_piper_model(cfg, preset_id)
        _piper_subprocess(cfg, text, raw_wav, on_progress, model_path=model_path)
    elif backend == "edge":
        from tts.backend_presets import resolve_edge_voice

        prog(0.3, stage_label("cpu_synth"))
        raw_mp3 = output_dir / "tts_raw.mp3"
        voice = resolve_edge_voice(preset_id)
        if not voice:
            voice = cfg.get("tts", {}).get("edge_voice", "zh-CN-XiaoxiaoNeural")
        run_edge_tts(text, raw_mp3, voice)
        ffmpeg = cfg["paths"].get("ffmpeg", "ffmpeg")
        convert_to_wav(ffmpeg, raw_mp3, raw_wav)
    elif backend == "qwen3_local":
        if venv_python(cfg, "qwen3_local_dir") == sys.executable:
            raise RuntimeError("本地 Qwen3-TTS 未安装，请运行 .\\scripts\\setup\\setup_qwen3_local.ps1")
        if mode == "clone" and not ref:
            raise ValueError("克隆需要上传参考音或选择已保存音色")
        ref_prepared = None
        if ref:
            ref_prepared = _prepare_reference_wav(ffmpeg_bin, ref, output_dir, sample_rate=24000)
        clone_prompt = (prompt_text or _saved_prompt or "").strip()
        if mode == "clone" and not clone_prompt:
            raise ValueError(
                "Qwen3 本地克隆需要参考文案：请在 ② 配音页填写「参考音里说的内容」后重新保存"
            )
        _qwen3_local_subprocess(
            cfg,
            text,
            raw_wav,
            reference_wav=ref_prepared if mode == "clone" else None,
            prompt_text=clone_prompt,
            mode=mode,
            preset_id=preset_id,
            style_extra=style_extra,
            on_progress=on_progress,
        )
    elif backend == "qwen3_tts":
        from tts.qwen3_tts import synthesize_qwen3_tts, verify_qwen3_tts

        health = verify_qwen3_tts(cfg, ping=False)
        if not health.get("configured"):
            raise RuntimeError(health.get("message") or "未配置 DashScope API Key")
        synthesize_qwen3_tts(
            cfg,
            text,
            raw_wav,
            preset_id=preset_id or "mandarin_female_warm",
            mode=mode,
            saved_voice_id=saved_voice_id,
            on_progress=on_progress,
        )
    else:
        raise ValueError(f"不支持的 TTS backend: {backend}")

    prog(0.9, stage_label("convert_16k"))
    final_wav = output_dir / "dubbing_16k.wav"
    convert_to_wav(ffmpeg_bin, raw_wav, final_wav, sample_rate=16000)
    prog(1.0, stage_label("done"))

    duration = _audio_duration_sec(final_wav)
    try:
        from tts.dubbing_timing import (
            ASR_TIMING_FILE,
            collect_qwen3_part_timing,
            save_timing_manifest,
        )

        stale_asr = output_dir / ASR_TIMING_FILE
        if stale_asr.is_file():
            stale_asr.unlink(missing_ok=True)

        if backend == "qwen3_tts":
            segs = collect_qwen3_part_timing(output_dir)
            if segs:
                save_timing_manifest(
                    output_dir,
                    {
                        "source": "tts_segments",
                        "backend": "qwen3_tts",
                        "duration": duration,
                        "segments": segs,
                    },
                )
    except Exception:
        pass

    return {
        "prompt": str(meta_path),
        "raw_audio": str(raw_wav),
        "audio": str(final_wav),
        "audio_duration_sec": duration,
        "audio_duration": format_hms(duration),
        "backend": backend,
        "mode": mode,
        "preset_id": preset_id,
        "speed": speed,
    }

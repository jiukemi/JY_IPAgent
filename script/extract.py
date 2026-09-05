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
    from workflow.engine_dirs import resolve_engine_dir

    root = resolve_engine_dir(
        cfg,
        path_key="whisper_dir",
        default_rel="tools/Whisper",
        runtime_name="Whisper",
        markers=("run_asr.py",),
    )
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
    from workflow.engine_dirs import resolve_engine_dir

    script_cfg = cfg.get("script") or {}
    model = script_cfg.get("whisper_model", "small")
    language = script_cfg.get("language", "zh")
    whisper_dir = resolve_engine_dir(
        cfg,
        path_key="whisper_dir",
        default_rel="tools/Whisper",
        runtime_name="Whisper",
        markers=("run_asr.py",),
    )
    runner = whisper_dir / "run_asr.py"
    if not runner.exists():
        raise FileNotFoundError(
            f"Whisper 未安装: {whisper_dir}\n请到设置安装 Whisper，或运行 scripts/setup/setup_whisper.ps1"
        )

    _emit(on_progress, 0.35, "Whisper 转写中…")
    py = whisper_python(cfg)
    env = os.environ.copy()
    env.setdefault("HF_ENDPOINT", cfg.get("hf_endpoint", "https://hf-mirror.com"))
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    out_path = wav_path.with_name(wav_path.stem + ".whisper.txt")
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
    text = _write_and_read_asr_out(cmd, cwd=whisper_dir, env=env, out_path=out_path)
    if not text:
        raise RuntimeError("Whisper 未识别到有效口播文案")
    _emit(on_progress, 0.95, "转写完成")
    return text


def _funasr_roots(cfg: dict) -> list[Path]:
    """Candidate FunASR install dirs (config + runtime engines)."""
    roots: list[Path] = []
    configured = Path(cfg.get("paths", {}).get("funasr_dir", "tools/FunASR"))
    roots.append(configured)
    rt = (os.environ.get("AGENT_RUNTIME_DIR") or "").strip()
    if rt:
        roots.append(Path(rt) / "engines" / "FunASR")
    roots.append(Path("tools/FunASR"))
    out: list[Path] = []
    seen: set[str] = set()
    for r in roots:
        key = str(r).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _funasr_python_candidates(cfg: dict) -> list[str]:
    """Ordered python interpreters that may host FunASR."""
    out: list[str] = []
    for root in _funasr_roots(cfg):
        for sub in (".venv", "venv"):
            win = root / sub / "Scripts" / "python.exe"
            if win.exists():
                out.append(str(win.resolve()))
            unix = root / sub / "bin" / "python"
            if unix.exists():
                out.append(str(unix.resolve()))
    out.append(sys.executable)
    # de-dupe preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for p in out:
        key = p.lower()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)
    return uniq


def _python_has_funasr(py: str) -> bool:
    """Fast readiness: package present (avoid full torch import — can take minutes)."""
    try:
        result = subprocess.run(
            [
                py,
                "-c",
                "import importlib.util as u;"
                "assert u.find_spec('torch'), 'no torch';"
                "assert u.find_spec('funasr'), 'no funasr';"
                "print('OK')",
            ],
            capture_output=True,
            timeout=45,
        )
        return result.returncode == 0
    except Exception:
        return False


def _funasr_python(cfg: dict) -> str:
    """Prefer a dedicated FunASR venv that actually has torch; else system python."""
    for py in _funasr_python_candidates(cfg):
        if _python_has_funasr(py):
            return py
    # Fall back to venv path (caller will surface a clear install error)
    cands = _funasr_python_candidates(cfg)
    return cands[0] if cands else sys.executable


def _funasr_available(cfg: dict) -> bool:
    return any(_python_has_funasr(py) for py in _funasr_python_candidates(cfg))


def _decode_pipe(raw: bytes | str | None) -> str:
    """Decode subprocess output; prefer UTF-8, fall back to GBK on Windows mojibake."""
    if raw is None:
        return ""
    if isinstance(raw, str):
        # Already decoded (possibly with replacement chars) — try repair if heavily corrupted
        if raw.count("\ufffd") >= 3:
            try:
                return raw.encode("latin-1", errors="ignore").decode("gbk", errors="ignore").strip() or raw
            except Exception:
                return raw
        return raw
    for enc in ("utf-8", "utf-8-sig", "gbk", "cp936"):
        try:
            return raw.decode(enc).strip()
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace").strip()


def _write_and_read_asr_out(cmd: list[str], *, cwd: Path, env: dict, out_path: Path) -> str:
    """Run ASR runner with --out file (UTF-8) to avoid Windows pipe encoding corruption.

    Older Whisper/FunASR runners only print to stdout and reject --out; fall back
    to stdout capture when that happens so existing installs keep working.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink(missing_ok=True)

    def _run(full_cmd: list[str]) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            full_cmd,
            cwd=str(cwd.resolve()),
            capture_output=True,
            check=False,
            env=env,
        )

    result = _run(list(cmd) + ["--out", str(out_path.resolve())])
    stderr = _decode_pipe(result.stderr)
    stdout = _decode_pipe(result.stdout)
    if result.returncode != 0 and (
        "unrecognized arguments" in (stderr + stdout).lower()
        or "unrecognized arguments" in (stderr + stdout)
        or "--out" in (stderr + stdout) and "error:" in (stderr + stdout).lower()
    ):
        # Legacy runner without --out
        result = _run(list(cmd))
        stderr = _decode_pipe(result.stderr)
        stdout = _decode_pipe(result.stdout)
        if result.returncode == 0 and stdout:
            try:
                out_path.write_text(stdout + "\n", encoding="utf-8")
            except OSError:
                pass
            return stdout

    if out_path.is_file() and out_path.stat().st_size > 0:
        text = out_path.read_text(encoding="utf-8").strip()
        if text:
            return text
    if result.returncode != 0:
        raise RuntimeError((stderr or stdout or "ASR 进程失败").strip())
    if not stdout:
        raise RuntimeError((stderr or "ASR 未识别到有效口播文案").strip())
    return stdout


def _resolve_funasr_dir(cfg: dict) -> Path:
    """Prefer a FunASR dir that has run_asr.py + venv."""
    for root in _funasr_roots(cfg):
        if (root / "run_asr.py").is_file() and any(
            (root / sub).is_dir() for sub in (".venv", "venv")
        ):
            return root
    for root in _funasr_roots(cfg):
        if any((root / sub).is_dir() for sub in (".venv", "venv")):
            return root
    return _funasr_roots(cfg)[0]


def transcribe_funasr(
    cfg: dict,
    wav_path: Path,
    *,
    on_progress: ProgressFn | None = None,
) -> str:
    script_cfg = cfg.get("script") or {}
    funasr_dir = _resolve_funasr_dir(cfg)
    runner = funasr_dir / "run_asr.py"
    if not runner.exists():
        raise FileNotFoundError(f"FunASR runner 缺失: {runner}")
    if not _funasr_available(cfg):
        raise RuntimeError(
            "FunASR 未就绪（需要 funasr + torch）。\n"
            "请到 设置 → 本机环境 重新安装 FunASR，或运行：\n"
            "  .\\scripts\\setup\\setup_funasr.ps1"
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
    env["PYTHONUTF8"] = "1"
    out_path = wav_path.with_name(wav_path.stem + ".funasr.txt")
    cmd = [
        py,
        str(runner.resolve()),
        "--audio",
        str(wav_path.resolve()),
        "--model",
        model,
    ]
    try:
        text = _write_and_read_asr_out(cmd, cwd=funasr_dir, env=env, out_path=out_path)
    except RuntimeError as exc:
        raise RuntimeError(f"FunASR 转写失败:\n{exc}") from exc
    if not text:
        raise RuntimeError("FunASR 未识别到有效口播文案")
    # Guard: heavily corrupted pipe/file should not be accepted as 口播
    if text.count("\ufffd") >= max(3, len(text) // 10):
        raise RuntimeError(
            "FunASR 输出疑似乱码（编码损坏）。请确认 FunASR 环境已安装 torch，"
            "或改用 Whisper / 重新提取。"
        )
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

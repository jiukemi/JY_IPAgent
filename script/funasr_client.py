"""Client for the FunASR warm worker (persistent subprocess, model loaded once).

Falls back to a one-shot subprocess when the worker is disabled or unavailable.
Mirrors the IndexTTS worker client pattern (stdio JSON lines protocol).
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
from pathlib import Path

from script.extract import _funasr_python

ROOT = Path(__file__).resolve().parent.parent

_PROTO = "FUNASR_JSON::"

_worker_proc: subprocess.Popen | None = None
_worker_lock = threading.Lock()
_worker_model: str | None = None


def _funasr_cfg(cfg: dict) -> dict:
    return (cfg.get("script") or {}).get("funasr") or {}


def worker_enabled(cfg: dict) -> bool:
    return _funasr_cfg(cfg).get("worker_enabled", False) is True


def worker_model(cfg: dict) -> str:
    return (cfg.get("script") or {}).get("funasr_model", "sensevoice")


def is_worker_running() -> bool:
    with _worker_lock:
        return _worker_proc is not None and _worker_proc.poll() is None


def shutdown_funasr_worker() -> None:
    global _worker_proc, _worker_model
    with _worker_lock:
        proc = _worker_proc
        _worker_proc = None
        _worker_model = None
    if proc is None or proc.poll() is not None:
        return
    try:
        if proc.stdin:
            proc.stdin.write("shutdown\n")
            proc.stdin.flush()
    except OSError:
        pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def _start_worker(cfg: dict) -> subprocess.Popen:
    from script.extract import _resolve_funasr_dir

    py = _funasr_python(cfg)
    fun_dir = _resolve_funasr_dir(cfg)
    worker_script = fun_dir / "worker.py"
    if not worker_script.is_file():
        worker_script = ROOT / "tools" / "FunASR" / "worker.py"
    model = worker_model(cfg)
    cmd = [py, "-u", str(worker_script), "--model", model]
    import os as _os
    env = _os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    proc = subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=env,
    )
    assert proc.stdout is not None
    deadline = 300.0  # first model load can take a while
    t0 = time.time()
    while time.time() - t0 < deadline:
        line = proc.stdout.readline()
        if not line and proc.poll() is not None:
            raise RuntimeError("FunASR worker 启动失败（进程已退出）")
        if not line:
            continue
        line = line.strip()
        if not line.startswith(_PROTO):
            continue
        data = json.loads(line[len(_PROTO):])
        if data.get("ready"):
            return proc
        if data.get("status") == "loading":
            continue
        err = data.get("error") or "unknown"
        raise RuntimeError(f"FunASR worker 未就绪: {err}")
    raise RuntimeError("FunASR worker 加载超时（首次下载/加载模型可能需数分钟）")


def ensure_funasr_worker(cfg: dict) -> bool:
    """Start warm worker if enabled. Returns True when worker is ready."""
    global _worker_proc, _worker_model
    if not worker_enabled(cfg):
        return False
    # Fail fast with a clear message instead of a silent broken venv launch
    from script.extract import _funasr_available, _funasr_python

    if not _funasr_available(cfg):
        raise RuntimeError(
            "FunASR 环境缺少 torch（常驻 ASR 无法启动）。\n"
            f"当前解释器：{_funasr_python(cfg)}\n"
            "请执行：tools\\FunASR\\.venv\\Scripts\\python.exe -m pip install torch torchaudio\n"
            "或运行 .\\scripts\\setup\\setup_funasr.ps1"
        )
    model = worker_model(cfg)
    with _worker_lock:
        if (
            _worker_proc is not None
            and _worker_proc.poll() is None
            and _worker_model == model
        ):
            return True
        old = _worker_proc
        _worker_proc = None
        _worker_model = None
    if old is not None and old.poll() is None:
        try:
            old.stdin.write("shutdown\n")  # type: ignore[union-attr]
            old.stdin.flush()  # type: ignore[union-attr]
        except OSError:
            old.kill()
    proc = _start_worker(cfg)
    with _worker_lock:
        _worker_proc = proc
        _worker_model = model
    return True


def transcribe_via_worker(cfg: dict, wav_path: Path, *, timeout: float = 300.0) -> str:
    """Send one transcribe job to the warm worker. Raises on failure."""
    if not ensure_funasr_worker(cfg):
        raise RuntimeError("FunASR worker 未启用")
    with _worker_lock:
        proc = _worker_proc
        if proc is None or proc.poll() is not None:
            raise RuntimeError("FunASR worker 不可用")
        assert proc.stdin is not None
        assert proc.stdout is not None
        job = {"audio": str(wav_path.resolve())}
        proc.stdin.write(json.dumps(job, ensure_ascii=False) + "\n")
        proc.stdin.flush()

        t0 = time.time()
        while time.time() - t0 < timeout:
            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    raise RuntimeError("FunASR worker 意外退出")
                continue
            line = line.strip()
            if not line.startswith(_PROTO):
                continue
            data = json.loads(line[len(_PROTO):])
            if data.get("ok"):
                return str(data.get("text") or "").strip()
            err = data.get("error") or "转写失败"
            raise RuntimeError(err)
        raise RuntimeError("FunASR worker 转写超时")


def try_worker_transcribe(cfg: dict, wav_path: Path) -> str | None:
    """Return transcript text if worker handled it, else None."""
    if not worker_enabled(cfg):
        return None
    try:
        return transcribe_via_worker(cfg, wav_path)
    except Exception:
        shutdown_funasr_worker()
        return None


def worker_status() -> dict:
    return {
        "enabled_running": is_worker_running(),
        "model": _worker_model,
    }

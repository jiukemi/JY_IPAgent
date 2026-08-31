"""Client for IndexTTS2 warm worker (persistent subprocess, model loaded once)."""

from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path

from tts.engine import venv_python
from tts.progress import MARKER, _parse_marker, stage_label

_worker_proc: subprocess.Popen | None = None
_worker_lock = threading.Lock()
_worker_cfg_key: str | None = None


def is_worker_running() -> bool:
    with _worker_lock:
        return _worker_proc is not None and _worker_proc.poll() is None


def _cfg_key(cfg: dict) -> str:
    it = cfg.get("indextts", {}) or {}
    return str(Path(cfg.get("paths", {}).get("indextts_dir", "")).resolve()) + "|" + str(
        it.get("model_dir", "checkpoints")
    )


def worker_enabled(cfg: dict) -> bool:
    it = cfg.get("indextts", {}) or {}
    return it.get("worker_enabled", True) is not False


def shutdown_indextts_worker() -> None:
    global _worker_proc, _worker_cfg_key
    with _worker_lock:
        proc = _worker_proc
        _worker_proc = None
        _worker_cfg_key = None
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
    py = venv_python(cfg, "indextts_dir")
    worker_script = Path(__file__).resolve().parent / "indextts_worker.py"
    config_path = Path("config.yaml").resolve()
    cmd = [py, "-u", str(worker_script), "--config", str(config_path), "--stdio"]
    proc = subprocess.Popen(
        cmd,
        cwd=str(Path.cwd()),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    assert proc.stdout is not None
    deadline = 600.0
    import time

    t0 = time.time()
    while time.time() - t0 < deadline:
        line = proc.stdout.readline()
        if not line and proc.poll() is not None:
            raise RuntimeError("IndexTTS worker 启动失败（进程已退出）")
        if not line:
            continue
        if line.startswith(MARKER):
            continue
        if line.strip().startswith("{"):
            data = json.loads(line.strip())
            if data.get("ready"):
                return proc
            err = data.get("error") or "unknown"
            raise RuntimeError(f"IndexTTS worker 未就绪: {err}")
    raise RuntimeError("IndexTTS worker 加载超时（首次加载模型可能需 1–3 分钟）")


def ensure_indextts_worker(cfg: dict) -> bool:
    """Start warm worker if enabled. Returns True when worker is ready."""
    global _worker_proc, _worker_cfg_key
    if not worker_enabled(cfg):
        return False
    key = _cfg_key(cfg)
    with _worker_lock:
        if _worker_proc is not None and _worker_proc.poll() is None and _worker_cfg_key == key:
            return True
        old = _worker_proc
        _worker_proc = None
        _worker_cfg_key = None
    if old is not None and old.poll() is None:
        try:
            old.kill()
        except OSError:
            pass
    proc = _start_worker(cfg)
    with _worker_lock:
        _worker_proc = proc
        _worker_cfg_key = key
    return True


def synthesize_via_worker(
    cfg: dict,
    job: dict,
    *,
    on_progress=None,
    span: tuple[float, float] = (0.15, 0.88),
) -> dict:
    """Send one synthesis job to warm worker. Raises on failure."""
    if not ensure_indextts_worker(cfg):
        raise RuntimeError("IndexTTS worker 未启用或启动失败")

    start, end = span
    with _worker_lock:
        proc = _worker_proc
        if proc is None or proc.poll() is not None:
            raise RuntimeError("IndexTTS worker 不可用，将回退单次子进程")
        assert proc.stdin is not None
        assert proc.stdout is not None
        proc.stdin.write(json.dumps(job, ensure_ascii=False) + "\n")
        proc.stdin.flush()

        while True:
            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    raise RuntimeError("IndexTTS worker 意外退出")
                continue
            line = line.rstrip("\n\r")
            parsed = _parse_marker(line)
            if parsed and on_progress:
                pct, key, seg, audio_sec = parsed
                mapped = start + pct * (end - start)
                desc = stage_label(key)
                if seg and seg[1] > 0:
                    desc += f" · 段落 {seg[0]}/{seg[1]}"
                on_progress(mapped, desc)
                continue
            if line.startswith("{"):
                data = json.loads(line)
                if data.get("ok"):
                    return data
                err = data.get("error") or "合成失败"
                trace = data.get("trace") or ""
                raise RuntimeError(f"{err}\n{trace}".strip())


def try_worker_synthesize(
    cfg: dict,
    job: dict,
    *,
    on_progress=None,
    span: tuple[float, float] = (0.15, 0.88),
) -> bool:
    """Return True if worker handled the job."""
    if not worker_enabled(cfg):
        return False
    try:
        synthesize_via_worker(cfg, job, on_progress=on_progress, span=span)
        return True
    except Exception:
        shutdown_indextts_worker()
        return False

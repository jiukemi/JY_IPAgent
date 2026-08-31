"""Cooperative cancel for long-running GPU / subprocess jobs (lipsync, publish, …)."""

from __future__ import annotations

import os
import subprocess
import threading
from typing import Any


class TaskCancelled(Exception):
    """Raised when the user requests job termination."""


_lock = threading.Lock()
_cancel = threading.Event()
_procs: set[subprocess.Popen] = set()
_label = ""


def begin_job(label: str = "") -> None:
    """Clear previous cancel flag and mark a new job as active."""
    global _label
    with _lock:
        _cancel.clear()
        _label = (label or "").strip()
        # Drop already-finished process handles
        dead = [p for p in _procs if p.poll() is not None]
        for p in dead:
            _procs.discard(p)


def is_cancelled() -> bool:
    return _cancel.is_set()


def check_cancelled() -> None:
    if _cancel.is_set():
        raise TaskCancelled("任务已取消")


def register_proc(proc: subprocess.Popen) -> None:
    with _lock:
        _procs.add(proc)


def unregister_proc(proc: subprocess.Popen) -> None:
    with _lock:
        _procs.discard(proc)


def _kill_tree(proc: subprocess.Popen) -> bool:
    if proc.poll() is not None:
        return False
    pid = proc.pid
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=True,
                check=False,
            )
        else:
            proc.kill()
        return True
    except OSError:
        return False


def request_cancel() -> dict[str, Any]:
    """Signal cancel and force-kill tracked subprocess trees."""
    _cancel.set()
    killed: list[int] = []
    with _lock:
        procs = list(_procs)
        label = _label
    for proc in procs:
        pid = proc.pid
        if _kill_tree(proc):
            killed.append(pid)
        try:
            proc.wait(timeout=3)
        except Exception:
            pass
        unregister_proc(proc)
    return {
        "ok": True,
        "cancelled": True,
        "label": label,
        "killed_pids": killed,
        "message": "已请求终止" + (f"（{label}）" if label else ""),
    }


def active_job() -> dict[str, Any]:
    with _lock:
        alive = [p.pid for p in _procs if p.poll() is None]
        return {
            "label": _label,
            "cancel_requested": _cancel.is_set(),
            "pids": alive,
            "running": bool(alive) or (bool(_label) and not _cancel.is_set()),
        }

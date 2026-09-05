"""Production / development server entry (replaces Gradio app.py)."""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

# Packaged / venv launches must find local packages (api/, workflow/, …)
_ROOT = Path(__file__).resolve().parent
_root_s = str(_ROOT)
if _root_s not in sys.path:
    sys.path.insert(0, _root_s)
# Also keep cwd-based imports working when spawn cwd differs
_cwd = os.getcwd()
if _cwd and _cwd not in sys.path:
    sys.path.insert(0, _cwd)

import uvicorn

from api.main import boot_workers


def pick_free_port(start: int = 7860, end: int = 7890) -> int:
    for port in range(start, end + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise OSError(f"端口 {start}-{end} 均被占用")


if __name__ == "__main__":
    os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost,::1")
    try:
        from workflow.app_config import ensure_config_file

        ensure_config_file()
    except Exception as exc:
        print(f"* config ensure skipped: {exc}")
    try:
        from workflow.runtime_bootstrap import apply_runtime_path, ensure_ffmpeg

        apply_runtime_path()
        # Never block backend listen on FFmpeg download (offline / slow mirrors look like
        # "polling 7860-7890"). Install via Settings or first media use.
        ensure_ffmpeg(download=False)
    except Exception as exc:
        print(f"* runtime bootstrap skipped: {exc}")
    boot_workers()
    port = int(os.environ.get("AGENT_PORT", "0")) or pick_free_port()
    if port != 7860:
        print(f"* 7860 已占用，改用端口 {port}")
    print(f"* 打开 http://127.0.0.1:{port}")
    print(f"* ROOT={_ROOT}")
    uvicorn.run(
        "api.main:app",
        host="127.0.0.1",
        port=port,
        reload=False,
    )

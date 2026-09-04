"""Safe static file responses with HTTP Range support (needed for <audio>/<video>)."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from starlette.responses import FileResponse, Response


def safe_file_bytes(path: Path) -> bytes:
    p = path.resolve()
    if not p.is_file():
        raise FileNotFoundError(str(p))
    data = p.read_bytes()
    if len(data) < 1:
        raise ValueError(f"文件为空: {p}")
    return data


def safe_file_response(
    path: Path,
    media_type: str | None = None,
    *,
    cache_control: str = "no-store, no-cache, must-revalidate",
) -> Response:
    """Serve a local file without loading it entirely into memory.

    Uses Starlette FileResponse so browsers can Range-seek media (fixes
    asset-center / BGM preview that previously hung or failed to play).
    """
    p = path.resolve()
    if not p.is_file():
        raise FileNotFoundError(str(p))
    try:
        size = p.stat().st_size
    except OSError as exc:
        raise FileNotFoundError(str(p)) from exc
    if size < 1:
        raise ValueError(f"文件为空: {p}")
    if not media_type:
        media_type = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    headers = {"Cache-Control": cache_control}
    if "no-store" in cache_control or "no-cache" in cache_control:
        headers["Pragma"] = "no-cache"
    return FileResponse(
        path=p,
        media_type=media_type,
        headers=headers,
    )


def stable_audio_path(path: str | None, *, min_bytes: int = 100) -> str | None:
    if not path:
        return None
    p = Path(path).resolve()
    if not p.is_file():
        return None
    try:
        if p.stat().st_size < min_bytes:
            return None
    except OSError:
        return None
    return str(p)

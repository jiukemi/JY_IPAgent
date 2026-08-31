"""Safe static file responses (avoids Content-Length mismatch on Windows)."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from starlette.responses import Response


def safe_file_bytes(path: Path) -> bytes:
    p = path.resolve()
    if not p.is_file():
        raise FileNotFoundError(str(p))
    data = p.read_bytes()
    if len(data) < 1:
        raise ValueError(f"文件为空: {p}")
    return data


def safe_file_response(path: Path, media_type: str | None = None) -> Response:
    p = path.resolve()
    data = safe_file_bytes(p)
    if not media_type:
        media_type = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    return Response(
        content=data,
        media_type=media_type,
        headers={
            "Content-Length": str(len(data)),
            "Accept-Ranges": "bytes",
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
        },
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

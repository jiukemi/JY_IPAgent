"""Static session file serving."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from workflow.file_serve import safe_file_response

router = APIRouter(prefix="/api/files", tags=["files"])


def _session_file_or_403(path: str) -> Path:
    p = Path(path).resolve()
    root = Path("output/sessions").resolve()
    if not str(p).startswith(str(root)):
        raise HTTPException(status_code=403, detail="路径不允许")
    return p


@router.get("/session")
def session_file(path: str):
    """Serve session files over HTTP (browser / non-desktop). Desktop uses agent-media://."""
    p = _session_file_or_403(path)
    try:
        return safe_file_response(p)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="文件不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/prepare")
def prepare_session_media(path: str = Query(...)):
    """Remux MP4 moov-to-front once so local/HTTP preview can start immediately."""
    from workflow.mp4_faststart import ensure_mp4_faststart, mp4_needs_faststart

    p = _session_file_or_403(path)
    if not p.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    needed = p.suffix.lower() in {".mp4", ".m4v", ".mov"} and mp4_needs_faststart(p)
    if needed:
        p = ensure_mp4_faststart(p)
    return {
        "ok": True,
        "path": str(p.resolve()),
        "optimized": bool(needed),
    }

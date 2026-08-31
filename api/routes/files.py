"""Static session file serving."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from workflow.file_serve import safe_file_response

router = APIRouter(prefix="/api/files", tags=["files"])


@router.get("/session")
def session_file(path: str):
    from pathlib import Path

    p = Path(path).resolve()
    root = Path("output/sessions").resolve()
    if not str(p).startswith(str(root)):
        raise HTTPException(status_code=403, detail="路径不允许")
    try:
        return safe_file_response(p)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="文件不存在") from exc

"""Session management routes."""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile

from api.schemas import SessionItem, SessionRename, SessionSnapshot, StageResult
from api.services.stages import (
    delete_named_session_dubbing,
    delete_named_session_lipsync,
    get_session_snapshot,
    patch_dubbing_segment,
    save_named_session_dubbing,
    select_session_dubbing,
    select_session_lipsync,
    upload_session_dubbing,
)
from workflow.session import (
    default_display_name,
    delete_session,
    ensure_session_dir,
    format_created_at,
    get_session_by_path,
    latest_session,
    list_sessions,
    new_session,
    rename_session,
    system_jobs_session,
)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.get("/system-jobs")
def system_jobs() -> dict:
    """Fixed session used for engine-install jobs (visible across user sessions)."""
    path = system_jobs_session()
    return {"ok": True, "path": str(path), "name": "系统任务"}


def _to_item(row: dict, current: str | None) -> SessionItem:
    path = row["path"]
    return SessionItem(
        path=path,
        id=row.get("id", ""),
        name=row.get("name", ""),
        created_at=row.get("created_label") or format_created_at(row.get("created_at", "")),
        badges=row.get("badges") or [],
        status=row.get("status") or "",
        is_current=bool(current and str(path) == str(current)),
    )


@router.get("")
def list_all(current: str | None = None) -> list[SessionItem]:
    sessions = list_sessions()
    return [_to_item(s, current) for s in sessions]


@router.get("/active")
def active_session() -> dict:
    path = ensure_session_dir(str(latest_session() or ""))
    item = get_session_by_path(str(path)) or {}
    return {"path": str(path), "name": item.get("name", default_display_name())}


@router.post("")
def create_session() -> dict:
    path = new_session(name=default_display_name())
    snap = get_session_snapshot(str(path))
    return snap


@router.get("/snapshot", response_model=SessionSnapshot)
def snapshot(path: str = Query(..., description="Session directory path")) -> SessionSnapshot:
    p = Path(path)
    if not p.is_dir():
        raise HTTPException(status_code=404, detail="会话不存在")
    data = get_session_snapshot(str(p.resolve()))
    return SessionSnapshot(**data)


@router.patch("")
def rename(path: str = Query(...), body: SessionRename | None = None) -> dict:
    if body is None:
        raise HTTPException(status_code=400, detail="缺少 body")
    resolved = ensure_session_dir(path)
    rename_session(str(resolved), body.name)
    item = get_session_by_path(str(resolved)) or {}
    return {"path": str(resolved), "name": item.get("name", body.name)}


@router.delete("")
def remove(path: str = Query(...)) -> dict:
    resolved = ensure_session_dir(path)
    ok = delete_session(str(resolved))
    if not ok:
        raise HTTPException(status_code=404, detail="会话不存在或无法删除")
    return {"ok": True}


@router.post("/dubbing/upload", response_model=StageResult)
async def dubbing_upload(
    session_path: str = Form(...),
    source_type: str = Form("upload"),
    audio: UploadFile = File(...),
) -> StageResult:
    suffix = Path(audio.filename or "dub.wav").suffix or ".wav"
    tmp = Path(tempfile.gettempdir()) / f"dub_upload_{audio.filename or 'dub.wav'}"
    tmp.write_bytes(await audio.read())
    try:
        data = upload_session_dubbing(session_path, str(tmp), source_type=source_type)
        snap = get_session_snapshot(session_path)
        return StageResult(message=data.get("message", ""), data={**data, "session": snap})
    finally:
        tmp.unlink(missing_ok=True)


@router.post("/dubbing/patch", response_model=StageResult)
async def dubbing_patch(
    session_path: str = Form(...),
    segment_index: int = Form(...),
    mode: str = Form("resynth"),
    text: str = Form(""),
    voice_uid: str = Form(""),
    speed_mode: str = Form("balanced"),
    crossfade_ms: float = Form(40.0),
    audio: UploadFile | None = File(None),
) -> StageResult:
    tmp: Path | None = None
    try:
        replacement: str | None = None
        if audio is not None and audio.filename:
            tmp = Path(tempfile.gettempdir()) / f"dub_patch_{audio.filename}"
            tmp.write_bytes(await audio.read())
            replacement = str(tmp)
        data = patch_dubbing_segment(
            session_path,
            int(segment_index),
            mode=mode,
            text=text or None,
            voice_uid=voice_uid or None,
            speed_mode=speed_mode or "balanced",
            replacement_audio=replacement,
            crossfade_ms=float(crossfade_ms),
        )
        snap = get_session_snapshot(session_path)
        return StageResult(message=data.get("message", ""), data={**data, "session": snap})
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


@router.post("/dubbing/save", response_model=StageResult)
def dubbing_save(
    session_path: str = Form(...),
    name: str = Form(...),
    audio_path: str = Form(""),
) -> StageResult:
    data = save_named_session_dubbing(
        session_path,
        name,
        audio_path or None,
    )
    snap = get_session_snapshot(session_path)
    return StageResult(message=data.get("message", ""), data={**data, "session": snap})


@router.put("/dubbing/select", response_model=StageResult)
def dubbing_select(
    session_path: str = Query(...),
    audio_path: str = Query(...),
) -> StageResult:
    data = select_session_dubbing(session_path, audio_path)
    snap = get_session_snapshot(session_path)
    return StageResult(message=data.get("message", ""), data={**data, "session": snap})


@router.put("/lipsync/select", response_model=StageResult)
def lipsync_select(
    session_path: str = Query(...),
    video_path: str = Query(...),
) -> StageResult:
    data = select_session_lipsync(session_path, video_path)
    snap = get_session_snapshot(session_path)
    return StageResult(message=data.get("message", ""), data={**data, "session": snap})


@router.delete("/lipsync")
def lipsync_delete(
    session_path: str = Query(...),
    take_id: str = Query(...),
) -> StageResult:
    data = delete_named_session_lipsync(session_path, take_id)
    snap = get_session_snapshot(session_path)
    return StageResult(
        message=f"已删除口播「{data.get('name', take_id)}」",
        data={**data, "session": snap},
    )


@router.delete("/dubbing")
def dubbing_delete(
    session_path: str = Query(...),
    dub_id: str = Query(...),
) -> StageResult:
    data = delete_named_session_dubbing(session_path, dub_id)
    snap = get_session_snapshot(session_path)
    return StageResult(
        message=f"已删除配音「{data.get('name', dub_id)}」",
        data={**data, "session": snap},
    )

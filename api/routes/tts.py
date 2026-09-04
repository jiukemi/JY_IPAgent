"""TTS and voice routes."""

from __future__ import annotations

import asyncio
import base64
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse

from api.schemas import StageResult, TtsBody, TtsPreviewBody, TtsSettingsPayload, VoiceItem
from api.services.stages import run_tts, run_tts_preview, save_clone_voice
from workflow.app_config import CONFIG_PATH, load_cfg
from workflow.deployment import resolve_tts_backend
from workflow.tts_model_options import build_tts_options, save_tts_settings
from tts.preview_cache import build_preview, get_preview_path, update_preview_manifest
from tts.speed import speed_choices, speed_choices_for_engine
from tts.voice_catalog import (
    default_voice_uid_for_engine,
    list_clone_voices,
    list_system_voices,
    list_voices_for_tts_engine,
    refresh_catalog,
    selected_label,
)
from tts.voices import delete_voice, get_voice, list_voices, next_default_name

router = APIRouter(prefix="/api", tags=["tts"])
_tts_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="tts")

# 克隆参考音一般很小；列表里直接塞 data URL，点击零延迟本地播
_CLONE_INLINE_MAX_BYTES = 2_500_000


def _clone_audio_data_url(voice_id: str) -> str | None:
    entry = get_voice(voice_id)
    if not entry:
        return None
    path = Path(str(entry.get("reference_wav") or ""))
    if not path.is_file():
        return None
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size < 100:
        return None
    if size > _CLONE_INLINE_MAX_BYTES:
        return f"/api/voices/{voice_id}/audio"
    raw = path.read_bytes()
    b64 = base64.standard_b64encode(raw).decode("ascii")
    return f"data:audio/wav;base64,{b64}"


def _voice_items(entries) -> list[VoiceItem]:
    items: list[VoiceItem] = []
    for e in entries:
        preview = None
        local_path = None
        if e.uid.startswith("clone:"):
            preview = _clone_audio_data_url(e.uid[len("clone:") :])
            disk = get_preview_path(e.uid)
            if disk:
                local_path = str(Path(disk).resolve())
        else:
            disk = get_preview_path(e.uid)
            if disk:
                local_path = str(Path(disk).resolve())
                preview = f"/api/files/preview?voice={e.uid}"
        items.append(
            VoiceItem(
                uid=e.uid,
                label=e.card_label,
                kind="system" if e.uid.startswith("sys:") else "clone",
                preview_url=preview,
                local_path=local_path,
                category=getattr(e, "category", "") or "",
                hint=getattr(e, "hint", "") or "",
            )
        )
    return items


@router.get("/voices/system")
def system_voices(backend: str | None = None, category: str | None = None) -> list[VoiceItem]:
    eng = (backend or resolve_tts_backend(load_cfg())).lower()
    if backend or not category:
        system, _ = list_voices_for_tts_engine(eng)
        if category:
            system = [e for e in system if e.category == category]
    else:
        system = list_system_voices(category)
    return _voice_items(system)


@router.get("/voices/clone")
def clone_voices(backend: str | None = None) -> list[VoiceItem]:
    eng = (backend or resolve_tts_backend(load_cfg())).lower()
    if backend:
        _, clones = list_voices_for_tts_engine(eng)
    else:
        clones = list_clone_voices()
    return _voice_items(clones)


@router.get("/voices/default")
def default_voice(backend: str | None = None) -> dict:
    eng = (backend or resolve_tts_backend(load_cfg())).lower()
    uid = default_voice_uid_for_engine(eng)
    return {"uid": uid, "label": selected_label(uid) if uid else ""}


@router.get("/voices/library")
def voice_library() -> list[dict]:
    rows: list[dict] = []
    for v in list_voices():
        vid = v["id"]
        uid = f"clone:{vid}"
        row = dict(v)
        row["uid"] = uid
        row["preview_url"] = _clone_audio_data_url(vid)
        ref = Path(str(v.get("reference_wav") or ""))
        row["local_path"] = str(ref.resolve()) if ref.is_file() else None
        rows.append(row)
    return rows


@router.get("/voices/{voice_id}/audio")
def voice_audio(voice_id: str):
    """Serve saved reference wav directly (fallback when too large to inline)."""
    vid = (voice_id or "").strip()
    if vid.startswith("clone:"):
        vid = vid[len("clone:") :]
    entry = get_voice(vid)
    if not entry:
        raise HTTPException(status_code=404, detail="音色不存在")
    path = Path(str(entry.get("reference_wav") or ""))
    if not path.is_file():
        raise HTTPException(status_code=404, detail="参考音文件缺失")
    from workflow.file_serve import safe_file_response

    return safe_file_response(path, media_type="audio/wav", cache_control="private, max-age=86400")


@router.get("/voices/next-name")
def next_voice_name(source: str = "upload") -> dict:
    src = "record" if (source or "").lower() == "record" else "upload"
    return {"name": next_default_name(src)}


@router.delete("/voices/{voice_id}")
def remove_voice(voice_id: str) -> dict:
    vid = (voice_id or "").strip()
    if vid.startswith("clone:"):
        vid = vid[len("clone:") :]
    if not vid:
        raise HTTPException(status_code=400, detail="缺少音色 ID")
    if not delete_voice(vid):
        raise HTTPException(status_code=404, detail="音色不存在或已删除")
    refresh_catalog()
    return {"ok": True}


@router.post("/voices/clone", response_model=StageResult)
async def clone_voice(
    name: str = Form(""),
    source_type: str = Form("upload"),
    prompt_text: str = Form(""),
    audio: UploadFile = File(...),
) -> StageResult:
    import tempfile
    from pathlib import Path

    tmp = Path(tempfile.gettempdir()) / f"clone_upload_{audio.filename or 'ref.wav'}"
    tmp.write_bytes(await audio.read())
    entry = save_clone_voice(
        name or next_default_name(source_type),
        str(tmp),
        source_type,
        prompt_text=prompt_text,
    )
    return StageResult(message=f"已保存音色 {entry['name']}", data=entry)


@router.get("/tts/speeds")
def speeds(engine: str | None = None) -> list[dict]:
    eng = (engine or resolve_tts_backend(load_cfg())).lower()
    pairs = speed_choices_for_engine(eng)
    return [{"value": val, "label": lbl} for lbl, val in pairs]


@router.get("/tts/options")
def tts_options(engine: str | None = None) -> dict:
    cfg = load_cfg()
    opts = build_tts_options(cfg, preview_engine=engine)
    eng = opts["engine"]
    uid = default_voice_uid_for_engine(eng)
    opts["default_voice_uid"] = uid
    return opts


@router.put("/tts/settings")
def put_tts_settings(body: TtsSettingsPayload) -> dict:
    cfg = save_tts_settings(
        engine=body.engine,
        values=body.values,
        cfg_path=CONFIG_PATH,
    )
    opts = build_tts_options(cfg)
    opts["default_voice_uid"] = default_voice_uid_for_engine(opts["engine"])
    return opts


@router.post("/tts/verify")
def verify_tts(engine: str | None = None) -> dict:
    cfg = load_cfg()
    from workflow.tts_model_options import engine_health

    eng = (engine or resolve_tts_backend(cfg)).lower()
    return engine_health(cfg, eng, ping=True)


def _run_tts_job(body: TtsBody, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue) -> None:
    def on_progress(p: float, msg: str | None = None) -> None:
        loop.call_soon_threadsafe(
            queue.put_nowait,
            {"type": "progress", "p": p, "msg": msg or ""},
        )

    try:
        data = run_tts(
            body.session_path,
            body.text,
            body.voice_uid,
            body.speed_mode,
            backend=body.backend,
            style_extra=body.style_extra,
            on_progress=on_progress,
        )
        loop.call_soon_threadsafe(queue.put_nowait, {"type": "done", "data": data})
    except Exception as exc:
        from workflow.task_control import TaskCancelled

        msg = "任务已取消" if isinstance(exc, TaskCancelled) or "已取消" in str(exc) else str(exc)
        loop.call_soon_threadsafe(
            queue.put_nowait,
            {"type": "error", "msg": msg},
        )


@router.post("/tts/synthesize/cancel")
def synthesize_cancel() -> dict:
    from workflow.task_control import request_cancel

    return request_cancel()


@router.post("/tts/synthesize/stream")
async def synthesize_stream(body: TtsBody):
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    async def event_stream():
        yield f"data: {json.dumps({'type': 'start'}, ensure_ascii=False)}\n\n"
        _tts_executor.submit(_run_tts_job, body, loop, queue)
        finished = False
        while not finished:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=1.0)
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
                if item.get("type") in ("done", "error"):
                    finished = True
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/tts/preview-emo", response_model=StageResult)
def preview_clone_emo(body: TtsPreviewBody) -> StageResult:
    """Quick A/B preview for clone emotion — does not replace dubbing_16k.wav."""
    data = run_tts_preview(
        body.session_path,
        body.voice_uid,
        text=body.text,
        style_extra=body.style_extra,
        speed_mode=body.speed_mode,
        backend=body.backend,
        preview_key=body.preview_key or "styled",
    )
    note = "（无情感描述）" if not (body.style_extra or "").strip() else f"（情感：{body.style_extra.strip()[:40]}）"
    return StageResult(
        message=f"试听已生成{note}",
        data=data,
    )


@router.post("/tts/synthesize", response_model=StageResult)
def synthesize(body: TtsBody) -> StageResult:
    data = run_tts(
        body.session_path,
        body.text,
        body.voice_uid,
        body.speed_mode,
        backend=body.backend,
        style_extra=body.style_extra,
    )
    return StageResult(log=data.get("log", ""), data=data)


@router.get("/voices/label")
def voice_label(uid: str) -> dict:
    return {"uid": uid, "label": selected_label(uid)}


@router.get("/files/preview")
def voice_preview(voice: str):
    from fastapi import HTTPException

    path = get_preview_path(voice)
    if not path:
        raise HTTPException(status_code=404, detail="无预览")
    try:
        from pathlib import Path
        from workflow.file_serve import safe_file_response

        p = Path(path)
        ext = p.suffix.lower()
        media = {
            ".wav": "audio/wav",
            ".mp3": "audio/mpeg",
            ".m4a": "audio/mp4",
            ".ogg": "audio/ogg",
            ".webm": "audio/webm",
            ".flac": "audio/flac",
        }.get(ext, "audio/wav")
        # 音色参考音落盘后不变；允许短缓存，避免每次试听都重新读盘
        cache = "private, max-age=600" if (voice or "").startswith("clone:") else "no-store"
        return safe_file_response(p, media_type=media, cache_control=cache)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="无预览") from exc


@router.get("/tts/previews/status")
def previews_status(engine: str | None = None) -> dict:
    cfg = load_cfg()
    eng = (engine or resolve_tts_backend(cfg)).lower()
    system, _ = list_voices_for_tts_engine(eng)
    cached = [e.uid for e in system if get_preview_path(e.uid)]
    missing = [e.uid for e in system if e.uid not in cached]
    return {
        "engine": eng,
        "total": len(system),
        "cached": len(cached),
        "missing": len(missing),
        "missing_uids": missing[:20],
    }


def _build_previews_job(engine: str, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue) -> None:
    try:
        cfg = load_cfg()
        eng = (engine or resolve_tts_backend(cfg)).lower()
        system, _ = list_voices_for_tts_engine(eng)
        ok, skip, fail = 0, 0, 0
        errors: list[str] = []
        for i, entry in enumerate(system):
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {
                    "type": "progress",
                    "i": i + 1,
                    "total": len(system),
                    "label": entry.label,
                    "uid": entry.uid,
                    "p": (i + 0.5) / max(len(system), 1),
                },
            )
            if get_preview_path(entry.uid):
                skip += 1
                continue
            path, err = build_preview(entry.uid, cfg, engine=eng)
            if path:
                ok += 1
                update_preview_manifest(entry.uid, path)
            else:
                fail += 1
                if err:
                    errors.append(f"{entry.label}: {err}")
        loop.call_soon_threadsafe(
            queue.put_nowait,
            {
                "type": "done",
                "ok": ok,
                "skip": skip,
                "fail": fail,
                "errors": errors[:8],
                "p": 1.0,
            },
        )
    except Exception as exc:
        loop.call_soon_threadsafe(
            queue.put_nowait,
            {"type": "error", "msg": str(exc)},
        )


@router.post("/tts/previews/build/stream")
async def build_previews_stream(engine: str | None = Query(None)):
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    eng = (engine or resolve_tts_backend(load_cfg())).lower()

    async def event_stream():
        yield f"data: {json.dumps({'type': 'start', 'engine': eng}, ensure_ascii=False)}\n\n"
        _tts_executor.submit(_build_previews_job, eng, loop, queue)
        finished = False
        while not finished:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=1.0)
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
                if item.get("type") in ("done", "error"):
                    finished = True
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

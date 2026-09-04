"""Avatar / lipsync routes."""

from __future__ import annotations

import asyncio
import json
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse

from api.schemas import StageResult
from api.services.stages import run_lipsync
from avatar.catalog import (
    delete_avatar,
    ensure_avatar_poster,
    ensure_avatar_streamable,
    get_avatar,
    list_avatars,
    save_avatar,
)
from avatar.heygem_runtime import (
    heygem_service_status,
    start_heygem_stream_lines,
    stop_heygem,
)
from ui.avatar_stage import avatar_choices
from workflow.app_config import load_cfg
from workflow.session import ensure_session_dir

router = APIRouter(prefix="/api/avatar", tags=["avatar"])
_lipsync_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lipsync")
_ROOT = Path(__file__).resolve().parent.parent.parent


def _avatar_row(entry) -> dict:
    ensure_avatar_poster(entry)
    row = entry.to_dict()
    row["label"] = entry.name
    # media_url = 原素材；thumb_url = 网格封面（勿把视频 URL 塞进 <img>）
    row["media_url"] = f"/api/avatar/media?id={entry.id}"
    row["preview_url"] = f"/api/avatar/media?id={entry.id}"
    row["thumb_url"] = f"/api/avatar/thumb?id={entry.id}"
    row["supports_heygem"] = entry.supports_backend("heygem")
    row["supports_sadtalker"] = entry.supports_backend("sadtalker")
    return row


async def _save_lipsync_uploads(
    session_path: str,
    media: UploadFile | None,
    ref_pose: UploadFile | None,
    *,
    media_asset_id: str = "",
    ref_pose_asset_id: str = "",
) -> tuple[str | None, str | None]:
    from workflow.asset_library import stage_asset_for_lipsync

    media_path = None
    ref_pose_path = None
    session = ensure_session_dir(session_path)
    asset_media = (media_asset_id or "").strip()
    asset_pose = (ref_pose_asset_id or "").strip()

    if media and media.filename:
        ext = "." + media.filename.rsplit(".", 1)[-1] if "." in media.filename else ""
        dest = session / f"upload_media{ext or '.mp4'}"
        dest.write_bytes(await media.read())
        media_path = str(dest)
    elif asset_media:
        try:
            media_path = str(stage_asset_for_lipsync(session, asset_media, "media"))
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    if ref_pose and ref_pose.filename:
        ext = "." + ref_pose.filename.rsplit(".", 1)[-1] if "." in ref_pose.filename else ""
        dest = session / f"upload_ref_pose{ext or '.mp4'}"
        dest.write_bytes(await ref_pose.read())
        ref_pose_path = str(dest)
    elif asset_pose:
        try:
            ref_pose_path = str(stage_asset_for_lipsync(session, asset_pose, "ref_pose"))
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return media_path, ref_pose_path


def _run_lipsync_job(
    *,
    loop: asyncio.AbstractEventLoop,
    queue: asyncio.Queue,
    session_path: str,
    track_mode: str,
    backend: str,
    quality: str,
    avatar_id: str | None,
    audio_path: str | None,
    media_path: str | None,
    ref_pose_path: str | None,
    pose_style: float,
    still_head: bool,
    expression_scale: float,
) -> None:
    def on_progress(p: float, msg: str | None = None) -> None:
        loop.call_soon_threadsafe(
            queue.put_nowait,
            {"type": "progress", "p": p, "msg": msg or ""},
        )

    try:
        data = run_lipsync(
            session_path,
            track_mode,
            backend,
            quality,
            avatar_id,
            audio_path,
            media_file=media_path,
            ref_pose_file=ref_pose_path,
            pose_style=pose_style,
            still_head=still_head,
            expression_scale=expression_scale,
            on_progress=on_progress,
        )
        loop.call_soon_threadsafe(queue.put_nowait, {"type": "done", "data": data})
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "msg": detail})
    except Exception as exc:
        from workflow.task_control import TaskCancelled

        msg = "任务已取消" if isinstance(exc, TaskCancelled) or "已取消" in str(exc) else str(exc)
        loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "msg": msg})


@router.get("/choices")
def choices() -> list[dict]:
    return [{"id": a[1], "label": a[0]} for a in avatar_choices() if a[1]]


@router.get("/library")
def library() -> list[dict]:
    return [_avatar_row(e) for e in list_avatars()]


@router.get("/thumb")
def thumb(id: str = Query(..., alias="id")):
    from workflow.file_serve import safe_file_response

    entry = get_avatar(id)
    if not entry:
        raise HTTPException(status_code=404, detail="形象不存在")
    ensure_avatar_poster(entry)
    path = entry.poster_path
    if not path and entry.source_kind == "portrait":
        path = entry.preview_path
    if not path:
        raise HTTPException(status_code=404, detail="无封面")
    # Never serve video as thumb — browsers show broken-image icon in <img>
    if path.suffix.lower() in {".mp4", ".mov", ".webm", ".mkv", ".m4v", ".avi"}:
        raise HTTPException(status_code=404, detail="封面未生成")
    ext = path.suffix.lower()
    media = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }.get(ext, "image/jpeg")
    try:
        return safe_file_response(path, media_type=media, cache_control="private, max-age=86400")
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="封面文件缺失") from exc


@router.get("/media")
def media(id: str = Query(..., alias="id")):
    """Original reference video / portrait (for 查看原素材)."""
    from workflow.file_serve import safe_file_response

    entry = get_avatar(id)
    if not entry:
        raise HTTPException(status_code=404, detail="形象不存在")
    # Remux moov-to-front once so Chromium can stream instead of buffering entire file
    path = ensure_avatar_streamable(entry) or entry.preview_path
    if not path:
        raise HTTPException(status_code=404, detail="原素材缺失")
    ext = path.suffix.lower()
    media_type = {
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".webm": "video/webm",
        ".mkv": "video/x-matroska",
        ".m4v": "video/mp4",
        ".avi": "video/x-msvideo",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }.get(ext, "application/octet-stream")
    try:
        return safe_file_response(path, media_type=media_type, cache_control="private, max-age=3600")
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="原素材文件缺失") from exc


@router.post("/prepare/{avatar_id}")
def prepare_avatar(avatar_id: str) -> dict:
    """Ensure poster + faststart remux before opening lightbox (optional warm-up)."""
    entry = get_avatar(avatar_id)
    if not entry:
        raise HTTPException(status_code=404, detail="形象不存在")
    poster = ensure_avatar_poster(entry)
    media_path = ensure_avatar_streamable(entry)
    return {
        "ok": True,
        "thumb_url": f"/api/avatar/thumb?id={entry.id}",
        "media_url": f"/api/avatar/media?id={entry.id}",
        "poster_ready": bool(poster and Path(poster).is_file()),
        "streamable": bool(media_path and Path(media_path).is_file()),
    }


@router.get("/preview")
def preview(id: str = Query(..., alias="id")):
    """Backward-compatible alias → original media."""
    return media(id)


@router.post("/register", response_model=StageResult)
async def register_avatar(
    name: str = Form(""),
    media: UploadFile = File(...),
) -> StageResult:
    suffix = Path(media.filename or "ref.bin").suffix or ".mp4"
    tmp = Path(tempfile.gettempdir()) / f"avatar_upload_{media.filename or 'ref'}"
    tmp.write_bytes(await media.read())
    try:
        entry = save_avatar(name or "数字人", tmp)
        kind = "HeyGem 视频形象" if entry.source_kind == "video" else "SadTalker 肖像"
        return StageResult(
            message=f"已注册数字人「{entry.name}」（{kind}）\n\n可在 ④ 口播 选择该形象并生成视频。",
            data=_avatar_row(entry),
        )
    finally:
        tmp.unlink(missing_ok=True)


@router.post("/generate", response_model=StageResult)
def generate_and_register(
    prompt: str = Form(...),
    name: str = Form(""),
    save_to_library: bool = Form(True),
) -> StageResult:
    cfg = load_cfg()
    from avatar.ai_portrait import generate_portrait

    tmp = Path(tempfile.gettempdir()) / f"avatar_ai_{abs(hash(prompt)) % 10_000_000}.png"
    generate_portrait(cfg, prompt, tmp)
    if not save_to_library:
        return StageResult(message="AI 肖像已生成", data={"preview_path": str(tmp)})
    display = (name or prompt[:16] or "AI角色").strip()
    entry = save_avatar(display, tmp, ai_prompt=prompt)
    tmp.unlink(missing_ok=True)
    return StageResult(
        message=f"已生成并注册「{entry.name}」（SadTalker 肖像）\n\n效果弱于真实参考视频，可在 ④ 口播 使用。",
        data=_avatar_row(entry),
    )


@router.delete("/{avatar_id}")
def remove_avatar(avatar_id: str) -> dict:
    if not delete_avatar(avatar_id):
        raise HTTPException(status_code=404, detail="形象不存在")
    return {"ok": True}


@router.get("/heygem/status")
def heygem_status() -> dict:
    return heygem_service_status(load_cfg())


@router.get("/heygem/wizard")
def heygem_wizard() -> dict:
    """4-step HeyGem install wizard snapshot (GPU / Docker / pack / load+start)."""
    from workflow.heygem_wizard import wizard_status

    return wizard_status()


@router.post("/heygem/wizard/open-docker")
def heygem_wizard_open_docker() -> dict:
    from workflow.heygem_wizard import open_docker_desktop_download

    return open_docker_desktop_download()


@router.post("/heygem/wizard/launch-docker")
def heygem_wizard_launch_docker() -> dict:
    from workflow.heygem_wizard import try_launch_docker_desktop

    return try_launch_docker_desktop()


@router.post("/heygem/wizard/load-image")
def heygem_wizard_load_image(body: dict | None = None) -> dict:
    """docker load runtime tar for recommended (or specified) GPU family."""
    from workflow.heygem_wizard import docker_load_tar

    body = body or {}
    family = (body.get("family") or "").strip() or None
    path = (body.get("path") or "").strip()
    return docker_load_tar(Path(path) if path else None, family=family)


@router.post("/heygem/stop")
def heygem_stop() -> dict:
    ok, msg = stop_heygem()
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True, "message": msg}


@router.post("/heygem/start/stream")
async def heygem_start_stream():
    argv = start_heygem_stream_lines()
    if not argv:
        raise HTTPException(
            status_code=400,
            detail="口播引擎组件未就绪：请到设置→组件中心下载并安装，或检查 start.ps1",
        )

    async def events():
        yield f"data: {json.dumps({'type': 'start', 'p': 0.02}, ensure_ascii=False)}\n\n"
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(_ROOT),
        )
        assert proc.stdout is not None
        progress = 0.05
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").rstrip()
            if text:
                low = text.lower()
                if any(k in low for k in ("clone", "pull", "download", "拉取", "镜像")):
                    progress = max(progress, 0.35)
                elif any(k in low for k in ("compose", "up", "start", "启动")):
                    progress = max(progress, 0.55)
                elif any(k in low for k in ("ok", "ready", "成功", "is up")):
                    progress = max(progress, 0.88)
                else:
                    progress = min(progress + 0.012, 0.9)
                yield f"data: {json.dumps({'type': 'log', 'line': text, 'p': progress}, ensure_ascii=False)}\n\n"
        code = await proc.wait()
        cfg = load_cfg()
        ready = False
        for i in range(45):
            if heygem_service_status(cfg)["ready"]:
                ready = True
                break
            yield f"data: {json.dumps({'type': 'progress', 'p': min(0.9, 0.6 + i * 0.007), 'msg': f'等待 HeyGem 就绪… ({i + 1}/45)'}, ensure_ascii=False)}\n\n"
            await asyncio.sleep(2)
        st = heygem_service_status(cfg)
        payload = {
            "type": "done",
            "exit_code": code,
            "ready": st["ready"],
            "p": 1.0,
            "state": st["state"],
            "hint": st["hint"],
        }
        if code != 0:
            payload["error"] = f"启动脚本退出码 {code}，请查看上方日志"
        elif not st["ready"]:
            if st["state"] == "no_docker":
                payload["error"] = "Docker Desktop 未运行，无法启动 HeyGem 容器"
            else:
                payload["error"] = (
                    "镜像拉取或容器启动尚未完成（首次约 10–30 分钟）。"
                    "请查看上方日志是否仍在 Downloading/Pulling；完成后点「刷新状态」。"
                )
        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/lipsync/enqueue")
async def lipsync_enqueue(
    session_path: str = Form(...),
    track_mode: str = Form("digital"),
    backend: str = Form(""),
    quality: str = Form("balanced"),
    avatar_id: str = Form(""),
    audio_path: str = Form(""),
    pose_style: float = Form(0),
    still_head: str = Form(""),
    expression_scale: float = Form(1.0),
    media_asset_id: str = Form(""),
    ref_pose_asset_id: str = Form(""),
    force: str = Form("true"),
    media: UploadFile | None = File(None),
    ref_pose: UploadFile | None = File(None),
) -> dict:
    """Save uploads then enqueue avatar_lipsync into 任务中心."""
    from api.services import job_worker
    from workflow.job_queue import enqueue_job

    media_path, ref_pose_path = await _save_lipsync_uploads(
        session_path,
        media,
        ref_pose,
        media_asset_id=media_asset_id,
        ref_pose_asset_id=ref_pose_asset_id,
    )
    session = ensure_session_dir(session_path)
    backend_l = (backend or "").strip().lower()
    model_labels = {"heygem": "HeyGem", "sadtalker": "SadTalker", "latentsync": "LatentSync"}
    model_label = model_labels.get(backend_l, backend_l or "对口型")
    avatar_name = ""
    aid = (avatar_id or "").strip()
    if aid:
        entry = get_avatar(aid)
        if entry:
            avatar_name = entry.name
    title_bits = ["生成口播", model_label]
    if avatar_name:
        title_bits.append(avatar_name)
    elif (track_mode or "").lower() == "real":
        title_bits.append("实拍换嘴")
    payload = {
        "session_path": str(session.resolve()),
        "track_mode": track_mode or "digital",
        "backend": backend_l,
        "quality": quality or "balanced",
        "avatar_id": aid,
        "avatar_name": avatar_name,
        "model_label": model_label,
        "audio_path": (audio_path or "").strip(),
        "media_path": media_path or "",
        "ref_pose_path": ref_pose_path or "",
        "pose_style": float(pose_style or 0),
        "still_head": still_head.lower() in ("true", "1", "yes", "on"),
        "expression_scale": float(expression_scale or 1.0),
    }
    try:
        result = enqueue_job(
            session,
            "avatar_lipsync",
            payload,
            title=" · ".join(title_bits),
            force=force.lower() in ("true", "1", "yes", "on"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result.get("ok") and result.get("job"):
        job_worker.submit(
            str(session.resolve()),
            result["job"]["id"],
            priority=int(result["job"].get("priority") or 0),
        )
    return result


@router.post("/lipsync/cancel")
def lipsync_cancel() -> dict:
    """Terminate the running lipsync job (SadTalker / HeyGem / LatentSync)."""
    from workflow.task_control import request_cancel

    return request_cancel()


@router.post("/lipsync/stream")
async def lipsync_stream(
    session_path: str = Form(...),
    track_mode: str = Form("digital"),
    backend: str = Form(""),
    quality: str = Form("balanced"),
    avatar_id: str = Form(""),
    audio_path: str = Form(""),
    pose_style: float = Form(0),
    still_head: str = Form(""),
    expression_scale: float = Form(1.0),
    media_asset_id: str = Form(""),
    ref_pose_asset_id: str = Form(""),
    media: UploadFile | None = File(None),
    ref_pose: UploadFile | None = File(None),
):
    media_path, ref_pose_path = await _save_lipsync_uploads(
        session_path,
        media,
        ref_pose,
        media_asset_id=media_asset_id,
        ref_pose_asset_id=ref_pose_asset_id,
    )
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    async def event_stream():
        yield f"data: {json.dumps({'type': 'start'}, ensure_ascii=False)}\n\n"
        _lipsync_executor.submit(
            _run_lipsync_job,
            loop=loop,
            queue=queue,
            session_path=session_path,
            track_mode=track_mode,
            backend=backend,
            quality=quality,
            avatar_id=avatar_id or None,
            audio_path=audio_path or None,
            media_path=media_path,
            ref_pose_path=ref_pose_path,
            pose_style=pose_style,
            still_head=still_head.lower() in ("true", "1", "yes", "on"),
            expression_scale=expression_scale,
        )
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


@router.post("/lipsync", response_model=StageResult)
async def lipsync(
    session_path: str = Form(...),
    track_mode: str = Form("digital"),
    backend: str = Form(""),
    quality: str = Form("balanced"),
    avatar_id: str = Form(""),
    audio_path: str = Form(""),
    pose_style: float = Form(0),
    still_head: str = Form(""),
    expression_scale: float = Form(1.0),
    media_asset_id: str = Form(""),
    ref_pose_asset_id: str = Form(""),
    media: UploadFile | None = File(None),
    ref_pose: UploadFile | None = File(None),
) -> StageResult:
    media_path, ref_pose_path = await _save_lipsync_uploads(
        session_path,
        media,
        ref_pose,
        media_asset_id=media_asset_id,
        ref_pose_asset_id=ref_pose_asset_id,
    )
    data = run_lipsync(
        session_path,
        track_mode,
        backend,
        quality,
        avatar_id or None,
        audio_path or None,
        media_file=media_path,
        ref_pose_file=ref_pose_path,
        pose_style=pose_style,
        still_head=still_head.lower() in ("true", "1", "yes", "on"),
        expression_scale=expression_scale,
    )
    return StageResult(log=data.get("log", ""), data=data)

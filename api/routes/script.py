"""Script stage routes."""

from __future__ import annotations

import json
import threading
import queue

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import StreamingResponse

from api.schemas import (
    CompetitorAnalyzeBody,
    GenerateScriptBody,
    HotwordBody,
    LegalBody,
    RewriteBody,
    ScriptSaveBody,
    ShareUrlBody,
    StageResult,
)
from api.services.stages import (
    get_script_panel,
    save_script_text,
    script_cdn,
    script_competitor_analyze,
    script_extract,
    script_extract_with_progress,
    script_generate_from_profile,
    script_rewrite,
    script_suggest_hotwords,
    script_transcript,
    script_legal,
)
from workflow.session import ensure_session_dir

router = APIRouter(prefix="/api/script", tags=["script"])


@router.get("/panel")
def panel(session_path: str) -> dict:
    ensure_session_dir(session_path)
    return get_script_panel(session_path)


@router.post("/cdn", response_model=StageResult)
def cdn(body: ShareUrlBody) -> StageResult:
    data = script_cdn(body.session_path, body.share_url)
    return StageResult(log=data.get("log", ""), data=data)


@router.post("/transcript", response_model=StageResult)
async def transcript(
    session_path: str = Form(...),
    share_url: str = Form(""),
    media: UploadFile | None = File(None),
) -> StageResult:
    ref = None
    if media and media.filename:
        session = ensure_session_dir(session_path)
        ext = "." + media.filename.rsplit(".", 1)[-1] if "." in media.filename else ".mp4"
        dest = session / f"upload_ref{ext}"
        dest.write_bytes(await media.read())
        ref = str(dest)
    data = script_transcript(session_path, share_url, ref)
    return StageResult(log=data.get("log", ""), data=data)


@router.post("/extract", response_model=StageResult)
async def extract(
    session_path: str = Form(...),
    share_url: str = Form(""),
    media: UploadFile | None = File(None),
) -> StageResult:
    ref = None
    if media and media.filename:
        session = ensure_session_dir(session_path)
        ext = "." + media.filename.rsplit(".", 1)[-1] if "." in media.filename else ".mp4"
        dest = session / f"upload_ref{ext}"
        dest.write_bytes(await media.read())
        ref = str(dest)
    data = script_extract(session_path, share_url, ref)
    return StageResult(log=data.get("log", ""), data=data)


@router.post("/extract_stream")
async def extract_stream(
    session_path: str = Form(...),
    share_url: str = Form(""),
    media: UploadFile | None = File(None),
):
    """SSE streaming extract: emits progress events then a final result event."""
    ref = None
    if media and media.filename:
        session = ensure_session_dir(session_path)
        ext = "." + media.filename.rsplit(".", 1)[-1] if "." in media.filename else ".mp4"
        dest = session / f"upload_ref{ext}"
        dest.write_bytes(await media.read())
        ref = str(dest)

    ev_queue: queue.Queue = queue.Queue()
    done_flag = threading.Event()

    def on_progress(pct: float, desc: str | None) -> None:
        ev_queue.put({"type": "progress", "pct": pct, "desc": desc or ""})

    def worker() -> None:
        try:
            data = script_extract_with_progress(session_path, share_url, ref, on_progress)
            ev_queue.put({"type": "done", "data": data})
        except Exception as exc:
            ev_queue.put({"type": "error", "message": str(exc)})
        finally:
            done_flag.set()

    threading.Thread(target=worker, daemon=True).start()

    def event_stream():
        while not done_flag.is_set() or not ev_queue.empty():
            try:
                ev = ev_queue.get(timeout=0.5)
            except queue.Empty:
                yield f": keepalive\n\n"
                continue
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
            if ev.get("type") in ("done", "error"):
                break
        yield "data: {\"type\": \"end\"}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/rewrite", response_model=StageResult)
def rewrite(body: RewriteBody) -> StageResult:
    data = script_rewrite(body.session_path, body.script, body.intensity)
    return StageResult(log=data.get("log", ""), data=data)


@router.post("/hotwords", response_model=StageResult)
def hotwords(body: HotwordBody) -> StageResult:
    data = script_suggest_hotwords(
        body.identity,
        body.profession,
        industry=body.industry,
        product=body.product,
        audience=body.audience,
        roles=body.roles,
        mix_roles=body.mix_roles,
    )
    return StageResult(log=data.get("log", ""), data=data)


@router.post("/generate", response_model=StageResult)
def generate(body: GenerateScriptBody) -> StageResult:
    data = script_generate_from_profile(
        body.session_path,
        identity=body.identity,
        profession=body.profession,
        industry=body.industry,
        product=body.product,
        audience=body.audience,
        selling_points=body.selling_points,
        duration_sec=body.duration_sec,
        hotwords=body.hotwords,
        extra=body.extra,
        roles=body.roles,
        mix_roles=body.mix_roles,
        auto_hotwords=body.auto_hotwords,
        save_as=body.save_as,
        continue_from=body.continue_from,
    )
    return StageResult(log=data.get("log", ""), data=data, message="口播文稿已生成")


@router.post("/generate/stream")
def generate_stream(body: GenerateScriptBody):
    """SSE: stream LLM tokens; client abort = pause; pass continue_from to resume."""
    ev_queue: queue.Queue = queue.Queue()
    done_flag = threading.Event()
    stop_flag = threading.Event()

    def on_progress(pct: float, desc: str | None = None) -> None:
        ev_queue.put({"type": "progress", "pct": pct, "desc": desc or ""})

    def on_delta(text: str) -> None:
        ev_queue.put({"type": "delta", "text": text})

    def should_stop() -> bool:
        return stop_flag.is_set()

    def worker() -> None:
        try:
            data = script_generate_from_profile(
                body.session_path,
                identity=body.identity,
                profession=body.profession,
                industry=body.industry,
                product=body.product,
                audience=body.audience,
                selling_points=body.selling_points,
                duration_sec=body.duration_sec,
                hotwords=body.hotwords,
                extra=body.extra,
                roles=body.roles,
                mix_roles=body.mix_roles,
                auto_hotwords=body.auto_hotwords and not (body.continue_from or "").strip(),
                save_as=body.save_as,
                continue_from=body.continue_from,
                on_delta=on_delta,
                should_stop=should_stop,
                on_progress=on_progress,
            )
            # ProgressShim is inside stage — also push final via data
            kind = "paused" if data.get("paused") else "done"
            ev_queue.put({"type": kind, "data": data})
        except Exception as exc:
            ev_queue.put({"type": "error", "message": str(exc)})
        finally:
            done_flag.set()

    threading.Thread(target=worker, daemon=True).start()

    def event_stream():
        try:
            while not done_flag.is_set() or not ev_queue.empty():
                try:
                    ev = ev_queue.get(timeout=0.5)
                except queue.Empty:
                    yield ": keepalive\n\n"
                    continue
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                if ev.get("type") in ("done", "paused", "error"):
                    break
            yield 'data: {"type": "end"}\n\n'
        finally:
            stop_flag.set()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/competitor-analyze", response_model=StageResult)
def competitor_analyze(body: CompetitorAnalyzeBody) -> StageResult:
    data = script_competitor_analyze(
        body.session_path,
        body.profile_url,
        competitor_id=body.competitor_id,
        roles=body.roles,
        mix_roles=body.mix_roles,
        duration_sec=body.duration_sec,
        hotwords=body.hotwords,
        extra=body.extra,
        deep_transcript=body.deep_transcript,
        save_as=body.save_as,
    )
    return StageResult(log=data.get("log", ""), data=data, message="根据对标仿写完成")


@router.post("/legal", response_model=StageResult)
def legal(body: LegalBody) -> StageResult:
    data = script_legal(body.session_path, body.script, body.source)
    return StageResult(log=data.get("log", ""), data=data)


@router.put("/text", response_model=StageResult)
def save_text(body: ScriptSaveBody) -> StageResult:
    data = save_script_text(body.session_path, body.variant, body.text)
    return StageResult(message="已保存", data=data)

"""Cover template API — list / get / save / delete / render preview."""

from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel

from api.schemas import CoverRenderBody, CoverTemplateBody, StageResult
from cover.render import cover_canvas_size, make_placeholder, render_cover
from cover.templates import (
    delete_template,
    get_template,
    list_templates,
    normalize_template,
    save_template,
)
from script.llm_client import chat_completion, has_llm_key
from workflow.app_config import load_cfg
from workflow.session import ensure_session_dir

router = APIRouter(prefix="/api/cover", tags=["cover"])


class SuggestBody(BaseModel):
    script: str = ""
    session_path: str = ""
    save: bool = True


@router.get("/templates")
def templates() -> dict:
    return {"templates": list_templates()}


@router.get("/template")
def template_detail(tid: str) -> dict:
    tpl = get_template(tid)
    if not tpl:
        return {"template": None}
    return {"template": normalize_template(tpl)}


@router.post("/template")
def save(tpl: CoverTemplateBody) -> dict:
    data = json.loads(tpl.template_json) if isinstance(tpl.template_json, str) else tpl.template_json
    saved = save_template(normalize_template(data))
    return {"template": saved}


@router.delete("/template")
def delete(tid: str) -> dict:
    ok = delete_template(tid)
    return {"ok": ok}


@router.post("/asset")
async def upload_asset(
    session_path: str = Form(...),
    image: UploadFile = File(...),
) -> dict:
    """Upload a decoration image for cover layers; returns server path."""
    session = ensure_session_dir(session_path)
    assets_dir = session / "publish" / "cover_assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(image.filename or "").suffix.lower() or ".png"
    if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        suffix = ".png"
    dest = assets_dir / f"deco_{int(time.time() * 1000)}{suffix}"
    dest.write_bytes(await image.read())
    return {"ok": True, "path": str(dest.resolve())}


class CoverUrlBody(BaseModel):
    session_path: str
    url: str


@router.post("/asset_url")
def asset_from_url(body: CoverUrlBody) -> dict:
    """Download a network image/GIF into session cover_assets."""
    import hashlib
    import urllib.request

    url = (body.url or "").strip()
    if not url.startswith(("http://", "https://")):
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="请填写以 http(s):// 开头的图片链接")

    session = ensure_session_dir(body.session_path)
    assets_dir = session / "publish" / "cover_assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    lower = url.lower().split("?", 1)[0]
    suffix = ".jpg"
    for cand in (".gif", ".png", ".webp", ".jpeg", ".jpg"):
        if lower.endswith(cand):
            suffix = ".jpg" if cand == ".jpeg" else cand
            break

    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
    dest = assets_dir / f"url_{digest}{suffix}"
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; CoverBot/1.0)"},
        )
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = resp.read()
            ctype = (resp.headers.get("Content-Type") or "").lower()
    except Exception as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=f"下载失败：{exc}") from exc

    if not data or len(data) < 32:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="下载内容为空或过小")

    if "gif" in ctype:
        dest = dest.with_suffix(".gif")
    elif "png" in ctype:
        dest = dest.with_suffix(".png")
    elif "webp" in ctype:
        dest = dest.with_suffix(".webp")

    dest.write_bytes(data)
    return {"ok": True, "path": str(dest.resolve()), "url": url}


@router.post("/frame")
async def cover_frame(
    session_path: str = Form(...),
    time_sec: float = Form(0.5),
    video_path: str = Form(""),
) -> dict:
    """Extract one frame from lipsync / publish video for cover background."""
    from pipeline import ensure_ffmpeg
    from workflow.app_config import load_cfg
    from workflow.publish import extract_cover_frame, resolve_lipsync_video, resolve_session_video

    session = ensure_session_dir(session_path)
    session_root = session.resolve()
    publish_dir = session / "publish"
    publish_dir.mkdir(parents=True, exist_ok=True)

    video: Path | None = None
    raw = (video_path or "").strip()
    if raw:
        cand = Path(raw)
        try:
            resolved = cand.resolve()
            if resolved.is_file() and (
                resolved == session_root
                or session_root in resolved.parents
            ):
                video = resolved
        except OSError:
            video = None
    if video is None:
        video = resolve_lipsync_video(session) or resolve_session_video(session)
    if video is None or not video.is_file():
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="未找到成片视频，请先完成口播或发布成片")

    cfg = load_cfg()
    ffmpeg_bin = ensure_ffmpeg(cfg["paths"].get("ffmpeg", "ffmpeg"))
    out = publish_dir / f"cover_frame_{int(time.time() * 1000)}.jpg"
    extract_cover_frame(ffmpeg_bin, video, max(0.0, float(time_sec)), out)
    return {
        "ok": True,
        "frame_path": str(out.resolve()),
        "mtime": int(out.stat().st_mtime * 1000),
        "video_path": str(video.resolve()),
        "time_sec": max(0.0, float(time_sec)),
    }


@router.post("/render")
async def render(
    session_path: str = Form(...),
    template_json: str = Form("{}"),
    title: str = Form(""),
    subtitle: str = Form(""),
    base_path: str = Form(""),
    output_aspect: str = Form("portrait_9_16"),
    base: UploadFile | None = File(None),
) -> StageResult:
    """Render a cover preview from template + optional base image.

    If no base image is uploaded, uses the session's latest cover frame,
    or a gradient placeholder when nothing is available.
    Canvas follows output_aspect (9:16 default, 16:9 when landscape).
    """
    from workflow.publish import resolve_session_video
    from workflow.session import ensure_session_dir
    from workflow.app_config import load_cfg
    from pipeline import ensure_ffmpeg

    session = ensure_session_dir(session_path)
    publish_dir = session / "publish"
    publish_dir.mkdir(parents=True, exist_ok=True)
    canvas_w, canvas_h = cover_canvas_size(output_aspect)

    base_path_out: Path
    if base and base.filename:
        suffix = Path(base.filename).suffix or ".jpg"
        tmp = publish_dir / f"cover_base{suffix}"
        tmp.write_bytes(await base.read())
        base_path_out = tmp
    elif (base_path or "").strip():
        cand = Path(base_path.strip())
        try:
            resolved = cand.resolve()
            if resolved.is_file() and (
                resolved == session.resolve() or session.resolve() in resolved.parents
            ):
                base_path_out = resolved
            else:
                base_path_out = make_placeholder(aspect=output_aspect)
        except OSError:
            base_path_out = make_placeholder(aspect=output_aspect)
    else:
        # Try to extract a frame from the session video
        cfg = load_cfg()
        video = resolve_session_video(session)
        if video and video.exists():
            from workflow.publish import extract_cover_frame

            ffmpeg_bin = ensure_ffmpeg(cfg["paths"].get("ffmpeg", "ffmpeg"))
            frame = publish_dir / "cover_frame.jpg"
            extract_cover_frame(ffmpeg_bin, video, 0.5, frame)
            base_path_out = frame
        else:
            base_path_out = make_placeholder(aspect=output_aspect)

    tpl = json.loads(template_json) if template_json else {}
    if not tpl:
        tpl = {"id": "preview", "name": "预览", "layers": []}

    context = {"title": title or "3分钟学会AI口播", "subtitle": subtitle or "干货分享 · 一学就会"}
    out = publish_dir / "cover_preview.jpg"
    try:
        render_cover(base_path_out, out, tpl, context=context, aspect=output_aspect)
    except RuntimeError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=str(exc)) from exc
    subject_on = bool((tpl.get("subject") or {}).get("enabled"))
    hint = "（已抠像）" if subject_on else ""
    return StageResult(
        log=f"封面预览已生成{hint} → {out.name}（{canvas_w}×{canvas_h}）",
        data={
            "cover_path": str(out.resolve()),
            "base_path": str(base_path_out.resolve()),
            "subject_cutout": subject_on,
            "canvas_width": canvas_w,
            "canvas_height": canvas_h,
            "output_aspect": output_aspect,
        },
    )


@router.post("/prepare_subject")
async def prepare_subject(
    session_path: str = Form(...),
    subject_json: str = Form("{}"),
    base_path: str = Form(""),
    output_aspect: str = Form("portrait_9_16"),
) -> StageResult:
    """Prepare cutout bg + sticker for interactive editor preview (no text)."""
    from PIL import Image

    from cover.render import _fit_crop, cover_canvas_size
    from cover.subject import prepare_subject_preview_assets

    session = ensure_session_dir(session_path)
    publish_dir = session / "publish"
    publish_dir.mkdir(parents=True, exist_ok=True)
    canvas_w, canvas_h = cover_canvas_size(output_aspect)

    base_path_out: Path
    if (base_path or "").strip():
        cand = Path(base_path.strip())
        try:
            resolved = cand.resolve()
            if resolved.is_file() and (
                resolved == session.resolve() or session.resolve() in resolved.parents
            ):
                base_path_out = resolved
            else:
                base_path_out = make_placeholder(aspect=output_aspect)
        except OSError:
            base_path_out = make_placeholder(aspect=output_aspect)
    else:
        frame = publish_dir / "cover_frame.jpg"
        base_path_out = frame if frame.is_file() else make_placeholder(aspect=output_aspect)

    try:
        subject_cfg = json.loads(subject_json) if subject_json else {}
    except json.JSONDecodeError:
        subject_cfg = {}
    subject_cfg = dict(subject_cfg or {})
    subject_cfg["enabled"] = True

    base = Image.open(base_path_out).convert("RGBA")
    if base.size != (canvas_w, canvas_h):
        base = _fit_crop(base, canvas_w, canvas_h)

    try:
        assets = prepare_subject_preview_assets(base, subject_cfg, publish_dir)
    except RuntimeError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return StageResult(
        log="抠像样片已就绪，可拖拽调整位置",
        data=assets,
    )


@router.post("/suggest")
def suggest(body: SuggestBody) -> dict:
    """AI-generate title / subtitle / description / topics; optionally persist to session."""
    cfg = load_cfg()
    if not has_llm_key(cfg, "rewrite"):
        return {"ok": False, "message": "未配置 DeepSeek API Key，无法生成标题"}
    script = (body.script or "").strip()
    if not script:
        return {"ok": False, "message": "文案为空"}

    system = (
        "你是抖音/短视频爆款文案专家。根据口播文案生成发布用素材。\n"
        "要求：\n"
        "1. title：封面主标题，6-14 字，有冲击力、悬念或数字\n"
        "2. subtitle：封面副标题，4-12 字，补充钩子\n"
        "3. description：发布简介，80-180 字，口语化，可带 1-2 个 emoji，结尾引导互动\n"
        "4. topics：3-6 个话题标签（不要带 #）\n"
        '严格返回 JSON：{"title":"...","subtitle":"...","description":"...","topics":["..."]}，不要多余文字。'
    )
    user = f"口播文案：\n{script[:2000]}\n\n请生成标题、副标题、简介与话题标签。"
    try:
        raw = chat_completion(cfg, block="rewrite", system=system, user=user, temperature=0.75)
        import re

        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            data = json.loads(m.group(0))
        else:
            data = json.loads(raw)
        title = str(data.get("title", "")).strip()
        subtitle = str(data.get("subtitle", "")).strip()
        description = str(data.get("description", "")).strip()
        topics_raw = data.get("topics") or []
        if isinstance(topics_raw, str):
            topics = [t.strip().lstrip("#") for t in topics_raw.replace("，", ",").split(",") if t.strip()]
        elif isinstance(topics_raw, list):
            topics = [str(t).strip().lstrip("#") for t in topics_raw if str(t).strip()]
        else:
            topics = []
        topics = topics[:8]
        saved = False
        if body.save and (body.session_path or "").strip():
            from workflow.session import save_publish_copy

            save_publish_copy(
                body.session_path.strip(),
                title=title,
                subtitle=subtitle,
                description=description,
                topics=topics,
            )
            saved = True
        return {
            "ok": True,
            "title": title,
            "subtitle": subtitle,
            "description": description,
            "topics": topics,
            "saved": saved,
        }
    except Exception as exc:
        return {"ok": False, "message": str(exc)}

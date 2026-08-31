"""Publish stage routes."""

from __future__ import annotations

import asyncio
import json
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.schemas import PublishCuesBody, PublishBody, StageResult
from api.services.stages import (
    align_publish_from_audio,
    extract_publish_subtitles,
    preview_publish_cues,
    preview_publish_subtitle,
    run_publish_stage,
)
from workflow.bgm import list_bgm_library, resolve_bgm_path
from workflow.session import ensure_session_dir

router = APIRouter(prefix="/api/publish", tags=["publish"])
_publish_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="publish")


class PipAssetBody(BaseModel):
    session_path: str
    cue_index: int


class ResetMixBody(BaseModel):
    session_path: str
    delete_generated: bool = True


class DeletePipAssignmentBody(BaseModel):
    session_path: str
    cue_indices: list[int] = Field(default_factory=list)
    media_path: str = ""
    delete_media: bool = True


@router.post("/align")
def publish_align(body: PublishCuesBody) -> dict:
    return align_publish_from_audio(body.session_path, use_video_audio=False)


@router.post("/align_video")
def publish_align_video(body: PublishCuesBody) -> dict:
    return align_publish_from_audio(body.session_path, use_video_audio=True)


class ExtractSubtitlesBody(BaseModel):
    session_path: str
    use_video_audio: bool = True
    update_script: bool = True
    subtitle_font_size: int = 16
    output_aspect: str = "portrait_9_16"
    subtitle_max_chars: int | None = None


@router.post("/extract_subtitles")
def publish_extract_subtitles(body: ExtractSubtitlesBody) -> dict:
    """Force ASR on lipsync/dubbing audio; cues + optional script use recognized text."""
    return extract_publish_subtitles(
        body.session_path,
        use_video_audio=body.use_video_audio,
        update_script=body.update_script,
        subtitle_font_size=body.subtitle_font_size,
        output_aspect=body.output_aspect,
        subtitle_max_chars=body.subtitle_max_chars,
    )


@router.post("/cues")
def publish_cues(body: PublishCuesBody) -> dict:
    cfg_pub = {}
    try:
        from workflow.app_config import load_cfg

        cfg_pub = load_cfg().get("publish", {}) or {}
    except Exception:
        pass
    return preview_publish_cues(
        body.session_path,
        body.script,
        body.subtitle_pause,
        int(body.subtitle_max_chars or cfg_pub.get("subtitle_max_chars", 12)),
        subtitle_font_size=int(body.subtitle_font_size or 16),
        output_aspect=str(body.output_aspect or "portrait_9_16"),
    )


@router.post("/subtitle_preview")
async def publish_subtitle_preview(
    session_path: str = Form(...),
    text: str = Form("字幕预览"),
    time_sec: float = Form(0.5),
    subtitle_font_size: int = Form(16),
    subtitle_color: str = Form("#FFFFFF"),
    subtitle_outline: int = Form(1),
    subtitle_shadow: int = Form(0),
    subtitle_position: str = Form("bottom"),
    subtitle_style: str = Form("bottom_clean"),
    layout_mode: str = Form("education"),
    output_aspect: str = Form("portrait_9_16"),
    pip_position: str = Form("bottom_right"),
    pip_scale: float = Form(0.28),
    pip_margin: int = Form(24),
    pip_bg_media: str = Form(""),
    content_pip_position: str = Form("fullscreen"),
    content_pip_scale: float = Form(0.32),
    content_key_black: str = Form("false"),
    hyperframes_consent: bool = Form(False),
    hyperframes_theme: str = Form("tokyo_night"),
    hyperframes_layout: str = Form("kinetic"),
    hyperframes_aspect: str = Form("portrait_9_16"),
    education_bg: UploadFile | None = File(None),
    hide_subtitles: str = Form("false"),
    hide_lecturer: str = Form("false"),
    lecturer_crop_json: str = Form(""),
    remotion_theme: str = Form("off"),
    smart_keywords: str = Form("true"),
    cue_start: float | None = Form(None),
    cue_end: float | None = Form(None),
) -> dict:
    education_bg_path = None
    if education_bg and education_bg.filename:
        session = ensure_session_dir(session_path)
        preview_dir = session / "publish" / "preview"
        preview_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(education_bg.filename).suffix.lower() or ".jpg"
        dest = preview_dir / f"_education_bg_upload{suffix}"
        dest.write_bytes(await education_bg.read())
        education_bg_path = str(dest)
    lec_crop = None
    if (lecturer_crop_json or "").strip():
        try:
            lec_crop = json.loads(lecturer_crop_json)
            if not isinstance(lec_crop, dict):
                lec_crop = None
        except json.JSONDecodeError:
            lec_crop = None
    return preview_publish_subtitle(
        session_path,
        text,
        time_sec,
        subtitle_font_size=subtitle_font_size,
        subtitle_color=subtitle_color,
        subtitle_outline=subtitle_outline,
        subtitle_shadow=subtitle_shadow,
        subtitle_position=subtitle_position,
        subtitle_style=subtitle_style,
        layout_mode=layout_mode,
        output_aspect=output_aspect,
        pip_position=pip_position,
        pip_scale=pip_scale,
        pip_margin=pip_margin,
        pip_bg_media=pip_bg_media.strip() or None,
        content_pip_position=content_pip_position,
        content_pip_scale=content_pip_scale,
        content_key_black=content_key_black.lower() in ("true", "1", "yes", "on"),
        education_bg_path=education_bg_path,
        hyperframes_consent=hyperframes_consent,
        hyperframes_theme=hyperframes_theme,
        hyperframes_layout=hyperframes_layout,
        hyperframes_aspect=hyperframes_aspect,
        hide_subtitles=hide_subtitles.lower() in ("true", "1", "yes", "on"),
        hide_lecturer=hide_lecturer.lower() in ("true", "1", "yes", "on"),
        lecturer_crop=lec_crop,
        remotion_theme=remotion_theme or "off",
        smart_keywords=smart_keywords,
        cue_start=cue_start,
        cue_end=cue_end,
    )


@router.post("/glass_cards/suggest")
async def glass_cards_suggest(
    session_path: str = Form(...),
    cues_json: str = Form("[]"),
    cue_indices_json: str = Form("[]"),
    use_llm: str = Form("true"),
) -> dict:
    """AI / heuristic glass-card drafts for selected subtitle cues (short mix)."""
    from workflow.app_config import load_cfg
    from workflow.glass_cards import heuristic_card_from_text, llm_card_from_text

    try:
        cues = json.loads(cues_json or "[]")
    except json.JSONDecodeError:
        cues = []
    try:
        indices = {int(i) for i in json.loads(cue_indices_json or "[]") if int(i) > 0}
    except (json.JSONDecodeError, TypeError, ValueError):
        indices = set()
    if not isinstance(cues, list) or not cues:
        raise HTTPException(status_code=400, detail="请先准备字幕时间轴")
    if not indices:
        raise HTTPException(status_code=400, detail="请先勾选要做字卡的字幕句")

    selected = [
        c
        for c in cues
        if isinstance(c, dict) and int(c.get("index") or 0) in indices and str(c.get("text") or "").strip()
    ]
    if not selected:
        raise HTTPException(status_code=400, detail="所选字幕没有可用文案")

    # Contiguous islands → one card per island
    selected.sort(key=lambda c: float(c.get("start") or 0))
    groups: list[list[dict]] = []
    for c in selected:
        if not groups:
            groups.append([c])
            continue
        prev = groups[-1][-1]
        gap = float(c.get("start") or 0) - float(prev.get("end") or 0)
        if gap <= 0.45:
            groups[-1].append(c)
        else:
            groups.append([c])

    cfg = load_cfg()
    want_llm = use_llm.lower() in ("true", "1", "yes", "on")
    cards = []
    for gi, group in enumerate(groups):
        text = "，".join(str(x.get("text") or "").strip() for x in group if str(x.get("text") or "").strip())
        payload = llm_card_from_text(cfg, text) if want_llm else heuristic_card_from_text(text)
        cards.append(
            {
                "id": f"glass_{gi}_{int(group[0].get('index') or 0)}",
                "cue_indices": [int(x.get("index") or 0) for x in group],
                "start": float(group[0].get("start") or 0),
                "end": float(group[-1].get("end") or 0),
                "title": payload.get("title") or "要点",
                "bullets": payload.get("bullets") or [],
                "source_text": text[:200],
            }
        )
    _ = session_path  # reserved for future session cache
    return {"ok": True, "cards": cards, "count": len(cards)}


@router.post("/remotion_preview")
async def publish_remotion_preview(
    session_path: str = Form(...),
    text: str = Form("字幕预览"),
    remotion_theme: str = Form("bar"),
    accent: str = Form("#FFFFFF"),
) -> dict:
    """One-frame Remotion caption template preview (PNG under session publish/preview)."""
    from fastapi import HTTPException
    from workflow.remotion_captions import is_available, render_timed_caption_still

    theme = (remotion_theme or "bar").strip().lower()
    if theme in ("off", "none", "ass", "classic", ""):
        raise HTTPException(status_code=400, detail="请选择 Remotion 字幕模板")
    if not is_available():
        raise HTTPException(status_code=400, detail="Remotion 不可用（需 Node + tools/remotion-captions）")
    session = ensure_session_dir(session_path)
    preview_dir = session / "publish" / "preview"
    preview_dir.mkdir(parents=True, exist_ok=True)
    out = preview_dir / f"remotion_still_{theme}.png"
    try:
        render_timed_caption_still(
            text,
            out,
            accent=accent or "#FFFFFF",
            theme=theme,
            width=720,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Remotion 预览失败: {exc}") from exc
    return {
        "ok": True,
        "theme": theme,
        "preview_path": str(out.resolve()),
        "preview_url": f"/api/files/session?path={out.resolve()}".replace("\\", "/"),
    }


@router.post("/lecturer_crop_auto")
async def lecturer_crop_auto(
    session_path: str = Form(...),
    time_sec: float = Form(0.8),
) -> dict:
    from api.services.stages import auto_detect_lecturer_crop

    return auto_detect_lecturer_crop(session_path, time_sec=time_sec)


@router.post("/lecturer_crop_frame")
async def lecturer_crop_frame(
    session_path: str = Form(...),
    time_sec: float = Form(0.8),
) -> dict:
    from api.services.stages import extract_lecturer_crop_frame

    return extract_lecturer_crop_frame(session_path, time_sec=time_sec)


@router.get("/bgm")
def bgm_library() -> list[dict]:
    return list_bgm_library()


@router.get("/bgm/preview")
def bgm_preview(id: str = Query(..., alias="id")):
    from fastapi import HTTPException
    from workflow.file_serve import safe_file_response

    path = resolve_bgm_path(id)
    if not path:
        raise HTTPException(status_code=404, detail="BGM 未下载，请运行 scripts/download_bgm.py 或重新上传")
    return safe_file_response(path, media_type="audio/mpeg")


@router.post("/bgm/upload")
async def bgm_upload(
    name: str = Form(""),
    file: UploadFile = File(...),
) -> dict:
    """User-uploaded BGM → data/bgm/user/；发布页与素材中心共用。"""
    from fastapi import HTTPException
    from workflow.bgm import upload_user_bgm

    suffix = Path(file.filename or "track.mp3").suffix.lower() or ".mp3"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = Path(tmp.name)
    try:
        return upload_user_bgm(
            tmp_path,
            name=name or Path(file.filename or "").stem,
            mime=file.content_type or "",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        tmp_path.unlink(missing_ok=True)


@router.delete("/bgm/{bgm_id}")
def bgm_delete(bgm_id: str) -> dict:
    from fastapi import HTTPException
    from workflow.bgm import delete_user_bgm

    try:
        delete_user_bgm(bgm_id)
        return {"ok": True}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/pip_asset")
async def pip_asset(
    session_path: str = Form(...),
    cue_index: int = Form(...),
    media: UploadFile = File(...),
) -> dict:
    session = ensure_session_dir(session_path)
    assets = session / "publish" / "pip_cues"
    assets.mkdir(parents=True, exist_ok=True)
    name = media.filename or ""
    suffix = Path(name).suffix.lower()
    ctype = (media.content_type or "").lower()
    video_exts = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}
    image_exts = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
    if suffix not in video_exts | image_exts:
        if ctype.startswith("video/"):
            suffix = ".mp4"
        elif ctype.startswith("image/"):
            suffix = ".png"
        else:
            suffix = ".png"
    media_type = "video" if suffix in video_exts or ctype.startswith("video/") else "image"
    if media_type == "video" and suffix not in video_exts:
        suffix = ".mp4"
    dest = assets / f"cue_{cue_index}_{int(time.time() * 1000)}{suffix}"
    dest.write_bytes(await media.read())
    return {
        "ok": True,
        "cue_index": cue_index,
        "media_path": str(dest.resolve()),
        "media_type": media_type,
    }


@router.post("/pip_frame")
async def pip_frame(
    session_path: str = Form(...),
    media_path: str = Form(...),
    time_sec: float = Form(0),
) -> dict:
    """Extract one frame from PiP image/video for crop UI."""
    import subprocess

    from fastapi import HTTPException
    from pipeline import IMAGE_EXTENSIONS, ensure_ffmpeg, ffprobe_bin
    from workflow.app_config import load_cfg

    session = ensure_session_dir(session_path)
    src = Path(media_path)
    if not src.is_file():
        raise HTTPException(status_code=404, detail="素材不存在")
    preview_dir = session / "publish" / "preview"
    preview_dir.mkdir(parents=True, exist_ok=True)
    out = preview_dir / f"pip_frame_{src.stem}_{int(time.time() * 1000)}.jpg"
    cfg = load_cfg()
    ffmpeg_bin = ensure_ffmpeg((cfg.get("paths") or {}).get("ffmpeg", "ffmpeg"))
    ext = src.suffix.lower()
    try:
        if ext in IMAGE_EXTENSIONS:
            subprocess.run(
                [ffmpeg_bin, "-y", "-i", str(src), "-frames:v", "1", str(out)],
                check=True,
                capture_output=True,
            )
        else:
            ss = max(0.0, float(time_sec or 0))
            subprocess.run(
                [
                    ffmpeg_bin,
                    "-y",
                    "-ss",
                    f"{ss:.3f}",
                    "-i",
                    str(src),
                    "-frames:v",
                    "1",
                    str(out),
                ],
                check=True,
                capture_output=True,
            )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"抽帧失败: {exc}") from exc
    if not out.is_file():
        raise HTTPException(status_code=400, detail="抽帧失败：无输出")
    dur = None
    try:
        if ext not in IMAGE_EXTENSIONS:
            from workflow.pip_overlay import _media_duration

            probe = ffprobe_bin(ffmpeg_bin)
            dur = _media_duration(probe, src)
    except Exception:
        dur = None
    return {
        "ok": True,
        "frame_path": str(out.resolve()),
        "duration_sec": dur,
        "time_sec": float(time_sec or 0),
    }


@router.post("/pip_asset_from_library")
async def pip_asset_from_library(
    session_path: str = Form(...),
    cue_index: int = Form(...),
    asset_id: str = Form(...),
) -> dict:
    from fastapi import HTTPException
    from workflow.asset_library import get_item, stage_asset_for_pip

    session = ensure_session_dir(session_path)
    assets_dir = session / "publish" / "pip_cues"
    try:
        dest = stage_asset_for_pip(assets_dir, asset_id, cue_index)
        item = get_item(asset_id)
        ext = dest.suffix.lower()
        media_type = "video" if ext in {".mp4", ".mov", ".webm", ".mkv"} else "image"
        return {
            "ok": True,
            "cue_index": cue_index,
            "media_path": str(dest),
            "media_type": media_type,
            "asset_id": asset_id,
            "name": item.get("name") or "",
        }
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/hyperframe_suggest")
async def hyperframe_suggest(
    text: str = Form(""),
    aspect: str = Form("portrait_9_16"),
) -> dict:
    from workflow.hyperframes import suggest_hyperframe_style
    from workflow.remotion_captions import suggest_remotion_caption_theme

    sug = suggest_hyperframe_style(text or "", aspect=aspect)
    rem = suggest_remotion_caption_theme(text or "")
    return {"ok": True, **sug, "remotion_theme": rem["theme"], "remotion_reasons": rem.get("reasons") or []}


@router.post("/hyperframe_fill_cues")
async def hyperframe_fill_cues(
    session_path: str = Form(...),
    theme: str = Form("tokyo_night"),
    layout: str = Form("kinetic"),
    aspect: str = Form("portrait_9_16"),
    cues_json: str = Form("[]"),
    skip_indices_json: str = Form("[]"),
    target_indices_json: str = Form("[]"),
    smart_merge: str = Form("true"),
    force_contiguous: str = Form("auto"),
    smart_style: str = Form("true"),
    remotion_captions: str = Form("true"),
    font_id: str = Form("noto_sc"),
    font_scale: str = Form("1"),
    bg_mode: str = Form("generative"),
    bg_asset: str = Form(""),
    bg_prompt: str = Form(""),
    remotion_theme: str = Form("bar"),
    style_pack_json: str = Form(""),
    save_to_library: str = Form("true"),
) -> dict:
    from fastapi import HTTPException
    from pipeline import ensure_ffmpeg
    from workflow.app_config import load_cfg
    from workflow.hyperframes import generate_cue_scene_assets
    from workflow.publish import SubCue
    from workflow.scene_style_pack import normalize_style_pack

    session = ensure_session_dir(session_path)
    cfg = load_cfg()
    try:
        ffmpeg_bin = ensure_ffmpeg((cfg.get("paths") or {}).get("ffmpeg", "ffmpeg"))
        raw_cues = json.loads(cues_json or "[]")
        skip_raw = json.loads(skip_indices_json or "[]")
        target_raw = json.loads(target_indices_json or "[]")
        pack_raw = json.loads(style_pack_json) if (style_pack_json or "").strip() else {}
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="字幕 JSON 无效") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"准备失败: {exc}") from exc

    if not isinstance(raw_cues, list) or not raw_cues:
        raise HTTPException(status_code=400, detail="请先加载字幕时间轴")

    skip = {int(i) for i in skip_raw if int(i) > 0} if isinstance(skip_raw, list) else set()
    target = (
        {int(i) for i in target_raw if int(i) > 0}
        if isinstance(target_raw, list) and target_raw
        else None
    )
    cues = [
        SubCue(
            int(c.get("index") or i + 1),
            float(c["start"]),
            float(c["end"]),
            str(c.get("text") or "").strip(),
        )
        for i, c in enumerate(raw_cues)
        if c.get("text")
    ]
    work = session / "publish" / "pip_cues" / "hf_auto"
    fc = (force_contiguous or "auto").lower()
    if fc in ("true", "1", "yes", "on"):
        do_force = True
    elif fc in ("false", "0", "no", "off"):
        do_force = False
    else:
        do_force = target is not None
    do_smart = smart_merge.lower() in ("true", "1", "yes", "on")
    do_smart_style = smart_style.lower() in ("true", "1", "yes", "on")
    do_remotion = remotion_captions.lower() in ("true", "1", "yes", "on")
    pack = normalize_style_pack(
        {
            "theme": theme,
            "layout": layout,
            "aspect": aspect,
            "font_id": font_id,
            "font_scale": font_scale,
            "bg_mode": bg_mode,
            "bg_asset": bg_asset,
            "bg_prompt": bg_prompt,
            "remotion_theme": remotion_theme if do_remotion else "off",
            **(pack_raw if isinstance(pack_raw, dict) else {}),
        }
    )
    try:
        assignments = generate_cue_scene_assets(
            cues,
            work,
            theme=pack["theme"],
            layout=pack["layout"],
            aspect=pack["aspect"],
            skip_indices=skip,
            target_indices=target,
            smart_merge=do_smart,
            force_contiguous=do_force,
            smart_style=do_smart_style,
            remotion_captions=do_remotion,
            style_pack=pack,
            ffmpeg_bin=ffmpeg_bin,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"HyperFrames 场景生成失败: {exc}") from exc
    if not assignments:
        raise HTTPException(status_code=400, detail="未能生成任何场景，请检查所选字幕或文案")

    from workflow.pip_assignments_store import mirror_assignments_to_library, merge_pip_assignments

    store_path = merge_pip_assignments(session, assignments)
    library_items: list = []
    if save_to_library.lower() in ("true", "1", "yes", "on"):
        library_items = mirror_assignments_to_library(assignments, prefix="智能场景")
    return {
        "ok": True,
        "assignments": assignments,
        "count": len(assignments),
        "layout": pack["layout"],
        "aspect": pack["aspect"],
        "merged": do_smart or do_force,
        "force_contiguous": do_force,
        "smart_style": do_smart_style,
        "remotion_captions": do_remotion,
        "style_pack": pack,
        "work_dir": str(work.resolve()),
        "assignments_file": str(store_path.resolve()),
        "library_saved": len(library_items),
        "note": "场景文件保留在会话 publish/pip_cues，不会自动删除；已同步到素材中心（视频分组）。",
    }


@router.post("/hyperframe_restyle")
async def hyperframe_restyle(
    session_path: str = Form(...),
    cues_json: str = Form("[]"),
    assignments_json: str = Form("[]"),
    theme: str = Form("tokyo_night"),
    layout: str = Form("kinetic"),
    aspect: str = Form("portrait_9_16"),
    font_id: str = Form("noto_sc"),
    font_scale: str = Form("1"),
    bg_mode: str = Form("generative"),
    bg_asset: str = Form(""),
    bg_prompt: str = Form(""),
    remotion_theme: str = Form("bar"),
    remotion_captions: str = Form("true"),
    smart_style: str = Form("false"),
    save_to_library: str = Form("true"),
) -> dict:
    """Re-render existing auto scenes with Style Pack; keep cue timing / selection."""
    from fastapi import HTTPException
    from pipeline import ensure_ffmpeg
    from workflow.app_config import load_cfg
    from workflow.hyperframes import restyle_cue_scene_assets
    from workflow.publish import SubCue
    from workflow.scene_style_pack import normalize_style_pack

    session = ensure_session_dir(session_path)
    cfg = load_cfg()
    try:
        ffmpeg_bin = ensure_ffmpeg((cfg.get("paths") or {}).get("ffmpeg", "ffmpeg"))
        raw_cues = json.loads(cues_json or "[]")
        raw_assignments = json.loads(assignments_json or "[]")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="JSON 无效") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"准备失败: {exc}") from exc

    if not isinstance(raw_cues, list) or not raw_cues:
        raise HTTPException(status_code=400, detail="请先加载字幕时间轴")
    if not isinstance(raw_assignments, list) or not raw_assignments:
        raise HTTPException(status_code=400, detail="没有可换肤的场景，请先智能生成")

    cues = [
        SubCue(
            int(c.get("index") or i + 1),
            float(c["start"]),
            float(c["end"]),
            str(c.get("text") or "").strip(),
        )
        for i, c in enumerate(raw_cues)
        if c.get("text")
    ]
    pack = normalize_style_pack(
        {
            "theme": theme,
            "layout": layout,
            "aspect": aspect,
            "font_id": font_id,
            "font_scale": font_scale,
            "bg_mode": bg_mode,
            "bg_asset": bg_asset,
            "bg_prompt": bg_prompt,
            "remotion_theme": remotion_theme,
        }
    )
    do_remotion = remotion_captions.lower() in ("true", "1", "yes", "on")
    work = session / "publish" / "pip_cues" / "hf_restyle"
    try:
        assignments = restyle_cue_scene_assets(
            cues,
            raw_assignments,
            work,
            style_pack=pack,
            theme=pack["theme"],
            layout=pack["layout"],
            aspect=pack["aspect"],
            remotion_captions=do_remotion,
            smart_style=smart_style.lower() in ("true", "1", "yes", "on"),
            ffmpeg_bin=ffmpeg_bin,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"换肤重渲失败: {exc}") from exc
    if not assignments:
        raise HTTPException(status_code=400, detail="未能换肤任何场景")

    from workflow.pip_assignments_store import mirror_assignments_to_library, merge_pip_assignments

    store_path = merge_pip_assignments(session, assignments)
    library_items: list = []
    if save_to_library.lower() in ("true", "1", "yes", "on"):
        library_items = mirror_assignments_to_library(assignments, prefix="换肤场景")
    return {
        "ok": True,
        "assignments": assignments,
        "count": len(assignments),
        "style_pack": pack,
        "work_dir": str(work.resolve()),
        "assignments_file": str(store_path.resolve()),
        "library_saved": len(library_items),
        "note": "换肤结果已写入会话目录，并同步到素材中心；旧文件不会自动删除。",
    }


@router.get("/pip_assignments")
def get_pip_assignments(session_path: str) -> dict:
    """Load last smart-gen / restyle assignments for this session (files kept on disk)."""
    from workflow.pip_assignments_store import load_pip_assignments

    session = ensure_session_dir(session_path)
    data = load_pip_assignments(session)
    return {"ok": True, **data}


@router.post("/reset_mix")
def reset_publish_mix(body: ResetMixBody) -> dict:
    """Clear PiP timeline / HyperFrames scenes so user can remix from scratch."""
    from workflow.pip_assignments_store import clear_pip_mix

    session = ensure_session_dir(body.session_path)
    data = clear_pip_mix(session, delete_generated=bool(body.delete_generated))
    return {
        "ok": True,
        "message": "混剪工作区已重置，可重新配置画中画与一键成片",
        **data,
    }


@router.post("/pip_assignments/delete")
def delete_pip_assignment(body: DeletePipAssignmentBody) -> dict:
    """Remove one PiP / smart-scene assignment; optionally delete its media file."""
    from workflow.pip_assignments_store import remove_pip_assignments

    if not body.cue_indices and not (body.media_path or "").strip():
        raise HTTPException(status_code=400, detail="请指定 cue_indices 或 media_path")
    session = ensure_session_dir(body.session_path)
    data = remove_pip_assignments(
        session,
        cue_indices=body.cue_indices or None,
        media_path=(body.media_path or "").strip() or None,
        delete_media=bool(body.delete_media),
    )
    msg = f"已删除 {data.get('removed', 0)} 个画中画"
    if data.get("deleted_files"):
        msg += f"（移除 {data['deleted_files']} 个生成文件）"
    return {"ok": True, "message": msg, **data}


@router.post("/run", response_model=StageResult)
async def publish(
    session_path: str = Form(...),
    script: str = Form(""),
    title: str = Form(""),
    cover_time: float = Form(0.5),
    template: str = Form("classic_bottom"),
    subtitle_style: str = Form("bottom_clean"),
    subtitle_pause: float = Form(0.35),
    subtitle_font_size: int = Form(16),
    subtitle_color: str = Form("#FFFFFF"),
    subtitle_outline: int = Form(1),
    subtitle_shadow: int = Form(0),
    subtitle_position: str = Form("bottom"),
    burn_subtitles: bool = Form(True),
    remotion_theme: str = Form("off"),
    layout_mode: str = Form("short"),
    hf_text_cards: bool = Form(False),
    glass_cards_json: str = Form("[]"),
    hf_card_position: str = Form("auto"),
    hf_card_scale: float = Form(0.42),
    embed_cover: bool = Form(True),
    cover_image_path: str = Form(""),
    pip_mode: str = Form("none"),
    pip_position: str = Form("bottom_right"),
    pip_scale: float = Form(0.28),
    pip_margin: int = Form(24),
    hyperframes_consent: bool = Form(False),
    hyperframes_theme: str = Form("tokyo_night"),
    hyperframes_layout: str = Form("kinetic"),
    hyperframes_aspect: str = Form("portrait_9_16"),
    pip_cues_json: str = Form("[]"),
    cues_json: str = Form(""),
    hyperframes_target_indices_json: str = Form(""),
    lecturer_crop_json: str = Form(""),
    enable_bgm: str = Form("true"),
    bgm_id: str = Form("hook_drop"),
    bgm_volume: float = Form(0.22),
    bgm_start: float = Form(0),
    pip_upload: UploadFile | None = File(None),
) -> StageResult:
    pip_path = None
    if pip_upload and pip_upload.filename:
        import tempfile

        suffix = Path(pip_upload.filename).suffix or ".mp4"
        tmp = Path(tempfile.gettempdir()) / f"pip_{pip_upload.filename}"
        tmp.write_bytes(await pip_upload.read())
        pip_path = str(tmp)
    data = run_publish_stage(
        session_path,
        script,
        title,
        cover_time,
        template,
        subtitle_style,
        subtitle_pause,
        burn_subtitles,
        embed_cover,
        pip_mode,
        pip_path,
        pip_position,
        pip_scale,
        pip_margin,
        hyperframes_consent,
        hyperframes_theme,
        hyperframes_layout,
        hyperframes_aspect,
        subtitle_font_size=subtitle_font_size,
        subtitle_color=subtitle_color,
        subtitle_outline=subtitle_outline,
        subtitle_shadow=subtitle_shadow,
        subtitle_position=subtitle_position,
        pip_cues_json=pip_cues_json,
        cues_json=cues_json,
        bgm_id=bgm_id,
        bgm_volume=bgm_volume,
        bgm_start=bgm_start,
        enable_bgm=enable_bgm.lower() in ("true", "1", "yes", "on"),
        hyperframes_target_indices_json=hyperframes_target_indices_json,
        lecturer_crop_json=lecturer_crop_json,
        remotion_theme=remotion_theme,
        layout_mode=layout_mode,
        hf_text_cards=hf_text_cards,
        cover_image_path=cover_image_path,
        glass_cards_json=glass_cards_json,
        hf_card_position=hf_card_position,
        hf_card_scale=hf_card_scale,
    )
    return StageResult(log=data.get("log", ""), data=data)


async def _save_pip_upload(pip_upload: UploadFile | None, session_path: str) -> str | None:
    if not pip_upload or not pip_upload.filename:
        return None
    import tempfile

    suffix = Path(pip_upload.filename).suffix or ".mp4"
    tmp = Path(tempfile.gettempdir()) / f"pip_{pip_upload.filename}"
    tmp.write_bytes(await pip_upload.read())
    return str(tmp)


def _run_publish_job(
    *,
    loop: asyncio.AbstractEventLoop,
    queue: asyncio.Queue,
    session_path: str,
    script: str,
    title: str,
    cover_time: float,
    template: str,
    subtitle_style: str,
    subtitle_pause: float,
    burn_subtitles: bool,
    embed_cover: bool,
    pip_mode: str,
    pip_path: str | None,
    pip_position: str,
    pip_scale: float,
    pip_margin: int,
    hyperframes_consent: bool,
    hyperframes_theme: str,
    hyperframes_layout: str,
    hyperframes_aspect: str,
    subtitle_font_size: int,
    subtitle_color: str,
    subtitle_outline: int,
    subtitle_shadow: int,
    subtitle_position: str,
    pip_cues_json: str,
    cues_json: str,
    bgm_id: str,
    bgm_volume: float,
    bgm_start: float,
    enable_bgm: bool,
    hyperframes_target_indices_json: str = "",
    lecturer_crop_json: str = "",
    remotion_theme: str = "off",
    layout_mode: str = "short",
    hf_text_cards: bool = False,
    cover_image_path: str = "",
    glass_cards_json: str = "[]",
    hf_card_position: str = "auto",
    hf_card_scale: float = 0.42,
) -> None:
    def on_progress(p: float, msg: str | None = None) -> None:
        loop.call_soon_threadsafe(
            queue.put_nowait,
            {"type": "progress", "p": p, "msg": msg or ""},
        )

    try:
        data = run_publish_stage(
            session_path,
            script,
            title,
            cover_time,
            template,
            subtitle_style,
            subtitle_pause,
            burn_subtitles,
            embed_cover,
            pip_mode,
            pip_path,
            pip_position,
            pip_scale,
            pip_margin,
            hyperframes_consent,
            hyperframes_theme,
            hyperframes_layout,
            hyperframes_aspect,
            subtitle_font_size=subtitle_font_size,
            subtitle_color=subtitle_color,
            subtitle_outline=subtitle_outline,
            subtitle_shadow=subtitle_shadow,
            subtitle_position=subtitle_position,
            pip_cues_json=pip_cues_json,
            cues_json=cues_json,
            bgm_id=bgm_id,
            bgm_volume=bgm_volume,
            bgm_start=bgm_start,
            enable_bgm=enable_bgm,
            hyperframes_target_indices_json=hyperframes_target_indices_json,
            lecturer_crop_json=lecturer_crop_json,
            on_progress=on_progress,
            remotion_theme=remotion_theme,
            layout_mode=layout_mode,
            hf_text_cards=hf_text_cards,
            cover_image_path=cover_image_path,
            glass_cards_json=glass_cards_json,
            hf_card_position=hf_card_position,
            hf_card_scale=hf_card_scale,
        )
        loop.call_soon_threadsafe(queue.put_nowait, {"type": "done", "data": data})
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "msg": detail})
    except Exception as exc:
        from workflow.task_control import TaskCancelled

        msg = "任务已取消" if isinstance(exc, TaskCancelled) or "已取消" in str(exc) else str(exc)
        loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "msg": msg})


@router.post("/run/cancel")
def publish_cancel() -> dict:
    from workflow.task_control import request_cancel

    return request_cancel()


@router.post("/run/stream")
async def publish_stream(
    session_path: str = Form(...),
    script: str = Form(""),
    title: str = Form(""),
    cover_time: float = Form(0.5),
    template: str = Form("classic_bottom"),
    subtitle_style: str = Form("bottom_clean"),
    subtitle_pause: float = Form(0.35),
    subtitle_font_size: int = Form(16),
    subtitle_color: str = Form("#FFFFFF"),
    subtitle_outline: int = Form(1),
    subtitle_shadow: int = Form(0),
    subtitle_position: str = Form("bottom"),
    burn_subtitles: bool = Form(True),
    remotion_theme: str = Form("off"),
    layout_mode: str = Form("short"),
    hf_text_cards: bool = Form(False),
    glass_cards_json: str = Form("[]"),
    hf_card_position: str = Form("auto"),
    hf_card_scale: float = Form(0.42),
    embed_cover: bool = Form(True),
    cover_image_path: str = Form(""),
    pip_mode: str = Form("none"),
    pip_position: str = Form("bottom_right"),
    pip_scale: float = Form(0.28),
    pip_margin: int = Form(24),
    hyperframes_consent: bool = Form(False),
    hyperframes_theme: str = Form("tokyo_night"),
    hyperframes_layout: str = Form("kinetic"),
    hyperframes_aspect: str = Form("portrait_9_16"),
    pip_cues_json: str = Form("[]"),
    cues_json: str = Form(""),
    hyperframes_target_indices_json: str = Form(""),
    lecturer_crop_json: str = Form(""),
    enable_bgm: str = Form("true"),
    bgm_id: str = Form("hook_drop"),
    bgm_volume: float = Form(0.22),
    bgm_start: float = Form(0),
    pip_upload: UploadFile | None = File(None),
):
    pip_path = await _save_pip_upload(pip_upload, session_path)
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    async def event_stream():
        yield f"data: {json.dumps({'type': 'start'}, ensure_ascii=False)}\n\n"
        _publish_executor.submit(
            _run_publish_job,
            loop=loop,
            queue=queue,
            session_path=session_path,
            script=script,
            title=title,
            cover_time=cover_time,
            template=template,
            subtitle_style=subtitle_style,
            subtitle_pause=subtitle_pause,
            burn_subtitles=burn_subtitles,
            embed_cover=embed_cover,
            pip_mode=pip_mode,
            pip_path=pip_path,
            pip_position=pip_position,
            pip_scale=pip_scale,
            pip_margin=pip_margin,
            hyperframes_consent=hyperframes_consent,
            hyperframes_theme=hyperframes_theme,
            hyperframes_layout=hyperframes_layout,
            hyperframes_aspect=hyperframes_aspect,
            subtitle_font_size=subtitle_font_size,
            subtitle_color=subtitle_color,
            subtitle_outline=subtitle_outline,
            subtitle_shadow=subtitle_shadow,
            subtitle_position=subtitle_position,
            pip_cues_json=pip_cues_json,
            cues_json=cues_json,
            bgm_id=bgm_id,
            bgm_volume=bgm_volume,
            bgm_start=bgm_start,
            enable_bgm=enable_bgm.lower() in ("true", "1", "yes", "on"),
            hyperframes_target_indices_json=hyperframes_target_indices_json,
            lecturer_crop_json=lecturer_crop_json,
            remotion_theme=remotion_theme,
            layout_mode=layout_mode,
            hf_text_cards=hf_text_cards,
            cover_image_path=cover_image_path,
            glass_cards_json=glass_cards_json,
            hf_card_position=hf_card_position,
            hf_card_scale=hf_card_scale,
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


class AutoPostBody(BaseModel):
    session_path: str
    video_path: str = ""
    title: str = ""
    description: str = ""
    topics: list[str] | str = ""
    # Ordered multi-select. `platform` kept for backward compatibility.
    platforms: list[str] | None = None
    platform: str = ""


@router.post("/auto_post", response_model=StageResult)
def publish_auto_post(body: AutoPostBody) -> StageResult:
    """Publish to selected platforms in order; returns need_login when a platform is not logged in."""
    from api.progress import ProgressShim
    from script.auto_publish import NeedLoginError, auto_publish_sequence
    from workflow.app_config import load_cfg

    session = ensure_session_dir(body.session_path)
    video_path = (body.video_path or "").strip()
    if not video_path:
        cand = session / "final_publish.mp4"
        if cand.is_file():
            video_path = str(cand.resolve())
    if not video_path:
        raise HTTPException(status_code=400, detail="请先完成一键成片，再自动发布")

    if isinstance(body.topics, str):
        topics = [t.strip() for t in body.topics.replace("，", ",").replace("#", " ").split(",") if t.strip()]
        if len(topics) <= 1:
            topics = [t for t in body.topics.replace("，", " ").replace(",", " ").split() if t.strip()]
    else:
        topics = [str(t).strip().lstrip("#") for t in body.topics if str(t).strip()]

    platforms: list[str] = []
    if body.platforms:
        platforms = [str(p).strip().lower() for p in body.platforms if str(p).strip()]
    elif (body.platform or "").strip():
        platforms = [body.platform.strip().lower()]
    if not platforms:
        platforms = ["douyin"]

    cfg = load_cfg()
    progress = ProgressShim()
    try:
        data = auto_publish_sequence(
            cfg,
            platforms,
            video_path=video_path,
            title=body.title,
            description=body.description,
            topics=topics,
            on_progress=progress,
        )
    except NeedLoginError as exc:
        data = {
            "ok": False,
            "need_login": True,
            "platform": exc.platform_id,
            "platform_name": exc.platform_name,
            "remaining": platforms,
            "results": [],
            "message": str(exc),
        }
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return StageResult(
        log=progress.last_msg or data.get("message", ""),
        data=data,
        message=data.get("message", "已打开创作者中心"),
    )

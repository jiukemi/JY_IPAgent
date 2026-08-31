"""Asset library routes."""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from workflow.asset_library import (
    add_file_item,
    add_url_item,
    create_group,
    delete_group,
    delete_item,
    list_library,
    rename_group,
    resolve_file,
    update_item,
)
from workflow.file_serve import safe_file_response

router = APIRouter(prefix="/api/assets", tags=["assets"])


class GroupBody(BaseModel):
    name: str


class GroupRenameBody(BaseModel):
    name: str


class UrlItemBody(BaseModel):
    group_id: str
    name: str = ""
    url: str


class ItemPatchBody(BaseModel):
    name: str | None = None
    group_id: str | None = None


@router.get("")
def get_library() -> dict:
    return list_library()


@router.post("/groups")
def post_group(body: GroupBody) -> dict:
    try:
        return create_group(body.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/groups/{group_id}")
def patch_group(group_id: str, body: GroupRenameBody) -> dict:
    try:
        return rename_group(group_id, body.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/groups/{group_id}")
def remove_group(group_id: str) -> dict:
    try:
        delete_group(group_id)
        return {"ok": True}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/upload")
async def upload_item(
    group_id: str = Form(...),
    name: str = Form(""),
    file: UploadFile = File(...),
) -> dict:
    suffix = Path(file.filename or "").suffix or ".bin"
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await file.read())
            tmp_path = Path(tmp.name)
        item = add_file_item(group_id, name, tmp_path, mime=file.content_type or "")
        tmp_path.unlink(missing_ok=True)
        return {"ok": True, "item": item}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/url")
def post_url_item(body: UrlItemBody) -> dict:
    try:
        item = add_url_item(body.group_id, body.name, body.url)
        return {"ok": True, "item": item}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/items/{item_id}")
def patch_item(item_id: str, body: ItemPatchBody) -> dict:
    try:
        item = update_item(item_id, name=body.name, group_id=body.group_id)
        return {"ok": True, "item": item}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/items/{item_id}")
def remove_item(item_id: str) -> dict:
    try:
        delete_item(item_id)
        return {"ok": True}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class ActiveStyleBody(BaseModel):
    theme: str
    layout: str
    aspect: str
    font_id: str = "noto_sc"
    font_scale: float = 1.0
    bg_mode: str = "generative"
    bg_asset: str = ""
    bg_prompt: str = ""
    remotion_theme: str = "bar"


@router.get("/hyperframe/active_style")
def get_hyperframe_active_style() -> dict:
    from workflow.hyperframe_style import get_active_style

    return get_active_style()


@router.put("/hyperframe/active_style")
def put_hyperframe_active_style(body: ActiveStyleBody) -> dict:
    from workflow.hyperframe_style import set_active_style

    try:
        return set_active_style(
            body.theme,
            body.layout,
            body.aspect,
            font_id=body.font_id,
            font_scale=body.font_scale,
            bg_mode=body.bg_mode,
            bg_asset=body.bg_asset,
            bg_prompt=body.bg_prompt,
            remotion_theme=body.remotion_theme,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/hyperframe/themes")
def get_hyperframe_themes() -> dict:
    from workflow.hyperframes import list_hyperframe_options

    return list_hyperframe_options()


@router.get("/hyperframe/preview")
def preview_hyperframe_card(
    theme: str = "tokyo_night",
    text: str = "HyperFrames 预览",
    layout: str = "kinetic",
    aspect: str = "portrait_9_16",
    font_scale: float = 1.0,
    compose_mode: str = "",
):
    """Static HyperFrames scene still (fast fallback)."""
    import hashlib

    from workflow.hyperframes import render_scene_preview_image

    sample = (text or "").strip()[:160] or "HyperFrames 预览"
    fs = max(0.7, min(2.0, float(font_scale or 1.0)))
    mode = (compose_mode or "").strip().lower()
    key = hashlib.sha256(
        f"still_v4:{theme}:{layout}:{aspect}:{fs:.2f}:{mode}:{sample}".encode("utf-8")
    ).hexdigest()[:20]
    cache_dir = Path("data/assets/hf_previews")
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = cache_dir / f"{key}.png"
    if not out.is_file():
        render_scene_preview_image(
            sample, out, theme=theme, layout=layout, aspect=aspect, font_scale=fs, compose_mode=mode
        )
    return safe_file_response(out, media_type="image/png")


@router.get("/hyperframe/preview_motion")
def preview_hyperframe_motion(
    theme: str = "tokyo_night",
    text: str = "HyperFrames 预览",
    layout: str = "kinetic",
    aspect: str = "portrait_9_16",
    font_scale: float = 1.0,
    compose_mode: str = "",
):
    """Short animated HyperFrames clip for theme/layout picker (loop in UI)."""
    import hashlib

    from fastapi import HTTPException

    from workflow.hyperframes import render_scene_preview_image, render_scene_preview_motion

    sample = (text or "").strip()[:160] or "HyperFrames 预览"
    fs = max(0.7, min(2.0, float(font_scale or 1.0)))
    mode = (compose_mode or "").strip().lower()
    key = hashlib.sha256(
        f"motion_v5:{theme}:{layout}:{aspect}:{fs:.2f}:{mode}:{sample}".encode("utf-8")
    ).hexdigest()[:20]
    cache_dir = Path("data/assets/hf_previews")
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = cache_dir / f"{key}.mp4"
    if not out.is_file() or out.stat().st_size < 64:
        try:
            render_scene_preview_motion(
                sample, out, theme=theme, layout=layout, aspect=aspect, font_scale=fs, compose_mode=mode
            )
        except Exception as exc:
            # Fall back to still PNG if motion render fails
            still = cache_dir / f"{key}_still.png"
            if not still.is_file():
                render_scene_preview_image(
                    sample, still, theme=theme, layout=layout, aspect=aspect, font_scale=fs, compose_mode=mode
                )
            return safe_file_response(still, media_type="image/png")
    if not out.is_file():
        raise HTTPException(status_code=500, detail="动效预览生成失败")
    return safe_file_response(out, media_type="video/mp4")


@router.post("/hyperframe")
async def generate_hyperframe_asset(
    text: str = Form(...),
    mode: str = Form("image"),
    theme: str = Form("tokyo_night"),
    layout: str = Form("kinetic"),
    aspect: str = Form("portrait_9_16"),
    group_id: str = Form("card"),
    name: str = Form(""),
    duration_sec: float = Form(5.0),
    pause_sec: float = Form(0.35),
    max_chars: int = Form(16),
) -> dict:
    """Generate HyperFrames scene (PNG / CSS MP4 / slideshow) and save to library."""
    import tempfile

    from workflow.app_config import load_cfg
    from workflow.hyperframes import (
        generate_hyperframes_video,
        render_scene_preview_image,
    )
    from workflow.hyperframes_scenes import generate_scene_video, resolve_layout
    from pipeline import ensure_ffmpeg

    text = (text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="请填写文案内容")

    mode = (mode or "image").lower()
    layout_key = (layout or "kinetic").lower().replace("-", "_")
    aspect_key = (aspect or "portrait_9_16").lower().replace("-", "_")
    cfg = load_cfg()
    ffmpeg_bin = ensure_ffmpeg((cfg.get("paths") or {}).get("ffmpeg", "ffmpeg"))
    display = (name or "").strip() or text[:24].replace("\n", " ")
    from workflow.hyperframes import _resolve_theme

    pal = _resolve_theme(theme)
    meta = resolve_layout(layout_key)

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        if mode == "slideshow":
            duration = max(3.0, min(len(text) * 0.35 + 2.0, 180.0))
            out = work / "hf_slideshow.mp4"
            generate_hyperframes_video(
                text,
                duration,
                out,
                pause_sec=float(pause_sec),
                max_chars=int(max_chars),
                ffmpeg_bin=ffmpeg_bin,
                theme=theme,
                layout=layout_key,
                aspect=aspect_key,
            )
            target_group = "video" if group_id not in ("card", "video") else group_id
            item = add_file_item(target_group, display, out, mime="video/mp4")
        elif mode in ("video", "scene"):
            out = work / "hf_scene.mp4"
            generate_scene_video(
                text,
                out,
                duration_sec=float(duration_sec),
                layout=layout_key,
                theme=pal,
                ffmpeg_bin=ffmpeg_bin,
                aspect=aspect_key,
            )
            target_group = group_id if group_id in ("card", "video") else "video"
            item = add_file_item(target_group, display, out, mime="video/mp4")
        else:
            out = work / "hf_scene.png"
            render_scene_preview_image(
                text, out, theme=theme, layout=layout_key, aspect=aspect_key
            )
            target_group = group_id if group_id in ("card", "icon", "video") else "card"
            item = add_file_item(target_group, display, out, mime="image/png")

    return {"ok": True, "item": item, "mode": mode, "theme": theme, "layout": layout_key, "aspect": aspect_key}


@router.get("/picker")
def get_picker_assets() -> dict:
    from workflow.asset_library import list_picker_items

    return {"items": list_picker_items()}


@router.get("/file")
def get_asset_file(id: str):
    try:
        path = resolve_file(id)
        return safe_file_response(path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="文件不存在") from exc

"""Stage services — workflow logic without Gradio UI."""

from __future__ import annotations

import shutil
import subprocess
import traceback
from collections.abc import Callable
from pathlib import Path

from api.errors import stage_errors
from api.progress import ProgressShim
from pipeline import apply_lipsync_quality, ensure_ffmpeg, ffprobe_bin, media_kind, run_pipeline
from script.cloud import load_reference_meta
from tts.engine import synthesize
from tts.voice_catalog import get_voice_entry, resolve_synthesis, selected_label
from tts.voices import get_voice, save_voice, update_voice
from ui.script_stage import (
    load_script_panel,
    run_cdn_stage,
    run_extract_stage,
    run_rewrite_stage,
    run_transcript_stage,
)
from workflow.app_config import CONFIG_PATH, load_cfg
from workflow.deployment import resolve_tts_backend
from workflow.media_utils import media_path
from workflow.providers.avatar import run_avatar_video
from workflow.publish import (
    default_title_from_script,
    load_session_script,
    render_subtitle_preview_frame,
    resolve_lipsync_video,
    resolve_session_dub_audio,
    resolve_session_video,
    resolve_subtitle_cues,
    resolve_timing_duration,
    run_publish,
)
from workflow.session import (
    archive_current_lipsync,
    default_display_name,
    ensure_session_dir,
    get_session_by_path,
    list_session_dubbings,
    list_session_lipsyncs,
    session_ui_snapshot,
    set_selected_dub_path,
    set_selected_lipsync_path,
)

from avatar.catalog import get_avatar
from tts.voice_catalog import refresh_catalog


def _lipsync_backend_default(mode: str, avatar_id: str | None = None) -> str:
    lipsync = load_cfg().get("lipsync", {})
    mode = (mode or "digital").lower()
    if avatar_id:
        entry = get_avatar(avatar_id)
        if entry and entry.backend:
            return entry.backend.lower()
    if mode == "real":
        return (lipsync.get("real_backend") or "latentsync").lower()
    return (lipsync.get("digital_backend") or "heygem").lower()


@stage_errors
def script_cdn(session_path: str, share_url: str) -> dict:
    cfg = load_cfg()
    progress = ProgressShim()
    log, preview, cdn_md = run_cdn_stage(session_path, share_url, cfg, progress=progress)
    return {
        "log": log,
        "preview_video": preview,
        "cdn_md": cdn_md,
    }


@stage_errors
def script_transcript(session_path: str, share_url: str, ref_media: str | None = None) -> dict:
    cfg = load_cfg()
    progress = ProgressShim()
    text, log, preview, cdn_md = run_transcript_stage(
        session_path, share_url, ref_media, cfg, progress=progress
    )
    if text:
        from workflow.session import snapshot_script_extract

        snapshot_script_extract(session_path, text)
    return {
        "script": text,
        "log": log,
        "preview_video": preview,
        "cdn_md": cdn_md,
    }


@stage_errors
def script_extract(session_path: str, share_url: str, ref_media: str | None = None) -> dict:
    cfg = load_cfg()
    progress = ProgressShim()
    text, log, preview, cdn_md = run_extract_stage(
        session_path, share_url, ref_media, cfg, progress=progress
    )
    if text:
        from workflow.session import snapshot_script_extract

        snapshot_script_extract(session_path, text)
    return {
        "script": text,
        "log": log,
        "preview_video": preview,
        "cdn_md": cdn_md,
    }


def script_extract_with_progress(
    session_path: str,
    share_url: str,
    ref_media: str | None,
    on_progress,
) -> dict:
    """Same as script_extract but streams progress via on_progress(pct, desc)."""
    cfg = load_cfg()
    progress = ProgressShim(on_tick=on_progress)
    text, log, preview, cdn_md = run_extract_stage(
        session_path, share_url, ref_media, cfg, progress=progress
    )
    if text:
        from workflow.session import snapshot_script_extract

        snapshot_script_extract(session_path, text)
    on_progress(1.0, "完成")
    return {
        "script": text,
        "log": log,
        "preview_video": preview,
        "cdn_md": cdn_md,
    }


@stage_errors
def script_rewrite(session_path: str, script: str, intensity: str) -> dict:
    cfg = load_cfg()
    progress = ProgressShim()
    text, log = run_rewrite_stage(session_path, script, intensity, cfg, progress=progress)
    if text:
        from workflow.session import snapshot_script_rewritten

        snapshot_script_rewritten(session_path, text)
    return {"script": text, "log": log}


@stage_errors
def script_suggest_hotwords(
    identity: str = "",
    profession: str = "",
    *,
    industry: str = "",
    product: str = "",
    audience: str = "",
    roles: list | None = None,
    mix_roles: bool = False,
) -> dict:
    from script.hot_generate import suggest_hotwords

    cfg = load_cfg()
    progress = ProgressShim()
    data = suggest_hotwords(
        cfg,
        identity=identity,
        profession=profession,
        industry=industry,
        product=product,
        audience=audience,
        roles=roles,
        mix_roles=mix_roles,
        on_progress=progress,
    )
    return {**data, "log": progress.last_msg or "热词已生成"}


@stage_errors
def script_generate_from_profile(
    session_path: str,
    *,
    identity: str = "",
    profession: str = "",
    industry: str = "",
    product: str = "",
    audience: str = "",
    selling_points: str = "",
    duration_sec: int = 45,
    hotwords: list[str] | None = None,
    extra: str = "",
    roles: list | None = None,
    mix_roles: bool = False,
    auto_hotwords: bool = False,
    save_as: str = "rewritten",
    continue_from: str = "",
    on_delta=None,
    should_stop=None,
    on_progress=None,
) -> dict:
    from script.hot_generate import generate_script_from_profile
    from workflow.session import snapshot_script_extract, snapshot_script_rewritten

    cfg = load_cfg()
    progress = ProgressShim(on_tick=on_progress)
    ensure_session_dir(session_path)
    data = generate_script_from_profile(
        cfg,
        identity=identity,
        profession=profession,
        industry=industry,
        product=product,
        audience=audience,
        selling_points=selling_points,
        roles=roles,
        mix_roles=mix_roles,
        duration_sec=duration_sec,
        hotwords=hotwords,
        extra=extra,
        auto_hotwords=auto_hotwords,
        on_progress=progress,
        on_delta=on_delta,
        should_stop=should_stop,
        continue_from=continue_from,
    )
    text = (data.get("script") or "").strip()
    if not text:
        raise RuntimeError("文稿生成结果为空")
    variant = (save_as or "rewritten").strip().lower()
    if variant == "extract":
        snapshot_script_extract(session_path, text)
    else:
        snapshot_script_rewritten(session_path, text)
        variant = "rewritten"
    session = ensure_session_dir(session_path)
    (session / "script.txt").write_text(text, encoding="utf-8")
    return {
        **data,
        "save_as": variant,
        "log": progress.last_msg or ("已暂停，可点继续" if data.get("paused") else "文稿已生成"),
    }


@stage_errors
def script_competitor_analyze(
    session_path: str,
    profile_url: str = "",
    *,
    competitor_id: str = "",
    roles: list | None = None,
    mix_roles: bool = False,
    duration_sec: int = 45,
    hotwords: list[str] | None = None,
    extra: str = "",
    deep_transcript: bool = True,
    save_as: str = "rewritten",
) -> dict:
    from script.competitor_pipeline import generate_from_saved_competitor, save_competitor_blogger
    from script.hot_generate import normalize_roles
    from workflow.session import snapshot_script_extract, snapshot_script_rewritten

    cfg = load_cfg()
    progress = ProgressShim()
    session = ensure_session_dir(session_path)
    role_list = normalize_roles(roles)
    if not role_list:
        raise ValueError("请先添加自己的角色人设")

    cid = (competitor_id or "").strip()
    if not cid:
        if not (profile_url or "").strip():
            raise ValueError("请选择知识库对标，或填写主页链接先入库")
        entry = save_competitor_blogger(
            cfg,
            profile_url,
            work_dir=session / "competitor_analysis",
            deep_transcript=deep_transcript,
            on_progress=lambda p, d: progress(p * 0.55, d),
        )
        cid = entry["id"]

    data = generate_from_saved_competitor(
        cfg,
        cid,
        roles=role_list,
        mix_roles=mix_roles,
        duration_sec=duration_sec,
        hotwords=hotwords,
        extra=extra,
        on_progress=lambda p, d: progress(0.55 + p * 0.45, d),
    )
    text = (data.get("script") or "").strip()
    if not text:
        raise RuntimeError("专属文稿生成结果为空")
    variant = (save_as or "rewritten").strip().lower()
    if variant == "extract":
        snapshot_script_extract(session_path, text)
    else:
        snapshot_script_rewritten(session_path, text)
        variant = "rewritten"
    (session / "script.txt").write_text(text, encoding="utf-8")
    return {
        **data,
        "save_as": variant,
        "log": progress.last_msg or "根据对标仿写完成",
    }


@stage_errors
def script_legal(session_path: str, script: str, source: str = "extract") -> dict:
    cfg = load_cfg()
    progress = ProgressShim()
    from workflow.providers.script import run_script_legal
    from workflow.session import read_session_scripts, snapshot_script_legal

    scripts = read_session_scripts(session_path)
    text = (script or "").strip()
    if not text:
        if source == "rewritten":
            text = scripts.get("rewritten") or scripts.get("extract") or ""
        else:
            text = scripts.get("extract") or scripts.get("active") or ""
    if not text.strip():
        raise ValueError("文案为空，请先提取或手写")

    result = run_script_legal(cfg, text, on_progress=progress)
    session = ensure_session_dir(session_path)
    (session / "script.txt").write_text(result.cleaned, encoding="utf-8")
    snapshot_script_legal(session_path, result.cleaned)
    report_path = session / "legal_report.txt"
    report_path.write_text(result.report, encoding="utf-8")

    flags = f"本地词表命中: {', '.join(result.local_flags)}" if result.local_flags else ""
    log = "\n".join(
        x
        for x in [
            "AI法务审查完成 → script_legal.txt",
            flags,
            "",
            result.report,
            "",
            f"合规文案 {len(text)} → {len(result.cleaned)} 字",
        ]
        if x is not None
    )
    return {
        "script": result.cleaned,
        "report": result.report,
        "local_flags": result.local_flags,
        "log": log,
    }


@stage_errors
def save_script_text(session_path: str, variant: str, text: str) -> dict:
    from workflow.session import save_script_variant

    scripts = save_script_variant(session_path, variant, text)
    return {"scripts": scripts, "script": scripts["active"]}


@stage_errors
def run_tts(
    session_path: str,
    text: str,
    voice_uid: str,
    speed_mode: str = "balanced",
    backend: str | None = None,
    style_extra: str | None = None,
    on_progress=None,
) -> dict:
    if not session_path:
        raise ValueError("请先创建或恢复会话")
    text = (text or "").strip()
    if not text:
        raise ValueError("请输入口播文案")
    if not voice_uid:
        raise ValueError("请先选择音色")

    from workflow.session import archive_current_dubbing
    from workflow.task_control import begin_job

    session = ensure_session_dir(session_path)
    session.mkdir(parents=True, exist_ok=True)
    begin_job("tts")
    archive_current_dubbing(str(session))
    (session / "script.txt").write_text(text, encoding="utf-8")
    cfg = load_cfg()
    params = resolve_synthesis(voice_uid)
    tts_backend = (backend or "").strip() or resolve_tts_backend(cfg)
    entry = get_voice_entry(voice_uid)
    voice_backend = params.get("backend") or tts_backend

    if entry and entry.mode != "clone":
        if entry.backend != tts_backend:
            raise ValueError(
                f"音色「{entry.label}」属于 {entry.backend}，"
                f"与当前引擎 {tts_backend} 不一致，请切换引擎或重新选择音色"
            )
        effective_backend = tts_backend
    elif voice_backend == tts_backend:
        effective_backend = tts_backend
    else:
        raise ValueError(
            f"克隆音色属于 {voice_backend}，与当前引擎 {tts_backend} 不匹配，"
            f"请在 ② 配音切换引擎或用当前引擎重新保存克隆"
        )

    progress = ProgressShim(on_tick=on_progress)

    clone_prompt = ""
    if params["mode"] == "clone":
        entry = get_voice(params["saved_voice_id"])
        clone_prompt = (entry or {}).get("prompt_text", "")

    try:
        extra = (style_extra or "").strip() or (params.get("style_extra") or "")
        result = synthesize(
            cfg,
            text,
            session,
            mode=params["mode"],
            preset_id=params["preset_id"] or "mandarin_female_warm",
            style_extra=extra,
            saved_voice_id=params.get("saved_voice_id"),
            prompt_text=clone_prompt,
            backend=effective_backend,
            speed=speed_mode or "balanced",
            on_progress=progress,
        )
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        from api.errors import format_user_error

        raise type(exc)(format_user_error(str(exc), engine=effective_backend)) from exc
    entry = get_voice_entry(voice_uid)
    voice_name = entry.label if entry else voice_uid
    log = (
        f"音色={voice_name}\n"
        f"backend={result['backend']}\n"
        f"音频时长={result.get('audio_duration', '—')}\n"
        f"16k={result['audio']}"
    )
    _pin_latest_dub(str(session), result["audio"])
    return {
        "audio_path": result["audio"],
        "log": log,
        "session_path": str(session),
    }


TTS_PREVIEW_SAMPLE = "大家好，这款产品真的很好用，值得了解一下！"


@stage_errors
def run_tts_preview(
    session_path: str,
    voice_uid: str,
    *,
    text: str = "",
    style_extra: str = "",
    speed_mode: str = "balanced",
    backend: str | None = None,
    preview_key: str = "styled",
) -> dict:
    """Short clone preview — does not archive or replace session dubbing."""
    if not session_path:
        raise ValueError("请先创建或恢复会话")
    if not voice_uid:
        raise ValueError("请先选择音色")

    session = ensure_session_dir(session_path)
    cfg = load_cfg()
    params = resolve_synthesis(voice_uid)
    if params.get("mode") != "clone":
        raise ValueError("情感试听仅支持克隆音色")

    tts_backend = (backend or "").strip() or resolve_tts_backend(cfg)
    entry = get_voice_entry(voice_uid)
    voice_backend = params.get("backend") or tts_backend
    if entry and entry.mode != "clone" and entry.backend != tts_backend:
        raise ValueError(f"音色引擎与当前设置不一致")
    if voice_backend != tts_backend:
        raise ValueError(f"克隆音色属于 {voice_backend}，与当前引擎 {tts_backend} 不匹配")

    body = (text or TTS_PREVIEW_SAMPLE).strip()
    preview_root = session / "_tts_preview"
    preview_root.mkdir(parents=True, exist_ok=True)
    out_dir = preview_root / (preview_key or "styled")
    if out_dir.is_dir():
        shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    clone_prompt = ""
    if params["mode"] == "clone":
        entry_v = get_voice(params["saved_voice_id"])
        clone_prompt = (entry_v or {}).get("prompt_text", "")

    extra = (style_extra or "").strip()
    result = synthesize(
        cfg,
        body,
        out_dir,
        mode=params["mode"],
        preset_id=params["preset_id"] or "mandarin_female_warm",
        style_extra=extra,
        saved_voice_id=params.get("saved_voice_id"),
        prompt_text=clone_prompt,
        backend=tts_backend,
        speed=speed_mode or "balanced",
    )
    return {
        "audio_path": result["audio"],
        "preview_key": preview_key,
        "style_extra": extra,
        "text": body,
    }


def _pin_latest_dub(session_path: str, audio_path: str) -> None:
    try:
        set_selected_dub_path(session_path, audio_path)
    except (ValueError, FileNotFoundError):
        pass
    try:
        from workflow.session import invalidate_stale_lipsync_outputs

        invalidate_stale_lipsync_outputs(session_path)
    except OSError:
        pass


@stage_errors
def run_lipsync(
    session_path: str,
    track_mode: str,
    backend: str,
    quality: str,
    avatar_id: str | None,
    audio_path: str | None,
    media_file: str | None = None,
    ref_pose_file: str | None = None,
    pose_style: float = 0,
    still_head: bool = False,
    expression_scale: float = 1.0,
    on_progress=None,
) -> dict:
    if not session_path:
        raise ValueError("请先完成阶段一或创建会话")
    mode = (track_mode or "digital").lower()
    backend = (backend or _lipsync_backend_default(mode, avatar_id)).lower()
    media = media_path(media_file)
    audio = media_path(audio_path)
    if not audio:
        raise ValueError("没有可用配音：请先在阶段三生成配音")

    from workflow.task_control import begin_job

    session = ensure_session_dir(session_path)
    session.mkdir(parents=True, exist_ok=True)
    begin_job(f"lipsync:{backend or mode}")
    progress = ProgressShim(on_tick=on_progress)
    # Keep previous takes in lipsync_takes/ before pipeline overwrites canonical files
    archive_current_lipsync(session, backend=backend, mode=mode)

    ext = Path(media).suffix.lower() if media else ""
    video_copy = None
    portrait_copy = None
    kind = "image"
    if media:
        kind = media_kind(media)

    if mode == "digital":
        if backend == "heygem":
            if not avatar_id:
                raise ValueError("HeyGem 需要选择数字人形象（参考视频类型）")
            entry = get_avatar(avatar_id) if avatar_id else None
            if entry and not entry.supports_backend("heygem"):
                raise ValueError(
                    f"形象「{entry.name}」是肖像类型，请切换 SadTalker，或选择 HeyGem 视频形象"
                )
        elif backend == "sadtalker":
            # Video-type library avatars are HeyGem-only; ignore them when a portrait image is provided.
            if avatar_id:
                entry = get_avatar(avatar_id)
                if entry and not entry.supports_backend("sadtalker"):
                    if media and kind == "image":
                        avatar_id = None
                    elif media and kind == "video":
                        raise ValueError(
                            f"形象「{entry.name}」是 HeyGem 视频形象，不能当肖像人脸。"
                            "请上传肖像图片（jpg/png）；"
                            "动作参考视频请放到「动作参考视频」栏；或改用 HeyGem。"
                        )
                    else:
                        raise ValueError(
                            f"形象「{entry.name}」是视频类型（HeyGem 专用）。"
                            "请改用 HeyGem，或选择 AI/肖像形象，或上传肖像图片。"
                        )
            if not avatar_id and not media:
                raise ValueError(f"{backend} 请选择肖像数字人，或上传肖像图片")
            if media and kind == "video":
                raise ValueError(
                    "人脸素材必须是肖像图片（jpg/png）。"
                    "若要上传动作参考视频，请用「动作参考视频」栏；需要视频驱动请改用 HeyGem。"
                )
        elif not media:
            label = "素材"
            raise ValueError(f"请上传{label}")
        elif backend != "heygem" and kind != "image":
            raise ValueError("数字人请上传肖像图片（jpg/png）")
    else:
        if not media:
            raise ValueError("请上传实拍视频")
        if kind != "video":
            raise ValueError("实拍模式请上传视频（mp4/mov 等）")

    if kind == "image" and media:
        portrait_copy = session / f"input_image{ext or '.png'}"
        shutil.copy2(media, portrait_copy)
    elif kind == "video" and media:
        video_copy = session / f"input_video{ext or '.mp4'}"
        shutil.copy2(media, video_copy)

    if kind == "image" and backend == "latentsync":
        raise ValueError("图片请用 HeyGem 或 SadTalker；LatentSync 仅支持实拍视频")

    sadtalker_overrides = None
    if mode == "digital" and backend == "sadtalker":
        cfg_q = apply_lipsync_quality(load_cfg(), quality)
        st_base = cfg_q.get("sadtalker", {})
        sadtalker_overrides = {
            "pose_style": int(pose_style),
            "still": bool(still_head),
            "expression_scale": float(expression_scale or st_base.get("expression_scale", 1.0)),
            "size": st_base.get("size"),
            "batch_size": st_base.get("batch_size"),
            "enhancer": st_base.get("enhancer"),
        }
        sadtalker_overrides = {k: v for k, v in sadtalker_overrides.items() if v is not None}
        ref_pose = media_path(ref_pose_file)
        if ref_pose:
            ref_ext = Path(ref_pose).suffix.lower() or ".mp4"
            ref_copy = session / f"ref_pose{ref_ext}"
            shutil.copy2(ref_pose, ref_copy)
            sadtalker_overrides["ref_pose"] = str(ref_copy)

    cfg = load_cfg()
    if mode == "digital" and backend in ("heygem", "sadtalker"):
        final = run_avatar_video(
            cfg,
            audio_path=Path(audio),
            work_dir=session,
            backend=backend,
            source_image=portrait_copy,
            avatar_id=avatar_id or None,
            quality=quality,
            sadtalker_overrides=sadtalker_overrides,
            on_progress=progress,
        )
    else:
        final = run_pipeline(
            video_copy,
            Path(audio),
            CONFIG_PATH,
            work_dir=session,
            quality=quality,
            backend=backend,
            source_image=portrait_copy,
            sadtalker_overrides=sadtalker_overrides,
            on_progress=progress,
        )
    video_path = str(Path(final).resolve())
    try:
        from workflow.mp4_faststart import ensure_mp4_faststart

        video_path = str(ensure_mp4_faststart(video_path).resolve())
    except Exception:
        pass
    set_selected_lipsync_path(str(session), video_path)
    model_labels = {
        "heygem": "HeyGem",
        "sadtalker": "SadTalker",
        "latentsync": "LatentSync",
    }
    avatar_name = None
    if avatar_id:
        try:
            entry = get_avatar(avatar_id)
            if entry:
                avatar_name = entry.name
        except Exception:
            pass
    return {
        "video_path": video_path,
        "log": f"[{backend}] 完成 → {final}",
        "backend": backend,
        "model": model_labels.get(backend, backend),
        "quality": quality,
        "track_mode": mode,
        "avatar_id": avatar_id,
        "avatar_name": avatar_name,
    }


@stage_errors
def run_publish_stage(
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
    pip_upload: str | None,
    pip_position: str,
    pip_scale: float,
    pip_margin: int,
    hyperframes_consent: bool,
    hyperframes_theme: str = "tokyo_night",
    hyperframes_layout: str = "kinetic",
    hyperframes_aspect: str = "portrait_9_16",
    *,
    subtitle_font_size: int = 16,
    subtitle_color: str = "#FFFFFF",
    subtitle_outline: int = 1,
    subtitle_shadow: int = 0,
    subtitle_position: str = "bottom",
    pip_cues_json: str = "[]",
    cues_json: str = "",
    bgm_id: str = "",
    bgm_volume: float = 0.18,
    bgm_start: float = 0.0,
    enable_bgm: bool = True,
    hyperframes_target_indices_json: str = "",
    lecturer_crop_json: str = "",
    on_progress: Callable[[float, str | None], None] | None = None,
    remotion_theme: str = "off",
    layout_mode: str = "short",
    remotion_smart_keywords: bool = True,
    hf_text_cards: bool = False,
    cover_image_path: str = "",
    glass_cards_json: str = "[]",
    hf_card_position: str = "auto",
    hf_card_scale: float = 0.42,
) -> dict:
    if not session_path:
        raise ValueError("请先创建或选择会话")
    from workflow.task_control import begin_job

    session = ensure_session_dir(session_path)
    begin_job("publish")
    video = resolve_session_video(session)
    if video is None:
        raise ValueError("未找到成片，请先在阶段四生成对口型视频")
    script = (script or load_session_script(session)).strip()
    if not script:
        raise ValueError("字幕需要文案")

    cfg = load_cfg()
    pub = cfg.get("publish", {})
    paths = cfg["paths"]
    ffmpeg_bin = ensure_ffmpeg(paths.get("ffmpeg", "ffmpeg"))
    probe = ffprobe_bin(ffmpeg_bin)
    progress = ProgressShim()

    pip_path = None
    pip_mode = (pip_mode or "none").lower()
    if pip_mode in ("upload", "education", "education_timed"):
        up = media_path(pip_upload)
        if up:
            ext = Path(up).suffix.lower() or ".mp4"
            pip_path = session / "publish" / f"pip_upload{ext}"
            pip_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(up, pip_path)
        elif pip_mode == "upload":
            raise ValueError("画中画：请上传图片或短视频")
    elif pip_mode == "hyperframes" and not hyperframes_consent:
        raise ValueError("请勾选同意 HyperFrames 根据文案生成画中画素材")

    import json

    pip_cue_assignments: list[dict] = []
    if pip_mode in ("timed", "education_timed"):
        try:
            pip_cue_assignments = json.loads(pip_cues_json or "[]")
        except json.JSONDecodeError:
            pip_cue_assignments = []
        if not isinstance(pip_cue_assignments, list):
            pip_cue_assignments = []

    cues_override = None
    if (cues_json or "").strip():
        try:
            raw = json.loads(cues_json)
            if isinstance(raw, list) and raw:
                from workflow.publish import SubCue

                cues_override = [
                    SubCue(
                        int(c.get("index") or i + 1),
                        float(c["start"]),
                        float(c["end"]),
                        str(c.get("text") or "").strip(),
                    )
                    for i, c in enumerate(raw)
                    if c.get("text")
                ]
        except (json.JSONDecodeError, TypeError, ValueError, KeyError):
            cues_override = None

    from workflow.bgm import resolve_bgm_path

    bgm_path = None
    if enable_bgm and (bgm_id or "").strip() and (bgm_id or "").lower() not in ("none", "off"):
        bgm_path = resolve_bgm_path(bgm_id)
        if bgm_path is None:
            raise ValueError(f"BGM 未找到: {bgm_id}。请运行 py -3.11 scripts/download_bgm.py 下载曲库")

    hf_target: set[int] | None = None
    if (hyperframes_target_indices_json or "").strip():
        try:
            raw_t = json.loads(hyperframes_target_indices_json)
            if isinstance(raw_t, list):
                hf_target = {int(i) for i in raw_t if int(i) > 0}
        except (json.JSONDecodeError, TypeError, ValueError):
            hf_target = None

    lecturer_crop = None
    if (lecturer_crop_json or "").strip():
        try:
            raw_c = json.loads(lecturer_crop_json)
            if isinstance(raw_c, dict) and raw_c.get("w"):
                lecturer_crop = raw_c
        except (json.JSONDecodeError, TypeError, ValueError):
            lecturer_crop = None

    glass_specs: list[dict] = []
    if (glass_cards_json or "").strip():
        try:
            raw_g = json.loads(glass_cards_json)
            if isinstance(raw_g, list):
                glass_specs = [x for x in raw_g if isinstance(x, dict)]
        except (json.JSONDecodeError, TypeError, ValueError):
            glass_specs = []

    result = run_publish(
        session,
        script=script,
        title=(title or default_title_from_script(script)).strip(),
        cover_time=float(cover_time),
        template_id=template,
        do_burn_subtitles=bool(burn_subtitles),
        subtitle_style=subtitle_style,
        subtitle_pause=float(subtitle_pause),
        subtitle_max_chars=int(pub.get("subtitle_max_chars", 18)),
        do_embed_cover=bool(embed_cover),
        ffmpeg_bin=ffmpeg_bin,
        probe_bin=probe,
        pip_mode=pip_mode,
        pip_source=pip_path,
        pip_position=pip_position or pub.get("pip_position", "top_right"),
        pip_scale=float(pip_scale or pub.get("pip_scale", 0.28)),
        pip_margin=int(pip_margin or pub.get("pip_margin", 24)),
        hyperframes_consent=bool(hyperframes_consent),
        hyperframes_theme=(hyperframes_theme or "tokyo_night"),
        hyperframes_layout=(hyperframes_layout or pub.get("hyperframes_layout", "kinetic")),
        hyperframes_aspect=(hyperframes_aspect or pub.get("hyperframes_aspect", "portrait_9_16")),
        hyperframes_target_indices=hf_target,
        pip_cue_assignments=pip_cue_assignments,
        lecturer_crop=lecturer_crop,
        subtitle_font_size=int(subtitle_font_size or pub.get("subtitle_font_size", 8)),
        subtitle_color=subtitle_color or "#FFFFFF",
        subtitle_outline=int(subtitle_outline if subtitle_outline is not None else 1),
        subtitle_shadow=int(subtitle_shadow if subtitle_shadow is not None else 0),
        subtitle_position=subtitle_position or "bottom",
        bgm_path=bgm_path,
        bgm_volume=float(bgm_volume if bgm_volume is not None else pub.get("default_bgm_volume", 0.22)),
        bgm_start=float(bgm_start or 0),
        cues_override=cues_override,
        on_progress=on_progress,
        remotion_theme=remotion_theme,
        layout_mode=layout_mode or "short",
        remotion_smart_keywords=remotion_smart_keywords,
        hf_text_cards=bool(hf_text_cards),
        cover_image_path=(cover_image_path or "").strip() or None,
        glass_cards=glass_specs,
        hf_card_position=(hf_card_position or "auto"),
        hf_card_scale=float(hf_card_scale or 0.42),
    )
    log = (
        f"发布完成 → {result['video']}\n"
        f"字幕条数: {result['cue_count']} | 时长: {result['duration']} ({result.get('timing_note', '')})\n"
        f"SRT: {result['srt']}\n"
        f"封面: {result['cover']}"
    )
    if result.get("bgm"):
        log += f"\nBGM: 已混入 {result['bgm']}"
        if bgm_start and float(bgm_start) > 0:
            log += f"（起点 {float(bgm_start):.1f}s）"
    elif enable_bgm and bgm_id:
        log += "\nBGM: 未混入（请检查曲目或音量）"
    return {
        "video_path": str(result["video"]),
        "cover_path": str(result["cover"]),
        "srt_path": str(result["srt"]),
        "log": log,
    }


@stage_errors
def preview_publish_cues(
    session_path: str,
    script: str,
    subtitle_pause: float,
    subtitle_max_chars: int,
    *,
    subtitle_font_size: int = 16,
    output_aspect: str = "portrait_9_16",
) -> dict:
    if not session_path:
        raise ValueError("请先创建或选择会话")
    session = ensure_session_dir(session_path)
    video = resolve_session_video(session)
    if video is None:
        raise ValueError("未找到成片，请先在阶段四生成对口型视频")
    script = (script or load_session_script(session)).strip()
    if not script:
        raise ValueError("文案为空")

    cfg = load_cfg()
    paths = cfg["paths"]
    ffmpeg_bin = ensure_ffmpeg(paths.get("ffmpeg", "ffmpeg"))
    probe = ffprobe_bin(ffmpeg_bin)
    pub = cfg.get("publish", {})
    duration, _ = resolve_timing_duration(session, video, probe)
    from workflow.hyperframes_scenes import resolve_scene_aspect
    from workflow.publish import probe_video_dimensions, resolve_subtitle_split_chars

    vw, vh = probe_video_dimensions(probe, video)
    _ = resolve_scene_aspect(output_aspect, video_width=vw, video_height=vh)
    split_chars = resolve_subtitle_split_chars(
        int(subtitle_font_size or 16),
        vw,
        vh,
        config_max=int(subtitle_max_chars or pub.get("subtitle_max_chars", 18)),
    )
    cues, timing_note, timing_mode = resolve_subtitle_cues(
        session,
        script,
        duration,
        cfg=cfg,
        pause_sec=float(subtitle_pause),
        max_chars=split_chars,
        auto_align_audio=True,
    )
    has_dub = resolve_session_dub_audio(session) is not None
    font_note = f" · 字号{int(subtitle_font_size or 16)}→约{split_chars}字/条"
    return {
        "cues": [
            {
                "index": c.index,
                "start": round(c.start, 2),
                "end": round(c.end, 2),
                "text": c.text,
            }
            for c in cues
        ],
        "duration": round(duration, 2),
        "timing_note": (timing_note or "") + font_note,
        "timing_mode": timing_mode,
        "split_chars": split_chars,
        "has_dubbing": has_dub,
        "lipsync_video": str(video) if video else None,
        "pause_mode": "segment_anchored" if timing_mode != "proportional" else "punctuation_weighted",
    }


@stage_errors
def preview_publish_subtitle(
    session_path: str,
    text: str,
    time_sec: float,
    *,
    subtitle_font_size: int = 16,
    subtitle_color: str = "#FFFFFF",
    subtitle_outline: int = 1,
    subtitle_shadow: int = 0,
    subtitle_position: str = "bottom",
    subtitle_style: str = "bottom_clean",
    layout_mode: str = "education",
    output_aspect: str = "portrait_9_16",
    pip_position: str = "bottom_right",
    pip_scale: float = 0.28,
    pip_margin: int = 24,
    pip_bg_media: str | None = None,
    content_pip_position: str = "fullscreen",
    content_pip_scale: float = 0.32,
    content_key_black: bool = False,
    education_bg_path: str | None = None,
    hyperframes_consent: bool = False,
    hyperframes_theme: str = "tokyo_night",
    hyperframes_layout: str = "kinetic",
    hyperframes_aspect: str = "portrait_9_16",
    hide_subtitles: bool = False,
    hide_lecturer: bool = False,
    lecturer_crop: dict | None = None,
    remotion_theme: str = "off",
    smart_keywords: bool = True,
    cue_start: float | None = None,
    cue_end: float | None = None,
) -> dict:
    if not session_path:
        raise ValueError("请先创建或选择会话")
    session = ensure_session_dir(session_path)
    cfg = load_cfg()
    paths = cfg["paths"]
    ffmpeg_bin = ensure_ffmpeg(paths.get("ffmpeg", "ffmpeg"))
    probe = ffprobe_bin(ffmpeg_bin)
    edu_bg = Path(education_bg_path) if education_bg_path else None
    preview_path = render_subtitle_preview_frame(
        ffmpeg_bin,
        probe,
        session,
        "" if hide_subtitles else (text or "字幕预览").strip(),
        time_sec=max(0.0, float(time_sec)),
        font_size=int(subtitle_font_size),
        color_hex=subtitle_color or "#FFFFFF",
        outline=int(subtitle_outline),
        shadow=int(subtitle_shadow),
        position=subtitle_position or "bottom",
        subtitle_style=subtitle_style or "bottom_clean",
        layout_mode=layout_mode or "education",
        output_aspect=output_aspect or "portrait_9_16",
        pip_position=pip_position or "bottom_right",
        pip_scale=float(pip_scale),
        pip_margin=int(pip_margin),
        pip_bg_media=pip_bg_media or None,
        content_pip_position=content_pip_position or "fullscreen",
        content_pip_scale=float(content_pip_scale or 0.32),
        content_key_black=bool(content_key_black),
        education_bg=edu_bg if edu_bg and edu_bg.is_file() else None,
        hyperframes_consent=bool(hyperframes_consent),
        hyperframes_theme=hyperframes_theme or "tokyo_night",
        hyperframes_layout=hyperframes_layout or "kinetic",
        hyperframes_aspect=hyperframes_aspect or output_aspect or "portrait_9_16",
        hide_subtitles=bool(hide_subtitles),
        hide_lecturer=bool(hide_lecturer),
        lecturer_crop=lecturer_crop,
        remotion_theme=remotion_theme or "off",
        smart_keywords=smart_keywords,
        cue_start=cue_start,
        cue_end=cue_end,
    )
    mtime = int(preview_path.stat().st_mtime * 1000)
    mode = (layout_mode or "education").lower()
    aspect_label = "16:9" if "16_9" in (output_aspect or "") else "9:16"
    rem = (remotion_theme or "off").strip().lower()
    rem_resolved = rem
    if rem not in ("", "off", "none", "ass", "classic"):
        from workflow.remotion_captions import resolve_remotion_theme

        rem_resolved = resolve_remotion_theme(rem, (text or "").strip())
    return {
        "preview_path": str(preview_path.resolve()),
        "mtime": mtime,
        "used_placeholder": resolve_lipsync_video(session) is None,
        "layout_mode": mode,
        "remotion_theme": rem,
        "remotion_theme_resolved": rem_resolved,
        "output_aspect": output_aspect,
        "aspect_label": aspect_label,
    }


@stage_errors
def auto_detect_lecturer_crop(session_path: str, *, time_sec: float = 0.8) -> dict:
    if not session_path:
        raise ValueError("请先创建或选择会话")
    from PIL import Image

    from workflow.lecturer_crop import detect_lecturer_norm_crop, apply_norm_crop_image
    from workflow.publish import extract_cover_frame, resolve_lipsync_video

    session = ensure_session_dir(session_path)
    video = resolve_lipsync_video(session)
    if video is None or not video.is_file():
        raise FileNotFoundError("未找到口播成片，请先完成④对口型")
    cfg = load_cfg()
    paths = cfg["paths"]
    ffmpeg_bin = ensure_ffmpeg(paths.get("ffmpeg", "ffmpeg"))
    preview_dir = session / "publish" / "preview"
    preview_dir.mkdir(parents=True, exist_ok=True)
    frame = preview_dir / "_lecturer_crop_probe.jpg"
    extract_cover_frame(ffmpeg_bin, video, max(0.0, float(time_sec)), frame)
    im = Image.open(frame).convert("RGB")
    crop = detect_lecturer_norm_crop(im)
    cut = apply_norm_crop_image(im, crop)
    cut_path = preview_dir / "_lecturer_crop_preview.jpg"
    cut.save(cut_path, quality=90)
    return {
        "ok": True,
        "crop": crop.to_dict(),
        "preview_path": str(cut_path.resolve()),
        "frame_path": str(frame.resolve()),
        "mtime": int(cut_path.stat().st_mtime * 1000),
        "source_size": {"w": im.size[0], "h": im.size[1]},
    }


@stage_errors
def extract_lecturer_crop_frame(session_path: str, *, time_sec: float = 0.8) -> dict:
    if not session_path:
        raise ValueError("请先创建或选择会话")
    from PIL import Image

    from workflow.publish import extract_cover_frame, resolve_lipsync_video

    session = ensure_session_dir(session_path)
    video = resolve_lipsync_video(session)
    if video is None or not video.is_file():
        raise FileNotFoundError("未找到口播成片，请先完成④对口型")
    cfg = load_cfg()
    paths = cfg["paths"]
    ffmpeg_bin = ensure_ffmpeg(paths.get("ffmpeg", "ffmpeg"))
    preview_dir = session / "publish" / "preview"
    preview_dir.mkdir(parents=True, exist_ok=True)
    frame = preview_dir / "_lecturer_crop_probe.jpg"
    extract_cover_frame(ffmpeg_bin, video, max(0.0, float(time_sec)), frame)
    im = Image.open(frame).convert("RGB")
    return {
        "ok": True,
        "frame_path": str(frame.resolve()),
        "mtime": int(frame.stat().st_mtime * 1000),
        "source_size": {"w": im.size[0], "h": im.size[1]},
    }


@stage_errors
def align_publish_from_audio(session_path: str, *, use_video_audio: bool = False) -> dict:
    if not session_path:
        raise ValueError("请先创建或选择会话")
    session = ensure_session_dir(session_path)
    cfg = load_cfg()
    from tts.dubbing_timing import align_dubbing_from_audio
    from workflow.publish import resolve_lipsync_video, resolve_session_dub_audio

    if use_video_audio:
        if resolve_lipsync_video(session) is None:
            raise FileNotFoundError("未找到口播成片，请先在阶段四生成对口型视频")
    elif resolve_session_dub_audio(session) is None and resolve_lipsync_video(session) is None:
        raise FileNotFoundError("未找到配音或口播成片")

    probe = ffprobe_bin(ensure_ffmpeg(cfg["paths"].get("ffmpeg", "ffmpeg")))
    payload = align_dubbing_from_audio(
        cfg,
        session,
        probe_bin=probe,
        use_video_audio=use_video_audio,
    )
    return {
        "ok": True,
        "segment_count": len(payload.get("segments") or []),
        "duration": payload.get("duration"),
        "source": payload.get("source"),
    }


@stage_errors
def extract_publish_subtitles(
    session_path: str,
    *,
    use_video_audio: bool = True,
    update_script: bool = True,
    subtitle_font_size: int = 16,
    output_aspect: str = "portrait_9_16",
    subtitle_max_chars: int | None = None,
) -> dict:
    """One-click: ASR from lipsync/dubbing audio → cues use recognized text (source of truth)."""
    if not session_path:
        raise ValueError("请先创建或选择会话")
    session = ensure_session_dir(session_path)
    cfg = load_cfg()
    from tts.dubbing_timing import ensure_subtitle_timing_manifest
    from workflow.hyperframes_scenes import resolve_scene_aspect
    from workflow.publish import (
        asr_transcript_from_segments,
        cues_from_asr_segments,
        probe_video_dimensions,
        resolve_lipsync_video,
        resolve_session_dub_audio,
        resolve_session_video,
        resolve_subtitle_split_chars,
        resolve_timing_duration,
    )
    from workflow.session import save_script_variant

    video = resolve_lipsync_video(session) or resolve_session_video(session)
    dub = resolve_session_dub_audio(session)
    if use_video_audio and video is None and dub is None:
        raise FileNotFoundError("未找到口播成片或配音，无法提取字幕")
    if not use_video_audio and dub is None and video is None:
        raise FileNotFoundError("未找到配音或口播成片，无法提取字幕")

    paths = cfg["paths"]
    ffmpeg_bin = ensure_ffmpeg(paths.get("ffmpeg", "ffmpeg"))
    probe = ffprobe_bin(ffmpeg_bin)
    pub = cfg.get("publish", {})

    # Prefer lipsync audio when available (matches what users hear on screen)
    force_video = bool(use_video_audio and video is not None)
    video_mtime = video.stat().st_mtime if video and video.is_file() else None
    if force_video:
        from tts.dubbing_timing import align_dubbing_from_audio

        manifest = align_dubbing_from_audio(
            cfg,
            session,
            probe_bin=probe,
            use_video_audio=True,
            lipsync_video_mtime=video_mtime,
        )
    else:
        manifest = ensure_subtitle_timing_manifest(cfg, session, probe_bin=probe, force=True)
    segs = (manifest or {}).get("segments") or []
    if not segs:
        raise RuntimeError("语音识别未返回有效分段，请确认 Whisper / FunASR 已安装")

    media = video if video and video.is_file() else dub
    duration, _ = resolve_timing_duration(session, media, probe) if media else (
        float((manifest or {}).get("duration") or 0),
        "asr",
    )
    vw, vh = (1080, 1920)
    if video and video.is_file():
        try:
            vw, vh = probe_video_dimensions(probe, video)
        except Exception:
            pass
    _ = resolve_scene_aspect(output_aspect, video_width=vw, video_height=vh)
    split_chars = resolve_subtitle_split_chars(
        int(subtitle_font_size or 16),
        vw,
        vh,
        config_max=int(subtitle_max_chars or pub.get("subtitle_max_chars", 18)),
    )
    cues = cues_from_asr_segments(segs, max_chars=split_chars)
    if not cues:
        raise RuntimeError("识别结果无法生成字幕条，请重试或检查音频质量")

    transcript = asr_transcript_from_segments(segs)
    script_updated = False
    if update_script and transcript:
        # Persist as extract + active script.txt — audio is source of truth
        save_script_variant(str(session), "extract", transcript)
        script_updated = True

    align_from = str((manifest or {}).get("align_from") or "")
    note = (
        f"一键提取 · {'口播成片' if align_from == 'lipsync_video' else '配音'}识别文案"
        f" · {len(cues)} 条 · 以音频为准"
    )
    return {
        "ok": True,
        "cues": [
            {
                "index": c.index,
                "start": round(c.start, 2),
                "end": round(c.end, 2),
                "text": c.text,
            }
            for c in cues
        ],
        "script": transcript,
        "script_updated": script_updated,
        "duration": round(float(duration or (manifest or {}).get("duration") or 0), 2),
        "timing_note": note,
        "timing_mode": "asr_extract",
        "split_chars": split_chars,
        "segment_count": len(segs),
    }


def get_script_panel(session_path: str) -> dict:
    from workflow.session import read_session_scripts

    script, preview, share, cdn_md = load_script_panel(session_path)
    scripts = read_session_scripts(session_path)
    return {
        "script": scripts["active"] or script,
        "script_extract": scripts["extract"],
        "script_rewritten": scripts["rewritten"],
        "script_legal": scripts.get("legal") or "",
        "script_manual": scripts.get("manual") or "",
        "preview_video": preview,
        "share_url": share,
        "cdn_md": cdn_md,
    }


def _read_dubbing_duration(session_path: str) -> float | None:
    import json
    from pathlib import Path

    timing = Path(session_path) / "dubbing_timing.json"
    if timing.is_file():
        try:
            data = json.loads(timing.read_text(encoding="utf-8"))
            dur = float(data.get("duration") or 0)
            if dur > 0:
                return dur
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass
    dub = Path(session_path) / "dubbing_16k.wav"
    if not dub.is_file():
        return None
    try:
        from tts.engine import _audio_duration_sec

        return round(_audio_duration_sec(dub), 2)
    except (OSError, ValueError):
        return None


def _read_dubbing_segments(session_path: str) -> list[dict]:
    from tts.dubbing_patch import resolve_patch_segments

    segs, _src = resolve_patch_segments(Path(session_path))
    out: list[dict] = []
    for s in segs:
        try:
            out.append(
                {
                    "index": int(s.get("index", len(out) + 1)),
                    "start": float(s["start"]),
                    "end": float(s["end"]),
                    "text": str(s.get("text") or ""),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    return out


@stage_errors
def patch_dubbing_segment(
    session_path: str,
    segment_index: int,
    *,
    mode: str = "resynth",
    text: str | None = None,
    voice_uid: str | None = None,
    speed_mode: str = "balanced",
    replacement_audio: str | None = None,
    crossfade_ms: float = 40.0,
) -> dict:
    """Replace one timed segment in current dubbing; archive prior track; keep total timeline."""
    import shutil
    import tempfile
    from datetime import datetime

    from tts.dubbing_patch import (
        find_segment,
        fit_wav_duration,
        resolve_patch_segments,
        splice_with_crossfade,
        synthesize_segment_clip,
        update_segment_in_manifest,
    )
    from tts.engine import convert_to_wav
    from workflow.session import archive_current_dubbing, save_named_dubbing

    if not session_path:
        raise ValueError("请先创建或恢复会话")
    session = ensure_session_dir(session_path)
    base = session / "dubbing_16k.wav"
    if not base.is_file() or base.stat().st_size < 100:
        raise ValueError("当前没有配音成片，请先生成或上传")

    segments, seg_src = resolve_patch_segments(session)
    if not segments:
        raise ValueError("没有可用的段落时间轴。请先完成 TTS 合成，或对配音做一次对齐。")
    seg = find_segment(segments, int(segment_index))
    try:
        start = float(seg["start"])
        end = float(seg["end"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("段落时间无效") from exc
    slot = max(0.05, end - start)
    seg_text = (text if text is not None else str(seg.get("text") or "")).strip()
    mode_l = (mode or "resynth").strip().lower()
    if mode_l not in ("resynth", "replace", "record"):
        raise ValueError("mode 须为 resynth / replace / record")

    cfg = load_cfg()
    ffmpeg = ensure_ffmpeg(cfg["paths"].get("ffmpeg", "ffmpeg"))
    work = Path(tempfile.mkdtemp(prefix="dub_seg_patch_"))
    try:
        clip_raw = work / "clip_in.wav"
        if mode_l == "resynth":
            if not voice_uid:
                raise ValueError("重合成需要先选择音色")
            if not seg_text:
                raise ValueError("该段没有文案，请先填写后再重合成")
            clip_src = synthesize_segment_clip(
                cfg,
                session,
                seg_text,
                voice_uid=voice_uid,
                speed_mode=speed_mode or "balanced",
                work_dir=work / "tts",
            )
            shutil.copy2(clip_src, clip_raw)
            note = "resynth"
        else:
            if not replacement_audio:
                raise ValueError("请提供替换音频")
            convert_to_wav(ffmpeg, Path(replacement_audio), clip_raw, sample_rate=16000)
            note = "record" if mode_l == "record" else "replace"

        clip_fit = work / "clip_fit.wav"
        fit_wav_duration(ffmpeg, clip_raw, clip_fit, slot, sample_rate=16000)
        out_tmp = work / "dubbing_patched.wav"
        splice_with_crossfade(
            ffmpeg,
            base,
            clip_fit,
            out_tmp,
            start,
            end,
            crossfade_ms=float(crossfade_ms),
            sample_rate=16000,
        )
        if not out_tmp.is_file() or out_tmp.stat().st_size < 100:
            raise RuntimeError("拼接失败，未生成有效音频")

        archive_current_dubbing(session)
        shutil.copy2(out_tmp, base)
        update_segment_in_manifest(
            session,
            int(seg.get("index", segment_index)),
            text=seg_text or None,
            note=note,
        )
        # Named history copy for easy rollback
        now = datetime.now().strftime("%H:%M")
        idx_label = seg.get("index", segment_index)
        try:
            save_named_dubbing(
                str(session),
                f"修补段{idx_label}·{now}",
                str(base),
            )
        except (ValueError, FileNotFoundError, OSError):
            pass
        _pin_latest_dub(str(session), str(base.resolve()))
        return {
            "audio_path": str(base.resolve()),
            "segment_index": int(seg.get("index", segment_index)),
            "start": round(start, 3),
            "end": round(end, 3),
            "mode": mode_l,
            "segment_source": seg_src,
            "message": f"已修补第 {idx_label} 段（{start:.1f}s–{end:.1f}s），原轨已归档",
        }
    finally:
        shutil.rmtree(work, ignore_errors=True)


def get_session_snapshot(session_path: str) -> dict:
    snap = session_ui_snapshot(session_path)
    panel = get_script_panel(session_path)
    item = get_session_by_path(session_path) or {}
    dubs = list_session_dubbings(session_path)
    lips = snap.get("lipsyncs") or list_session_lipsyncs(session_path)
    from workflow.session import load_publish_copy

    pub = load_publish_copy(session_path)
    return {
        "path": session_path,
        "name": item.get("name", default_display_name()),
        "script": panel["script"] or snap["script"],
        "script_extract": panel.get("script_extract") or "",
        "script_rewritten": panel.get("script_rewritten") or "",
        "script_legal": panel.get("script_legal") or "",
        "script_manual": panel.get("script_manual") or "",
        "share_url": panel["share_url"],
        "dubbing_duration": _read_dubbing_duration(session_path),
        "dubbing_segments": _read_dubbing_segments(session_path),
        "dubbing_mtime": snap.get("dubbing_mtime"),
        "lipsync_mtime": snap.get("lipsync_mtime"),
        "lipsync_stale": snap.get("lipsync_stale", False),
        "cdn_md": panel["cdn_md"],
        "preview_video": panel["preview_video"] or snap.get("preview_16k"),
        "dubbing_audio": snap.get("preview_16k"),
        "selected_dub": snap.get("selected_dub"),
        "selected_lipsync": snap.get("selected_lipsync"),
        "dubs": dubs,
        "lipsyncs": lips,
        "lipsync_video": snap.get("video_out"),
        "media_input": snap.get("media_in"),
        "tts_log": snap.get("tts_log", ""),
        "lipsync_log": snap.get("lipsync_log", ""),
        "publish_title": pub.get("title") or "",
        "publish_subtitle": pub.get("subtitle") or "",
        "publish_description": pub.get("description") or "",
        "publish_topics": pub.get("topics") or [],
    }


@stage_errors
def upload_session_dubbing(
    session_path: str,
    audio_path: str,
    *,
    source_type: str = "upload",
) -> dict:
    if not session_path:
        raise ValueError("请先创建或恢复会话")
    if not audio_path:
        raise ValueError("请提供音频文件")

    session = ensure_session_dir(session_path)
    session.mkdir(parents=True, exist_ok=True)
    cfg = load_cfg()
    from pathlib import Path
    from tts.engine import convert_to_wav

    final = session / "dubbing_16k.wav"
    convert_to_wav(cfg["paths"].get("ffmpeg", "ffmpeg"), Path(audio_path), final, sample_rate=16000)
    if not final.is_file() or final.stat().st_size < 100:
        raise ValueError("音频无效或过短")
    label = "录音" if (source_type or "").lower() == "record" else "上传"
    audio = str(final.resolve())
    _pin_latest_dub(session_path, audio)
    return {
        "audio_path": audio,
        "message": f"已使用{label}音频作为当前配音",
    }


@stage_errors
def select_session_dubbing(session_path: str, audio_path: str) -> dict:
    entry = set_selected_dub_path(session_path, audio_path)
    return {"message": "已切换配音音轨", **entry}


@stage_errors
def select_session_lipsync(session_path: str, video_path: str) -> dict:
    entry = set_selected_lipsync_path(session_path, video_path)
    return {"message": "已切换口播成片", **entry}


@stage_errors
def delete_named_session_lipsync(session_path: str, take_id: str) -> dict:
    from workflow.session import delete_session_lipsync

    return delete_session_lipsync(session_path, take_id)


@stage_errors
def save_named_session_dubbing(session_path: str, name: str, source_path: str | None = None) -> dict:
    from workflow.session import save_named_dubbing

    entry = save_named_dubbing(session_path, name, source_path)
    return {"message": f"已保存配音「{entry['name']}」", "entry": entry}


@stage_errors
def delete_named_session_dubbing(session_path: str, dub_id: str) -> dict:
    from workflow.session import delete_session_dubbing

    return delete_session_dubbing(session_path, dub_id)


@stage_errors
def save_clone_voice(
    name: str,
    audio_path: str,
    source_type: str = "upload",
    prompt_text: str = "",
) -> dict:
    if not audio_path:
        raise ValueError("请先上传参考音频")
    cfg = load_cfg()
    from workflow.deployment import resolve_tts_backend
    from tts.engine import load_presets

    backend = resolve_tts_backend(cfg)
    prompt = (prompt_text or "").strip()
    if not prompt:
        scripts = (load_presets().get("clone") or {}).get("recording_scripts") or {}
        prompt = (scripts.get(backend) or scripts.get("indextts") or "").strip()
    if backend in ("cosyvoice", "qwen3_local") and not prompt:
        raise ValueError(
            f"{'CosyVoice' if backend == 'cosyvoice' else 'Qwen3 本地'} 克隆必须填写参考文案（与参考音频中实际说的内容一致）"
        )
    entry = save_voice(
        name,
        audio_path,
        prompt_text=prompt,
        backend=backend,
        source_type=source_type or "",
    )
    if backend == "qwen3_tts":
        from tts.qwen3_tts import enroll_clone_voice

        qwen_voice = enroll_clone_voice(cfg, entry["reference_wav"], entry["name"])
        entry = update_voice(entry["id"], qwen_voice=qwen_voice)
    refresh_catalog()
    return entry

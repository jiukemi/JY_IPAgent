"""Sync runners for session job queue (publish-related)."""

from __future__ import annotations

import json
import logging
import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from workflow.session import ensure_session_dir

log = logging.getLogger(__name__)

ProgressCb = Callable[[float, str], None]


def _bool(v: Any, default: bool = False) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return bool(v)
    s = str(v).strip().lower()
    if s in ("true", "1", "yes", "on"):
        return True
    if s in ("false", "0", "no", "off", ""):
        return False
    return default


def run_hyperframe_fill_cues(
    payload: dict[str, Any],
    *,
    on_progress: ProgressCb | None = None,
) -> dict[str, Any]:
    from pipeline import ensure_ffmpeg
    from workflow.app_config import load_cfg
    from workflow.hyperframes import generate_cue_scene_assets
    from workflow.pip_assignments_store import mirror_assignments_to_library, merge_pip_assignments
    from workflow.publish import SubCue
    from workflow.scene_style_pack import normalize_style_pack

    def tick(p: float, msg: str) -> None:
        if on_progress:
            on_progress(p, msg)

    session_path = str(payload.get("session_path") or "")
    session = ensure_session_dir(session_path)
    cfg = load_cfg()
    ffmpeg_bin = ensure_ffmpeg((cfg.get("paths") or {}).get("ffmpeg", "ffmpeg"))

    raw_cues = payload.get("cues")
    if isinstance(raw_cues, str):
        raw_cues = json.loads(raw_cues or "[]")
    if not isinstance(raw_cues, list) or not raw_cues:
        raise ValueError("请先加载字幕时间轴")

    skip_raw = payload.get("skip_indices") or []
    target_raw = payload.get("target_indices") or []
    if isinstance(skip_raw, str):
        skip_raw = json.loads(skip_raw or "[]")
    if isinstance(target_raw, str):
        target_raw = json.loads(target_raw or "[]")

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
        if isinstance(c, dict) and c.get("text")
    ]

    pack_raw = payload.get("style_pack") if isinstance(payload.get("style_pack"), dict) else {}
    do_remotion = False  # Remotion is publish burn-in only; never bake into scene cards
    compose_mode = str(payload.get("compose_mode") or "").strip().lower()
    from workflow.hyperframes_scenes import is_fusion_layout

    if compose_mode not in ("fusion", "cover"):
        compose_mode = (
            "fusion"
            if is_fusion_layout(str(payload.get("layout") or ""))
            else "cover"
        )
    merge_meta = payload.get("merge_meta") if isinstance(payload.get("merge_meta"), dict) else {}
    pack = normalize_style_pack(
        {
            "theme": payload.get("theme") or "tokyo_night",
            "layout": payload.get("layout") or "kinetic",
            "aspect": payload.get("aspect") or "portrait_9_16",
            "font_id": payload.get("font_id") or "noto_sc",
            "font_scale": payload.get("font_scale") or "1",
            "bg_mode": payload.get("bg_mode") or "generative",
            "bg_asset": payload.get("bg_asset") or "",
            "bg_prompt": payload.get("bg_prompt") or "",
            "remotion_theme": "off",
            **pack_raw,
        }
    )
    pack["remotion_theme"] = "off"
    pack["compose_mode"] = compose_mode
    pack["smart_keywords"] = _bool(payload.get("smart_keywords"), True)
    pack["smart_layout"] = _bool(
        payload.get("smart_layout"),
        _bool(payload.get("smart_style"), True),
    )
    pack["smart_theme"] = _bool(
        payload.get("smart_theme"),
        _bool(payload.get("smart_style"), True),
    )
    from workflow.hyperframes_scenes import resolve_scene_aspect
    from workflow.publish import resolve_session_video
    from pipeline import ensure_ffmpeg, ffprobe_bin

    probe_bin = ffprobe_bin(ffmpeg_bin)
    session_video = resolve_session_video(session)
    if session_video and session_video.is_file():
        try:
            from workflow.pip_overlay import _video_size

            vw, vh = _video_size(probe_bin, session_video)
            pack["aspect"] = resolve_scene_aspect(
                pack.get("aspect"),
                video_width=vw,
                video_height=vh,
            )
        except (OSError, subprocess.CalledProcessError, ValueError):
            pass
    if compose_mode == "fusion":
        # Fusion must stay black-key transparent — never generative scene bg
        pack["bg_mode"] = "transparent"
        pack["bg_prompt"] = ""
        pack["bg_asset"] = ""
        if not is_fusion_layout(pack["layout"]):
            pack["layout"] = "glass_card"
        # auto → face-aware at burn; store corner for list preview
        pos = str(merge_meta.get("position") or "auto")
        pack["fusion_position"] = "top_right" if pos in ("auto", "fullscreen", "") else pos
        pack["fusion_scale"] = float(merge_meta.get("scale") or 0.42)

    fc = str(payload.get("force_contiguous") or "auto").lower()
    if fc in ("true", "1", "yes", "on"):
        do_force = True
    elif fc in ("false", "0", "no", "off"):
        do_force = False
    else:
        do_force = target is not None

    work = session / "publish" / "pip_cues" / "hf_auto"
    tick(0.05, "开始生成 HyperFrames 场景…")
    want_smart = _bool(payload.get("smart_style"), True)
    # Fusion: keep glass/plain_text; smart may only retint theme inside generator
    assignments = generate_cue_scene_assets(
        cues,
        work,
        theme=pack["theme"],
        layout=pack["layout"],
        aspect=pack["aspect"],
        skip_indices=skip,
        target_indices=target,
        smart_merge=_bool(payload.get("smart_merge"), True),
        force_contiguous=do_force,
        smart_style=want_smart,
        remotion_captions=do_remotion,
        style_pack=pack,
        ffmpeg_bin=ffmpeg_bin,
    )
    if not assignments:
        raise ValueError("未能生成任何场景，请检查所选字幕或文案")

    for a in assignments:
        a["compose_mode"] = compose_mode
        a["content_style"] = pack["layout"]
        if compose_mode == "fusion":
            a["position"] = "fullscreen"
            a["scale"] = 1.0
            a["fusion_anchor"] = str(
                merge_meta.get("position")
                or pack.get("fusion_position")
                or "top_right"
            )
            if a["fusion_anchor"] in ("auto", "fullscreen", ""):
                a["fusion_anchor"] = "top_right"
        else:
            a["position"] = "fullscreen"
            a["scale"] = 1.0

    tick(0.85, "保存场景分配…")
    store_path = merge_pip_assignments(session, assignments)
    library_items: list = []
    if _bool(payload.get("save_to_library"), True):
        library_items = mirror_assignments_to_library(assignments, prefix="智能场景")

    result = {
        "ok": True,
        "assignments": assignments,
        "count": len(assignments),
        "layout": pack["layout"],
        "aspect": pack["aspect"],
        "style_pack": pack,
        "compose_mode": compose_mode,
        "work_dir": str(work.resolve()),
        "assignments_file": str(store_path.resolve()),
        "library_saved": len(library_items),
        "note": "场景文件保留在会话 publish/pip_cues，不会自动删除；已同步到素材中心。",
    }

    chain = payload.get("chain_publish")
    if isinstance(chain, dict) and chain:
        tick(0.9, "场景完成，开始一键成片…")
        # Inject updated pip cues into publish payload
        pub = dict(chain)
        pub.setdefault("session_path", session_path)
        pub["pip_cues"] = [
            {
                "cue_indices": a.get("cue_indices"),
                "start": a.get("start"),
                "end": a.get("end"),
                "media_path": a.get("media_path"),
                "position": a.get("position") or ("top_right" if compose_mode == "fusion" else "fullscreen"),
                "scale": a.get("scale") if a.get("scale") is not None else (0.42 if compose_mode == "fusion" else 1),
                "auto_hyperframe": True,
                "compose_mode": a.get("compose_mode") or compose_mode,
                "content_style": a.get("content_style") or pack["layout"],
                "scene_layout": a.get("scene_layout") or pack["layout"],
                "play_full_video": a.get("play_full_video", True),
                "display_duration_sec": a.get("display_duration_sec"),
            }
            for a in assignments
        ]
        if compose_mode == "fusion":
            pub["pip_mode"] = pub.get("pip_mode") or "timed"
            pub["layout_mode"] = pub.get("layout_mode") or "short"
            pub["hf_text_cards"] = True
        else:
            pub["pip_mode"] = pub.get("pip_mode") or "education_timed"
        pub_result = run_publish_run(pub, on_progress=on_progress)
        result["publish"] = pub_result
    tick(1.0, "完成")
    return result


def run_hyperframe_restyle(
    payload: dict[str, Any],
    *,
    on_progress: ProgressCb | None = None,
) -> dict[str, Any]:
    from pipeline import ensure_ffmpeg
    from workflow.app_config import load_cfg
    from workflow.hyperframes import restyle_cue_scene_assets
    from workflow.pip_assignments_store import mirror_assignments_to_library, merge_pip_assignments
    from workflow.publish import SubCue
    from workflow.scene_style_pack import normalize_style_pack

    def tick(p: float, msg: str) -> None:
        if on_progress:
            on_progress(p, msg)

    session = ensure_session_dir(str(payload.get("session_path") or ""))
    cfg = load_cfg()
    ffmpeg_bin = ensure_ffmpeg((cfg.get("paths") or {}).get("ffmpeg", "ffmpeg"))

    raw_cues = payload.get("cues")
    if isinstance(raw_cues, str):
        raw_cues = json.loads(raw_cues or "[]")
    raw_assignments = payload.get("assignments")
    if isinstance(raw_assignments, str):
        raw_assignments = json.loads(raw_assignments or "[]")
    if not isinstance(raw_cues, list) or not raw_cues:
        raise ValueError("请先加载字幕时间轴")
    if not isinstance(raw_assignments, list) or not raw_assignments:
        raise ValueError("没有可换肤的场景，请先智能生成")

    cues = [
        SubCue(
            int(c.get("index") or i + 1),
            float(c["start"]),
            float(c["end"]),
            str(c.get("text") or "").strip(),
        )
        for i, c in enumerate(raw_cues)
        if isinstance(c, dict) and c.get("text")
    ]
    do_remotion = False
    pack = normalize_style_pack(
        {
            "theme": payload.get("theme") or "tokyo_night",
            "layout": payload.get("layout") or "kinetic",
            "aspect": payload.get("aspect") or "portrait_9_16",
            "font_id": payload.get("font_id") or "noto_sc",
            "font_scale": payload.get("font_scale") or "1",
            "bg_mode": payload.get("bg_mode") or "generative",
            "bg_asset": payload.get("bg_asset") or "",
            "bg_prompt": payload.get("bg_prompt") or "",
            "remotion_theme": "off",
        }
    )
    pack["remotion_theme"] = "off"
    work = session / "publish" / "pip_cues" / "hf_restyle"
    tick(0.1, "换肤重渲中…")
    assignments = restyle_cue_scene_assets(
        cues,
        raw_assignments,
        work,
        style_pack=pack,
        theme=pack["theme"],
        layout=pack["layout"],
        aspect=pack["aspect"],
        remotion_captions=do_remotion,
        smart_style=_bool(payload.get("smart_style"), False),
        ffmpeg_bin=ffmpeg_bin,
    )
    if not assignments:
        raise ValueError("未能换肤任何场景")
    tick(0.9, "保存换肤结果…")
    store_path = merge_pip_assignments(session, assignments)
    library_items: list = []
    if _bool(payload.get("save_to_library"), True):
        library_items = mirror_assignments_to_library(assignments, prefix="换肤场景")
    tick(1.0, "完成")
    return {
        "ok": True,
        "assignments": assignments,
        "count": len(assignments),
        "style_pack": pack,
        "work_dir": str(work.resolve()),
        "assignments_file": str(store_path.resolve()),
        "library_saved": len(library_items),
        "note": "换肤结果已写入会话目录，并同步到素材中心。",
    }


def run_publish_run(
    payload: dict[str, Any],
    *,
    on_progress: ProgressCb | None = None,
) -> dict[str, Any]:
    from api.services.stages import run_publish_stage

    def tick(p: float, msg: str | None = None) -> None:
        if on_progress:
            on_progress(float(p), msg or "")

    session_path = str(payload.get("session_path") or "")
    pip_cues = payload.get("pip_cues") or []
    if isinstance(pip_cues, str):
        pip_cues_json = pip_cues
    else:
        pip_cues_json = json.dumps(pip_cues, ensure_ascii=False)

    cues = payload.get("cues")
    if isinstance(cues, list):
        cues_json = json.dumps(cues, ensure_ascii=False)
    else:
        cues_json = str(cues or "")

    hf_target = payload.get("hyperframes_target_indices")
    if isinstance(hf_target, list):
        hf_target_json = json.dumps(hf_target)
    else:
        hf_target_json = str(hf_target or "")

    lecturer = payload.get("lecturer_crop")
    if isinstance(lecturer, dict):
        lecturer_json = json.dumps(lecturer, ensure_ascii=False)
    else:
        lecturer_json = str(lecturer or "")

    data = run_publish_stage(
        session_path,
        str(payload.get("script") or ""),
        str(payload.get("title") or ""),
        float(payload.get("cover_time") or 0.5),
        str(payload.get("template") or "classic_bottom"),
        str(payload.get("subtitle_style") or "bottom_clean"),
        float(payload.get("subtitle_pause") or 0.35),
        _bool(payload.get("burn_subtitles"), True),
        _bool(payload.get("embed_cover"), True),
        str(payload.get("pip_mode") or "none"),
        payload.get("pip_upload_path"),
        str(payload.get("pip_position") or "bottom_right"),
        float(payload.get("pip_scale") or 0.28),
        int(payload.get("pip_margin") or 24),
        _bool(payload.get("hyperframes_consent"), False),
        str(payload.get("hyperframes_theme") or "tokyo_night"),
        str(payload.get("hyperframes_layout") or "kinetic"),
        str(payload.get("hyperframes_aspect") or payload.get("publish_aspect") or "portrait_9_16"),
        subtitle_font_size=int(payload.get("subtitle_font_size") or 16),
        subtitle_color=str(payload.get("subtitle_color") or "#FFFFFF"),
        subtitle_outline=int(payload.get("subtitle_outline") if payload.get("subtitle_outline") is not None else 1),
        subtitle_shadow=int(payload.get("subtitle_shadow") if payload.get("subtitle_shadow") is not None else 0),
        subtitle_position=str(payload.get("subtitle_position") or "bottom"),
        pip_cues_json=pip_cues_json,
        cues_json=cues_json,
        bgm_id=str(payload.get("bgm_id") or "hook_drop"),
        bgm_volume=float(payload.get("bgm_volume") if payload.get("bgm_volume") is not None else 0.22),
        bgm_start=float(payload.get("bgm_start") or 0),
        enable_bgm=_bool(payload.get("enable_bgm"), True),
        hyperframes_target_indices_json=hf_target_json,
        lecturer_crop_json=lecturer_json,
        on_progress=tick,
        remotion_theme=str(payload.get("remotion_theme") or "off"),
        layout_mode=str(payload.get("layout_mode") or "short"),
        remotion_smart_keywords=_bool(payload.get("remotion_smart_keywords"), True),
        hf_text_cards=_bool(payload.get("hf_text_cards"), False),
        cover_image_path=str(payload.get("cover_image_path") or ""),
        glass_cards_json=(
            json.dumps(payload.get("glass_cards"), ensure_ascii=False)
            if isinstance(payload.get("glass_cards"), list)
            else str(payload.get("glass_cards_json") or "[]")
        ),
        hf_card_position=str(payload.get("hf_card_position") or "auto"),
        hf_card_scale=float(payload.get("hf_card_scale") if payload.get("hf_card_scale") is not None else 0.42),
    )
    return {"ok": True, **data}


def run_tts_synthesize(
    payload: dict[str, Any],
    *,
    on_progress: ProgressCb | None = None,
) -> dict[str, Any]:
    from api.services.stages import run_tts

    def tick(p: float, msg: str | None = None) -> None:
        if on_progress:
            on_progress(p, msg or "")

    backend = (str(payload.get("backend") or "").strip() or None)
    data = run_tts(
        str(payload.get("session_path") or ""),
        str(payload.get("text") or ""),
        str(payload.get("voice_uid") or ""),
        str(payload.get("speed_mode") or "balanced"),
        backend=backend,
        style_extra=str(payload.get("style_extra") or ""),
        on_progress=tick,
    )
    out = {"ok": True, **data}
    if backend:
        out.setdefault("backend", backend)
        out.setdefault("model", backend)
    out.setdefault("speed_mode", str(payload.get("speed_mode") or "balanced"))
    return out


_AVATAR_MODEL_LABELS = {
    "heygem": "HeyGem",
    "sadtalker": "SadTalker",
    "latentsync": "LatentSync",
}


def run_avatar_lipsync(
    payload: dict[str, Any],
    *,
    on_progress: ProgressCb | None = None,
) -> dict[str, Any]:
    from api.services.stages import run_lipsync

    def tick(p: float, msg: str | None = None) -> None:
        if on_progress:
            on_progress(p, msg or "")

    backend = str(payload.get("backend") or "").strip().lower()
    track_mode = str(payload.get("track_mode") or "digital")
    quality = str(payload.get("quality") or "balanced")
    avatar_id = str(payload.get("avatar_id") or "").strip() or None
    data = run_lipsync(
        str(payload.get("session_path") or ""),
        track_mode,
        backend,
        quality,
        avatar_id,
        str(payload.get("audio_path") or "") or None,
        media_file=str(payload.get("media_path") or "") or None,
        ref_pose_file=str(payload.get("ref_pose_path") or "") or None,
        pose_style=float(payload.get("pose_style") or 0),
        still_head=_bool(payload.get("still_head"), False),
        expression_scale=float(payload.get("expression_scale") or 1.0),
        on_progress=tick,
    )
    model = (
        str(payload.get("model_label") or "").strip()
        or _AVATAR_MODEL_LABELS.get(backend, backend or "lipsync")
    )
    return {
        "ok": True,
        **data,
        "backend": backend or data.get("backend"),
        "model": model,
        "quality": quality,
        "track_mode": track_mode,
        "avatar_id": avatar_id,
        "avatar_name": str(payload.get("avatar_name") or "") or None,
    }


def run_script_extract(
    payload: dict[str, Any],
    *,
    on_progress: ProgressCb | None = None,
) -> dict[str, Any]:
    from api.services.stages import script_extract_with_progress

    def tick(p: float, msg: str | None = None) -> None:
        if on_progress:
            on_progress(p, msg or "")

    data = script_extract_with_progress(
        str(payload.get("session_path") or ""),
        str(payload.get("share_url") or ""),
        str(payload.get("ref_media") or "") or None,
        tick,
    )
    return {"ok": True, **data}


def run_subtitle_asr(
    payload: dict[str, Any],
    *,
    on_progress: ProgressCb | None = None,
) -> dict[str, Any]:
    from api.services.stages import extract_publish_subtitles

    def tick(p: float, msg: str) -> None:
        if on_progress:
            on_progress(p, msg)

    tick(0.05, "准备本地 ASR…")
    data = extract_publish_subtitles(
        str(payload.get("session_path") or ""),
        use_video_audio=_bool(payload.get("use_video_audio"), True),
        update_script=_bool(payload.get("update_script"), True),
        subtitle_font_size=int(payload.get("subtitle_font_size") or 16),
        output_aspect=str(payload.get("output_aspect") or "portrait_9_16"),
        subtitle_max_chars=(
            int(payload["subtitle_max_chars"])
            if payload.get("subtitle_max_chars") is not None
            else None
        ),
    )
    tick(1.0, "字幕提取完成")
    return {"ok": True, **data}


def dispatch_job(
    job_type: str,
    payload: dict[str, Any],
    *,
    on_progress: ProgressCb | None = None,
) -> dict[str, Any]:
    if job_type == "hyperframe_fill_cues":
        return run_hyperframe_fill_cues(payload, on_progress=on_progress)
    if job_type == "hyperframe_restyle":
        return run_hyperframe_restyle(payload, on_progress=on_progress)
    if job_type == "publish_run":
        return run_publish_run(payload, on_progress=on_progress)
    if job_type == "tts_synthesize":
        return run_tts_synthesize(payload, on_progress=on_progress)
    if job_type == "avatar_lipsync":
        return run_avatar_lipsync(payload, on_progress=on_progress)
    if job_type == "engine_install":
        return run_engine_install(payload, on_progress=on_progress)
    if job_type == "script_extract":
        return run_script_extract(payload, on_progress=on_progress)
    if job_type == "subtitle_asr":
        return run_subtitle_asr(payload, on_progress=on_progress)
    raise ValueError(f"unsupported job type: {job_type}")


def run_engine_install(
    payload: dict[str, Any],
    *,
    on_progress: ProgressCb | None = None,
) -> dict[str, Any]:
    """Run setup_*.ps1 for a local engine; stream progress via on_progress."""
    import subprocess

    from tts.engine_profiles import ENGINE_PROFILES
    from workflow.app_config import load_cfg
    from workflow.engine_status import check_engine
    from workflow.task_control import register_proc, unregister_proc

    root = Path(__file__).resolve().parents[2]
    setup_dir = root / "scripts" / "setup"
    allowed = {
        eng: spec["setup"]
        for eng, spec in ENGINE_PROFILES.items()
        if spec.get("setup")
    }
    allowed["heygem"] = "setup_heygem.ps1"
    allowed["whisper"] = "setup_whisper.ps1"
    allowed["funasr"] = "setup_funasr.ps1"
    allowed["local_whisper"] = "setup_whisper.ps1"
    allowed["rembg"] = "setup_rembg.ps1"
    allowed["playwright"] = "setup_playwright.ps1"
    allowed["ffmpeg"] = "setup_ffmpeg.ps1"
    optional = {"rembg", "playwright", "ffmpeg"}

    def tick(p: float, msg: str) -> None:
        if on_progress:
            on_progress(p, msg)

    eng = str(payload.get("engine") or "").strip().lower()
    if not eng:
        raise ValueError("缺少 engine")
    script = allowed.get(eng)
    if not script:
        raise ValueError(f"引擎 {eng} 不支持一键安装")

    cfg = load_cfg()
    if eng not in optional:
        st = check_engine(eng if eng != "local_whisper" else "whisper", cfg)
        if not st.get("compatible", True):
            min_v = st.get("min_vram_gb") or 0
            missing = st.get("missing") or []
            why = "；".join(str(m) for m in missing[:3]) if missing else f"本机显存不足（建议 ≥ {min_v:g}GB）"
            raise ValueError(
                f"本机配置不支持「{st.get('label') or eng}」：{why}。请改用云端或 Piper 等轻量引擎。"
            )
    else:
        if eng == "rembg":
            st = {"label": "封面抠图 rembg"}
        elif eng == "playwright":
            st = {"label": "浏览器引擎 Playwright"}
        elif eng == "ffmpeg":
            st = {"label": "FFmpeg"}
        else:
            st = {"label": eng}

    script_path = (setup_dir / script).resolve()
    if not script_path.is_file() or script_path.parent != setup_dir.resolve():
        raise ValueError(f"安装脚本不存在：{script}")

    tick(0.02, f"开始安装 {st.get('label') or eng}…")
    ps_args = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script_path),
    ]
    # Pass writable InstallDir for engines that support it (packaged AppData runtime).
    if eng == "indextts":
        from tts.engine import resolve_indextts_install_dir

        install = resolve_indextts_install_dir(cfg)
        # Prefer runtime engines path when packaging / AGENT_RUNTIME_DIR is set
        rt = (os.environ.get("AGENT_RUNTIME_DIR") or "").strip()
        if rt:
            install = Path(rt).expanduser().resolve() / "engines" / "IndexTTS"
        ps_args.extend(["-Root", str(root), "-InstallDir", str(install)])
        tick(0.03, f"安装目录：{install}")

    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    proc = subprocess.Popen(
        ps_args,
        cwd=str(root),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    register_proc(proc)
    log_lines: list[str] = []
    progress = 0.05
    code: int | None = None
    try:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = (raw or "").rstrip()
            if not line:
                continue
            log_lines.append(line)
            if len(log_lines) > 200:
                log_lines = log_lines[-200:]
            low = line.lower()
            if any(k in low for k in ("download", "下载", "fetch", "pull")):
                progress = max(progress, 0.35)
            elif any(k in low for k in ("install", "pip", "wheel", "解压")):
                progress = max(progress, 0.55)
            elif any(k in low for k in ("complete", "done", "成功", "finished")):
                progress = max(progress, 0.88)
            else:
                progress = min(progress + 0.012, 0.92)
            tick(progress, line[:240])
        code = proc.wait(timeout=30)
    finally:
        unregister_proc(proc)
        try:
            if proc.poll() is None:
                proc.kill()
        except OSError:
            pass

    if code is None:
        code = proc.returncode if proc.returncode is not None else 1
    check_id = "whisper" if eng in ("whisper", "local_whisper") else eng
    st2 = check_engine(check_id, load_cfg())
    tick(1.0, "安装脚本已结束，正在检测状态…")
    if int(code or 0) != 0 and not st2.get("ready"):
        tail = "\n".join(log_lines[-30:])
        raise RuntimeError(f"安装失败（exit={code}）\n{tail}")
    return {
        "ok": bool(st2.get("ready")),
        "engine": check_id,
        "model": st2.get("label") or check_id,
        "ready": bool(st2.get("ready")),
        "missing": list(st2.get("missing") or []),
        "exit_code": int(code or 0),
        "log": "\n".join(log_lines[-80:]),
    }

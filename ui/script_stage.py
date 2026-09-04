"""Stage ①: CDN resolve + transcript + LLM rewrite (local fallback)."""



from __future__ import annotations



import json
import shutil

import traceback

from pathlib import Path



from ui.gradio_compat import gr



from script.cloud import ExtractResult, load_reference_meta
from script.share_link import normalize_share_input

from workflow.deployment import is_cloud
from workflow.providers.script import (

    run_script_extract_file,

    run_script_extract_transcript,

    run_script_extract_url,

    run_script_resolve_cdn,

    run_script_rewrite,

)

from workflow.session import ensure_session_dir





def _preview_path(session: Path, meta: dict | None = None) -> str | None:
    """Page preview prefers a short local clip; full download is for ASR only.

    Never returns a remote CDN URL — UI must only play files under the session.
    Never runs ffmpeg here (snapshot/API must stay fast).
    """
    meta = meta or load_reference_meta(session)
    ui = meta.get("ui_preview") or ""
    if ui and Path(ui).is_file() and not _is_http_url(ui):
        return str(Path(ui).resolve())
    ui_file = session / "reference_ui_preview.mp4"
    if ui_file.is_file():
        return str(ui_file.resolve())
    local = meta.get("local_video") or ""
    if local and not _is_http_url(local) and Path(local).is_file():
        return str(Path(local).resolve())
    full = session / "reference_from_cdn.mp4"
    if full.is_file():
        return str(full.resolve())
    return None


def _is_http_url(value: str) -> bool:
    v = (value or "").strip().lower()
    return v.startswith("http://") or v.startswith("https://")


def session_storage_md(session_dir: str) -> str:
    if not session_dir:
        return ""
    session = Path(session_dir).resolve()
    lines = [
        f"**本会话目录：** `{session}`",
        f"- 对标视频（完整）：`{session / 'reference_from_cdn.mp4'}`",
        f"- 页面预览（可选短片段）：`{session / 'reference_ui_preview.mp4'}`",
        f"- 口播文案：`{session / 'script.txt'}`",
    ]
    return "\n".join(lines)


def _append_storage_log(lines: list[str], session: Path) -> None:
    lines.append(f"会话目录：{session.resolve()}")
    full = session / "reference_from_cdn.mp4"
    if full.is_file():
        size_mb = full.stat().st_size / (1024 * 1024)
        lines.append(f"对标视频：{full} （{size_mb:.0f} MB）")
    ui = session / "reference_ui_preview.mp4"
    if ui.is_file():
        lines.append(f"页面预览：{ui}")


def _format_log(result: ExtractResult, *, phase: str, session: Path | None = None) -> str:

    lines = list(result.pipeline_log or [])

    if not lines:

        lines.append(phase)

    lines.append(f"字数≈{len(result.text or '')}")

    lines.append(f"CDN直链={'有' if result.video_url else '无'}")

    lines.append(f"本地预览={'有' if result.local_video and Path(result.local_video).is_file() else '无'}")
    if session is not None:
        _append_storage_log(lines, session)
    return "\n".join(lines)





def _cdn_md(result: ExtractResult) -> str:

    parts = []

    if result.title:

        parts.append(f"**标题**：{result.title}")

    local = result.local_video or ""
    if local and Path(local).is_file():
        size_mb = Path(local).stat().st_size / (1024 * 1024)
        parts.append(f"**本地缓存（页面只播这个，不连 CDN）**：`{local}`（{size_mb:.1f} MB）")
    ui = result.ui_preview or ""
    if ui and Path(ui).is_file() and ui != local:
        parts.append(f"**轻量预览片段**：`{ui}`")

    if result.video_url:
        parts.append(
            "**CDN 直链（仅解析后下载一次，勿反复打开）**：\n"
            f"`{result.video_url}`"
        )

    if result.cdn_provider:

        parts.append(f"_CDN 引擎：{result.cdn_provider}_")

    if result.transcript_provider:

        parts.append(f"_口播引擎：{result.transcript_provider}_")

    return "\n\n".join(parts)





def load_script_panel(session_dir: str) -> tuple[str, str | None, str, str]:

    if not session_dir:

        return "", None, "", ""

    session = Path(session_dir)

    script_p = session / "script.txt"

    script = script_p.read_text(encoding="utf-8").strip() if script_p.exists() else ""

    meta = load_reference_meta(session)

    share = meta.get("share_url") or ""

    preview = _preview_path(session, meta)

    return script, preview, share, _cdn_md_from_meta(meta)





def _cdn_md_from_meta(meta: dict) -> str:

    if not meta:

        return ""

    return _cdn_md(

        ExtractResult(

            text=meta.get("text") or "",

            video_url=meta.get("video_url") or "",

            title=meta.get("title") or "",

            share_url=meta.get("share_url") or "",

            local_video=meta.get("local_video") or "",

            cdn_provider=meta.get("cdn_provider") or "",

            transcript_provider=meta.get("transcript_provider") or "",

        )

    )





def run_cdn_stage(

    session_dir: str,

    share_url: str,

    cfg: dict,

    progress=gr.Progress(track_tqdm=False),

) -> tuple[str, str | None, str]:

    """Sub-step A only: link → CDN preview (no script.txt change)."""

    if not session_dir:

        raise gr.Error("请先创建或选择会话")

    share_url = normalize_share_input(share_url)
    if not share_url:
        raise gr.Error("请粘贴分享链接，或整段分享文案（会自动识别 v.douyin.com 链接）")

    session = ensure_session_dir(session_dir)

    def on_progress(p: float, msg: str) -> None:
        progress(p, desc=msg)

    try:
        progress(0.05, desc=f"已识别：{share_url[:80]}…")
        result = run_script_resolve_cdn(cfg, share_url, session, on_progress=on_progress)

        preview = (
            result.ui_preview
            if result.ui_preview and Path(result.ui_preview).is_file()
            else (
                result.local_video
                if result.local_video and Path(result.local_video).is_file()
                else None
            )
        )

        log = _format_log(result, phase="[①-A CDN] 解析完成（未改口播文案）", session=session)

        return log, preview, _cdn_md(result)

    except Exception as e:
        raise gr.Error(f"CDN 解析失败: {e}") from e





def run_transcript_stage(
    session_dir: str,
    share_url: str,
    ref_media: str | dict | None,
    cfg: dict,
    progress=gr.Progress(track_tqdm=False),
) -> tuple[str, str, str | None, str]:
    """Sub-step B: uploaded file, CDN cache, or share link → spoken script."""
    if not session_dir:
        raise gr.Error("请先创建或选择会话")

    share_url = normalize_share_input(share_url or "")
    session = ensure_session_dir(session_dir)

    def on_progress(p: float, msg: str) -> None:
        progress(p, desc=msg)

    try:
        meta = load_reference_meta(session)
        has_local = bool(meta.get("local_video") and Path(meta["local_video"]).is_file())

        if not has_local:
            media = ref_media if isinstance(ref_media, str) else (ref_media or {}).get("path")
            if media and Path(media).is_file():
                src = Path(media)
                ext = src.suffix.lower() or ".mp4"
                ref_copy = session / f"reference_media{ext}"
                shutil.copy2(src, ref_copy)
                meta["local_video"] = str(ref_copy.resolve())
                if share_url:
                    meta["share_url"] = share_url
                (session / "reference_meta.json").write_text(
                    json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                has_local = True
                progress(0.1, desc="使用上传的对标视频…")

        if has_local and not share_url:
            progress(0.1, desc="本地 Whisper 转写上传视频…")
            result = run_script_extract_file(
                cfg, Path(meta["local_video"]), session, on_progress=on_progress
            )
        elif share_url:
            progress(0.05, desc=f"口播提取：{share_url[:80]}…")
            result = run_script_extract_transcript(
                cfg, share_url, session, on_progress=on_progress
            )
        else:
            raise gr.Error("请粘贴分享链接，或展开「上传对标视频」上传 mp4")

        (session / "script.txt").write_text(result.text, encoding="utf-8")
        (session / "script_original.txt").write_text(result.text, encoding="utf-8")
        preview = (
            result.ui_preview
            if result.ui_preview and Path(result.ui_preview).is_file()
            else (
                result.local_video
                if result.local_video and Path(result.local_video).is_file()
                else None
            )
        )
        log = _format_log(result, phase="[①-B 口播] 提取完成 → script.txt", session=session)
        return result.text, log, preview, _cdn_md(result)
    except gr.Error:
        raise
    except Exception as e:
        raise gr.Error(f"口播提取失败: {e}") from e


def run_extract_stage(

    session_dir: str,

    share_url: str,

    ref_media: str | dict | None,

    cfg: dict,

    progress=gr.Progress(track_tqdm=False),

) -> tuple[str, str, str | None, str]:

    """Full chain: CDN → transcript (one click)."""

    if not session_dir:

        raise gr.Error("请先创建或选择会话")



    session = ensure_session_dir(session_dir)

    session.mkdir(parents=True, exist_ok=True)

    share_url = (share_url or "").strip()



    def on_progress(p: float, msg: str) -> None:

        progress(p, desc=msg)



    try:

        if share_url:

            result = run_script_extract_url(

                cfg, share_url, session, on_progress=on_progress

            )

        else:

            media = ref_media if isinstance(ref_media, str) else (ref_media or {}).get("path")

            if not media:

                raise gr.Error("请粘贴分享链接（推荐），或在本地上传模式下上传视频")

            src = Path(media)

            ext = src.suffix.lower() or ".mp4"

            ref_copy = session / f"reference_media{ext}"

            shutil.copy2(src, ref_copy)

            result = run_script_extract_file(

                cfg, ref_copy, session, on_progress=on_progress

            )



        (session / "script.txt").write_text(result.text, encoding="utf-8")

        (session / "script_original.txt").write_text(result.text, encoding="utf-8")



        preview = (
            result.ui_preview
            if result.ui_preview and Path(result.ui_preview).is_file()
            else (
                result.local_video
                if result.local_video and Path(result.local_video).is_file()
                else None
            )
        )

        log = _format_log(result, phase="[① 全流程] CDN + 口播 完成", session=session)

        return result.text, log, preview, _cdn_md(result)

    except ValueError as e:

        raise gr.Error(str(e)) from e

    except Exception as e:

        raise gr.Error(f"提取失败: {e}\n\n{traceback.format_exc()}") from e





def run_rewrite_stage(

    session_dir: str,

    text: str,

    intensity: str,

    cfg: dict,

    progress=gr.Progress(track_tqdm=False),

) -> tuple[str, str]:

    if not session_dir:

        raise gr.Error("请先创建或选择会话")

    text = (text or "").strip()

    if not text:

        raise gr.Error("文案为空，请先提取或手写")



    session = ensure_session_dir(session_dir)



    def on_progress(p: float, msg: str) -> None:

        progress(p, desc=msg)



    try:

        out = run_script_rewrite(

            cfg, text, intensity=intensity or "medium", on_progress=on_progress

        )

        (session / "script.txt").write_text(out, encoding="utf-8")

        from script.llm_client import has_llm_key

        if is_cloud(cfg, "script") or has_llm_key(cfg, "rewrite"):
            mode = "LLM（DeepSeek 等）"
        else:
            mode = "本地规则"

        log = f"仿写完成（{mode}）→ script.txt\n字数 {len(text)} → {len(out)}"

        return out, log

    except Exception as e:

        raise gr.Error(f"仿写失败: {e}\n\n{traceback.format_exc()}") from e



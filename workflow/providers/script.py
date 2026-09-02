"""Script step: cloud URL parse + LLM rewrite, or local Whisper fallback."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Callable

from pipeline import ensure_ffmpeg
from script.cloud import (
    ExtractResult,
    extract_from_share_url,
    extract_transcript_for_share,
    resolve_share_cdn,
    rewrite_with_llm,
)
from script.extract import extract_script_from_media
from script.legal import legal_review_with_llm
from script.llm_client import has_llm_key
from script.rewrite import rewrite_script
from workflow.deployment import is_cloud, step_engine

ProgressFn = Callable[[float, str], None]


def _cfg_for_share_extract(cfg: dict) -> dict:
    """Share-link extract is allowed in both modes.

    - Cloud mode: use configured CDN + transcript providers as-is.
    - Local mode: still allow CDN / browser_share to fetch the video, but force
      local ASR (Whisper / FunASR) for the transcript step.
    """
    if is_cloud(cfg, "script"):
        return cfg
    out = deepcopy(cfg)
    engine = step_engine(cfg, "script")
    asr = engine if engine in ("local_whisper", "funasr") else "local_whisper"
    cloud = out.setdefault("script", {}).setdefault("cloud", {})
    tr = cloud.setdefault("transcript", {})
    tr["provider"] = asr
    cdn = cloud.setdefault("cdn", {})
    # Local users often leave CDN key empty; keep browser login as a usable path.
    if not (cdn.get("fallback_provider") or "").strip():
        cdn["fallback_provider"] = "browser_share"
    return out


def run_script_resolve_cdn(
    cfg: dict,
    share_url: str,
    work_dir: Path,
    *,
    on_progress: ProgressFn | None = None,
) -> ExtractResult:
    return resolve_share_cdn(cfg, share_url, work_dir, on_progress=on_progress)


def run_script_extract_transcript(
    cfg: dict,
    share_url: str,
    work_dir: Path,
    *,
    on_progress: ProgressFn | None = None,
) -> ExtractResult:
    from script.cloud import load_reference_meta

    cfg = _cfg_for_share_extract(cfg)
    meta = load_reference_meta(work_dir)
    existing = None
    if meta.get("share_url") == share_url.strip() or meta.get("video_url") or meta.get("local_video"):
        existing = ExtractResult(
            text=meta.get("text") or "",
            video_url=meta.get("video_url") or "",
            title=meta.get("title") or "",
            share_url=meta.get("share_url") or share_url,
            local_video=meta.get("local_video") or "",
            cdn_provider=meta.get("cdn_provider") or "",
            transcript_provider=meta.get("transcript_provider") or "",
            pipeline_log=meta.get("pipeline_log") or [],
        )
    return extract_transcript_for_share(
        cfg, share_url, work_dir, existing=existing, on_progress=on_progress
    )


def run_script_extract_url(
    cfg: dict,
    share_url: str,
    work_dir: Path,
    *,
    on_progress: ProgressFn | None = None,
) -> ExtractResult:
    return extract_from_share_url(
        _cfg_for_share_extract(cfg), share_url, work_dir, on_progress=on_progress
    )


def run_script_extract_file(
    cfg: dict,
    media_path: Path,
    work_dir: Path,
    *,
    on_progress: ProgressFn | None = None,
) -> ExtractResult:
    ffmpeg = ensure_ffmpeg(cfg.get("paths", {}).get("ffmpeg", "ffmpeg"))
    text = extract_script_from_media(
        cfg, media_path, work_dir, ffmpeg, on_progress=on_progress
    )
    return ExtractResult(text=text, local_video=str(media_path.resolve()))


def run_script_rewrite(
    cfg: dict,
    text: str,
    *,
    style: str = "口播",
    intensity: str = "medium",
    on_progress: ProgressFn | None = None,
) -> str:
    if on_progress:
        on_progress(0.05, "仿写准备…")
    use_llm = is_cloud(cfg, "script") or has_llm_key(cfg, "rewrite")
    if use_llm:
        return rewrite_with_llm(
            cfg, text, intensity=intensity, style=style, on_progress=on_progress
        )
    if on_progress:
        on_progress(0.1, "本地规则仿写…")
    result = rewrite_script(text, style=style, intensity=intensity)
    if on_progress:
        on_progress(1.0, "仿写完成")
    return result


def run_script_legal(
    cfg: dict,
    text: str,
    *,
    on_progress: ProgressFn | None = None,
):
    if on_progress:
        on_progress(0.05, "AI法务准备…")
    if not has_llm_key(cfg, "legal") and not has_llm_key(cfg, "rewrite"):
        raise RuntimeError(
            "未配置 LLM API Key。\n"
            "请在 config.yaml → script.cloud.rewrite 或 script.cloud.legal 填写 DeepSeek Key。"
        )
    return legal_review_with_llm(cfg, text, on_progress=on_progress)

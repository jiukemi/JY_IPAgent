"""Pipeline: scrape competitor → knowledge base; generate from saved KB entry."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from script.cloud import extract_from_share_url
from script.competitor_kb import get_competitor, upsert_competitor
from script.hot_generate import analyze_competitor_style, generate_script_from_profile
from script.profile_scrape import scrape_competitor_profile

ProgressFn = Callable[[float, str], None]


def _emit(on_progress: ProgressFn | None, pct: float, desc: str) -> None:
    if on_progress:
        on_progress(pct, desc)


def _collect_samples(
    cfg: dict,
    work: Path,
    videos: list[dict],
    *,
    deep_transcript: bool,
    on_progress: ProgressFn | None,
) -> list[dict]:
    samples: list[dict] = []
    for i, v in enumerate(videos[:4]):
        sample = {
            "url": v.get("url") or "",
            "title": v.get("title") or "",
            "pick": v.get("pick") or "",
            "aweme_id": v.get("aweme_id") or "",
            "script": (v.get("title") or "").strip(),
        }
        if deep_transcript and sample["url"]:
            _emit(
                on_progress,
                0.35 + i * 0.1,
                f"提取对标视频口播 {i + 1}/{min(4, len(videos))}…",
            )
            try:
                sub = work / f"video_{sample['aweme_id'] or i}"
                sub.mkdir(parents=True, exist_ok=True)
                result = extract_from_share_url(cfg, sample["url"], sub, on_progress=None)
                text = (result.text or "").strip()
                if text:
                    sample["script"] = text
                    sample["transcript_ok"] = True
                else:
                    sample["transcript_ok"] = False
            except Exception as exc:
                sample["transcript_ok"] = False
                sample["error"] = str(exc)[:160]
        samples.append(sample)
    return samples


def save_competitor_blogger(
    cfg: dict,
    profile_url: str,
    *,
    work_dir: Path | None = None,
    deep_transcript: bool = True,
    on_progress: ProgressFn | None = None,
) -> dict:
    """Scrape competitor homepage, analyze style, persist to knowledge base."""
    work = Path(work_dir or Path("data/competitors/_tmp"))
    work.mkdir(parents=True, exist_ok=True)

    _emit(on_progress, 0.05, "抓取对标主页…")
    profile = scrape_competitor_profile(
        cfg,
        profile_url,
        on_progress=lambda p, d: _emit(on_progress, 0.05 + p * 0.3, d),
    )
    videos = list(profile.get("videos") or [])
    samples = _collect_samples(
        cfg, work, videos, deep_transcript=deep_transcript, on_progress=on_progress
    )
    if not any((s.get("script") or "").strip() for s in samples):
        # Still save profile with titles if scrape got videos
        if not videos:
            raise RuntimeError("未能解析对标主页视频，无法入库。请确认链接与浏览器登录态。")

    style = {}
    if any((s.get("script") or "").strip() for s in samples):
        _emit(on_progress, 0.78, "提炼对标风格入库…")
        style = analyze_competitor_style(
            cfg,
            nickname=profile.get("nickname") or "",
            signature=profile.get("signature") or "",
            samples=samples,
            on_progress=lambda p, d: _emit(on_progress, 0.78 + p * 0.15, d),
        )

    entry = upsert_competitor(
        {
            "nickname": profile.get("nickname") or "",
            "signature": profile.get("signature") or "",
            "profile_url": profile.get("profile_url") or profile_url,
            "platform": profile.get("platform") or "douyin",
            "videos_found": profile.get("videos_found") or 0,
            "samples": samples,
            "style": style,
            "all_videos": profile.get("all_videos") or [],
        }
    )
    _emit(on_progress, 1.0, f"已保存对标「{entry.get('nickname') or entry['id']}」到知识库")
    return entry


def generate_from_saved_competitor(
    cfg: dict,
    competitor_id: str,
    *,
    roles: list[dict],
    mix_roles: bool = False,
    duration_sec: int = 45,
    hotwords: list[str] | None = None,
    extra: str = "",
    on_progress: ProgressFn | None = None,
) -> dict:
    """Generate exclusive script using a knowledge-base competitor entry."""
    entry = get_competitor(competitor_id)
    if not entry:
        raise ValueError("知识库中未找到该对标博主，请先保存")
    style = entry.get("style") or {}
    samples = entry.get("samples") or []
    if not style and samples:
        _emit(on_progress, 0.2, "补全对标风格分析…")
        style = analyze_competitor_style(
            cfg,
            nickname=entry.get("nickname") or "",
            signature=entry.get("signature") or "",
            samples=samples,
            on_progress=on_progress,
        )
        entry = upsert_competitor({**entry, "style": style})

    gen = generate_script_from_profile(
        cfg,
        roles=roles,
        mix_roles=mix_roles,
        duration_sec=duration_sec,
        hotwords=hotwords or [],
        extra=extra,
        competitor_style=style or {"tone": "对标短视频口播节奏", "structure": "钩子-干货-引导"},
        competitor_meta={
            "nickname": entry.get("nickname") or "",
            "signature": entry.get("signature") or "",
            "profile_url": entry.get("profile_url") or "",
        },
        on_progress=on_progress,
    )
    return {
        **gen,
        "competitor": {
            "id": entry.get("id"),
            "nickname": entry.get("nickname") or "",
            "signature": entry.get("signature") or "",
            "profile_url": entry.get("profile_url") or "",
            "style": style,
            "sample_count": len(samples),
        },
    }


# Backward-compatible alias used by older stage
def competitor_to_exclusive_script(
    cfg: dict,
    session_dir: Path,
    profile_url: str,
    *,
    roles: list[dict],
    mix_roles: bool = False,
    duration_sec: int = 45,
    hotwords: list[str] | None = None,
    extra: str = "",
    deep_transcript: bool = True,
    on_progress: ProgressFn | None = None,
) -> dict:
    entry = save_competitor_blogger(
        cfg,
        profile_url,
        work_dir=Path(session_dir) / "competitor_analysis",
        deep_transcript=deep_transcript,
        on_progress=lambda p, d: _emit(on_progress, p * 0.7, d),
    )
    return generate_from_saved_competitor(
        cfg,
        entry["id"],
        roles=roles,
        mix_roles=mix_roles,
        duration_sec=duration_sec,
        hotwords=hotwords,
        extra=extra,
        on_progress=lambda p, d: _emit(on_progress, 0.7 + p * 0.3, d),
    )

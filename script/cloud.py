"""Cloud script pipeline: CDN resolve (preview) and transcript (ASR) are separate sub-steps."""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from pipeline import ensure_ffmpeg, ffprobe_bin, media_duration
from script.extract import extract_script_from_media
from script.parse_providers import call_cdn_provider, call_transcript_provider
from script.share_link import normalize_share_input

ProgressFn = Callable[[float, str], None]

_DIRECT_VIDEO = re.compile(
    r"^https?://.+\.(mp4|mov|webm|m4v)(\?.*)?$",
    re.I,
)


@dataclass
class ExtractResult:
    text: str
    video_url: str = ""
    title: str = ""
    share_url: str = ""
    local_video: str = ""
    ui_preview: str = ""
    cdn_provider: str = ""
    transcript_provider: str = ""
    pipeline_log: list[str] = field(default_factory=list)


def _cloud_cfg(cfg: dict) -> dict:
    return (cfg.get("script") or {}).get("cloud") or {}


def _rewrite_cfg(cfg: dict) -> dict:
    return _cloud_cfg(cfg).get("rewrite") or {}


def _browser_cfg(cfg: dict) -> dict:
    return _cloud_cfg(cfg).get("browser") or {}


def _emit(on_progress: ProgressFn | None, p: float, msg: str) -> None:
    if on_progress:
        on_progress(p, msg)


def _parse_headers(api_key: str, header_name: str) -> dict:
    if not api_key:
        return {}
    name = (header_name or "Authorization").strip()
    value = api_key if api_key.lower().startswith("bearer ") else f"Bearer {api_key}"
    if name.lower() == "authorization":
        return {name: value}
    return {name: api_key}


def _sub_cfg(cloud: dict, key: str, legacy_provider: str | None = None) -> dict:
    """Read cdn / transcript block with legacy parse_* fallback."""
    block = dict(cloud.get(key) or {})
    legacy_pp = (cloud.get("parse_provider") or os.environ.get("SCRIPT_PARSE_PROVIDER") or "").strip()
    legacy_key = (cloud.get("parse_api_key") or os.environ.get("SCRIPT_PARSE_API_KEY") or "").strip()
    legacy_url = (cloud.get("parse_api_url") or os.environ.get("SCRIPT_PARSE_API_URL") or "").strip()
    legacy_extra = cloud.get("parse_api_extra")
    if not isinstance(legacy_extra, dict):
        legacy_extra = {}

    if not block.get("provider"):
        if legacy_provider:
            block["provider"] = legacy_provider
        elif key == "cdn":
            block["provider"] = legacy_pp or "none"
        else:
            if legacy_pp in (
                "asr_sync_videourl",
                "asr_sync_content",
                "asr_custom_json",
                "asr_async_poll",
                "17zhiling_asr",
                "kuhuyun",
                "local_whisper",
                "funasr",
                "generic",
            ):
                block["provider"] = legacy_pp
            elif legacy_pp in ("cdn_form_key_url", "17zhiling_watermark", "tenapi"):
                block["provider"] = "funasr"
            elif cloud.get("whisper_fallback", True) is not False:
                block["provider"] = "funasr"
            else:
                block["provider"] = "asr_sync_videourl"

    block.setdefault("api_key", legacy_key)
    block.setdefault("api_url", legacy_url)
    if "extra" not in block and legacy_extra:
        block["extra"] = legacy_extra
    if not isinstance(block.get("extra"), dict):
        block["extra"] = {}
    return block


def _cdn_settings(cfg: dict) -> dict:
    return _sub_cfg(_cloud_cfg(cfg), "cdn")


def _transcript_settings(cfg: dict) -> dict:
    return _sub_cfg(_cloud_cfg(cfg), "transcript")


def _request_timeout(cfg: dict) -> float:
    return float(_cloud_cfg(cfg).get("parse_timeout_sec", 120))


def resolve_share_url(share_url: str) -> str:
    share_url = normalize_share_input(share_url)
    if not share_url:
        raise ValueError("请粘贴分享链接或整段分享文案（会自动识别其中的链接）")
    return share_url


def _transcribe_local_video(
    cfg: dict,
    media_path: Path,
    work_dir: Path,
    *,
    on_progress: ProgressFn | None = None,
) -> str:
    ffmpeg = ensure_ffmpeg(cfg.get("paths", {}).get("ffmpeg", "ffmpeg"))
    return extract_script_from_media(cfg, media_path, work_dir, ffmpeg, on_progress=on_progress)


def resolve_share_cdn(
    cfg: dict,
    share_url: str,
    work_dir: Path,
    *,
    download_video: bool = True,
    on_progress: ProgressFn | None = None,
) -> ExtractResult:
    """Sub-step A: share link → CDN URL + optional local preview file."""
    share_url = resolve_share_url(share_url)
    cloud = _cloud_cfg(cfg)
    cdn = _cdn_settings(cfg)
    provider = (cdn.get("provider") or "none").strip().lower()
    used_provider = provider
    logs: list[str] = []

    video_url = ""
    title = ""
    local_video = ""
    ui_preview = ""

    if _DIRECT_VIDEO.match(share_url):
        used_provider = "direct"
        video_url = share_url
        logs.append("[①-A CDN] 直链 mp4，跳过解析接口")
        _emit(on_progress, 0.15, "直链视频…")
    else:
        # Configured provider (+ optional fallback). provider=none still may try fallback
        # (e.g. browser_share) so local mode can fetch videos without a CDN API Key.
        providers: list[str] = []
        if provider and provider != "none":
            providers.append(provider)
        fb_name = (cdn.get("fallback_provider") or "").strip().lower()
        if fb_name and fb_name not in providers and fb_name != "none":
            # browser_share 不依赖 api_key；其它带 Key 的 fallback 才要求已配置
            if fb_name == "browser_share" or (cdn.get("api_key") or "").strip():
                providers.append(fb_name)

        if not providers:
            used_provider = "none"
            logs.append("[①-A CDN] 已跳过（未配置 CDN / 浏览器回退）")
            _emit(on_progress, 0.12, "跳过 CDN 视频提取…")
        else:
            parsed: dict = {}
            last_err: Exception | None = None
            used_provider = providers[0]
            for idx, p in enumerate(providers):
                try:
                    _emit(on_progress, 0.08 + idx * 0.04, f"①-A 解析 CDN（{p}）…")
                    parsed = call_cdn_provider(
                        p,
                        api_url=(cdn.get("api_url") or "").strip() if p == provider else "",
                        api_key=(cdn.get("api_key") or "").strip(),
                        share_url=share_url,
                        extra={**(cdn.get("extra") or {}), "_cfg": cfg},
                        headers=_parse_headers(
                            cdn.get("api_key", ""), cloud.get("parse_api_header", "Authorization")
                        ),
                        timeout=_request_timeout(cfg),
                    )
                    used_provider = p
                    if provider and p != provider and provider != "none":
                        logs.append(f"[①-A CDN] 主接口 {provider} 失败，已切换 {p}")
                    break
                except Exception as exc:
                    last_err = exc
                    logs.append(f"[①-A CDN] {p} 失败: {exc}")
            else:
                last_msg = str(last_err) if last_err else "未知错误"
                raise RuntimeError(
                    f"CDN 视频提取失败（已试: {', '.join(providers)}）\n"
                    f"最后错误: {last_msg}\n\n"
                    "可行方案：\n"
                    "1. 检查设置里 CDN 的 API Key / 接口地址\n"
                    "2. 先「浏览器登录」抖音后再试（browser_share）\n"
                    "3. 上传对标 mp4 后直接提取口播"
                ) from last_err

            video_url = parsed.get("video_url") or ""
            title = parsed.get("title") or ""
            logs.append(f"[①-A CDN] 完成 · {used_provider} · 直链={'有' if video_url else '无'}")

    if video_url and download_video and cloud.get("download_cdn", True) is not False:
        dest = work_dir / "reference_from_cdn.mp4"
        _emit(on_progress, 0.45, "下载对标视频到本地（仅此一次）…")
        try:
            download_cdn_video(video_url, dest, on_progress=on_progress)
        except Exception as exc:
            raise RuntimeError(
                f"CDN 直链已解析，但下载到本地失败（不会边播边拉远程）：{exc}\n"
                "请重试，或改用「上传本地视频」提取。"
            ) from exc
        local_video = str(dest.resolve())
        ui_preview = _maybe_build_ui_preview(cfg, dest, on_progress=on_progress)
        size_mb = dest.stat().st_size / (1024 * 1024)
        try:
            probe = ffprobe_bin(ensure_ffmpeg(cfg.get("paths", {}).get("ffmpeg", "ffmpeg")))
            mins = media_duration(probe, dest) / 60
            logs.append(
                f"[①-A CDN] 已下载到本地 · {size_mb:.0f}MB · 时长≈{mins:.0f}分钟（页面只播本地缓存）"
            )
            if mins >= 10:
                logs.append(
                    "[提示] 视频较长：①-B 本地 Whisper 可能需 20–60 分钟；"
                    "可先确认右侧预览，或改用云端 ASR（config transcript.provider）"
                )
        except Exception:
            logs.append(f"[①-A CDN] 已下载到本地 · {size_mb:.0f}MB（页面只播本地缓存）")
        if ui_preview and ui_preview != local_video:
            logs.append("[①-A CDN] 已生成轻量预览片段供页面播放（完整文件仅用于 ASR）")
    elif video_url and not download_video:
        logs.append("[①-A CDN] 已跳过下载（download_video=false）；页面不会直接播远程 CDN")
    elif video_url and cloud.get("download_cdn", True) is False:
        logs.append("[①-A CDN] download_cdn=false，未落盘；请改为 true，避免反复读远程链接")

    result = ExtractResult(
        text="",
        video_url=video_url,
        title=title,
        share_url=share_url,
        local_video=local_video,
        ui_preview=ui_preview,
        cdn_provider=used_provider,
        pipeline_log=logs,
    )
    _merge_reference_meta(work_dir, result)
    _emit(on_progress, 0.5, "CDN 步骤完成")
    return result


def extract_transcript_for_share(
    cfg: dict,
    share_url: str,
    work_dir: Path,
    *,
    existing: ExtractResult | None = None,
    on_progress: ProgressFn | None = None,
) -> ExtractResult:
    """Sub-step B: share link or downloaded media → spoken script."""
    share_url = resolve_share_url(share_url)
    cloud = _cloud_cfg(cfg)
    tr = _transcript_settings(cfg)
    provider = (tr.get("provider") or "local_whisper").strip().lower()
    logs: list[str] = list((existing.pipeline_log if existing else []) or [])

    video_url = (existing.video_url if existing else "") or ""
    title = (existing.title if existing else "") or ""
    local_video = (existing.local_video if existing else "") or ""
    ui_preview = (existing.ui_preview if existing else "") or ""
    text = (existing.text if existing else "") or ""

    if provider in ("local_whisper", "funasr"):
        media = Path(local_video) if local_video else None
        if not media or not media.is_file():
            if video_url and cloud.get("download_cdn", True) is not False:
                dest = work_dir / "reference_from_cdn.mp4"
                _emit(on_progress, 0.55, f"为 {provider} 下载对标视频…")
                download_cdn_video(video_url, dest, on_progress=on_progress)
                local_video = str(dest.resolve())
                ui_preview = _maybe_build_ui_preview(cfg, dest, on_progress=on_progress)
                media = dest
            elif _DIRECT_VIDEO.match(share_url):
                dest = work_dir / "reference_from_cdn.mp4"
                download_cdn_video(share_url, dest, on_progress=on_progress)
                video_url = share_url
                local_video = str(dest.resolve())
                ui_preview = _maybe_build_ui_preview(cfg, dest, on_progress=on_progress)
                media = dest
        if not media or not media.is_file():
            raise RuntimeError(
                f"本地转写（{provider}）需要对标视频文件。\n"
                "请先执行「①-A 解析 CDN」或确保 cdn 步骤已下载 preview。"
            )
        if local_video and not ui_preview:
            ui_preview = _preview_for_ui(cfg, local_video)
        label = "FunASR" if provider == "funasr" else "本地 Whisper"
        _emit(on_progress, 0.6, f"①-B {label} 转写…")
        text = _transcribe_local_video(cfg, media, work_dir, on_progress=on_progress)
        logs.append(f"[①-B 口播] 完成 · {provider}")
    else:
        from script.parse_providers import ASR_ASYNC_PROTOCOLS, normalize_transcript_provider

        provider_n = normalize_transcript_provider(provider)
        timeout = _request_timeout(cfg)
        if provider_n in ASR_ASYNC_PROTOCOLS:
            timeout = max(
                timeout,
                float(
                    (tr.get("async_timeout_sec") or cloud.get("asr_async_timeout_sec") or 300)
                ),
            )
        _emit(on_progress, 0.55, f"①-B 云端口播提取（{provider_n}）…")
        parsed = call_transcript_provider(
            provider_n,
            api_url=(tr.get("api_url") or "").strip(),
            api_key=(tr.get("api_key") or "").strip(),
            share_url=share_url,
            extra=tr.get("extra") if isinstance(tr.get("extra"), dict) else {},
            headers=_parse_headers(tr.get("api_key", ""), cloud.get("parse_api_header", "Authorization")),
            timeout=timeout,
        )
        text = (parsed.get("text") or "").strip()
        if not video_url:
            video_url = parsed.get("video_url") or ""
        if not title:
            title = parsed.get("title") or ""
        logs.append(f"[①-B 口播] 完成 · {provider} · {len(text)} 字")
        if video_url and not local_video and cloud.get("download_cdn", True) is not False:
            dest = work_dir / "reference_from_cdn.mp4"
            try:
                download_cdn_video(video_url, dest, on_progress=on_progress)
                local_video = str(dest.resolve())
                ui_preview = _maybe_build_ui_preview(cfg, dest, on_progress=on_progress)
                logs.append("[①-A CDN] 从口播接口补下载预览")
            except Exception as exc:
                logs.append(f"[①-A CDN] 补下载跳过: {exc}")

    if not text:
        raise RuntimeError("口播文案为空")

    if local_video and not ui_preview:
        ui_preview = _preview_for_ui(cfg, local_video)

    result = ExtractResult(
        text=text,
        video_url=video_url,
        title=title,
        share_url=share_url,
        local_video=local_video,
        ui_preview=ui_preview,
        cdn_provider=(existing.cdn_provider if existing else "") or "",
        transcript_provider=provider,
        pipeline_log=logs,
    )
    save_reference_meta(work_dir, result)
    _emit(on_progress, 1.0, "口播提取完成")
    return result


def extract_from_share_url(
    cfg: dict,
    share_url: str,
    work_dir: Path,
    *,
    download_video: bool = True,
    on_progress: ProgressFn | None = None,
) -> ExtractResult:
    """Full ① pipeline: CDN resolve then transcript (complementary chain)."""
    cdn_result = resolve_share_cdn(
        cfg, share_url, work_dir, download_video=download_video, on_progress=on_progress
    )
    return extract_transcript_for_share(
        cfg, share_url, work_dir, existing=cdn_result, on_progress=on_progress
    )


def download_cdn_video(
    video_url: str,
    dest: Path,
    *,
    on_progress: ProgressFn | None = None,
    timeout: float = 300.0,
    referer: str = "",
) -> Path:
    """Download CDN once to a local file. UI / ASR must use this path, not the remote URL."""
    if not video_url:
        raise ValueError("无 CDN 地址可下载")
    if video_url.startswith(("http://", "https://")) is False:
        raise ValueError("CDN 地址无效")
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Platform CDNs often require a browser-like UA + Referer; avoid "live browse" of the URL.
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    ref = (referer or "").strip()
    if not ref:
        # Best-effort referer from URL host family
        low = video_url.lower()
        if any(k in low for k in ("douyin", "bytecdn", "365yg", "douyinvod", "tiktok")):
            ref = "https://www.douyin.com/"
        elif any(k in low for k in ("kuaishou", "kwcdn", "gifshow")):
            ref = "https://www.kuaishou.com/"
        elif any(k in low for k in ("xiaohongshu", "xhscdn", "sns-video")):
            ref = "https://www.xiaohongshu.com/"
        elif "bili" in low:
            ref = "https://www.bilibili.com/"
    if ref:
        headers["Referer"] = ref
    req = urllib.request.Request(video_url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        chunk_size = 1024 * 256
        downloaded = 0
        with dest.open("wb") as f:
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if total > 0 and on_progress:
                    frac = downloaded / total
                    _emit(on_progress, 0.45 + 0.25 * frac, "下载对标视频到本地…")
    if dest.stat().st_size < 1024:
        dest.unlink(missing_ok=True)
        raise RuntimeError("CDN 下载失败或文件过小，链接可能已过期")
    return dest


def _maybe_build_ui_preview(
    cfg: dict,
    src: Path,
    *,
    on_progress: ProgressFn | None = None,
    max_bytes: int | None = None,
    clip_sec: int | None = None,
) -> str:
    """Build a short local clip for UI preview. Full file stays for ASR.

    Default clip_sec=90 so the page never scrub-streams a huge mp4 through the API.
    """
    src = src.resolve()
    if not src.is_file():
        return ""
    cloud_cfg = (cfg.get("script") or {}).get("cloud") or {}
    if clip_sec is None:
        # 0 = always use full file (legacy); default 90s light preview for smoothness
        clip_sec = int(cloud_cfg.get("ui_preview_clip_sec", 90))
    if max_bytes is None:
        max_mb = int(cloud_cfg.get("ui_preview_max_mb", 30))
        max_bytes = max_mb * 1024 * 1024
    if clip_sec <= 0:
        return str(src)

    # Prefer a capped local clip whenever clip_sec > 0 (page must not scrub the full download).
    # Keep this OFF the snapshot/API path — only call during CDN download step.
    size = src.stat().st_size
    # Small/short files: serve as-is immediately (no ffmpeg wait).
    if size <= max_bytes:
        try:
            probe = ffprobe_bin(ensure_ffmpeg(cfg.get("paths", {}).get("ffmpeg", "ffmpeg")))
            if media_duration(probe, src) <= float(clip_sec) + 0.5:
                return str(src)
        except Exception:
            return str(src)

    ui = src.parent / "reference_ui_preview.mp4"
    if ui.is_file() and ui.stat().st_mtime >= src.stat().st_mtime:
        return str(ui.resolve())
    ffmpeg = ensure_ffmpeg(cfg.get("paths", {}).get("ffmpeg", "ffmpeg"))
    _emit(on_progress, 0.72, f"生成页面预览片段（约 {clip_sec} 秒）…")
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(src),
        "-t",
        str(clip_sec),
        "-vf",
        "scale=-2:720",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "28",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        str(ui),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return str(ui.resolve()) if ui.is_file() else str(src)


def _preview_for_ui(cfg: dict, local_video: str) -> str:
    if not local_video:
        return ""
    path = Path(local_video)
    if not path.is_file():
        return ""
    ui = path.parent / "reference_ui_preview.mp4"
    if ui.is_file():
        return str(ui.resolve())
    return _maybe_build_ui_preview(cfg, path)


def _merge_reference_meta(session: Path, partial: ExtractResult) -> None:
    prev = load_reference_meta(session)
    merged = {**prev, **{k: v for k, v in asdict(partial).items() if v or k == "text"}}
    if partial.pipeline_log:
        old_log = prev.get("pipeline_log") or []
        if isinstance(old_log, list):
            merged["pipeline_log"] = old_log + [
                line for line in partial.pipeline_log if line not in old_log
            ]
    session.mkdir(parents=True, exist_ok=True)
    (session / "reference_meta.json").write_text(
        json.dumps(merged, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def save_reference_meta(session: Path, result: ExtractResult) -> None:
    session.mkdir(parents=True, exist_ok=True)
    (session / "reference_meta.json").write_text(
        json.dumps(asdict(result), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_reference_meta(session: Path) -> dict:
    p = session / "reference_meta.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def rewrite_with_llm(
    cfg: dict,
    text: str,
    *,
    intensity: str = "medium",
    style: str = "口播",
    on_progress: ProgressFn | None = None,
) -> str:
    from script.llm_client import chat_completion
    from script.prompt_store import format_rewrite_system

    system = format_rewrite_system(style=style, intensity=intensity)
    _emit(on_progress, 0.2, "LLM 仿写中…")
    content = chat_completion(
        cfg,
        block="rewrite",
        system=system,
        user=(
            "请按系统要求改写下面口播文案。"
            "若为轻度润色，也必须明显改写多处表述，禁止几乎原样返回。\n\n"
            f"{text}"
        ),
        temperature=0.75 if (intensity or "").lower() == "light" else 0.7,
        on_progress=on_progress,
    )
    _emit(on_progress, 1.0, "仿写完成")
    return content

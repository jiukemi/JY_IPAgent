"""Resolve share links via logged-in Playwright browser (multi-platform)."""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from script.browser import with_page
from script.platforms import detect_platform, get_platform
from script.share_link import normalize_share_input, parse_channels_link

ProgressFn = Callable[[float, str], None]

# Douyin-specific patterns (kept as optimization, generic fallback below).
_VOD_URL = re.compile(
    r"https://[^\"'\s\\]+(?:douyinvod|365yg|bytecdn|douyinstatic|video/tos)[^\"'\s\\]*",
    re.I,
)
_AWEME_ID = re.compile(r"(?:/video/|modal_id=|item_ids=)(\d{10,})")

# Generic video URL pattern (works across platforms).
_GENERIC_VIDEO_URL = re.compile(
    r"https://[^\"'\s\\]+\.(?:mp4|m3u8|flv|ts)(?:\?[^\"'\s\\]*)?",
    re.I,
)


def _pick_video_url(candidates: list[str], platform_id: str = "") -> str:
    platform = get_platform(platform_id)
    cdn_domains = platform.cdn_domains if platform else []
    for url in candidates:
        if not url:
            continue
        u = url.replace("\\u002F", "/").replace("\\/", "/")
        if "playwm" in u:
            u = u.replace("playwm", "play")
        if not u.startswith("http"):
            continue
        # Prefer platform-specific CDN domains.
        if cdn_domains and any(d in u for d in cdn_domains):
            return u
        # Fallback: any direct video URL.
        if ".mp4" in u or "video/tos" in u or ".m3u8" in u:
            return u
    # Last resort: any HTTP URL from the candidates.
    for url in candidates:
        u = url.replace("\\u002F", "/").replace("\\/", "/")
        if u.startswith("http") and (".mp4" in u or ".m3u8" in u):
            return u
    return ""


def _title_from_html(html: str) -> str:
    m = re.search(r'"desc"\s*:\s*"([^"]{1,500})"', html)
    if not m:
        return ""
    return m.group(1).encode("utf-8").decode("unicode_escape", errors="replace")


def _walk_play_urls(node: Any, out: list[str]) -> None:
    """Recursively collect play_addr.url_list entries from RENDER_DATA JSON."""
    if isinstance(node, dict):
        if isinstance(node.get("play_addr"), dict):
            urls = node["play_addr"].get("url_list") or []
            if isinstance(urls, list):
                out.extend(str(u) for u in urls if isinstance(u, str) and u.startswith("http"))
        for v in node.values():
            _walk_play_urls(v, out)
    elif isinstance(node, list):
        for v in node:
            _walk_play_urls(v, out)


def _urls_from_render_data(html: str) -> list[str]:
    urls: list[str] = []
    m = re.search(r'<script id="RENDER_DATA" type="application/json">([^<]+)</script>', html)
    if not m:
        return urls
    try:
        from urllib.parse import unquote

        payload = json.loads(unquote(m.group(1)))
        _walk_play_urls(payload, urls)
        blob = json.dumps(payload, ensure_ascii=False)
        urls.extend(_VOD_URL.findall(blob))
    except (json.JSONDecodeError, ValueError):
        pass
    return urls


def _get_video_src(page) -> str:
    """Try to get the video element's src attribute (cross-platform)."""
    try:
        v = page.query_selector("video")
        if v:
            src = v.get_attribute("src") or ""
            if src and src.startswith("http"):
                return src
            # Some platforms use <source> inside <video>
            source = v.query_selector("source")
            if source:
                src = source.get_attribute("src") or ""
                if src and src.startswith("http"):
                    return src
    except Exception:
        pass
    return ""


def resolve_share_cdn_browser(
    share_url: str,
    cfg: dict,
    *,
    timeout: float = 60.0,
    on_progress: ProgressFn | None = None,
) -> dict:
    share_url = normalize_share_input(share_url)
    if not share_url:
        raise RuntimeError("浏览器 CDN 需要有效的分享链接")

    platform_id = detect_platform(share_url)
    platform = get_platform(platform_id)
    platform_name = platform.name if platform else platform_id

    if on_progress:
        on_progress(0.1, f"浏览器打开{platform_name}分享页…")

    captured: list[str] = []

    def _run(page) -> dict:
        def on_response(response) -> None:
            url = response.url or ""
            # Capture any video-like URL from network traffic.
            if any(k in url for k in (".mp4", ".m3u8", "video/tos", "play_addr")):
                captured.append(url)
            if platform and any(d in url for d in platform.cdn_domains):
                captured.append(url)

        page.on("response", on_response)
        page.goto(share_url, wait_until="domcontentloaded", timeout=int(timeout * 1000))
        page.wait_for_timeout(2500)

        # Try clicking play to trigger video load.
        play_selectors = platform.play_selectors if platform else ["video"]
        for selector in play_selectors:
            try:
                el = page.query_selector(selector)
                if el:
                    el.click(timeout=2000)
                    page.wait_for_timeout(2500)
                    break
            except Exception:
                continue

        # Method 1: get video element src directly (works for most platforms).
        video_src = _get_video_src(page)

        # Method 2: parse page HTML for video URLs.
        html = page.content()
        urls = list(captured) + _urls_from_render_data(html)
        # Add generic video URLs found in HTML.
        urls.extend(_GENERIC_VIDEO_URL.findall(html))
        if platform_id == "douyin":
            urls.extend(_VOD_URL.findall(html))

        video_url = video_src or _pick_video_url(urls, platform_id)
        title = _title_from_html(html)
        if not title:
            try:
                title = (page.title() or "").strip()
            except Exception:
                title = ""

        # Douyin fallback: try the video page directly.
        if not video_url and platform_id == "douyin":
            aweme = _AWEME_ID.search(page.url) or _AWEME_ID.search(share_url)
            if aweme:
                page.goto(
                    f"https://www.douyin.com/video/{aweme.group(1)}",
                    wait_until="domcontentloaded",
                    timeout=int(timeout * 1000),
                )
                page.wait_for_timeout(3000)
                try:
                    v = page.query_selector("video")
                    if v:
                        v.click(timeout=2000)
                        page.wait_for_timeout(2500)
                except Exception:
                    pass
                video_src = _get_video_src(page)
                html2 = page.content()
                urls2 = list(captured) + _urls_from_render_data(html2) + _VOD_URL.findall(html2)
                video_url = video_src or _pick_video_url(urls2, platform_id)
                if not title:
                    title = _title_from_html(html2)

        if not video_url and platform_id == "channels":
            meta = parse_channels_link(share_url)
            sph = meta.get("sph_id")
            if sph and "channels.weixin.qq.com" not in page.url:
                try:
                    page.goto(
                        f"https://channels.weixin.qq.com/platform/post/{sph}",
                        wait_until="domcontentloaded",
                        timeout=int(timeout * 1000),
                    )
                    page.wait_for_timeout(3500)
                    video_src = _get_video_src(page) or video_src
                    html3 = page.content()
                    urls3 = list(captured) + _GENERIC_VIDEO_URL.findall(html3)
                    video_url = video_src or _pick_video_url(urls3, platform_id)
                    if not title:
                        title = (page.title() or "").strip()
                except Exception:
                    pass

        if not video_url:
            raise RuntimeError(
                f"{platform_name}浏览器未能解析视频直链（可能未登录或触发风控）。"
                f"请先点击「浏览器登录」完成{platform_name}登录后重试。"
            )
        return {"video_url": video_url, "text": "", "title": title}

    result = with_page(cfg, _run, headless=bool(cfg.get("_browser_headless", True)), platform_id=platform_id)
    if on_progress:
        on_progress(0.9, f"{platform_name}浏览器 CDN 解析完成")
    return result

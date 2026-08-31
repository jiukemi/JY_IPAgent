"""Local CDN resolve: short link → aweme_id → video URL (no API key).

Best-effort only — Douyin may block without cookies; commercial API remains more stable.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_AWEME_ID = re.compile(r"(?:/video/|modal_id=|item_ids=)(\d{10,})")
_VOD_URL = re.compile(r"https://[^\"'\s\\]+(?:douyinvod|365yg|douyinstatic)[^\"'\s\\]*", re.I)


def _open(url: str, *, timeout: float, headers: dict | None = None) -> tuple[str, bytes]:
    hdrs = {"User-Agent": _UA}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.geturl(), resp.read()


def _aweme_id_from_share(share_url: str, timeout: float) -> str:
    final_url, _ = _open(share_url, timeout=timeout)
    m = _AWEME_ID.search(final_url)
    if m:
        return m.group(1)
    m = _AWEME_ID.search(share_url)
    if m:
        return m.group(1)
    raise RuntimeError(f"无法从链接解析视频 ID: {final_url[:120]}")


def _play_url_from_iteminfo(aweme_id: str, timeout: float) -> tuple[str, str]:
    api = f"https://www.iesdouyin.com/web/api/v2/aweme/iteminfo/?item_ids={aweme_id}"
    _, body = _open(api, timeout=timeout, headers={"Referer": "https://www.douyin.com/"})
    data = json.loads(body.decode("utf-8", errors="replace"))
    items = data.get("item_list") or []
    if not items:
        return "", ""
    item = items[0]
    title = str(item.get("desc") or "").strip()
    urls = (item.get("video") or {}).get("play_addr", {}).get("url_list") or []
    video_url = urls[0] if urls else ""
    if video_url and "playwm" in video_url:
        video_url = video_url.replace("playwm", "play")
    return video_url, title


def _play_url_from_page(aweme_id: str, timeout: float) -> tuple[str, str]:
    page = f"https://www.douyin.com/video/{aweme_id}"
    _, body = _open(page, timeout=timeout, headers={"Referer": "https://www.douyin.com/"})
    html = body.decode("utf-8", errors="replace")
    title = ""
    m = re.search(r'"desc"\s*:\s*"([^"]{1,500})"', html)
    if m:
        title = m.group(1).encode("utf-8").decode("unicode_escape", errors="replace")
    urls = _VOD_URL.findall(html)
    video_url = urls[0] if urls else ""
    if video_url and "playwm" in video_url:
        video_url = video_url.replace("playwm", "play")
    return video_url, title


def resolve_share_cdn_local(share_url: str, *, timeout: float = 30.0) -> dict:
    """No API key. Returns video_url + title or raises."""
    share_url = (share_url or "").strip()
    if not share_url.startswith("http"):
        raise RuntimeError("本地 CDN 解析需要 http(s) 分享链接")

    aweme_id = _aweme_id_from_share(share_url, timeout)
    video_url, title = _play_url_from_iteminfo(aweme_id, timeout)
    if not video_url:
        video_url, title2 = _play_url_from_page(aweme_id, timeout)
        title = title or title2
    if not video_url:
        raise RuntimeError(
            "本地解析未能拿到视频直链（抖音接口可能已风控）。\n"
            "请：① 在 config.yaml 填写 cdn.api_key；或 ② 运行方式改「本地」并上传 mp4。"
        )
    return {
        "video_url": video_url,
        "text": "",
        "title": title,
        "_provider": "local_share",
        "aweme_id": aweme_id,
    }

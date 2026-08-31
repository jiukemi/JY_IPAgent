"""Extract share URL from pasted platform copy text."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlparse

# Common short-link patterns (paste whole share message is OK)
_SHARE_PATTERNS = [
    re.compile(r"https?://v\.douyin\.com/[A-Za-z0-9\-_]+/?", re.I),
    re.compile(r"https?://www\.douyin\.com/video/\d+", re.I),
    re.compile(r"https?://v\.kuaishou\.com/[A-Za-z0-9\-_]+/?", re.I),
    re.compile(r"https?://www\.kuaishou\.com/short-video/[A-Za-z0-9]+", re.I),
    re.compile(r"https?://www\.xiaohongshu\.com/[^\s\u4e00-\u9fff\"']+", re.I),
    re.compile(r"https?://xhslink\.com/[^\s\u4e00-\u9fff\"']+", re.I),
    re.compile(r"https?://www\.bilibili\.com/video/[A-Za-z0-9]+", re.I),
    re.compile(r"https?://b23\.tv/[A-Za-z0-9]+", re.I),
    # 微信视频号（channels / finder / sph 短链）
    re.compile(r"https?://channels\.weixin\.qq\.com/[^\s\u4e00-\u9fff\"']+", re.I),
    re.compile(r"https?://finder\.video\.qq\.com/[^\s\u4e00-\u9fff\"']+", re.I),
    re.compile(
        r"https?://weixin\.qq\.com/sph/[A-Za-z0-9]+(?:\?[^\s\u4e00-\u9fff\"']*)?",
        re.I,
    ),
    re.compile(r"https?://weixin\.qq\.com/[^\s\u4e00-\u9fff\"']+", re.I),
    re.compile(r"https?://[^\s\u4e00-\u9fff]+\.(mp4|mov|webm|m4v)(\?[^\s]*)?", re.I),
]

_SPH_ID_RE = re.compile(r"/sph/([A-Za-z0-9]+)", re.I)
_FINDER_ID_RE = re.compile(r"(?:v2_[0-9a-fA-F]{20,}@finder|sph[0-9A-Za-z]{6,})")


def normalize_share_input(text: str) -> str:
    """Return bare share URL from full paste or trimmed input."""
    raw = (text or "").strip()
    if not raw:
        return ""
    if raw.startswith("http") and " " not in raw and "\n" not in raw:
        return raw.rstrip(".,;，。；)")
    for pat in _SHARE_PATTERNS:
        m = pat.search(raw)
        if m:
            return m.group(0).rstrip(".,;，。；)")
    return raw


def parse_channels_link(url: str) -> dict[str, Any]:
    """Extract 视频号 identifiers from a normalized share URL (best-effort)."""
    u = (url or "").strip()
    sph_m = _SPH_ID_RE.search(u)
    qs = parse_qs(urlparse(u).query)
    feed_id = (qs.get("feedId") or qs.get("feedid") or [None])[0]
    object_id = (qs.get("objectId") or qs.get("objectid") or [None])[0]
    finder_m = _FINDER_ID_RE.search(u)
    return {
        "platform": "channels",
        "sph_id": sph_m.group(1) if sph_m else None,
        "feed_id": feed_id or object_id,
        "finder_id": finder_m.group(0) if finder_m else None,
    }


def is_channels_share(url: str) -> bool:
    u = (url or "").lower()
    return any(
        k in u
        for k in (
            "channels.weixin.qq.com",
            "finder.video.qq.com",
            "weixin.qq.com/sph/",
        )
    )

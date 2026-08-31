"""Multi-platform registry for browser login + CDN extraction.

Each platform defines: login URL, cookie-based user data dir, CDN video URL
patterns, and page-level extraction selectors. The generic <video> element
approach works as a cross-platform fallback.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class PlatformConfig:
    id: str
    name: str
    login_url: str
    user_data_subdir: str
    # Domains that appear in CDN video URLs for this platform.
    cdn_domains: list[str] = field(default_factory=list)
    # Selectors to click to trigger video load (platform-specific player).
    play_selectors: list[str] = field(default_factory=lambda: ["video"])
    # Cookie names that indicate logged-in state.
    login_cookies: set[str] = field(default_factory=set)
    # Regex to extract video ID from share URL (for fallback CDN API).
    video_id_re: re.Pattern | None = None
    # Creator upload / publish page for auto-post.
    creator_upload_url: str = ""


_PLATFORMS: dict[str, PlatformConfig] = {
    "douyin": PlatformConfig(
        id="douyin",
        name="抖音",
        login_url="https://www.douyin.com/",
        user_data_subdir="data/browser/douyin",
        cdn_domains=["douyinvod", "365yg", "bytecdn", "douyinstatic", "video/tos"],
        play_selectors=[
            "xg-startinner",
            "xg-poster",
            '[data-e2e="feed-active-video"]',
            "video",
            ".xgplayer-play-btn",
        ],
        login_cookies={"sessionid", "sessionid_ss", "sid_guard", "uid_tt", "uid_tt_ss"},
        video_id_re=re.compile(r"(?:/video/|modal_id=|item_ids=)(\d{10,})"),
        creator_upload_url="https://creator.douyin.com/creator-micro/content/upload",
    ),
    "kuaishou": PlatformConfig(
        id="kuaishou",
        name="快手",
        login_url="https://www.kuaishou.com/",
        user_data_subdir="data/browser/kuaishou",
        cdn_domains=["kwaixsdomains", "yx_cb", "kwcdn", "gifshow", "kuaishou", "txvod"],
        play_selectors=["video", ".video-play", "[data-e2e='video-play']", ".player-block"],
        login_cookies={"userId", "passToken", "kuaishou.server.web_st", "_did"},
        video_id_re=re.compile(r"/short-video/([A-Za-z0-9_-]+)"),
        creator_upload_url="https://cp.kuaishou.com/article/publish/video",
    ),
    "xiaohongshu": PlatformConfig(
        id="xiaohongshu",
        name="小红书",
        login_url="https://www.xiaohongshu.com/",
        user_data_subdir="data/browser/xiaohongshu",
        cdn_domains=["sns-video", "xhscdn", "xiaohongshu", "aliyuncs"],
        play_selectors=["video", ".play-btn", ".media-container"],
        login_cookies={"web_session", "customerClientId", "xhs_CID", "a1"},
        video_id_re=re.compile(r"/explore/([A-Za-z0-9]+)"),
        creator_upload_url="https://creator.xiaohongshu.com/publish/publish",
    ),
    "bilibili": PlatformConfig(
        id="bilibili",
        name="B站",
        login_url="https://www.bilibili.com/",
        user_data_subdir="data/browser/bilibili",
        cdn_domains=["bilivideo", "biliplayer", "akamaized", "mcdn", "cn-ecloud", "upos-sz"],
        play_selectors=["video", ".bpx-player-cover", ".squirtle-video", ".bilibili-player"],
        login_cookies={"SESSDATA", "DedeUserID", "bili_jct", "SESSDATA"},
        video_id_re=re.compile(r"/video/(BV[A-Za-z0-9]+)"),
        creator_upload_url="https://member.bilibili.com/platform/upload/video/frame",
    ),
    "channels": PlatformConfig(
        id="channels",
        name="视频号",
        login_url="https://channels.weixin.qq.com/",
        user_data_subdir="data/browser/channels",
        cdn_domains=[
            "finder.video.qq.com",
            "findermp.video.qq.com",
            "video.weixin.qq.com",
            "wxapp.tc.qq.com",
            "stodownload",
            "finder",
        ],
        play_selectors=[
            "video",
            ".video-player",
            ".player-video",
            "[class*='video']",
            ".play-btn",
        ],
        login_cookies={
            "wxuin",
            "wxtoken",
            "webwx_data_ticket",
            "passport",
            "mm_lang",
        },
        video_id_re=re.compile(r"/sph/([A-Za-z0-9]+)"),
        creator_upload_url="https://channels.weixin.qq.com/platform/post/create",
    ),
}

# URL patterns → platform id, for auto-detection from share links.
_URL_DETECT = [
    (re.compile(r"(?:v\.douyin\.com|www\.douyin\.com|iesdouyin)", re.I), "douyin"),
    (re.compile(r"(?:v\.kuaishou\.com|www\.kuaishou\.com)", re.I), "kuaishou"),
    (re.compile(r"(?:xiaohongshu\.com|xhslink\.com)", re.I), "xiaohongshu"),
    (re.compile(r"(?:bilibili\.com|b23\.tv)", re.I), "bilibili"),
    (
        re.compile(
            r"(?:channels\.weixin\.qq\.com|finder\.video\.qq\.com|weixin\.qq\.com/sph/)",
            re.I,
        ),
        "channels",
    ),
]


def list_platforms() -> list[dict]:
    return [
        {
            "id": p.id,
            "name": p.name,
            "login_url": p.login_url,
            "creator_upload_url": p.creator_upload_url,
        }
        for p in _PLATFORMS.values()
    ]


def get_platform(platform_id: str) -> PlatformConfig | None:
    return _PLATFORMS.get(platform_id)


def detect_platform(share_url: str) -> str:
    """Auto-detect platform from a share URL; defaults to douyin."""
    for pat, pid in _URL_DETECT:
        if pat.search(share_url or ""):
            return pid
    return "douyin"

"""Scrape competitor Douyin (etc.) profile: bio + pinned + latest videos."""

from __future__ import annotations

import json
import re
from typing import Any, Callable
from urllib.parse import unquote

from script.browser import check_login_status, with_page
from script.platforms import detect_platform
from script.share_link import normalize_share_input

ProgressFn = Callable[[float, str], None]

_USER_URL = re.compile(
    r"https?://(?:www\.)?douyin\.com/user/[A-Za-z0-9_\-=]+|https?://v\.douyin\.com/[A-Za-z0-9\-_]+/?",
    re.I,
)
_VIDEO_PATH = re.compile(r"/video/(\d{10,})")


def normalize_profile_url(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    m = _USER_URL.search(raw)
    if m:
        return m.group(0).rstrip(".,;，。；)/")
    # Accept full paste containing user link
    for pat in (
        re.compile(r"https?://www\.douyin\.com/user/[^\s\u4e00-\u9fff]+", re.I),
        re.compile(r"https?://v\.douyin\.com/[A-Za-z0-9\-_]+/?", re.I),
    ):
        m2 = pat.search(raw)
        if m2:
            return m2.group(0).rstrip(".,;，。；)/")
    u = normalize_share_input(raw)
    return u


def _walk_awemes(node: Any, out: list[dict]) -> None:
    if isinstance(node, dict):
        aweme_id = node.get("aweme_id") or node.get("awemeId")
        desc = node.get("desc") or node.get("caption") or ""
        if aweme_id and isinstance(aweme_id, (str, int)):
            aid = str(aweme_id)
            is_top = bool(
                node.get("is_top")
                or node.get("isTop")
                or node.get("stick")
                or (isinstance(node.get("status"), dict) and node["status"].get("is_prohibited") is False and node.get("is_top"))
            )
            # Douyin sometimes uses mark: bit flags / is_top in nested
            if node.get("is_top") in (1, "1", True):
                is_top = True
            create_time = node.get("create_time") or node.get("createTime") or 0
            try:
                create_time = int(create_time)
            except (TypeError, ValueError):
                create_time = 0
            out.append(
                {
                    "aweme_id": aid,
                    "title": str(desc)[:200],
                    "url": f"https://www.douyin.com/video/{aid}",
                    "is_pinned": is_top,
                    "create_time": create_time,
                }
            )
        for v in node.values():
            _walk_awemes(v, out)
    elif isinstance(node, list):
        for v in node:
            _walk_awemes(v, out)


def _user_from_node(node: Any) -> dict:
    info = {"nickname": "", "signature": "", "uid": "", "sec_uid": ""}
    if not isinstance(node, dict):
        return info

    def take(u: dict) -> None:
        if not isinstance(u, dict):
            return
        nick = u.get("nickname") or u.get("nickName") or ""
        sig = u.get("signature") or u.get("desc") or ""
        if nick and not info["nickname"]:
            info["nickname"] = str(nick)[:80]
        if sig and not info["signature"]:
            info["signature"] = str(sig)[:300]
        uid = u.get("uid") or u.get("user_id") or ""
        if uid and not info["uid"]:
            info["uid"] = str(uid)
        sec = u.get("sec_uid") or u.get("secUid") or ""
        if sec and not info["sec_uid"]:
            info["sec_uid"] = str(sec)

    if "user" in node and isinstance(node["user"], dict):
        take(node["user"])
    if "userInfo" in node:
        ui = node["userInfo"]
        if isinstance(ui, dict):
            take(ui.get("user") or ui)
    take(node)
    for v in node.values():
        if isinstance(v, (dict, list)):
            nested = _user_from_node(v) if isinstance(v, dict) else {}
            if nested.get("nickname") and not info["nickname"]:
                info["nickname"] = nested["nickname"]
            if nested.get("signature") and not info["signature"]:
                info["signature"] = nested["signature"]
    return info


def _dedupe_videos(items: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for it in items:
        aid = it.get("aweme_id") or ""
        if not aid or aid in seen:
            continue
        seen.add(aid)
        out.append(it)
    return out


def _select_pinned_and_latest(videos: list[dict], *, pinned: int = 2, latest: int = 3) -> list[dict]:
    videos = _dedupe_videos(videos)
    tops = [v for v in videos if v.get("is_pinned")]
    rest = [v for v in videos if not v.get("is_pinned")]
    rest.sort(key=lambda x: int(x.get("create_time") or 0), reverse=True)
    # If no pin flag, treat first items as latest only
    if not tops and rest:
        # Heuristic: first 1–2 on homepage often include pins; mark none, just take latest
        pass
    picked: list[dict] = []
    for v in tops[: max(0, pinned)]:
        picked.append({**v, "pick": "pinned"})
    for v in rest:
        if len([p for p in picked if p.get("pick") == "latest"]) >= latest:
            break
        if any(p["aweme_id"] == v["aweme_id"] for p in picked):
            continue
        picked.append({**v, "pick": "latest"})
    return picked


def scrape_competitor_profile(
    cfg: dict,
    profile_url: str,
    *,
    on_progress: ProgressFn | None = None,
) -> dict:
    """Open competitor homepage with logged-in browser; return bio + video list."""
    url = normalize_profile_url(profile_url)
    if not url:
        raise ValueError("请粘贴对标账号主页链接（抖音用户主页）")

    platform_id = detect_platform(url) or "douyin"
    st = check_login_status(cfg, platform_id)
    if not st.get("logged_in"):
        raise RuntimeError(
            f"浏览器未登录{st.get('platform_name') or platform_id}。"
            "请先在 ① 文案页点击「浏览器登录」后再分析对标主页。"
        )

    def _emit(p: float, d: str) -> None:
        if on_progress:
            on_progress(p, d)

    collected: list[dict] = []
    user_info = {"nickname": "", "signature": "", "uid": "", "sec_uid": ""}
    final_url = url

    def _run(page) -> dict:
        nonlocal final_url, user_info

        def on_response(response) -> None:
            try:
                u = response.url or ""
                if "aweme" not in u and "user" not in u:
                    return
                if response.status != 200:
                    return
                ctype = (response.headers or {}).get("content-type", "")
                if "json" not in ctype and "javascript" not in ctype:
                    # still try
                    pass
                data = response.json()
            except Exception:
                return
            _walk_awemes(data, collected)
            ui = _user_from_node(data)
            if ui.get("nickname"):
                user_info["nickname"] = user_info["nickname"] or ui["nickname"]
            if ui.get("signature"):
                user_info["signature"] = user_info["signature"] or ui["signature"]

        page.on("response", on_response)
        _emit(0.15, "打开对标主页…")
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4500)
        # scroll to load more posts
        for _ in range(3):
            page.mouse.wheel(0, 2400)
            page.wait_for_timeout(1200)
        final_url = page.url or url
        html = page.content() or ""

        # RENDER_DATA
        m = re.search(r'<script id="RENDER_DATA" type="application/json">([^<]+)</script>', html)
        if m:
            try:
                payload = json.loads(unquote(m.group(1)))
                _walk_awemes(payload, collected)
                ui = _user_from_node(payload)
                if ui.get("nickname"):
                    user_info["nickname"] = user_info["nickname"] or ui["nickname"]
                if ui.get("signature"):
                    user_info["signature"] = user_info["signature"] or ui["signature"]
            except (json.JSONDecodeError, ValueError):
                pass

        # DOM fallback: video links
        try:
            hrefs = page.eval_on_selector_all(
                "a[href*='/video/']",
                "els => els.map(e => e.href)",
            )
        except Exception:
            hrefs = []
        for href in hrefs or []:
            mm = _VIDEO_PATH.search(href or "")
            if not mm:
                continue
            aid = mm.group(1)
            collected.append(
                {
                    "aweme_id": aid,
                    "title": "",
                    "url": f"https://www.douyin.com/video/{aid}",
                    "is_pinned": False,
                    "create_time": 0,
                }
            )

        # Nickname from title
        try:
            title = page.title() or ""
            if "的抖音" in title and not user_info["nickname"]:
                user_info["nickname"] = title.split("的抖音")[0].strip()[:40]
        except Exception:
            pass

        videos = _dedupe_videos(collected)
        picked = _select_pinned_and_latest(videos, pinned=2, latest=3)
        return {
            "profile_url": final_url,
            "platform": platform_id,
            "nickname": user_info.get("nickname") or "",
            "signature": user_info.get("signature") or "",
            "videos_found": len(videos),
            "videos": picked,
            "all_videos": videos[:20],
        }

    _emit(0.1, "使用登录浏览器抓取对标主页…")
    result = with_page(cfg, _run, headless=True, platform_id=platform_id)
    if not result.get("videos"):
        raise RuntimeError(
            "未能从对标主页解析到视频列表。请确认链接是用户主页、已登录抖音，"
            "且账号主页对登录态可见；也可改用单条视频分享链接提取口播。"
        )
    _emit(1.0, f"已抓到 {result.get('videos_found', 0)} 条，选用 {len(result['videos'])} 条分析")
    return result

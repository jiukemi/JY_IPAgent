"""Multi-platform auto publish: sequential creator upload with login gate."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from script.browser import check_login_status, with_page
from script.platforms import get_platform, list_platforms

ProgressFn = Callable[[float, str], None]


class NeedLoginError(RuntimeError):
    def __init__(self, platform_id: str, platform_name: str):
        self.platform_id = platform_id
        self.platform_name = platform_name
        super().__init__(f"浏览器未登录{platform_name}，请先登录")


def _emit(fn: ProgressFn | None, p: float, d: str) -> None:
    if fn:
        fn(p, d)


def _normalize_platforms(platforms: list[str] | None) -> list[str]:
    raw = [str(p).strip().lower() for p in (platforms or []) if str(p).strip()]
    if not raw:
        raw = ["douyin"]
    seen: set[str] = set()
    out: list[str] = []
    for pid in raw:
        if pid in seen:
            continue
        if get_platform(pid) is None:
            continue
        seen.add(pid)
        out.append(pid)
    return out or ["douyin"]


def _build_caption(title: str, description: str, topics: list[str] | None) -> tuple[str, list[str], str]:
    tags = [t.strip().lstrip("#") for t in (topics or []) if str(t).strip()]
    caption = (description or title or "").strip()
    if tags:
        caption = (caption + "\n" + " ".join(f"#{t}" for t in tags)).strip()
    return (title or "")[:40], tags, caption


def _fill_publish_fields(
    page,
    *,
    platform_id: str,
    title_s: str,
    caption: str,
) -> tuple[bool, bool]:
    """Fill creator title + description. Returns (title_ok, desc_ok)."""
    title_ok = False
    desc_ok = False
    title_s = (title_s or "").strip()
    caption = (caption or "").strip()

    # Douyin: dedicated title input; description is a separate contenteditable.
    if platform_id == "douyin":
        try:
            page.wait_for_selector(
                'input[placeholder*="标题"], input[placeholder*="作品"], [contenteditable="true"]',
                timeout=12000,
            )
        except Exception:
            pass
        page.wait_for_timeout(800)

        for sel in (
            'input[placeholder*="作品标题"]',
            'input[placeholder*="标题"]',
            'input[placeholder*="添加标题"]',
            'div[data-e2e="video_title"] input',
            '.semi-input input[type="text"]',
            'input[type="text"][maxlength="30"]',
            'input[type="text"][maxlength="55"]',
        ):
            try:
                loc = page.locator(sel).first
                if loc.count() == 0:
                    continue
                if not loc.is_visible(timeout=800):
                    continue
                loc.click(timeout=1500)
                page.keyboard.press("Control+A")
                page.keyboard.press("Backspace")
                # Douyin title soft-limit ~30 Chinese chars
                page.keyboard.type((title_s or caption)[:30], delay=18)
                title_ok = True
                break
            except Exception:
                continue

        for sel in (
            '[contenteditable="true"]',
            "textarea",
            'div[role="textbox"]',
        ):
            try:
                boxes = page.locator(sel)
                n = min(boxes.count(), 3)
                for i in range(n):
                    el = boxes.nth(i)
                    try:
                        if not el.is_visible(timeout=600):
                            continue
                        el.click(timeout=1500)
                        page.keyboard.press("Control+A")
                        page.keyboard.type(caption[:500] or title_s, delay=10)
                        desc_ok = True
                        break
                    except Exception:
                        continue
                if desc_ok:
                    break
            except Exception:
                continue
        return title_ok, desc_ok

    # Generic platforms: first editable = caption, second = title when present
    for sel in (
        '[contenteditable="true"]',
        "textarea",
        'div[role="textbox"]',
        'input[type="text"]',
    ):
        try:
            boxes = page.locator(sel)
            n = min(boxes.count(), 4)
            for i in range(n):
                el = boxes.nth(i)
                try:
                    el.click(timeout=1500)
                    page.keyboard.press("Control+A")
                    text = caption[:500] if i == 0 else title_s
                    page.keyboard.type(text or title_s, delay=12)
                    if i == 0:
                        desc_ok = True
                    else:
                        title_ok = True
                except Exception:
                    continue
            if desc_ok:
                break
        except Exception:
            continue
    if title_s and not title_ok:
        # Try explicit title placeholders
        for sel in (
            'input[placeholder*="标题"]',
            'input[placeholder*="title" i]',
            'textarea[placeholder*="标题"]',
        ):
            try:
                loc = page.locator(sel).first
                if loc.count() == 0:
                    continue
                loc.click(timeout=1500)
                page.keyboard.press("Control+A")
                page.keyboard.type(title_s[:40], delay=12)
                title_ok = True
                break
            except Exception:
                continue
    return title_ok, desc_ok


def auto_publish_one(
    cfg: dict,
    platform_id: str,
    *,
    video_path: str,
    title: str,
    description: str = "",
    topics: list[str] | None = None,
    on_progress: ProgressFn | None = None,
) -> dict:
    """Publish to one platform. Raises NeedLoginError if not logged in."""
    platform = get_platform(platform_id)
    if platform is None:
        raise ValueError(f"未知平台：{platform_id}")
    if not (platform.creator_upload_url or "").strip():
        raise ValueError(f"{platform.name} 暂未配置创作者上传页")

    video = Path(video_path)
    if not video.is_file():
        raise FileNotFoundError(f"成片不存在：{video}")

    st = check_login_status(cfg, platform_id)
    if not st.get("logged_in"):
        raise NeedLoginError(platform_id, platform.name)

    title_s, tags, caption = _build_caption(title, description, topics)
    meta = {
        "platform": platform_id,
        "platform_name": platform.name,
        "title": title_s,
        "description": caption,
        "topics": tags,
        "video": str(video.resolve()),
    }
    upload_url = platform.creator_upload_url

    def _run(page) -> dict:
        _emit(on_progress, 0.15, f"打开{platform.name}创作者上传页…")
        page.goto(upload_url, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(2800)

        _emit(on_progress, 0.4, f"[{platform.name}] 选择成片…")
        attached = False
        for sel in (
            'input[type="file"][accept*="video"]',
            'input[type="file"][accept*="mp4"]',
            'input[type="file"]',
        ):
            try:
                loc = page.locator(sel).first
                if loc.count() > 0:
                    loc.set_input_files(str(video.resolve()))
                    attached = True
                    break
            except Exception:
                continue

        page.wait_for_timeout(4500)
        _emit(on_progress, 0.65, f"[{platform.name}] 填写标题与文案…")
        title_ok, desc_ok = _fill_publish_fields(
            page,
            platform_id=platform_id,
            title_s=title_s,
            caption=caption,
        )
        filled = title_ok or desc_ok

        _emit(on_progress, 0.9, f"[{platform.name}] 请在浏览器中确认并点击发布…")
        page.wait_for_timeout(800)
        fill_note = []
        if title_ok:
            fill_note.append("标题已填")
        elif title_s:
            fill_note.append("标题未自动填入，请手动补")
        if desc_ok:
            fill_note.append("文案已填")
        return {
            "ok": True,
            "platform": platform_id,
            "platform_name": platform.name,
            "attached": attached,
            "filled": filled,
            "title_filled": title_ok,
            "desc_filled": desc_ok,
            "message": (
                f"已打开{platform.name}创作者中心"
                + ("并选中成片" if attached else "（未自动选到文件，请手动上传）")
                + ("，" + "、".join(fill_note) if fill_note else "")
                + "。请在浏览器中核对并点击发布；完成后关闭该浏览器窗口以继续下一平台。"
            ),
            "meta": meta,
        }

    _emit(on_progress, 0.05, f"使用已登录浏览器发布到{platform.name}…")
    # Keep browser open until user closes it — otherwise Playwright closes
    # right after fill and they never get to click「发布」.
    result = with_page(
        cfg,
        _run,
        headless=False,
        platform_id=platform_id,
        wait_close_after=True,
    )
    return result


def auto_publish_sequence(
    cfg: dict,
    platforms: list[str],
    *,
    video_path: str,
    title: str,
    description: str = "",
    topics: list[str] | None = None,
    on_progress: ProgressFn | None = None,
) -> dict:
    """Publish to platforms in order. Stops on first NeedLoginError and returns remaining."""
    order = _normalize_platforms(platforms)
    results: list[dict] = []
    total = len(order)

    for i, pid in enumerate(order):
        plat = get_platform(pid)
        name = plat.name if plat else pid
        base = i / max(total, 1)
        span = 1 / max(total, 1)

        def _tick(p: float, d: str, _base=base, _span=span) -> None:
            _emit(on_progress, _base + p * _span * 0.95, d)

        _emit(on_progress, base, f"按序发布 {i + 1}/{total}：{name}")
        try:
            one = auto_publish_one(
                cfg,
                pid,
                video_path=video_path,
                title=title,
                description=description,
                topics=topics,
                on_progress=_tick,
            )
            results.append(one)
        except NeedLoginError as exc:
            remaining = order[i:]
            return {
                "ok": False,
                "need_login": True,
                "platform": exc.platform_id,
                "platform_name": exc.platform_name,
                "remaining": remaining,
                "completed": [r.get("platform") for r in results],
                "results": results,
                "message": f"未登录{exc.platform_name}。请先登录，登录后将按顺序继续发布剩余平台。",
            }

    # Persist last meta
    try:
        video = Path(video_path)
        out = video.parent / "publish_meta.json"
        out.write_text(
            json.dumps(
                {
                    "platforms": order,
                    "title": title,
                    "description": description,
                    "topics": topics or [],
                    "results": results,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError:
        pass

    name_parts: list[str] = []
    for r in results:
        plat = get_platform(str(r.get("platform") or ""))
        name_parts.append(plat.name if plat else str(r.get("platform") or "?"))
    names = " → ".join(name_parts)
    _emit(on_progress, 1.0, f"已按序处理：{names}")
    return {
        "ok": True,
        "need_login": False,
        "platforms": order,
        "results": results,
        "message": (
            f"已按序打开发布页（{len(results)} 个平台）。"
            "请在各窗口确认发布；每完成一个请关闭该浏览器窗口再继续。"
        ),
    }


# Backward-compatible alias
def auto_publish_douyin(
    cfg: dict,
    *,
    video_path: str,
    title: str,
    description: str = "",
    topics: list[str] | None = None,
    on_progress: ProgressFn | None = None,
) -> dict:
    return auto_publish_sequence(
        cfg,
        ["douyin"],
        video_path=video_path,
        title=title,
        description=description,
        topics=topics,
        on_progress=on_progress,
    )


def supported_publish_platforms() -> list[dict]:
    return list_platforms()

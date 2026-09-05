"""Playwright persistent browser profile — multi-platform login + anti-bot CDN.

Supports: 抖音 / 快手 / 小红书 / B站. Platform is auto-detected from the share
URL or selected explicitly. Each platform uses its own persistent user data dir
(so cookies don't collide).
"""

from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

from script.platforms import PlatformConfig, detect_platform, get_platform

ROOT = Path(__file__).resolve().parent.parent

_login_lock = threading.Lock()
_login_running = False
_login_started_at: float = 0.0
_login_platform: str = ""
_login_last_error: str = ""
_login_last_result: dict[str, Any] | None = None
_login_cancel = threading.Event()
_login_ctx_holder: list[Any] = []  # mutable box for live Playwright context
_LOGIN_STALE_SECONDS = 600.0
# Persistent profile is exclusive — while extract/CDN holds it, status checks must not
# launch another Chrome or the UI falsely shows「登录掉了」.
_profile_busy = threading.Lock()
_profile_busy_held = False
_profile_busy_platform: str = ""
_profile_busy_reason: str = ""
_profile_busy_since: float = 0.0


def playwright_available() -> bool:
    try:
        import playwright  # noqa: F401

        return True
    except ImportError:
        return False


def _require_playwright() -> None:
    if not playwright_available():
        raise RuntimeError(
            "未安装 Playwright。请运行：\n"
            "  py -3.11 -m pip install playwright\n"
            "  py -3.11 -m playwright install chromium"
        )


def browser_cfg(cfg: dict) -> dict:
    return dict(((cfg.get("script") or {}).get("cloud") or {}).get("browser") or {})


def user_data_dir(cfg: dict, platform_id: str = "") -> Path:
    """Return the persistent profile dir for the given platform.

    Packaged apps prefer AGENT_RUNTIME_DIR (writable) over install ROOT.
    """
    if platform_id:
        p = get_platform(platform_id)
        subdir = p.user_data_subdir if p else f"data/browser/{platform_id}"
    else:
        raw = browser_cfg(cfg).get("user_data_dir") or "data/browser/douyin"
        subdir = raw
    path = Path(subdir)
    if not path.is_absolute():
        rt = (os.environ.get("AGENT_RUNTIME_DIR") or "").strip()
        path = (Path(rt) / path) if rt else (ROOT / path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cleanup_stale_locks(user_dir: Path) -> None:
    """Remove Chromium singleton lock files left by crashed/killed processes."""
    if not user_dir.is_dir():
        return
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        f = user_dir / name
        try:
            if f.exists() or f.is_symlink():
                f.unlink(missing_ok=True)
        except OSError:
            pass


def _launch_kwargs(cfg: dict, *, headless: bool) -> dict:
    b = browser_cfg(cfg)
    # Prefer system Chrome when available: Playwright 自带 Chromium 打开抖音常白屏/被风控。
    channel = (b.get("channel") or "").strip()
    if not channel:
        channel = "chrome"
    kw: dict = {
        "headless": headless,
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process",
        ],
        "ignore_default_args": ["--enable-automation"],
        "viewport": {"width": 1280, "height": 900},
        "locale": "zh-CN",
        "timezone_id": "Asia/Shanghai",
        "channel": channel,
    }
    return kw


def _page_looks_blank(page) -> bool:
    try:
        html = page.content() or ""
    except Exception:
        return True
    text = html.strip()
    if len(text) < 400:
        return True
    low = text.lower()
    if "douyin" in low or "kuaishou" in low or "xiaohongshu" in low or "bilibili" in low:
        return False
    # SPA shell with almost no body content
    return "<body" in low and len(text) < 1200


def _mark_profile_busy(platform_id: str, reason: str) -> None:
    global _profile_busy_held, _profile_busy_platform, _profile_busy_reason, _profile_busy_since
    _profile_busy_held = True
    _profile_busy_platform = platform_id or "douyin"
    _profile_busy_reason = reason
    _profile_busy_since = time.time()


def _release_profile_busy() -> None:
    global _profile_busy_held, _profile_busy_platform, _profile_busy_reason, _profile_busy_since
    if not _profile_busy_held:
        return
    _profile_busy_held = False
    _profile_busy_platform = ""
    _profile_busy_reason = ""
    _profile_busy_since = 0.0
    try:
        _profile_busy.release()
    except RuntimeError:
        pass


def _request_cancel_login() -> None:
    """Signal headed login to close and drop any held Playwright context."""
    _login_cancel.set()
    for ctx in list(_login_ctx_holder):
        try:
            ctx.close()
        except Exception:
            pass
    _login_ctx_holder.clear()


def steal_login_profile_lock(*, wait_seconds: float = 12.0) -> bool:
    """Cancel headed login so extract/CDN can take the persistent profile.

    Returns True if the profile lock is free afterward.
    """
    if not _profile_busy.locked():
        return True
    reason = _profile_busy_reason or ""
    if reason not in ("login",):
        return False
    _request_cancel_login()
    with _login_lock:
        running = _login_running
    if not running:
        # Orphan login hold (thread died / flag cleared) — drop in-process lock.
        _release_profile_busy()
        return True
    deadline = time.time() + max(1.0, wait_seconds)
    while time.time() < deadline:
        if not _profile_busy.locked():
            return True
        with _login_lock:
            still = _login_running
        if not still and _profile_busy_reason == "login":
            _release_profile_busy()
            return True
        time.sleep(0.2)
    # Last resort: drop in-process login lock so CDN can proceed.
    if _profile_busy_reason == "login":
        _release_profile_busy()
        return True
    return not _profile_busy.locked()


@contextmanager
def persistent_context(
    cfg: dict, *, headless: bool = True, platform_id: str = ""
) -> Iterator:
    """Yield Playwright persistent Chromium context (saved cookies)."""
    _require_playwright()
    from playwright.sync_api import sync_playwright

    user_dir = user_data_dir(cfg, platform_id)
    got_busy = _profile_busy.acquire(blocking=False)
    if not got_busy and _profile_busy_reason == "login":
        # Extract/CDN wins over a stuck headed login window.
        if steal_login_profile_lock(wait_seconds=12.0):
            got_busy = _profile_busy.acquire(blocking=False)
    if not got_busy:
        raise RuntimeError(
            f"浏览器资料夹正被占用（{_profile_busy_reason or '其它任务'}）。"
            "请关闭「浏览器登录」窗口后重试提取；或点「强制重开」结束卡住的登录。"
        )
    _mark_profile_busy(platform_id or "douyin", "headless" if headless else "headed")
    _cleanup_stale_locks(user_dir)
    try:
        with sync_playwright() as pw:
            kw = _launch_kwargs(cfg, headless=headless)
            try:
                ctx = pw.chromium.launch_persistent_context(str(user_dir), **kw)
            except Exception as first_exc:
                # channel=chrome 找不到时回退到 Playwright Chromium
                if kw.get("channel"):
                    kw = dict(kw)
                    kw.pop("channel", None)
                    try:
                        ctx = pw.chromium.launch_persistent_context(str(user_dir), **kw)
                    except Exception:
                        raise first_exc from None
                else:
                    raise
            try:
                yield ctx
            finally:
                try:
                    ctx.close()
                except Exception:
                    pass
    finally:
        _release_profile_busy()


def profile_busy_status(platform_id: str = "") -> dict | None:
    """If profile is in use, return a non-destructive status (do not flip logged_in=false)."""
    if _profile_busy.locked():
        pid = platform_id or _profile_busy_platform or "douyin"
        platform = get_platform(pid)
        return {
            "ready": True,
            "logged_in": True,
            "deferred": True,
            "message": "浏览器正用于提取/CDN，登录态检测已暂缓（不是掉登录）",
            "profile_dir": "",
            "platform": pid,
            "platform_name": platform.name if platform else pid,
            "cookie_count": -1,
        }
    return None


def _detect_login_from_cookies(ctx, platform: PlatformConfig) -> tuple[bool, int]:
    """Read login state from the given context's cookies (no new launch)."""
    try:
        cookies = ctx.cookies()
    except Exception:
        return False, 0
    names = {c.get("name", "") for c in cookies}
    logged_in = bool(names & platform.login_cookies) if platform.login_cookies else len(cookies) > 5
    return logged_in, len(cookies)


def login_progress_snapshot(platform_id: str = "") -> dict:
    """Non-destructive flags for UI polling (no browser launch)."""
    with _login_lock:
        running = _login_running
        err = _login_last_error
        result = dict(_login_last_result) if _login_last_result else None
        plat = _login_platform or platform_id or "douyin"
    out: dict[str, Any] = {
        "login_running": running,
        "login_error": err or "",
        "login_platform": plat,
    }
    if result and not running:
        out["login_result"] = result
    return out


def check_login_status(cfg: dict, platform_id: str = "") -> dict:
    """Best-effort: read saved cookies (prefer no navigation); optionally open homepage."""
    platform_id = platform_id or "douyin"
    progress = login_progress_snapshot(platform_id)
    # While headed login holds the profile, do not launch a second Chrome.
    if progress.get("login_running") or (_profile_busy.locked() and _profile_busy_reason == "login"):
        return {
            "ready": True,
            "logged_in": False,
            "deferred": True,
            "message": "登录窗口打开中，请在浏览器里完成登录后关闭窗口",
            "profile_dir": str(user_data_dir(cfg, platform_id)),
            "platform": platform_id,
            "platform_name": (get_platform(platform_id).name if get_platform(platform_id) else platform_id),
            "cookie_count": -1,
            **progress,
        }
    busy = profile_busy_status(platform_id)
    if busy:
        busy["profile_dir"] = str(user_data_dir(cfg, platform_id))
        busy.update(progress)
        return busy
    platform = get_platform(platform_id)
    if not platform:
        return {"ready": False, "logged_in": False, "message": f"未知平台: {platform_id}", **progress}
    if not playwright_available():
        return {
            "ready": False,
            "logged_in": False,
            "message": "Playwright 未安装",
            "profile_dir": str(user_data_dir(cfg, platform_id)),
            "platform": platform_id,
            "platform_name": platform.name,
            **progress,
        }
    try:
        with persistent_context(cfg, headless=True, platform_id=platform_id) as ctx:
            # Cookie-only first — 避免再开首页白屏/风控把检测打挂
            logged_in, n = _detect_login_from_cookies(ctx, platform)
            if logged_in:
                return {
                    "ready": True,
                    "logged_in": True,
                    "message": "已检测到登录态",
                    "profile_dir": str(user_data_dir(cfg, platform_id)),
                    "platform": platform_id,
                    "platform_name": platform.name,
                    "cookie_count": n,
                    **progress,
                }
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                page.goto(platform.login_url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(2000)
            except Exception as exc:
                logged_in, n = _detect_login_from_cookies(ctx, platform)
                hint = "访问失败（403 通常是开了梯子/VPN，请关闭后重试）"
                return {
                    "ready": False,
                    "logged_in": logged_in,
                    "message": f"{hint}：{str(exc)[:120]}",
                    "profile_dir": str(user_data_dir(cfg, platform_id)),
                    "platform": platform_id,
                    "platform_name": platform.name,
                    "cookie_count": n,
                    **progress,
                }
            logged_in, n = _detect_login_from_cookies(ctx, platform)
            msg = "已检测到登录态" if logged_in else "未登录或登录已过期，请点击「浏览器登录」（需用本机 Chrome，勿开梯子）"
            return {
                "ready": True,
                "logged_in": logged_in,
                "message": msg,
                "profile_dir": str(user_data_dir(cfg, platform_id)),
                "platform": platform_id,
                "platform_name": platform.name,
                "cookie_count": n,
                **progress,
            }
    except Exception as exc:
        err = str(exc)
        if "资料夹正被占用" in err or "SingletonLock" in err or "process_singleton" in err.lower():
            busy = profile_busy_status(platform_id) or {
                "ready": True,
                "logged_in": True,
                "deferred": True,
                "message": "浏览器正用于提取，登录态检测已暂缓（不是掉登录）",
                "profile_dir": str(user_data_dir(cfg, platform_id)),
                "platform": platform_id,
                "platform_name": platform.name if platform else platform_id,
                "cookie_count": -1,
            }
            busy["profile_dir"] = str(user_data_dir(cfg, platform_id))
            busy.update(progress)
            return busy
        if "Executable doesn't exist" in err or "chrome" in err.lower() and "channel" in err.lower():
            err = (
                f"{err}\n未找到本机 Google Chrome。请安装 Chrome，或在 config.yaml 里把 "
                "script.cloud.browser.channel 改成空后执行：py -3.11 -m playwright install chromium"
            )
        return {
            "ready": False,
            "logged_in": False,
            "message": err,
            "profile_dir": str(user_data_dir(cfg, platform_id)),
            "platform": platform_id,
            "platform_name": platform.name,
            **progress,
        }


def open_login_browser(cfg: dict, *, wait_close: bool = True, platform_id: str = "") -> dict:
    """Open headed browser for manual platform login; cookies persist in profile."""
    _require_playwright()
    from playwright.sync_api import sync_playwright

    platform_id = platform_id or "douyin"
    platform = get_platform(platform_id)
    if not platform:
        raise RuntimeError(f"未知平台: {platform_id}")

    if not _profile_busy.acquire(blocking=False):
        # If extract holds it, fail; if orphan login, steal ourselves.
        if _profile_busy_reason == "login":
            steal_login_profile_lock(wait_seconds=5.0)
            if not _profile_busy.acquire(blocking=False):
                raise RuntimeError(
                    f"浏览器资料夹正被占用（{_profile_busy_reason or '提取/CDN'}）。"
                    "请等当前任务结束后再登录。"
                )
        else:
            raise RuntimeError(
                f"浏览器资料夹正被占用（{_profile_busy_reason or '提取/CDN'}）。"
                "请等当前任务结束后再登录。"
            )
    _mark_profile_busy(platform_id, "login")
    user_dir = user_data_dir(cfg, platform_id)
    _cleanup_stale_locks(user_dir)
    closed = threading.Event()

    try:
        with sync_playwright() as pw:
            kw = _launch_kwargs(cfg, headless=False)
            try:
                ctx = pw.chromium.launch_persistent_context(str(user_dir), **kw)
            except Exception as first_exc:
                if kw.get("channel"):
                    kw = dict(kw)
                    kw.pop("channel", None)
                    try:
                        ctx = pw.chromium.launch_persistent_context(str(user_dir), **kw)
                    except Exception:
                        raise first_exc from None
                else:
                    raise

            def _signal_close(*_a, **_kw) -> None:
                closed.set()

            try:
                ctx.on("close", _signal_close)
            except Exception:
                pass
            try:
                browser = ctx.browser
                if browser is not None:
                    browser.on("disconnected", _signal_close)
            except Exception:
                pass

            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            _login_ctx_holder.clear()
            _login_ctx_holder.append(ctx)

            def _check_empty(*_a, **_kw) -> None:
                try:
                    if len(ctx.pages) == 0:
                        closed.set()
                except Exception:
                    closed.set()

            try:
                page.on("close", _check_empty)
                ctx.on("page", lambda p: p.on("close", _check_empty))
            except Exception:
                pass

            def _show_manual_hint(reason: str) -> None:
                hint = "403/白屏通常是：1) 开了梯子/VPN  2) 没用本机 Chrome  3) 被风控。请关闭 VPN 后在地址栏手动打开下方链接登录。"
                alt = platform.creator_upload_url or platform.login_url
                html = (
                    "<body style='font-family:system-ui;padding:40px;color:#333;line-height:1.6'>"
                    f"<h2>加载{platform.name}失败或白屏</h2>"
                    f"<p>请在地址栏打开：</p>"
                    f"<p><b>{platform.login_url}</b></p>"
                    f"<p>或创作者入口：<b>{alt}</b></p>"
                    f"<p style='color:#c00'>{hint}</p>"
                    f"<pre style='background:#f4f4f4;padding:12px;border-radius:8px;"
                    f"white-space:pre-wrap'>{reason[:400]}</pre>"
                    "<p>登录成功后<strong>关闭本窗口</strong>，回到软件点刷新状态。</p>"
                    "</body>"
                )
                try:
                    page.set_content(html)
                except Exception:
                    pass

            try:
                page.goto(platform.login_url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(1500)
                if _page_looks_blank(page):
                    alt = (platform.creator_upload_url or "").strip()
                    if alt and alt.rstrip("/") != platform.login_url.rstrip("/"):
                        try:
                            page.goto(alt, wait_until="domcontentloaded", timeout=60000)
                            page.wait_for_timeout(1500)
                        except Exception as exc2:
                            _show_manual_hint(str(exc2))
                    if _page_looks_blank(page):
                        _show_manual_hint("页面内容几乎为空（白屏）。请手动在地址栏输入链接登录。")
            except Exception as exc:
                _show_manual_hint(str(exc))

            if wait_close:
                # Cap wait so a stuck Chrome window cannot block CDN forever.
                deadline = time.time() + _LOGIN_STALE_SECONDS
                while not closed.is_set():
                    if _login_cancel.is_set() or time.time() >= deadline:
                        closed.set()
                        break
                    if closed.wait(timeout=1.0):
                        break
                    try:
                        pages = ctx.pages
                        if not pages:
                            closed.set()
                            break
                        browser = ctx.browser
                        if browser is not None and not browser.is_connected():
                            closed.set()
                            break
                    except Exception:
                        closed.set()
                        break

            logged_in, cookie_count = _detect_login_from_cookies(ctx, platform)
            try:
                ctx.close()
            except Exception:
                pass

            msg = "已登录，Cookie 已保存" if logged_in else "未检测到登录态，可重新点击「浏览器登录」"
            return {
                "ok": True,
                "logged_in": logged_in,
                "message": msg,
                "profile_dir": str(user_dir),
                "platform": platform_id,
                "platform_name": platform.name,
                "cookie_count": cookie_count,
            }
    finally:
        _login_ctx_holder.clear()
        _release_profile_busy()


def _is_login_stale() -> bool:
    """True if the running guard has been held past the stale timeout."""
    return bool(_login_started_at and (time.time() - _login_started_at) > _LOGIN_STALE_SECONDS)


def start_login_async(cfg: dict, *, force: bool = False, platform_id: str = "") -> dict:
    """Non-blocking login window (background thread).

    `force=True` kills any stuck previous attempt and relaunches.
    """
    global _login_running, _login_started_at, _login_platform, _login_last_error, _login_last_result
    platform_id = platform_id or "douyin"
    platform = get_platform(platform_id)

    with _login_lock:
        if _login_running and not force and not _is_login_stale():
            return {
                "ok": False,
                "message": "登录窗口已在打开中；如窗口未出现或已关掉，请再点「强制重开」",
                "login_running": True,
            }
        need_cancel = _login_running and (force or _is_login_stale())

    if need_cancel:
        _request_cancel_login()
        # Wait for previous login thread to release the profile lock.
        for _ in range(40):
            with _login_lock:
                still = _login_running
            if not still and not _profile_busy.locked():
                break
            time.sleep(0.25)

    with _login_lock:
        _login_running = True
        _login_started_at = time.time()
        _login_platform = platform_id
        _login_last_error = ""
        _login_last_result = None
        _login_cancel.clear()

    def _run() -> None:
        global _login_running, _login_last_error, _login_last_result
        try:
            result = open_login_browser(cfg, wait_close=True, platform_id=platform_id)
            with _login_lock:
                _login_last_result = result
                _login_last_error = ""
        except Exception as exc:
            err = str(exc)
            with _login_lock:
                _login_last_error = err
                _login_last_result = {
                    "ok": False,
                    "logged_in": False,
                    "message": err,
                    "platform": platform_id,
                }
        finally:
            with _login_lock:
                _login_running = False
                _login_started_at = 0.0
                _login_platform = ""

    threading.Thread(target=_run, daemon=True).start()
    return {
        "ok": True,
        "message": (
            f"正在打开{platform.name if platform else platform_id}浏览器，请在窗口中登录；"
            "完成后关闭浏览器窗口，软件会自动刷新登录状态"
        ),
        "profile_dir": str(user_data_dir(cfg, platform_id)),
        "platform": platform_id,
        "platform_name": platform.name if platform else platform_id,
        "login_running": True,
    }


def with_page(
    cfg: dict,
    fn: Callable,
    *,
    headless: bool = True,
    platform_id: str = "",
    wait_close_after: bool = False,
):
    """Run fn(page) inside persistent context.

    wait_close_after=True: after fn returns, keep the headed browser open until
    the user closes it (needed for auto-publish confirmation).
    """
    import threading

    with persistent_context(cfg, headless=headless, platform_id=platform_id) as ctx:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        result = fn(page)
        if wait_close_after and not headless:
            closed = threading.Event()

            def _signal(*_a, **_kw) -> None:
                closed.set()

            try:
                ctx.on("close", _signal)
            except Exception:
                pass
            try:
                browser = ctx.browser
                if browser is not None:
                    browser.on("disconnected", _signal)
            except Exception:
                pass

            def _check_empty(*_a, **_kw) -> None:
                try:
                    if len(ctx.pages) == 0:
                        closed.set()
                except Exception:
                    closed.set()

            try:
                for p in list(ctx.pages):
                    p.on("close", _check_empty)
                ctx.on("page", lambda p: p.on("close", _check_empty))
            except Exception:
                pass

            while not closed.is_set():
                if closed.wait(timeout=1.5):
                    break
                try:
                    _ = ctx.pages
                except Exception:
                    break
        return result

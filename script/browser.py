"""Playwright persistent browser profile — multi-platform login + anti-bot CDN.

Supports: 抖音 / 快手 / 小红书 / B站. Platform is auto-detected from the share
URL or selected explicitly. Each platform uses its own persistent user data dir
(so cookies don't collide).
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

from script.platforms import PlatformConfig, detect_platform, get_platform

ROOT = Path(__file__).resolve().parent.parent

_login_lock = threading.Lock()
_login_running = False
_login_started_at: float = 0.0
_login_platform: str = ""
_LOGIN_STALE_SECONDS = 600.0


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
    """Return the persistent profile dir for the given platform."""
    if platform_id:
        p = get_platform(platform_id)
        subdir = p.user_data_subdir if p else f"data/browser/{platform_id}"
    else:
        raw = browser_cfg(cfg).get("user_data_dir") or "data/browser/douyin"
        subdir = raw
    path = Path(subdir)
    if not path.is_absolute():
        path = ROOT / path
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
    kw: dict = {
        "headless": headless,
        "args": ["--disable-blink-features=AutomationControlled"],
        "viewport": {"width": 1280, "height": 900},
        "locale": "zh-CN",
    }
    channel = (b.get("channel") or "").strip()
    if channel:
        kw["channel"] = channel
    return kw


@contextmanager
def persistent_context(
    cfg: dict, *, headless: bool = True, platform_id: str = ""
) -> Iterator:
    """Yield Playwright persistent Chromium context (saved cookies)."""
    _require_playwright()
    from playwright.sync_api import sync_playwright

    user_dir = user_data_dir(cfg, platform_id)
    _cleanup_stale_locks(user_dir)
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            str(user_dir),
            **_launch_kwargs(cfg, headless=headless),
        )
        try:
            yield ctx
        finally:
            ctx.close()


def _detect_login_from_cookies(ctx, platform: PlatformConfig) -> tuple[bool, int]:
    """Read login state from the given context's cookies (no new launch)."""
    try:
        cookies = ctx.cookies()
    except Exception:
        return False, 0
    names = {c.get("name", "") for c in cookies}
    logged_in = bool(names & platform.login_cookies) if platform.login_cookies else len(cookies) > 5
    return logged_in, len(cookies)


def check_login_status(cfg: dict, platform_id: str = "") -> dict:
    """Best-effort: visit platform homepage and detect login cookies."""
    platform_id = platform_id or "douyin"
    platform = get_platform(platform_id)
    if not platform:
        return {"ready": False, "logged_in": False, "message": f"未知平台: {platform_id}"}
    if not playwright_available():
        return {
            "ready": False,
            "logged_in": False,
            "message": "Playwright 未安装",
            "profile_dir": str(user_data_dir(cfg, platform_id)),
            "platform": platform_id,
            "platform_name": platform.name,
        }
    try:
        with persistent_context(cfg, headless=True, platform_id=platform_id) as ctx:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                page.goto(platform.login_url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(2500)
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
                }
            logged_in, n = _detect_login_from_cookies(ctx, platform)
            msg = "已检测到登录态" if logged_in else f"未登录或登录已过期，请点击「浏览器登录」"
            return {
                "ready": True,
                "logged_in": logged_in,
                "message": msg,
                "profile_dir": str(user_data_dir(cfg, platform_id)),
                "platform": platform_id,
                "platform_name": platform.name,
                "cookie_count": n,
            }
    except Exception as exc:
        return {
            "ready": False,
            "logged_in": False,
            "message": str(exc),
            "profile_dir": str(user_data_dir(cfg, platform_id)),
            "platform": platform_id,
            "platform_name": platform.name,
        }


def open_login_browser(cfg: dict, *, wait_close: bool = True, platform_id: str = "") -> dict:
    """Open headed browser for manual platform login; cookies persist in profile."""
    _require_playwright()
    from playwright.sync_api import sync_playwright

    platform_id = platform_id or "douyin"
    platform = get_platform(platform_id)
    if not platform:
        raise RuntimeError(f"未知平台: {platform_id}")

    user_dir = user_data_dir(cfg, platform_id)
    _cleanup_stale_locks(user_dir)
    closed = threading.Event()

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            str(user_dir),
            **_launch_kwargs(cfg, headless=False),
        )

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

        try:
            page.goto(platform.login_url, wait_until="domcontentloaded", timeout=60000)
        except Exception as exc:
            hint = "403 通常是开了梯子/VPN，平台封境外 IP，请关闭后重试"
            html = (
                "<body style='font-family:system-ui;padding:40px;color:#333'>"
                f"<h2>加载{platform.name}失败</h2>"
                f"<p>请手动在地址栏打开 <b>{platform.login_url}</b> 登录。</p>"
                f"<p style='color:#c00'>{hint}</p>"
                f"<pre style='background:#f4f4f4;padding:12px;border-radius:8px;"
                f"white-space:pre-wrap'>{str(exc)[:300]}</pre>"
                "</body>"
            )
            try:
                page.set_content(html)
            except Exception:
                pass

        if wait_close:
            while not closed.is_set():
                if closed.wait(timeout=1.5):
                    break
                try:
                    _ = ctx.pages
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


def _is_login_stale() -> bool:
    """True if the running guard has been held past the stale timeout."""
    return _login_started_at and (time.time() - _login_started_at) > _LOGIN_STALE_SECONDS


def start_login_async(cfg: dict, *, force: bool = False, platform_id: str = "") -> dict:
    """Non-blocking login window (background thread).

    `force=True` kills any stuck previous attempt and relaunches.
    """
    global _login_running, _login_started_at, _login_platform
    platform_id = platform_id or "douyin"
    with _login_lock:
        if _login_running and not force and not _is_login_stale():
            return {
                "ok": False,
                "message": "登录窗口已在打开中；如已关闭但点不动，再点一次本按钮会强制重开",
            }
        _login_running = True
        _login_started_at = time.time()
        _login_platform = platform_id

    def _run() -> None:
        global _login_running
        try:
            open_login_browser(cfg, wait_close=True, platform_id=platform_id)
        except Exception:
            pass
        finally:
            with _login_lock:
                _login_running = False
                _login_started_at = 0.0
                _login_platform = ""

    threading.Thread(target=_run, daemon=True).start()
    platform = get_platform(platform_id)
    return {
        "ok": True,
        "message": f"已打开{platform.name if platform else platform_id}浏览器，请在窗口中登录；完成后关闭浏览器窗口即可",
        "profile_dir": str(user_data_dir(cfg, platform_id)),
        "platform": platform_id,
        "platform_name": platform.name if platform else platform_id,
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

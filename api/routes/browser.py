"""Browser login / status for multi-platform CDN and future publish RPA."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from script.browser import check_login_status, playwright_available, start_login_async
from script.platforms import detect_platform, list_platforms
from workflow.app_config import load_cfg

router = APIRouter(prefix="/api/browser", tags=["browser"])


class LoginBody(BaseModel):
    force: bool = False
    platform: str = ""


def _safe_cfg() -> dict:
    try:
        return load_cfg()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"读取配置失败：{exc}") from exc


@router.get("/platforms")
def platforms() -> dict:
    return {"platforms": list_platforms()}


@router.get("/status")
def status(platform: str = "") -> dict:
    cfg = _safe_cfg()
    pid = platform or "douyin"
    try:
        info = check_login_status(cfg, pid)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"检测浏览器状态失败：{exc}") from exc
    info["playwright_installed"] = playwright_available()
    return info


@router.post("/login")
def login(body: LoginBody | None = None) -> dict:
    cfg = _safe_cfg()
    if not playwright_available():
        return {
            "ok": False,
            "message": "请先安装 Playwright：在本机环境安装后重开，或运行 py -m pip install playwright && py -m playwright install chromium",
        }
    force = bool(body and body.force)
    platform = (body and body.platform) or ""
    if not platform:
        # Auto-detect from share URL is done on the frontend; default to douyin
        platform = "douyin"
    try:
        return start_login_async(cfg, force=force, platform_id=platform)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/detect")
def detect(url: str = "") -> dict:
    """Auto-detect platform from a share URL."""
    return {"platform": detect_platform(url), "url": url}

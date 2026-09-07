"""App version + Release update check (GitHub / Gitee)."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import APIRouter

router = APIRouter(prefix="/api/updates", tags=["updates"])

ROOT = Path(__file__).resolve().parent.parent.parent
GITHUB_LATEST = "https://api.github.com/repos/jiukemi/JY_IPAgent/releases/latest"
GITEE_LATEST = "https://gitee.com/api/v5/repos/webhwh/JY_IPAgent-/releases/latest"
GITHUB_SETUP_RE = re.compile(r"JY_IPAgent-Setup-[\d.]+\.exe$", re.I)
GITEE_SETUP_RE = re.compile(r"(九易AI智能体|JY_IPAgent)-Setup-[\d.]+\.exe$", re.I)


def read_app_version() -> str:
    for candidate in (ROOT / "VERSION", ROOT / "desktop" / "package.json"):
        if not candidate.is_file():
            continue
        try:
            if candidate.name == "package.json":
                data = json.loads(candidate.read_text(encoding="utf-8"))
                ver = str(data.get("version") or "").strip()
            else:
                ver = candidate.read_text(encoding="utf-8").strip().splitlines()[0].strip()
            if ver:
                return ver.lstrip("vV")
        except Exception:
            continue
    return "0.0.0"


def _parse_semver(raw: str) -> tuple[int, ...]:
    s = (raw or "").strip().lstrip("vV")
    parts = re.findall(r"\d+", s)
    nums = [int(x) for x in parts[:4]]
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums)


def is_newer(remote: str, local: str) -> bool:
    return _parse_semver(remote) > _parse_semver(local)


def _http_json(url: str, timeout: float = 12.0) -> dict | None:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "JY_IPAgent-Updater/1.0",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, ValueError):
        return None


def _pick_asset(assets: list, prefer: str) -> dict | None:
    if not isinstance(assets, list):
        return None
    named = []
    for a in assets:
        if not isinstance(a, dict):
            continue
        name = str(a.get("name") or "")
        if not name.lower().endswith(".exe"):
            continue
        named.append(a)
    if prefer == "github":
        for a in named:
            if GITHUB_SETUP_RE.search(str(a.get("name") or "")):
                return a
    else:
        for a in named:
            if GITEE_SETUP_RE.search(str(a.get("name") or "")):
                return a
    return named[0] if named else None


def _normalize_release(source: str, payload: dict | None) -> dict | None:
    if not payload:
        return None
    tag = str(payload.get("tag_name") or payload.get("name") or "").strip()
    version = tag.lstrip("vV")
    if not version:
        return None
    assets = payload.get("assets") or payload.get("attach_files") or []
    if source == "gitee" and (not assets) and payload.get("id"):
        # Gitee often omits attach_files on /releases/latest — fetch explicitly
        rid = payload.get("id")
        extra = _http_json(
            f"https://gitee.com/api/v5/repos/webhwh/JY_IPAgent-/releases/{rid}/attach_files"
        )
        if isinstance(extra, list):
            assets = extra
    asset = _pick_asset(assets if isinstance(assets, list) else [], prefer=source)
    url = ""
    name = ""
    size = 0
    if asset:
        url = str(
            asset.get("browser_download_url")
            or asset.get("browser_url")
            or asset.get("url")
            or ""
        ).strip()
        name = str(asset.get("name") or "").strip()
        try:
            size = int(asset.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
    if not url and source == "github":
        # Construct conventional URL even if asset list empty
        name = f"JY_IPAgent-Setup-{version}.exe"
        url = f"https://github.com/jiukemi/JY_IPAgent/releases/download/v{version}/{name}"
    if not url and source == "gitee":
        # Prefer ASCII asset name (Chinese filenames often mangle on Gitee).
        name = f"JY_IPAgent-Setup-{version}.exe"
        url = (
            "https://gitee.com/webhwh/JY_IPAgent-/releases/download/"
            f"v{version}/{name}"
        )
    html_url = str(payload.get("html_url") or payload.get("url") or "").strip()
    body = str(payload.get("body") or payload.get("description") or "").strip()
    # Filename version must match release tag — catches stale/wrong assets.
    file_ver = ""
    m = re.search(r"Setup-([\d.]+)\.exe$", name or "", re.I)
    if m:
        file_ver = m.group(1)
    version_mismatch = bool(file_ver and _parse_semver(file_ver) != _parse_semver(version))
    return {
        "source": source,
        "version": version,
        "tag": tag if tag.startswith("v") else f"v{version}",
        "name": name,
        "download_url": url,
        "html_url": html_url,
        "size": size,
        "notes": body[:2000],
        "file_version": file_ver or version,
        "version_mismatch": version_mismatch,
    }


@router.get("/version")
def get_version() -> dict:
    return {"version": read_app_version()}


@router.get("/check")
def check_updates() -> dict:
    local = read_app_version()
    mirrors = []
    for source, url in (("gitee", GITEE_LATEST), ("github", GITHUB_LATEST)):
        info = _normalize_release(source, _http_json(url))
        if info:
            mirrors.append(info)

    newest = None
    for m in mirrors:
        if newest is None or is_newer(m["version"], newest["version"]):
            newest = m

    update_available = bool(newest and is_newer(newest["version"], local))
    # Only offer installers that are actually newer than the running app
    # (Gitee often lags GitHub — clicking an old Gitee mirror reinstalls e.g. 0.1.30).
    # Also drop assets whose filename version disagrees with the release tag.
    usable = [
        m
        for m in mirrors
        if is_newer(m["version"], local) and not m.get("version_mismatch")
    ]
    usable.sort(key=lambda m: _parse_semver(m["version"]), reverse=True)
    newest_ver = (newest or {}).get("version") or ""
    for m in mirrors:
        m["is_newest"] = bool(newest_ver and m.get("version") == newest_ver)
        m["behind_latest"] = bool(
            newest_ver and is_newer(newest_ver, str(m.get("version") or ""))
        )
    lagging = [
        m
        for m in mirrors
        if m.get("behind_latest") or m.get("version_mismatch")
    ]
    return {
        "ok": True,
        "current_version": local,
        "update_available": update_available,
        "latest": newest if update_available else newest,
        "mirrors": usable if update_available else [],
        "all_mirrors": mirrors,
        "lagging_mirrors": lagging,
        "warning": (
            (
                "有镜像源版本落后或文件名与版本不一致，请只点「推荐」最新版，"
                "勿下旧包以免白装。"
            )
            if lagging and update_available
            else (
                "检测到某镜像源安装包文件名与版本不一致，已隐藏该下载按钮。"
                if any(m.get("version_mismatch") for m in mirrors)
                else ""
            )
        ),
    }

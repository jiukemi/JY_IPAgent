"""On-demand component registry (engines downloaded after install, not bundled)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPONENTS_DIR = ROOT / "data" / "components"
MANIFEST_PATH = COMPONENTS_DIR / "manifest.json"
EXAMPLE_MANIFEST = COMPONENTS_DIR / "manifest.example.json"


def ensure_dirs() -> None:
    COMPONENTS_DIR.mkdir(parents=True, exist_ok=True)
    if not MANIFEST_PATH.is_file() and EXAMPLE_MANIFEST.is_file():
        shutil.copy2(EXAMPLE_MANIFEST, MANIFEST_PATH)


def load_manifest() -> dict:
    ensure_dirs()
    path = MANIFEST_PATH if MANIFEST_PATH.is_file() else EXAMPLE_MANIFEST
    if not path.is_file():
        return {"version": 1, "components": []}
    return json.loads(path.read_text(encoding="utf-8"))


def component_dir(component_id: str) -> Path:
    return COMPONENTS_DIR / component_id


def _installed_version(component_id: str) -> str:
    marker = component_dir(component_id) / ".installed"
    if not marker.is_file():
        return ""
    text = marker.read_text(encoding="utf-8-sig").strip()
    if text.startswith("version="):
        return text.split("=", 1)[1].strip()
    man = component_dir(component_id) / "manifest.component.json"
    if man.is_file():
        try:
            return str(json.loads(man.read_text(encoding="utf-8-sig")).get("version") or "")
        except Exception:
            return ""
    return text or "unknown"


def _is_fixture_version(version: str) -> bool:
    v = (version or "").lower()
    return "fixture" in v or v.startswith("0.0.0")


def is_installed(component_id: str) -> bool:
    """True only for a real (non-fixture) install with .installed marker."""
    marker = component_dir(component_id) / ".installed"
    if not marker.is_file():
        return False
    if _is_fixture_version(_installed_version(component_id)):
        return False
    entry_ok = False
    man = component_dir(component_id) / "manifest.component.json"
    if man.is_file():
        try:
            data = json.loads(man.read_text(encoding="utf-8-sig"))
            entry = data.get("entry") or "start.ps1"
            entry_ok = (component_dir(component_id) / entry).is_file()
        except Exception:
            entry_ok = False
    return entry_ok


def usable_mirrors(mirrors: list | None) -> list[dict]:
    out: list[dict] = []
    for m in mirrors or []:
        url = (m.get("url") or "").strip()
        if not url:
            continue
        out.append(m)
    return out


def component_statuses() -> list[dict]:
    manifest = load_manifest()
    out: list[dict] = []
    for item in manifest.get("components") or []:
        cid = str(item.get("id") or "")
        if not cid:
            continue
        mirrors = usable_mirrors(item.get("mirrors"))
        installed = is_installed(cid)
        has_marker = (component_dir(cid) / ".installed").is_file()
        fixture = has_marker and _is_fixture_version(_installed_version(cid))
        if installed:
            status = "installed"
            status_label = "已安装"
        elif fixture:
            status = "fixture"
            status_label = "测试占位（无效）"
        elif not mirrors:
            status = "unavailable"
            status_label = "运行时包未提供"
        else:
            status = "not_installed"
            status_label = "可下载"
        note = item.get("note") or ""
        if not mirrors and not note:
            note = "正式便携包尚未托管；开发请用「本机环境 · GPU 与模型」。口播目前仍可能走本机 Docker。"
        out.append(
            {
                "id": cid,
                "name": item.get("name") or cid,
                "kind": item.get("kind") or "engine",
                "required_for": item.get("required_for") or [],
                "approx_size_gb": item.get("approx_size_gb"),
                "installed": installed,
                "path": str(component_dir(cid)) if installed else "",
                "mirrors": mirrors,
                "downloadable": bool(mirrors) and not installed,
                "status": status,
                "status_label": status_label,
                "note": note,
                "packaging_only": True,
            }
        )
    return out


def install_component(component_id: str, on_progress=None) -> Path:
    ensure_dirs()
    manifest = load_manifest()
    item = next((c for c in (manifest.get("components") or []) if c.get("id") == component_id), None)
    if not item:
        raise KeyError(component_id)
    mirrors = usable_mirrors(item.get("mirrors"))
    if not mirrors:
        raise RuntimeError(
            f"组件 {component_id} 尚无可用下载地址（运行时包未提供）。"
            "请使用设置里的「本机环境 · GPU 与模型」，或配置真实 mirrors 后再试。"
        )
    dest = component_dir(component_id)
    from workflow.component_download import install_from_mirrors

    install_from_mirrors(mirrors, dest, on_progress=on_progress)
    marker = dest / ".installed"
    ver = ""
    man = dest / "manifest.component.json"
    if man.is_file():
        ver = json.loads(man.read_text(encoding="utf-8-sig")).get("version") or ""
    if _is_fixture_version(ver):
        raise RuntimeError("拒绝安装 fixture 测试包到正式组件目录；请使用真实运行时 zip。")
    marker.write_text(f"version={ver}\n", encoding="utf-8")
    return dest


def mark_installed(component_id: str) -> Path:
    """Dev/helper: create install marker (tests/dev only)."""
    d = component_dir(component_id)
    d.mkdir(parents=True, exist_ok=True)
    marker = d / ".installed"
    marker.write_text("ok\n", encoding="utf-8")
    return d

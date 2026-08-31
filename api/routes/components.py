"""Component download / status API (on-demand engines)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from workflow.components import component_statuses, install_component, mark_installed
from workflow.edition import edition_payload

router = APIRouter(prefix="/api/components", tags=["components"])

_PROGRESS: dict[str, dict] = {}


class InstallBody(BaseModel):
    component_id: str


@router.get("")
def list_components() -> dict:
    return {
        "edition": edition_payload(),
        "components": component_statuses(),
        "hint": "日常请用「本机环境 · GPU 与模型」。下列为安装包按需下载预留；无真实镜像时显示「运行时包未提供」。",
    }


@router.get("/edition")
def get_edition() -> dict:
    return edition_payload()


@router.get("/download/progress/{component_id}")
def download_progress(component_id: str) -> dict:
    return _PROGRESS.get(component_id) or {
        "status": "idle",
        "received": 0,
        "total": -1,
        "message": "",
    }


@router.post("/mark-installed")
def mark_component_installed(body: InstallBody) -> dict:
    """P0 stub: mark a component installed without downloading (dev / placeholder)."""
    cid = (body.component_id or "").strip()
    if not cid:
        raise HTTPException(400, "component_id 必填")
    known = {c["id"] for c in component_statuses()}
    # Allow marking even if only in example manifest
    path = mark_installed(cid)
    return {"ok": True, "component_id": cid, "path": str(path), "components": component_statuses()}


@router.post("/download")
def download_component(body: InstallBody) -> dict:
    """Download and install a component via multi-mirror installer."""
    cid = (body.component_id or "").strip()
    if not cid:
        raise HTTPException(400, "component_id 必填")
    statuses = {c["id"]: c for c in component_statuses()}
    item = statuses.get(cid)
    if not item:
        raise HTTPException(404, f"未知组件: {cid}")
    if item.get("installed"):
        return {"ok": True, "already": True, "component": item}

    def on_progress(received, total, message):
        _PROGRESS[cid] = {
            "status": "running",
            "received": received,
            "total": total,
            "message": message,
            "percent": (received / total) if total and total > 0 else None,
        }

    _PROGRESS[cid] = {"status": "running", "received": 0, "total": -1, "message": "starting"}
    try:
        path = install_component(cid, on_progress=on_progress)
        _PROGRESS[cid] = {"status": "done", "received": 0, "total": 0, "message": "ok"}
        return {"ok": True, "path": str(path), "components": component_statuses()}
    except Exception as e:
        _PROGRESS[cid] = {"status": "error", "message": str(e)}
        raise HTTPException(500, str(e)) from e

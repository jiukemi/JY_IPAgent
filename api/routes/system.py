"""System resource stats API."""

from __future__ import annotations

from fastapi import APIRouter, File, Form, UploadFile

from workflow.system_stats import live_system_stats
from workflow.task_control import active_job, request_cancel
from workflow.runtime_bootstrap import runtime_status, ensure_ffmpeg

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/stats")
def system_stats() -> dict:
    return live_system_stats()


@router.get("/runtime")
def get_runtime() -> dict:
    st = runtime_status()
    st["docker_desktop_installer"] = {
        "win_x64": "https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe",
        "note": "需管理员安装并可能重启；无法完全静默。有 Docker 后可用 setup_heygem / 离线 tar。",
    }
    return st


@router.post("/runtime/ensure-ffmpeg")
def post_ensure_ffmpeg() -> dict:
    return ensure_ffmpeg(download=True)


@router.get("/quark/catalog")
def quark_catalog() -> dict:
    """Pack list for netdisk line + GPU family recommendation (general vs RTX50)."""
    from workflow.quark_accel import catalog_for_ui

    return catalog_for_ui()


@router.get("/quark/scan")
def quark_scan() -> dict:
    """List Quark accelerator zips found under Downloads / Desktop / Quark folders."""
    from workflow.quark_accel import catalog_for_ui, default_scan_dirs, find_accel_zips

    cands = find_accel_zips()
    machine = catalog_for_ui().get("machine") or {}
    return {
        "ok": True,
        "count": len(cands),
        "machine": machine,
        "candidates": [
            {
                "path": c["path"],
                "bytes": c["bytes"],
                "bundle_name": (c.get("manifest") or {}).get("bundle_name"),
                "pack_id": c.get("pack_id") or (c.get("manifest") or {}).get("pack_id"),
                "pack_kind": c.get("pack_kind"),
                "gpu_family": c.get("gpu_family"),
                "scan_dir": c.get("scan_dir"),
            }
            for c in cands[:10]
        ],
        "scan_dirs": [str(p) for p in default_scan_dirs()],
        "note": "仅加速大文件。口播包请按本机显卡选「通用」或「RTX50」，勿混用。",
    }


@router.post("/quark/install")
def quark_install(body: dict | None = None) -> dict:
    """Install latest or specified Quark accelerator zip into runtime."""
    from workflow.quark_accel import install_accel_zip, scan_and_install_latest

    body = body or {}
    path = (body.get("path") or "").strip()
    force = bool(body.get("force"))
    if path:
        return install_accel_zip(path, force=force)
    return scan_and_install_latest(force=force)


@router.post("/quark/upload")
async def quark_upload(
    file: UploadFile = File(...),
    force: bool = Form(False),
) -> dict:
    """Drag-drop / file picker: upload zip then install (browser has no local path)."""
    from workflow.quark_accel import save_upload_and_install

    raw = await file.read()
    return save_upload_and_install(raw, file.filename or "upload.zip", force=force)


@router.get("/tasks")
def task_status() -> dict:
    return active_job()


@router.post("/tasks/cancel")
def task_cancel() -> dict:
    """Terminate the current long-running job (lipsync / publish / subprocess trees)."""
    return request_cancel()

"""FunASR worker control — start/stop the persistent ASR worker."""

from __future__ import annotations

from fastapi import APIRouter

from script.funasr_client import (
    ensure_funasr_worker,
    is_worker_running,
    shutdown_funasr_worker,
    worker_status,
)
from workflow.app_config import CONFIG_PATH, load_cfg

router = APIRouter(prefix="/api/funasr", tags=["funasr"])


def _set_worker_enabled(value: bool) -> None:
    """Flip script.funasr.worker_enabled in config.yaml (idempotent)."""
    try:
        import yaml
    except ImportError:
        return
    try:
        text = CONFIG_PATH.read_text(encoding="utf-8")
        cfg = yaml.safe_load(text) or {}
    except Exception:
        return
    script = cfg.setdefault("script", {})
    funasr = script.setdefault("funasr", {})
    funasr["worker_enabled"] = bool(value)
    try:
        CONFIG_PATH.write_text(
            yaml.dump(cfg, allow_unicode=True, sort_keys=False, default_flow_style=False),
            encoding="utf-8",
        )
    except Exception:
        pass


@router.get("/worker/status")
def status() -> dict:
    cfg = load_cfg()
    enabled = (cfg.get("script") or {}).get("funasr", {}).get("worker_enabled", False) is True
    running = is_worker_running()
    return {
        "enabled": enabled,
        "running": running,
        "model": worker_status().get("model"),
    }


@router.post("/worker/start")
def start() -> dict:
    # Auto-enable in config so the user doesn't have to edit YAML.
    _set_worker_enabled(True)
    cfg = load_cfg()
    try:
        ok = ensure_funasr_worker(cfg)
        return {"ok": ok, "running": is_worker_running(), "enabled": True}
    except Exception as exc:
        return {"ok": False, "message": str(exc), "running": False, "enabled": True}


@router.post("/worker/stop")
def stop() -> dict:
    shutdown_funasr_worker()
    _set_worker_enabled(False)
    return {"ok": True, "running": is_worker_running(), "enabled": False}

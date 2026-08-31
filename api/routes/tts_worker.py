"""TTS (IndexTTS) worker control — start/stop the persistent TTS worker."""

from __future__ import annotations

from fastapi import APIRouter

from workflow.app_config import CONFIG_PATH, load_cfg

router = APIRouter(prefix="/api/tts", tags=["tts"])


def _set_worker_enabled(value: bool) -> None:
    try:
        import yaml
    except ImportError:
        return
    try:
        cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        return
    cfg.setdefault("indextts", {})["worker_enabled"] = bool(value)
    try:
        CONFIG_PATH.write_text(
            yaml.dump(cfg, allow_unicode=True, sort_keys=False, default_flow_style=False),
            encoding="utf-8",
        )
    except Exception:
        pass


@router.get("/worker/status")
def status() -> dict:
    from tts.indextts_client import is_worker_running as _is_running

    cfg = load_cfg()
    enabled = (cfg.get("indextts") or {}).get("worker_enabled", True) is not False
    return {"enabled": enabled, "running": _is_running()}


@router.post("/worker/start")
def start() -> dict:
    from tts.indextts_client import ensure_indextts_worker

    _set_worker_enabled(True)
    cfg = load_cfg()
    try:
        ok = ensure_indextts_worker(cfg)
        from tts.indextts_client import is_worker_running as _is_running

        return {"ok": ok, "running": _is_running(), "enabled": True}
    except Exception as exc:
        return {"ok": False, "message": str(exc), "running": False, "enabled": True}


@router.post("/worker/stop")
def stop() -> dict:
    from tts.indextts_client import shutdown_indextts_worker, is_worker_running as _is_running

    shutdown_indextts_worker()
    _set_worker_enabled(False)
    return {"ok": True, "running": _is_running(), "enabled": False}

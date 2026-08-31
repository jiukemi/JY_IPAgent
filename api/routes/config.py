"""Config and global settings routes."""

from __future__ import annotations

from fastapi import APIRouter, Body

from api.schemas import SettingsPayload, SettingsResponse
from ui.global_settings import load_settings_values, save_global_settings
from ui.workflow_shell import deployment_summary_md
from tts.engine_profiles import engine_profile
from workflow.app_config import CONFIG_PATH, load_cfg
from workflow.deployment import step_engine, step_mode
from workflow.engine_catalog import engine_dropdown_choices, engine_label, whisper_dropdown_choices


def _engine_choice_list(step: str, mode: str) -> list[dict]:
    return [
        {
            "value": val,
            "label": lbl,
            "hardware": engine_profile(val).get("hardware", ""),
            "summary": engine_profile(val).get("summary", ""),
        }
        for lbl, val in engine_dropdown_choices(step, mode)
    ]

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("/prompts")
def get_text_prompts() -> dict:
    from script.prompt_store import list_prompts

    return {"items": list_prompts()}


@router.put("/prompts")
def put_text_prompts(body: dict = Body(...)) -> dict:
    from script.prompt_store import save_prompts

    updates = body.get("prompts") if isinstance(body.get("prompts"), dict) else body
    if not isinstance(updates, dict):
        updates = {}
    items = save_prompts(
        {
            str(k): str(v)
            for k, v in updates.items()
            if str(k) not in ("prompts", "ok", "items") and not str(k).startswith("_")
        }
    )
    return {"ok": True, "items": items}


@router.post("/prompts/reset")
def reset_text_prompts(body: dict | None = Body(default=None)) -> dict:
    from script.prompt_store import reset_prompts

    ids = None
    if isinstance(body, dict) and body.get("ids") is not None:
        raw = body.get("ids")
        ids = [str(x) for x in raw] if isinstance(raw, list) else None
    items = reset_prompts(ids)
    return {"ok": True, "items": items}


@router.get("/settings")
def get_settings() -> dict:
    cfg = load_cfg()
    values = load_settings_values(cfg)
    engines = {}
    for step in ("script", "tts", "avatar", "publish"):
        mode = step_mode(cfg, step)
        engines[step] = {
            "mode": mode,
            "engine": step_engine(cfg, step),
            "choices": _engine_choice_list(step, mode),
            "choices_local": _engine_choice_list(step, "local"),
            "choices_cloud": _engine_choice_list(step, "cloud"),
        }
    return {
        "settings": values,
        "summary_md": deployment_summary_md(cfg),
        "whisper_choices": [{"value": v, "label": l} for l, v in whisper_dropdown_choices()],
        "engines": engines,
    }


@router.put("/settings", response_model=SettingsResponse)
def put_settings(body: SettingsPayload) -> SettingsResponse:
    cfg = save_global_settings(
        body.script_mode,
        body.script_engine,
        body.whisper_model,
        body.tts_mode,
        body.tts_engine,
        body.avatar_mode,
        body.avatar_engine,
        body.publish_mode,
        body.publish_engine,
        cdn_api_key=body.cdn_api_key,
        transcript_api_key=body.transcript_api_key,
        rewrite_api_key=body.rewrite_api_key,
        qwen3_tts_api_key=body.qwen3_tts_api_key,
        cdn_provider=body.cdn_provider or "",
        cdn_api_url=body.cdn_api_url or "",
        transcript_provider=body.transcript_provider or "",
        transcript_api_url=body.transcript_api_url or "",
        cfg_path=CONFIG_PATH,
    )
    values = load_settings_values(cfg)
    return SettingsResponse(
        settings=SettingsPayload(**values),
        summary_md=deployment_summary_md(cfg),
    )

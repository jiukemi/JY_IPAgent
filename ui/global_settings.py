"""Global settings modal: per-step local/cloud + engine backend + API keys."""

from __future__ import annotations

from pathlib import Path

import yaml

from ui.gradio_compat import gr

from workflow.deployment import normalize_tts_engine, step_backend_label, step_engine, step_mode
from workflow.engine_catalog import (
    WHISPER_MODEL_CHOICES,
    default_engine,
    engine_choices,
    engine_dropdown_choices,
    engine_label,
)
from script.parse_providers import (
    ASR_PROTOCOL_ASYNC_COUNT,
    ASR_PROTOCOL_ASYNC_POLL,
    ASR_PROTOCOL_ASYNC_TIME,
    ASR_PROTOCOL_CUSTOM_JSON,
    ASR_PROTOCOL_SYNC_CONTENT,
    ASR_PROTOCOL_SYNC_VIDEOURL,
    CDN_PROTOCOL_AGG_PROFILE,
    CDN_PROTOCOL_AGG_VIDEO,
    CDN_PROTOCOL_FORM_KEY_URL,
    CDN_PROTOCOL_FORM_KEY_URL_TIMES,
    CDN_PROTOCOL_JSON_URL,
    CDN_PROTOCOL_NONE,
    normalize_cdn_provider,
    normalize_transcript_provider,
)

from workflow.app_config import CONFIG_PATH, ensure_config_file

ensure_config_file()

_CDN_UI_PROTOCOLS = frozenset(
    {
        CDN_PROTOCOL_NONE,
        CDN_PROTOCOL_FORM_KEY_URL,
        CDN_PROTOCOL_FORM_KEY_URL_TIMES,
        CDN_PROTOCOL_AGG_VIDEO,
        CDN_PROTOCOL_AGG_PROFILE,
        CDN_PROTOCOL_JSON_URL,
    }
)
_ASR_UI_PROTOCOLS = frozenset(
    {
        ASR_PROTOCOL_SYNC_VIDEOURL,
        ASR_PROTOCOL_SYNC_CONTENT,
        ASR_PROTOCOL_ASYNC_TIME,
        ASR_PROTOCOL_ASYNC_COUNT,
        ASR_PROTOCOL_ASYNC_POLL,
        ASR_PROTOCOL_CUSTOM_JSON,
    }
)


def engine_value(cfg: dict, step: str) -> str:
    return step_engine(cfg, step)  # type: ignore[arg-type]


def _cloud_block(cfg: dict) -> dict:
    return (cfg.get("script") or {}).setdefault("cloud", {})


def load_settings_values(cfg: dict) -> dict:
    sc = cfg.get("script") or {}
    cloud = sc.get("cloud") or {}
    cdn = cloud.get("cdn") or {}
    tr = cloud.get("transcript") or {}
    rw = cloud.get("rewrite") or {}
    q3 = cfg.get("qwen3_tts") or {}
    return {
        "script_mode": step_mode(cfg, "script"),
        "script_engine": engine_value(cfg, "script"),
        "whisper_model": sc.get("whisper_model") or "small",
        "tts_mode": step_mode(cfg, "tts"),
        "tts_engine": engine_value(cfg, "tts"),
        "avatar_mode": step_mode(cfg, "avatar"),
        "avatar_engine": engine_value(cfg, "avatar"),
        "publish_mode": step_mode(cfg, "publish"),
        "publish_engine": engine_value(cfg, "publish"),
        "cdn_provider": normalize_cdn_provider(cdn.get("provider") or CDN_PROTOCOL_NONE),
        "cdn_api_url": cdn.get("api_url") or "",
        "cdn_api_key": cdn.get("api_key") or "",
        "transcript_provider": normalize_transcript_provider(
            tr.get("provider") or ASR_PROTOCOL_SYNC_VIDEOURL
        ),
        "transcript_api_url": tr.get("api_url") or "",
        "transcript_api_key": tr.get("api_key") or "",
        "rewrite_api_key": rw.get("api_key") or "",
        "qwen3_tts_api_key": q3.get("api_key") or "",
    }


def needs_cdn_key(script_mode: str, script_engine: str) -> bool:
    return (script_mode or "local") == "cloud"


def needs_transcript_key(script_mode: str, script_engine: str) -> bool:
    return (script_mode or "local") == "cloud"


def needs_rewrite_key(script_mode: str, _script_engine: str) -> bool:
    return (script_mode or "local") == "cloud"


def needs_qwen3_key(_tts_mode: str, tts_engine: str) -> bool:
    return tts_engine == "qwen3_tts"


def needs_whisper_model(script_mode: str, script_engine: str) -> bool:
    return (script_mode or "local") == "local" and script_engine == "local_whisper"


def on_engine_mode_change(step: str, mode: str, current_engine: str):
    pairs = engine_choices(step, mode)
    values = [v for v, _ in pairs]
    value = current_engine if current_engine in values else default_engine(step, mode)
    return gr.update(choices=engine_dropdown_choices(step, mode), value=value)


def on_script_mode_change(mode: str, script_engine: str):
    eng_up = on_engine_mode_change("script", mode, script_engine)
    new_val = eng_up.get("value") if isinstance(eng_up, dict) else script_engine
    return eng_up, gr.update(visible=needs_whisper_model(mode, new_val))


def refresh_script_key_fields(script_mode: str, script_engine: str):
    sm = (script_mode or "local").lower()
    se = script_engine or ""
    return (
        gr.update(visible=needs_cdn_key(sm, se)),
        gr.update(visible=needs_transcript_key(sm, se)),
        gr.update(visible=needs_rewrite_key(sm, se)),
    )


def refresh_qwen3_key_field(tts_mode: str, tts_engine: str):
    return gr.update(visible=needs_qwen3_key(tts_mode, tts_engine))


def refresh_all_conditional_fields(
    script_mode: str,
    script_engine: str,
    tts_mode: str,
    tts_engine: str,
):
    eng_up, whisper_up = on_script_mode_change(script_mode, script_engine)
    cdn_up, tr_up, rw_up = refresh_script_key_fields(script_mode, script_engine)
    qwen_up = refresh_qwen3_key_field(tts_mode, tts_engine)
    return eng_up, whisper_up, cdn_up, tr_up, rw_up, qwen_up


def _apply_script_engine(cfg: dict, mode: str, engine: str) -> None:
    """Sync side effects for script engine (transcript provider / cloud catalog)."""
    mode = (mode or "local").lower()
    engine = (engine or "").strip()
    if mode == "local":
        tr = cfg.setdefault("script", {}).setdefault("cloud", {}).setdefault("transcript", {})
        if engine == "funasr":
            tr["provider"] = "funasr"
        elif engine == "local_whisper":
            tr["provider"] = "local_whisper"
        return
    if mode != "cloud":
        return
    engines = cfg.setdefault("deployment", {}).setdefault("engines", {}).setdefault("script", {})
    if not isinstance(engines, dict):
        return
    engines["cloud"] = engine or default_engine("script", "cloud")


def _apply_tts_engine(cfg: dict, mode: str, engine: str) -> None:
    dep = cfg.setdefault("deployment", {})
    cloud = dep.setdefault("cloud", {})
    tts = cfg.setdefault("tts", {})
    if mode == "cloud":
        cloud["tts_provider"] = engine
    else:
        tts["backend"] = engine


def _apply_avatar_engine(cfg: dict, mode: str, engine: str) -> None:
    if mode != "local":
        dep = cfg.setdefault("deployment", {})
        dep.setdefault("cloud", {})["avatar_provider"] = engine
        return
    lipsync = cfg.setdefault("lipsync", {})
    if engine in ("heygem", "sadtalker"):
        lipsync["digital_backend"] = engine
    elif engine == "latentsync":
        lipsync["real_backend"] = engine
        lipsync["backend"] = engine


def _apply_publish_engine(cfg: dict, mode: str, engine: str) -> None:
    dep = cfg.setdefault("deployment", {})
    dep.setdefault("cloud", {})["publish_provider"] = engine


def save_global_settings(
    script_mode: str,
    script_engine: str,
    whisper_model: str,
    tts_mode: str,
    tts_engine: str,
    avatar_mode: str,
    avatar_engine: str,
    publish_mode: str,
    publish_engine: str,
    cdn_api_key: str = "",
    transcript_api_key: str = "",
    rewrite_api_key: str = "",
    qwen3_tts_api_key: str = "",
    cdn_provider: str = "",
    cdn_api_url: str = "",
    transcript_provider: str = "",
    transcript_api_url: str = "",
    cfg_path: Path | str = CONFIG_PATH,
) -> dict:
    path = Path(cfg_path)
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    dep = cfg.setdefault("deployment", {})
    steps = dep.setdefault("steps", {})
    engines = dep.setdefault("engines", {})

    for step, mode, engine in (
        ("script", script_mode, script_engine),
        ("tts", tts_mode, tts_engine),
        ("avatar", avatar_mode, avatar_engine),
        ("publish", publish_mode, publish_engine),
    ):
        mode = (mode or "local").lower()
        if mode not in ("local", "cloud"):
            mode = "local"
        steps[step] = mode
        eng_block = engines.setdefault(step, {})
        if not isinstance(eng_block, dict):
            eng_block = {}
            engines[step] = eng_block
        if step == "tts":
            engine = normalize_tts_engine(mode, engine or default_engine(step, mode))
        else:
            engine = engine or default_engine(step, mode)
        eng_block[mode] = engine

    sc = cfg.setdefault("script", {})
    sc["whisper_model"] = whisper_model or "small"
    cloud = sc.setdefault("cloud", {})
    cdn = cloud.setdefault("cdn", {})
    tr = cloud.setdefault("transcript", {})
    cdn["api_url"] = (cdn_api_url or "").strip()
    cdn["api_key"] = (cdn_api_key or "").strip()
    cdn_p = normalize_cdn_provider(cdn_provider or CDN_PROTOCOL_NONE)
    if cdn_p == CDN_PROTOCOL_FORM_KEY_URL and not cdn["api_key"]:
        cdn_p = CDN_PROTOCOL_NONE
    if cdn_p == CDN_PROTOCOL_FORM_KEY_URL_TIMES and not cdn["api_key"]:
        cdn_p = CDN_PROTOCOL_NONE
    if cdn_p in (CDN_PROTOCOL_AGG_VIDEO, CDN_PROTOCOL_AGG_PROFILE) and not cdn["api_key"]:
        cdn_p = CDN_PROTOCOL_NONE
    if cdn_p == CDN_PROTOCOL_JSON_URL and not cdn["api_url"]:
        cdn_p = CDN_PROTOCOL_NONE
    if cdn_p not in _CDN_UI_PROTOCOLS and cdn_p not in (
        "browser_share",
        "local_share",
        "tenapi",
    ):
        cdn_p = CDN_PROTOCOL_FORM_KEY_URL if cdn["api_key"] else CDN_PROTOCOL_NONE
    cdn["provider"] = cdn_p
    if cdn_p == CDN_PROTOCOL_NONE:
        cdn["fallback_provider"] = ""

    tr["api_url"] = (transcript_api_url or "").strip()
    tr["api_key"] = (transcript_api_key or "").strip()
    tr_p = normalize_transcript_provider(transcript_provider or ASR_PROTOCOL_SYNC_VIDEOURL)
    if tr_p not in _ASR_UI_PROTOCOLS and tr_p not in ("funasr", "local_whisper"):
        tr_p = ASR_PROTOCOL_SYNC_VIDEOURL
    tr["provider"] = tr_p
    cloud.setdefault("rewrite", {})["api_key"] = (rewrite_api_key or "").strip()
    cfg.setdefault("qwen3_tts", {})["api_key"] = (qwen3_tts_api_key or "").strip()

    _apply_script_engine(cfg, script_mode, script_engine)
    _apply_tts_engine(
        cfg,
        tts_mode,
        normalize_tts_engine((tts_mode or "local").lower(), tts_engine),
    )
    _apply_avatar_engine(cfg, avatar_mode, avatar_engine)
    _apply_publish_engine(cfg, publish_mode, publish_engine)

    path.write_text(yaml.dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def settings_summary_md(cfg: dict) -> str:
    rows = []
    for step, label in (
        ("script", "① 文案"),
        ("tts", "② 配音"),
        ("avatar", "③ 口播"),
        ("publish", "④ 发布"),
    ):
        mode = step_mode(cfg, step)
        mode_cn = "本地" if mode == "local" else "云端"
        eng = engine_label(engine_value(cfg, step))
        rows.append(f"| {label} | {mode_cn} | {eng} |")
    return (
        "**全局运行方式**（点右上角 **⚙ 全局设置** 修改）\n\n"
        "| 步骤 | 模式 | 引擎 |\n|------|------|------|\n"
        + "\n".join(rows)
    )


def step_runtime_line(cfg: dict, step: str) -> str:
    mode = step_mode(cfg, step)
    tag = "🖥️ **本地**" if mode == "local" else "☁️ **云端**"
    detail = step_backend_label(cfg, step)
    return f"**本步运行：** {tag} · {detail}"

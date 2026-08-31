"""Per-step local vs cloud deployment (local-first; cloud stubs for future API)."""

from __future__ import annotations

from typing import Literal

from workflow.engine_catalog import default_engine, engine_choices, engine_label

StepName = Literal["script", "tts", "avatar", "publish"]
STEP_LABELS: dict[str, str] = {
    "script": "文案",
    "tts": "配音",
    "avatar": "数字人",
    "publish": "发布",
}
ALL_STEPS: tuple[StepName, ...] = ("script", "tts", "avatar", "publish")

LOCAL_TTS_ENGINES = frozenset({"indextts", "cosyvoice", "piper", "edge", "qwen3_local"})
CLOUD_TTS_ENGINES = frozenset({"qwen3_tts", "volcengine"})


def normalize_tts_engine(mode: str, engine: str) -> str:
    """Map invalid cross-mode engine ids to a valid default."""
    mode = (mode or "local").lower()
    engine = (engine or "").lower()
    if engine == "voxcpm":
        engine = "indextts"
    allowed = LOCAL_TTS_ENGINES if mode == "local" else CLOUD_TTS_ENGINES
    if engine in allowed:
        return engine
    if mode == "local" and engine == "qwen3_tts":
        return "indextts"
    if mode == "cloud" and engine in LOCAL_TTS_ENGINES:
        return "qwen3_tts"
    return default_engine("tts", mode)


def deployment_cfg(cfg: dict) -> dict:
    dep = cfg.get("deployment") or {}
    steps = dep.get("steps") or {}
    default = (dep.get("mode") or "local").lower()
    if default not in ("local", "cloud"):
        default = "local"
    normalized: dict[str, str] = {}
    for step in ALL_STEPS:
        mode = (steps.get(step) or default).lower()
        normalized[step] = mode if mode in ("local", "cloud") else default
    return {
        "mode": default,
        "steps": normalized,
        "cloud": dep.get("cloud") or {},
        "engines": dep.get("engines") or {},
    }


def step_mode(cfg: dict, step: StepName) -> str:
    return deployment_cfg(cfg)["steps"].get(step, "local")


def is_cloud(cfg: dict, step: StepName) -> bool:
    return step_mode(cfg, step) == "cloud"


def step_engine(cfg: dict, step: StepName) -> str:
    """Effective engine id for a step in the current mode."""
    mode = step_mode(cfg, step)
    engines = deployment_cfg(cfg).get("engines") or {}
    step_eng = engines.get(step) or {}
    if isinstance(step_eng, dict):
        val = (step_eng.get(mode) or step_eng.get("local") or step_eng.get("cloud") or "").strip()
        if val:
            if step == "tts":
                return normalize_tts_engine(mode, val)
            return val
    if step == "tts":
        if mode == "cloud":
            raw = (deployment_cfg(cfg)["cloud"].get("tts_provider") or "qwen3_tts").lower()
            return normalize_tts_engine(mode, raw)
        raw = (cfg.get("tts") or {}).get("backend") or "indextts"
        return normalize_tts_engine(mode, raw)
    if step == "script" and mode == "local":
        return "local_whisper"
    if step == "script" and mode == "cloud":
        return "cloud_17zhiling"
    if step == "avatar" and mode == "local":
        lipsync = cfg.get("lipsync") or {}
        return (lipsync.get("digital_backend") or "heygem").lower()
    if step == "publish" and mode == "local":
        return "ffmpeg"
    return default_engine(step, mode)


def resolve_tts_backend(cfg: dict) -> str:
    """Backend string for synthesize() from global settings."""
    return step_engine(cfg, "tts")


def step_backend_label(cfg: dict, step: StepName) -> str:
    mode = step_mode(cfg, step)
    engine = step_engine(cfg, step)
    eng = engine_label(engine)

    if step == "script":
        if mode == "local":
            sc = cfg.get("script") or {}
            if engine == "local_whisper":
                return f"Whisper · {sc.get('whisper_model', 'small')}"
            if engine == "funasr":
                return f"FunASR · {sc.get('funasr_model', 'sensevoice')}"
            return eng
        cloud_sc = cfg.get("script", {}).get("cloud") or {}
        cdn_key = bool(((cloud_sc.get("cdn") or {}).get("api_key") or "").strip())
        tr_key = bool(((cloud_sc.get("transcript") or {}).get("api_key") or "").strip())
        cdn_label = "已配置" if cdn_key else "未配置（跳过）"
        asr_label = "已配置" if tr_key else "未配置"
        return f"云端 · CDN {cdn_label} · ASR {asr_label}"

    if step == "tts":
        return eng

    if step == "avatar":
        if mode == "local":
            if engine == "heygem":
                return "HeyGem + LatentSync 实拍可选"
            if engine == "latentsync":
                return f"{eng}（实拍）"
            return eng
        return f"{eng}（待接入 API）"

    if mode == "cloud":
        return f"{eng}（待接入 API）"
    return eng

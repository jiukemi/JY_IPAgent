"""Per-engine model settings schema and config read/write for TTS step UI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from tts.backend_presets import preset_choices_for
from ui.global_settings import _apply_tts_engine
from workflow.app_config import CONFIG_PATH
from tts.engine_profiles import engine_profile
from workflow.deployment import normalize_tts_engine, step_engine, step_mode
from workflow.engine_catalog import engine_dropdown_choices, engine_label


def _mask_secret(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}…{value[-4:]}"


def engine_health(cfg: dict, engine: str, *, ping: bool = False) -> dict[str, Any]:
    engine = (engine or "").lower()
    if engine == "qwen3_tts":
        from tts.qwen3_tts import verify_qwen3_tts

        return verify_qwen3_tts(cfg, ping=ping)

    from workflow.engine_status import engine_health_status

    return engine_health_status(cfg, engine)

FieldDef = dict[str, Any]

ENGINE_FIELDS: dict[str, list[FieldDef]] = {
    "indextts": [
        {"section": "indextts", "name": "model_dir", "label": "模型目录", "type": "text"},
        {"section": "indextts", "name": "worker_enabled", "label": "常驻 Worker（启动预加载）", "type": "boolean"},
        {"section": "indextts", "name": "use_fp16", "label": "FP16 推理", "type": "boolean"},
        {"section": "indextts", "name": "use_emo_text", "label": "情感文本控制", "type": "boolean"},
        {"section": "indextts", "name": "max_text_tokens_per_segment", "label": "每段最大 token", "type": "number"},
        {"section": "indextts", "name": "interval_silence", "label": "段间静音 (ms)", "type": "number"},
        {"section": "indextts", "name": "temperature", "label": "Temperature", "type": "number", "step": 0.05},
        {"section": "indextts", "name": "top_p", "label": "Top-P", "type": "number", "step": 0.05},
        {"section": "indextts", "name": "top_k", "label": "Top-K", "type": "number"},
        {"section": "indextts", "name": "default_spk_wav", "label": "默认参考音", "type": "text"},
    ],
    "cosyvoice": [
        {"section": "cosyvoice", "name": "model_dir", "label": "模型目录", "type": "text"},
        {"section": "cosyvoice", "name": "default_sft_speaker", "label": "默认 SFT 说话人", "type": "text"},
        {"section": "cosyvoice", "name": "speed", "label": "语速倍率", "type": "number", "step": 0.1},
    ],
    "piper": [
        {"section": "piper", "name": "model", "label": "默认 Piper 模型路径", "type": "text"},
        {
            "section": "piper",
            "name": "preset_voice",
            "label": "UI 默认音色",
            "type": "select",
            "choices_from": "piper_voices",
            "persist": False,
        },
    ],
    "edge": [
        {
            "section": "tts",
            "name": "edge_voice",
            "label": "Edge 默认 Neural 音色",
            "type": "select",
            "choices_from": "edge_voices",
        },
    ],
    "qwen3_tts": [
        {"section": "qwen3_tts", "name": "model", "label": "预设合成模型", "type": "text"},
        {"section": "qwen3_tts", "name": "vc_model", "label": "克隆合成模型（与注册一致）", "type": "text"},
        {"section": "qwen3_tts", "name": "base_url", "label": "API Base URL", "type": "text"},
        {"section": "qwen3_tts", "name": "api_key", "label": "DashScope API Key", "type": "password"},
    ],
    "qwen3_local": [
        {
            "section": "qwen3_local",
            "name": "size",
            "label": "模型规格（0.6B≈4GB / 1.7B≈8GB 显存）",
            "type": "select",
            "choices_from": "qwen3_local_sizes",
        },
        {"section": "qwen3_local", "name": "device", "label": "推理设备（如 cuda:0）", "type": "text"},
        {"section": "qwen3_local", "name": "dtype", "label": "精度（bfloat16/float16/float32）", "type": "text"},
        {"section": "qwen3_local", "name": "attn_implementation", "label": "注意力实现（sdpa/flash_attention_2）", "type": "text"},
        {"section": "qwen3_local", "name": "default_speaker", "label": "默认说话人", "type": "text"},
    ],
}

CLOUD_ENGINE_HINTS: dict[str, dict[str, Any]] = {
    "qwen3_tts": {
        "title": "通义 Qwen3-TTS（DashScope）",
        "description": "配置 DashScope API Key 后可用。保存设置后可点「检测连接」验证。",
        "settings_keys": ["qwen3_tts_api_key"],
    },
    "volcengine": {
        "title": "火山引擎 TTS",
        "description": "火山引擎 TTS 接口预留中。请在全局设置选择引擎，接入后在此配置密钥。",
        "settings_keys": [],
        "check": lambda _cfg: False,
        "missing": "接口待接入，暂不可用",
    },
}


def _resolve_choices(choices_from: str) -> list[dict[str, str]]:
    if choices_from == "edge_voices":
        pairs = preset_choices_for("edge")
        return [{"value": p[1], "label": p[0]} for p in pairs]
    if choices_from == "piper_voices":
        pairs = preset_choices_for("piper")
        return [{"value": p[1], "label": p[0]} for p in pairs]
    if choices_from == "qwen3_local_sizes":
        return [
            {"value": "0.6B", "label": "0.6B（推荐起步 · 约 4GB+ 显存）"},
            {"value": "1.7B", "label": "1.7B（更高质量 · 约 8GB+ 显存）"},
        ]
    return []


def _field_value(cfg: dict, field: FieldDef) -> Any:
    section = cfg.get(field["section"]) or {}
    name = field["name"]
    if field.get("persist") is False and field["type"] == "select":
        val = section.get(name)
        if val is not None:
            return val
        if field.get("choices_from") == "piper_voices":
            model = (cfg.get("piper") or {}).get("model") or ""
            if model:
                stem = Path(str(model)).stem.replace(".onnx", "")
                return stem
        return ""
    return section.get(name, _default_for(field))


def _default_for(field: FieldDef) -> Any:
    if field["type"] == "boolean":
        return False
    if field["type"] == "number":
        return 0
    if field["section"] == "qwen3_local" and field["name"] == "size":
        return "0.6B"
    if field["section"] == "qwen3_local" and field["name"] == "device":
        return "cuda:0"
    if field["section"] == "qwen3_local" and field["name"] == "dtype":
        return "bfloat16"
    if field["section"] == "qwen3_local" and field["name"] == "attn_implementation":
        return "sdpa"
    if field["section"] == "qwen3_local" and field["name"] == "default_speaker":
        return "Vivian"
    return ""


def _serialize_field(field: FieldDef, raw: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "key": f"{field['section']}.{field['name']}",
        "section": field["section"],
        "name": field["name"],
        "label": field["label"],
        "type": field["type"],
        "value": raw,
    }
    if field["type"] == "password":
        secret = str(raw or "").strip()
        out["value"] = ""
        out["configured"] = bool(secret)
        out["hint"] = _mask_secret(secret) if secret else ""
    if field.get("step") is not None:
        out["step"] = field["step"]
    if field.get("choices_from"):
        out["choices"] = _resolve_choices(field["choices_from"])
    return out


def fields_for_engine(engine: str) -> list[FieldDef]:
    return list(ENGINE_FIELDS.get(engine, []))


def build_tts_options(cfg: dict, *, preview_engine: str | None = None) -> dict:
    mode = step_mode(cfg, "tts")
    engine = preview_engine or step_engine(cfg, "tts")
    profile = engine_profile(engine)
    choices = []
    for lbl, val in engine_dropdown_choices("tts", mode):
        prof = engine_profile(val)
        choices.append(
            {
                "value": val,
                "label": lbl,
                "hardware": prof.get("hardware", ""),
                "summary": prof.get("summary", ""),
            }
        )

    fields = [_serialize_field(f, _field_value(cfg, f)) for f in fields_for_engine(engine)]
    health = engine_health(cfg, engine, ping=False)
    preset_ready = bool(health.get("preset_ready", health.get("ok")))

    cloud_hint = None
    ready = bool(health.get("ok"))
    if engine == "qwen3_tts":
        ready = bool(health.get("ok"))
    if mode == "cloud":
        hint = CLOUD_ENGINE_HINTS.get(engine, {})
        if hint:
            ready = bool(health.get("ok"))
            cloud_hint = {
                "title": hint["title"],
                "description": hint["description"],
                "ready": ready,
                "missing": health.get("message") if not ready else "",
                "settings_keys": hint.get("settings_keys", []),
            }
        else:
            cloud_hint = {
                "title": engine_label(engine),
                "description": "请在全局设置中配置云端引擎与 API Key。",
                "ready": False,
                "missing": "请在全局设置完成配置",
                "settings_keys": [],
            }
            ready = False

    from tts.engine import load_presets

    clone_cfg = load_presets().get("clone") or {}
    scripts = clone_cfg.get("recording_scripts") or {}
    default_prompt = (scripts.get(engine) or scripts.get("indextts") or "").strip()

    return {
        "mode": mode,
        "mode_label": "本地" if mode == "local" else "云端",
        "engine": engine,
        "engine_label": engine_label(engine),
        "profile": profile,
        "engines": choices,
        "fields": fields,
        "cloud_hint": cloud_hint,
        "health": health,
        "ready": ready,
        "preset_ready": preset_ready,
        "clone_prompt_required": engine in ("cosyvoice", "qwen3_local"),
        "clone_default_prompt": default_prompt,
        "clone_hint": (clone_cfg.get("hint") or "").strip(),
    }


def save_tts_settings(
    *,
    engine: str | None = None,
    values: dict[str, Any] | None = None,
    cfg_path: Path | str = CONFIG_PATH,
) -> dict:
    path = Path(cfg_path)
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    mode = step_mode(cfg, "tts")

    if engine and mode == "local":
        dep = cfg.setdefault("deployment", {})
        engines = dep.setdefault("engines", {})
        tts_eng = engines.setdefault("tts", {})
        if not isinstance(tts_eng, dict):
            tts_eng = {}
            engines["tts"] = tts_eng
        engine = normalize_tts_engine("local", engine)
        tts_eng["local"] = engine
        _apply_tts_engine(cfg, "local", engine)

    if engine and mode == "cloud":
        dep = cfg.setdefault("deployment", {})
        engines = dep.setdefault("engines", {})
        tts_eng = engines.setdefault("tts", {})
        if not isinstance(tts_eng, dict):
            tts_eng = {}
            engines["tts"] = tts_eng
        engine = normalize_tts_engine("cloud", engine)
        tts_eng["cloud"] = engine
        _apply_tts_engine(cfg, "cloud", engine)

    if values:
        for full_key, raw in values.items():
            if "." not in full_key:
                continue
            section, name = full_key.split(".", 1)
            field = _find_field(section, name)
            if field and field.get("persist") is False:
                continue
            block = cfg.setdefault(section, {})
            if field and field["type"] == "password" and not str(raw or "").strip():
                continue
            block[name] = _coerce_value(field, raw)

    path.write_text(yaml.dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _find_field(section: str, name: str) -> FieldDef | None:
    for fields in ENGINE_FIELDS.values():
        for f in fields:
            if f["section"] == section and f["name"] == name:
                return f
    return None


def _coerce_value(field: FieldDef | None, raw: Any) -> Any:
    if field is None:
        return raw
    t = field["type"]
    if t == "boolean":
        if isinstance(raw, bool):
            return raw
        return str(raw).lower() in ("1", "true", "yes", "on")
    if t == "number":
        try:
            step = field.get("step")
            if step and float(step) < 1:
                return float(raw)
            return int(float(raw))
        except (TypeError, ValueError):
            return _default_for(field)
    return str(raw) if raw is not None else ""

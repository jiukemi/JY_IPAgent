"""Unified system + clone voice catalog (engine chosen automatically)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from tts.engine import load_presets
from tts.voices import get_voice, list_voices

EDGE_MANDARIN = {
    "zh-CN-XiaoxiaoNeural",
    "zh-CN-XiaoyiNeural",
    "zh-CN-YunxiNeural",
    "zh-CN-YunjianNeural",
    "zh-CN-YunxiaNeural",
    "zh-CN-YunyangNeural",
}
EDGE_DIALECT = {
    "zh-CN-liaoning-XiaobeiNeural",
    "zh-CN-shaanxi-XiaoniNeural",
    "zh-HK-HiuMaanNeural",
    "zh-HK-WanLungNeural",
    "zh-TW-HsiaoChenNeural",
}
EDGE_ENGLISH = {
    "en-US-AriaNeural",
    "en-US-GuyNeural",
    "en-US-JennyNeural",
    "en-US-ChristopherNeural",
}

CATEGORY_LABELS = {
    "mandarin": "普通话",
    "dialect": "方言",
    "english": "英语",
}


@dataclass(frozen=True)
class VoiceEntry:
    uid: str
    label: str
    category: str
    backend: str
    mode: str
    preset_id: str
    hint: str = ""
    clone_id: str = ""
    reference_wav: str = ""

    @property
    def card_label(self) -> str:
        return self.label


def _sys_uid(backend: str, key: str) -> str:
    return f"sys:{backend}:{key}"


def _piper_dir() -> Path:
    try:
        from workflow.app_config import load_cfg
        from workflow.engine_dirs import resolve_engine_dir

        return resolve_engine_dir(
            load_cfg(),
            path_key="piper_dir",
            default_rel="tools/Piper",
            runtime_name="Piper",
            markers=("zh_CN-huayan-medium.onnx",),
        )
    except Exception:
        cfg_path = Path("config.yaml")
        if cfg_path.exists():
            try:
                cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
                return Path(cfg["paths"]["piper_dir"])
            except (KeyError, TypeError, yaml.YAMLError):
                pass
        return Path("tools/Piper")


def _style_entries_for_backend(backend: str) -> list[VoiceEntry]:
    """Preset + dialect voices for indextts / cosyvoice from backend_catalog."""
    data = load_presets()
    cat = data.get("backend_catalog", {}).get(backend, {})
    if not cat:
        return []
    entries: list[VoiceEntry] = []
    for key in cat.get("preset_keys", []):
        item = data.get("presets", {}).get(key) or data.get("english_presets", {}).get(key)
        if not item:
            continue
        cat_name = "english" if key in data.get("english_presets", {}) else "mandarin"
        entries.append(
            VoiceEntry(
                uid=_sys_uid(backend, key),
                label=item["label"],
                category=cat_name,
                backend=backend,
                mode="preset",
                preset_id=key,
            )
        )
    for key in cat.get("dialect_keys", []):
        item = data.get("dialects", {}).get(key)
        if not item:
            continue
        entries.append(
            VoiceEntry(
                uid=_sys_uid(backend, f"dialect:{key}"),
                label=item["label"],
                category="dialect",
                backend=backend,
                mode="dialect",
                preset_id=key,
                hint=item.get("hint", ""),
            )
        )
    return entries


def _build_system_entries() -> list[VoiceEntry]:
    data = load_presets()
    entries: list[VoiceEntry] = []

    for backend in ("indextts", "cosyvoice"):
        entries.extend(_style_entries_for_backend(backend))
    piper_dir = _piper_dir()
    piper_voices = data.get("backend_catalog", {}).get("piper", {}).get("voices", {})
    for key, item in piper_voices.items():
        model_file = item.get("model_file", f"{key}.onnx")
        if not (piper_dir / model_file).exists():
            continue
        entries.append(
            VoiceEntry(
                uid=_sys_uid("piper", key),
                label=item["label"],
                category="mandarin",
                backend="piper",
                mode="preset",
                preset_id=key,
            )
        )

    edge_voices = data.get("backend_catalog", {}).get("edge", {}).get("voices", {})
    for key, item in edge_voices.items():
        if key in EDGE_MANDARIN:
            cat = "mandarin"
        elif key in EDGE_DIALECT:
            cat = "dialect"
        elif key in EDGE_ENGLISH:
            cat = "english"
        else:
            cat = "mandarin"
        entries.append(
            VoiceEntry(
                uid=_sys_uid("edge", key),
                label=item["label"],
                category=cat,
                backend="edge",
                mode="preset",
                preset_id=key,
            )
        )

    qwen_voices = data.get("backend_catalog", {}).get("qwen3_tts", {}).get("voices", {})
    for key, item in qwen_voices.items():
        cat = "english" if key.startswith("en_") else "mandarin"
        entries.append(
            VoiceEntry(
                uid=_sys_uid("qwen3_tts", key),
                label=item["label"],
                category=cat,
                backend="qwen3_tts",
                mode="preset",
                preset_id=key,
            )
        )

    local_qwen = data.get("backend_catalog", {}).get("qwen3_local", {}).get("voices", {})
    for key, item in local_qwen.items():
        cat = (item.get("category") or "mandarin").strip() or "mandarin"
        if cat not in ("mandarin", "dialect", "english"):
            cat = "mandarin"
        entries.append(
            VoiceEntry(
                uid=_sys_uid("qwen3_local", key),
                label=item["label"],
                category=cat,
                backend="qwen3_local",
                mode="dialect" if cat == "dialect" else "preset",
                preset_id=key,
                hint=item.get("hint", ""),
            )
        )

    return entries


def _build_clone_entries() -> list[VoiceEntry]:
    entries: list[VoiceEntry] = []
    for v in list_voices():
        backend = v.get("backend", "indextts")
        entries.append(
            VoiceEntry(
                uid=f"clone:{v['id']}",
                label=v["name"],
                category="clone",
                backend=backend,
                mode="clone",
                preset_id="",
                clone_id=v["id"],
                reference_wav=v.get("reference_wav", ""),
            )
        )
    return entries


_CATALOG: dict[str, VoiceEntry] | None = None


def catalog_map() -> dict[str, VoiceEntry]:
    global _CATALOG
    if _CATALOG is None:
        _CATALOG = {}
        for e in _build_system_entries():
            _CATALOG[e.uid] = e
        for e in _build_clone_entries():
            _CATALOG[e.uid] = e
    return _CATALOG


def refresh_catalog() -> None:
    global _CATALOG
    _CATALOG = None


def list_system_voices(category: str | None = None) -> list[VoiceEntry]:
    entries = _build_system_entries()
    if not category:
        return entries
    return [e for e in entries if e.category == category]


def list_voices_for_tts_engine(engine: str) -> tuple[list[VoiceEntry], list[VoiceEntry]]:
    """System + clone voices for one TTS backend only."""
    engine = (engine or "indextts").lower()

    all_system = _build_system_entries()
    system = [e for e in all_system if e.backend == engine]

    clones = _build_clone_entries()
    if engine == "qwen3_tts":
        clones = [e for e in clones if e.backend == "qwen3_tts"]
    elif engine in ("piper", "edge"):
        clones = []
    else:
        clones = [e for e in clones if e.backend == engine]

    return system, clones


_DEFAULT_VOICE: dict[str, str] = {
    "indextts": "sys:indextts:mandarin_female_warm",
    "cosyvoice": "sys:cosyvoice:mandarin_female_warm",
    "edge": "sys:edge:zh-CN-XiaoxiaoNeural",
    "piper": "sys:piper:zh_CN-huayan-medium",
    "qwen3_tts": "sys:qwen3_tts:mandarin_female_warm",
    "qwen3_local": "sys:qwen3_local:vivian",
}


def default_voice_uid_for_engine(engine: str, category: str = "mandarin") -> str:
    system, clones = list_voices_for_tts_engine(engine)
    preferred = _DEFAULT_VOICE.get((engine or "indextts").lower())
    for pool in (system, clones):
        if preferred and any(v.uid == preferred for v in pool):
            return preferred
        cat_match = [v for v in pool if v.category == category]
        if cat_match:
            return cat_match[0].uid
        if pool:
            return pool[0].uid
    return ""


def list_clone_voices() -> list[VoiceEntry]:
    return _build_clone_entries()


def get_voice_entry(uid: str) -> VoiceEntry | None:
    if uid.startswith("clone:"):
        return _build_clone_entries_map().get(uid)
    return catalog_map().get(uid)


def _build_clone_entries_map() -> dict[str, VoiceEntry]:
    return {e.uid: e for e in _build_clone_entries()}


def default_system_uid(category: str = "mandarin") -> str:
    voices = list_system_voices(category)
    if not voices:
        return ""
    for preferred in (
        "sys:indextts:mandarin_female_warm",
        "sys:edge:zh-CN-XiaoxiaoNeural",
        "sys:piper:zh_CN-huayan-medium",
    ):
        if any(v.uid == preferred for v in voices):
            return preferred
    return voices[0].uid


def resolve_synthesis(uid: str) -> dict:
    entry = get_voice_entry(uid)
    if not entry:
        raise ValueError(f"未知音色: {uid}")

    if entry.mode == "clone":
        voice = get_voice(entry.clone_id)
        if not voice:
            raise ValueError("克隆音色不存在，可能已被删除")
        backend = voice.get("backend", "indextts")
        return {
            "backend": backend,
            "mode": "clone",
            "preset_id": "",
            "saved_voice_id": entry.clone_id,
            "style_extra": "",
        }

    return {
        "backend": entry.backend,
        "mode": entry.mode,
        "preset_id": entry.preset_id,
        "saved_voice_id": None,
        "style_extra": "",
    }


def selected_label(uid: str) -> str:
    entry = get_voice_entry(uid)
    if not entry:
        return "（未选择）"
    return entry.label

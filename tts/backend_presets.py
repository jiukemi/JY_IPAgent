"""Per-backend preset / dialect catalogs for the TTS UI."""

from __future__ import annotations

from pathlib import Path

from ui.gradio_compat import gr

from tts.backends import get_backend
from tts.engine import load_presets
from tts.voices import list_voices

MODE_LABELS: dict[str, str] = {
    "preset": "预设音色",
    "dialect": "方言",
    "clone": "已保存克隆音色",
    "custom": "自定义描述",
    "upload": "跳过 · 上传音频",
}


def _catalog(backend: str) -> dict:
    data = load_presets()
    return data.get("backend_catalog", {}).get(backend, {})


def mode_choices_for(backend: str) -> list[tuple[str, str]]:
    modes = _catalog(backend).get("modes") or get_backend(backend).get("modes")
    if not modes:
        info = get_backend(backend)
        modes = ["preset", "upload"]
        if info.get("supports_dialect"):
            modes = ["preset", "dialect", "clone", "custom", "upload"]
        elif info.get("supports_clone"):
            modes = ["clone", "upload"]
    return [(MODE_LABELS.get(m, m), m) for m in modes]


def _style_preset_entry(data: dict, key: str) -> tuple[str, str] | None:
    for section in ("presets", "english_presets"):
        entry = data.get(section, {}).get(key)
        if entry:
            return entry["label"], key
    return None


def preset_choices_for(backend: str) -> list[tuple[str, str]]:
    data = load_presets()
    cat = _catalog(backend)
    choices: list[tuple[str, str]] = []

    for key in cat.get("preset_keys", []):
        item = _style_preset_entry(data, key)
        if item:
            choices.append(item)

    for key, entry in cat.get("voices", {}).items():
        choices.append((entry["label"], key))

    if backend in ("indextts", "cosyvoice") and not choices:
        for key, entry in data.get("presets", {}).items():
            choices.append((entry["label"], key))
        for key, entry in data.get("english_presets", {}).items():
            choices.append((entry["label"], key))

    return choices


def dialect_choices_for(backend: str) -> list[tuple[str, str]]:
    info = get_backend(backend)
    if not info.get("supports_dialect"):
        return []
    data = load_presets()
    cat = _catalog(backend)
    keys = cat.get("dialect_keys") or list(data.get("dialects", {}).keys())
    choices: list[tuple[str, str]] = []
    for key in keys:
        entry = data.get("dialects", {}).get(key)
        if entry:
            choices.append((entry["label"], key))
    return choices


def default_preset_for(backend: str) -> str:
    choices = preset_choices_for(backend)
    if not choices:
        return ""
    defaults = {
        "indextts": "mandarin_female_warm",
        "cosyvoice": "mandarin_female_warm",
        "piper": "zh_CN-huayan-medium",
        "edge": "zh-CN-XiaoxiaoNeural",
        "qwen3_local": "vivian",
        "qwen3_tts": "mandarin_female_warm",
    }
    preferred = defaults.get(backend)
    ids = [c[1] for c in choices]
    if preferred and preferred in ids:
        return preferred
    return ids[0]


def default_dialect_for(backend: str) -> str:
    choices = dialect_choices_for(backend)
    return choices[0][1] if choices else ""


def pick_valid_choice(current: str, choices: list[tuple[str, str]], fallback: str) -> str | None:
    ids = [c[1] for c in choices]
    if not choices:
        return None
    if current in ids:
        return current
    if fallback in ids:
        return fallback
    return ids[0]


def dropdown_update(
    choices: list[tuple[str, str]],
    value: str | None,
    *,
    visible: bool = True,
    fallback: str = "",
):
    """Gradio rejects value='' when choices is empty — use None instead."""
    resolved = pick_valid_choice(value or "", choices, fallback)
    return gr.update(choices=choices, value=resolved, visible=visible)


def voice_choices_for_backend(backend: str) -> list[tuple[str, str]]:
    items = [v for v in list_voices() if v.get("backend", "indextts") == backend]
    if not items:
        label = {
            "indextts": "（暂无 IndexTTS 音色，请去新增克隆）",
            "cosyvoice": "（暂无 CosyVoice 音色，请去新增克隆）",
        }.get(backend, "（暂无克隆音色）")
        return [(label, "")]
    return [(v["name"], v["id"]) for v in items]


def resolve_piper_model(cfg: dict, preset_id: str) -> Path:
    data = load_presets()
    entry = data.get("backend_catalog", {}).get("piper", {}).get("voices", {}).get(preset_id, {})
    model_file = entry.get("model_file") or f"{preset_id}.onnx"
    piper_dir = Path(cfg["paths"]["piper_dir"])
    path = piper_dir / model_file
    if not path.exists():
        raise FileNotFoundError(
            f"Piper 模型未安装: {path.name}，请运行 scripts/setup/setup_piper.ps1 或下载对应 .onnx"
        )
    return path


def resolve_edge_voice(preset_id: str) -> str:
    data = load_presets()
    entry = data.get("backend_catalog", {}).get("edge", {}).get("voices", {}).get(preset_id)
    if entry:
        return entry["voice"]
    return preset_id


def backend_voice_note(backend: str) -> str:
    info = get_backend(backend)
    setup = info.get("setup") or "无需"
    note = f"**{info['label']}** — 安装: `{setup}`"
    presets = preset_choices_for(backend)
    dialects = dialect_choices_for(backend)
    if backend == "piper":
        note += f"（{len(presets)} 个 Piper 音色，极速 CPU，不支持克隆/方言）"
    elif backend == "edge":
        note += f"（{len(presets)} 个在线 Neural 音色，不支持克隆/方言）"
    elif backend == "indextts":
        note += f"（{len(presets)} 个预设 · {len(dialects)} 种方言 · 支持克隆与情感）"
    elif backend == "cosyvoice":
        note += f"（{len(presets)} 个预设 · {len(dialects)} 种方言 · 支持克隆）"
    elif backend == "qwen3_local":
        note += f"（{len(presets)} 个内置音色 · 支持克隆 · 需 GPU）"
    elif backend == "qwen3_tts":
        note += f"（{len(presets)} 个云端预设 · 需 DashScope Key）"
    return note

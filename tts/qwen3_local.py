"""Local open-source Qwen3-TTS (CustomVoice presets + Base clone)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

SIZE_SPECS: dict[str, dict[str, str]] = {
    "0.6B": {
        "custom": "Qwen3-TTS-12Hz-0.6B-CustomVoice",
        "base": "Qwen3-TTS-12Hz-0.6B-Base",
        "hf_custom": "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice",
        "hf_base": "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
        "min_vram_gb": "4",
    },
    "1.7B": {
        "custom": "Qwen3-TTS-12Hz-1.7B-CustomVoice",
        "base": "Qwen3-TTS-12Hz-1.7B-Base",
        "hf_custom": "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
        "hf_base": "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
        "min_vram_gb": "8",
    },
}


def qwen3_local_block(cfg: dict) -> dict:
    return cfg.get("qwen3_local") or {}


def resolve_install_dir(cfg: dict) -> Path:
    try:
        from workflow.engine_dirs import resolve_engine_dir

        return resolve_engine_dir(
            cfg,
            path_key="qwen3_local_dir",
            default_rel="tools/Qwen3-TTS",
            runtime_name="Qwen3-TTS",
            markers=("models",),
        )
    except Exception:
        raw = (cfg.get("paths") or {}).get("qwen3_local_dir", "tools/Qwen3-TTS")
        path = Path(raw)
        if not path.is_absolute():
            path = ROOT / path
        return path


def normalize_size(size: str | None) -> str:
    raw = (size or "0.6B").strip().upper().replace(" ", "")
    if raw in ("1.7", "1.7B", "17B"):
        return "1.7B"
    return "0.6B"


def size_spec(cfg: dict) -> dict[str, str]:
    size = normalize_size(qwen3_local_block(cfg).get("size"))
    return SIZE_SPECS[size]


def custom_voice_dir(cfg: dict) -> Path:
    block = qwen3_local_block(cfg)
    install = resolve_install_dir(cfg)
    rel = (block.get("custom_voice_dir") or f"models/{size_spec(cfg)['custom']}").strip()
    path = Path(rel)
    return path if path.is_absolute() else install / path


def base_model_dir(cfg: dict) -> Path:
    block = qwen3_local_block(cfg)
    install = resolve_install_dir(cfg)
    rel = (block.get("base_model_dir") or f"models/{size_spec(cfg)['base']}").strip()
    path = Path(rel)
    return path if path.is_absolute() else install / path


def _model_ready(path: Path) -> bool:
    if not path.is_dir():
        return False
    # HF/ModelScope layouts vary; config + weights is enough signal
    markers = (
        "config.json",
        "model.safetensors",
        "model.safetensors.index.json",
        "pytorch_model.bin",
    )
    return any((path / m).exists() for m in markers) or any(path.glob("*.safetensors"))


def resolve_speaker(cfg: dict, preset_id: str) -> tuple[str, str]:
    """Return (speaker_id, language_type) for CustomVoice."""
    from tts.engine import load_presets

    cat = load_presets().get("backend_catalog", {}).get("qwen3_local", {}).get("voices", {})
    entry = cat.get(preset_id) or {}
    if entry:
        return (
            (entry.get("voice") or entry.get("speaker") or "Vivian").strip(),
            (entry.get("language_type") or "Chinese").strip(),
        )
    default = (qwen3_local_block(cfg).get("default_speaker") or "Vivian").strip()
    return default, "Chinese"


def verify_qwen3_local(cfg: dict) -> dict[str, Any]:
    from tts.engine import venv_python
    import sys

    size = normalize_size(qwen3_local_block(cfg).get("size"))
    spec = SIZE_SPECS[size]
    install = resolve_install_dir(cfg)
    custom = custom_voice_dir(cfg)
    base = base_model_dir(cfg)
    py = venv_python(cfg, "qwen3_local_dir")
    venv_ok = py != sys.executable and Path(py).is_file()
    custom_ok = _model_ready(custom)
    base_ok = _model_ready(base)
    missing: list[str] = []
    if not venv_ok:
        missing.append("Python 虚拟环境未安装（运行 scripts/setup/setup_qwen3_local.ps1）")
    if not custom_ok:
        missing.append(f"内置音色模型未安装：{custom.name}")
    if not base_ok:
        missing.append(f"克隆 Base 模型未安装：{base.name}（克隆需要）")
    ready = venv_ok and custom_ok
    return {
        "ok": ready,
        "configured": venv_ok,
        "preset_ready": ready,
        "clone_ready": venv_ok and base_ok,
        "size": size,
        "min_vram_gb": float(spec["min_vram_gb"]),
        "install_dir": str(install),
        "custom_voice_dir": str(custom),
        "base_model_dir": str(base),
        "missing": missing,
        "message": "；".join(missing) if missing else f"本地 Qwen3-TTS {size} 已就绪",
    }

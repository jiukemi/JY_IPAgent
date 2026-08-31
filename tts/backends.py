"""TTS backend registry."""

from __future__ import annotations

BACKENDS: dict[str, dict] = {
    "indextts": {
        "label": "IndexTTS2（推荐：中英混读 / 克隆 / 情感）",
        "supports_clone": True,
        "supports_dialect": True,
        "needs_gpu": True,
        "setup": "setup_indextts.ps1",
    },
    "cosyvoice": {
        "label": "CosyVoice2（备选克隆 · 英文较弱）",
        "supports_clone": True,
        "supports_dialect": True,
        "needs_gpu": True,
        "setup": "setup_cosyvoice.ps1",
    },
    "piper": {
        "label": "Piper（极速 CPU，无克隆）",
        "supports_clone": False,
        "supports_dialect": False,
        "needs_gpu": False,
        "setup": "setup_piper.ps1",
    },
    "edge": {
        "label": "Edge-TTS（在线备选，最快）",
        "supports_clone": False,
        "supports_dialect": False,
        "needs_gpu": False,
        "setup": None,
    },
    "qwen3_local": {
        "label": "Qwen3-TTS 本地（开源 · 英文较弱）",
        "supports_clone": True,
        "supports_dialect": True,
        "needs_gpu": True,
        "setup": "setup_qwen3_local.ps1",
    },
}


def backend_choices() -> list[tuple[str, str]]:
    return [(v["label"], k) for k, v in BACKENDS.items()]


def get_backend(name: str) -> dict:
    return BACKENDS.get(name, BACKENDS["indextts"])


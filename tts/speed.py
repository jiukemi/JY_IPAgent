"""TTS speed / quality presets."""

from __future__ import annotations

SPEED_PRESETS: dict[str, dict] = {
    "fast": {
        "label": "极速（GPU，步数少）",
        "indextts": {"temperature": 0.75, "top_p": 0.75, "top_k": 25, "max_text_tokens_per_segment": 80},
    },
    "balanced": {
        "label": "平衡",
        "indextts": {"temperature": 0.8, "top_p": 0.8, "top_k": 30, "max_text_tokens_per_segment": 72},
    },
    "quality": {
        "label": "高质量（更慢）",
        "indextts": {"temperature": 0.85, "top_p": 0.85, "top_k": 35, "max_text_tokens_per_segment": 140},
    },
}


def get_speed_preset(name: str) -> dict:
    return SPEED_PRESETS.get(name or "balanced", SPEED_PRESETS["balanced"])


def speed_choices() -> list[tuple[str, str]]:
    return [(v["label"], k) for k, v in SPEED_PRESETS.items()]


def speed_choices_for_engine(engine: str) -> list[tuple[str, str]]:
    """Return speed presets applicable to the active TTS backend."""
    eng = (engine or "indextts").lower()
    if eng == "indextts":
        return speed_choices()
    return []

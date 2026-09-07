"""TTS package — keep imports lazy so IndexTTS/Cosy subprocess venvs stay light."""

from __future__ import annotations

__all__ = [
    "build_tts_text",
    "load_presets",
    "synthesize",
    "list_voices",
    "save_voice",
    "voice_choices",
]


def __getattr__(name: str):
    if name in ("build_tts_text", "load_presets", "synthesize"):
        from tts import engine as _engine

        return getattr(_engine, name)
    if name in ("list_voices", "save_voice", "voice_choices"):
        from tts import voices as _voices

        return getattr(_voices, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

"""Per-step engine catalogs for global settings (local / cloud)."""

from __future__ import annotations

from typing import Literal

Mode = Literal["local", "cloud"]

# (value, label) — listed in UI order; first local TTS = recommended default
STEP_ENGINE_CHOICES: dict[str, dict[str, list[tuple[str, str]]]] = {
    "script": {
        "local": [
            ("funasr", "本地 FunASR / SenseVoice（推荐）"),
            ("local_whisper", "本地 Whisper 转写"),
            ("local_file_only", "仅本地上传（不解析分享链接）"),
        ],
        "cloud": [
            ("cloud_parse", "云端解析 · CDN + ASR 接口"),
            ("cloud_17zhiling", "云端解析 · CDN + ASR 接口"),
            ("cloud_kuhuyun", "云端解析 · ASR 接口"),
        ],
    },
    "tts": {
        "local": [
            ("indextts", "IndexTTS2（推荐 · 本地 GPU）"),
            ("cosyvoice", "CosyVoice2（本地 GPU · 约 6GB · 性价比高）"),
            ("qwen3_local", "Qwen3-TTS 本地（开源 · 0.6B/1.7B）"),
            ("piper", "Piper（轻量 CPU）"),
            ("edge", "Edge-TTS（微软在线，免 GPU）"),
        ],
        "cloud": [
            ("qwen3_tts", "通义 Qwen3-TTS（DashScope 云端 API）"),
            ("volcengine", "火山引擎 TTS（预留）"),
        ],
    },
    "avatar": {
        "local": [
            ("heygem", "HeyGem（参考视频 · Docker 侧车）"),
            ("sadtalker", "SadTalker"),
            ("latentsync", "LatentSync（实拍精修 · 很慢）"),
        ],
        "cloud": [
            ("volcengine", "火山 · 单图/视频驱动（预留）"),
            ("heygem_cloud", "HeyGem 云端（预留）"),
        ],
    },
    "publish": {
        "local": [
            ("ffmpeg", "FFmpeg 字幕 / 封面 / 合成"),
        ],
        "cloud": [
            ("volcengine", "火山发布合成（预留）"),
        ],
    },
}

WHISPER_MODEL_CHOICES: list[tuple[str, str]] = [
    ("tiny", "tiny（最快）"),
    ("base", "base"),
    ("small", "small（默认）"),
    ("medium", "medium"),
    ("large-v3", "large-v3（最准最慢）"),
]

ENGINE_LABELS: dict[str, str] = {}
for _step, modes in STEP_ENGINE_CHOICES.items():
    for _mode, pairs in modes.items():
        for val, label in pairs:
            ENGINE_LABELS[val] = label.split("（")[0].split(" · ")[0]


def engine_choices(step: str, mode: str) -> list[tuple[str, str]]:
    """Internal list of (engine_id, label)."""
    mode = (mode or "local").lower()
    if mode not in ("local", "cloud"):
        mode = "local"
    return list(STEP_ENGINE_CHOICES.get(step, {}).get(mode, []))


def engine_dropdown_choices(step: str, mode: str) -> list[tuple[str, str]]:
    """Gradio Dropdown: (display label, stored value)."""
    return [(label, val) for val, label in engine_choices(step, mode)]


def whisper_dropdown_choices() -> list[tuple[str, str]]:
    return [(label, val) for val, label in WHISPER_MODEL_CHOICES]


def default_engine(step: str, mode: str) -> str:
    choices = engine_choices(step, mode)
    return choices[0][0] if choices else ""


def engine_label(engine_id: str) -> str:
    return ENGINE_LABELS.get(engine_id, engine_id or "—")

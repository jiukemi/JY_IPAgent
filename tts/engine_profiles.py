"""Per-engine capability and hardware requirements for TTS UI."""

from __future__ import annotations

ENGINE_PROFILES: dict[str, dict] = {
    "indextts": {
        "label": "IndexTTS2",
        "hardware": "NVIDIA GPU / 8GB+ VRAM recommended / 16GB RAM",
        "supports_clone": True,
        "supports_dialect": True,
        "supports_speed": True,
        "online": False,
        "summary": "Local flagship: clone, emotion, dialects; best for CN+EN mixed scripts",
        "setup": "setup_indextts.ps1",
    },
    "cosyvoice": {
        "label": "CosyVoice2",
        "hardware": "NVIDIA GPU / 6GB+ VRAM / 16GB RAM",
        "supports_clone": True,
        "supports_dialect": True,
        "supports_speed": False,
        "online": False,
        "summary": "Clone backup; weaker on English brands (may spell); needs matching prompt text",
        "setup": "setup_cosyvoice.ps1",
    },
    "piper": {
        "label": "Piper",
        "hardware": "CPU only / 4GB RAM / no GPU",
        "supports_clone": False,
        "supports_dialect": False,
        "supports_speed": False,
        "online": False,
        "summary": "Lightweight offline presets; fastest; no clone",
        "setup": "setup_piper.ps1",
    },
    "edge": {
        "label": "Edge-TTS",
        "hardware": "Online / no GPU / Microsoft Neural",
        "supports_clone": False,
        "supports_dialect": True,
        "supports_speed": False,
        "online": True,
        "summary": "Online Neural voices; no install; no clone",
        "setup": None,
    },
    "qwen3_tts": {
        "label": "Qwen3-TTS Cloud",
        "hardware": "DashScope API / no local GPU",
        "supports_clone": True,
        "supports_dialect": False,
        "supports_speed": False,
        "online": True,
        "summary": "Cloud API (DashScope); for local weights use Qwen3-TTS Local",
        "setup": None,
    },
    "qwen3_local": {
        "label": "Qwen3-TTS Local",
        "hardware": "NVIDIA GPU / 0.6B needs 4GB+ VRAM / 1.7B needs 8GB+",
        "supports_clone": True,
        "supports_dialect": True,
        "supports_speed": False,
        "online": False,
        "summary": "Open-source local; 0.6B weak on English; prefer IndexTTS for mixed CN–EN",
        "setup": "setup_qwen3_local.ps1",
    },
    "whisper": {
        "label": "Whisper ASR",
        "hardware": "CPU / optional GPU / 4GB+ RAM",
        "supports_clone": False,
        "supports_dialect": False,
        "supports_speed": False,
        "online": False,
        "summary": "Local speech-to-text for script step",
        "setup": "setup_whisper.ps1",
    },
    "funasr": {
        "label": "FunASR SenseVoice",
        "hardware": "CPU / optional GPU / 4GB+ RAM",
        "supports_clone": False,
        "supports_dialect": False,
        "supports_speed": False,
        "online": False,
        "summary": "Local Chinese ASR for script step (recommended)",
        "setup": "setup_funasr.ps1",
    },
    "ffmpeg": {
        "label": "FFmpeg",
        "hardware": "CPU / no GPU",
        "supports_clone": False,
        "supports_dialect": False,
        "supports_speed": False,
        "online": False,
        "summary": "Subtitles / cover / mux; skipped on first boot — install here or on first media use",
        "setup": "setup_ffmpeg.ps1",
    },
    "heygem": {
        "label": "HeyGem",
        "hardware": "NVIDIA GPU / Docker / 6GB+ VRAM",
        "supports_clone": False,
        "supports_dialect": False,
        "supports_speed": False,
        "online": False,
        "summary": "Digital human lipsync sidecar",
        "setup": "setup_heygem.ps1",
    },
}


# Chinese UI copy (kept separate so source file stays ASCII-safe on Windows)
_UI_ZH: dict[str, dict[str, str]] = {
    "indextts": {
        "hardware": "NVIDIA GPU · 8GB+ 显存推荐 · 16GB 内存",
        "summary": "本地旗舰：中英混读最稳；克隆/情感/方言最全（口播推荐）",
    },
    "cosyvoice": {
        "hardware": "NVIDIA GPU · 6GB+ 显存 · 16GB 内存",
        "summary": "克隆备选（须填参考文案）；英文品牌易逐字母读，中英混读不如 IndexTTS",
    },
    "piper": {
        "hardware": "纯 CPU · 4GB 内存即可 · 无需显卡",
        "summary": "轻量离线，仅预设 Neural 音色，速度最快",
    },
    "edge": {
        "hardware": "联网 · 无需 GPU · 微软在线服务",
        "summary": "在线 Neural 音色，免安装，不支持克隆",
    },
    "qwen3_tts": {
        "hardware": "云端 DashScope API · 无需本地 GPU",
        "summary": "云端 API（DashScope）；本地开源版请选「Qwen3-TTS 本地」",
    },
    "qwen3_local": {
        "hardware": "NVIDIA GPU · 0.6B约4GB+ / 1.7B约8GB+ 显存",
        "summary": "开源本地；默认 0.6B 英文弱；中英混读请用 IndexTTS（或换 1.7B）",
    },
    "whisper": {
        "hardware": "CPU / 可选 GPU · 4GB+ 内存",
        "summary": "文案步骤本地转写（faster-whisper）",
    },
    "funasr": {
        "hardware": "CPU / 可选 GPU · 4GB+ 内存",
        "summary": "文案步骤本地转写（SenseVoice，中文推荐）",
    },
    "ffmpeg": {
        "hardware": "纯 CPU · 无需显卡",
        "summary": "字幕/封面/合成必备；首启不下，设置一键装或首次用到时拉取",
    },
    "heygem": {
        "hardware": "NVIDIA GPU · Docker · 6GB+ 显存",
        "summary": "口播数字人侧车（需 Docker Desktop）",
    },
}


def engine_profile(engine: str) -> dict:
    eng = (engine or "indextts").lower()
    base = ENGINE_PROFILES.get(eng, {})
    zh = _UI_ZH.get(eng, {})
    return {
        "engine": eng,
        "label": base.get("label", eng),
        "hardware": zh.get("hardware") or base.get("hardware", ""),
        "supports_clone": bool(base.get("supports_clone")),
        "supports_dialect": bool(base.get("supports_dialect")),
        "supports_speed": bool(base.get("supports_speed")),
        "online": bool(base.get("online")),
        "summary": zh.get("summary") or base.get("summary", ""),
        "setup": base.get("setup"),
    }

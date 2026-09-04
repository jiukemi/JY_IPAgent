"""Local preview audio for unified voice picker (pre-built, read-only in UI)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from tts.engine import load_presets, synthesize
from tts.voice_catalog import VoiceEntry, get_voice_entry, resolve_synthesis

PREVIEW_ROOT = Path("data/voice_previews")
MANIFEST_PATH = PREVIEW_ROOT / "manifest.json"
PREVIEW_MIN_BYTES = 500

SAMPLE_TEXT = {
    "mandarin": "你好，这是音色试听示例，欢迎使用智能配音。",
    "dialect": "伙计，这是方言试听示例，效果仅供参考。",
    "english": "Hello, this is a short voice preview sample.",
}


def _safe_name(uid: str) -> str:
    return re.sub(r"[^\w.\-]+", "_", uid)


def preview_path(uid: str) -> Path:
    return PREVIEW_ROOT / f"{_safe_name(uid)}.wav"


def dialect_sample_text(preset_id: str) -> str:
    data = load_presets()
    entry = data.get("dialects", {}).get(preset_id, {}) or {}
    sample = (entry.get("sample") or "").strip()
    if sample:
        return sample[:48]
    # 本地 Qwen3 CustomVoice 方言说话人（不在 dialects 段）
    local = (data.get("backend_catalog") or {}).get("qwen3_local", {}).get("voices", {}).get(preset_id) or {}
    if local:
        if preset_id == "dylan_beijing":
            return "今儿天气真不错，咱们出去遛遛弯儿。"
        if preset_id == "eric_sichuan":
            return "老板，整个火锅要微辣嘛，再来两瓶冰粉。"
        return SAMPLE_TEXT["dialect"]
    if preset_id == "cantonese":
        return "伙计，唔该一杯冻奶茶少甜。"
    if preset_id == "sichuan":
        return "老板，整个火锅要微辣嘛。"
    hint = (entry.get("hint") or "").strip()
    return hint[:40] or SAMPLE_TEXT["dialect"]


def sample_text_for(entry: VoiceEntry) -> str:
    if entry.mode == "clone":
        return SAMPLE_TEXT["mandarin"]
    if entry.category == "english":
        if entry.backend == "qwen3_local" and entry.preset_id == "ono_anna":
            return "こんにちは、これは音声サンプルです。"
        if entry.backend == "qwen3_local" and entry.preset_id == "sohee":
            return "안녕하세요, 짧은 음성 미리듣기입니다."
        return SAMPLE_TEXT["english"]
    if entry.category == "dialect":
        return dialect_sample_text(entry.preset_id)
    return SAMPLE_TEXT["mandarin"]


def build_preview(uid: str, cfg: dict, *, engine: str | None = None) -> tuple[str | None, str | None]:
    """Generate one preview file (used by build_previews.py only). Returns (path, error)."""
    entry = get_voice_entry(uid)
    if not entry or entry.mode == "clone":
        return None, "跳过克隆音色"
    if engine and entry.backend != engine:
        return None, f"音色引擎 {entry.backend} 与 {engine} 不一致"

    out = preview_path(uid)
    PREVIEW_ROOT.mkdir(parents=True, exist_ok=True)
    params = resolve_synthesis(uid)
    work = PREVIEW_ROOT / "_work" / _safe_name(uid)
    try:
        result = synthesize(
            cfg,
            sample_text_for(entry),
            work,
            mode=params["mode"],
            preset_id=params["preset_id"] or "mandarin_female_warm",
            style_extra="",
            saved_voice_id=params.get("saved_voice_id"),
            backend=params["backend"],
            speed="balanced",
        )
        src = Path(result["audio"])
        if src.exists() and src.stat().st_size > PREVIEW_MIN_BYTES:
            out.write_bytes(src.read_bytes())
            return str(out), None
        return None, "生成文件过小或为空"
    except Exception as exc:
        return None, str(exc)


def update_preview_manifest(uid: str, path: str) -> None:
    manifest: dict[str, str] = {}
    if MANIFEST_PATH.exists():
        try:
            manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = {}
    manifest[uid] = path
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def get_preview_path(uid: str) -> str | None:
    """Read cached preview only — never synthesize on UI click."""
    if not uid:
        return None

    if uid.startswith("clone:"):
        # 直接读音色库，避免每次重建整表目录
        from tts.voices import get_voice

        voice = get_voice(uid[len("clone:") :])
        if not voice:
            return None
        ref = Path(str(voice.get("reference_wav") or ""))
        return str(ref) if ref.is_file() else None

    path = preview_path(uid)
    if path.exists() and path.stat().st_size > PREVIEW_MIN_BYTES:
        return str(path)

    if MANIFEST_PATH.exists():
        try:
            manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
            cached = manifest.get(uid)
            if cached and Path(cached).exists():
                return cached
        except json.JSONDecodeError:
            pass
    return None

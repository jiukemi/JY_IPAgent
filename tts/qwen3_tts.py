"""DashScope Qwen3-TTS (HTTP API, no SDK required)."""

from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from tts.engine import load_presets
from tts.progress import stage_label

ProgressFn = Callable[[float, str], None]

# preset_id -> (voice, language_type)
_PRESET_VOICE_MAP: dict[str, tuple[str, str]] = {
    "mandarin_female_warm": ("Cherry", "Chinese"),
    "mandarin_male_steady": ("Ethan", "Chinese"),
    "mandarin_female_energetic": ("Serena", "Chinese"),
    "mandarin_male_friendly": ("Ryan", "Chinese"),
    "en_female_clear": ("Cherry", "English"),
    "en_male_warm": ("Ryan", "English"),
    "en_female_energetic": ("Serena", "English"),
    "en_male_narrator": ("Ethan", "English"),
}


def qwen3_block(cfg: dict) -> dict:
    return cfg.get("qwen3_tts") or {}


def api_endpoint(cfg: dict) -> str:
    base = (qwen3_block(cfg).get("base_url") or "https://dashscope.aliyuncs.com/api/v1").strip().rstrip("/")
    return f"{base}/services/aigc/multimodal-generation/generation"


def resolve_qwen3_voice(cfg: dict, preset_id: str) -> tuple[str, str]:
    cat = load_presets().get("backend_catalog", {}).get("qwen3_tts", {}).get("voices", {})
    entry = cat.get(preset_id) or cat.get(preset_id.replace("dialect:", ""))
    if entry:
        return entry.get("voice", "Cherry"), entry.get("language_type", "Auto")
    if preset_id in _PRESET_VOICE_MAP:
        return _PRESET_VOICE_MAP[preset_id]
    default = (qwen3_block(cfg).get("default_voice") or "Cherry").strip()
    lang = (qwen3_block(cfg).get("language_type") or "Chinese").strip()
    return default, lang


def _mask_key(key: str) -> str:
    key = (key or "").strip()
    if len(key) <= 8:
        return "****" if key else ""
    return f"{key[:4]}…{key[-4:]}"


def verify_qwen3_tts(cfg: dict, *, ping: bool = False) -> dict[str, Any]:
    """Config check; optional ping sends a minimal synthesis request."""
    q3 = qwen3_block(cfg)
    key = (q3.get("api_key") or "").strip()
    model = (q3.get("model") or "qwen3-tts-flash").strip()
    base_url = (q3.get("base_url") or "https://dashscope.aliyuncs.com/api/v1").strip()

    if not key:
        return {
            "ok": False,
            "configured": False,
            "reachable": False,
            "model": model,
            "api_key_hint": "",
            "message": "未配置 DashScope API Key",
        }

    result: dict[str, Any] = {
        "ok": True,
        "configured": True,
        "reachable": None,
        "model": model,
        "api_key_hint": _mask_key(key),
        "message": f"API Key 已配置（{_mask_key(key)}）",
    }

    if not ping:
        return result

    try:
        _call_api(
            cfg,
            text="测试",
            voice="Cherry",
            language_type="Chinese",
            timeout_sec=30,
        )
        result["reachable"] = True
        result["message"] = "DashScope 连接正常，Qwen3-TTS 可用"
    except Exception as exc:
        result["ok"] = False
        result["reachable"] = False
        result["message"] = f"DashScope 自检失败：{exc}"

    return result


def customization_endpoint(cfg: dict) -> str:
    base = (qwen3_block(cfg).get("base_url") or "https://dashscope.aliyuncs.com/api/v1").strip().rstrip("/")
    return f"{base}/services/audio/tts/customization"


def vc_model(cfg: dict) -> str:
    return (qwen3_block(cfg).get("vc_model") or "qwen3-tts-vc-2026-01-22").strip()


def synth_model(cfg: dict, *, clone: bool = False) -> str:
    q3 = qwen3_block(cfg)
    if clone:
        return vc_model(cfg)
    return (q3.get("model") or "qwen3-tts-flash").strip()


def _api_post(cfg: dict, url: str, payload: dict, *, timeout_sec: int = 120) -> dict[str, Any]:
    q3 = qwen3_block(cfg)
    key = (q3.get("api_key") or "").strip()
    if not key:
        raise RuntimeError("未配置 DashScope API Key（config.yaml → qwen3_tts → api_key）")
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            err = json.loads(detail)
            msg = err.get("message") or err.get("code") or detail
        except json.JSONDecodeError:
            msg = detail or str(exc)
        raise RuntimeError(f"DashScope HTTP {exc.code}: {msg}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"无法连接 DashScope：{exc.reason}") from exc
    data = json.loads(raw)
    if data.get("code"):
        raise RuntimeError(data.get("message") or data.get("code") or "DashScope 返回错误")
    return data


def enroll_clone_voice(cfg: dict, audio_path: str, preferred_name: str) -> str:
    """Register reference audio on DashScope; returns voice id for synthesis."""
    path = Path(audio_path)
    if not path.is_file():
        raise FileNotFoundError(f"参考音频不存在: {audio_path}")
    suffix = path.suffix.lower()
    mime = {
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".ogg": "audio/ogg",
        ".webm": "audio/webm",
    }.get(suffix, "audio/wav")
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    safe_name = re.sub(r"[^\w\u4e00-\u9fff-]", "_", preferred_name or "clone")[:32] or "clone"
    payload = {
        "model": "qwen-voice-enrollment",
        "input": {
            "action": "create",
            "target_model": vc_model(cfg),
            "preferred_name": safe_name,
            "audio": {"data": f"data:{mime};base64,{b64}"},
        },
    }
    data = _api_post(cfg, customization_endpoint(cfg), payload, timeout_sec=180)
    voice = (data.get("output") or {}).get("voice")
    if not voice:
        raise RuntimeError("DashScope 未返回克隆 voice 标识")
    return str(voice)


def _call_api(
    cfg: dict,
    *,
    text: str,
    voice: str,
    language_type: str = "Auto",
    model: str | None = None,
    timeout_sec: int = 120,
) -> dict[str, Any]:
    payload = {
        "model": model or synth_model(cfg, clone=False),
        "input": {
            "text": text,
            "voice": voice,
            "language_type": language_type or "Auto",
        },
    }
    return _api_post(cfg, api_endpoint(cfg), payload, timeout_sec=timeout_sec)


def _download_audio(url: str, dest: Path, timeout_sec: int = 120) -> None:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
        dest.write_bytes(resp.read())


def synthesize_qwen3_tts(
    cfg: dict,
    text: str,
    output_wav: Path,
    *,
    preset_id: str = "mandarin_female_warm",
    mode: str = "preset",
    saved_voice_id: str | None = None,
    on_progress: ProgressFn | None = None,
) -> None:
    def prog(p: float, msg: str) -> None:
        if on_progress:
            on_progress(p, msg)

    clone_model = synth_model(cfg, clone=True)
    if mode == "clone":
        from tts.voices import get_voice

        entry = get_voice(saved_voice_id or "")
        qwen_voice = (entry or {}).get("qwen_voice") or ""
        if not qwen_voice:
            raise ValueError(
                "该克隆音色尚未在 DashScope 注册。\n"
                "请使用 Qwen3-TTS 引擎重新在 ② 音色克隆 保存一次。"
            )
        voice = qwen_voice
        language_type = (qwen3_block(cfg).get("language_type") or "Chinese").strip()
        api_model = clone_model
        prog(0.12, f"{stage_label('prep')} · Qwen3 克隆 · {voice}")
    else:
        voice, language_type = resolve_qwen3_voice(cfg, preset_id)
        api_model = synth_model(cfg, clone=False)
        prog(0.12, f"{stage_label('prep')} · Qwen3-TTS · {voice}")

    chunks: list[str] = []
    max_chars = int(qwen3_block(cfg).get("max_chars_per_request") or 500)
    parts = _split_text(text, max_chars)
    total = len(parts)

    for i, part in enumerate(parts):
        base = 0.15 + 0.7 * (i / max(total, 1))
        prog(base, f"{stage_label('cpu_synth')} · 段落 {i + 1}/{total}")
        resp = _call_api(
            cfg,
            text=part,
            voice=voice,
            language_type=language_type,
            model=api_model,
        )
        audio = (resp.get("output") or {}).get("audio") or {}
        url = audio.get("url") or ""
        b64 = audio.get("data") or ""
        tmp = output_wav.parent / f"qwen3_part_{i}.wav"
        if url:
            _download_audio(url, tmp)
        elif b64:
            tmp.write_bytes(base64.b64decode(b64))
        else:
            raise RuntimeError("DashScope 未返回音频（无 url / data）")
        chunks.append(str(tmp))

    prog(0.88, stage_label("convert_16k"))
    if len(chunks) == 1:
        _ensure_wav(Path(chunks[0]), output_wav)
    else:
        _concat_wavs([Path(p) for p in chunks], output_wav, cfg)


def _split_text(text: str, max_chars: int) -> list[str]:
    text = (text or "").strip()
    if not text:
        raise ValueError("文案不能为空")
    if len(text) <= max_chars:
        return [text]
    parts: list[str] = []
    buf = ""
    for para in re.split(r"\n+", text):
        para = para.strip()
        if not para:
            continue
        for sent in re.split(r"(?<=[。！？；!?;])", para):
            sent = sent.strip()
            if not sent:
                continue
            if len(sent) > max_chars:
                for j in range(0, len(sent), max_chars):
                    chunk = sent[j : j + max_chars]
                    if buf and len(buf) + len(chunk) > max_chars:
                        parts.append(buf)
                        buf = chunk
                    elif buf:
                        buf += chunk
                    else:
                        buf = chunk
                continue
            if len(buf) + len(sent) > max_chars:
                if buf:
                    parts.append(buf)
                buf = sent
            else:
                buf = (buf + sent) if buf else sent
        if buf:
            parts.append(buf)
            buf = ""
    return parts or [text]


def _ensure_wav(src: Path, dest: Path) -> None:
    if src.resolve() == dest.resolve():
        return
    dest.write_bytes(src.read_bytes())


def _concat_wavs(paths: list[Path], dest: Path, cfg: dict) -> None:
    import subprocess
    import wave

    if len(paths) == 1:
        _ensure_wav(paths[0], dest)
        return

    ffmpeg = (cfg.get("paths") or {}).get("ffmpeg", "ffmpeg")
    list_file = dest.parent / "qwen3_concat.txt"
    list_file.write_text(
        "\n".join(f"file '{p.resolve().as_posix()}'" for p in paths),
        encoding="utf-8",
    )
    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_file),
        "-c",
        "copy",
        str(dest),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        # Fallback: stitch PCM via wave module (same format assumed)
        with wave.open(str(dest), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(24000)
            for p in paths:
                with wave.open(str(p), "rb") as w:
                    out.writeframes(w.readframes(w.getnframes()))

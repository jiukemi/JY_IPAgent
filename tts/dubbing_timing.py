"""Dubbing timeline — TTS segment capture + audio ASR alignment for subtitles/PiP."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

TIMING_FILE = "dubbing_timing.json"
ASR_TIMING_FILE = "dubbing_asr_timing.json"
# Bump when ASR payload shape changes (e.g. word timestamps) so stale caches re-run.
ASR_TIMING_SCHEMA = 2
SAMPLING_RATE = 22050


def _tokens_to_text(tokens: list[str]) -> str:
    raw = "".join(tokens)
    raw = raw.replace("▁", "")
    return re.sub(r"\s+", "", raw).strip()


def save_timing_manifest(session_dir: Path, payload: dict, *, filename: str = TIMING_FILE) -> Path:
    session_dir = Path(session_dir)
    payload = dict(payload)
    payload.setdefault("created_at", datetime.now().isoformat(timespec="seconds"))
    out = session_dir / filename
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def ensure_subtitle_timing_manifest(
    cfg: dict,
    session_dir: Path,
    *,
    probe_bin: str | None = None,
    force: bool = False,
) -> dict | None:
    """Prefer lipsync video audio ASR; cache until lipsync file changes."""
    from workflow.publish import resolve_lipsync_video, resolve_session_dub_audio

    session_dir = Path(session_dir)
    video = resolve_lipsync_video(session_dir)
    dub = resolve_session_dub_audio(session_dir)
    if video is None and dub is None:
        return None

    video_mtime = video.stat().st_mtime if video and video.is_file() else None
    asr_p = session_dir / ASR_TIMING_FILE
    if not force and asr_p.is_file():
        try:
            data = json.loads(asr_p.read_text(encoding="utf-8"))
            segs = data.get("segments") or []
            schema_ok = int(data.get("schema") or 0) >= ASR_TIMING_SCHEMA
            if segs and schema_ok and _segments_usable(segs):
                align_from = data.get("align_from")
                if video and align_from == "lipsync_video":
                    if data.get("lipsync_mtime") == video_mtime:
                        return data
                elif not video and align_from == "dubbing_wav":
                    return data
                elif video is None:
                    return data
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            pass

    if video and video.is_file():
        return align_dubbing_from_audio(
            cfg,
            session_dir,
            probe_bin=probe_bin,
            use_video_audio=True,
            lipsync_video_mtime=video_mtime,
        )
    return align_dubbing_from_audio(cfg, session_dir, probe_bin=probe_bin)


def _text_quality_score(text: str) -> float:
    text = (text or "").strip()
    if not text:
        return 0.0
    if "\ufffd" in text:
        return 0.0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return cjk / max(len(text), 1)


def _segments_usable(segments: list[dict], *, min_score: float = 0.25) -> bool:
    """Accept timing manifests that have valid start/end anchors.

    ASR text quality is optional — publish maps the session script onto these times,
    so replacement-char transcripts must not force endless re-ASR.
    """
    if not segments:
        return False
    ok = 0
    for s in segments:
        try:
            start = float(s["start"])
            end = float(s["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if end > start:
            ok += 1
    return ok >= max(1, (len(segments) + 1) // 2)


def load_timing_manifest(session_dir: Path, *, prefer_asr: bool = True) -> dict | None:
    session_dir = Path(session_dir)
    asr_p = session_dir / ASR_TIMING_FILE
    tts_p = session_dir / TIMING_FILE
    asr_data: dict | None = None
    tts_data: dict | None = None
    if asr_p.is_file():
        try:
            asr_data = json.loads(asr_p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            asr_data = None
    if tts_p.is_file():
        try:
            tts_data = json.loads(tts_p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            tts_data = None

    asr_ok = bool(asr_data and asr_data.get("segments") and _segments_usable(asr_data["segments"]))
    tts_ok = bool(tts_data and tts_data.get("segments"))

    if prefer_asr and asr_ok:
        return asr_data
    if tts_ok:
        return tts_data
    if asr_ok:
        return asr_data
    return None


def capture_indextts_segment_timing(
    tts,
    cfg: dict,
    speak_text: str,
    infer_kwargs: dict,
) -> list[dict]:
    """Measure real per-segment durations via IndexTTS stream_return."""
    import torch

    max_tok = int(infer_kwargs.get("max_text_tokens_per_segment", 120))
    interval_ms = int(infer_kwargs.get("interval_silence", 200))
    silence_sec = interval_ms / 1000.0

    text_tokens_list = tts.tokenizer.tokenize(speak_text)
    seg_token_lists = tts.tokenizer.split_segments(text_tokens_list, max_tok)
    expected_segments = len(seg_token_lists)

    gen = tts.infer(stream_return=True, **infer_kwargs)
    segments: list[dict] = []
    t = 0.0
    seg_idx = 0
    chunk_i = 0

    try:
        for chunk in gen:
            if not isinstance(chunk, torch.Tensor):
                continue
            dur = float(chunk.shape[-1]) / SAMPLING_RATE
            if chunk_i % 2 == 0:
                text = ""
                if seg_idx < len(seg_token_lists):
                    text = _tokens_to_text(seg_token_lists[seg_idx])
                segments.append(
                    {
                        "index": seg_idx + 1,
                        "start": round(t, 3),
                        "end": round(t + dur, 3),
                        "text": text,
                    }
                )
                t += dur + silence_sec
                seg_idx += 1
            else:
                t += dur
            chunk_i += 1
    except Exception:
        return []

    if seg_idx < expected_segments:
        return []
    return segments


def collect_qwen3_part_timing(session_dir: Path) -> list[dict]:
    import wave

    session_dir = Path(session_dir)
    parts = sorted(session_dir.glob("qwen3_part_*.wav"))
    segments: list[dict] = []
    t = 0.0
    for i, part in enumerate(parts):
        with wave.open(str(part), "rb") as wf:
            dur = wf.getnframes() / float(wf.getframerate() or 1)
        segments.append(
            {
                "index": i + 1,
                "start": round(t, 3),
                "end": round(t + dur, 3),
                "text": "",
            }
        )
        t += dur
    return segments


def _venv_python(cfg: dict, key: str) -> str:
    from tts.engine import venv_python

    return venv_python(cfg, key)


def _whisper_engine_dir(cfg: dict) -> Path:
    from workflow.engine_dirs import resolve_engine_dir

    return resolve_engine_dir(
        cfg,
        path_key="whisper_dir",
        default_rel="tools/Whisper",
        runtime_name="Whisper",
        markers=("run_asr_timestamps.py", "run_asr.py"),
    )


def _bundled_timestamps_runner() -> Path:
    return Path(__file__).resolve().parents[1] / "script" / "run_asr_timestamps.py"


def _ensure_timestamps_runner(engine_dir: Path) -> Path | None:
    """Prefer engine-local runner; refresh from bundled script so upgrades pick up HF mirror fixes."""
    local = engine_dir / "run_asr_timestamps.py"
    bundled = _bundled_timestamps_runner()
    if bundled.is_file():
        try:
            engine_dir.mkdir(parents=True, exist_ok=True)
            text = bundled.read_text(encoding="utf-8")
            if (not local.is_file()) or local.read_text(encoding="utf-8") != text:
                local.write_text(text, encoding="utf-8")
            if local.is_file():
                return local
        except OSError:
            return bundled
        return bundled
    if local.is_file():
        return local
    return None


def transcribe_dubbing_whisper(cfg: dict, audio_path: Path) -> list[dict]:
    """ASR on dubbing audio with segment timestamps (faster-whisper engine venv)."""
    audio_path = Path(audio_path)
    if not audio_path.is_file():
        return []

    engine_dir = _whisper_engine_dir(cfg)
    py = _venv_python(cfg, "whisper_dir")
    runner = _ensure_timestamps_runner(engine_dir)

    # No Whisper engine venv → cannot use app Python (mini pack has no faster-whisper).
    if py == sys.executable or not runner:
        inline = _transcribe_dubbing_inline(cfg, audio_path)
        if inline:
            return inline
        raise RuntimeError(
            "混剪「提取字幕」需要本机 Whisper（faster-whisper）。\n"
            "迷你安装包不含该引擎：请打开「设置 → 本机环境」安装 Whisper 后重试"
            "（仅装 FunASR 可提取文案，但第四步字幕时间轴目前走 Whisper）。\n"
            f"引擎目录：{engine_dir}"
        )

    model = (cfg.get("script") or {}).get("whisper_model", "small")
    lang = (cfg.get("script") or {}).get("language", "zh")
    out_json = audio_path.with_suffix(audio_path.suffix + ".asr_segments.json")
    cmd = [
        py,
        str(runner),
        "--audio",
        str(audio_path.resolve()),
        "--model",
        str(model),
        "--language",
        str(lang),
        "--out",
        str(out_json.resolve()),
    ]
    env = os.environ.copy()
    env.setdefault("HF_ENDPOINT", (cfg.get("hf_endpoint") or "https://hf-mirror.com"))
    env.setdefault("HUGGINGFACE_HUB_ENDPOINT", env["HF_ENDPOINT"])
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    if proc.returncode != 0:
        err_tail = ((proc.stderr or "") + "\n" + (proc.stdout or "")).strip()[-800:]
        inline = _transcribe_dubbing_inline(cfg, audio_path)
        if inline:
            return inline
        raise RuntimeError(
            "Whisper 字幕识别失败。\n"
            "常见原因：首次下载模型连不上 huggingface.co（超时）。\n"
            "处理：① 升到 0.1.37+ 并重装 Whisper（会走 hf-mirror 预下载）；"
            "② 开梯子或确认可访问 https://hf-mirror.com 后重试；"
            "③ 确认 FFmpeg 可用。\n"
            + (err_tail or f"exit={proc.returncode}")
        )
    try:
        if out_json.is_file():
            data = json.loads(out_json.read_text(encoding="utf-8"))
            out_json.unlink(missing_ok=True)
            return data.get("segments") or []
        data = json.loads(proc.stdout.strip())
        return data.get("segments") or []
    except (json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(f"Whisper 字幕结果解析失败：{exc}") from exc


def _transcribe_dubbing_inline(cfg: dict, audio_path: Path) -> list[dict]:
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return []

    model_name = (cfg.get("script") or {}).get("whisper_model", "small")
    lang = (cfg.get("script") or {}).get("language", "zh")
    try:
        model = WhisperModel(model_name, device="cuda", compute_type="float16")
    except Exception:
        model = WhisperModel(model_name, device="cpu", compute_type="int8")

    segments, _info = model.transcribe(
        str(audio_path),
        language=lang or None,
        vad_filter=True,
        word_timestamps=True,
    )
    out: list[dict] = []
    for i, seg in enumerate(segments):
        text = re.sub(r"\s+", "", (seg.text or "").strip())
        if not text:
            continue
        words_out = []
        for w in seg.words or []:
            wtext = re.sub(r"\s+", "", (getattr(w, "word", None) or "").strip())
            if not wtext:
                continue
            words_out.append(
                {
                    "word": wtext,
                    "start": round(float(w.start), 3),
                    "end": round(float(w.end), 3),
                }
            )
        item = {
            "index": i + 1,
            "start": round(float(seg.start), 3),
            "end": round(float(seg.end), 3),
            "text": text,
        }
        if words_out:
            item["words"] = words_out
        out.append(item)
    return out


def align_dubbing_from_audio(
    cfg: dict,
    session_dir: Path,
    audio_path: Path | None = None,
    *,
    probe_bin: str | None = None,
    use_video_audio: bool = False,
    lipsync_video_mtime: float | None = None,
) -> dict:
    """Run ASR on dubbing (or lipsync video audio) and persist segment timing."""
    from workflow.publish import (
        media_duration,
        resolve_lipsync_video,
        resolve_session_dub_audio,
    )

    session_dir = Path(session_dir)
    audio: Path | None = None
    if use_video_audio:
        video = resolve_lipsync_video(session_dir)
        if video and video.is_file():
            from pipeline import ensure_ffmpeg

            ffmpeg = ensure_ffmpeg(cfg.get("paths", {}).get("ffmpeg", "ffmpeg"))
            tmp = session_dir / "publish" / "lipsync_audio_16k.wav"
            tmp.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-i",
                    str(video),
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    str(tmp),
                ],
                check=True,
                capture_output=True,
            )
            audio = tmp
    else:
        audio = Path(audio_path) if audio_path else resolve_session_dub_audio(session_dir)
        if audio is None or not audio.is_file():
            video = resolve_lipsync_video(session_dir)
            if video and video.is_file():
                from pipeline import ensure_ffmpeg

                ffmpeg = ensure_ffmpeg(cfg.get("paths", {}).get("ffmpeg", "ffmpeg"))
                tmp = session_dir / "publish" / "extracted_audio_16k.wav"
                tmp.parent.mkdir(parents=True, exist_ok=True)
                subprocess.run(
                    [
                        ffmpeg,
                        "-y",
                        "-i",
                        str(video),
                        "-ac",
                        "1",
                        "-ar",
                        "16000",
                        str(tmp),
                    ],
                    check=True,
                    capture_output=True,
                )
                audio = tmp
    if audio is None or not audio.is_file():
        raise FileNotFoundError("未找到配音或成片音频，无法对齐")

    segments = transcribe_dubbing_whisper(cfg, audio)
    if not segments:
        raise RuntimeError(
            "配音语音识别未返回有效分段。请到「设置 → 本机环境」安装 Whisper 后重试；"
            "并确认 FFmpeg 可用（设置里可装）。"
        )

    duration = segments[-1]["end"] if segments else 0.0
    if probe_bin:
        try:
            duration = media_duration(probe_bin, audio)
        except Exception:
            pass

    payload = {
        "schema": ASR_TIMING_SCHEMA,
        "source": "dubbing_asr",
        "align_from": "lipsync_video" if use_video_audio else "dubbing_wav",
        "audio_path": str(audio.resolve()),
        "duration": round(duration, 3),
        "segments": segments,
    }
    if lipsync_video_mtime is not None:
        payload["lipsync_mtime"] = lipsync_video_mtime
    save_timing_manifest(session_dir, payload, filename=ASR_TIMING_FILE)
    return payload

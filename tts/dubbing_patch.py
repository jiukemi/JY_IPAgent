"""Patch one dubbing segment (re-TTS or replace clip) with duration fit + crossfade."""

from __future__ import annotations

import json
import subprocess
import tempfile
import wave
from datetime import datetime
from pathlib import Path

from tts.dubbing_timing import ASR_TIMING_FILE, TIMING_FILE, save_timing_manifest

SAMPLE_RATE = 16000
DEFAULT_CROSSFADE_MS = 40.0


def _wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as wf:
        frames = wf.getnframes()
        rate = float(wf.getframerate() or 1)
    return frames / rate if rate > 0 else 0.0


def _run_ffmpeg(ffmpeg: str, args: list[str]) -> None:
    cmd = [ffmpeg, "-y", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(err[-800:] if err else "ffmpeg 失败")


def _atempo_filters(ratio: float) -> list[str]:
    """Build atempo chain (each factor must be in [0.5, 2.0])."""
    filters: list[str] = []
    r = float(ratio)
    if r <= 0:
        raise ValueError("无效变速比")
    while r > 2.0:
        filters.append("atempo=2.0")
        r /= 2.0
    while r < 0.5:
        filters.append("atempo=0.5")
        r /= 0.5
    if abs(r - 1.0) > 0.001:
        filters.append(f"atempo={r:.5f}")
    return filters


def fit_wav_duration(ffmpeg: str, src: Path, dst: Path, target_sec: float, *, sample_rate: int = SAMPLE_RATE) -> float:
    """Time-stretch (and pad/trim) so output length ≈ target_sec. Returns actual duration."""
    target_sec = max(0.05, float(target_sec))
    src_dur = _wav_duration(src)
    if src_dur <= 0.01:
        raise ValueError("替换音频过短或无效")

    work = dst.with_suffix(".fit_tmp.wav")
    ratio = src_dur / target_sec
    filters = _atempo_filters(ratio)
    if filters:
        af = ",".join(filters)
        _run_ffmpeg(
            ffmpeg,
            ["-i", str(src), "-ac", "1", "-ar", str(sample_rate), "-af", af, str(work)],
        )
    else:
        _run_ffmpeg(
            ffmpeg,
            ["-i", str(src), "-ac", "1", "-ar", str(sample_rate), str(work)],
        )

    # Exact length: pad or trim
    _run_ffmpeg(
        ffmpeg,
        [
            "-i",
            str(work),
            "-af",
            f"apad=whole_dur={target_sec:.4f},atrim=0:{target_sec:.4f},asetpts=PTS-STARTPTS",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            str(dst),
        ],
    )
    work.unlink(missing_ok=True)
    return _wav_duration(dst)


def splice_with_crossfade(
    ffmpeg: str,
    base: Path,
    mid: Path,
    dst: Path,
    start: float,
    end: float,
    *,
    crossfade_ms: float = DEFAULT_CROSSFADE_MS,
    sample_rate: int = SAMPLE_RATE,
) -> float:
    """Replace [start, end) in base with mid (same duration preferred), soft fades at seams."""
    start = max(0.0, float(start))
    end = max(start + 0.05, float(end))
    base_dur = _wav_duration(base)
    mid_dur = _wav_duration(mid)
    if mid_dur <= 0.01:
        raise ValueError("中间片段无效")
    if start >= base_dur:
        raise ValueError("段落起点超出配音时长")

    cf = max(0.0, min(float(crossfade_ms) / 1000.0, mid_dur / 3.0, start, max(0.0, base_dur - end)))
    # Keep a little fade even at edges when possible
    if start > 0:
        cf = min(cf if cf > 0 else DEFAULT_CROSSFADE_MS / 1000.0, start, mid_dur / 3.0)
    if end < base_dur:
        cf = min(max(cf, 0.0), max(0.0, base_dur - end), mid_dur / 3.0)

    pre_out = max(0.0, start)
    post_in = min(base_dur, end)

    # Three-way concat with edge fades (skip empty pre/post)
    parts: list[str] = []
    labels: list[str] = []
    n = 0

    if pre_out > 0.001:
        fade_out_st = max(0.0, pre_out - cf) if cf > 0.001 else None
        if fade_out_st is not None and cf > 0.001:
            parts.append(
                f"[0:a]atrim=0:{pre_out:.4f},asetpts=PTS-STARTPTS,"
                f"afade=t=out:st={fade_out_st:.4f}:d={cf:.4f}[p{n}]"
            )
        else:
            parts.append(f"[0:a]atrim=0:{pre_out:.4f},asetpts=PTS-STARTPTS[p{n}]")
        labels.append(f"[p{n}]")
        n += 1

    mid_fades: list[str] = [f"[1:a]atrim=0:{mid_dur:.4f},asetpts=PTS-STARTPTS"]
    if cf > 0.001 and pre_out > 0.001:
        mid_fades.append(f"afade=t=in:d={cf:.4f}")
    if cf > 0.001 and post_in < base_dur - 0.001:
        st = max(0.0, mid_dur - cf)
        mid_fades.append(f"afade=t=out:st={st:.4f}:d={cf:.4f}")
    parts.append(",".join(mid_fades) + f"[p{n}]")
    labels.append(f"[p{n}]")
    n += 1

    if post_in < base_dur - 0.001:
        if cf > 0.001:
            parts.append(
                f"[0:a]atrim={post_in:.4f},asetpts=PTS-STARTPTS,afade=t=in:d={cf:.4f}[p{n}]"
            )
        else:
            parts.append(f"[0:a]atrim={post_in:.4f},asetpts=PTS-STARTPTS[p{n}]")
        labels.append(f"[p{n}]")
        n += 1

    if n == 1:
        # Whole-file replace
        _run_ffmpeg(
            ffmpeg,
            ["-i", str(mid), "-ac", "1", "-ar", str(sample_rate), str(dst)],
        )
        return _wav_duration(dst)

    fc = ";".join(parts) + ";" + "".join(labels) + f"concat=n={n}:v=0:a=1[out]"
    _run_ffmpeg(
        ffmpeg,
        [
            "-i",
            str(base),
            "-i",
            str(mid),
            "-filter_complex",
            fc,
            "-map",
            "[out]",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            str(dst),
        ],
    )
    return _wav_duration(dst)


def resolve_patch_segments(session_dir: Path) -> tuple[list[dict], str]:
    """Return (segments, source_label). Prefer TTS timing with segments, else ASR."""
    session_dir = Path(session_dir)
    for name, label in ((TIMING_FILE, "tts"), (ASR_TIMING_FILE, "asr")):
        fp = session_dir / name
        if not fp.is_file():
            continue
        try:
            payload = json.loads(fp.read_text(encoding="utf-8"))
            segs = payload.get("segments") or []
            if segs and _asr_segs_ok(segs):
                return list(segs), label
        except (OSError, json.JSONDecodeError, TypeError):
            continue
    return [], ""


def _asr_segs_ok(segments: list) -> bool:
    ok = 0
    for s in segments:
        try:
            if float(s["end"]) > float(s["start"]):
                ok += 1
        except (KeyError, TypeError, ValueError):
            continue
    return ok > 0


def find_segment(segments: list[dict], index: int) -> dict:
    for s in segments:
        try:
            if int(s.get("index", -1)) == int(index):
                return s
        except (TypeError, ValueError):
            continue
    # Allow 0-based UI index into list order
    if 0 <= index < len(segments):
        return segments[index]
    raise ValueError(f"找不到段落 #{index}")


def update_segment_in_manifest(
    session_dir: Path,
    segment_index: int,
    *,
    text: str | None = None,
    note: str = "",
) -> None:
    """Keep start/end (duration fitted); refresh text/meta on TTS timing file."""
    session_dir = Path(session_dir)
    timing_path = session_dir / TIMING_FILE
    payload: dict
    if timing_path.is_file():
        try:
            payload = json.loads(timing_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
    else:
        payload = {"source": "patch", "segments": []}

    segs = list(payload.get("segments") or [])
    if not segs:
        # Seed from ASR so UI keeps working
        asr_segs, _ = resolve_patch_segments(session_dir)
        segs = [dict(s) for s in asr_segs]

    touched = False
    for s in segs:
        try:
            if int(s.get("index", -1)) == int(segment_index):
                if text is not None:
                    s["text"] = text
                s["patched_at"] = datetime.now().isoformat(timespec="seconds")
                if note:
                    s["patch_note"] = note
                touched = True
                break
        except (TypeError, ValueError):
            continue
    if not touched and segs:
        # try list position
        for i, s in enumerate(segs):
            if i + 1 == int(segment_index) or i == int(segment_index):
                if text is not None:
                    s["text"] = text
                s["patched_at"] = datetime.now().isoformat(timespec="seconds")
                if note:
                    s["patch_note"] = note
                touched = True
                break

    payload["segments"] = segs
    payload["updated_at"] = datetime.now().isoformat(timespec="seconds")
    save_timing_manifest(session_dir, payload, filename=TIMING_FILE)


def synthesize_segment_clip(
    cfg: dict,
    session_dir: Path,
    text: str,
    *,
    voice_uid: str,
    speed_mode: str = "balanced",
    work_dir: Path | None = None,
) -> Path:
    """Run full TTS pipeline for one short text into a temp wav (16k)."""
    from tts.engine import convert_to_wav, synthesize
    from tts.voice_catalog import get_voice_entry, resolve_synthesis
    from tts.voices import get_voice
    from workflow.deployment import resolve_tts_backend

    text = (text or "").strip()
    if not text:
        raise ValueError("段落文案为空，无法重合成")
    if not voice_uid:
        raise ValueError("请先选择音色")

    params = resolve_synthesis(voice_uid)
    tts_backend = resolve_tts_backend(cfg)
    entry = get_voice_entry(voice_uid)
    voice_backend = params.get("backend") or tts_backend

    if entry and entry.mode != "clone":
        if entry.backend != tts_backend:
            raise ValueError(
                f"音色「{entry.label}」属于 {entry.backend}，与当前引擎 {tts_backend} 不一致"
            )
        effective_backend = tts_backend
    elif voice_backend == tts_backend:
        effective_backend = tts_backend
    else:
        raise ValueError(f"克隆音色属于 {voice_backend}，与当前引擎 {tts_backend} 不匹配")

    clone_prompt = ""
    if params["mode"] == "clone":
        saved = get_voice(params["saved_voice_id"])
        clone_prompt = (saved or {}).get("prompt_text", "")

    work = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="dub_patch_"))
    work.mkdir(parents=True, exist_ok=True)
    result = synthesize(
        cfg,
        text,
        work,
        mode=params["mode"],
        preset_id=params["preset_id"] or "mandarin_female_warm",
        style_extra=params.get("style_extra", ""),
        saved_voice_id=params.get("saved_voice_id"),
        prompt_text=clone_prompt,
        backend=effective_backend,
        speed=speed_mode or "balanced",
    )
    audio = Path(result["audio"])
    if not audio.is_file():
        # Some backends write tts_raw then convert to dubbing_16k in session — use whatever exists
        for cand in (work / "dubbing_16k.wav", work / "tts_raw.wav"):
            if cand.is_file():
                audio = cand
                break
    if not audio.is_file():
        raise RuntimeError("段落重合成未产出音频")

    out = work / "segment_clip_16k.wav"
    ffmpeg = cfg.get("paths", {}).get("ffmpeg", "ffmpeg")
    if audio.resolve() != out.resolve():
        convert_to_wav(ffmpeg, audio, out, sample_rate=SAMPLE_RATE)
    return out

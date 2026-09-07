"""Shared IndexTTS2 load + infer (one-shot subprocess and warm worker)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

import yaml

from tts.engine import load_presets, resolve_indextts_reference
from tts.progress import emit, estimate_speech_seconds
from tts.speed import get_speed_preset

ProgressFn = Callable[[float, str], None]


def load_project_cfg(config_path: Path | str) -> dict:
    return yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))


def resolve_speak_emo_spk(
    cfg: dict,
    *,
    speak_text: str,
    mode: str,
    preset_id: str,
    style_extra: str,
    reference_wav: str | None,
) -> tuple[str, str, str]:
    presets = load_presets()
    emo_text = (style_extra or "").strip()
    mode = (mode or "preset").lower()
    preset_id = preset_id or "mandarin_female_warm"

    if mode == "clone":
        # 保留用户填写的 style_extra；空则仍只靠参考音（偏平）
        if not emo_text:
            emo_text = ""
    elif mode == "preset":
        preset = presets.get("presets", {}).get(preset_id)
        if not preset:
            preset = presets.get("english_presets", {}).get(preset_id)
        if preset and not emo_text:
            raw = preset.get("style_prefix", "").strip()
            emo_text = raw.strip("()") if raw else ""
    elif mode == "dialect":
        dialect = presets.get("dialects", {}).get(preset_id, {})
        hint = (dialect.get("style_prefix") or "").strip().strip("()")
        if hint and not emo_text:
            emo_text = hint
    elif mode == "english":
        eng = presets.get("english_presets", {}).get(preset_id, {})
        raw = (eng.get("style_prefix") or "").strip().strip("()")
        if raw and not emo_text:
            emo_text = raw

    spk_wav = resolve_indextts_reference(
        cfg,
        mode=mode,
        preset_id=preset_id,
        reference_wav=reference_wav,
    )
    return speak_text.strip(), emo_text, spk_wav


def model_paths(cfg: dict) -> tuple[Path, Path]:
    from tts.engine import resolve_indextts_install_dir

    it_cfg = cfg.get("indextts", {}) or {}
    install = resolve_indextts_install_dir(cfg)
    model_dir = install / it_cfg.get("model_dir", "checkpoints")
    cfg_path = model_dir / "config.yaml"
    if not cfg_path.exists():
        raise FileNotFoundError(
            f"IndexTTS2 模型未找到: {model_dir}\n"
            "请到「设置 → 本机环境」安装/重装 IndexTTS2（会下载 checkpoints）。\n"
            "打包版模型在运行时目录 engines\\IndexTTS\\checkpoints，不是安装目录下的 tools\\IndexTTS。"
        )
    return cfg_path, model_dir


# Core weights required before IndexTTS2 can load (partial downloads often miss these).
_CORE_CHECKPOINT_FILES: tuple[tuple[str, int], ...] = (
    ("gpt.pth", 100_000_000),
    ("s2mel.pth", 50_000_000),
    ("bpe.model", 1000),
    ("feat1.pt", 1000),
    ("feat2.pt", 1000),
    ("wav2vec2bert_stats.pt", 1000),
)


def missing_core_checkpoints(model_dir: Path) -> list[str]:
    missing: list[str] = []
    for name, min_size in _CORE_CHECKPOINT_FILES:
        p = model_dir / name
        if not p.is_file() or p.stat().st_size < min_size:
            missing.append(name)
    return missing


def core_checkpoints_ready(model_dir: Path) -> bool:
    return not missing_core_checkpoints(model_dir)


def _hf_mirror_env() -> None:
    import os

    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    os.environ.setdefault("HUGGINGFACE_HUB_ENDPOINT", "https://hf-mirror.com")


def _snapshot_indextts(model_dir: Path, patterns: list[str] | None = None) -> None:
    """Download IndexTTS-2 files into model_dir (ModelScope then HF mirror)."""
    _hf_mirror_env()
    last_err = ""
    try:
        from modelscope import snapshot_download

        kwargs: dict = {"local_dir": str(model_dir)}
        if patterns:
            kwargs["allow_patterns"] = patterns
        snapshot_download("IndexTeam/IndexTTS-2", **kwargs)
        return
    except Exception as exc:
        last_err = f"modelscope: {exc}"
    try:
        from huggingface_hub import snapshot_download as hf_snap

        kwargs = {
            "repo_id": "IndexTeam/IndexTTS-2",
            "local_dir": str(model_dir),
            "local_dir_use_symlinks": False,
        }
        if patterns:
            kwargs["allow_patterns"] = patterns
        hf_snap(**kwargs)
        return
    except Exception as exc:
        raise RuntimeError(f"IndexTTS 权重下载失败（{last_err}; hf: {exc}）") from exc


def ensure_core_checkpoints(model_dir: Path) -> None:
    """Ensure gpt.pth / s2mel.pth / … exist; repair partial installs."""
    missing = missing_core_checkpoints(model_dir)
    if not missing:
        return
    model_dir.mkdir(parents=True, exist_ok=True)
    # If many core files missing, pull the whole repo; else only the gaps.
    patterns = None if len(missing) >= 3 else list(missing)
    try:
        _snapshot_indextts(model_dir, patterns)
    except Exception:
        # Pattern-only download may not be supported — fall back to full
        if patterns is not None:
            _snapshot_indextts(model_dir, None)
        else:
            raise
    still = missing_core_checkpoints(model_dir)
    if still:
        raise FileNotFoundError(
            f"IndexTTS2 核心权重缺失: {', '.join(still)}\n"
            f"目录: {model_dir}\n"
            "请到「设置 → 本机环境」重装 IndexTTS2，并保持网络畅通（可用国内镜像）。\n"
            "常见缺文件：gpt.pth（主模型，体积很大）。"
        )


def _qwen_emo_dir(model_dir: Path) -> Path:
    return (model_dir / "qwen0.6bemo4-merge").resolve()


def qwen_emo_ready(model_dir: Path) -> bool:
    emo = _qwen_emo_dir(model_dir)
    cfg_ok = (emo / "config.json").is_file()
    # weights may be safetensors or split; require a sizable weight file
    weight_ok = False
    for name in ("model.safetensors", "pytorch_model.bin", "model.safetensors.index.json"):
        p = emo / name
        if p.is_file() and (name.endswith(".json") or p.stat().st_size > 100_000_000):
            weight_ok = True
            break
    if not weight_ok:
        for p in emo.glob("*.safetensors"):
            if p.stat().st_size > 100_000_000:
                weight_ok = True
                break
    return cfg_ok and weight_ok


def ensure_qwen_emo_model(model_dir: Path) -> Path:
    """Ensure qwen0.6bemo4-merge exists; incomplete installs cause HFValidationError on Windows."""
    emo = _qwen_emo_dir(model_dir)
    if qwen_emo_ready(model_dir):
        return emo

    model_dir.mkdir(parents=True, exist_ok=True)
    last_err = ""
    try:
        _snapshot_indextts(
            model_dir,
            ["qwen0.6bemo4-merge/*", "qwen0.6bemo4-merge/**"],
        )
    except Exception as exc:
        last_err = str(exc)

    if not qwen_emo_ready(model_dir):
        raise FileNotFoundError(
            f"IndexTTS2 情感模型缺失或不完整: {emo}\n"
            "这会导致 HuggingFace 把 Windows 路径误判为 repo id（HFValidationError）。\n"
            "请到「设置 → 本机环境」重装 IndexTTS2，确保下载完 qwen0.6bemo4-merge（约 1.2GB）。\n"
            f"详情: {last_err or '未找到 config.json / 权重文件'}"
        )
    return emo


def prepare_indextts_cfg(cfg_path: Path, model_dir: Path) -> Path:
    """Ensure weights + write runtime config with absolute POSIX qwen_emo_path."""
    ensure_core_checkpoints(model_dir)
    emo = ensure_qwen_emo_model(model_dir)
    try:
        from omegaconf import OmegaConf

        oc = OmegaConf.load(str(cfg_path))
        oc.qwen_emo_path = emo.as_posix()
        out = model_dir / "config.agent.yaml"
        OmegaConf.save(oc, str(out))
        return out
    except Exception:
        # Fallback: text patch (no OmegaConf in some envs)
        raw = cfg_path.read_text(encoding="utf-8")
        line = f'qwen_emo_path: "{emo.as_posix()}"'
        if re.search(r"(?m)^qwen_emo_path\s*:", raw):
            raw = re.sub(r"(?m)^qwen_emo_path\s*:.*$", line, raw)
        else:
            raw = raw.rstrip() + "\n" + line + "\n"
        out = model_dir / "config.agent.yaml"
        out.write_text(raw, encoding="utf-8")
        return out


def create_index_tts2(cfg: dict):
    from indextts.infer_v2 import IndexTTS2

    it_cfg = cfg.get("indextts", {})
    cfg_path, model_dir = model_paths(cfg)
    patched = prepare_indextts_cfg(cfg_path, model_dir)
    return IndexTTS2(
        cfg_path=str(patched.resolve()),
        model_dir=str(model_dir.resolve()),
        use_fp16=bool(it_cfg.get("use_fp16", True)),
        use_cuda_kernel=bool(it_cfg.get("use_cuda_kernel", False)),
        use_deepspeed=False,
    )


def _wav_duration_sec(path: Path) -> float:
    import wave

    with wave.open(str(path), "rb") as wf:
        rate = wf.getframerate() or 1
        return wf.getnframes() / float(rate)


def _resolve_max_mel_tokens(cfg: dict) -> int:
    it_cfg = cfg.get("indextts", {}) or {}
    if it_cfg.get("max_mel_tokens"):
        return int(it_cfg["max_mel_tokens"])
    try:
        cfg_path, _ = model_paths(cfg)
        model_cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
        return int((model_cfg.get("gpt") or {}).get("max_mel_tokens", 1815))
    except (OSError, TypeError, ValueError):
        return 1815


def _synthesis_complete(
    *,
    out: Path,
    est_audio: float,
    timing_segments: list[dict] | None,
    expected_segments: int,
    mode: str = "preset",
    has_emo: bool = False,
) -> bool:
    if not out.is_file() or out.stat().st_size < 1000:
        return False
    actual = _wav_duration_sec(out)
    threshold = 0.82
    if (mode or "").lower() == "clone":
        # 克隆 + 情感描述时语速常偏快，预估时长偏长；放宽避免误报截断
        threshold = 0.68 if has_emo else 0.76
    if est_audio > 0 and actual < est_audio * threshold:
        return False
    if timing_segments and len(timing_segments) < expected_segments:
        soft = 0.88 if has_emo and (mode or "").lower() == "clone" else 0.92
        if est_audio > 0 and actual < est_audio * soft:
            return False
    return True


def _retry_segment_tokens(base: int, attempt: int) -> int:
    """Progressively smaller segments to avoid max_mel_tokens truncation."""
    if attempt <= 0:
        return base
    factors = (0.75, 0.58, 0.5, 0.42)
    factor = factors[min(attempt - 1, len(factors) - 1)]
    return max(48, int(base * factor))


def run_index_tts_infer(
    tts,
    cfg: dict,
    *,
    speak_text: str,
    output_path: Path | str,
    spk_wav: str,
    speed: str = "balanced",
    emo_text: str = "",
    mode: str = "preset",
    on_progress: ProgressFn | None = None,
) -> Path:
    it_cfg = cfg.get("indextts", {})
    speed_cfg = get_speed_preset(speed).get("indextts", {})
    est_audio = estimate_speech_seconds(speak_text)
    out = Path(output_path)
    mode = (mode or "preset").lower()
    emo_text = (emo_text or "").strip()

    # Clone: default 只靠参考音；填写 emo_text 时可叠加情感（略牺牲一点相似度）
    if mode == "clone":
        allow = bool(it_cfg.get("clone_use_emo_text", True))
        if emo_text and allow:
            use_emo_text = True
        else:
            use_emo_text = False
            emo_text = ""
    else:
        use_emo_text = bool(emo_text) and bool(it_cfg.get("use_emo_text", True))

    def gr_progress(value: float, desc: str = "") -> None:
        seg_cur, seg_total = 0, 0
        m = re.search(r"(\d+)/(\d+)", desc or "")
        if m:
            seg_cur, seg_total = int(m.group(1)), int(m.group(2))
        inner = max(0.0, min(1.0, (float(value) - 0.1) / 0.8))
        pct = 0.22 + 0.75 * inner
        if seg_total > 0 and seg_cur > 0:
            synth = est_audio * seg_cur / seg_total
            msg_pct, msg_key, seg, audio_sec = (
                pct,
                "indextts_synth",
                (seg_cur, seg_total),
                synth,
            )
        else:
            msg_pct, msg_key, seg, audio_sec = pct, "indextts_synth", None, est_audio * inner
        if on_progress:
            from tts.progress import stage_label

            parts = [stage_label(msg_key)]
            if seg and seg[1] > 0:
                parts.append(f"段落 {seg[0]}/{seg[1]}")
            if audio_sec is not None:
                from tts.progress import format_hms

                parts.append(f"已合成 {format_hms(audio_sec)}")
            on_progress(msg_pct, " · ".join(parts))
        emit(msg_pct, msg_key, seg=seg, audio_sec=audio_sec)

    tts.gr_progress = gr_progress

    infer_kwargs = {
        "spk_audio_prompt": str(Path(spk_wav).resolve()),
        "text": speak_text,
        "output_path": str(out.resolve()),
        "verbose": True,
        "max_text_tokens_per_segment": int(
            speed_cfg.get(
                "max_text_tokens_per_segment",
                it_cfg.get("max_text_tokens_per_segment", 120),
            )
        ),
        "max_mel_tokens": _resolve_max_mel_tokens(cfg),
        "interval_silence": int(it_cfg.get("interval_silence", 200)),
        "use_emo_text": use_emo_text,
        "temperature": float(speed_cfg.get("temperature", it_cfg.get("temperature", 0.8))),
        "top_p": float(speed_cfg.get("top_p", it_cfg.get("top_p", 0.8))),
        "top_k": int(speed_cfg.get("top_k", it_cfg.get("top_k", 30))),
    }
    if emo_text and use_emo_text:
        infer_kwargs["emo_text"] = emo_text
        if mode == "clone":
            infer_kwargs["emo_alpha"] = float(it_cfg.get("clone_emo_alpha", 0.28))
        # Dialect style prompts need stronger weight; emotion text default ~0.6 is too soft
        elif mode == "dialect":
            infer_kwargs["emo_alpha"] = float(it_cfg.get("dialect_emo_alpha", 0.85))
        else:
            infer_kwargs["emo_alpha"] = float(it_cfg.get("emo_alpha", 0.6))

    if mode == "clone":
        infer_kwargs["temperature"] = min(
            float(infer_kwargs["temperature"]),
            float(it_cfg.get("clone_temperature", 0.75)),
        )

    if on_progress:
        on_progress(0.22, "IndexTTS 合成中…")
    emit(0.22, "indextts_synth", audio_sec=0.0)

    from tts.dubbing_timing import SAMPLING_RATE, capture_indextts_segment_timing, save_timing_manifest

    text_tokens_list = tts.tokenizer.tokenize(speak_text)
    base_seg_tokens = int(infer_kwargs["max_text_tokens_per_segment"])
    has_emo = bool(use_emo_text and emo_text)
    max_attempts = 4
    timing_segments: list[dict] = []

    for attempt in range(max_attempts):
        attempt_kwargs = dict(infer_kwargs)
        if attempt > 0:
            if out.is_file():
                out.unlink(missing_ok=True)
            attempt_kwargs["max_text_tokens_per_segment"] = _retry_segment_tokens(
                base_seg_tokens, attempt
            )
            if on_progress:
                on_progress(
                    0.22 + 0.02 * attempt,
                    f"检测到配音偏短，正在自动重试（分段 {attempt_kwargs['max_text_tokens_per_segment']}）…",
                )
            emit(0.22 + 0.02 * attempt, "indextts_synth")

        expected_segments = len(
            tts.tokenizer.split_segments(
                text_tokens_list, int(attempt_kwargs["max_text_tokens_per_segment"])
            )
        )
        tts.infer(**attempt_kwargs)
        infer_kwargs = attempt_kwargs

        if _synthesis_complete(
            out=out,
            est_audio=est_audio,
            timing_segments=None,
            expected_segments=expected_segments,
            mode=mode,
            has_emo=has_emo,
        ):
            break
    else:
        actual = _wav_duration_sec(out) if out.is_file() else 0.0
        # 克隆试听/短句：有可用音频且时长合理则放行（情感会改变语速）
        if (mode == "clone" and out.is_file() and actual >= 2.0
            and (est_audio <= 0 or actual >= est_audio * 0.62)):
            pass
        else:
            seg_hint = int(infer_kwargs.get("max_text_tokens_per_segment", base_seg_tokens))
            raise RuntimeError(
                f"配音不完整：实际约 {actual:.0f} 秒，预估约 {est_audio:.0f} 秒。"
                f"可能在长句或中英混排处被截断。请重新生成；若仍失败，"
                f"在 config.yaml 将 indextts.max_text_tokens_per_segment 调小（如 64，当前约 {seg_hint}）"
                f"或提高 max_mel_tokens（当前 {int(infer_kwargs.get('max_mel_tokens', 1815))}）。"
            )

    if mode != "clone":
        pre_duration = _wav_duration_sec(out) if out.is_file() else 0.0
        backup = out.read_bytes() if out.is_file() else None
        timing_segments = capture_indextts_segment_timing(tts, cfg, speak_text, infer_kwargs)
        if backup and (
            not out.is_file()
            or (pre_duration > 0 and _wav_duration_sec(out) < pre_duration * 0.95)
        ):
            out.write_bytes(backup)
            timing_segments = []

    if timing_segments:
        save_timing_manifest(
            out.parent,
            {
                "source": "tts_segments",
                "backend": "indextts",
                "sample_rate": SAMPLING_RATE,
                "interval_silence_ms": int(infer_kwargs.get("interval_silence", 200)),
                "duration": timing_segments[-1]["end"] if timing_segments else 0,
                "segments": timing_segments,
            },
        )
    elif mode == "clone" and out.is_file():
        save_timing_manifest(
            out.parent,
            {
                "source": "tts_clone",
                "backend": "indextts",
                "sample_rate": SAMPLING_RATE,
                "duration": round(_wav_duration_sec(out), 3),
                "segments": [],
            },
        )

    emit(0.98, "indextts_synth", audio_sec=est_audio)
    emit(1.0, "indextts_done", audio_sec=est_audio)
    if on_progress:
        on_progress(1.0, "IndexTTS2 完成")
    return out.resolve()

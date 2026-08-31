"""Run inside tools/Qwen3-TTS venv — local open-source Qwen3-TTS inference."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tts.progress import emit  # noqa: E402
from tts.qwen3_local import (  # noqa: E402
    base_model_dir,
    custom_voice_dir,
    qwen3_local_block,
    resolve_speaker,
    verify_qwen3_local,
)
from tts.text_normalize import latin_ratio  # noqa: E402


def _pick_language(text: str, default: str = "Chinese") -> str:
    """Prefer Auto on mixed CN–EN so leftover English is not force-Chinese."""
    share = latin_ratio(text)
    if share >= 0.55:
        return "English"
    if share >= 0.08:
        return "Auto"
    return default or "Chinese"


def _load_dtype(name: str):
    import torch

    key = (name or "bfloat16").lower()
    if key in ("bf16", "bfloat16"):
        return torch.bfloat16
    if key in ("fp16", "float16", "half"):
        return torch.float16
    return torch.float32


def _pick_device(cfg: dict) -> str:
    import torch

    block = qwen3_local_block(cfg)
    device = (block.get("device") or "").strip()
    if device:
        return device
    return "cuda:0" if torch.cuda.is_available() else "cpu"


def _load_model(model_dir: Path, cfg: dict):
    import torch
    from qwen_tts import Qwen3TTSModel

    block = qwen3_local_block(cfg)
    device = _pick_device(cfg)
    dtype = _load_dtype(block.get("dtype", "bfloat16" if device.startswith("cuda") else "float32"))
    attn = (block.get("attn_implementation") or "sdpa").strip()
    kwargs = {
        "device_map": device if device != "cpu" else "cpu",
        "dtype": dtype,
    }
    if attn and device != "cpu":
        kwargs["attn_implementation"] = attn
    try:
        return Qwen3TTSModel.from_pretrained(str(model_dir.resolve()), **kwargs)
    except TypeError:
        # older package may not accept attn_implementation
        kwargs.pop("attn_implementation", None)
        return Qwen3TTSModel.from_pretrained(str(model_dir.resolve()), **kwargs)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--text")
    parser.add_argument("--text-file")
    parser.add_argument("--output", required=True)
    parser.add_argument("--mode", default="preset")
    parser.add_argument("--preset", default="vivian")
    parser.add_argument("--style", default="")
    parser.add_argument("--reference")
    parser.add_argument("--prompt-text", default="")
    args = parser.parse_args()

    if args.text_file:
        text = Path(args.text_file).read_text(encoding="utf-8").strip()
    elif args.text:
        text = args.text.strip()
    else:
        parser.error("需要 --text 或 --text-file")

    import soundfile as sf
    import yaml

    emit(0.05, "config")
    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    health = verify_qwen3_local(cfg)
    mode = (args.mode or "preset").lower()

    if mode == "clone":
        if not health.get("clone_ready"):
            raise RuntimeError(health.get("message") or "本地 Qwen3 Base 模型未安装")
        if not args.reference:
            raise ValueError("Qwen3 本地克隆需要参考音频")
        prompt_text = (args.prompt_text or "").strip()
        if not prompt_text:
            raise ValueError("Qwen3 本地克隆需要参考文案（与参考音频内容一致）")
        model_dir = base_model_dir(cfg)
        emit(0.15, "load_model")
        model = _load_model(model_dir, cfg)
        emit(0.45, "gpu_synth")
        language = _pick_language(text, default="Chinese")
        wavs, sr = model.generate_voice_clone(
            text=text,
            language=language,
            ref_audio=str(Path(args.reference).resolve()),
            ref_text=prompt_text,
        )
    else:
        if not health.get("preset_ready"):
            raise RuntimeError(health.get("message") or "本地 Qwen3 CustomVoice 未安装")
        model_dir = custom_voice_dir(cfg)
        speaker, language = resolve_speaker(cfg, args.preset or "vivian")
        emit(0.15, "load_model")
        model = _load_model(model_dir, cfg)
        emit(0.45, "gpu_synth")
        language = _pick_language(text, default=language)
        instruct = (args.style or "").strip()
        kwargs = {
            "text": text,
            "language": language,
            "speaker": speaker,
        }
        if instruct:
            kwargs["instruct"] = instruct
        wavs, sr = model.generate_custom_voice(**kwargs)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    audio = wavs[0]
    sf.write(str(out), audio, sr)
    emit(1.0, "qwen3_local_done")
    print(json.dumps({"raw_audio": str(out.resolve()), "sample_rate": int(sr)}))


if __name__ == "__main__":
    main()

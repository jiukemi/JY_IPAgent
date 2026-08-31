"""Run inside tools/CosyVoice/CosyVoice venv — CosyVoice2 inference."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tts.progress import emit  # noqa: E402


def _ensure_cosyvoice_path(install: Path) -> None:
    """CosyVoice package + Matcha-TTS live in the install tree, not site-packages."""
    install = install.resolve()
    candidates = [
        install,
        install / "third_party" / "Matcha-TTS",
        install / "third_party" / "Matcha-TTS-main",
    ]
    for path in candidates:
        if path.is_dir() and str(path) not in sys.path:
            sys.path.insert(0, str(path))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--text")
    parser.add_argument("--text-file")
    parser.add_argument("--output", required=True)
    parser.add_argument("--reference")
    parser.add_argument("--prompt-text", default="")
    parser.add_argument("--mode", default="clone")
    parser.add_argument("--preset", default="")
    parser.add_argument("--style", default="")
    args = parser.parse_args()
    if args.text_file:
        tts_text = Path(args.text_file).read_text(encoding="utf-8").strip()
    elif args.text:
        tts_text = args.text.strip()
    else:
        parser.error("需要 --text 或 --text-file")
    if not tts_text:
        raise ValueError("文案不能为空")

    import torch
    import torchaudio
    import yaml

    emit(0.05, "config")
    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    cv_cfg = cfg.get("cosyvoice", {}) or {}
    install = Path(cfg["paths"]["cosyvoice_dir"])
    if not install.is_absolute():
        install = ROOT / install
    model_dir = install / cv_cfg.get("model_dir", "pretrained_models/CosyVoice2-0.5B")
    if not model_dir.exists():
        raise FileNotFoundError(
            f"CosyVoice 模型未找到: {model_dir}\n请运行 .\\scripts\\setup\\setup_cosyvoice.ps1"
        )

    _ensure_cosyvoice_path(install)

    mode = (args.mode or "clone").lower()
    # CosyVoice2-0.5B 无内置 SFT 说话人（无 spk2info.pt），仅支持零样本克隆；
    # 方言预设由上层 engine 走 Edge Neural，不应落到这里。
    if mode != "clone":
        raise ValueError(
            "CosyVoice2 仅支持音色克隆（零样本）。"
            "请选用已保存克隆音色，或切换到 Edge/IndexTTS 的预设/方言。"
        )
    if not args.reference:
        raise ValueError("CosyVoice 克隆需要参考音频")
    prompt_text = (args.prompt_text or "").strip()
    if not prompt_text:
        raise ValueError(
            "CosyVoice 克隆需要参考文案（须与参考音频中实际说的内容一致）"
        )

    emit(0.15, "load_model")
    from cosyvoice.cli.cosyvoice import AutoModel

    from tts.text_normalize import latin_ratio

    cosyvoice = AutoModel(model_dir=str(model_dir.resolve()))
    emit(0.45, "gpu_synth")
    out = Path(args.output)
    speech = []
    speed = float(cv_cfg.get("speed", 1.0))
    # Mixed CN+EN: cross-lingual reduces letter-by-letter English spelling.
    use_xling = latin_ratio(tts_text) >= 0.12
    if use_xling:
        emit(0.48, "cosy_cross_lingual")
        gen = cosyvoice.inference_cross_lingual(
            tts_text,
            args.reference,
            stream=False,
            speed=speed,
        )
    else:
        gen = cosyvoice.inference_zero_shot(
            tts_text,
            prompt_text,
            args.reference,
            stream=False,
            speed=speed,
        )
    for _, chunk in enumerate(gen):
        speech.append(chunk["tts_speech"])
    if not speech:
        raise RuntimeError("CosyVoice 未返回音频")
    merged = speech[0] if len(speech) == 1 else torch.cat(speech, dim=1)
    torchaudio.save(str(out), merged, cosyvoice.sample_rate)
    emit(1.0, "cosyvoice_done")
    print(
        json.dumps(
            {
                "raw_audio": str(out.resolve()),
                "cross_lingual": use_xling,
            }
        )
    )


if __name__ == "__main__":
    main()

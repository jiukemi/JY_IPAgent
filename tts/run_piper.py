"""Piper TTS — fast CPU synthesis."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tts.progress import emit  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--text", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", default="")
    args = parser.parse_args()

    import yaml

    emit(0.1, "config")
    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    piper_cfg = cfg.get("piper", {})
    model_path = Path(args.model) if args.model else Path(
        piper_cfg.get("model", "tools/Piper/zh_CN-huayan-medium.onnx")
    )
    if not model_path.exists():
        raise FileNotFoundError(
            f"Piper 模型缺失: {model_path}，请运行 scripts/setup/setup_piper.ps1"
        )

    emit(0.3, "load_model")
    from piper import PiperVoice

    voice = PiperVoice.load(str(model_path))
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)

    import wave

    emit(0.6, "cpu_synth")
    with wave.open(str(out), "wb") as wav_file:
        voice.synthesize_wav(args.text, wav_file)

    emit(1.0, "piper_done")
    print(json.dumps({"raw_audio": str(out)}))


if __name__ == "__main__":
    main()

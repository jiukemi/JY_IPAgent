"""Run inside tools/IndexTTS venv — IndexTTS2 one-shot inference (fallback when worker off)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tts.indextts_core import (  # noqa: E402
    create_index_tts2,
    load_project_cfg,
    resolve_speak_emo_spk,
    run_index_tts_infer,
)
from tts.progress import emit  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--text")
    parser.add_argument("--text-file")
    parser.add_argument("--output", required=True)
    parser.add_argument("--reference")
    parser.add_argument("--mode", default="preset")
    parser.add_argument("--preset", default="mandarin_female_warm")
    parser.add_argument("--style", default="")
    parser.add_argument("--speed", default="balanced")
    args = parser.parse_args()
    if args.text_file:
        speak_src = Path(args.text_file).read_text(encoding="utf-8").strip()
    elif args.text:
        speak_src = args.text.strip()
    else:
        parser.error("需要 --text 或 --text-file")

    emit(0.05, "config")
    cfg = load_project_cfg(args.config)
    speak_text, emo_text, spk_wav = resolve_speak_emo_spk(
        cfg,
        speak_text=speak_src,
        mode=args.mode,
        preset_id=args.preset,
        style_extra=args.style or "",
        reference_wav=args.reference,
    )

    emit(0.15, "indextts_load")
    tts = create_index_tts2(cfg)

    def _prog(p: float, _msg: str) -> None:
        emit(p, "indextts_synth")

    run_index_tts_infer(
        tts,
        cfg,
        speak_text=speak_text,
        output_path=args.output,
        spk_wav=spk_wav,
        speed=args.speed,
        emo_text=emo_text,
        mode=args.mode,
        on_progress=_prog,
    )
    print(json.dumps({"raw_audio": str(Path(args.output).resolve())}))


if __name__ == "__main__":
    main()

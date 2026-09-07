"""faster-whisper CLI with segment timestamps — used by tts/dubbing_timing.py for 混剪字幕.

Invoked with the Whisper engine venv Python (not the app runtime).
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--audio", required=True)
    p.add_argument("--model", default="small")
    p.add_argument("--language", default="zh")
    p.add_argument("--out", default="", help="Write JSON {segments:[...]} UTF-8")
    args = p.parse_args()

    from faster_whisper import WhisperModel

    device, compute = "cpu", "int8"
    try:
        import torch

        if torch.cuda.is_available():
            device, compute = "cuda", "float16"
    except Exception:
        pass

    model = WhisperModel(args.model, device=device, compute_type=compute)
    segments, _info = model.transcribe(
        str(Path(args.audio).resolve()),
        language=args.language or None,
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

    payload = {"segments": out}
    raw = json.dumps(payload, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(raw, encoding="utf-8")
    print(raw)


if __name__ == "__main__":
    main()

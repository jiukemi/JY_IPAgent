"""faster-whisper CLI with segment timestamps — used by tts/dubbing_timing.py for 混剪字幕.

Invoked with the Whisper engine venv Python (not the app runtime).
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path


def _setup_hf_mirror() -> Path:
    """Prefer China HF mirror; cache models under engines/Whisper/models."""
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    os.environ.setdefault("HUGGINGFACE_HUB_ENDPOINT", "https://hf-mirror.com")
    root = Path(__file__).resolve().parent
    models = root / "models"
    models.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(models / "hf_home"))
    return models


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--audio", required=True)
    p.add_argument("--model", default="small")
    p.add_argument("--language", default="zh")
    p.add_argument("--out", default="", help="Write JSON {segments:[...]} UTF-8")
    args = p.parse_args()

    download_root = _setup_hf_mirror()

    from faster_whisper import WhisperModel

    device, compute = "cpu", "int8"
    try:
        import torch

        if torch.cuda.is_available():
            device, compute = "cuda", "float16"
    except Exception:
        pass

    try:
        model = WhisperModel(
            args.model,
            device=device,
            compute_type=compute,
            download_root=str(download_root),
        )
    except Exception as exc:
        raise SystemExit(
            "Whisper 模型加载/下载失败。请确认：\n"
            "1) 设置 → 本机环境已安装 Whisper；\n"
            "2) 网络可访问 hf-mirror.com（或开梯子后重试）；\n"
            "3) 重装 Whisper 时会预下载 small 模型到 engines\\Whisper\\models。\n"
            f"详情: {exc}"
        ) from exc

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

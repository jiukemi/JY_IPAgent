"""IndexTTS2 warm worker — load model once, serve synthesis over stdio (JSON lines)."""

from __future__ import annotations

import argparse
import json
import sys
import traceback
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


def _progress_stdout(pct: float, msg: str) -> None:
    emit(pct, "indextts_synth")


def _handle_job(tts, cfg: dict, job: dict) -> dict:
    text_file = job.get("text_file")
    text = job.get("text") or ""
    if text_file:
        speak_src = Path(text_file).read_text(encoding="utf-8").strip()
    else:
        speak_src = str(text).strip()
    if not speak_src:
        raise ValueError("文案为空")

    output = Path(job["output"])
    speak_text, emo_text, spk_wav = resolve_speak_emo_spk(
        cfg,
        speak_text=speak_src,
        mode=job.get("mode") or "preset",
        preset_id=job.get("preset") or "mandarin_female_warm",
        style_extra=job.get("style") or "",
        reference_wav=job.get("reference"),
    )
    run_index_tts_infer(
        tts,
        cfg,
        speak_text=speak_text,
        output_path=output,
        spk_wav=spk_wav,
        speed=job.get("speed") or "balanced",
        emo_text=emo_text,
        mode=job.get("mode") or "preset",
        on_progress=_progress_stdout,
    )
    return {"ok": True, "raw_audio": str(output.resolve())}


def stdio_loop(config_path: Path) -> int:
    emit(0.05, "config")
    cfg = load_project_cfg(config_path)
    emit(0.10, "indextts_load")
    tts = create_index_tts2(cfg)
    emit(0.14, "indextts_ready")
    print(json.dumps({"ready": True, "backend": "indextts2-worker"}), flush=True)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        if line == "ping":
            print(json.dumps({"pong": True}), flush=True)
            continue
        if line == "shutdown":
            print(json.dumps({"shutdown": True}), flush=True)
            break
        try:
            job = json.loads(line)
            result = _handle_job(tts, cfg, job)
            print(json.dumps(result, ensure_ascii=False), flush=True)
        except Exception as exc:
            print(
                json.dumps(
                    {"ok": False, "error": str(exc), "trace": traceback.format_exc()},
                    ensure_ascii=False,
                ),
                flush=True,
            )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="IndexTTS2 warm worker (stdio JSON lines)")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--stdio", action="store_true", help="Read jobs from stdin (default)")
    args = parser.parse_args()
    config_path = Path(args.config).resolve()
    if not config_path.is_file():
        print(json.dumps({"ready": False, "error": f"config not found: {config_path}"}), flush=True)
        raise SystemExit(1)
    raise SystemExit(stdio_loop(config_path))


if __name__ == "__main__":
    main()

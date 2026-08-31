"""Pre-generate system voice preview WAVs into data/voice_previews/.

Run once (or after presets change):
    python -m tts.build_previews
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tts.preview_cache import PREVIEW_MIN_BYTES, PREVIEW_ROOT, build_preview, preview_path  # noqa: E402
from tts.voice_catalog import list_system_voices  # noqa: E402


def load_cfg() -> dict:
    import yaml

    path = ROOT / "config.yaml"
    if not path.exists():
        raise FileNotFoundError("缺少 config.yaml")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def main() -> None:
    cfg = load_cfg()
    PREVIEW_ROOT.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, str] = {}
    ok, skip, fail = 0, 0, 0

    voices = []
    for cat in ("mandarin", "dialect", "english"):
        voices.extend(list_system_voices(cat))

    print(f"==> 共 {len(voices)} 个系统音色待生成试听")
    for entry in voices:
        out = preview_path(entry.uid)
        if out.exists() and out.stat().st_size > PREVIEW_MIN_BYTES:
            manifest[entry.uid] = str(out)
            skip += 1
            print(f"  跳过（已存在） {entry.label}")
            continue
        print(f"  生成 {entry.label} [{entry.backend}] ...")
        path, err = build_preview(entry.uid, cfg)
        if path:
            manifest[entry.uid] = path
            ok += 1
            print(f"    -> {path}")
        else:
            fail += 1
            print(f"    !! 失败 {entry.uid}: {err or '未知'}")

    (PREVIEW_ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n完成: 新生成 {ok}, 已缓存 {skip}, 失败 {fail}")
    print(f"目录: {PREVIEW_ROOT.resolve()}")


if __name__ == "__main__":
    main()

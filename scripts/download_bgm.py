"""Download BGM clips tuned for short-video (trimmed segments)."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline import ensure_ffmpeg
from workflow.bgm import BGM_ROOT, MANIFEST, catalog_entries

CATALOG_VERSION = 2


def _probe_duration(probe: str, path: Path) -> float:
    from workflow.publish import media_duration

    return media_duration(probe, path)


def _try_url_download(url: str, dest: Path) -> bool:
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
        if len(data) < 100_000:
            return False
        dest.write_bytes(data)
        return True
    except OSError:
        return False


def _trim_clip(
    ffmpeg: str,
    probe: str,
    src: Path,
    dest: Path,
    *,
    start_sec: float,
    trim_sec: float,
) -> bool:
    start = max(0.0, float(start_sec))
    dur = max(30.0, float(trim_sec))
    cmd = [
        ffmpeg,
        "-y",
        "-ss",
        f"{start:.3f}",
        "-i",
        str(src),
        "-t",
        f"{dur:.3f}",
        "-c:a",
        "libmp3lame",
        "-q:a",
        "4",
        str(dest),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return dest.is_file() and dest.stat().st_size > 50_000
    except (subprocess.CalledProcessError, OSError):
        return False


def download_all(*, force: bool = False) -> int:
    BGM_ROOT.mkdir(parents=True, exist_ok=True)
    ffmpeg = ensure_ffmpeg("ffmpeg")
    probe = ffmpeg.replace("ffmpeg", "ffprobe") if "ffmpeg" in ffmpeg else "ffprobe"
    manifest: list[dict] = []
    ok = 0
    for row in catalog_entries():
        dest = BGM_ROOT / f"{row['name']}.mp3"
        clip_start = float(row.get("clip_start") or 0)
        trim_sec = float(row.get("trim_sec") or 75)
        print(f"-> {row['name']}.mp3 ({row.get('category', '')} · {row['mood']})")
        if dest.is_file() and not force:
            try:
                old = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.is_file() else []
                prev = next((x for x in old if x.get("id") == row["id"]), None)
                if (
                    prev
                    and prev.get("catalog_version") == CATALOG_VERSION
                    and prev.get("source") not in ("generated", "fallback")
                    and dest.stat().st_size > 200_000
                ):
                    manifest.append(prev)
                    ok += 1
                    print(f"   SKIP [{prev.get('source', 'cached')}] {dest.stat().st_size // 1024} KB")
                    continue
            except (json.JSONDecodeError, OSError):
                pass

        with tempfile.TemporaryDirectory() as tmp:
            full = Path(tmp) / "full.mp3"
            source = "soundhelix"
            if not _try_url_download(row["url"], full):
                print("   FAIL download")
                continue
            if not _trim_clip(ffmpeg, probe, full, dest, start_sec=clip_start, trim_sec=trim_sec):
                print("   FAIL trim")
                continue

        try:
            duration_sec = round(_probe_duration(probe, dest), 1)
        except Exception:
            duration_sec = trim_sec

        manifest.append(
            {
                "id": row["id"],
                "name": row["name"],
                "mood": row["mood"],
                "category": row.get("category", ""),
                "file": dest.name,
                "source": source,
                "url": row["url"],
                "clip_start": clip_start,
                "trim_sec": trim_sec,
                "duration_sec": duration_sec,
                "catalog_version": CATALOG_VERSION,
            }
        )
        ok += 1
        print(f"   OK [{source}] {dest.stat().st_size // 1024} KB · {duration_sec}s from {clip_start}s")
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nDone: {ok}/{len(catalog_entries())} tracks -> {BGM_ROOT}")
    print("可将自有 mp3 放入 data/bgm/ 并更新 manifest.json。")
    return ok


if __name__ == "__main__":
    force = "--force" in sys.argv
    download_all(force=force)

"""Ensure MP4/MOV have moov near the start so HTTP <video> can stream."""

from __future__ import annotations

from pathlib import Path

_VIDEO_EXT = {".mp4", ".m4v", ".mov"}


def mp4_needs_faststart(path: Path, *, probe_bytes: int = 2_000_000) -> bool:
    """True when moov atom is not near the start (browser must download entire file)."""
    try:
        size = path.stat().st_size
        if size < 64:
            return False
        with path.open("rb") as f:
            head = f.read(min(probe_bytes, size))
        return b"moov" not in head
    except OSError:
        return False


def _resolve_ffmpeg() -> str:
    from pipeline import ensure_ffmpeg
    from workflow.app_config import load_cfg

    try:
        return ensure_ffmpeg(load_cfg()["paths"].get("ffmpeg", "ffmpeg"))
    except Exception:
        return ensure_ffmpeg("ffmpeg")


def ensure_mp4_faststart(path: str | Path) -> Path:
    """Remux in place with +faststart when needed. Returns the playable path."""
    video = Path(path)
    if not video.is_file() or video.suffix.lower() not in _VIDEO_EXT:
        return video
    if not mp4_needs_faststart(video):
        return video
    tmp = video.with_name(video.stem + ".faststart.tmp" + video.suffix)
    try:
        import subprocess

        ffmpeg = _resolve_ffmpeg()
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(video),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(tmp),
            ],
            check=True,
            capture_output=True,
            timeout=300,
        )
        if not tmp.is_file() or tmp.stat().st_size < 100:
            tmp.unlink(missing_ok=True)
            return video
        bak = video.with_suffix(video.suffix + ".bak")
        try:
            if bak.exists():
                bak.unlink()
            video.replace(bak)
            tmp.replace(video)
            bak.unlink(missing_ok=True)
        except OSError:
            if tmp.is_file():
                return tmp
            return video
        return video
    except Exception:
        tmp.unlink(missing_ok=True)
        return video

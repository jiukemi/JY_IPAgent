"""Local digital-human avatar library (HeyGem reference videos + SadTalker portraits)."""

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

AVATAR_ROOT = Path("data/avatars")
INDEX_FILE = AVATAR_ROOT / "index.json"

_VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".m4v", ".avi"}
_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


@dataclass
class AvatarEntry:
    id: str
    name: str
    created_at: str
    source_kind: str = "video"  # video | portrait
    reference_video: str = ""
    reference_image: str = ""
    backend: str = "heygem"
    ai_prompt: str = ""

    @property
    def preview_path(self) -> Path | None:
        if self.source_kind == "portrait" and self.reference_image:
            p = Path(self.reference_image)
            return p if p.is_file() else None
        if self.reference_video:
            p = Path(self.reference_video)
            return p if p.is_file() else None
        return None

    @property
    def poster_path(self) -> Path | None:
        """Grid thumbnail — jpeg for video, portrait image for photos."""
        if self.source_kind == "portrait" and self.reference_image:
            p = Path(self.reference_image)
            return p if p.is_file() else None
        folder = AVATAR_ROOT / self.id
        poster = folder / "poster.jpg"
        if poster.is_file() and poster.stat().st_size > 100:
            return poster
        return None

    def supports_backend(self, backend: str) -> bool:
        b = (backend or "").lower()
        if b == "heygem":
            return self.source_kind == "video" and bool(self.reference_video)
        if b == "sadtalker":
            return self.source_kind == "portrait" and bool(self.reference_image)
        return False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at,
            "source_kind": self.source_kind,
            "reference_video": self.reference_video,
            "reference_image": self.reference_image,
            "backend": self.backend,
            "ai_prompt": self.ai_prompt,
        }


def _resolve_ffmpeg() -> str:
    from pipeline import ensure_ffmpeg
    from workflow.app_config import load_cfg

    try:
        return ensure_ffmpeg(load_cfg()["paths"].get("ffmpeg", "ffmpeg"))
    except Exception:
        return ensure_ffmpeg("ffmpeg")


def ensure_avatar_streamable(entry: AvatarEntry) -> Path | None:
    """Remux reference video with +faststart so in-app <video> can play without full download."""
    if entry.source_kind != "video" or not entry.reference_video:
        p = Path(entry.reference_image) if entry.reference_image else None
        return p if p and p.is_file() else None
    from workflow.mp4_faststart import ensure_mp4_faststart

    video = Path(entry.reference_video)
    if not video.is_file():
        return None
    return ensure_mp4_faststart(video)


def ensure_avatar_poster(entry: AvatarEntry) -> Path | None:
    """Create poster.jpg from reference video (lazy). Portraits use the image itself."""
    if entry.source_kind == "portrait":
        p = Path(entry.reference_image) if entry.reference_image else None
        return p if p and p.is_file() else None
    folder = AVATAR_ROOT / entry.id
    poster = folder / "poster.jpg"
    if poster.is_file() and poster.stat().st_size > 100:
        return poster
    video = Path(entry.reference_video) if entry.reference_video else None
    if not video or not video.is_file():
        return None
    folder.mkdir(parents=True, exist_ok=True)
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
                "-ss",
                "0.5",
                "-i",
                str(video),
                "-frames:v",
                "1",
                "-q:v",
                "4",
                str(poster),
            ],
            check=True,
            capture_output=True,
            timeout=60,
        )
        if poster.is_file() and poster.stat().st_size > 100:
            return poster
    except Exception:
        return None
    return None


def _load_index() -> list[dict]:
    if not INDEX_FILE.exists():
        return []
    try:
        data = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def _save_index(items: list[dict]) -> None:
    AVATAR_ROOT.mkdir(parents=True, exist_ok=True)
    INDEX_FILE.write_text(
        json.dumps(items, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _parse_entry(raw: dict) -> AvatarEntry | None:
    try:
        ref_video = raw.get("reference_video") or ""
        ref_image = raw.get("reference_image") or ""
        kind = raw.get("source_kind") or ("portrait" if ref_image and not ref_video else "video")
        return AvatarEntry(
            id=raw["id"],
            name=raw.get("name") or "未命名形象",
            created_at=raw.get("created_at") or "",
            source_kind=kind,
            reference_video=ref_video,
            reference_image=ref_image,
            backend=raw.get("backend") or ("sadtalker" if kind == "portrait" else "heygem"),
            ai_prompt=raw.get("ai_prompt") or "",
        )
    except (KeyError, TypeError):
        return None


def list_avatars() -> list[AvatarEntry]:
    out: list[AvatarEntry] = []
    for raw in _load_index():
        entry = _parse_entry(raw)
        if entry:
            out.append(entry)
    return out


def get_avatar(avatar_id: str) -> AvatarEntry | None:
    for e in list_avatars():
        if e.id == avatar_id:
            return e
    return None


def _detect_kind(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in _VIDEO_EXT:
        return "video"
    if ext in _IMAGE_EXT:
        return "portrait"
    raise ValueError("请上传 mp4/mov 参考视频，或 jpg/png 肖像图")


def save_avatar(
    name: str,
    media_source: str | Path,
    *,
    backend: str | None = None,
    ai_prompt: str = "",
) -> AvatarEntry:
    name = (name or "").strip() or "未命名形象"
    src = Path(media_source)
    if not src.is_file():
        raise FileNotFoundError(f"参考文件不存在: {src}")

    kind = _detect_kind(src)
    aid = uuid.uuid4().hex[:12]
    folder = AVATAR_ROOT / aid
    folder.mkdir(parents=True, exist_ok=True)
    ext = src.suffix.lower() or (".mp4" if kind == "video" else ".png")

    ref_video = ""
    ref_image = ""
    if kind == "video":
        dest = folder / f"reference{ext}"
        shutil.copy2(src, dest)
        ref_video = str(dest.resolve())
        default_backend = "heygem"
    else:
        dest = folder / f"portrait{ext}"
        shutil.copy2(src, dest)
        ref_image = str(dest.resolve())
        default_backend = "sadtalker"

    entry = AvatarEntry(
        id=aid,
        name=name,
        created_at=datetime.now().isoformat(timespec="seconds"),
        source_kind=kind,
        reference_video=ref_video,
        reference_image=ref_image,
        backend=(backend or default_backend).lower(),
        ai_prompt=(ai_prompt or "").strip(),
    )
    ensure_avatar_poster(entry)
    ensure_avatar_streamable(entry)
    items = _load_index()
    items.append(entry.to_dict())
    _save_index(items)
    return entry


def delete_avatar(avatar_id: str) -> bool:
    items = _load_index()
    kept = [x for x in items if x.get("id") != avatar_id]
    if len(kept) == len(items):
        return False
    _save_index(kept)
    folder = AVATAR_ROOT / avatar_id
    if folder.is_dir():
        shutil.rmtree(folder, ignore_errors=True)
    return True

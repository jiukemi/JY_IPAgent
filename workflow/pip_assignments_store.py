"""Persist publish HyperFrames cue assignments + optional asset-library mirror."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def assignments_path(session: Path) -> Path:
    return Path(session) / "publish" / "pip_cues" / "assignments.json"


def save_pip_assignments(session: Path, assignments: list[dict[str, Any]]) -> Path:
    path = assignments_path(session)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "assignments": assignments,
        "work_dir": str((Path(session) / "publish" / "pip_cues").resolve()),
        "note": "智能生成场景保存在会话目录；不会自动删除。刷新页面后可从此文件恢复列表。",
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def merge_pip_assignments(session: Path, new_assignments: list[dict[str, Any]]) -> Path:
    """Replace overlapping cue indices; keep other existing assignments."""
    existing = load_pip_assignments(session).get("assignments") or []
    covered: set[int] = set()
    for a in new_assignments:
        if not isinstance(a, dict):
            continue
        for i in a.get("cue_indices") or []:
            try:
                covered.add(int(i))
            except (TypeError, ValueError):
                pass
    kept: list[dict[str, Any]] = []
    for a in existing:
        if not isinstance(a, dict):
            continue
        idxs = []
        for i in a.get("cue_indices") or []:
            try:
                idxs.append(int(i))
            except (TypeError, ValueError):
                pass
        if idxs and any(i in covered for i in idxs):
            continue
        kept.append(a)
    merged = kept + [a for a in new_assignments if isinstance(a, dict)]
    return save_pip_assignments(session, merged)


def clear_pip_mix(session: Path, *, delete_generated: bool = True) -> dict[str, Any]:
    """Clear smart-scene assignments and optionally remove generated PiP/HyperFrames files."""
    import shutil

    session = Path(session)
    pip_root = session / "publish" / "pip_cues"
    removed_files = 0
    removed_dirs = 0
    if delete_generated and pip_root.is_dir():
        for child in pip_root.iterdir():
            if child.name == "assignments.json":
                continue
            if child.is_file():
                try:
                    child.unlink()
                    removed_files += 1
                except OSError:
                    pass
            elif child.is_dir():
                try:
                    shutil.rmtree(child, ignore_errors=True)
                    removed_dirs += 1
                except OSError:
                    pass
    save_pip_assignments(session, [])
    return {
        "assignments": [],
        "work_dir": str(pip_root.resolve()),
        "removed_files": removed_files,
        "removed_dirs": removed_dirs,
    }


def load_pip_assignments(session: Path) -> dict[str, Any]:
    path = assignments_path(session)
    if not path.is_file():
        return {"assignments": [], "work_dir": str((Path(session) / "publish" / "pip_cues").resolve())}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"assignments": [], "work_dir": str((Path(session) / "publish" / "pip_cues").resolve())}
    if not isinstance(data, dict):
        return {"assignments": [], "work_dir": str(path.parent.resolve())}
    items = data.get("assignments") if isinstance(data.get("assignments"), list) else []
    # Drop missing files
    kept = []
    for a in items:
        if not isinstance(a, dict):
            continue
        mp = Path(str(a.get("media_path") or ""))
        if mp.is_file():
            kept.append(a)
    return {
        "assignments": kept,
        "work_dir": str(data.get("work_dir") or path.parent.resolve()),
        "note": data.get("note") or "",
    }


def remove_pip_assignments(
    session: Path,
    *,
    cue_indices: list[int] | None = None,
    media_path: str | None = None,
    delete_media: bool = True,
) -> dict[str, Any]:
    """Remove one or more PiP assignments; optionally delete generated media files."""
    session = Path(session)
    data = load_pip_assignments(session)
    items = [a for a in (data.get("assignments") or []) if isinstance(a, dict)]
    if not items:
        return {"assignments": [], "removed": 0, "deleted_files": 0}

    target_idxs: set[int] | None = None
    if cue_indices:
        target_idxs = {int(i) for i in cue_indices if int(i) > 0}
    target_media = (media_path or "").strip()
    target_resolved = ""
    if target_media:
        try:
            target_resolved = str(Path(target_media).resolve())
        except OSError:
            target_resolved = target_media

    kept: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    for a in items:
        idxs = []
        for i in a.get("cue_indices") or []:
            try:
                idxs.append(int(i))
            except (TypeError, ValueError):
                pass
        mp = str(a.get("media_path") or "")
        mp_resolved = ""
        if mp:
            try:
                mp_resolved = str(Path(mp).resolve())
            except OSError:
                mp_resolved = mp
        match = False
        if target_idxs and idxs and any(i in target_idxs for i in idxs):
            match = True
        elif target_resolved and mp_resolved and mp_resolved == target_resolved:
            match = True
        elif target_resolved and mp and mp == target_media:
            match = True
        if match:
            removed.append(a)
        else:
            kept.append(a)

    deleted_files = 0
    if delete_media:
        for a in removed:
            mp = Path(str(a.get("media_path") or ""))
            if mp.is_file():
                try:
                    mp.unlink()
                    deleted_files += 1
                except OSError:
                    log.warning("failed to delete pip media: %s", mp)

    save_pip_assignments(session, kept)
    return {
        "assignments": kept,
        "removed": len(removed),
        "deleted_files": deleted_files,
    }


def mirror_assignments_to_library(assignments: list[dict[str, Any]], *, prefix: str = "智能场景") -> list[dict]:
    """Copy generated MP4/PNG into 素材中心 so they appear in Asset Center."""
    from workflow.asset_library import add_file_item

    saved: list[dict] = []
    for i, a in enumerate(assignments):
        mp = Path(str(a.get("media_path") or ""))
        if not mp.is_file():
            continue
        indices = a.get("cue_indices") or []
        label = f"{prefix} #{i + 1}"
        if indices:
            label = f"{prefix} 字幕{indices[0]}-{indices[-1]}"
        mime = "video/mp4" if mp.suffix.lower() in (".mp4", ".mov", ".webm", ".mkv") else "image/png"
        group = "video" if mime.startswith("video/") else "card"
        try:
            item = add_file_item(group, label, mp, mime=mime)
            saved.append(item)
        except Exception:
            log.exception("mirror scene to library failed: %s", mp)
    return saved

"""Project session folders for staged workflow artifacts."""

from __future__ import annotations

import json
import re
import shutil
import wave
from datetime import datetime
from pathlib import Path

SESSION_ROOT = Path("output/sessions")
META_FILE = "session.json"
LEGACY_META = "meta.txt"
_FOLDER_RE = re.compile(r"^\d{8}_\d{6}$")


def _folder_id(now: datetime | None = None) -> str:
    now = now or datetime.now()
    return now.strftime("%Y%m%d_%H%M%S")


def default_display_name(now: datetime | None = None) -> str:
    """yyyy-mm-dd-HHMMSS"""
    now = now or datetime.now()
    return f"{now.strftime('%Y-%m-%d')}-{now.strftime('%H%M%S')}"


def folder_to_display_name(folder_name: str) -> str:
    if _FOLDER_RE.match(folder_name):
        return f"{folder_name[:4]}-{folder_name[4:6]}-{folder_name[6:8]}-{folder_name[9:]}"
    return folder_name


def _read_meta(path: Path) -> dict:
    meta_path = path / META_FILE
    if meta_path.exists():
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    legacy = path / LEGACY_META
    folder_id = path.name
    name = folder_to_display_name(folder_id)
    created = datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
    if legacy.exists():
        for line in legacy.read_text(encoding="utf-8").splitlines():
            if line.startswith("session="):
                folder_id = line.split("=", 1)[1].strip() or folder_id
    return {
        "id": folder_id,
        "name": name,
        "created_at": created,
    }


def _write_meta(path: Path, data: dict) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / META_FILE).write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (path / LEGACY_META).write_text(f"session={data['id']}\n", encoding="utf-8")


def session_badges(path: Path) -> list[str]:
    badges: list[str] = []
    script_p = path / "script.txt"
    if script_p.exists() and script_p.read_text(encoding="utf-8").strip():
        badges.append("文案")
    if (path / "dubbing_16k.wav").exists():
        badges.append("配音")
    if (path / "input_video.mp4").exists():
        badges.append("视频")
    if (path / "final_lipsync.mp4").exists() or (path / "real_lipsync.mp4").exists():
        badges.append("成片")
    if (path / "digital_lipsync.mp4").exists():
        badges.append("数字人")
    if (path / "final_publish.mp4").exists():
        badges.append("发布")
    return badges


def session_status(path: Path) -> str:
    badges = session_badges(path)
    return " · ".join(badges) if badges else "空白"


def format_created_at(iso: str) -> str:
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return iso[:16].replace("T", " ")
    now = datetime.now()
    if dt.date() == now.date():
        return f"今天 {dt.strftime('%H:%M')}"
    if dt.year == now.year:
        return dt.strftime("%m-%d %H:%M")
    return dt.strftime("%Y-%m-%d %H:%M")


def list_sessions(root: Path = SESSION_ROOT) -> list[dict]:
    if not root.exists():
        return []
    items: list[dict] = []
    for path in root.iterdir():
        if not path.is_dir() or path.name.startswith("_"):
            continue
        meta = _read_meta(path)
        badges = session_badges(path)
        created = meta.get("created_at", "")
        items.append(
            {
                "id": meta.get("id", path.name),
                "name": meta.get("name", folder_to_display_name(path.name)),
                "path": str(path.resolve()),
                "folder": path.name,
                "created_at": created,
                "created_label": format_created_at(created),
                "badges": badges,
                "status": session_status(path),
            }
        )
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return items


def get_session_by_path(path_str: str, root: Path = SESSION_ROOT) -> dict | None:
    if not path_str:
        return None
    path = Path(path_str)
    for item in list_sessions(root):
        if Path(item["path"]) == path.resolve():
            return item
    return None


def system_jobs_session(root: Path = SESSION_ROOT) -> Path:
    """Fixed session folder for global jobs (engine installs, etc.)."""
    path = root / "_system"
    path.mkdir(parents=True, exist_ok=True)
    meta = path / META_FILE
    if not meta.is_file():
        now = datetime.now()
        _write_meta(
            path,
            {
                "id": "_system",
                "name": "系统任务",
                "created_at": now.isoformat(timespec="seconds"),
                "system": True,
            },
        )
    return path.resolve()


def ensure_session_dir(path_str: str | None = None, root: Path = SESSION_ROOT) -> Path:
    """Return a valid session directory; recover if *path_str* is missing on disk."""
    if path_str:
        p = Path(path_str)
        if p.is_dir():
            return p.resolve()
    latest = latest_session(root)
    if latest is not None and latest.is_dir():
        return latest.resolve()
    return new_session(root=root).resolve()


def new_session(name: str | None = None, root: Path = SESSION_ROOT) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    sid = _folder_id(now)
    path = root / sid
    path.mkdir(parents=True, exist_ok=True)
    display = (name or "").strip() or default_display_name(now)
    _write_meta(
        path,
        {
            "id": sid,
            "name": display,
            "created_at": now.isoformat(timespec="seconds"),
        },
    )
    return path


def rename_session(path_str: str, name: str) -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError("会话名称不能为空")
    path = Path(path_str)
    if not path.exists():
        raise FileNotFoundError(f"会话不存在: {path_str}")
    meta = _read_meta(path)
    meta["name"] = name
    _write_meta(path, meta)
    return meta


def delete_session(path_str: str) -> bool:
    path = Path(path_str)
    if not path.exists() or not path.is_dir():
        return False
    if path.resolve() == SESSION_ROOT.resolve():
        return False
    shutil.rmtree(path, ignore_errors=True)
    return True


def latest_session(root: Path = SESSION_ROOT) -> Path | None:
    sessions = list_sessions(root)
    if not sessions:
        return None
    path = Path(sessions[0]["path"])
    return path if path.is_dir() else None


_DUB_NAME_RE = re.compile(r"[^\w\u4e00-\u9fff\-]+", re.UNICODE)

_LIPSYNC_OUTPUTS = (
    "final_lipsync.mp4",
    "real_lipsync.mp4",
    "digital_lipsync.mp4",
    "latentsync_raw.mp4",
    "sadtalker_audio_16k.wav",
)

# Canonical session lipsync files (overwritten each run; history lives in lipsync_takes/)
_LIPSYNC_CANONICAL = (
    "final_lipsync.mp4",
    "real_lipsync.mp4",
    "digital_lipsync.mp4",
    "latentsync_raw.mp4",
    "heygem_raw.mp4",
    "sadtalker_raw.mp4",
)


def _file_mtime(path: Path | str | None) -> float | None:
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        return None
    try:
        return p.stat().st_mtime
    except OSError:
        return None


def invalidate_stale_lipsync_outputs(session_path: Path | str) -> list[str]:
    """Remove avatar outputs that may still reflect an older dubbing track.

    Keeps lipsync_takes/ history; only clears canonical session files.
    """
    p = Path(session_path)
    if not p.is_dir():
        return []
    removed: list[str] = []
    for name in _LIPSYNC_OUTPUTS:
        fp = p / name
        if fp.is_file():
            try:
                fp.unlink()
                removed.append(name)
            except OSError:
                pass
    meta = _read_meta(p)
    meta["dubbing_updated_at"] = datetime.now().isoformat(timespec="seconds")
    if removed:
        meta["lipsync_cleared_at"] = meta["dubbing_updated_at"]
        # Prefer an archived take if present; otherwise clear selection
        takes = list_session_lipsyncs(p)
        archived = [t for t in takes if t.get("source") != "current"]
        if archived:
            meta["selected_lipsync_path"] = archived[0]["path"]
        else:
            meta.pop("selected_lipsync_path", None)
    _write_meta(p, meta)
    return removed


def lipsync_needs_regen(session_path: Path | str) -> bool:
    p = Path(session_path)
    if not p.is_dir():
        return False
    dub = p / "dubbing_16k.wav"
    if not dub.is_file():
        return False
    dub_mtime = _file_mtime(dub)
    if dub_mtime is None:
        return False
    selected = resolve_selected_lipsync_path(p)
    if selected:
        lip_mtime = _file_mtime(Path(selected))
        return lip_mtime is not None and lip_mtime < dub_mtime - 1
    for name in _LIPSYNC_OUTPUTS:
        if not name.endswith(".mp4"):
            continue
        fp = p / name
        if fp.is_file():
            lip_mtime = _file_mtime(fp)
            if lip_mtime is not None and lip_mtime < dub_mtime - 1:
                return True
    return False


def _sanitize_dub_filename(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise ValueError("请输入配音名称")
    safe = _DUB_NAME_RE.sub("_", name).strip("_")
    if not safe:
        safe = "dub"
    return safe[:60]


def _read_dub_audio_meta(session_dir: Path, wav_path: Path | None = None) -> dict:
    """Duration + segment count for a dub wav (timing file applies to current 成片)."""
    import json
    import wave

    out: dict = {"duration_sec": None, "segment_count": None}
    fp = wav_path or (session_dir / "dubbing_16k.wav")
    if fp.is_file():
        try:
            with wave.open(str(fp), "rb") as wf:
                rate = wf.getframerate() or 1
                out["duration_sec"] = round(wf.getnframes() / float(rate), 2)
        except (OSError, ValueError):
            pass
    timing = session_dir / "dubbing_timing.json"
    if wav_path is None and timing.is_file():
        try:
            data = json.loads(timing.read_text(encoding="utf-8"))
            segs = data.get("segments") or []
            if segs:
                out["segment_count"] = len(segs)
            dur = float(data.get("duration") or 0)
            if dur > 0:
                out["duration_sec"] = round(dur, 2)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass
    return out


def archive_current_dubbing(session_path: Path | str) -> dict | None:
    """Before overwriting dubbing_16k.wav, archive the previous generation into dubs/."""
    p = ensure_session_dir(session_path)
    src = p / "dubbing_16k.wav"
    if not src.is_file() or src.stat().st_size < 1000:
        return None

    meta = _read_meta(p)
    dubbings = meta.get("dubbings")
    if not isinstance(dubbings, list):
        dubbings = []

    dubs_dir = p / "dubs"
    dubs_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    dest = dubs_dir / f"tts_{now.strftime('%Y%m%d_%H%M%S')}.wav"
    while dest.exists():
        dest = dubs_dir / f"tts_{now.strftime('%Y%m%d_%H%M%S')}_{dest.suffix}"
    shutil.copy2(src, dest)

    audio_meta = _read_dub_audio_meta(p)
    history_n = sum(1 for e in dubbings if isinstance(e, dict) and e.get("source") == "tts_archive") + 1
    seg_note = ""
    if audio_meta.get("segment_count"):
        seg_note = f" · {audio_meta['segment_count']}段"
    entry = {
        "id": dest.stem,
        "name": f"配音 #{history_n}（{now.strftime('%m-%d %H:%M')}{seg_note}）",
        "file": dest.relative_to(p).as_posix(),
        "created_at": now.isoformat(timespec="seconds"),
        "source": "tts_archive",
        "duration_sec": audio_meta.get("duration_sec"),
        "segment_count": audio_meta.get("segment_count"),
    }
    dubbings.append(entry)
    meta["dubbings"] = dubbings
    _write_meta(p, meta)
    return {**entry, "path": str(dest.resolve())}


def find_canonical_lipsync(session_path: Path | str) -> Path | None:
    """Newest playable canonical lipsync file in the session root (not history folder)."""
    p = Path(session_path)
    if not p.is_dir():
        return None
    cands = [
        p / name
        for name in _LIPSYNC_CANONICAL
        if (p / name).is_file() and (p / name).stat().st_size > 50_000
    ]
    if not cands:
        return None
    return max(cands, key=lambda x: x.stat().st_mtime)


def archive_current_lipsync(
    session_path: Path | str,
    *,
    backend: str = "",
    mode: str = "",
) -> dict | None:
    """Before overwriting lipsync outputs, archive the previous take into lipsync_takes/."""
    p = ensure_session_dir(session_path)
    src = find_canonical_lipsync(p)
    if src is None:
        return None

    meta = _read_meta(p)
    takes = meta.get("lipsyncs")
    if not isinstance(takes, list):
        takes = []

    takes_dir = p / "lipsync_takes"
    takes_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    tag = (backend or mode or "take").strip().lower().replace(" ", "_")[:24] or "take"
    stamp = now.strftime("%Y%m%d_%H%M%S")
    dest = takes_dir / f"{tag}_{stamp}.mp4"
    n = 0
    while dest.exists():
        n += 1
        dest = takes_dir / f"{tag}_{stamp}_{n}.mp4"
    shutil.copy2(src, dest)

    history_n = sum(1 for e in takes if isinstance(e, dict) and e.get("source") == "lipsync_archive") + 1
    mode_l = (mode or "").lower()
    label = "数字人" if mode_l == "digital" or "heygem" in tag or "sad" in tag else "实拍"
    engine_note = f" · {tag}" if tag and tag not in ("take", "digital", "real") else ""
    entry = {
        "id": dest.stem,
        "name": f"口播 #{history_n}（{label}{engine_note} · {now.strftime('%m-%d %H:%M')}）",
        "file": dest.relative_to(p).as_posix(),
        "created_at": now.isoformat(timespec="seconds"),
        "source": "lipsync_archive",
        "backend": (backend or "").strip().lower(),
        "mode": mode_l,
    }
    takes.append(entry)
    meta["lipsyncs"] = takes
    _write_meta(p, meta)
    return {**entry, "path": str(dest.resolve())}


def _sync_lipsync_takes_folder(session_path: Path) -> None:
    p = session_path
    takes_dir = p / "lipsync_takes"
    if not takes_dir.is_dir():
        return
    meta = _read_meta(p)
    takes = meta.get("lipsyncs")
    if not isinstance(takes, list):
        takes = []
    known = {e.get("file") for e in takes if isinstance(e, dict)}
    changed = False
    for fp in sorted(takes_dir.glob("*.mp4"), key=lambda x: x.stat().st_mtime, reverse=True):
        if fp.stat().st_size < 50_000:
            continue
        rel = fp.relative_to(p).as_posix()
        if rel in known:
            continue
        takes.append(
            {
                "id": fp.stem,
                "name": fp.stem.replace("_", " "),
                "file": rel,
                "created_at": datetime.fromtimestamp(fp.stat().st_mtime).isoformat(timespec="seconds"),
                "source": "imported",
            }
        )
        changed = True
    if changed:
        meta["lipsyncs"] = takes
        _write_meta(p, meta)


def _lipsync_file_key(fp: Path) -> tuple[int, int]:
    st = fp.stat()
    return (int(st.st_size), int(st.st_mtime))


def list_session_lipsyncs(session_path: Path | str | None) -> list[dict]:
    """Return lipsync takes: current canonical first, then archives / leftover roots."""
    if not session_path:
        return []
    p = Path(session_path)
    if not p.is_dir():
        return []
    _sync_lipsync_takes_folder(p)
    meta = _read_meta(p)
    named = meta.get("lipsyncs")
    if not isinstance(named, list):
        named = []
    items: list[dict] = []
    seen_keys: set[tuple[int, int]] = set()
    seen_paths: set[str] = set()

    def _add(item: dict) -> None:
        path_str = item.get("path") or ""
        if not path_str:
            return
        fp = Path(path_str)
        if not fp.is_file() or fp.stat().st_size < 50_000:
            return
        try:
            resolved = str(fp.resolve())
        except OSError:
            return
        key = _lipsync_file_key(fp)
        if resolved in seen_paths or key in seen_keys:
            return
        seen_paths.add(resolved)
        seen_keys.add(key)
        items.append({**item, "path": resolved})

    current = find_canonical_lipsync(p)
    if current is not None:
        _add(
            {
                "id": "_current",
                "name": f"当前成片 · {current.name}",
                "path": str(current.resolve()),
                "created_at": datetime.fromtimestamp(current.stat().st_mtime).isoformat(timespec="seconds"),
                "source": "current",
                "backend": "",
                "mode": "",
            }
        )
    saved: list[dict] = []
    for entry in named:
        if not isinstance(entry, dict):
            continue
        rel = entry.get("file", "")
        if not rel:
            continue
        fp = p / rel
        if not fp.is_file() or fp.stat().st_size < 50_000:
            continue
        saved.append(
            {
                "id": entry.get("id") or fp.stem,
                "name": entry.get("name") or fp.stem,
                "path": str(fp.resolve()),
                "created_at": entry.get("created_at") or "",
                "source": entry.get("source") or "lipsync_archive",
                "backend": entry.get("backend") or "",
                "mode": entry.get("mode") or "",
            }
        )
    saved.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    for item in saved:
        _add(item)

    # Legacy leftovers still sitting in session root (pre-archive era)
    _LEGACY_LABELS = {
        "final_lipsync.mp4": "遗留成片",
        "digital_lipsync.mp4": "数字人口播",
        "real_lipsync.mp4": "实拍换嘴",
        "latentsync_raw.mp4": "LatentSync 原稿",
        "heygem_raw.mp4": "HeyGem 原稿",
        "sadtalker_raw.mp4": "SadTalker 原稿",
    }
    legacy: list[dict] = []
    for name, label in _LEGACY_LABELS.items():
        fp = p / name
        if not fp.is_file() or fp.stat().st_size < 50_000:
            continue
        if current is not None and fp.resolve() == current.resolve():
            continue
        mtime = datetime.fromtimestamp(fp.stat().st_mtime)
        legacy.append(
            {
                "id": f"legacy_{fp.stem}",
                "name": f"{label}（{mtime.strftime('%m-%d %H:%M')}）",
                "path": str(fp.resolve()),
                "created_at": mtime.isoformat(timespec="seconds"),
                "source": "legacy",
                "backend": "",
                "mode": "",
            }
        )
    legacy.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    for item in legacy:
        _add(item)
    return items


def resolve_selected_lipsync_path(session_path: Path | str) -> str | None:
    """Validated selected lipsync path, else newest among current + history."""
    p = Path(session_path)
    if not p.is_dir():
        return None
    takes = list_session_lipsyncs(p)
    if not takes:
        return None
    meta = _read_meta(p)
    saved = (meta.get("selected_lipsync_path") or "").strip()
    if saved:
        for item in takes:
            try:
                if item.get("path") == saved or Path(item.get("path", "")).resolve() == Path(saved).resolve():
                    return item["path"]
            except OSError:
                continue
    # Prefer current canonical; else first history item
    for item in takes:
        if item.get("source") == "current":
            return item["path"]
    return takes[0]["path"]


def set_selected_lipsync_path(session_path: str, video_path: str | None) -> dict:
    """Persist which lipsync take is active for preview / publish."""
    p = ensure_session_dir(session_path)
    takes = list_session_lipsyncs(p)
    if not takes:
        raise FileNotFoundError("暂无可用口播成片")
    target = (video_path or "").strip()
    if not target:
        target = takes[0]["path"]
    resolved = None
    for item in takes:
        ip = Path(item.get("path", ""))
        try:
            if item.get("path") == target or (ip.is_file() and ip.resolve() == Path(target).resolve()):
                resolved = item["path"]
                break
        except OSError:
            continue
    if not resolved:
        raise FileNotFoundError("所选口播成片不存在，请重新选择")
    meta = _read_meta(p)
    meta["selected_lipsync_path"] = resolved
    _write_meta(p, meta)
    return {"selected_lipsync_path": resolved}


def delete_session_lipsync(session_path: str, take_id: str) -> dict:
    """Delete an archived / legacy / current lipsync take (keeps other versions)."""
    p = ensure_session_dir(session_path)
    take_id = (take_id or "").strip()
    if not take_id:
        raise ValueError("请指定要删除的口播版本")

    takes = list_session_lipsyncs(p)
    found = next((t for t in takes if (t.get("id") or "") == take_id), None)
    if found is None:
        # Also match by filename stem in path
        found = next(
            (t for t in takes if Path(t.get("path", "")).stem == take_id),
            None,
        )
    if found is None:
        raise FileNotFoundError("口播版本不存在")

    target = Path(found["path"])
    deleted_abs = ""
    if target.is_file():
        deleted_abs = str(target.resolve())
        try:
            target.unlink()
        except OSError as exc:
            raise ValueError(f"无法删除文件: {exc}") from exc

    meta = _read_meta(p)
    named = meta.get("lipsyncs")
    if isinstance(named, list):
        remaining: list = []
        for e in named:
            if not isinstance(e, dict):
                continue
            if e.get("id") == take_id or e.get("id") == found.get("id"):
                continue
            rel = e.get("file") or ""
            if deleted_abs and rel:
                try:
                    if (p / rel).resolve() == Path(deleted_abs).resolve():
                        continue
                except OSError:
                    pass
            remaining.append(e)
        meta["lipsyncs"] = remaining

    selected = (meta.get("selected_lipsync_path") or "").strip()
    if selected and deleted_abs:
        try:
            if Path(selected).resolve() == Path(deleted_abs).resolve():
                meta.pop("selected_lipsync_path", None)
        except OSError:
            if selected == deleted_abs:
                meta.pop("selected_lipsync_path", None)
    _write_meta(p, meta)

    remaining_takes = list_session_lipsyncs(p)
    if remaining_takes and not (meta.get("selected_lipsync_path") or "").strip():
        set_selected_lipsync_path(str(p), remaining_takes[0]["path"])

    return {
        "id": found.get("id") or take_id,
        "name": found.get("name", take_id),
        "deleted": True,
    }


def prune_missing_lipsync_meta(session_path: Path | str) -> int:
    """Drop lipsync meta / selection entries whose files no longer exist. Returns pruned count."""
    p = ensure_session_dir(session_path)
    meta = _read_meta(p)
    named = meta.get("lipsyncs")
    if not isinstance(named, list):
        named = []
    kept: list = []
    pruned = 0
    for e in named:
        if not isinstance(e, dict):
            pruned += 1
            continue
        rel = (e.get("file") or "").strip()
        if not rel:
            pruned += 1
            continue
        fp = p / rel
        if fp.is_file() and fp.stat().st_size >= 50_000:
            kept.append(e)
        else:
            pruned += 1
    meta["lipsyncs"] = kept

    selected = (meta.get("selected_lipsync_path") or "").strip()
    if selected:
        try:
            sel = Path(selected)
            if not sel.is_file() or sel.stat().st_size < 50_000:
                meta.pop("selected_lipsync_path", None)
                pruned += 1
        except OSError:
            meta.pop("selected_lipsync_path", None)
            pruned += 1

    _write_meta(p, meta)
    return pruned


def _sync_dubs_folder(session_path: Path) -> None:
    """Register orphan wav files under dubs/ that are missing from session meta."""
    p = session_path
    dubs_dir = p / "dubs"
    if not dubs_dir.is_dir():
        return
    meta = _read_meta(p)
    dubbings = meta.get("dubbings")
    if not isinstance(dubbings, list):
        dubbings = []
    known = {e.get("file") for e in dubbings if isinstance(e, dict)}
    changed = False
    for fp in sorted(dubs_dir.glob("*.wav"), key=lambda x: x.stat().st_mtime, reverse=True):
        rel = fp.relative_to(p).as_posix()
        if rel in known:
            continue
        try:
            with wave.open(str(fp), "rb") as wf:
                rate = wf.getframerate() or 1
                dur = round(wf.getnframes() / float(rate), 2)
        except (OSError, ValueError):
            dur = None
        dubbings.append(
            {
                "id": fp.stem,
                "name": fp.stem.replace("_", " "),
                "file": rel,
                "created_at": datetime.fromtimestamp(fp.stat().st_mtime).isoformat(timespec="seconds"),
                "source": "imported",
                "duration_sec": dur,
            }
        )
        changed = True
    if changed:
        meta["dubbings"] = dubbings
        _write_meta(p, meta)


def list_session_dubbings(session_path: Path | str | None) -> list[dict]:
    """Return dub tracks: current 成片 first, then archived/history copies."""
    if not session_path:
        return []
    p = Path(session_path)
    if not p.is_dir():
        return []
    _sync_dubs_folder(p)
    meta = _read_meta(p)
    named = meta.get("dubbings")
    if not isinstance(named, list):
        named = []
    items: list[dict] = []
    current = p / "dubbing_16k.wav"
    if current.exists():
        cur_meta = _read_dub_audio_meta(p)
        items.append(
            {
                "id": "_current",
                "name": "当前成片",
                "path": str(current.resolve()),
                "created_at": "",
                "duration_sec": cur_meta.get("duration_sec"),
                "segment_count": cur_meta.get("segment_count"),
                "source": "current",
            }
        )
    saved: list[dict] = []
    for entry in named:
        if not isinstance(entry, dict):
            continue
        rel = entry.get("file", "")
        if not rel:
            continue
        fp = p / rel
        if fp.is_file():
            dur = entry.get("duration_sec")
            if dur is None:
                try:
                    with wave.open(str(fp), "rb") as wf:
                        rate = wf.getframerate() or 1
                        dur = round(wf.getnframes() / float(rate), 2)
                except (OSError, ValueError):
                    dur = None
            saved.append(
                {
                    "id": entry.get("id", fp.stem),
                    "name": entry.get("name", fp.stem),
                    "path": str(fp.resolve()),
                    "created_at": entry.get("created_at", ""),
                    "duration_sec": dur,
                    "segment_count": entry.get("segment_count"),
                    "source": entry.get("source", "saved"),
                }
            )
    saved.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    items.extend(saved)
    return items


def save_named_dubbing(
    session_path: str, name: str, source_path: str | None = None
) -> dict:
    """Copy dub audio into session dubs/ and register under a display name."""
    p = ensure_session_dir(session_path)
    display_name = (name or "").strip()
    if not display_name:
        raise ValueError("请输入配音名称")
    src = Path(source_path) if source_path else p / "dubbing_16k.wav"
    if not src.is_file():
        raise FileNotFoundError("没有可保存的配音，请先生成或上传")
    safe = _sanitize_dub_filename(display_name)
    dubs_dir = p / "dubs"
    dubs_dir.mkdir(parents=True, exist_ok=True)
    dest = dubs_dir / f"{safe}.wav"
    if dest.exists():
        dest = dubs_dir / f"{safe}_{datetime.now().strftime('%H%M%S')}.wav"
    shutil.copy2(src, dest)
    rel = dest.relative_to(p).as_posix()
    entry = {
        "id": dest.stem,
        "name": display_name,
        "file": rel,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    meta = _read_meta(p)
    dubbings = meta.get("dubbings")
    if not isinstance(dubbings, list):
        dubbings = []
    dubbings.append(entry)
    meta["dubbings"] = dubbings
    _write_meta(p, meta)
    return {**entry, "path": str(dest.resolve())}


def read_session_scripts(session_path: Path | str) -> dict[str, str]:
    """Active script (script.txt) plus extract / rewritten variants."""
    p = Path(session_path)
    if not p.is_dir():
        return {"active": "", "extract": "", "rewritten": "", "legal": "", "manual": ""}

    def _read(name: str) -> str:
        fp = p / name
        return fp.read_text(encoding="utf-8").strip() if fp.is_file() else ""

    active = _read("script.txt")
    extract = _read("script_extract.txt") or active
    rewritten = _read("script_rewritten.txt")
    legal = _read("script_legal.txt")
    manual = _read("script_manual.txt")
    return {
        "active": active,
        "extract": extract,
        "rewritten": rewritten,
        "legal": legal,
        "manual": manual,
    }


def save_script_variant(session_path: str, variant: str, text: str) -> dict[str, str]:
    """Persist extract or rewritten copy; script.txt follows the saved variant."""
    p = ensure_session_dir(session_path)
    body = (text or "").strip()
    if variant == "extract":
        (p / "script_extract.txt").write_text(body, encoding="utf-8")
        (p / "script.txt").write_text(body, encoding="utf-8")
    elif variant == "rewritten":
        (p / "script_rewritten.txt").write_text(body, encoding="utf-8")
        (p / "script.txt").write_text(body, encoding="utf-8")
    elif variant == "legal":
        (p / "script_legal.txt").write_text(body, encoding="utf-8")
        (p / "script.txt").write_text(body, encoding="utf-8")
    elif variant == "manual":
        (p / "script_manual.txt").write_text(body, encoding="utf-8")
    else:
        raise ValueError("variant 必须是 extract、rewritten、legal 或 manual")
    return read_session_scripts(p)


def snapshot_script_extract(session_path: str, text: str) -> None:
    """After ASR/extract pipeline writes script.txt."""
    p = ensure_session_dir(session_path)
    body = (text or "").strip()
    if body:
        (p / "script_extract.txt").write_text(body, encoding="utf-8")


def snapshot_script_rewritten(session_path: str, text: str) -> None:
    """After rewrite pipeline writes script.txt."""
    p = ensure_session_dir(session_path)
    body = (text or "").strip()
    if body:
        (p / "script_rewritten.txt").write_text(body, encoding="utf-8")


def snapshot_script_legal(session_path: str, text: str) -> None:
    """After legal review pipeline writes script.txt."""
    p = ensure_session_dir(session_path)
    body = (text or "").strip()
    if body:
        (p / "script_legal.txt").write_text(body, encoding="utf-8")


def publish_copy_path(session_path: str | Path) -> Path:
    return ensure_session_dir(session_path) / "publish_copy.json"


def load_publish_copy(session_path: str | Path) -> dict:
    fp = publish_copy_path(session_path)
    if not fp.is_file():
        return {
            "title": "",
            "subtitle": "",
            "description": "",
            "topics": [],
        }
    try:
        data = json.loads(fp.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"title": "", "subtitle": "", "description": "", "topics": []}
        topics = data.get("topics") or []
        if isinstance(topics, str):
            topics = [t.strip().lstrip("#") for t in topics.replace("，", " ").split() if t.strip()]
        elif isinstance(topics, list):
            topics = [str(t).strip().lstrip("#") for t in topics if str(t).strip()]
        else:
            topics = []
        return {
            "title": str(data.get("title") or "").strip(),
            "subtitle": str(data.get("subtitle") or "").strip(),
            "description": str(data.get("description") or "").strip(),
            "topics": topics,
        }
    except (OSError, json.JSONDecodeError):
        return {"title": "", "subtitle": "", "description": "", "topics": []}


def save_publish_copy(
    session_path: str | Path,
    *,
    title: str = "",
    subtitle: str = "",
    description: str = "",
    topics: list[str] | None = None,
) -> dict:
    data = {
        "title": (title or "").strip(),
        "subtitle": (subtitle or "").strip(),
        "description": (description or "").strip(),
        "topics": [str(t).strip().lstrip("#") for t in (topics or []) if str(t).strip()],
    }
    fp = publish_copy_path(session_path)
    fp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data

def resolve_selected_dub_path(session_path: Path | str) -> str | None:
    """Return validated user-selected dub path, or latest 成片 if unset."""
    p = Path(session_path)
    if not p.is_dir():
        return None
    dubs = list_session_dubbings(p)
    if not dubs:
        return None
    meta = _read_meta(p)
    saved = (meta.get("selected_dub_path") or "").strip()
    if saved:
        for item in dubs:
            if item.get("path") == saved or Path(item.get("path", "")).resolve() == Path(saved).resolve():
                return item["path"]
    return dubs[0]["path"]


def set_selected_dub_path(session_path: str, audio_path: str | None) -> dict:
    """Persist which dub track is active for avatar / export."""
    p = ensure_session_dir(session_path)
    dubs = list_session_dubbings(p)
    if not dubs:
        raise FileNotFoundError("暂无可用配音")
    target = (audio_path or "").strip()
    if not target:
        target = dubs[0]["path"]
    resolved = None
    for item in dubs:
        ip = Path(item.get("path", ""))
        if item.get("path") == target or (ip.is_file() and ip.resolve() == Path(target).resolve()):
            resolved = item["path"]
            break
    if not resolved:
        raise FileNotFoundError("所选配音不存在，请重新选择")
    meta = _read_meta(p)
    meta["selected_dub_path"] = resolved
    _write_meta(p, meta)
    return {"selected_dub_path": resolved}


def delete_session_dubbing(session_path: str, dub_id: str) -> dict:
    """Remove a saved named dub copy (not the current 成片)."""
    p = ensure_session_dir(session_path)
    dub_id = (dub_id or "").strip()
    if not dub_id or dub_id == "_current":
        raise ValueError("当前成片不可删除，仅可删除已另存的副本")

    meta = _read_meta(p)
    dubbings = meta.get("dubbings")
    if not isinstance(dubbings, list):
        raise FileNotFoundError("配音不存在")

    found: dict | None = None
    remaining: list = []
    for entry in dubbings:
        if not isinstance(entry, dict):
            continue
        if entry.get("id") == dub_id:
            found = entry
        else:
            remaining.append(entry)

    if not found:
        raise FileNotFoundError("配音不存在")

    rel = found.get("file", "")
    deleted_abs = ""
    if rel:
        fp = p / rel
        if fp.is_file():
            deleted_abs = str(fp.resolve())
            fp.unlink()
    meta["dubbings"] = remaining
    selected = (meta.get("selected_dub_path") or "").strip()
    if selected and deleted_abs:
        try:
            if Path(selected).resolve() == Path(deleted_abs).resolve():
                meta.pop("selected_dub_path", None)
        except OSError:
            if selected == deleted_abs:
                meta.pop("selected_dub_path", None)
    _write_meta(p, meta)
    return {"id": dub_id, "name": found.get("name", dub_id), "deleted": True}


def session_ui_snapshot(path_str: str) -> dict:
    """Load session artifacts for switching UI state."""
    empty = {
        "script": "",
        "preview_16k": None,
        "stage_audio": None,
        "selected_dub": None,
        "media_in": None,
        "video_out": None,
        "tts_log": "",
        "lipsync_log": "",
    }
    if not path_str:
        return empty
    p = Path(path_str)
    if not p.exists():
        return empty
    meta = _read_meta(p)
    script_p = p / "script.txt"
    dub = p / "dubbing_16k.wav"
    dubs = list_session_dubbings(p)
    lips = list_session_lipsyncs(p)
    selected_lip = resolve_selected_lipsync_path(p)
    final = Path(selected_lip) if selected_lip else None
    media_in = None
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".bmp"):
        candidate = p / f"input_image{ext}"
        if candidate.exists():
            media_in = candidate
            break
    if media_in is None:
        for ext in (".mp4", ".mov", ".webm", ".mkv", ".m4v", ".avi"):
            candidate = p / f"input_video{ext}"
            if candidate.exists():
                media_in = candidate
                break
    if media_in is None:
        legacy = p / "input_video.mp4"
        media_in = legacy if legacy.exists() else None
    lines = [
        f"会话: {meta.get('name', p.name)}",
        f"目录: {p}",
    ]
    if dub.exists():
        lines.append(f"配音: {dub}")
    if len(dubs) > 1:
        lines.append(f"已保存配音: {len(dubs) - 1} 条")
    if final is not None and final.exists():
        lines.append(f"成片: {final}")
    if len(lips) > 1:
        lines.append(f"已保存口播: {len(lips) - 1} 条")
    selected = resolve_selected_dub_path(p)
    dub_mtime = _file_mtime(dub)
    video_mtime = _file_mtime(final) if final else None
    return {
        "script": script_p.read_text(encoding="utf-8") if script_p.exists() else "",
        "preview_16k": str(dub) if dub.exists() else None,
        "stage_audio": str(dub) if dub.exists() else None,
        "selected_dub": selected,
        "selected_lipsync": selected_lip,
        "lipsyncs": lips,
        "dubbing_mtime": int(dub_mtime) if dub_mtime else None,
        "lipsync_mtime": int(video_mtime) if video_mtime else None,
        "lipsync_stale": lipsync_needs_regen(p),
        "media_in": str(media_in) if media_in else None,
        "video_out": str(final) if final is not None and final.exists() else None,
        "tts_log": "\n".join(lines),
        "lipsync_log": "已加载对口型成片。" if final is not None and final.exists() else "",
    }

"""Session-scoped job queue store (publish jobs index.json)."""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOCK = threading.RLock()

JOB_TYPES = frozenset(
    {
        "hyperframe_fill_cues",
        "hyperframe_restyle",
        "publish_run",
        "tts_synthesize",
        "avatar_lipsync",
        "engine_install",
    }
)

DEFAULT_TITLES = {
    "hyperframe_fill_cues": "智能时间段场景",
    "hyperframe_restyle": "场景换肤",
    "publish_run": "一键成片",
    "tts_synthesize": "生成配音",
    "avatar_lipsync": "生成口播",
    "engine_install": "引擎安装",
}

ACTIVE_STATUSES = frozenset({"queued", "running"})
HISTORY_STATUSES = frozenset({"done", "failed", "cancelled"})


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def jobs_dir(session: Path) -> Path:
    d = Path(session) / "publish" / "jobs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def index_path(session: Path) -> Path:
    return jobs_dir(session) / "index.json"


def _atomic_write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _load_index(session: Path) -> list[dict[str, Any]]:
    path = index_path(session)
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(raw, dict) and isinstance(raw.get("jobs"), list):
        return [j for j in raw["jobs"] if isinstance(j, dict)]
    if isinstance(raw, list):
        return [j for j in raw if isinstance(j, dict)]
    return []


def _save_index(session: Path, jobs: list[dict[str, Any]]) -> None:
    _atomic_write(index_path(session), {"jobs": jobs})


def canonical_params_hash(payload: dict[str, Any] | None) -> str:
    """Stable SHA-256 of normalized JSON (sorted keys)."""
    payload = payload if isinstance(payload, dict) else {}

    def normalize(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {str(k): normalize(obj[k]) for k in sorted(obj.keys(), key=str)}
        if isinstance(obj, (list, tuple)):
            return [normalize(x) for x in obj]
        if isinstance(obj, bool) or obj is None:
            return obj
        if isinstance(obj, (int, float)):
            return obj
        return str(obj)

    blob = json.dumps(normalize(payload), ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def list_jobs(session: Path, *, status: str | None = None) -> list[dict[str, Any]]:
    with _LOCK:
        jobs = _load_index(Path(session))
    if status:
        jobs = [j for j in jobs if j.get("status") == status]
    return sorted(jobs, key=lambda j: j.get("created_at") or "", reverse=True)


def get_job(session: Path, job_id: str) -> dict[str, Any] | None:
    with _LOCK:
        for j in _load_index(Path(session)):
            if j.get("id") == job_id:
                return dict(j)
    return None


def update_job(session: Path, job_id: str, **fields: Any) -> dict[str, Any] | None:
    session = Path(session)
    with _LOCK:
        jobs = _load_index(session)
        for i, j in enumerate(jobs):
            if j.get("id") != job_id:
                continue
            updated = {**j, **fields}
            jobs[i] = updated
            _save_index(session, jobs)
            return dict(updated)
    return None


def delete_job(session: Path, job_id: str) -> bool:
    session = Path(session)
    with _LOCK:
        jobs = _load_index(session)
        new_jobs = [j for j in jobs if j.get("id") != job_id]
        if len(new_jobs) == len(jobs):
            return False
        _save_index(session, new_jobs)
        return True


def _safe_under_session(session: Path, path: Path) -> Path | None:
    """Return resolved path only if it lives under session (prevent path escape)."""
    try:
        session_r = session.resolve()
        target = Path(path).resolve()
        target.relative_to(session_r)
        return target
    except (OSError, ValueError):
        return None


def collect_job_source_paths(session: Path, job: dict[str, Any]) -> list[Path]:
    """Gather generated media / work dirs referenced by a finished job."""
    session = Path(session)
    out: list[Path] = []
    seen: set[str] = set()

    def add(p: object) -> None:
        if not p:
            return
        safe = _safe_under_session(session, Path(str(p)))
        if safe is None:
            return
        key = str(safe)
        if key in seen:
            return
        seen.add(key)
        out.append(safe)

    result = job.get("result") if isinstance(job.get("result"), dict) else {}
    payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
    for key in (
        "work_dir",
        "assignments_file",
        "video_path",
        "audio",
        "cover_path",
        "srt_path",
    ):
        add(result.get(key))
        add(payload.get(key))
    assignments = result.get("assignments")
    if isinstance(assignments, list):
        for a in assignments:
            if isinstance(a, dict):
                add(a.get("media_path"))

    # 口播任务清除源文件时一并清理会话根与 lipsync_takes 归档，避免页面残留旧数字人记录
    if job.get("type") == "avatar_lipsync":
        for name in (
            "digital_lipsync.mp4",
            "real_lipsync.mp4",
            "final_lipsync.mp4",
            "heygem_raw.mp4",
            "sadtalker_raw.mp4",
            "latentsync_raw.mp4",
        ):
            add(session / name)
        takes_dir = session / "lipsync_takes"
        if takes_dir.is_dir():
            for fp in takes_dir.glob("*.mp4"):
                add(fp)

    return out


def purge_job_sources(session: Path, job: dict[str, Any]) -> dict[str, Any]:
    """Delete generated files for a job. Also prune matching pip assignments."""
    import shutil

    session = Path(session)
    removed_files = 0
    removed_dirs = 0
    media_paths: set[str] = set()
    for path in collect_job_source_paths(session, job):
        try:
            if path.is_file():
                if path.suffix.lower() in (".mp4", ".mov", ".webm", ".mkv", ".png", ".jpg", ".jpeg", ".webp"):
                    media_paths.add(str(path.resolve()))
                path.unlink(missing_ok=True)
                removed_files += 1
            elif path.is_dir():
                for child in path.rglob("*"):
                    if child.is_file() and child.suffix.lower() in (
                        ".mp4",
                        ".mov",
                        ".webm",
                        ".mkv",
                        ".png",
                        ".jpg",
                        ".jpeg",
                        ".webp",
                    ):
                        media_paths.add(str(child.resolve()))
                shutil.rmtree(path, ignore_errors=True)
                removed_dirs += 1
        except OSError:
            continue

    pruned = 0
    if media_paths:
        try:
            import json

            from workflow.pip_assignments_store import (
                assignments_path,
                load_pip_assignments,
                save_pip_assignments,
            )

            path = assignments_path(session)
            raw_items: list = []
            if path.is_file():
                try:
                    raw = json.loads(path.read_text(encoding="utf-8"))
                    raw_items = raw.get("assignments") if isinstance(raw.get("assignments"), list) else []
                except (json.JSONDecodeError, OSError):
                    raw_items = []

            # After file deletes, load_pip_assignments drops missing media
            alive = list(load_pip_assignments(session).get("assignments") or [])
            kept: list = []
            for a in alive:
                if not isinstance(a, dict):
                    continue
                mp = str(Path(str(a.get("media_path") or "")).resolve()) if a.get("media_path") else ""
                if mp and mp in media_paths:
                    continue
                kept.append(a)
            pruned = max(0, len(raw_items) - len(kept))
            if pruned or len(kept) != len(raw_items):
                save_pip_assignments(session, kept)
        except Exception:
            pass

    lipsync_pruned = 0
    if job.get("type") == "avatar_lipsync":
        try:
            from workflow.session import prune_missing_lipsync_meta

            lipsync_pruned = prune_missing_lipsync_meta(session)
        except Exception:
            lipsync_pruned = 0

    return {
        "removed_files": removed_files,
        "removed_dirs": removed_dirs,
        "pruned_assignments": pruned,
        "pruned_lipsyncs": lipsync_pruned,
    }


def delete_job_with_options(
    session: Path,
    job_id: str,
    *,
    delete_sources: bool = False,
) -> dict[str, Any]:
    session = Path(session)
    job = get_job(session, job_id)
    if not job:
        return {"ok": False, "error": "任务不存在"}
    purge_info: dict[str, Any] = {}
    if delete_sources:
        purge_info = purge_job_sources(session, job)
    ok = delete_job(session, job_id)
    return {"ok": ok, "deleted_sources": bool(delete_sources), **purge_info}


def clear_history(session: Path) -> int:
    """Remove done/failed/cancelled records. Returns count removed."""
    session = Path(session)
    with _LOCK:
        jobs = _load_index(session)
        keep = [j for j in jobs if j.get("status") not in HISTORY_STATUSES]
        removed = len(jobs) - len(keep)
        if removed:
            _save_index(session, keep)
        return removed


def mark_stale_running_jobs(session: Path) -> int:
    """Map running → failed after process restart. Returns count."""
    session = Path(session)
    with _LOCK:
        jobs = _load_index(session)
        n = 0
        for i, j in enumerate(jobs):
            if j.get("status") != "running":
                continue
            jobs[i] = {
                **j,
                "status": "failed",
                "message": "服务重启，任务中断",
                "error": "服务重启，任务中断",
                "finished_at": _utc_now(),
            }
            n += 1
        if n:
            _save_index(session, jobs)
        return n


def find_duplicate(
    session: Path,
    job_type: str,
    params_hash: str,
    *,
    include_done: bool = True,
) -> dict[str, Any] | None:
    with _LOCK:
        jobs = _load_index(Path(session))
    for j in jobs:
        if j.get("type") != job_type or j.get("params_hash") != params_hash:
            continue
        st = j.get("status")
        if st in ACTIVE_STATUSES:
            return dict(j)
        if include_done and st == "done":
            return dict(j)
    return None


def enqueue_job(
    session: Path,
    job_type: str,
    payload: dict[str, Any] | None,
    *,
    title: str | None = None,
    force: bool = False,
    priority: int = 0,
) -> dict[str, Any]:
    """
    Enqueue a job. Returns:
      {"ok": True, "job": {...}}
      {"ok": False, "duplicate": True, "message": "...", "existing_job_id": "...", "existing_job": {...}}
    """
    if job_type not in JOB_TYPES:
        raise ValueError(f"unsupported job type: {job_type}")

    session = Path(session)
    session.mkdir(parents=True, exist_ok=True)
    payload = dict(payload or {})
    params_hash = canonical_params_hash(payload)

    existing = find_duplicate(session, job_type, params_hash, include_done=not force)
    if existing:
        st = existing.get("status")
        if st in ACTIVE_STATUSES:
            return {
                "ok": False,
                "duplicate": True,
                "message": "当前条件下已有任务在队列/执行中",
                "existing_job_id": existing["id"],
                "existing_job": existing,
            }
        if st == "done" and not force:
            return {
                "ok": False,
                "duplicate": True,
                "message": "当前条件下已执行过相同任务",
                "existing_job_id": existing["id"],
                "existing_job": existing,
            }

    job = {
        "id": str(uuid.uuid4()),
        "session_path": str(session.resolve()),
        "type": job_type,
        "title": (title or DEFAULT_TITLES.get(job_type) or job_type).strip(),
        "status": "queued",
        "progress": 0.0,
        "message": "排队中",
        "params_hash": params_hash,
        "payload": payload,
        "result": None,
        "error": None,
        "priority": int(priority or 0),
        "created_at": _utc_now(),
        "started_at": None,
        "finished_at": None,
        "cancel_requested": False,
    }
    with _LOCK:
        jobs = _load_index(session)
        jobs.insert(0, job)
        _save_index(session, jobs)
    return {"ok": True, "job": job}


def prioritize_job(session: Path, job_id: str, *, priority: int = 100) -> dict[str, Any]:
    """Bump a queued job so the worker runs it sooner (higher priority first)."""
    session = Path(session)
    with _LOCK:
        jobs = _load_index(session)
        for i, j in enumerate(jobs):
            if j.get("id") != job_id:
                continue
            if j.get("status") != "queued":
                return {"ok": False, "message": "仅排队中的任务可设为优先", "job": dict(j)}
            jobs[i] = {**j, "priority": int(priority), "message": "优先排队"}
            _save_index(session, jobs)
            return {"ok": True, "job": dict(jobs[i])}
    return {"ok": False, "message": "任务不存在"}


def requeue_job(session: Path, job_id: str) -> dict[str, Any]:
    """Re-queue a failed/cancelled job with the same payload (full re-run, not mid-point resume)."""
    session = Path(session)
    with _LOCK:
        jobs = _load_index(session)
        for i, j in enumerate(jobs):
            if j.get("id") != job_id:
                continue
            st = j.get("status")
            if st not in ("failed", "cancelled"):
                return {"ok": False, "message": "仅失败或已取消的任务可重新排队", "job": dict(j)}
            jobs[i] = {
                **j,
                "status": "queued",
                "progress": 0.0,
                "message": "重新排队",
                "error": None,
                "result": None,
                "started_at": None,
                "finished_at": None,
                "cancel_requested": False,
            }
            _save_index(session, jobs)
            return {"ok": True, "job": dict(jobs[i])}
    return {"ok": False, "message": "任务不存在"}


def request_cancel(session: Path, job_id: str) -> dict[str, Any]:
    """Cancel queued immediately; mark cancel_requested for running."""
    session = Path(session)
    with _LOCK:
        jobs = _load_index(session)
        for i, j in enumerate(jobs):
            if j.get("id") != job_id:
                continue
            st = j.get("status")
            if st == "queued":
                jobs[i] = {
                    **j,
                    "status": "cancelled",
                    "message": "已取消",
                    "finished_at": _utc_now(),
                    "cancel_requested": True,
                }
                _save_index(session, jobs)
                return {"ok": True, "job": dict(jobs[i])}
            if st == "running":
                jobs[i] = {**j, "cancel_requested": True, "message": j.get("message") or "正在取消…"}
                _save_index(session, jobs)
                return {"ok": True, "job": dict(jobs[i]), "cancel_requested": True}
            return {"ok": False, "message": f"任务状态为 {st}，无法取消", "job": dict(j)}
    return {"ok": False, "message": "任务不存在"}


def is_cancel_requested(session: Path, job_id: str) -> bool:
    job = get_job(session, job_id)
    return bool(job and job.get("cancel_requested"))

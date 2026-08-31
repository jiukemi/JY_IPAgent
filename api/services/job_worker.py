"""Global priority job worker (one runner thread; higher priority first, then FIFO)."""

from __future__ import annotations

import itertools
import json
import logging
import queue
import threading
import traceback
from pathlib import Path
from typing import Any

from workflow.job_queue import (
    get_job,
    is_cancel_requested,
    list_jobs,
    mark_stale_running_jobs,
    update_job,
)

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
PENDING_PATH = REPO_ROOT / "data" / "job_worker_pending.json"

# PriorityQueue item: (-priority, seq, session_path, job_id)
_work_q: queue.PriorityQueue[tuple[int, int, str, str] | None] = queue.PriorityQueue()
_seq = itertools.count()
_started = False
_start_lock = threading.Lock()
_worker_thread: threading.Thread | None = None


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_pending() -> list[dict[str, str]]:
    if not PENDING_PATH.is_file():
        return []
    try:
        raw = json.loads(PENDING_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict) and x.get("session_path") and x.get("job_id")]
    return []


def _save_pending(items: list[dict[str, str]]) -> None:
    PENDING_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PENDING_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(PENDING_PATH)


def _pending_add(session_path: str, job_id: str) -> None:
    with _start_lock:
        items = _load_pending()
        key = (str(Path(session_path).resolve()), job_id)
        for it in items:
            if (str(Path(it["session_path"]).resolve()), it["job_id"]) == key:
                return
        items.append({"session_path": str(Path(session_path).resolve()), "job_id": job_id})
        _save_pending(items)


def _pending_remove(session_path: str, job_id: str) -> None:
    with _start_lock:
        items = _load_pending()
        sp = str(Path(session_path).resolve())
        items = [
            it
            for it in items
            if not (str(Path(it["session_path"]).resolve()) == sp and it["job_id"] == job_id)
        ]
        _save_pending(items)


def _job_priority(session_path: str, job_id: str) -> int:
    job = get_job(Path(session_path), job_id)
    try:
        return int((job or {}).get("priority") or 0)
    except (TypeError, ValueError):
        return 0


def submit(session_path: str, job_id: str, *, priority: int | None = None) -> None:
    """Enqueue work item for the global worker (higher priority runs first)."""
    session_path = str(Path(session_path).resolve())
    _pending_add(session_path, job_id)
    pri = int(priority) if priority is not None else _job_priority(session_path, job_id)
    _work_q.put((-pri, next(_seq), session_path, job_id))


def _thin_result(result: dict[str, Any] | None) -> dict[str, Any] | None:
    if not result:
        return None
    out: dict[str, Any] = {}
    for k in (
        "ok",
        "count",
        "note",
        "work_dir",
        "assignments_file",
        "library_saved",
        "video_path",
        "cover_path",
        "srt_path",
        "log",
        "audio",
        "audio_duration",
        "backend",
        "model",
        "quality",
        "track_mode",
        "avatar_id",
        "avatar_name",
        "speed_mode",
        "duration_sec",
        "engine",
        "ready",
        "missing",
        "exit_code",
    ):
        if k in result and result[k] is not None:
            out[k] = result[k]
    if "assignments" in result and isinstance(result["assignments"], list):
        out["assignments"] = result["assignments"]
        out["assignment_count"] = len(result["assignments"])
    if "publish" in result and isinstance(result["publish"], dict):
        out["publish"] = _thin_result(result["publish"])
    if "style_pack" in result:
        out["style_pack"] = result["style_pack"]
    return out


def _elapsed_sec(started_at: str | None, finished_at: str | None) -> float | None:
    if not started_at or not finished_at:
        return None
    from datetime import datetime

    def parse(s: str) -> datetime | None:
        raw = (s or "").strip().replace("Z", "+00:00")
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None

    a, b = parse(started_at), parse(finished_at)
    if not a or not b:
        return None
    return max(0.0, (b - a).total_seconds())


def _process_one(session_path: str, job_id: str) -> None:
    from api.services.job_runner import dispatch_job
    from workflow.task_control import TaskCancelled, begin_job, request_cancel

    session = Path(session_path)
    job = get_job(session, job_id)
    if not job:
        _pending_remove(session_path, job_id)
        return
    if job.get("status") == "cancelled":
        _pending_remove(session_path, job_id)
        return
    # Only start from queued (skip duplicate priority re-submits while running/done)
    if job.get("status") != "queued":
        _pending_remove(session_path, job_id)
        return

    begin_job(job.get("type") or "job")
    update_job(
        session,
        job_id,
        status="running",
        progress=0.0,
        message="执行中…",
        started_at=_utc_now(),
        error=None,
    )

    def on_progress(p: float, msg: str = "") -> None:
        if is_cancel_requested(session, job_id):
            request_cancel()
        update_job(
            session,
            job_id,
            progress=max(0.0, min(1.0, float(p))),
            message=msg or "执行中…",
        )

    try:
        if is_cancel_requested(session, job_id):
            raise TaskCancelled("任务已取消")
        result = dispatch_job(
            str(job["type"]),
            dict(job.get("payload") or {}),
            on_progress=on_progress,
        )
        finished = _utc_now()
        started = (get_job(session, job_id) or {}).get("started_at") or job.get("started_at")
        elapsed = _elapsed_sec(started, finished)
        if is_cancel_requested(session, job_id):
            update_job(
                session,
                job_id,
                status="cancelled",
                message="已取消",
                finished_at=finished,
                duration_sec=elapsed,
                progress=float(job.get("progress") or 0),
            )
        else:
            thin = _thin_result(result if isinstance(result, dict) else {"ok": True}) or {}
            if elapsed is not None:
                thin["duration_sec"] = round(elapsed, 1)
            update_job(
                session,
                job_id,
                status="done",
                progress=1.0,
                message="完成",
                result=thin,
                finished_at=finished,
                duration_sec=elapsed,
                error=None,
            )
    except TaskCancelled:
        finished = _utc_now()
        started = (get_job(session, job_id) or {}).get("started_at")
        update_job(
            session,
            job_id,
            status="cancelled",
            message="已取消",
            finished_at=finished,
            duration_sec=_elapsed_sec(started, finished),
            error="任务已取消",
        )
    except Exception as exc:
        log.exception("job %s failed", job_id)
        finished = _utc_now()
        started = (get_job(session, job_id) or {}).get("started_at")
        update_job(
            session,
            job_id,
            status="failed",
            message=str(exc),
            error=str(exc),
            finished_at=finished,
            duration_sec=_elapsed_sec(started, finished),
        )
        log.debug(traceback.format_exc())
    finally:
        _pending_remove(session_path, job_id)


def _worker_loop() -> None:
    log.info("job worker started (priority + FIFO)")
    while True:
        item = _work_q.get()
        if item is None:
            break
        _pri, _seq_n, session_path, job_id = item
        try:
            _process_one(session_path, job_id)
        except Exception:
            log.exception("worker crash on %s %s", session_path, job_id)
        finally:
            _work_q.task_done()


def rehydrate_pending() -> int:
    """Reload pending + session queued jobs into memory queue. Mark stale running."""
    n = 0
    seen: set[tuple[str, str]] = set()
    pending_items = _load_pending()
    # Sort by job priority so high-priority jobs are submitted first after restart
    enriched: list[tuple[int, str, str]] = []
    for it in pending_items:
        sp = str(Path(it["session_path"]).resolve())
        jid = it["job_id"]
        mark_stale_running_jobs(Path(sp))
        job = get_job(Path(sp), jid)
        if job and job.get("status") == "queued":
            enriched.append((int(job.get("priority") or 0), sp, jid))
        elif job and job.get("status") == "running":
            _pending_remove(sp, jid)
        else:
            _pending_remove(sp, jid)
    enriched.sort(key=lambda x: (-x[0], x[1], x[2]))
    for pri, sp, jid in enriched:
        key = (sp, jid)
        if key not in seen:
            seen.add(key)
            submit(sp, jid, priority=pri)
            n += 1

    sessions: set[str] = {str(Path(it["session_path"]).resolve()) for it in _load_pending()}
    for sp in list(sessions):
        mark_stale_running_jobs(Path(sp))
        for job in list_jobs(Path(sp), status="queued"):
            key = (sp, str(job["id"]))
            if key not in seen:
                seen.add(key)
                _pending_add(sp, str(job["id"]))
                submit(sp, str(job["id"]), priority=int(job.get("priority") or 0))
                n += 1
    return n


def start_job_worker() -> None:
    global _started, _worker_thread
    with _start_lock:
        if _started:
            return
        _started = True
        rehydrate_pending()
        _worker_thread = threading.Thread(target=_worker_loop, name="job-worker", daemon=True)
        _worker_thread.start()
        log.info("job worker thread launched")

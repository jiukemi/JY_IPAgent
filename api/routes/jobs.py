"""REST API for session task queue / 任务中心."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from workflow.session import ensure_session_dir

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


class EnqueueBody(BaseModel):
    session_path: str
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    title: str | None = None
    force: bool = False
    priority: int = 0


@router.post("")
def enqueue(body: EnqueueBody) -> dict[str, Any]:
    from api.services import job_worker
    from workflow.job_queue import JOB_TYPES, enqueue_job

    if body.type not in JOB_TYPES:
        raise HTTPException(status_code=400, detail=f"不支持的任务类型: {body.type}")
    session = ensure_session_dir(body.session_path)
    payload = dict(body.payload or {})
    payload.setdefault("session_path", str(session.resolve()))
    try:
        result = enqueue_job(
            session,
            body.type,
            payload,
            title=body.title,
            force=body.force,
            priority=body.priority,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if result.get("ok") and result.get("job"):
        job_worker.submit(
            str(session.resolve()),
            result["job"]["id"],
            priority=int(result["job"].get("priority") or 0),
        )
    return result


@router.post("/{job_id}/prioritize")
def prioritize_session_job(job_id: str, session_path: str) -> dict[str, Any]:
    """Move a queued job ahead of others (worker picks higher priority first)."""
    from api.services import job_worker
    from workflow.job_queue import prioritize_job

    session = ensure_session_dir(session_path)
    result = prioritize_job(session, job_id, priority=100)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("message") or "无法优先")
    job = result["job"]
    job_worker.submit(str(session.resolve()), job["id"], priority=int(job.get("priority") or 100))
    return result


@router.post("/{job_id}/requeue")
def requeue_session_job(job_id: str, session_path: str) -> dict[str, Any]:
    """Re-queue failed/cancelled job (full re-run; TTS has no mid-audio checkpoint)."""
    from api.services import job_worker
    from workflow.job_queue import requeue_job

    session = ensure_session_dir(session_path)
    result = requeue_job(session, job_id)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("message") or "无法重新排队")
    job = result["job"]
    job_worker.submit(str(session.resolve()), job["id"], priority=int(job.get("priority") or 0))
    return result


@router.get("")
def list_session_jobs(session_path: str, status: str | None = None) -> dict[str, Any]:
    from workflow.job_queue import list_jobs

    session = ensure_session_dir(session_path)
    # Do NOT call mark_stale_running_jobs here — that is only for process boot.
    # Polling would otherwise kill live running jobs as "服务重启，任务中断".
    jobs = list_jobs(session, status=status)
    active = sum(1 for j in jobs if j.get("status") in ("queued", "running"))
    return {"ok": True, "jobs": jobs, "active_count": active}


@router.post("/clear_history")
def clear_job_history(session_path: str) -> dict[str, Any]:
    from workflow.job_queue import clear_history

    session = ensure_session_dir(session_path)
    n = clear_history(session)
    return {"ok": True, "removed": n}


@router.get("/{job_id}")
def get_session_job(job_id: str, session_path: str) -> dict[str, Any]:
    from workflow.job_queue import get_job

    session = ensure_session_dir(session_path)
    job = get_job(session, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"ok": True, "job": job}


@router.delete("/{job_id}")
def delete_session_job(
    job_id: str,
    session_path: str,
    delete_sources: bool = False,
) -> dict[str, Any]:
    from workflow.job_queue import delete_job_with_options, get_job, request_cancel

    session = ensure_session_dir(session_path)
    job = get_job(session, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    st = job.get("status")
    if st == "running":
        raise HTTPException(status_code=400, detail="进行中的任务请先取消，再删除记录")
    if st == "queued":
        request_cancel(session, job_id)
    return delete_job_with_options(session, job_id, delete_sources=bool(delete_sources))


@router.post("/{job_id}/cancel")
def cancel_session_job(job_id: str, session_path: str) -> dict[str, Any]:
    from workflow.job_queue import get_job, request_cancel
    from workflow.task_control import request_cancel as tc_cancel

    session = ensure_session_dir(session_path)
    job = get_job(session, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    result = request_cancel(session, job_id)
    if job.get("status") == "running" or result.get("cancel_requested"):
        tc_cancel()
    return result

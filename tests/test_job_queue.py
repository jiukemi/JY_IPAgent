"""Tests for session job queue store."""

from __future__ import annotations

from pathlib import Path

from workflow.job_queue import (
    canonical_params_hash,
    enqueue_job,
    list_jobs,
    mark_stale_running_jobs,
    update_job,
)


def test_params_hash_stable_and_order_independent() -> None:
    a = canonical_params_hash({"b": 1, "a": [2, 1], "x": "z"})
    b = canonical_params_hash({"a": [2, 1], "b": 1, "x": "z"})
    assert a == b
    assert len(a) == 64


def test_enqueue_duplicate_queued(tmp_path: Path) -> None:
    session = tmp_path / "sess"
    session.mkdir()
    r1 = enqueue_job(session, "hyperframe_fill_cues", {"cues": [1], "theme": "t"}, title="生成")
    assert r1["ok"] is True
    r2 = enqueue_job(session, "hyperframe_fill_cues", {"theme": "t", "cues": [1]}, title="生成")
    assert r2["ok"] is False
    assert r2["duplicate"] is True
    assert r2["existing_job_id"] == r1["job"]["id"]


def test_force_bypasses_done_duplicate(tmp_path: Path) -> None:
    session = tmp_path / "sess"
    session.mkdir()
    r1 = enqueue_job(session, "hyperframe_restyle", {"pack": "a"}, title="换肤")
    jid = r1["job"]["id"]
    update_job(session, jid, status="done", progress=1.0, message="ok")
    r2 = enqueue_job(session, "hyperframe_restyle", {"pack": "a"}, title="换肤")
    assert r2["ok"] is False and r2["duplicate"] is True
    r3 = enqueue_job(session, "hyperframe_restyle", {"pack": "a"}, title="换肤", force=True)
    assert r3["ok"] is True


def test_mark_stale_running(tmp_path: Path) -> None:
    session = tmp_path / "sess"
    session.mkdir()
    r = enqueue_job(session, "publish_run", {"burn": True}, title="成片")
    update_job(session, r["job"]["id"], status="running", progress=0.2)
    n = mark_stale_running_jobs(session)
    assert n == 1
    jobs = list_jobs(session)
    assert jobs[0]["status"] == "failed"
    assert "重启" in (jobs[0].get("error") or jobs[0].get("message") or "")

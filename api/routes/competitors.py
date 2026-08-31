"""Competitor knowledge-base routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.progress import ProgressShim
from api.schemas import StageResult
from script.competitor_kb import delete_competitor, list_competitors
from script.competitor_pipeline import save_competitor_blogger
from workflow.app_config import load_cfg
from workflow.session import ensure_session_dir

router = APIRouter(prefix="/api/competitors", tags=["competitors"])


class SaveCompetitorBody(BaseModel):
    profile_url: str
    session_path: str = ""
    deep_transcript: bool = True


@router.get("")
def competitors_list() -> dict:
    return {"items": list_competitors()}


@router.post("/save", response_model=StageResult)
def competitors_save(body: SaveCompetitorBody) -> StageResult:
    cfg = load_cfg()
    progress = ProgressShim()
    work = None
    if body.session_path:
        work = ensure_session_dir(body.session_path) / "competitor_analysis"
    try:
        entry = save_competitor_blogger(
            cfg,
            body.profile_url,
            work_dir=work,
            deep_transcript=body.deep_transcript,
            on_progress=progress,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return StageResult(
        message=f"已保存对标「{entry.get('nickname') or entry['id']}」",
        log=progress.last_msg or "已入库",
        data=entry,
    )


@router.delete("/{comp_id}", response_model=StageResult)
def competitors_delete(comp_id: str) -> StageResult:
    ok = delete_competitor(comp_id)
    if not ok:
        raise HTTPException(status_code=404, detail="未找到该对标")
    return StageResult(message="已删除", data={"id": comp_id})

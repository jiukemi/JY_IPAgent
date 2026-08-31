"""Global competitor (对标博主) knowledge base — profile + style samples."""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
KB_DIR = ROOT / "data" / "competitors"
INDEX_PATH = KB_DIR / "index.json"


def _ensure() -> None:
    KB_DIR.mkdir(parents=True, exist_ok=True)


def _read_index() -> list[dict]:
    _ensure()
    if not INDEX_PATH.is_file():
        return []
    try:
        data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return list(data) if isinstance(data, list) else []


def _write_index(items: list[dict]) -> None:
    _ensure()
    INDEX_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def _slug_from_url(url: str) -> str:
    m = re.search(r"/user/([A-Za-z0-9_\-=]+)", url or "")
    if m:
        return m.group(1)[:48]
    return uuid.uuid4().hex[:12]


def list_competitors() -> list[dict]:
    items = _read_index()
    # Lightweight list for UI
    out = []
    for it in items:
        out.append(
            {
                "id": it.get("id"),
                "nickname": it.get("nickname") or "",
                "signature": (it.get("signature") or "")[:120],
                "profile_url": it.get("profile_url") or "",
                "videos_found": it.get("videos_found") or 0,
                "sample_count": len(it.get("samples") or []),
                "updated_at": it.get("updated_at") or "",
                "platform": it.get("platform") or "douyin",
            }
        )
    out.sort(key=lambda x: x.get("updated_at") or "", reverse=True)
    return out


def get_competitor(comp_id: str) -> dict | None:
    for it in _read_index():
        if it.get("id") == comp_id:
            return it
    return None


def delete_competitor(comp_id: str) -> bool:
    items = _read_index()
    nxt = [it for it in items if it.get("id") != comp_id]
    if len(nxt) == len(items):
        return False
    _write_index(nxt)
    folder = KB_DIR / comp_id
    if folder.is_dir():
        for f in folder.glob("*"):
            try:
                f.unlink()
            except OSError:
                pass
        try:
            folder.rmdir()
        except OSError:
            pass
    return True


def upsert_competitor(payload: dict[str, Any]) -> dict:
    """Insert or update by profile_url / id."""
    items = _read_index()
    profile_url = (payload.get("profile_url") or "").strip()
    comp_id = (payload.get("id") or "").strip() or _slug_from_url(profile_url)
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    entry = {
        "id": comp_id,
        "nickname": payload.get("nickname") or "",
        "signature": payload.get("signature") or "",
        "profile_url": profile_url,
        "platform": payload.get("platform") or "douyin",
        "videos_found": payload.get("videos_found") or 0,
        "samples": payload.get("samples") or [],
        "style": payload.get("style") or {},
        "all_videos": (payload.get("all_videos") or [])[:20],
        "updated_at": now,
        "created_at": payload.get("created_at") or now,
    }
    replaced = False
    for i, it in enumerate(items):
        if it.get("id") == comp_id or (
            profile_url and it.get("profile_url") == profile_url
        ):
            entry["id"] = it.get("id") or comp_id
            entry["created_at"] = it.get("created_at") or now
            items[i] = entry
            replaced = True
            break
    if not replaced:
        items.append(entry)
    _write_index(items)
    # Persist full dump beside index
    folder = KB_DIR / entry["id"]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "profile.json").write_text(
        json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return entry

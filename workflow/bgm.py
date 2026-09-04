"""BGM catalog for short-video publish mixing (+ user uploads)."""

from __future__ import annotations

import json
import re
import shutil
import uuid
from pathlib import Path

BGM_ROOT = Path("data/bgm")
MANIFEST = BGM_ROOT / "manifest.json"
USER_DIR = BGM_ROOT / "user"
USER_INDEX = BGM_ROOT / "user_bgm.json"

_AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".wma"}

# clip_start: 推荐跳过前奏（秒）；下载时会裁成约 75s 短视频片段
_CATALOG = [
    {
        "id": "hook_drop",
        "name": "爆款开场",
        "mood": "高潮直入",
        "category": "短视频",
        "url": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-4.mp3",
        "clip_start": 0,
        "trim_sec": 75,
    },
    {
        "id": "viral_upbeat",
        "name": "节奏种草",
        "mood": "带货种草",
        "category": "短视频",
        "url": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-12.mp3",
        "clip_start": 8,
        "trim_sec": 75,
    },
    {
        "id": "tech_pulse",
        "name": "科技脉冲",
        "mood": "数码测评",
        "category": "短视频",
        "url": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-5.mp3",
        "clip_start": 12,
        "trim_sec": 75,
    },
    {
        "id": "vlog_groove",
        "name": "Vlog律动",
        "mood": "生活记录",
        "category": "短视频",
        "url": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-6.mp3",
        "clip_start": 5,
        "trim_sec": 75,
    },
    {
        "id": "story_emotion",
        "name": "叙事铺底",
        "mood": "情感口播",
        "category": "口播",
        "url": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-8.mp3",
        "clip_start": 18,
        "trim_sec": 90,
    },
    {
        "id": "knowledge_calm",
        "name": "知识讲解",
        "mood": "科普解说",
        "category": "口播",
        "url": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-11.mp3",
        "clip_start": 22,
        "trim_sec": 90,
    },
    {
        "id": "morning_motivate",
        "name": "清晨励志",
        "mood": "励志口播",
        "category": "口播",
        "url": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3",
        "clip_start": 15,
        "trim_sec": 90,
    },
    {
        "id": "uplifting",
        "name": "振奋人心",
        "mood": "正能量",
        "category": "口播",
        "url": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-2.mp3",
        "clip_start": 20,
        "trim_sec": 90,
    },
    {
        "id": "driving_ambition",
        "name": "商业宣传",
        "mood": "品牌片头",
        "category": "商业",
        "url": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-3.mp3",
        "clip_start": 25,
        "trim_sec": 90,
    },
    {
        "id": "fashion_vibe",
        "name": "时尚节拍",
        "mood": "穿搭美妆",
        "category": "短视频",
        "url": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-15.mp3",
        "clip_start": 6,
        "trim_sec": 75,
    },
    {
        "id": "happy_pop",
        "name": "活泼气氛",
        "mood": "欢乐种草",
        "category": "短视频",
        "url": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-12.mp3",
        "clip_start": 0,
        "trim_sec": 60,
    },
    {
        "id": "soft_calm",
        "name": "轻柔安宁",
        "mood": "治愈讲解",
        "category": "口播",
        "url": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-7.mp3",
        "clip_start": 30,
        "trim_sec": 90,
    },
    {
        "id": "suspense_pad",
        "name": "悬疑氛围",
        "mood": "反转铺垫",
        "category": "剧情",
        "url": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-14.mp3",
        "clip_start": 35,
        "trim_sec": 90,
    },
    {
        "id": "deep_chill",
        "name": "慢节奏",
        "mood": "冥想背景",
        "category": "氛围",
        "url": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-10.mp3",
        "clip_start": 40,
        "trim_sec": 90,
    },
    {
        "id": "dreamy",
        "name": "唯美梦境",
        "mood": "文艺短片",
        "category": "氛围",
        "url": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-13.mp3",
        "clip_start": 28,
        "trim_sec": 90,
    },
]


def catalog_entries() -> list[dict]:
    return [dict(x) for x in _CATALOG]


def _catalog_by_id(bgm_id: str) -> dict | None:
    for row in _CATALOG:
        if row["id"] == bgm_id:
            return row
    return None


def _load_user_index() -> list[dict]:
    USER_DIR.mkdir(parents=True, exist_ok=True)
    if not USER_INDEX.is_file():
        return []
    try:
        data = json.loads(USER_INDEX.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _save_user_index(rows: list[dict]) -> None:
    USER_DIR.mkdir(parents=True, exist_ok=True)
    USER_INDEX.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def _user_by_id(bgm_id: str) -> dict | None:
    for row in _load_user_index():
        if row.get("id") == bgm_id:
            return row
    return None


def _probe_duration(path: Path) -> float | None:
    try:
        from pipeline import ensure_ffmpeg
        from workflow.publish import media_duration

        probe = ensure_ffmpeg("ffmpeg").replace("ffmpeg", "ffprobe")
        if "ffmpeg" not in probe:
            probe = "ffprobe"
        return round(media_duration(probe, path), 1)
    except Exception:
        return None


def _safe_stem(name: str) -> str:
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", (name or "").strip())
    s = s.strip(" .") or "user_bgm"
    return s[:80]


def upload_user_bgm(src_path: Path, name: str = "", *, mime: str = "") -> dict:
    """Save a user-uploaded audio file into the BGM library."""
    src = Path(src_path)
    if not src.is_file():
        raise ValueError("音频文件不存在")
    suffix = src.suffix.lower()
    if suffix not in _AUDIO_EXT:
        # allow by mime hint
        m = (mime or "").lower()
        if not m.startswith("audio/"):
            raise ValueError("请上传音频文件（mp3 / wav / m4a / aac / ogg / flac）")
        suffix = ".mp3" if not suffix else suffix
    USER_DIR.mkdir(parents=True, exist_ok=True)
    item_id = f"user_{uuid.uuid4().hex[:10]}"
    display = (name or src.stem).strip() or "我的 BGM"
    display = _safe_stem(display)
    dest = USER_DIR / f"{item_id}{suffix}"
    shutil.copy2(src, dest)
    duration = _probe_duration(dest)
    row = {
        "id": item_id,
        "name": display,
        "mood": "用户上传",
        "category": "我的",
        "file": f"user/{dest.name}",
        "source": "user",
        "clip_start": 0,
        "trim_sec": duration or 75,
        "duration_sec": duration,
    }
    rows = _load_user_index()
    rows.append(row)
    _save_user_index(rows)
    return {
        "id": item_id,
        "name": display,
        "mood": "用户上传",
        "category": "我的",
        "ready": True,
        "source": "user",
        "clip_start": 0,
        "duration_sec": duration,
        "preview_url": f"/api/publish/bgm/preview?id={item_id}",
        "local_path": str(dest.resolve()),
        "user": True,
    }


def delete_user_bgm(bgm_id: str) -> None:
    bid = (bgm_id or "").strip()
    if not bid.startswith("user_"):
        raise ValueError("内置曲库不可删除")
    rows = _load_user_index()
    kept: list[dict] = []
    removed = None
    for row in rows:
        if row.get("id") == bid:
            removed = row
            continue
        kept.append(row)
    if removed is None:
        raise ValueError("BGM 不存在")
    rel = removed.get("file") or ""
    if rel:
        p = BGM_ROOT / rel
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass
    _save_user_index(kept)


def _asset_audio_rows() -> list[dict]:
    """Audio files uploaded in 素材中心 (音频分组等) — selectable as BGM."""
    try:
        from workflow.asset_library import _load
    except Exception:
        return []
    try:
        data = _load()
    except Exception:
        return []
    out: list[dict] = []
    for row in data.get("items", []) or []:
        if row.get("kind") != "file":
            continue
        path = Path(str(row.get("path") or ""))
        if not path.is_file():
            continue
        mime = str(row.get("mime") or "").lower()
        asset_type = str(row.get("asset_type") or "").lower()
        suffix = path.suffix.lower()
        is_audio = asset_type == "audio" or mime.startswith("audio/") or suffix in _AUDIO_EXT
        if not is_audio:
            continue
        iid = str(row.get("id") or "").strip()
        if not iid:
            continue
        duration = _probe_duration(path)
        out.append(
            {
                "id": iid,
                "name": row.get("name") or iid,
                "mood": "素材中心",
                "category": "素材",
                "ready": True,
                "source": "asset",
                "clip_start": 0,
                "duration_sec": duration,
                "preview_url": f"/api/assets/file?id={iid}",
                "local_path": str(path.resolve()),
                "user": True,
                "from_asset": True,
            }
        )
    out.sort(key=lambda r: str(r.get("name") or ""))
    return out


def resolve_bgm_path(bgm_id: str) -> Path | None:
    bid = (bgm_id or "").strip()
    if not bid or bid.lower() in ("none", "off", ""):
        return None
    # 素材中心上传的音频（ast_…）
    if bid.startswith("ast_"):
        try:
            from workflow.asset_library import resolve_file

            return resolve_file(bid)
        except (FileNotFoundError, ValueError, OSError):
            return None
    user = _user_by_id(bid)
    if user and user.get("file"):
        p = BGM_ROOT / str(user["file"])
        if p.is_file():
            return p.resolve()
    if MANIFEST.is_file():
        try:
            items = json.loads(MANIFEST.read_text(encoding="utf-8"))
            for row in items:
                if row.get("id") == bid and row.get("file"):
                    p = BGM_ROOT / row["file"]
                    if p.is_file():
                        return p.resolve()
        except json.JSONDecodeError:
            pass
    row = _catalog_by_id(bid)
    if row:
        guess = BGM_ROOT / f"{row['name']}.mp3"
        if guess.is_file():
            return guess.resolve()
    return None


def bgm_meta(bgm_id: str) -> dict | None:
    bid = (bgm_id or "").strip()
    if bid.startswith("ast_"):
        path = resolve_bgm_path(bid)
        if not path:
            return None
        name = bid
        try:
            from workflow.asset_library import get_item

            item = get_item(bid)
            name = str(item.get("name") or bid)
        except Exception:
            pass
        duration = _probe_duration(path)
        return {
            "id": bid,
            "name": name,
            "mood": "素材中心",
            "category": "素材",
            "clip_start": 0.0,
            "trim_sec": float(duration or 75),
            "duration_sec": duration,
            "user": True,
            "from_asset": True,
        }
    user = _user_by_id(bid)
    if user:
        path = resolve_bgm_path(bid)
        duration = user.get("duration_sec")
        if duration is None and path and path.is_file():
            duration = _probe_duration(path)
        return {
            "id": user["id"],
            "name": user.get("name") or user["id"],
            "mood": user.get("mood") or "用户上传",
            "category": user.get("category") or "我的",
            "clip_start": float(user.get("clip_start") or 0),
            "trim_sec": float(user.get("trim_sec") or duration or 75),
            "duration_sec": duration,
            "user": True,
        }
    row = _catalog_by_id(bgm_id)
    if not row:
        return None
    path = resolve_bgm_path(bgm_id)
    duration = None
    if path and path.is_file():
        duration = _probe_duration(path)
        if duration is None:
            duration = float(row.get("trim_sec") or 75)
    return {
        "id": row["id"],
        "name": row["name"],
        "mood": row["mood"],
        "category": row.get("category", ""),
        "clip_start": float(row.get("clip_start") or 0),
        "trim_sec": float(row.get("trim_sec") or 75),
        "duration_sec": duration,
        "user": False,
    }


def list_bgm_library() -> list[dict]:
    manifest_map: dict[str, dict] = {}
    if MANIFEST.is_file():
        try:
            for row in json.loads(MANIFEST.read_text(encoding="utf-8")):
                if row.get("id"):
                    manifest_map[row["id"]] = row
        except json.JSONDecodeError:
            pass
    rows: list[dict] = []
    # User uploads first for visibility
    for row in _load_user_index():
        bid = str(row.get("id") or "")
        if not bid:
            continue
        path = resolve_bgm_path(bid)
        duration = row.get("duration_sec")
        if duration is None and path:
            duration = _probe_duration(path)
        rows.append(
            {
                "id": bid,
                "name": row.get("name") or bid,
                "mood": row.get("mood") or "用户上传",
                "category": row.get("category") or "我的",
                "ready": bool(path and path.is_file()),
                "source": "user",
                "clip_start": float(row.get("clip_start") or 0),
                "duration_sec": duration,
                "preview_url": f"/api/publish/bgm/preview?id={bid}" if path else None,
                "local_path": str(path.resolve()) if path and path.is_file() else None,
                "user": True,
            }
        )
    # 素材中心「音频」等分组上传的文件，也可在发布页选作 BGM
    rows.extend(_asset_audio_rows())
    for row in _CATALOG:
        path = BGM_ROOT / f"{row['name']}.mp3"
        meta = manifest_map.get(row["id"], {})
        source = meta.get("source") or ("ready" if path.is_file() else "missing")
        duration = meta.get("duration_sec")
        if duration is None and path.is_file():
            m = bgm_meta(row["id"])
            duration = m.get("duration_sec") if m else None
        rows.append(
            {
                "id": row["id"],
                "name": row["name"],
                "mood": row["mood"],
                "category": row.get("category", ""),
                "ready": path.is_file(),
                "source": source,
                "clip_start": float(row.get("clip_start") or 0),
                "duration_sec": duration,
                "preview_url": f"/api/publish/bgm/preview?id={row['id']}" if path.is_file() else None,
                "local_path": str(path.resolve()) if path.is_file() else None,
                "user": False,
            }
        )
    return rows


def needs_bgm_refresh() -> bool:
    """Re-download when manifest version old or files missing."""
    if not MANIFEST.is_file():
        return True
    try:
        items = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return True
    if not items:
        return True
    if any(row.get("source") == "generated" for row in items):
        return True
    if any(row.get("catalog_version") != 2 for row in items):
        return True
    for row in _CATALOG:
        if not (BGM_ROOT / f"{row['name']}.mp3").is_file():
            return True
    return False

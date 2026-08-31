"""User asset library: groups, uploads, and URL resources."""

from __future__ import annotations

import json
import shutil
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

ASSET_ROOT = Path("data/assets")
FILES_DIR = ASSET_ROOT / "files"
INDEX_PATH = ASSET_ROOT / "library.json"

_BUILTIN_GROUPS = [
    {"id": "icon", "name": "图标", "builtin": True},
    {"id": "card", "name": "HyperFrames", "builtin": True},
    {"id": "audio", "name": "音频", "builtin": True},
    {"id": "bgm", "name": "背景音乐", "builtin": True},
    {"id": "video", "name": "视频", "builtin": True},
    {"id": "avatar", "name": "数字人分身", "builtin": True},
]

# Fixed group ids used by UI / APIs (must stay in sync with _BUILTIN_GROUPS)
BUILTIN_GROUP_IDS = frozenset(g["id"] for g in _BUILTIN_GROUPS)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _default_index() -> dict:
    return {"version": 1, "groups": [dict(g) for g in _BUILTIN_GROUPS], "items": []}


def _load() -> dict:
    ASSET_ROOT.mkdir(parents=True, exist_ok=True)
    FILES_DIR.mkdir(parents=True, exist_ok=True)
    if not INDEX_PATH.is_file():
        data = _default_index()
        INDEX_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return data
    try:
        data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        data = _default_index()
    if not data.get("groups"):
        data["groups"] = [dict(g) for g in _BUILTIN_GROUPS]
    else:
        existing = {g["id"] for g in data["groups"]}
        for g in _BUILTIN_GROUPS:
            if g["id"] not in existing:
                data["groups"].append(dict(g))
        # Keep builtin groups in declared order at the front
        by_id = {g["id"]: g for g in data["groups"]}
        ordered: list[dict] = []
        for g in _BUILTIN_GROUPS:
            if g["id"] in by_id:
                row = by_id.pop(g["id"])
                row["builtin"] = True
                row["name"] = g["name"]
                ordered.append(row)
        for g in data["groups"]:
            if g["id"] in by_id:
                ordered.append(by_id.pop(g["id"]))
        data["groups"] = ordered
    return data


def _save(data: dict) -> None:
    ASSET_ROOT.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _guess_kind(mime: str, name: str) -> str:
    m = (mime or "").lower()
    n = (name or "").lower()
    if m.startswith("image/") or n.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".ico")):
        return "icon"
    if m.startswith("audio/") or n.endswith((".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac")):
        return "audio"
    if m.startswith("video/") or n.endswith((".mp4", ".mov", ".webm", ".mkv")):
        return "video"
    return "icon"


def list_library() -> dict:
    data = _load()
    items = []
    for row in data.get("items", []):
        # Skip stray copies that belong in the BGM virtual group
        if row.get("group_id") == "bgm":
            continue
        items.append(_item_public(row))
    items.extend(_bgm_virtual_items())
    return {"groups": data.get("groups", []), "items": items}


def _bgm_virtual_items() -> list[dict]:
    """Surface curated + user BGM tracks inside the asset center."""
    try:
        from workflow.bgm import list_bgm_library
    except Exception:
        return []
    out: list[dict] = []
    for row in list_bgm_library():
        bid = str(row.get("id") or "")
        if not bid:
            continue
        ready = bool(row.get("ready"))
        preview = row.get("preview_url") if ready else None
        out.append(
            {
                "id": f"bgm::{bid}",
                "group_id": "bgm",
                "name": row.get("name") or bid,
                "asset_type": "audio",
                "kind": "file",
                "preview_url": preview,
                "url": "",
                "bgm_id": bid,
                "mood": row.get("mood") or "",
                "category": row.get("category") or "",
                "source": row.get("source") or "",
                "user": bool(row.get("user")),
                "ready": ready,
                "duration_sec": row.get("duration_sec"),
                "builtin_bgm": not bool(row.get("user")),
            }
        )
    return out


def _item_public(row: dict) -> dict:
    out = dict(row)
    if row.get("kind") == "file" and row.get("path"):
        out["preview_url"] = f"/api/assets/file?id={row['id']}"
    elif row.get("kind") == "url" and row.get("url"):
        out["preview_url"] = row["url"]
    return out


def create_group(name: str) -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError("分组名称不能为空")
    data = _load()
    gid = f"grp_{uuid.uuid4().hex[:10]}"
    group = {"id": gid, "name": name, "builtin": False}
    data["groups"].append(group)
    _save(data)
    return group


def rename_group(group_id: str, name: str) -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError("分组名称不能为空")
    data = _load()
    for g in data["groups"]:
        if g["id"] == group_id:
            g["name"] = name
            _save(data)
            return g
    raise ValueError("分组不存在")


def delete_group(group_id: str) -> None:
    data = _load()
    grp = next((g for g in data["groups"] if g["id"] == group_id), None)
    if not grp:
        raise ValueError("分组不存在")
    if grp.get("builtin"):
        raise ValueError("内置分组不可删除")
    fallback = "icon"
    for item in data["items"]:
        if item.get("group_id") == group_id:
            item["group_id"] = fallback
    data["groups"] = [g for g in data["groups"] if g["id"] != group_id]
    _save(data)


def add_file_item(
    group_id: str,
    name: str,
    src_path: Path,
    *,
    mime: str = "",
) -> dict:
    if group_id == "avatar":
        raise ValueError("数字人分身请在「数字人分身」分组使用专用上传（写入形象库）")
    if group_id == "bgm":
        from workflow.bgm import upload_user_bgm

        bgm = upload_user_bgm(Path(src_path), name=name, mime=mime)
        return {
            "id": f"bgm::{bgm['id']}",
            "group_id": "bgm",
            "name": bgm["name"],
            "asset_type": "audio",
            "kind": "file",
            "preview_url": bgm.get("preview_url"),
            "url": "",
            "bgm_id": bgm["id"],
            "mood": bgm.get("mood") or "用户上传",
            "category": "我的",
            "source": "user",
            "user": True,
            "ready": True,
            "duration_sec": bgm.get("duration_sec"),
            "builtin_bgm": False,
        }
    data = _load()
    if not any(g["id"] == group_id for g in data["groups"]):
        raise ValueError("分组不存在")
    FILES_DIR.mkdir(parents=True, exist_ok=True)
    item_id = f"ast_{uuid.uuid4().hex[:12]}"
    suffix = src_path.suffix.lower() or ".bin"
    dest = FILES_DIR / f"{item_id}{suffix}"
    shutil.copy2(src_path, dest)
    display = (name or src_path.stem).strip() or "未命名素材"
    row = {
        "id": item_id,
        "group_id": group_id,
        "name": display,
        "asset_type": _guess_kind(mime, dest.name),
        "kind": "file",
        "path": str(dest.resolve()),
        "mime": mime or "",
        "url": "",
        "created_at": _now_ms(),
    }
    data["items"].append(row)
    _save(data)
    return _item_public(row)


def add_url_item(group_id: str, name: str, url: str) -> dict:
    if group_id == "avatar":
        raise ValueError("数字人分身不支持 URL，请上传本地参考视频或肖像图")
    if group_id == "bgm":
        raise ValueError("背景音乐请上传本地音频文件（不支持 URL）")
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError("请填写 http(s) 开头的资源 URL")
    parsed = urlparse(url)
    if not parsed.netloc:
        raise ValueError("URL 无效")
    data = _load()
    if not any(g["id"] == group_id for g in data["groups"]):
        raise ValueError("分组不存在")
    item_id = f"ast_{uuid.uuid4().hex[:12]}"
    guess_name = (name or "").strip() or Path(parsed.path).name or parsed.netloc
    row = {
        "id": item_id,
        "group_id": group_id,
        "name": guess_name,
        "asset_type": _guess_kind("", guess_name),
        "kind": "url",
        "path": "",
        "mime": "",
        "url": url,
        "created_at": _now_ms(),
    }
    data["items"].append(row)
    _save(data)
    return _item_public(row)


def update_item(item_id: str, *, name: str | None = None, group_id: str | None = None) -> dict:
    if str(item_id).startswith("bgm::"):
        raise ValueError("背景音乐请在发布页或本分组重新上传；曲目名称暂不支持在素材中心改名")
    data = _load()
    for item in data["items"]:
        if item["id"] != item_id:
            continue
        if name is not None:
            n = name.strip()
            if n:
                item["name"] = n
        if group_id is not None:
            if group_id == "avatar":
                raise ValueError("普通素材不能移入「数字人分身」分组")
            if group_id == "bgm":
                raise ValueError("普通素材不能移入「背景音乐」；请直接上传音频到该分组")
            if not any(g["id"] == group_id for g in data["groups"]):
                raise ValueError("分组不存在")
            item["group_id"] = group_id
        _save(data)
        return _item_public(item)
    raise ValueError("素材不存在")


def delete_item(item_id: str) -> None:
    sid = str(item_id)
    if sid.startswith("bgm::"):
        from workflow.bgm import delete_user_bgm

        delete_user_bgm(sid[5:])
        return
    data = _load()
    kept = []
    removed = None
    for item in data["items"]:
        if item["id"] == item_id:
            removed = item
            continue
        kept.append(item)
    if removed is None:
        raise ValueError("素材不存在")
    if removed.get("kind") == "file" and removed.get("path"):
        try:
            Path(removed["path"]).unlink(missing_ok=True)
        except OSError:
            pass
    data["items"] = kept
    _save(data)


def resolve_file(item_id: str) -> Path:
    data = _load()
    for item in data["items"]:
        if item["id"] == item_id and item.get("kind") == "file":
            p = Path(item["path"])
            if p.is_file():
                return p.resolve()
    raise FileNotFoundError("素材文件不存在")


def get_item(item_id: str) -> dict:
    data = _load()
    for item in data["items"]:
        if item["id"] == item_id:
            return _item_public(item)
    raise ValueError("素材不存在")


def list_picker_items() -> list[dict]:
    """Local image/video assets for publish timeline picker."""
    data = _load()
    image_ext = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
    video_ext = {".mp4", ".mov", ".webm", ".mkv"}
    out: list[dict] = []
    for item in data.get("items", []):
        if item.get("kind") != "file":
            continue
        path = item.get("path") or ""
        ext = Path(path).suffix.lower()
        is_video = item.get("asset_type") == "video" or ext in video_ext
        is_image = item.get("group_id") == "card" or item.get("asset_type") == "icon" or ext in image_ext
        if not is_video and not is_image:
            continue
        row = _item_public(item)
        row["media_path"] = path
        row["media_type"] = "video" if is_video else "image"
        out.append(row)
    return out


def stage_asset_for_pip(session_pip_dir: Path, asset_id: str, cue_index: int) -> Path:
    src = resolve_file(asset_id)
    session_pip_dir.mkdir(parents=True, exist_ok=True)
    suffix = src.suffix.lower() or ".png"
    if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".mov", ".webm", ".mkv"}:
        suffix = ".png"
    dest = session_pip_dir / f"lib_{asset_id}_cue{cue_index}_{int(time.time() * 1000)}{suffix}"
    shutil.copy2(src, dest)
    return dest.resolve()


def stage_asset_for_lipsync(session_dir: Path, asset_id: str, role: str = "media") -> Path:
    """Copy a library image/video into the session for LatentSync / SadTalker."""
    src = resolve_file(asset_id)
    session_dir.mkdir(parents=True, exist_ok=True)
    suffix = src.suffix.lower() or ".mp4"
    allowed = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".mp4", ".mov", ".webm", ".mkv", ".m4v"}
    if suffix not in allowed:
        raise ValueError(f"素材类型不支持对口型：{suffix}")
    safe_role = (role or "media").strip().replace(" ", "_")[:32] or "media"
    dest = session_dir / f"lib_{safe_role}_{asset_id}_{int(time.time() * 1000)}{suffix}"
    shutil.copy2(src, dest)
    return dest.resolve()

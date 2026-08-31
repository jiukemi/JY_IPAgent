"""Saved clone voice library."""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path

VOICES_ROOT = Path("data/voices")
INDEX_PATH = VOICES_ROOT / "index.json"


def _load_index() -> dict:
    if not INDEX_PATH.exists():
        return {"voices": []}
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


def _save_index(data: dict) -> None:
    VOICES_ROOT.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def list_voices() -> list[dict]:
    return _load_index().get("voices", [])


def voice_choices() -> list[tuple[str, str]]:
    items = list_voices()
    if not items:
        return [("（暂无，请去新增克隆）", "")]
    return [(v["name"], v["id"]) for v in items]


def library_choices() -> list[tuple[str, str]]:
    items = list_voices()
    if not items:
        return [("（暂无音色）", "")]
    return [(f"{v['name']}  [{v.get('backend', 'indextts')}]", v["id"]) for v in items]


def next_default_name(source: str) -> str:
    """source: record | upload -> 录制声音N / 上传声音N"""
    prefix = "录制声音" if source == "record" else "上传声音"
    max_n = 0
    for v in list_voices():
        name = v.get("name", "")
        if name.startswith(prefix):
            suffix = name[len(prefix) :]
            if suffix.isdigit():
                max_n = max(max_n, int(suffix))
    return f"{prefix}{max_n + 1}"


def get_voice(voice_id: str) -> dict | None:
    if not voice_id:
        return None
    for v in list_voices():
        if v["id"] == voice_id:
            return v
    return None


def update_voice(voice_id: str, **fields) -> dict:
    data = _load_index()
    for v in data.get("voices", []):
        if v["id"] == voice_id:
            v.update(fields)
            _save_index(data)
            return v
    raise ValueError(f"音色不存在: {voice_id}")


def save_voice(
    name: str,
    reference_path: str,
    *,
    prompt_text: str = "",
    backend: str = "indextts",
    source_type: str = "",
) -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError("请填写音色名称")
    src = Path(reference_path)
    if not src.exists():
        raise FileNotFoundError(f"参考音频不存在: {reference_path}")

    vid = uuid.uuid4().hex[:12]
    dest_dir = VOICES_ROOT / vid
    dest_dir.mkdir(parents=True, exist_ok=True)
    ext = (src.suffix or ".wav").lower()
    upload_copy = dest_dir / f"upload{ext}"
    shutil.copy2(src, upload_copy)

    dest_wav = dest_dir / "reference.wav"
    converted = False
    try:
        from pipeline import ensure_ffmpeg
        from tts.engine import convert_to_wav

        try:
            from workflow.app_config import load_cfg

            ffmpeg_bin = ensure_ffmpeg(load_cfg()["paths"].get("ffmpeg", "ffmpeg"))
        except Exception:
            ffmpeg_bin = ensure_ffmpeg("ffmpeg")
        convert_to_wav(ffmpeg_bin, upload_copy, dest_wav, sample_rate=22050)
        converted = dest_wav.is_file() and dest_wav.stat().st_size > 100
    except Exception:
        converted = False

    if not converted:
        if ext == ".wav":
            if dest_wav.exists():
                dest_wav.unlink(missing_ok=True)
            upload_copy.replace(dest_wav)
        else:
            dest_wav = upload_copy

    if not dest_wav.is_file() or dest_wav.stat().st_size < 100:
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise ValueError("参考音频无效或过短，请上传/录制至少 3 秒的清晰人声")

    if converted and upload_copy.exists() and upload_copy != dest_wav:
        upload_copy.unlink(missing_ok=True)

    entry = {
        "id": vid,
        "name": name,
        "reference_wav": str(dest_wav.resolve()),
        "prompt_text": (prompt_text or "").strip(),
        "backend": (backend or "indextts").lower(),
        "source_type": source_type or "",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    data = _load_index()
    data.setdefault("voices", []).insert(0, entry)
    _save_index(data)
    return entry


def _source_label(source_type: str) -> str:
    return {"record": "录音", "upload": "上传"}.get(source_type, source_type)


def format_voice_table() -> str:
    items = list_voices()
    if not items:
        return "*暂无音色，点击「新增克隆」开始。*"
    lines = [f"共 **{len(items)}** 个音色："]
    for v in items:
        src = _source_label(v.get("source_type", ""))
        src_tag = f" · {src}" if src else ""
        lines.append(f"- **{v['name']}**{src_tag} · {v.get('backend', 'indextts')} · {v.get('created_at', '')}")
    return "\n".join(lines)


def delete_voice(voice_id: str) -> bool:
    data = _load_index()
    voices = data.get("voices", [])
    kept = []
    removed = False
    for v in voices:
        if v["id"] == voice_id:
            removed = True
            p = Path(v.get("reference_wav", ""))
            if p.parent.exists() and p.parent != VOICES_ROOT:
                shutil.rmtree(p.parent, ignore_errors=True)
        else:
            kept.append(v)
    if removed:
        data["voices"] = kept
        _save_index(data)
    return removed

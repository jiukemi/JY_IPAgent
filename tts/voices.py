"""Saved clone voice library."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from workflow.bundle_paths import project_root


def _candidate_voice_roots() -> list[Path]:
    """Prefer runtime data dir (desktop), then project data/, then cwd-relative legacy."""
    roots: list[Path] = []
    rt = (os.environ.get("AGENT_RUNTIME_DIR") or "").strip()
    if rt:
        roots.append(Path(rt).expanduser().resolve() / "data" / "voices")
    roots.append(project_root() / "data" / "voices")
    try:
        roots.append(Path("data/voices").resolve())
    except OSError:
        pass
    seen: set[str] = set()
    out: list[Path] = []
    for r in roots:
        key = str(r)
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def voices_root() -> Path:
    """Writable root for new saves; prefer existing library if present."""
    cands = _candidate_voice_roots()
    for r in cands:
        if (r / "index.json").is_file():
            return r
    return cands[0]


def _index_path() -> Path:
    return voices_root() / "index.json"


# Back-compat aliases (some code imported these as constants)
def _sync_legacy_aliases() -> None:
    global VOICES_ROOT, INDEX_PATH
    VOICES_ROOT = voices_root()
    INDEX_PATH = _index_path()


VOICES_ROOT = Path("data/voices")
INDEX_PATH = VOICES_ROOT / "index.json"
_sync_legacy_aliases()


def _load_index() -> dict:
    _sync_legacy_aliases()
    # Merge voices from all candidate roots (runtime + legacy project)
    by_id: dict[str, dict] = {}
    order: list[str] = []
    for root in _candidate_voice_roots():
        idx = root / "index.json"
        if not idx.is_file():
            continue
        try:
            data = json.loads(idx.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for v in data.get("voices") or []:
            if not isinstance(v, dict):
                continue
            vid = str(v.get("id") or "")
            if not vid or vid in by_id:
                continue
            repaired = dict(v)
            repaired["reference_wav"] = str(
                resolve_voice_wav(repaired, root=root) or repaired.get("reference_wav") or ""
            )
            by_id[vid] = repaired
            order.append(vid)
    return {"voices": [by_id[i] for i in order]}


def _save_index(data: dict) -> None:
    root = voices_root()
    root.mkdir(parents=True, exist_ok=True)
    path = root / "index.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    _sync_legacy_aliases()


def resolve_voice_wav(entry: dict, *, root: Path | None = None) -> Path | None:
    """Resolve a usable reference wav for a library entry (repairs moved installs)."""
    candidates: list[Path] = []
    raw = str(entry.get("reference_wav") or "").strip()
    if raw:
        candidates.append(Path(raw))
    vid = str(entry.get("id") or "").strip()
    roots = [root] if root is not None else _candidate_voice_roots()
    if vid:
        for r in roots:
            if r is None:
                continue
            candidates.append(r / vid / "reference.wav")
    for c in candidates:
        try:
            if c.is_file() and c.stat().st_size > 100:
                return c.resolve()
        except OSError:
            continue
    return None


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
            wav = resolve_voice_wav(v)
            if wav is not None:
                out = dict(v)
                out["reference_wav"] = str(wav)
                return out
            return v
    return None


def update_voice(voice_id: str, **fields) -> dict:
    data = _load_index()
    for v in data.get("voices", []):
        if v["id"] == voice_id:
            v.update(fields)
            _save_index({"voices": data["voices"]})
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

    root = voices_root()
    root.mkdir(parents=True, exist_ok=True)
    vid = uuid.uuid4().hex[:12]
    dest_dir = root / vid
    dest_dir.mkdir(parents=True, exist_ok=True)
    ext = (src.suffix or ".wav").lower()
    upload_copy = dest_dir / f"upload{ext}"
    shutil.copy2(src, upload_copy)

    # 存盘时统一转成 mono 22.05kHz wav，后续配音/试听直接用，不再每次 ffmpeg
    dest_wav = dest_dir / "reference.wav"
    sample_rate = 22050
    try:
        from pipeline import ensure_ffmpeg
        from tts.engine import _wav_ready, convert_to_wav

        try:
            from workflow.app_config import load_cfg

            ffmpeg_bin = ensure_ffmpeg(load_cfg()["paths"].get("ffmpeg", "ffmpeg"))
        except Exception:
            ffmpeg_bin = ensure_ffmpeg("ffmpeg")

        if _wav_ready(upload_copy, sample_rate):
            if upload_copy.resolve() != dest_wav.resolve():
                if dest_wav.exists():
                    dest_wav.unlink(missing_ok=True)
                upload_copy.replace(dest_wav)
        else:
            convert_to_wav(ffmpeg_bin, upload_copy, dest_wav, sample_rate=sample_rate)
            if not dest_wav.is_file() or dest_wav.stat().st_size < 100:
                raise RuntimeError("ffmpeg 转换后文件无效")
            if upload_copy.exists() and upload_copy.resolve() != dest_wav.resolve():
                upload_copy.unlink(missing_ok=True)
    except Exception as exc:
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise ValueError(
            f"参考音频无法转成标准 wav（请用 wav/mp3/m4a，或检查本机 ffmpeg）：{exc}"
        ) from exc

    if not dest_wav.is_file() or dest_wav.stat().st_size < 100:
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise ValueError("参考音频无效或过短，请上传/录制至少 3 秒的清晰人声")

    entry = {
        "id": vid,
        "name": name,
        "reference_wav": str(dest_wav.resolve()),
        "prompt_text": (prompt_text or "").strip(),
        "backend": (backend or "indextts").lower(),
        "source_type": source_type or "",
        "sample_rate": sample_rate,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    data = _load_index()
    merged = [entry] + [v for v in data.get("voices", []) if v.get("id") != vid]
    _save_index({"voices": merged})
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
    target_root = voices_root()
    for v in voices:
        if v["id"] == voice_id:
            removed = True
            wav = resolve_voice_wav(v)
            if wav is not None and wav.parent.exists() and wav.parent != target_root:
                shutil.rmtree(wav.parent, ignore_errors=True)
            else:
                for root in _candidate_voice_roots():
                    d = root / voice_id
                    if d.is_dir():
                        shutil.rmtree(d, ignore_errors=True)
        else:
            kept.append(v)
    if removed:
        _save_index({"voices": kept})
    return removed

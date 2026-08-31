"""HeyGem / Duix-Avatar local HTTP client (port 8383)."""

from __future__ import annotations

import json
import shutil
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable

ProgressFn = Callable[[float, str], None]

# Duix query status codes (when nested under data.status)
_STATUS_DONE = {2, "2", "success", "done", "finish", "completed", "200"}
_STATUS_FAIL = {3, "3", "fail", "failed", "error", "cancel", "cancelled"}


def heygem_cfg(cfg: dict) -> dict:
    return cfg.get("heygem") or {}


def api_base(cfg: dict) -> str:
    return (heygem_cfg(cfg).get("video_api") or "http://127.0.0.1:8383").rstrip("/")


def health_check(cfg: dict, timeout: float = 3.0) -> bool:
    url = f"{api_base(cfg)}/easy/query?code=health_probe"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
        return True
    except urllib.error.HTTPError:
        return True
    except OSError:
        return False


def host_mount(cfg: dict) -> Path:
    raw = heygem_cfg(cfg).get("data_mount_host") or ""
    if not raw:
        raise RuntimeError(
            "HeyGem 未配置 data_mount_host。\n"
            "在 config.yaml → heygem.data_mount_host 填写 Docker 挂载目录"
            "（如 E:/agent/data/heygem_face2face）。"
        )
    return Path(raw).expanduser().resolve()


def container_prefix(cfg: dict) -> str:
    return (heygem_cfg(cfg).get("data_mount_container") or "/code/data").rstrip("/")


def to_container_path(cfg: dict, host_path: Path) -> str:
    mount = host_mount(cfg)
    host_path = host_path.resolve()
    try:
        rel = host_path.relative_to(mount)
    except ValueError as exc:
        raise ValueError(
            f"文件须在 HeyGem 挂载目录内: {mount}\n当前: {host_path}"
        ) from exc
    return f"{container_prefix(cfg)}/{rel.as_posix()}"


def stage_file(cfg: dict, src: Path, subdir: str, name: str) -> tuple[Path, str]:
    """Copy into mount and return (host_path, container_path)."""
    mount = host_mount(cfg)
    task_dir = mount / subdir
    task_dir.mkdir(parents=True, exist_ok=True)
    dest = task_dir / name
    shutil.copy2(src, dest)
    return dest, to_container_path(cfg, dest)


def _post_json(url: str, payload: dict, timeout: float = 60.0) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    if not body.strip():
        return {}
    return json.loads(body)


def _get_json(url: str, timeout: float = 30.0) -> dict:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    return json.loads(body) if body.strip() else {}


def _unwrap_query(raw: dict) -> dict[str, Any]:
    """Normalize Duix /easy/query payload (nested under data)."""
    inner = raw.get("data")
    if not isinstance(inner, dict):
        inner = {}
    msg = str(raw.get("msg") or inner.get("msg") or "").strip()
    code = raw.get("code")
    status = inner.get("status", raw.get("status"))
    progress = inner.get("progress", raw.get("progress"))
    result = (
        inner.get("result")
        or inner.get("video_path")
        or inner.get("video_url")
        or raw.get("result")
        or raw.get("video_path")
        or raw.get("video_url")
    )
    return {
        "api_code": code,
        "msg": msg,
        "status": status,
        "progress": progress,
        "result": result,
        "raw": raw,
    }


def _status_label(status: Any, msg: str) -> str:
    if msg:
        return msg
    if status in (None, ""):
        return "合成中"
    mapping = {0: "排队中", 1: "合成中", 2: "完成", 3: "失败"}
    try:
        return mapping.get(int(status), str(status))
    except (TypeError, ValueError):
        return str(status)


def _is_missing_task(api_code: Any, msg: str) -> bool:
    if api_code in (10004, "10004"):
        return True
    return any(k in msg for k in ("不存在", "not exist", "not found", "NotFound"))


def _is_failed(status: Any, msg: str, api_code: Any) -> bool:
    if _is_missing_task(api_code, msg):
        return True
    if any(k in msg.lower() for k in ("失败", "fail", "error", "异常", "timeout")):
        return True
    if status in _STATUS_FAIL:
        return True
    text = str(status).lower()
    return any(m in text for m in ("fail", "error", "cancel"))


def _is_done(status: Any, result: Any) -> bool:
    if status in _STATUS_DONE:
        return True
    text = str(status).lower()
    if any(m in text for m in ("success", "done", "finish", "completed")):
        return True
    return isinstance(result, str) and result.endswith(".mp4")


def assert_docker_mount_matches(cfg: dict) -> None:
    """Warn early when container volume ≠ config data_mount_host."""
    import subprocess

    expected = str(host_mount(cfg)).replace("\\", "/").lower().rstrip("/")
    try:
        out = subprocess.check_output(
            [
                "docker",
                "inspect",
                "duix-avatar-gen-video",
                "--format",
                "{{range .Mounts}}{{.Source}}->{{.Destination}};{{end}}",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=8,
        )
    except (OSError, subprocess.SubprocessError):
        return
    mounts = (out or "").strip()
    if not mounts:
        return
    # Source path appears before ->/code/data
    for part in mounts.split(";"):
        if "->/code/data" in part.replace("\\", "/") or ">/code/data" in part.replace("\\", "/"):
            src = part.split("->")[0].split(">")[0].strip().replace("\\", "/").lower().rstrip("/")
            # Docker may report d:/foo or D:/foo
            if src and expected not in src and src not in expected:
                raise RuntimeError(
                    "HeyGem Docker 挂载目录与 config.yaml 不一致，任务会立即失败（三次获取音频时长失败 / 任务不存在）。\n"
                    f"配置目录: {host_mount(cfg)}\n"
                    f"容器挂载: {src}\n"
                    "请在 ④ 口播面板重新「启动 HeyGem」，或运行 .\\scripts\\setup\\setup_heygem.ps1 重建容器。"
                )


def submit_video_task(
    cfg: dict,
    audio_host: Path,
    model_video_host: Path,
    *,
    task_code: str | None = None,
) -> str:
    assert_docker_mount_matches(cfg)
    code = task_code or uuid.uuid4().hex
    _audio_dest, audio_url = stage_file(cfg, audio_host, f"tasks/{code}", "audio.wav")
    _model_dest, video_url = stage_file(
        cfg, model_video_host, f"tasks/{code}", "model.mp4"
    )
    # Ensure container can see the staged files (same path as bind mount).
    if not _audio_dest.is_file() or _audio_dest.stat().st_size < 1000:
        raise RuntimeError(f"HeyGem 音频写入失败: {_audio_dest}")
    if not _model_dest.is_file() or _model_dest.stat().st_size < 1000:
        raise RuntimeError(f"HeyGem 参考视频写入失败: {_model_dest}")

    payload = {
        "audio_url": audio_url,
        "video_url": video_url,
        "code": code,
        "chaofen": int(heygem_cfg(cfg).get("chaofen", 0)),
        "watermark_switch": int(heygem_cfg(cfg).get("watermark_switch", 0)),
        "pn": int(heygem_cfg(cfg).get("pn", 1)),
    }
    url = f"{api_base(cfg)}/easy/submit"
    resp = _post_json(url, payload)
    api_code = resp.get("code")
    if api_code not in (None, 0, 10000, "10000", 200, "200") and resp.get("success") is False:
        raise RuntimeError(f"HeyGem 提交失败: {resp}")
    if resp.get("success") is False:
        raise RuntimeError(f"HeyGem 提交失败: {resp}")
    return code


def _candidate_result_paths(cfg: dict, task_code: str) -> list[Path]:
    mount = host_mount(cfg)
    return [
        mount / "temp" / f"{task_code}-r.mp4",
        mount / "temp" / f"{task_code}.mp4",
        mount / "result" / f"{task_code}-r.mp4",
        mount / "result" / f"{task_code}.mp4",
        mount / "tasks" / task_code / "result.mp4",
    ]


def _mp4_looks_complete(path: Path, *, min_size: int = 100_000) -> bool:
    """Reject files still being written by Docker ffmpeg (no moov → unplayable)."""
    try:
        if not path.is_file():
            return False
        size = path.stat().st_size
        if size < min_size:
            return False
        # moov may be at start (faststart) or near end — sample both.
        with path.open("rb") as f:
            head = f.read(2_048_000)
            if size > 2_048_000:
                f.seek(max(0, size - 2_048_000))
                tail = f.read(2_048_000)
            else:
                tail = b""
        blob = head + tail
        if b"moov" not in blob:
            return False
        # Size must be stable across a short wait (ffmpeg still appending).
        time.sleep(0.8)
        if path.stat().st_size != size:
            return False
        return True
    except OSError:
        return False


def _copy_complete_result(src: Path, output_host: Path) -> Path | None:
    if not _mp4_looks_complete(src):
        return None
    output_host.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_host.with_suffix(output_host.suffix + ".partial")
    try:
        shutil.copy2(src, tmp)
        if not _mp4_looks_complete(tmp, min_size=50_000):
            tmp.unlink(missing_ok=True)
            return None
        tmp.replace(output_host)
        return output_host
    except OSError:
        tmp.unlink(missing_ok=True)
        return None


def _try_collect_result(cfg: dict, task_code: str, output_host: Path) -> Path | None:
    for guess in _candidate_result_paths(cfg, task_code):
        collected = _copy_complete_result(guess, output_host)
        if collected is not None:
            return collected
    return None


def poll_video_task(
    cfg: dict,
    task_code: str,
    output_host: Path,
    *,
    on_progress: ProgressFn | None = None,
) -> Path:
    poll = float(heygem_cfg(cfg).get("poll_interval_sec", 2))
    timeout = float(heygem_cfg(cfg).get("timeout_sec", 3600))
    url = f"{api_base(cfg)}/easy/query?code={task_code}"
    started = time.time()
    seen_running = False
    missing_streak = 0

    while time.time() - started < timeout:
        from workflow.task_control import check_cancelled

        check_cancelled()
        raw = _get_json(url)
        info = _unwrap_query(raw)
        status = info["status"]
        msg = info["msg"]
        progress = info["progress"]
        result_path = info["result"]
        api_code = info["api_code"]
        label = _status_label(status, msg)

        if on_progress:
            pct = 0.2
            if isinstance(progress, (int, float)):
                # Duix may report 0–1 or 0–100
                p = float(progress)
                if p > 1.0:
                    p = p / 100.0
                pct = 0.2 + max(0.0, min(1.0, p)) * 0.75
            elif status in (1, "1"):
                pct = 0.35
            on_progress(min(pct, 0.95), f"HeyGem · {label}")

        if status in (1, "1", 0, "0") or (isinstance(progress, (int, float)) and float(progress) > 0):
            seen_running = True
            missing_streak = 0

        # Duix often returns 10004 after finishing and purging task index —
        # the mp4 already lives under temp/{code}-r.mp4.
        collected = _try_collect_result(cfg, task_code, output_host)
        if collected is not None:
            if on_progress:
                on_progress(1.0, "HeyGem 完成")
            return collected

        if _is_missing_task(api_code, msg):
            missing_streak += 1
            # Right after submit, query may briefly 10004; tolerate a few polls.
            if seen_running or missing_streak >= 5:
                # One last scan — success file may appear a second late.
                collected = _try_collect_result(cfg, task_code, output_host)
                if collected is not None:
                    if on_progress:
                        on_progress(1.0, "HeyGem 完成")
                    return collected
                raise RuntimeError(
                    "HeyGem 任务不存在或已失败（常见原因：Docker 数据目录与 config.yaml "
                    "heygem.data_mount_host 不一致，容器读不到音频/视频；"
                    "或合成已结束但结果路径未接到）。\n"
                    f"详情: {raw}\n"
                    "请重新「启动 HeyGem」或运行 .\\scripts\\setup\\setup_heygem.ps1，再试一次。"
                )
            time.sleep(poll)
            continue

        if _is_failed(status, msg, api_code):
            raise RuntimeError(f"HeyGem 合成失败: {raw}")

        if _is_done(status, result_path):
            if isinstance(result_path, dict):
                result_path = result_path.get("video_path") or result_path.get("path")
            if isinstance(result_path, str) and result_path:
                host = _resolve_result_host(cfg, result_path)
                if host and host.exists():
                    copied = _copy_complete_result(host, output_host)
                    if copied is not None:
                        if on_progress:
                            on_progress(1.0, "HeyGem 完成")
                        return copied
            collected = _try_collect_result(cfg, task_code, output_host)
            if collected is not None:
                if on_progress:
                    on_progress(1.0, "HeyGem 完成")
                return collected

        time.sleep(poll)

    collected = _try_collect_result(cfg, task_code, output_host)
    if collected is not None:
        if on_progress:
            on_progress(1.0, "HeyGem 完成")
        return collected
    raise TimeoutError(f"HeyGem 合成超时（>{timeout}s）")


def _resolve_result_host(cfg: dict, result_path: str) -> Path | None:
    mount = host_mount(cfg)
    prefix = container_prefix(cfg)
    raw = (result_path or "").strip()
    if not raw:
        return None
    if raw.startswith(prefix):
        rel = raw[len(prefix) :].lstrip("/\\")
        return mount / rel.replace("/", "\\")
    p = Path(raw)
    if p.is_absolute() and p.exists():
        return p
    # Duix sometimes returns "/{code}-r.mp4" (absolute-looking but under /code/data/temp)
    name = raw.lstrip("/\\")
    for candidate in (
        mount / name,
        mount / "temp" / name,
        mount / "result" / name,
        mount / "temp" / Path(name).name,
        mount / "result" / Path(name).name,
    ):
        if candidate.is_file():
            return candidate
    return None


def generate_video(
    cfg: dict,
    audio_path: Path,
    model_video_path: Path,
    output_path: Path,
    *,
    on_progress: ProgressFn | None = None,
) -> Path:
    if not health_check(cfg):
        raise RuntimeError(
            "口播引擎未启动（8383 无响应）。\n"
            "请下载并启动本机口播组件（data/components/heygem-runtime），无需 Docker Desktop；\n"
            "或在口播页点「一键启动口播引擎」。\n"
            "若只有肖像图，可改选引擎「SadTalker」。"
        )
    _validate_reference_video(cfg, model_video_path)
    if on_progress:
        on_progress(0.05, "提交 HeyGem 任务…")
    code = submit_video_task(cfg, audio_path, model_video_path)
    if on_progress:
        on_progress(0.15, f"任务 {code[:8]}…")
    return poll_video_task(cfg, code, output_path, on_progress=on_progress)


def _validate_reference_video(cfg: dict, model_video_path: Path) -> None:
    """Warn early if reference clip is too short/long for good lip-sync."""
    try:
        from pipeline import ensure_ffmpeg, ffprobe_bin, media_duration

        ffmpeg = ensure_ffmpeg((cfg.get("paths") or {}).get("ffmpeg", "ffmpeg"))
        probe = ffprobe_bin(ffmpeg)
        dur = media_duration(probe, model_video_path)
    except (RuntimeError, OSError, ValueError):
        return
    if dur < 5:
        raise ValueError(
            f"参考视频过短（{dur:.1f}s）。建议上传 10–20 秒正脸口播 mp4/mov，对口型与动作更自然。"
        )
    if dur > 45:
        raise ValueError(
            f"参考视频较长（{dur:.0f}s），合成会更慢。"
            "建议裁剪到 10–20 秒；或换一段更短的参考片以提速。"
        )

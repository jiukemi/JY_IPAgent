"""API error helpers."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from functools import wraps
from typing import TypeVar

from fastapi import HTTPException

from ui.gradio_compat import gr

F = TypeVar("F", bound=Callable)


def format_user_error(message: str, *, engine: str | None = None) -> str:
    """Turn raw backend errors into structured user-facing text."""
    msg = (message or "").strip()
    eng = (engine or "").lower()

    if "IndexTTS2" in msg or "需要参考音频" in msg or "缺少参考音频" in msg:
        if eng and eng not in ("indextts", ""):
            return (
                f"当前引擎是 {eng}，但报错来自 IndexTTS2。\n"
                "请确认 ② 配音 已切换到目标引擎，并重新选择对应音色。\n"
                "若仍出现此提示，请刷新页面后重试。"
            )
        return (
            "IndexTTS2 · 缺少参考音频\n\n"
            "原因：预设音色需要示例参考 wav，克隆音色需先在本页保存。\n\n"
            "处理：\n"
            "1. 预设模式 → 展开「引擎与模型」→ 一键安装 / 运行 scripts/setup/setup_indextts.ps1\n"
            "2. 克隆模式 → 在 ② 配音页上方保存后，选「克隆音色」\n"
            "3. 若不用 IndexTTS2 → 切换到 CosyVoice2 / Piper 等已安装引擎"
        )

    if "未安装" in msg and "setup_" in msg:
        m = re.search(r"setup_\w+\.ps1", msg)
        script = m.group(0) if m else "对应 setup 脚本"
        return f"本地模型未安装\n\n请运行 .\\{script}，或在 ② 配音 面板使用「一键安装」。"

    if ("与当前引擎" in msg) or ("克隆音色属于" in msg and "不匹配" in msg) or (
        "音色" in msg and "不一致" in msg and "属于" in msg
    ):
        return f"音色与引擎不匹配\n\n{msg}"

    if "HeyGem" in msg or "任务不存在" in msg or "data_mount" in msg:
        return f"HeyGem 数字人\n\n{msg}"

    return msg


def format_subprocess_error(exc: subprocess.CalledProcessError, *, engine: str | None = None) -> str:
    output = (exc.output or exc.stderr or "")
    if isinstance(output, bytes):
        output = output.decode("utf-8", errors="replace")
    lines = [
        ln.strip()
        for ln in output.splitlines()
        if ln.strip() and not ln.strip().startswith("@@PROGRESS@@")
    ]
    if lines:
        tail = "\n".join(lines[-10:])
        if "RemoteDisconnected" in tail or "urlopen error" in tail:
            hint = (
                "\n\n常见原因：SadTalker 面部增强（GFPGAN）从 GitHub 下载模型失败，"
                "或 HeyGem Docker 未启动。建议：画质选「快速」、引擎选 SadTalker，"
                "或先启动 HeyGem 再试。"
            )
            return format_user_error(
                f"合成失败（退出码 {exc.returncode}）：\n{tail}{hint}",
                engine=engine,
            )
        return format_user_error(
            f"合成失败（退出码 {exc.returncode}）：\n{tail}",
            engine=engine,
        )
    return format_user_error(f"合成失败（退出码 {exc.returncode}）", engine=engine)


def stage_errors(fn: F) -> F:
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            if isinstance(exc, gr.Error):
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            if isinstance(exc, subprocess.CalledProcessError):
                backend = kwargs.get("backend")
                raise HTTPException(
                    status_code=400,
                    detail=format_subprocess_error(exc, engine=backend),
                ) from exc
            if isinstance(exc, (ValueError, FileNotFoundError)):
                backend = kwargs.get("backend")
                raise HTTPException(
                    status_code=400,
                    detail=format_user_error(str(exc), engine=backend),
                ) from exc
            if isinstance(exc, RuntimeError):
                raise HTTPException(status_code=400, detail=format_user_error(str(exc))) from exc
            raise

    return wrapper  # type: ignore

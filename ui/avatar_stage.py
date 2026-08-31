"""Avatar library UI helpers."""

from __future__ import annotations

import traceback
from pathlib import Path

from ui.gradio_compat import gr

from avatar.catalog import delete_avatar, list_avatars, save_avatar


def avatar_choices() -> list[tuple[str, str]]:
    items = list_avatars()
    if not items:
        return []
    return [(f"{e.name} ({e.source_kind})", e.id) for e in items]


def on_save_avatar(name: str, video_file: str | dict | None) -> tuple:
    media = video_file if isinstance(video_file, str) else (video_file or {}).get("path")
    if not media:
        raise gr.Error("请上传约 10 秒正脸口播参考视频")
    try:
        entry = save_avatar(name or "数字人", media)
        choices = avatar_choices()
        value = entry.id if choices else ""
        return (
            gr.update(choices=choices, value=value),
            f"已注册：{entry.name}\n参考视频={entry.reference_video}",
            "",
        )
    except Exception as e:
        raise gr.Error(f"注册失败: {e}\n\n{traceback.format_exc()}") from e


def on_delete_avatar(avatar_id: str) -> tuple:
    if not avatar_id:
        raise gr.Error("请选择要删除的形象")
    delete_avatar(avatar_id)
    choices = avatar_choices()
    return gr.update(choices=choices, value=choices[0][1] if choices else ""), "已删除"

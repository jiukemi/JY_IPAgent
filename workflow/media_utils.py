"""Media path helpers."""

from __future__ import annotations

from pathlib import Path


def media_path(path: str | dict | None) -> str | None:
    if not path:
        return None
    if isinstance(path, dict):
        path = path.get("path") or path.get("name") or path.get("video")
        if isinstance(path, dict):
            path = path.get("path") or path.get("name")
    if not path:
        return None
    p = Path(str(path))
    return str(p.resolve()) if p.is_file() else None

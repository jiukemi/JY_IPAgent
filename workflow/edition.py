"""Product edition: full (local engines) vs light (cloud placeholders)."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"


def get_edition() -> str:
    env = (os.environ.get("AGENT_EDITION") or "").strip().lower()
    if env in ("full", "light"):
        return env
    try:
        import yaml

        if CONFIG_PATH.is_file():
            cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
            ed = ((cfg.get("app") or {}).get("edition") or "").strip().lower()
            if ed in ("full", "light"):
                return ed
    except Exception:
        pass
    return "full"


def is_light() -> bool:
    return get_edition() == "light"


def is_full() -> bool:
    return get_edition() == "full"


def edition_payload() -> dict:
    ed = get_edition()
    return {
        "edition": ed,
        "label": "全量（本地引擎）" if ed == "full" else "轻量（云端预留）",
        "local_avatar": ed == "full",
        "cloud_avatar_reserved": True,
        "built_with_duix": ed == "full",
    }

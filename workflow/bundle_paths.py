"""Resolve project-relative paths for portable / exe distribution."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def project_root() -> Path:
    """Directory containing server.py (or frozen exe parent)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    env = os.environ.get("AGENT_ROOT", "").strip()
    if env:
        return Path(env).resolve()
    return Path(__file__).resolve().parent.parent


def resolve_path(value: str | Path, root: Path | None = None) -> Path:
    root = root or project_root()
    p = Path(value)
    if p.is_absolute():
        return p.resolve()
    return (root / p).resolve()


def normalize_config_paths(cfg: dict, root: Path | None = None) -> dict:
    """Turn relative paths in config.yaml into absolute paths under project root."""
    root = root or project_root()
    path_keys = (
        "latentsync_dir",
        "sadtalker_dir",
        "indextts_dir",
        "cosyvoice_dir",
        "piper_dir",
        "whisper_dir",
    )
    paths = cfg.get("paths")
    if isinstance(paths, dict):
        for key in path_keys:
            val = paths.get(key)
            if isinstance(val, str) and val:
                paths[key] = str(resolve_path(val, root))
        piper = cfg.get("piper", {})
        if isinstance(piper.get("model"), str) and piper["model"]:
            piper["model"] = str(resolve_path(piper["model"], root))
    return cfg

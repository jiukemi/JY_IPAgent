"""Shared config loader for API and legacy Gradio app."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import yaml


def _resolve_config_path() -> Path:
    """Prefer explicit path, then writable runtime dir (packaged), else project cwd/root."""
    env = (os.environ.get("AGENT_CONFIG") or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    rt = (os.environ.get("AGENT_RUNTIME_DIR") or "").strip()
    if rt:
        return (Path(rt).expanduser().resolve() / "config.yaml")
    # Dev / unpackaged: next to project root when possible
    try:
        from workflow.bundle_paths import project_root

        return (project_root() / "config.yaml").resolve()
    except Exception:
        return Path("config.yaml").resolve()


CONFIG_PATH = _resolve_config_path()


def ensure_config_file() -> Path:
    """Create config.yaml from example on first run (packaged installs ship only the example)."""
    path = CONFIG_PATH
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    candidates = []
    try:
        from workflow.bundle_paths import project_root

        root = project_root()
        candidates.extend(
            [
                root / "config.example.yaml",
                root / "config.yaml",
            ]
        )
    except Exception:
        pass
    candidates.append(Path("config.example.yaml"))
    candidates.append(Path("config.yaml"))
    for src in candidates:
        if src.exists() and src.resolve() != path.resolve():
            shutil.copy2(src, path)
            return path
    raise FileNotFoundError(
        f"缺少配置文件：{path}\n请将 config.example.yaml 复制为 config.yaml 后重试。"
    )


def load_cfg() -> dict:
    ensure_config_file()
    from workflow.bundle_paths import normalize_config_paths, project_root

    cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    return normalize_config_paths(cfg, project_root())

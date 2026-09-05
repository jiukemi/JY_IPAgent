"""Resolve local engine install directories (config + AGENT_RUNTIME_DIR engines/)."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _runtime_engines() -> Path | None:
    rt = (os.environ.get("AGENT_RUNTIME_DIR") or "").strip()
    if not rt:
        return None
    return Path(rt).expanduser().resolve() / "engines"


def resolve_engine_dir(
    cfg: dict,
    *,
    path_key: str,
    default_rel: str,
    runtime_name: str,
    markers: tuple[str, ...] = (),
) -> Path:
    """Prefer an existing install among config / runtime / project tools."""
    cands: list[Path] = []
    configured = Path((cfg.get("paths") or {}).get(path_key, default_rel))
    if not configured.is_absolute():
        configured = ROOT / configured
    cands.append(configured)
    eng = _runtime_engines()
    if eng is not None:
        cands.append(eng / runtime_name)
    cands.append(ROOT / default_rel)

    def score(p: Path) -> int:
        s = 0
        if any((p / m).exists() for m in markers):
            s += 2
        if (p / "venv").is_dir() or (p / ".venv").is_dir():
            s += 1
        if p.is_dir():
            s += 0
        return s

    best = configured
    best_s = -1
    for p in cands:
        sc = score(p)
        if sc > best_s:
            best_s = sc
            best = p
    return best

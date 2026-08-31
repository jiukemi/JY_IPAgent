"""Verify offline bundle: venvs, checkpoints, no missing assets before ship."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml

from workflow.bundle_paths import normalize_config_paths, project_root, resolve_path


def _ok(msg: str) -> None:
    print(f"  OK  {msg}")


def _fail(msg: str) -> None:
    print(f"  FAIL {msg}")


def main() -> int:
    root = project_root()
    print(f"Project root: {root}")
    cfg_path = root / "config.yaml"
    if not cfg_path.exists():
        _fail("config.yaml missing")
        return 1

    cfg = normalize_config_paths(
        yaml.safe_load(cfg_path.read_text(encoding="utf-8")), root
    )
    paths = cfg["paths"]
    errors: list[str] = []

    checks: list[tuple[str, Path]] = [
        ("LatentSync venv", resolve_path(paths["latentsync_dir"], root) / "venv/Scripts/python.exe"),
        (
            "LatentSync ckpt",
            resolve_path(paths["latentsync_dir"], root)
            / cfg["latentsync"]["checkpoint"],
        ),
        ("SadTalker venv", resolve_path(paths["sadtalker_dir"], root) / "venv/Scripts/python.exe"),
        ("SadTalker script", resolve_path(paths["sadtalker_dir"], root) / "inference.py"),
        ("SadTalker checkpoints dir", resolve_path(paths["sadtalker_dir"], root) / "checkpoints"),
    ]

    for label, p in checks:
        if p.exists():
            _ok(f"{label}: {p}")
        else:
            _fail(f"{label}: {p}")
            errors.append(label)

    st_ckpt = resolve_path(paths["sadtalker_dir"], root) / "checkpoints"
    st_patterns = ("*.pth", "*.pth.tar", "*.safetensors", "*.pt")
    has_st = st_ckpt.exists() and any(
        f for pat in st_patterns for f in st_ckpt.rglob(pat)
    )
    if st_ckpt.exists() and not has_st:
        _fail("SadTalker: checkpoints folder empty")
        errors.append("SadTalker weights")
    required_st = (
        "mapping_00109-model.pth.tar",
        "mapping_00229-model.pth.tar",
        "SadTalker_V0.0.2_256.safetensors",
    )
    for name in required_st:
        p = st_ckpt / name
        if not p.is_file() or p.stat().st_size < 50_000_000:
            _fail(f"SadTalker weight missing/incomplete: {name}")
            errors.append(f"SadTalker {name}")

    if errors:
        print(f"\n{len(errors)} issue(s). Run: .\\scripts\\bootstrap_offline.ps1")
        return 1
    print("\nBundle ready for offline / exe packaging.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Download SadTalker assets into tools/ (build machine only)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ST = ROOT / "tools" / "SadTalker"


def py(venv_dir: Path) -> str:
    win = venv_dir / "venv" / "Scripts" / "python.exe"
    return str(win if win.exists() else sys.executable)


def sadtalker_repo() -> None:
    if (ST / "inference.py").exists():
        return
    ST.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--depth", "1", "https://github.com/OpenTalker/SadTalker.git", str(ST)],
        check=True,
        cwd=ROOT,
    )


def sadtalker_assets() -> None:
    sadtalker_repo()
    sp = ST / "scripts" / "download_models.py"
    sh = ST / "scripts" / "download_models.sh"
    if sp.exists():
        subprocess.run([py(ST), str(sp)], cwd=ST, check=True)
    elif sh.exists():
        subprocess.run(["bash", str(sh)], cwd=ST, check=True)
    else:
        raise SystemExit("SadTalker download script not found")


def main() -> int:
    script = ROOT / "scripts" / "download_assets_resumable.py"
    if script.exists():
        return subprocess.call([sys.executable, str(script)])
    print("=== download_lipsync_assets ===")
    sadtalker_assets()
    print("=== complete ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

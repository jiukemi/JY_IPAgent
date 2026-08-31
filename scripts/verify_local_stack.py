"""Quick health check for local 旗博士 stack."""

from __future__ import annotations

import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def ok(msg: str) -> None:
    print(f"  OK   {msg}")


def warn(msg: str) -> None:
    print(f"  WARN {msg}")


def fail(msg: str) -> None:
    print(f"  FAIL {msg}")


def check_path(label: str, p: Path) -> bool:
    if p.exists():
        ok(f"{label}: {p}")
        return True
    fail(f"{label}: {p}")
    return False


def main() -> int:
    print(f"Project: {ROOT}\n")
    errors = 0

    checks = [
        ("Whisper venv", ROOT / "tools/Whisper/.venv/Scripts/python.exe"),
        ("IndexTTS venv", ROOT / "tools/IndexTTS/.venv/Scripts/python.exe"),
        ("SadTalker venv", ROOT / "tools/SadTalker/venv/Scripts/python.exe"),
        ("LatentSync venv", ROOT / "tools/LatentSync/venv/Scripts/python.exe"),
        ("SadTalker ckpt", ROOT / "tools/SadTalker/checkpoints/SadTalker_V0.0.2_256.safetensors"),
        ("LatentSync ckpt", ROOT / "tools/LatentSync/checkpoints/latentsync_unet.pt"),
        ("IndexTTS config", ROOT / "tools/IndexTTS/checkpoints/config.yaml"),
        ("Duix-Avatar", ROOT / "tools/Duix-Avatar/README.md"),
        ("HeyGem mount dir", ROOT / "data/heygem_face2face"),
    ]
    for label, p in checks:
        if not check_path(label, p):
            if "Duix" in label or "HeyGem mount" in label:
                warn(f"{label} — HeyGem 可选，需 Docker")
            elif "Whisper" in label:
                errors += 1
            else:
                pass

    ffmpeg = subprocess.run(["ffmpeg", "-version"], capture_output=True)
    if ffmpeg.returncode == 0:
        ok("ffmpeg in PATH")
    else:
        fail("ffmpeg not found")
        errors += 1

    docker = subprocess.run(["docker", "info"], capture_output=True)
    if docker.returncode == 0:
        ok("Docker daemon running")
        try:
            urllib.request.urlopen("http://127.0.0.1:8383/easy/query?code=probe", timeout=2)
            ok("HeyGem API :8383 reachable")
        except OSError:
            warn("HeyGem API :8383 not up — start Duix-Avatar docker compose")
    else:
        warn("Docker not running — HeyGem 需先启动 Docker Desktop")

    if errors:
        print(f"\n{errors} critical item(s) missing.")
        return 1
    print("\nLocal stack ready (HeyGem optional until Docker up).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

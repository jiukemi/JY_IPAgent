"""Fast hardware probe for local TTS engine compatibility."""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HW_PROBE = ROOT / "tools" / "hw_probe" / "target" / "release" / "hw_probe.exe"

_HW_CACHE: dict | None = None
_HW_CACHE_AT = 0.0
_HW_TTL_SEC = 45.0


def _probe_via_rust() -> dict | None:
    if not HW_PROBE.is_file():
        return None
    try:
        out = subprocess.run(
            [str(HW_PROBE)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
        if out.returncode == 0 and out.stdout.strip():
            return json.loads(out.stdout)
    except (OSError, json.JSONDecodeError, subprocess.TimeoutExpired):
        return None
    return None


def _probe_nvidia_smi() -> list[dict]:
    smi = shutil.which("nvidia-smi")
    if not smi:
        return []
    try:
        out = subprocess.run(
            [
                smi,
                "--query-gpu=name,memory.total,memory.free,driver_version",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
        )
        if out.returncode != 0:
            return []
        gpus: list[dict] = []
        for line in out.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 2:
                continue
            name = parts[0]
            try:
                total_mb = float(parts[1])
            except ValueError:
                total_mb = 0.0
            free_mb = float(parts[2]) if len(parts) > 2 else total_mb
            gpus.append(
                {
                    "name": name,
                    "vram_total_gb": round(total_mb / 1024, 1),
                    "vram_free_gb": round(free_mb / 1024, 1),
                }
            )
        return gpus
    except (OSError, subprocess.TimeoutExpired):
        return []


def _system_ram_gb() -> float:
    try:
        import psutil

        return round(psutil.virtual_memory().total / (1024**3), 1)
    except ImportError:
        pass
    if platform.system() == "Windows":
        try:
            out = subprocess.run(
                ["wmic", "OS", "get", "TotalVisibleMemorySize", "/Value"],
                capture_output=True,
                text=True,
                timeout=4,
                check=False,
            )
            for line in out.stdout.splitlines():
                if line.startswith("TotalVisibleMemorySize="):
                    kb = int(line.split("=", 1)[1].strip())
                    return round(kb / (1024**2), 1)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
    return 0.0


def detect_hardware(*, force: bool = False) -> dict:
    """Return GPU/CPU/RAM summary for UI compatibility hints."""
    global _HW_CACHE, _HW_CACHE_AT
    now = time.monotonic()
    if not force and _HW_CACHE is not None and (now - _HW_CACHE_AT) < _HW_TTL_SEC:
        return _HW_CACHE

    rust = _probe_via_rust()
    if rust:
        _HW_CACHE = rust
        _HW_CACHE_AT = now
        return rust

    gpus = _probe_nvidia_smi()
    ram_gb = _system_ram_gb()
    cpu = platform.processor() or platform.machine()
    max_vram = max((g["vram_total_gb"] for g in gpus), default=0.0)
    result = {
        "source": "python",
        "cpu": cpu,
        "ram_gb": ram_gb,
        "gpus": gpus,
        "cuda_available": bool(gpus),
        "max_vram_gb": max_vram,
        "summary": (
            f"{gpus[0]['name']} · {max_vram}GB 显存 · {ram_gb}GB 内存"
            if gpus
            else f"无 NVIDIA 显卡 · {ram_gb}GB 内存（可用 Piper / Edge 云端）"
        ),
    }
    _HW_CACHE = result
    _HW_CACHE_AT = now
    return result

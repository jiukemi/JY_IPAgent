"""Real-time system resource stats (Rust hw_probe preferred)."""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HW_PROBE = ROOT / "tools" / "hw_probe" / "target" / "release" / "hw_probe.exe"
HW_PROBE_UNIX = ROOT / "tools" / "hw_probe" / "target" / "release" / "hw_probe"


def _probe_bin() -> Path | None:
    if platform.system() == "Windows":
        return HW_PROBE if HW_PROBE.is_file() else None
    return HW_PROBE_UNIX if HW_PROBE_UNIX.is_file() else None


def _run_rust_live() -> dict | None:
    exe = _probe_bin()
    if not exe:
        return None
    try:
        out = subprocess.run(
            [str(exe), "--live"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if out.returncode == 0 and out.stdout.strip():
            return json.loads(out.stdout)
    except (OSError, json.JSONDecodeError, subprocess.TimeoutExpired):
        return None
    return None


def _python_live() -> dict:
    cpu_percent = 0.0
    ram_used_gb = 0.0
    ram_total_gb = 0.0
    ram_percent = 0.0
    try:
        import psutil

        cpu_percent = float(psutil.cpu_percent(interval=0.15))
        mem = psutil.virtual_memory()
        ram_total_gb = round(mem.total / (1024**3), 1)
        ram_used_gb = round(mem.used / (1024**3), 1)
        ram_percent = round(mem.percent, 1)
    except ImportError:
        pass

    gpus: list[dict] = []
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            proc = subprocess.run(
                [
                    smi,
                    "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            if proc.returncode == 0:
                for line in proc.stdout.strip().splitlines():
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) < 4:
                        continue
                    used_mb = float(parts[2])
                    total_mb = float(parts[3])
                    gpus.append(
                        {
                            "name": parts[0],
                            "util_percent": min(100, int(float(parts[1]))),
                            "vram_used_gb": round(used_mb / 1024, 1),
                            "vram_total_gb": round(total_mb / 1024, 1),
                            "vram_percent": round(used_mb / total_mb * 100, 1)
                            if total_mb
                            else 0,
                            "temp_c": int(float(parts[4])) if len(parts) > 4 else None,
                        }
                    )
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass

    return {
        "source": "python",
        "cpu_percent": cpu_percent,
        "ram_used_gb": ram_used_gb,
        "ram_total_gb": ram_total_gb,
        "ram_percent": ram_percent,
        "gpus": gpus,
        "cuda_available": bool(gpus),
        "timestamp_ms": int(time.time() * 1000),
    }


def live_system_stats() -> dict:
    rust = _run_rust_live()
    if rust:
        return rust
    return _python_live()

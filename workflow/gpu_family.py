"""Classify host GPU for HeyGem / Duix image selection (general vs RTX 50-series)."""

from __future__ import annotations

import re
from typing import Any

# Pack / catalog ids used by quark accel + scripts/setup/setup_heygem.ps1
GPU_FAMILY_GENERAL = "general"
GPU_FAMILY_RTX50 = "rtx50"
GPU_FAMILY_ANY = "any"

_HEYGEM_IMAGE = {
    GPU_FAMILY_GENERAL: "guiji2025/duix.avatar",
    GPU_FAMILY_RTX50: "guiji2025/duix.avatar-5090",
}


def heygem_docker_image(family: str) -> str:
    return _HEYGEM_IMAGE.get(family, _HEYGEM_IMAGE[GPU_FAMILY_GENERAL])


def classify_gpu_family(hardware: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return recommended HeyGem image family from detect_hardware()-like dict."""
    if hardware is None:
        from workflow.hardware import detect_hardware

        hardware = detect_hardware()

    gpus = hardware.get("gpus") if isinstance(hardware, dict) else None
    names: list[str] = []
    if isinstance(gpus, list):
        for g in gpus:
            if isinstance(g, dict) and g.get("name"):
                names.append(str(g["name"]))
    summary = str((hardware or {}).get("summary") or "")
    blob = " ".join(names) + " " + summary

    # Match scripts/setup/setup_heygem.ps1: RTX 50 → 5090 variant
    rtx50 = bool(re.search(r"RTX\s*50\d{0,2}", blob, re.I)) or bool(
        re.search(r"GeForce\s+RTX\s*50", blob, re.I)
    )
    family = GPU_FAMILY_RTX50 if rtx50 else GPU_FAMILY_GENERAL
    max_vram = float((hardware or {}).get("max_vram_gb") or 0)
    return {
        "gpu_family": family,
        "gpu_names": names,
        "max_vram_gb": max_vram,
        "heygem_image": heygem_docker_image(family),
        "label": "RTX 50 系（需 5090 镜像）" if family == GPU_FAMILY_RTX50 else "通用显卡（默认镜像）",
        "hint": (
            "本机是 RTX 50 系，请下载「口播引擎 · RTX50」包，不要下通用 HeyGem 镜像。"
            if family == GPU_FAMILY_RTX50
            else "本机非 RTX 50 系，请下载「口播引擎 · 通用」包；RTX50 包在本机可能无法用。"
        ),
        "summary": (hardware or {}).get("summary") or "",
    }


def pack_matches_machine(pack_family: str, machine_family: str) -> tuple[bool, str]:
    """Whether a quark/CDN pack's gpu_family fits this PC. Returns (ok, message)."""
    pf = (pack_family or GPU_FAMILY_ANY).strip().lower() or GPU_FAMILY_ANY
    mf = (machine_family or GPU_FAMILY_GENERAL).strip().lower() or GPU_FAMILY_GENERAL
    if pf in (GPU_FAMILY_ANY, "universal", "all", ""):
        return True, "通用包，与显卡无关"
    if pf == mf:
        return True, "与本机显卡匹配"
    if pf == GPU_FAMILY_RTX50 and mf == GPU_FAMILY_GENERAL:
        return False, "这是 RTX 50 专用包，你的显卡应使用「通用」口播包"
    if pf == GPU_FAMILY_GENERAL and mf == GPU_FAMILY_RTX50:
        return False, "这是通用口播包；你的 RTX 50 系应使用「RTX50」专用包"
    return False, f"包类型 {pf} 与本机 {mf} 不匹配"

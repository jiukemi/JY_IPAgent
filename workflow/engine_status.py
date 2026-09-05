"""Per-engine install / readiness checks for local TTS."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from tts.engine import find_indextts_reference, venv_python
from tts.engine_profiles import ENGINE_PROFILES, engine_profile
from tts.qwen3_tts import verify_qwen3_tts
from workflow.app_config import load_cfg
from workflow.deployment import LOCAL_TTS_ENGINES, step_mode
from workflow.hardware import detect_hardware

ROOT = Path(__file__).resolve().parent.parent

MIN_VRAM_GB: dict[str, float] = {
    "indextts": 8.0,
    "cosyvoice": 6.0,
    "qwen3_local": 4.0,
    "piper": 0.0,
    "edge": 0.0,
    "whisper": 0.0,
    "funasr": 0.0,
    "heygem": 6.0,
}

# Approximate download / install footprint (GB) for UI — not exact disk usage.
PACKAGE_SIZE_GB: dict[str, float] = {
    "indextts": 6.5,
    "cosyvoice": 5.0,
    "qwen3_local": 3.5,
    "piper": 0.3,
    "edge": 0.0,
    "qwen3_tts": 0.0,
    "heygem": 8.0,
    "whisper": 1.5,
    "funasr": 2.0,
}


def _path(*parts: str) -> Path:
    return ROOT.joinpath(*parts)


def _venv_ok(cfg: dict, path_key: str) -> bool:
    import sys

    py = venv_python(cfg, path_key)
    return py != sys.executable and Path(py).is_file()


def _first_existing(*paths: Path) -> Path | None:
    for p in paths:
        if p.is_file() and p.stat().st_size > 100:
            return p
    return None


def _indextts_status(cfg: dict) -> dict:
    from tts.engine import resolve_indextts_install_dir

    install = resolve_indextts_install_dir(cfg)
    it = cfg.get("indextts") or {}
    model_dir = install / it.get("model_dir", "checkpoints")
    missing: list[str] = []
    if not _venv_ok(cfg, "indextts_dir"):
        missing.append("Python 虚拟环境未安装")
    if not (model_dir / "config.yaml").is_file():
        missing.append("模型权重 checkpoints（需运行 scripts/setup/setup_indextts.ps1）")
    ref = find_indextts_reference(cfg)
    preset_missing: list[str] = []
    if not ref:
        preset_missing.append(
            "缺少预设参考音：可一键安装下载内置示例，或在 ② 配音页保存任一条参考音"
            "（支持 wav/mp3/m4a 等，自动转换）"
        )
    installed = _venv_ok(cfg, "indextts_dir") and (model_dir / "config.yaml").is_file()
    ready = installed
    preset_ready = installed and ref is not None
    return {
        "installed": installed,
        "ready": ready,
        "preset_ready": preset_ready,
        "missing": missing + preset_missing,
        "missing_preset": preset_missing,
        "reference_ok": ref is not None,
        "install_dir": str(install),
    }


def _cosyvoice_status(cfg: dict) -> dict:
    install = Path(cfg.get("paths", {}).get("cosyvoice_dir", "tools/CosyVoice/CosyVoice"))
    if not install.is_absolute():
        install = ROOT / install
    model = install / "pretrained_models" / "CosyVoice2-0.5B"
    missing: list[str] = []
    if not _venv_ok(cfg, "cosyvoice_dir"):
        missing.append("Python 虚拟环境未安装")
    if not model.is_dir():
        missing.append("CosyVoice2-0.5B 模型目录")
    # Catch incomplete pip installs (setup used to abort on whisper / torch pin conflicts)
    py = install / "venv" / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python")
    if py.is_file():
        try:
            chk = subprocess.run(
                [str(py), "-c", "import lightning, gdown"],
                capture_output=True,
                text=True,
                timeout=20,
                encoding="utf-8",
                errors="replace",
            )
            if chk.returncode != 0:
                missing.append("依赖不完整（缺 lightning/gdown 等），请重新运行 scripts/setup/setup_cosyvoice.ps1")
        except (OSError, subprocess.TimeoutExpired):
            pass
    ready = len(missing) == 0
    return {"installed": _venv_ok(cfg, "cosyvoice_dir"), "ready": ready, "preset_ready": ready, "missing": missing}


def _piper_status(cfg: dict) -> dict:
    piper_dir = Path(cfg.get("paths", {}).get("piper_dir", "tools/Piper"))
    if not piper_dir.is_absolute():
        piper_dir = ROOT / piper_dir
    model = piper_dir / "zh_CN-huayan-medium.onnx"
    missing: list[str] = []
    if not _venv_ok(cfg, "piper_dir"):
        missing.append("Piper 未安装")
    if not model.is_file():
        missing.append("zh_CN-huayan-medium.onnx 模型文件")
    ready = len(missing) == 0
    return {"installed": _venv_ok(cfg, "piper_dir"), "ready": ready, "preset_ready": ready, "missing": missing}


def _edge_status(_cfg: dict) -> dict:
    try:
        import edge_tts  # noqa: F401

        return {"installed": True, "ready": True, "preset_ready": True, "missing": []}
    except ImportError:
        return {
            "installed": False,
            "ready": False,
            "preset_ready": False,
            "missing": ["edge-tts 未安装（首次在线配音会尝试自动安装，或清除运行时后重开）"],
        }


def _qwen3_status(cfg: dict) -> dict:
    health = verify_qwen3_tts(cfg, ping=False)
    missing = [health.get("message", "未配置 API Key")] if not health.get("ok") else []
    return {"installed": bool(health.get("configured")), "ready": bool(health.get("ok")), "preset_ready": bool(health.get("ok")), "missing": missing}


def _qwen3_local_status(cfg: dict) -> dict:
    from tts.qwen3_local import normalize_size, verify_qwen3_local

    health = verify_qwen3_local(cfg)
    missing = list(health.get("missing") or [])
    size = normalize_size((cfg.get("qwen3_local") or {}).get("size"))
    return {
        "installed": bool(health.get("configured")),
        "ready": bool(health.get("ok")),
        "preset_ready": bool(health.get("preset_ready")),
        "missing": missing,
        "size": size,
        "clone_ready": bool(health.get("clone_ready")),
    }


def _whisper_status(cfg: dict) -> dict:
    install = Path(cfg.get("paths", {}).get("whisper_dir", "tools/Whisper"))
    if not install.is_absolute():
        install = ROOT / install
    py = install / (".venv" if (install / ".venv").is_dir() else "venv") / (
        "Scripts" if os.name == "nt" else "bin"
    ) / ("python.exe" if os.name == "nt" else "python")
    missing: list[str] = []
    if not py.is_file():
        missing.append("Whisper 虚拟环境未安装（运行 scripts/setup/setup_whisper.ps1）")
    else:
        try:
            chk = subprocess.run(
                [str(py), "-c", "import faster_whisper"],
                capture_output=True,
                text=True,
                timeout=20,
                encoding="utf-8",
                errors="replace",
            )
            if chk.returncode != 0:
                missing.append("faster-whisper 未安装")
        except (OSError, subprocess.TimeoutExpired):
            missing.append("无法检测 faster-whisper")
    ready = len(missing) == 0
    return {"installed": py.is_file(), "ready": ready, "preset_ready": ready, "missing": missing}


def _funasr_status(cfg: dict) -> dict:
    from script.extract import _funasr_python

    missing: list[str] = []
    # Fast path: no dedicated FunASR venv → not installed (skip 60s import probe on main Python).
    import sys

    py = _funasr_python(cfg)
    root = Path(cfg.get("paths", {}).get("funasr_dir", "tools/FunASR"))
    if not root.is_absolute():
        root = ROOT / root
    has_venv = any((root / sub).is_dir() for sub in (".venv", "venv"))
    if not has_venv and py == sys.executable:
        missing.append("FunASR 未安装（运行 scripts/setup/setup_funasr.ps1）")
        return {"installed": False, "ready": False, "preset_ready": False, "missing": missing}

    from script.extract import _funasr_available

    ok = False
    try:
        ok = bool(_funasr_available(cfg))
    except Exception:
        ok = False
    if not ok:
        missing.append("FunASR 未安装（运行 scripts/setup/setup_funasr.ps1）")
    return {"installed": ok, "ready": ok, "preset_ready": ok, "missing": missing}


def _heygem_status(cfg: dict) -> dict:
    missing: list[str] = []
    try:
        from avatar.heygem_runtime import heygem_service_status

        st = heygem_service_status(cfg)
        ready = bool(st.get("ok") or st.get("ready") or st.get("running"))
        installed = bool(
            st.get("installed")
            or st.get("component_installed")
            or st.get("duix_present")
            or st.get("docker_available")
            or ready
        )
        if not ready:
            missing.append(
                st.get("hint")
                or st.get("message")
                or "HeyGem 未就绪：请启动 Docker Desktop 后点「一键启动」，或安装口播组件"
            )
        return {
            "installed": installed,
            "ready": ready,
            "preset_ready": ready,
            "missing": missing if not ready else [],
        }
    except Exception as exc:
        missing.append(f"HeyGem 状态检测失败：{exc}")
        return {"installed": False, "ready": False, "preset_ready": False, "missing": missing}


_CHECKERS = {
    "indextts": _indextts_status,
    "cosyvoice": _cosyvoice_status,
    "piper": _piper_status,
    "edge": _edge_status,
    "qwen3_tts": _qwen3_status,
    "qwen3_local": _qwen3_local_status,
    "whisper": _whisper_status,
    "funasr": _funasr_status,
    "heygem": _heygem_status,
}


def check_engine(engine: str, cfg: dict | None = None, hw: dict | None = None) -> dict:
    cfg = cfg or load_cfg()
    eng = (engine or "indextts").lower()
    prof = engine_profile(eng)
    hw = hw if hw is not None else detect_hardware()
    min_vram = MIN_VRAM_GB.get(eng, 0.0)
    qwen_size = ""
    if eng == "qwen3_local":
        from tts.qwen3_local import normalize_size, size_spec

        qwen_size = normalize_size((cfg.get("qwen3_local") or {}).get("size"))
        min_vram = float(size_spec({"qwen3_local": {"size": qwen_size}})["min_vram_gb"])
    max_vram = float(hw.get("max_vram_gb") or 0)
    needs_gpu = min_vram > 0
    compatible = (not needs_gpu) or max_vram >= min_vram or eng in ("edge", "qwen3_tts")

    base = _CHECKERS.get(eng, lambda _c: {"installed": False, "ready": False, "missing": ["未知引擎"]})(cfg)
    missing = list(base.get("missing") or [])
    if needs_gpu and not hw.get("cuda_available"):
        missing.insert(0, f"需要 NVIDIA GPU（推荐 {min_vram:g}GB+ 显存）")
        compatible = False

    usage_rules = _usage_rules(eng)
    package_gb = float(PACKAGE_SIZE_GB.get(eng, 0.0))
    if eng == "qwen3_local":
        package_gb = 5.5 if qwen_size == "1.7B" else 3.5

    host_vram = float(hw.get("max_vram_gb") or 0)
    host_ram = float(hw.get("ram_gb") or 0)
    if compatible:
        match_label = "本机匹配"
        if needs_gpu:
            match_hint = f"本机约 {host_vram:g}GB 显存 ≥ 建议 {min_vram:g}GB"
        else:
            match_hint = "无需独显，CPU/云端即可"
    else:
        match_label = "本机不匹配"
        if needs_gpu and not hw.get("cuda_available"):
            match_hint = "未检测到 NVIDIA GPU"
        else:
            match_hint = f"本机约 {host_vram:g}GB 显存 < 建议 {min_vram:g}GB"

    return {
        "engine": eng,
        "label": prof["label"],
        "hardware": prof["hardware"],
        "summary": prof["summary"],
        "setup_script": prof.get("setup") or ENGINE_PROFILES.get(eng, {}).get("setup"),
        "min_vram_gb": min_vram,
        "compatible": compatible,
        "match_label": match_label,
        "match_hint": match_hint,
        "package_size_gb": package_gb,
        "host_vram_gb": host_vram,
        "host_ram_gb": host_ram,
        "installed": bool(base.get("installed")),
        "ready": bool(base.get("ready")) and compatible,
        "preset_ready": bool(base.get("preset_ready", base.get("ready"))) and compatible,
        "missing": missing,
        "missing_preset": list(base.get("missing_preset") or []),
        "usage_rules": usage_rules,
        "mirrors": {
            "hf": (cfg.get("hf_endpoint") or "https://hf-mirror.com"),
            "pypi": "https://mirrors.aliyun.com/pypi/simple",
            "github": ["https://ghfast.top/", "https://mirror.ghproxy.com/"],
        },
    }


def _usage_rules(engine: str) -> list[str]:
    rules = {
        "indextts": [
            "预设音色可用内置参考音，或 ② 音色库任一条参考音；克隆音色在 ② 保存后选用。",
            "参考音支持常见音频格式，上传后自动转换；切换引擎后音色列表会自动刷新。",
        ],
        "cosyvoice": [
            "CosyVoice2 以克隆为主（须填与录音一致的参考文案）；方言走 Edge 准确口音。",
            "无内置普通话预设音色，请用本页克隆，或改选 IndexTTS / Edge。",
        ],
        "piper": [
            "纯 CPU，仅预设 Neural 音色，不支持克隆；无需 GPU。",
        ],
        "edge": [
            "联网即用，无需安装；不支持克隆。",
        ],
        "qwen3_tts": [
            "需在全局设置配置 DashScope Key；仅云端 API，无本地权重。",
        ],
        "qwen3_local": [
            "需先运行 scripts/setup/setup_qwen3_local.ps1 下载 CustomVoice（内置 9 音色）与 Base（克隆）。",
            "默认 0.6B（约 4GB+ 显存）；设置里可改 1.7B（约 8GB+）。切换引擎后音色列表会刷新。",
            "克隆须填写参考文案（与参考音频内容一致）。",
        ],
    }
    return rules.get(engine, ["切换引擎后请重新选择音色。"])


def scan_local_tts_engines(cfg: dict | None = None) -> list[dict]:
    cfg = cfg or load_cfg()
    mode = step_mode(cfg, "tts")
    engines = sorted(LOCAL_TTS_ENGINES) if mode == "local" else ["qwen3_tts"]
    hw = detect_hardware()
    return [check_engine(e, cfg, hw=hw) for e in engines]


def _pick_recommended_ids(hw: dict) -> dict[str, str]:
    """Per role: best engine id for this host (Rust/nvidia-smi probe)."""
    vram = float(hw.get("max_vram_gb") or 0)
    cuda = bool(hw.get("cuda_available"))
    # ASR: FunASR preferred for Chinese; Whisper always OK as light alt
    asr = "funasr"
    # TTS ladder by VRAM
    if cuda and vram >= 8.0:
        tts = "indextts"
    elif cuda and vram >= 6.0:
        tts = "cosyvoice"
    elif cuda and vram >= 4.0:
        tts = "qwen3_local"
    else:
        tts = "piper"
    # Digital human: only HeyGem in setup panel; mark when VRAM allows try
    avatar = "heygem" if cuda and vram >= 6.0 else ""
    return {"asr": asr, "tts": tts, "avatar": avatar}


def _recommend_reason(engine: str, role: str, hw: dict) -> str:
    vram = float(hw.get("max_vram_gb") or 0)
    if role == "asr":
        return "中文转写优先；本机无需高显存"
    if role == "tts":
        if engine == "indextts":
            return f"本机约 {vram:g}GB 显存，推荐旗舰本地配音"
        if engine == "cosyvoice":
            return f"本机约 {vram:g}GB 显存，推荐克隆向本地配音（比 IndexTTS 略省）"
        if engine == "qwen3_local":
            return f"本机约 {vram:g}GB 显存偏紧，推荐轻量本地 TTS"
        return "低显存/无独显：推荐 Piper（CPU）或改用云端配音"
    if role == "avatar":
        return f"本机约 {vram:g}GB 显存，可尝试口播引擎（建议串行，勿与重型 TTS 同开）"
    return "按本机配置推荐"


def apply_host_recommendations(engines: list[dict], hw: dict) -> tuple[list[dict], dict]:
    picks = _pick_recommended_ids(hw)
    pick_set = {v for v in picks.values() if v}
    role_of = {v: k for k, v in picks.items() if v}
    out: list[dict] = []
    for st in engines:
        eng = st["engine"]
        recommended = eng in pick_set and bool(st.get("compatible"))
        row = dict(st)
        row["recommended"] = recommended
        if recommended:
            role = role_of.get(eng, "")
            row["recommend_role"] = role
            row["recommend_reason"] = _recommend_reason(eng, role, hw)
            row["match_label"] = "推荐安装"
        out.append(row)
    # Recommended first, then compatible, then the rest
    out.sort(
        key=lambda r: (
            0 if r.get("recommended") else 1 if r.get("compatible") else 2,
            r.get("engine") or "",
        )
    )
    plan = {
        "asr": picks.get("asr") or "",
        "tts": picks.get("tts") or "",
        "avatar": picks.get("avatar") or "",
        "summary": "",
        "source": hw.get("source") or "probe",
        "max_vram_gb": float(hw.get("max_vram_gb") or 0),
    }
    labels = {e["engine"]: e["label"] for e in out}
    parts = []
    if plan["asr"]:
        parts.append(f"转写 {labels.get(plan['asr'], plan['asr'])}")
    if plan["tts"]:
        parts.append(f"配音 {labels.get(plan['tts'], plan['tts'])}")
    if plan["avatar"]:
        parts.append(f"口播 {labels.get(plan['avatar'], plan['avatar'])}")
    else:
        parts.append("口播暂不推荐（显存不足时可仅用文案/配音）")
    plan["summary"] = " · ".join(parts)
    return out, plan


def scan_setup_engines(cfg: dict | None = None) -> list[dict]:
    """Engines shown in Settings → 本机环境 install panel (TTS + ASR + HeyGem)."""
    cfg = cfg or load_cfg()
    ids = [
        "funasr",
        "whisper",
        "indextts",
        "cosyvoice",
        "qwen3_local",
        "piper",
        "heygem",
    ]
    hw = detect_hardware()
    raw = [check_engine(e, cfg, hw=hw) for e in ids]
    engines, _plan = apply_host_recommendations(raw, hw)
    return engines


def scan_setup_bundle(cfg: dict | None = None) -> dict:
    """Hardware + engines + recommend plan for Settings UI."""
    cfg = cfg or load_cfg()
    hw = detect_hardware()
    ids = [
        "funasr",
        "whisper",
        "indextts",
        "cosyvoice",
        "qwen3_local",
        "piper",
        "heygem",
    ]
    raw = [check_engine(e, cfg, hw=hw) for e in ids]
    engines, plan = apply_host_recommendations(raw, hw)
    return {"hardware": hw, "engines": engines, "recommend": plan}


def engine_health_status(cfg: dict, engine: str) -> dict[str, object]:
    st = check_engine(engine, cfg)
    ok = bool(st["ready"])
    preset_ready = bool(st.get("preset_ready", ok))
    if ok:
        msg = "就绪" if preset_ready else "可克隆合成；预设音色需补充参考音"
    else:
        msg = "；".join(st["missing"][:3]) if st["missing"] else "未就绪"
    return {
        "ok": ok,
        "preset_ready": preset_ready,
        "configured": st["installed"] or engine in ("edge", "qwen3_tts"),
        "reachable": None,
        "message": msg,
        "status": st,
    }

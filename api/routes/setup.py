"""Local model setup: status probe and one-click install."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from tts.engine_profiles import ENGINE_PROFILES
from workflow.app_config import CONFIG_PATH, load_cfg
from workflow.engine_status import (
    check_engine,
    scan_local_tts_engines,
    scan_setup_bundle,
    scan_setup_engines,
)
from workflow.hardware import detect_hardware

router = APIRouter(prefix="/api/setup", tags=["setup"])

ROOT = Path(__file__).resolve().parent.parent.parent
SETUP_DIR = ROOT / "scripts" / "setup"

ALLOWED_SCRIPTS = {
    eng: spec["setup"]
    for eng, spec in ENGINE_PROFILES.items()
    if spec.get("setup")
}
ALLOWED_SCRIPTS["heygem"] = "setup_heygem.ps1"
ALLOWED_SCRIPTS["whisper"] = "setup_whisper.ps1"
ALLOWED_SCRIPTS["funasr"] = "setup_funasr.ps1"
ALLOWED_SCRIPTS["local_whisper"] = "setup_whisper.ps1"
# Optional first-boot skips — one-click install when cover / browser needs them
ALLOWED_SCRIPTS["rembg"] = "setup_rembg.ps1"
ALLOWED_SCRIPTS["playwright"] = "setup_playwright.ps1"

OPTIONAL_INSTALL = frozenset({"rembg", "playwright"})


@router.get("/hardware")
def hardware_info() -> dict:
    return detect_hardware()


@router.get("/engines")
def engines_status(engine: str | None = None) -> dict:
    cfg = load_cfg()
    if engine:
        hw = detect_hardware()
        return {"hardware": hw, "engine": check_engine(engine, cfg)}
    # Prefer full setup list (ASR + TTS + HeyGem) + host recommend plan
    return scan_setup_bundle(cfg)


@router.post("/install/stream")
async def install_stream(engine: str = Query(...)):
    eng = (engine or "").lower()
    script = ALLOWED_SCRIPTS.get(eng)
    if not script:
        raise HTTPException(status_code=400, detail=f"引擎 {eng} 不支持一键安装")

    cfg = load_cfg()
    if eng not in OPTIONAL_INSTALL:
        st = check_engine(eng, cfg)
        if not st.get("compatible", True):
            min_v = st.get("min_vram_gb") or 0
            missing = st.get("missing") or []
            why = "；".join(str(m) for m in missing[:3]) if missing else f"本机显存不足（建议 ≥ {min_v:g}GB）"
            raise HTTPException(
                status_code=400,
                detail=f"本机配置不支持「{st.get('label') or eng}」：{why}。请改用云端配音（Qwen3-TTS）或 Piper 等轻量引擎。",
            )

    script_path = (SETUP_DIR / script).resolve()
    if not script_path.is_file() or script_path.parent != SETUP_DIR.resolve():
        raise HTTPException(status_code=400, detail="安装脚本不存在")

    async def events():
        yield f"data: {json.dumps({'type': 'start', 'engine': eng, 'p': 0.02}, ensure_ascii=False)}\n\n"
        ps_cmd = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
        ]
        if eng == "indextts":
            import os

            from tts.engine import resolve_indextts_install_dir

            install = resolve_indextts_install_dir(cfg)
            rt = (os.environ.get("AGENT_RUNTIME_DIR") or "").strip()
            if rt:
                from pathlib import Path as _P

                install = _P(rt).expanduser().resolve() / "engines" / "IndexTTS"
            ps_cmd.extend(["-Root", str(ROOT), "-InstallDir", str(install)])
            yield f"data: {json.dumps({'type': 'log', 'line': f'InstallDir={install}', 'p': 0.03}, ensure_ascii=False)}\n\n"

        proc = await asyncio.create_subprocess_exec(
            *ps_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(ROOT),
        )
        assert proc.stdout is not None
        progress = 0.05
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").rstrip()
            if text:
                low = text.lower()
                if any(k in low for k in ("download", "下载", "fetch", "pull")):
                    progress = max(progress, 0.35)
                elif any(k in low for k in ("install", "pip", "wheel", "解压")):
                    progress = max(progress, 0.55)
                elif any(k in low for k in ("complete", "done", "成功", "finished", "rembg_ok", "playwright_ok")):
                    progress = max(progress, 0.88)
                else:
                    progress = min(progress + 0.015, 0.92)
                yield f"data: {json.dumps({'type': 'log', 'line': text, 'p': progress}, ensure_ascii=False)}\n\n"
        code = await proc.wait()
        if eng in OPTIONAL_INSTALL:
            ready = code == 0
            missing = [] if ready else [f"{eng} 安装失败（exit={code}）"]
        else:
            st = check_engine(eng, load_cfg())
            ready = bool(st.get("ready"))
            missing = list(st.get("missing") or [])
        yield f"data: {json.dumps({'type': 'done', 'exit_code': code, 'ready': ready, 'missing': missing, 'p': 1.0}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

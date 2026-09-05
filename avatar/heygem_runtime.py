"""HeyGem / Duix local runtime helpers (component-first; Docker optional legacy)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from avatar.heygem import health_check
from workflow.components import is_installed
from workflow.hardware import detect_hardware
from workflow.runtime_mode import strict_user

ROOT = Path(__file__).resolve().parent.parent
DUX_DIR = ROOT / "tools" / "Duix-Avatar"
DEPLOY_DIR = DUX_DIR / "deploy"
COMPONENT_ID = "heygem-runtime"

_DEV_DOCKER_NOTE = "仅开发兜底"


def docker_cli_present() -> bool:
    return bool(shutil.which("docker"))


def docker_available() -> bool:
    if not docker_cli_present():
        return False
    try:
        r = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=15,
            check=False,
        )
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def duix_present() -> bool:
    return DEPLOY_DIR.is_dir() and any(DEPLOY_DIR.glob("docker-compose*.yml"))


def component_present() -> bool:
    return is_installed(COMPONENT_ID)


def heygem_service_status(cfg: dict) -> dict:
    ready = health_check(cfg, timeout=2.0)
    api = (cfg.get("heygem") or {}).get("video_api", "http://127.0.0.1:8383")
    docker_cli = docker_cli_present()
    docker_ok = docker_available()
    present = duix_present()
    comp = component_present()
    # Files / compose / component count as "downloaded"; ready still needs 8383 up.
    installed = bool(comp or present or ready)
    is_strict = strict_user()
    hw = detect_hardware()
    max_vram = float(hw.get("max_vram_gb") or 0)
    cuda_ok = bool(hw.get("cuda_available"))
    # 口播数字人通常需要独立 NVIDIA 显卡；无 GPU 时明确提示
    min_vram_gb = 6.0
    gpu_ok = cuda_ok and max_vram >= min_vram_gb
    if not cuda_ok:
        gpu_hint = "未检测到 NVIDIA GPU。口播引擎需要独显，本机无法运行；可用文案/配音等其他功能。"
    elif max_vram < min_vram_gb:
        gpu_hint = (
            f"当前显存约 {max_vram:g}GB，口播引擎建议 ≥ {min_vram_gb:g}GB。"
            "低配机可能很慢或失败，建议换更高配电脑，或仅用云端配音流程。"
        )
    else:
        gpu_hint = ""

    if is_strict:
        if ready:
            hint = "口播引擎服务已就绪，可直接生成视频。"
            state = "ready"
        elif comp:
            hint = "口播引擎组件已安装但服务未运行。请点「一键启动」（无需 Docker Desktop）。"
            state = "component_stopped"
        else:
            hint = (
                "口播引擎未安装。请到设置 → 特殊引擎安装 →「口播引擎安装向导」："
                "安装 Docker Desktop → 用夸克加速包导入镜像并启动。"
            )
            state = "need_component"
        can_start = bool(ready or comp) and (cuda_ok or ready)
        runtime = "component" if comp else "none"
    else:
        if ready:
            hint = "口播引擎服务已就绪，可直接生成视频。"
            state = "ready"
        elif comp:
            hint = "口播引擎组件已安装但服务未运行。请点「一键启动」（无需 Docker Desktop）。"
            state = "component_stopped"
        elif docker_ok and present:
            hint = (
                "本机已有 Duix 部署目录，Docker 可用。请点「一键启动口播引擎」拉起 8383。"
                f"（{_DEV_DOCKER_NOTE}）"
            )
            state = "stopped"
        elif present and docker_cli and not docker_ok:
            hint = (
                "本机已有 Duix 部署目录（算已下载），但 Docker Desktop 引擎未就绪："
                "客户端存在却无法执行 docker info。"
                "请打开 Docker Desktop，等到状态正常后再点「一键启动」或运行 .\\scripts\\setup\\setup_heygem.ps1。"
            )
            state = "docker_engine_down"
        elif present and not docker_cli:
            hint = (
                "本机已有 Duix 部署目录，但未检测到 Docker。"
                "请安装并启动 Docker Desktop 后再启动口播引擎。"
            )
            state = "need_docker"
        elif docker_ok and not present:
            hint = (
                "Docker 可用但尚未克隆 Duix-Avatar。"
                "有外网/梯子时可在「本机环境」安装 HeyGem，或运行 .\\scripts\\setup\\setup_heygem.ps1；"
                "无 Docker Hub 时请用设置 → 口播引擎安装向导 + 夸克加速包。"
                f"（{_DEV_DOCKER_NOTE}）"
            )
            state = "not_installed"
        else:
            hint = (
                "口播引擎未就绪。请到设置 → 特殊引擎安装 →「口播引擎安装向导」："
                "① 安装并启动 Docker Desktop  ② 夸克加速包导入镜像  ③ 一键启动。"
                "有梯子能访问 GitHub/Docker Hub 时，也可在「本机环境 · GPU 与模型」里直接安装 HeyGem（仍需 Docker）。"
            )
            state = "need_setup"
        # 无独显时不允许启动；显存偏低仍可试，但前端会强提示
        can_start = bool(ready or comp or docker_ok) and (cuda_ok or ready)
        runtime = "component" if comp else ("docker" if docker_ok else ("duix_files" if present else "none"))

    if gpu_hint and not ready:
        hint = f"{gpu_hint} {hint}".strip()

    return {
        "ready": ready,
        "state": state,
        "api": api,
        "docker_available": docker_ok,
        "docker_cli": docker_cli,
        "duix_present": present,
        "component_installed": comp,
        "installed": installed,
        "can_start": can_start,
        "deploy_dir": str(DEPLOY_DIR),
        "hint": hint,
        "runtime": runtime,
        "strict_user": is_strict,
        "gpu_ok": gpu_ok,
        "cuda_available": cuda_ok,
        "max_vram_gb": max_vram,
        "min_vram_gb": min_vram_gb,
        "gpu_hint": gpu_hint,
        "note": (
            "「已下载」≠「已就绪」：就绪需本机 8383 服务响应。"
            "当前迷你安装包主路径：Docker Desktop + 夸克加速包（或有梯子时 docker pull）。"
            "Built with DUIX.COM。"
        ),
    }


def compose_file() -> Path | None:
    if not DEPLOY_DIR.is_dir():
        return None
    primary = DEPLOY_DIR / "docker-compose.yml"
    if primary.is_file():
        return primary
    lite = DEPLOY_DIR / "docker-compose-lite.yml"
    return lite if lite.is_file() else None


def start_heygem_stream_lines() -> list[str]:
    """Yield command argv for streaming start.

    P1: prefer component runtime launcher when installed.
    Legacy: scripts/setup/setup_heygem.ps1 / docker compose (disabled in strict user mode).
    """
    if component_present():
        launcher = ROOT / "data" / "components" / COMPONENT_ID / "start.ps1"
        if launcher.is_file():
            return [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(launcher),
            ]
        # Marker without launcher yet — no-op command list signals UI
        return []

    if strict_user():
        return []

    script = ROOT / "scripts" / "setup" / "setup_heygem.ps1"
    if script.is_file():
        return [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
        ]
    cf = compose_file()
    if cf:
        return ["docker", "compose", "-f", str(cf), "up", "-d"]
    return []


def stop_heygem() -> tuple[bool, str]:
    if component_present():
        stopper = ROOT / "data" / "components" / COMPONENT_ID / "stop.ps1"
        if stopper.is_file():
            try:
                subprocess.run(
                    [
                        "powershell",
                        "-NoProfile",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        str(stopper),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=120,
                    check=True,
                )
                return True, "口播引擎已停止。"
            except subprocess.CalledProcessError as exc:
                err = (exc.stderr or exc.stdout or str(exc)).strip()
                return False, err or "停止失败"

    if strict_user():
        return (
            False,
            "未安装口播引擎，无法停止。请到设置 → 特殊引擎安装 →「口播引擎安装向导」完成安装。",
        )

    cf = compose_file()
    if not cf:
        return False, "未找到可停止的口播引擎（组件或遗留 Docker 部署）。"
    if not docker_available():
        return False, "遗留 Docker 部署需要 Docker 在运行才能停止容器。"
    try:
        subprocess.run(
            ["docker", "compose", "-f", str(cf), "down"],
            cwd=str(DEPLOY_DIR),
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        )
        return True, "口播引擎（Docker 遗留）已停止。"
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or exc.stdout or str(exc)).strip()
        return False, err or "停止失败"

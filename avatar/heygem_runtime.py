"""HeyGem / Duix local runtime helpers (component-first; Docker + quark for mini)."""

from __future__ import annotations

import os
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


def _docker_image_present(image: str) -> bool:
    if not docker_cli_present():
        return False
    try:
        r = subprocess.run(
            ["docker", "image", "inspect", image],
            capture_output=True,
            timeout=30,
            check=False,
        )
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def resolve_heygem_docker_image() -> str | None:
    """Pick a loaded guiji2025/duix.avatar* image (prefer GPU family match)."""
    from workflow.gpu_family import classify_gpu_family, heygem_docker_image

    machine = classify_gpu_family()
    fam = str(machine.get("gpu_family") or "general")
    prefer = heygem_docker_image(fam)
    if _docker_image_present(prefer):
        return prefer
    for alt_fam in ("general", "rtx50"):
        img = heygem_docker_image(alt_fam)
        if img != prefer and _docker_image_present(img):
            return img
    try:
        r = subprocess.run(
            [
                "docker",
                "images",
                "--format",
                "{{.Repository}}:{{.Tag}}",
                "guiji2025/duix.avatar",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if r.returncode == 0:
            for line in (r.stdout or "").splitlines():
                name = line.strip()
                if name and not name.endswith(":<none>"):
                    if "5090" in name:
                        return "guiji2025/duix.avatar-5090"
                    return "guiji2025/duix.avatar"
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def heygem_docker_image_ready() -> bool:
    return resolve_heygem_docker_image() is not None


def _runtime_root() -> Path:
    rt = (os.environ.get("AGENT_RUNTIME_DIR") or "").strip()
    if rt:
        return Path(rt).expanduser().resolve()
    return (ROOT / "data" / "runtime").resolve()


def app_packaged_hint() -> bool:
    return strict_user() or bool((os.environ.get("AGENT_RUNTIME_DIR") or "").strip())


def resolve_heygem_data_mount() -> Path:
    """Writable host mount for /code/data — prefer config, else runtime dir."""
    mount: Path | None = None
    try:
        from workflow.app_config import load_cfg

        raw = ((load_cfg().get("heygem") or {}).get("data_mount_host") or "").strip()
        if raw:
            p = Path(raw).expanduser()
            if not p.is_absolute():
                p = (ROOT / p).resolve()
            else:
                p = p.resolve()
            # Seeded example E:/agent/... is useless on other PCs
            norm = str(p).replace("\\", "/").lower()
            if norm.startswith("e:/agent/") and app_packaged_hint() and not p.exists():
                mount = None
            else:
                mount = p
    except Exception:
        mount = None
    if mount is None:
        mount = _runtime_root() / "heygem_face2face"
    ensure_heygem_data_layout(mount)
    return mount


def ensure_heygem_data_layout(mount: Path | None = None) -> Path:
    """Create host dirs the Duix container expects under /code/data (result/temp/…)."""
    root = Path(mount) if mount is not None else resolve_heygem_data_mount()
    root.mkdir(parents=True, exist_ok=True)
    for sub in ("result", "temp", "tasks", "model"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def _persist_data_mount_host(mount: Path) -> None:
    """Keep config.yaml heygem.data_mount_host in sync with the compose volume."""
    try:
        import yaml

        from workflow.app_config import CONFIG_PATH, load_cfg, repair_yaml_windows_path_quotes

        cfg = load_cfg()
        heygem = dict(cfg.get("heygem") or {})
        abs_mount = str(mount.resolve()).replace("\\", "/")
        cur = str(heygem.get("data_mount_host") or "").strip().replace("\\", "/").rstrip("/")
        if cur.lower() == abs_mount.lower().rstrip("/"):
            return
        heygem["data_mount_host"] = abs_mount
        heygem.setdefault("data_mount_container", "/code/data")
        cfg["heygem"] = heygem
        text = yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False)
        text = repair_yaml_windows_path_quotes(text)
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(text, encoding="utf-8")
    except Exception:
        pass


def _mount_for_compose(mount: Path) -> str:
    """Windows host path → compose volume left-hand side (e.g. d:/foo/bar)."""
    s = str(mount.resolve())
    if len(s) >= 2 and s[1] == ":":
        drive = s[0].lower()
        rest = s[2:].replace("\\", "/").lstrip("/")
        return f"{drive}:/{rest}"
    return s.replace("\\", "/")


def ensure_heygem_docker_compose(image: str | None = None) -> Path | None:
    """Write a minimal lite compose under runtime (no Duix-Avatar git clone needed)."""
    img = image or resolve_heygem_docker_image()
    if not img:
        return None
    mount = resolve_heygem_data_mount()
    ensure_heygem_data_layout(mount)
    _persist_data_mount_host(mount)
    deploy = _runtime_root() / "heygem" / "deploy"
    deploy.mkdir(parents=True, exist_ok=True)
    compose = deploy / "docker-compose.yml"
    mount_docker = _mount_for_compose(mount)
    body = f"""networks:
  ai_network:
    driver: bridge

services:
  duix-avatar-gen-video:
    image: {img}
    container_name: duix-avatar-gen-video
    restart: always
    runtime: nvidia
    privileged: true
    volumes:
      - {mount_docker}:/code/data
    environment:
      - PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:512
    deploy:
      resources:
        reservations:
          devices:
            - capabilities: [gpu]
    shm_size: '8g'
    ports:
      - '8383:8383'
    command: python /code/app_local.py
    networks:
      - ai_network
"""
    compose.write_text(body, encoding="utf-8")
    return compose


def heygem_service_status(cfg: dict) -> dict:
    ready = health_check(cfg, timeout=2.0)
    api = (cfg.get("heygem") or {}).get("video_api", "http://127.0.0.1:8383")
    docker_cli = docker_cli_present()
    docker_ok = docker_available()
    present = duix_present()
    comp = component_present()
    image_ok = heygem_docker_image_ready() if docker_cli else False
    # Files / compose / component / loaded image count as "downloaded"; ready still needs 8383 up.
    installed = bool(comp or present or ready or image_ok)
    is_strict = strict_user()
    hw = detect_hardware()
    max_vram = float(hw.get("max_vram_gb") or 0)
    cuda_ok = bool(hw.get("cuda_available"))
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
        elif docker_ok and image_ok:
            hint = (
                "Docker 与口播镜像已就绪。请点「一键启动口播引擎」拉起 8383 "
                "（迷你包：Docker + 夸克加速包，无需再装免 Docker 组件）。"
            )
            state = "image_ready"
        elif docker_ok and not image_ok:
            hint = (
                "Docker 已运行，但尚未加载口播镜像。"
                "请在向导第③步安装夸克加速包，第④步点「加载镜像」。"
            )
            state = "need_image"
        elif image_ok and not docker_ok:
            hint = (
                "口播镜像已在本地，但 Docker Desktop 未就绪。"
                "请打开 Docker，跳过登录，等到托盘就绪后再点「一键启动」。"
            )
            state = "docker_engine_down"
        else:
            hint = (
                "口播引擎未安装。请到设置 → 特殊引擎安装 →「口播引擎安装向导」："
                "安装 Docker Desktop → 用夸克加速包导入镜像并启动。"
            )
            state = "need_component"
        can_start = bool(ready or comp or (docker_ok and image_ok)) and (cuda_ok or ready)
        runtime = (
            "component"
            if comp
            else ("docker_image" if image_ok else ("docker" if docker_ok else "none"))
        )
    else:
        if ready:
            hint = "口播引擎服务已就绪，可直接生成视频。"
            state = "ready"
        elif comp:
            hint = "口播引擎组件已安装但服务未运行。请点「一键启动」（无需 Docker Desktop）。"
            state = "component_stopped"
        elif docker_ok and (present or image_ok):
            hint = (
                "本机 Docker 可用且镜像/部署已就绪。请点「一键启动口播引擎」拉起 8383。"
                f"（{_DEV_DOCKER_NOTE}）"
            )
            state = "stopped" if present else "image_ready"
        elif present and docker_cli and not docker_ok:
            hint = (
                "本机已有 Duix 部署目录（算已下载），但 Docker Desktop 引擎未就绪："
                "客户端存在却无法执行 docker info（验收只看这个，不必注册 Docker Hub）。"
                "请打开 Docker Desktop，跳过登录窗，等到托盘就绪后再点「一键启动」"
                "或运行 .\\scripts\\setup\\setup_heygem.ps1。"
            )
            state = "docker_engine_down"
        elif present and not docker_cli:
            hint = (
                "本机已有 Duix 部署目录，但未检测到 Docker。"
                "请安装并启动 Docker Desktop 后再启动口播引擎。"
            )
            state = "need_docker"
        elif docker_ok and not present and not image_ok:
            hint = (
                "Docker 可用但尚未克隆 Duix-Avatar / 未加载镜像。"
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
        can_start = bool(ready or comp or docker_ok) and (cuda_ok or ready)
        runtime = (
            "component"
            if comp
            else ("docker" if docker_ok else ("duix_files" if present else "none"))
        )

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
        "image_loaded": image_ok,
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
    Mini / strict: Docker + already-loaded quark image (no Duix git clone).
    Legacy: scripts/setup/setup_heygem.ps1 / docker compose.
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
        # Marker without launcher — fall through to Docker if image is ready

    # Mini installer path: image already docker-load'd via 夸克加速包
    if docker_available():
        img = resolve_heygem_docker_image()
        if img:
            compose = ensure_heygem_docker_compose(img)
            if compose and compose.is_file():
                # Always recreate so volume matches current data_mount (升级后旧容器挂错盘会报 param.json)
                return [
                    "docker",
                    "compose",
                    "-f",
                    str(compose),
                    "up",
                    "-d",
                    "--force-recreate",
                    "--remove-orphans",
                ]
        script_docker = ROOT / "scripts" / "setup" / "start_heygem_docker.ps1"
        if script_docker.is_file() and (img or duix_present()):
            return [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script_docker),
            ]

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

    if docker_available():
        compose = _runtime_root() / "heygem" / "deploy" / "docker-compose.yml"
        try:
            if compose.is_file():
                subprocess.run(
                    ["docker", "compose", "-f", str(compose), "down"],
                    capture_output=True,
                    text=True,
                    timeout=120,
                    check=False,
                )
            subprocess.run(
                ["docker", "rm", "-f", "duix-avatar-gen-video"],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            if not strict_user():
                cf = compose_file()
                if cf:
                    subprocess.run(
                        ["docker", "compose", "-f", str(cf), "down"],
                        cwd=str(DEPLOY_DIR),
                        capture_output=True,
                        text=True,
                        timeout=120,
                        check=False,
                    )
            return True, "口播引擎（Docker）已停止。"
        except OSError as exc:
            return False, str(exc)

    if strict_user():
        return (
            False,
            "未安装口播引擎，无法停止。请到设置 → 特殊引擎安装 →「口播引擎安装向导」完成安装。",
        )

    cf = compose_file()
    if not cf:
        return False, "未找到可停止的口播引擎（组件或遗留 Docker 部署）。"
    return False, "遗留 Docker 部署需要 Docker 在运行才能停止容器。"

"""HeyGem install wizard: Docker check, quark tar load, status for UI steps."""

from __future__ import annotations

import os
import subprocess
import webbrowser
from pathlib import Path
from typing import Any

from avatar.heygem_runtime import (
    docker_available,
    docker_cli_present,
    heygem_service_status,
)
from workflow.app_config import load_cfg
from workflow.gpu_family import classify_gpu_family
from workflow.quark_accel import catalog_for_ui, runtime_root

ROOT = Path(__file__).resolve().parent.parent
DOCKER_INSTALLER_URL = (
    "https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe"
)
DOCKER_PRODUCT_URL = "https://www.docker.com/products/docker-desktop/"

TAR_BY_FAMILY = {
    "general": "duix.avatar.tar",
    "rtx50": "duix.avatar-5090.tar",
}
IMAGE_BY_FAMILY = {
    "general": "guiji2025/duix.avatar",
    "rtx50": "guiji2025/duix.avatar-5090",
}


def heygem_runtime_dir() -> Path:
    return runtime_root() / "heygem"


def find_heygem_tars() -> list[dict[str, Any]]:
    d = heygem_runtime_dir()
    out: list[dict[str, Any]] = []
    if not d.is_dir():
        return out
    for family, name in TAR_BY_FAMILY.items():
        p = d / name
        if p.is_file():
            out.append(
                {
                    "family": family,
                    "path": str(p),
                    "name": name,
                    "bytes": p.stat().st_size,
                    "image": IMAGE_BY_FAMILY[family],
                }
            )
    return out


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


def docker_load_tar(tar_path: Path | None = None, *, family: str | None = None) -> dict[str, Any]:
    """Load HeyGem image tar into local Docker (needs Docker Desktop running)."""
    if not docker_available():
        return {
            "ok": False,
            "message": "Docker Desktop 未运行。请先安装并打开 Docker，等到引擎就绪后再加载镜像。",
            "need_docker": True,
        }

    machine = classify_gpu_family()
    prefer = (family or machine.get("gpu_family") or "general").strip().lower()
    tars = find_heygem_tars()
    if tar_path is None:
        match = next((t for t in tars if t["family"] == prefer), None)
        if match is None and tars:
            match = tars[0]
        if match is None:
            return {
                "ok": False,
                "message": "未找到口播镜像 tar。请先在向导中安装对应夸克加速包（会解压到 data/runtime/heygem/）。",
                "need_pack": True,
                "expected": TAR_BY_FAMILY.get(prefer, TAR_BY_FAMILY["general"]),
            }
        tar_path = Path(match["path"])
        image = str(match["image"])
        used_family = str(match["family"])
    else:
        tar_path = Path(tar_path)
        used_family = prefer
        image = IMAGE_BY_FAMILY.get(prefer, IMAGE_BY_FAMILY["general"])
        for t in tars:
            if Path(t["path"]).resolve() == tar_path.resolve():
                image = str(t["image"])
                used_family = str(t["family"])
                break

    if not tar_path.is_file():
        return {"ok": False, "message": f"镜像文件不存在：{tar_path}"}

    if _docker_image_present(image):
        return {
            "ok": True,
            "already": True,
            "message": f"镜像已在本地：{image}，无需重复 load。",
            "image": image,
            "family": used_family,
            "tar": str(tar_path),
        }

    try:
        proc = subprocess.run(
            ["docker", "load", "-i", str(tar_path)],
            capture_output=True,
            text=True,
            timeout=3600,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "docker load 超时（大镜像可能需更长时间，请重试）。"}
    except OSError as exc:
        return {"ok": False, "message": f"无法执行 docker load：{exc}"}

    out = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    if proc.returncode != 0:
        return {
            "ok": False,
            "message": f"docker load 失败（退出码 {proc.returncode}）。\n{out[-800:]}",
            "log": out[-2000:],
        }

    present = _docker_image_present(image)
    return {
        "ok": True,
        "already": False,
        "message": f"已加载镜像：{image}" if present else f"docker load 完成。\n{out[-400:]}",
        "image": image,
        "family": used_family,
        "tar": str(tar_path),
        "image_present": present,
        "log": out[-1500:],
    }


def open_docker_desktop_download() -> dict[str, Any]:
    """Open Docker Desktop download page in the default browser."""
    url = DOCKER_PRODUCT_URL
    try:
        webbrowser.open(url)
        opened = True
    except Exception:
        opened = False
    return {
        "ok": True,
        "opened": opened,
        "product_url": DOCKER_PRODUCT_URL,
        "installer_url": DOCKER_INSTALLER_URL,
        "message": "已尝试打开 Docker Desktop 下载页。安装需管理员权限，完成后可能要重启，再回到本向导点「重新检测」。",
    }


def try_launch_docker_desktop() -> dict[str, Any]:
    """Best-effort start Docker Desktop on Windows."""
    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "Docker"
        / "Docker"
        / "Docker Desktop.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "Docker"
        / "Docker"
        / "Docker Desktop.exe",
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Docker"
        / "Docker Desktop.exe",
    ]
    exe = next((p for p in candidates if p.is_file()), None)
    if exe is None:
        return {
            "ok": False,
            "message": "未找到 Docker Desktop 安装路径。请先下载安装，或从开始菜单手动打开。",
            "need_install": True,
            **open_docker_desktop_download(),
        }
    try:
        subprocess.Popen(
            [str(exe)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return {
            "ok": True,
            "message": f"已尝试启动：{exe.name}。请等待托盘图标就绪（约 30–90 秒），再点「重新检测」。",
            "path": str(exe),
        }
    except OSError as exc:
        return {"ok": False, "message": f"启动失败：{exc}"}


def wizard_status() -> dict[str, Any]:
    """Aggregate state for the 4-step install wizard."""
    cfg = load_cfg()
    st = heygem_service_status(cfg)
    machine = classify_gpu_family()
    catalog = catalog_for_ui()
    family = str(machine.get("gpu_family") or "general")
    packs = catalog.get("packs") or []
    recommended = next(
        (
            p
            for p in packs
            if isinstance(p, dict)
            and p.get("pack_kind") == "gpu"
            and p.get("gpu_family") == family
        ),
        None,
    )
    tars = find_heygem_tars()
    prefer_tar = next((t for t in tars if t["family"] == family), None)
    image = IMAGE_BY_FAMILY.get(family, IMAGE_BY_FAMILY["general"])
    image_ok = _docker_image_present(image) if docker_cli_present() else False

    docker_cli = docker_cli_present()
    docker_ok = docker_available()
    step2_done = docker_ok
    step3_done = prefer_tar is not None or any(t["family"] == family for t in tars)
    # Also accept installed marker for matching pack
    installed = catalog.get("installed") or {}
    if isinstance(installed, dict) and installed.get("pack_kind") == "gpu":
        if installed.get("gpu_family") == family or installed.get("forced"):
            step3_done = step3_done or bool(tars)
    step4_done = bool(st.get("ready"))
    step4_partial = image_ok and not step4_done
    # Already serving 8383 → treat prior steps complete for UI
    if step4_done:
        step2_done = True
        step3_done = True
        image_ok = True

    steps = [
        {
            "id": 1,
            "title": "检测本机显卡",
            "done": True,
            "detail": machine.get("label") or family,
        },
        {
            "id": 2,
            "title": "安装并启动 Docker Desktop",
            "done": step2_done,
            "detail": (
                "Docker 引擎已就绪"
                if step2_done
                else ("已检测到 Docker 客户端，但引擎未就绪" if docker_cli else "未检测到 Docker")
            ),
        },
        {
            "id": 3,
            "title": "下载并安装口播加速包",
            "done": step3_done,
            "detail": (
                f"已找到镜像：{prefer_tar['name']}"
                if prefer_tar
                else (f"请安装「{recommended.get('name')}」" if recommended else "请安装对应显卡夸克包")
            ),
        },
        {
            "id": 4,
            "title": "加载镜像并启动口播",
            "done": step4_done,
            "detail": (
                "8383 已就绪"
                if step4_done
                else ("镜像已 load，待启动服务" if step4_partial else "待 docker load + 一键启动")
            ),
        },
    ]

    general_ops_note = (
        "非 RTX50 用户请下载「通用显卡」夸克包（不是 RTX50 包）。"
        "若你这边只能打出 50 系包：请换一台非 50 机器，或在能拉取 Hub 的环境执行 "
        "`docker pull guiji2025/duix.avatar` 后再 `scripts/export_heygem_docker_image.ps1` "
        "与 `pack_quark_accel.py --pack-id heygem-docker-general`，把通用包传到夸克。"
        "通用用户提速靠夸克分享，不要把通用镜像打进安装包。"
    )

    return {
        "ok": True,
        "machine": machine,
        "heygem": {
            "ready": st.get("ready"),
            "state": st.get("state"),
            "hint": st.get("hint"),
            "docker_available": docker_ok,
            "docker_cli": docker_cli,
            "api": st.get("api"),
            "gpu_ok": st.get("gpu_ok"),
            "gpu_hint": st.get("gpu_hint"),
        },
        "recommended_pack": recommended,
        "share_root_url": catalog.get("share_root_url") or "",
        "share_extract_code": (
            (recommended or {}).get("share_extract_code")
            or catalog.get("share_extract_code")
            or ""
        ),
        "portal_note": catalog.get("quark_portal_note") or catalog.get("portal_note") or "",
        "tars": tars,
        "image": image,
        "image_loaded": image_ok,
        "steps": steps,
        "current_step": next((s["id"] for s in steps if not s["done"]), 4),
        "docker_product_url": DOCKER_PRODUCT_URL,
        "docker_installer_url": DOCKER_INSTALLER_URL,
        "general_pack_ops_note": general_ops_note,
        "can_load": bool(tars) and docker_ok,
        "can_start": bool(st.get("can_start")),
    }

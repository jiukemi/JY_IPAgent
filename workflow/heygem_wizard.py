"""HeyGem install wizard: Docker check, quark tar load, status for UI steps."""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
import urllib.request
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
# WSL data + images grow fast; warn below this free space.
_MIN_FREE_BYTES = 25 * 1024 * 1024 * 1024

_DOCKER_INSTALL_LOCK = threading.Lock()
_DOCKER_INSTALL: dict[str, Any] = {
    "phase": "idle",  # idle | downloading | elevating | launched | error | done
    "message": "",
    "drive": "",
    "install_root": "",
    "progress_pct": 0,
    "updated_at": 0.0,
}


def _set_docker_install(**kwargs: Any) -> None:
    with _DOCKER_INSTALL_LOCK:
        _DOCKER_INSTALL.update(kwargs)
        _DOCKER_INSTALL["updated_at"] = time.time()


def docker_install_progress() -> dict[str, Any]:
    with _DOCKER_INSTALL_LOCK:
        return dict(_DOCKER_INSTALL)


def list_install_drives() -> list[dict[str, Any]]:
    """Fixed/local drives for Docker install picker (Windows)."""
    out: list[dict[str, Any]] = []
    if os.name != "nt":
        return out
    for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        root = Path(f"{letter}:\\")
        if not root.exists():
            continue
        try:
            usage = shutil.disk_usage(str(root))
        except OSError:
            continue
        free = int(usage.free)
        total = int(usage.total)
        out.append(
            {
                "letter": f"{letter}:",
                "root": str(root),
                "free_bytes": free,
                "total_bytes": total,
                "free_gb": round(free / (1024**3), 1),
                "total_gb": round(total / (1024**3), 1),
                "recommended": free >= _MIN_FREE_BYTES and letter != "C",
                "enough_space": free >= _MIN_FREE_BYTES,
                "label": f"{letter}:（剩余约 {round(free / (1024**3), 1)} GB）",
            }
        )
    # Prefer non-C with most free space as default hint
    preferred = sorted(
        (d for d in out if d["letter"] != "C:" and d["enough_space"]),
        key=lambda d: d["free_bytes"],
        reverse=True,
    )
    if preferred:
        for d in out:
            d["default"] = d["letter"] == preferred[0]["letter"]
    elif out:
        for d in out:
            d["default"] = d["letter"] == "C:"
    return out


def _installer_cache_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or ".")
    return base / "JY_IPAgent" / "DockerDesktopInstaller.exe"


def _installer_looks_valid(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size >= 50_000_000
    except OSError:
        return False


def _normalize_installer_path(installer: Path) -> Path:
    """Copy installer to a no-space path so cmd.exe / UAC never break on spaces.

    Official name is ``Docker Desktop Installer.exe``; Downloads folders may also
    contain spaces (e.g. ``C:\\Users\\Foo Bar\\Downloads\\...``).
    """
    src = installer.expanduser().resolve()
    if not _installer_looks_valid(src):
        raise RuntimeError(f"安装包无效或不完整：{src}")
    dest = _installer_cache_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Already the cache file and name has no spaces
    try:
        if src.resolve() == dest.resolve():
            return dest
    except OSError:
        pass
    need_copy = (" " in str(src)) or (src.name != dest.name) or (not dest.is_file())
    if need_copy:
        # Skip copy if same size already cached (resume-friendly)
        try:
            if dest.is_file() and dest.stat().st_size == src.stat().st_size:
                return dest
        except OSError:
            pass
        _set_docker_install(
            message=f"安装包文件名含空格或路径含空格，正在复制到无空格路径：{dest.name}…",
        )
        shutil.copy2(src, dest)
    if not _installer_looks_valid(dest):
        raise RuntimeError(f"复制安装包失败：{dest}")
    return dest


def find_local_docker_installers() -> list[dict[str, Any]]:
    """Scan common folders for Docker Desktop Installer.exe (no network)."""
    homes: list[Path] = []
    user = Path.home()
    for name in ("Downloads", "下载", "Desktop", "桌面"):
        homes.append(user / name)
    for env_key in ("USERPROFILE", "PUBLIC"):
        base = os.environ.get(env_key)
        if base:
            homes.append(Path(base) / "Downloads")
            homes.append(Path(base) / "下载")
    homes.append(_installer_cache_path().parent)
    # Also scan free drives' Downloads
    for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        homes.append(Path(f"{letter}:\\Downloads"))
        homes.append(Path(f"{letter}:\\下载"))

    seen: set[str] = set()
    found: list[dict[str, Any]] = []
    patterns = (
        "Docker Desktop Installer.exe",
        "DockerDesktopInstaller.exe",
        "*Docker*Desktop*Installer*.exe",
        "*docker*desktop*installer*.exe",
    )
    for folder in homes:
        try:
            if not folder.is_dir():
                continue
        except OSError:
            continue
        for pat in patterns:
            try:
                matches = list(folder.glob(pat))
            except OSError:
                continue
            for p in matches:
                try:
                    key = str(p.resolve()).lower()
                except OSError:
                    key = str(p).lower()
                if key in seen:
                    continue
                if not _installer_looks_valid(p):
                    continue
                seen.add(key)
                size = p.stat().st_size
                found.append(
                    {
                        "path": str(p),
                        "name": p.name,
                        "bytes": size,
                        "size_gb": round(size / (1024**3), 2),
                        "label": f"{p.name}（{round(size / (1024**3), 2)} GB · {p.parent}）",
                    }
                )
    found.sort(key=lambda x: x["bytes"], reverse=True)
    return found[:20]


def _download_docker_installer(dest: Path) -> None:
    """Resume-capable download; official CDN often fails in CN — prefer local file."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".partial")
    expected = 0
    last_err: Exception | None = None

    for attempt in range(1, 4):
        existing = tmp.stat().st_size if tmp.is_file() else 0
        headers = {"User-Agent": "JY_IPAgent/0.1"}
        if existing > 0:
            headers["Range"] = f"bytes={existing}-"
        try:
            req = urllib.request.Request(DOCKER_INSTALLER_URL, headers=headers)
            with urllib.request.urlopen(req, timeout=120) as resp:
                cr = resp.headers.get("Content-Range") or ""
                if "/" in cr:
                    try:
                        expected = int(cr.rsplit("/", 1)[-1])
                    except ValueError:
                        pass
                elif resp.headers.get("Content-Length") and existing == 0:
                    try:
                        expected = int(resp.headers["Content-Length"])
                    except ValueError:
                        pass
                # Server ignored Range → rewrite from scratch
                mode = "ab" if existing > 0 and getattr(resp, "status", 200) == 206 else "wb"
                if mode == "wb":
                    existing = 0
                written = existing
                with open(tmp, mode) as out:
                    while True:
                        chunk = resp.read(1024 * 256)
                        if not chunk:
                            break
                        out.write(chunk)
                        written += len(chunk)
                        if expected > 0:
                            pct = int(min(99, written * 100 / expected))
                            _set_docker_install(
                                phase="downloading",
                                progress_pct=pct,
                                message=(
                                    f"正在下载 Docker Desktop 安装包… {pct}% "
                                    f"（第 {attempt}/3 次尝试）"
                                ),
                            )
            if expected > 0 and written < int(expected * 0.98):
                raise OSError(
                    f"retrieval incomplete: got only {written} out of {expected} bytes"
                )
            if written < 50_000_000:
                raise OSError(f"下载文件过小（{written} bytes），疑似被中断或拦截")
            tmp.replace(dest)
            return
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            _set_docker_install(
                phase="downloading",
                progress_pct=0,
                message=f"下载中断，正在重试（{attempt}/3）…",
            )
            time.sleep(1.5 * attempt)

    raise RuntimeError(
        "官网安装包下载失败（国内直连 Docker CDN 经常中断）。"
        "请改用：浏览器/夸克/迅雷下好「Docker Desktop Installer.exe」后，"
        "在向导里选择该文件或点「扫描本机安装包」，再「安装到所选盘」。"
        f"原始错误：{last_err}"
    )


def _write_docker_install_cmd(installer: Path, install_root: Path) -> Path:
    """Write a .cmd that runs the installer with custom dirs (UAC-friendly)."""
    # Always use no-space path — official "Docker Desktop Installer.exe" breaks cmd quoting.
    installer = _normalize_installer_path(installer)
    app_dir = install_root / "DockerDesktop"
    wsl_root = install_root / "wsl"
    win_root = install_root / "windows-containers"
    for p in (app_dir, wsl_root, win_root):
        p.mkdir(parents=True, exist_ok=True)
    cache = _installer_cache_path().parent
    cache.mkdir(parents=True, exist_ok=True)
    cmd_path = cache / "install_docker_custom_drive.cmd"

    # Paths here have no spaces by design (D:\Docker\..., DockerDesktopInstaller.exe).
    exe = str(installer)
    app_s, wsl_s, win_s = str(app_dir), str(wsl_root), str(win_root)
    lines = [
        "@echo off",
        "chcp 65001 >nul",
        "setlocal",
        "echo Installing Docker Desktop to custom drive...",
        f"echo Installer: {exe}",
        f"echo Target: {install_root}",
        f'"{exe}" install --accept-license --installation-dir={app_s} --wsl-default-data-root={wsl_s} --windows-containers-default-data-root={win_s}',
        "set ERR=%ERRORLEVEL%",
        "if not %ERR%==0 (",
        "  echo Install failed, exit=%ERR%",
        "  pause",
        "  exit /b %ERR%",
        ")",
        "echo Install finished. You can close this window.",
        "exit /b 0",
        "",
    ]
    cmd_path.write_text("\r\n".join(lines), encoding="utf-8")
    return cmd_path


def _elevate_docker_installer(installer: Path, install_root: Path) -> Path:
    """Show UAC and start installer. Prefer ShellExecute runas; return .cmd path used."""
    cmd_path = _write_docker_install_cmd(installer, install_root)

    # 1) ShellExecuteW "runas" — reliable UAC on interactive desktop
    try:
        import ctypes

        rc = int(
            ctypes.windll.shell32.ShellExecuteW(
                None,
                "runas",
                str(cmd_path),
                None,
                str(cmd_path.parent),
                1,  # SW_SHOWNORMAL
            )
        )
        if rc > 32:
            return cmd_path
        raise RuntimeError(f"ShellExecuteW runas 返回 {rc}")
    except Exception as shell_exc:
        # 2) PowerShell Start-Process -Verb RunAs (fallback)
        def _q(s: str) -> str:
            return "'" + s.replace("'", "''") + "'"

        ps = (
            f"$p = Start-Process -FilePath {_q(str(cmd_path))} "
            f"-Verb RunAs -PassThru; "
            f"if ($null -eq $p) {{ throw 'UAC cancelled or failed' }}; "
            f"Write-Output $p.Id"
        )
        r = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                ps,
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0) if os.name == "nt" else 0,
        )
        if r.returncode != 0:
            err = (r.stderr or r.stdout or "").strip() or f"exit {r.returncode}"
            raise RuntimeError(
                "未能弹出管理员确认（UAC）。"
                f"ShellExecute：{shell_exc}；PowerShell：{err}。"
                f"请手动右键以管理员运行：{cmd_path}"
            )
        return cmd_path


def prepare_docker_desktop_install(
    drive: str,
    *,
    installer_path: str | None = None,
) -> dict[str, Any]:
    """Validate inputs and write elevate .cmd — for Electron main to UAC-launch."""
    if os.name != "nt":
        return {"ok": False, "message": "仅支持 Windows。"}
    letter = (drive or "").strip().upper().rstrip("\\")
    if len(letter) == 1:
        letter = f"{letter}:"
    if not (len(letter) == 2 and letter[1] == ":" and letter[0].isalpha()):
        return {"ok": False, "message": "磁盘盘符无效"}
    root = Path(f"{letter[0]}:\\")
    if not root.exists():
        return {"ok": False, "message": f"磁盘 {letter} 不存在"}
    try:
        free = shutil.disk_usage(str(root)).free
    except OSError as exc:
        return {"ok": False, "message": f"无法读取磁盘空间：{exc}"}
    if free < _MIN_FREE_BYTES:
        return {
            "ok": False,
            "message": f"{letter} 剩余约 {round(free / (1024**3), 1)} GB，建议至少 25 GB。",
        }

    installer: Path | None = None
    if installer_path:
        cand = Path(installer_path.strip().strip('"'))
        if _installer_looks_valid(cand):
            installer = cand
    if installer is None:
        local = find_local_docker_installers()
        if local:
            installer = Path(local[0]["path"])
        elif _installer_looks_valid(_installer_cache_path()):
            installer = _installer_cache_path()
    if installer is None:
        return {
            "ok": False,
            "message": "未找到本机 Docker Desktop 安装包。请先下载并扫描/填写路径。",
            "local_installers": find_local_docker_installers(),
        }

    install_root = root / "Docker"
    try:
        cmd_path = _write_docker_install_cmd(installer, install_root)
        # Prefer the normalized (no-space) installer path for Electron / display
        normalized = _normalize_installer_path(installer)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": f"准备安装失败：{exc}"}
    return {
        "ok": True,
        "drive": letter,
        "installer": str(normalized),
        "install_root": str(install_root),
        "cmd_path": str(cmd_path),
        "message": (
            f"已准备安装到 {install_root}。"
            + (
                "（已将带空格的「Docker Desktop Installer.exe」复制为无空格文件名再安装。）"
                if " " in str(installer)
                else ""
            )
            + "接下来会弹出管理员确认，请点「是」。若没看到窗口，请看任务栏盾牌图标是否闪烁。"
        ),
    }

def _install_docker_worker(
    drive: str,
    *,
    installer_path: str | None = None,
    allow_download: bool = False,
) -> None:
    letter = drive.strip().upper().rstrip("\\")
    if len(letter) == 1:
        letter = f"{letter}:"
    if not (len(letter) == 2 and letter[1] == ":" and letter[0].isalpha()):
        _set_docker_install(phase="error", message="磁盘盘符无效，请选择如 D:", progress_pct=0)
        return
    root = Path(f"{letter[0]}:\\")
    if not root.exists():
        _set_docker_install(phase="error", message=f"磁盘 {letter} 不存在", progress_pct=0)
        return
    try:
        free = shutil.disk_usage(str(root)).free
    except OSError as exc:
        _set_docker_install(phase="error", message=f"无法读取磁盘空间：{exc}", progress_pct=0)
        return
    if free < _MIN_FREE_BYTES:
        _set_docker_install(
            phase="error",
            message=(
                f"{letter} 剩余约 {round(free / (1024**3), 1)} GB，建议至少 25 GB 空闲后再装 Docker。"
                "请换一块空间更大的盘。"
            ),
            progress_pct=0,
        )
        return

    install_root = root / "Docker"
    _set_docker_install(
        phase="downloading",
        drive=letter,
        install_root=str(install_root),
        progress_pct=0,
        message="正在准备 Docker Desktop 安装包…",
    )
    try:
        installer: Path | None = None
        if installer_path:
            cand = Path(installer_path.strip().strip('"'))
            if not _installer_looks_valid(cand):
                _set_docker_install(
                    phase="error",
                    message=(
                        f"安装包无效或不完整：{cand}。"
                        "请确认是「Docker Desktop Installer.exe」（通常约 500MB+）。"
                    ),
                    progress_pct=0,
                )
                return
            installer = cand
            _set_docker_install(
                progress_pct=100,
                message=f"使用本机安装包：{installer.name}",
            )
        else:
            local = find_local_docker_installers()
            if local:
                installer = Path(local[0]["path"])
                _set_docker_install(
                    progress_pct=100,
                    message=f"已自动找到本机安装包：{installer}",
                )
            elif _installer_looks_valid(_installer_cache_path()):
                installer = _installer_cache_path()
                _set_docker_install(
                    progress_pct=100,
                    message="使用本机缓存的安装包。",
                )
            elif allow_download:
                installer = _installer_cache_path()
                _set_docker_install(message="正在从官网下载安装包（国内常失败，不推荐）…")
                _download_docker_installer(installer)
            else:
                _set_docker_install(
                    phase="error",
                    message=(
                        "未找到本机 Docker Desktop 安装包。"
                        "国内直连官网经常下到一半就断。"
                        "请先用浏览器/网盘下载「Docker Desktop Installer.exe」到「下载」文件夹，"
                        "再点「扫描本机安装包」或粘贴完整路径，然后「安装到所选盘」。"
                    ),
                    progress_pct=0,
                )
                return

        assert installer is not None
        _set_docker_install(
            phase="elevating",
            progress_pct=100,
            message="即将弹出「用户账户控制」：请点「是」。若没看到窗口，请看任务栏盾牌图标是否闪烁。",
        )
        cmd_path = _elevate_docker_installer(installer, install_root)
        _set_docker_install(
            phase="launched",
            message=(
                f"已请求管理员权限安装到 {install_root}。"
                f"若仍未出现 UAC，请手动右键以管理员运行：{cmd_path}"
                "装好后打开 Docker，登录窗可 Skip，托盘就绪后回本向导点「重新检测」。"
            ),
        )
    except Exception as exc:  # noqa: BLE001 — surface to UI
        _set_docker_install(phase="error", message=f"安装失败：{exc}", progress_pct=0)


def start_docker_desktop_install(
    drive: str,
    *,
    installer_path: str | None = None,
    allow_download: bool = False,
) -> dict[str, Any]:
    """Install Docker Desktop to the chosen drive from a local installer (preferred)."""
    if os.name != "nt":
        return {"ok": False, "message": "仅支持 Windows 上一键安装 Docker Desktop。"}
    with _DOCKER_INSTALL_LOCK:
        phase = _DOCKER_INSTALL.get("phase")
        if phase in ("downloading", "elevating"):
            return {
                "ok": False,
                "message": _DOCKER_INSTALL.get("message") or "安装进行中，请稍候…",
                "docker_install": dict(_DOCKER_INSTALL),
            }
    letter = (drive or "").strip() or next(
        (d["letter"] for d in list_install_drives() if d.get("default")),
        "D:",
    )
    path = (installer_path or "").strip() or None
    if path and not _installer_looks_valid(Path(path.strip('"'))) and not allow_download:
        return {
            "ok": False,
            "message": (
                f"安装包无效或不完整：{path}。"
                "请选择完整的 Docker Desktop Installer.exe（约 500MB+）。"
            ),
            "docker_install": docker_install_progress(),
            "local_installers": find_local_docker_installers(),
        }

    _set_docker_install(
        phase="downloading",
        drive=letter,
        message="已排队：准备安装…",
        progress_pct=0,
        install_root="",
    )
    threading.Thread(
        target=_install_docker_worker,
        kwargs={
            "drive": letter,
            "installer_path": path,
            "allow_download": allow_download,
        },
        name="docker-desktop-install",
        daemon=True,
    ).start()
    if allow_download and not path:
        msg = (
            f"已开始尝试官网下载并安装到 {letter}（国内网络常失败）。"
            "更稳妥：先下好安装包，再选文件安装到所选盘。"
        )
    else:
        msg = (
            f"已开始安装到 {letter}：使用本机安装包，将弹出管理员确认。"
            "请点「是」，装完后回向导「重新检测」。"
        )
    return {
        "ok": True,
        "message": msg,
        "drive": letter,
        "docker_install": docker_install_progress(),
        "local_installers": find_local_docker_installers(),
    }


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
            "message": "Docker Desktop 未运行。请先安装并打开 Docker（个人使用通常无需注册，登录可跳过），等到 docker info / 向导「重新检测」通过后再加载镜像。",
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
    """Open Docker Desktop installer URL in the default browser (user downloads themselves)."""
    # Prefer direct installer link so browser download UI appears; product page often blocked in CN.
    url = DOCKER_INSTALLER_URL
    try:
        webbrowser.open(url)
        opened = True
    except Exception:
        opened = False
        try:
            webbrowser.open(DOCKER_PRODUCT_URL)
            opened = True
        except Exception:
            opened = False
    return {
        "ok": True,
        "opened": opened,
        "product_url": DOCKER_PRODUCT_URL,
        "installer_url": DOCKER_INSTALLER_URL,
        "message": (
            "已尝试打开安装包下载链接。国内直连常失败或很慢，可用浏览器下载管理/网盘把 "
            "「Docker Desktop Installer.exe」下到「下载」文件夹，"
            "再回向导点「扫描本机安装包」→ 选盘 →「安装到所选盘」。"
            "不要双击官网安装器装到默认 C 盘。"
        ),
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
        # Custom-drive installs via wizard / install_docker_desktop_custom_drive.ps1
        Path(r"D:\Docker\DockerDesktop\Docker Desktop.exe"),
        Path(r"E:\Docker\DockerDesktop\Docker Desktop.exe"),
        Path(r"F:\Docker\DockerDesktop\Docker Desktop.exe"),
    ]
    for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        candidates.append(Path(f"{letter}:\\Docker\\DockerDesktop\\Docker Desktop.exe"))
    custom = (os.environ.get("DOCKER_DESKTOP_PATH") or "").strip()
    if custom:
        candidates.insert(0, Path(custom))
    exe = next((p for p in candidates if p.is_file()), None)
    if exe is None:
        return {
            "ok": False,
            "message": (
                "未找到 Docker Desktop。请在上方选一块剩余空间够的盘，点「一键安装到所选盘」"
                "（会弹管理员确认，装到该盘，不必打开终端）。"
            ),
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
            "message": (
                f"已尝试启动：{exe.name}。"
                "请等待托盘就绪（约 30–90 秒）；若弹出登录请跳过，不必注册。"
                "再点「重新检测」（验收：docker info 成功即可）。"
            ),
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
                "验收通过：docker info 成功（无需 Docker Hub 账号）"
                if step2_done
                else (
                    "已装客户端但引擎未就绪：打开 Docker，跳过登录，等到托盘就绪后点「重新检测」"
                    if docker_cli
                    else "未检测到 Docker。个人使用通常无需注册；装好后验收以 docker info 为准"
                )
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
        "docker_acceptance_note": (
            "验收：本机 docker info 成功即可（通常无需注册）。"
            "国内直连官网安装包经常下到一半失败——"
            "请先自行下好「Docker Desktop Installer.exe」，再选盘并点「安装到所选盘」。"
            "软件只负责把已下载的安装包装到你选的盘（避开默认 C 盘）。"
        ),
        "install_drives": list_install_drives(),
        "local_docker_installers": find_local_docker_installers(),
        "docker_install": docker_install_progress(),
        "general_pack_ops_note": general_ops_note,
        "can_load": bool(tars) and docker_ok,
        "can_start": bool(st.get("can_start")),
    }

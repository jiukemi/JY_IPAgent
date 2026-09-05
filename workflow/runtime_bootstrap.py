"""Ensure FFmpeg (and report runtime gaps) without breaking existing PATH setups."""

from __future__ import annotations

import os
import shutil
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent


def runtime_dir() -> Path:
    env = (os.environ.get("AGENT_RUNTIME_DIR") or "").strip()
    if env:
        return Path(env)
    return ROOT / "data" / "runtime"


def ffmpeg_dir() -> Path:
    return runtime_dir() / "ffmpeg"


def ffmpeg_exe() -> Path:
    return ffmpeg_dir() / "ffmpeg.exe"


# BtbN essentials build (Windows amd64) — public GitHub release + mirrors
FFMPEG_ZIP_URLS = (
    "https://ghfast.top/https://github.com/BtbN/FFmpeg-Builds/releases/download/"
    "latest/ffmpeg-master-latest-win64-gpl-shared.zip",
    "https://mirror.ghproxy.com/https://github.com/BtbN/FFmpeg-Builds/releases/download/"
    "latest/ffmpeg-master-latest-win64-gpl-shared.zip",
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/"
    "latest/ffmpeg-master-latest-win64-gpl-shared.zip",
)


def _download(url: str, dest: Path, timeout: int = 45) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = Request(url, headers={"User-Agent": "agent-runtime-bootstrap/1.0"})
    with urlopen(req, timeout=timeout) as resp, dest.open("wb") as out:
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            out.write(chunk)


def ffmpeg_on_path() -> str | None:
    which = shutil.which("ffmpeg")
    return which


def ensure_ffmpeg(download: bool = True) -> dict:
    """Return status; optionally download FFmpeg into runtime/ffmpeg."""
    existing = ffmpeg_on_path()
    if existing:
        return {"ok": True, "path": existing, "source": "path"}
    exe = ffmpeg_exe()
    fdir = ffmpeg_dir()
    if exe.is_file():
        _prepend_path(str(fdir))
        return {"ok": True, "path": str(exe), "source": "runtime"}
    if not download:
        return {"ok": False, "path": "", "source": "missing", "message": "未找到 FFmpeg"}

    rt = runtime_dir()
    rt.mkdir(parents=True, exist_ok=True)
    zpath = rt / "ffmpeg-download.zip"
    last_err = ""
    try:
        for url in FFMPEG_ZIP_URLS:
            try:
                _download(url, zpath)
                break
            except Exception as e:
                last_err = str(e)
                continue
        else:
            return {"ok": False, "path": "", "source": "error", "message": last_err or "下载失败"}

        extract_to = rt / "ffmpeg_extract"
        if extract_to.exists():
            shutil.rmtree(extract_to)
        extract_to.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zpath, "r") as z:
            z.extractall(extract_to)
        found = next(extract_to.rglob("ffmpeg.exe"), None)
        if not found:
            return {"ok": False, "path": "", "source": "error", "message": "zip 内无 ffmpeg.exe"}
        if fdir.exists():
            shutil.rmtree(fdir)
        fdir.mkdir(parents=True, exist_ok=True)
        for f in found.parent.iterdir():
            shutil.copy2(f, fdir / f.name)
        shutil.rmtree(extract_to, ignore_errors=True)
        zpath.unlink(missing_ok=True)
        _prepend_path(str(fdir))
        return {"ok": True, "path": str(exe), "source": "downloaded"}
    except Exception as e:
        return {"ok": False, "path": "", "source": "error", "message": str(e)}


def _prepend_path(dir_path: str) -> None:
    cur = os.environ.get("PATH", "")
    if dir_path.lower() in cur.lower():
        return
    os.environ["PATH"] = dir_path + os.pathsep + cur


def apply_runtime_path() -> None:
    """Call early so child tools see bundled ffmpeg."""
    if ffmpeg_exe().is_file():
        _prepend_path(str(ffmpeg_dir()))


def runtime_status() -> dict:
    py = shutil.which("py") or shutil.which("python") or shutil.which("python3")
    portable_py = runtime_dir() / "python" / "python.exe"
    return {
        "ffmpeg": ensure_ffmpeg(download=False),
        "python": {
            "ok": bool(py) or portable_py.is_file(),
            "path": str(portable_py) if portable_py.is_file() else (py or ""),
            "portable": portable_py.is_file(),
        },
        "docker": bool(shutil.which("docker")),
        "hints": {
            "heygem_portable": (
                "官方无 Windows 免 Docker 包。可选：① 社区「Duix/HeyGem 一键整合包」自行下载后上传你的 OSS；"
                "② 本机 Docker 已拉取镜像后运行 scripts/export_heygem_docker_image.ps1 得到离线 tar，"
                "用户仍需 Docker，但可免拉 Docker Hub。"
            ),
        },
    }

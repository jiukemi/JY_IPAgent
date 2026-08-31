"""Fetch component archives from file:// or http(s) mirrors; verify; extract."""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import urllib.request
from pathlib import Path
from typing import Callable
from urllib.parse import unquote, urlparse
import zipfile

ProgressCb = Callable[[int, int, str], None]  # received, total_or_-1, message


def verify_sha256(path: Path, expected: str) -> bool:
    if not expected:
        return True
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().lower() == expected.strip().lower()


def _open_url(url: str):
    parsed = urlparse(url)
    if parsed.scheme == "file":
        path = unquote(parsed.path)
        if path.startswith("/") and len(path) > 2 and path[2] == ":":
            path = path[1:]  # Windows /E:/...
        return Path(path).open("rb"), Path(path).stat().st_size
    req = urllib.request.Request(url, headers={"User-Agent": "agent-component-installer/1.0"})
    resp = urllib.request.urlopen(req, timeout=120)
    total = int(resp.headers.get("Content-Length") or -1)
    return resp, total


def download_to_file(url: str, dest: Path, on_progress: ProgressCb | None = None) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    stream, total = _open_url(url)
    received = 0
    try:
        with dest.open("wb") as out:
            while True:
                chunk = stream.read(1024 * 256)
                if not chunk:
                    break
                out.write(chunk)
                received += len(chunk)
                if on_progress:
                    on_progress(received, total, "downloading")
    finally:
        stream.close()
    if on_progress:
        on_progress(received, total if total > 0 else received, "downloaded")
    return dest


def extract_zip(zip_path: Path, dest_dir: Path) -> None:
    staging = dest_dir.with_name(dest_dir.name + ".__staging")
    wrap = staging.with_name(staging.name + ".__wrap")

    def _cleanup_temps() -> None:
        for p in (staging, wrap):
            if p.exists():
                shutil.rmtree(p)

    _cleanup_temps()
    staging.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(staging)
        man = staging / "manifest.component.json"
        if not man.is_file():
            subs = [p for p in staging.iterdir() if p.is_dir()]
            if len(subs) == 1 and (subs[0] / "manifest.component.json").is_file():
                if wrap.exists():
                    shutil.rmtree(wrap)
                subs[0].rename(wrap)
                shutil.rmtree(staging)
                wrap.rename(staging)
                man = staging / "manifest.component.json"
            else:
                raise ValueError("zip 缺少 manifest.component.json")
        data = json.loads(man.read_text(encoding="utf-8-sig"))
        entry = data.get("entry") or "start.ps1"
        if not (staging / entry).is_file():
            raise ValueError(f"zip 缺少入口脚本: {entry}")
        if dest_dir.exists():
            shutil.rmtree(dest_dir)
        staging.rename(dest_dir)
    except Exception:
        _cleanup_temps()
        raise


def install_from_mirrors(
    mirrors: list[dict],
    dest_dir: Path,
    on_progress: ProgressCb | None = None,
) -> Path:
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="agent-comp-") as td:
        archive = Path(td) / "pkg.zip"
        for m in mirrors:
            url = (m.get("url") or "").strip()
            if not url:
                continue
            try:
                if on_progress:
                    on_progress(0, -1, f"trying {m.get('label') or url}")
                download_to_file(url, archive, on_progress=on_progress)
                sha = (m.get("sha256") or "").strip()
                if sha and not verify_sha256(archive, sha):
                    raise ValueError("sha256 校验失败")
                if on_progress:
                    on_progress(0, -1, "extracting")
                extract_zip(archive, dest_dir)
                return dest_dir
            except Exception as e:
                errors.append(f"{url}: {e}")
                continue
    raise RuntimeError("所有镜像均失败: " + "; ".join(errors[:5]))

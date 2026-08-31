"""Resumable per-file downloads for offline bundle (build machine only)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
ST = ROOT / "tools" / "SadTalker"


def _load_hf_endpoint() -> str:
    cfg = ROOT / "config.yaml"
    if cfg.exists():
        data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
        ep = (data.get("hf_endpoint") or "").strip().rstrip("/")
        if ep:
            return ep
    return "https://hf-mirror.com"


def _venv_site() -> None:
    for base in (ST,):
        site = base / "venv" / "Lib" / "site-packages"
        if site.is_dir():
            sys.path.insert(0, str(site))


def _ensure_hf() -> None:
    _venv_site()
    try:
        import huggingface_hub  # noqa: F401
    except ImportError:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q", "huggingface_hub"],
            check=True,
        )


def _hub_env(endpoint: str) -> None:
    os.environ["HF_ENDPOINT"] = endpoint.rstrip("/")
    os.environ.setdefault("HF_XET_HIGH_PERFORMANCE", "1")


def _ok(path: Path, min_bytes: int) -> bool:
    return path.is_file() and path.stat().st_size >= min_bytes


def _remove_bad(path: Path, min_bytes: int) -> None:
    if not path.exists() or (path.is_file() and path.stat().st_size >= min_bytes):
        return
    print(f"  remove incomplete: {path}", flush=True)
    for attempt in range(5):
        try:
            path.unlink(missing_ok=True)
            return
        except PermissionError:
            time.sleep(attempt + 1)
    if path.exists() and path.stat().st_size < min_bytes:
        raise PermissionError(f"cannot replace locked incomplete file: {path}")


def _curl_download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".part")
    cmd = [
        "curl.exe",
        "-L",
        "--retry",
        "8",
        "--retry-delay",
        "5",
        "--connect-timeout",
        "30",
        "-C",
        "-",
        "-o",
        str(partial),
        url,
    ]
    print(f"  curl {url}", flush=True)
    subprocess.run(cmd, check=True)
    if partial.exists():
        if dest.exists():
            dest.unlink()
        partial.rename(dest)


def hf_file(
    repo: str,
    filename: str,
    dest: Path,
    *,
    min_bytes: int = 1,
    endpoint: str,
) -> None:
    from huggingface_hub import hf_hub_download

    _remove_bad(dest, min_bytes)
    if _ok(dest, min_bytes):
        print(f"  skip {dest.name} ({dest.stat().st_size // 1024 // 1024} MB)", flush=True)
        return

    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  get {repo}/{filename} -> {dest}", flush=True)
    url = f"{endpoint.rstrip('/')}/{repo}/resolve/main/{filename}"

    last_err: Exception | None = None
    for attempt in range(1, 4):
        try:
            cache = hf_hub_download(repo_id=repo, filename=filename)
            got = Path(cache)
            if got.resolve() != dest.resolve():
                if dest.exists():
                    dest.unlink()
                shutil.copy2(got, dest)
            if _ok(dest, min_bytes):
                return
        except Exception as exc:
            last_err = exc
            print(f"  hub attempt {attempt} failed: {exc}", flush=True)
            time.sleep(attempt * 2)

    try:
        _curl_download(url, dest)
        if _ok(dest, min_bytes):
            return
    except Exception as exc:
        last_err = exc
        print(f"  curl failed: {exc}", flush=True)

    raise RuntimeError(
        f"download incomplete: {dest} ({dest.stat().st_size if dest.exists() else 0} bytes)"
    ) from last_err


def sadtalker(endpoint: str) -> None:
    if not (ST / "inference.py").exists():
        raise SystemExit(f"Missing SadTalker at {ST}")
    ckpt = ST / "checkpoints"
    print("== SadTalker checkpoints", flush=True)
    repo = "camenduru/SadTalker"
    mapping = [
        ("new/checkpoints/mapping_00109-model.pth.tar", "mapping_00109-model.pth.tar", 150_000_000),
        ("new/checkpoints/mapping_00229-model.pth.tar", "mapping_00229-model.pth.tar", 150_000_000),
        ("new/checkpoints/SadTalker_V0.0.2_256.safetensors", "SadTalker_V0.0.2_256.safetensors", 700_000_000),
        ("new/checkpoints/SadTalker_V0.0.2_512.safetensors", "SadTalker_V0.0.2_512.safetensors", 700_000_000),
    ]
    for remote, local, min_b in mapping:
        hf_file(repo, remote, ckpt / local, min_bytes=min_b, endpoint=endpoint)


def main() -> int:
    endpoint = _load_hf_endpoint()
    print(f"=== download_assets_resumable (endpoint={endpoint}) ===", flush=True)
    _ensure_hf()
    _hub_env(endpoint)
    sadtalker(endpoint)
    print("=== complete ===", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

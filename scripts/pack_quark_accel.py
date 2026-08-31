#!/usr/bin/env python3
"""Build Quark accelerator zip packs (universal vs GPU-specific HeyGem)."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "dist" / "quark-packs"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def write_manifest(staging: Path, meta: dict, parts: list[dict], share_url: str = "") -> None:
    payload = {
        "version": 1,
        "bundle_id": "agent-quark-accel",
        "bundle_name": meta["bundle_name"],
        "pack_id": meta["pack_id"],
        "pack_kind": meta["pack_kind"],
        "gpu_family": meta["gpu_family"],
        "channel": "quark",
        "min_app_version": "0.1.0",
        "parts": parts,
        "quark_share_url": share_url or "",
        "post_install_hint": meta.get("post_install_hint") or "",
        "notes": meta.get("notes") or [],
    }
    (staging / "MANIFEST.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def zip_dir(staging: Path, zip_path: Path) -> str:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.is_file():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for fp in staging.rglob("*"):
            if fp.is_file():
                zf.write(fp, fp.relative_to(staging).as_posix())
    digest = sha256_file(zip_path)
    print(f"OK  {zip_path}")
    print(f"SHA256  {digest}")
    print("Upload to Quark, then fill share_url in data/quark/catalog.json")
    return digest


def meta_pack_id(zip_path: Path) -> str:
    return zip_path.stem


def pack_demo(out_dir: Path, share_url: str) -> Path:
    with tempfile.TemporaryDirectory(prefix="quark-demo-") as tmp:
        staging = Path(tmp)
        payload = staging / "payload"
        payload.mkdir(parents=True)
        ready = payload / "READY.txt"
        ready.write_text("quark-accel demo\n", encoding="utf-8")
        rel = "payload/READY.txt"
        parts = [
            {
                "id": "demo_marker",
                "file": rel,
                "optional": False,
                "install_as": "accel/READY.txt",
                "sha256": sha256_file(ready),
            }
        ]
        write_manifest(
            staging,
            {
                "bundle_name": "九易AI-加速包-演示",
                "pack_id": "demo",
                "pack_kind": "universal",
                "gpu_family": "any",
                "post_install_hint": "演示包仅写入 accel/READY.txt，无真实引擎。",
                "notes": ["smoke-test"],
            },
            parts,
            share_url,
        )
        dest = out_dir / "九易AI-加速包-演示.zip"
        zip_dir(staging, dest)
        return dest


def pack_ffmpeg(out_dir: Path, ffmpeg_zip: Path, share_url: str) -> Path:
    if not ffmpeg_zip.is_file():
        raise SystemExit(f"FFmpeg zip not found: {ffmpeg_zip}")
    with tempfile.TemporaryDirectory(prefix="quark-ffmpeg-") as tmp:
        staging = Path(tmp)
        payload = staging / "payload"
        payload.mkdir(parents=True)
        dest_part = payload / "ffmpeg-portable.zip"
        shutil.copy2(ffmpeg_zip, dest_part)
        parts = [
            {
                "id": "ffmpeg",
                "file": "payload/ffmpeg-portable.zip",
                "optional": False,
                "install_as": "ffmpeg/bundle.zip",
                "extract_to": "ffmpeg",
                "sha256": sha256_file(dest_part),
            }
        ]
        write_manifest(
            staging,
            {
                "bundle_name": "九易AI-加速包-通用-ffmpeg",
                "pack_id": "universal-ffmpeg",
                "pack_kind": "universal",
                "gpu_family": "any",
                "post_install_hint": "已解压到 data/runtime/ffmpeg。重启应用或点「确保 FFmpeg」。",
                "notes": ["universal"],
            },
            parts,
            share_url,
        )
        dest = out_dir / "九易AI-加速包-通用-ffmpeg.zip"
        zip_dir(staging, dest)
        return dest


def pack_indextts(out_dir: Path, indextts_dir: Path, share_url: str) -> Path:
    if not indextts_dir.is_dir():
        raise SystemExit(f"IndexTTS dir not found: {indextts_dir}")
    with tempfile.TemporaryDirectory(prefix="quark-indextts-") as tmp:
        staging = Path(tmp)
        payload = staging / "payload"
        payload.mkdir(parents=True)
        inner = payload / "indextts-weights.zip"
        src = indextts_dir
        for cand in (indextts_dir / "checkpoints", indextts_dir / "models"):
            if cand.is_dir():
                src = cand
                break
        print(f"Zipping weights from {src} …")
        with zipfile.ZipFile(inner, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for fp in src.rglob("*"):
                if fp.is_file():
                    zf.write(fp, fp.relative_to(src).as_posix())
        parts = [
            {
                "id": "indextts_weights",
                "file": "payload/indextts-weights.zip",
                "optional": False,
                "install_as": "indextts/weights.zip",
                "extract_to": "indextts",
                "sha256": sha256_file(inner),
            }
        ]
        write_manifest(
            staging,
            {
                "bundle_name": "九易AI-加速包-通用-IndexTTS权重",
                "pack_id": "universal-indextts-weights",
                "pack_kind": "universal",
                "gpu_family": "any",
                "post_install_hint": "权重已落到 data/runtime/indextts。请再在「本机环境」确认 IndexTTS 就绪。",
                "notes": ["weights-universal"],
            },
            parts,
            share_url,
        )
        dest = out_dir / "九易AI-加速包-通用-IndexTTS权重.zip"
        zip_dir(staging, dest)
        return dest


def pack_heygem(out_dir: Path, docker_tar: Path, family: str, share_url: str) -> Path:
    if not docker_tar.is_file():
        raise SystemExit(f"Docker tar not found: {docker_tar}")
    if family == "general":
        pack_id = "heygem-docker-general"
        tar_name = "duix.avatar.tar"
        install_as = "heygem/duix.avatar.tar"
        zip_name = "九易AI-加速包-口播-通用显卡.zip"
        bundle = "九易AI-加速包-口播-通用显卡"
        hint = (
            "已保存镜像 tar。执行: docker load -i data\\runtime\\heygem\\duix.avatar.tar "
            "然后运行 scripts/setup/setup_heygem.ps1（非 RTX50）。"
        )
        notes = ["not-rtx50", "duix.avatar"]
    else:
        pack_id = "heygem-docker-rtx50"
        tar_name = "duix.avatar-5090.tar"
        install_as = "heygem/duix.avatar-5090.tar"
        zip_name = "九易AI-加速包-口播-RTX50系.zip"
        bundle = "九易AI-加速包-口播-RTX50系"
        hint = (
            "已保存 5090 镜像 tar。执行: docker load -i data\\runtime\\heygem\\duix.avatar-5090.tar "
            "；RTX50 机器上再跑 scripts/setup/setup_heygem.ps1。"
        )
        notes = ["rtx50-only", "duix.avatar-5090"]

    with tempfile.TemporaryDirectory(prefix=f"quark-heygem-{family}-") as tmp:
        staging = Path(tmp)
        payload = staging / "payload"
        payload.mkdir(parents=True)
        dest_tar = payload / tar_name
        shutil.copy2(docker_tar, dest_tar)
        parts = [
            {
                "id": "heygem_tar",
                "file": f"payload/{tar_name}",
                "optional": False,
                "install_as": install_as,
                "sha256": sha256_file(dest_tar),
            }
        ]
        write_manifest(
            staging,
            {
                "bundle_name": bundle,
                "pack_id": pack_id,
                "pack_kind": "gpu",
                "gpu_family": family,
                "post_install_hint": hint,
                "notes": notes,
            },
            parts,
            share_url,
        )
        dest = out_dir / zip_name
        zip_dir(staging, dest)
        return dest


def main() -> None:
    ap = argparse.ArgumentParser(description="Pack Quark accelerator zips")
    ap.add_argument(
        "--pack-id",
        required=True,
        choices=[
            "demo",
            "universal-ffmpeg",
            "universal-indextts-weights",
            "heygem-docker-general",
            "heygem-docker-rtx50",
        ],
    )
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT))
    ap.add_argument("--docker-tar", default="")
    ap.add_argument("--ffmpeg-zip", default="")
    ap.add_argument("--indextts-dir", default=str(ROOT / "tools" / "IndexTTS"))
    ap.add_argument("--share-url", default="")
    args = ap.parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.pack_id == "demo":
        pack_demo(out_dir, args.share_url)
    elif args.pack_id == "universal-ffmpeg":
        pack_ffmpeg(out_dir, Path(args.ffmpeg_zip), args.share_url)
    elif args.pack_id == "universal-indextts-weights":
        pack_indextts(out_dir, Path(args.indextts_dir), args.share_url)
    elif args.pack_id == "heygem-docker-general":
        pack_heygem(out_dir, Path(args.docker_tar), "general", args.share_url)
    elif args.pack_id == "heygem-docker-rtx50":
        pack_heygem(out_dir, Path(args.docker_tar), "rtx50", args.share_url)


if __name__ == "__main__":
    main()

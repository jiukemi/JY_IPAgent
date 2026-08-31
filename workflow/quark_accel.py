"""Quark netdisk accelerator: catalog, scan, verify MANIFEST, extract into runtime."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

from workflow.gpu_family import (
    GPU_FAMILY_ANY,
    classify_gpu_family,
    pack_matches_machine,
)

BUNDLE_MARKERS = ("agent-quark-accel", "九易AI", "quark-accel")
ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = ROOT / "data" / "quark" / "catalog.json"
SCHEMA_PATH = ROOT / "data" / "quark" / "manifest.schema.json"


def runtime_root() -> Path:
    rt = (os.environ.get("AGENT_RUNTIME_DIR") or "").strip()
    if rt:
        return Path(rt).expanduser().resolve()
    return (ROOT / "data" / "runtime").resolve()


def default_scan_dirs() -> list[Path]:
    home = Path.home()
    dirs: list[Path] = []
    for rel in (
        "Downloads",
        "下载",
        "Desktop",
        "桌面",
        "Documents/夸克网盘",
        "Documents/Quark",
    ):
        dirs.append(home / rel)
    for env_key in ("USERPROFILE", "HOME"):
        base = os.environ.get(env_key)
        if not base:
            continue
        b = Path(base)
        dirs.extend(
            [
                b / "Downloads",
                b / "下载",
                b / "Quark",
                b / "夸克网盘",
            ]
        )
    seen: set[str] = set()
    out: list[Path] = []
    for d in dirs:
        key = str(d.resolve()) if d.exists() else str(d)
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
    return out


def load_catalog() -> dict:
    if not CATALOG_PATH.is_file():
        return {"version": 1, "packs": [], "quark_portal_note": ""}
    try:
        data = json.loads(CATALOG_PATH.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {"version": 1, "packs": []}
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "packs": [], "error": "catalog.json 无法解析"}


def _sha256_file(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _looks_like_bundle_zip(path: Path) -> bool:
    name = path.name.lower()
    if not name.endswith(".zip"):
        return False
    return any(m.lower() in name for m in BUNDLE_MARKERS)


def _read_manifest_from_zip(zip_path: Path) -> dict | None:
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            cand = None
            for n in names:
                if n.replace("\\", "/").rstrip("/").endswith("MANIFEST.json"):
                    cand = n
                    break
            if not cand:
                return None
            raw = zf.read(cand).decode("utf-8-sig")
            data = json.loads(raw)
            if not isinstance(data, dict):
                return None
            if data.get("bundle_id") != "agent-quark-accel":
                return None
            return data
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError, UnicodeDecodeError):
        return None


def find_accel_zips(scan_dirs: list[Path] | None = None) -> list[dict]:
    """Return candidate bundles newest-first."""
    roots = scan_dirs or default_scan_dirs()
    found: list[dict] = []
    for root in roots:
        if not root.is_dir():
            continue
        try:
            zips = list(root.glob("*.zip"))
            zips += list(root.glob("*/*.zip"))
        except OSError:
            continue
        for zp in zips:
            if not _looks_like_bundle_zip(zp):
                if not any(k in zp.name.lower() for k in ("accel", "quark", "九易", "agent")):
                    continue
            manifest = _read_manifest_from_zip(zp)
            if not manifest:
                continue
            try:
                st = zp.stat()
                mtime = st.st_mtime
                size = st.st_size
            except OSError:
                mtime, size = 0.0, 0
            found.append(
                {
                    "path": str(zp.resolve()),
                    "manifest": manifest,
                    "mtime": mtime,
                    "bytes": size,
                    "scan_dir": str(root),
                    "gpu_family": (manifest.get("gpu_family") or GPU_FAMILY_ANY),
                    "pack_kind": manifest.get("pack_kind") or "universal",
                    "pack_id": manifest.get("pack_id") or "",
                }
            )
    found.sort(key=lambda x: x.get("mtime") or 0, reverse=True)
    return found


def install_accel_zip(
    zip_path: str | Path,
    *,
    dest_root: Path | None = None,
    force: bool = False,
) -> dict:
    """Verify MANIFEST parts and extract into runtime. Returns status dict."""
    zp = Path(zip_path).expanduser().resolve()
    if not zp.is_file():
        return {"ok": False, "message": f"文件不存在：{zp}"}

    manifest = _read_manifest_from_zip(zp)
    if not manifest:
        return {"ok": False, "message": "不是有效的夸克加速包（缺少 MANIFEST.json / bundle_id）"}

    machine = classify_gpu_family()
    pack_family = str(manifest.get("gpu_family") or GPU_FAMILY_ANY)
    ok_match, match_msg = pack_matches_machine(pack_family, machine["gpu_family"])
    if not ok_match and not force:
        return {
            "ok": False,
            "message": f"显卡不匹配：{match_msg}",
            "gpu_mismatch": True,
            "pack_gpu_family": pack_family,
            "machine_gpu_family": machine["gpu_family"],
            "machine": machine,
            "hint": "请改下对应夸克包，或确认无误后勾选「强制安装」。",
        }

    rt = dest_root or runtime_root()
    rt.mkdir(parents=True, exist_ok=True)
    work = rt / "_quark_extract"
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)

    installed: list[str] = []
    try:
        with zipfile.ZipFile(zp, "r") as zf:
            zf.extractall(work)
            manifest_files = list(work.rglob("MANIFEST.json"))
            if not manifest_files:
                return {"ok": False, "message": "解压后未找到 MANIFEST.json"}
            base = manifest_files[0].parent
            parts = manifest.get("parts") or []
            for part in parts:
                if not isinstance(part, dict):
                    continue
                rel = str(part.get("file") or "").replace("\\", "/")
                if not rel:
                    continue
                src = base / rel
                if not src.is_file():
                    if part.get("optional"):
                        continue
                    return {"ok": False, "message": f"缺少部件：{rel}"}
                expect = (part.get("sha256") or "").lower()
                if expect:
                    actual = _sha256_file(src)
                    if actual != expect:
                        return {
                            "ok": False,
                            "message": f"校验失败：{rel}\n期望 {expect}\n实际 {actual}",
                        }
                install_as = part.get("install_as") or rel
                extract_to = part.get("extract_to")
                dest = rt / str(install_as)
                dest.parent.mkdir(parents=True, exist_ok=True)
                if src.suffix.lower() == ".zip" and extract_to:
                    target_dir = rt / str(extract_to)
                    target_dir.mkdir(parents=True, exist_ok=True)
                    with zipfile.ZipFile(src, "r") as inner:
                        inner.extractall(target_dir)
                    installed.append(f"{rel} -> {target_dir}")
                else:
                    shutil.copy2(src, dest)
                    installed.append(f"{rel} -> {dest}")

        marker = rt / "accel" / "QUARK_INSTALLED.json"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(
            json.dumps(
                {
                    "bundle_id": manifest.get("bundle_id"),
                    "bundle_name": manifest.get("bundle_name"),
                    "pack_id": manifest.get("pack_id"),
                    "pack_kind": manifest.get("pack_kind"),
                    "gpu_family": pack_family,
                    "source_zip": str(zp),
                    "installed": installed,
                    "machine_gpu_family": machine["gpu_family"],
                    "forced": bool(force and not ok_match),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        post = manifest.get("post_install_hint") or ""
        result: dict = {
            "ok": True,
            "message": "夸克加速包已安装到运行时目录"
            + (f"（已强制：{match_msg}）" if force and not ok_match else ""),
            "runtime": str(rt),
            "installed": installed,
            "gpu_match": ok_match,
            "match_message": match_msg,
            "post_install_hint": post,
            "manifest": {
                "bundle_id": manifest.get("bundle_id"),
                "bundle_name": manifest.get("bundle_name"),
                "pack_id": manifest.get("pack_id"),
                "pack_kind": manifest.get("pack_kind"),
                "gpu_family": pack_family,
                "quark_share_url": manifest.get("quark_share_url") or "",
            },
            "machine": machine,
        }
        # Optional: immediately docker load HeyGem tar when Docker is up
        pack_id = str(manifest.get("pack_id") or "")
        if pack_id.startswith("heygem-docker"):
            try:
                from workflow.heygem_wizard import docker_load_tar

                load_res = docker_load_tar(family=pack_family if pack_family in ("general", "rtx50") else None)
                result["docker_load"] = load_res
                if load_res.get("ok"):
                    result["post_install_hint"] = (
                        (post + "\n" if post else "")
                        + str(load_res.get("message") or "镜像已加载，请在向导中启动口播。")
                    )
                elif load_res.get("need_docker"):
                    result["post_install_hint"] = (
                        (post + "\n" if post else "")
                        + "镜像 tar 已就位；请先打开 Docker Desktop，再在「口播安装向导」里点加载。"
                    )
            except Exception as load_exc:
                result["docker_load"] = {"ok": False, "message": str(load_exc)}
        return result
    except Exception as exc:
        return {"ok": False, "message": f"安装失败：{exc}"}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def save_upload_and_install(data: bytes, filename: str = "upload.zip", *, force: bool = False) -> dict:
    """Persist an uploaded zip under runtime staging, then install."""
    if not data or len(data) < 64:
        return {"ok": False, "message": "上传文件过小或为空"}
    name = Path(filename or "upload.zip").name
    if not name.lower().endswith(".zip"):
        name += ".zip"
    staging = runtime_root() / "accel" / "uploads"
    staging.mkdir(parents=True, exist_ok=True)
    dest = staging / name
    dest.write_bytes(data)
    return install_accel_zip(dest, force=force)


def scan_and_install_latest(*, force: bool = False, prefer_gpu_match: bool = True) -> dict:
    cands = find_accel_zips()
    if not cands:
        return {
            "ok": False,
            "message": "未在「下载/桌面/夸克目录」找到加速包。请先用夸克或浏览器下载 zip（勿改关键名）。",
            "scan_dirs": [str(p) for p in default_scan_dirs()],
        }
    machine = classify_gpu_family()
    mf = machine["gpu_family"]
    chosen = cands[0]
    if prefer_gpu_match:
        matched = [
            c
            for c in cands
            if pack_matches_machine(str(c.get("gpu_family") or GPU_FAMILY_ANY), mf)[0]
        ]
        if matched:
            chosen = matched[0]
    result = install_accel_zip(chosen["path"], force=force)
    result["found"] = chosen["path"]
    result["candidates"] = len(cands)
    result["machine"] = machine
    return result


def catalog_for_ui() -> dict:
    """Pack list + GPU recommendation for Settings UI."""
    catalog = load_catalog()
    machine = classify_gpu_family()
    packs_out: list[dict] = []
    for p in catalog.get("packs") or []:
        if not isinstance(p, dict):
            continue
        pf = str(p.get("gpu_family") or GPU_FAMILY_ANY)
        ok, msg = pack_matches_machine(pf, machine["gpu_family"])
        packs_out.append(
            {
                **p,
                "recommended": bool(ok and (p.get("pack_kind") != "gpu" or pf == machine["gpu_family"])),
                "matches_machine": ok,
                "match_message": msg,
            }
        )
    # Prefer recommended gpu packs first, then universal
    packs_out.sort(
        key=lambda x: (
            0 if x.get("recommended") and x.get("pack_kind") == "gpu" else 1,
            0 if x.get("pack_kind") == "universal" else 1,
            str(x.get("id") or ""),
        )
    )
    installed_marker = runtime_root() / "accel" / "QUARK_INSTALLED.json"
    installed = None
    if installed_marker.is_file():
        try:
            installed = json.loads(installed_marker.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            installed = {"raw": True}
    return {
        "ok": True,
        "machine": machine,
        "packs": packs_out,
        "portal_note": catalog.get("quark_portal_note") or "",
        "share_root_url": catalog.get("share_root_url") or "",
        "share_extract_code": catalog.get("share_extract_code") or "",
        "installed": installed,
        "scan_dirs": [str(p) for p in default_scan_dirs()],
        "schema_path": str(SCHEMA_PATH) if SCHEMA_PATH.is_file() else "",
    }

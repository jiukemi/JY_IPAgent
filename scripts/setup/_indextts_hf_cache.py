"""Pre-download IndexTTS2 hf_cache aux models (no dependency on indextts.utils.model_download).

Used by setup_indextts.ps1 and as a fallback when Gitee mirrors ship older IndexTTS trees
that lack indextts.utils.model_download / examples_downloader.
"""

from __future__ import annotations

import os
import shutil
import sys
import urllib.request
from pathlib import Path


def _env_mirrors() -> None:
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    os.environ.setdefault("HUGGINGFACE_HUB_ENDPOINT", "https://hf-mirror.com")


def _weight_ok(d: Path, min_b: int = 50_000_000) -> bool:
    if not d.is_dir():
        return False
    for n in ("model.safetensors", "pytorch_model.bin", "model.safetensors.index.json"):
        p = d / n
        if not p.is_file():
            continue
        if n.endswith(".json"):
            if any(d.glob("*.safetensors")):
                return True
            continue
        if p.stat().st_size >= min_b:
            return True
    return any(p.stat().st_size >= min_b for p in d.glob("*.safetensors"))


def _http_download(url: str, dest: Path, *, timeout: int = 600) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    print(f">> http {url} -> {dest}")
    with urllib.request.urlopen(url, timeout=timeout) as resp, open(tmp, "wb") as out:
        shutil.copyfileobj(resp, out)
    tmp.replace(dest)


def _hf_file(repo_id: str, filename: str, dest: Path) -> None:
    """Download one file via huggingface_hub, else hf-mirror HTTP."""
    _env_mirrors()
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size > 1000:
        return
    try:
        from huggingface_hub import hf_hub_download

        path = hf_hub_download(
            repo_id=repo_id,
            filename=filename,
            local_dir=str(dest.parent),
            local_dir_use_symlinks=False,
        )
        p = Path(path)
        if p.is_file() and p.resolve() != dest.resolve():
            # hf may nest under repo subdirs
            nested = dest.parent / filename
            if nested.is_file() and nested.resolve() != dest.resolve():
                shutil.copy2(nested, dest)
            elif p.resolve() != dest.resolve():
                shutil.copy2(p, dest)
        if dest.is_file() and dest.stat().st_size > 1000:
            return
    except Exception as exc:
        print(f"!! hf_hub_download {repo_id}/{filename}: {exc}")

    url = f"https://hf-mirror.com/{repo_id}/resolve/main/{filename}"
    _http_download(url, dest)
    if not dest.is_file() or dest.stat().st_size < 1000:
        raise RuntimeError(f"download failed: {repo_id}/{filename} -> {dest}")


def _snapshot_w2v(w2v: Path) -> None:
    _env_mirrors()
    if w2v.exists() and not _weight_ok(w2v):
        shutil.rmtree(w2v, ignore_errors=True)
    if _weight_ok(w2v):
        return
    w2v.mkdir(parents=True, exist_ok=True)
    try:
        from modelscope import snapshot_download

        print(">> ModelScope AI-ModelScope/w2v-bert-2.0")
        snapshot_download("AI-ModelScope/w2v-bert-2.0", local_dir=str(w2v))
        if _weight_ok(w2v):
            return
    except Exception as exc:
        print(f"!! modelscope w2v: {exc}")
    from huggingface_hub import snapshot_download as hf_snap

    print(">> HF facebook/w2v-bert-2.0")
    hf_snap("facebook/w2v-bert-2.0", local_dir=str(w2v), local_dir_use_symlinks=False)
    if not _weight_ok(w2v):
        raise SystemExit(f"w2v-bert-2.0 incomplete: {w2v}")


def ensure_hf_cache(model_dir: Path) -> None:
    cache = model_dir / "hf_cache"
    cache.mkdir(parents=True, exist_ok=True)

    # Prefer upstream helper when present (newer IndexTTS trees).
    try:
        install = Path(os.environ.get("INDEXTTS_INSTALL_DIR") or model_dir.parent)
        if str(install) not in sys.path:
            sys.path.insert(0, str(install))
        from indextts.utils.model_download import ensure_models_available  # type: ignore

        print(">> using indextts.utils.model_download.ensure_models_available")
        ensure_models_available(str(model_dir))
    except Exception as exc:
        print(f"!! upstream ensure_models_available unavailable ({exc}); standalone download")

    w2v = cache / "w2v-bert-2.0"
    if not _weight_ok(w2v):
        _snapshot_w2v(w2v)

    sc = cache / "semantic_codec_model.safetensors"
    if not sc.is_file() or sc.stat().st_size < 1_000_000:
        # Flat name expected by IndexTTS; source file lives under semantic_codec/
        nested = cache / "semantic_codec" / "model.safetensors"
        try:
            _hf_file("amphion/MaskGCT", "semantic_codec/model.safetensors", nested)
            if nested.is_file():
                shutil.copy2(nested, sc)
        except Exception:
            _hf_file("amphion/MaskGCT", "semantic_codec/model.safetensors", sc)

    camp = cache / "campplus_cn_common.bin"
    if not camp.is_file() or camp.stat().st_size < 10_000:
        try:
            from modelscope.hub.file_download import model_file_download

            print(">> ModelScope campplus")
            p = model_file_download(
                model_id="iic/speech_campplus_sv_zh-cn_16k-common",
                file_path="campplus_cn_common.bin",
                local_dir=str(cache),
            )
            if p and Path(p).is_file() and Path(p).resolve() != camp.resolve():
                shutil.copy2(p, camp)
        except Exception as exc:
            print(f"!! modelscope campplus: {exc}")
        if not camp.is_file() or camp.stat().st_size < 10_000:
            _hf_file("funasr/campplus", "campplus_cn_common.bin", camp)

    big = cache / "bigvgan"
    big.mkdir(parents=True, exist_ok=True)
    for name in ("config.json", "bigvgan_generator.pt"):
        dest = big / name
        if dest.is_file() and dest.stat().st_size > 100:
            continue
        _hf_file("nvidia/bigvgan_v2_22khz_80band_256x", name, dest)

    missing = []
    if not _weight_ok(w2v):
        missing.append("w2v-bert-2.0")
    if not sc.is_file() or sc.stat().st_size < 1_000_000:
        missing.append("semantic_codec_model.safetensors")
    if not camp.is_file() or camp.stat().st_size < 10_000:
        missing.append("campplus_cn_common.bin")
    if not (big / "config.json").is_file() or not (big / "bigvgan_generator.pt").is_file():
        missing.append("bigvgan")
    if missing:
        raise SystemExit("hf_cache still incomplete: " + ", ".join(missing))
    print("HF_CACHE_AUX_OK")


def main() -> None:
    raw = os.environ.get("INDEXTTS_CKPT_DIR") or (sys.argv[1] if len(sys.argv) > 1 else "")
    if not raw:
        raise SystemExit("usage: INDEXTTS_CKPT_DIR=... python _indextts_hf_cache.py")
    ensure_hf_cache(Path(raw))


if __name__ == "__main__":
    main()

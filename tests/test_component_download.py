from pathlib import Path
import hashlib
import zipfile

from workflow.component_download import download_to_file, verify_sha256, extract_zip, install_from_mirrors


def test_verify_sha256(tmp_path: Path):
    p = tmp_path / "a.bin"
    data = b"hello-component"
    p.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    assert verify_sha256(p, digest) is True
    assert verify_sha256(p, "0" * 64) is False


def test_extract_zip_requires_manifest(tmp_path: Path):
    zpath = tmp_path / "c.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("start.ps1", "echo hi\n")
    dest = tmp_path / "out"
    try:
        extract_zip(zpath, dest)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "manifest.component.json" in str(e)


def test_extract_zip_ok(tmp_path: Path):
    zpath = tmp_path / "c.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("manifest.component.json", '{"id":"demo","version":"1","entry":"start.ps1"}')
        z.writestr("start.ps1", "echo hi\n")
    dest = tmp_path / "out"
    extract_zip(zpath, dest)
    assert (dest / "manifest.component.json").is_file()
    assert (dest / "start.ps1").is_file()


def test_extract_zip_failure_preserves_existing_dest(tmp_path: Path):
    dest = tmp_path / "out"
    dest.mkdir()
    keep = dest / "keep.txt"
    keep.write_text("safe\n", encoding="utf-8")

    zpath = tmp_path / "bad.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("start.ps1", "echo hi\n")

    try:
        extract_zip(zpath, dest)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "manifest.component.json" in str(e)

    assert keep.is_file()
    assert keep.read_text(encoding="utf-8") == "safe\n"
    assert not (tmp_path / "out.__staging").exists()

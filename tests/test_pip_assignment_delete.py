"""PiP assignment removal from session store."""

from pathlib import Path

from workflow.pip_assignments_store import (
    load_pip_assignments,
    remove_pip_assignments,
    save_pip_assignments,
)


def test_remove_pip_assignment_by_cue_indices(tmp_path: Path):
    media = tmp_path / "scene.mp4"
    media.write_bytes(b"\x00" * 60_000)
    save_pip_assignments(
        tmp_path,
        [
            {
                "cue_indices": [1, 2],
                "start": 0.0,
                "end": 2.0,
                "media_path": str(media),
                "auto_hyperframe": True,
            },
            {
                "cue_indices": [3],
                "start": 2.0,
                "end": 4.0,
                "media_path": str(tmp_path / "other.mp4"),
                "auto_hyperframe": True,
            },
        ],
    )
    (tmp_path / "other.mp4").write_bytes(b"\x00" * 60_000)

    out = remove_pip_assignments(tmp_path, cue_indices=[1, 2], delete_media=True)
    assert out["removed"] == 1
    assert out["deleted_files"] == 1
    assert not media.is_file()
    kept = load_pip_assignments(tmp_path)["assignments"]
    assert len(kept) == 1
    assert kept[0]["cue_indices"] == [3]

"""Reset publish mix workspace."""

from pathlib import Path

from workflow.pip_assignments_store import (
    assignments_path,
    clear_pip_mix,
    load_pip_assignments,
    save_pip_assignments,
)


def test_clear_pip_mix_empties_assignments_and_files(tmp_path: Path):
    session = tmp_path / "sess"
    pip_root = session / "publish" / "pip_cues"
    pip_root.mkdir(parents=True)
    clip = pip_root / "hf_auto" / "clip.mp4"
    clip.parent.mkdir(parents=True)
    clip.write_bytes(b"fake")
    save_pip_assignments(
        session,
        [{"cue_indices": [1], "media_path": str(clip), "start": 0, "end": 1}],
    )
    out = clear_pip_mix(session, delete_generated=True)
    assert out["assignments"] == []
    assert load_pip_assignments(session)["assignments"] == []
    assert not clip.is_file()
    assert assignments_path(session).is_file()

"""HyperFrames cue grouping: force-contiguous vs smart merge."""

from pathlib import Path
from types import SimpleNamespace

from workflow.hyperframes import group_cues_contiguous, group_cues_for_scenes, generate_cue_scene_assets


def _cue(index: int, start: float, end: float, text: str):
    return SimpleNamespace(index=index, start=start, end=end, text=text)


def test_force_contiguous_merges_across_sentence_and_8s():
    cues = [
        _cue(1, 0.0, 2.0, "第一句结束。"),
        _cue(2, 2.1, 5.0, "第二句继续讲"),
        _cue(3, 5.2, 10.5, "第三句跨过八秒限制也要并"),
    ]
    groups = group_cues_contiguous(cues)
    assert len(groups) == 1
    assert [c.index for c in groups[0]] == [1, 2, 3]


def test_force_contiguous_splits_on_timeline_gap():
    cues = [
        _cue(1, 0.0, 1.0, "A。"),
        _cue(2, 1.1, 2.0, "B"),
        _cue(3, 5.0, 6.0, "隔开的另一段"),
    ]
    groups = group_cues_contiguous(cues)
    assert len(groups) == 2
    assert [c.index for c in groups[0]] == [1, 2]
    assert [c.index for c in groups[1]] == [3]


def test_smart_merge_still_splits_on_sentence_end():
    cues = [
        _cue(1, 0.0, 1.0, "第一句结束。"),
        _cue(2, 1.1, 2.0, "第二句"),
    ]
    groups = group_cues_for_scenes(cues)
    assert len(groups) == 2


def test_generate_force_contiguous_one_asset(tmp_path, monkeypatch):
    cues = [
        _cue(1, 0.0, 1.5, "第一句结束。"),
        _cue(2, 1.6, 3.0, "紧接着再说"),
    ]

    def fake_still(text, output_path, **kwargs):
        output_path.write_bytes(b"png")
        return output_path

    monkeypatch.setattr("workflow.hyperframes_scenes.render_scene_still", fake_still)
    monkeypatch.setattr(
        "workflow.hyperframes_scenes.resolve_layout",
        lambda _layout: {"animated": False, "css": False},
    )
    out = generate_cue_scene_assets(
        cues,
        tmp_path,
        layout="card",
        force_contiguous=True,
        smart_merge=True,
    )
    assert len(out) == 1
    assert out[0]["cue_indices"] == [1, 2]
    assert abs(out[0]["start"] - 0.0) < 1e-6
    assert abs(out[0]["end"] - 3.0) < 1e-6
    # Still layout must not dump both sentences onto one lead card
    # (only first smart phrase). File exists.
    assert Path(out[0]["media_path"]).is_file()


def test_progressive_video_splits_text_not_wall(tmp_path, monkeypatch):
    cues = [
        _cue(1, 0.0, 2.0, "第一句结束。"),
        _cue(2, 2.1, 4.0, "第二句继续。"),
        _cue(3, 4.1, 6.0, "第三句收尾。"),
    ]
    texts: list[str] = []

    def fake_video(text, output_path, **kwargs):
        texts.append(text)
        Path(output_path).write_bytes(b"fake")
        return output_path

    def fake_concat(ffmpeg_bin, parts, output):
        Path(output).write_bytes(b"concat")
        return output

    monkeypatch.setattr("workflow.hf_official.is_available", lambda: False)
    monkeypatch.setattr("workflow.hyperframes_scenes.generate_scene_video", fake_video)
    monkeypatch.setattr("workflow.hyperframes._ffmpeg_concat_videos", fake_concat)
    monkeypatch.setattr(
        "workflow.hyperframes_scenes.resolve_layout",
        lambda _layout: {"animated": True, "css": True},
    )
    out = generate_cue_scene_assets(
        cues,
        tmp_path,
        layout="kinetic",
        force_contiguous=True,
        ffmpeg_bin="ffmpeg",
        remotion_captions=False,
    )
    assert len(out) == 1
    assert out[0]["media_path"].endswith(".mp4")
    assert len(texts) >= 2
    assert all("第一句结束。第二句继续。第三句收尾。" != t for t in texts)


def test_progressive_uses_official_beats(tmp_path, monkeypatch):
    cues = [
        _cue(1, 0.0, 2.0, "第一句结束。"),
        _cue(2, 2.1, 4.0, "第二句继续。"),
    ]
    captured: dict = {}

    def fake_beats(beats, output_path, **kwargs):
        captured["beats"] = beats
        captured["duration"] = kwargs.get("duration_sec")
        Path(output_path).write_bytes(b"beats")
        return Path(output_path)

    monkeypatch.setattr("workflow.hf_official.is_available", lambda: True)
    monkeypatch.setattr("workflow.hf_official.render_scene_beats", fake_beats)
    monkeypatch.setattr(
        "workflow.hyperframes_scenes.resolve_layout",
        lambda _layout: {"animated": True, "css": True},
    )
    monkeypatch.setattr(
        "workflow.hyperframes_scenes.resolve_dimensions",
        lambda *_a, **_k: (1080, 1920),
    )
    out = generate_cue_scene_assets(
        cues,
        tmp_path,
        layout="kinetic",
        force_contiguous=True,
        ffmpeg_bin="ffmpeg",
        remotion_captions=False,
    )
    assert len(out) == 1
    assert len(captured.get("beats") or []) >= 2
    assert all("text" in b for b in captured["beats"])

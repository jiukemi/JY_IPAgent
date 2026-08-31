"""Remotion caption bridge availability / gating."""

import workflow.remotion_captions as rc


def test_off_mode_disables_remotion(monkeypatch):
    monkeypatch.setenv("AGENT_REMOTION_ENGINE", "off")
    assert rc.is_available() is False


def test_auto_requires_render_script(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_REMOTION_ENGINE", "auto")
    monkeypatch.setattr(rc, "RENDER_JS", tmp_path / "missing.mjs")
    assert rc.is_available() is False


def test_side_theme_normalized():
    assert rc._normalize_burn_mode("side") == "side"
    assert rc._normalize_burn_mode("side_kinetic") == "side"
    assert rc._normalize_burn_mode("bar") == "bar"
    assert rc._normalize_burn_mode("kinetic") == "bar"
    assert rc._normalize_burn_mode("pop") == "pop"
    assert rc._normalize_burn_mode("off") == "off"


def test_enrich_remotion_cues_adds_smart_spans():
    cues = rc._enrich_remotion_cues(
        [{"start": 0, "end": 2, "text": "限时福利 立即领取"}]
    )
    assert len(cues) == 1
    spans = cues[0].get("spans") or []
    assert spans
    classes = {s["cls"] for s in spans}
    assert "hook" in classes or "key" in classes


def test_resolve_remotion_auto_theme():
    assert rc.resolve_remotion_theme("auto", "限时福利马上领取") in ("pop", "pill", "glass", "kinetic", "bar")
    assert rc.resolve_remotion_theme("glass", "test") == "glass"


def test_suggest_remotion_caption_theme():
    sug = rc.suggest_remotion_caption_theme("这是一个比较长的讲解句子，需要毛玻璃底牌来承载更多文字内容。")
    assert sug["theme"] == "glass"


def test_side_burn_uses_lipsync_fusion_not_strip_overlay(monkeypatch, tmp_path):
    """口播混剪 side burn must one-shot LipsyncFusion (no ffmpeg side strip)."""
    src = tmp_path / "lipsync.mp4"
    src.write_bytes(b"fake")
    out = tmp_path / "out.mp4"
    called: dict = {}

    def fake_fusion(video_path, cues, output_path, **kwargs):
        called["video"] = str(video_path)
        called["side"] = kwargs.get("side")
        output_path.write_bytes(b"ok")
        return output_path

    monkeypatch.setattr(rc, "is_available", lambda: True)
    monkeypatch.setattr(rc, "render_lipsync_fusion", fake_fusion)
    monkeypatch.setattr(
        "workflow.publish.probe_video_dimensions",
        lambda *_a, **_k: (1080, 1920),
    )
    monkeypatch.setattr("workflow.publish.media_duration", lambda *_a, **_k: 2.0)
    monkeypatch.setattr("pipeline.ffprobe_bin", lambda *_a, **_k: "ffprobe")

    rc.burn_remotion_on_video(
        src,
        [{"start": 0, "end": 1, "text": "你好"}],
        out,
        remotion_theme="side",
        caption_side="left",
        duration_sec=2.0,
    )
    assert called.get("side") == "left"
    assert out.is_file()

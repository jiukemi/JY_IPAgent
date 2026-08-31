"""Official HyperFrames bridge availability / gating."""

import workflow.hf_official as hf


def test_pil_mode_disables_official(monkeypatch):
    monkeypatch.setenv("AGENT_HF_ENGINE", "pil")
    assert hf.is_available() is False


def test_auto_requires_render_script(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_HF_ENGINE", "auto")
    monkeypatch.setattr(hf, "RENDER_JS", tmp_path / "missing.mjs")
    assert hf.is_available() is False

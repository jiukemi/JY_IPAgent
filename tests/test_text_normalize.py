"""Tests for TTS speech text normalization."""

from tts.text_normalize import normalize_speech_text


def test_codex_kept_readable():
    assert normalize_speech_text("推荐 Codex 写代码") == "推荐 Codex 写代码"
    assert normalize_speech_text("用 CODEX 辅助") == "用 Codex 辅助"


def test_spaced_latin_collapsed():
    assert normalize_speech_text("C o d e x 很强") == "Codex 很强"
    assert normalize_speech_text("c o d e x") == "Codex"


def test_mac_brand_rules():
    assert normalize_speech_text("MAC口红") == "魅可口红"
    assert normalize_speech_text("MAC 电脑") == "Mac 电脑"


def test_common_english_preserved():
    assert normalize_speech_text("Hello world") == "Hello world"
    assert normalize_speech_text("This is Codex") == "This is Codex"


def test_vibecoding_latin_for_indextts():
    assert normalize_speech_text("入行 VibeCoding", backend="indextts") == "入行 vibe coding"
    assert normalize_speech_text("入门vibecoding。", backend="indextts") == "入门vibe coding。"
    assert normalize_speech_text("VibeStart 工具", backend="indextts") == "vibe start 工具"
    assert normalize_speech_text("vibestart一键部署", backend="indextts") == "vibe start一键部署"


def test_vibecoding_cn_for_cosyvoice():
    assert normalize_speech_text("入行 VibeCoding", backend="cosyvoice") == "入行 氛围编程"


def test_slash_enum_and_brands():
    assert normalize_speech_text("codex / cursor", backend="indextts") == "Codex 、 Cursor"
    assert normalize_speech_text("模型Kimi引导", backend="indextts") == "模型Kimi引导"
    assert normalize_speech_text("DeepSeek 很强", backend="indextts") == "deep seek 很强"
    assert normalize_speech_text("claude Code 安装", backend="indextts") == "Claude Code 安装"


def test_latin_brand_rules_for_edge():
    assert normalize_speech_text("VibeCoding", backend="edge") == "vibe coding"


def test_legacy_phonetic_revert():
    corrupted = "还在问怎么入行 外波抠丁？工具 外波 start，学会了外波抠丁。"
    fixed = normalize_speech_text(corrupted, backend="indextts")
    assert "外波" not in fixed
    assert "vibe coding" in fixed
    assert "vibe start" in fixed

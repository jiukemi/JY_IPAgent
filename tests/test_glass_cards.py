"""Unit tests for glass overlay card helpers."""

from workflow.glass_cards import (
    format_card_display_text,
    heuristic_card_from_text,
    parse_card_display_text,
    resolve_card_position,
)


def test_heuristic_splits_punctuation():
    card = heuristic_card_from_text("先讲调色，再讲剪辑，最后导出")
    assert card["title"]
    assert len(card["bullets"]) >= 1


def test_format_roundtrip():
    text = format_card_display_text({"title": "调色", "bullets": ["对比度", "LUT — PREMIERE"]})
    parsed = parse_card_display_text(text)
    assert parsed["title"] == "调色"
    assert "对比度" in parsed["bullets"]
    assert any("LUT" in b for b in parsed["bullets"])


def test_resolve_auto_away_from_face():
    assert resolve_card_position("auto", face_empty_side="right") == "top_right"
    assert resolve_card_position("auto", face_empty_side="left") == "top_left"
    assert resolve_card_position("bottom_left") == "bottom_left"

"""Smart HyperFrames theme / layout suggestion."""

from workflow.hyperframes import suggest_hyperframe_style


def test_suggest_bullets_for_list_text():
    sug = suggest_hyperframe_style("第一点、第二点、第三点要注意")
    assert sug["layout"] == "bullets"
    assert sug["color_keywords"] is True
    assert sug["auto_background"] is True


def test_suggest_quote_for_quoted_text():
    sug = suggest_hyperframe_style("他说「坚持就是胜利」")
    assert sug["layout"] == "quote"


def test_suggest_urgent_theme():
    sug = suggest_hyperframe_style("立刻行动，名额仅剩最后 3 个")
    assert sug["theme"] in ("dracula", "gruvbox", "tokyo_night")
    assert sug["reasons"]

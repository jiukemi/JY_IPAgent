"""Local script rewrite (structure polish); cloud LLM via providers later."""

from __future__ import annotations

import re

SENTENCE_SPLIT = re.compile(r"(?<=[。！？；!?;])\s*|[\r\n]+")


def _normalize_lines(text: str) -> list[str]:
    parts: list[str] = []
    for block in SENTENCE_SPLIT.split(text.strip()):
        block = re.sub(r"\s+", " ", block.strip())
        if block:
            parts.append(block)
    return parts


def rewrite_script(text: str, *, style: str = "口播", intensity: str = "medium") -> str:
    """Rule-based local rewrite: dedupe fillers, tighten sentences, add hook."""
    text = (text or "").strip()
    if not text:
        raise ValueError("文案不能为空")

    lines = _normalize_lines(text)
    cleaned: list[str] = []
    filler = re.compile(
        r"^(嗯|啊|呃|那个|然后呢|就是说|你知道吗|对吧|好吧)[，,、]?",
        re.I,
    )
    for line in lines:
        line = filler.sub("", line).strip()
        line = re.sub(r"[，,]{2,}", "，", line)
        if line:
            cleaned.append(line)

    if not cleaned:
        cleaned = lines or [text]

    if intensity == "light":
        return "\n".join(cleaned)

    body = cleaned
    if intensity == "strong" and len(body) > 4:
        body = body[: max(3, len(body) - 1)]

    hook = body[0]
    if not hook.endswith(("。", "！", "？", "!", "?", ";", "；")):
        hook += "。"
    rest = body[1:]
    if style == "口播" and rest:
        out = [hook, *rest]
    else:
        out = body
    return "\n".join(out)

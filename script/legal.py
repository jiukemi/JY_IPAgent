"""AI legal / compliance review for short-video scripts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from script.llm_client import chat_completion

ProgressFn = Callable[[float, str], None]

# Lightweight pre-check; LLM does the heavy lifting.
_SENSITIVE_HINTS = (
    "最好",
    "第一",
    "唯一",
    "100%",
    "国家级",
    "全网最低",
    "永久",
    "根治",
    "药到病除",
    "稳赚",
    "保本",
    "加微信",
    "私信领取",
)


@dataclass
class LegalReviewResult:
    report: str
    cleaned: str
    local_flags: list[str]


def _local_scan(text: str) -> list[str]:
    flags: list[str] = []
    for word in _SENSITIVE_HINTS:
        if word in text:
            flags.append(word)
    return flags


def _split_report_and_script(content: str) -> tuple[str, str]:
    """Parse LLM output: optional ---CLEANED--- section."""
    marker = "---CLEANED---"
    if marker in content:
        report, cleaned = content.split(marker, 1)
        return report.strip(), cleaned.strip()
    # Fallback: last paragraph as cleaned if marked
    m = re.search(r"(?:合规改写|修改后文案|建议文案)[:：]\s*\n([\s\S]+)$", content)
    if m:
        cleaned = m.group(1).strip()
        report = content[: m.start()].strip()
        return report, cleaned
    return content.strip(), ""


def legal_review_with_llm(
    cfg: dict,
    text: str,
    *,
    platform: str = "抖音",
    on_progress: ProgressFn | None = None,
) -> LegalReviewResult:
    text = (text or "").strip()
    if not text:
        raise ValueError("文案为空")

    local_flags = _local_scan(text)
    if on_progress:
        on_progress(0.15, "AI法务审查中…")

    hint = ""
    if local_flags:
        hint = f"\n本地词表命中：{', '.join(local_flags[:12])}（请重点审查）。"

    from script.prompt_store import format_legal_system

    system = format_legal_system(platform=platform)
    user = f"请审查并改写以下口播文案：{hint}\n\n{text}"

    raw = chat_completion(
        cfg,
        block="legal",
        system=system,
        user=user,
        temperature=0.3,
        on_progress=on_progress,
    )
    report, cleaned = _split_report_and_script(raw)
    if not cleaned:
        cleaned = text
    return LegalReviewResult(report=report, cleaned=cleaned, local_flags=local_flags)

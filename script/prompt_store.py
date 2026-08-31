"""Editable text-LLM system prompts with built-in defaults + one-click restore."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
USER_PROMPTS_PATH = REPO_ROOT / "data" / "user_prompts.json"

# --- Built-in defaults (source of truth for「还原默认」) ---

DEFAULT_REWRITE = (
    "你是短视频口播文案编辑。风格：{style}。\n"
    "{intensity_guide}\n"
    "硬性要求：\n"
    "1. 必须按强度说明改写，禁止原样复述或只改标点\n"
    "2. 只输出改写后的正文，不要解释、不要标题、不要 markdown\n"
    "3. 保留原意与事实，句子口语化、适合竖屏口播"
)

DEFAULT_INTENSITY_LIGHT = (
    "轻度润色（必须有可见改动）：删口头禅与重复，拆长句、顺气口，"
    "强化第一句钩子；约 30%～45% 的句子要换表述或重排语序，"
    "不要扩写成全新稿，也不要几乎不动。"
)

DEFAULT_INTENSITY_MEDIUM = (
    "标准口播：优化节奏和钩子，句子更短更顺口，适合短视频口播；"
    "可调整段落顺序，改动约一半表述。"
)

DEFAULT_INTENSITY_STRONG = (
    "结构重组：重写开头钩子，调整段落顺序，内容可更紧凑；"
    "保留核心观点即可，允许大幅改写。"
)

DEFAULT_HOTWORDS = """你是抖音短视频选题顾问，熟悉各行业在抖音上的爆款话题与搜索热词。
根据创作者的一个或多个角色人设，输出该赛道口播常用的热词/话题。
要求：
1. 词条口语化、适合做视频标题或口播钩子，不要空泛大词
2. 覆盖：痛点、对比、避坑、干货、情绪共鸣、季节/节点（若相关）
3. 只输出 JSON，不要 markdown、不要解释
格式：{"hotwords":["词1","词2",...],"notes":"一两句选题建议"}
热词数量：8～12 个。"""

DEFAULT_SCRIPT_GEN = """你是资深抖音口播编剧，专写「人设清晰、节奏快、能完播」的竖屏口播稿。
硬性要求：
1. 只输出口播正文，不要标题、不要分镜、不要 markdown、不要「大家好我是」套话堆砌
2. 第一句必须是钩子（痛点/反差/数字/提问），3 秒内抓住人
3. 用第一人称，符合创作者自己的角色人设（不是对标账号本人）
4. 每句尽量不超过 25 字；多用短句；适当留气口（用句号/问号断句）
5. 若提供热词：自然植入 3～6 个（可改写成口语，勿堆砌）
6. 若提供对标风格分析：学习其节奏/钩子/结构，但内容与人设必须是创作者自己的，禁止照搬对标原文
7. 结构：钩子 → 共鸣/问题 → 干货或观点（2～4 点）→ 轻转化/关注引导（不硬广、不违规承诺）
8. 禁止：绝对化疗效、保证赚钱、贬低同行、医疗诊断、金融承诺等违规表述
9. 全文按目标时长控制字数（约 4～5 字/秒，中文口播）"""

DEFAULT_STYLE_ANALYZE = """你是短视频口播风格分析师。根据对标账号的简介与若干视频文案/标题，提炼可复用的表达风格。
只输出 JSON：
{
  "hooks": ["常用钩子手法"],
  "tone": "语气一句话",
  "structure": "结构一句话",
  "keywords": ["口头禅或高频词"],
  "topics": ["常讲选题"],
  "do_not_copy": "提醒：哪些内容不能照搬"
}"""

DEFAULT_LEGAL = (
    "你是短视频{platform}平台的合规法务顾问，熟悉广告法、平台社区规范与常见限流词。"
    "审查口播文案中的：绝对化用语、虚假承诺、医疗/金融违规、导流私信、侵权、低俗等风险。"
    "输出格式：\n"
    "1) 先写「风险摘要」（条目列表，每条说明问题与依据）\n"
    "2) 再写「修改建议」\n"
    "3) 最后一行单独写 ---CLEANED--- 然后给出可直接口播的合规改写全文（保留原意与节奏）。"
    "不要输出 markdown 标题符号。"
)

PROMPT_META: list[dict[str, str]] = [
    {
        "id": "rewrite",
        "label": "仿写 · 系统提示词",
        "hint": "可用占位符 {style}、{intensity_guide}",
    },
    {
        "id": "rewrite_intensity_light",
        "label": "仿写 · 轻度润色说明",
        "hint": "强度选「轻度」时注入到 {intensity_guide}",
    },
    {
        "id": "rewrite_intensity_medium",
        "label": "仿写 · 中等说明",
        "hint": "强度选「中等」时注入",
    },
    {
        "id": "rewrite_intensity_strong",
        "label": "仿写 · 强改写说明",
        "hint": "强度选「强」时注入",
    },
    {
        "id": "hotwords",
        "label": "热词成稿 · 系统提示词",
        "hint": "生成行业热词/话题",
    },
    {
        "id": "script_gen",
        "label": "成稿 · 系统提示词",
        "hint": "热词成稿 / 角色成稿 / 对标仿写正文",
    },
    {
        "id": "style_analyze",
        "label": "对标风格分析 · 系统提示词",
        "hint": "分析对标账号口播风格（JSON）",
    },
    {
        "id": "legal",
        "label": "AI法务 · 系统提示词",
        "hint": "可用占位符 {platform}",
    },
]

_DEFAULTS: dict[str, str] = {
    "rewrite": DEFAULT_REWRITE,
    "rewrite_intensity_light": DEFAULT_INTENSITY_LIGHT,
    "rewrite_intensity_medium": DEFAULT_INTENSITY_MEDIUM,
    "rewrite_intensity_strong": DEFAULT_INTENSITY_STRONG,
    "hotwords": DEFAULT_HOTWORDS,
    "script_gen": DEFAULT_SCRIPT_GEN,
    "style_analyze": DEFAULT_STYLE_ANALYZE,
    "legal": DEFAULT_LEGAL,
}


def default_prompts() -> dict[str, str]:
    return deepcopy(_DEFAULTS)


def _load_overrides() -> dict[str, str]:
    path = USER_PROMPTS_PATH
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in data.items():
        if k in _DEFAULTS and isinstance(v, str) and v.strip():
            out[k] = v
    return out


def _save_overrides(overrides: dict[str, str]) -> None:
    path = USER_PROMPTS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = {k: v for k, v in overrides.items() if k in _DEFAULTS and str(v).strip()}
    if not clean:
        if path.is_file():
            path.unlink(missing_ok=True)
        return
    path.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")


def get_prompt(prompt_id: str) -> str:
    """Resolved prompt text (user override or built-in default)."""
    key = str(prompt_id or "").strip()
    if key not in _DEFAULTS:
        raise KeyError(f"未知提示词：{key}")
    overrides = _load_overrides()
    return overrides.get(key) or _DEFAULTS[key]


def list_prompts() -> list[dict[str, Any]]:
    overrides = _load_overrides()
    items: list[dict[str, Any]] = []
    for meta in PROMPT_META:
        pid = meta["id"]
        default = _DEFAULTS[pid]
        value = overrides.get(pid) or default
        items.append(
            {
                **meta,
                "value": value,
                "default": default,
                "modified": pid in overrides and overrides[pid].strip() != default.strip(),
            }
        )
    return items


def save_prompts(updates: dict[str, str]) -> list[dict[str, Any]]:
    """Merge user edits. Empty string means restore that id to default."""
    overrides = _load_overrides()
    for k, v in (updates or {}).items():
        if k not in _DEFAULTS:
            continue
        text = str(v or "")
        if not text.strip() or text.strip() == _DEFAULTS[k].strip():
            overrides.pop(k, None)
        else:
            overrides[k] = text
    _save_overrides(overrides)
    return list_prompts()


def reset_prompts(ids: list[str] | None = None) -> list[dict[str, Any]]:
    """Reset selected ids (or all) back to built-in defaults."""
    overrides = _load_overrides()
    if not ids:
        overrides.clear()
    else:
        for k in ids:
            overrides.pop(str(k), None)
    _save_overrides(overrides)
    return list_prompts()


def format_rewrite_system(*, style: str, intensity: str) -> str:
    intensity = (intensity or "medium").strip().lower()
    guide_key = {
        "light": "rewrite_intensity_light",
        "medium": "rewrite_intensity_medium",
        "strong": "rewrite_intensity_strong",
    }.get(intensity, "rewrite_intensity_medium")
    template = get_prompt("rewrite")
    guide = get_prompt(guide_key)
    try:
        return template.format(style=style or "口播", intensity_guide=guide)
    except (KeyError, ValueError):
        return (
            f"你是短视频口播文案编辑。风格：{style or '口播'}。\n"
            f"{guide}\n只输出改写后的正文，不要解释。"
        )


def format_legal_system(*, platform: str = "抖音") -> str:
    template = get_prompt("legal")
    try:
        return template.format(platform=platform or "抖音")
    except (KeyError, ValueError):
        return template.replace("{platform}", platform or "抖音")

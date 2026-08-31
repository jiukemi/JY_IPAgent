"""Generate口播文案 from multi-role identity + hotwords + optional competitor style."""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from script.llm_client import chat_completion, chat_completion_stream, has_llm_key
from script.prompt_store import get_prompt

ProgressFn = Callable[[float, str], None]
DeltaFn = Callable[[str], None]
StopFn = Callable[[], bool]


def _hotword_system() -> str:
    return get_prompt("hotwords")


def _script_system() -> str:
    return get_prompt("script_gen")


def _style_system() -> str:
    return get_prompt("style_analyze")


def _emit(on_progress: ProgressFn | None, pct: float, desc: str) -> None:
    if on_progress:
        on_progress(pct, desc)


def _parse_json_object(raw: str) -> dict:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        return json.loads(m.group(0))
    raise RuntimeError(f"模型返回无法解析为 JSON：{text[:200]}")


def _require_llm(cfg: dict) -> None:
    if not has_llm_key(cfg, "rewrite"):
        raise RuntimeError(
            "未配置文本大模型 Key。\n"
            "请在设置 → ① 文案 填写 DeepSeek API Key（与仿写/热词/对标成稿共用）。"
        )


def normalize_roles(roles: list[dict] | None, *, fallback: dict | None = None) -> list[dict]:
    """Normalize role dicts; optionally build one role from legacy flat fields."""
    out: list[dict] = []
    for i, r in enumerate(roles or []):
        if not isinstance(r, dict):
            continue
        identity = str(r.get("identity") or "").strip()
        profession = str(r.get("profession") or "").strip()
        if not identity and not profession:
            continue
        out.append(
            {
                "id": str(r.get("id") or f"role_{i+1}"),
                "label": str(r.get("label") or identity or profession or f"角色{i+1}")[:40],
                "identity": identity,
                "profession": profession,
                "industry": str(r.get("industry") or "").strip(),
                "product": str(r.get("product") or "").strip(),
                "audience": str(r.get("audience") or "").strip(),
                "selling_points": str(r.get("selling_points") or "").strip(),
            }
        )
    if out:
        return out
    fb = fallback or {}
    identity = str(fb.get("identity") or "").strip()
    profession = str(fb.get("profession") or "").strip()
    if identity or profession:
        return [
            {
                "id": "role_1",
                "label": identity or profession,
                "identity": identity,
                "profession": profession,
                "industry": str(fb.get("industry") or "").strip(),
                "product": str(fb.get("product") or "").strip(),
                "audience": str(fb.get("audience") or "").strip(),
                "selling_points": str(fb.get("selling_points") or "").strip(),
            }
        ]
    return []


def _format_roles_block(roles: list[dict], *, mix: bool) -> str:
    if not roles:
        return "（未填角色）"
    if not mix:
        r = roles[0]
        return (
            f"- 当前角色：{r.get('label')}\n"
            f"- 身份：{r.get('identity') or '创作者'}\n"
            f"- 职业：{r.get('profession') or '（未填）'}\n"
            f"- 行业：{r.get('industry') or '（按职业推断）'}\n"
            f"- 产品/服务：{r.get('product') or '无具体产品，偏认知分享'}\n"
            f"- 卖点：{r.get('selling_points') or '专业、真诚、实用'}\n"
            f"- 受众：{r.get('audience') or '对该赛道感兴趣的抖音用户'}\n"
        )
    lines = ["- 多角色混合（同一条口播里自然切换视角，不要生硬列举）："]
    for r in roles:
        lines.append(
            f"  · {r.get('label')}: 身份={r.get('identity') or '-'} / 职业={r.get('profession') or '-'} / "
            f"行业={r.get('industry') or '-'} / 卖点={r.get('selling_points') or '-'}"
        )
    aud = next((r.get("audience") for r in roles if r.get("audience")), "") or "泛流量"
    lines.append(f"- 综合受众：{aud}")
    return "\n".join(lines)


def suggest_hotwords(
    cfg: dict,
    *,
    identity: str = "",
    profession: str = "",
    industry: str = "",
    product: str = "",
    audience: str = "",
    roles: list[dict] | None = None,
    mix_roles: bool = False,
    on_progress: ProgressFn | None = None,
) -> dict:
    _require_llm(cfg)
    role_list = normalize_roles(
        roles,
        fallback={
            "identity": identity,
            "profession": profession,
            "industry": industry,
            "product": product,
            "audience": audience,
        },
    )
    if not role_list:
        raise ValueError("请至少填写一个角色的身份或职业")

    user = (
        f"【创作者人设】\n{_format_roles_block(role_list, mix=mix_roles or len(role_list) > 1)}\n"
        "平台：抖音短视频口播\n"
        "请给出该赛道近期适合拍的热词/话题。"
    )
    _emit(on_progress, 0.2, "正在生成行业热词…")
    raw = chat_completion(
        cfg,
        block="rewrite",
        system=_hotword_system(),
        user=user,
        temperature=0.8,
    )
    data = _parse_json_object(raw)
    words = [str(w).strip() for w in (data.get("hotwords") or []) if str(w).strip()]
    if not words:
        raise RuntimeError("未得到有效热词，请重试或手动填写")
    _emit(on_progress, 1.0, "热词就绪")
    return {
        "hotwords": words[:12],
        "notes": str(data.get("notes") or "").strip(),
        "source": "llm_trend",
    }


def analyze_competitor_style(
    cfg: dict,
    *,
    nickname: str,
    signature: str,
    samples: list[dict[str, Any]],
    on_progress: ProgressFn | None = None,
) -> dict:
    _require_llm(cfg)
    blocks = []
    for i, s in enumerate(samples, 1):
        pick = s.get("pick") or ""
        title = (s.get("title") or "").strip()
        script = (s.get("script") or title).strip()
        blocks.append(
            f"样本{i}（{pick or '视频'}）\n标题/简介：{title or '（无）'}\n口播/文案：\n{script[:1200] or '（无）'}"
        )
    user = (
        f"对标昵称：{nickname or '未知'}\n"
        f"对标简介：{signature or '（无）'}\n\n"
        + "\n\n".join(blocks)
        + "\n\n请提炼风格，供创作者学习手法（非照搬内容）。"
    )
    _emit(on_progress, 0.4, "分析对标口播风格…")
    raw = chat_completion(cfg, block="rewrite", system=_style_system(), user=user, temperature=0.5)
    style = _parse_json_object(raw)
    _emit(on_progress, 1.0, "风格分析完成")
    return style


def generate_script_from_profile(
    cfg: dict,
    *,
    identity: str = "",
    profession: str = "",
    industry: str = "",
    product: str = "",
    audience: str = "",
    selling_points: str = "",
    roles: list[dict] | None = None,
    mix_roles: bool = False,
    duration_sec: int = 45,
    hotwords: list[str] | None = None,
    extra: str = "",
    auto_hotwords: bool = False,
    competitor_style: dict | None = None,
    competitor_meta: dict | None = None,
    on_progress: ProgressFn | None = None,
    on_delta: DeltaFn | None = None,
    should_stop: StopFn | None = None,
    continue_from: str = "",
) -> dict:
    _require_llm(cfg)
    role_list = normalize_roles(
        roles,
        fallback={
            "identity": identity,
            "profession": profession,
            "industry": industry,
            "product": product,
            "audience": audience,
            "selling_points": selling_points,
        },
    )
    if not role_list:
        raise ValueError("请至少填写一个角色的身份或职业")

    duration_sec = max(20, min(180, int(duration_sec or 45)))
    target_chars = int(duration_sec * 4.5)
    words = [w.strip() for w in (hotwords or []) if w and str(w).strip()]
    notes = ""

    if auto_hotwords and not (continue_from or "").strip():
        _emit(on_progress, 0.1, "先拉取行业热词…")
        hw = suggest_hotwords(
            cfg,
            roles=role_list,
            mix_roles=mix_roles,
            on_progress=lambda p, d: _emit(on_progress, 0.1 + p * 0.3, d),
        )
        # Prefer freshly pulled words; keep any manual extras
        pulled = hw["hotwords"]
        words = list(dict.fromkeys([*pulled, *words]))
        notes = hw.get("notes") or ""

    user = (
        f"【创作者自己的人设（必须用这个人设写，不是对标）】\n"
        f"{_format_roles_block(role_list, mix=mix_roles)}\n"
    )
    if words:
        user += f"\n【热词（请自然融入）】\n{'、'.join(words)}\n"
    if competitor_style:
        meta = competitor_meta or {}
        user += (
            f"\n【对标账号风格（只学手法，内容必须原创）】\n"
            f"- 对标：{meta.get('nickname') or '未知'}\n"
            f"- 简介：{meta.get('signature') or '（无）'}\n"
            f"- 语气：{competitor_style.get('tone') or ''}\n"
            f"- 结构：{competitor_style.get('structure') or ''}\n"
            f"- 钩子手法：{'；'.join(competitor_style.get('hooks') or [])}\n"
            f"- 高频词：{'、'.join(competitor_style.get('keywords') or [])}\n"
            f"- 常讲选题：{'、'.join(competitor_style.get('topics') or [])}\n"
            f"- 禁忌：{competitor_style.get('do_not_copy') or '禁止照搬对标原文与个人经历'}\n"
        )
    user += (
        f"\n【规格】\n"
        f"- 目标时长：约 {duration_sec} 秒\n"
        f"- 目标字数：约 {target_chars} 字（可 ±15%）\n"
        f"- 平台：抖音竖屏口播\n"
    )
    if (extra or "").strip():
        user += f"\n【额外要求】\n{(extra or '').strip()}\n"
    if notes:
        user += f"\n【选题参考】\n{notes}\n"

    _emit(on_progress, 0.7, "正在流式生成专属口播文稿…")
    prefix = (continue_from or "").strip()
    script = chat_completion_stream(
        cfg,
        block="rewrite",
        system=_script_system(),
        user=user,
        temperature=0.75,
        on_progress=on_progress,
        on_delta=on_delta,
        should_stop=should_stop,
        continue_from=prefix,
    )
    if prefix and script and not script.startswith(prefix[: min(20, len(prefix))]):
        script = prefix + script
    elif prefix and not script:
        script = prefix
    script = script.strip()
    if script.startswith("```"):
        script = re.sub(r"^```(?:\w+)?\s*", "", script)
        script = re.sub(r"\s*```$", "", script).strip()
    stopped = bool(should_stop and should_stop())
    _emit(on_progress, 1.0 if not stopped else 0.85, "已暂停" if stopped else "文稿已生成")
    return {
        "script": script,
        "hotwords": words,
        "notes": notes,
        "duration_sec": duration_sec,
        "target_chars": target_chars,
        "competitor_style": competitor_style or {},
        "paused": stopped,
    }

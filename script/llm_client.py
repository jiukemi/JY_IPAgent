"""OpenAI-compatible chat completion helper (DeepSeek / DashScope / etc.)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

ProgressFn = Callable[[float, str], None]
DeltaFn = Callable[[str], None]
StopFn = Callable[[], bool]


def cloud_block(cfg: dict) -> dict:
    return (cfg.get("script") or {}).get("cloud") or {}


def sub_block(cfg: dict, name: str) -> dict:
    return dict(cloud_block(cfg).get(name) or {})


def resolve_llm_settings(cfg: dict, name: str) -> dict:
    """Merge named block (rewrite / legal) with rewrite defaults."""
    primary = sub_block(cfg, name)
    fallback = sub_block(cfg, "rewrite")
    merged = {**fallback, **{k: v for k, v in primary.items() if v not in (None, "")}}
    api_key = (
        merged.get("api_key")
        or os.environ.get("DEEPSEEK_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or ""
    ).strip()
    return {
        "api_key": api_key,
        "base_url": (merged.get("base_url") or "https://api.deepseek.com/v1").rstrip("/"),
        "model": merged.get("model") or "deepseek-chat",
        "timeout_sec": float(merged.get("timeout_sec") or 120),
    }


def has_llm_key(cfg: dict, name: str = "rewrite") -> bool:
    return bool(resolve_llm_settings(cfg, name).get("api_key"))


def _build_messages(
    system: str,
    user: str,
    *,
    continue_from: str = "",
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    draft = (continue_from or "").strip()
    if draft:
        messages.append({"role": "assistant", "content": draft})
        messages.append(
            {
                "role": "user",
                "content": "请从上文断点继续写完，不要重复已有内容，直接续写即可。",
            }
        )
    return messages


def chat_completion(
    cfg: dict,
    *,
    block: str,
    system: str,
    user: str,
    temperature: float = 0.7,
    on_progress: ProgressFn | None = None,
    continue_from: str = "",
) -> str:
    """Non-streaming convenience wrapper (still uses stream under the hood when possible)."""
    return chat_completion_stream(
        cfg,
        block=block,
        system=system,
        user=user,
        temperature=temperature,
        on_progress=on_progress,
        continue_from=continue_from,
    )


def chat_completion_stream(
    cfg: dict,
    *,
    block: str,
    system: str,
    user: str,
    temperature: float = 0.7,
    on_progress: ProgressFn | None = None,
    on_delta: DeltaFn | None = None,
    should_stop: StopFn | None = None,
    continue_from: str = "",
) -> str:
    settings = resolve_llm_settings(cfg, block)
    api_key = settings["api_key"]
    if not api_key:
        label = "仿写" if block == "rewrite" else "AI法务"
        raise RuntimeError(
            f"未配置 {label} API Key。\n"
            f"请在 config.yaml → script.cloud.{block}.api_key 填写 DeepSeek Key，"
            "或设置环境变量 DEEPSEEK_API_KEY。"
        )

    payload: dict[str, Any] = {
        "model": settings["model"],
        "messages": _build_messages(system, user, continue_from=continue_from),
        "temperature": temperature,
        "stream": True,
    }
    url = f"{settings['base_url']}/chat/completions"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "Accept": "text/event-stream",
        },
        method="POST",
    )

    pieces: list[str] = []
    try:
        with urllib.request.urlopen(req, timeout=settings["timeout_sec"]) as resp:
            while True:
                if should_stop and should_stop():
                    break
                raw = resp.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").strip()
                if not line or line.startswith(":"):
                    continue
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = (choices[0].get("delta") or {}).get("content") or ""
                if not delta:
                    continue
                pieces.append(delta)
                if on_delta:
                    on_delta(delta)
                if on_progress and len(pieces) % 8 == 0:
                    on_progress(min(0.95, 0.55 + len("".join(pieces)) / 8000), "流式生成中…")
    except urllib.error.HTTPError as exc:
        err = exc.read().decode("utf-8", errors="replace")
        # Some providers reject stream — fall back to non-stream once.
        if "stream" in err.lower() or exc.code in (400, 404, 422):
            return _chat_completion_once(
                cfg,
                block=block,
                system=system,
                user=user,
                temperature=temperature,
                on_progress=on_progress,
                continue_from=continue_from,
            )
        raise RuntimeError(f"LLM API HTTP {exc.code}: {err[:800]}") from exc

    content = "".join(pieces).strip()
    if not content and not (should_stop and should_stop()):
        # Empty stream — try classic completion
        return _chat_completion_once(
            cfg,
            block=block,
            system=system,
            user=user,
            temperature=temperature,
            on_progress=on_progress,
            continue_from=continue_from,
        )
    if on_progress and not (should_stop and should_stop()):
        on_progress(1.0, "完成")
    return content


def _chat_completion_once(
    cfg: dict,
    *,
    block: str,
    system: str,
    user: str,
    temperature: float = 0.7,
    on_progress: ProgressFn | None = None,
    continue_from: str = "",
) -> str:
    settings = resolve_llm_settings(cfg, block)
    api_key = settings["api_key"]
    payload = {
        "model": settings["model"],
        "messages": _build_messages(system, user, continue_from=continue_from),
        "temperature": temperature,
    }
    url = f"{settings['base_url']}/chat/completions"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=settings["timeout_sec"]) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        err = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LLM API HTTP {exc.code}: {err[:800]}") from exc

    choices = body.get("choices") or []
    if not choices:
        raise RuntimeError(f"LLM 无返回: {json.dumps(body, ensure_ascii=False)[:400]}")
    content = choices[0].get("message", {}).get("content", "").strip()
    if not content:
        raise RuntimeError("LLM 返回内容为空")
    if on_progress:
        on_progress(1.0, "完成")
    return content

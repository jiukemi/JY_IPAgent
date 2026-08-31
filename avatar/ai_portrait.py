"""Generate portrait images via DashScope Wanx (reuse qwen3_tts API key)."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from tts.qwen3_tts import qwen3_block


def _api_key(cfg: dict) -> str:
    key = (qwen3_block(cfg).get("api_key") or "").strip()
    if not key:
        raise ValueError("未配置 DashScope API Key，请在全局设置填写 qwen3_tts.api_key")
    return key


def _base_url(cfg: dict) -> str:
    return (qwen3_block(cfg).get("base_url") or "https://dashscope.aliyuncs.com/api/v1").strip().rstrip("/")


def generate_portrait(cfg: dict, prompt: str, out_path: Path, *, size: str = "768*768") -> Path:
    """Text-to-image portrait for SadTalker avatar registration."""
    prompt = (prompt or "").strip()
    if not prompt:
        raise ValueError("请输入角色描述")

    full_prompt = (
        f"{prompt}，正面半身肖像，清晰面部，纯色或虚化背景，"
        "适合数字人口播，写实风格，无文字无水印"
    )
    key = _api_key(cfg)
    base = _base_url(cfg)
    submit_url = f"{base}/services/aigc/text2image/image-synthesis"

    body = json.dumps(
        {
            "model": "wanx-v1",
            "input": {"prompt": full_prompt},
            "parameters": {"size": size, "n": 1},
        },
        ensure_ascii=False,
    ).encode("utf-8")

    req = urllib.request.Request(
        submit_url,
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "X-DashScope-Async": "enable",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"AI 生图请求失败: {detail}") from exc

    task_id = (payload.get("output") or {}).get("task_id")
    if not task_id:
        raise RuntimeError(f"AI 生图未返回任务 ID: {payload}")

    query_url = f"{base}/tasks/{task_id}"
    deadline = time.time() + 120
    while time.time() < deadline:
        time.sleep(2)
        qreq = urllib.request.Request(
            query_url,
            headers={"Authorization": f"Bearer {key}"},
            method="GET",
        )
        with urllib.request.urlopen(qreq, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        status = (result.get("output") or {}).get("task_status") or result.get("task_status")
        if status == "SUCCEEDED":
            results = (result.get("output") or {}).get("results") or []
            if not results:
                raise RuntimeError("AI 生图成功但未返回图片")
            url = results[0].get("url")
            if not url:
                raise RuntimeError("AI 生图结果缺少 URL")
            img_req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(img_req, timeout=60) as img_resp:
                data = img_resp.read()
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(data)
            if out_path.stat().st_size < 500:
                raise RuntimeError("AI 生图文件无效")
            return out_path
        if status in ("FAILED", "CANCELED"):
            msg = (result.get("output") or {}).get("message") or result.get("message") or status
            raise RuntimeError(f"AI 生图失败: {msg}")

    raise RuntimeError("AI 生图超时，请稍后重试")

"""Share-link API adapters — CDN resolve vs transcript are separate roles.

CDN (去水印): link → video_url + title/cover — for preview/download only.
Transcript (ASR): link or media → spoken script text — never use title/desc as transcript.

Public ids are protocol shapes (no vendor names in UI). Legacy ids still accepted.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Literal

Role = Literal["cdn", "transcript"]

# Neutral protocol ids (preferred in config / settings UI)
CDN_PROTOCOL_NONE = "none"
CDN_PROTOCOL_FORM_KEY_URL = "cdn_form_key_url"  # GET/query: key + url（包月默认地址）
CDN_PROTOCOL_FORM_KEY_URL_TIMES = "cdn_form_key_url_times"  # 同协议，计次默认地址
CDN_PROTOCOL_AGG_VIDEO = "cdn_agg_video"  # Bearer + JSON {url} 单视频聚合去水印
CDN_PROTOCOL_AGG_PROFILE = "cdn_agg_profile"  # Bearer + JSON {url} 主页批量（取首条视频）
CDN_PROTOCOL_JSON_URL = "cdn_json_url"  # POST JSON {url}

ASR_PROTOCOL_SYNC_VIDEOURL = "asr_sync_videourl"  # form: key + videoUrl（同步）
ASR_PROTOCOL_SYNC_CONTENT = "asr_sync_content"  # form: key + content
ASR_PROTOCOL_ASYNC_TIME = "asr_async_time"  # 异步计时：提交 + 轮询
ASR_PROTOCOL_ASYNC_COUNT = "asr_async_count"  # 异步计次：提交 + 轮询
ASR_PROTOCOL_ASYNC_POLL = "asr_async_poll"  # 兼容旧 id → 计时
ASR_PROTOCOL_CUSTOM_JSON = "asr_custom_json"  # POST JSON {url}

ASR_ASYNC_PROTOCOLS = frozenset(
    {ASR_PROTOCOL_ASYNC_TIME, ASR_PROTOCOL_ASYNC_COUNT, ASR_PROTOCOL_ASYNC_POLL}
)

# Legacy → canonical (keep old yaml working)
_CDN_ALIASES: dict[str, str] = {
    "none": CDN_PROTOCOL_NONE,
    CDN_PROTOCOL_NONE: CDN_PROTOCOL_NONE,
    CDN_PROTOCOL_FORM_KEY_URL: CDN_PROTOCOL_FORM_KEY_URL,
    "17zhiling_watermark": CDN_PROTOCOL_FORM_KEY_URL,
    CDN_PROTOCOL_FORM_KEY_URL_TIMES: CDN_PROTOCOL_FORM_KEY_URL_TIMES,
    CDN_PROTOCOL_AGG_VIDEO: CDN_PROTOCOL_AGG_VIDEO,
    CDN_PROTOCOL_AGG_PROFILE: CDN_PROTOCOL_AGG_PROFILE,
    CDN_PROTOCOL_JSON_URL: CDN_PROTOCOL_JSON_URL,
    "generic": CDN_PROTOCOL_JSON_URL,
    "local_share": "local_share",
    "browser_share": "browser_share",
    "tenapi": "tenapi",
}

_ASR_ALIASES: dict[str, str] = {
    ASR_PROTOCOL_SYNC_VIDEOURL: ASR_PROTOCOL_SYNC_VIDEOURL,
    "17zhiling_asr": ASR_PROTOCOL_SYNC_VIDEOURL,
    ASR_PROTOCOL_SYNC_CONTENT: ASR_PROTOCOL_SYNC_CONTENT,
    "kuhuyun": ASR_PROTOCOL_SYNC_CONTENT,
    ASR_PROTOCOL_ASYNC_TIME: ASR_PROTOCOL_ASYNC_TIME,
    ASR_PROTOCOL_ASYNC_COUNT: ASR_PROTOCOL_ASYNC_COUNT,
    ASR_PROTOCOL_ASYNC_POLL: ASR_PROTOCOL_ASYNC_TIME,
    ASR_PROTOCOL_CUSTOM_JSON: ASR_PROTOCOL_CUSTOM_JSON,
    "generic": ASR_PROTOCOL_CUSTOM_JSON,
    "local_whisper": "local_whisper",
    "funasr": "funasr",
}

CDN_PROVIDERS = frozenset(_CDN_ALIASES.keys()) | frozenset(_CDN_ALIASES.values())
TRANSCRIPT_PROVIDERS = frozenset(_ASR_ALIASES.keys()) | frozenset(_ASR_ALIASES.values())

BUILTIN_ENDPOINTS: dict[str, str] = {
    ASR_PROTOCOL_SYNC_VIDEOURL: "https://api.17zhiling.com/api/asr/parse-video-sync",
    "17zhiling_asr": "https://api.17zhiling.com/api/asr/parse-video-sync",
    ASR_PROTOCOL_SYNC_CONTENT: "https://api.kuhuyun.com/api/aibasic/videoanalysis",
    "kuhuyun": "https://api.kuhuyun.com/api/aibasic/videoanalysis",
    ASR_PROTOCOL_ASYNC_TIME: "https://api.17zhiling.com/api/asr/parse-video-url-time",
    ASR_PROTOCOL_ASYNC_COUNT: "https://api.17zhiling.com/api/asr/parse-video-url-times",
    ASR_PROTOCOL_ASYNC_POLL: "https://api.17zhiling.com/api/asr/parse-video-url-time",
    CDN_PROTOCOL_FORM_KEY_URL: "https://api.17zhiling.com/api/video/parse-video-url",
    "17zhiling_watermark": "https://api.17zhiling.com/api/video/parse-video-url",
    CDN_PROTOCOL_FORM_KEY_URL_TIMES: "https://api.17zhiling.com/api/video/parse-video-url-times",
    CDN_PROTOCOL_AGG_VIDEO: "https://gateway.diadi.cn/api/parse",
    CDN_PROTOCOL_AGG_PROFILE: "https://gateway.diadi.cn/api/parse/user",
    "tenapi": "https://tenapi.cn/v2/video",
    CDN_PROTOCOL_JSON_URL: "",
    ASR_PROTOCOL_CUSTOM_JSON: "",
    "generic": "",
}

BUILTIN_ASR_POLL_URL = "https://api.17zhiling.com/api/asr/task-status"

PROVIDER_HELP: dict[str, str] = {
    CDN_PROTOCOL_NONE: "跳过 CDN 视频提取",
    "local_share": "本机直连解析分享短链",
    "browser_share": "本机浏览器登录态解析",
    "tenapi": "表单 url 去水印（内置备用）",
    CDN_PROTOCOL_FORM_KEY_URL: "CDN：同步 · key + url（包月）",
    CDN_PROTOCOL_FORM_KEY_URL_TIMES: "CDN：同步 · key + url（计次）",
    CDN_PROTOCOL_AGG_VIDEO: "CDN：聚合 · 单视频去水印（Bearer + url）",
    CDN_PROTOCOL_AGG_PROFILE: "CDN：聚合 · 主页批量（取首条视频）",
    "17zhiling_watermark": "CDN：同步 · key + url",
    ASR_PROTOCOL_SYNC_VIDEOURL: "ASR：同步 · 表单 key + videoUrl",
    "17zhiling_asr": "ASR：同步 · 表单 key + videoUrl",
    ASR_PROTOCOL_SYNC_CONTENT: "ASR：同步 · 表单 key + content",
    "kuhuyun": "ASR：同步 · 表单 key + content",
    ASR_PROTOCOL_ASYNC_TIME: "ASR：异步计时 · 提交 + 轮询",
    ASR_PROTOCOL_ASYNC_COUNT: "ASR：异步计次 · 提交 + 轮询",
    ASR_PROTOCOL_ASYNC_POLL: "ASR：异步 · 提交 + 轮询",
    "local_whisper": "本地 Whisper",
    "funasr": "本地 FunASR",
    CDN_PROTOCOL_JSON_URL: "CDN：自定义 JSON POST {url}",
    ASR_PROTOCOL_CUSTOM_JSON: "ASR：自定义 JSON POST {url}",
    "generic": "自定义 JSON：POST {url}",
}


def normalize_cdn_provider(provider: str) -> str:
    raw = (provider or CDN_PROTOCOL_NONE).strip().lower()
    return _CDN_ALIASES.get(raw, raw)


def normalize_transcript_provider(provider: str) -> str:
    raw = (provider or ASR_PROTOCOL_SYNC_VIDEOURL).strip().lower()
    return _ASR_ALIASES.get(raw, raw)


def _pick_str(*values: Any) -> str:
    for v in values:
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return ""


def _http_request(
    url: str,
    *,
    method: str = "POST",
    form: dict[str, str] | None = None,
    json_body: dict | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 120.0,
) -> dict:
    hdrs = dict(headers or {})
    data: bytes | None = None
    if json_body is not None:
        hdrs.setdefault("Content-Type", "application/json")
        hdrs.setdefault("Accept", "application/json")
        data = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
    elif form is not None:
        hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")
        data = urllib.parse.urlencode(form).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        err = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"API HTTP {exc.code}: {err[:800]}") from exc
    if not body.strip():
        return {}
    parsed = json.loads(body)
    if not isinstance(parsed, dict):
        return {"data": parsed}
    code = parsed.get("code")
    if code not in (None, 0, 200, "0", "200"):
        raise RuntimeError(str(parsed.get("message") or parsed.get("msg") or f"code={code}"))
    return parsed


def _prompt_list_video_url(data: dict) -> str:
    for item in data.get("prompt") or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "")
        if "下载" in title or "视频" in title:
            url = _pick_str(item.get("prompt"))
            if url.startswith("http"):
                return url
    return ""


def _unwrap_dict(raw: dict) -> dict:
    data = raw.get("data")
    if isinstance(data, dict):
        return data
    if isinstance(data, str):
        return {"text": data.strip()}
    for key in ("result", "payload"):
        inner = raw.get(key)
        if isinstance(inner, dict):
            return inner
    return raw


def _extract_transcript_fields(data: dict, raw: dict) -> str:
    if isinstance(raw.get("data"), str):
        return raw["data"].strip()
    return _pick_str(
        data.get("text"),
        data.get("resultText"),
        data.get("script"),
        data.get("content"),
        data.get("asr_text"),
        data.get("transcript"),
    )


def _extract_video_fields(data: dict) -> str:
    return _pick_str(
        data.get("video_url"),
        data.get("videoUrl"),
        data.get("video"),
        data.get("cdn_url"),
        data.get("cdnUrl"),
        data.get("play_url"),
        data.get("url"),
        _prompt_list_video_url(data),
    )


def _call_cdn_form_key_url(url: str, api_key: str, share_url: str, timeout: float) -> dict:
    qs = urllib.parse.urlencode({"key": api_key, "url": share_url})
    sep = "&" if "?" in url else "?"
    raw = _http_request(f"{url}{sep}{qs}", method="GET", timeout=timeout)
    data = _unwrap_dict(raw)
    videos = data.get("videosList") or data.get("videos") or []
    video_url = _extract_video_fields(data)
    if not video_url and isinstance(videos, list) and videos:
        first = videos[0]
        if isinstance(first, str):
            video_url = first.strip()
        elif isinstance(first, dict):
            video_url = _pick_str(first.get("url"), first.get("video"))
    return {
        "video_url": video_url,
        "text": "",
        "title": _pick_str(data.get("title"), data.get("desc"), data.get("name")),
    }


def _resolve_asr_poll_url(submit_url: str, extra: dict) -> str:
    poll = _pick_str(extra.get("poll_url"), extra.get("status_url"))
    if poll:
        return poll
    # Same host as submit → /api/asr/task-status
    try:
        parts = urllib.parse.urlsplit(submit_url)
        if parts.scheme and parts.netloc:
            return urllib.parse.urlunsplit(
                (parts.scheme, parts.netloc, "/api/asr/task-status", "", "")
            )
    except Exception:
        pass
    return BUILTIN_ASR_POLL_URL


def _extract_task_id(raw: dict) -> str:
    data = raw.get("data")
    if isinstance(data, str) and data.strip():
        return data.strip()
    if isinstance(data, dict):
        return _pick_str(data.get("taskId"), data.get("task_id"), data.get("id"))
    return _pick_str(raw.get("taskId"), raw.get("task_id"))


def _call_asr_async_poll(
    *,
    submit_url: str,
    poll_url: str,
    api_key: str,
    share_url: str,
    extra: dict,
    timeout: float,
) -> dict:
    """Submit key+videoUrl → taskId, then poll task-status until SUCCESS/FAIL."""
    form = {"key": api_key, "videoUrl": share_url}
    cb = _pick_str(extra.get("callbackUrl"), extra.get("callback_url"))
    if cb:
        form["callbackUrl"] = cb
    raw = _http_request(submit_url, form=form, timeout=min(timeout, 60.0))
    task_id = _extract_task_id(raw)
    if not task_id:
        raise RuntimeError(f"异步 ASR 未返回任务 id：{raw!r}")

    poll_interval = float(extra.get("poll_interval_sec") or 2.0)
    poll_interval = max(1.0, min(poll_interval, 10.0))
    deadline = time.monotonic() + max(float(timeout), 60.0)
    last_schedule = ""

    while time.monotonic() < deadline:
        status_raw = _http_request(
            poll_url,
            form={"key": api_key, "taskId": task_id},
            timeout=min(60.0, max(15.0, timeout / 4)),
        )
        data = status_raw.get("data")
        if not isinstance(data, dict):
            data = _unwrap_dict(status_raw)
        schedule = _pick_str(data.get("schedule"), data.get("status")).upper()
        last_schedule = schedule or last_schedule
        if schedule in ("SUCCESS", "SUCCEED", "DONE", "COMPLETED", "OK"):
            text = _pick_str(
                data.get("content"),
                data.get("text"),
                data.get("resultText"),
                data.get("script"),
            )
            if not text:
                raise RuntimeError(f"异步 ASR 成功但无文案（taskId={task_id}）")
            return {
                "video_url": _extract_video_fields(data),
                "text": text,
                "title": _pick_str(data.get("title"), data.get("videoDesc")),
            }
        if schedule in ("FAIL", "FAILED", "ERROR"):
            raise RuntimeError(
                f"异步 ASR 失败（taskId={task_id}，schedule={schedule}）："
                f"{data.get('msg') or data.get('message') or status_raw.get('msg') or ''}"
            )
        time.sleep(poll_interval)

    raise RuntimeError(
        f"异步 ASR 超时（taskId={task_id}，最后状态={last_schedule or '未知'}，"
        f"已等待 {int(max(timeout, 60))}s）"
    )


def _bearer_headers(api_key: str, headers: dict | None = None) -> dict[str, str]:
    out = dict(headers or {})
    key = (api_key or "").strip()
    if not key:
        return out
    # Don't override an explicit Authorization from caller.
    has_auth = any(k.lower() == "authorization" for k in out)
    if not has_auth:
        out["Authorization"] = key if key.lower().startswith("bearer ") else f"Bearer {key}"
    return out


def _first_media_url(items: Any) -> str:
    if isinstance(items, str) and items.startswith("http"):
        return items.strip()
    if not isinstance(items, list):
        return ""
    for item in items:
        if isinstance(item, str) and item.startswith("http"):
            return item.strip()
        if isinstance(item, dict):
            u = _pick_str(
                item.get("url"),
                item.get("video"),
                item.get("video_url"),
                item.get("videoUrl"),
                item.get("play_url"),
                item.get("playUrl"),
            )
            if u.startswith("http"):
                return u
    return ""


def _extract_agg_parse_item(data: dict) -> dict:
    """Map gateway /api/parse (and list item) payload → video_url / text / title."""
    video_url = _first_media_url(data.get("video"))
    if not video_url:
        video_url = _extract_video_fields(data)
    title = _pick_str(data.get("title"), data.get("text"))
    text = _pick_str(data.get("text"))
    # Prefer dedicated title when present; keep text for optional downstream use.
    if data.get("title"):
        title = _pick_str(data.get("title"))
    return {
        "video_url": video_url,
        "text": text if text != title else "",
        "title": title,
    }


def _call_cdn_agg_video(
    url: str,
    api_key: str,
    share_url: str,
    extra: dict,
    headers: dict | None,
    timeout: float,
) -> dict:
    body: dict[str, Any] = {"url": share_url}
    if extra.get("is_title") is not None:
        body["is_title"] = int(extra["is_title"])
    dm = _pick_str(extra.get("dm_id"), extra.get("dmId"))
    if dm:
        body["dm_id"] = dm
    hdrs = _bearer_headers(api_key, headers)
    try:
        raw = _http_request(url, json_body=body, headers=hdrs, timeout=timeout)
    except RuntimeError:
        # Some gateways expect form instead of JSON.
        form = {k: str(v) for k, v in body.items()}
        raw = _http_request(url, form=form, headers=hdrs, timeout=timeout)
    data = _unwrap_dict(raw)
    out = _extract_agg_parse_item(data if isinstance(data, dict) else {})
    if not out.get("video_url"):
        raise RuntimeError(f"聚合单视频未返回 video 直链：{raw!r}")
    return out


def _call_cdn_agg_profile(
    url: str,
    api_key: str,
    share_url: str,
    extra: dict,
    headers: dict | None,
    timeout: float,
) -> dict:
    body: dict[str, Any] = {"url": share_url}
    cursor = _pick_str(extra.get("max_cursor"), extra.get("maxCursor"))
    if cursor:
        body["max_cursor"] = cursor
    if extra.get("number") is not None:
        try:
            body["number"] = max(1, min(int(extra["number"]), 30))
        except (TypeError, ValueError):
            body["number"] = 10
    else:
        body["number"] = 10
    hdrs = _bearer_headers(api_key, headers)
    try:
        raw = _http_request(url, json_body=body, headers=hdrs, timeout=timeout)
    except RuntimeError:
        form = {k: str(v) for k, v in body.items()}
        raw = _http_request(url, form=form, headers=hdrs, timeout=timeout)
    data = _unwrap_dict(raw)
    items = data.get("list") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        raise RuntimeError(f"主页解析未返回作品列表：{raw!r}")
    first = items[0] if isinstance(items[0], dict) else {}
    out = _extract_agg_parse_item(first)
    if not out.get("video_url"):
        raise RuntimeError(
            f"主页列表首条无视频直链（共 {len(items)} 条）。可改用「聚合 · 单视频」贴作品链接。"
        )
    author = data.get("author")
    if isinstance(author, dict) and not out.get("title"):
        out["title"] = _pick_str(author.get("name"), author.get("nickname"))
    return out


def _call_tenapi(url: str, share_url: str, timeout: float) -> dict:
    raw = _http_request(
        url,
        form={"url": share_url},
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        },
        timeout=timeout,
    )
    data = _unwrap_dict(raw)
    return {
        "video_url": _extract_video_fields(data),
        "text": "",
        "title": _pick_str(data.get("title")),
    }


def call_cdn_provider(
    provider: str,
    *,
    api_url: str,
    api_key: str,
    share_url: str,
    extra: dict | None = None,
    headers: dict | None = None,
    timeout: float = 120.0,
) -> dict:
    provider = normalize_cdn_provider(provider)
    if provider == CDN_PROTOCOL_NONE:
        return {"video_url": "", "text": "", "title": "", "_provider": CDN_PROTOCOL_NONE}

    url = (api_url or BUILTIN_ENDPOINTS.get(provider) or "").strip()
    _local_providers = frozenset({"local_share", "browser_share"})
    if not url and provider not in _local_providers:
        raise RuntimeError(f"CDN 协议 {provider!r} 需要填写接口地址，或使用内置默认地址。")
    if not api_key and provider in (
        CDN_PROTOCOL_FORM_KEY_URL,
        CDN_PROTOCOL_FORM_KEY_URL_TIMES,
        CDN_PROTOCOL_AGG_VIDEO,
        CDN_PROTOCOL_AGG_PROFILE,
    ):
        raise RuntimeError("该 CDN 协议需要填写 API Key（Bearer Token）。")

    extra = extra or {}

    if provider == "local_share":
        from script.local_cdn import resolve_share_cdn_local

        out = resolve_share_cdn_local(share_url, timeout=timeout)
    elif provider == "browser_share":
        from script.browser_cdn import resolve_share_cdn_browser
        from workflow.app_config import load_cfg

        cfg = (extra or {}).get("_cfg") or load_cfg()
        out = resolve_share_cdn_browser(share_url, cfg, timeout=timeout)
    elif provider in (CDN_PROTOCOL_FORM_KEY_URL, CDN_PROTOCOL_FORM_KEY_URL_TIMES):
        out = _call_cdn_form_key_url(url, api_key, share_url, timeout)
    elif provider == CDN_PROTOCOL_AGG_VIDEO:
        out = _call_cdn_agg_video(url, api_key, share_url, extra, headers, timeout)
    elif provider == CDN_PROTOCOL_AGG_PROFILE:
        out = _call_cdn_agg_profile(url, api_key, share_url, extra, headers, timeout)
    elif provider == "tenapi":
        out = _call_tenapi(url, share_url, timeout)
    elif provider == CDN_PROTOCOL_JSON_URL:
        body = {"url": share_url}
        body.update(extra or {})
        raw = _http_request(url, json_body=body, headers=headers, timeout=timeout)
        data = _unwrap_dict(raw)
        out = {
            "video_url": _extract_video_fields(data),
            "text": "",
            "title": _pick_str(data.get("title")),
        }
    else:
        raise RuntimeError(f"未知 CDN 协议: {provider}")

    out["_provider"] = provider
    if not out.get("video_url"):
        raise RuntimeError(f"CDN 接口未返回 video_url（协议={provider}）")
    return out


def call_transcript_provider(
    provider: str,
    *,
    api_url: str,
    api_key: str,
    share_url: str,
    extra: dict | None = None,
    headers: dict | None = None,
    timeout: float = 120.0,
) -> dict:
    provider = normalize_transcript_provider(provider)
    if provider == "local_whisper":
        return {"video_url": "", "text": "", "title": "", "_provider": "local_whisper"}

    url = (api_url or BUILTIN_ENDPOINTS.get(provider) or "").strip()
    if provider in ASR_ASYNC_PROTOCOLS:
        if not api_key:
            raise RuntimeError("ASR「异步 · 提交 + 轮询」需要填写 API Key。")
        if not url:
            raise RuntimeError("ASR 异步协议需要提交接口地址（或使用内置默认）。")
        extra = dict(extra or {})
        poll_url = _resolve_asr_poll_url(url, extra)
        out = _call_asr_async_poll(
            submit_url=url,
            poll_url=poll_url,
            api_key=api_key,
            share_url=share_url,
            extra=extra,
            timeout=timeout,
        )
        out["_provider"] = provider
        return out

    if not url:
        raise RuntimeError(f"ASR 协议 {provider!r} 需要填写接口地址，或使用内置默认地址。")
    if not api_key and provider != ASR_PROTOCOL_CUSTOM_JSON:
        raise RuntimeError(f"ASR 协议 {provider!r} 需要填写 API Key。")

    extra = extra or {}

    if provider == ASR_PROTOCOL_SYNC_VIDEOURL:
        raw = _http_request(
            url,
            form={"key": api_key, "videoUrl": share_url, **{k: str(v) for k, v in extra.items()}},
            timeout=timeout,
        )
        data = _unwrap_dict(raw)
        out = {
            "video_url": _extract_video_fields(data),
            "text": _extract_transcript_fields(data, raw),
            "title": _pick_str(data.get("title"), data.get("videoDesc")),
        }
    elif provider == ASR_PROTOCOL_SYNC_CONTENT:
        raw = _http_request(
            url,
            form={"key": api_key, "content": share_url, **{k: str(v) for k, v in extra.items()}},
            timeout=timeout,
        )
        data = _unwrap_dict(raw)
        out = {
            "video_url": _extract_video_fields(data),
            "text": _extract_transcript_fields(data, raw),
            "title": _pick_str(data.get("title"), data.get("videoDesc")),
        }
    elif provider == ASR_PROTOCOL_CUSTOM_JSON:
        body = {"url": share_url}
        body.update(extra)
        raw = _http_request(url, json_body=body, headers=headers, timeout=timeout)
        data = _unwrap_dict(raw)
        out = {
            "video_url": _extract_video_fields(data),
            "text": _extract_transcript_fields(data, raw),
            "title": _pick_str(data.get("title")),
        }
    elif provider == "funasr":
        return {"video_url": "", "text": "", "title": "", "_provider": "funasr"}
    else:
        raise RuntimeError(f"未知 ASR 协议: {provider}")

    out["_provider"] = provider
    if not out.get("text"):
        raise RuntimeError(
            f"口播接口未返回 text（协议={provider}）。"
            "请勿把 CDN 视频提取接口配在 ASR 下。"
        )
    return out


def call_provider(**kwargs) -> dict:
    provider = (kwargs.get("provider") or ASR_PROTOCOL_CUSTOM_JSON).strip().lower()
    cdn_ids = {
        "none",
        "local_share",
        "browser_share",
        "tenapi",
        CDN_PROTOCOL_FORM_KEY_URL,
        CDN_PROTOCOL_FORM_KEY_URL_TIMES,
        CDN_PROTOCOL_AGG_VIDEO,
        CDN_PROTOCOL_AGG_PROFILE,
        CDN_PROTOCOL_JSON_URL,
        "17zhiling_watermark",
    }
    if provider in cdn_ids:
        return call_cdn_provider(provider, **{k: v for k, v in kwargs.items() if k != "provider"})
    return call_transcript_provider(provider, **{k: v for k, v in kwargs.items() if k != "provider"})

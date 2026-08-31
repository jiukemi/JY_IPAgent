"""Normalize script text before TTS to fix acronym / brand mispronunciation."""

from __future__ import annotations

import re

# Legacy phonetic rewrites from an earlier normalize pass — revert before re-normalizing.
_LEGACY_PHONETIC_REVERT: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"外波抠丁"), "vibe coding"),
    (re.compile(r"外波\s*start", re.I), "vibe start"),
    (re.compile(r"vibe\s*code(?:ing)?", re.I), "vibe coding"),
    (re.compile(r"基米"), "Kimi"),
    (re.compile(r"克瑟"), "Cursor"),
    (re.compile(r"克劳德Code"), "Claude Code"),
    (re.compile(r"克劳德"), "Claude"),
]

# Prefer Chinese product phrasing for CN-local engines (avoids letter-by-letter EN).
_BRAND_CN_FIXES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?<![A-Za-z])vibe[\s\-_.]*cod(?:e|ing)(?![A-Za-z])", re.I), "氛围编程"),
    (re.compile(r"(?<![A-Za-z])vibecoding(?![A-Za-z])", re.I), "氛围编程"),
    (re.compile(r"(?<![A-Za-z])vibecode(?![A-Za-z])", re.I), "氛围编程"),
    (re.compile(r"(?<![A-Za-z])vibestart(?![A-Za-z])", re.I), "氛围启动"),
    (re.compile(r"(?<![A-Za-z])vibe\s*start(?![A-Za-z])", re.I), "氛围启动"),
    (re.compile(r"(?<![A-Za-z])deep\s*seek(?![A-Za-z])", re.I), "深度求索"),
    (re.compile(r"(?<![A-Za-z])deepseek(?![A-Za-z])", re.I), "深度求索"),
    (re.compile(r"(?<![A-Za-z])chat\s*gpt(?![A-Za-z])", re.I), "ChatGPT"),
    (re.compile(r"(?<![A-Za-z])open\s*ai(?![A-Za-z])", re.I), "OpenAI"),
    (re.compile(r"(?<![A-Za-z])git\s*hub(?![A-Za-z])", re.I), "GitHub"),
    (re.compile(r"(?<![A-Za-z])you\s*tube(?![A-Za-z])", re.I), "YouTube"),
    (re.compile(r"(?<![A-Za-z])tik\s*tok(?![A-Za-z])", re.I), "抖音国际版"),
    (re.compile(r"(?<![A-Za-z])claude\s*code(?![A-Za-z])", re.I), "Claude Code"),
]

# Latin forms for Edge / Piper (they handle EN words better).
_BRAND_LATIN_FIXES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?<![A-Za-z])vibe[\s\-_.]*cod(?:e|ing)(?![A-Za-z])", re.I), "vibe coding"),
    (re.compile(r"(?<![A-Za-z])vibecoding(?![A-Za-z])", re.I), "vibe coding"),
    (re.compile(r"(?<![A-Za-z])vibecode(?![A-Za-z])", re.I), "vibe code"),
    (re.compile(r"(?<![A-Za-z])vibestart(?![A-Za-z])", re.I), "vibe start"),
    (re.compile(r"(?<![A-Za-z])deepseek(?![A-Za-z])", re.I), "deep seek"),
    (re.compile(r"(?<![A-Za-z])claude\s+code(?![A-Za-z])", re.I), "Claude Code"),
]

_PHRASE_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"MAC(?=\s*口\s*红)", re.I), "魅可"),
    (re.compile(r"MAC(?=\s*电\s*脑)", re.I), "Mac"),
    (re.compile(r"MAC(?=\s*book)", re.I), "MacBook"),
    (re.compile(r"\bMAC\b"), "Mac"),
    (re.compile(r"\biPhone\b", re.I), "iPhone"),
    (re.compile(r"\biPad\b", re.I), "iPad"),
    (re.compile(r"\biOS\b"), "iOS"),
    (re.compile(r"\bAPI\b"), "API"),
    (re.compile(r"\bTTS\b"), "TTS"),
    (re.compile(r"\bGPU\b"), "GPU"),
    (re.compile(r"\bCPU\b"), "CPU"),
    (re.compile(r"\bAI\b"), "AI"),
]

# Continuous Latin for IndexTTS (handles EN better than Cosy / small Qwen).
_TECH_CN_MAP: dict[str, str] = {
    "Cursor": "Cursor",
    "CURSOR": "Cursor",
    "cursor": "Cursor",
    "Codex": "Codex",
    "CODEX": "Codex",
    "codex": "Codex",
    "Copilot": "Copilot",
    "Claude": "Claude",
    "Gemini": "Gemini",
    "ChatGPT": "ChatGPT",
    "chatgpt": "ChatGPT",
    "OpenAI": "OpenAI",
    "openai": "OpenAI",
    "DeepSeek": "深度求索",
    "deepseek": "深度求索",
    "GitHub": "GitHub",
    "github": "GitHub",
    "Docker": "Docker",
    "Python": "Python",
    "Linux": "Linux",
    "Windows": "Windows",
    "Android": "安卓",
    "Adobe": "Adobe",
    "Notion": "Notion",
    "Figma": "Figma",
    "Slack": "Slack",
    "Zoom": "Zoom",
    "TikTok": "抖音国际版",
    "YouTube": "YouTube",
    "Netflix": "Netflix",
    "Spotify": "Spotify",
    "NVIDIA": "英伟达",
    "Nvidia": "英伟达",
    "IndexTTS": "IndexTTS",
    "CosyVoice": "CosyVoice",
    "HeyGem": "HeyGem",
    "LatentSync": "LatentSync",
    "Remotion": "Remotion",
    "HyperFrames": "HyperFrames",
    "Playwright": "Playwright",
    "FastAPI": "FastAPI",
}

# Phonetic / Chinese names for CosyVoice & Qwen3-local (reduce letter-by-letter spelling).
_TECH_WEAK_CN_MAP: dict[str, str] = {
    "Cursor": "克瑟",
    "CURSOR": "克瑟",
    "cursor": "克瑟",
    "Codex": "扣底克斯",
    "CODEX": "扣底克斯",
    "codex": "扣底克斯",
    "Copilot": "副驾驶",
    "Claude": "克劳德",
    "Gemini": "双子星",
    "ChatGPT": "ChatGPT",
    "chatgpt": "ChatGPT",
    "OpenAI": "OpenAI",
    "openai": "OpenAI",
    "DeepSeek": "深度求索",
    "deepseek": "深度求索",
    "GitHub": "GitHub",
    "github": "GitHub",
    "Docker": "Docker",
    "Python": "派森",
    "Linux": "Linux",
    "Windows": "Windows",
    "Android": "安卓",
    "Adobe": "Adobe",
    "Notion": "Notion",
    "Figma": "Figma",
    "Slack": "Slack",
    "Zoom": "Zoom",
    "TikTok": "抖音国际版",
    "YouTube": "油管",
    "Netflix": "奈飞",
    "Spotify": "Spotify",
    "NVIDIA": "英伟达",
    "Nvidia": "英伟达",
    "Claude Code": "克劳德代码",
}

# Keep continuous Latin word form (avoid C-o-d-e-x spelling) for engines that can say EN.
_TECH_WORD_MAP: dict[str, str] = {
    "Codex": "codex",
    "CODEX": "codex",
    "Cursor": "cursor",
    "Copilot": "copilot",
    "Claude": "claude",
    "Gemini": "gemini",
    "ChatGPT": "chatgpt",
    "OpenAI": "openai",
    "DeepSeek": "deepseek",
    "GitHub": "github",
    "Docker": "docker",
    "Python": "python",
    "Linux": "linux",
    "Windows": "windows",
    "Android": "android",
    "Adobe": "adobe",
    "Notion": "notion",
    "Figma": "figma",
    "Slack": "slack",
    "Zoom": "zoom",
    "TikTok": "tiktok",
    "YouTube": "youtube",
    "Netflix": "netflix",
    "Spotify": "spotify",
    "NVIDIA": "nvidia",
    "Nvidia": "nvidia",
}

_COMMON_ENGLISH = frozenset(
    {
        "The",
        "This",
        "That",
        "These",
        "Those",
        "What",
        "When",
        "Where",
        "Which",
        "Who",
        "Why",
        "How",
        "Hello",
        "Please",
        "Thank",
        "Thanks",
        "Today",
        "Tomorrow",
        "Yesterday",
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    }
)

_ACRONYM = re.compile(r"\b([A-Z]{2,5})\b")
_TITLE_WORD = re.compile(r"\b([A-Z][a-z]{2,})\b")
_SPACED_LATIN = re.compile(r"(?<![A-Za-z])(?:[A-Za-z]\s+){2,}[A-Za-z](?![A-Za-z])")
_SLASH_ENUM = re.compile(r"\s*/\s*")
# CamelCase product names: VibeCoding → Vibe Coding (then CN fix / word map)
_CAMEL = re.compile(r"(?<![A-Za-z])([A-Z]+[a-z]+(?:[A-Z][a-z0-9]+)+)(?![A-Za-z])")
# Isolated Latin run (2+ letters) inside Chinese text
_LATIN_RUN = re.compile(r"(?<![A-Za-z])([A-Za-z][A-Za-z0-9+\-.]{1,})(?![A-Za-z])")
_CJK = re.compile(r"[\u4e00-\u9fff]")

# Latin with readable casing for IndexTTS / Edge / Piper (no Chinese brand translations).
_TECH_LATIN_MAP: dict[str, str] = dict(_TECH_WORD_MAP)
for _src, _dst in _TECH_CN_MAP.items():
    if not _CJK.search(_dst):
        _TECH_LATIN_MAP[_src] = _dst
_TECH_LATIN_MAP["DeepSeek"] = "deep seek"
_TECH_LATIN_MAP["deepseek"] = "deep seek"
_TECH_LATIN_MAP["VibeStart"] = "vibe start"
_TECH_LATIN_MAP["vibestart"] = "vibe start"


def _collapse_spaced_latin(match: re.Match[str]) -> str:
    raw = re.sub(r"\s+", "", match.group(0))
    if raw in _TECH_CN_MAP:
        return _TECH_CN_MAP[raw]
    return _TECH_WORD_MAP.get(raw, raw)


def _split_camel(match: re.Match[str]) -> str:
    word = match.group(1)
    if word in _TECH_CN_MAP:
        return _TECH_CN_MAP[word]
    if word in _TECH_WORD_MAP:
        return _TECH_WORD_MAP[word]
    parts = re.findall(r"[A-Z]+(?=[A-Z][a-z]|$)|[A-Z]?[a-z]+|[0-9]+", word)
    if len(parts) >= 2:
        return " ".join(parts)
    return word


def _apply_tech_map(text: str, *, mapping: dict[str, str]) -> str:
    for src, dst in sorted(mapping.items(), key=lambda x: -len(x[0])):
        text = re.sub(rf"(?<![A-Za-z]){re.escape(src)}(?![A-Za-z])", dst, text)
        if src.lower() != src:
            text = re.sub(
                rf"(?<![A-Za-z]){re.escape(src)}(?![A-Za-z])",
                dst,
                text,
                flags=re.I,
            )
    return text


def _lower_acronym(match: re.Match[str]) -> str:
    word = match.group(1)
    if word in {"OK", "TV", "AI", "CPU", "GPU", "USB", "VIP", "APP", "PDF", "API", "TTS", "IOS", "GPU"}:
        return word if word != "IOS" else "iOS"
    if word in _TECH_CN_MAP:
        return _TECH_CN_MAP[word]
    mapped = _TECH_WORD_MAP.get(word)
    if mapped:
        return mapped
    return word


def _lower_title_word(match: re.Match[str], *, tech_map: dict[str, str]) -> str:
    word = match.group(1)
    if word in _COMMON_ENGLISH:
        return word
    if word in tech_map:
        return tech_map[word]
    if word in _TECH_WORD_MAP:
        return _TECH_WORD_MAP[word]
    return word


def _cjk_ratio(text: str) -> float:
    if not text:
        return 0.0
    cjk = len(_CJK.findall(text))
    return cjk / max(len(text), 1)


def _protect_latin_in_chinese(text: str) -> str:
    """Keep Latin tokens continuous; pad with spaces so weak TTS doesn't glue to CJK and spell."""

    def repl(m: re.Match[str]) -> str:
        w = m.group(1)
        if w in _TECH_CN_MAP:
            return _TECH_CN_MAP[w]
        # Prefer known continuous forms
        key = w[0].upper() + w[1:] if w else w
        if key in _TECH_CN_MAP:
            return _TECH_CN_MAP[key]
        if w.upper() in _TECH_CN_MAP:
            return _TECH_CN_MAP[w.upper()]
        # Avoid letter-spelling: keep as one token, lower long ALLCAPS product-like words
        if w.isupper() and 2 < len(w) <= 12 and w not in {"OK", "TV", "AI", "CPU", "GPU", "USB", "VIP", "APP", "PDF", "API", "TTS"}:
            return w.capitalize() if len(w) > 3 else w
        return w

    return _LATIN_RUN.sub(repl, text)


def latin_ratio(text: str) -> float:
    """Share of ASCII letters among letters+CJK (for Cosy cross-lingual / Qwen Auto)."""
    letters = sum(1 for c in text if c.isalpha() and ord(c) < 128)
    cjk = len(_CJK.findall(text))
    denom = letters + cjk
    if denom <= 0:
        return 0.0
    return letters / denom


def normalize_speech_text(text: str, *, backend: str | None = None) -> str:
    """Fix brands / camelCase / spaced letters so CN TTS does not spell English."""
    if not text or not text.strip():
        return text

    out = text
    engine = (backend or "").lower()
    cn_engines = ("", "indextts", "cosyvoice", "qwen3_local", "qwen3_tts")
    cn_mode = engine in cn_engines
    # Cosy / small Qwen are weakest at EN — lean hardest on CN substitutions
    weak_en = engine in ("cosyvoice", "qwen3_local")
    # IndexTTS / Edge / Piper handle EN brands — keep Latin, don't translate to Chinese
    latin_first = engine in ("indextts", "edge", "piper")

    if cn_mode:
        for pat, repl in _LEGACY_PHONETIC_REVERT:
            out = pat.sub(repl, out)
        if latin_first:
            for pat, repl in _BRAND_LATIN_FIXES:
                out = pat.sub(repl, out)
        else:
            for pat, repl in _BRAND_CN_FIXES:
                out = pat.sub(repl, out)
        out = _SLASH_ENUM.sub(" 、 ", out)
    elif latin_first:
        for pat, repl in _BRAND_LATIN_FIXES:
            out = pat.sub(repl, out)

    for pat, repl in _PHRASE_RULES:
        out = pat.sub(repl, out)

    if weak_en:
        tech_map = _TECH_WEAK_CN_MAP
    elif cn_mode and not latin_first:
        tech_map = _TECH_CN_MAP
    elif latin_first:
        tech_map = _TECH_LATIN_MAP
    else:
        tech_map = _TECH_WORD_MAP

    out = _CAMEL.sub(_split_camel, out)
    out = _SPACED_LATIN.sub(_collapse_spaced_latin, out)
    out = _apply_tech_map(out, mapping=tech_map)
    out = _TITLE_WORD.sub(lambda m: _lower_title_word(m, tech_map=tech_map), out)
    out = _ACRONYM.sub(_lower_acronym, out)

    # Dominant Chinese + leftover English → keep Latin continuous (esp. Cosy/Qwen)
    if (cn_mode or weak_en) and _cjk_ratio(out) >= 0.25:
        out = _protect_latin_in_chinese(out)
        if weak_en:
            out = _apply_tech_map(out, mapping=tech_map)

    return out

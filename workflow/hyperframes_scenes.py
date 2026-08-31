"""HyperFrames CSS scene templates → PNG / MP4 (headless browser + PIL fallback)."""

from __future__ import annotations

import html as html_lib
import math
import re
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

from workflow.publish import split_script_for_subtitles

SCENE_FPS = 15
DEFAULT_SCENE_LAYOUT = "kinetic"
DEFAULT_ASPECT = "portrait_9_16"

ASPECT_PRESETS: dict[str, dict] = {
    "portrait_9_16": {
        "label": "竖屏 9:16",
        "width": 1080,
        "height": 1920,
        "ratio": "9:16",
    },
    "landscape_16_9": {
        "label": "横屏 16:9",
        "width": 1920,
        "height": 1080,
        "ratio": "16:9",
    },
}

SCENE_LAYOUTS: dict[str, dict] = {
    "card": {"label": "信息卡片", "animated": False, "css": True},
    "kinetic": {"label": "动感大字", "animated": True, "css": True},
    "hero": {"label": "标题开场", "animated": True, "css": True},
    "bullets": {"label": "要点列表", "animated": True, "css": True},
    "quote": {"label": "金句引用", "animated": True, "css": True},
    "glass": {"label": "毛玻璃", "animated": True, "css": True},
    "editorial": {"label": "杂志分栏", "animated": True, "css": True},
    "spotlight": {"label": "聚光强调", "animated": True, "css": True},
    "text_card": {"label": "透明玻璃字卡", "animated": True, "css": True, "compose": "fusion"},
    "glass_card": {"label": "透明玻璃字卡", "animated": True, "css": True, "compose": "fusion"},
    "plain_text": {"label": "纯透明文字", "animated": True, "css": True, "compose": "fusion"},
}

# Layouts that burn with black colorkey onto lipsync (原视频融合)
FUSION_LAYOUTS = frozenset({"text_card", "glass_card", "plain_text"})


def normalize_layout_key(layout: str | None) -> str:
    key = (layout or DEFAULT_SCENE_LAYOUT).lower().replace("-", "_")
    if key == "glass_card":
        return "text_card"  # same glass renderer; id kept for API/UI
    return key


def is_fusion_layout(layout: str | None) -> bool:
    key = (layout or "").lower().replace("-", "_")
    return key in FUSION_LAYOUTS

_CJK_WORD = re.compile(r"[\u4e00-\u9fff]{2,}")
_EN_WORD = re.compile(r"[A-Za-z][A-Za-z0-9+#.\-]{1,}")
_NUM_TOKEN = re.compile(r"\d+(?:\.\d+)?%?")

# 智能配色词库（长词优先匹配）
_SMART_HOOK_WORDS: tuple[str, ...] = (
    "限时免费", "错过再无", "手慢无", "0元购", "零成本", "免费送", "爆款", "必看", "干货",
    "秘诀", "躺赚", "逆袭", "暴涨", "秒杀", "福利", "赠送", "白嫖", "性价比", "天花板",
    "封神", "绝绝子", "真香", "薅羊毛", "抄底", "闭眼入", "王炸", "封神作", "免费",
    "限时", "特惠", "立减", "折扣", "省", "赚", "爆", "火", "新", "首发",
)
_SMART_URGENT_WORDS: tuple[str, ...] = (
    "立刻", "马上", "抓紧", "仅剩", "最后", "倒计时", "今天", "今晚", "本周", "本月",
    "仅限", "名额", "抢", "速来", "别错过", "不容错过", "就现在",
)
_SMART_TRUST_WORDS: tuple[str, ...] = (
    "官方", "实测", "亲测", "科学", "权威", "正版", "保障", "包邮", "正品", "推荐",
    "专业", "系统课", "方法论", "保姆级", "手把手",
)
_SMART_EMO_WORDS: tuple[str, ...] = (
    "太绝了", "震惊", "真的", "居然", "原来", "竟然", "绝了", "太强了", "离谱", "哇",
)
_QUOTE_PAT = re.compile(r"[「『""]([^」』""]{1,24})[」』""]")
_NUM_PAT = re.compile(r"\d+(?:\.\d+)?%?")
_EN_PAT = re.compile(r"[A-Za-z][A-Za-z0-9+#.\-]{1,}")

_SPAN_PRIORITY: dict[str, int] = {
    "quote": 100,
    "hook": 92,
    "urgent": 88,
    "trust": 82,
    "emo": 78,
    "num": 74,
    "en": 70,
    "key": 62,
}


def _warn_from_accent(accent_hex: str) -> str:
    r, g, b = _hex_to_rgb(accent_hex)
    return f"#{min(255, r + 48):02x}{max(0, g - 12):02x}{max(0, b - 72):02x}"


def _theme_palette(theme: dict) -> dict[str, str]:
    def hx(rgb: tuple[int, int, int]) -> str:
        r, g, b = rgb
        return f"#{r:02x}{g:02x}{b:02x}"

    top = hx(theme["top"])
    bottom = hx(theme["bottom"])
    text = hx(theme["text"])
    accent = hx(theme["accent_bar"])
    outline = hx(theme["outline"])
    return {
        "top": top,
        "bottom": bottom,
        "text": text,
        "accent": accent,
        "outline": outline,
        "muted": _mix_hex(text, bottom, 0.42),
        "highlight2": outline,
        "glow": _mix_hex(accent, text, 0.35),
        "panel": _mix_hex(bottom, text, 0.12),
        "warn": _warn_from_accent(accent),
        "hook_bg": _mix_hex(accent, "#ffffff", 0.15),
    }


def list_aspect_ratios() -> list[dict]:
    return [
        {
            "id": key,
            "label": meta["label"],
            "width": meta["width"],
            "height": meta["height"],
            "ratio": meta["ratio"],
        }
        for key, meta in ASPECT_PRESETS.items()
    ]


def list_scene_layouts() -> list[dict]:
    w, h = resolve_dimensions("kinetic", DEFAULT_ASPECT)
    return [
        {
            "id": key,
            "label": meta["label"],
            "animated": meta["animated"],
            "width": w,
            "height": h,
        }
        for key, meta in SCENE_LAYOUTS.items()
    ]


def normalize_aspect(aspect: str) -> str:
    raw = (aspect or DEFAULT_ASPECT).lower().replace("-", "_")
    aliases = {
        "portrait": "portrait_9_16",
        "9_16": "portrait_9_16",
        "9x16": "portrait_9_16",
        "vertical": "portrait_9_16",
        "landscape": "landscape_16_9",
        "16_9": "landscape_16_9",
        "16x9": "landscape_16_9",
        "horizontal": "landscape_16_9",
    }
    return aliases.get(raw, raw if raw in ASPECT_PRESETS else DEFAULT_ASPECT)


def resolve_layout(layout: str) -> dict:
    key = (layout or DEFAULT_SCENE_LAYOUT).lower().replace("-", "_")
    if key in SCENE_LAYOUTS:
        return SCENE_LAYOUTS[key]
    # glass_card shares text_card meta if somehow missing
    if key == "glass_card":
        return SCENE_LAYOUTS["text_card"]
    return SCENE_LAYOUTS[DEFAULT_SCENE_LAYOUT]


def resolve_dimensions(layout: str, aspect: str = DEFAULT_ASPECT) -> tuple[int, int]:
    asp = normalize_aspect(aspect)
    preset = ASPECT_PRESETS.get(asp, ASPECT_PRESETS[DEFAULT_ASPECT])
    return int(preset["width"]), int(preset["height"])


def _find_headless_browser() -> str | None:
    for path in (
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    ):
        if path.is_file():
            return str(path)
    for name in ("msedge", "chrome", "chromium"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    raw = hex_color.lstrip("#")
    if len(raw) != 6:
        return 255, 255, 255
    return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)


def _mix_hex(a: str, b: str, t: float) -> str:
    ar, ag, ab = _hex_to_rgb(a)
    br, bg, bb = _hex_to_rgb(b)
    t = max(0.0, min(1.0, t))
    r = int(ar * (1 - t) + br * t)
    g = int(ag * (1 - t) + bg * t)
    bl = int(ab * (1 - t) + bb * t)
    return f"#{r:02x}{g:02x}{bl:02x}"


def _esc(text: str) -> str:
    return html_lib.escape((text or "").strip())


def resolve_scene_aspect(
    aspect: str | None = None,
    *,
    video_width: int | None = None,
    video_height: int | None = None,
) -> str:
    """Match scene canvas to output video when dimensions are known."""
    if video_width and video_height and video_width > 0 and video_height > 0:
        return "landscape_16_9" if video_width > video_height else "portrait_9_16"
    return normalize_aspect(aspect or DEFAULT_ASPECT)


def _font_scale_value(style_pack: dict | None) -> float:
    if not style_pack:
        return 1.0
    try:
        raw = float(style_pack.get("font_scale") or 1.0)
    except (TypeError, ValueError):
        raw = 1.0
    return max(0.7, min(2.0, raw))


def _scale_px(px: float, font_scale: float) -> int:
    return max(8, int(round(px * font_scale)))


def _pick_fusion_layout(text: str, suggested: str | None = None) -> str:
    """Map smart suggestions + cue shape → fusion layout (glass_card | plain_text)."""
    key = normalize_layout_key(suggested or "")
    if is_fusion_layout(key):
        return key
    raw = (text or "").strip()
    compact = raw.replace("\n", "").replace(" ", "")
    if "•" in raw or raw.count("\n") >= 1 or any(
        x in raw for x in ("1.", "①", "②", "要点", "第一", "第二")
    ):
        return "glass_card"
    if len(compact) <= 16:
        return "plain_text"
    if any(m in raw for m in ("「", "」", "“", "”", '"')):
        return "plain_text"
    return "glass_card"


def _split_lines(text: str, max_chars: int, *, landscape: bool) -> list[str]:
    """Split for on-canvas titles; long CJK phrases hard-wrap so nothing clips sideways."""
    cap = max(6, int(max_chars) + (4 if landscape else 0))
    lines = split_script_for_subtitles(text, max_chars=cap) or [text.strip() or "…"]
    # Hard-wrap any residual overlong line (punctuation-less sentences)
    out: list[str] = []
    limit = 4 if not landscape else 3
    for line in lines:
        s = (line or "").strip()
        if not s:
            continue
        if len(s) <= cap + 2:
            out.append(s)
        else:
            for i in range(0, len(s), cap):
                chunk = s[i : i + cap].strip()
                if chunk:
                    out.append(chunk)
        if len(out) >= limit:
            break
    return out[:limit] or ["…"]


def _title_size_for_text(
    text: str,
    landscape: bool,
    *,
    large: bool = True,
    fusion: bool = False,
    font_scale: float = 1.0,
) -> str:
    """Shrink title when a single phrase is long so wrap stays inside safe margins."""
    fs = max(0.7, min(2.0, float(font_scale or 1.0)))
    n = max(len((text or "").replace("\n", "").replace(" ", "")), 1)
    if fusion:
        if landscape:
            if n >= 28:
                return f"clamp({_scale_px(52, fs)}px, {5.2 * fs:.2f}vw, {_scale_px(88, fs)}px)"
            if n >= 18:
                return f"clamp({_scale_px(64, fs)}px, {6.4 * fs:.2f}vw, {_scale_px(104, fs)}px)"
            return (
                f"clamp({_scale_px(72, fs)}px, {7.8 * fs:.2f}vw, {_scale_px(120, fs)}px)"
                if large
                else f"clamp({_scale_px(56, fs)}px, {6.0 * fs:.2f}vw, {_scale_px(92, fs)}px)"
            )
        if n >= 24:
            return f"clamp({_scale_px(56, fs)}px, {7.0 * fs:.2f}vw, {_scale_px(88, fs)}px)"
        if n >= 16:
            return f"clamp({_scale_px(64, fs)}px, {8.0 * fs:.2f}vw, {_scale_px(98, fs)}px)"
        return (
            f"clamp({_scale_px(72, fs)}px, {9.2 * fs:.2f}vw, {_scale_px(118, fs)}px)"
            if large
            else f"clamp({_scale_px(56, fs)}px, {7.0 * fs:.2f}vw, {_scale_px(88, fs)}px)"
        )
    if landscape:
        if n >= 28:
            return f"clamp({_scale_px(28, fs)}px, {3.2 * fs:.2f}vw, {_scale_px(40, fs)}px)"
        if n >= 18:
            return f"clamp({_scale_px(34, fs)}px, {4.0 * fs:.2f}vw, {_scale_px(52, fs)}px)"
        return (
            f"clamp({_scale_px(40, fs)}px, {4.8 * fs:.2f}vw, {_scale_px(64, fs)}px)"
            if large
            else f"clamp({_scale_px(28, fs)}px, {3.2 * fs:.2f}vw, {_scale_px(42, fs)}px)"
        )
    if n >= 24:
        return f"clamp({_scale_px(34, fs)}px, {4.6 * fs:.2f}vw, {_scale_px(48, fs)}px)"
    if n >= 16:
        return f"clamp({_scale_px(42, fs)}px, {5.6 * fs:.2f}vw, {_scale_px(62, fs)}px)"
    return (
        f"clamp({_scale_px(52, fs)}px, {6.8 * fs:.2f}vw, {_scale_px(78, fs)}px)"
        if large
        else f"clamp({_scale_px(34, fs)}px, {4.2 * fs:.2f}vw, {_scale_px(48, fs)}px)"
    )


def _pick_keyword(line: str, occupied: list[bool]) -> str | None:
    candidates: list[str] = []
    for m in _CJK_WORD.finditer(line):
        if any(occupied[m.start() : m.end()]):
            continue
        candidates.append(m.group(0))
    for m in _EN_PAT.finditer(line):
        if any(occupied[m.start() : m.end()]):
            continue
        candidates.append(m.group(0))
    if not candidates:
        return None
    return max(candidates, key=len)


def _collect_word_spans(line: str, words: tuple[str, ...], cls: str) -> list[tuple[int, int, str, int]]:
    spans: list[tuple[int, int, str, int]] = []
    prio = _SPAN_PRIORITY[cls]
    for word in sorted(words, key=len, reverse=True):
        if not word:
            continue
        start = 0
        while True:
            idx = line.find(word, start)
            if idx < 0:
                break
            spans.append((idx, idx + len(word), cls, prio))
            start = idx + len(word)
    return spans


def _collect_regex_spans(
    line: str, pattern: re.Pattern[str], cls: str, group: int = 0
) -> list[tuple[int, int, str, int]]:
    spans: list[tuple[int, int, str, int]] = []
    prio = _SPAN_PRIORITY[cls]
    for m in pattern.finditer(line):
        if group and m.lastindex:
            spans.append((m.start(group), m.end(group), cls, prio))
        else:
            spans.append((m.start(), m.end(), cls, prio))
    return spans


def _merge_spans(candidates: list[tuple[int, int, str, int]]) -> list[tuple[int, int, str]]:
    """Greedy non-overlapping span selection by priority then length."""
    candidates.sort(key=lambda s: (-s[3], -(s[1] - s[0]), s[0]))
    picked: list[tuple[int, int, str, int]] = []
    for start, end, cls, prio in candidates:
        if start >= end:
            continue
        if any(not (end <= a or start >= b) for a, b, _, _ in picked):
            continue
        picked.append((start, end, cls, prio))
    picked.sort(key=lambda s: s[0])
    return [(a, b, c) for a, b, c, _ in picked]


def _render_spans_html(line: str, spans: list[tuple[int, int, str]]) -> str:
    if not spans:
        return _esc(line)
    out: list[str] = []
    pos = 0
    for start, end, cls in spans:
        if start > pos:
            out.append(_esc(line[pos:start]))
        out.append(f'<span class="tok {cls}">{_esc(line[start:end])}</span>')
        pos = end
    out.append(_esc(line[pos:]))
    return "".join(out)


def analyze_smart_spans(line: str) -> list[tuple[int, int, str]]:
    line = (line or "").strip()
    if not line:
        return []
    candidates: list[tuple[int, int, str, int]] = []
    candidates.extend(_collect_regex_spans(line, _QUOTE_PAT, "quote", group=1))
    candidates.extend(_collect_word_spans(line, _SMART_HOOK_WORDS, "hook"))
    candidates.extend(_collect_word_spans(line, _SMART_URGENT_WORDS, "urgent"))
    candidates.extend(_collect_word_spans(line, _SMART_TRUST_WORDS, "trust"))
    candidates.extend(_collect_word_spans(line, _SMART_EMO_WORDS, "emo"))
    candidates.extend(_collect_regex_spans(line, _NUM_PAT, "num"))
    candidates.extend(_collect_regex_spans(line, _EN_PAT, "en"))

    merged = _merge_spans(candidates)
    occupied = [False] * len(line)
    for start, end, _ in merged:
        for i in range(start, min(end, len(line))):
            occupied[i] = True

    keyword = _pick_keyword(line, occupied)
    if keyword:
        idx = line.find(keyword)
        if idx >= 0 and not any(
            not (idx + len(keyword) <= a or idx >= b) for a, b, _ in merged
        ):
            merged.append((idx, idx + len(keyword), "key"))
            merged.sort(key=lambda s: s[0])
    return merged


_SMART_KEYWORDS_ENABLED = True


@contextmanager
def smart_keywords_scope(enabled: bool = True):
    """Toggle keyword span coloring for HTML/PIL scene text and Remotion cues."""
    global _SMART_KEYWORDS_ENABLED
    prev = _SMART_KEYWORDS_ENABLED
    _SMART_KEYWORDS_ENABLED = bool(enabled)
    try:
        yield
    finally:
        _SMART_KEYWORDS_ENABLED = prev


def colorize_line_html(line: str, line_idx: int) -> str:
    """Smart palette: hook / urgent / trust / emo / num / en / key / quote."""
    line = (line or "").strip()
    if not line:
        return ""
    role = "lead" if line_idx == 0 else ("sub" if line_idx == 1 else "body")
    if not _SMART_KEYWORDS_ENABLED:
        return f'<span class="line {role}">{html_lib.escape(line)}</span>'
    spans = analyze_smart_spans(line)
    colored = _render_spans_html(line, spans)
    return f'<span class="line {role}">{colored}</span>'


def _pil_class_colors(theme: dict) -> dict[str, tuple[int, int, int]]:
    pal_css = _theme_palette(theme)
    tr, tg, tb = theme["text"]
    ar, ag, ab = theme["accent_bar"]
    or_, og, ob = theme["outline"]
    wr, wg, wb = _hex_to_rgb(pal_css["warn"])
    gr, gg, gb = _hex_to_rgb(pal_css["glow"])
    return {
        "text": (tr, tg, tb),
        "key": (ar, ag, ab),
        "hook": (wr, wg, wb),
        "urgent": (wr, wg, wb),
        "trust": (gr, gg, gb),
        "emo": (ar, ag, ab),
        "quote": (gr, gg, gb),
        "num": (wr, wg, wb),
        "en": (or_, og, ob),
    }


def _line_parts_from_spans(line: str, spans: list[tuple[int, int, str]]) -> list[tuple[str, str]]:
    if not spans:
        return [(line, "text")]
    parts: list[tuple[str, str]] = []
    pos = 0
    for start, end, cls in spans:
        if start > pos:
            parts.append((line[pos:start], "text"))
        parts.append((line[start:end], cls))
        pos = end
    if pos < len(line):
        parts.append((line[pos:], "text"))
    return parts


def _draw_smart_line(
    draw,
    *,
    center_x: int,
    y: int,
    line: str,
    font,
    colors: dict[str, tuple[int, int, int]],
    alpha: float = 1.0,
) -> None:
    if not _SMART_KEYWORDS_ENABLED:
        bbox = draw.textbbox((0, 0), line, font=font)
        w = bbox[2] - bbox[0]
        a = max(0, min(255, int(255 * alpha)))
        rgb = colors.get("text", (245, 247, 255))
        draw.text((center_x - w // 2, y), line, font=font, fill=(*rgb, a))
        return
    spans = analyze_smart_spans(line)
    parts = _line_parts_from_spans(line, spans)
    widths: list[int] = []
    for chunk, _ in parts:
        bbox = draw.textbbox((0, 0), chunk, font=font)
        widths.append(bbox[2] - bbox[0])
    total_w = sum(widths)
    x = center_x - total_w // 2
    a = max(0, min(255, int(255 * alpha)))
    for (chunk, cls), w in zip(parts, widths):
        if not chunk:
            continue
        rgb = colors.get(cls, colors["text"])
        draw.text((x, y), chunk, font=font, fill=(*rgb, a))
        x += w


def list_smart_color_rules() -> dict:
    return {
        "hook": list(_SMART_HOOK_WORDS[:18]),
        "urgent": list(_SMART_URGENT_WORDS[:12]),
        "trust": list(_SMART_TRUST_WORDS[:10]),
        "emo": list(_SMART_EMO_WORDS[:8]),
        "auto": ["数字/百分比", "英文", "引号内文案", "最长关键词"],
    }


def colorize_block_html(lines: list[str], *, join: str = "") -> str:
    """Join lines; default empty because .line is display:block (avoid <br> double spacing)."""
    return join.join(colorize_line_html(ln, i) for i, ln in enumerate(lines) if ln.strip())


def _fusion_viewport_css(width: int, height: int) -> str:
    """Fusion full-canvas: no extra body padding (flex layout owns placement)."""
    return f"""
html, body {{
  width: {width}px;
  height: {height}px;
  margin: 0;
  padding: 0;
}}
"""


def _viewport_css(width: int, height: int) -> str:
    landscape = width > height
    pad_main = "56px 88px" if landscape else "72px 56px"
    return f"""
html, body {{
  width: {width}px;
  height: {height}px;
  margin: 0;
  padding: 0;
}}
body {{
  padding: {pad_main};
}}
body.landscape .wrap, body.landscape .panel, body.landscape .glass {{
  max-width: {int(width * 0.86)}px;
}}
body.portrait .wrap, body.portrait .panel, body.portrait .glass {{
  max-width: {int(width * 0.90)}px;
}}
.wrap {{
  display: flex;
  flex-direction: column;
  align-items: center;
}}
.wrap, .panel, .glass, h1, h2, p, .quote {{
  max-width: 100%;
  overflow-wrap: anywhere;
  word-break: break-word;
  white-space: normal;
}}
.line {{
  display: block;
  line-height: 1.58;
  margin: 0;
  padding: 0.08em 0;
}}
h1, h2, blockquote, .glass p, .card h1, .quote {{
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: 0.28em;
  line-height: 1.58;
}}
"""


def _smart_text_css() -> str:
    return """
.line {
  display: block;
  line-height: 1.58;
  margin: 0;
  padding: 0.08em 0;
}
.line.lead {
  font-weight: 900;
  line-height: 1.58;
  background: linear-gradient(118deg, var(--text) 8%, var(--accent) 46%, var(--highlight2) 92%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  -webkit-box-decoration-break: clone;
  box-decoration-break: clone;
}
.line.sub { color: var(--muted); font-weight: 600; line-height: 1.58; }
.line.body { color: var(--text); font-weight: 650; line-height: 1.58; }
.tok.key {
  color: var(--accent);
  font-weight: 900;
  text-shadow: 0 0 24px color-mix(in srgb, var(--accent) 50%, transparent);
}
.tok.hook {
  font-weight: 900;
  background: linear-gradient(120deg, var(--warn) 0%, var(--accent) 45%, var(--highlight2) 100%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  filter: drop-shadow(0 0 10px color-mix(in srgb, var(--accent) 35%, transparent));
}
.tok.urgent {
  color: var(--warn);
  font-weight: 900;
  text-shadow: 0 0 16px color-mix(in srgb, var(--warn) 55%, transparent);
}
.tok.trust {
  color: var(--glow);
  font-weight: 700;
  border-bottom: 2px solid color-mix(in srgb, var(--accent) 70%, transparent);
}
.tok.emo {
  color: var(--accent);
  font-weight: 900;
  font-style: italic;
}
.tok.quote {
  color: var(--glow);
  font-weight: 800;
  font-style: italic;
}
.tok.num {
  font-weight: 900;
  background: linear-gradient(95deg, var(--warn), var(--accent) 55%, var(--highlight2));
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  padding: 0 2px;
}
.tok.en {
  color: var(--highlight2);
  font-weight: 800;
  letter-spacing: 0.05em;
}
"""


def _base_css(pal: dict[str, str], width: int, height: int) -> str:
    landscape = width > height
    body_cls = "landscape" if landscape else "portrait"
    return f"""
:root {{
  --top: {pal['top']};
  --bottom: {pal['bottom']};
  --text: {pal['text']};
  --accent: {pal['accent']};
  --outline: {pal['outline']};
  --muted: {pal['muted']};
  --highlight2: {pal['highlight2']};
  --glow: {pal['glow']};
  --panel: {pal['panel']};
  --warn: {pal['warn']};
  --hook_bg: {pal['hook_bg']};
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
{_viewport_css(width, height)}
body.{body_cls} {{
  background:
    radial-gradient(ellipse 80% 55% at 15% 12%, color-mix(in srgb, var(--accent) 28%, transparent), transparent 58%),
    radial-gradient(ellipse 70% 50% at 88% 78%, color-mix(in srgb, var(--highlight2) 22%, transparent), transparent 55%),
    linear-gradient(155deg, var(--top) 0%, var(--bottom) 68%);
  font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
  overflow: hidden;
  color: var(--text);
}}
{_smart_text_css()}
.blob {{
  position: absolute;
  border-radius: 50%;
  background: var(--accent);
  opacity: 0.16;
  filter: blur(72px);
  animation: float 7s ease-in-out infinite;
}}
@keyframes float {{
  0%, 100% {{ transform: translate(-12%, -8%) scale(1); }}
  50% {{ transform: translate(14%, 10%) scale(1.08); }}
}}
"""


def _title_size(landscape: bool, large: bool = True) -> str:
    return _title_size_for_text("", landscape, large=large)


def _build_kinetic_html(
    text: str,
    pal: dict[str, str],
    progress: float,
    width: int,
    height: int,
    *,
    font_scale: float = 1.0,
) -> str:
    landscape = width > height
    lines = _split_lines(text, 10, landscape=landscape)
    body = colorize_block_html(lines)
    p = max(0.0, min(1.0, progress))
    align = "center"
    text_align = "center"
    fs = _title_size_for_text(text, landscape, fusion=True, font_scale=font_scale)
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
{_base_css(pal, width, height)}
body {{ display:flex; align-items:center; justify-content:{align}; }}
.wrap {{ position:relative; z-index:2; text-align:{text_align}; width:100%; box-sizing:border-box; }}
h1 {{
  font-size: {fs};
  line-height: 1.58;
  font-weight: 800;
  width: 100%;
  text-align: center;
  align-items: center;
  text-shadow: 0 6px 28px rgba(0,0,0,.38);
  animation: rise .95s cubic-bezier(.22,1,.36,1) both;
  animation-delay: calc(-1 * {p:.4f} * .95s);
}}
@keyframes rise {{
  from {{ opacity:0; transform: translateY(56px) scale(.92); }}
  to {{ opacity:1; transform:none; }}
}}
.bar {{
  width:128px; height:7px; margin:36px auto 0; border-radius:4px;
  background: linear-gradient(90deg, var(--accent), var(--outline));
  animation: grow .75s ease-out both;
  animation-delay: calc(-1 * {p:.4f} * .75s + .12s);
}}
@keyframes grow {{ from {{ width:0; opacity:0; }} to {{ width:128px; opacity:1; }} }}
</style></head><body class="{'landscape' if landscape else 'portrait'}">
<div class="blob" style="left:8%;top:12%;width:520px;height:520px;"></div>
<div class="blob" style="right:6%;bottom:16%;width:440px;height:440px;animation-delay:-2.4s;"></div>
<div class="wrap"><h1>{body}</h1><div class="bar"></div></div>
</body></html>"""


def _build_hero_html(
    text: str,
    pal: dict[str, str],
    progress: float,
    width: int,
    height: int,
    *,
    font_scale: float = 1.0,
) -> str:
    landscape = width > height
    lines = _split_lines(text, 16, landscape=landscape)
    title = colorize_line_html(lines[0], 0) if lines else ""
    sub = colorize_line_html(" ".join(lines[1:]), 1) if len(lines) > 1 else ""
    p = max(0.0, min(1.0, progress))
    justify = "center" if landscape else "flex-end"
    fs = max(0.7, min(2.0, float(font_scale or 1.0)))
    tag_px = _scale_px(26 if not landscape else 22, fs)
    sub_px = _scale_px(34 if not landscape else 28, fs)
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
{_base_css(pal, width, height)}
body {{ display:flex; flex-direction:column; justify-content:{justify}; align-items:center; text-align:center; }}
.tag {{
  display:inline-block; padding:10px 18px; border-radius:999px;
  background: color-mix(in srgb, var(--accent) 22%, transparent);
  border: 1px solid color-mix(in srgb, var(--accent) 55%, transparent);
  font-size: {tag_px}px; letter-spacing:.08em; margin-bottom:28px;
  color: var(--accent); font-weight: 700;
  animation: fade .7s ease both; animation-delay: calc(-1 * {p:.4f} * .7s);
}}
h1 {{ font-size: {_title_size_for_text(text, landscape, fusion=True, font_scale=fs)}; line-height:1.55; font-weight:800;
  animation: slide .9s cubic-bezier(.22,1,.36,1) both;
  animation-delay: calc(-1 * {p:.4f} * .9s + .08s);
}}
p.sub {{
  margin-top:28px; font-size:{sub_px}px; line-height:1.55; max-width:100%;
  animation: fade .85s ease both; animation-delay: calc(-1 * {p:.4f} * .85s + .22s);
}}
@keyframes fade {{ from {{ opacity:0; }} to {{ opacity:1; }} }}
@keyframes slide {{ from {{ opacity:0; transform:translateX(-48px); }} to {{ opacity:1; transform:none; }} }}
</style></head><body class="{'landscape' if landscape else 'portrait'}">
<div class="blob" style="right:-8%;top:-6%;width:620px;height:620px;"></div>
<span class="tag">重点</span>
<h1>{title}</h1>
{f'<p class="sub">{sub}</p>' if sub else ''}
</body></html>"""


def _build_bullets_html(
    text: str,
    pal: dict[str, str],
    progress: float,
    width: int,
    height: int,
    *,
    font_scale: float = 1.0,
) -> str:
    landscape = width > height
    lines = _split_lines(text, 14 if landscape else 18, landscape=landscape)
    if len(lines) == 1 and len(lines[0]) > 10:
        lines = _split_lines(text, 10, landscape=landscape)
    items = "".join(
        f'<li style="animation-delay:calc(-1 * {max(0.0, min(1.0, progress)):.4f} * .65s + {i * 0.12:.2f}s)">'
        f"<span></span>{colorize_line_html(ln, i)}</li>"
        for i, ln in enumerate(lines[:5])
    )
    p = max(0.0, min(1.0, progress))
    cols = "grid-template-columns:1fr 1fr; gap:18px 32px;" if landscape and len(lines) > 2 else ""
    fs = max(0.7, min(2.0, float(font_scale or 1.0)))
    h2_px = _scale_px(36 if landscape else 42, fs)
    li_px = _scale_px(30 if landscape else 36, fs)
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
{_base_css(pal, width, height)}
body {{ display:flex; align-items:center; justify-content:center; }}
.panel {{
  position:relative; z-index:2; width:100%;
  padding:{'44px 48px' if landscape else '56px 52px'}; border-radius:28px;
  background: color-mix(in srgb, var(--panel) 88%, transparent);
  border: 1px solid color-mix(in srgb, var(--outline) 35%, transparent);
  box-shadow: 0 24px 80px rgba(0,0,0,.28);
  text-align:center;
}}
h2 {{ font-size:{h2_px}px; margin-bottom:28px;
  background: linear-gradient(90deg, var(--accent), var(--highlight2));
  -webkit-background-clip:text; background-clip:text; color:transparent; }}
ul {{ list-style:none; display:grid; gap:22px; {cols} }}
li {{
  font-size:{li_px}px; line-height:1.35; display:flex; gap:18px; align-items:flex-start;
  animation: pop .65s cubic-bezier(.22,1,.36,1) both;
}}
li span {{
  flex-shrink:0; width:14px; height:14px; margin-top:14px; border-radius:50%;
  background: linear-gradient(135deg, var(--accent), var(--outline));
  box-shadow: 0 0 18px color-mix(in srgb, var(--accent) 60%, transparent);
}}
@keyframes pop {{ from {{ opacity:0; transform:translateX(-28px); }} to {{ opacity:1; transform:none; }} }}
</style></head><body class="{'landscape' if landscape else 'portrait'}">
<div class="blob" style="left:10%;bottom:8%;width:500px;height:500px;"></div>
<div class="panel"><h2>要点</h2><ul>{items}</ul></div>
</body></html>"""


def _build_quote_html(
    text: str,
    pal: dict[str, str],
    progress: float,
    width: int,
    height: int,
    *,
    font_scale: float = 1.0,
) -> str:
    landscape = width > height
    lines = _split_lines(text, 12, landscape=landscape)
    quote = colorize_block_html(lines)
    p = max(0.0, min(1.0, progress))
    fs = _title_size_for_text(text, landscape, fusion=True, font_scale=font_scale)
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
{_base_css(pal, width, height)}
body {{ display:flex; align-items:center; justify-content:center; }}
blockquote {{
  position:relative; z-index:2; max-width:92%; text-align:center;
  font-size: {fs}; line-height:1.58; font-weight:600;
  animation: zoom .9s cubic-bezier(.22,1,.36,1) both;
  animation-delay: calc(-1 * {p:.4f} * .9s);
}}
blockquote::before, blockquote::after {{
  content:"\\201C"; position:absolute; font-size:120px; opacity:.22; color:var(--accent);
}}
blockquote::before {{ left:-12px; top:-36px; }}
blockquote::after {{ content:"\\201D"; right:-8px; bottom:-64px; }}
@keyframes zoom {{ from {{ opacity:0; transform:scale(.9); }} to {{ opacity:1; transform:none; }} }}
</style></head><body class="{'landscape' if landscape else 'portrait'}">
<div class="blob" style="left:18%;top:20%;width:460px;height:460px;"></div>
<div class="blob" style="right:12%;bottom:18%;width:380px;height:380px;animation-delay:-3s;"></div>
<blockquote>{quote}</blockquote>
</body></html>"""


def _build_glass_html(
    text: str,
    pal: dict[str, str],
    progress: float,
    width: int,
    height: int,
    *,
    font_scale: float = 1.0,
) -> str:
    landscape = width > height
    lines = _split_lines(text, 14, landscape=landscape)
    body = colorize_block_html(lines)
    p = max(0.0, min(1.0, progress))
    fs = _title_size_for_text(text, landscape, fusion=True, font_scale=font_scale)
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
{_base_css(pal, width, height)}
body {{ display:flex; align-items:center; justify-content:center; }}
.glass {{
  position:relative; z-index:2; width:min(900px, 92vw); padding:{'48px 44px' if landscape else '64px 56px'};
  border-radius:32px;
  background: color-mix(in srgb, var(--text) 8%, transparent);
  backdrop-filter: blur(22px) saturate(1.35);
  -webkit-backdrop-filter: blur(22px) saturate(1.35);
  border: 1px solid color-mix(in srgb, var(--text) 22%, transparent);
  box-shadow: 0 28px 90px rgba(0,0,0,.32), inset 0 1px 0 color-mix(in srgb, var(--text) 18%, transparent);
  text-align:center;
  animation: floatin .95s cubic-bezier(.22,1,.36,1) both;
  animation-delay: calc(-1 * {p:.4f} * .95s);
}}
.glass p {{ font-size: {fs}; line-height:1.58; font-weight:700; }}
@keyframes floatin {{ from {{ opacity:0; transform:translateY(40px); }} to {{ opacity:1; transform:none; }} }}
</style></head><body class="{'landscape' if landscape else 'portrait'}">
<div class="blob" style="left:5%;top:10%;width:560px;height:560px;"></div>
<div class="blob" style="right:0;bottom:5%;width:480px;height:480px;animation-delay:-2s;"></div>
<div class="glass"><p>{body}</p></div>
</body></html>"""


def _fusion_body_layout_css(width: int, height: int, *, landscape: bool) -> str:
    """Flex placement for fusion PiP cards — centered, mobile-readable."""
    if landscape:
        pad_v = int(height * 0.10)
        pad_h = int(width * 0.08)
        return f"""  align-items: center;
  justify-content: center;
  padding: {pad_v}px {pad_h}px;"""
    pad_top = int(height * 0.14)
    pad_side = int(width * 0.04)
    pad_bottom = int(height * 0.24)
    return f"""  align-items: center;
  justify-content: flex-start;
  padding: {pad_top}px {pad_side}px {pad_bottom}px;"""


def _fusion_card_width_expr(width: int, *, landscape: bool) -> str:
    if landscape:
        return f"min({int(width * 0.88)}px, 92%)"
    return f"min({int(width * 0.92)}px, 94%)"


def _text_card_css(
    pal: dict[str, str], width: int, height: int, text: str = "", *, font_scale: float = 1.0
) -> str:
    """Black canvas (colorkey) + glassmorphism panel for lipsync PiP overlay."""
    landscape = width > height
    body_cls = "landscape" if landscape else "portrait"
    fs = max(0.7, min(2.0, float(font_scale or 1.0)))
    li_px = _scale_px(34 if landscape else 36, fs)
    eyebrow_px = _scale_px(20 if landscape else 22, fs)
    meta_px = _scale_px(18 if landscape else 20, fs)
    return f"""
:root {{
  --text: {pal['text']};
  --accent: {pal['accent']};
  --outline: {pal['outline']};
  --muted: {pal['muted']};
  --highlight2: {pal['highlight2']};
  --glow: {pal['glow']};
  --warn: {pal['warn']};
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
{_fusion_viewport_css(width, height)}
body.{body_cls} {{
  background: #000000;
  font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans SC", sans-serif;
  overflow: hidden;
  color: var(--text);
  display: flex;
{_fusion_body_layout_css(width, height, landscape=landscape)}
}}
{_smart_text_css()}
.text-card {{
  position: relative;
  z-index: 2;
  width: {_fusion_card_width_expr(width, landscape=landscape)};
  max-width: {'92%' if landscape else '94%'};
  margin: 0 auto;
  text-align: center;
  padding: {'28px 36px' if landscape else '32px 36px'};
  border-radius: 22px;
  /* Lighter frosted panel — avoid near-black fills that colorkey eats */
  background: linear-gradient(
    155deg,
    rgba(255, 255, 255, 0.34) 0%,
    rgba(230, 236, 255, 0.28) 42%,
    rgba(180, 198, 255, 0.22) 100%
  );
  border: 1px solid rgba(255, 255, 255, 0.55);
  box-shadow:
    0 0 0 1px rgba(122, 162, 247, 0.35) inset,
    0 14px 36px rgba(0, 0, 0, 0.35),
    0 0 28px color-mix(in srgb, var(--accent) 40%, transparent);
}}
.text-card .eyebrow {{
  font-size: {eyebrow_px}px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: color-mix(in srgb, var(--accent) 70%, #fff);
  font-weight: 700;
  margin-bottom: 10px;
  opacity: 1;
  text-shadow: 0 1px 2px rgba(0,0,0,.55);
}}
.text-card h1 {{
  font-size: {_title_size_for_text(text, landscape, fusion=True, font_scale=fs)};
  line-height: 1.38;
  font-weight: 800;
  color: #ffffff;
  text-align: center;
  text-shadow:
    0 0 2px rgba(0,0,0,.95),
    0 2px 0 rgba(0,0,0,.75),
    0 4px 14px rgba(0,0,0,.55);
  margin-bottom: 14px;
}}
.text-card ul {{
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 12px;
  text-align: center;
  align-items: center;
  margin: 0 auto;
  max-width: 96%;
}}
.text-card li {{
  font-size: {li_px}px;
  line-height: 1.38;
  font-weight: 700;
  padding-left: 0;
  border-left: none;
  border-bottom: 2px solid color-mix(in srgb, var(--accent) 55%, transparent);
  padding-bottom: 8px;
  color: #f5f7ff;
  text-shadow: 0 1px 3px rgba(0,0,0,.7);
}}
.text-card li .meta {{
  display: block;
  margin-top: 2px;
  font-size: {meta_px}px;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: color-mix(in srgb, var(--accent) 55%, #fff);
  opacity: 1;
}}
"""


def _split_bullet_meta(item: str) -> tuple[str, str]:
    """Split '剪辑 — PREMIERE' into label + meta."""
    for sep in (" — ", " – ", " - ", "——", "—", "–"):
        if sep in item:
            a, b = item.split(sep, 1)
            return a.strip(), b.strip()
    return item.strip(), ""


def _fusion_motion_css(selector: str, motion: str, progress: float) -> str:
    """CSS for smart fusion enter motions (scrubbed via animation-delay)."""
    p = max(0.0, min(1.0, float(progress)))
    key = (motion or "pop_scale").strip().lower()
    dur = 1.25
    easing = "cubic-bezier(.22,1,.36,1)"
    frames: dict[str, str] = {
        "slide_ltr": """
@keyframes fusionMotion {
  0% { opacity:0; transform: translateX(-56px) scale(.9); }
  20% { opacity:1; transform: translateX(0) scale(1); }
  55% { transform: translateX(18px) scale(1.04); }
  100% { opacity:1; transform: translateX(0) scale(1); }
}""",
        "slide_rtl": """
@keyframes fusionMotion {
  0% { opacity:0; transform: translateX(56px) scale(.9); }
  20% { opacity:1; transform: translateX(0) scale(1); }
  55% { transform: translateX(-18px) scale(1.04); }
  100% { opacity:1; transform: translateX(0) scale(1); }
}""",
        "slide_scale": """
@keyframes fusionMotion {
  0% { opacity:0; transform: translateX(-52px) scale(.86); }
  16% { opacity:1; transform: translateX(0) scale(1); }
  42% { transform: translateX(24px) scale(1.07); }
  68% { transform: translateX(-14px) scale(.97); }
  100% { opacity:1; transform: translateX(0) scale(1); }
}""",
        "pop_scale": """
@keyframes fusionMotion {
  0% { opacity:0; transform: scale(.72); }
  35% { opacity:1; transform: scale(1.12); }
  62% { transform: scale(.96); }
  100% { opacity:1; transform: scale(1); }
}""",
        "rise_soft": """
@keyframes fusionMotion {
  0% { opacity:0; transform: translateY(36px) scale(.94); }
  40% { opacity:1; transform: translateY(0) scale(1.02); }
  100% { opacity:1; transform: translateY(0) scale(1); }
}""",
        "pulse": """
@keyframes fusionMotion {
  0% { opacity:0; transform: scale(.8); }
  25% { opacity:1; transform: scale(1.14); }
  50% { transform: scale(.95); }
  75% { transform: scale(1.06); }
  100% { opacity:1; transform: scale(1); }
}""",
        "drift": """
@keyframes fusionMotion {
  0% { opacity:0; transform: translate(-28px, 12px) scale(.92); }
  30% { opacity:1; transform: translate(10px, -6px) scale(1.03); }
  70% { transform: translate(-8px, 4px) scale(.99); }
  100% { opacity:1; transform: translate(0, 0) scale(1); }
}""",
    }
    kf = frames.get(key, frames["pop_scale"])
    return f"""
{kf}
{selector} {{
  animation: fusionMotion {dur}s {easing} both;
  animation-delay: calc(-1 * {p:.4f} * {dur}s);
}}
"""


def _build_text_card_html(
    text: str,
    pal: dict[str, str],
    progress: float,
    width: int,
    height: int,
    *,
    motion: str = "slide_scale",
    font_scale: float = 1.0,
) -> str:
    from workflow.glass_cards import parse_card_display_text

    landscape = width > height
    parsed = parse_card_display_text(text)
    title = parsed.get("title") or ""
    bullets = parsed.get("bullets") or []
    # Fallback: plain paragraph card when no structure
    if not bullets and "\n" not in (text or "") and "•" not in (text or ""):
        lines = _split_lines(text, 12, landscape=landscape)
        body = colorize_block_html(lines)
        bullet_html = ""
        title_html = f"<h1>{body}</h1>"
    else:
        title_html = f"<h1>{colorize_block_html([title]) if title else ''}</h1>"
        items = []
        for b in bullets:
            label, meta = _split_bullet_meta(str(b))
            meta_html = f'<span class="meta">{meta}</span>' if meta else ""
            items.append(f"<li>{colorize_block_html([label])}{meta_html}</li>")
        bullet_html = f"<ul>{''.join(items)}</ul>" if items else ""
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
{_text_card_css(pal, width, height, title or text, font_scale=font_scale)}
{_fusion_motion_css('.text-card', motion, progress)}
</style></head><body class="{'landscape' if landscape else 'portrait'}">
<div class="text-card">{title_html}{bullet_html}</div>
</body></html>"""


def _plain_text_css(
    pal: dict[str, str], width: int, height: int, text: str = "", *, font_scale: float = 1.0
) -> str:
    """Black canvas (colorkey) + text only — no glass panel."""
    landscape = width > height
    body_cls = "landscape" if landscape else "portrait"
    fs = max(0.7, min(2.0, float(font_scale or 1.0)))
    li_px = _scale_px(34 if landscape else 36, fs)
    meta_px = _scale_px(18 if landscape else 20, fs)
    return f"""
:root {{
  --text: {pal['text']};
  --accent: {pal['accent']};
  --muted: {pal['muted']};
  --glow: {pal['glow']};
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
{_fusion_viewport_css(width, height)}
body.{body_cls} {{
  background: #000000;
  font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans SC", sans-serif;
  overflow: hidden;
  color: var(--text);
  display: flex;
{_fusion_body_layout_css(width, height, landscape=landscape)}
}}
{_smart_text_css()}
.plain-text {{
  position: relative;
  z-index: 2;
  width: {_fusion_card_width_expr(width, landscape=landscape)};
  max-width: {'92%' if landscape else '94%'};
  margin: 0 auto;
  text-align: center;
  background: transparent;
  border: none;
  box-shadow: none;
}}
.plain-text h1 {{
  font-size: {_title_size_for_text(text, landscape, fusion=True, font_scale=fs)};
  line-height: 1.36;
  font-weight: 800;
  color: #ffffff;
  text-align: center;
  text-shadow:
    0 0 2px rgba(0,0,0,.98),
    0 2px 0 rgba(0,0,0,.85),
    0 4px 16px rgba(0,0,0,.65),
    0 0 22px color-mix(in srgb, var(--accent) 45%, transparent);
  margin-bottom: 12px;
}}
.plain-text ul {{
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 12px;
  text-align: center;
  align-items: center;
  margin: 0 auto;
  max-width: 96%;
}}
.plain-text li {{
  font-size: {li_px}px;
  line-height: 1.38;
  font-weight: 700;
  color: #f7f9ff;
  text-shadow: 0 0 2px rgba(0,0,0,.95), 0 2px 10px rgba(0,0,0,.75);
}}
.plain-text li .meta {{
  display: block;
  margin-top: 2px;
  font-size: {meta_px}px;
  font-weight: 600;
  color: color-mix(in srgb, var(--accent) 60%, #fff);
}}
"""


def _build_plain_text_html(
    text: str,
    pal: dict[str, str],
    progress: float,
    width: int,
    height: int,
    *,
    motion: str = "slide_scale",
    font_scale: float = 1.0,
) -> str:
    from workflow.glass_cards import parse_card_display_text

    landscape = width > height
    parsed = parse_card_display_text(text)
    title = parsed.get("title") or ""
    bullets = parsed.get("bullets") or []
    if not bullets and "\n" not in (text or "") and "•" not in (text or ""):
        lines = _split_lines(text, 12, landscape=landscape)
        title_html = f"<h1>{colorize_block_html(lines)}</h1>"
        bullet_html = ""
    else:
        title_html = f"<h1>{colorize_block_html([title]) if title else ''}</h1>"
        items = []
        for b in bullets:
            label, meta = _split_bullet_meta(str(b))
            meta_html = f'<span class="meta">{meta}</span>' if meta else ""
            items.append(f"<li>{colorize_block_html([label])}{meta_html}</li>")
        bullet_html = f"<ul>{''.join(items)}</ul>" if items else ""
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
{_plain_text_css(pal, width, height, title or text, font_scale=font_scale)}
{_fusion_motion_css('.plain-text', motion, progress)}
</style></head><body class="{'landscape' if landscape else 'portrait'}">
<div class="plain-text">{title_html}{bullet_html}</div>
</body></html>"""


def _build_card_html(
    text: str,
    pal: dict[str, str],
    progress: float,
    width: int,
    height: int,
    *,
    font_scale: float = 1.0,
) -> str:
    landscape = width > height
    lines = _split_lines(text, 10, landscape=landscape)
    body = colorize_block_html(lines)
    p = max(0.0, min(1.0, progress))
    panel_w = int(width * (0.88 if landscape else 0.9))
    panel_h = int(height * (0.72 if landscape else 0.42))
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
{_base_css(pal, width, height)}
body {{ display:flex; align-items:center; justify-content:center; }}
.card {{
  position:relative; z-index:2; width:{panel_w}px; min-height:{panel_h}px;
  padding:48px 40px; border-radius:24px;
  background: linear-gradient(145deg, color-mix(in srgb, var(--top) 85%, #000), color-mix(in srgb, var(--bottom) 90%, #000));
  border: 3px solid color-mix(in srgb, var(--outline) 65%, transparent);
  box-shadow: 0 20px 60px rgba(0,0,0,.35);
  text-align:center;
  animation: rise .85s ease both;
  animation-delay: calc(-1 * {p:.4f} * .85s);
}}
.card::before {{
  content:''; position:absolute; left:0; top:0; right:0; height:10px;
  background: linear-gradient(90deg, var(--accent), var(--highlight2));
  border-radius:24px 24px 0 0;
}}
.card h1 {{ font-size: {_title_size_for_text(text, landscape, fusion=True, font_scale=font_scale)}; line-height:1.58; margin-top:12px; }}
@keyframes rise {{ from {{ opacity:0; transform:translateY(32px); }} to {{ opacity:1; transform:none; }} }}
</style></head><body class="{'landscape' if landscape else 'portrait'}">
<div class="blob" style="left:12%;top:18%;width:400px;height:400px;"></div>
<div class="card"><h1>{body}</h1></div>
</body></html>"""


def build_scene_html(
    text: str,
    layout: str,
    theme: dict,
    progress: float = 0.75,
    *,
    aspect: str = DEFAULT_ASPECT,
    motion: str | None = None,
    motion_index: int = 0,
    font_scale: float = 1.0,
) -> str:
    pal = _theme_palette(theme)
    width, height = resolve_dimensions(layout, aspect)
    key = normalize_layout_key(layout)
    fs = max(0.7, min(2.0, float(font_scale or 1.0)))
    builders = {
        "card": _build_card_html,
        "kinetic": _build_kinetic_html,
        "hero": _build_hero_html,
        "bullets": _build_bullets_html,
        "quote": _build_quote_html,
        "glass": _build_glass_html,
        "text_card": _build_text_card_html,
        "plain_text": _build_plain_text_html,
    }
    builder = builders.get(key, _build_kinetic_html)
    if key in ("text_card", "glass_card", "plain_text") or is_fusion_layout(key):
        if key == "glass_card":
            builder = _build_text_card_html
        mot = (motion or "").strip().lower()
        if not mot:
            try:
                from workflow.hyperframes import suggest_fusion_motion

                mot = str(suggest_fusion_motion(text, index=motion_index).get("motion") or "pop_scale")
            except Exception:
                mot = "pop_scale"
        return builder(text, pal, progress, width, height, motion=mot, font_scale=fs)
    return builder(text, pal, progress, width, height, font_scale=fs)


def capture_html_to_png(
    html_content: str,
    output_path: Path,
    *,
    width: int,
    height: int,
) -> bool:
    browser = _find_headless_browser()
    if not browser:
        return False
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        html_path = Path(tmp) / "scene.html"
        html_path.write_text(html_content, encoding="utf-8")
        cmd = [
            browser,
            "--headless=new",
            f"--screenshot={output_path.resolve()}",
            f"--window-size={width},{height}",
            "--hide-scrollbars",
            "--force-device-scale-factor=1",
            html_path.as_uri(),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=45)
            return output_path.is_file()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
            return False


def _ease_out(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1.0 - (1.0 - t) ** 3


def render_pil_scene_frame(
    text: str,
    output_path: Path,
    *,
    layout: str,
    theme: dict,
    progress: float = 0.75,
    aspect: str = DEFAULT_ASPECT,
    font_scale: float = 1.0,
) -> Path:
    """PIL fallback when headless CSS capture is unavailable."""
    from PIL import Image, ImageDraw, ImageFilter

    w, h = resolve_dimensions(layout, aspect)
    pal = theme
    layout_key = normalize_layout_key(layout)
    img = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(img)
    if layout_key in ("text_card", "plain_text") or is_fusion_layout(layout):
        draw.rectangle([(0, 0), (w, h)], fill=(0, 0, 0))
    else:
        r1, g1, b1 = pal["top"]
        r2, g2, b2 = pal["bottom"]
        for y in range(h):
            t = y / max(h - 1, 1)
            color = (
                int(r1 * (1 - t) + r2 * t),
                int(g1 * (1 - t) + g2 * t),
                int(b1 * (1 - t) + b2 * t),
            )
            draw.line([(0, y), (w, y)], fill=color)

        ar, ag, ab = pal["accent_bar"]
        blob = Image.new("RGB", (w, h), (ar, ag, ab))
        mask = Image.new("L", (w, h), 0)
        md = ImageDraw.Draw(mask)
        cx = int(w * (0.25 + 0.1 * math.sin(progress * 6.28)))
        cy = int(h * (0.2 + 0.08 * math.cos(progress * 6.28)))
        md.ellipse((cx - 220, cy - 220, cx + 220, cy + 220), fill=90)
        img = Image.composite(blob, img, mask.filter(ImageFilter.GaussianBlur(48)))

    from workflow.hyperframes import _load_font

    landscape = w > h
    lines = _split_lines(text, 10 if layout != "bullets" else 14, landscape=landscape)
    alpha = _ease_out(min(1.0, progress * 1.35))
    offset_y = int((1.0 - _ease_out(progress)) * 48)
    longest = max((len(x) for x in lines), default=1)
    base_div = 18 if landscape else 14
    if longest >= 14:
        base_div += 4
    if longest >= 20:
        base_div += 4
    fs = max(0.7, min(2.0, float(font_scale or 1.0)))
    font_main = _load_font(max(int((28 if landscape else 32) * fs), int(w // base_div * fs)))
    font_sub = _load_font(max(int((22 if landscape else 24) * fs), int(w // (base_div + 6) * fs)))
    tr, tg, tb = pal["text"]
    colors = _pil_class_colors(pal)
    line_gap = max(int(font_main.size * 1.65), font_main.size + 28)
    y0 = (h - len(lines) * line_gap) // 2 + offset_y
    for i, line in enumerate(lines[:4]):
        font = font_main if i == 0 or layout != "hero" else font_sub
        y = y0 + i * line_gap
        if alpha < 1:
            layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            ld = ImageDraw.Draw(layer)
            _draw_smart_line(
                ld, center_x=w // 2, y=y, line=line, font=font, colors=colors, alpha=alpha
            )
            img = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")
            draw = ImageDraw.Draw(img)
        else:
            rgba = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            ld = ImageDraw.Draw(rgba)
            _draw_smart_line(
                ld, center_x=w // 2, y=y, line=line, font=font, colors=colors, alpha=1.0
            )
            img = Image.alpha_composite(img.convert("RGBA"), rgba).convert("RGB")
            draw = ImageDraw.Draw(img)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, quality=92)
    return output_path


def render_scene_still(
    text: str,
    output_path: Path,
    *,
    layout: str,
    theme: dict,
    progress: float = 0.78,
    aspect: str = DEFAULT_ASPECT,
    font_scale: float = 1.0,
) -> Path:
    meta = resolve_layout(layout)
    width, height = resolve_dimensions(layout, aspect)
    if meta.get("css"):
        html = build_scene_html(
            text,
            layout,
            theme,
            progress=progress,
            aspect=aspect,
            font_scale=font_scale,
        )
        if capture_html_to_png(html, output_path, width=width, height=height):
            return output_path
    return render_pil_scene_frame(
        text,
        output_path,
        layout=layout,
        theme=theme,
        progress=progress,
        aspect=aspect,
        font_scale=font_scale,
    )


def generate_scene_video(
    text: str,
    output_path: Path,
    *,
    duration_sec: float = 3.0,
    layout: str = DEFAULT_SCENE_LAYOUT,
    theme: dict,
    ffmpeg_bin: str = "ffmpeg",
    fps: int = SCENE_FPS,
    aspect: str = DEFAULT_ASPECT,
    prefer_pil: bool = True,
    max_frames: int = 10,
    style_pack: dict | None = None,
    motion: str | None = None,
    motion_index: int = 0,
) -> Path:
    """Render scene video: official HyperFrames when available, else PIL hold clip.

    Prefers official heygen HyperFrames (tools/hf-bridge) for real GSAP motion.
    Falls back to PIL + last-frame hold so pipelines never hard-fail.
    """
    from workflow.scene_style_pack import ensure_extra_layouts_registered

    ensure_extra_layouts_registered()
    meta = resolve_layout(layout)
    duration_sec = max(0.8, min(float(duration_sec), 120.0))
    width, height = resolve_dimensions(layout, aspect)
    smart_kw = bool((style_pack or {}).get("smart_keywords", True))

    with smart_keywords_scope(smart_kw):
        return _generate_scene_video_inner(
            text,
            output_path,
            duration_sec=duration_sec,
            layout=layout,
            theme=theme,
            ffmpeg_bin=ffmpeg_bin,
            fps=fps,
            aspect=aspect,
            prefer_pil=prefer_pil,
            max_frames=max_frames,
            style_pack=style_pack,
            motion=motion,
            motion_index=motion_index,
            meta=meta,
            width=width,
            height=height,
        )


def _generate_scene_video_inner(
    text: str,
    output_path: Path,
    *,
    duration_sec: float,
    layout: str,
    theme: dict,
    ffmpeg_bin: str,
    fps: int,
    aspect: str,
    prefer_pil: bool,
    max_frames: int,
    style_pack: dict | None,
    motion: str | None,
    motion_index: int,
    meta: dict,
    width: int,
    height: int,
) -> Path:
    """Inner render body (runs under smart_keywords_scope)."""
    from workflow.hyperframes_scenes import is_fusion_layout

    use_official = True
    if is_fusion_layout(layout):
        use_official = False
    elif style_pack and str(style_pack.get("compose_mode") or "").lower() == "fusion":
        use_official = False
    elif style_pack and str(style_pack.get("bg_mode") or "").lower() in (
        "transparent",
        "none",
        "off",
    ):
        use_official = False
    elif style_pack and (
        style_pack.get("picker_preview") or style_pack.get("skip_official")
    ):
        # Theme picker: match still preview (CSS capture), not hf-bridge layout drift
        use_official = False
    elif str((style_pack or {}).get("compose_mode") or "").lower() == "cover":
        # Cover PiP scenes: same CSS renderer as modal preview
        use_official = False

    try:
        from workflow.hf_official import is_available, render_scene

        if use_official and is_available():
            return render_scene(
                text,
                Path(output_path),
                layout=(layout or DEFAULT_SCENE_LAYOUT),
                theme=theme,
                duration_sec=duration_sec,
                width=width,
                height=height,
                style_pack=style_pack,
            )
    except Exception:
        import logging

        logging.getLogger(__name__).exception(
            "official HyperFrames render failed; falling back to PIL"
        )

    work = output_path.parent / f"hf_scene_{layout}_work"
    work.mkdir(parents=True, exist_ok=True)
    frames_dir = work / "frames"
    if frames_dir.is_dir():
        for old in frames_dir.glob("*.png"):
            try:
                old.unlink()
            except OSError:
                pass
    frames_dir.mkdir(parents=True, exist_ok=True)

    # Motion intro (~0.7–1.6s), then freeze — except fusion cards: full-window slide+scale
    fusion = is_fusion_layout(layout)
    fusion_motion = (motion or "").strip().lower()
    if fusion and not fusion_motion:
        try:
            from workflow.hyperframes import suggest_fusion_motion

            fusion_motion = str(
                suggest_fusion_motion(text, index=motion_index).get("motion") or "pop_scale"
            )
        except Exception:
            fusion_motion = "pop_scale"
    if fusion:
        anim_sec = max(1.0, min(float(duration_sec), 8.0))
        n_frames = max(10, min(28, int(anim_sec * 7) + 1))
    else:
        anim_sec = min(1.6, max(0.7, min(duration_sec, duration_sec * 0.45)))
        n_frames = max(5, min(int(max_frames), int(anim_sec * max(4, min(fps, 8))) + 1))
    use_css = (
        (not prefer_pil)
        and bool(meta.get("css"))
        and _find_headless_browser() is not None
    )
    w, h = resolve_dimensions(layout, aspect)
    fs = _font_scale_value(style_pack)
    # Drive progress slower so entrance motion stays visible
    for i in range(n_frames):
        t = i / max(n_frames - 1, 1)
        if fusion:
            progress = t  # scrub full slide+scale across cue window
        else:
            progress = min(1.0, t / 0.72) if t < 0.72 else 1.0
        frame = frames_dir / f"frame_{i:04d}.png"
        if use_css:
            html = build_scene_html(
                text,
                layout,
                theme,
                progress=progress,
                aspect=aspect,
                motion=fusion_motion if fusion else None,
                motion_index=motion_index,
                font_scale=fs,
            )
            ok = capture_html_to_png(html, frame, width=w, height=h)
            if not ok:
                render_pil_scene_frame(
                    text,
                    frame,
                    layout=layout,
                    theme=theme,
                    progress=progress,
                    aspect=aspect,
                    font_scale=fs,
                )
        else:
            render_pil_scene_frame(
                text,
                frame,
                layout=layout,
                theme=theme,
                progress=progress,
                aspect=aspect,
                font_scale=fs,
            )

    last = frames_dir / f"frame_{n_frames - 1:04d}.png"
    hold_fps = max(4, min(fps, 8)) if not fusion else max(6, min(fps, 10))
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Build a short intro clip from motion frames
    intro = work / "_intro.mp4"
    crf = "18" if fusion else "23"
    subprocess.run(
        [
            ffmpeg_bin,
            "-y",
            "-framerate",
            str(hold_fps),
            "-i",
            str(frames_dir / "frame_%04d.png"),
            "-frames:v",
            str(n_frames),
            "-vf",
            "scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            crf,
            "-pix_fmt",
            "yuv420p",
            str(intro),
        ],
        check=True,
    )

    if duration_sec <= (n_frames / float(hold_fps)) + 0.05:
        shutil.copy2(intro, output_path)
        return output_path

    # Pad with frozen last frame so file length matches the cue window
    intro_dur = n_frames / float(hold_fps)
    hold_sec = max(0.1, duration_sec - intro_dur)
    subprocess.run(
        [
            ffmpeg_bin,
            "-y",
            "-i",
            str(intro),
            "-loop",
            "1",
            "-t",
            f"{hold_sec:.3f}",
            "-i",
            str(last),
            "-filter_complex",
            (
                "[0:v]scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p,setsar=1[v0];"
                f"[1:v]scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p,fps={hold_fps},setsar=1[v1];"
                "[v0][v1]concat=n=2:v=1:a=0[v]"
            ),
            "-map",
            "[v]",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            crf,
            "-pix_fmt",
            "yuv420p",
            "-t",
            f"{duration_sec:.3f}",
            str(output_path),
        ],
        check=True,
    )
    return output_path

"""Progress reporting — subprocess uses ASCII stage keys only (Windows encoding safe)."""

from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path

MARKER = "@@PROGRESS@@"

# ASCII keys -> UI 中文（仅在主进程映射，子进程不输出中文）
STAGE_LABELS: dict[str, str] = {
    "config": "读取配置",
    "prep": "准备参数",
    "load_model": "加载模型（首次较慢）",
    "gpu_synth": "GPU 合成中",
    "cpu_synth": "CPU 合成中",
    "convert_16k": "转 16kHz",
    "done": "完成",
    "indextts_done": "IndexTTS2 完成",
    "indextts_synth": "IndexTTS 合成中",
    "indextts_load": "IndexTTS 加载模型",
    "indextts_ready": "IndexTTS 模型已常驻",
    "cosyvoice_done": "CosyVoice 完成",
    "piper_done": "Piper 完成",
    "prep_video": "准备视频与音频",
    "norm_audio": "标准化音频",
    "video_fps": "转换视频帧率",
    "lipsync": "LatentSync 对口型（较慢）",
    "lipsync_load": "加载 LatentSync 模型",
    "lipsync_prep": "分析音视频",
    "lipsync_faces": "人脸检测与对齐",
    "lipsync_batch": "扩散推理（主耗时）",
    "lipsync_restore": "贴回面部",
    "lipsync_mux": "合成输出视频",
    "save_out": "保存成片",
    "lipsync_done": "对口型完成",
    "sadtalker": "SadTalker 生成",
    "sadtalker_prep": "SadTalker 预处理",
    "heygem": "HeyGem 数字人",
    "heygem_submit": "HeyGem 提交任务",
    "copy_audio": "复制音频",
}

_SEG_RE = re.compile(r"seg=(\d+)/(\d+)")
_AUDIO_RE = re.compile(r"audio=([\d.]+)")


def stage_label(key: str) -> str:
    return STAGE_LABELS.get(key, key)


def format_hms(seconds: float) -> str:
    """Format seconds as H:MM:SS (hours omitted when zero)."""
    total = max(0, int(round(seconds)))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def estimate_speech_seconds(text: str, *, chars_per_sec: float = 4.2) -> float:
    """Rough speech duration from character count (Mandarin / Latin / mixed)."""
    raw = text or ""
    compact = re.sub(r"\s+", "", raw)
    if not compact:
        return 0.0

    cjk = sum(1 for c in compact if "\u4e00" <= c <= "\u9fff")
    latin = sum(1 for c in compact if c.isascii() and c.isalpha())
    digits = sum(1 for c in compact if c.isdigit())
    other = max(0, len(compact) - cjk - latin - digits)

    if cjk == 0 and latin > 0:
        return latin / 12.0 + digits / 5.0 + other / 8.0

    # Mixed or Chinese-heavy: English tokens are spoken faster per character.
    return cjk / chars_per_sec + latin / 12.0 + digits / 5.0 + other / chars_per_sec


def emit(
    pct: float,
    stage_key: str,
    *,
    seg: tuple[int, int] | None = None,
    audio_sec: float | None = None,
) -> None:
    parts = [MARKER, f"{pct:.3f}", stage_key]
    if seg and seg[1] > 0:
        parts.append(f"seg={seg[0]}/{seg[1]}")
    if audio_sec is not None:
        parts.append(f"audio={audio_sec:.1f}")
    print(" ".join(parts), flush=True)


ProgressFn = Callable[[float, str], None]


class TtsProgressReporter:
    """Rich TTS progress: real updates + gentle fake creep, hh:mm:ss labels."""

    def __init__(
        self,
        on_progress: ProgressFn | None,
        text: str,
        *,
        span: tuple[float, float] = (0.0, 1.0),
    ) -> None:
        self.on_progress = on_progress
        self.span_start, self.span_end = span
        self.est_audio = estimate_speech_seconds(text)
        self.t0 = time.time()
        self.stage = stage_label("prep")
        self.seg_cur = 0
        self.seg_total = 0
        self.synth_audio = 0.0
        self.real_pct = self.span_start
        self.display_pct = self.span_start
        self._lock = threading.Lock()

    def _map(self, pct: float) -> float:
        return self.span_start + pct * (self.span_end - self.span_start)

    def _synth_display(self) -> float:
        if self.synth_audio > 0:
            return self.synth_audio
        if self.seg_total > 0 and self.seg_cur > 0:
            return self.est_audio * self.seg_cur / self.seg_total
        return 0.0

    def _format_desc(self, pct: float) -> str:
        elapsed = time.time() - self.t0
        synth = self._synth_display()
        seg_txt = f"{self.seg_cur}/{self.seg_total}" if self.seg_total else "—"
        pct_i = int(max(0.0, min(1.0, pct)) * 100)
        return (
            f"{self.stage} · {pct_i}% · "
            f"已用 {format_hms(elapsed)} · "
            f"段落 {seg_txt} · "
            f"预估音频 {format_hms(self.est_audio)} · "
            f"已合成 {format_hms(synth)}"
        )

    def _emit(self, *, creep: bool = False) -> None:
        if not self.on_progress:
            return
        with self._lock:
            if creep:
                cap = min(self.real_pct + 0.06, self.span_end - 0.01)
                if self.display_pct < cap:
                    self.display_pct = min(self.display_pct + 0.0015, cap)
                pct = max(self.display_pct, self.real_pct)
            else:
                self.display_pct = max(self.display_pct, self.real_pct)
                pct = self.real_pct
            self.on_progress(pct, self._format_desc(pct))

    def note_stdout(self, line: str) -> None:
        if "segments count:" in line:
            try:
                self.seg_total = int(line.rsplit("segments count:", 1)[-1].strip())
                self._emit()
            except ValueError:
                pass
        if "Generated audio length:" in line:
            try:
                raw = line.rsplit("Generated audio length:", 1)[-1].strip()
                self.synth_audio = float(raw.split()[0])
                self._emit()
            except ValueError:
                pass

    def note_marker(
        self,
        pct: float,
        key: str,
        *,
        seg: tuple[int, int] | None = None,
        audio_sec: float | None = None,
    ) -> None:
        with self._lock:
            self.real_pct = self._map(pct)
            self.stage = stage_label(key)
            if seg and seg[1] > 0:
                self.seg_cur, self.seg_total = seg
            if audio_sec is not None:
                self.synth_audio = audio_sec
        self._emit()

    def creep_tick(self) -> None:
        self._emit(creep=True)


def _parse_marker(line: str) -> tuple[float, str, tuple[int, int] | None, float | None] | None:
    if not line.startswith(MARKER):
        return None
    parts = line.split()
    if len(parts) < 3:
        return None
    pct = float(parts[1])
    key = parts[2]
    seg = None
    audio_sec = None
    for part in parts[3:]:
        m = _SEG_RE.match(part)
        if m:
            seg = (int(m.group(1)), int(m.group(2)))
            continue
        m = _AUDIO_RE.match(part)
        if m:
            audio_sec = float(m.group(1))
    return pct, key, seg, audio_sec


def run_cmd_with_progress(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    env: dict | None = None,
    on_progress: ProgressFn | None = None,
    span: tuple[float, float] = (0.0, 1.0),
    progress_text: str = "",
    fake_creep: bool = True,
) -> subprocess.CompletedProcess:
    from workflow.task_control import TaskCancelled, check_cancelled, is_cancelled, register_proc, unregister_proc

    start, end = span
    reporter = TtsProgressReporter(on_progress, progress_text, span=(start, end)) if progress_text else None
    stop = threading.Event()
    last_real_update = time.time()

    def creep_loop() -> None:
        while not stop.wait(1.0):
            if not fake_creep or reporter is None:
                continue
            if time.time() - last_real_update > 1.2:
                reporter.creep_tick()

    creep_thread = threading.Thread(target=creep_loop, daemon=True)
    creep_thread.start()

    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    register_proc(proc)

    def kill_on_cancel() -> None:
        while proc.poll() is None:
            if stop.wait(0.4):
                return
            if is_cancelled():
                try:
                    if os.name == "nt":
                        subprocess.run(
                            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                            capture_output=True,
                            check=False,
                        )
                    else:
                        proc.kill()
                except OSError:
                    pass
                return

    cancel_thread = threading.Thread(target=kill_on_cancel, daemon=True)
    cancel_thread.start()

    lines: list[str] = []
    assert proc.stdout is not None
    try:
        check_cancelled()
        for line in proc.stdout:
            if is_cancelled():
                break
            line = line.rstrip()
            lines.append(line)
            if reporter:
                reporter.note_stdout(line)
            parsed = _parse_marker(line)
            if parsed:
                pct, key, seg, audio_sec = parsed
                last_real_update = time.time()
                if reporter:
                    reporter.note_marker(pct, key, seg=seg, audio_sec=audio_sec)
                elif on_progress:
                    on_progress(start + pct * (end - start), stage_label(key))
    finally:
        stop.set()
        creep_thread.join(timeout=2.0)
        cancel_thread.join(timeout=2.0)
        unregister_proc(proc)

    proc.wait()
    output = "\n".join(lines)
    if is_cancelled():
        raise TaskCancelled("任务已取消")
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd, output)
    return subprocess.CompletedProcess(cmd, proc.returncode, output, "")

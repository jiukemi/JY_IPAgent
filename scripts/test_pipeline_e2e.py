"""Smoke-test ③配音 → ④口播 → ⑤发布 chain for a session."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_SESSION = ROOT / "output" / "sessions" / "20260707_170205"
API_BASE = "http://127.0.0.1:7860"


def _probe_duration(path: Path) -> float | None:
    if not path.is_file():
        return None
    r = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    try:
        return float(r.stdout.strip())
    except ValueError:
        return None


def _api_get(path: str) -> dict:
    with urllib.request.urlopen(f"{API_BASE}{path}", timeout=30) as resp:
        return json.loads(resp.read())


def _api_post_json(path: str, body: dict) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        path if path.startswith("http") else f"{API_BASE}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())


def test_dubbing_local(session: Path) -> dict:
    from workflow.session import list_session_dubbings

    dub = session / "dubbing_16k.wav"
    dur = _probe_duration(dub)
    dubs = list_session_dubbings(session)
    timing = session / "dubbing_timing.json"
    seg_n = 0
    if timing.is_file():
        try:
            seg_n = len(json.loads(timing.read_text(encoding="utf-8")).get("segments") or [])
        except json.JSONDecodeError:
            pass
    ok = dub.is_file() and (dur or 0) >= 30
    return {
        "step": "③ 配音",
        "ok": ok,
        "duration_sec": dur,
        "tracks": len(dubs),
        "segments": seg_n,
        "detail": f"dubbing_16k.wav {dur:.1f}s, {len(dubs)} 轨, {seg_n} 段" if dur else "无配音文件",
    }


def test_lipsync_local(session: Path) -> dict:
    lipsync_names = (
        "final_lipsync.mp4",
        "real_lipsync.mp4",
        "digital_lipsync.mp4",
        "latentsync_raw.mp4",
        "sadtalker_raw.mp4",
    )
    video = None
    for name in lipsync_names:
        p = session / name
        if p.is_file() and p.stat().st_size > 0:
            video = p
            break
    dur = _probe_duration(video) if video else None
    ok = video is not None and (dur or 0) >= 10
    return {
        "step": "④ 口播",
        "ok": ok,
        "video": str(video) if video else None,
        "duration_sec": dur,
        "detail": f"{video.name} {dur:.1f}s" if video and dur else "未生成对口型成片，请在 ④ 口播重新合成",
    }


def test_publish_local(session: Path, *, script: str) -> dict:
    from workflow.publish import resolve_session_video

    video = resolve_session_video(session)
    if video is None:
        return {
            "step": "⑤ 发布",
            "ok": False,
            "skipped": True,
            "detail": "跳过：缺少口播视频",
        }

    from api.services.stages import preview_publish_cues, run_publish_stage

    cues = preview_publish_cues(str(session), script, 0.35, 16)
    cue_n = len(cues.get("cues") or [])
    if cue_n < 1:
        return {"step": "⑤ 发布", "ok": False, "detail": "字幕 cue 为空"}

    try:
        out = run_publish_stage(
            str(session),
            script,
            title="自测标题",
            cover_time=0.5,
            template="classic_bottom",
            subtitle_style="bottom_white",
            subtitle_pause=0.35,
            burn_subtitles=False,
            embed_cover=False,
            pip_mode="none",
            pip_upload=None,
            pip_position="top_right",
            pip_scale=0.28,
            pip_margin=24,
            hyperframes_consent=False,
            enable_bgm=False,
        )
        pub = Path(out.get("video_path") or session / "final_publish.mp4")
        dur = _probe_duration(pub)
        ok = pub.is_file() and (dur or 0) >= 5
        return {
            "step": "⑤ 发布",
            "ok": ok,
            "cues": cue_n,
            "output": str(pub),
            "duration_sec": dur,
            "detail": f"final_publish {dur:.1f}s, {cue_n} cues",
        }
    except Exception as exc:
        return {"step": "⑤ 发布", "ok": False, "detail": str(exc)}


def test_api_snapshot(session: Path) -> dict:
    try:
        q = urllib.parse.quote(str(session.resolve()))
        snap = _api_get(f"/api/sessions/snapshot?path={q}")
        return {
            "step": "API 快照",
            "ok": bool(snap.get("dubbing_audio")),
            "dubbing_duration": snap.get("dubbing_duration"),
            "dubs": len(snap.get("dubs") or []),
            "segments": len(snap.get("dubbing_segments") or []),
            "lipsync_stale": snap.get("lipsync_stale"),
            "detail": "需重启 server 后才有 dubbing_duration / segments 字段",
        }
    except Exception as exc:
        return {"step": "API 快照", "ok": False, "detail": str(exc)}


def main() -> int:
    import os

    os.chdir(ROOT)
    session = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SESSION
    if not session.is_dir():
        print(f"会话不存在: {session}")
        return 1

    script = (session / "script.txt").read_text(encoding="utf-8").strip()
    results = [
        test_dubbing_local(session),
        test_lipsync_local(session),
        test_publish_local(session, script=script),
        test_api_snapshot(session),
    ]

    print(f"\n=== 流水线自测 · {session.name} ===\n")
    failed = 0
    for r in results:
        mark = "PASS" if r.get("ok") else ("SKIP" if r.get("skipped") else "FAIL")
        if mark == "FAIL":
            failed += 1
        print(f"[{mark}] {r['step']}: {r.get('detail', '')}")

    # Optional publish smoke with reference video stub
    if not results[1]["ok"]:
        stub_src = session / "reference_ui_preview.mp4"
        stub_dst = session / "digital_lipsync.mp4"
        copied_stub = False
        if stub_src.is_file() and not stub_dst.is_file():
            print("\n--- 使用 reference_ui_preview.mp4 作为口播占位，仅测试 ⑤ 发布 ---")
            shutil.copy2(stub_src, stub_dst)
            copied_stub = True
            pub = test_publish_local(session, script=script)
            mark = "PASS" if pub.get("ok") else "FAIL"
            if mark == "FAIL":
                failed += 1
            print(f"[{mark}] {pub['step']}（占位视频）: {pub.get('detail', '')}")
            if copied_stub and stub_dst.is_file():
                try:
                    stub_dst.unlink()
                except OSError:
                    pass

    print()
    if not results[1]["ok"]:
        print("说明: ③ 配音已就绪；④ 真实口播尚未生成（当前只有对标参考视频）；⑤ 发布逻辑可用。")
        return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

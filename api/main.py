"""FastAPI application entry."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.routes import avatar, browser, competitors, config, cover, files, funasr, jobs, publish, script, sessions, setup, system, tts, tts_worker
from api.routes import assets as assets_routes
from api.routes import components as components_routes

ROOT = Path(__file__).resolve().parent.parent
WEB_DIST = ROOT / "web" / "dist"


def create_app() -> FastAPI:
    app = FastAPI(title="AI 口播智能体", version="2.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(config.router)
    app.include_router(setup.router)
    app.include_router(system.router)
    app.include_router(sessions.router)
    app.include_router(script.router)
    app.include_router(browser.router)
    app.include_router(competitors.router)
    app.include_router(tts.router)
    app.include_router(avatar.router)
    app.include_router(publish.router)
    app.include_router(jobs.router)
    app.include_router(assets_routes.router)
    app.include_router(cover.router)
    app.include_router(funasr.router)
    app.include_router(tts_worker.router)
    app.include_router(files.router)
    app.include_router(components_routes.router)

    @app.get("/api/health")
    def health() -> dict:
        from workflow.edition import edition_payload

        ui_mtime = None
        index = WEB_DIST / "index.html"
        if index.is_file():
            ui_mtime = int(index.stat().st_mtime)
        return {
            "ok": True,
            "ui": WEB_DIST.exists(),
            "ui_build": ui_mtime,
            **edition_payload(),
        }

    if WEB_DIST.is_dir():
        dist_assets = WEB_DIST / "assets"
        if dist_assets.is_dir():
            app.mount("/assets", StaticFiles(directory=dist_assets), name="static_assets")

        @app.get("/{full_path:path}")
        def spa(full_path: str):
            if full_path.startswith("api/"):
                from fastapi import HTTPException

                raise HTTPException(status_code=404)
            candidate = WEB_DIST / full_path
            if candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(
                WEB_DIST / "index.html",
                headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
            )

    return app


app = create_app()


def boot_workers() -> None:
    try:
        from api.services.job_worker import start_job_worker

        start_job_worker()
        print("* 任务队列 worker 已启动")
    except Exception as exc:
        print(f"* 任务队列 worker 未启动: {exc}")

    def _warm_engines() -> None:
        cfg = None
        try:
            from workflow.app_config import load_cfg
            from tts.indextts_client import ensure_indextts_worker

            cfg = load_cfg()
            if ensure_indextts_worker(cfg):
                print("* IndexTTS2 常驻 worker 已启动")
        except Exception as exc:
            print(f"* IndexTTS2 worker 未预启动: {exc}")
        try:
            from workflow.app_config import load_cfg
            from script.funasr_client import ensure_funasr_worker

            if ensure_funasr_worker(cfg if cfg is not None else load_cfg()):
                print("* FunASR 常驻 worker 已启动")
        except Exception as exc:
            print(f"* FunASR worker 未预启动: {exc}")
        try:
            from workflow.bgm import needs_bgm_refresh

            if needs_bgm_refresh():
                import subprocess
                import sys

                print("* BGM 曲库需更新（旧版为合成音轨），正在后台下载…")
                subprocess.run(
                    [sys.executable, str(ROOT / "scripts" / "download_bgm.py"), "--force"],
                    cwd=str(ROOT),
                    check=False,
                )
        except Exception as exc:
            print(f"* BGM 自动下载跳过: {exc}")

    import threading

    threading.Thread(target=_warm_engines, name="warm-engines", daemon=True).start()
    print("* 引擎预热已转后台（不阻塞 API）")

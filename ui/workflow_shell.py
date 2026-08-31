"""Workflow shell: step labels, CSS, deployment summary."""

from __future__ import annotations

from ui.global_settings import settings_summary_md, step_runtime_line

WORKFLOW_CSS = """
.pipeline-hero {
    padding: 12px 16px;
    margin: 0 0 8px 0;
    border-radius: 10px;
    background: #f0f9ff;
    border: 1px solid #bae6fd;
    font-size: 14px;
}
.step-runtime {
    padding: 8px 12px;
    margin-bottom: 10px;
    border-radius: 8px;
    background: #f1f5f9;
    border-left: 4px solid #0ea5e9;
    font-size: 13px;
}
.deploy-bar {
    padding: 10px 14px;
    margin-bottom: 8px;
    border-radius: 10px;
    background: #f8fafc;
    border: 1px solid #cbd5e1;
    font-size: 13px;
}
.deploy-table { width: 100%; border-collapse: collapse; margin-top: 6px; }
.deploy-table th, .deploy-table td {
    text-align: left;
    padding: 4px 8px;
    border-bottom: 1px solid #e2e8f0;
    font-size: 13px;
}
"""

STEP_TAB_ORDER = [
    ("script", "① 文案", "script_tab"),
    ("tts", "② 配音", "stage1"),
    ("avatar", "③ 口播", "stage2"),
    ("publish", "④ 发布", "stage3"),
]


def pipeline_hero_md() -> str:
    return (
        "**AI 口播智能体** · ① 文案 → ② 配音/音色 → ③ 口播 → ④ 发布\n\n"
        "分享链接 → CDN 预览 → 口播文案 → 仿写 → 配音 → 对口型 → 发布。"
        " 运行方式与 API Key 点右上角 **⚙ 全局设置**。"
    )


def _mode_tag(mode: str) -> str:
    return "🖥️ **本地**" if mode == "local" else "☁️ **云端**"


def deployment_summary_md(cfg: dict) -> str:
    return settings_summary_md(cfg)


def step_runtime_md(cfg: dict, step: str) -> str:
    return step_runtime_line(cfg, step)


def save_deployment_step(cfg_path, step: str, mode: str) -> None:
    import yaml
    from pathlib import Path

    path = Path(cfg_path)
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    dep = cfg.setdefault("deployment", {})
    steps = dep.setdefault("steps", {})
    steps[step] = mode
    path.write_text(yaml.dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")


def save_all_deployment(
    cfg_path,
    script_mode: str,
    tts_mode: str,
    avatar_mode: str,
    publish_mode: str,
) -> None:
    for step, mode in (
        ("script", script_mode),
        ("tts", tts_mode),
        ("avatar", avatar_mode),
        ("publish", publish_mode),
    ):
        save_deployment_step(cfg_path, step, mode)

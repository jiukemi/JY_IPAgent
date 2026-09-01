# JY_IPAgent

本地教育口播视频智能体：**文案 → 配音 → 数字人/实拍对口型 → 发布合成**。

产品说明见 **[docs/用户手册.md](docs/用户手册.md)**。本文面向**开发者 / 二次集成**：架构、技术栈、目录职责与如何跑起来。

**下载 Release（自动选 GitHub / Gitee）**：[docs/download.html](docs/download.html)

开源名：**JY_IPAgent** · 桌面安装包品牌名：「九易AI智能体」。

---

## 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│  Electron desktop/  （可选壳：启动 API、加载 web/dist）        │
└────────────────────────────┬────────────────────────────────┘
                             │ localhost HTTP
┌────────────────────────────▼────────────────────────────────┐
│  FastAPI  server.py → api/main.py                            │
│  · REST / 流式进度 · 静态托管 web/dist · CORS 本机放开         │
└───┬──────────────┬──────────────┬──────────────┬────────────┘
    │              │              │              │
    ▼              ▼              ▼              ▼
 script/         tts/          avatar/       workflow/
 文案 / ASR      配音引擎        数字人/口型     会话·发布·任务
    │              │              │              │
    └──────────────┴──────────────┴──────────────┘
                         │
                         ▼
              data/（运行态） + tools/（重型引擎）
                         │
                         ▼
              output/sessions/（每次成片工作区）
```

**数据流（典型本地路径）**

1. **文案** `script/`：分享链接 / 本地视频 → 本机 ASR（或自配解析）→ `script.txt` 等变体  
2. **配音** `tts/`：文案 + 音色 → `dubbing_16k.wav` + `dubbing_timing.json`（可按段修补）  
3. **口播** `avatar/`：参考形象 + 配音 → HeyGem / SadTalker / LatentSync 成片  
4. **发布** `workflow/publish.py`：字幕、封面、画中画、BGM、HyperFrames 等 → 导出视频  

配置：`config.example.yaml` → 本机 `config.yaml`（勿提交）。运行时读写 `data/`，会话产物在 `output/sessions/<id>/`。

---

## 技术栈

### 应用层

| 层 | 技术 | 说明 |
|----|------|------|
| API | **Python 3.11+**, **FastAPI**, **Uvicorn**, **Pydantic v2** | 入口 `server.py`；路由在 `api/routes/`；业务编排在 `api/services/` |
| Web UI | **React 19**, **TypeScript**, **Vite 8**, **Tailwind CSS 4** | 源码 `web/src/`；构建产物 `web/dist/`，由 FastAPI 静态托管 |
| 桌面壳 | **Electron 35**, **electron-builder** | `desktop/`；打包时嵌入应用 + 运行时引导 |
| 配置 | **PyYAML** | `workflow/app_config.py` 加载/合并配置 |
| 媒体 | **FFmpeg / ffprobe** | 转码、拼接、字幕烧录、封面合成等；可落到 `data/runtime/ffmpeg/` |
| 浏览器自动化 | **Playwright**（可选） | 平台登录态辅助；用户数据在 `data/browser/` |
| 封面抠像 | **Pillow**, **rembg**（可选） | `cover/` |

### 管线引擎（多在 `tools/`，按需安装）

| 阶段 | 本地默认 / 常用 | 其它选项 |
|------|-----------------|----------|
| ASR | FunASR SenseVoice / Whisper | — |
| TTS | **IndexTTS2**（推荐） | CosyVoice、Piper、Edge-TTS、Qwen3-TTS 等 |
| 数字人口型 | **HeyGem / Duix-Avatar**（Docker，默认） | SadTalker（静图） |
| 实拍精修 | LatentSync | — |
| 发布增强 | 自研 FFmpeg 合成 + HyperFrames 场景 | `tools/remotion-captions`、`tools/hf-bridge` |

### 进程与任务模型

- **同步 HTTP**：多数阶段接口直接返回结果。  
- **流式**：部分 TTS / 文案生成用 SSE 或分块进度（见 `api/progress.py`、前端 `JobQueue`）。  
- **后台 Job**：`workflow/job_queue.py` + `api/routes/jobs.py`（任务中心）。  
- **常驻 Worker（可选）**：FunASR / IndexTTS worker，减少冷启动（设置页开关；占内存）。  
- **HeyGem**：独立 Docker 服务（常见端口如 8383），由 `avatar/heygem_runtime.py` 探测与编排。

---

## 快速开始（源码）

```powershell
copy config.example.yaml config.yaml
# 编辑 config.yaml：路径、默认引擎等（勿提交含密钥的文件）

py -3.11 -m pip install -r requirements.txt

cd web
npm install
npm run build
cd ..

.\start.bat
# 或: py -3.11 server.py
# 默认尝试 http://127.0.0.1:7860（占用则顺延）
```

桌面壳开发：

```powershell
cd web && npm run build
cd ..\desktop
npm install
# 国内可设: $env:ELECTRON_MIRROR="https://npmmirror.com/mirrors/electron/"
npm start
```

按需引擎（也可在应用内「本机环境 · GPU 与模型」/「口播引擎安装向导」）：

```powershell
.\scripts\setup\setup_indextts.ps1
.\scripts\setup\setup_heygem.ps1      # 需 Docker Desktop 已运行
.\scripts\setup\setup_funasr.ps1      # 或 .\scripts\setup\setup_whisper.ps1
.\scripts\setup\setup_sadtalker.ps1
```

迷你安装包：`scripts/ship.ps1`。口播离线镜像包：`docs/quark-accel-packs.md`。

---

## 目录结构说明

> **粗体** = 日常开发必碰 · *斜体* = 大体量 / 本机生成，通常不进 Git

```
JY_IPAgent/
├── server.py                 # Uvicorn 生产入口；选端口、引导 runtime/ffmpeg
├── start.bat                 # 本机一键启动
├── pipeline.py               # 口型/媒体底层辅助（ffmpeg 封装等）
├── config.example.yaml       # 配置模板（可提交）
├── config.yaml               # *本机私有配置（可含 API Key）— 勿提交*
├── requirements.txt          # Python 核心依赖
├── requirements-*.txt        # 桌面核心 / SadTalker Win 等补充依赖
├── LICENSE                   # PolyForm Noncommercial 1.0.0
├── README.md                 # 本文件
│
├── api/                      # HTTP 层
│   ├── main.py               # FastAPI app：挂路由、托管 web/dist、/api/health
│   ├── schemas.py / errors.py / progress.py
│   ├── routes/               # sessions, script, tts, avatar, publish, …
│   └── services/             # 阶段编排（stages）、任务 runner
│
├── web/                      # 前端工程
│   ├── src/pages/            # 文案 / 配音 / 形象 / 发布等页面
│   ├── src/components/       # 封面编辑、配音音轨、设置、口播向导等
│   ├── src/api/client.ts     # 调后端的统一客户端
│   └── dist/                 # *build 产物；API 静态服务读这里*
│
├── desktop/                  # Electron 壳
│   ├── main.mjs / preload.mjs
│   └── build/                # 图标等 builder 资源
│
├── script/                   # 文案域逻辑（非 UI）
│   ├── extract / rewrite / legal / hot_generate
│   ├── share_link.py / funasr_client.py / llm_client.py
│   ├── browser.py / platforms.py
│   └── …
│
├── tts/                      # 配音域
│   ├── engine.py             # 多后端合成入口 → dubbing_16k.wav
│   ├── voice_catalog.py / voices.py / presets.yaml
│   ├── dubbing_timing.py     # 分段时间轴 / ASR 对齐
│   ├── dubbing_patch.py      # 按段重合成 / 重录拼接
│   └── indextts_* / qwen3_* / run_*.py
│
├── avatar/                   # 口播形象与引擎封装
│   ├── heygem.py / heygem_runtime.py
│   ├── catalog.py / ai_portrait.py
│   └── …
│
├── cover/                    # 封面模板、渲染、主体抠图
│
├── workflow/                 # 横切：会话、发布、硬件、夸克加速
│   ├── session.py / publish.py
│   ├── job_queue.py / task_control.py / system_stats.py
│   ├── engine_status.py / hardware.py / gpu_family.py
│   ├── heygem_wizard.py / quark_accel.py
│   ├── hyperframes*.py / remotion_captions.py / bgm.py
│   └── runtime_bootstrap.py
│
├── ui/                       # 遗留 Gradio 适配层（仍被部分 API 引用）
│
├── scripts/                  # 运维与发版脚本
│   ├── setup/                # 各引擎一键安装
│   ├── ship.ps1 / ship_full.ps1
│   ├── export_heygem_docker_image.ps1 / pack_quark_accel.py
│   └── …
│
├── tests/                    # pytest
│
├── docs/
│   ├── 用户手册.md
│   ├── download.html         # Release 下载页（按网络选 GitHub / Gitee）
│   ├── quark-accel-packs.md
│   └── THIRD_PARTY_NOTICES.md
│
├── data/                     # *运行态与用户数据（多数本地-only）*
│   ├── voices/ / avatars/ / assets/ / bgm/
│   ├── browser/              # Playwright 用户目录（敏感）
│   ├── runtime/              # 便携 Python、ffmpeg（.gitignore）
│   ├── quark/                # 夸克加速目录（可提交 catalog）
│   └── …
│
├── output/                   # *生成物*
│   └── sessions/             # 每次会话工作区（.gitignore）
│
└── tools/                    # *重型第三方引擎与 venv（勿整仓推送）*
    ├── IndexTTS/ CosyVoice/ Piper/ …
    ├── FunASR/ Whisper/
    ├── Duix-Avatar/ SadTalker/ LatentSync/
    └── …
```

### 按「你要改什么」找目录

| 目标 | 优先看 |
|------|--------|
| 加/改 HTTP 接口 | `api/routes/` → `api/services/stages.py` |
| 改页面交互 | `web/src/pages/`、`web/src/components/` |
| 文案提取 / 转写 / 对标 | `script/` |
| TTS 音色与按段修补 | `tts/`、`web/.../DubbingSourcePanel.tsx` |
| HeyGem 状态与口型 | `avatar/`、`scripts/setup/setup_heygem.ps1` |
| 口播安装向导 / 夸克包 | `workflow/heygem_wizard.py`、`workflow/quark_accel.py` |
| 字幕/画中画/发布布局 | `workflow/publish.py`、`web/.../PublishPage.tsx` |
| 封面编辑器 | `cover/`、`web/.../CoverEditor.tsx` |
| 安装检测与推荐引擎 | `workflow/engine_status.py`、设置页 ModelSetup |
| 打 Windows 安装包 | `scripts/ship.ps1`、`scripts/ship_full.ps1`、`desktop/` |

---

## 会话目录约定（`output/sessions/<id>/`）

| 文件 / 目录 | 作用 |
|-------------|------|
| `script.txt` 及 `script_*.txt` | 口播文案及提取/仿写/法务变体 |
| `dubbing_16k.wav` | 当前配音成片（16 kHz） |
| `dubbing_timing.json` / `dubbing_asr_timing.json` | 分段时间轴（修补、字幕对齐） |
| `dubs/` | 历史配音版本 |
| 口型成片 mp4 + `lipsync_takes/` | 当前与历史对口型 |
| `publish_copy.json` 等 | 标题/封面/发布文案 |
| `meta`（会话元数据） | 选中的配音轨、口型轨等 |

---

## 环境要求

| 项目 | 说明 |
|------|------|
| 系统 | Windows 10/11（当前主路径） |
| Python | 3.11+（源码）；安装包可引导便携 Python → `data/runtime/python/` |
| Node.js | 前端 / Electron |
| GPU | NVIDIA 推荐（IndexTTS / 口型）；详见用户手册「最低与推荐配置」 |
| Docker | HeyGem 需要 [Docker Desktop](https://www.docker.com/products/docker-desktop/) |
| 磁盘 | `tools/` + 模型 + 镜像常需 **数十 GB** |

---

## 许可

[PolyForm Noncommercial License 1.0.0](LICENSE)：**禁止商用**；非商业使用、修改与分发须保留署名 `JY_IPAgent` 与协议。第三方引擎各自许可证见 [docs/THIRD_PARTY_NOTICES.md](docs/THIRD_PARTY_NOTICES.md)。

---

## 请作者喝杯咖啡

若项目对你有帮助，可自愿打赏（不是购买软件 / 会员）：

<p align="center">
  <img src="docs/assets/wechat-pay-coffee.png" alt="微信收款码 · 请喝咖啡" width="280" />
</p>

应用内：**设置 → 关于我们**。

---

## 反馈

Issue 请附：现象、系统 / GPU、是否 Docker、相关日志（打码密钥）。

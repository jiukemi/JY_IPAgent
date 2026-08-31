# JY_IPAgent

本地教育口播视频智能体：**文案 → 配音 → 数字人/实拍对口型 → 发布合成**。

产品说明见 **[docs/用户手册.md](docs/用户手册.md)**。本文面向源码使用者：怎么跑起来、目录在哪。

开源名：**JY_IPAgent** · 桌面安装包品牌名：「九易AI智能体」。

---

## 架构

```
Electron desktop/（可选） → FastAPI (server.py) → 托管 web/dist
                              │
          script/  tts/  avatar/  workflow/
           文案     配音   口播     会话·发布
                              │
                    data/ + tools/ + output/sessions/
```

配置：`config.example.yaml` → 本机 `config.yaml`（勿提交）。引擎装在 `tools/`，会话产物在 `output/sessions/`。

---

## 技术栈（本地主路径）

| 层 | 技术 |
|----|------|
| API | Python 3.11+ · FastAPI · Uvicorn |
| UI | React · TypeScript · Vite · Tailwind |
| 桌面 | Electron · electron-builder |
| 媒体 | FFmpeg |
| ASR | FunASR / Whisper |
| TTS | IndexTTS2（推荐）· CosyVoice / Piper / Edge-TTS 等 |
| 口播 | HeyGem / Duix（Docker）· SadTalker（静图备选）· LatentSync（实拍） |

按需安装脚本：`scripts/setup/setup_*.ps1`。迷你安装包：`scripts/ship.ps1`。口播离线包说明：`docs/quark-accel-packs.md`。

---

## 快速开始

```powershell
copy config.example.yaml config.yaml

py -3.11 -m pip install -r requirements.txt

cd web
npm install
npm run build
cd ..

.\start.bat
# 或: py -3.11 server.py
# 默认 http://127.0.0.1:7860（占用则顺延）
```

常用引擎：

```powershell
.\scripts\setup\setup_indextts.ps1
.\scripts\setup\setup_heygem.ps1   # 需 Docker Desktop
.\scripts\setup\setup_funasr.ps1
```

也可在应用内：**设置 → 本机环境 · GPU 与模型** / **口播引擎安装向导**。

桌面壳开发：`web` 先 `npm run build`，再 `cd desktop && npm install && npm start`。

---

## 目录要点

| 路径 | 作用 |
|------|------|
| `api/` | HTTP 路由与任务编排 |
| `web/` | 前端；`dist/` 由 API 静态托管 |
| `desktop/` | Electron 壳 |
| `script/` `tts/` `avatar/` `cover/` | 文案 / 配音 / 口播 / 封面 |
| `workflow/` | 会话、发布、硬件探测、夸克加速等 |
| `scripts/setup/` | 本机引擎安装 |
| `scripts/ship.ps1` | 迷你安装包 |
| `docs/` | 用户手册与打包说明 |
| `data/` `output/` `tools/` | 运行态 / 成片 / 重型引擎（默认不进 Git） |

改接口看 `api/routes/`；改页面看 `web/src/`；改成片合成看 `workflow/publish.py`。

---

## 环境要求

| 项目 | 说明 |
|------|------|
| 系统 | Windows 10/11 |
| Python / Node | 3.11+ · 用于前端与 Electron |
| GPU | NVIDIA 推荐（本地 TTS / 口播）；详见用户手册「最低与推荐配置」 |
| Docker | 口播主路径需要 [Docker Desktop](https://www.docker.com/products/docker-desktop/) |
| 磁盘 | 模型与镜像常需数十 GB |

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

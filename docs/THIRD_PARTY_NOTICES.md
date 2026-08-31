# 第三方组件与模型声明

> **JY_IPAgent**（九易AI智能体）由本仓库作者集成多类开源与第三方服务。**本文件不构成法律意见**；商用、对外提供服务或再分发前，请自行核对各组件许可证与用户协议。

本仓库自身许可：**PolyForm Noncommercial License 1.0.0**（禁止商用）。见根目录 `LICENSE`。

---

## 1. 本应用如何使用这些能力

| 类别 | 典型用途 | 默认路径 |
|------|----------|----------|
| 文案 LLM | 仿写、热词、对标、AI 法务 | 云端 API（如 DeepSeek），Key 由用户在 `config.yaml` 填写 |
| ASR | 提取口播文案 | 本地 Whisper / FunASR，或云端解析/ASR API |
| TTS | 配音合成 | 本地 IndexTTS2 等，或云端 Qwen3-TTS（DashScope） |
| 数字人口型 | 对口型视频 | 本地 HeyGem（Docker）/ SadTalker，或云端预留（火山等） |
| 发布合成 | 字幕、封面、画中画 | 本机 FFmpeg + 自研合成逻辑 |
| 浏览器自动化 | 平台登录态、部分 CDN | Playwright（可选） |

**合规要点（使用者责任）**

- 在 `config.yaml` 中启用的**每一个云端 API**，均受对应服务商条款约束（计费、内容审核、实名、备案等）。
- **本地模型权重**仍受原作者许可证约束；不得用于许可证禁止的场景。
- 生成内容的责任主体为**使用者**；请遵守法律法规与平台规则。

---

## 2. 本地引擎与模型（`tools/` 按需安装）

| 组件 | 用途 | 来源 / 参考 | 许可（摘要） |
|------|------|-------------|--------------|
| **IndexTTS2** | 默认本地 TTS | [IndexTTS](https://github.com/index-tts/index-tts) 等上游 | 以官方仓库 LICENSE 为准 |
| **CosyVoice** | 可选 TTS | [FunAudioLLM/CosyVoice](https://github.com/FunAudioLLM/CosyVoice) | 以官方仓库 LICENSE 为准 |
| **Piper** | 轻量 TTS | [rhasspy/piper](https://github.com/rhasspy/piper) | 以官方仓库 LICENSE 为准 |
| **Qwen3-TTS（本地）** | 本地千问 TTS | [QwenLM/Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) 等 | 以官方仓库 LICENSE 为准 |
| **Microsoft Edge TTS** | 神经音色 / 部分方言 | Microsoft Edge 在线语音服务 | 受 Microsoft 服务条款约束 |
| **FunASR / SenseVoice** | 本地 ASR、常驻加速 | [modelscope/FunASR](https://github.com/modelscope/FunASR) 等 | 以官方仓库 LICENSE 为准 |
| **Whisper** | 本地 ASR | [openai/whisper](https://github.com/openai/whisper) | MIT |
| **HeyGem / Duix-Avatar** | 数字人口型（Docker） | Duix / HeyGem 生态；镜像如 `guiji2025/duix.avatar` | **以镜像与官方文档为准**；非本仓库授权 |
| **SadTalker** | 静图对口型备选 | [OpenTalker/SadTalker](https://github.com/OpenTalker/SadTalker) | 以官方仓库 LICENSE 为准 |
| **LatentSync** | 实拍口型精修 | [ByteDance/LatentSync](https://github.com/bytedance/LatentSync) 等 | 以官方仓库 LICENSE 为准 |
| **FFmpeg** | 转码、拼接、字幕烧录 | [FFmpeg](https://ffmpeg.org/) | LGPL/GPL 依构建而定 |
| **rembg** | 封面抠像（可选） | [danielgatis/rembg](https://github.com/danielgatis/rembg) | 以官方仓库 LICENSE 为准 |
| **faster-whisper** | 配音时间轴 ASR | [SYSTRAN/faster-whisper](https://github.com/SYSTRAN/faster-whisper) | 以官方仓库 LICENSE 为准 |
| **Playwright** | 浏览器自动化 | [microsoft/playwright](https://github.com/microsoft/playwright) | Apache-2.0 |
| **remotion-captions** | 侧字幕桥接（若启用） | Remotion 生态相关 | 以子模块 LICENSE 为准 |

模型权重多来自 **Hugging Face / ModelScope**；下载镜像可在设置中配置（如 `hf-mirror.com`）。权重许可证以各模型卡片为准。

---

## 3. 云端 API（用户在配置中填写 Key 后才会调用）

| 服务 | 用途 | 配置位置 | 说明 |
|------|------|----------|------|
| **DeepSeek** | 文案仿写 / 法务等 LLM | `script.cloud.rewrite` / `legal` | [DeepSeek 开放平台](https://platform.deepseek.com/) 条款与计费 |
| **阿里云 DashScope** | Qwen3-TTS 云端 | `qwen3_tts` | [DashScope](https://help.aliyun.com/zh/dashscope/) 条款 |
| **17zhiling 等解析 API** | CDN 去水印、ASR 异步 | `script.cloud.cdn` / `transcript` | 第三方商业 API；URL 见 `script/parse_providers.py` |
| **diadi.cn gateway** 等 | 分享链接解析（可选） | `config` CDN provider | 第三方服务；自行签约合规 |
| **火山引擎 Volcengine**（预留） | 云端口播 / 发布 | `deployment.cloud` | 配置占位；启用前查阅火山条款 |
| **Ollama** 等 | 未默认接线 | — | 若自行集成，遵守对应条款 |

本仓库**不提供**上述云服务的账号、配额或内容审核能力；费用与合规由使用者承担。

---

## 4. 前端与桌面壳

| 组件 | 许可 |
|------|------|
| React | MIT |
| Vite | MIT |
| Tailwind CSS | MIT |
| Electron | MIT（应用打包） |

---

## 5. 品牌与署名

- 开源项目名：**JY_IPAgent**
- 桌面产品名：**九易AI智能体**
- 口播能力涉及 **DUIX.COM** 生态时，界面可能显示 **Built with DUIX.COM**（遵循上游品牌要求时请保留）。

衍生分发须保留 `LICENSE` 中的 **Required Notice** 与 PolyForm Noncommercial 全文。

---

## 6. 组件中心与夸克加速包

**组件中心**（`data/components/manifest.json`）：可选的按需下载入口；公开示例里 `mirrors` 通常为空，开发机请用 `scripts/setup/setup_*.ps1` 与设置里「本机环境」。

**夸克网盘加速包**（`workflow/quark_accel.py` + `data/quark/catalog.json`）：用户从网盘下载 zip 后，在设置页扫描/拖入安装。口播镜像分通用 / RTX50，见应用内向导。

本软件**不提供**应用内购买、会员或激活码。

---

## 7. 生成式人工智能与内容合规（中国大陆相关提示）

> 以下为产品使用层面的**提示**，不构成法律意见；对外经营前请咨询律师或合规顾问。

| 场景 | 提示 |
|------|------|
| **个人私下本机使用** | 在自有设备上安装、用本地或自购 API Key 生成内容，通常由**使用者**承担内容合规与肖像/版权责任。 |
| **对外提供生成服务** | 若将本软件或基于其的接口**向公网用户**提供文案/配音/口播生成能力，可能涉及生成式 AI **备案、安全评估、算法标识**等监管要求（以当时有效法规为准）。 |
| **使用云端大模型 API** | DeepSeek、DashScope 等服务商通常有自己的实名、计费与内容策略；**不得**默认视为已由本软件完成备案。 |
| **数字人 / 口播视频** | 使用他人肖像、声音合成口播，须取得**肖像权、声音权**等授权；禁止用于诈骗、虚假宣传等违法用途。 |
| **合成内容标识** | 向平台发布 AI 生成或深度合成内容时，遵守平台与国家对**显著标识**的要求（如「AI 生成」标注）。 |
| **训练数据与版权** | 本地模型权重来自上游项目；商用或二次分发模型须遵守上游与模型卡许可。 |

**本仓库作者**不对使用者违反法律法规、平台规则或第三方条款的行为承担责任。

---

## 8. 更新

上游版本与许可证可能变更。发版前建议核对 `tools/` 各子项目与本文差异。欢迎通过 Issue 指出遗漏或过时条目。

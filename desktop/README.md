# Agent Desktop（单安装包）

## 开发启动

1. `cd web && npm run build`
2. `cd desktop && npm install`（国内可设 `ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/`）
3. `npm start`（轻量：`npm run start:light`）

窗口默认 1280×800。

## 引擎安装

设置 → **本机环境 · GPU 与模型**：一键安装会进入**任务中心**（FunASR / Whisper / IndexTTS / HeyGem 等）。

口播：开发机继续 Docker + 8383；也可用本机环境里的 HeyGem 安装脚本。

## 打包给别人用

见根目录 [README.md](../README.md)「打 Windows 安装包」与 `scripts/ship.ps1`。

**Python / FFmpeg：** 打包版首次启动自动下载到用户目录 `runtime/`。

```powershell
cd desktop
npm run dist
```


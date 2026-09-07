# 豆包「电脑本地模式」协助安装 · 可复制提示词

**应用内入口（推荐）：** 设置 → 特殊引擎安装 → **口播引擎安装向导**  
- ② Docker 未就绪：可一键复制「只装 Docker」或「Docker + pull」  
- ③ 装加速包：可一键复制「只拉镜像」（有外网时跳过夸克 zip）

给用户：打开 **豆包桌面端最新版 → 电脑本地模式**，粘贴提示词。装完后回到向导点「重新检测 / 一键启动」。

> 说明：豆包能执行本机命令、装软件、改配置，但 **UAC/管理员弹窗必须用户本地点确认**。网络差时 `docker pull` 仍可能失败，那时再改用夸克加速包。

---

## 与九易逻辑如何对齐

| 点 | 用户原稿 | 九易实际 | 建议 |
|----|----------|----------|------|
| 镜像名 | `guiji2025/heygem.ai` | **`guiji2025/duix.avatar`** / **`…-5090`** | 必须改，否则 pull 错或空 |
| 容器名 | `heygem` | **`duix-avatar-gen-video`** | 必须一致，否则软件启停对不上 |
| 数据目录 | 未提 | 挂载本机 `…/heygem_face2face` → 容器 `/code/data` | 缺挂载则口播读不到音视频 |
| nvidia-toolkit | Linux 装法 | Win 上主要靠 **驱动 + Docker Desktop WSL2 GPU** | 勿强行按 Linux 装 toolkit |
| 夸克包 | 禁止 | 有外网 pull 可跳过夸克 | 与软件「有网可 pull」路径一致 |
| 穿起来 | — | pull 成功后软件能识别镜像 | **优先只装 Docker+拉镜像，启动交给九易「一键启动」** |

理论上：**豆包完成 Docker + pull 后，九易向导「重新检测」→「一键启动口播」即可穿起来**（不必再下夸克 zip）。向导第③步若仍提示加速包可忽略，以 `docker images` 已有对应镜像、`8383` 能通为准。

---

## 提示词 A（推荐）· Docker + 拉口播镜像，启动交回九易

```
请在这台 Windows 电脑用「电脑本地模式」协助完成九易AI智能体 / JY_IPAgent 的口播 Docker 环境。逐步执行并输出日志；出错立刻打印完整报错，不要跳过。

【目标 · 与九易软件对齐】
- 不要下载夸克网盘 zip，不要 docker load 本地 tar（除非我另行说明）。
- 装好后由我回到「九易AI智能体 → 口播引擎安装向导」点「重新检测」和「一键启动口播引擎」。你这边以「镜像已在本地」为完成标准即可；容器启动优先交给九易，避免容器名/挂载和软件不一致。

【步骤】
1) 下载并安装 Docker Desktop（若 C 盘空间不足，尽量装到 D/E）。启用 WSL2 后端；个人使用可跳过 Docker Hub 登录。验收：`docker info` 成功。
2) 确认 NVIDIA 驱动正常：`nvidia-smi` 能显示 GPU。在 Docker Desktop 打开 GPU/WSL 相关选项（若有）。Windows 上不要按 Linux 教程强行安装 nvidia-container-toolkit；用 Docker Desktop 的 GPU 支持即可。用例如下命令做 GPU 可见性抽查（失败则记录日志，不要假装成功）：
   docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi
3) 识别本机 N 卡型号（nvidia-smi），按规则选镜像（名称必须一字不差）：
   - 型号含 RTX 50 / 5060 / 5070 / 5080 / 5090 → guiji2025/duix.avatar-5090
   - 其它 NVIDIA（含 30/40 系）→ guiji2025/duix.avatar
   - 无 NVIDIA：停止并说明九易口播主路径需要 NVIDIA。
4) 配置国内可用的 Docker Hub 镜像加速（改 Docker Desktop daemon.json / 镜像源），然后：
   docker pull <上面选中的完整镜像名>
5) 验收：`docker images` 能看到该镜像。输出镜像名与 IMAGE ID。
6) （可选）不要自行 docker run 起名为 heygem 的容器。若你想预检端口，可说明「建议回九易点一键启动」；若用户坚持让你启动，必须满足下一节「提示词 A+」的容器名与挂载，否则会与九易冲突。
7) 全部步骤输出执行日志；最终用几行中文总结：Docker 是否 OK、选了哪张镜像、pull 是否成功、下一步回九易点什么。

【禁止】
- 禁止使用 guiji2025/heygem.ai 或 heygem.ai-5090（错误名字）。
- 禁止容器名 heygem（九易使用 duix-avatar-gen-video）。
- 禁止去下夸克加速包 zip。
```

---

## 提示词 A+（可选）· 连容器也由豆包拉起（须与九易一致）

仅在用户明确要求「豆包直接开到浏览器能开 8383」时使用；挂载目录按本机实际改（优先 `D:\JY_IPAgent-Data\runtime\heygem_face2face`，否则 `%AppData%\jy-ipagent\runtime\heygem_face2face`，没有就创建）。

```
在提示词 A 的 Docker + pull 已成功前提下，请按九易约定启动容器（不要用名字 heygem）：

1) 确认镜像已是：guiji2025/duix.avatar 或 guiji2025/duix.avatar-5090（按显卡）。
2) 创建数据目录（若不存在）：
   - 优先：<安装盘>\JY_IPAgent-Data\runtime\heygem_face2face
   - 否则：%AppData%\jy-ipagent\runtime\heygem_face2face
3) 若已有容器 duix-avatar-gen-video，先 docker rm -f duix-avatar-gen-video。
4) 使用 GPU 启动，端口 8383，容器名必须为 duix-avatar-gen-video，挂载上述目录到 /code/data，命令类似：
   docker run -d --name duix-avatar-gen-video --gpus all --privileged --shm-size=8g -p 8383:8383 -v "<本机heygem_face2face绝对路径>:/code/data" -e PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:512 <镜像名> python /code/app_local.py
5) 等待服务就绪后访问 http://127.0.0.1:8383 ；可用：
   Invoke-WebRequest "http://127.0.0.1:8383/easy/query?code=probe" -UseBasicParsing
6) 输出日志；成功后告诉用户：回到九易口播向导点「重新检测」，应显示 8383 就绪。
```

---

## 提示词 B · 仅修 Docker Desktop（装不上 / 启不来）

```
请在本机 Windows 用电脑本地模式排查并修好 Docker Desktop，供「九易AI智能体」使用。
要求：启用 WSL2；可装到非 C 盘；个人使用跳过 Docker Hub 登录；验收标准是 `docker info` 成功。
逐步输出日志；需要管理员权限时明确提示我点击 UAC。
修好后不要拉口播镜像，让我回九易向导继续。
```

---

## 提示词 C · FunASR（文案提取）安装失败

```
我在用「九易AI智能体 / JY_IPAgent」。文案提取要用本地 FunASR，安装失败。请用电脑本地模式协助排查并重装。

【优先】
1) 若软件「设置 → 本机环境」里有 FunASR 安装按钮，指导我点那里；你根据我贴出的报错继续修。
2) 若你能找到项目/安装目录下的 scripts\setup\setup_funasr.ps1，在对应环境执行它（注意 AGENT_RUNTIME_DIR 指向 JY_IPAgent-Data\runtime 或 AppData\jy-ipagent\runtime）。
3) 需要网络下 torch/funasr；可换国内 pip 源；不要卸载九易主程序。
4) 装好后提醒我：设置 → 全局引擎设置 → 文案步骤选「本地 + FunASR」并保存。
请输出完整日志；把关键报错原文保留。下面是我的报错：
（在此粘贴报错）
```

---

## 提示词 D · IndexTTS2（配音）安装失败

```
我在用「九易AI智能体 / JY_IPAgent」。配音要用本地 IndexTTS2，安装失败。请用电脑本地模式协助排查并重装。

【优先】
1) 指导我在软件「本机环境」重装 IndexTTS；或运行 scripts\setup\setup_indextts.ps1（InstallDir 优先 %AGENT_RUNTIME_DIR%\engines\IndexTTS）。
2) 需要 Git/ZIP 拉源码与模型权重；网络失败时换镜像/代理并重试；不要改成其它无关 TTS 除非我同意。
3) 装好后提醒：全局引擎设置 → 配音选「本地 + IndexTTS2」；克隆音色需在音色库保存并再点选。
请输出完整日志。我的报错如下：
（在此粘贴报错）
```

---

## 提示词 E · 通用：任意引擎报错交给豆包

```
我在用九易AI智能体（JY_IPAgent）。下面功能安装/运行报错，请用 Windows 电脑本地模式诊断并给出可执行修复（改配置、重跑安装、装依赖均可），不要删除用户作品与音色库。
每步输出日志；需要我点击的 UAC/重启请明确写出。
软件相关目录可能在：安装盘\JY_IPAgent-Data\runtime 或 %AppData%\jy-ipagent\runtime。
报错与场景：
（粘贴：哪一步、引擎名、完整报错、是否 NVIDIA、Windows 版本）
```

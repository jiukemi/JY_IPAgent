/** Copy-paste prompts for 豆包「电脑本地模式」— keep in sync with docs/doubao-install-prompts.md */

export const DOUBAO_PROMPT_DOCKER_ONLY = `请在本机 Windows 用电脑本地模式排查并修好 Docker Desktop，供「九易AI智能体」使用。
要求：启用 WSL2；可装到非 C 盘；个人使用跳过 Docker Hub 登录；验收标准是 docker info 成功。
逐步输出日志；需要管理员权限时明确提示我点击 UAC。
修好后不要拉口播镜像，让我回九易向导点「重新检测」。`

export const DOUBAO_PROMPT_DOCKER_AND_PULL = `请在这台 Windows 电脑用「电脑本地模式」协助完成九易AI智能体 / JY_IPAgent 的口播 Docker 环境。逐步执行并输出日志；出错立刻打印完整报错，不要跳过。

【目标 · 与九易软件对齐】
- 不要下载夸克网盘 zip，不要 docker load 本地 tar（除非我另行说明）。
- 装好后由我回到「九易AI智能体 → 口播引擎安装向导」点「重新检测」和「一键启动口播引擎」。你这边以「镜像已在本地」为完成标准；容器启动优先交给九易。

【步骤】
1) 下载并安装 Docker Desktop（C 盘不足则装到 D/E）。启用 WSL2；可跳过 Docker Hub 登录。验收：docker info 成功。
2) nvidia-smi 能显示 GPU。Windows 不要按 Linux 教程强装 nvidia-container-toolkit；用 Docker Desktop 的 GPU/WSL 支持。抽查：
   docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi
3) 按显卡选镜像（名称必须一字不差）：
   - RTX 50 / 5060 / 5070 / 5080 / 5090 → guiji2025/duix.avatar-5090
   - 其它 NVIDIA（含 30/40 系）→ guiji2025/duix.avatar
   - 无 NVIDIA：停止并说明口播主路径需要 NVIDIA。
4) 配置国内 Docker 镜像加速，然后 docker pull <选中的镜像名>
5) 验收：docker images 能看到该镜像。输出镜像名与 IMAGE ID。
6) 不要自行 docker run 起名为 heygem 的容器（九易容器名是 duix-avatar-gen-video）。
7) 总结：Docker 是否 OK、选了哪张镜像、pull 是否成功、下一步回九易点什么。

【禁止】guiji2025/heygem.ai、容器名 heygem、下载夸克加速包 zip。`

export const DOUBAO_PROMPT_PULL_ONLY = `本机 Docker Desktop 已能 docker info。请用电脑本地模式继续为「九易AI智能体」拉取口播镜像（不要下夸克 zip）。

1) nvidia-smi 看显卡：RTX 50 系 → guiji2025/duix.avatar-5090；其它 N 卡 → guiji2025/duix.avatar
2) 配国内镜像加速后 docker pull 对应镜像
3) docker images 确认后告诉我回九易向导点「重新检测」→「一键启动口播引擎」
禁止错误镜像名 heygem.ai；禁止容器名 heygem。输出完整日志。`

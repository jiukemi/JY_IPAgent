# 夸克网盘加速包：要托管什么、怎么区分显卡

> 对应代码：`workflow/quark_accel.py`、`workflow/gpu_family.py`、`data/quark/catalog.json`  
> 设置页：**设置 → 网盘加速 · 夸克（免费线）**

## 两条线里的「免费线」怎么用

1. 你把 zip 传到**夸克分享**（**两个口播 zip 放同一文件夹一起分享即可**，不必各开一条链接）  
2. 在 `data/quark/catalog.json` 填 `share_root_url`（文件夹总入口）+ 各包 `share_url`（可与总入口相同）+ 可选 `share_extract_code`  
3. 用户：打开分享 → **只下本机推荐的那一个 zip** → 下到「下载」→ 设置页 **扫描安装** / **粘贴路径** / **拖入 zip**

安装时会读包内 `MANIFEST.json`：校验 sha256；若 `gpu_family` 与本机不符会拦截（可勾选强制安装）。

## 通用 vs 显卡相关（务必分开托管）

| 类型 | pack_id | gpu_family | 内容 | 谁该下 |
|------|---------|------------|------|--------|
| **通用** | `universal-ffmpeg` | `any` | 便携 FFmpeg | 人人可下 |
| **通用** | `universal-indextts-weights` | `any` | IndexTTS2 **权重** | 要本地配音且无外网的人 |
| **显卡** | `heygem-docker-general` | `general` | Docker 镜像 `guiji2025/duix.avatar` | **非** RTX 50 系 |
| **显卡** | `heygem-docker-rtx50` | `rtx50` | Docker 镜像 `guiji2025/duix.avatar-5090` | **仅** RTX 5060/70/80/90 等 50 系 |

与 `scripts/setup/setup_heygem.ps1` 一致：检测到 `RTX 50*` → 用 5090 镜像；否则用默认镜像。  
**两包都要传到夸克**（文件名不同），分享页写清「通用 / RTX50」；软件按显卡只推荐一个。

不要把两个 HeyGem tar 打进同一个 zip 让用户自己挑文件。

### 本机已打好的产物（开发机）

| 包 | 路径 | 约体积 |
|----|------|--------|
| 通用 | `dist/quark-packs/九易AI-加速包-口播-通用显卡.zip` | ~4.6 GB |
| RTX50 | `dist/quark-packs/九易AI-加速包-口播-RTX50系.zip` | ~6.7 GB |

中间 tar（可再打包，不必进 Git）：`E:\agent-dist\guiji2025_duix.avatar.tar`、`…-5090.tar`。  
`dist/` 默认 gitignore，勿把数 GB zip 推进公开仓库。  

**当前镜像加速包（口播两 zip 各自独立分享）**：  
- 通用显卡：`https://pan.quark.cn/s/189d3ac515d1?pwd=47zj`（提取码 `47zj`）  
- RTX50：`https://pan.quark.cn/s/e1fba3b2d463?pwd=kZhv`（提取码 `kZhv`）  
- 已写入 `data/quark/catalog.json` 各包 `share_url` / `share_extract_code`

## 你本机如何打出待上传资源

```powershell
# 1) 导出 Docker 镜像（需已 docker pull）
powershell -File scripts/export_heygem_docker_image.ps1 -Also5090
# 默认写出到 E:\agent-dist\*.tar

# 2) 打夸克 zip（推荐直接调 Python）
py -3.11 scripts/pack_quark_accel.py --pack-id heygem-docker-general --docker-tar E:\agent-dist\guiji2025_duix.avatar.tar
py -3.11 scripts/pack_quark_accel.py --pack-id heygem-docker-rtx50 --docker-tar E:\agent-dist\guiji2025_duix.avatar-5090.tar

# 可选通用包
py -3.11 scripts/pack_quark_accel.py --pack-id demo
py -3.11 scripts/pack_quark_accel.py --pack-id universal-ffmpeg --ffmpeg-zip D:\path\to\ffmpeg.zip
py -3.11 scripts/pack_quark_accel.py --pack-id universal-indextts-weights
```

也可：`powershell -File scripts/pack_quark_accel.ps1 -PackId demo`（内部仍调用上面的 Python）。

产物目录：`dist/quark-packs/`。

## 传到夸克后

编辑 `data/quark/catalog.json`：

```json
"share_root_url": "https://pan.quark.cn/s/你的分享码",
"share_extract_code": "xxxx",
"share_url": "https://pan.quark.cn/s/你的分享码"
```

同目录分享时，两包 `share_url` 可填同一链接；用户进文件夹后按文件名选「通用」或「RTX50」。用户设置页 / **口播安装向导** 会显示「本机推荐」并引导 Docker → 安装包 → 自动 load。
## 本机是 RTX50，也能打「通用包」吗？

**可以。** 打包装只 `docker pull` + `docker save`，不必用该镜像在本机跑口播。  
50 系机器上只要 Hub / 代理能拉下 `guiji2025/duix.avatar`，即可导出通用包（本仓库开发机已能同时产出通用 + RTX50 zip）。

若 pull 失败（超时 / EOF）：

1. 修好 Docker 出网（VPN / Desktop 代理），再 `docker pull guiji2025/duix.avatar`  
2. 或换一台能 pull 的机器导出 tar，拷回后打包  

```powershell
# 镜像已在本地时跳过 pull
powershell -File scripts/export_heygem_docker_image.ps1 -OnlyLocal
py -3.11 scripts/pack_quark_accel.py --pack-id heygem-docker-general --docker-tar E:\agent-dist\guiji2025_duix.avatar.tar --out-dir dist\quark-packs
```

非 50 用户：向导推荐通用包 → 夸克下载 → 安装。**不要**下 RTX50 包，也**不要**把镜像打进软件 Setup。

## 用户装完口播 tar 还要做什么

应用内请走 **口播引擎安装向导**（形象页 / 设置）。手动时：

```powershell
docker load -i data\runtime\heygem\duix.avatar.tar
# 或 5090：
docker load -i data\runtime\heygem\duix.avatar-5090.tar
.\scripts\setup\setup_heygem.ps1
```

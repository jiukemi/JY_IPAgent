/** FAQ shown in Settings → 常见问题. Keep answers short and actionable. */

export type FaqItem = {
  id: string
  q: string
  a: string
}

export const FAQ_ITEMS: FaqItem[] = [
  {
    id: 'accel-download',
    q: '夸克加速包下载一次就失效？能否用 GitHub / Gitee？',
    a:
      '夸克分享链接常「下一次就失效」。失效后请私聊作者重新要链接，或改用其它可用渠道。\n'
      + '口播加速包约 4.6～6.7GB，不能塞进代码仓库；若用 GitHub Releases，单文件不能超过 2GB，须分卷 .part1/.part2…（应用内可自动拼接）。\n'
      + 'Gitee 单附件更小，不适合整包。有外网/梯子时也可不走加速包，直接 docker pull。',
  },
  {
    id: 'starter-models',
    q: '刚下载装好后，该装哪些大模型？（为你解决方案）',
    a:
      '迷你安装包不含大模型，请按流水线「每步只装一个」即可开跑（有 NVIDIA 显卡时）：\n'
      + '① 文案提取 → 本机环境安装 FunASR（推荐；也可用 Whisper）\n'
      + '② 配音 → 安装 IndexTTS2（推荐本地克隆/中英混读）\n'
      + '③ 数字人口播 → 装 Docker Desktop + 按显卡下 HeyGem 加速包（通用或 RTX50）并 load\n'
      + '④ 剪辑合成：成片混剪一般不用再下大模型；若要用「一键提取字幕」，请额外安装 Whisper（仅 FunASR 不够）\n'
      + '装好后务必打开「设置 → 全局引擎设置」：文案选「本地 + FunASR」、配音选「本地 + IndexTTS2」、口播选 HeyGem，点保存。'
      + '只装模型不改全局引用，页面仍可能走旧引擎或报未就绪。显存紧张可把配音改成 Piper/Edge（轻量，效果不同）。',
  },
  {
    id: 'boot-96',
    q: '装了特殊引擎/插件后启动卡在约 96%？清运行时后还要重装依赖吗？',
    a:
      '96% 多半是「等本机健康检查」卡住，常见于系统代理/梯子异常（Clash 等），不是引擎文件突然丢了。\n'
      + '先试：① 关失效代理，或先开好梯子再启动；② 等约 20 分钟看日志有无变化；③ 启动页点「打开日志」看 bootstrap.log。\n'
      + '仍不行再点「清除运行时并重试」：会删掉整份运行时（含 Python/FFmpeg 与 engines 里的 FunASR/IndexTTS/Whisper 等），开机后要重新下基础环境，特殊插件一般也要再装一遍。\n'
      + '若只重装「安装包 .exe」、不要点清除运行时：安装盘 JY_IPAgent-Data\\runtime（或 AppData 下 runtime）通常还在，已装模型/依赖大多保留，一般不必重下大模型。',
  },
  {
    id: 'docker-drive',
    q: 'Docker Desktop 只能装 C 盘、体积太大，或注册页打不开？',
    a:
      '请用 0.1.30 及以上：先自行下完整「Docker Desktop Installer.exe」（约 500MB+，资源管理器看大小）。再到「设置 → 特殊引擎安装 → 口播引擎安装向导」：扫描/选安装包 → 选有空间的盘 → 安装到所选目录。扫描到文件但只有一两百 MB 多半下残了。C 盘满时勿指望再拷到 AppData；装到 D/E 即可。个人使用通常不必注册 Docker Hub；验收以本机 docker info 成功为准。UAC 点是，安装往往要几分钟。\n'
      + '也可让本机「豆包」最新版帮你装：打开豆包桌面端 → 说明要装 Docker Desktop、装到哪块盘、装完要启动 → 按它指引操作；装好并启动后，再回本软件口播向导点检测/刷新 Docker 状态。',
  },
  {
    id: 'indextts-ref',
    q: 'IndexTTS2 提示「缺少参考音频」，但音色管理里已上传并选了克隆音色？',
    a:
      '0.1.31+ 已加强参考音路径解析。若仍遇到：① 音色管理上传并点「保存到音色库」；② 关闭后在下方「克隆音色」点选该条（高亮），不要停在系统预设；③ 系统预设也要能用则到本机环境重装 IndexTTS 补 examples；④ 仍失败则删除该音色后重新上传，确认能试听再生成。',
  },
  {
    id: 'indextts-checkpoints',
    q: '克隆/配音报 IndexTTS2 模型未找到 tools\\IndexTTS\\checkpoints？',
    a:
      '打包版模型在运行时 engines\\IndexTTS\\checkpoints，不在安装目录 tools 下。\n'
      + '处理：① 升到 0.1.35+（会自动找运行时模型）；② 设置 → 本机环境 → 安装/重装 IndexTTS2，等 checkpoints 下完；③ 确认已选克隆音色再合成。勿只拷安装包目录里的空 tools 路径。',
  },
  {
    id: 'indextts-hf-repo-id',
    q: '配音报 HFValidationError / Repo id … qwen0.6bemo4-merge？',
    a:
      '情感子模型 qwen0.6bemo4-merge（约 1.2GB）没下全时，Windows 路径会被 HuggingFace 当成仓库名而报错。\n'
      + '处理：升到 0.1.36+ 后重试（会自动补下）；或设置 → 本机环境 → 重装 IndexTTS2，确认 runtime\\engines\\IndexTTS\\checkpoints\\qwen0.6bemo4-merge 里有 config.json 与大体积权重。',
  },
  {
    id: 'extract-script',
    q: '提取文案失败 / 本地已选 FunASR 仍提示装 Whisper？',
    a:
      '请用 0.1.30 及以上。在「设置 → 全局引擎设置」把文案步骤设为「本地」且引擎选 FunASR（或 Whisper），保存后再到文案页提取。并确认「本机环境」已装对应引擎。提取需本机有谷歌 Chrome（不必登录谷歌账号）。',
  },
  {
    id: 'min-vram',
    q: '最低配置要求？',
    a: '建议 NVIDIA 显卡，最低约 8GB 显存；推荐 16GB 及以上显存，口播与本地配音会更稳。',
  },
  {
    id: 'where-download',
    q: '安装包哪里取？',
    a:
      '看群公告 / 下载页，或到 GitHub 搜索仓库 JY_IPAgent 的 Releases。也可克隆源码按文档本地运行（需要一定基础）。',
  },
  {
    id: 'will-charge',
    q: '是否会突然收费？',
    a:
      '不会。软件免费使用，源码开源。设置里的微信收款码仅为自愿打赏（请喝咖啡），不是买软件或会员。任何「付费版 / 激活码 / 官方强制收费」均为诈骗或倒卖。',
  },
  {
    id: 'heygem-pack',
    q: 'HeyGem / 口播镜像包怎么选？',
    a:
      '显卡为 RTX 5060 / 5070 / 5080 / 5090 等 50 系：选「RTX50」镜像包。其它显卡选「通用」包。有稳定外网/梯子时，也可在引擎安装流程里直接拉取；国内拉不动再用夸克加速包。',
  },
  {
    id: 'engine-fail',
    q: '引擎安装失败怎么办？',
    a:
      '先确认网络，有条件可开梯子后重试。未安装 Git 时，IndexTTS / CosyVoice / SadTalker 会改用 ZIP 下载源码，一般仍可装；口播主路径走 Docker/夸克，不必强依赖 Git。旧电脑报 FFmpeg/Python 找不到或 _repo_fetch 解析错误时，请升到 0.1.30+。整合包尚在准备中。急用可联系群主。失败时请用下方「一键反馈」附上诊断包。',
  },
  {
    id: 'funasr-numpy-build',
    q: '本机推荐安装 FunASR 报错 Unknown compiler / vswhere / numpy 编译失败？',
    a:
      '不是要你装 Visual Studio。旧版可能用了系统/豆包沙箱 Python，没有现成 numpy 轮子就去源码编译，才找 cl/gcc。\n'
      + '处理：① 升到 0.1.34+ 后重试「本机环境 → FunASR」；② 若仍失败，启动页「清除运行时并重试」再用便携 Python 重装；③ 口播另需先打开 Docker Desktop，再跑 HeyGem 向导。',
  },
  {
    id: 'boot-pending-lock',
    q: '下载/装引擎中途关掉后，再开软件起不来、像登录不了？',
    a:
      '旧版在恢复排队任务时可能死锁，后端起不来。0.1.34+ 已修复。\n'
      + '临时自救：完全退出软件后，删除运行时目录下的 data\\job_worker_pending.json（或 JY_IPAgent-Data\\runtime 旁的 data），再启动；中断的引擎安装可在设置里重新点安装。\n'
      + '勿用豆包沙箱当「系统 Python」；装坏空环境时用「清除运行时并重试」恢复便携 Python。',
  },
  // —— 底部补充（用户高频） ——
  {
    id: 'update-still-old',
    q: '应用内更新到新版，装完还是旧版本（如 0.1.30）？',
    a:
      '常见原因：点了「Gitee 下载」但 Gitee Release 还停在旧版，等于又装回旧安装包。\n'
      + '处理：检查更新时选带最新版本号的按钮（优先 GitHub）；或到 GitHub Releases 手动下 JY_IPAgent-Setup-新版本.exe 覆盖安装。装完看设置/关于里的版本号确认。\n'
      + '克隆音色 / 部分试听不全：请先确认已真正升到 0.1.31+；克隆需保存后点选该条；普通话等预设试听需 IndexTTS examples（本机环境重装 IndexTTS）。',
  },
  {
    id: 'heygem-param-json',
    q: '升级到 0.1.32 后口播报 param.json /code/data/result 找不到？',
    a:
      '与 Whisper 字幕修复无关。多半是升级/重装加速包后，旧 Docker 容器仍挂着旧数据目录，容器写不了 result。\n'
      + '处理：设置 → 口播引擎安装向导 →「一键启动口播引擎」（会强制重建并挂当前目录）；或 Docker Desktop 删除容器 duix-avatar-gen-video 后再启动。确认引擎就绪后再生成口播。',
  },
  {
    id: 'heygem-docker-load',
    q: '口播向导④「加载镜像」会报错吗？会一直卡着吗？有进度吗？',
    a:
      '会报错：Docker 未开、缺 tar、磁盘满、load 失败都会弹窗。\n'
      + '不会无限挂死：后端 docker load 最长约 1 小时超时；通用包正常约 5～15 分钟。\n'
      + '没有百分比进度（docker load 本身几乎不报进度），界面会显示已用时间。可看 Docker Desktop → Images 是否在变大；磁盘忙则多半仍在加载。超过约 30 分钟完全无动静再重试/查空间。',
  },
  {
    id: 'indextts-preview-clone',
    q: 'IndexTTS2：14 个音色只有粤/东北/台/陕能试听，克隆配音失败？',
    a:
      '正常现象分流：这 4 个方言走 Edge 神经音色，不依赖 IndexTTS 内置 examples，所以能试听、能生成。\n'
      + '其余约 10 个（普通话/英文 + 四川/上海近似）要 IndexTTS 的 examples/*.wav。迷你包装完若没下到 examples，「一键下载试听」会一直缺。\n'
      + '处理：设置 → 本机环境 → 重装/一键安装 IndexTTS（会拉 examples）→ 回配音页再点「一键下载试听」。\n'
      + '克隆失败：音色管理保存后，必须在「克隆音色」列表点选该条（高亮）再生成；升级/换盘后旧路径会失效，删了重传。请用 0.1.31+。',
  },
  {
    id: 'script-ffmpeg-cdn',
    q: '链接提取文案报 FFmpeg 退出码 4294967274 / -22？',
    a:
      '多半不是 FFmpeg 坏了，而是下载的对标视频 reference_from_cdn.mp4 损坏、不完整，或实际是网页错误页。\n'
      + '处理：换一条未过期的分享链接；或改用本机上传视频再提取。确认设置里 FFmpeg 已装。任务中心可用「一键复制报错」反馈。',
  },
  {
    id: 'subtitle-asr-pack',
    q: '第四步混剪「一键提取字幕」报错？安装包常见原因',
    a:
      '迷你安装包不含 Whisper。混剪字幕时间轴目前走本机 Whisper（faster-whisper），只装 FunASR 可以提文案，但不够做第四步字幕提取。\n'
      + '解决：① 设置 → 本机环境 → 安装 Whisper；② 确认 FFmpeg 已装（同页）；③ 有口播成片或配音后再点提取。\n'
      + '失败时到任务中心点「一键复制报错 / 复制并邮件反馈」。旧版若 Whisper 已装仍失败，请更新软件后重装一次 Whisper（会补上时间轴脚本）。',
  },
  {
    id: 'accel-expired',
    q: '镜像包 / 夸克链接失效怎么办？',
    a:
      '私聊作者重新获取最新下载链接即可（勿轻信群外人转发的「收费激活」）。拿到新链接后按显卡下「通用」或「RTX50」整包，放到本机后再「扫描安装」或「按路径安装」。',
  },
  {
    id: 'accel-parse-body',
    q: '安装镜像包提示 There was an error parsing the body？怎么解决？',
    a:
      '这是用网页「拖入/上传」装数 GB 整包时，后端解析失败导致的，不是镜像坏了（分卷、未分卷都会这样）。\n'
      + '解决：① 确认 zip 已完整下载到本机；② 不要点「安装拖入的 zip」；③ 把路径粘贴到输入框点「按路径安装」，或放到「下载」文件夹点「扫描安装」。\n'
      + '通用包按路径安装通常约 5～15 分钟（含解压与 docker load）。一直转圈别关软件；半小时仍无结果再查磁盘空间与 Docker 是否卡住。',
  },
  {
    id: 'accel-stuck',
    q: '按路径安装一直显示「安装中」，怎么判断是卡住还是正常？',
    a:
      '界面暂时没有分步进度，属正常。按阶段自查：\n'
      + '① 资源管理器看运行时目录下是否出现/增大 `_quark_extract`（解压中）或 `heygem` 里的 .tar（拷贝中）。目录在安装盘 `JY_IPAgent-Data\\runtime`，或 `%AppData%\\jy-ipagent\\runtime`。\n'
      + '② 任务管理器：python 进程磁盘读写很高 → 多半在解压/校验；若随后出现 docker 且磁盘忙 → 在 docker load（可再等 10～20 分钟）。\n'
      + '③ 打开 Docker Desktop：若在「Images」里慢慢出现口播镜像，说明还在 load，未卡死。\n'
      + '判定卡住：超过约 30 分钟，且上述文件夹大小长时间不动、python/docker 几乎 0% 磁盘与 CPU。可关软件重开后再「按路径安装」一次；C/目标盘空间不足也会假死。',
  },
  {
    id: 'docker-doubao',
    q: 'Docker Desktop 安装/启动有问题怎么办？（可让豆包协助）',
    a:
      '优先用本软件「口播引擎安装向导」：完整安装包 → 选有空间的盘 → 安装并启动；验收看向导里 Docker 状态 / docker info。\n'
      + '仍搞不定：向导②步有「豆包电脑本地模式」一键复制提示词 → 粘贴到豆包桌面端电脑本地模式执行 → 回向导「重新检测」。\n'
      + '有外网时③步也可复制「只拉镜像」提示词，让豆包 docker pull（镜像名 guiji2025/duix.avatar，50 系用 …-5090），再一键启动。\n'
      + 'FunASR / IndexTTS 失败可把报错贴给豆包；完整提示词见 docs/doubao-install-prompts.md。',
  },
]

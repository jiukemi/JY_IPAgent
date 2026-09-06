/** FAQ shown in Settings → 常见问题. Keep answers short and actionable. */

export type FaqItem = {
  id: string
  q: string
  a: string
}

export const FAQ_ITEMS: FaqItem[] = [
  {
    id: 'boot-96',
    q: '启动卡住约 96% 怎么办？',
    a:
      '先检查网络（含系统代理/梯子是否异常）。若超过约 20 分钟仍无进展，点启动页左下角「清除运行时并重试」。仍失败请用「一键反馈」导出诊断包发给群主。近期版本已针对代理劫持健康检查做过修复，请尽量使用最新安装包。',
  },
  {
    id: 'docker-drive',
    q: 'Docker Desktop 只能装 C 盘、体积太大，或注册页打不开？',
    a:
      '请先自行下载「Docker Desktop Installer.exe」，再到「设置 → 特殊引擎安装 → 口播引擎安装向导」：扫描/选择安装包 → 选盘 → 安装到所选目录。个人使用通常不必注册 Docker Hub，登录窗可跳过；验收以本机 docker info 成功为准。',
  },
  {
    id: 'extract-script',
    q: '提取文案失败怎么办？',
    a:
      '请确认已安装谷歌 Chrome（不必登录谷歌账号）。并在「设置 → 本机环境」安装 Whisper 或 FunASR 至少其中一个，且在文案页选用对应引擎。',
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
      '先确认网络，有条件可开梯子后重试。未安装 Git 时，IndexTTS / CosyVoice / SadTalker 会改用 ZIP 下载源码，一般仍可装；口播主路径走 Docker/夸克，不必强依赖 Git。整合包尚在准备中。急用可联系群主。失败时请用下方「一键反馈」附上诊断包。',
  },
]

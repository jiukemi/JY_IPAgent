/** Third-party summary for Settings → 关于我们（完整版见 docs/THIRD_PARTY_NOTICES.md） */

export const THIRD_PARTY_NOTICE_TITLE = '第三方组件与模型'

export const THIRD_PARTY_SUMMARY =
  '本应用集成开源引擎与可选云端 API。本地引擎（IndexTTS、FunASR、Whisper、HeyGem/Duix、SadTalker、LatentSync、FFmpeg 等）各自遵循上游许可证；' +
  '您在 config.yaml 中配置的 DeepSeek、DashScope、解析/ASR 等云端 Key 受对应服务商条款约束。' +
  '生成内容与合规责任由使用者承担。'

export const AI_COMPLIANCE_NOTE =
  '若您对外提供生成服务（公网 API、代运营账号等），可能涉及生成式 AI 备案、内容标识等监管要求；个人本机私下使用通常由使用者自行合规。' +
  '使用他人肖像/声音合成口播须取得授权。详见第三方声明文档「生成式人工智能与内容合规」章节。'

export type ThirdPartyRow = {
  name: string
  role: string
  license: string
}

/** 常用栈摘要（非完整清单） */
export const THIRD_PARTY_ROWS: ThirdPartyRow[] = [
  { name: 'IndexTTS2', role: '本地配音（默认）', license: '上游 LICENSE' },
  { name: 'FunASR / SenseVoice', role: '本地 ASR', license: '上游 LICENSE' },
  { name: 'OpenAI Whisper', role: '本地 ASR 备选', license: 'MIT' },
  { name: 'HeyGem / Duix', role: '数字人口型（Docker）', license: '官方镜像/文档' },
  { name: 'SadTalker / LatentSync', role: '口型备选 / 实拍精修', license: '上游 LICENSE' },
  { name: 'CosyVoice / Piper / Edge TTS', role: 'TTS 备选', license: '上游 / Microsoft 条款' },
  { name: 'Qwen3-TTS', role: '本地或 DashScope 云端', license: '上游 / 阿里云条款' },
  { name: 'DeepSeek API', role: '文案 LLM（可选）', license: 'DeepSeek 平台条款' },
  { name: 'FFmpeg / rembg / Playwright', role: '媒体与自动化', license: 'LGPL/GPL / 上游 / Apache-2.0' },
  { name: 'React / Vite / Electron', role: '界面与桌面壳', license: 'MIT' },
]

export const REPO_THIRD_PARTY_DOC = 'docs/THIRD_PARTY_NOTICES.md'

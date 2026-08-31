import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import { AlertModal, parseApiError } from './AlertModal'
import { FileDropZone } from './FileDropZone'

export type AvatarItem = {
  id: string
  name: string
  label: string
  source_kind: 'video' | 'portrait'
  preview_url: string
  supports_heygem: boolean
  supports_sadtalker: boolean
  ai_prompt?: string
  created_at?: string
}

type Props = {
  open: boolean
  selectedId: string
  backend: string
  onClose: () => void
  onSelect: (item: AvatarItem) => void
  /** 注册/AI 生成成功：由父页面弹窗提示（避免形象库关闭后看不到反馈） */
  onRegistered?: (item: AvatarItem, message: string) => void
}

type Tab = 'pick' | 'register' | 'ai'

type RegFileMeta = {
  kind: 'video' | 'image' | 'unknown'
  durationSec: number | null
  landscape: boolean | null
}

function detectRegMeta(file: File): Promise<RegFileMeta> {
  const ext = file.name.split('.').pop()?.toLowerCase() || ''
  const videoExt = new Set(['mp4', 'mov', 'webm', 'mkv', 'm4v', 'avi'])
  const imageExt = new Set(['jpg', 'jpeg', 'png', 'webp', 'bmp'])
  if (imageExt.has(ext) || file.type.startsWith('image/')) {
    return Promise.resolve({ kind: 'image', durationSec: null, landscape: null })
  }
  if (!videoExt.has(ext) && !file.type.startsWith('video/')) {
    return Promise.resolve({ kind: 'unknown', durationSec: null, landscape: null })
  }
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file)
    const el = document.createElement('video')
    el.preload = 'metadata'
    el.onloadedmetadata = () => {
      const d = Number.isFinite(el.duration) ? el.duration : null
      const w = el.videoWidth || 0
      const h = el.videoHeight || 0
      const landscape = w > 0 && h > 0 ? w >= h : null
      URL.revokeObjectURL(url)
      resolve({ kind: 'video', durationSec: d, landscape })
    }
    el.onerror = () => {
      URL.revokeObjectURL(url)
      resolve({ kind: 'video', durationSec: null, landscape: null })
    }
    el.src = url
  })
}

function durationHint(sec: number | null): { text: string; ok: boolean } {
  if (sec == null) return { text: '无法读取时长，请确认是有效 mp4/mov', ok: false }
  if (sec < 5) return { text: `过短（${sec.toFixed(1)}s），建议 10–20 秒`, ok: false }
  if (sec > 45) return { text: `较长（${sec.toFixed(0)}s），建议裁剪到 10–20 秒以提速`, ok: false }
  if (sec >= 8 && sec <= 25) return { text: `时长 ${sec.toFixed(1)}s · 理想范围`, ok: true }
  return { text: `时长 ${sec.toFixed(1)}s · 可用，10–20 秒更佳`, ok: true }
}

export function AvatarPickerModal({ open, selectedId, backend, onClose, onSelect, onRegistered }: Props) {
  const [tab, setTab] = useState<Tab>('pick')
  const [items, setItems] = useState<AvatarItem[]>([])
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [regName, setRegName] = useState('')
  const [regFile, setRegFile] = useState<File | null>(null)
  const [regMeta, setRegMeta] = useState<RegFileMeta | null>(null)
  const [aiPrompt, setAiPrompt] = useState('')
  const [aiName, setAiName] = useState('')
  const [alert, setAlert] = useState<{ title: string; message: string; variant: 'error' | 'success' | 'info' } | null>(
    null,
  )

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setItems(await api.avatarLibrary())
    } catch {
      setItems([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (open) void load()
  }, [open, load])

  if (!open) return null

  const filtered = items.filter((item) => {
    if (backend === 'heygem') return item.supports_heygem
    if (backend === 'sadtalker') {
      return item.supports_sadtalker
    }
    return true
  })

  const register = async () => {
    if (!regFile) {
      setAlert({ title: '缺少文件', message: '请上传参考视频或肖像图', variant: 'error' })
      return
    }
    setBusy(true)
    try {
      const res = await api.registerAvatar(regName, regFile)
      await load()
      const row = res.data as AvatarItem
      const message = res.message || '已加入数字人库'
      setTab('pick')
      setRegName('')
      setRegFile(null)
      setRegMeta(null)
      if (row?.id && onRegistered) {
        onRegistered(row, message)
      } else if (row?.id) {
        onSelect(row)
        setAlert({ title: '注册成功', message, variant: 'success' })
      } else {
        setAlert({ title: '注册成功', message, variant: 'success' })
      }
    } catch (e) {
      const { title, message } = parseApiError(e, '注册失败')
      setAlert({ title, message, variant: 'error' })
    } finally {
      setBusy(false)
    }
  }

  const generateAi = async () => {
    if (!aiPrompt.trim()) {
      setAlert({ title: '缺少描述', message: '请输入角色外观描述', variant: 'error' })
      return
    }
    setBusy(true)
    try {
      const res = await api.generateAvatar(aiPrompt, aiName)
      await load()
      const row = res.data as AvatarItem
      const message = res.message || '已注册为 SadTalker 肖像'
      setAiPrompt('')
      setAiName('')
      setTab('pick')
      if (row?.id && onRegistered) {
        onRegistered(row, message)
      } else if (row?.id) {
        onSelect(row)
        setAlert({ title: '生成成功', message, variant: 'success' })
      } else {
        setAlert({ title: '生成成功', message, variant: 'success' })
      }
    } catch (e) {
      const { title, message } = parseApiError(e, 'AI 生成失败')
      setAlert({ title, message, variant: 'error' })
    } finally {
      setBusy(false)
    }
  }

  const pickRegFile = (file: File | null) => {
    if (!file) {
      setRegFile(null)
      setRegMeta(null)
      return
    }
    setRegFile(file)
    void detectRegMeta(file).then(setRegMeta)
  }

  const remove = async (id: string) => {
    if (!window.confirm('确定删除该数字人形象？')) return
    setBusy(true)
    try {
      await api.deleteAvatar(id)
      await load()
    } catch (e) {
      const { title, message } = parseApiError(e, '删除失败')
      setAlert({ title, message, variant: 'error' })
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
        <div className="flex max-h-[90vh] w-full max-w-2xl flex-col rounded-2xl border border-[var(--border)] bg-[var(--panel)]">
          <div className="flex items-center justify-between border-b border-[var(--border)] px-5 py-4">
            <div>
              <h2 className="text-lg font-semibold">数字人形象库</h2>
              <p className="mt-1 text-xs text-[var(--muted)]">
                推荐上传 10–20 秒参考口播视频（HeyGem）· 肖像图 / AI 为备选
              </p>
            </div>
            <button type="button" onClick={onClose} className="text-[var(--muted)] hover:text-[var(--text)]">
              ✕
            </button>
          </div>

          <div className="flex gap-1 border-b border-[var(--border)] px-5 pt-2">
            {(
              [
                ['pick', '选择形象'],
                ['register', '上传注册'],
                ['ai', 'AI 生成'],
              ] as const
            ).map(([id, label]) => (
              <button
                key={id}
                type="button"
                onClick={() => setTab(id)}
                className={`rounded-t-lg px-3 py-2 text-xs ${
                  tab === id
                    ? 'border border-b-0 border-[var(--border)] bg-[var(--panel)] font-semibold text-[var(--accent)]'
                    : 'text-[var(--muted)]'
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          <div className="flex-1 overflow-y-auto p-5">
            {tab === 'pick' && (
              <>
                {loading ? (
                  <p className="text-sm text-[var(--muted)]">加载中…</p>
                ) : filtered.length === 0 ? (
                  <div className="space-y-3 text-sm text-[var(--muted)]">
                    <p>暂无可用形象。</p>
                    <button
                      type="button"
                      onClick={() => setTab('register')}
                      className="rounded-lg border border-[var(--accent)]/40 bg-[var(--select-bg)] px-3 py-2 text-left text-xs text-[var(--accent)] hover:border-[var(--accent)]"
                    >
                      → 去「上传注册」：推荐上传 10–20 秒正脸口播 mp4，效果最佳
                    </button>
                  </div>
                ) : (
                  <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                    {filtered.map((item) => (
                      <div
                        key={item.id}
                        className={`rounded-xl border p-2 ${
                          selectedId === item.id
                            ? 'border-[var(--accent)] bg-[var(--select-bg)]'
                            : 'border-[var(--border)] bg-[var(--bg)]'
                        }`}
                      >
                        <button type="button" className="w-full text-left" onClick={() => onSelect(item)}>
                          {item.source_kind === 'portrait' ? (
                            <img
                              src={item.preview_url}
                              alt={item.name}
                              className="mb-2 aspect-square w-full rounded-lg object-cover"
                            />
                          ) : (
                            <video
                              src={item.preview_url}
                              className="mb-2 aspect-square w-full rounded-lg object-cover"
                              muted
                              playsInline
                              preload="metadata"
                            />
                          )}
                          <div className="truncate text-xs font-medium">{item.name}</div>
                          <div className="text-[10px] text-[var(--muted)]">
                            {item.source_kind === 'video' ? 'HeyGem 视频' : 'SadTalker 肖像'}
                          </div>
                        </button>
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => void remove(item.id)}
                          className="mt-1 text-[10px] text-red-500 hover:underline"
                        >
                          删除
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}

            {tab === 'register' && (
              <div className="space-y-4 text-sm">
                <div className="rounded-xl border border-[var(--accent)]/35 bg-[var(--select-bg)] px-4 py-3">
                  <p className="text-xs font-semibold text-[var(--accent)]">最佳效果 · 四步完成</p>
                  <ol className="mt-2 list-decimal space-y-1 pl-4 text-[11px] leading-relaxed text-[var(--muted)]">
                    <li>
                      <strong className="text-[var(--text)]">拍摄参考视频</strong>：10–20 秒，正脸对镜头自然口播（可念任意台词）
                    </li>
                    <li>
                      <strong className="text-[var(--text)]">上传并注册</strong>：下方选择 mp4/mov，保存进形象库
                    </li>
                    <li>
                      <strong className="text-[var(--text)]">③ 口播选 HeyGem</strong>：用 ② 克隆配音驱动，动作会沿用参考片
                    </li>
                    <li>
                      <strong className="text-[var(--text)]">画质选「均衡」</strong>：试跑用「快速」，成片用「高画质」
                    </li>
                  </ol>
                </div>

                <div className="grid gap-2 sm:grid-cols-2">
                  <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 px-3 py-2">
                    <p className="text-[11px] font-semibold text-emerald-700">推荐 · HeyGem 参考视频</p>
                    <ul className="mt-1 space-y-0.5 text-[10px] text-[var(--muted)]">
                      <li>· 时长 10–20 秒，720p 以上</li>
                      <li>· 竖屏参考 → 竖屏口播；横屏参考 → 横屏口播</li>
                      <li>· 单人正脸，光线均匀，嘴部无遮挡</li>
                      <li>· 轻微点头/手势，避免快晃头</li>
                      <li>· 参考片里的动作会带到成片</li>
                    </ul>
                  </div>
                  <div className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2">
                    <p className="text-[11px] font-semibold text-[var(--text)]">备选 · SadTalker 肖像</p>
                    <ul className="mt-1 space-y-0.5 text-[10px] text-[var(--muted)]">
                      <li>· 仅 jpg/png 正面半身照</li>
                      <li>· 无墨镜帽子，表情自然</li>
                      <li>· 效果不如参考视频自然</li>
                      <li>· 可在 ③ 口播上传「动作参考视频」改善</li>
                    </ul>
                  </div>
                </div>

                <label className="block text-xs font-medium text-[var(--text)]">
                  形象名称
                  <input
                    value={regName}
                    onChange={(e) => setRegName(e.target.value)}
                    className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2.5 text-sm"
                    placeholder="例如：主播小美（方便在列表里辨认）"
                  />
                </label>

                <div>
                  <p className="mb-2 text-xs font-medium text-[var(--text)]">参考文件</p>
                  <FileDropZone
                    file={regFile}
                    onFile={pickRegFile}
                    accept="video/*,image/*,.mp4,.mov,.jpg,.jpeg,.png,.webp"
                    icon="📁"
                    emptyTitle="拖拽文件到此处"
                    emptyHint="或点击选择 · mp4 / mov / jpg / png / webp"
                    chooseLabel="选择文件"
                    replaceLabel="更换文件"
                    accent
                    meta={
                      regFile ? (
                        <>
                          {regMeta?.kind === 'video' && (
                            <>
                              <p className={durationHint(regMeta.durationSec).ok ? 'text-emerald-600' : 'text-[var(--warn-text)]'}>
                                {durationHint(regMeta.durationSec).text} → 将注册为 <strong>HeyGem 视频形象</strong>
                              </p>
                              {regMeta.landscape != null && (
                                <p className="text-[var(--muted)]">
                                  画幅：{regMeta.landscape ? '横屏（约 16:9，口播成片多为横屏）' : '竖屏（约 9:16，口播成片多为竖屏）'}
                                </p>
                              )}
                            </>
                          )}
                          {regMeta?.kind === 'image' && (
                            <p className="text-[var(--warn-text)]">
                              图片将注册为 <strong>SadTalker 肖像</strong>（无参考动作）。想要更自然效果请改传 mp4/mov。
                            </p>
                          )}
                          {regMeta?.kind === 'unknown' && (
                            <p className="text-[var(--warn-text)]">未识别格式，请使用 mp4/mov 或 jpg/png</p>
                          )}
                        </>
                      ) : null
                    }
                  />
                </div>

                <p className="text-[10px] text-[var(--muted)]">
                  注册后自动保存到形象库，并可在「选择形象」中预览。视频与图片不可混用：视频走 HeyGem，图片走 SadTalker。
                </p>
                <button
                  type="button"
                  disabled={busy || !regFile}
                  onClick={() => void register()}
                  className="btn-primary w-full rounded-xl px-4 py-3 text-sm font-semibold disabled:opacity-40"
                >
                  {busy ? '注册中…' : '注册到形象库'}
                </button>
              </div>
            )}

            {tab === 'ai' && (
              <div className="space-y-3 text-sm">
                <div className="rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-[11px] text-[var(--muted)]">
                  <strong className="text-[var(--text)]">说明：</strong>AI 生成的是静态肖像，效果弱于真实参考视频。
                  若追求最佳对口型与自然动作，请用「上传注册」传 10–20 秒口播 mp4。
                </div>
                <label className="block text-xs text-[var(--muted)]">
                  角色描述
                  <textarea
                    value={aiPrompt}
                    onChange={(e) => setAiPrompt(e.target.value)}
                    rows={4}
                    className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-2 py-2 text-sm"
                    placeholder="例如：25岁女性新闻主播，短发，穿白色衬衫，温和微笑"
                  />
                </label>
                <label className="block text-xs text-[var(--muted)]">
                  注册名称（可选）
                  <input
                    value={aiName}
                    onChange={(e) => setAiName(e.target.value)}
                    className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-2 py-2"
                    placeholder="默认可用描述前几个字"
                  />
                </label>
                <p className="text-xs text-[var(--muted)]">
                  使用 DashScope 万相生图（与 Qwen API Key 共用），生成后自动注册为 SadTalker 肖像数字人。
                </p>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void generateAi()}
                  className="btn-primary rounded-lg px-4 py-2 text-xs font-medium disabled:opacity-50"
                >
                  {busy ? '生成中…' : 'AI 生成并注册'}
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      <AlertModal
        open={!!alert}
        title={alert?.title || ''}
        message={alert?.message || ''}
        variant={alert?.variant || 'info'}
        onClose={() => setAlert(null)}
      />
    </>
  )
}

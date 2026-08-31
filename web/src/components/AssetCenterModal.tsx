import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import { HyperFrameThemePicker, type HyperAspectMeta, type HyperLayoutMeta, type HyperThemeMeta } from './HyperFrameThemePicker'
import { StylePackFields, type StylePackOption } from './StylePackFields'

type AssetGroup = { id: string; name: string; builtin?: boolean }
type AssetItem = {
  id: string
  group_id: string
  name: string
  asset_type: string
  kind: 'file' | 'url'
  preview_url?: string | null
  url?: string
  bgm_id?: string
  mood?: string
  category?: string
  user?: boolean
  builtin_bgm?: boolean
  ready?: boolean
  duration_sec?: number
}

type HyperTheme = HyperThemeMeta

type Props = {
  open: boolean
  onClose: () => void
}

export function AssetCenterModal({ open, onClose }: Props) {
  const [groups, setGroups] = useState<AssetGroup[]>([])
  const [items, setItems] = useState<AssetItem[]>([])
  const [activeGroup, setActiveGroup] = useState('card')
  const [busy, setBusy] = useState('')
  const [newGroupName, setNewGroupName] = useState('')
  const [urlForm, setUrlForm] = useState({ name: '', url: '' })
  const [showUrlForm, setShowUrlForm] = useState(false)
  const [hfThemes, setHfThemes] = useState<HyperTheme[]>([])
  const [hfLayouts, setHfLayouts] = useState<HyperLayoutMeta[]>([])
  const [hfAspects, setHfAspects] = useState<HyperAspectMeta[]>([])
  const [hfText, setHfText] = useState('')
  const [hfTheme, setHfTheme] = useState('tokyo_night')
  const [hfLayout, setHfLayout] = useState('kinetic')
  const [hfAspect, setHfAspect] = useState('portrait_9_16')
  const [hfFonts, setHfFonts] = useState<StylePackOption[]>([])
  const [hfBgModes, setHfBgModes] = useState<StylePackOption[]>([])
  const [hfFontId, setHfFontId] = useState('noto_sc')
  const [hfFontScale, setHfFontScale] = useState(1)
  const [hfBgMode, setHfBgMode] = useState('generative')
  const [hfBgPrompt, setHfBgPrompt] = useState('')
  const [hfMode, setHfMode] = useState<'image' | 'video' | 'slideshow'>('image')
  const [hfDuration, setHfDuration] = useState(6)
  const [hfPause, setHfPause] = useState(0.35)
  const [hfMaxChars, setHfMaxChars] = useState(16)
  const [hfName, setHfName] = useState('')
  const [activeStyleNote, setActiveStyleNote] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  const refresh = useCallback(async () => {
    const lib = await api.assetLibrary()
    setGroups(lib.groups)
    setItems(lib.items)
    if (lib.groups.length && !lib.groups.some((g) => g.id === activeGroup)) {
      setActiveGroup(lib.groups[0].id)
    }
  }, [activeGroup])

  useEffect(() => {
    if (!open) return
    void refresh().catch(() => {})
    void api.hyperframeThemes().then((r) => {
      setHfThemes(r.themes)
      setHfLayouts(r.layouts || [])
      setHfAspects(r.aspects || [])
      setHfFonts(r.fonts || [])
      setHfBgModes(r.bg_modes || [])
    }).catch(() => {})
    void api
      .getHyperframeActiveStyle()
      .then((s) => {
        setHfTheme(s.theme)
        setHfLayout(s.layout)
        setHfAspect(s.aspect)
        if (s.font_id) setHfFontId(s.font_id)
        if (typeof s.font_scale === 'number') setHfFontScale(s.font_scale)
        if (s.bg_mode) setHfBgMode(s.bg_mode)
        if (s.bg_prompt != null) setHfBgPrompt(s.bg_prompt)
        setActiveStyleNote(
          `成片风格：${s.theme} · ${s.layout} · ${s.font_id || 'noto_sc'} · ${s.bg_mode || 'generative'}`,
        )
      })
      .catch(() => {})
  }, [open, refresh])

  const saveActiveStyle = async () => {
    setBusy('设风格')
    try {
      const s = await api.setHyperframeActiveStyle({
        theme: hfTheme,
        layout: hfLayout,
        aspect: hfAspect,
        font_id: hfFontId,
        font_scale: hfFontScale,
        bg_mode: hfBgMode,
        bg_prompt: hfBgPrompt,
        remotion_theme: 'off',
      })
      setActiveStyleNote(
        `已设为成片风格：${s.theme} · ${s.layout} · 字号${Math.round((s.font_scale || hfFontScale) * 100)}% · ${s.bg_mode || hfBgMode}`,
      )
    } catch (e) {
      setActiveStyleNote(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy('')
    }
  }

  if (!open) return null

  const groupItems = items.filter((i) => i.group_id === activeGroup)
  const activeMeta = groups.find((g) => g.id === activeGroup)

  const upload = async (file: File) => {
    setBusy('上传')
    try {
      await api.uploadAsset(activeGroup, file.name.replace(/\.[^.]+$/, ''), file)
      await refresh()
    } finally {
      setBusy('')
    }
  }

  const addUrl = async () => {
    if (!urlForm.url.trim()) return
    setBusy('添加')
    try {
      await api.addAssetUrl(activeGroup, urlForm.name, urlForm.url.trim())
      setUrlForm({ name: '', url: '' })
      setShowUrlForm(false)
      await refresh()
    } finally {
      setBusy('')
    }
  }

  const generateHyperframe = async () => {
    if (!hfText.trim()) return
    setBusy('生成场景')
    try {
      await api.generateHyperframeAsset({
        text: hfText.trim(),
        mode: hfMode,
        theme: hfTheme,
        layout: hfLayout,
        aspect: hfAspect,
        name: hfName.trim() || undefined,
        duration_sec: hfMode === 'video' ? hfDuration : undefined,
        pause_sec: hfMode === 'slideshow' ? hfPause : undefined,
        max_chars: hfMode === 'slideshow' ? hfMaxChars : undefined,
        group_id: hfMode === 'slideshow' || hfMode === 'video' ? 'video' : 'card',
      })
      setHfName('')
      await refresh()
      if (hfMode === 'slideshow' || hfMode === 'video') setActiveGroup('video')
      else setActiveGroup('card')
    } finally {
      setBusy('')
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 p-4">
      <div className="flex max-h-[88vh] w-full max-w-4xl flex-col rounded-2xl border border-[var(--border)] bg-[var(--panel)] shadow-2xl">
        <div className="flex items-center justify-between border-b border-[var(--border)] px-5 py-4">
          <div>
            <h2 className="text-lg font-semibold">素材中心</h2>
            <p className="mt-0.5 text-xs text-[var(--muted)]">
              管理图标、HyperFrames、音频、背景音乐、视频与数字人分身；BGM 可在此试听与上传
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm hover:bg-[var(--panel-2)]"
          >
            关闭
          </button>
        </div>

        <div className="flex min-h-0 flex-1">
          <aside className="w-44 shrink-0 border-r border-[var(--border)] p-3">
            <p className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-[var(--muted)]">分组</p>
            <div className="space-y-1">
              {groups.map((g) => (
                <div key={g.id} className="flex items-center gap-1">
                  <button
                    type="button"
                    onClick={() => setActiveGroup(g.id)}
                    className={`min-w-0 flex-1 truncate rounded-lg px-2 py-1.5 text-left text-xs ${
                      activeGroup === g.id
                        ? 'bg-[var(--select-bg)] text-[var(--accent)]'
                        : 'hover:bg-[var(--panel-2)]'
                    }`}
                  >
                    {g.name}
                  </button>
                  {!g.builtin && (
                    <button
                      type="button"
                      title="删除分组"
                      className="px-1 text-[10px] text-red-400"
                      onClick={() => void api.deleteAssetGroup(g.id).then(refresh)}
                    >
                      ×
                    </button>
                  )}
                </div>
              ))}
            </div>
            <div className="mt-3 flex gap-1">
              <input
                value={newGroupName}
                onChange={(e) => setNewGroupName(e.target.value)}
                placeholder="新分组"
                className="min-w-0 flex-1 rounded border border-[var(--border)] bg-[var(--bg)] px-2 py-1 text-[10px]"
              />
              <button
                type="button"
                disabled={!newGroupName.trim() || !!busy}
                onClick={() => {
                  const n = newGroupName.trim()
                  void api.createAssetGroup(n).then(() => {
                    setNewGroupName('')
                    return refresh()
                  })
                }}
                className="rounded border border-[var(--border)] px-2 text-[10px] hover:bg-[var(--panel-2)]"
              >
                +
              </button>
            </div>
          </aside>

          <div className="flex min-w-0 flex-1 flex-col overflow-y-auto p-4">
            {activeGroup === 'card' && (
            <div className="mb-4 rounded-xl border border-[var(--info-border)] bg-[var(--info-bg)] p-3">
              <p className="text-xs font-semibold text-[var(--info-text)]">HyperFrames · 文案场景合成</p>
              <p className="mt-1 text-[10px] text-[var(--muted)]">
                本地根据文案自动配色并合成 CSS 动效场景，支持竖屏 9:16 / 横屏 16:9。
              </p>
              <textarea
                value={hfText}
                onChange={(e) => setHfText(e.target.value)}
                rows={3}
                placeholder="输入一句标题，或多段讲解文案（幻灯片模式会按句切分）"
                className="mt-2 w-full rounded-lg border border-[var(--border)] bg-[var(--panel)] px-3 py-2 text-sm"
              />
              <div className="mt-3">
                <HyperFrameThemePicker
                  themes={hfThemes}
                  layouts={hfLayouts}
                  aspects={hfAspects}
                  value={hfTheme}
                  onChange={setHfTheme}
                  layout={hfLayout}
                  onLayoutChange={setHfLayout}
                  aspect={hfAspect}
                  onAspectChange={setHfAspect}
                  previewText={hfText || 'AI 驱动 ROI 提升 200%'}
                  fontScale={hfFontScale}
                />
              </div>
              <div className="mt-3 rounded-lg border border-[var(--border)] bg-[var(--panel)] p-3">
                <StylePackFields
                  fonts={hfFonts}
                  bgModes={hfBgModes}
                  fontId={hfFontId}
                  fontScale={hfFontScale}
                  bgMode={hfBgMode}
                  bgPrompt={hfBgPrompt}
                  onFontId={setHfFontId}
                  onFontScale={setHfFontScale}
                  onBgMode={setHfBgMode}
                  onBgPrompt={setHfBgPrompt}
                />
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  disabled={!!busy}
                  onClick={() => void saveActiveStyle()}
                  className="rounded-lg border border-[var(--accent)] px-3 py-1.5 text-xs font-medium text-[var(--accent)] hover:bg-[var(--select-bg)] disabled:opacity-40"
                >
                  {busy === '设风格' ? '保存中…' : '设为成片风格'}
                </button>
                {activeStyleNote && (
                  <span className="text-[10px] text-[var(--muted)]">{activeStyleNote}</span>
                )}
              </div>
              <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                <label className="block text-[10px] text-[var(--muted)]">
                  输出类型
                  <select
                    value={hfMode}
                    onChange={(e) => setHfMode(e.target.value as typeof hfMode)}
                    className="mt-1 w-full rounded border border-[var(--border)] bg-[var(--panel)] px-2 py-1.5 text-xs"
                  >
                    <option value="image">单帧 PNG 预览</option>
                    <option value="video">CSS 动效短视频</option>
                    <option value="slideshow">多段场景幻灯片</option>
                  </select>
                </label>
                {hfMode === 'video' && (
                  <label className="block text-[10px] text-[var(--muted)]">
                    时长 {hfDuration}s
                    <input
                      type="range"
                      min={2}
                      max={30}
                      value={hfDuration}
                      onChange={(e) => setHfDuration(Number(e.target.value))}
                      className="mt-1 w-full"
                    />
                  </label>
                )}
                {hfMode === 'slideshow' && (
                  <>
                    <label className="block text-[10px] text-[var(--muted)]">
                      句间停顿 {hfPause.toFixed(2)}s
                      <input
                        type="range"
                        min={0.1}
                        max={1.2}
                        step={0.05}
                        value={hfPause}
                        onChange={(e) => setHfPause(Number(e.target.value))}
                        className="mt-1 w-full"
                      />
                    </label>
                    <label className="block text-[10px] text-[var(--muted)]">
                      每卡字数 {hfMaxChars}
                      <input
                        type="range"
                        min={8}
                        max={24}
                        step={1}
                        value={hfMaxChars}
                        onChange={(e) => setHfMaxChars(Number(e.target.value))}
                        className="mt-1 w-full"
                      />
                    </label>
                  </>
                )}
                <label className="block text-[10px] text-[var(--muted)]">
                  素材名称（可选）
                  <input
                    value={hfName}
                    onChange={(e) => setHfName(e.target.value)}
                    className="mt-1 w-full rounded border border-[var(--border)] bg-[var(--panel)] px-2 py-1.5 text-xs"
                    placeholder="默认识别文案前几句"
                  />
                </label>
              </div>
              <button
                type="button"
                disabled={!!busy || !hfText.trim()}
                onClick={() => void generateHyperframe()}
                className="btn-primary mt-3 rounded-lg px-4 py-2 text-xs font-semibold disabled:opacity-40"
              >
                {busy === '生成场景' ? '生成中…' : '生成并入库'}
              </button>
            </div>
            )}

            {activeGroup === 'avatar' ? (
              <AvatarGroupPanel busy={busy} setBusy={setBusy} />
            ) : (
              <>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div>
                <span className="text-sm font-medium">{activeMeta?.name || '素材'}</span>
                {activeGroup === 'bgm' && (
                  <p className="mt-0.5 text-[10px] text-[var(--muted)]">
                    内置曲库 + 你上传的 BGM；上传后可在发布页「背景音乐」直接选用
                  </p>
                )}
              </div>
              <div className="flex flex-wrap gap-2">
                <input
                  ref={fileRef}
                  type="file"
                  className="hidden"
                  accept={
                    activeGroup === 'bgm'
                      ? 'audio/*,.mp3,.wav,.m4a,.aac,.ogg,.flac'
                      : 'image/*,audio/*,video/*,.svg,.ico'
                  }
                  onChange={(e) => {
                    const f = e.target.files?.[0]
                    if (f) void upload(f)
                    e.target.value = ''
                  }}
                />
                <button
                  type="button"
                  disabled={!!busy}
                  onClick={() => fileRef.current?.click()}
                  className="btn-primary rounded-lg px-3 py-1.5 text-xs font-medium disabled:opacity-50"
                >
                  {busy === '上传' ? '上传中…' : activeGroup === 'bgm' ? '上传 BGM' : '上传文件'}
                </button>
                {activeGroup !== 'bgm' && (
                  <button
                    type="button"
                    onClick={() => setShowUrlForm((v) => !v)}
                    className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs hover:bg-[var(--panel-2)]"
                  >
                    添加 URL
                  </button>
                )}
              </div>
            </div>

            {showUrlForm && activeGroup !== 'bgm' && (
              <div className="mb-3 flex flex-wrap items-end gap-2 rounded-xl border border-dashed border-[var(--border)] bg-[var(--bg)] p-3">
                <label className="block flex-1 text-xs text-[var(--muted)]">
                  名称
                  <input
                    value={urlForm.name}
                    onChange={(e) => setUrlForm((s) => ({ ...s, name: e.target.value }))}
                    className="mt-1 w-full rounded border border-[var(--border)] bg-[var(--panel)] px-2 py-1.5 text-sm"
                    placeholder="可选"
                  />
                </label>
                <label className="block min-w-[200px] flex-[2] text-xs text-[var(--muted)]">
                  资源 URL
                  <input
                    value={urlForm.url}
                    onChange={(e) => setUrlForm((s) => ({ ...s, url: e.target.value }))}
                    className="mt-1 w-full rounded border border-[var(--border)] bg-[var(--panel)] px-2 py-1.5 text-sm"
                    placeholder="https://..."
                  />
                </label>
                <button
                  type="button"
                  disabled={!!busy || !urlForm.url.trim()}
                  onClick={() => void addUrl()}
                  className="btn-primary rounded-lg px-3 py-2 text-xs disabled:opacity-50"
                >
                  保存
                </button>
              </div>
            )}

            {groupItems.length === 0 ? (
              <p className="text-sm text-[var(--muted)]">暂无素材，可上传或添加网络资源 URL</p>
            ) : (
              <div className="grid max-h-[50vh] gap-3 overflow-y-auto sm:grid-cols-2 lg:grid-cols-3">
                {groupItems.map((item) => (
                  <AssetCard
                    key={item.id}
                    item={item}
                    groups={groups.filter((g) => g.id !== 'avatar')}
                    onChanged={refresh}
                  />
                ))}
              </div>
            )}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function AvatarGroupPanel({
  busy,
  setBusy,
}: {
  busy: string
  setBusy: (v: string) => void
}) {
  const [avatars, setAvatars] = useState<
    {
      id: string
      name: string
      source_kind: string
      preview_url: string
      supports_heygem?: boolean
      supports_sadtalker?: boolean
    }[]
  >([])
  const [name, setName] = useState('')
  const [note, setNote] = useState('')
  const [viewId, setViewId] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const refresh = useCallback(async () => {
    const list = await api.avatarLibrary()
    setAvatars(list)
  }, [])

  useEffect(() => {
    void refresh().catch(() => setAvatars([]))
  }, [refresh])

  const uploadAvatar = async (file: File) => {
    setBusy('上传分身')
    setNote('')
    try {
      const res = await api.registerAvatar(name.trim() || file.name.replace(/\.[^.]+$/, ''), file)
      setName('')
      setNote(res.message || '已注册数字人分身')
      await refresh()
      const id = (res.data as { id?: string } | undefined)?.id
      if (id) setViewId(id)
    } catch (e) {
      setNote(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy('')
    }
  }

  const viewing = avatars.find((a) => a.id === viewId) || null

  return (
    <div className="space-y-3">
      <div className="rounded-xl border border-[var(--info-border)] bg-[var(--info-bg)] p-3">
        <p className="text-xs font-semibold text-[var(--info-text)]">数字人分身（固定分组）</p>
        <p className="mt-1 text-[10px] leading-relaxed text-[var(--muted)]">
          上传参考视频（HeyGem）或肖像图（SadTalker）。写入全局形象库，口播页可直接选用；视频分身可点击查看原视频。
        </p>
        <div className="mt-2 flex flex-wrap items-end gap-2">
          <label className="block min-w-[140px] flex-1 text-[10px] text-[var(--muted)]">
            名称
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="mt-1 w-full rounded border border-[var(--border)] bg-[var(--panel)] px-2 py-1.5 text-xs"
              placeholder="可选，默认用文件名"
            />
          </label>
          <input
            ref={fileRef}
            type="file"
            className="hidden"
            accept="video/*,image/*,.mp4,.mov,.webm,.jpg,.jpeg,.png,.webp"
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) void uploadAvatar(f)
              e.target.value = ''
            }}
          />
          <button
            type="button"
            disabled={!!busy}
            onClick={() => fileRef.current?.click()}
            className="btn-primary rounded-lg px-3 py-2 text-xs font-medium disabled:opacity-50"
          >
            {busy === '上传分身' ? '上传中…' : '上传分身'}
          </button>
        </div>
        {note && <p className="mt-2 text-[11px] text-[var(--muted)]">{note}</p>}
      </div>

      {avatars.length === 0 ? (
        <p className="text-sm text-[var(--muted)]">暂无分身，请上传参考视频或肖像图</p>
      ) : (
        <div className="grid max-h-[50vh] gap-3 overflow-y-auto sm:grid-cols-2 lg:grid-cols-3">
          {avatars.map((a) => {
            const isVideo = a.source_kind === 'video'
            return (
              <div key={a.id} className="rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3">
                <div className="mb-2 flex aspect-video items-center justify-center overflow-hidden rounded-lg bg-[var(--panel)]">
                  {isVideo && a.preview_url ? (
                    <button
                      type="button"
                      className="group relative h-full w-full"
                      onClick={() => setViewId(a.id)}
                      title="查看原视频"
                    >
                      <video
                        className="max-h-full max-w-full object-contain"
                        src={a.preview_url}
                        muted
                        playsInline
                        preload="metadata"
                        onMouseEnter={(e) => {
                          void e.currentTarget.play().catch(() => {})
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.pause()
                          e.currentTarget.currentTime = 0
                        }}
                      />
                      <span className="pointer-events-none absolute inset-0 flex items-center justify-center bg-black/25 opacity-0 transition group-hover:opacity-100">
                        <span className="rounded-full bg-black/60 px-3 py-1 text-[11px] text-white">
                          查看原视频
                        </span>
                      </span>
                    </button>
                  ) : a.preview_url ? (
                    <button type="button" className="h-full w-full" onClick={() => setViewId(a.id)}>
                      <img src={a.preview_url} alt="" className="max-h-full max-w-full object-contain" />
                    </button>
                  ) : (
                    <span className="text-2xl opacity-50">🧑</span>
                  )}
                </div>
                <p className="truncate text-xs font-medium">{a.name}</p>
                <p className="mt-0.5 text-[10px] text-[var(--muted)]">
                  {isVideo ? '参考视频 · HeyGem' : '肖像 · SadTalker'}
                </p>
                <div className="mt-2 flex items-center gap-2">
                  <button
                    type="button"
                    className="text-[10px] text-[var(--accent)] underline"
                    onClick={() => setViewId(a.id)}
                  >
                    {isVideo ? '查看原视频' : '查看大图'}
                  </button>
                  <button
                    type="button"
                    className="ml-auto text-[10px] text-red-400 hover:underline"
                    onClick={() => {
                      if (!window.confirm(`删除分身「${a.name}」？`)) return
                      void api.deleteAvatar(a.id).then(refresh)
                    }}
                  >
                    删除
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {viewing && (
        <div
          className="fixed inset-0 z-[80] flex items-center justify-center bg-black/70 p-4"
          onClick={() => setViewId(null)}
          role="presentation"
        >
          <div
            className="relative w-full max-w-3xl rounded-xl border border-[var(--border)] bg-[var(--panel)] p-3 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-label={viewing.name}
          >
            <div className="mb-2 flex items-center justify-between gap-2">
              <p className="truncate text-sm font-medium">
                {viewing.name}
                <span className="ml-2 text-[10px] font-normal text-[var(--muted)]">
                  {viewing.source_kind === 'video' ? '原视频' : '原图'}
                </span>
              </p>
              <button
                type="button"
                className="rounded-lg border border-[var(--border)] px-2 py-1 text-xs hover:bg-[var(--panel-2)]"
                onClick={() => setViewId(null)}
              >
                关闭
              </button>
            </div>
            {viewing.source_kind === 'video' ? (
              <video
                src={viewing.preview_url}
                controls
                autoPlay
                className="max-h-[70vh] w-full rounded-lg bg-black"
              />
            ) : (
              <img
                src={viewing.preview_url}
                alt={viewing.name}
                className="mx-auto max-h-[70vh] max-w-full rounded-lg object-contain"
              />
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function AssetCard({
  item,
  groups,
  onChanged,
}: {
  item: AssetItem
  groups: AssetGroup[]
  onChanged: () => Promise<void>
}) {
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(item.name)
  const [videoOpen, setVideoOpen] = useState(false)
  const isBgm = item.group_id === 'bgm' || Boolean(item.bgm_id)
  const canDelete = !item.builtin_bgm
  const canRename = !isBgm

  const saveName = async () => {
    if (!canRename) {
      setEditing(false)
      setName(item.name)
      return
    }
    await api.updateAssetItem(item.id, { name: name.trim() || item.name })
    setEditing(false)
    await onChanged()
  }

  const videoSrc =
    item.asset_type === 'video' && item.kind === 'file' && item.preview_url
      ? item.preview_url
      : null

  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3">
      <div className="mb-2 flex aspect-video items-center justify-center overflow-hidden rounded-lg bg-[var(--panel)]">
        {item.asset_type === 'icon' && item.preview_url ? (
          <img src={item.preview_url} alt="" className="max-h-full max-w-full object-contain" />
        ) : videoSrc ? (
          <button
            type="button"
            className="group relative h-full w-full"
            onClick={() => setVideoOpen(true)}
            title="点击放大播放"
          >
            <video
              className="max-h-full max-w-full object-contain"
              src={videoSrc}
              muted
              playsInline
              preload="metadata"
              onMouseEnter={(e) => {
                void e.currentTarget.play().catch(() => {})
              }}
              onMouseLeave={(e) => {
                e.currentTarget.pause()
                e.currentTarget.currentTime = 0
              }}
            />
            <span className="pointer-events-none absolute inset-0 flex items-center justify-center bg-black/25 opacity-0 transition group-hover:opacity-100">
              <span className="rounded-full bg-black/60 px-3 py-1 text-[11px] text-white">放大播放</span>
            </span>
          </button>
        ) : item.asset_type === 'video' ? (
          <span className="text-2xl opacity-50">🎬</span>
        ) : item.asset_type === 'audio' ? (
          item.preview_url ? (
            <div className="flex w-full flex-col items-center gap-2 px-2">
              <span className="text-2xl opacity-60">🎵</span>
              <audio controls className="w-full" src={item.preview_url} preload="metadata" />
            </div>
          ) : (
            <span className="text-[11px] text-[var(--muted)]">未就绪</span>
          )
        ) : (
          <span className="text-2xl opacity-50">📁</span>
        )}
      </div>
      {videoOpen && videoSrc && (
        <div
          className="fixed inset-0 z-[80] flex items-center justify-center bg-black/70 p-4"
          onClick={() => setVideoOpen(false)}
          role="presentation"
        >
          <div
            className="relative w-full max-w-3xl rounded-xl border border-[var(--border)] bg-[var(--panel)] p-3 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-label={item.name}
          >
            <div className="mb-2 flex items-center justify-between gap-2">
              <p className="truncate text-sm font-medium">{item.name}</p>
              <button
                type="button"
                className="rounded-lg border border-[var(--border)] px-2 py-1 text-xs hover:bg-[var(--panel-2)]"
                onClick={() => setVideoOpen(false)}
              >
                关闭
              </button>
            </div>
            <video src={videoSrc} controls autoPlay className="max-h-[70vh] w-full rounded-lg bg-black" />
          </div>
        </div>
      )}
      {editing && canRename ? (
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          onBlur={() => void saveName()}
          onKeyDown={(e) => e.key === 'Enter' && void saveName()}
          className="w-full rounded border border-[var(--border)] bg-[var(--panel)] px-2 py-1 text-xs"
          autoFocus
        />
      ) : (
        <button
          type="button"
          onClick={() => canRename && setEditing(true)}
          className={`w-full truncate text-left text-xs font-medium ${canRename ? 'hover:text-[var(--accent)]' : ''}`}
        >
          {item.name}
        </button>
      )}
      <p className="mt-1 truncate text-[10px] text-[var(--muted)]">
        {isBgm
          ? `${item.user ? '我的上传' : item.category || '曲库'}${item.mood ? ` · ${item.mood}` : ''}${
              typeof item.duration_sec === 'number' ? ` · ${item.duration_sec}s` : ''
            }${item.ready === false ? ' · 未下载' : ''}`
          : item.kind === 'url'
            ? item.url
            : '本地文件'}
      </p>
      <div className="mt-2 flex items-center gap-2">
        {!isBgm && (
          <select
            value={item.group_id}
            onChange={(e) => void api.updateAssetItem(item.id, { group_id: e.target.value }).then(onChanged)}
            className="min-w-0 flex-1 rounded border border-[var(--border)] bg-[var(--panel)] px-1 py-0.5 text-[10px]"
          >
            {groups
              .filter((g) => g.id !== 'avatar' && g.id !== 'bgm')
              .map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name}
                </option>
              ))}
          </select>
        )}
        {canDelete ? (
          <button
            type="button"
            className="text-[10px] text-red-400 hover:underline"
            onClick={() => {
              if (!window.confirm(`删除「${item.name}」？`)) return
              void api.deleteAssetItem(item.id).then(onChanged)
            }}
          >
            删除
          </button>
        ) : (
          <span className="text-[10px] text-[var(--muted)]">内置</span>
        )}
      </div>
    </div>
  )
}

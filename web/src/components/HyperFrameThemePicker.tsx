import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'

export type HyperThemeMeta = {
  id: string
  label: string
  top: string
  bottom: string
  text: string
  accent: string
  outline: string
}

export type HyperLayoutMeta = {
  id: string
  label: string
  animated: boolean
  width: number
  height: number
}

export type HyperAspectMeta = {
  id: string
  label: string
  width: number
  height: number
  ratio: string
}

type Props = {
  themes: HyperThemeMeta[]
  layouts?: HyperLayoutMeta[]
  aspects?: HyperAspectMeta[]
  value: string
  onChange: (id: string) => void
  layout?: string
  onLayoutChange?: (id: string) => void
  aspect?: string
  onAspectChange?: (id: string) => void
  previewText: string
  fontScale?: number
  compact?: boolean
  composeMode?: 'fusion' | 'cover' | ''
  /** When true, preview only loads after clicking the generate button. */
  manualPreview?: boolean
}

export function HyperFrameThemePicker({
  themes,
  layouts = [],
  aspects = [],
  value,
  onChange,
  layout = 'kinetic',
  onLayoutChange,
  aspect = 'portrait_9_16',
  onAspectChange,
  previewText,
  fontScale = 1,
  compact,
  composeMode = '',
  manualPreview = false,
}: Props) {
  const [stillUrl, setStillUrl] = useState<string | null>(null)
  const [motionUrl, setMotionUrl] = useState<string | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [motionReady, setMotionReady] = useState(false)
  const [motionFailed, setMotionFailed] = useState(false)
  const [previewStale, setPreviewStale] = useState(true)

  const sample = useMemo(() => {
    const raw = previewText.trim().replace(/\s+/g, ' ')
    if (!raw) return 'HyperFrames 智能配色预览'
    return raw.length > 160 ? `${raw.slice(0, 159)}…` : raw
  }, [previewText])

  const aspectMeta = aspects.find((a) => a.id === aspect)
  const layoutMeta = layouts.find((l) => l.id === layout)
  const isLandscape = (aspectMeta?.width ?? 1080) > (aspectMeta?.height ?? 1920)
  const wantsMotion = layoutMeta ? layoutMeta.animated !== false : true
  const normalizedFontScale = Math.max(0.7, Math.min(2, fontScale || 1))

  const loadPreview = useCallback(() => {
    setPreviewLoading(true)
    setMotionReady(false)
    setMotionFailed(false)
    const still = api.hyperframePreviewUrl(
      value,
      sample,
      layout,
      aspect,
      normalizedFontScale,
      composeMode,
    )
    setStillUrl(`${still}&_=${Date.now()}`)
    setMotionUrl(null)

    const t = window.setTimeout(() => {
      if (!wantsMotion) {
        setPreviewLoading(false)
        return
      }
      const motion = api.hyperframePreviewMotionUrl(
        value,
        sample,
        layout,
        aspect,
        normalizedFontScale,
        composeMode,
      )
      setMotionUrl(`${motion}&_=${Date.now()}`)
    }, 280)
    return () => window.clearTimeout(t)
  }, [value, sample, layout, aspect, wantsMotion, normalizedFontScale, composeMode])

  useEffect(() => {
    if (manualPreview) {
      setPreviewStale(true)
      return
    }
    setPreviewStale(false)
    return loadPreview()
  }, [manualPreview, loadPreview])

  useEffect(() => {
    if (manualPreview) setPreviewStale(true)
  }, [manualPreview, value, sample, layout, aspect, normalizedFontScale])

  const triggerPreview = () => {
    setPreviewStale(false)
    loadPreview()
  }

  if (!themes.length) {
    return <p className="text-[10px] text-[var(--muted)]">加载主题…</p>
  }

  return (
    <div className={compact ? 'space-y-2' : 'space-y-3'}>
      {aspects.length > 0 && onAspectChange && (
        <div>
          <p className="mb-1.5 text-[10px] font-medium text-[var(--text)]">画幅比例</p>
          <div className="flex flex-wrap gap-2">
            {aspects.map((a) => {
              const active = a.id === aspect
              const landscape = a.width > a.height
              return (
                <button
                  key={a.id}
                  type="button"
                  onClick={() => onAspectChange(a.id)}
                  className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-left transition ${
                    active
                      ? 'border-[var(--accent)] bg-[var(--select-bg)] ring-1 ring-[var(--select-border)]'
                      : 'border-[var(--border)] hover:border-[var(--muted)]'
                  }`}
                >
                  <span
                    className={`inline-block shrink-0 rounded border border-white/20 bg-gradient-to-br from-[var(--accent)]/30 to-transparent ${
                      landscape ? 'h-5 w-9' : 'h-9 w-5'
                    }`}
                  />
                  <span>
                    <span className="block text-[10px] font-medium">{a.label}</span>
                    <span className="text-[9px] text-[var(--muted)]">{a.ratio}</span>
                  </span>
                </button>
              )
            })}
          </div>
        </div>
      )}

      {layouts.length > 0 && onLayoutChange && (
        <div>
          <p className="mb-1.5 text-[10px] font-medium text-[var(--text)]">场景版式</p>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {layouts.map((l) => {
              const active = l.id === layout
              return (
                <button
                  key={l.id}
                  type="button"
                  onClick={() => onLayoutChange(l.id)}
                  className={`rounded-lg border px-2 py-2 text-left transition ${
                    active
                      ? 'border-[var(--accent)] bg-[var(--select-bg)] ring-1 ring-[var(--select-border)]'
                      : 'border-[var(--border)] hover:border-[var(--muted)]'
                  }`}
                >
                  <span className="block text-[10px] font-medium">{l.label}</span>
                  <span className="mt-0.5 block text-[9px] text-[var(--muted)]">
                    {l.animated ? '智能配色 · 动效' : '静态帧'}
                  </span>
                </button>
              )
            })}
          </div>
        </div>
      )}

      <div>
        <p className="mb-1.5 text-[10px] font-medium text-[var(--text)]">配色主题</p>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {themes.map((t) => {
            const active = t.id === value
            return (
              <button
                key={t.id}
                type="button"
                onClick={() => onChange(t.id)}
                className={`rounded-lg border p-2 text-left transition ${
                  active
                    ? 'border-[var(--accent)] bg-[var(--select-bg)] ring-1 ring-[var(--select-border)]'
                    : 'border-[var(--border)] hover:border-[var(--muted)]'
                }`}
              >
                <div
                  className="mb-1.5 h-8 overflow-hidden rounded border border-white/10"
                  style={{
                    background: `linear-gradient(180deg, ${t.top} 0%, ${t.bottom} 100%)`,
                  }}
                >
                  <div className="h-1.5 w-full" style={{ background: t.accent }} />
                </div>
                <span className="block truncate text-[10px] font-medium">{t.label}</span>
              </button>
            )
          })}
        </div>
      </div>

      <div className="rounded-lg border border-dashed border-[var(--border)] bg-[var(--bg)] p-2">
        <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
          <p className="text-[9px] text-[var(--muted)]">
            {manualPreview
              ? previewStale
                ? '调整版式/主题/字号后，点击下方按钮生成预览'
                : wantsMotion && !motionFailed
                  ? '动效预览（循环）· 用当前字幕文案'
                  : '静态预览 · 用当前字幕文案'
              : wantsMotion && !motionFailed
                ? '动效预览（循环）· 用当前字幕文案'
                : '静态预览 · 用当前字幕文案'}
            {' · '}
            {aspectMeta?.ratio || '9:16'}
            {normalizedFontScale !== 1 ? ` · 字号 ${Math.round(normalizedFontScale * 100)}%` : ''}
          </p>
          {manualPreview && (
            <button
              type="button"
              disabled={previewLoading}
              onClick={() => triggerPreview()}
              className="rounded-md border border-[var(--border)] bg-[var(--panel)] px-2 py-1 text-[10px] text-[var(--text)] hover:border-[var(--accent)] disabled:opacity-50"
            >
              {previewLoading
                ? '渲染中…'
                : previewStale || !stillUrl
                  ? '生成场景预览'
                  : '重新生成场景预览'}
            </button>
          )}
        </div>
        <div
          className={`relative mx-auto flex w-full items-center justify-center overflow-hidden rounded-md bg-[var(--panel)] ${
            isLandscape
              ? 'aspect-video max-h-40 max-w-full'
              : 'aspect-[9/16] max-h-72 w-full max-w-[200px]'
          }`}
        >
          {previewLoading && (
            <div className="absolute inset-0 z-10 flex items-center justify-center bg-[var(--panel)]/70 text-[10px] text-[var(--muted)]">
              {wantsMotion && !motionReady ? '渲染动效预览…' : '渲染预览…'}
            </div>
          )}
          {manualPreview && previewStale && !stillUrl && !previewLoading && (
            <div className="px-3 text-center text-[10px] leading-relaxed text-[var(--muted)]">
              尚未生成预览
            </div>
          )}
          {/* Still as placeholder until motion is ready */}
          {stillUrl && !(motionReady && motionUrl) && (
            <img
              src={stillUrl}
              alt="场景静态预览"
              className={`max-h-full max-w-full object-contain ${previewStale ? 'opacity-55' : ''}`}
              onLoad={() => {
                if (!wantsMotion || motionFailed) setPreviewLoading(false)
              }}
              onError={() => setPreviewLoading(false)}
            />
          )}
          {motionUrl && !motionFailed && (
            <video
              key={motionUrl}
              src={motionUrl}
              className={`max-h-full max-w-full object-contain ${motionReady ? '' : 'absolute opacity-0'} ${
                previewStale ? 'opacity-55' : ''
              }`}
              autoPlay
              loop
              muted
              playsInline
              onLoadedData={() => {
                setMotionReady(true)
                setPreviewLoading(false)
              }}
              onError={() => {
                setMotionFailed(true)
                setPreviewLoading(false)
              }}
            />
          )}
        </div>
        {sample && (
          <p className="mt-1.5 line-clamp-2 text-[9px] leading-relaxed text-[var(--muted)]">
            文案：{sample}
          </p>
        )}
      </div>
    </div>
  )
}

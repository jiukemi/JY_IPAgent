import { useEffect, useRef, useState } from 'react'
import { mediaUrl } from '../api/client'

type Source = { id: string; label: string; path: string }

type Props = {
  open: boolean
  sources: Source[]
  initialSourceId?: string
  initialTime?: number
  confirming?: boolean
  onClose: () => void
  /** User confirmed a timestamp; parent should ffmpeg-extract that frame */
  onConfirm: (payload: { videoPath: string; sourceId: string; timeSec: number }) => void
}

/** Slideshow-style frame picker: scrub video, step frames, confirm → ffmpeg. */
export function CoverFramePickerModal({
  open,
  sources,
  initialSourceId,
  initialTime = 0.5,
  confirming = false,
  onClose,
  onConfirm,
}: Props) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [sourceId, setSourceId] = useState(initialSourceId || sources[0]?.id || '')
  const [timeSec, setTimeSec] = useState(initialTime)
  const [duration, setDuration] = useState(0)
  const [paused, setPaused] = useState(true)

  const source = sources.find((s) => s.id === sourceId) || sources[0] || null
  const videoSrc = source?.path ? mediaUrl(source.path) : null

  useEffect(() => {
    if (!open) return
    setSourceId(initialSourceId || sources[0]?.id || '')
    setTimeSec(initialTime)
    setPaused(true)
  }, [open, initialSourceId, initialTime, sources])

  useEffect(() => {
    if (!open) return
    const v = videoRef.current
    if (!v) return
    v.pause()
    setPaused(true)
    const t = Math.max(0, timeSec)
    const apply = () => {
      try {
        if (Number.isFinite(v.duration) && v.duration > 0) {
          v.currentTime = Math.min(t, Math.max(0, v.duration - 0.05))
        } else {
          v.currentTime = t
        }
      } catch {
        /* ignore seek errors while loading */
      }
    }
    if (v.readyState >= 1) apply()
    else v.addEventListener('loadedmetadata', apply, { once: true })
  }, [open, sourceId, videoSrc]) // eslint-disable-line react-hooks/exhaustive-deps -- seek on source change only

  if (!open) return null

  const seekTo = (t: number) => {
    const v = videoRef.current
    const dur = duration || v?.duration || 0
    const next = Math.max(0, Math.min(dur > 0 ? dur - 0.04 : t, t))
    setTimeSec(next)
    if (v) {
      try {
        v.currentTime = next
      } catch {
        /* ignore */
      }
      v.pause()
      setPaused(true)
    }
  }

  const step = (delta: number) => seekTo(timeSec + delta)

  return (
    <div
      className="fixed inset-0 z-[70] flex items-center justify-center bg-black/60 p-4 backdrop-blur-[2px]"
      onClick={onClose}
      role="presentation"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="cover-frame-picker-title"
        onClick={(e) => e.stopPropagation()}
        className="flex max-h-[92vh] w-full max-w-lg flex-col overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--panel)] shadow-2xl"
      >
        <div className="flex shrink-0 items-center justify-between border-b border-[var(--border)] px-4 py-3">
          <h3 id="cover-frame-picker-title" className="text-sm font-semibold text-[var(--text)]">
            选封面帧 · 幻灯片预览
          </h3>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-[var(--border)] px-2.5 py-1 text-xs text-[var(--muted)] hover:bg-[var(--bg)]"
          >
            取消
          </button>
        </div>

        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
          {sources.length > 1 && (
            <div className="flex flex-wrap gap-1.5">
              {sources.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => setSourceId(s.id)}
                  className={`rounded-lg border px-2.5 py-1 text-[11px] ${
                    (source?.id || '') === s.id
                      ? 'border-[var(--select-border)] bg-[var(--select-bg)] text-[var(--accent)]'
                      : 'border-[var(--border)] text-[var(--muted)]'
                  }`}
                >
                  {s.label}
                </button>
              ))}
            </div>
          )}

          <div className="relative mx-auto aspect-[9/16] w-full max-w-[280px] overflow-hidden rounded-xl border border-[var(--border)] bg-black">
            {videoSrc ? (
              <video
                ref={videoRef}
                src={videoSrc}
                className="absolute inset-0 h-full w-full object-contain"
                playsInline
                preload="metadata"
                onLoadedMetadata={(e) => {
                  const v = e.currentTarget
                  setDuration(Number.isFinite(v.duration) ? v.duration : 0)
                  const t = Math.min(Math.max(0, timeSec), Math.max(0, (v.duration || 1) - 0.05))
                  try {
                    v.currentTime = t
                  } catch {
                    /* ignore */
                  }
                }}
                onTimeUpdate={(e) => {
                  if (!paused) setTimeSec(e.currentTarget.currentTime)
                }}
                onSeeked={(e) => setTimeSec(e.currentTarget.currentTime)}
                onPlay={() => setPaused(false)}
                onPause={() => setPaused(true)}
              />
            ) : (
              <div className="flex h-full items-center justify-center text-xs text-[var(--muted)]">
                暂无成片视频
              </div>
            )}
          </div>

          <p className="text-center text-xs text-[var(--muted)]">
            当前时间点 <span className="font-medium text-[var(--text)]">{timeSec.toFixed(2)}s</span>
            {duration > 0 && <span> / {duration.toFixed(1)}s</span>}
          </p>

          <label className="block text-[11px] text-[var(--muted)]">
            拖动预览（像翻幻灯片）
            <input
              type="range"
              min={0}
              max={Math.max(0.1, duration || 60)}
              step={0.05}
              value={Math.min(timeSec, duration || 60)}
              onChange={(e) => seekTo(Number(e.target.value))}
              className="mt-1 w-full"
            />
          </label>

          <div className="flex flex-wrap items-center justify-center gap-2">
            <button
              type="button"
              disabled={!videoSrc}
              onClick={() => step(-1)}
              className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs hover:bg-[var(--bg)] disabled:opacity-40"
            >
              ← 1秒
            </button>
            <button
              type="button"
              disabled={!videoSrc}
              onClick={() => step(-0.2)}
              className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs hover:bg-[var(--bg)] disabled:opacity-40"
            >
              ← 0.2秒
            </button>
            <button
              type="button"
              disabled={!videoSrc}
              onClick={() => {
                const v = videoRef.current
                if (!v) return
                if (v.paused) void v.play()
                else v.pause()
              }}
              className="rounded-lg border border-[var(--select-border)] bg-[var(--select-bg)] px-3 py-1.5 text-xs text-[var(--accent)] disabled:opacity-40"
            >
              {paused ? '播放' : '暂停'}
            </button>
            <button
              type="button"
              disabled={!videoSrc}
              onClick={() => step(0.2)}
              className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs hover:bg-[var(--bg)] disabled:opacity-40"
            >
              0.2秒 →
            </button>
            <button
              type="button"
              disabled={!videoSrc}
              onClick={() => step(1)}
              className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs hover:bg-[var(--bg)] disabled:opacity-40"
            >
              1秒 →
            </button>
          </div>
        </div>

        <div className="flex shrink-0 justify-end gap-2 border-t border-[var(--border)] px-4 py-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs hover:bg-[var(--bg)]"
          >
            取消
          </button>
          <button
            type="button"
            disabled={!source?.path || confirming}
            onClick={() => {
              if (!source?.path) return
              const v = videoRef.current
              const t = v && Number.isFinite(v.currentTime) ? v.currentTime : timeSec
              onConfirm({ videoPath: source.path, sourceId: source.id, timeSec: Math.max(0, t) })
            }}
            className="rounded-lg btn-primary px-3 py-1.5 text-xs font-medium disabled:opacity-50"
          >
            {confirming ? '截取中…' : '确认此帧并截取'}
          </button>
        </div>
      </div>
    </div>
  )
}

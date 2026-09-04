import { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'

type Props = {
  open: boolean
  src: string
  title?: string
  /** Continue from this time when opening (seconds). */
  startAt?: number
  onClose: () => void
}

/**
 * Fills the app window (Electron/browser chrome), not OS/monitor fullscreen.
 * Esc / 关闭 exits; native video fullscreen button is still available if wanted.
 */
export function InAppVideoTheater({ open, src, title, startAt = 0, onClose }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null)

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  useEffect(() => {
    if (!open) return
    const el = videoRef.current
    if (!el) return
    const apply = () => {
      if (startAt > 0 && Number.isFinite(startAt)) {
        try {
          el.currentTime = startAt
        } catch {
          /* ignore */
        }
      }
      void el.play().catch(() => {})
    }
    if (el.readyState >= 1) apply()
    else el.addEventListener('loadedmetadata', apply, { once: true })
  }, [open, src, startAt])

  if (!open || !src) return null

  return createPortal(
    <div
      className="fixed inset-0 z-[90] flex flex-col bg-black"
      role="dialog"
      aria-modal="true"
      aria-label={title || '视频预览'}
    >
      <div className="flex shrink-0 items-center justify-between gap-3 border-b border-white/10 bg-black/90 px-4 py-2">
        <p className="min-w-0 truncate text-sm text-white/90">{title || '应用内全屏预览'}</p>
        <div className="flex shrink-0 items-center gap-2">
          <span className="hidden text-[10px] text-white/45 sm:inline">Esc 退出 · 铺满软件窗口</span>
          <button
            type="button"
            className="rounded-lg border border-white/25 bg-white/10 px-3 py-1.5 text-xs text-white hover:bg-white/20"
            onClick={onClose}
          >
            退出全屏
          </button>
        </div>
      </div>
      <div className="relative min-h-0 flex-1 bg-black">
        <video
          ref={videoRef}
          key={src}
          src={src}
          controls
          playsInline
          preload="auto"
          className="absolute inset-0 h-full w-full object-contain"
        />
      </div>
    </div>,
    document.body,
  )
}

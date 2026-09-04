import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { playableUrl } from '../api/client'

let sharedAudio: HTMLAudioElement | null = null
let sharedOwner: symbol | null = null

type Props = {
  url: string | null | undefined
  /** Absolute disk path — desktop plays via agent-media (no HTTP). */
  localPath?: string | null
  size?: 'sm' | 'md'
  className?: string
  title?: string
}

function isInstantAudioUrl(url: string) {
  return url.startsWith('data:') || url.startsWith('blob:') || url.startsWith('agent-media:')
}

export function AudioPreviewButton({
  url,
  localPath,
  size = 'sm',
  className = '',
  title = '试听',
}: Props) {
  const owner = useRef(Symbol('preview'))
  const [playing, setPlaying] = useState(false)
  const [missing, setMissing] = useState(false)
  const resolved = useMemo(() => playableUrl(url, { localPath }), [url, localPath])

  useEffect(() => {
    return () => {
      if (sharedOwner === owner.current && sharedAudio) {
        sharedAudio.pause()
        sharedOwner = null
      }
    }
  }, [])

  useEffect(() => {
    if (sharedOwner === owner.current && sharedAudio) {
      sharedAudio.pause()
      sharedOwner = null
    }
    setPlaying(false)
    setMissing(false)
  }, [resolved])

  const stopSelf = useCallback(() => {
    if (sharedOwner === owner.current && sharedAudio) {
      sharedAudio.pause()
      sharedOwner = null
    }
    setPlaying(false)
  }, [])

  const toggle = useCallback(
    async (e: React.MouseEvent) => {
      e.stopPropagation()
      e.preventDefault()
      if (!resolved || missing) return

      if (playing) {
        stopSelf()
        return
      }

      if (sharedAudio && sharedOwner !== owner.current) {
        sharedAudio.pause()
      }

      const audio = new Audio()
      sharedAudio?.pause()
      sharedAudio = audio
      sharedOwner = owner.current
      audio.preload = isInstantAudioUrl(resolved) ? 'auto' : 'metadata'

      audio.onended = () => setPlaying(false)
      audio.onpause = () => {
        if (sharedOwner === owner.current) setPlaying(false)
      }
      audio.onerror = () => {
        setMissing(true)
        setPlaying(false)
      }

      audio.src = resolved
      try {
        const p = audio.play()
        setPlaying(true)
        setMissing(false)
        await p
      } catch {
        setMissing(true)
        setPlaying(false)
      }
    },
    [resolved, missing, playing, stopSelf],
  )

  const dim = !resolved || missing
  const pad = size === 'md' ? 'h-9 w-9 text-base' : 'h-7 w-7 text-xs'

  return (
    <button
      type="button"
      title={dim ? '暂无试听' : title}
      disabled={dim}
      onClick={toggle}
      className={`inline-flex shrink-0 items-center justify-center rounded-full border transition ${
        dim
          ? 'cursor-not-allowed border-[var(--border)] text-[var(--muted)] opacity-40'
          : playing
            ? 'border-[var(--accent)] bg-[var(--select-bg)] text-[var(--accent)] shadow-[0_0_12px_var(--select-shadow)]'
            : 'border-[var(--border)] bg-[var(--panel)] text-[var(--accent)] hover:border-[var(--accent)] hover:bg-[var(--select-bg)]'
      } ${pad} ${className}`}
    >
      {playing ? '⏸' : '▶'}
    </button>
  )
}

export function formatAudioDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00'
  const s = Math.floor(seconds)
  const m = Math.floor(s / 60)
  const r = s % 60
  if (m >= 60) {
    const h = Math.floor(m / 60)
    return `${h}:${String(m % 60).padStart(2, '0')}:${String(r).padStart(2, '0')}`
  }
  return `${m}:${String(r).padStart(2, '0')}`
}

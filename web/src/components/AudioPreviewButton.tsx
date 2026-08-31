import { useCallback, useEffect, useRef, useState } from 'react'

let sharedAudio: HTMLAudioElement | null = null
let sharedOwner: symbol | null = null

type Props = {
  url: string | null | undefined
  size?: 'sm' | 'md'
  className?: string
  title?: string
}

export function AudioPreviewButton({ url, size = 'sm', className = '', title = '试听' }: Props) {
  const owner = useRef(Symbol('preview'))
  const [playing, setPlaying] = useState(false)
  const [missing, setMissing] = useState(false)

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
  }, [url])

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
      if (!url || missing) return

      if (playing) {
        stopSelf()
        return
      }

      if (sharedAudio && sharedOwner !== owner.current) {
        sharedAudio.pause()
      }

      const audio = sharedAudio ?? new Audio()
      sharedAudio = audio
      sharedOwner = owner.current

      audio.onended = () => setPlaying(false)
      audio.onpause = () => {
        if (sharedOwner === owner.current) setPlaying(false)
      }
      audio.onerror = () => {
        setMissing(true)
        setPlaying(false)
      }

      audio.src = url
      try {
        await audio.play()
        setPlaying(true)
        setMissing(false)
      } catch {
        setMissing(true)
        setPlaying(false)
      }
    },
    [url, missing, playing, stopSelf],
  )

  const dim = !url || missing
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

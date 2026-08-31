import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { APP_NAME } from '../brand'

type GpuLive = {
  name: string
  util_percent: number
  vram_used_gb: number
  vram_total_gb: number
  vram_percent: number
  temp_c?: number | null
}

type LiveStats = {
  source: string
  cpu_percent: number
  ram_used_gb: number
  ram_total_gb: number
  ram_percent: number
  gpus: GpuLive[]
  cuda_available: boolean
  timestamp_ms: number
}

function barClass(pct: number) {
  if (pct >= 90) return 'bg-red-500'
  if (pct >= 75) return 'bg-amber-500'
  return 'bg-[var(--accent)]'
}

function MetricBar({ label, pct, detail }: { label: string; pct: number; detail: string }) {
  const p = Math.max(0, Math.min(100, pct))
  return (
    <div className="flex min-w-[140px] flex-1 items-center gap-2">
      <span className="w-10 shrink-0 text-[10px] text-[var(--muted)]">{label}</span>
      <div className="h-1.5 min-w-[48px] flex-1 overflow-hidden rounded-full bg-[var(--bg)]">
        <div className={`h-full rounded-full transition-all duration-500 ${barClass(p)}`} style={{ width: `${Math.max(4, p)}%` }} />
      </div>
      <span className="shrink-0 text-[10px] tabular-nums text-[var(--text)]">{detail}</span>
    </div>
  )
}

export function ResourceFooter() {
  const [stats, setStats] = useState<LiveStats | null>(null)
  const [error, setError] = useState(false)
  const [editionLabel, setEditionLabel] = useState('')
  const [builtWithDuix, setBuiltWithDuix] = useState(false)

  useEffect(() => {
    let alive = true
    const tick = async () => {
      try {
        const s = await api.systemStats()
        if (alive) {
          setStats(s)
          setError(false)
        }
      } catch {
        if (alive) setError(true)
      }
    }
    void tick()
    const id = window.setInterval(() => void tick(), 2000)
    return () => {
      alive = false
      window.clearInterval(id)
    }
  }, [])

  useEffect(() => {
    api
      .getEdition()
      .then((e) => {
        setEditionLabel(e.label || '')
        setBuiltWithDuix(!!e.built_with_duix)
      })
      .catch(() => {
        setEditionLabel('')
        setBuiltWithDuix(false)
      })
  }, [])

  const gpu = stats?.gpus?.[0]
  const source = stats?.source === 'rust' ? 'Rust' : stats?.source === 'python' ? 'Python' : '—'

  return (
    <footer className="shrink-0 border-t border-[var(--border)] bg-[var(--panel)] px-4 py-2">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <span className="text-[10px] font-semibold tracking-wide text-[var(--muted)]">本机资源</span>
        {error && !stats ? (
          <span className="text-[10px] text-[var(--warn-text)]">资源探测不可用</span>
        ) : stats ? (
          <>
            <MetricBar label="CPU" pct={stats.cpu_percent} detail={`${stats.cpu_percent.toFixed(0)}%`} />
            <MetricBar
              label="内存"
              pct={stats.ram_percent}
              detail={`${stats.ram_used_gb}/${stats.ram_total_gb}G`}
            />
            {gpu ? (
              <MetricBar
                label="GPU"
                pct={gpu.util_percent}
                detail={`${gpu.util_percent}% · VRAM ${gpu.vram_used_gb}/${gpu.vram_total_gb}G${gpu.temp_c != null ? ` · ${gpu.temp_c}°C` : ''}`}
              />
            ) : (
              <span className="text-[10px] text-[var(--muted)]">无 NVIDIA GPU</span>
            )}
          </>
        ) : (
          <span className="text-[10px] text-[var(--muted)]">探测中…</span>
        )}
        <span className="ml-auto flex flex-wrap items-center gap-x-3 text-[10px] text-[var(--muted)]">
          <span>{APP_NAME}</span>
          {editionLabel && <span>{editionLabel}</span>}
          {builtWithDuix && <span>Built with DUIX.COM</span>}
          <span>
            {source} · 2s 刷新
          </span>
        </span>
      </div>
    </footer>
  )
}

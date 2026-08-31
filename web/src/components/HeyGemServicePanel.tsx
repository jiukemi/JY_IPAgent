import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import { AlertModal, parseApiError } from './AlertModal'
import { HeyGemInstallWizard } from './HeyGemInstallWizard'

type HeygemStatus = {
  ready: boolean
  state: string
  api: string
  docker_available: boolean
  duix_present: boolean
  component_installed?: boolean
  can_start?: boolean
  hint: string
  note: string
  runtime: string
  gpu_ok?: boolean
  cuda_available?: boolean
  max_vram_gb?: number
  min_vram_gb?: number
  gpu_hint?: string
}

type Props = {
  onReadyChange?: (ready: boolean) => void
}

export function HeyGemServicePanel({ onReadyChange }: Props) {
  const [status, setStatus] = useState<HeygemStatus | null>(null)
  const [starting, setStarting] = useState(false)
  const [stopping, setStopping] = useState(false)
  const [startLog, setStartLog] = useState<string[]>([])
  const [startPct, setStartPct] = useState(0)
  const [showWizard, setShowWizard] = useState(true)
  const [alert, setAlert] = useState<{
    title: string
    message: string
    variant: 'error' | 'success' | 'info' | 'warning'
  } | null>(null)

  const refresh = useCallback(async () => {
    try {
      const s = await api.heygemStatus()
      setStatus(s)
      onReadyChange?.(s.ready)
      if (!s.ready) setShowWizard(true)
    } catch {
      setStatus(null)
      onReadyChange?.(false)
    }
  }, [onReadyChange])

  useEffect(() => {
    void refresh()
    const t = window.setInterval(() => void refresh(), 8000)
    return () => window.clearInterval(t)
  }, [refresh])

  const start = async () => {
    if (!status?.cuda_available && !status?.ready) {
      setAlert({
        title: '本机无法运行口播引擎',
        message:
          status?.gpu_hint ||
          '未检测到 NVIDIA 独显。口播需要 GPU；可用文案与云端配音等其他功能。',
        variant: 'warning',
      })
      return
    }
    setStarting(true)
    setStartLog([])
    setStartPct(0.02)
    try {
      const result = await api.heygemStartStream({
        onLog: (line) => setStartLog((prev) => [...prev.slice(-60), line]),
        onProgress: (p, msg) => {
          setStartPct(p)
          if (msg) setStartLog((prev) => [...prev.slice(-60), msg])
        },
      })
      await refresh()
      if (result.ready) {
        setAlert({ title: '口播引擎已启动', message: '服务就绪，可以生成口播视频。', variant: 'success' })
      } else if (result.error) {
        setAlert({
          title: result.exit_code !== 0 ? '启动失败' : '启动未完成',
          message: result.error + (result.hint ? `\n\n${result.hint}` : ''),
          variant: result.exit_code !== 0 ? 'error' : 'warning',
        })
      } else {
        setAlert({
          title: '启动未完成',
          message: '8383 尚未响应。请打开上方「口播引擎安装向导」完成 Docker 与加速包步骤。',
          variant: 'warning',
        })
      }
    } catch (e) {
      const { title, message } = parseApiError(e, '启动失败')
      setAlert({ title, message, variant: 'error' })
    } finally {
      setStarting(false)
    }
  }

  const stop = async () => {
    setStopping(true)
    try {
      const res = await api.heygemStop()
      await refresh()
      setAlert({ title: '已停止', message: res.message, variant: 'info' })
    } catch (e) {
      const { title, message } = parseApiError(e, '停止失败')
      setAlert({ title, message, variant: 'error' })
    } finally {
      setStopping(false)
    }
  }

  const badge =
    status?.ready === true
      ? { text: '已就绪', cls: 'text-emerald-600 border-emerald-500/40 bg-emerald-500/10' }
      : status?.state === 'docker_engine_down' || status?.state === 'need_docker'
        ? { text: '需启动 Docker', cls: 'text-amber-700 border-amber-500/40 bg-amber-500/10' }
        : status?.state === 'need_component'
          ? { text: '待完成安装向导', cls: 'text-amber-700 border-amber-500/40 bg-amber-500/10' }
          : status?.duix_present || status?.component_installed
            ? { text: '已下载未启动', cls: 'text-sky-700 border-sky-500/40 bg-sky-500/10' }
            : { text: '未运行', cls: 'text-[var(--warn-text)] border-[var(--warn-text)]/30 bg-amber-500/5' }

  const canStart =
    status?.can_start !== false &&
    (status?.docker_available || status?.component_installed || Boolean(status?.ready))

  return (
    <>
      {(showWizard || !status?.ready) && (
        <HeyGemInstallWizard
          onReadyChange={(ready) => {
            onReadyChange?.(ready)
            if (ready) void refresh()
          }}
        />
      )}
      <div className="mt-3 rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <p className="text-xs font-semibold text-[var(--text)]">口播引擎（Duix.HeyGem）</p>
            <p className="mt-0.5 text-[10px] text-[var(--muted)]">
              本机服务 · {status?.api || '8383'}
              {status?.runtime ? ` · ${status.runtime}` : ''}
            </p>
          </div>
          <span className={`rounded-full border px-2 py-0.5 text-[10px] font-medium ${badge.cls}`}>{badge.text}</span>
        </div>

        <p className="mt-2 text-[10px] leading-relaxed text-[var(--muted)]">
          新手请先完成上方安装向导（Docker → 夸克包 → 加载启动）。开发机若已就绪可直接启动。
        </p>

        {status?.gpu_hint && !status.ready && (
          <div className="mt-2 rounded-lg border border-amber-400/50 bg-amber-50 px-2.5 py-2 text-[11px] text-amber-950 dark:border-amber-500/40 dark:bg-amber-950/40 dark:text-amber-100">
            {status.gpu_hint}
          </div>
        )}

        {status?.hint && <p className="mt-2 text-[11px] text-[var(--muted)]">{status.hint}</p>}

        <div className="mt-3 flex flex-wrap gap-2">
          {!status?.ready && (
            <button
              type="button"
              disabled={starting || !canStart}
              onClick={() => void start()}
              className="btn-primary rounded-lg px-4 py-2 text-xs font-semibold disabled:opacity-40"
            >
              {starting ? `启动中 ${Math.round(startPct * 100)}%…` : '一键启动口播引擎'}
            </button>
          )}
          {status?.ready && (
            <button
              type="button"
              disabled={stopping}
              onClick={() => void stop()}
              className="rounded-lg border border-[var(--border)] px-3 py-2 text-xs hover:bg-[var(--panel)]"
            >
              {stopping ? '停止中…' : '停止引擎'}
            </button>
          )}
          {!showWizard && (
            <button
              type="button"
              onClick={() => setShowWizard(true)}
              className="rounded-lg border border-[var(--border)] px-3 py-2 text-xs hover:bg-[var(--panel)]"
            >
              打开安装向导
            </button>
          )}
          <button
            type="button"
            onClick={() => void refresh()}
            className="rounded-lg border border-[var(--border)] px-3 py-2 text-xs hover:bg-[var(--panel)]"
          >
            刷新状态
          </button>
        </div>

        {starting && (
          <div className="mt-3">
            <div className="mb-1 flex justify-between text-[10px] text-[var(--muted)]">
              <span>启动口播引擎…</span>
              <span>{Math.round(startPct * 100)}%</span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-[var(--panel)]">
              <div
                className="h-full rounded-full bg-[var(--accent)] transition-all"
                style={{ width: `${Math.max(4, startPct * 100)}%` }}
              />
            </div>
            {startLog.length > 0 && (
              <pre className="mt-2 max-h-28 overflow-auto rounded-lg bg-[var(--panel)] p-2 text-[10px] text-[var(--muted)]">
                {startLog.join('\n')}
              </pre>
            )}
          </div>
        )}
      </div>
      {alert && (
        <AlertModal
          open
          title={alert.title}
          message={alert.message}
          variant={alert.variant}
          onClose={() => setAlert(null)}
        />
      )}
    </>
  )
}

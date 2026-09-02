import { useEffect, useState } from 'react'
import { api, type UpdateCheckResult, type UpdateRelease } from '../api/client'

type DesktopBridge = {
  isDesktop?: boolean
  downloadUpdate?: (release: UpdateRelease) => Promise<{ ok: boolean; message?: string; path?: string }>
  openReleasePage?: (url: string) => Promise<{ ok: boolean }>
  onUpdateProgress?: (cb: (p: { pct: number }) => void) => () => void
  appVersion?: () => Promise<{ version: string }>
}

function desktop(): DesktopBridge | null {
  return (window as unknown as { agentDesktop?: DesktopBridge }).agentDesktop || null
}

type Props = {
  /** Startup: silently check and prompt when newer. */
  autoCheck?: boolean
  /** Settings「检查更新」: force open the dialog. */
  forceOpen?: boolean
  onClose?: () => void
}

export function UpdateModal({ autoCheck = true, forceOpen = false, onClose }: Props) {
  const [info, setInfo] = useState<UpdateCheckResult | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [pct, setPct] = useState(0)
  const [dismissed, setDismissed] = useState(false)
  const [manualOpen, setManualOpen] = useState(false)

  const load = async () => {
    setError('')
    try {
      const res = await api.checkUpdates()
      setInfo(res)
      return res
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      return null
    }
  }

  useEffect(() => {
    if (!autoCheck) return
    const t = window.setTimeout(() => void load(), 2500)
    return () => window.clearTimeout(t)
  }, [autoCheck])

  useEffect(() => {
    if (!forceOpen) return
    setDismissed(false)
    setManualOpen(true)
    void load()
  }, [forceOpen])

  useEffect(() => {
    const d = desktop()
    if (!d?.onUpdateProgress) return
    return d.onUpdateProgress((p) => setPct(Math.max(0, Math.min(1, Number(p?.pct) || 0))))
  }, [])

  const open = manualOpen || (!dismissed && !!info?.update_available)

  if (!open) return null

  const latest = info?.latest
  const mirrors = info?.mirrors || []
  const current = info?.current_version || '—'

  const close = () => {
    setDismissed(true)
    setManualOpen(false)
    onClose?.()
  }

  const download = async (release: UpdateRelease) => {
    setBusy(true)
    setPct(0)
    setError('')
    try {
      const d = desktop()
      if (d?.downloadUpdate) {
        const res = await d.downloadUpdate(release)
        if (!res.ok) throw new Error(res.message || '下载失败')
        return
      }
      window.open(release.download_url, '_blank', 'noopener')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--panel)] p-5 shadow-xl">
        <p className="text-sm font-semibold text-[var(--text)]">
          {info?.update_available ? '发现新版本' : '检查更新'}
        </p>
        <p className="mt-2 text-xs leading-relaxed text-[var(--muted)]">
          当前版本 <span className="text-[var(--text)]">{current}</span>
          {latest?.version ? (
            <>
              {' '}
              · 最新 <span className="font-medium text-[var(--accent)]">{latest.version}</span>
            </>
          ) : null}
          {info && !info.update_available && !error ? (
            <span className="mt-1 block text-emerald-500">已是最新版本</span>
          ) : null}
        </p>
        {latest?.notes && info?.update_available ? (
          <pre className="mt-3 max-h-36 overflow-auto whitespace-pre-wrap rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3 text-[11px] text-[var(--muted)]">
            {latest.notes}
          </pre>
        ) : null}
        {error ? <p className="mt-3 text-xs text-red-500">{error}</p> : null}
        {busy ? (
          <div className="mt-4">
            <div className="h-2 overflow-hidden rounded-full bg-[var(--bg)]">
              <div
                className="h-full rounded-full bg-[var(--accent)] transition-[width]"
                style={{ width: `${Math.round(pct * 100)}%` }}
              />
            </div>
            <p className="mt-2 text-[11px] text-[var(--muted)]">
              正在下载安装包… {Math.round(pct * 100)}%（完成后将启动安装程序）
            </p>
          </div>
        ) : null}
        <div className="mt-4 flex flex-wrap gap-2">
          {info?.update_available &&
            mirrors.map((m) => (
              <button
                key={m.source}
                type="button"
                disabled={busy || !m.download_url}
                onClick={() => void download(m)}
                className="rounded-lg bg-[var(--accent)] px-3 py-2 text-xs font-semibold text-white disabled:opacity-50"
              >
                {m.source === 'gitee' ? 'Gitee 下载更新' : 'GitHub 下载更新'}
              </button>
            ))}
          <button
            type="button"
            disabled={busy}
            onClick={() => void load()}
            className="rounded-lg border border-[var(--border)] px-3 py-2 text-xs"
          >
            重新检查
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={close}
            className="rounded-lg border border-[var(--border)] px-3 py-2 text-xs text-[var(--muted)]"
          >
            {info?.update_available ? '稍后' : '关闭'}
          </button>
        </div>
      </div>
    </div>
  )
}

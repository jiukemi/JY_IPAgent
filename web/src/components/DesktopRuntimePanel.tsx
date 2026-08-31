import { useEffect, useState } from 'react'

type RuntimeInfo = {
  path: string
  exists: boolean
  sizeBytes: number
  hasVenv?: boolean
  hasEmbed?: boolean
  hasLog?: boolean
  hasConfig?: boolean
}

type DesktopBridge = {
  isDesktop?: boolean
  runtimeInfo?: () => Promise<RuntimeInfo>
  clearRuntimeAndRelaunch?: () => Promise<{ ok: boolean; message?: string; relaunching?: boolean }>
}

function getDesktop(): DesktopBridge | null {
  const w = window as unknown as { agentDesktop?: DesktopBridge }
  return w.agentDesktop?.isDesktop ? w.agentDesktop : null
}

function fmtSize(n: number) {
  if (!n || n < 1024) return `${n || 0} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`
  return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`
}

/** Desktop-only: detect / one-click clear AppData runtime and relaunch. */
export function DesktopRuntimePanel() {
  const desktop = getDesktop()
  const [info, setInfo] = useState<RuntimeInfo | null>(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  const refresh = async () => {
    if (!desktop?.runtimeInfo) return
    try {
      setInfo(await desktop.runtimeInfo())
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e))
    }
  }

  useEffect(() => {
    void refresh()
  }, [])

  if (!desktop?.runtimeInfo) return null

  const flags = [
    info?.hasVenv ? 'venv' : null,
    info?.hasEmbed ? 'portable-python' : null,
    info?.hasConfig ? 'config' : null,
    info?.hasLog ? 'log' : null,
  ].filter(Boolean)

  return (
    <div className="space-y-2 rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-medium text-[var(--text)]">桌面运行时</p>
          <p className="mt-0.5 text-xs text-[var(--muted)]">
            {info
              ? info.exists
                ? `已检测到 · ${fmtSize(info.sizeBytes)}${flags.length ? ` · ${flags.join(' · ')}` : ''}`
                : '未检测到运行时目录（下次启动会自动创建）'
              : '检测中…'}
          </p>
          {info?.path && (
            <p className="mt-1 break-all font-mono text-[10px] text-[var(--muted)]">{info.path}</p>
          )}
        </div>
        <div className="flex shrink-0 gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={() => void refresh()}
            className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs"
          >
            刷新
          </button>
          <button
            type="button"
            disabled={busy || !info?.exists}
            onClick={async () => {
              if (!desktop.clearRuntimeAndRelaunch) return
              const ok = window.confirm(
                '将清除本机运行时（Python 环境 / 缓存），并自动重启软件重新准备。\n\n确定继续？',
              )
              if (!ok) return
              setBusy(true)
              setMsg('正在清除并重启…')
              try {
                const res = await desktop.clearRuntimeAndRelaunch()
                if (!res?.ok) {
                  setMsg(res?.message || '清除失败')
                  setBusy(false)
                  return
                }
                setMsg(res.message || '已清除，正在重启…')
              } catch (e) {
                setMsg(e instanceof Error ? e.message : String(e))
                setBusy(false)
              }
            }}
            className="rounded-lg bg-[var(--accent)] px-3 py-1.5 text-xs font-semibold text-[var(--accent-contrast)] disabled:opacity-50"
          >
            {busy ? '处理中…' : '一键清除并重启'}
          </button>
        </div>
      </div>
      {msg && <p className="text-xs text-[var(--muted)]">{msg}</p>}
    </div>
  )
}

import { useEffect, useState } from 'react'

type RuntimeInfo = {
  path: string
  exists: boolean
  sizeBytes: number
  hasVenv?: boolean
  hasEmbed?: boolean
  hasLog?: boolean
  hasConfig?: boolean
  source?: string
  installDrive?: string
  preferredOnInstallDrive?: string
  freeBytes?: number | null
}

type DriveInfo = {
  letter: string
  root: string
  freeBytes: number | null
  label: string
}

type DesktopBridge = {
  isDesktop?: boolean
  runtimeInfo?: () => Promise<RuntimeInfo>
  clearRuntimeAndRelaunch?: () => Promise<{ ok: boolean; message?: string; relaunching?: boolean }>
  exportDiagnostics?: () => Promise<{ ok: boolean; path?: string; message?: string; cancelled?: boolean }>
  listDrives?: () => Promise<{ drives: DriveInfo[]; current: RuntimeInfo; installDrive: string }>
  setRuntimeDriveAndRelaunch?: (
    driveLetter: string,
  ) => Promise<{ ok: boolean; path?: string; message?: string; relaunching?: boolean }>
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

/** Desktop-only: runtime path / drive pick / clear / diagnostic zip. */
export function DesktopRuntimePanel() {
  const desktop = getDesktop()
  const [info, setInfo] = useState<RuntimeInfo | null>(null)
  const [drives, setDrives] = useState<DriveInfo[]>([])
  const [pick, setPick] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  const refresh = async () => {
    if (!desktop?.runtimeInfo) return
    try {
      const rt = await desktop.runtimeInfo()
      setInfo(rt)
      if (desktop.listDrives) {
        const listed = await desktop.listDrives()
        setDrives(listed.drives || [])
        const curDrive = (rt.path || '').slice(0, 2).toUpperCase()
        setPick(curDrive.match(/^[A-Z]:$/) ? curDrive : 'APPDATA')
      }
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
    <div className="space-y-3 rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-medium text-[var(--text)]">桌面运行时</p>
          <p className="mt-0.5 text-xs text-[var(--muted)]">
            {info
              ? info.exists
                ? `已检测到 · ${fmtSize(info.sizeBytes)}${flags.length ? ` · ${flags.join(' · ')}` : ''}`
                : '未检测到运行时目录（下次启动会自动创建）'
              : '检测中…'}
            {typeof info?.freeBytes === 'number' ? ` · 所在盘剩余 ${fmtSize(info.freeBytes)}` : ''}
          </p>
          {info?.path && (
            <p className="mt-1 break-all font-mono text-[10px] text-[var(--muted)]">{info.path}</p>
          )}
          {info?.installDrive && (
            <p className="mt-1 text-[10px] text-[var(--muted)]">
              安装盘 {info.installDrive} · 默认可写到 {info.preferredOnInstallDrive}
            </p>
          )}
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
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
            disabled={busy || !desktop.exportDiagnostics}
            onClick={async () => {
              if (!desktop.exportDiagnostics) return
              setBusy(true)
              setMsg('正在打包诊断信息…')
              try {
                const res = await desktop.exportDiagnostics()
                setMsg(res?.cancelled ? '已取消' : res?.message || (res?.ok ? '已导出' : '导出失败'))
              } catch (e) {
                setMsg(e instanceof Error ? e.message : String(e))
              } finally {
                setBusy(false)
              }
            }}
            className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs"
          >
            导出诊断包
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

      {drives.length > 0 && desktop.setRuntimeDriveAndRelaunch && (
        <div className="rounded-lg border border-[var(--border)] bg-[var(--panel)] px-2.5 py-2">
          <p className="text-xs font-medium text-[var(--text)]">运行时磁盘（C 盘满时可改到安装盘）</p>
          <p className="mt-0.5 text-[10px] text-[var(--muted)]">
            新用户默认跟安装盘走。已有环境不会自动搬家；换盘后建议「清除并重启」在新位置重建。
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <select
              value={pick}
              onChange={(e) => setPick(e.target.value)}
              className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-2 py-1 text-xs"
            >
              <option value="APPDATA">用户目录（通常 C 盘 AppData）</option>
              {drives.map((d) => (
                <option key={d.letter} value={d.letter}>
                  {d.letter} {typeof d.freeBytes === 'number' ? `剩余 ${fmtSize(d.freeBytes)}` : ''}
                </option>
              ))}
            </select>
            <button
              type="button"
              disabled={busy || !pick}
              onClick={async () => {
                const ok = window.confirm(
                  `将运行时切换到「${pick === 'APPDATA' ? '用户目录' : pick}」并重启。\n旧目录不会自动删除。\n\n确定？`,
                )
                if (!ok) return
                setBusy(true)
                setMsg('正在切换磁盘并重启…')
                try {
                  const res = await desktop.setRuntimeDriveAndRelaunch?.(pick)
                  if (!res?.ok) {
                    setMsg(res?.message || '切换失败')
                    setBusy(false)
                    return
                  }
                  setMsg(res.message || '已切换，正在重启…')
                } catch (e) {
                  setMsg(e instanceof Error ? e.message : String(e))
                  setBusy(false)
                }
              }}
              className="rounded-lg border border-[var(--select-border)] bg-[var(--select-bg)] px-2.5 py-1 text-xs text-[var(--accent)] disabled:opacity-50"
            >
              切换并重启
            </button>
          </div>
        </div>
      )}

      {msg && <p className="text-xs text-[var(--muted)]">{msg}</p>}
    </div>
  )
}

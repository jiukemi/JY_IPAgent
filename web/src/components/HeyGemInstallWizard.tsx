import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import { FileDropZone } from './FileDropZone'
import { AlertModal, parseApiError } from './AlertModal'

type WizardStep = { id: number; title: string; done: boolean; detail: string }

type WizardState = {
  machine?: { gpu_family: string; label: string; hint?: string; heygem_image?: string }
  heygem?: {
    ready?: boolean
    state?: string
    hint?: string
    docker_available?: boolean
    docker_cli?: boolean
    gpu_hint?: string
  }
  recommended_pack?: {
    id: string
    name: string
    share_url?: string
    share_extract_code?: string
    zip_name?: string
    note?: string
    approx_size_gb?: number
    gpu_family?: string
  } | null
  share_root_url?: string
  share_extract_code?: string
  steps: WizardStep[]
  current_step: number
  docker_product_url?: string
  tars?: Array<{ family: string; name: string; path: string; bytes: number }>
  image_loaded?: boolean
  can_load?: boolean
  general_pack_ops_note?: string
}

type Props = {
  onReadyChange?: (ready: boolean) => void
  compact?: boolean
}

export function HeyGemInstallWizard({ onReadyChange, compact }: Props) {
  const [wiz, setWiz] = useState<WizardState | null>(null)
  const [busy, setBusy] = useState('')
  const [log, setLog] = useState<string[]>([])
  const [force, setForce] = useState(false)
  const [localPath, setLocalPath] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [open, setOpen] = useState(true)
  const [alert, setAlert] = useState<{
    title: string
    message: string
    variant: 'error' | 'success' | 'info' | 'warning'
  } | null>(null)

  const refresh = useCallback(async () => {
    try {
      const s = await api.heygemWizard()
      setWiz(s)
      onReadyChange?.(!!s.heygem?.ready)
    } catch (e) {
      setLog((prev) => [...prev.slice(-40), e instanceof Error ? e.message : String(e)])
    }
  }, [onReadyChange])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const push = (line: string) => setLog((prev) => [...prev.slice(-50), line])

  const openDocker = async () => {
    setBusy('打开下载页')
    try {
      const r = await api.heygemWizardOpenDocker()
      push(r.message)
      setAlert({ title: 'Docker Desktop', message: r.message, variant: 'info' })
    } catch (e) {
      const { title, message } = parseApiError(e, '打开失败')
      setAlert({ title, message, variant: 'error' })
    } finally {
      setBusy('')
    }
  }

  const launchDocker = async () => {
    setBusy('启动 Docker')
    try {
      const r = await api.heygemWizardLaunchDocker()
      push(r.message)
      setAlert({
        title: r.ok ? '已尝试启动' : '未找到安装',
        message: r.message,
        variant: r.ok ? 'info' : 'warning',
      })
      window.setTimeout(() => void refresh(), 3000)
    } catch (e) {
      const { title, message } = parseApiError(e, '启动失败')
      setAlert({ title, message, variant: 'error' })
    } finally {
      setBusy('')
    }
  }

  const installPack = async (mode: 'scan' | 'path' | 'upload') => {
    setBusy(mode === 'scan' ? '扫描安装' : mode === 'path' ? '路径安装' : '上传安装')
    try {
      let res: { ok: boolean; message?: string; post_install_hint?: string; docker_load?: { ok?: boolean; message?: string } }
      if (mode === 'scan') res = await api.quarkInstall({ force })
      else if (mode === 'path') {
        if (!localPath.trim()) {
          setAlert({ title: '缺少路径', message: '请填写本机 zip 完整路径', variant: 'warning' })
          return
        }
        res = await api.quarkInstall({ path: localPath.trim(), force })
      } else {
        if (!file) {
          setAlert({ title: '未选择文件', message: '请拖入或选择加速包 zip', variant: 'warning' })
          return
        }
        res = await api.quarkUpload(file, force)
      }
      const parts = [res.message || '', res.post_install_hint || '', res.docker_load?.message || ''].filter(Boolean)
      push(parts.join('\n'))
      setAlert({
        title: res.ok ? '加速包已安装' : '安装失败',
        message: parts.join('\n\n') || '完成',
        variant: res.ok ? 'success' : 'error',
      })
      await refresh()
    } catch (e) {
      const { title, message } = parseApiError(e, '安装失败')
      setAlert({ title, message, variant: 'error' })
    } finally {
      setBusy('')
    }
  }

  const loadImage = async () => {
    setBusy('加载镜像')
    try {
      const r = await api.heygemWizardLoadImage({
        family: wiz?.machine?.gpu_family,
      })
      push(r.message)
      setAlert({
        title: r.ok ? '镜像就绪' : '加载失败',
        message: r.message,
        variant: r.ok ? 'success' : 'error',
      })
      await refresh()
    } catch (e) {
      const { title, message } = parseApiError(e, '加载失败')
      setAlert({ title, message, variant: 'error' })
    } finally {
      setBusy('')
    }
  }

  const startEngine = async () => {
    setBusy('启动口播')
    try {
      if (!wiz?.image_loaded && wiz?.can_load) {
        const load = await api.heygemWizardLoadImage({ family: wiz?.machine?.gpu_family })
        push(load.message)
        if (!load.ok) {
          setAlert({ title: '请先加载镜像', message: load.message, variant: 'warning' })
          return
        }
      }
      const result = await api.heygemStartStream({
        onLog: (line) => push(line),
      })
      await refresh()
      if (result.ready) {
        setAlert({ title: '口播引擎已就绪', message: '可以生成口播视频了。', variant: 'success' })
      } else {
        setAlert({
          title: '启动未完成',
          message: (result.error || '') + (result.hint ? `\n\n${result.hint}` : ''),
          variant: 'warning',
        })
      }
    } catch (e) {
      const { title, message } = parseApiError(e, '启动失败')
      setAlert({ title, message, variant: 'error' })
    } finally {
      setBusy('')
    }
  }

  if (!wiz) {
    return (
      <div className="mt-3 rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3 text-[11px] text-[var(--muted)]">
        正在加载口播安装向导…
      </div>
    )
  }

  const pack = wiz.recommended_pack
  const ready = !!wiz.heygem?.ready
  const step = wiz.current_step

  return (
    <>
      <div className={`mt-3 rounded-xl border border-[var(--border)] bg-[var(--bg)] ${compact ? 'p-2.5' : 'p-3'}`}>
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <p className="text-xs font-semibold text-[var(--text)]">口播引擎安装向导</p>
            <p className="mt-0.5 text-[10px] text-[var(--muted)]">
              安装包保持小体积；大镜像用夸克包按需下载。按步骤完成即可，无需手敲命令。
            </p>
          </div>
          <div className="flex items-center gap-2">
            <span
              className={`rounded-full border px-2 py-0.5 text-[10px] font-medium ${
                ready
                  ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-700'
                  : 'border-amber-500/40 bg-amber-500/10 text-amber-800'
              }`}
            >
              {ready ? '已就绪' : `进行到第 ${step} 步`}
            </span>
            <button
              type="button"
              className="text-[10px] text-[var(--muted)] underline"
              onClick={() => setOpen((v) => !v)}
            >
              {open ? '收起' : '展开'}
            </button>
          </div>
        </div>

        {!open ? null : (
          <>
            <ol className="mt-3 space-y-2">
              {wiz.steps.map((s) => (
                <li
                  key={s.id}
                  className={`rounded-lg border px-2.5 py-2 text-[11px] ${
                    s.done
                      ? 'border-emerald-500/30 bg-emerald-500/5'
                      : s.id === step
                        ? 'border-[var(--accent)]/40 bg-[var(--accent)]/5'
                        : 'border-[var(--border)]'
                  }`}
                >
                  <div className="flex items-center gap-2 font-medium text-[var(--text)]">
                    <span className="tabular-nums text-[var(--muted)]">{s.done ? '✓' : s.id}</span>
                    {s.title}
                  </div>
                  <p className="mt-0.5 text-[10px] text-[var(--muted)]">{s.detail}</p>
                </li>
              ))}
            </ol>

            {wiz.heygem?.gpu_hint && !ready && (
              <p className="mt-2 rounded-lg border border-amber-400/40 bg-amber-50 px-2.5 py-2 text-[11px] text-amber-950 dark:bg-amber-950/30 dark:text-amber-100">
                {wiz.heygem.gpu_hint}
              </p>
            )}

            {/* Step 2 actions */}
            {!wiz.steps[1]?.done && (
              <div className="mt-3 space-y-2 rounded-lg border border-[var(--border)] p-2.5">
                <p className="text-[11px] font-medium text-[var(--text)]">② Docker Desktop</p>
                <p className="text-[10px] text-[var(--muted)]">
                  需管理员安装，完成后可能要重启。装好后打开 Docker，托盘图标正常再继续。本地 load
                  镜像一般不必注册 Docker Hub。
                </p>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    disabled={!!busy}
                    onClick={() => void openDocker()}
                    className="btn-primary rounded-lg px-3 py-1.5 text-xs font-semibold disabled:opacity-40"
                  >
                    打开官网下载
                  </button>
                  <button
                    type="button"
                    disabled={!!busy}
                    onClick={() => void launchDocker()}
                    className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs hover:bg-[var(--panel)] disabled:opacity-40"
                  >
                    启动已安装的 Docker
                  </button>
                  <button
                    type="button"
                    disabled={!!busy}
                    onClick={() => void refresh()}
                    className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs hover:bg-[var(--panel)]"
                  >
                    重新检测
                  </button>
                </div>
              </div>
            )}

            {/* Step 3 actions */}
            {wiz.steps[1]?.done && !wiz.steps[2]?.done && (
              <div className="mt-3 space-y-2 rounded-lg border border-[var(--border)] p-2.5">
                <p className="text-[11px] font-medium text-[var(--text)]">③ 安装加速包</p>
                <p className="text-[10px] leading-relaxed text-[var(--muted)]">
                  本机推荐：<strong className="text-[var(--text)]">{pack?.name || '对应显卡包'}</strong>
                  {pack?.approx_size_gb ? `（约 ${pack.approx_size_gb} GB）` : ''}
                  。请用夸克下载后扫描 / 拖入，勿下错「通用 / RTX50」。
                </p>
                {pack?.share_url ? (
                  <a
                    href={pack.share_url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-block text-[11px] font-medium text-[var(--accent)] underline"
                  >
                    打开本机推荐包的夸克分享
                  </a>
                ) : (
                  <p className="text-[10px] text-amber-800 dark:text-amber-200">
                    推荐包尚未填写 share_url。请让运营在 data/quark/catalog.json 填入夸克链接；或使用已下载的
                    zip 拖入下方。
                    {wiz.machine?.gpu_family === 'general' && wiz.general_pack_ops_note
                      ? ` ${wiz.general_pack_ops_note}`
                      : ''}
                  </p>
                )}
                {(pack?.share_extract_code || wiz.share_extract_code) ? (
                  <p className="text-[10px] text-[var(--muted)]">
                    提取码：
                    <span className="font-mono text-[var(--text)]">
                      {pack?.share_extract_code || wiz.share_extract_code}
                    </span>
                    （只下载本机推荐的那个 zip）
                  </p>
                ) : null}
                {wiz.share_root_url && (
                  <a
                    href={wiz.share_root_url}
                    target="_blank"
                    rel="noreferrer"
                    className="block text-[10px] text-[var(--muted)] underline"
                  >
                    夸克总入口
                  </a>
                )}
                <label className="flex items-center gap-2 text-[10px] text-[var(--muted)]">
                  <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} />
                  强制安装（显卡不匹配时慎用）
                </label>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    disabled={!!busy}
                    onClick={() => void installPack('scan')}
                    className="btn-primary rounded-lg px-3 py-1.5 text-xs font-semibold disabled:opacity-40"
                  >
                    扫描下载目录并安装
                  </button>
                </div>
                <div className="flex flex-wrap gap-2">
                  <input
                    value={localPath}
                    onChange={(e) => setLocalPath(e.target.value)}
                    placeholder="或粘贴 zip 完整路径"
                    className="min-w-[12rem] flex-1 rounded border border-[var(--border)] bg-[var(--panel)] px-2 py-1 text-[11px]"
                  />
                  <button
                    type="button"
                    disabled={!!busy}
                    onClick={() => void installPack('path')}
                    className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs disabled:opacity-40"
                  >
                    按路径安装
                  </button>
                </div>
                <FileDropZone
                  file={file}
                  onFile={setFile}
                  accept=".zip,application/zip"
                  emptyTitle="拖入加速包 zip"
                  emptyHint="或点击选择 · 装好后校验 MANIFEST 与显卡"
                  chooseLabel="选择 zip"
                />
                <button
                  type="button"
                  disabled={!!busy || !file}
                  onClick={() => void installPack('upload')}
                  className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs disabled:opacity-40"
                >
                  安装拖入的 zip
                </button>
              </div>
            )}

            {/* Step 4 */}
            {wiz.steps[2]?.done && !ready && (
              <div className="mt-3 space-y-2 rounded-lg border border-[var(--border)] p-2.5">
                <p className="text-[11px] font-medium text-[var(--text)]">④ 加载镜像并启动</p>
                <p className="text-[10px] text-[var(--muted)]">
                  {wiz.image_loaded
                    ? '本地已有对应 Docker 镜像，可直接启动。'
                    : wiz.tars?.length
                      ? `将加载：${wiz.tars.map((t) => t.name).join('、')}`
                      : '未找到 tar，请回到上一步安装加速包。'}
                </p>
                <div className="flex flex-wrap gap-2">
                  {!wiz.image_loaded && (
                    <button
                      type="button"
                      disabled={!!busy || !wiz.can_load}
                      onClick={() => void loadImage()}
                      className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs disabled:opacity-40"
                    >
                      加载镜像（docker load）
                    </button>
                  )}
                  <button
                    type="button"
                    disabled={!!busy}
                    onClick={() => void startEngine()}
                    className="btn-primary rounded-lg px-3 py-1.5 text-xs font-semibold disabled:opacity-40"
                  >
                    {busy === '启动口播' ? '启动中…' : '一键启动口播引擎'}
                  </button>
                  <button
                    type="button"
                    disabled={!!busy}
                    onClick={() => void refresh()}
                    className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs"
                  >
                    刷新
                  </button>
                </div>
              </div>
            )}

            {ready && (
              <p className="mt-3 text-[11px] text-emerald-700 dark:text-emerald-300">
                口播引擎已就绪。可在本页生成视频；需要停用时用下方「停止引擎」。
              </p>
            )}

            {busy && <p className="mt-2 text-[10px] text-[var(--muted)]">进行中：{busy}…</p>}
            {log.length > 0 && (
              <pre className="mt-2 max-h-28 overflow-auto rounded-lg bg-[var(--panel)] p-2 text-[10px] text-[var(--muted)]">
                {log.join('\n')}
              </pre>
            )}
          </>
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

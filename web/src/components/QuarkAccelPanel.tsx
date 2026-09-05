import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import { FileDropZone } from './FileDropZone'

type Pack = {
  id: string
  name: string
  pack_kind: string
  gpu_family: string
  approx_size_gb?: number
  share_url?: string
  share_extract_code?: string
  zip_name?: string
  note?: string
  docker_image?: string
  recommended?: boolean
  matches_machine?: boolean
  match_message?: string
}

export function QuarkAccelPanel() {
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState('')
  const [message, setMessage] = useState('')
  const [force, setForce] = useState(false)
  const [localPath, setLocalPath] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [machine, setMachine] = useState<{
    gpu_family: string
    label: string
    hint: string
    heygem_image: string
    summary?: string
  } | null>(null)
  const [packs, setPacks] = useState<Pack[]>([])
  const [portalNote, setPortalNote] = useState('')
  const [shareRoot, setShareRoot] = useState('')
  const [shareCode, setShareCode] = useState('')
  const [candidates, setCandidates] = useState<
    Array<{ path: string; bytes: number; bundle_name?: string; gpu_family?: string; pack_id?: string }>
  >([])
  const [installed, setInstalled] = useState<Record<string, unknown> | null>(null)
  const pathHintRef = useRef<HTMLInputElement>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const cat = await api.quarkCatalog()
      setMachine(cat.machine)
      setPacks(cat.packs || [])
      setPortalNote(cat.portal_note || '')
      setShareRoot(cat.share_root_url || '')
      setShareCode(cat.share_extract_code || '')
      setInstalled((cat.installed as Record<string, unknown>) || null)
      const scan = await api.quarkScan()
      setCandidates(scan.candidates || [])
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const showResult = (res: {
    ok: boolean
    message?: string
    gpu_mismatch?: boolean
    hint?: string
    post_install_hint?: string
  }) => {
    const parts = [res.message || (res.ok ? '完成' : '失败')]
    if (res.hint) parts.push(res.hint)
    if (res.post_install_hint) parts.push(res.post_install_hint)
    setMessage(parts.join('\n'))
    if (res.ok) void refresh()
  }

  const scanInstall = async () => {
    setBusy('扫描安装')
    setMessage('')
    try {
      showResult(await api.quarkInstall({ force }))
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy('')
    }
  }

  const installPath = async () => {
    const p = localPath.trim()
    if (!p) {
      setMessage('请填写本机 zip 完整路径，例如 C:\\Users\\你\\Downloads\\九易AI-加速包-….zip')
      return
    }
    setBusy('路径安装')
    setMessage('')
    try {
      showResult(await api.quarkInstall({ path: p, force }))
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy('')
    }
  }

  const installUpload = async () => {
    if (!file) {
      setMessage('请先拖入或选择加速包 zip')
      return
    }
    setBusy('上传安装')
    setMessage('')
    try {
      showResult(await api.quarkUpload(file, force))
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy('')
    }
  }

  const gpuPacks = packs.filter((p) => p.pack_kind === 'gpu')
  const uniPacks = packs.filter((p) => p.pack_kind !== 'gpu')

  return (
    <div className="space-y-3 rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-xs font-semibold text-[var(--text)]">网盘加速线 · 夸克包</p>
          <p className="mt-0.5 text-[10px] leading-relaxed text-[var(--muted)]">
            {portalNote ||
              '无外网时：夸克下载加速包 → 扫描 / 填路径 / 拖入 zip。口播引擎按显卡分「通用」与「RTX50」两包，勿下错。'}
          </p>
        </div>
        <button
          type="button"
          disabled={loading || !!busy}
          onClick={() => void refresh()}
          className="rounded border border-[var(--border)] px-2 py-1 text-[10px] hover:bg-[var(--panel)] disabled:opacity-40"
        >
          {loading ? '刷新中…' : '刷新'}
        </button>
      </div>

      {machine && (
        <div className="rounded-lg border border-[var(--info-border)] bg-[var(--info-bg)] px-3 py-2 text-[11px] text-[var(--info-text)]">
          <p className="font-medium">本机推荐：{machine.label}</p>
          <p className="mt-0.5 opacity-90">{machine.hint}</p>
          {machine.summary && (
            <p className="mt-0.5 text-[10px] opacity-80">
              {machine.summary} · 镜像 {machine.heygem_image}
            </p>
          )}
        </div>
      )}

      {shareRoot && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px]">
          <a
            href={shareRoot}
            target="_blank"
            rel="noreferrer"
            className="text-[var(--accent)] underline"
          >
            打开夸克分享入口
          </a>
          {shareCode ? (
            <span className="text-[var(--muted)]">
              提取码 <span className="font-mono text-[var(--text)]">{shareCode}</span>
            </span>
          ) : null}
        </div>
      )}

      <div className="space-y-2">
        <p className="text-[10px] font-semibold uppercase tracking-wide text-[var(--muted)]">
          按显卡区分（必看）
        </p>
        {gpuPacks.map((p) => (
          <div
            key={p.id}
            className={`rounded-lg border px-2.5 py-2 text-[11px] ${
              p.recommended
                ? 'border-emerald-500/40 bg-emerald-500/5'
                : 'border-[var(--border)] opacity-80'
            }`}
          >
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium text-[var(--text)]">{p.name}</span>
              {p.recommended && (
                <span className="rounded bg-emerald-500/20 px-1.5 text-[9px] text-emerald-700">
                  本机推荐
                </span>
              )}
              <span className="text-[10px] text-[var(--muted)]">
                ≈{p.approx_size_gb ?? '?'} GB · {p.gpu_family}
              </span>
            </div>
            {p.note && <p className="mt-1 text-[10px] text-[var(--muted)]">{p.note}</p>}
            {p.share_url ? (
              <a
                href={p.share_url}
                target="_blank"
                rel="noreferrer"
                className="mt-1 inline-block text-[10px] text-[var(--accent)] underline"
              >
                夸克下载
                {p.share_extract_code ? `（提取码 ${p.share_extract_code}）` : ''}
              </a>
            ) : (
              <p className="mt-1 text-[10px] text-amber-700/90">
                分享链接未配置（运营填 data/quark/catalog.json）
              </p>
            )}
          </div>
        ))}
      </div>

      <div className="space-y-2">
        <p className="text-[10px] font-semibold uppercase tracking-wide text-[var(--muted)]">
          通用（与显卡无关）
        </p>
        {uniPacks.map((p) => (
          <div key={p.id} className="rounded-lg border border-[var(--border)] px-2.5 py-2 text-[11px]">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium">{p.name}</span>
              <span className="text-[10px] text-[var(--muted)]">≈{p.approx_size_gb ?? '?'} GB</span>
            </div>
            {p.note && <p className="mt-1 text-[10px] text-[var(--muted)]">{p.note}</p>}
            {p.share_url ? (
              <a
                href={p.share_url}
                target="_blank"
                rel="noreferrer"
                className="mt-1 inline-block text-[10px] text-[var(--accent)] underline"
              >
                夸克下载
                {p.share_extract_code ? `（提取码 ${p.share_extract_code}）` : ''}
              </a>
            ) : (
              <p className="mt-1 text-[10px] text-[var(--muted)]">分享链接未配置</p>
            )}
          </div>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          disabled={!!busy}
          onClick={() => void scanInstall()}
          className="btn-primary rounded-lg px-3 py-1.5 text-xs font-medium disabled:opacity-40"
        >
          {busy === '扫描安装' ? '安装中…' : '扫描下载目录并安装'}
        </button>
        <label className="flex items-center gap-1.5 text-[10px] text-[var(--muted)]">
          <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} />
          强制安装（忽略显卡不匹配警告）
        </label>
      </div>

      {candidates.length > 0 && (
        <div className="rounded-lg border border-dashed border-[var(--border)] p-2 text-[10px] text-[var(--muted)]">
          <p className="mb-1 font-medium text-[var(--text)]">已扫描到 {candidates.length} 个包</p>
          <ul className="max-h-24 space-y-1 overflow-auto">
            {candidates.map((c) => (
              <li key={c.path}>
                <button
                  type="button"
                  className="text-left text-[var(--accent)] underline"
                  onClick={() => setLocalPath(c.path)}
                >
                  {(c.bundle_name || c.pack_id || '包') +
                    (c.gpu_family ? ` · ${c.gpu_family}` : '')}
                </button>
                <span className="ml-1 opacity-70">
                  ({Math.round((c.bytes || 0) / (1024 * 1024))} MB)
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="space-y-1.5">
        <p className="text-[10px] font-medium text-[var(--muted)]">本机路径安装</p>
        <div className="flex flex-wrap gap-2">
          <input
            ref={pathHintRef}
            value={localPath}
            onChange={(e) => setLocalPath(e.target.value)}
            placeholder="粘贴 zip 完整路径…"
            className="min-w-[12rem] flex-1 rounded border border-[var(--border)] bg-[var(--panel)] px-2 py-1.5 text-xs"
          />
          <button
            type="button"
            disabled={!!busy || !localPath.trim()}
            onClick={() => void installPath()}
            className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs hover:bg-[var(--panel)] disabled:opacity-40"
          >
            {busy === '路径安装' ? '安装中…' : '按路径安装'}
          </button>
        </div>
      </div>

      <div className="space-y-1.5">
        <p className="text-[10px] font-medium text-[var(--muted)]">拖入 / 选择 zip（浏览器上传）</p>
        <FileDropZone
          file={file}
          onFile={setFile}
          accept=".zip,application/zip"
          emptyTitle="拖入加速包 zip"
          emptyHint="或点击选择 · 装好后会校验 MANIFEST 与显卡类型"
          chooseLabel="选择 zip"
        />
        <button
          type="button"
          disabled={!!busy || !file}
          onClick={() => void installUpload()}
          className="rounded-lg border border-[var(--accent)] px-3 py-1.5 text-xs text-[var(--accent)] hover:bg-[var(--select-bg)] disabled:opacity-40"
        >
          {busy === '上传安装' ? '上传安装中…' : '上传并安装'}
        </button>
      </div>

      {installed && (
        <p className="text-[10px] text-[var(--muted)]">
          上次安装：
          {String(installed.bundle_name || installed.pack_id || '已安装')}
          {installed.gpu_family ? ` · ${String(installed.gpu_family)}` : ''}
        </p>
      )}

      {message && (
        <pre className="whitespace-pre-wrap rounded-lg border border-[var(--border)] bg-[var(--panel)] px-2.5 py-2 text-[11px] text-[var(--text)]">
          {message}
        </pre>
      )}
    </div>
  )
}

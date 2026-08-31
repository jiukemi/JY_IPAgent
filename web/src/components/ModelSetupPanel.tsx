import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import { useJobQueue } from '../context/JobQueueContext'
import { AlertModal, parseApiError } from './AlertModal'

export type EngineSetupStatus = {
  engine: string
  label: string
  hardware: string
  summary: string
  setup_script: string | null
  min_vram_gb: number
  compatible: boolean
  recommended?: boolean
  recommend_role?: string
  recommend_reason?: string
  match_label?: string
  match_hint?: string
  package_size_gb?: number
  host_vram_gb?: number
  installed: boolean
  ready: boolean
  preset_ready?: boolean
  missing: string[]
  missing_preset?: string[]
  usage_rules: string[]
  mirrors?: { hf: string; pypi: string; github: string[] }
}

type Props = {
  currentEngine?: string
  onRefresh?: () => void
  /** When true, panel starts expanded (e.g. deep-link from header). */
  defaultOpen?: boolean
}

export function ModelSetupPanel({ currentEngine, onRefresh, defaultOpen = false }: Props) {
  const jobQueue = useJobQueue()
  const [hardware, setHardware] = useState<{
    summary?: string
    max_vram_gb?: number
    ram_gb?: number
    source?: string
  } | null>(null)
  const [engines, setEngines] = useState<EngineSetupStatus[]>([])
  const [recommend, setRecommend] = useState<{
    asr?: string
    tts?: string
    avatar?: string
    summary?: string
    source?: string
    max_vram_gb?: number
  } | null>(null)
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(defaultOpen)
  const [alert, setAlert] = useState<{
    title: string
    message: string
    variant: 'error' | 'success' | 'info'
  } | null>(null)

  useEffect(() => {
    if (defaultOpen) setOpen(true)
  }, [defaultOpen])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await api.setupEngines()
      setHardware(res.hardware)
      setEngines(res.engines)
      setRecommend(res.recommend || null)
    } catch {
      setEngines([])
      setRecommend(null)
    } finally {
      setLoading(false)
    }
  }, [])

  // Only probe when panel is expanded (or deep-linked open) — avoids blocking Settings open.
  useEffect(() => {
    if (!open) return
    void load()
  }, [open, load])

  // Auto-refresh engine status when install jobs finish
  useEffect(() => {
    const fin = jobQueue.lastFinished
    if (!fin || fin.type !== 'engine_install') return
    void load().then(() => onRefresh?.())
    if (fin.status === 'done') {
      const ready = fin.result?.ready !== false
      setAlert({
        title: ready ? '安装完成' : '安装已结束',
        message: ready
          ? `「${fin.title}」已完成，设置中的引擎状态已更新。`
          : `「${fin.title}」脚本已跑完，但引擎尚未完全就绪。请到任务中心查看日志。`,
        variant: ready ? 'success' : 'info',
      })
    } else if (fin.status === 'failed') {
      setAlert({
        title: '安装失败',
        message: fin.error || fin.message || '请到任务中心查看错误日志',
        variant: 'error',
      })
    }
  }, [jobQueue.completionTick, jobQueue.lastFinished, load, onRefresh])

  const activeInstallEngines = new Set(
    jobQueue.jobs
      .filter((j) => j.type === 'engine_install' && (j.status === 'queued' || j.status === 'running'))
      .map((j) => String(j.payload?.engine || '').toLowerCase())
      .filter(Boolean),
  )

  const runInstall = async (engine: string) => {
    const st = engines.find((e) => e.engine === engine)
    if (st && !st.compatible) {
      const why =
        st.missing?.length > 0
          ? st.missing
              .slice(0, 3)
              .map((m) => `· ${m}`)
              .join('\n')
          : `建议显存 ≥ ${st.min_vram_gb}GB`
      setAlert({
        title: '本机暂不支持该引擎',
        message: `「${st.label}」需要更高配置。\n\n${why}\n\n低配机请改用：云端 Qwen3-TTS，或本机 Piper（几乎无显存要求）。`,
        variant: 'error',
      })
      return
    }
    if (activeInstallEngines.has(engine.toLowerCase())) {
      setAlert({
        title: '已在任务中心',
        message: `「${st?.label || engine}」正在下载/安装中，请到顶部「任务中心」查看进度与日志，请勿重复点击。`,
        variant: 'info',
      })
      jobQueue.setCenterOpen(true)
      return
    }
    try {
      const outcome = await jobQueue.enqueue({
        type: 'engine_install',
        title: `安装 ${st?.label || engine}`,
        force: true,
        priority: 20,
        payload: { engine },
      })
      if (!outcome.ok) {
        setAlert({
          title: '已加入或重复',
          message: `${outcome.message}\n\n请到任务中心查看记录。`,
          variant: 'info',
        })
      }
    } catch (e) {
      const { title, message } = parseApiError(e, '无法加入任务中心')
      setAlert({ title, message, variant: 'error' })
    }
  }

  const badge = (st: EngineSetupStatus) => {
    if (activeInstallEngines.has(st.engine.toLowerCase())) {
      return { text: '安装中', cls: 'bg-sky-500/15 text-sky-800 dark:text-sky-200' }
    }
    if (st.ready && st.preset_ready !== false) {
      return { text: '就绪', cls: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300' }
    }
    if (st.ready) {
      return { text: '克隆可用', cls: 'bg-sky-500/15 text-sky-800 dark:text-sky-200' }
    }
    if (st.installed && st.engine === 'heygem') {
      return { text: '已下载未启动', cls: 'bg-sky-500/15 text-sky-800 dark:text-sky-200' }
    }
    if (st.installed) return { text: '需修复', cls: 'bg-amber-500/15 text-amber-800 dark:text-amber-200' }
    if (!st.compatible) return { text: '配置不足', cls: 'bg-red-500/15 text-red-800 dark:text-red-200' }
    if (st.recommended) return { text: '推荐安装', cls: 'bg-violet-500/15 text-violet-800 dark:text-violet-200' }
    return { text: '未安装', cls: 'bg-[var(--badge-bg)] text-[var(--badge-text)]' }
  }

  const installRecommended = async () => {
    const targets = engines.filter((e) => e.recommended && !e.ready && e.setup_script)
    if (!targets.length) {
      setAlert({
        title: '无需安装',
        message: '推荐引擎均已就绪，或本机暂无可推荐项。',
        variant: 'info',
      })
      return
    }
    for (const st of targets) {
      await runInstall(st.engine)
    }
  }

  return (
    <>
      <div className="rounded-xl border border-[var(--border)] bg-[var(--bg)]">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="flex w-full items-center justify-between px-3 py-2.5 text-left text-xs"
        >
          <span>
            <span className="font-medium text-[var(--text)]">本机配置与模型安装</span>
            {hardware?.summary && (
              <span className="ml-2 text-[var(--muted)]">
                {hardware.summary}
                {hardware.source === 'rust' && ' · Rust 探测'}
              </span>
            )}
          </span>
          <span className="text-[var(--muted)]">{open ? '收起 ▲' : '展开 ▼'}</span>
        </button>

        {open && (
          <div className="space-y-2 border-t border-[var(--border)] p-3">
            <p className="text-[10px] text-[var(--muted)]">
              根据本机硬件（优先 Rust 探测）推荐转写 / 配音 / 口播引擎；点击安装会加入任务中心。
            </p>
            {recommend?.summary && (
              <div className="rounded-lg border border-violet-400/40 bg-violet-50 px-3 py-2 text-[11px] text-violet-950 dark:border-violet-500/30 dark:bg-violet-950/30 dark:text-violet-100">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <p className="font-medium">为本机推荐</p>
                    <p className="mt-0.5 leading-relaxed">{recommend.summary}</p>
                    {hardware?.source === 'rust' && (
                      <p className="mt-0.5 text-[10px] opacity-80">检测来源：Rust hw_probe</p>
                    )}
                  </div>
                  <button
                    type="button"
                    disabled={loading}
                    onClick={() => void installRecommended()}
                    className="shrink-0 rounded-lg border border-violet-500/40 bg-violet-500/15 px-2.5 py-1 text-[11px] font-medium text-violet-800 hover:bg-violet-500/25 disabled:opacity-50 dark:text-violet-200"
                  >
                    一键装推荐
                  </button>
                </div>
              </div>
            )}
            {hardware && (hardware.max_vram_gb ?? 0) < 6 && (
              <div className="rounded-lg border border-amber-400/50 bg-amber-50 px-3 py-2 text-[11px] text-amber-950 dark:border-amber-500/40 dark:bg-amber-950/40 dark:text-amber-100">
                <p className="font-medium">低配提示</p>
                <p className="mt-0.5 leading-relaxed">
                  {hardware.summary || '本机显存偏低或无独显'}。本地 IndexTTS / CosyVoice /
                  口播引擎可能无法安装或运行；请优先用云端配音，或安装 Piper。
                </p>
              </div>
            )}
            {loading ? (
              <p className="text-xs text-[var(--muted)]">检测中…</p>
            ) : (
              engines.map((st) => {
                const b = badge(st)
                const isCurrent = st.engine === currentEngine
                const installing = activeInstallEngines.has(st.engine.toLowerCase())
                return (
                  <div
                    key={st.engine}
                    className={`rounded-xl border p-3 text-xs ${
                      !st.compatible
                        ? 'border-red-400/40 bg-red-50/80 dark:bg-red-950/20'
                        : st.recommended
                          ? 'border-violet-400/50 bg-violet-50/70 dark:bg-violet-950/20'
                          : isCurrent
                            ? 'border-[var(--accent)] bg-[var(--select-bg)]'
                            : 'border-[var(--border)] bg-[var(--panel)]'
                    }`}
                  >
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div>
                        <span className="font-semibold text-[var(--text)]">{st.label}</span>
                        {isCurrent && <span className="ml-2 text-[var(--accent)]">当前</span>}
                        <span className={`ml-2 rounded-md px-1.5 py-0.5 ${b.cls}`}>{b.text}</span>
                        <span
                          className={`ml-2 rounded-md px-1.5 py-0.5 ${
                            st.recommended
                              ? 'bg-violet-500/15 text-violet-800 dark:text-violet-200'
                              : st.compatible
                                ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300'
                                : 'bg-red-500/15 text-red-800 dark:text-red-200'
                          }`}
                        >
                          {st.match_label || (st.compatible ? '本机匹配' : '本机不匹配')}
                        </span>
                        {typeof st.package_size_gb === 'number' && (
                          <span className="ml-2 text-[10px] text-[var(--muted)]">
                            {st.package_size_gb <= 0 ? '无需下载' : `约 ${st.package_size_gb} GB`}
                          </span>
                        )}
                        <p className="mt-1 text-[var(--muted)]">{st.hardware}</p>
                        {st.match_hint && (
                          <p className="mt-0.5 text-[10px] text-[var(--muted)]">{st.match_hint}</p>
                        )}
                        {st.recommended && st.recommend_reason && (
                          <p className="mt-0.5 text-[10px] text-violet-700 dark:text-violet-300">
                            {st.recommend_reason}
                          </p>
                        )}
                        {!st.compatible && (
                          <p className="mt-1 font-medium text-red-700 dark:text-red-300">
                            本机不支持（需约 {st.min_vram_gb}GB+ 显存）· 请换轻量/云端引擎
                          </p>
                        )}
                      </div>
                      {st.ready && !installing ? (
                        <span className="shrink-0 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-emerald-700 dark:text-emerald-300">
                          已就绪
                        </span>
                      ) : st.setup_script ? (
                        <button
                          type="button"
                          disabled={installing}
                          onClick={() => void runInstall(st.engine)}
                          className={`shrink-0 rounded-lg border px-2.5 py-1 disabled:opacity-50 ${
                            st.compatible
                              ? 'border-[var(--select-border)] bg-[var(--select-bg)] text-[var(--accent)]'
                              : 'border-red-400/40 bg-red-500/10 text-red-700 dark:text-red-300'
                          }`}
                        >
                          {installing
                            ? '任务中心安装中…'
                            : st.compatible
                              ? '一键安装'
                              : '查看不支持原因'}
                        </button>
                      ) : null}
                    </div>
                    {st.missing.length > 0 && (
                      <ul className="mt-2 space-y-1.5">
                        {st.missing
                          .filter((m) => !(st.ready && st.missing_preset?.includes(m)))
                          .map((m) => (
                            <li
                              key={m}
                              className="rounded-lg border border-amber-300/40 bg-amber-50 px-2.5 py-1.5 text-amber-950 dark:border-amber-500/30 dark:bg-amber-950/40 dark:text-amber-100"
                            >
                              {m}
                            </li>
                          ))}
                      </ul>
                    )}
                    {st.usage_rules?.[0] && (
                      <p className="mt-2 text-[var(--muted)]">{st.usage_rules[0]}</p>
                    )}
                  </div>
                )
              })
            )}
          </div>
        )}
      </div>

      <AlertModal
        open={!!alert}
        title={alert?.title || ''}
        message={alert?.message || ''}
        variant={alert?.variant || 'info'}
        onClose={() => setAlert(null)}
      />
    </>
  )
}

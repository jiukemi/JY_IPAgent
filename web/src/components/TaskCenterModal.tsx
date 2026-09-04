import { useState } from 'react'
import type { JobRecord } from '../api/client'
import { useJobQueue } from '../context/JobQueueContext'

function statusLabel(s: string) {
  switch (s) {
    case 'queued':
      return '排队'
    case 'running':
      return '进行中'
    case 'done':
      return '完成'
    case 'failed':
      return '失败'
    case 'cancelled':
      return '已取消'
    default:
      return s
  }
}

function typeLabel(t: string) {
  switch (t) {
    case 'tts_synthesize':
      return '配音'
    case 'avatar_lipsync':
      return '口播'
    case 'publish_run':
      return '成片'
    case 'hyperframe_fill_cues':
      return '时间段场景'
    case 'hyperframe_restyle':
      return '换肤'
    case 'engine_install':
      return '引擎安装'
    case 'script_extract':
      return '文案提取'
    case 'subtitle_asr':
      return '字幕 ASR'
    default:
      return t
  }
}

function formatDuration(sec: number | null | undefined): string | null {
  if (sec == null || !Number.isFinite(sec) || sec < 0) return null
  const s = Math.round(sec)
  if (s < 60) return `${s} 秒`
  const m = Math.floor(s / 60)
  const r = s % 60
  if (m < 60) return r ? `${m} 分 ${r} 秒` : `${m} 分钟`
  const h = Math.floor(m / 60)
  const rm = m % 60
  return rm ? `${h} 小时 ${rm} 分` : `${h} 小时`
}

function formatClock(iso: string | null | undefined): string | null {
  if (!iso) return null
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return iso
    return d.toLocaleString('zh-CN', { hour12: false })
  } catch {
    return iso
  }
}

function jobModel(job: JobRecord): string | null {
  const r = job.result || {}
  const p = job.payload || {}
  const fromResult = r.model ?? r.backend
  const fromPayload = p.model_label ?? p.backend ?? p.engine
  const v = fromResult ?? fromPayload
  return typeof v === 'string' && v.trim() ? v.trim() : null
}

function detailRows(job: JobRecord): { label: string; value: string }[] {
  const r = job.result || {}
  const p = job.payload || {}
  const rows: { label: string; value: string }[] = []
  const model = jobModel(job)
  if (model) rows.push({ label: '模型', value: model })
  if (job.type === 'avatar_lipsync') {
    const q = r.quality ?? p.quality
    if (typeof q === 'string' && q) {
      const qMap: Record<string, string> = { high: '高画质', balanced: '均衡', fast: '快速' }
      rows.push({ label: '画质', value: qMap[q] || q })
    }
    const mode = r.track_mode ?? p.track_mode
    if (mode === 'digital') rows.push({ label: '轨道', value: '数字人口播' })
    else if (mode === 'real') rows.push({ label: '轨道', value: '实拍换嘴' })
    const an = r.avatar_name ?? p.avatar_name
    if (typeof an === 'string' && an) rows.push({ label: '形象', value: an })
  }
  if (job.type === 'tts_synthesize') {
    const speed = r.speed_mode ?? p.speed_mode
    if (typeof speed === 'string' && speed) rows.push({ label: '语速', value: speed })
    const voice = p.voice_uid
    if (typeof voice === 'string' && voice) rows.push({ label: '音色', value: voice })
  }
  if (job.type === 'engine_install') {
    const eng = r.engine ?? p.engine
    if (typeof eng === 'string' && eng) rows.push({ label: '引擎', value: eng })
    if (r.ready === true) rows.push({ label: '状态', value: '已就绪' })
    if (r.ready === false) rows.push({ label: '状态', value: '未完全就绪' })
    const missing = r.missing
    if (Array.isArray(missing) && missing.length) {
      rows.push({ label: '仍缺失', value: missing.map(String).slice(0, 5).join('；') })
    }
    if (typeof r.log === 'string' && r.log.trim()) {
      rows.push({ label: '日志', value: r.log.trim().slice(-1200) })
    }
    if (typeof job.error === 'string' && job.error.trim()) {
      rows.push({ label: '错误', value: job.error.trim().slice(-1200) })
    }
  }
  const dur =
    formatDuration(
      typeof job.duration_sec === 'number'
        ? job.duration_sec
        : typeof r.duration_sec === 'number'
          ? r.duration_sec
          : null,
    ) || null
  if (dur) rows.push({ label: '用时', value: dur })
  const started = formatClock(job.started_at)
  const finished = formatClock(job.finished_at)
  if (started) rows.push({ label: '开始', value: started })
  if (finished) rows.push({ label: '结束', value: finished })
  if (typeof r.audio === 'string' && r.audio) rows.push({ label: '音频', value: r.audio })
  if (typeof r.work_dir === 'string' && r.work_dir) rows.push({ label: '源目录', value: r.work_dir })
  if (typeof r.video_path === 'string' && r.video_path) rows.push({ label: '成片', value: r.video_path })
  if (typeof r.audio_duration === 'number' && r.audio_duration > 0) {
    rows.push({ label: '音频时长', value: formatDuration(r.audio_duration) || `${r.audio_duration}s` })
  }
  return rows
}

function JobRow({
  job,
  onCancel,
  onDelete,
  onPrioritize,
  onRequeue,
}: {
  job: JobRecord
  onCancel: () => void
  onDelete: (deleteSources: boolean) => void
  onPrioritize?: () => void
  onRequeue?: () => void
}) {
  const [open, setOpen] = useState(false)
  const [confirmPurge, setConfirmPurge] = useState(false)
  const pct = Math.round(Math.max(0, Math.min(1, job.progress || 0)) * 100)
  const active = job.status === 'queued' || job.status === 'running'
  const pri = Number(job.priority || 0)
  const details = detailRows(job)
  const showDetails = !active && details.length > 0
  const canPurgeSources =
    !active &&
    (job.type === 'hyperframe_fill_cues' ||
      job.type === 'hyperframe_restyle' ||
      job.type === 'publish_run' ||
      job.type === 'tts_synthesize' ||
      job.type === 'avatar_lipsync')
  // Always allow expanding engine install rows (even while running) to follow live message
  const canExpand = showDetails || job.type === 'engine_install' || !!job.error

  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--panel-2)] p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-sm font-medium text-[var(--text)]">
            <span className="mr-1.5 rounded bg-[var(--panel)] px-1.5 py-0.5 text-[10px] text-[var(--muted)]">
              {typeLabel(job.type)}
            </span>
            {job.title}
            {pri > 0 && job.status === 'queued' && (
              <span className="ml-1.5 text-[10px] text-amber-600">优先</span>
            )}
          </div>
          <div className="mt-0.5 text-xs text-[var(--muted)]">
            {statusLabel(job.status)}
            {job.message ? ` · ${job.message}` : ''}
            {!active && jobModel(job) ? ` · ${jobModel(job)}` : ''}
            {!active &&
            formatDuration(
              typeof job.duration_sec === 'number'
                ? job.duration_sec
                : typeof job.result?.duration_sec === 'number'
                  ? (job.result.duration_sec as number)
                  : null,
            )
              ? ` · ${formatDuration(
                  typeof job.duration_sec === 'number'
                    ? job.duration_sec
                    : (job.result?.duration_sec as number),
                )}`
              : ''}
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap justify-end gap-1">
          {job.status === 'queued' && onPrioritize && (
            <button
              type="button"
              onClick={onPrioritize}
              className="rounded border border-amber-500/40 px-2 py-0.5 text-[11px] text-amber-700 hover:bg-amber-500/10"
            >
              优先
            </button>
          )}
          {(job.status === 'failed' || job.status === 'cancelled') && onRequeue && (
            <button
              type="button"
              onClick={onRequeue}
              className="rounded border border-[var(--accent)]/40 px-2 py-0.5 text-[11px] text-[var(--accent)] hover:bg-[var(--accent)]/10"
            >
              重新排队
            </button>
          )}
          {active && (
            <button
              type="button"
              onClick={onCancel}
              className="rounded border border-red-500/40 px-2 py-0.5 text-[11px] text-red-600 hover:bg-red-500/10"
            >
              取消
            </button>
          )}
          {job.status !== 'running' && !confirmPurge && (
            <button
              type="button"
              onClick={() => (canPurgeSources ? setConfirmPurge(true) : onDelete(false))}
              className="rounded border border-[var(--border)] px-2 py-0.5 text-[11px] text-[var(--muted)] hover:bg-[var(--panel)]"
            >
              删除
            </button>
          )}
        </div>
      </div>
      {confirmPurge && (
        <div className="mt-2 rounded-lg border border-red-500/30 bg-red-500/5 px-2.5 py-2 text-[11px]">
          <p className="text-[var(--text)]">删除任务记录？可同时清除生成的源文件（场景/成片等）。</p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <button
              type="button"
              onClick={() => {
                setConfirmPurge(false)
                onDelete(false)
              }}
              className="rounded border border-[var(--border)] px-2 py-0.5 text-[var(--muted)] hover:bg-[var(--panel)]"
            >
              仅删记录
            </button>
            <button
              type="button"
              onClick={() => {
                setConfirmPurge(false)
                onDelete(true)
              }}
              className="rounded border border-red-500/50 px-2 py-0.5 text-red-600 hover:bg-red-500/10"
            >
              删除并清除源文件
              {job.type === 'avatar_lipsync' ? '（含口播历史）' : ''}
            </button>
            <button
              type="button"
              onClick={() => setConfirmPurge(false)}
              className="rounded px-2 py-0.5 text-[var(--muted)] underline"
            >
              取消
            </button>
          </div>
        </div>
      )}
      {active && (
        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-[var(--panel)]">
          <div
            className="h-full rounded-full bg-[var(--accent)] transition-all duration-300"
            style={{ width: `${Math.max(job.status === 'queued' ? 2 : 3, pct)}%` }}
          />
        </div>
      )}
      {job.error && job.status === 'failed' && (
        <pre className="mt-2 max-h-32 overflow-auto whitespace-pre-wrap break-all text-xs text-red-600">
          {job.error}
        </pre>
      )}
      {canExpand && (
        <div className="mt-2">
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="text-[11px] text-[var(--accent)] underline"
          >
            {open ? '收起详情' : '查看详情 / 日志'}
          </button>
          {open && (
            <dl className="mt-2 space-y-1 rounded-lg bg-[var(--panel)] px-2.5 py-2 text-[11px]">
              {details.length === 0 && job.message && (
                <div className="flex gap-2">
                  <dt className="w-14 shrink-0 text-[var(--muted)]">进度</dt>
                  <dd className="min-w-0 break-all text-[var(--text)]">{job.message}</dd>
                </div>
              )}
              {details.map((row) => (
                <div key={row.label} className="flex gap-2">
                  <dt className="w-14 shrink-0 text-[var(--muted)]">{row.label}</dt>
                  <dd className="min-w-0 whitespace-pre-wrap break-all text-[var(--text)]">{row.value}</dd>
                </div>
              ))}
            </dl>
          )}
        </div>
      )}
      {job.created_at && !open && (
        <p className="mt-1 text-[10px] text-[var(--muted)]">{formatClock(job.created_at)}</p>
      )}
    </div>
  )
}

export function TaskCenterModal() {
  const {
    centerOpen,
    setCenterOpen,
    jobs,
    cancelJob,
    prioritizeJob,
    requeueJob,
    deleteJob,
    clearHistory,
    toast,
    clearToast,
  } = useJobQueue()

  const running = jobs.filter((j) => j.status === 'running')
  const queued = jobs
    .filter((j) => j.status === 'queued')
    .slice()
    .sort(
      (a, b) =>
        (b.priority || 0) - (a.priority || 0) ||
        (a.created_at || '').localeCompare(b.created_at || ''),
    )
  const history = jobs.filter(
    (j) => j.status === 'done' || j.status === 'failed' || j.status === 'cancelled',
  )

  return (
    <>
      {toast && !centerOpen && (
        <button
          type="button"
          onClick={() => {
            clearToast()
            setCenterOpen(true)
          }}
          className="fixed bottom-6 right-6 z-[55] max-w-sm rounded-xl border border-[var(--border)] bg-[var(--panel)] px-4 py-3 text-left text-sm shadow-lg"
        >
          <div className="font-medium text-[var(--text)]">{toast.message}</div>
          <div className="mt-1 text-xs text-[var(--accent)]">打开任务中心</div>
        </button>
      )}

      {centerOpen && (
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 p-4 backdrop-blur-[2px]"
          role="presentation"
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="task-center-title"
            className="flex max-h-[85vh] w-full max-w-lg flex-col rounded-2xl border border-[var(--border)] bg-[var(--panel)] shadow-2xl"
          >
            <div className="flex items-center justify-between border-b border-[var(--border)] px-5 py-3">
              <div>
                <h2 id="task-center-title" className="text-base font-semibold">
                  任务中心
                </h2>
                <p className="text-[10px] text-[var(--muted)]">
                  单 worker 按序执行 · 可点「优先」插队 · 完成后可查看模型与用时
                </p>
              </div>
              <button
                type="button"
                onClick={() => setCenterOpen(false)}
                className="rounded-lg px-2 py-1 text-sm text-[var(--muted)] hover:bg-[var(--panel-2)]"
              >
                关闭
              </button>
            </div>

            {toast && (
              <div className="border-b border-[var(--border)] bg-[var(--select-bg)] px-5 py-2 text-xs text-[var(--accent)]">
                {toast.message}
                <button type="button" className="ml-2 underline" onClick={clearToast}>
                  知道了
                </button>
              </div>
            )}

            <div className="flex-1 space-y-4 overflow-y-auto px-5 py-4">
              <section>
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">
                  进行中 ({running.length})
                </h3>
                {running.length === 0 ? (
                  <p className="text-xs text-[var(--muted)]">暂无</p>
                ) : (
                  <div className="space-y-2">
                    {running.map((j) => (
                      <JobRow
                        key={j.id}
                        job={j}
                        onCancel={() => void cancelJob(j.id)}
                        onDelete={(purge) => void deleteJob(j.id, { deleteSources: purge })}
                      />
                    ))}
                  </div>
                )}
              </section>

              <section>
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">
                  排队 ({queued.length})
                </h3>
                {queued.length === 0 ? (
                  <p className="text-xs text-[var(--muted)]">暂无</p>
                ) : (
                  <div className="space-y-2">
                    {queued.map((j) => (
                      <JobRow
                        key={j.id}
                        job={j}
                        onCancel={() => void cancelJob(j.id)}
                        onDelete={(purge) => void deleteJob(j.id, { deleteSources: purge })}
                        onPrioritize={() => void prioritizeJob(j.id)}
                      />
                    ))}
                  </div>
                )}
              </section>

              <section>
                <div className="mb-2 flex items-center justify-between">
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">
                    历史 ({history.length})
                  </h3>
                  {history.length > 0 && (
                    <button
                      type="button"
                      onClick={() => void clearHistory()}
                      className="text-[11px] text-[var(--muted)] underline hover:text-[var(--text)]"
                    >
                      清空历史
                    </button>
                  )}
                </div>
                {history.length === 0 ? (
                  <p className="text-xs text-[var(--muted)]">暂无</p>
                ) : (
                  <div className="space-y-2">
                    {history.map((j) => (
                      <JobRow
                        key={j.id}
                        job={j}
                        onCancel={() => void cancelJob(j.id)}
                        onDelete={(purge) => void deleteJob(j.id, { deleteSources: purge })}
                        onRequeue={() => void requeueJob(j.id)}
                      />
                    ))}
                  </div>
                )}
              </section>

              <p className="text-[10px] leading-relaxed text-[var(--muted)]">
                断点说明：排队任务在服务重启后会继续；进行中的配音/口播/成片中断后需「重新排队」完整重跑。
              </p>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

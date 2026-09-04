import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { api, type JobRecord } from '../api/client'

type EnqueueInput = {
  type:
    | 'hyperframe_fill_cues'
    | 'hyperframe_restyle'
    | 'publish_run'
    | 'tts_synthesize'
    | 'avatar_lipsync'
    | 'engine_install'
    | 'script_extract'
    | 'subtitle_asr'
  payload: Record<string, unknown>
  title?: string
  force?: boolean
  priority?: number
}

type EnqueueOutcome =
  | { ok: true; job: JobRecord; message: string }
  | { ok: false; duplicate: true; message: string; existing_job_id?: string }

type JobQueueContextValue = {
  jobs: JobRecord[]
  activeCount: number
  centerOpen: boolean
  setCenterOpen: (open: boolean) => void
  toast: { message: string; variant: 'info' | 'success' | 'warning' | 'error' } | null
  clearToast: () => void
  refresh: () => Promise<void>
  enqueue: (input: EnqueueInput) => Promise<EnqueueOutcome>
  cancelJob: (jobId: string) => Promise<void>
  prioritizeJob: (jobId: string) => Promise<void>
  requeueJob: (jobId: string) => Promise<void>
  deleteJob: (jobId: string, opts?: { deleteSources?: boolean }) => Promise<void>
  clearHistory: () => Promise<void>
  completionTick: number
  lastFinished: JobRecord | null
  assignmentsTick: number
}

const JobQueueContext = createContext<JobQueueContextValue | null>(null)

function mergeJobs(a: JobRecord[], b: JobRecord[]): JobRecord[] {
  const map = new Map<string, JobRecord>()
  for (const j of [...a, ...b]) map.set(j.id, j)
  return [...map.values()].sort((x, y) => String(y.created_at || '').localeCompare(String(x.created_at || '')))
}

export function JobQueueProvider({
  sessionPath,
  children,
}: {
  sessionPath: string
  children: ReactNode
}) {
  const [systemPath, setSystemPath] = useState('')
  const [jobs, setJobs] = useState<JobRecord[]>([])
  const [activeCount, setActiveCount] = useState(0)
  const [centerOpen, setCenterOpen] = useState(false)
  const [toast, setToast] = useState<JobQueueContextValue['toast']>(null)
  const [completionTick, setCompletionTick] = useState(0)
  const [lastFinished, setLastFinished] = useState<JobRecord | null>(null)
  const [assignmentsTick, setAssignmentsTick] = useState(0)
  const prevStatusRef = useRef<Record<string, string>>({})

  useEffect(() => {
    void api
      .systemJobsSession()
      .then((r) => setSystemPath(r.path || ''))
      .catch(() => setSystemPath(''))
  }, [])

  const refresh = useCallback(async () => {
    try {
      const lists = await Promise.all([
        sessionPath
          ? api.jobsList(sessionPath).catch(() => ({ jobs: [] as JobRecord[], active_count: 0 }))
          : Promise.resolve({ jobs: [] as JobRecord[], active_count: 0 }),
        systemPath
          ? api.jobsList(systemPath).catch(() => ({ jobs: [] as JobRecord[], active_count: 0 }))
          : Promise.resolve({ jobs: [] as JobRecord[], active_count: 0 }),
      ])
      const next = mergeJobs(lists[0].jobs || [], lists[1].jobs || [])
      const prev = prevStatusRef.current
      for (const j of next) {
        const was = prev[j.id]
        if (
          was &&
          was !== j.status &&
          (j.status === 'done' || j.status === 'failed' || j.status === 'cancelled')
        ) {
          setLastFinished(j)
          setCompletionTick((t) => t + 1)
        }
        prev[j.id] = j.status
      }
      const ids = new Set(next.map((j) => j.id))
      for (const id of Object.keys(prev)) {
        if (!ids.has(id)) delete prev[id]
      }
      setJobs(next)
      setActiveCount(next.filter((j) => j.status === 'queued' || j.status === 'running').length)
    } catch (e) {
      console.error(e)
    }
  }, [sessionPath, systemPath])

  useEffect(() => {
    void refresh()
  }, [refresh])

  useEffect(() => {
    if (!sessionPath && !systemPath) return
    const needPoll = centerOpen || activeCount > 0
    if (!needPoll) return
    const t = window.setInterval(() => void refresh(), 1500)
    return () => window.clearInterval(t)
  }, [sessionPath, systemPath, centerOpen, activeCount, refresh])

  const resolveJobSession = useCallback(
    (jobId: string) => {
      const job = jobs.find((j) => j.id === jobId)
      return job?.session_path || sessionPath || systemPath
    },
    [jobs, sessionPath, systemPath],
  )

  const enqueue = useCallback(
    async (input: EnqueueInput): Promise<EnqueueOutcome> => {
      const targetPath =
        input.type === 'engine_install' ? systemPath || sessionPath : sessionPath
      if (!targetPath) {
        return { ok: false, duplicate: true, message: '请先选择会话（或等待系统任务目录就绪）' }
      }
      const res = await api.jobsEnqueue({
        session_path: targetPath,
        type: input.type,
        payload: {
          ...input.payload,
          session_path: String(input.payload.session_path || targetPath),
        },
        title: input.title,
        force: input.force,
        priority: input.priority,
      })
      if (res.ok && res.job) {
        setToast({
          message: input.type === 'engine_install' ? '引擎安装已加入任务中心' : '已加入任务中心',
          variant: 'success',
        })
        setCenterOpen(true)
        await refresh()
        return { ok: true, job: res.job, message: '已加入任务中心' }
      }
      const msg =
        res.message ||
        (input.type === 'engine_install'
          ? '该引擎已有安装任务在进行中，请到任务中心查看'
          : '当前条件下已有任务')
      setToast({ message: msg, variant: 'warning' })
      setCenterOpen(true)
      await refresh()
      return {
        ok: false,
        duplicate: true,
        message: msg,
        existing_job_id: res.existing_job_id,
      }
    },
    [sessionPath, systemPath, refresh],
  )

  const cancelJob = useCallback(
    async (jobId: string) => {
      const sp = resolveJobSession(jobId)
      if (!sp) return
      await api.jobsCancel(sp, jobId)
      await refresh()
    },
    [resolveJobSession, refresh],
  )

  const prioritizeJob = useCallback(
    async (jobId: string) => {
      const sp = resolveJobSession(jobId)
      if (!sp) return
      await api.jobsPrioritize(sp, jobId)
      setToast({ message: '已设为优先，将尽快执行', variant: 'info' })
      await refresh()
    },
    [resolveJobSession, refresh],
  )

  const requeueJob = useCallback(
    async (jobId: string) => {
      const sp = resolveJobSession(jobId)
      if (!sp) return
      await api.jobsRequeue(sp, jobId)
      setToast({ message: '已重新排队（完整重跑）', variant: 'info' })
      setCenterOpen(true)
      await refresh()
    },
    [resolveJobSession, refresh],
  )

  const deleteJob = useCallback(
    async (jobId: string, opts?: { deleteSources?: boolean }) => {
      const sp = resolveJobSession(jobId)
      if (!sp) return
      const job = jobs.find((j) => j.id === jobId)
      const res = await api.jobsDelete(sp, jobId, !!opts?.deleteSources)
      const touchPip =
        !!opts?.deleteSources ||
        job?.type === 'hyperframe_fill_cues' ||
        job?.type === 'hyperframe_restyle'
      if (touchPip) {
        setAssignmentsTick((t) => t + 1)
        try {
          window.dispatchEvent(
            new CustomEvent('agent:pip-assignments-changed', {
              detail: { sessionPath: sp, pruned: res.pruned_assignments ?? 0 },
            }),
          )
        } catch {
          /* ignore */
        }
      }
      if (opts?.deleteSources && job?.type === 'avatar_lipsync') {
        try {
          window.dispatchEvent(
            new CustomEvent('agent:session-refresh', {
              detail: { sessionPath: sp, reason: 'lipsync-purged' },
            }),
          )
        } catch {
          /* ignore */
        }
      }
      if (opts?.deleteSources) {
        const pruned = res.pruned_assignments ?? 0
        const lipsyncPruned = res.pruned_lipsyncs ?? 0
        const removed = (res.removed_files ?? 0) + (res.removed_dirs ?? 0)
        if (lipsyncPruned > 0 || job?.type === 'avatar_lipsync') {
          setToast({
            message:
              removed > 0
                ? '已清除口播源文件与历史版本，正在刷新页面列表…'
                : '已清理口播记录',
            variant: 'info',
          })
        } else if (pruned > 0) {
          setToast({
            message: `已清除源文件，并移除 ${pruned} 个废弃场景绑定`,
            variant: 'info',
          })
        } else if (removed > 0) {
          setToast({ message: '已清除任务源文件，正在同步场景列表…', variant: 'info' })
        }
      }
      await refresh()
    },
    [resolveJobSession, refresh, jobs],
  )

  const clearHistory = useCallback(async () => {
    await Promise.all([
      sessionPath ? api.jobsClearHistory(sessionPath).catch(() => null) : null,
      systemPath ? api.jobsClearHistory(systemPath).catch(() => null) : null,
    ])
    await refresh()
  }, [sessionPath, systemPath, refresh])

  const clearToast = useCallback(() => setToast(null), [])

  const value = useMemo(
    () => ({
      jobs,
      activeCount,
      centerOpen,
      setCenterOpen,
      toast,
      clearToast,
      refresh,
      enqueue,
      cancelJob,
      prioritizeJob,
      requeueJob,
      deleteJob,
      clearHistory,
      completionTick,
      lastFinished,
      assignmentsTick,
    }),
    [
      jobs,
      activeCount,
      centerOpen,
      toast,
      clearToast,
      refresh,
      enqueue,
      cancelJob,
      prioritizeJob,
      requeueJob,
      deleteJob,
      clearHistory,
      completionTick,
      lastFinished,
      assignmentsTick,
    ],
  )

  return <JobQueueContext.Provider value={value}>{children}</JobQueueContext.Provider>
}

export function useJobQueue() {
  const ctx = useContext(JobQueueContext)
  if (!ctx) throw new Error('useJobQueue must be used within JobQueueProvider')
  return ctx
}

/** Optional hook when provider may be absent (should not happen in App). */
export function useJobQueueOptional() {
  return useContext(JobQueueContext)
}

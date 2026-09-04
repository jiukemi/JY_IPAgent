import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import { AlertModal, parseApiError } from '../components/AlertModal'
import { AudioPreviewButton, formatAudioDuration } from '../components/AudioPreviewButton'
import { DubbingSourcePanel } from '../components/DubbingSourcePanel'
import { useJobQueue } from '../context/JobQueueContext'
import type { SessionSnapshot, TtsModelField, TtsOptions, VoiceItem } from '../types'
import { ActionBtn, Panel } from './ScriptPage'
import { ClonePage } from './ClonePage'
import {
  emoPreviewKey,
  getEmoAudioPath,
  getEmoDubbingPath,
  loadEmoStylesForVoice,
  loadLastEmoForVoice,
  rememberEmoForVoice,
  sessionAudioUrl,
  setLastEmoForVoice,
  type CloneVoiceEmoItem,
} from '../utils/cloneEmoHistory'

const CLONE_EMO_PRESETS = [
  { label: '热情带货', value: '热情活泼，语速略快，适合带货口播' },
  { label: '温柔聊天', value: '温柔亲切，语速自然，像跟朋友聊天' },
  { label: '激动振奋', value: '激动振奋，强调卖点，情绪饱满' },
  { label: '沉稳播报', value: '沉稳专业，新闻播报感，吐字清晰' },
] as const

type TextSource = 'script' | 'manual'

type AlertState = {
  title: string
  message: string
  variant: 'error' | 'warning' | 'success' | 'info'
}

type Props = {
  session: SessionSnapshot
  onUpdate: (s: SessionSnapshot) => void
  onOpenSettings: (section?: 'tts' | 'env') => void
  configVersion?: number
  voiceVersion?: number
  onVoiceSaved?: (voiceUid?: string) => void
  /** 当前是否在配音步骤；首次进入才拉取引擎，避免一启动就卡 */
  active?: boolean
}

export function TtsPage({
  session,
  onUpdate,
  onOpenSettings,
  configVersion = 0,
  voiceVersion = 0,
  onVoiceSaved,
  active = true,
}: Props) {
  const jobQueue = useJobQueue()
  const [source, setSource] = useState<TextSource>('script')
  const [manualText, setManualText] = useState('')
  const [system, setSystem] = useState<VoiceItem[]>([])
  const [clones, setClones] = useState<VoiceItem[]>([])
  const [voiceUid, setVoiceUid] = useState('')
  const [speed, setSpeed] = useState('balanced')
  const [speeds, setSpeeds] = useState<{ value: string; label: string }[]>([])
  const [cloneEmoStyle, setCloneEmoStyle] = useState('')
  const [cloneEmoOpen, setCloneEmoOpen] = useState(false)
  const [emoPreviewBusy, setEmoPreviewBusy] = useState(false)
  const [emoPreviewPlain, setEmoPreviewPlain] = useState<string | null>(null)
  const [emoPreviewStyled, setEmoPreviewStyled] = useState<string | null>(null)
  const [emoPreviewBust, setEmoPreviewBust] = useState(0)
  const [voiceEmoStyles, setVoiceEmoStyles] = useState<CloneVoiceEmoItem[]>([])
  const [runtime, setRuntime] = useState<TtsOptions | null>(null)
  const [fieldDraft, setFieldDraft] = useState<Record<string, string | number | boolean>>({})
  const [busy, setBusy] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [savingModel, setSavingModel] = useState(false)
  const [modelMsg, setModelMsg] = useState('')
  const [alert, setAlert] = useState<AlertState | null>(null)
  const [cloneManageOpen, setCloneManageOpen] = useState(false)
  const cloneDirtyRef = useRef(false)
  const [engineOpen, setEngineOpen] = useState(true)
  const [verifying, setVerifying] = useState(false)
  const [previewStats, setPreviewStats] = useState<{ total: number; cached: number; missing: number } | null>(null)
  const [buildingPreviews, setBuildingPreviews] = useState(false)
  const [previewMsg, setPreviewMsg] = useState('')
  const [previewBuildPct, setPreviewBuildPct] = useState(0)
  const [ttsWorker, setTtsWorker] = useState<{ enabled: boolean; running: boolean } | null>(null)
  const [workerBusy, setWorkerBusy] = useState(false)
  const selectedDubPath = session.selected_dub ?? session.dubbing_audio

  const onDubSelect = useCallback(
    async (path: string | null) => {
      if (!path || !session.path) return
      try {
        await api.selectSessionDubbing(session.path, path)
        onUpdate(await api.sessionSnapshot(session.path))
      } catch (e) {
        setAlert({
          title: '切换音轨失败',
          message: e instanceof Error ? e.message : String(e),
          variant: 'error',
        })
      }
    },
    [session.path, onUpdate],
  )

  const isCloneVoice = voiceUid.startsWith('clone:')
  const showCloneEmo = runtime?.engine === 'indextts' && clones.length > 0
  const emoEngine = runtime?.engine || 'indextts'
  const selectedClone = clones.find((v) => v.uid === voiceUid)
  const effectiveEmoStyle = cloneEmoOpen && isCloneVoice ? cloneEmoStyle.trim() : ''

  const refreshVoiceEmoStyles = useCallback(
    (engine?: string, uid?: string) => {
      const eng = engine || runtime?.engine || 'indextts'
      const v = uid || voiceUid
      if (!v.startsWith('clone:')) {
        setVoiceEmoStyles([])
        return
      }
      setVoiceEmoStyles(loadEmoStylesForVoice(eng, v))
    },
    [runtime?.engine, voiceUid],
  )

  useEffect(() => {
    if (!runtime?.engine || !voiceUid.startsWith('clone:')) {
      setVoiceEmoStyles([])
      if (!voiceUid.startsWith('clone:')) setCloneEmoStyle('')
      return
    }
    refreshVoiceEmoStyles(runtime.engine, voiceUid)
    if (cloneEmoOpen) {
      const last = loadLastEmoForVoice(runtime.engine, voiceUid)
      setCloneEmoStyle(last)
      syncEmoPreviewPlayers(last)
    } else {
      setCloneEmoStyle('')
      setEmoPreviewStyled(null)
    }
  }, [voiceUid, runtime?.engine, refreshVoiceEmoStyles, cloneEmoOpen])

  const toggleCloneEmo = (open: boolean) => {
    setCloneEmoOpen(open)
    if (!open) {
      setCloneEmoStyle('')
      setEmoPreviewStyled(null)
      return
    }
    if (voiceUid.startsWith('clone:') && runtime?.engine) {
      const last = loadLastEmoForVoice(runtime.engine, voiceUid)
      setCloneEmoStyle(last)
      syncEmoPreviewPlayers(last)
    }
  }

  const syncEmoPreviewPlayers = (emoValue: string) => {
    if (!voiceUid.startsWith('clone:')) return
    const eng = emoEngine
    const plainPath = getEmoAudioPath(eng, voiceUid, '')
    if (plainPath) {
      setEmoPreviewPlain(sessionAudioUrl(plainPath))
    }
    const styledPath = getEmoAudioPath(eng, voiceUid, emoValue)
    if (emoValue.trim() && styledPath) {
      setEmoPreviewStyled(sessionAudioUrl(styledPath))
      setEmoPreviewBust(Date.now())
    } else if (!emoValue.trim()) {
      setEmoPreviewStyled(null)
    } else {
      setEmoPreviewStyled(null)
    }
  }

  const syncDubbingToEmo = async (emoValue: string) => {
    if (!session.path || !voiceUid.startsWith('clone:')) return
    const dubPath = getEmoDubbingPath(emoEngine, voiceUid, emoValue)
    if (dubPath && dubPath !== selectedDubPath) {
      await onDubSelect(dubPath)
    }
  }

  const selectEmoStyle = (value: string) => {
    setCloneEmoStyle(value)
    if (voiceUid.startsWith('clone:')) {
      setLastEmoForVoice(emoEngine, voiceUid, value)
      syncEmoPreviewPlayers(value)
      void syncDubbingToEmo(value)
    }
  }

  useEffect(() => {
    if (!active) return
    let cancelled = false
    const tick = () => {
      api
        .ttsWorkerStatus()
        .then((s) => {
          if (!cancelled) setTtsWorker(s)
        })
        .catch(() => {
          if (!cancelled) setTtsWorker(null)
        })
    }
    tick()
    const id = window.setInterval(tick, 4000)
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [active, emoPreviewBusy, busy, buildingPreviews])

  const previewCloneEmotion = async (mode: 'plain' | 'styled') => {
    if (!session.path || !voiceUid.startsWith('clone:')) {
      setAlert({ title: '请先选择克隆音色', message: '在下方音色列表中点选你的克隆音色后再试听。', variant: 'warning' })
      return
    }
    if (runtime && !runtime.ready) {
      setAlert({ title: '引擎未就绪', message: runtime.health?.message || '请先完成 IndexTTS 安装', variant: 'warning' })
      return
    }
    setEmoPreviewBusy(true)
    try {
      const style = mode === 'styled' ? effectiveEmoStyle : ''
      const res = await api.previewCloneEmo({
        session_path: session.path,
        voice_uid: voiceUid,
        speed_mode: speed,
        backend: runtime?.engine || '',
        style_extra: style,
        preview_key: emoPreviewKey(voiceUid, style, mode),
      })
      const path = res.data?.audio_path as string | undefined
      if (!path) throw new Error('未返回试听音频')
      const url = sessionAudioUrl(path)
      setEmoPreviewBust(Date.now())
      rememberEmoForVoice(emoEngine, voiceUid, style, undefined, { previewPath: path })
      refreshVoiceEmoStyles(emoEngine, voiceUid)
      if (mode === 'plain') setEmoPreviewPlain(url)
      else setEmoPreviewStyled(url)
      void api.ttsWorkerStatus().then(setTtsWorker).catch(() => {})
    } catch (e) {
      const { title, message } = parseApiError(e, '试听失败')
      setAlert({ title, message, variant: 'error' })
    } finally {
      setEmoPreviewBusy(false)
    }
  }

  const scriptText = session.script || ''
  const activeText = source === 'script' ? scriptText : manualText
  const charCount = activeText.length
  const isLocal = runtime?.mode === 'local'

  useEffect(() => {
    const manual = session.script_manual || ''
    setManualText(manual)
    if (manual.trim() && manual.trim() !== scriptText.trim()) {
      setSource('manual')
    }
  }, [session.path, session.script_manual, scriptText])

  useEffect(() => {
    if (!session.path || !manualText.trim()) return
    const timer = window.setTimeout(() => {
      void api.saveScriptText(session.path, 'manual', manualText).catch(() => {})
    }, 700)
    return () => window.clearTimeout(timer)
  }, [manualText, session.path])

  const loadVoices = useCallback(
    async (
      engine: string,
      preferredUid?: string,
      resetVoice = false,
      profile?: TtsOptions['profile'],
    ) => {
    try {
      const prof = profile ?? (await api.ttsOptions(engine)).profile
      const [s, c, sp] = await Promise.all([
        api.systemVoices(engine),
        api.cloneVoices(engine),
        api.ttsSpeeds(engine),
      ])
      setSystem(s)
      setClones(c)
      const speedList = sp.length
        ? sp
        : prof?.supports_speed
          ? [{ value: 'balanced', label: '平衡' }]
          : []
      setSpeeds(speedList)
      setSpeed((prev) => {
        if (!speedList.length) return prev
        if (speedList.some((x) => x.value === prev)) return prev
        return speedList[0]?.value || 'balanced'
      })
      const all = [...s, ...c]
      setVoiceUid((prev) => {
        if (!resetVoice && prev && all.some((v) => v.uid === prev)) return prev
        if (preferredUid && all.some((v) => v.uid === preferredUid)) return preferredUid
        return all[0]?.uid || ''
      })
    } catch (e) {
      setAlert({
        title: '音色加载失败',
        message: e instanceof Error ? e.message : String(e),
        variant: 'error',
      })
      setSystem([])
      setClones([])
    }
  },
  [])

  const loadRuntime = useCallback(async (engine?: string, resetVoice = false) => {
    const opts = await api.ttsOptions(engine)
    setRuntime(opts)
    const draft: Record<string, string | number | boolean> = {}
    for (const f of opts.fields) draft[f.key] = f.value
    setFieldDraft(draft)
    await loadVoices(opts.engine, opts.default_voice_uid, resetVoice || Boolean(engine), opts.profile)
    try {
      const ps = await api.previewStatus(opts.engine)
      setPreviewStats({ total: ps.total, cached: ps.cached, missing: ps.missing })
    } catch {
      setPreviewStats(null)
    }
    return opts
  }, [loadVoices])

  const loadedConfigRef = useRef<number | null>(null)

  useEffect(() => {
    if (!active) return
    if (loadedConfigRef.current === configVersion) return
    let cancelled = false
    void loadRuntime().then(() => {
      if (!cancelled) loadedConfigRef.current = configVersion
    })
    return () => {
      cancelled = true
    }
    // 仅在进入配音页或配置变更时拉取；音色变更走下方独立刷新
  }, [active, configVersion, loadRuntime])

  useEffect(() => {
    if (!voiceVersion || !runtime?.engine) return
    void loadVoices(runtime.engine, voiceUid, false, runtime.profile)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only react to voice library bumps
  }, [voiceVersion])

  const closeCloneManage = useCallback(() => {
    setCloneManageOpen(false)
    if (!cloneDirtyRef.current || !runtime?.engine) return
    cloneDirtyRef.current = false
    void loadVoices(runtime.engine, voiceUid, false, runtime.profile)
  }, [loadVoices, runtime?.engine, runtime?.profile, voiceUid])

  const onCloneLibraryChanged = useCallback(
    (nextUid?: string) => {
      cloneDirtyRef.current = true
      if (runtime?.engine) {
        void loadVoices(runtime.engine, nextUid || voiceUid, Boolean(nextUid), runtime.profile).then(() => {
          if (nextUid) setVoiceUid(nextUid)
        })
      } else if (nextUid) {
        setVoiceUid(nextUid)
      }
      onVoiceSaved?.(nextUid)
    },
    [loadVoices, onVoiceSaved, runtime?.engine, runtime?.profile, voiceUid],
  )

  const refreshSession = async () => {
    onUpdate(await api.sessionSnapshot(session.path))
  }

  const refreshScript = async () => {
    setSyncing(true)
    try {
      const snap = await api.sessionSnapshot(session.path)
      onUpdate(snap)
    } finally {
      setSyncing(false)
    }
  }

  const onEngineChange = async (engine: string) => {
    if (!runtime || engine === runtime.engine || savingModel) return
    const prev = runtime
    const picked = runtime.engines.find((e) => e.value === engine)
    // 立刻反馈：先切 UI，再落盘；不再每次先扫全套硬件（以前会卡很久且无提示）
    setSavingModel(true)
    setModelMsg(`正在切换到「${picked?.label || engine}」…`)
    setRuntime({
      ...runtime,
      engine,
      engine_label: picked?.label || engine,
      profile: {
        ...(runtime.profile || {
          engine,
          label: picked?.label || engine,
          hardware: picked?.hardware || '',
          supports_clone: false,
          supports_dialect: false,
          supports_speed: false,
          online: false,
          summary: picked?.summary || '',
          setup: null,
        }),
        engine,
        label: picked?.label || engine,
        hardware: picked?.hardware || runtime.profile?.hardware || '',
        summary: picked?.summary || runtime.profile?.summary || '',
      },
    })
    setEngineOpen(true)
    setSystem([])
    setClones([])
    try {
      // PUT 已返回完整 tts options，无需再请求 /tts/options
      const opts = await api.saveTtsSettings({ engine })
      setRuntime(opts)
      const draft: Record<string, string | number | boolean> = {}
      for (const f of opts.fields) draft[f.key] = f.value
      setFieldDraft(draft)
      setModelMsg('正在刷新音色列表…')
      await loadVoices(opts.engine, opts.default_voice_uid, true, opts.profile)
      setModelMsg(`已切换为 ${opts.engine_label}`)
      void api.previewStatus(opts.engine).then((ps) => {
        setPreviewStats({ total: ps.total, cached: ps.cached, missing: ps.missing })
      }).catch(() => setPreviewStats(null))
    } catch (e) {
      setRuntime(prev)
      setModelMsg(e instanceof Error ? e.message : String(e))
      try {
        await loadRuntime()
      } catch {
        /* ignore */
      }
    } finally {
      setSavingModel(false)
    }
  }

  const saveModelSettings = async () => {
    if (!runtime) return
    setSavingModel(true)
    setModelMsg('')
    try {
      await api.saveTtsSettings({ engine: runtime.engine, values: fieldDraft })
      await loadRuntime(runtime.engine)
      setModelMsg('模型设置已保存')
      if (runtime.engine === 'qwen3_tts') {
        await runVerify(runtime.engine, false)
      }
    } catch (e) {
      setModelMsg(e instanceof Error ? e.message : String(e))
    } finally {
      setSavingModel(false)
    }
  }

  const runVerify = async (engine: string, showBusy = true) => {
    if (showBusy) setVerifying(true)
    try {
      const res = await api.verifyTts(engine)
      setModelMsg(res.message)
      await loadRuntime(engine)
    } catch (e) {
      setModelMsg(e instanceof Error ? e.message : String(e))
    } finally {
      if (showBusy) setVerifying(false)
    }
  }

  const patchField = (key: string, value: string | number | boolean) => {
    setFieldDraft((d) => ({ ...d, [key]: value }))
  }

  const buildPreviews = async () => {
    if (!runtime) return
    setBuildingPreviews(true)
    setPreviewMsg('')
    setPreviewBuildPct(0)
    try {
      const health = await api.verifyTts(runtime.engine)
      if (!health.ok) {
        setAlert({
          title: '引擎未就绪',
          message: health.message || '请先完成模型安装或配置后再生成试听',
          variant: 'warning',
        })
        return
      }
      if (!health.preset_ready) {
        setAlert({
          title: '预设参考音未就绪',
          message:
            health.message ||
            '预设音色试听需要参考音。可一键安装下载示例，或在本页上方保存参考音。',
          variant: 'warning',
        })
        return
      }
      const r = await api.buildPreviewsStream(runtime.engine, (p) => {
        setPreviewBuildPct(p.pct)
        if (p.total > 0) {
          setPreviewMsg(`生成试听 ${p.i}/${p.total} · ${p.label}`)
        } else {
          setPreviewMsg(p.label || '生成中…')
        }
      })
      const errHint = r.errors?.length ? `\n${r.errors.slice(0, 3).join('\n')}` : ''
      setPreviewMsg(`完成：新生成 ${r.ok}，已有 ${r.skip}，失败 ${r.fail}${errHint}`)
      if (r.fail > 0 && r.ok === 0) {
        setAlert({
          title: '试听生成失败',
          message: r.errors?.join('\n') || '请检查引擎是否就绪、参考音是否可用',
          variant: 'error',
        })
      }
      await loadVoices(runtime.engine, voiceUid, false, runtime.profile)
      const ps = await api.previewStatus(runtime.engine)
      setPreviewStats({ total: ps.total, cached: ps.cached, missing: ps.missing })
    } catch (e) {
      const { message } = parseApiError(e, '试听生成失败')
      setPreviewMsg(message)
      setAlert({ title: '试听生成失败', message, variant: 'error' })
    } finally {
      setBuildingPreviews(false)
      setPreviewBuildPct(0)
    }
  }

  const synth = async () => {
    if (
      source === 'script' &&
      manualText.trim() &&
      manualText.trim() !== scriptText.trim()
    ) {
      setAlert({
        title: '文案来源不对',
        message:
          '你在「手动输入」里改过文案，但当前选中的是「① 文案」。请切换到「手动输入」再点生成，否则会漏掉修改。',
        variant: 'warning',
      })
      return
    }
    const text = activeText.trim()
    if (!text) {
      setAlert({
        title: '缺少文案',
        message: source === 'script' ? '请先在 ① 文案 提取或仿写口播文案' : '请输入要配音的文案',
        variant: 'warning',
      })
      return
    }
    if (!voiceUid) {
      setAlert({
        title: '未选择音色',
        message: clones.length
          ? '请在下方选择克隆音色，或切换到系统音色'
          : '请先点击「音色管理」保存克隆音色，或选择系统音色',
        variant: 'warning',
      })
      return
    }
    const isCloneVoice = voiceUid.startsWith('clone:')
    const engineReady = isCloneVoice
      ? Boolean(runtime?.ready)
      : Boolean(runtime?.preset_ready ?? runtime?.ready)
    if (runtime && !engineReady) {
      const localHint =
        runtime.mode === 'local'
          ? isCloneVoice
            ? '请先到顶栏「设置 → 本机环境」完成模型安装（克隆合成无需预设参考音）。'
            : '预设音色需要参考音：可在「设置」里安装模型，或在本页上方保存参考音。'
          : '请先完成云端引擎配置（展开引擎设置或打开顶栏「设置」）。'
      setAlert({
        title: '引擎未就绪',
        message: runtime.health?.message || localHint,
        variant: 'warning',
      })
      return
    }
    setBusy(true)
    try {
      if (source === 'manual') {
        await api.saveScriptText(session.path, 'manual', text)
      }
      const outcome = await jobQueue.enqueue({
        type: 'tts_synthesize',
        title: '生成配音',
        force: true,
        payload: {
          session_path: session.path,
          text,
          voice_uid: voiceUid,
          speed_mode: speed,
          backend: runtime?.engine || '',
          style_extra: voiceUid.startsWith('clone:') ? effectiveEmoStyle : '',
        },
      })
      if (outcome.ok) {
        setAlert({
          title: '已加入任务中心',
          message: '配音在后台按序生成，可继续操作其它步骤；进度见任务中心。',
          variant: 'success',
        })
      } else {
        setAlert({
          title: '未加入队列',
          message: outcome.message || '当前已有相同任务',
          variant: 'warning',
        })
      }
    } catch (e) {
      const { title, message } = parseApiError(e, '配音失败')
      setAlert({ title, message, variant: 'error' })
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    const job = jobQueue.lastFinished
    if (!job || jobQueue.completionTick <= 0) return
    if (job.type !== 'tts_synthesize') return
    if (job.status === 'done') {
      const payload = job.payload as {
        session_path?: string
        voice_uid?: string
        backend?: string
        style_extra?: string
      }
      void api.sessionSnapshot(session.path).then((updated) => {
        if (
          payload.session_path === session.path &&
          payload.voice_uid?.startsWith('clone:')
        ) {
          const eng = payload.backend || runtime?.engine || 'indextts'
          const style = (payload.style_extra || '').trim()
          const presetLabel = CLONE_EMO_PRESETS.find((p) => p.value === style)?.label
          const audioPath =
            (job.result?.audio_path as string | undefined) || updated.dubbing_audio
          rememberEmoForVoice(eng, payload.voice_uid!, style, presetLabel, {
            dubbingPath: audioPath || undefined,
          })
          if (payload.voice_uid === voiceUid) {
            refreshVoiceEmoStyles(eng, payload.voice_uid!)
            setCloneEmoStyle(loadLastEmoForVoice(eng, payload.voice_uid!))
            syncEmoPreviewPlayers(style)
            void syncDubbingToEmo(style)
          }
        }
        onUpdate(updated)
        const dur = updated.dubbing_duration
        setAlert({
          title: '配音已生成',
          message:
            dur && dur > 0
              ? `当前成片约 ${formatAudioDuration(dur)}。配音更新后请到 ③ 口播重新生成视频。`
              : '配音已更新。请到 ③ 口播重新生成对口型视频。',
          variant: 'success',
        })
      })
    } else if (job.status === 'failed') {
      setAlert({
        title: '配音失败',
        message: job.error || job.message || '请在任务中心查看详情',
        variant: 'error',
      })
    }
  }, [jobQueue.completionTick, jobQueue.lastFinished, session.path, onUpdate, voiceUid, runtime?.engine, refreshVoiceEmoStyles])

  const ttsRunningJob = jobQueue.jobs.find(
    (j) => j.type === 'tts_synthesize' && (j.status === 'queued' || j.status === 'running'),
  )

  const engineBusy =
    emoPreviewBusy || buildingPreviews || busy || Boolean(ttsRunningJob) || workerBusy
  const engName = runtime?.engine_label || runtime?.engine || '配音引擎'

  const scriptEmpty = !scriptText.trim()
  const supportsClone = !!runtime?.profile?.supports_clone

  return (
    <div className="flex flex-col gap-4">
      {(engineBusy || ttsWorker?.running) && (
        <div
          className={`rounded-xl border px-4 py-3 text-sm ${
            engineBusy
              ? 'border-amber-500/50 bg-amber-500/10 text-amber-950 dark:text-amber-100'
              : 'border-[var(--select-border)] bg-[var(--select-bg)] text-[var(--accent)]'
          }`}
          role="status"
        >
          {emoPreviewBusy ? (
            <p className="font-medium">
              {engName} 正在 GPU 合成「情感试听」…
              <span className="mt-1 block text-xs font-normal opacity-80">
                这不是播放本地录音；首次加载模型时显存会明显升高，请等合成结束。只听参考音请点音色旁的 ▶。
              </span>
            </p>
          ) : buildingPreviews ? (
            <p className="font-medium">
              {engName} 正在批量生成系统音色试听缓存（GPU）…
              <span className="mt-1 block text-xs font-normal opacity-80">{previewMsg || '请稍候'}</span>
            </p>
          ) : ttsRunningJob || busy ? (
            <p className="font-medium">
              {engName} 正在生成配音（GPU）…
              <span className="mt-1 block text-xs font-normal opacity-80">
                {ttsRunningJob?.message || '可在任务中心查看进度'}
              </span>
            </p>
          ) : ttsWorker?.running ? (
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="font-medium">
                IndexTTS 常驻进程占用 GPU
                <span className="mt-1 block text-xs font-normal opacity-80">
                  为加速下次合成而常驻；不用时可停止以释放显存。
                </span>
              </p>
              <button
                type="button"
                disabled={workerBusy}
                onClick={() => {
                  setWorkerBusy(true)
                  void api
                    .ttsWorkerStop()
                    .then((s) => setTtsWorker({ enabled: false, running: s.running }))
                    .catch((e) =>
                      setAlert({
                        title: '停止失败',
                        message: e instanceof Error ? e.message : String(e),
                        variant: 'error',
                      }),
                    )
                    .finally(() => setWorkerBusy(false))
                }}
                className="rounded-lg border border-red-500/40 px-3 py-1.5 text-xs text-red-600 hover:bg-red-500/10"
              >
                {workerBusy ? '处理中…' : '停止并释放显存'}
              </button>
            </div>
          ) : null}
        </div>
      )}

      <Panel title="02 配音 · 引擎与模型">
        {runtime ? (
          <div className="space-y-2">
            <button
              type="button"
              onClick={() => setEngineOpen((o) => !o)}
              className="flex w-full items-center justify-between rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3 py-2.5 text-left text-sm"
            >
              <span>
                <span className="mr-2 rounded-md border border-[var(--border)] px-2 py-0.5 text-xs">
                  {runtime.mode_label}
                </span>
                {runtime.engine_label}
                <span className="ml-2 text-xs text-[var(--muted)]">
                  {runtime.mode === 'local' ? '本地引擎' : '云端 API'}
                </span>
                {runtime.profile?.hardware && (
                  <span className="ml-2 text-xs text-[var(--muted)]">{runtime.profile.hardware}</span>
                )}
              </span>
              <span className="text-xs text-[var(--muted)]">{engineOpen ? '收起 ▲' : '展开 ▼'}</span>
            </button>

            {runtime.profile?.summary && (
              <p className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-xs text-[var(--muted)]">
                {runtime.profile.summary}
              </p>
            )}

            {isLocal && runtime && !runtime.ready && (
              <div className="flex flex-wrap items-center gap-2 rounded-lg border border-[var(--warn-border)] bg-[var(--warn-bg)] px-3 py-2 text-xs text-[var(--warn-text)]">
                <span>{runtime.health?.message || '本地引擎未就绪'}</span>
                <button
                  type="button"
                  onClick={() => onOpenSettings('env')}
                  className="rounded-md border border-[var(--select-border)] bg-[var(--select-bg)] px-2 py-0.5 text-[var(--accent)]"
                >
                  打开设置
                </button>
              </div>
            )}

            {isLocal && runtime?.ready && runtime.preset_ready === false && (
              <p className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-xs text-[var(--muted)]">
                克隆音色可用；预设音色与试听需补充参考音 →{' '}
                <button type="button" onClick={() => onOpenSettings('env')} className="text-[var(--accent)] hover:underline">
                  本机环境
                </button>
              </p>
            )}

            {!runtime.ready && runtime.health && !isLocal && (
              <p className="rounded-lg border border-[var(--warn-border)] bg-[var(--warn-bg)] px-3 py-2 text-xs text-[var(--warn-text)]">
                {runtime.health.message}
              </p>
            )}

            {engineOpen && (
              <div className="space-y-3 rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3">
                <label className="block text-xs text-[var(--muted)]">
                  {isLocal ? '本地 TTS 模型' : '云端 TTS 服务'}
                </label>
                {(savingModel || modelMsg) && (
                  <div
                    className={`rounded-lg border px-3 py-2 text-xs ${
                      savingModel
                        ? 'border-[var(--select-border)] bg-[var(--select-bg)] text-[var(--accent)]'
                        : 'border-[var(--border)] text-[var(--muted)]'
                    }`}
                  >
                    {savingModel ? (
                      <span className="inline-flex items-center gap-2">
                        <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-[var(--accent)] border-t-transparent" />
                        {modelMsg || '正在切换…'}
                      </span>
                    ) : (
                      modelMsg
                    )}
                  </div>
                )}
                <div className="mt-1 flex flex-col gap-1.5">
                  {runtime.engines.map((e) => {
                    const activeEng = e.value === runtime.engine
                    const switchingHere = savingModel && activeEng
                    return (
                      <button
                        key={e.value}
                        type="button"
                        disabled={savingModel}
                        onClick={() => void onEngineChange(e.value)}
                        className={`rounded-lg border px-3 py-2 text-left text-sm transition disabled:opacity-60 ${
                          activeEng
                            ? 'border-[var(--select-border)] bg-[var(--select-bg)] font-medium text-[var(--accent)]'
                            : 'border-[var(--border)] bg-[var(--panel)] hover:border-[var(--select-border)]'
                        }`}
                      >
                        <span className="block">
                          {e.label}
                          {switchingHere ? ' · 切换中…' : ''}
                        </span>
                        {e.hardware && (
                          <span className="mt-0.5 block text-[10px] text-[var(--muted)]">{e.hardware}</span>
                        )}
                      </button>
                    )
                  })}
                </div>

                {!isLocal && runtime.cloud_hint && (
                  <div
                    className={`rounded-xl border px-4 py-3 text-sm ${
                      runtime.cloud_hint.ready
                        ? 'border-emerald-500/40 bg-emerald-500/10'
                        : 'border-amber-500/40 bg-amber-500/10'
                    }`}
                  >
                    <div className="font-medium">{runtime.cloud_hint.title}</div>
                    <p className="mt-1 text-[var(--muted)]">{runtime.cloud_hint.description}</p>
                    {!runtime.cloud_hint.ready && runtime.cloud_hint.missing && (
                      <p className="mt-2 text-xs text-amber-300">{runtime.cloud_hint.missing}</p>
                    )}
                    <div className="mt-3 flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => onOpenSettings('tts')}
                        className="rounded-lg btn-primary px-3 py-1.5 text-xs font-medium"
                      >
                        打开设置
                      </button>
                      {runtime.engine === 'qwen3_tts' && (
                        <button
                          type="button"
                          disabled={verifying}
                          onClick={() => void runVerify(runtime.engine)}
                          className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs"
                        >
                          {verifying ? '检测中…' : '检测连接'}
                        </button>
                      )}
                    </div>
                  </div>
                )}

                {runtime.fields.length > 0 && (
                  <details className="rounded-lg border border-[var(--border)] p-2">
                    <summary className="cursor-pointer select-none px-1 py-1 text-xs font-medium text-[var(--muted)]">
                      高级模型参数（{runtime.fields.length} 项）
                    </summary>
                    <div className="mt-2 grid gap-3 md:grid-cols-2">
                      {runtime.fields.map((f) => (
                        <ModelField
                          key={f.key}
                          field={f}
                          value={fieldDraft[f.key] ?? f.value}
                          onChange={(v) => patchField(f.key, v)}
                        />
                      ))}
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <button
                        type="button"
                        disabled={savingModel}
                        onClick={saveModelSettings}
                        className="rounded-lg border border-[var(--select-border)] bg-[var(--select-bg)] px-3 py-1.5 text-xs text-[var(--accent)]"
                      >
                        {savingModel ? '保存中…' : '保存设置'}
                      </button>
                      {runtime.engine === 'qwen3_tts' && (
                        <button
                          type="button"
                          disabled={verifying || savingModel}
                          onClick={() => void runVerify(runtime.engine)}
                          className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs hover:bg-[var(--panel)]"
                        >
                          {verifying ? '检测中…' : '检测 DashScope 连接'}
                        </button>
                      )}
                    </div>
                  </details>
                )}

                {!isLocal && runtime.engine === 'qwen3_tts' && (
                  <p className="text-xs text-[var(--muted)]">
                    Qwen3-TTS 走 DashScope 云端；本地 GPU 配音请在顶栏「设置」选「本地」后使用 IndexTTS2 / CosyVoice2。
                  </p>
                )}
              </div>
            )}

            {!engineOpen && savingModel && (
              <p className="text-xs text-[var(--accent)]">正在切换引擎并刷新音色…</p>
            )}
            {!engineOpen && modelMsg && !savingModel && (
              <p className="text-xs text-[var(--muted)]">{modelMsg}</p>
            )}
          </div>
        ) : (
          <p className="text-sm text-[var(--muted)]">加载引擎配置…</p>
        )}
      </Panel>

      <Panel title="02 配音 · 文案来源">
        <SegmentTabs
          value={source}
          onChange={setSource}
          items={[
            { id: 'script', label: '① 文案' },
            { id: 'manual', label: '手动输入' },
          ]}
        />
        {source === 'script' ? (
          <div className="mt-3">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <span className="text-xs text-[var(--muted)]">
                只读展示 ① 文案（script.txt）；有改动请切到「手动输入」
              </span>
              <div className="flex items-center gap-2">
                <span className="text-xs text-[var(--muted)]">{charCount} 字</span>
                <button
                  type="button"
                  onClick={refreshScript}
                  disabled={syncing}
                  className="rounded-lg border border-[var(--border)] px-2.5 py-1 text-xs hover:bg-[var(--panel)]"
                >
                  {syncing ? '同步中…' : '刷新文案'}
                </button>
              </div>
            </div>
            {scriptEmpty ? (
              <div className="rounded-xl border border-dashed border-[var(--border)] bg-[var(--bg)] px-4 py-8 text-center text-sm text-[var(--muted)]">
                暂无文案。请先到 <strong className="text-[var(--accent)]">① 文案</strong> 提取或仿写，再回来配音。
              </div>
            ) : (
              <div className="max-h-56 overflow-y-auto rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm leading-relaxed whitespace-pre-wrap">
                {scriptText}
              </div>
            )}
          </div>
        ) : (
          <div className="mt-3">
            <div className="mb-2 flex justify-end">
              <span className="text-xs text-[var(--muted)]">{charCount} 字</span>
            </div>
            <textarea
              value={manualText}
              onChange={(e) => setManualText(e.target.value)}
              rows={10}
              placeholder="在此输入或粘贴要配音的口播文案…"
              className="w-full rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm leading-relaxed"
            />
            {scriptText && (
              <button
                type="button"
                onClick={() => setManualText(scriptText)}
                className="mt-2 text-xs text-[var(--accent)] hover:underline"
              >
                从 ① 文案 填入
              </button>
            )}
          </div>
        )}
      </Panel>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title={`选音色 · 语速${runtime ? ` · ${runtime.engine_label}` : ''}`}>
          {runtime?.profile && (
            <div className="mb-3 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-xs">
              <div className="font-medium text-[var(--text)]">{runtime.profile.hardware}</div>
              <div className="mt-1 text-[var(--muted)]">
                {runtime.profile.supports_clone ? '支持克隆' : '仅预设音色'}
                {' · '}
                {runtime.profile.supports_dialect ? '支持方言' : '无方言'}
                {' · '}
                {runtime.profile.supports_speed ? '支持语速档位' : '无语速档位'}
              </div>
            </div>
          )}
          <p className="mb-2 text-xs text-[var(--muted)]">
            预设音色与上方引擎一一对应，切换引擎后列表会自动刷新。
          </p>
          {system.length > 0 && previewStats && previewStats.missing > 0 && (
            <div className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-xs">
              <span className="text-[var(--muted)]">
                试听缓存 {previewStats.cached}/{previewStats.total}
                <span className="ml-1 text-amber-700 dark:text-amber-200">
                  （{previewStats.missing} 个未生成）
                </span>
              </span>
              <button
                type="button"
                disabled={buildingPreviews || busy}
                onClick={() => void buildPreviews()}
                className="rounded-lg border border-[var(--select-border)] bg-[var(--select-bg)] px-2.5 py-1 text-[var(--accent)] disabled:opacity-50"
              >
                {buildingPreviews ? '生成中…' : '一键下载试听'}
              </button>
              {buildingPreviews && (
                <div className="h-1.5 min-w-[6rem] flex-1 overflow-hidden rounded-full bg-[var(--border)]">
                  <div
                    className="h-full rounded-full bg-[var(--accent)] transition-all duration-300"
                    style={{ width: `${Math.round(previewBuildPct * 100)}%` }}
                  />
                </div>
              )}
              {previewMsg && <span className="text-[var(--muted)]">{previewMsg}</span>}
            </div>
          )}
          {!system.length && !clones.length && (
            <p className="mb-2 text-xs text-amber-300">
              当前引擎暂无可用音色。请切换模型
              {supportsClone ? '，或点击「音色管理」保存克隆音色' : ''}。
            </p>
          )}
          {system.length > 0 && (
            <VoiceGrid title="系统预设" items={system} selected={voiceUid} onSelect={setVoiceUid} />
          )}
          {(() => {
            const selected = system.find((v) => v.uid === voiceUid)
            if (!selected?.hint || selected.category !== 'dialect') return null
            return (
              <p className="mt-2 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-xs leading-relaxed text-[var(--muted)]">
                {selected.hint}
              </p>
            )
          })()}
          {supportsClone ? (
            <div className="mt-2">
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <span className="text-xs font-medium text-[var(--muted)]">克隆音色</span>
                <button
                  type="button"
                  onClick={() => {
                    cloneDirtyRef.current = false
                    setCloneManageOpen(true)
                  }}
                  className="rounded-lg border border-[var(--select-border)] bg-[var(--select-bg)] px-2.5 py-1 text-xs font-medium text-[var(--accent)]"
                >
                  音色管理
                </button>
              </div>
              {clones.length > 0 ? (
                <VoiceGrid title="" items={clones} selected={voiceUid} onSelect={setVoiceUid} />
              ) : (
                <p className="text-xs text-[var(--muted)]">
                  暂无克隆音色。点击「音色管理」上传/录音后保存（当前引擎：{runtime?.engine_label}）。
                </p>
              )}
            </div>
          ) : (
            runtime && (
              <p className="mt-2 text-xs text-[var(--muted)]">当前引擎不支持声音克隆，请使用系统预设音色。</p>
            )
          )}
          {showCloneEmo && isCloneVoice && (
            <button
              type="button"
              onClick={() => toggleCloneEmo(!cloneEmoOpen)}
              className="mt-2 text-xs text-[var(--muted)] underline decoration-dotted underline-offset-2 hover:text-[var(--accent)]"
            >
              {cloneEmoOpen ? '收起情感微调' : '情感微调（可选，默认纯克隆）'}
            </button>
          )}
          {showCloneEmo && isCloneVoice && cloneEmoOpen && (
            <div
              className={`mt-3 space-y-2 rounded-xl border-2 p-3 ${
                isCloneVoice
                  ? 'border-[var(--accent)]/50 bg-[var(--select-bg)]/40'
                  : 'border-[var(--border)] bg-[var(--bg)]'
              }`}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-xs font-semibold text-[var(--text)]">
                  克隆情感 · 试听对比
                  {selectedClone ? (
                    <span className="ml-1 font-normal text-[var(--muted)]">（{selectedClone.label}）</span>
                  ) : (
                    <span className="ml-1 font-normal text-[var(--muted)]">（请先选音色）</span>
                  )}
                </p>
                {!isCloneVoice && (
                  <span className="text-[10px] text-amber-700 dark:text-amber-300">请先在下方选择克隆音色</span>
                )}
              </div>
              <p className="text-[10px] leading-relaxed text-[var(--muted)]">
                情感会改变语气，也可能影响吐字准确度。默认请用纯克隆；需要时再填写并试听对比。
              </p>
              <label className="block text-xs text-[var(--muted)]">
                情感风格
                <input
                  value={cloneEmoStyle}
                  onChange={(e) => setCloneEmoStyle(e.target.value)}
                  onBlur={() => {
                    if (voiceUid.startsWith('clone:')) {
                      setLastEmoForVoice(emoEngine, voiceUid, cloneEmoStyle)
                    }
                  }}
                  disabled={!isCloneVoice}
                  placeholder="例如：热情活泼，适合短视频口播，语气有起伏"
                  className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--panel)] px-2.5 py-2 text-sm disabled:opacity-50"
                />
              </label>
              <div className="flex flex-wrap gap-1.5">
                <button
                  type="button"
                  disabled={!isCloneVoice}
                  onClick={() => selectEmoStyle('')}
                  className={`rounded-md border px-2 py-0.5 text-[10px] disabled:opacity-40 ${
                    !cloneEmoStyle.trim()
                      ? 'border-[var(--accent)] bg-[var(--select-bg)] text-[var(--accent)]'
                      : 'border-[var(--border)] text-[var(--muted)] hover:border-[var(--accent)]'
                  }`}
                >
                  无情感
                </button>
                {voiceEmoStyles.map((h) => (
                  <button
                    key={h.value}
                    type="button"
                    disabled={!isCloneVoice}
                    onClick={() => selectEmoStyle(h.value)}
                    className={`rounded-md border px-2 py-0.5 text-[10px] disabled:opacity-40 ${
                      cloneEmoStyle.trim() === h.value
                        ? 'border-[var(--accent)] bg-[var(--select-bg)] text-[var(--accent)]'
                        : 'border-[var(--border)] text-[var(--muted)] hover:border-[var(--accent)]'
                    }`}
                    title={h.value}
                  >
                    {h.label}
                  </button>
                ))}
                {CLONE_EMO_PRESETS.map((chip) => {
                  const saved = voiceEmoStyles.some((h) => h.value === chip.value)
                  if (saved) return null
                  return (
                    <button
                      key={chip.label}
                      type="button"
                      disabled={!isCloneVoice}
                      onClick={() => selectEmoStyle(chip.value)}
                      className={`rounded-md border border-dashed px-2 py-0.5 text-[10px] disabled:opacity-40 ${
                        cloneEmoStyle === chip.value
                          ? 'border-[var(--accent)] bg-[var(--select-bg)] text-[var(--accent)]'
                          : 'border-[var(--border)] text-[var(--muted)] hover:border-[var(--accent)]'
                      }`}
                    >
                      {chip.label}
                    </button>
                  )
                })}
              </div>
              <div className="flex flex-wrap gap-2">
                <ActionBtn
                  disabled={emoPreviewBusy || !isCloneVoice}
                  onClick={() => void previewCloneEmotion('plain')}
                >
                  {emoPreviewBusy ? 'GPU 合成中…' : '试听 · 无情感'}
                </ActionBtn>
                <ActionBtn
                  primary
                  disabled={emoPreviewBusy || !isCloneVoice}
                  onClick={() => void previewCloneEmotion('styled')}
                >
                  {emoPreviewBusy ? 'GPU 合成中…' : '试听 · 当前情感'}
                </ActionBtn>
              </div>
              <p className="text-[10px] text-[var(--muted)]">
                「试听 · 情感」会调用 {engName} 在 GPU 上重新合成；音色旁 ▶ 才是播本地参考音（不占 GPU）。
              </p>
              {(emoPreviewPlain || emoPreviewStyled) && (
                <div className="grid gap-2 sm:grid-cols-2">
                  {emoPreviewPlain && (
                    <div className="rounded-lg border border-[var(--border)] bg-[var(--panel)] p-2">
                      <p className="mb-1 text-[10px] text-[var(--muted)]">无情感（仅参考音）</p>
                      <audio src={emoPreviewPlain} controls className="w-full" key={`plain-${emoPreviewBust}`} />
                    </div>
                  )}
                  {emoPreviewStyled ? (
                    <div className="rounded-lg border border-[var(--accent)]/40 bg-[var(--panel)] p-2">
                      <p className="mb-1 text-[10px] text-[var(--accent)]">
                        当前情感{cloneEmoStyle.trim() ? `：${cloneEmoStyle.trim().slice(0, 24)}…` : '（未填）'}
                      </p>
                      <audio
                        src={emoPreviewStyled}
                        controls
                        className="w-full"
                        key={`styled-${cloneEmoStyle}-${emoPreviewBust}`}
                      />
                    </div>
                  ) : cloneEmoStyle.trim() ? (
                    <div className="rounded-lg border border-dashed border-[var(--border)] bg-[var(--panel)] p-2 text-[10px] text-[var(--muted)]">
                      该情感暂无缓存音频，请先「试听 · 当前情感」或「生成配音」
                    </div>
                  ) : null}
                </div>
              )}
            </div>
          )}
          {runtime?.profile?.supports_speed && speeds.length > 0 ? (
            <label className="mt-4 block text-xs text-[var(--muted)]">
              语速档位（{runtime.engine_label}）
              <select
                value={speed}
                onChange={(e) => setSpeed(e.target.value)}
                className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-2 py-2 text-sm"
              >
                {speeds.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            runtime && (
              <p className="mt-4 text-xs text-[var(--muted)]">
                当前引擎不使用语速档位{runtime.engine === 'cosyvoice' ? '（可在引擎设置中调整 speed）' : ''}。
              </p>
            )
          )}
          {(busy || ttsRunningJob) && (
            <div className="mt-4 space-y-2">
              <div className="flex justify-between text-xs text-[var(--muted)]">
                <span>
                  {ttsRunningJob?.status === 'queued' ? '排队中…' : '合成中…'}
                  {ttsRunningJob?.message ? ` · ${ttsRunningJob.message}` : ''}
                </span>
                <span>
                  {Math.round(Math.max(0, Math.min(1, ttsRunningJob?.progress || 0)) * 100)}%
                </span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-[var(--bg)]">
                <div
                  className="h-full rounded-full bg-[var(--accent)] transition-all duration-300"
                  style={{
                    width: `${Math.max(
                      3,
                      Math.round(Math.max(0, Math.min(1, ttsRunningJob?.progress || 0)) * 100),
                    )}%`,
                  }}
                />
              </div>
            </div>
          )}
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <ActionBtn
              primary
              disabled={
                busy ||
                !!ttsRunningJob ||
                !voiceUid ||
                !activeText.trim() ||
                (runtime !== null && !runtime.ready)
              }
              onClick={() => void synth()}
            >
              {ttsRunningJob ? '任务中心生成中…' : busy ? '提交中…' : '生成配音'}
            </ActionBtn>
            {ttsRunningJob && (
              <ActionBtn
                onClick={() => {
                  void jobQueue.cancelJob(ttsRunningJob.id)
                  void api.cancelTts().catch(() => api.cancelTask().catch(() => undefined))
                }}
              >
                取消任务
              </ActionBtn>
            )}
            <ActionBtn onClick={() => jobQueue.setCenterOpen(true)}>打开任务中心</ActionBtn>
          </div>
        </Panel>

        <Panel title="配音音轨 · 试听与导出">
          {session.dubbing_duration != null && session.dubbing_duration > 0 && (
            <p className="mb-2 text-xs text-[var(--muted)]">
              当前成片时长约 {formatAudioDuration(session.dubbing_duration)}
              {charCount > 0 && session.dubbing_duration < charCount / 4.5 && (
                <span className="ml-2 text-amber-700 dark:text-amber-200">
                  （偏短，可能未念完全文，请确认文案来源后重新生成）
                </span>
              )}
            </p>
          )}
          <DubbingSourcePanel
            sessionPath={session.path}
            dubs={session.dubs || []}
            latestPath={session.dubbing_audio}
            selectedPath={selectedDubPath}
            onSelectedChange={onDubSelect}
            onSessionRefresh={refreshSession}
            cacheBust={session.dubbing_mtime}
            segments={session.dubbing_segments}
            voiceUid={voiceUid}
            speedMode={speed}
          />
        </Panel>
      </div>

      <AlertModal
        open={!!alert}
        title={alert?.title || ''}
        message={alert?.message || ''}
        variant={alert?.variant || 'info'}
        onClose={() => setAlert(null)}
      />

      {cloneManageOpen && supportsClone && (
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 p-4 backdrop-blur-[2px]"
          role="presentation"
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="clone-manage-title"
            className="flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--panel)] shadow-2xl"
          >
            <div className="flex shrink-0 items-center justify-between border-b border-[var(--border)] px-4 py-3">
              <h3 id="clone-manage-title" className="text-sm font-semibold text-[var(--text)]">
                音色管理 · 克隆与音色库
              </h3>
              <button
                type="button"
                onClick={() => closeCloneManage()}
                className="rounded-lg border border-[var(--border)] px-2.5 py-1 text-xs text-[var(--muted)] hover:bg-[var(--bg)]"
              >
                关闭
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-4">
              <ClonePage embedded onVoiceSaved={onCloneLibraryChanged} />
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function ModelField({
  field,
  value,
  onChange,
}: {
  field: TtsModelField
  value: string | number | boolean
  onChange: (v: string | number | boolean) => void
}) {
  if (field.type === 'boolean') {
    return (
      <label className="flex items-center gap-2 text-xs text-[var(--muted)]">
        <input
          type="checkbox"
          checked={Boolean(value)}
          onChange={(e) => onChange(e.target.checked)}
          className="rounded border-[var(--border)]"
        />
        {field.label}
      </label>
    )
  }

  if (field.type === 'select' && field.choices?.length) {
    return (
      <label className="block text-xs text-[var(--muted)]">
        {field.label}
        <select
          value={String(value)}
          onChange={(e) => onChange(e.target.value)}
          className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--panel)] px-2 py-2 text-sm"
        >
          {field.choices.map((c) => (
            <option key={c.value} value={c.value}>
              {c.label}
            </option>
          ))}
        </select>
      </label>
    )
  }

  if (field.type === 'password') {
    return (
      <label className="block text-xs text-[var(--muted)] md:col-span-2">
        {field.label}
        {field.configured && field.hint && (
          <span className="ml-2 text-emerald-400/90">已配置 {field.hint}</span>
        )}
        <input
          type="password"
          placeholder={field.configured ? '留空则不修改' : 'sk-…'}
          value={String(value ?? '')}
          onChange={(e) => onChange(e.target.value)}
          className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--panel)] px-2 py-2 text-sm"
        />
      </label>
    )
  }

  return (
    <label className="block text-xs text-[var(--muted)]">
      {field.label}
      <input
        type={field.type === 'number' ? 'number' : 'text'}
        step={field.step}
        value={String(value ?? '')}
        onChange={(e) =>
          onChange(field.type === 'number' ? Number(e.target.value) : e.target.value)
        }
        className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--panel)] px-2 py-2 text-sm"
      />
    </label>
  )
}

function SegmentTabs<T extends string>({
  value,
  onChange,
  items,
}: {
  value: T
  onChange: (v: T) => void
  items: { id: T; label: string }[]
}) {
  return (
    <div className="inline-flex rounded-xl border border-[var(--border)] bg-[var(--bg)] p-1">
      {items.map((item) => (
        <button
          key={item.id}
          type="button"
          onClick={() => onChange(item.id)}
          className={`rounded-lg px-4 py-1.5 text-sm transition ${
            value === item.id
              ? 'bg-[var(--select-bg)] font-semibold text-[var(--accent)] shadow-sm'
              : 'text-[var(--muted)] hover:text-[var(--text)]'
          }`}
        >
          {item.label}
        </button>
      ))}
    </div>
  )
}

function VoiceGrid({
  title,
  items,
  selected,
  onSelect,
}: {
  title: string
  items: VoiceItem[]
  selected: string
  onSelect: (uid: string) => void
}) {
  if (!items.length) return null
  return (
    <div className={title ? 'mt-2' : ''}>
      {title ? <div className="mb-2 text-xs font-medium text-[var(--muted)]">{title}</div> : null}
      <div className="flex flex-wrap gap-2">
        {items.map((v) => (
          <div
            key={v.uid}
            className={`flex items-center gap-1 rounded-xl border pl-3 pr-1 py-1 transition ${
              selected === v.uid
                ? 'border-[var(--select-border)] bg-[var(--select-bg)]'
                : 'border-[var(--border)] bg-[var(--bg)] hover:border-[var(--select-border)]'
            }`}
          >
            <button
              type="button"
              onClick={() => onSelect(v.uid)}
              className={`py-1 text-xs ${
                selected === v.uid ? 'font-medium text-[var(--accent)]' : 'text-[var(--text)]'
              }`}
            >
              {v.label}
            </button>
            <AudioPreviewButton url={v.preview_url} localPath={v.local_path} title={`试听 ${v.label}`} />
          </div>
        ))}
      </div>
    </div>
  )
}

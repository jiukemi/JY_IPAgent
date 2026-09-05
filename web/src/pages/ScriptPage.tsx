import { useCallback, useEffect, useRef, useState } from 'react'
import { api, mediaUrl, type CompetitorItem } from '../api/client'
import type { SessionSnapshot } from '../types'
import { FileDropZone } from '../components/FileDropZone'
import { PhoneFitVideo } from '../components/PhonePreviewFrame'
import { InAppVideoTheater } from '../components/InAppVideoTheater'
import { useJobQueue } from '../context/JobQueueContext'
import { sameSessionPath } from '../utils/sessionPath'

type Props = {
  session: SessionSnapshot
  onUpdate: (snap: SessionSnapshot) => void
  /** Bumps when settings saved — refresh local/cloud script mode */
  configVersion?: number
}

type ScriptTab = 'extract' | 'rewritten' | 'legal'
type IngestTab = 'local' | 'cloud'

export function ScriptPage({ session, onUpdate, configVersion = 0 }: Props) {
  const jobQueue = useJobQueue()
  const [shareUrl, setShareUrl] = useState(session.share_url || '')
  const [extractText, setExtractText] = useState(session.script_extract || session.script || '')
  const [rewrittenText, setRewrittenText] = useState(session.script_rewritten || '')
  const [legalText, setLegalText] = useState(session.script_legal || '')
  const [scriptTab, setScriptTab] = useState<ScriptTab>(
    session.script_legal?.trim() ? 'legal' : session.script_rewritten?.trim() ? 'rewritten' : 'extract',
  )
  const [ingestTab, setIngestTab] = useState<IngestTab>('local')
  const [log, setLog] = useState('')
  const [busy, setBusy] = useState('')
  const [theaterOpen, setTheaterOpen] = useState(false)
  const [progress, setProgress] = useState<{ pct: number; desc: string } | null>(null)
  const [llmPaused, setLlmPaused] = useState(false)
  const [lastGenMode, setLastGenMode] = useState<'hotwords' | 'role' | null>(null)
  const genAbortRef = useRef<AbortController | null>(null)
  const [intensity, setIntensity] = useState('medium')
  const [legalSource, setLegalSource] = useState<'extract' | 'rewritten'>('extract')
  const [upload, setUpload] = useState<File | null>(null)
  const [saveHint, setSaveHint] = useState('')
  const [browserMsg, setBrowserMsg] = useState('')
  const [needBrowserInstall, setNeedBrowserInstall] = useState(false)
  const [browserForce, setBrowserForce] = useState(false)
  const [browserLoggedIn, setBrowserLoggedIn] = useState<boolean | null>(null)
  const [platforms, setPlatforms] = useState<{ id: string; name: string }[]>([
    { id: 'douyin', name: '抖音' },
    { id: 'kuaishou', name: '快手' },
    { id: 'xiaohongshu', name: '小红书' },
    { id: 'bilibili', name: 'B站' },
    { id: 'channels', name: '视频号' },
  ])
  const [activePlatform, setActivePlatform] = useState('douyin')
  const [funasrWorker, setFunasrWorker] = useState<{ enabled: boolean; running: boolean } | null>(null)
  const [publishCopy, setPublishCopy] = useState({
    title: session.publish_title || '',
    subtitle: session.publish_subtitle || '',
    description: session.publish_description || '',
    topics: session.publish_topics || ([] as string[]),
  })
  const saveTimer = useRef<number | null>(null)

  type Role = {
    id: string
    label: string
    identity: string
    profession: string
    industry: string
    product: string
    audience: string
    selling_points: string
  }
  const newRole = (n = 1): Role => ({
    id: `role_${Date.now()}_${n}`,
    label: `角色${n}`,
    identity: '',
    profession: '',
    industry: '',
    product: '',
    audience: '',
    selling_points: '',
  })
  const [roles, setRoles] = useState<Role[]>([newRole(1)])
  const [activeRoleId, setActiveRoleId] = useState('')
  const [mixRoles, setMixRoles] = useState(false)
  const [durationSec, setDurationSec] = useState(45)
  const [extraReq, setExtraReq] = useState('')
  const [hotwords, setHotwords] = useState<string[]>([])
  const [hotNotes, setHotNotes] = useState('')
  const [hotInput, setHotInput] = useState('')
  const [genOpen, setGenOpen] = useState(true)
  const [competitorUrl, setCompetitorUrl] = useState('')
  const [deepTranscript, setDeepTranscript] = useState(true)
  const [competitors, setCompetitors] = useState<CompetitorItem[]>([])
  const [selectedCompetitorId, setSelectedCompetitorId] = useState('')
  const activeRole = roles.find((r) => r.id === activeRoleId) || roles[0]

  useEffect(() => {
    if (!activeRoleId && roles[0]) setActiveRoleId(roles[0].id)
  }, [roles, activeRoleId])

  useEffect(() => {
    api
      .getSettings()
      .then((res) => {
        setIngestTab(res.settings.script_mode !== 'cloud' ? 'local' : 'cloud')
      })
      .catch(() => setIngestTab('local'))
  }, [session.path, configVersion])

  const refreshCompetitors = useCallback(async () => {
    try {
      const res = await api.competitorsList()
      setCompetitors(res.items || [])
    } catch {
      setCompetitors([])
    }
  }, [])

  useEffect(() => {
    void refreshCompetitors()
  }, [refreshCompetitors])

  const refreshBrowserStatus = useCallback(async () => {
    try {
      const st = await api.browserStatus(activePlatform)
      if ((st as { deferred?: boolean }).deferred) {
        setBrowserMsg(st.message || '浏览器正用于提取，登录检测暂缓（不是掉登录）')
        return
      }
      setBrowserLoggedIn(st.logged_in)
      setBrowserMsg(st.message)
    } catch {
      setBrowserLoggedIn(null)
      setBrowserMsg('无法检测浏览器状态')
    }
  }, [activePlatform])

  // Auto-detect platform from share URL
  useEffect(() => {
    const url = shareUrl.trim()
    if (!url) return
    api
      .browserDetect(url)
      .then((res) => {
        if (res.platform && res.platform !== activePlatform) {
          setActivePlatform(res.platform)
        }
      })
      .catch(() => {})
  }, [shareUrl]) // eslint-disable-line react-hooks/exhaustive-deps

  const refreshFunasrWorker = useCallback(async () => {
    try {
      const st = await api.funasrWorkerStatus()
      setFunasrWorker({ enabled: st.enabled, running: st.running })
    } catch {
      setFunasrWorker(null)
    }
  }, [])

  const toggleFunasrWorker = async () => {
    if (!funasrWorker) return
    setBusy('ASR')
    try {
      if (funasrWorker.running) {
        await api.funasrWorkerStop()
        setLog('已停止 ASR 常驻加速')
      } else {
        const res = await api.funasrWorkerStart()
        if (!res.ok || !res.running) {
          setLog(res.message || 'ASR 常驻启动失败（请检查 FunASR 是否已安装 torch）')
          window.alert(res.message || 'ASR 常驻启动失败，请到设置查看 FunASR / torch 环境')
        } else {
          setLog('ASR 常驻加速已启动')
        }
      }
      await refreshFunasrWorker()
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setLog(`ASR 常驻操作失败：${msg}`)
      window.alert(msg)
    } finally {
      setBusy('')
    }
  }

  const syncFromSession = useCallback((snap: SessionSnapshot) => {
    setExtractText(snap.script_extract || snap.script || '')
    setRewrittenText(snap.script_rewritten || '')
    setLegalText(snap.script_legal || '')
    setShareUrl(snap.share_url || '')
    setPublishCopy({
      title: snap.publish_title || '',
      subtitle: snap.publish_subtitle || '',
      description: snap.publish_description || '',
      topics: snap.publish_topics || [],
    })
  }, [])

  useEffect(() => {
    syncFromSession(session)
  }, [
    session.path,
    session.script,
    session.script_extract,
    session.script_rewritten,
    session.script_legal,
    session.publish_title,
    session.publish_subtitle,
    session.publish_description,
    session.publish_topics,
    syncFromSession,
  ])

  useEffect(() => {
    if (ingestTab === 'cloud') void refreshBrowserStatus()
  }, [refreshBrowserStatus, ingestTab])

  useEffect(() => {
    if (ingestTab !== 'cloud') return
    api.browserPlatforms().then((res) => {
      if (res.platforms?.length) setPlatforms(res.platforms)
    }).catch(() => {})
  }, [ingestTab])

  useEffect(() => {
    if (ingestTab === 'local') void refreshFunasrWorker()
  }, [refreshFunasrWorker, ingestTab])

  const refresh = async () => {
    const snap = await api.sessionSnapshot(session.path)
    onUpdate(snap)
    syncFromSession(snap)
  }

  const persistTab = useCallback(
    async (variant: ScriptTab, text: string) => {
      try {
        await api.saveScriptText(session.path, variant, text)
        setSaveHint('已自动保存')
        window.setTimeout(() => setSaveHint(''), 2000)
      } catch {
        setSaveHint('保存失败')
      }
    },
    [session.path],
  )

  const scheduleSave = (variant: ScriptTab, text: string) => {
    if (saveTimer.current) window.clearTimeout(saveTimer.current)
    saveTimer.current = window.setTimeout(() => {
      void persistTab(variant, text)
    }, 800)
  }

  const onScriptChange = (value: string) => {
    if (scriptTab === 'extract') {
      setExtractText(value)
      scheduleSave('extract', value)
    } else if (scriptTab === 'rewritten') {
      setRewrittenText(value)
      scheduleSave('rewritten', value)
    } else {
      setLegalText(value)
      scheduleSave('legal', value)
    }
  }

  const ensureLlmReady = async (actionLabel: string): Promise<boolean> => {
    try {
      const { settings } = await api.getSettings()
      if ((settings.rewrite_api_key || '').trim()) return true
    } catch {
      /* treat as missing */
    }
    window.alert(
      `未配置文本大模型 Key，无法进行「${actionLabel}」。\n\n请先打开顶栏「设置 → ① 文案」，填写 DeepSeek / OpenAI 兼容 Key 后再试。`,
    )
    return false
  }

  const run = async (label: string, fn: () => Promise<{ log: string; data: Record<string, unknown> }>) => {
    setBusy(label)
    setLog('')
    setProgress(null)
    try {
      const res = await fn()
      setLog(res.log)
      const snap = await api.sessionSnapshot(session.path)
      onUpdate(snap)
      syncFromSession(snap)
      if (label === '仿写') setScriptTab('rewritten')
      if (label === 'AI法务') setScriptTab('legal')
      if (label === '口播' || label === '一键') setScriptTab('extract')
    } catch (e) {
      setLog(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy('')
      setProgress(null)
    }
  }

  /** 文案确认后再点按钮生成；不自动跑 LLM */
  const generatePublishCopy = async (text: string) => {
    const body = text.trim()
    if (!body) {
      setLog('请先确认口播文案')
      return
    }
    if (!(await ensureLlmReady('生成发布文案'))) return
    setBusy('发布文案')
    try {
      const sug = await api.coverSuggest(body, session.path, true)
      if (!sug.ok) {
        setLog(sug.message || '发布文案生成失败')
        return
      }
      setPublishCopy({
        title: sug.title || '',
        subtitle: sug.subtitle || '',
        description: sug.description || '',
        topics: sug.topics || [],
      })
      setLog(
        `已生成发布文案：${sug.title || ''}｜${sug.subtitle || ''}｜标签 ${(sug.topics || []).map((t) => '#' + t).join(' ')}`,
      )
      const snap = await api.sessionSnapshot(session.path)
      onUpdate(snap)
    } catch (e) {
      setLog(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy('')
    }
  }

  const runExtract = () => {
    const isLocal = ingestTab === 'local'
    if (isLocal && !upload) {
      setLog('请先上传本地视频')
      return
    }
    if (!isLocal && !shareUrl.trim()) {
      setLog('请先粘贴分享链接')
      return
    }
    setBusy('一键')
    setLog('')
    setProgress({ pct: 0.05, desc: '加入任务中心…' })
    void (async () => {
      try {
        let refMedia = ''
        if (isLocal && upload) {
          setProgress({ pct: 0.08, desc: '上传本地媒体…' })
          const prep = await api.scriptPrepareMedia(session.path, upload)
          refMedia = prep.ref_media || ''
        }
        const outcome = await jobQueue.enqueue({
          type: 'script_extract',
          title: isLocal ? '本地 ASR 转写' : '链接提取文案',
          force: true,
          payload: {
            session_path: session.path,
            share_url: isLocal ? '' : shareUrl.trim(),
            ref_media: refMedia,
          },
        })
        if (outcome.ok) {
          setLog('已加入任务中心：本地引擎 ASR / 提取在后台运行，可继续其它操作。')
          jobQueue.setCenterOpen(true)
        } else {
          setLog(outcome.message || '当前已有相同提取任务')
        }
      } catch (e) {
        setLog(e instanceof Error ? e.message : String(e))
      } finally {
        setBusy('')
        setProgress(null)
      }
    })()
  }

  useEffect(() => {
    const job = jobQueue.lastFinished
    if (!job || jobQueue.completionTick <= 0) return
    if (job.type !== 'script_extract') return
    const payload = job.payload as { session_path?: string }
    const jobPath = payload.session_path || job.session_path
    if (!sameSessionPath(jobPath, session.path)) return
    if (job.status === 'failed') {
      setLog(job.error || job.message || '提取失败')
      return
    }
    if (job.status === 'cancelled') {
      setLog('提取任务已取消')
      return
    }
    if (job.status !== 'done') return
    const logText = String(job.result?.log || job.message || '提取完成')
    setLog(logText)
    setScriptTab('extract')
    const scriptText = String(job.result?.script || '').trim()
    if (scriptText) {
      setExtractText(scriptText)
    }
    void refresh().then(() => {
      window.dispatchEvent(
        new CustomEvent('agent:session-refresh', { detail: { sessionPath: session.path } }),
      )
    })
    void refreshBrowserStatus()
  }, [jobQueue.completionTick, jobQueue.lastFinished, session.path, refreshBrowserStatus])

  /** CDN 下载完成后立刻刷新预览；ASR 仍在跑时右侧也能先出视频 */
  const activeExtractJob = jobQueue.jobs.find(
    (j) =>
      j.type === 'script_extract' &&
      (j.status === 'queued' || j.status === 'running') &&
      sameSessionPath(j.session_path || (j.payload as { session_path?: string })?.session_path, session.path),
  )

  useEffect(() => {
    if (!activeExtractJob) return
    void refresh()
    const t = window.setInterval(() => {
      void refresh()
    }, 2000)
    return () => window.clearInterval(t)
  }, [activeExtractJob?.id, activeExtractJob?.status, session.path])

  const openBrowserLogin = async () => {
    setBusy('登录')
    try {
      const res = await api.browserLogin(browserForce, activePlatform)
      setBrowserMsg(res.message)
      setBrowserForce(!res.ok)
      const need =
        res.need_install === 'playwright' ||
        /playwright|chromium|浏览器引擎|Executable doesn't exist|chrome/i.test(res.message || '')
      setNeedBrowserInstall(!!need && !res.ok)
      window.setTimeout(() => void refreshBrowserStatus(), 3000)
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setBrowserMsg(msg)
      setNeedBrowserInstall(/playwright|chromium|浏览器引擎|Executable doesn't exist/i.test(msg))
    } finally {
      setBusy('')
    }
  }

  const installBrowserEngine = async () => {
    setBusy('安装浏览器')
    setBrowserMsg('正在安装 Playwright / Chromium… 请到任务中心看进度')
    try {
      const outcome = await jobQueue.enqueue({
        type: 'engine_install',
        title: '安装浏览器引擎 Playwright',
        force: true,
        priority: 20,
        payload: { engine: 'playwright' },
      })
      jobQueue.setCenterOpen(true)
      setBrowserMsg(
        outcome.ok
          ? '已加入任务中心安装浏览器引擎，完成后请再点「浏览器登录」'
          : outcome.message || '安装任务未能加入',
      )
      if (outcome.ok) setNeedBrowserInstall(false)
    } catch (e) {
      setBrowserMsg(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy('')
    }
  }

  const rolesPayload = () => {
    const list = mixRoles ? roles : activeRole ? [activeRole] : roles.slice(0, 1)
    return list.map((r) => ({ ...r }))
  }

  const patchActiveRole = (key: keyof Role, value: string) => {
    if (!activeRole) return
    setRoles((prev) => prev.map((r) => (r.id === activeRole.id ? { ...r, [key]: value } : r)))
  }

  const addRole = () => {
    const r = newRole(roles.length + 1)
    setRoles((prev) => [...prev, r])
    setActiveRoleId(r.id)
  }

  const removeRole = (id: string) => {
    setRoles((prev) => {
      if (prev.length <= 1) return prev
      const next = prev.filter((r) => r.id !== id)
      if (activeRoleId === id) setActiveRoleId(next[0]?.id || '')
      return next
    })
  }

  const generateByMode = async (
    mode: 'hotwords' | 'role' | 'competitor',
    opts?: { continueFrom?: string },
  ) => {
    const labels = { hotwords: '热词成稿', role: '角色成稿', competitor: '对标仿写' } as const
    if (!(await ensureLlmReady(labels[mode]))) return
    setBusy(labels[mode])
    setLog('')
    setProgress({
      pct: 0.05,
      desc: mode === 'hotwords' ? '拉取热词并生成…' : mode === 'competitor' ? '根据对标仿写…' : '按角色生成…',
    })
    try {
      if (mode === 'competitor') {
        setLlmPaused(false)
        if (!selectedCompetitorId) {
          throw new Error('请先在知识库中选择一个对标博主')
        }
        const res = await api.scriptCompetitorAnalyze({
          session_path: session.path,
          competitor_id: selectedCompetitorId,
          roles: rolesPayload(),
          mix_roles: mixRoles,
          duration_sec: durationSec,
          hotwords,
          extra: extraReq,
          save_as: 'rewritten',
        })
        const words = (res.data?.hotwords as string[]) || hotwords
        if (words.length) setHotwords(words)
        setLog(res.log || res.message || '对标仿写完成')
        await refresh()
        setScriptTab('rewritten')
        return
      }

      setLastGenMode(mode)
      setLlmPaused(false)
      const prefix = (opts?.continueFrom || '').trim()
      let acc = prefix
      if (prefix) setRewrittenText(prefix)
      setScriptTab('rewritten')
      const ac = new AbortController()
      genAbortRef.current = ac
      const res = await api.scriptGenerateStream(
        {
          session_path: session.path,
          roles: rolesPayload(),
          mix_roles: mixRoles,
          duration_sec: durationSec,
          hotwords,
          extra: extraReq,
          auto_hotwords: mode === 'hotwords' && !prefix,
          save_as: 'rewritten',
          continue_from: prefix,
        },
        {
          signal: ac.signal,
          onDelta: (t) => {
            acc += t
            setRewrittenText(acc)
          },
          onProgress: (pct, desc) => setProgress({ pct, desc: desc || '流式生成中…' }),
        },
      )
      const script = String(res.data?.script || acc || '')
      if (script) setRewrittenText(script)
      const words = (res.data?.hotwords as string[]) || hotwords
      if (Array.isArray(words) && words.length) setHotwords(words as string[])
      if (res.data?.notes) setHotNotes(String(res.data.notes))
      if (res.paused || ac.signal.aborted) {
        setLlmPaused(true)
        setLog(res.log || '已暂停，可点「继续生成」从断点续写')
      } else {
        setLlmPaused(false)
        setLog(res.log || '文稿已生成')
        await refresh()
      }
    } catch (e) {
      if (genAbortRef.current?.signal.aborted) {
        setLlmPaused(true)
        setLog('已暂停，可点「继续生成」从断点续写')
      } else {
        setLog(e instanceof Error ? e.message : String(e))
      }
    } finally {
      setBusy('')
      setProgress(null)
      genAbortRef.current = null
    }
  }

  const pauseLlm = () => {
    genAbortRef.current?.abort()
  }

  const continueLlm = () => {
    if (!lastGenMode) return
    void generateByMode(lastGenMode, { continueFrom: rewrittenText })
  }

  const saveCompetitor = async () => {
    if (!competitorUrl.trim()) return
    setBusy('入库')
    setLog('')
    setProgress({ pct: 0.05, desc: '抓取对标主页并入库…' })
    try {
      const res = await api.competitorsSave({
        profile_url: competitorUrl.trim(),
        session_path: session.path,
        deep_transcript: deepTranscript,
      })
      const entry = res.data as Partial<CompetitorItem> | undefined
      if (entry?.id) setSelectedCompetitorId(String(entry.id))
      setLog(res.log || res.message || '已保存到知识库')
      await refreshCompetitors()
    } catch (e) {
      setLog(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy('')
      setProgress(null)
    }
  }

  const removeCompetitor = async (id: string) => {
    try {
      await api.competitorsDelete(id)
      if (selectedCompetitorId === id) setSelectedCompetitorId('')
      await refreshCompetitors()
    } catch (e) {
      setLog(e instanceof Error ? e.message : String(e))
    }
  }

  const addHotword = () => {
    const w = hotInput.trim()
    if (!w) return
    if (!hotwords.includes(w)) setHotwords((prev) => [...prev, w])
    setHotInput('')
  }

  const preview = mediaUrl(session.preview_video)
  const displayScript =
    scriptTab === 'extract' ? extractText : scriptTab === 'rewritten' ? rewrittenText : legalText
  const charCount = displayScript.length
  const legalInput =
    legalSource === 'rewritten' && rewrittenText.trim() ? rewrittenText : extractText

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(260px,320px)]">
      <Panel title="01 文案 · 提取 / 仿写 / AI法务">
        <div className="space-y-3">
          <div className="overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--bg)]">
            <div className="flex border-b border-[var(--border)]">
              <TabBtn active={ingestTab === 'local'} onClick={() => setIngestTab('local')}>
                本地提取
              </TabBtn>
              <TabBtn active={ingestTab === 'cloud'} onClick={() => setIngestTab('cloud')}>
                云端提取
              </TabBtn>
            </div>

            {ingestTab === 'local' && (
              <div className="space-y-3 p-3">
                <p className="text-[11px] leading-relaxed text-[var(--muted)]">
                  上传本地视频，用本机 FunASR / SenseVoice 转写提取口播文案，无需分享链接。
                </p>
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-xs">
            <span className="text-[var(--muted)]">
              ASR 常驻加速（SenseVoice）：
              {funasrWorker?.running && <span className="ml-1 text-emerald-400">运行中 · 提速 3-5 倍</span>}
              {funasrWorker && !funasrWorker.running && funasrWorker.enabled && (
                <span className="ml-1 text-amber-400">已启用未启动</span>
              )}
              {funasrWorker && !funasrWorker.enabled && (
                <span className="ml-1 text-[var(--muted)]">未启用（省内存）</span>
              )}
              {funasrWorker === null && <span className="ml-1">检测中…</span>}
              <span className="ml-2 opacity-60">常驻约占 500MB 内存</span>
            </span>
            <div className="flex gap-2">
              <ActionBtn disabled={!!busy} onClick={() => void refreshFunasrWorker()}>
                刷新
              </ActionBtn>
              <ActionBtn
                primary
                disabled={!!busy}
                onClick={() => void toggleFunasrWorker()}
              >
                {busy === 'ASR' ? '…' : funasrWorker?.running ? '停止' : '启动'}
              </ActionBtn>
            </div>
          </div>
                <div className="rounded-xl border-2 border-[var(--accent)]/45 bg-[var(--select-bg)]/50 p-3 shadow-sm">
                  <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <p className="text-sm font-semibold text-[var(--text)]">本地视频上传</p>
                      <p className="mt-0.5 text-[10px] leading-relaxed text-[var(--muted)]">
                        支持 mp4 / mov / webm / mkv，上传后一键转写
                      </p>
                    </div>
                    {upload && (
                      <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] font-medium text-emerald-700 dark:text-emerald-300">
                        已选文件
                      </span>
                    )}
                  </div>
                  <FileDropZone
                    file={upload}
                    onFile={setUpload}
                    accept="video/*,.mp4,.mov,.webm,.mkv,.m4v"
                    icon="🎬"
                    emptyTitle="拖拽本地视频到此处"
                    emptyHint="或点击下方按钮 · mp4 / mov / webm"
                    chooseLabel="上传本地视频"
                    replaceLabel="更换本地视频"
                    accent
                  />
                </div>
                <div className="flex flex-wrap gap-2">
                  <ActionBtn
                    primary
                    disabled={!!busy || !upload}
                    onClick={() => runExtract()}
                  >
                    {busy === '一键' ? '转写中…' : '本地视频转写提取'}
                  </ActionBtn>
                </div>
              </div>
            )}

            {ingestTab === 'cloud' && (
              <div className="space-y-3 p-3">
                <p className="text-[11px] leading-relaxed text-[var(--muted)]">
                  云端路线：粘贴分享链接后，CDN 接口秒级解析直链，再下载到本地（预览只播本地文件）；随后才做 ASR。一键提取会等转写结束才出全文，下载完成后右侧会先出视频。
                </p>
          <div className="rounded-xl border border-[var(--border)] bg-[var(--bg)]">
            <button
              type="button"
              onClick={() => setGenOpen((o) => !o)}
              className="flex w-full items-center justify-between px-3 py-2.5 text-left text-xs"
            >
              <span className="font-medium text-[var(--text)]">角色人设 · 对标知识库 · 生成文案</span>
              <span className="text-[var(--muted)]">{genOpen ? '收起 ▲' : '展开 ▼'}</span>
            </button>
            {genOpen && (
              <div className="space-y-3 border-t border-[var(--border)] px-3 py-3">
                <p className="text-[11px] leading-relaxed text-[var(--muted)]">
                  先填自己的角色人设；对标主页入库后与链接一起保存在知识库。生成可选：拉热词、对标仿写、按角色。文本模型 Key 在设置 → ① 文案。
                </p>

                <div className="flex flex-wrap items-center gap-2">
                  {roles.map((r) => (
                    <button
                      key={r.id}
                      type="button"
                      onClick={() => setActiveRoleId(r.id)}
                      className={`rounded-lg border px-2.5 py-1 text-xs ${
                        (activeRole?.id || '') === r.id
                          ? 'border-[var(--select-border)] bg-[var(--select-bg)] text-[var(--accent)]'
                          : 'border-[var(--border)] text-[var(--muted)]'
                      }`}
                    >
                      {r.label || r.identity || r.profession || '未命名'}
                    </button>
                  ))}
                  <ActionBtn onClick={addRole}>＋角色</ActionBtn>
                  {roles.length > 1 && activeRole && (
                    <button
                      type="button"
                      onClick={() => removeRole(activeRole.id)}
                      className="text-[11px] text-red-400 hover:underline"
                    >
                      删除当前
                    </button>
                  )}
                  <label className="ml-auto flex items-center gap-1.5 text-[11px] text-[var(--muted)]">
                    <input
                      type="checkbox"
                      checked={mixRoles}
                      onChange={(e) => setMixRoles(e.target.checked)}
                    />
                    多角色混合成稿
                  </label>
                </div>

                {activeRole && (
                  <div className="grid gap-2 sm:grid-cols-2">
                    <label className="block text-xs text-[var(--muted)]">
                      角色名称
                      <input
                        value={activeRole.label}
                        onChange={(e) => patchActiveRole('label', e.target.value)}
                        className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--panel)] px-2.5 py-1.5 text-sm"
                      />
                    </label>
                    <label className="block text-xs text-[var(--muted)]">
                      身份
                      <input
                        value={activeRole.identity}
                        onChange={(e) => patchActiveRole('identity', e.target.value)}
                        placeholder="例如：宝妈 / 店长"
                        className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--panel)] px-2.5 py-1.5 text-sm"
                      />
                    </label>
                    <label className="block text-xs text-[var(--muted)]">
                      职业
                      <input
                        value={activeRole.profession}
                        onChange={(e) => patchActiveRole('profession', e.target.value)}
                        placeholder="例如：皮肤管理师"
                        className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--panel)] px-2.5 py-1.5 text-sm"
                      />
                    </label>
                    <label className="block text-xs text-[var(--muted)]">
                      行业 / 赛道
                      <input
                        value={activeRole.industry}
                        onChange={(e) => patchActiveRole('industry', e.target.value)}
                        className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--panel)] px-2.5 py-1.5 text-sm"
                      />
                    </label>
                    <label className="block text-xs text-[var(--muted)]">
                      产品 / 服务
                      <input
                        value={activeRole.product}
                        onChange={(e) => patchActiveRole('product', e.target.value)}
                        className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--panel)] px-2.5 py-1.5 text-sm"
                      />
                    </label>
                    <label className="block text-xs text-[var(--muted)]">
                      目标受众
                      <input
                        value={activeRole.audience}
                        onChange={(e) => patchActiveRole('audience', e.target.value)}
                        className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--panel)] px-2.5 py-1.5 text-sm"
                      />
                    </label>
                    <label className="block text-xs text-[var(--muted)] sm:col-span-2">
                      卖点
                      <input
                        value={activeRole.selling_points}
                        onChange={(e) => patchActiveRole('selling_points', e.target.value)}
                        className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--panel)] px-2.5 py-1.5 text-sm"
                      />
                    </label>
                  </div>
                )}

                <div className="grid gap-2 sm:grid-cols-2">
                  <label className="block text-xs text-[var(--muted)]">
                    口播时长（秒）
                    <input
                      type="number"
                      min={20}
                      max={180}
                      value={durationSec}
                      onChange={(e) => setDurationSec(Number(e.target.value) || 45)}
                      className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--panel)] px-2.5 py-1.5 text-sm"
                    />
                  </label>
                  <label className="block text-xs text-[var(--muted)]">
                    额外要求
                    <input
                      value={extraReq}
                      onChange={(e) => setExtraReq(e.target.value)}
                      placeholder="可选"
                      className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--panel)] px-2.5 py-1.5 text-sm"
                    />
                  </label>
                </div>

                <div className="rounded-lg border border-[var(--border)] bg-[var(--panel)] p-2.5 space-y-2">
                  <p className="text-[11px] font-medium text-[var(--text)]">对标博主知识库</p>
                  <label className="block text-xs text-[var(--muted)]">
                    对标主页链接（别人的号）
                    <input
                      value={competitorUrl}
                      onChange={(e) => setCompetitorUrl(e.target.value)}
                      placeholder="https://www.douyin.com/user/…"
                      className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-2.5 py-1.5 text-sm"
                    />
                  </label>
                  <div className="flex flex-wrap items-center gap-2">
                    <label className="flex items-center gap-1.5 text-[11px] text-[var(--muted)]">
                      <input
                        type="checkbox"
                        checked={deepTranscript}
                        onChange={(e) => setDeepTranscript(e.target.checked)}
                      />
                      深度提取口播样本
                    </label>
                    <ActionBtn
                      primary
                      disabled={!!busy || !competitorUrl.trim()}
                      onClick={() => void saveCompetitor()}
                    >
                      {busy === '入库' ? '入库中…' : '保存对标博主并存入知识库'}
                    </ActionBtn>
                  </div>
                  {competitors.length === 0 ? (
                    <p className="text-[11px] text-[var(--muted)]">暂无对标，粘贴主页链接后保存。</p>
                  ) : (
                    <ul className="space-y-1.5">
                      {competitors.map((c) => (
                        <li
                          key={c.id}
                          className={`flex flex-wrap items-start gap-2 rounded-lg border px-2 py-1.5 text-[11px] ${
                            selectedCompetitorId === c.id
                              ? 'border-[var(--select-border)] bg-[var(--select-bg)]'
                              : 'border-[var(--border)] bg-[var(--bg)]'
                          }`}
                        >
                          <button
                            type="button"
                            className="min-w-0 flex-1 text-left"
                            onClick={() => setSelectedCompetitorId(c.id)}
                          >
                            <span className="font-medium text-[var(--text)]">
                              {c.nickname || c.id}
                            </span>
                            <span className="ml-1 text-[var(--muted)]">
                              · {c.sample_count} 样本
                            </span>
                            {c.profile_url && (
                              <a
                                href={c.profile_url}
                                target="_blank"
                                rel="noreferrer"
                                className="mt-0.5 block truncate text-[var(--accent)] hover:underline"
                                onClick={(e) => e.stopPropagation()}
                              >
                                {c.profile_url}
                              </a>
                            )}
                          </button>
                          <button
                            type="button"
                            className="shrink-0 text-red-400 hover:underline"
                            onClick={() => void removeCompetitor(c.id)}
                          >
                            删除
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                <div className="flex flex-wrap gap-2">
                  <ActionBtn primary disabled={!!busy} onClick={() => void generateByMode('hotwords')}>
                    {busy === '热词成稿' ? '生成中…' : '拉热词生成文案'}
                  </ActionBtn>
                  <ActionBtn
                    primary
                    disabled={!!busy || !selectedCompetitorId}
                    onClick={() => void generateByMode('competitor')}
                  >
                    {busy === '对标仿写' ? '仿写中…' : '根据对标仿写'}
                  </ActionBtn>
                  <ActionBtn primary disabled={!!busy} onClick={() => void generateByMode('role')}>
                    {busy === '角色成稿' ? '生成中…' : '按角色生成文稿'}
                  </ActionBtn>
                  {(busy === '热词成稿' || busy === '角色成稿') && (
                    <ActionBtn onClick={pauseLlm}>暂停</ActionBtn>
                  )}
                  {llmPaused && !busy && lastGenMode && (
                    <ActionBtn primary onClick={continueLlm}>
                      继续生成
                    </ActionBtn>
                  )}
                </div>
                <p className="text-[10px] text-[var(--muted)]">
                  热词/角色成稿支持流式输出；生成中可暂停，再点「继续生成」从断点续写。
                </p>
                {hotNotes && (
                  <p className="rounded-lg border border-[var(--border)] bg-[var(--panel)] px-2.5 py-1.5 text-[11px] text-[var(--muted)]">
                    {hotNotes}
                  </p>
                )}

                <div className="space-y-2">
                  <div className="flex flex-wrap gap-1.5">
                    {hotwords.map((w) => (
                      <button
                        key={w}
                        type="button"
                        title="点击移除"
                        onClick={() => setHotwords((prev) => prev.filter((x) => x !== w))}
                        className="rounded-md border border-[var(--select-border)] bg-[var(--select-bg)] px-2 py-0.5 text-[11px] text-[var(--accent)]"
                      >
                        {w} ×
                      </button>
                    ))}
                  </div>
                  <div className="flex gap-2">
                    <input
                      value={hotInput}
                      onChange={(e) => setHotInput(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && addHotword()}
                      placeholder="可选：手动加热词，回车确认"
                      className="min-w-0 flex-1 rounded-lg border border-[var(--border)] bg-[var(--panel)] px-2.5 py-1.5 text-sm"
                    />
                    <ActionBtn onClick={addHotword}>添加</ActionBtn>
                  </div>
                </div>
              </div>
            )}
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-xs">
            <div className="flex items-center gap-2">
              <select
                value={activePlatform}
                onChange={(e) => {
                  setActivePlatform(e.target.value)
                  setBrowserLoggedIn(null)
                }}
                className="rounded-lg border border-[var(--border)] bg-[var(--panel)] px-2 py-1 text-xs"
              >
                {platforms.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
              <span className="text-[var(--muted)]">
                浏览器登录：
                {browserLoggedIn === true && <span className="ml-1 text-emerald-400">已登录</span>}
                {browserLoggedIn === false && <span className="ml-1 text-amber-400">未登录</span>}
                {browserLoggedIn === null && <span className="ml-1">检测中…</span>}
                {browserMsg && <span className="ml-2 opacity-70">{browserMsg}</span>}
              </span>
            </div>
            <div className="flex gap-2">
              <ActionBtn disabled={!!busy} onClick={() => void refreshBrowserStatus()}>
                刷新
              </ActionBtn>
              {needBrowserInstall && (
                <ActionBtn disabled={!!busy} onClick={() => void installBrowserEngine()}>
                  {busy === '安装浏览器' ? '安装中…' : '一键安装浏览器引擎'}
                </ActionBtn>
              )}
              <ActionBtn primary disabled={!!busy} onClick={() => void openBrowserLogin()}>
                {busy === '登录' ? '…' : browserForce ? '强制重开' : '浏览器登录'}
              </ActionBtn>
            </div>
          </div>
          <label className="block text-xs text-[var(--muted)]">
            分享链接（一键 ASR 提取）
            <textarea
              value={shareUrl}
              onChange={(e) => setShareUrl(e.target.value)}
              rows={2}
              placeholder="粘贴抖音/快手/小红书/B站/视频号分享链接或整段分享文案（支持 weixin.qq.com/sph、channels.weixin.qq.com）"
              className="mt-1 w-full rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm leading-snug"
            />
          </label>
                <div className="flex flex-wrap gap-2">
                  <ActionBtn
                    primary
                    disabled={!!busy || !shareUrl.trim()}
                    onClick={() => runExtract()}
                  >
                    {busy === '一键' ? '提取中…' : '链接一键 ASR 提取文案'}
                  </ActionBtn>
                  <ActionBtn disabled={!!busy || !shareUrl.trim()} onClick={() => run('CDN', () => api.scriptCdn(session.path, shareUrl))}>
                    {busy === 'CDN' ? '…' : 'CDN'}
                  </ActionBtn>
                </div>
              </div>
            )}
          </div>

          {progress && (
            <div className="rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3 py-2">
              <div className="mb-1 flex items-center justify-between text-xs text-[var(--muted)]">
                <span>{progress.desc || '处理中…'}</span>
                <span>{Math.round(progress.pct * 100)}%</span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-[var(--panel)]">
                <div
                  className="h-full rounded-full bg-[var(--accent)] transition-all duration-300"
                  style={{ width: `${Math.max(3, progress.pct * 100)}%` }}
                />
              </div>
            </div>
          )}

          <div className="rounded-xl border border-[var(--border)] bg-[var(--bg)]">
            <div className="flex border-b border-[var(--border)]">
              <TabBtn active={scriptTab === 'extract'} onClick={() => setScriptTab('extract')}>
                原提取文案
                {extractText.trim() && <span className="ml-1 opacity-60">{extractText.length}字</span>}
              </TabBtn>
              <TabBtn active={scriptTab === 'rewritten'} onClick={() => setScriptTab('rewritten')}>
                仿写文案
                {rewrittenText.trim() && <span className="ml-1 opacity-60">{rewrittenText.length}字</span>}
              </TabBtn>
              <TabBtn active={scriptTab === 'legal'} onClick={() => setScriptTab('legal')}>
                AI法务
                {legalText.trim() && <span className="ml-1 opacity-60">{legalText.length}字</span>}
              </TabBtn>
            </div>

            <div className="p-3">
              {scriptTab === 'rewritten' && !rewrittenText.trim() && !extractText.trim() ? (
                <p className="py-8 text-center text-sm text-[var(--muted)]">
                  请先提取口播文案，再点击下方「仿写生成」
                </p>
              ) : scriptTab === 'legal' && !legalText.trim() && !extractText.trim() ? (
                <p className="py-8 text-center text-sm text-[var(--muted)]">
                  请先提取或仿写文案，再运行 AI法务审查
                </p>
              ) : scriptTab === 'rewritten' && !rewrittenText.trim() ? (
                <p className="mb-2 text-xs text-[var(--muted)]">尚未仿写，将基于原提取文案生成（DeepSeek 等 LLM）</p>
              ) : scriptTab === 'legal' && !legalText.trim() ? (
                <p className="mb-2 text-xs text-[var(--muted)]">审查后将输出合规改写文案，详情见运行日志</p>
              ) : null}

              <textarea
                value={displayScript}
                onChange={(e) => onScriptChange(e.target.value)}
                rows={8}
                placeholder={
                  scriptTab === 'extract'
                    ? '提取口播后显示原文案…'
                    : scriptTab === 'rewritten'
                      ? '仿写结果将显示在这里，也可手动编辑'
                      : 'AI法务合规文案将显示在这里'
                }
                className="w-full resize-y rounded-lg border border-[var(--border)] bg-[var(--panel)] px-3 py-2 text-sm leading-relaxed min-h-[10rem]"
              />

              <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-xs text-[var(--muted)]">
                <span>
                  {charCount} 字
                  {saveHint && <span className="ml-2 text-[var(--accent)]">{saveHint}</span>}
                </span>
                <span>保存后自动用于 ② 配音</span>
              </div>

              {scriptTab === 'rewritten' && (
                <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-[var(--border)] pt-3">
                  <select
                    value={intensity}
                    onChange={(e) => setIntensity(e.target.value)}
                    className="rounded-lg border border-[var(--border)] bg-[var(--panel)] px-2 py-1.5 text-xs"
                  >
                    <option value="light">轻量润色</option>
                    <option value="medium">中等仿写</option>
                    <option value="strong">强力改写</option>
                  </select>
                  <ActionBtn
                    disabled={!!busy || !extractText.trim()}
                    onClick={() => {
                      void (async () => {
                        try {
                          const { settings } = await api.getSettings()
                          const hasKey = Boolean((settings.rewrite_api_key || '').trim())
                          if (!hasKey) {
                            const ok = window.confirm(
                              '未配置文本大模型 Key。\n\n确定用本地规则润色（效果有限）？\n取消后请到「设置 → ① 文案」填写 Key。',
                            )
                            if (!ok) return
                          }
                          await run('仿写', () => api.scriptRewrite(session.path, extractText, intensity))
                        } catch (e) {
                          setLog(e instanceof Error ? e.message : String(e))
                        }
                      })()
                    }}
                  >
                    {busy === '仿写' ? '仿写中…' : '仿写生成'}
                  </ActionBtn>
                  <ActionBtn
                    disabled={!!busy || !(rewrittenText.trim() || extractText.trim())}
                    onClick={() =>
                      void generatePublishCopy(rewrittenText.trim() || extractText.trim())
                    }
                  >
                    {busy === '发布文案' ? '生成中…' : '生成标题/简介/标签'}
                  </ActionBtn>
                </div>
              )}

              {(publishCopy.title || publishCopy.topics.length > 0) && (
                <div className="mt-3 space-y-2 rounded-lg border border-[var(--border)] bg-[var(--panel)] p-3">
                  <p className="text-xs font-medium text-[var(--text)]">
                    发布文案预览（确认文案后生成 · 封面/发布页自动带入）
                  </p>
                  <p className="text-sm text-[var(--text)]">
                    <span className="text-[var(--muted)]">标题：</span>
                    {publishCopy.title || '—'}
                  </p>
                  <p className="text-sm text-[var(--text)]">
                    <span className="text-[var(--muted)]">副标题：</span>
                    {publishCopy.subtitle || '—'}
                  </p>
                  {publishCopy.description && (
                    <p className="text-xs leading-relaxed text-[var(--muted)] line-clamp-3">
                      {publishCopy.description}
                    </p>
                  )}
                  {publishCopy.topics.length > 0 && (
                    <p className="text-xs text-[var(--accent)]">
                      {publishCopy.topics.map((t) => `#${t}`).join(' ')}
                    </p>
                  )}
                </div>
              )}

              {scriptTab === 'legal' && (
                <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-[var(--border)] pt-3">
                  <select
                    value={legalSource}
                    onChange={(e) => setLegalSource(e.target.value as 'extract' | 'rewritten')}
                    className="rounded-lg border border-[var(--border)] bg-[var(--panel)] px-2 py-1.5 text-xs"
                  >
                    <option value="extract">基于原提取文案</option>
                    <option value="rewritten">基于仿写文案</option>
                  </select>
                  <ActionBtn
                    disabled={!!busy || !legalInput.trim()}
                    onClick={() =>
                      void (async () => {
                        if (!(await ensureLlmReady('AI法务审查'))) return
                        await run('AI法务', () => api.scriptLegal(session.path, legalInput, legalSource))
                      })()
                    }
                  >
                    {busy === 'AI法务' ? '审查中…' : 'AI法务审查'}
                  </ActionBtn>
                </div>
              )}
            </div>
          </div>

          {log && (
            <details className="rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-xs">
              <summary className="cursor-pointer select-none text-[var(--muted)]">运行日志</summary>
              <pre className="mt-2 max-h-32 overflow-auto whitespace-pre-wrap text-[var(--muted)]">{log}</pre>
            </details>
          )}
        </div>
      </Panel>

      <Panel title="竖屏预览 9:16" className="lg:sticky lg:top-4 lg:self-start">
        <div className="mb-1 flex items-center justify-between gap-2">
          <span className="text-[11px] text-[var(--muted)]">参考视频</span>
          {preview && (
            <button
              type="button"
              className="rounded border border-[var(--accent)]/40 px-2 py-0.5 text-[10px] font-medium text-[var(--accent)] hover:bg-[var(--select-bg)]"
              onClick={() => setTheaterOpen(true)}
            >
              应用内全屏
            </button>
          )}
        </div>
        <div className="mx-auto w-full max-w-[280px]">
          <div className="relative aspect-[9/16] overflow-hidden rounded-2xl border border-[var(--border)] bg-black shadow-lg">
            {preview ? (
              <PhoneFitVideo key={session.preview_video || 'preview'} src={preview} controls preload="metadata" />
            ) : (
              <div className="flex h-full flex-col items-center justify-center gap-2 px-4 text-center text-xs text-[var(--muted)]">
                <span className="text-2xl opacity-40">▶</span>
                {activeExtractJob ? (
                  <>
                    <span className="text-[var(--accent)]">
                      {activeExtractJob.status === 'queued' ? '排队中…' : '提取进行中…'}
                    </span>
                    <span className="leading-relaxed">
                      {activeExtractJob.message ||
                        'CDN 解析很快；正在下载到本地后才会出预览，随后才 ASR'}
                    </span>
                    <span className="opacity-70">
                      {Math.round(Math.max(0, Math.min(1, activeExtractJob.progress || 0)) * 100)}%
                    </span>
                  </>
                ) : (
                  <>
                    <span>CDN 解析本身很快</span>
                    <span>但会先下载到本地再显示预览（不是边播边拉远程）</span>
                  </>
                )}
              </div>
            )}
          </div>
        </div>
        {activeExtractJob && preview && (
          <p className="mt-2 text-center text-[10px] text-[var(--muted)]">
            视频已就绪 · 文案 ASR 仍在后台进行（{activeExtractJob.message || '转写中'}）
          </p>
        )}
        {session.cdn_md && (
          <details className="mt-3 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-2 py-1.5 text-[10px]">
            <summary className="cursor-pointer text-[var(--muted)]">CDN 信息</summary>
            <pre className="mt-1 max-h-24 overflow-auto whitespace-pre-wrap">{session.cdn_md}</pre>
          </details>
        )}
      </Panel>

      <InAppVideoTheater
        open={theaterOpen && !!preview}
        src={preview || ''}
        title="参考视频 · 应用内全屏"
        onClose={() => setTheaterOpen(false)}
      />
    </div>
  )
}

export function TabBtn({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex-1 px-3 py-2.5 text-xs font-medium transition ${
        active
          ? 'border-b-2 border-[var(--accent)] text-[var(--accent)] bg-[var(--select-bg)]'
          : 'text-[var(--muted)] hover:text-[var(--text)]'
      }`}
    >
      {children}
    </button>
  )
}

export function Panel({ title, children, className = '' }: { title: string; children: React.ReactNode; className?: string }) {
  return (
    <section className={`ui-card p-4 sm:p-5 ${className}`}>
      <h2 className="mb-3 text-sm font-semibold tracking-wide text-[var(--text)]">{title}</h2>
      {children}
    </section>
  )
}

export function ActionBtn({
  children,
  onClick,
  disabled,
  primary,
}: {
  children: React.ReactNode
  onClick: () => void
  disabled?: boolean
  primary?: boolean
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={`rounded-xl px-3.5 py-2 text-xs font-semibold transition disabled:opacity-50 ${
        primary
          ? 'btn-primary'
          : 'border border-[var(--border)] bg-[var(--panel)] text-[var(--text)] hover:border-[var(--select-border)] hover:bg-[var(--select-bg)]'
      }`}
    >
      {children}
    </button>
  )
}

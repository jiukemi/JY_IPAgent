import { useCallback, useEffect, useState } from 'react'
import { api } from './api/client'
import { AssetCenterModal } from './components/AssetCenterModal'
import { SessionBar } from './components/SessionBar'
import { SessionModal } from './components/SessionModal'
import { SettingsModal } from './components/SettingsModal'
import { ResourceFooter } from './components/ResourceFooter'
import { Sidebar } from './components/Sidebar'
import { TaskCenterModal } from './components/TaskCenterModal'
import { AvatarPage } from './pages/AvatarPage'
import { PublishPage } from './pages/PublishPage'
import { ScriptPage } from './pages/ScriptPage'
import { TtsPage } from './pages/TtsPage'
import type { SessionItem, SessionSnapshot, StepId } from './types'
import { applyTheme, getInitialTheme, type ThemeId } from './theme'
import { JobQueueProvider, useJobQueue } from './context/JobQueueContext'
import { FreePrivateNoticeModal } from './components/FreePrivateNoticeModal'

const emptySnap = (): SessionSnapshot => ({
  path: '',
  name: '',
  script: '',
  script_extract: '',
  script_rewritten: '',
  script_legal: '',
  share_url: '',
  cdn_md: '',
  preview_video: null,
  dubbing_audio: null,
  selected_dub: null,
  selected_lipsync: null,
  dubs: [],
  lipsyncs: [],
  lipsync_video: null,
  media_input: null,
  tts_log: '',
  lipsync_log: '',
})

function JobActiveBanner() {
  const { activeCount, jobs, setCenterOpen, cancelJob } = useJobQueue()
  if (activeCount <= 0) return null
  const running = jobs.find((j) => j.status === 'running')
  const typeHint =
    running?.type === 'avatar_lipsync'
      ? '口播'
      : running?.type === 'tts_synthesize'
        ? '配音'
        : running?.type === 'publish_run'
          ? '成片'
          : running
            ? '任务'
            : '排队'
  const pct = Math.round(Math.max(0, Math.min(1, running?.progress || 0)) * 100)
  return (
    <div className="mx-auto mt-2 w-full max-w-[1600px] px-5">
      <div className="rounded-[var(--card-radius)] border border-[var(--info-border)] bg-[var(--info-bg)] px-4 py-2">
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
          <span className="font-medium text-[var(--accent)]">
            {running
              ? `${typeHint}进行中 · ${running.message || running.title} (${pct}%) · 共 ${activeCount} 个任务`
              : `有 ${activeCount} 个任务在队列中`}
          </span>
          <div className="flex items-center gap-3">
            {running && (
              <button
                type="button"
                onClick={() => void cancelJob(running.id)}
                className="rounded border border-red-500/40 px-2 py-0.5 text-red-600 hover:bg-red-500/10"
              >
                终止
              </button>
            )}
            <button
              type="button"
              onClick={() => setCenterOpen(true)}
              className="font-semibold text-[var(--accent)] underline"
            >
              打开任务中心
            </button>
          </div>
        </div>
        {running && (
          <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-black/5">
            <div
              className="h-full rounded-full bg-[var(--accent)] transition-all duration-300"
              style={{ width: `${Math.max(3, pct)}%` }}
            />
          </div>
        )}
      </div>
    </div>
  )
}

function AppShell({
  session,
  setSession,
  sessions,
  step,
  setStep,
  theme,
  changeTheme,
  sessionsOpen,
  setSessionsOpen,
  settingsOpen,
  setSettingsOpen,
  assetsOpen,
  setAssetsOpen,
  settingsFocus,
  setSettingsFocus,
  configVersion,
  setConfigVersion,
  voiceVersion,
  setVoiceVersion,
  reloadSessions,
  loadActive,
  switchSession,
  newSession,
}: {
  session: SessionSnapshot
  setSession: React.Dispatch<React.SetStateAction<SessionSnapshot>>
  sessions: SessionItem[]
  step: StepId
  setStep: (s: StepId) => void
  theme: ThemeId
  changeTheme: (t: ThemeId) => void
  sessionsOpen: boolean
  setSessionsOpen: (v: boolean) => void
  settingsOpen: boolean
  setSettingsOpen: (v: boolean) => void
  assetsOpen: boolean
  setAssetsOpen: (v: boolean) => void
  settingsFocus: 'script' | 'tts' | 'avatar' | 'publish' | 'env' | undefined
  setSettingsFocus: (v: 'script' | 'tts' | 'avatar' | 'publish' | 'env' | undefined) => void
  configVersion: number
  setConfigVersion: React.Dispatch<React.SetStateAction<number>>
  voiceVersion: number
  setVoiceVersion: React.Dispatch<React.SetStateAction<number>>
  reloadSessions: (current?: string) => Promise<void>
  loadActive: () => Promise<void>
  switchSession: (path: string) => Promise<void>
  newSession: () => Promise<void>
}) {
  const jobQueue = useJobQueue()

  return (
    <div className="flex h-full min-h-screen flex-col bg-[var(--bg)] text-[var(--text)]">
      <SessionBar
        name={session.name}
        path={session.path}
        sessions={sessions}
        theme={theme}
        activeJobCount={jobQueue.activeCount}
        onThemeChange={changeTheme}
        onOpenSessions={() => setSessionsOpen(true)}
        onOpenSettings={() => {
          setSettingsFocus(undefined)
          setSettingsOpen(true)
        }}
        onOpenAssets={() => setAssetsOpen(true)}
        onOpenTasks={() => jobQueue.setCenterOpen(true)}
      />
      <Sidebar active={step} onChange={setStep} />
      <JobActiveBanner />
      <main className="mx-auto w-full max-w-[1600px] flex-1 overflow-y-auto px-5 py-4">
        {!session.path ? (
          <p className="text-[var(--muted)]">正在加载会话…</p>
        ) : (
          <>
            <div className={step === 'script' ? 'contents' : 'hidden'}>
              <ScriptPage session={session} onUpdate={setSession} configVersion={configVersion} />
            </div>
            {(step === 'tts' || step === 'clone') && (
              <TtsPage
                session={session}
                onUpdate={setSession}
                onOpenSettings={(section) => {
                  setSettingsFocus(section === 'env' ? 'env' : section === 'tts' ? 'tts' : undefined)
                  setSettingsOpen(true)
                }}
                configVersion={configVersion}
                voiceVersion={voiceVersion}
                onVoiceSaved={() => setVoiceVersion((v) => v + 1)}
              />
            )}
            <div className={step === 'avatar' ? 'contents' : 'hidden'} aria-hidden={step !== 'avatar'}>
              <AvatarPage session={session} onUpdate={setSession} />
            </div>
            {step === 'publish' && <PublishPage session={session} onUpdate={setSession} />}
          </>
        )}
      </main>
      <ResourceFooter />

      <SessionModal
        open={sessionsOpen}
        sessions={sessions}
        currentPath={session.path}
        onClose={() => setSessionsOpen(false)}
        onSwitch={switchSession}
        onDelete={async (path) => {
          await api.deleteSession(path)
          await loadActive()
        }}
        onRename={async (path, name) => {
          await api.renameSession(path, name)
          await reloadSessions(session.path)
          if (path === session.path) setSession((s) => ({ ...s, name }))
        }}
        onNewSession={() => void newSession()}
      />

      <AssetCenterModal open={assetsOpen} onClose={() => setAssetsOpen(false)} />
      <TaskCenterModal />

      <SettingsModal
        open={settingsOpen}
        onClose={() => {
          setSettingsOpen(false)
          setSettingsFocus(undefined)
        }}
        onSaved={() => {
          void loadActive()
          setConfigVersion((v) => v + 1)
        }}
        focusSection={settingsFocus}
        configVersion={configVersion}
      />
    </div>
  )
}

function AppMain() {
  const [step, setStep] = useState<StepId>('script')
  const [session, setSession] = useState<SessionSnapshot>(emptySnap())
  const [sessions, setSessions] = useState<SessionItem[]>([])
  const [sessionsOpen, setSessionsOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [assetsOpen, setAssetsOpen] = useState(false)
  const [settingsFocus, setSettingsFocus] = useState<
    'script' | 'tts' | 'avatar' | 'publish' | 'env' | undefined
  >()
  const [configVersion, setConfigVersion] = useState(0)
  const [voiceVersion, setVoiceVersion] = useState(0)
  const [theme, setTheme] = useState<ThemeId>(() => getInitialTheme())

  const changeTheme = (next: ThemeId) => {
    setTheme(next)
    applyTheme(next)
  }

  const reloadSessions = useCallback(async (current?: string) => {
    const list = await api.listSessions(current)
    setSessions(list)
  }, [])

  const loadActive = useCallback(async () => {
    const active = await api.activeSession()
    const snap = await api.sessionSnapshot(active.path)
    setSession(snap)
    await reloadSessions(active.path)
  }, [reloadSessions])

  useEffect(() => {
    loadActive().catch((e) => console.error(e))
  }, [loadActive])

  const switchSession = async (path: string) => {
    const snap = await api.sessionSnapshot(path)
    setSession(snap)
    setSessionsOpen(false)
    await reloadSessions(path)
  }

  const newSession = async () => {
    const snap = await api.createSession()
    setSession(snap)
    await reloadSessions(snap.path)
  }

  return (
    <JobQueueProvider sessionPath={session.path}>
      <AppShell
        session={session}
        setSession={setSession}
        sessions={sessions}
        step={step}
        setStep={setStep}
        theme={theme}
        changeTheme={changeTheme}
        sessionsOpen={sessionsOpen}
        setSessionsOpen={setSessionsOpen}
        settingsOpen={settingsOpen}
        setSettingsOpen={setSettingsOpen}
        assetsOpen={assetsOpen}
        setAssetsOpen={setAssetsOpen}
        settingsFocus={settingsFocus}
        setSettingsFocus={setSettingsFocus}
        configVersion={configVersion}
        setConfigVersion={setConfigVersion}
        voiceVersion={voiceVersion}
        setVoiceVersion={setVoiceVersion}
        reloadSessions={reloadSessions}
        loadActive={loadActive}
        switchSession={switchSession}
        newSession={newSession}
      />
    </JobQueueProvider>
  )
}

export default function App() {
  return (
    <>
      <FreePrivateNoticeModal />
      <AppMain />
    </>
  )
}

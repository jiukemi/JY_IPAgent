import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import { DesktopRuntimePanel } from './DesktopRuntimePanel'
import { ModelSetupPanel } from './ModelSetupPanel'
import { QuarkAccelPanel } from './QuarkAccelPanel'
import { HeyGemInstallWizard } from './HeyGemInstallWizard'
import type { SettingsPayload } from '../types'
import { APP_NAME, APP_TAGLINE, FEEDBACK_EMAIL, FEEDBACK_MAILTO, OPEN_SOURCE_DISCLAIMER, TIP_BLURB, TIP_QR_SRC, TIP_TITLE } from '../brand'
import {
  REPO_THIRD_PARTY_DOC,
  THIRD_PARTY_NOTICE_TITLE,
  THIRD_PARTY_ROWS,
  THIRD_PARTY_SUMMARY,
  AI_COMPLIANCE_NOTE,
} from '../content/thirdPartyNotices'

type WorkerState = { enabled: boolean; running: boolean } | null

type Props = {
  open: boolean
  onClose: () => void
  onSaved: () => void
  focusSection?: 'script' | 'tts' | 'avatar' | 'publish' | 'env'
  configVersion?: number
  onCheckUpdates?: () => void
}

const MODES = [
  { value: 'local', label: '本地' },
  { value: 'cloud', label: '云端' },
]

type SettingsTab = 'engines' | 'install' | 'about'

const SETTINGS_TABS: { id: SettingsTab; label: string }[] = [
  { id: 'engines', label: '全局引擎设置' },
  { id: 'install', label: '特殊引擎安装' },
  { id: 'about', label: '关于我们' },
]

export function SettingsModal({
  open,
  onClose,
  onSaved,
  focusSection,
  configVersion = 0,
  onCheckUpdates,
}: Props) {
  const [settings, setSettings] = useState<SettingsPayload | null>(null)
  const [engines, setEngines] = useState<
    Record<
      string,
      {
        choices: { value: string; label: string; hardware?: string }[]
        choices_local?: { value: string; label: string; hardware?: string }[]
        choices_cloud?: { value: string; label: string; hardware?: string }[]
      }
    >
  >({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [funasrWorker, setFunasrWorker] = useState<WorkerState>(null)
  const [ttsWorker, setTtsWorker] = useState<WorkerState>(null)
  const [workerBusy, setWorkerBusy] = useState('')
  const [promptItems, setPromptItems] = useState<
    Array<{
      id: string
      label: string
      hint?: string
      value: string
      default: string
      modified: boolean
    }>
  >([])
  const [promptsOpen, setPromptsOpen] = useState(false)
  const [promptBusy, setPromptBusy] = useState(false)
  const [promptMsg, setPromptMsg] = useState('')
  const [tab, setTab] = useState<SettingsTab>('engines')
  const loadedConfigRef = useRef<number | null>(null)

  useEffect(() => {
    if (!open) return
    let cancelled = false
    const cacheHit = loadedConfigRef.current === configVersion && settings != null
    if (cacheHit) return

    setError('')
    api
      .getSettings()
      .then((res) => {
        if (cancelled) return
        setSettings(res.settings)
        setEngines(res.engines as typeof engines)
        loadedConfigRef.current = configVersion
      })
      .catch((e) => {
        if (cancelled) return
        setError(e instanceof Error ? e.message : String(e))
      })
    api.funasrWorkerStatus().then((s) => {
      if (!cancelled) setFunasrWorker(s)
    }).catch(() => {
      if (!cancelled) setFunasrWorker(null)
    })
    api.ttsWorkerStatus().then((s) => {
      if (!cancelled) setTtsWorker(s)
    }).catch(() => {
      if (!cancelled) setTtsWorker(null)
    })
    api
      .getTextPrompts()
      .then((r) => {
        if (!cancelled) setPromptItems(r.items || [])
      })
      .catch(() => {
        if (!cancelled) setPromptItems([])
      })
    return () => {
      cancelled = true
    }
    // settings intentionally omitted: used only as cache presence check
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, configVersion])

  useEffect(() => {
    if (!open || !focusSection || !settings) return
    setTab(focusSection === 'env' ? 'install' : 'engines')
    const id = `settings-${focusSection}`
    requestAnimationFrame(() => {
      document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    })
  }, [open, focusSection, settings])

  if (!open) return null

  if (!settings) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-4 backdrop-blur-[2px]">
        <div className="w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--panel)] p-5 shadow-xl">
          <h2 className="text-base font-semibold text-[var(--text)]">设置</h2>
          {error ? (
            <div className="mt-3 space-y-3">
              <p className="text-sm text-red-400">无法加载设置：{error}</p>
              <p className="text-xs text-[var(--muted)]">
                常见原因：配置文件缺失或后端未就绪。可关闭后重开软件，或删除运行时目录后重试。
              </p>
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={onClose}
                  className="rounded-lg border border-[var(--border)] px-4 py-2 text-sm"
                >
                  关闭
                </button>
              </div>
            </div>
          ) : (
            <p className="mt-3 text-sm text-[var(--muted)]">正在加载设置…</p>
          )}
        </div>
      </div>
    )
  }

  const needsLocalEnv =
    settings.tts_mode === 'local' ||
    settings.script_mode === 'local' ||
    settings.avatar_mode === 'local'
  const showTtsWorker = settings.tts_mode === 'local'
  const showFunasrWorker = settings.script_mode === 'local'
  const showWorkers = showTtsWorker || showFunasrWorker

  const save = async () => {
    setLoading(true)
    setError('')
    try {
      await api.saveSettings(settings)
      onSaved()
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  const savePartial = async (next: SettingsPayload) => {
    setSettings(next)
    setLoading(true)
    setError('')
    try {
      await api.saveSettings(next)
      onSaved()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  const patch = (key: keyof SettingsPayload, value: string) =>
    setSettings((s) => (s ? { ...s, [key]: value } : s))

  const engineChoices = (step: keyof typeof engines, mode?: string) => {
    const block = engines[step]
    if (!block) return []
    const m = mode || (step === 'script' ? settings.script_mode : step === 'tts' ? settings.tts_mode : step === 'avatar' ? settings.avatar_mode : settings.publish_mode)
    if (m === 'cloud' && block.choices_cloud?.length) return block.choices_cloud
    if (m === 'local' && block.choices_local?.length) return block.choices_local
    return block.choices
  }

  const patchMode = (step: 'script' | 'tts' | 'avatar' | 'publish', mode: string) => {
    const key = `${step}_mode` as keyof SettingsPayload
    const engKey = `${step}_engine` as keyof SettingsPayload
    const choices = engineChoices(step, mode)
    const current = settings[engKey]
    const nextEngine = choices.some((c) => c.value === current)
      ? current
      : choices[0]?.value || current
    const next: SettingsPayload = { ...settings, [key]: mode, [engKey]: nextEngine }
    if (step === 'tts') {
      void savePartial(next)
      return
    }
    setSettings(next)
  }

  const patchTtsEngine = (engine: string) => {
    if (engine === settings.tts_engine) return
    void savePartial({ ...settings, tts_engine: engine })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="flex max-h-[90vh] w-full max-w-5xl flex-col rounded-2xl border border-[var(--border)] bg-[var(--panel)]">
        <div className="border-b border-[var(--border)] px-5 pt-4">
          <h2 className="text-lg font-semibold">设置</h2>
          <p className="mt-1 text-sm text-[var(--muted)]">
            {tab === 'engines'
              ? '配置各步骤的本地 / 云端引擎；本地步骤才需要安装模型与常驻加速。'
              : tab === 'install'
                ? '安装口播引擎、夸克加速包，以及本机模型与运行时修复。'
                : '产品信息、反馈渠道与第三方组件声明。'}
          </p>
          <div className="mt-3 flex gap-1 overflow-x-auto pb-px" role="tablist" aria-label="设置分类">
            {SETTINGS_TABS.map((t) => {
              const active = tab === t.id
              return (
                <button
                  key={t.id}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  onClick={() => setTab(t.id)}
                  className={`shrink-0 rounded-t-lg border px-3.5 py-2 text-sm transition ${
                    active
                      ? 'border-[var(--border)] border-b-[var(--panel)] bg-[var(--panel)] font-semibold text-[var(--accent)]'
                      : 'border-transparent text-[var(--muted)] hover:bg-[var(--bg)] hover:text-[var(--text)]'
                  }`}
                >
                  {t.label}
                </button>
              )
            })}
          </div>
        </div>
        <div className="space-y-4 overflow-y-auto p-5">
          {tab === 'engines' && (
            <>
              <SettingsCard title="① 文案" id="settings-script">
            <ModeEngineRow
              mode={settings.script_mode}
              engine={settings.script_engine}
              choices={engineChoices('script')}
              showEngine={settings.script_mode === 'local'}
              onMode={(v) => patchMode('script', v)}
              onEngine={(v) => patch('script_engine', v)}
            />
            {settings.script_mode === 'local' && settings.script_engine === 'local_whisper' && (
              <label className="block text-xs text-[var(--muted)]">
                Whisper 模型
                <select
                  value={settings.whisper_model || 'small'}
                  onChange={(e) => patch('whisper_model', e.target.value)}
                  className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-2 py-2 text-sm"
                >
                  <option value="tiny">tiny（最快）</option>
                  <option value="base">base</option>
                  <option value="small">small（默认）</option>
                  <option value="medium">medium</option>
                  <option value="large-v3">large-v3（最准最慢）</option>
                </select>
              </label>
            )}
            {settings.script_mode === 'cloud' && (
              <div className="space-y-3 rounded-lg border border-[var(--border)] bg-[var(--bg)] p-3">
                <div className="space-y-2 rounded-lg border border-[var(--border)]/70 p-2.5">
                  <p className="text-[11px] font-medium text-[var(--accent)]">CDN 视频提取（可选）</p>
                  <p className="text-[10px] text-[var(--muted)]">
                    按接口文档的调用方式选协议。选「不提取」则跳过，只走下面的 ASR。
                  </p>
                  <label className="block text-xs text-[var(--muted)]">
                    协议形态
                    <select
                      value={settings.cdn_provider || 'none'}
                      onChange={(e) => patch('cdn_provider', e.target.value)}
                      className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--panel)] px-2 py-2 text-sm"
                    >
                      <option value="none">不提取（跳过）</option>
                      <option value="cdn_form_key_url">同步 · key + url（包月）</option>
                      <option value="cdn_form_key_url_times">同步 · key + url（计次）</option>
                      <option value="cdn_agg_video">聚合 · 单视频去水印（Bearer + url）</option>
                      <option value="cdn_agg_profile">聚合 · 主页批量（取列表首条）</option>
                      <option value="cdn_json_url">自定义 · JSON POST（url 字段）</option>
                    </select>
                  </label>
                  {settings.cdn_provider && settings.cdn_provider !== 'none' && (
                    <>
                      <Field
                        label={
                          settings.cdn_provider === 'cdn_agg_video' ||
                          settings.cdn_provider === 'cdn_agg_profile'
                            ? 'API Token（Bearer，控制台复制）'
                            : 'API Key'
                        }
                        type="password"
                        value={settings.cdn_api_key}
                        onChange={(v) => patch('cdn_api_key', v)}
                      />
                      <Field
                        label={
                          settings.cdn_provider === 'cdn_json_url'
                            ? '接口地址（必填）'
                            : '接口地址（选填，有默认时可留空）'
                        }
                        value={settings.cdn_api_url || ''}
                        onChange={(v) => patch('cdn_api_url', v)}
                      />
                      {(settings.cdn_provider === 'cdn_agg_video' ||
                        settings.cdn_provider === 'cdn_agg_profile') && (
                        <p className="text-[10px] text-[var(--muted)]">
                          默认地址分别为 /api/parse 与 /api/parse/user。主页协议会取作品列表第一条视频。
                        </p>
                      )}
                    </>
                  )}
                </div>

                <div className="space-y-2 rounded-lg border border-[var(--border)]/70 p-2.5">
                  <p className="text-[11px] font-medium text-[var(--accent)]">ASR 视频文案一键提取</p>
                  <p className="text-[10px] text-[var(--muted)]">
                    按接口文档选协议。异步会先提交任务再轮询结果（约 2s 一次）。
                  </p>
                  <label className="block text-xs text-[var(--muted)]">
                    协议形态
                    <select
                      value={
                        settings.transcript_provider === 'asr_async_poll'
                          ? 'asr_async_time'
                          : settings.transcript_provider || 'asr_sync_videourl'
                      }
                      onChange={(e) => patch('transcript_provider', e.target.value)}
                      className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--panel)] px-2 py-2 text-sm"
                    >
                      <option value="asr_sync_videourl">同步 · 表单 key + videoUrl</option>
                      <option value="asr_sync_content">同步 · 表单 key + content</option>
                      <option value="asr_async_time">异步 · 提交 + 轮询（计时）</option>
                      <option value="asr_async_count">异步 · 提交 + 轮询（计次）</option>
                      <option value="asr_custom_json">自定义 · JSON POST（url 字段）</option>
                    </select>
                  </label>
                  <Field
                    label="API Key"
                    type="password"
                    value={settings.transcript_api_key}
                    onChange={(v) => patch('transcript_api_key', v)}
                  />
                  <Field
                    label={
                      settings.transcript_provider === 'asr_custom_json'
                        ? '提交接口地址（必填）'
                        : '提交接口地址（选填，有默认时可留空）'
                    }
                    value={settings.transcript_api_url || ''}
                    onChange={(v) => patch('transcript_api_url', v)}
                  />
                  {(settings.transcript_provider === 'asr_async_time' ||
                    settings.transcript_provider === 'asr_async_count' ||
                    settings.transcript_provider === 'asr_async_poll') && (
                    <p className="text-[10px] text-[var(--muted)]">
                      轮询地址自动用同域 /api/asr/task-status，一般不用改。
                    </p>
                  )}
                </div>
              </div>
            )}
            <Field
              label="文本大模型 Key（DeepSeek · 仿写/热词/对标成稿共用）"
              type="password"
              value={settings.rewrite_api_key}
              onChange={(v) => patch('rewrite_api_key', v)}
            />
            <div className="rounded-lg border border-[var(--border)] bg-[var(--bg)] p-3">
              <button
                type="button"
                onClick={() => setPromptsOpen((v) => !v)}
                className="flex w-full items-center justify-between text-left text-xs font-medium text-[var(--text)]"
              >
                <span>文本处理提示词（进阶）</span>
                <span className="text-[var(--muted)]">{promptsOpen ? '收起' : '展开'}</span>
              </button>
              <p className="mt-1 text-[10px] text-[var(--muted)]">
                可改仿写/热词/成稿/法务等系统提示词；改坏可一键还原内置默认。轻度润色已加强改写力度。
              </p>
              {promptsOpen && (
                <div className="mt-3 space-y-3">
                  {promptItems.map((item) => (
                    <label key={item.id} className="block text-[11px] text-[var(--muted)]">
                      <span className="flex items-center gap-2 text-[var(--text)]">
                        {item.label}
                        {item.modified && (
                          <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] text-amber-700">
                            已修改
                          </span>
                        )}
                      </span>
                      {item.hint && (
                        <span className="mt-0.5 block text-[10px] text-[var(--muted)]">{item.hint}</span>
                      )}
                      <textarea
                        value={item.value}
                        rows={item.id.startsWith('rewrite_intensity') ? 3 : 5}
                        onChange={(e) => {
                          const v = e.target.value
                          setPromptItems((prev) =>
                            prev.map((p) =>
                              p.id === item.id
                                ? {
                                    ...p,
                                    value: v,
                                    modified: v.trim() !== p.default.trim(),
                                  }
                                : p,
                            ),
                          )
                        }}
                        className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--panel)] px-2 py-1.5 font-mono text-[11px] leading-relaxed text-[var(--text)]"
                      />
                      <button
                        type="button"
                        disabled={promptBusy || !item.modified}
                        onClick={async () => {
                          setPromptBusy(true)
                          setPromptMsg('')
                          try {
                            const res = await api.resetTextPrompts([item.id])
                            setPromptItems(res.items || [])
                            setPromptMsg(`已还原：${item.label}`)
                          } catch (e) {
                            setPromptMsg(e instanceof Error ? e.message : String(e))
                          } finally {
                            setPromptBusy(false)
                          }
                        }}
                        className="mt-1 text-[10px] text-[var(--accent)] underline disabled:opacity-40"
                      >
                        还原此项默认
                      </button>
                    </label>
                  ))}
                  <div className="flex flex-wrap gap-2 pt-1">
                    <button
                      type="button"
                      disabled={promptBusy || !promptItems.length}
                      onClick={async () => {
                        setPromptBusy(true)
                        setPromptMsg('')
                        try {
                          const map: Record<string, string> = {}
                          for (const p of promptItems) map[p.id] = p.value
                          const res = await api.saveTextPrompts(map)
                          setPromptItems(res.items || [])
                          setPromptMsg('提示词已保存')
                        } catch (e) {
                          setPromptMsg(e instanceof Error ? e.message : String(e))
                        } finally {
                          setPromptBusy(false)
                        }
                      }}
                      className="rounded-lg border border-[var(--accent)] bg-[var(--select-bg)] px-3 py-1.5 text-xs text-[var(--accent)] disabled:opacity-50"
                    >
                      {promptBusy ? '处理中…' : '保存提示词'}
                    </button>
                    <button
                      type="button"
                      disabled={promptBusy}
                      onClick={async () => {
                        setPromptBusy(true)
                        setPromptMsg('')
                        try {
                          const res = await api.resetTextPrompts()
                          setPromptItems(res.items || [])
                          setPromptMsg('已全部还原为内置默认')
                        } catch (e) {
                          setPromptMsg(e instanceof Error ? e.message : String(e))
                        } finally {
                          setPromptBusy(false)
                        }
                      }}
                      className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs text-[var(--muted)] disabled:opacity-50"
                    >
                      全部还原默认
                    </button>
                  </div>
                  {promptMsg && <p className="text-[10px] text-[var(--muted)]">{promptMsg}</p>}
                </div>
              )}
            </div>
          </SettingsCard>
          <SettingsCard title="② 配音 · 音色" id="settings-tts">
            <ModeEngineRow
              mode={settings.tts_mode}
              engine={settings.tts_engine}
              choices={engineChoices('tts')}
              onMode={(v) => patchMode('tts', v)}
              onEngine={patchTtsEngine}
              engineAsButtons
              busy={loading}
            />
            <p className="text-xs text-[var(--muted)]">
              点选引擎会立即保存并生效（无需再点底部保存）。
            </p>
            {settings.tts_mode === 'cloud' && settings.tts_engine === 'qwen3_tts' && (
              <p className="text-xs text-[var(--muted)]">
                云端为 DashScope API。本地开源千问请选「本地」→「Qwen3-TTS 本地」。
              </p>
            )}
            {settings.tts_mode === 'local' && settings.tts_engine === 'qwen3_local' && (
              <p className="text-xs text-[var(--muted)]">
                本地 Qwen3：默认 0.6B 对英文品牌偏弱（易逐字母读）。中英混读口播请用 IndexTTS2；若坚持千问可换 1.7B。
              </p>
            )}
            {settings.tts_mode === 'local' && settings.tts_engine === 'cosyvoice' && (
              <p className="text-xs text-[var(--muted)]">
                CosyVoice 克隆须填与录音一致的参考文案。英文品牌易逐字母读，中英混读请优先 IndexTTS2。
              </p>
            )}
            {settings.tts_mode === 'local' && settings.tts_engine === 'indextts' && (
              <p className="text-xs text-[var(--muted)]">
                IndexTTS2：中英混读口播推荐引擎；克隆一般不必填参考文案。
              </p>
            )}
            {settings.tts_engine === 'qwen3_tts' && (
              <Field label="DashScope Key" type="password" value={settings.qwen3_tts_api_key} onChange={(v) => patch('qwen3_tts_api_key', v)} />
            )}
          </SettingsCard>
          <SettingsCard title="③ 口播" id="settings-avatar">
            <ModeEngineRow
              mode={settings.avatar_mode}
              engine={settings.avatar_engine}
              choices={engineChoices('avatar')}
              onMode={(v) => patchMode('avatar', v)}
              onEngine={(v) => patch('avatar_engine', v)}
            />
          </SettingsCard>
          <SettingsCard title="④ 发布" id="settings-publish">
            <ModeEngineRow
              mode={settings.publish_mode}
              engine={settings.publish_engine}
              choices={engineChoices('publish')}
              onMode={(v) => patchMode('publish', v)}
              onEngine={(v) => patch('publish_engine', v)}
            />
          </SettingsCard>
            </>
          )}

          {tab === 'install' && (
            <>
              {needsLocalEnv && (
                <SettingsCard title="本机环境 · GPU 与模型" id="settings-env">
                  <p className="text-xs text-[var(--muted)]">
                    仅在步骤选择「本地」时显示。云端引擎不需要本机模型安装。
                  </p>
                  <ModelSetupPanel
                    currentEngine={settings.tts_mode === 'local' ? settings.tts_engine : undefined}
                    onRefresh={onSaved}
                    defaultOpen={focusSection === 'env'}
                  />
                </SettingsCard>
              )}
              <SettingsCard title="桌面运行时 · 一键修复" id="settings-runtime">
                <p className="mb-2 text-xs text-[var(--muted)]">
                  启动异常时可清除运行时并重启；C 盘满可改运行时磁盘；「导出诊断包」可发给客服排查。
                </p>
                <DesktopRuntimePanel />
              </SettingsCard>
              <SettingsCard title="口播引擎安装向导" id="settings-heygem-wizard">
                <p className="mb-2 text-xs text-[var(--muted)]">
                  Docker → 夸克加速包（按显卡）→ 自动加载镜像并启动。安装包体积不含镜像。
                </p>
                <HeyGemInstallWizard />
              </SettingsCard>
              <SettingsCard title="网盘加速 · 夸克（免费线）" id="settings-quark">
                <p className="mb-2 text-xs text-[var(--muted)]">
                  无外网时用夸克下载大包。口播引擎按显卡分「通用 / RTX50」两包；通用组件与显卡无关。也可在上方向导中完成口播安装。
                </p>
                <QuarkAccelPanel />
              </SettingsCard>
              {showWorkers && (
                <SettingsCard title="常驻加速 · Worker" id="settings-workers">
                  <p className="text-xs text-[var(--muted)]">
                    仅本地步骤需要。常驻会预加载模型到内存以提速，关闭即释放。
                  </p>
                  {showTtsWorker && (
            <WorkerToggle
                  name="IndexTTS2 配音引擎"
                  desc="常驻会把模型留在 GPU/内存里加速下次合成；不用时请关掉以释放显存。软件默认不在启动时偷偷加载。"
                  state={ttsWorker}
                  busy={workerBusy}
                  onToggle={async () => {
                        if (!ttsWorker) return
                        setWorkerBusy('tts')
                        try {
                          if (ttsWorker.running) await api.ttsWorkerStop()
                          else await api.ttsWorkerStart()
                          setTtsWorker(await api.ttsWorkerStatus())
                        } finally {
                          setWorkerBusy('')
                        }
                      }}
                    />
                  )}
                  {showFunasrWorker && (
                    <WorkerToggle
                      name="FunASR 语音转写 (SenseVoice)"
                      desc="常驻约占 500MB 内存 · 转写从 ~22s 降到 ~0.2s"
                      state={funasrWorker}
                      busy={workerBusy}
                      onToggle={async () => {
                        if (!funasrWorker) return
                        setWorkerBusy('funasr')
                        try {
                          if (funasrWorker.running) {
                            await api.funasrWorkerStop()
                          } else {
                            const res = await api.funasrWorkerStart()
                            if (!res.ok || !res.running) {
                              window.alert(
                                res.message ||
                                  'FunASR 常驻启动失败。请确认已安装 torch：tools\\FunASR\\.venv\\Scripts\\python.exe -m pip install torch torchaudio',
                              )
                            }
                          }
                          setFunasrWorker(await api.funasrWorkerStatus())
                        } catch (e) {
                          window.alert(e instanceof Error ? e.message : String(e))
                        } finally {
                          setWorkerBusy('')
                        }
                      }}
                    />
                  )}
                </SettingsCard>
              )}
            </>
          )}

          {tab === 'about' && (
            <SettingsCard title="关于我们" id="settings-about">
            <div className="flex gap-4">
              <img
                src="/app-icon.png"
                alt=""
                width={48}
                height={48}
                className="h-12 w-12 shrink-0 rounded-xl object-cover"
              />
              <div className="min-w-0 space-y-1.5">
                <p className="text-sm font-semibold text-[var(--text)]">{APP_NAME}</p>
                <p className="text-xs leading-relaxed text-[var(--muted)]">{APP_TAGLINE}</p>
                <p className="text-xs text-[var(--muted)]">
                  反馈与问题：{' '}
                  <a
                    href={FEEDBACK_MAILTO}
                    className="font-medium text-[var(--accent)] underline-offset-2 hover:underline"
                  >
                    {FEEDBACK_EMAIL}
                  </a>
                </p>
                {onCheckUpdates && (
                  <button
                    type="button"
                    onClick={onCheckUpdates}
                    className="mt-1 rounded-lg border border-[var(--border)] px-2.5 py-1 text-[11px] font-medium text-[var(--accent)] hover:bg-[var(--bg)]"
                  >
                    检查更新
                  </button>
                )}
              </div>
            </div>
            <div className="rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3">
              <p className="text-xs font-semibold text-[var(--text)]">{TIP_TITLE}</p>
              <p className="mt-2 text-[11px] leading-relaxed text-[var(--muted)]">{TIP_BLURB}</p>
              <div className="mt-3 flex justify-center">
                <img
                  src={TIP_QR_SRC}
                  alt="微信收款码 · 请喝咖啡"
                  width={220}
                  height={280}
                  className="max-h-72 w-auto max-w-full rounded-lg border border-[var(--border)] object-contain"
                />
              </div>
            </div>
            <div className="rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3">
              <p className="text-xs font-semibold text-[var(--text)]">开源免责说明</p>
              <p className="mt-2 whitespace-pre-line text-[11px] leading-relaxed text-[var(--muted)]">
                {OPEN_SOURCE_DISCLAIMER}
              </p>
            </div>
            <div className="rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3">
              <p className="text-xs font-semibold text-[var(--text)]">{THIRD_PARTY_NOTICE_TITLE}</p>
              <p className="mt-2 text-[11px] leading-relaxed text-[var(--muted)]">{THIRD_PARTY_SUMMARY}</p>
              <p className="mt-2 rounded-lg border border-amber-500/30 bg-amber-500/5 px-2.5 py-2 text-[10px] leading-relaxed text-[var(--muted)]">
                {AI_COMPLIANCE_NOTE}
              </p>
              <div className="mt-3 overflow-x-auto">
                <table className="w-full text-left text-[10px] text-[var(--muted)]">
                  <thead>
                    <tr className="border-b border-[var(--border)] text-[var(--text)]">
                      <th className="py-1 pr-2 font-medium">组件</th>
                      <th className="py-1 pr-2 font-medium">用途</th>
                      <th className="py-1 font-medium">许可/条款</th>
                    </tr>
                  </thead>
                  <tbody>
                    {THIRD_PARTY_ROWS.map((row) => (
                      <tr key={row.name} className="border-b border-[var(--border)]/60">
                        <td className="py-1 pr-2 text-[var(--text)]">{row.name}</td>
                        <td className="py-1 pr-2">{row.role}</td>
                        <td className="py-1">{row.license}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="mt-2 text-[10px] text-[var(--muted)]">
                完整清单与合规说明：
                <a
                  href="/third-party-notices.md"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="ml-1 text-[var(--accent)] underline-offset-2 hover:underline"
                >
                  第三方声明文档
                </a>
                （仓库路径 {REPO_THIRD_PARTY_DOC}）
              </p>
            </div>
          </SettingsCard>
          )}

          {error && <p className="text-sm text-red-400">{error}</p>}
        </div>
        <div className="flex justify-end gap-2 border-t border-[var(--border)] px-5 py-4">
          <button type="button" onClick={onClose} className="rounded-lg border border-[var(--border)] px-4 py-2 text-sm">
            {tab === 'engines' ? '取消' : '关闭'}
          </button>
          {tab === 'engines' && (
            <button
              type="button"
              disabled={loading}
              onClick={save}
              className="btn-primary rounded-lg px-4 py-2 text-sm font-medium disabled:opacity-50"
            >
              {loading ? '保存中…' : '保存并生效'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

function SettingsCard({
  title,
  children,
  id,
}: {
  title: string
  children: React.ReactNode
  id?: string
}) {
  return (
    <section
      id={id}
      className="rounded-xl border border-[var(--border)] bg-[var(--panel-2)] p-4 scroll-mt-4"
    >
      <h3 className="mb-3 text-sm font-bold text-[var(--accent)]">{title}</h3>
      <div className="space-y-3">{children}</div>
    </section>
  )
}

function ModeEngineRow({
  mode,
  engine,
  choices,
  onMode,
  onEngine,
  engineAsButtons = false,
  showEngine = true,
  busy = false,
}: {
  mode: string
  engine: string
  choices: { value: string; label: string; hardware?: string }[]
  onMode: (v: string) => void
  onEngine: (v: string) => void
  engineAsButtons?: boolean
  showEngine?: boolean
  busy?: boolean
}) {
  return (
    <div className={`grid gap-3 ${showEngine ? 'md:grid-cols-2' : ''}`}>
      <label className="block text-xs text-[var(--muted)]">
        运行方式
        <select
          value={mode}
          disabled={busy}
          onChange={(e) => onMode(e.target.value)}
          className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-2 py-2 text-sm disabled:opacity-60"
        >
          {MODES.map((m) => (
            <option key={m.value} value={m.value}>
              {m.label}
            </option>
          ))}
        </select>
      </label>
      {showEngine && engineAsButtons ? (
        <div className="block text-xs text-[var(--muted)] md:col-span-1">
          <span>引擎{busy ? ' · 保存中…' : ''}</span>
          <div className="mt-1 flex flex-col gap-1.5">
            {choices.map((c) => {
              const active = c.value === engine
              return (
                <button
                  key={c.value}
                  type="button"
                  disabled={busy}
                  onClick={() => onEngine(c.value)}
                  className={`rounded-lg border px-2.5 py-2 text-left text-sm transition disabled:opacity-60 ${
                    active
                      ? 'border-[var(--select-border)] bg-[var(--select-bg)] font-medium text-[var(--accent)]'
                      : 'border-[var(--border)] bg-[var(--bg)] text-[var(--text)] hover:border-[var(--select-border)]'
                  }`}
                >
                  <span className="block">{c.label}</span>
                  {c.hardware && (
                    <span className="mt-0.5 block text-[10px] text-[var(--muted)]">{c.hardware}</span>
                  )}
                </button>
              )
            })}
          </div>
        </div>
      ) : showEngine ? (
        <label className="block text-xs text-[var(--muted)]">
          引擎
          <select
            value={engine}
            disabled={busy}
            onChange={(e) => onEngine(e.target.value)}
            className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-2 py-2 text-sm disabled:opacity-60"
          >
            {choices.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
                {c.hardware ? ` · ${c.hardware}` : ''}
              </option>
            ))}
          </select>
        </label>
      ) : null}
    </div>
  )
}

function Field({
  label,
  value,
  onChange,
  type = 'text',
}: {
  label: string
  value: string
  onChange: (v: string) => void
  type?: string
}) {
  return (
    <label className="block text-xs text-[var(--muted)]">
      {label}
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-2 py-2 text-sm"
      />
    </label>
  )
}

function WorkerToggle({
  name,
  desc,
  state,
  busy,
  onToggle,
}: {
  name: string
  desc: string
  state: WorkerState
  busy: string
  onToggle: () => void
}) {
  const running = state?.running
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2.5">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 text-sm font-medium">
          {name}
          {running !== undefined && (
            <span
              className={`rounded-full px-2 py-0.5 text-[10px] ${
                running
                  ? 'bg-emerald-500/20 text-emerald-400'
                  : 'bg-[var(--panel)] text-[var(--muted)]'
              }`}
            >
              {running ? '运行中' : '已停止'}
            </span>
          )}
        </div>
        <p className="mt-0.5 text-xs text-[var(--muted)]">{desc}</p>
      </div>
      <button
        type="button"
        disabled={!!busy || state === null}
        onClick={onToggle}
        className={`shrink-0 rounded-lg px-3 py-1.5 text-xs font-medium disabled:opacity-50 ${
          running
            ? 'border border-red-400/50 text-red-400 hover:bg-red-500/10'
            : 'btn-primary'
        }`}
      >
        {busy ? '…' : running ? '停止' : '启动'}
      </button>
    </div>
  )
}

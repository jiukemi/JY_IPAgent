import { useCallback, useEffect, useRef, useState } from 'react'
import { api, playableUrl } from '../api/client'
import { AlertModal } from '../components/AlertModal'
import { formatAudioDuration } from '../components/AudioPreviewButton'
import type { TtsOptions } from '../types'
import { normalizeAudioToWavFile } from '../utils/audioNormalize'
import { ActionBtn, Panel } from './ScriptPage'

type InputMode = 'upload' | 'record'

type LibraryVoice = {
  id: string
  uid?: string
  name: string
  source_type?: string
  created_at?: string
  backend?: string
  preview_url?: string | null
  local_path?: string | null
  reference_wav?: string | null
  prompt_text?: string
}

type Props = {
  onVoiceSaved?: (voiceUid?: string) => void
  /** When true, omit duplicate engine banner (shown on 配音 page already). */
  embedded?: boolean
}

function useAudioDuration(src: string | null) {
  const [duration, setDuration] = useState<number | null>(null)

  useEffect(() => {
    if (!src) {
      setDuration(null)
      return
    }
    const audio = new Audio()
    audio.preload = 'metadata'
    audio.onloadedmetadata = () => {
      if (Number.isFinite(audio.duration)) setDuration(audio.duration)
    }
    audio.onerror = () => setDuration(null)
    audio.src = src
    return () => {
      audio.onloadedmetadata = null
      audio.onerror = null
      audio.src = ''
    }
  }, [src])

  return duration
}

export function ClonePage({ onVoiceSaved, embedded = false }: Props) {
  const [mode, setMode] = useState<InputMode>('upload')
  const [name, setName] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const [library, setLibrary] = useState<LibraryVoice[]>([])
  const [recording, setRecording] = useState(false)
  const [recordSec, setRecordSec] = useState(0)
  const [recordedSec, setRecordedSec] = useState<number | null>(null)
  const [playingId, setPlayingId] = useState<string | null>(null)
  const [alert, setAlert] = useState<{ title: string; message: string; variant: 'error' | 'warning' | 'success' } | null>(null)
  const [pendingDelete, setPendingDelete] = useState<{ id: string; name: string } | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [runtime, setRuntime] = useState<TtsOptions | null>(null)
  const [promptText, setPromptText] = useState('')

  const fileInputRef = useRef<HTMLInputElement>(null)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const timerRef = useRef<number | null>(null)
  const recordSecRef = useRef(0)
  const libraryAudioRef = useRef<HTMLAudioElement | null>(null)

  const clipDuration = useAudioDuration(previewUrl)

  const loadLibrary = useCallback(async () => {
    try {
      setLibrary(await api.voiceLibrary())
    } catch {
      setLibrary([])
    }
  }, [])

  const loadDefaultName = useCallback(async (src: InputMode) => {
    try {
      const { name: n } = await api.nextVoiceName(src)
      setName(n)
    } catch {
      setName(src === 'record' ? '录制声音1' : '上传声音1')
    }
  }, [])

  useEffect(() => {
    loadLibrary()
    loadDefaultName('upload')
    api
      .ttsOptions()
      .then((opts) => {
        setRuntime(opts)
        if (opts.clone_default_prompt) setPromptText(opts.clone_default_prompt)
      })
      .catch(() => setRuntime(null))
  }, [loadLibrary, loadDefaultName])

  useEffect(() => {
    return () => {
      if (previewUrl?.startsWith('blob:')) URL.revokeObjectURL(previewUrl)
      libraryAudioRef.current?.pause()
    }
  }, [previewUrl])

  const setAudioFile = (f: File | null) => {
    if (previewUrl?.startsWith('blob:')) URL.revokeObjectURL(previewUrl)
    setFile(f)
    setPreviewUrl(f ? URL.createObjectURL(f) : null)
    if (!f) setRecordedSec(null)
  }

  /** 录制/上传后立刻转成 wav，试听与落盘都走标准 PCM，不再等 WebM 缓冲 */
  const setNormalizedAudio = async (raw: File, fallbackSec?: number | null) => {
    try {
      const wav = await normalizeAudioToWavFile(raw, raw.name || 'recording')
      setAudioFile(wav)
      if (fallbackSec != null) setRecordedSec(fallbackSec)
    } catch {
      setAudioFile(raw)
      if (fallbackSec != null) setRecordedSec(fallbackSec)
    }
  }

  const pickFile = (f: File | null) => {
    if (!f) return
    if (!f.type.startsWith('audio/') && !/\.(wav|mp3|m4a|ogg|webm|flac)$/i.test(f.name)) {
      setAlert({ title: '格式不支持', message: '请上传音频文件（wav / mp3 / m4a 等）', variant: 'warning' })
      return
    }
    void setNormalizedAudio(f)
  }

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    pickFile(e.dataTransfer.files?.[0] || null)
  }

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          channelCount: 1,
        },
      })
      const mimeCandidates = [
        'audio/webm;codecs=opus',
        'audio/webm',
        'audio/mp4',
        'audio/ogg;codecs=opus',
      ]
      const mime = mimeCandidates.find((t) => MediaRecorder.isTypeSupported(t)) || ''
      const recorder = mime
        ? new MediaRecorder(stream, { mimeType: mime })
        : new MediaRecorder(stream)
      const actualMime = recorder.mimeType || mime || 'audio/webm'
      chunksRef.current = []
      recorder.ondataavailable = (ev) => {
        if (ev.data.size > 0) chunksRef.current.push(ev.data)
      }
      recorder.onstop = () => {
        stream.getTracks().forEach((t) => t.stop())
        const blob = new Blob(chunksRef.current, { type: actualMime })
        const ext = actualMime.includes('mp4') ? 'm4a' : actualMime.includes('ogg') ? 'ogg' : 'webm'
        const f = new File([blob], `recording_${Date.now()}.${ext}`, { type: actualMime })
        const sec = recordSecRef.current
        if (timerRef.current) window.clearInterval(timerRef.current)
        setRecordSec(0)
        recordSecRef.current = 0
        setRecording(false)
        void setNormalizedAudio(f, sec)
      }
      mediaRecorderRef.current = recorder
      // 不要 start(200)：分片 WebM 在 Electron 里常导致试听卡住/等很久才出声
      recorder.start()
      setRecording(true)
      setRecordSec(0)
      recordSecRef.current = 0
      setRecordedSec(null)
      timerRef.current = window.setInterval(() => {
        setRecordSec((s) => {
          const next = s + 1
          recordSecRef.current = next
          return next
        })
      }, 1000)
    } catch (e) {
      setAlert({
        title: '无法录音',
        message: e instanceof Error ? e.message : '无法访问麦克风，请检查浏览器权限',
        variant: 'error',
      })
    }
  }

  const stopRecording = () => {
    mediaRecorderRef.current?.stop()
    mediaRecorderRef.current = null
  }

  const switchMode = (m: InputMode) => {
    if (recording) stopRecording()
    setMode(m)
    setAudioFile(null)
    setRecordedSec(null)
    loadDefaultName(m)
  }

  const save = async () => {
    if (!file) {
      setAlert({
        title: '缺少音频',
        message: mode === 'record' ? '请先完成录音' : '请先上传或拖入参考音频',
        variant: 'warning',
      })
      return
    }
    const needsPrompt = Boolean(runtime?.clone_prompt_required)
    if (needsPrompt && !promptText.trim()) {
      setAlert({
        title: '缺少参考文案',
        message:
          'CosyVoice / 本地千问克隆要求：参考文案必须与参考音频里说的内容一致。请先照着文案录音或补全文案后再保存。',
        variant: 'warning',
      })
      return
    }
    setBusy(true)
    try {
      const res = await api.cloneVoice(name || '克隆音色', file, mode, promptText)
      const msg = res.message || '已保存到音色库，关闭弹窗后可在「克隆音色」中选用'
      const savedId = typeof res.data?.id === 'string' ? res.data.id : ''
      setAlert({ title: '保存成功', message: msg, variant: 'success' })
      setAudioFile(null)
      setRecordedSec(null)
      await loadLibrary()
      await loadDefaultName(mode)
      onVoiceSaved?.(savedId ? `clone:${savedId}` : undefined)
    } catch (e) {
      setAlert({
        title: '保存失败',
        message: e instanceof Error ? e.message : String(e),
        variant: 'error',
      })
    } finally {
      setBusy(false)
    }
  }

  const askRemoveVoice = (v: LibraryVoice, e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setPendingDelete({ id: v.id, name: v.name })
  }

  const confirmRemoveVoice = async () => {
    if (!pendingDelete) return
    const { id } = pendingDelete
    setDeleting(true)
    try {
      await api.deleteVoice(id)
      if (playingId === id) {
        libraryAudioRef.current?.pause()
        setPlayingId(null)
      }
      setLibrary((prev) => prev.filter((x) => x.id !== id))
      setPendingDelete(null)
      await loadLibrary()
      onVoiceSaved?.()
    } catch (err) {
      setPendingDelete(null)
      setAlert({
        title: '删除失败',
        message: err instanceof Error ? err.message : String(err),
        variant: 'error',
      })
    } finally {
      setDeleting(false)
    }
  }

  const playLibraryVoice = async (v: LibraryVoice) => {
    const src = playableUrl(v.preview_url, { localPath: v.local_path || v.reference_wav })
    if (!src) return
    if (playingId === v.id && libraryAudioRef.current && !libraryAudioRef.current.paused) {
      libraryAudioRef.current.pause()
      setPlayingId(null)
      return
    }
    libraryAudioRef.current?.pause()
    const audio = new Audio(src)
    libraryAudioRef.current = audio
    audio.preload = 'auto'
    audio.onended = () => setPlayingId(null)
    audio.onerror = () => setPlayingId(null)
    setPlayingId(v.id)
    try {
      await audio.play()
    } catch {
      setPlayingId(null)
    }
  }

  const formatTime = (s: number) => formatAudioDuration(s)

  const displayDuration =
    clipDuration != null
      ? clipDuration
      : mode === 'record' && recordedSec != null
        ? recordedSec
        : null

  const backendLabel = (b?: string) => {
    const map: Record<string, string> = {
      indextts: 'IndexTTS2',
      cosyvoice: 'CosyVoice2',
      qwen3_tts: 'Qwen3-TTS 云端',
      qwen3_local: 'Qwen3-TTS 本地',
    }
    return map[b || ''] || b || '本地'
  }

  const wrapClass = embedded
    ? 'flex flex-col gap-4'
    : 'mx-auto flex max-w-4xl flex-col gap-4'

  return (
    <div className={wrapClass}>
      <Panel title={embedded ? '克隆音色 · 上传 / 录音' : '02 配音 · 克隆音色'}>
        {!embedded && runtime?.profile && (
          <div className="mb-4 rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3 py-3 text-xs">
            <div className="font-medium text-[var(--text)]">
              当前配音引擎：{runtime.engine_label}
            </div>
            <div className="mt-1 text-[var(--muted)]">{runtime.profile.hardware}</div>
            <div className="mt-1 text-[var(--muted)]">{runtime.profile.summary}</div>
            {!runtime.profile.supports_clone && (
              <p className="mt-2 text-amber-300">
                当前引擎不支持克隆。请切换到 IndexTTS2 / CosyVoice2 / Qwen3-TTS 本地或云端。
              </p>
            )}
          </div>
        )}

        {!embedded && (
          <details className="mb-4 rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-xs">
            <summary className="cursor-pointer select-none py-1 font-medium text-[var(--muted)]">
              各引擎克隆与硬件要求
            </summary>
            <ul className="mt-2 space-y-2 text-[var(--muted)]">
              {(runtime?.engines || []).map((e) => (
                <li key={e.value} className="rounded-lg border border-[var(--border)] px-2 py-1.5">
                  <span className="font-medium text-[var(--text)]">{e.label}</span>
                  {e.hardware && <span className="ml-1">· {e.hardware}</span>}
                  {e.summary && <div className="mt-0.5">{e.summary}</div>}
                </li>
              ))}
            </ul>
          </details>
        )}

        <p className="mb-4 text-sm text-[var(--muted)]">
          上传或录制 <strong className="text-[var(--text)]">8–15 秒</strong> 清晰单人声，保存后即可在配音页「克隆音色」中选用。
          {runtime?.engine === 'indextts' && ' IndexTTS2 只需参考音，不必填参考文案。'}
          {runtime?.engine === 'indextts' && (
            <span className="mt-1 block text-[var(--muted)]">
              参考音请带自然语气与起伏（勿念稿平直）；配音页可为克隆音色补充「情感风格」。
            </span>
          )}
          {(runtime?.clone_prompt_required ||
            runtime?.engine === 'cosyvoice' ||
            runtime?.engine === 'qwen3_local') &&
            ' 当前引擎必须填写「参考文案」，且与录音内容一致。'}
        </p>

        {(runtime?.clone_prompt_required ||
          runtime?.engine === 'cosyvoice' ||
          runtime?.engine === 'qwen3_local') && (
          <label className="mb-4 block text-xs text-[var(--muted)]">
            参考文案
            <span className="ml-1 text-amber-600">（必填 · 必须与音频内容一致）</span>
            <textarea
              value={promptText}
              onChange={(e) => setPromptText(e.target.value)}
              rows={3}
              placeholder="请念这段话录音，或填写上传音频里实际说的内容…"
              className="mt-1 w-full rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3 py-2.5 text-sm leading-relaxed"
            />
            {runtime?.clone_hint && (
              <span className="mt-1 block text-[10px] text-[var(--muted)]">{runtime.clone_hint}</span>
            )}
          </label>
        )}

        <div className="mb-4 inline-flex rounded-xl border border-[var(--border)] bg-[var(--bg)] p-1">
          <ModeBtn active={mode === 'upload'} onClick={() => switchMode('upload')}>
            📁 上传文件
          </ModeBtn>
          <ModeBtn active={mode === 'record'} onClick={() => switchMode('record')}>
            🎙️ 麦克风录音
          </ModeBtn>
        </div>

        {mode === 'upload' ? (
          <div
            role="button"
            tabIndex={0}
            onDragOver={(e) => {
              e.preventDefault()
              setDragOver(true)
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={onDrop}
            onClick={() => fileInputRef.current?.click()}
            onKeyDown={(e) => e.key === 'Enter' && fileInputRef.current?.click()}
            className={`cursor-pointer rounded-2xl border-2 border-dashed px-6 py-10 text-center transition ${
              dragOver
                ? 'border-[var(--accent)] bg-[var(--select-bg)]'
                : 'border-[var(--border)] bg-[var(--bg)] hover:border-[var(--accent)] hover:bg-[var(--panel)]'
            }`}
          >
            <div className="text-3xl">🎵</div>
            <p className="mt-2 text-sm font-medium">拖拽音频到此处，或点击选择文件</p>
            <p className="mt-1 text-xs text-[var(--muted)]">支持 wav · mp3 · m4a · ogg · webm</p>
            <input
              ref={fileInputRef}
              type="file"
              accept="audio/*,.wav,.mp3,.m4a,.ogg,.webm,.flac"
              className="hidden"
              onChange={(e) => pickFile(e.target.files?.[0] || null)}
            />
          </div>
        ) : (
          <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg)] px-6 py-10 text-center">
            <div className={`text-4xl ${recording ? 'animate-pulse' : ''}`}>🎙️</div>
            <p className="mt-3 text-2xl font-mono tabular-nums">{formatTime(recordSec)}</p>
            <p className="mt-1 text-xs text-[var(--muted)]">
              {recording ? '录音中… 建议 8–15 秒后停止' : '点击下方开始录音'}
            </p>
            <div className="mt-5 flex justify-center gap-3">
              {!recording ? (
                <button type="button" onClick={startRecording} className="btn-primary rounded-xl px-6 py-2.5 text-sm font-semibold">
                  开始录音
                </button>
              ) : (
                <button
                  type="button"
                  onClick={stopRecording}
                  className="rounded-xl border-2 border-red-400/60 bg-red-500/10 px-6 py-2.5 text-sm font-semibold text-red-400"
                >
                  停止并保存片段
                </button>
              )}
            </div>
          </div>
        )}

        {previewUrl && (
          <div className="mt-4 rounded-xl border border-[var(--border)] bg-[var(--panel)] p-3">
            <div className="mb-2 flex items-center justify-between gap-2 text-xs text-[var(--muted)]">
              <span className="flex items-center gap-2">
                试听参考音
                {displayDuration != null && (
                  <span className="rounded-md bg-[var(--select-bg)] px-2 py-0.5 font-mono text-[var(--accent)]">
                    时长 {formatTime(displayDuration)}
                  </span>
                )}
              </span>
              <span className="truncate">{file?.name}</span>
            </div>
            <audio key={previewUrl} src={previewUrl} controls preload="auto" className="w-full" />
            <button
              type="button"
              onClick={() => setAudioFile(null)}
              className="mt-2 text-xs text-[var(--muted)] hover:text-[var(--accent)]"
            >
              清除重选
            </button>
          </div>
        )}

        <label className="mt-4 block text-xs text-[var(--muted)]">
          音色名称
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="例如：温柔女声"
            className="mt-1 w-full rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3 py-2.5 text-sm"
          />
        </label>

        <div className="mt-5">
          <ActionBtn primary disabled={busy || !file} onClick={save}>
            {busy ? '保存中…' : '✅ 保存到音色库'}
          </ActionBtn>
        </div>
      </Panel>

      {library.length > 0 && (
        <Panel title={`我的音色库 · ${library.length} 个`}>
          <p className="mb-4 text-xs text-[var(--muted)]">点击卡片试听参考音；保存后可在下方「克隆音色」选用。</p>
          <div className="grid gap-3 sm:grid-cols-2">
            {library.map((v) => {
              const isPlaying = playingId === v.id
              const src = v.source_type === 'record' ? '录音' : v.source_type === 'upload' ? '上传' : '克隆'
              return (
                <div
                  key={v.id}
                  role="button"
                  tabIndex={0}
                  onClick={() => void playLibraryVoice(v)}
                  onKeyDown={(e) => e.key === 'Enter' && void playLibraryVoice(v)}
                  className={`group relative overflow-hidden rounded-2xl border p-4 text-left transition ${
                    isPlaying
                      ? 'border-[var(--accent)] bg-[var(--select-bg)] shadow-[0_0_24px_var(--select-shadow)]'
                      : 'border-[var(--border)] bg-[var(--bg)] hover:border-[var(--accent)] hover:shadow-md'
                  } ${v.preview_url || v.local_path || v.reference_wav ? 'cursor-pointer' : 'cursor-default opacity-80'}`}
                >
                  <div
                    className="pointer-events-none absolute -right-6 -top-6 h-24 w-24 rounded-full opacity-20 blur-2xl transition group-hover:opacity-40"
                    style={{
                      background: isPlaying
                        ? 'linear-gradient(135deg, var(--accent), var(--accent-2))'
                        : 'linear-gradient(135deg, var(--accent), transparent)',
                    }}
                  />
                  <div className="relative flex items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span
                          className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-lg ${
                            isPlaying ? 'bg-[var(--accent)] text-white animate-pulse' : 'bg-[var(--panel-2)]'
                          }`}
                        >
                          {isPlaying ? '🔊' : '🎤'}
                        </span>
                        <div className="min-w-0">
                          <div className="truncate text-sm font-semibold">{v.name}</div>
                          <div className="mt-0.5 flex flex-wrap gap-1">
                            <span className="rounded-md bg-[var(--badge-bg)] px-1.5 py-0.5 text-[10px] text-[var(--badge-text)]">
                              {backendLabel(v.backend)}
                            </span>
                            <span className="rounded-md border border-[var(--border)] px-1.5 py-0.5 text-[10px] text-[var(--muted)]">
                              {src}
                            </span>
                          </div>
                        </div>
                      </div>
                      {v.created_at && (
                        <p className="mt-2 text-[10px] text-[var(--muted)]">
                          {v.created_at.slice(0, 16).replace('T', ' ')}
                        </p>
                      )}
                      {v.prompt_text && (
                        <p className="mt-1 line-clamp-2 text-[10px] text-[var(--muted)]" title={v.prompt_text}>
                          参考文案：{v.prompt_text}
                        </p>
                      )}
                      {(v.backend === 'cosyvoice' || v.backend === 'qwen3_local') && !v.prompt_text && (
                        <p className="mt-1 text-[10px] text-amber-600">
                          缺参考文案，建议重新保存
                        </p>
                      )}
                    </div>
                    <button
                      type="button"
                      onClick={(e) => askRemoveVoice(v, e)}
                      className="relative z-10 shrink-0 rounded-lg border border-red-900/40 px-2 py-1 text-[10px] text-red-400 hover:bg-red-500/10"
                    >
                      删除
                    </button>
                  </div>
                  {(v.preview_url || v.local_path || v.reference_wav) && (
                    <p className="relative mt-3 text-[10px] text-[var(--muted)]">
                      {isPlaying ? '播放中… 点击卡片暂停' : '点击卡片试听'}
                    </p>
                  )}
                </div>
              )
            })}
          </div>
        </Panel>
      )}

      <AlertModal
        open={!!alert}
        title={alert?.title || ''}
        message={alert?.message || ''}
        variant={alert?.variant || 'info'}
        onClose={() => setAlert(null)}
      />
      <AlertModal
        open={!!pendingDelete}
        title="删除音色"
        message={
          pendingDelete
            ? `确定删除「${pendingDelete.name}」？删除后不可恢复，配音页将无法再选用该克隆音色。`
            : ''
        }
        variant="warning"
        confirmLabel="删除"
        confirmBusy={deleting}
        onConfirm={() => void confirmRemoveVoice()}
        onClose={() => {
          if (!deleting) setPendingDelete(null)
        }}
      />
    </div>
  )
}

function ModeBtn({
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
      className={`rounded-lg px-4 py-2 text-sm transition ${
        active
          ? 'bg-[var(--select-bg)] font-semibold text-[var(--accent)] shadow-sm'
          : 'text-[var(--muted)] hover:text-[var(--text)]'
      }`}
    >
      {children}
    </button>
  )
}

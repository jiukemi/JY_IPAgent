import { useCallback, useEffect, useRef, useState } from 'react'
import { api, mediaUrl } from '../api/client'
import { FileDropZone } from './FileDropZone'
import { formatAudioDuration } from './AudioPreviewButton'

export type DubTrack = {
  id?: string
  name: string
  path: string
  created_at?: string
  duration_sec?: number | null
  segment_count?: number | null
  source?: string
}

type SourceTab = 'latest' | 'record' | 'upload'

type Props = {
  sessionPath: string
  dubs: DubTrack[]
  /** Latest TTS / active session dubbing path */
  latestPath: string | null
  selectedPath: string | null
  onSelectedChange: (path: string | null) => void | Promise<void>
  onSessionRefresh: () => void | Promise<void>
  /** Bust browser cache when dubbing file is regenerated */
  cacheBust?: number | null
  /** TTS segment timeline for current 成片 */
  segments?: { index: number; start: number; end: number; text: string }[]
  /** Current TTS voice — required for per-segment re-synth */
  voiceUid?: string
  speedMode?: string
  title?: string
  compact?: boolean
}

export function DubbingSourcePanel({
  sessionPath,
  dubs,
  latestPath,
  selectedPath,
  onSelectedChange,
  onSessionRefresh,
  cacheBust = null,
  segments = [],
  voiceUid = '',
  speedMode = 'balanced',
  title = '配音音轨',
  compact = false,
}: Props) {
  const [tab, setTab] = useState<SourceTab>('latest')
  const [recording, setRecording] = useState(false)
  const [recordSec, setRecordSec] = useState(0)
  const [recordedSec, setRecordedSec] = useState<number | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [pendingFile, setPendingFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [saveName, setSaveName] = useState('我的配音')
  const [segTexts, setSegTexts] = useState<Record<number, string>>({})
  const [patchingIndex, setPatchingIndex] = useState<number | null>(null)
  const [segRecordIndex, setSegRecordIndex] = useState<number | null>(null)

  const recorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const timerRef = useRef<number | null>(null)
  const recordSecRef = useRef(0)
  const prevLatestRef = useRef<string | null>(null)
  const segFileRef = useRef<HTMLInputElement | null>(null)
  const segUploadIndexRef = useRef<number | null>(null)

  useEffect(() => {
    const next: Record<number, string> = {}
    for (const s of segments) next[s.index] = s.text || ''
    setSegTexts(next)
  }, [segments])

  useEffect(() => {
    if (!latestPath) return
    const prevLatest = prevLatestRef.current
    if (!selectedPath || (prevLatest && selectedPath === prevLatest)) {
      void onSelectedChange(latestPath)
    }
    prevLatestRef.current = latestPath
  }, [latestPath]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    return () => {
      if (previewUrl?.startsWith('blob:')) URL.revokeObjectURL(previewUrl)
    }
  }, [previewUrl])

  const setLocalPreview = (f: File | null) => {
    if (previewUrl?.startsWith('blob:')) URL.revokeObjectURL(previewUrl)
    setPendingFile(f)
    setPreviewUrl(f ? URL.createObjectURL(f) : null)
  }

  const applyUpload = useCallback(
    async (file: File, sourceType: 'upload' | 'record') => {
      setBusy(true)
      setMsg('')
      try {
        const res = await api.uploadSessionDubbing(sessionPath, file, sourceType)
        const path =
          (res.data?.audio_path as string) ||
          (res.data?.session as { dubbing_audio?: string })?.dubbing_audio ||
          latestPath
        if (path) onSelectedChange(path)
        setTab('latest')
        setLocalPreview(null)
        setRecordedSec(null)
        await onSessionRefresh()
        setMsg(res.message || '已设为当前配音')
      } catch (e) {
        setMsg(e instanceof Error ? e.message : String(e))
      } finally {
        setBusy(false)
      }
    },
    [sessionPath, latestPath, onSelectedChange, onSessionRefresh],
  )

  const startRecord = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mime = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : 'audio/webm'
      const rec = new MediaRecorder(stream, { mimeType: mime })
      chunksRef.current = []
      rec.ondataavailable = (ev) => {
        if (ev.data.size > 0) chunksRef.current.push(ev.data)
      }
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop())
        const blob = new Blob(chunksRef.current, { type: mime })
        const f = new File([blob], `dub_${Date.now()}.webm`, { type: mime })
        setRecordedSec(recordSecRef.current)
        setLocalPreview(f)
        if (timerRef.current) window.clearInterval(timerRef.current)
        setRecordSec(0)
        recordSecRef.current = 0
        setRecording(false)
      }
      recorderRef.current = rec
      rec.start(200)
      setRecording(true)
      setRecordSec(0)
      recordSecRef.current = 0
      timerRef.current = window.setInterval(() => {
        setRecordSec((s) => {
          const n = s + 1
          recordSecRef.current = n
          return n
        })
      }, 1000)
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '无法访问麦克风')
    }
  }

  const stopRecord = () => {
    recorderRef.current?.stop()
    recorderRef.current = null
  }

  const exportUrl = selectedPath
    ? `/api/files/session?path=${encodeURIComponent(selectedPath)}`
    : null

  const saveNamed = async () => {
    if (!selectedPath) return
    setBusy(true)
    try {
      const res = await api.saveSessionDubbing(sessionPath, saveName, selectedPath)
      await onSessionRefresh()
      setMsg(res.message || '已保存')
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const deleteSaved = async (dub: DubTrack) => {
    if (!dub.id || dub.id === '_current') return
    if (!window.confirm(`确定删除配音「${dub.name}」？此操作不可恢复。`)) return
    setBusy(true)
    setMsg('')
    try {
      const res = await api.deleteSessionDubbing(sessionPath, dub.id)
      if (selectedPath === dub.path) {
        onSelectedChange(latestPath)
      }
      await onSessionRefresh()
      setMsg(res.message || '已删除')
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const runPatch = async (
    segmentIndex: number,
    mode: 'resynth' | 'replace' | 'record',
    audio?: File,
  ) => {
    setBusy(true)
    setPatchingIndex(segmentIndex)
    setMsg('')
    try {
      const res = await api.patchDubbingSegment({
        sessionPath,
        segmentIndex,
        mode,
        text: segTexts[segmentIndex] ?? '',
        voiceUid: voiceUid || undefined,
        speedMode,
        audio,
      })
      const path =
        (res.data?.audio_path as string) ||
        (res.data?.session as { dubbing_audio?: string })?.dubbing_audio ||
        latestPath
      if (path) await onSelectedChange(path)
      await onSessionRefresh()
      setMsg(res.message || '段落已修补')
      setSegRecordIndex(null)
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
      setPatchingIndex(null)
    }
  }

  const startSegRecord = async (segmentIndex: number) => {
    setSegRecordIndex(segmentIndex)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mime = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : 'audio/webm'
      const rec = new MediaRecorder(stream, { mimeType: mime })
      chunksRef.current = []
      rec.ondataavailable = (ev) => {
        if (ev.data.size > 0) chunksRef.current.push(ev.data)
      }
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop())
        const blob = new Blob(chunksRef.current, { type: mime })
        const f = new File([blob], `seg_${segmentIndex}_${Date.now()}.webm`, { type: mime })
        if (timerRef.current) window.clearInterval(timerRef.current)
        setRecordSec(0)
        recordSecRef.current = 0
        setRecording(false)
        void runPatch(segmentIndex, 'record', f)
      }
      recorderRef.current = rec
      rec.start(200)
      setRecording(true)
      setRecordSec(0)
      recordSecRef.current = 0
      timerRef.current = window.setInterval(() => {
        setRecordSec((s) => {
          const n = s + 1
          recordSecRef.current = n
          return n
        })
      }, 1000)
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '无法访问麦克风')
      setSegRecordIndex(null)
    }
  }

  const savedDubs = dubs.filter((d) => d.id !== '_current')
  const currentDub = dubs.find((d) => d.id === '_current')
  const onCurrentTrack =
    !!selectedPath &&
    (selectedPath === currentDub?.path || selectedPath === latestPath || selectedPath.endsWith('dubbing_16k.wav'))
  const showSegments = onCurrentTrack && segments.length > 0

  const activePreview = selectedPath ? mediaUrl(selectedPath, cacheBust) : null

  const trackLabel = (d: DubTrack) => {
    const parts = [d.name]
    if (d.duration_sec != null && d.duration_sec > 0) {
      parts.push(formatAudioDuration(d.duration_sec))
    }
    if (d.segment_count != null && d.segment_count > 0) {
      parts.push(`${d.segment_count}段`)
    }
    if (d.created_at) {
      parts.push(d.created_at.slice(0, 16).replace('T', ' '))
    }
    return parts.join(' · ')
  }

  return (
    <div className={compact ? 'space-y-2' : 'space-y-3'}>
      {!compact && <div className="text-xs font-medium text-[var(--muted)]">{title}</div>}

      <div className="inline-flex rounded-xl border border-[var(--border)] bg-[var(--bg)] p-1 text-xs">
        <TabBtn active={tab === 'latest'} onClick={() => setTab('latest')}>
          最新成片
        </TabBtn>
        <TabBtn active={tab === 'record'} onClick={() => setTab('record')}>
          麦克风录音
        </TabBtn>
        <TabBtn active={tab === 'upload'} onClick={() => setTab('upload')}>
          上传文件
        </TabBtn>
      </div>

      {tab === 'latest' && (
        <div className="space-y-2">
          {dubs.length > 0 ? (
            <>
              <div className="text-[10px] text-[var(--muted)]">
                历次配音会自动归档到下方列表（当前成片不可删，历史可删）
              </div>
              <div className="max-h-56 space-y-1.5 overflow-y-auto">
                {dubs.map((d) => {
                  const isCurrent = d.id === '_current'
                  const selected = selectedPath === d.path
                  return (
                    <div
                      key={(d.id || d.path) + d.path}
                      className={`rounded-lg border px-2 py-1.5 ${
                        selected
                          ? 'border-[var(--accent)] bg-[var(--select-bg)]'
                          : 'border-[var(--border)] bg-[var(--panel)]'
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={() => onSelectedChange(d.path)}
                          className={`min-w-0 flex-1 truncate text-left text-xs ${
                            selected ? 'font-medium text-[var(--accent)]' : 'text-[var(--text)]'
                          }`}
                        >
                          {trackLabel(d)}
                        </button>
                        {!isCurrent && d.id && (
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => void deleteSaved(d)}
                            className="shrink-0 rounded px-2 py-0.5 text-[10px] text-red-600 hover:bg-red-500/10 dark:text-red-300"
                          >
                            删除
                          </button>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
              {showSegments && (
                <details open className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-xs">
                  <summary className="cursor-pointer text-[var(--muted)]">
                    按段修补（{segments.length} 段）· 重合成 / 重录会贴齐原时长并淡入淡出
                  </summary>
                  <p className="mt-1.5 text-[10px] leading-relaxed text-[var(--muted)]">
                    使用上方已选音色重合成；或对本段录音/上传。修补后原轨归档，并另存「修补段」副本便于回退。
                  </p>
                  <ol className="mt-2 max-h-72 space-y-2 overflow-y-auto">
                    {segments.map((s) => {
                      const working = patchingIndex === s.index
                      const recordingThis = recording && segRecordIndex === s.index
                      return (
                        <li
                          key={s.index}
                          className="rounded-lg border border-[var(--border)] bg-[var(--panel)] px-2 py-2 text-[var(--text)]"
                        >
                          <div className="mb-1 flex flex-wrap items-center gap-2">
                            <span className="font-mono text-[10px] text-[var(--muted)]">
                              #{s.index} {formatAudioDuration(s.start)}–{formatAudioDuration(s.end)}
                            </span>
                            {working && <span className="text-[10px] text-[var(--accent)]">处理中…</span>}
                            {recordingThis && (
                              <span className="text-[10px] text-red-500">
                                录音中 {formatAudioDuration(recordSec)}
                              </span>
                            )}
                          </div>
                          <textarea
                            value={segTexts[s.index] ?? s.text}
                            onChange={(e) =>
                              setSegTexts((prev) => ({ ...prev, [s.index]: e.target.value }))
                            }
                            rows={2}
                            disabled={busy}
                            className="mb-1.5 w-full rounded-md border border-[var(--border)] bg-[var(--bg)] px-2 py-1 text-[11px] leading-snug"
                          />
                          <div className="flex flex-wrap gap-1.5">
                            <button
                              type="button"
                              disabled={busy || !voiceUid}
                              title={!voiceUid ? '请先在上方选择音色' : undefined}
                              onClick={() => void runPatch(s.index, 'resynth')}
                              className="rounded border border-[var(--select-border)] bg-[var(--select-bg)] px-2 py-0.5 text-[10px] text-[var(--accent)] disabled:opacity-40"
                            >
                              重合成
                            </button>
                            {!recordingThis ? (
                              <button
                                type="button"
                                disabled={busy}
                                onClick={() => void startSegRecord(s.index)}
                                className="rounded border border-[var(--border)] px-2 py-0.5 text-[10px] hover:bg-[var(--bg)] disabled:opacity-40"
                              >
                                重录此段
                              </button>
                            ) : (
                              <button
                                type="button"
                                onClick={stopRecord}
                                className="rounded border border-red-400/60 px-2 py-0.5 text-[10px] text-red-500"
                              >
                                停止并替换
                              </button>
                            )}
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() => {
                                segUploadIndexRef.current = s.index
                                segFileRef.current?.click()
                              }}
                              className="rounded border border-[var(--border)] px-2 py-0.5 text-[10px] hover:bg-[var(--bg)] disabled:opacity-40"
                            >
                              上传替换
                            </button>
                          </div>
                        </li>
                      )
                    })}
                  </ol>
                  <input
                    ref={segFileRef}
                    type="file"
                    accept="audio/*,.wav,.mp3,.m4a,.ogg,.webm,.flac"
                    className="hidden"
                    onChange={(e) => {
                      const f = e.target.files?.[0]
                      const idx = segUploadIndexRef.current
                      e.target.value = ''
                      if (f && idx != null) void runPatch(idx, 'replace', f)
                    }}
                  />
                </details>
              )}
            </>
          ) : (
            <p className="text-xs text-[var(--muted)]">暂无配音，请生成 TTS 或录音/上传。</p>
          )}
        </div>
      )}

      {tab === 'record' && (
        <div className="rounded-xl border border-[var(--border)] bg-[var(--bg)] px-4 py-5 text-center">
          <p className="font-mono text-xl tabular-nums">{formatAudioDuration(recordSec)}</p>
          <p className="mt-1 text-xs text-[var(--muted)]">
            {recording ? '录音中…' : recordedSec != null ? `已录 ${formatAudioDuration(recordedSec)}` : '点击开始录音'}
          </p>
          <div className="mt-3 flex justify-center gap-2">
            {!recording ? (
              <button type="button" onClick={startRecord} className="btn-primary rounded-lg px-4 py-2 text-xs">
                开始录音
              </button>
            ) : (
              <button
                type="button"
                onClick={stopRecord}
                className="rounded-lg border border-red-400/60 px-4 py-2 text-xs text-red-500"
              >
                停止
              </button>
            )}
            {pendingFile && !recording && (
              <button
                type="button"
                disabled={busy}
                onClick={() => void applyUpload(pendingFile, 'record')}
                className="rounded-lg border border-[var(--select-border)] bg-[var(--select-bg)] px-4 py-2 text-xs text-[var(--accent)]"
              >
                {busy ? '保存中…' : '使用此录音'}
              </button>
            )}
          </div>
        </div>
      )}

      {tab === 'upload' && (
        <div className="space-y-2">
          <FileDropZone
            file={pendingFile}
            onFile={(f) => setLocalPreview(f)}
            accept="audio/*,.wav,.mp3,.m4a,.ogg,.webm,.flac"
            icon="🎵"
            emptyTitle="拖拽音频到此处"
            emptyHint="或点击选择 · wav / mp3 / m4a / ogg / webm"
            chooseLabel="选择音频文件"
            replaceLabel="更换音频"
            accent
          />
          {pendingFile && (
            <button
              type="button"
              disabled={busy}
              onClick={() => void applyUpload(pendingFile, 'upload')}
              className="w-full rounded-xl btn-primary py-2.5 text-sm font-semibold"
            >
              {busy ? '导入中…' : '使用上传的音频作为配音'}
            </button>
          )}
        </div>
      )}

      {(activePreview || previewUrl) && (
        <audio src={activePreview || previewUrl || undefined} controls className="w-full" />
      )}

      <div className="flex flex-wrap items-center gap-2">
        {exportUrl && (
          <a
            href={exportUrl}
            download
            className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs hover:bg-[var(--panel)]"
          >
            导出 WAV
          </a>
        )}
        {selectedPath && (
          <>
            <input
              value={saveName}
              onChange={(e) => setSaveName(e.target.value)}
              className="max-w-[8rem] rounded-lg border border-[var(--border)] bg-[var(--bg)] px-2 py-1 text-xs"
              placeholder="命名保存"
            />
            <button
              type="button"
              disabled={busy}
              onClick={() => void saveNamed()}
              className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs hover:bg-[var(--panel)]"
            >
              另存副本
            </button>
            {savedDubs.some((d) => d.path === selectedPath) && (
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  const d = savedDubs.find((x) => x.path === selectedPath)
                  if (d) void deleteSaved(d)
                }}
                className="rounded-lg border border-red-300/50 px-3 py-1.5 text-xs text-red-600 hover:bg-red-500/10 dark:text-red-300"
              >
                删除选中副本
              </button>
            )}
          </>
        )}
      </div>
      {msg && <p className="text-xs text-[var(--muted)]">{msg}</p>}
    </div>
  )
}

function TabBtn({
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
      className={`rounded-lg px-3 py-1.5 transition ${
        active ? 'bg-[var(--select-bg)] font-semibold text-[var(--accent)]' : 'text-[var(--muted)]'
      }`}
    >
      {children}
    </button>
  )
}

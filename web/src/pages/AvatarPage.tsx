import { useCallback, useEffect, useState } from 'react'
import { api, mediaUrl } from '../api/client'
import { AlertModal, parseApiError } from '../components/AlertModal'
import { AssetPickerModal, type PickerAsset } from '../components/AssetPickerModal'
import { AvatarPickerModal, type AvatarItem } from '../components/AvatarPickerModal'
import { DubbingSourcePanel } from '../components/DubbingSourcePanel'
import { FileDropZone } from '../components/FileDropZone'
import { HeyGemServicePanel } from '../components/HeyGemServicePanel'
import { useJobQueue } from '../context/JobQueueContext'
import type { SessionSnapshot } from '../types'
import { detectVideoDuration } from '../utils/mediaFileMeta'
import {
  PhonePreviewColumn,
  PhonePreviewSlot,
  type PreviewAspect,
} from '../components/PhonePreviewColumn'
import { PhoneFitVideo } from '../components/PhonePreviewFrame'
import { InAppVideoTheater } from '../components/InAppVideoTheater'
import { ActionBtn, Panel } from './ScriptPage'

type Props = { session: SessionSnapshot; onUpdate: (s: SessionSnapshot) => void }

type LibraryPick = { id: string; name: string; mediaType: 'image' | 'video'; previewUrl?: string | null }

function isImageUploadFile(f: File): boolean {
  return f.type.startsWith('image/') || /\.(jpe?g|png|webp|bmp)$/i.test(f.name)
}

const QUALITY_OPTIONS = [
  { id: 'high', label: '高画质', hint: '最佳效果，最慢' },
  { id: 'balanced', label: '均衡', hint: '质量与速度兼顾' },
  { id: 'fast', label: '快速', hint: '试跑用，画质会差一些' },
] as const

const TRACK_OPTIONS = [
  { id: 'digital', label: '数字人口播', hint: '推荐：HeyGem + 参考视频' },
  { id: 'real', label: '实拍换嘴', hint: '用实拍视频换嘴（LatentSync）' },
] as const

const ENGINE_OPTIONS = [
  {
    id: 'heygem',
    label: 'HeyGem',
    hint: '推荐 · 需 10–20 秒参考视频，动作最自然',
  },
  {
    id: 'sadtalker',
    label: 'SadTalker',
    hint: '仅有静图时备选 · 效果明显弱于 HeyGem',
  },
] as const

const PORTRAIT_BACKENDS = new Set(['sadtalker'])

function ChoiceChip({
  checked,
  label,
  hint,
  onSelect,
  disabled,
}: {
  checked: boolean
  label: string
  hint?: string
  onSelect: () => void
  disabled?: boolean
}) {
  return (
    <label
      className={`flex cursor-pointer items-start gap-2 rounded-xl border px-3 py-2 text-left transition-colors ${
        checked
          ? 'border-[var(--accent)] bg-[var(--select-bg)]'
          : 'border-[var(--border)] bg-[var(--bg)] hover:border-[var(--accent)]/40'
      } ${disabled ? 'cursor-not-allowed opacity-50' : ''}`}
    >
      <input
        type="checkbox"
        className="mt-0.5"
        checked={checked}
        disabled={disabled}
        onChange={() => {
          if (!disabled) onSelect()
        }}
      />
      <span className="min-w-0">
        <span className="block text-xs font-medium text-[var(--text)]">{label}</span>
        {hint ? <span className="mt-0.5 block text-[10px] leading-snug text-[var(--muted)]">{hint}</span> : null}
      </span>
    </label>
  )
}

export function AvatarPage({ session, onUpdate }: Props) {
  const jobQueue = useJobQueue()
  const [trackMode, setTrackMode] = useState('digital')
  const [backend, setBackend] = useState('heygem')
  const [quality, setQuality] = useState('balanced')
  const [avatar, setAvatar] = useState<AvatarItem | null>(null)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [assetPicker, setAssetPicker] = useState<null | 'media' | 'ref_pose'>(null)
  const [media, setMedia] = useState<File | null>(null)
  const [libraryMedia, setLibraryMedia] = useState<LibraryPick | null>(null)
  const [mediaDurationSec, setMediaDurationSec] = useState<number | null>(null)
  const [refPose, setRefPose] = useState<File | null>(null)
  const [libraryRefPose, setLibraryRefPose] = useState<LibraryPick | null>(null)
  const [refPoseOpen, setRefPoseOpen] = useState(false)
  const [expressionScale, setExpressionScale] = useState(1)
  const [stillHead, setStillHead] = useState(false)
  const [heygemReady, setHeygemReady] = useState<boolean | null>(null)
  const [log, setLog] = useState(session.lipsync_log || '')
  const [enqueueBusy, setEnqueueBusy] = useState(false)
  const avatarJob = jobQueue.jobs.find(
    (j) => j.type === 'avatar_lipsync' && (j.status === 'queued' || j.status === 'running'),
  )
  const progress = avatarJob
    ? { pct: avatarJob.progress || 0, msg: avatarJob.message || '处理中…' }
    : null
  const busy = Boolean(avatarJob) || enqueueBusy
  const [alert, setAlert] = useState<{
    title: string
    message: string
    variant: 'error' | 'warning' | 'success' | 'info'
  } | null>(null)
  /** User-selected target aspect for preview / guidance (HeyGem follows reference video). */
  const [targetAspect, setTargetAspect] = useState<PreviewAspect>('9:16')
  const [avatarAspect, setAvatarAspect] = useState<PreviewAspect | null>(null)
  const [theaterOpen, setTheaterOpen] = useState(false)
  const [previewBust, setPreviewBust] = useState<number | null>(null)
  const [previewWarming, setPreviewWarming] = useState(false)

  const probeVideoAspect = useCallback((url: string) => {
    if (!url) {
      setAvatarAspect(null)
      return
    }
    const el = document.createElement('video')
    el.preload = 'metadata'
    el.onloadedmetadata = () => {
      if (el.videoWidth > 0 && el.videoHeight > 0) {
        const asp: PreviewAspect = el.videoWidth >= el.videoHeight ? '16:9' : '9:16'
        setAvatarAspect(asp)
      } else {
        setAvatarAspect(null)
      }
    }
    el.onerror = () => setAvatarAspect(null)
    el.src = url
  }, [])

  useEffect(() => {
    if (avatar?.source_kind === 'video' && avatar.preview_url) {
      probeVideoAspect(avatar.preview_url)
    } else {
      setAvatarAspect(null)
    }
  }, [avatar?.id, avatar?.preview_url, avatar?.source_kind, probeVideoAspect])

  const selectedDubPath = session.selected_dub ?? session.dubbing_audio
  const selectedLipsyncPath = session.selected_lipsync ?? session.lipsync_video
  const lipsyncTakes = session.lipsyncs || []

  const refreshSession = async () => {
    onUpdate(await api.sessionSnapshot(session.path))
  }

  const onDubSelect = useCallback(
    async (path: string | null) => {
      if (!path || !session.path) return
      try {
        await api.selectSessionDubbing(session.path, path)
        await refreshSession()
      } catch (e) {
        const { title, message } = parseApiError(e, '切换音轨失败')
        setAlert({ title, message, variant: 'error' })
      }
    },
    [session.path],
  )

  const onLipsyncSelect = useCallback(
    async (path: string) => {
      if (!path || !session.path) return
      try {
        await api.selectSessionLipsync(session.path, path)
        await refreshSession()
      } catch (e) {
        const { title, message } = parseApiError(e, '切换口播成片失败')
        setAlert({ title, message, variant: 'error' })
      }
    },
    [session.path],
  )

  const onLipsyncDelete = useCallback(
    async (takeId: string, takeName: string) => {
      if (!takeId || !session.path) return
      if (!window.confirm(`确定删除口播「${takeName}」？删除后不可恢复。`)) return
      try {
        await api.deleteSessionLipsync(session.path, takeId)
        await refreshSession()
      } catch (e) {
        const { title, message } = parseApiError(e, '删除口播失败')
        setAlert({ title, message, variant: 'error' })
      }
    },
    [session.path],
  )

  const onPickAvatar = (item: AvatarItem) => {
    setAvatar(item)
    setPickerOpen(false)
    if (item.supports_heygem) {
      setBackend('heygem')
    } else if (item.supports_sadtalker) {
      setBackend('sadtalker')
    }
  }

  const onTargetAspectChange = (asp: PreviewAspect) => {
    setTargetAspect(asp)
  }

  const onBackendChange = (value: string) => {
    setBackend(value)
    if (PORTRAIT_BACKENDS.has(value) && avatar && !avatar.supports_sadtalker) {
      // Video avatars are HeyGem-only; clear so user can upload a portrait instead
      setAvatar(null)
    }
    if (value === 'heygem' && avatar && !avatar.supports_heygem) {
      setAvatar(null)
    }
    if (!PORTRAIT_BACKENDS.has(value)) {
      setRefPoseOpen(false)
    }
  }

  useEffect(() => {
    if (refPose || libraryRefPose) setRefPoseOpen(true)
  }, [refPose, libraryRefPose])

  // Auto-pick a library avatar compatible with the current engine (do not force HeyGem video onto SadTalker).
  useEffect(() => {
    if (avatar) return
    if (trackMode !== 'digital') return
    void api.avatarLibrary().then((rows) => {
      const prefer =
        backend === 'sadtalker'
          ? rows.find((r) => r.supports_sadtalker || r.source_kind === 'portrait')
          : rows.find((r) => r.supports_heygem || r.source_kind === 'video')
      if (prefer) setAvatar(prefer)
      else if (rows.length === 1 && backend === 'heygem' && rows[0].supports_heygem) setAvatar(rows[0])
      else if (rows.length === 1 && backend === 'sadtalker' && rows[0].supports_sadtalker) setAvatar(rows[0])
    })
  }, [avatar, backend, trackMode])

  useEffect(() => {
    if (quality === 'high') setExpressionScale(1.15)
    else if (quality === 'fast') setExpressionScale(0.9)
    else setExpressionScale(1)
  }, [quality])

  useEffect(() => {
    if (trackMode !== 'digital' || backend !== 'heygem') {
      setHeygemReady(null)
      return
    }
    void api.heygemStatus().then((s) => setHeygemReady(s.ready))
  }, [trackMode, backend])

  useEffect(() => {
    if (trackMode === 'real') {
      setBackend('latentsync')
    } else if (avatar?.supports_heygem) {
      setBackend('heygem')
    } else if (avatar?.supports_sadtalker) {
      setBackend('sadtalker')
    } else {
      setBackend('heygem')
    }
  }, [trackMode])

  const onRealVideoPick = (file: File | null) => {
    setLibraryMedia(null)
    setMedia(file)
    if (!file) {
      setMediaDurationSec(null)
      return
    }
    void detectVideoDuration(file).then(setMediaDurationSec)
  }

  const onLibraryAssetPick = (asset: PickerAsset) => {
    const pick: LibraryPick = {
      id: asset.id,
      name: asset.name,
      mediaType: asset.media_type,
      previewUrl: asset.preview_url,
    }
    if (assetPicker === 'ref_pose') {
      setLibraryRefPose(pick)
      setRefPose(null)
    } else {
      setLibraryMedia(pick)
      setMedia(null)
      setMediaDurationSec(null)
    }
    setAssetPicker(null)
  }

  const hasMediaSource = Boolean(media || libraryMedia)

  const onRegistered = (item: AvatarItem, message: string) => {
    setAvatar(item)
    setPickerOpen(false)
    if (item.supports_heygem) setBackend('heygem')
    else if (item.supports_sadtalker) setBackend('sadtalker')
    setAlert({
      title: '注册成功',
      message: `${message}\n\n已自动选中「${item.name}」，可点击下方「生成口播视频」。`,
      variant: 'success',
    })
  }

  const run = async () => {
    const audioPath = selectedDubPath || session.dubbing_audio
    if (!audioPath) {
      setLog('请先完成 ② 配音，或在本页录音/上传配音')
      return
    }
    if (trackMode === 'digital' && backend === 'heygem' && !avatar?.supports_heygem) {
      setAlert({
        title: '请选择 HeyGem 形象',
        message: 'HeyGem 需要 10–20 秒参考视频。请在形象库「上传注册」mp4/mov，或切换 SadTalker 使用肖像。',
        variant: 'warning',
      })
      return
    }
    if (trackMode === 'digital' && backend === 'heygem' && heygemReady === false) {
      setAlert({
        title: 'HeyGem 未启动',
        message: '口播引擎未就绪。请下载并启动本机口播组件（无需 Docker Desktop），再生成视频。',
        variant: 'warning',
      })
      return
    }
    const hasPortraitImage =
      Boolean(avatar?.supports_sadtalker) ||
      Boolean(media && isImageUploadFile(media)) ||
      Boolean(libraryMedia?.mediaType === 'image')
    if (
      trackMode === 'digital' &&
      PORTRAIT_BACKENDS.has(backend) &&
      ((media && !isImageUploadFile(media)) || libraryMedia?.mediaType === 'video')
    ) {
      setAlert({
        title: '需要肖像图',
        message:
          '人脸请上传 jpg/png。驱动/动作视频请放到「动作参考视频」；若要用视频形象驱动，请改引擎为 HeyGem。',
        variant: 'warning',
      })
      return
    }
    if (trackMode === 'digital' && PORTRAIT_BACKENDS.has(backend) && !hasPortraitImage) {
      setAlert({
        title: '缺少肖像',
        message:
          '请选择 AI/肖像数字人，或上传 jpg/png。当前若只选了「视频」形象，请先清除后上传肖像，或改用 HeyGem。',
        variant: 'warning',
      })
      return
    }
    if (trackMode === 'real' && !hasMediaSource) {
      setAlert({
        title: '缺少实拍视频',
        message: '实拍对口型请从素材中心选择或上传 mp4/mov 视频。',
        variant: 'warning',
      })
      return
    }
    if (trackMode === 'real' && libraryMedia && libraryMedia.mediaType !== 'video') {
      setAlert({
        title: '素材类型不对',
        message: '实拍对口型需要视频素材，请重新从素材中心选择视频。',
        variant: 'warning',
      })
      return
    }
    setEnqueueBusy(true)
    setLog('')
    try {
      const fd = new FormData()
      fd.append('session_path', session.path)
      fd.append('track_mode', trackMode)
      fd.append('backend', backend)
      fd.append('quality', quality)
      fd.append('force', 'true')
      // Portrait backends only accept portrait avatars; never send a HeyGem video avatar id
      if (
        avatar?.id &&
        (!PORTRAIT_BACKENDS.has(backend) || avatar.supports_sadtalker)
      ) {
        fd.append('avatar_id', avatar.id)
      }
      fd.append('audio_path', audioPath)
      if (media) fd.append('media', media)
      else if (libraryMedia?.id) fd.append('media_asset_id', libraryMedia.id)
      if (refPose) fd.append('ref_pose', refPose)
      else if (libraryRefPose?.id) fd.append('ref_pose_asset_id', libraryRefPose.id)
      if (backend === 'sadtalker') {
        fd.append('expression_scale', String(expressionScale))
        fd.append('still_head', stillHead ? 'true' : 'false')
      }
      const res = await api.lipsyncEnqueue(fd)
      if (res.ok && res.job) {
        jobQueue.setCenterOpen(true)
        await jobQueue.refresh()
        setAlert({
          title: '已加入任务中心',
          message: '口播在后台按序生成，可继续其它步骤；进度与完成后的模型/用时见任务中心。',
          variant: 'success',
        })
      } else {
        setAlert({
          title: '未加入队列',
          message: res.message || '当前已有相同任务',
          variant: 'warning',
        })
        jobQueue.setCenterOpen(true)
        await jobQueue.refresh()
      }
    } catch (e) {
      const { title, message } = parseApiError(e, '口播入队失败')
      setLog(message)
      setAlert({ title, message, variant: 'error' })
    } finally {
      setEnqueueBusy(false)
    }
  }

  useEffect(() => {
    const job = jobQueue.lastFinished
    if (!job || jobQueue.completionTick <= 0) return
    if (job.type !== 'avatar_lipsync') return
    if (job.status === 'done') {
      void api.sessionSnapshot(session.path).then((updated) => {
        onUpdate(updated)
        setLog(typeof job.result?.log === 'string' ? job.result.log : '口播生成完成')
        const model =
          (typeof job.result?.model === 'string' && job.result.model) ||
          (typeof job.payload?.model_label === 'string' && job.payload.model_label) ||
          ''
        const dur =
          typeof job.duration_sec === 'number'
            ? job.duration_sec
            : typeof job.result?.duration_sec === 'number'
              ? job.result.duration_sec
              : null
        const durText =
          dur != null && Number.isFinite(dur)
            ? dur < 60
              ? `${Math.round(dur)} 秒`
              : `${Math.floor(dur / 60)} 分 ${Math.round(dur % 60)} 秒`
            : ''
        setAlert({
          title: '口播生成成功',
          message: [
            model ? `模型：${model}` : '',
            durText ? `用时：${durText}` : '',
            '成片已生成，可在右侧预览。继续下一步请前往 ④ 发布。',
          ]
            .filter(Boolean)
            .join(' · '),
          variant: 'success',
        })
      })
    } else if (job.status === 'failed') {
      setLog(job.error || job.message || '口播失败')
      setAlert({
        title: '口播失败',
        message: job.error || job.message || '请在任务中心查看详情',
        variant: 'error',
      })
    } else if (job.status === 'cancelled') {
      setLog('任务已取消')
      setAlert({ title: '已取消', message: '口播生成已取消。', variant: 'info' })
    }
  }, [jobQueue.completionTick, jobQueue.lastFinished, session.path, onUpdate])

  useEffect(() => {
    const onRefresh = (ev: Event) => {
      const detail = (ev as CustomEvent<{ sessionPath?: string }>).detail
      if (detail?.sessionPath && detail.sessionPath !== session.path) return
      if (!session.path) return
      void api.sessionSnapshot(session.path).then(onUpdate).catch(() => {})
    }
    window.addEventListener('agent:session-refresh', onRefresh)
    return () => window.removeEventListener('agent:session-refresh', onRefresh)
  }, [session.path, onUpdate])

  const lipsyncPath = selectedLipsyncPath || session.lipsync_video || null

  useEffect(() => {
    if (!lipsyncPath) {
      setPreviewBust(null)
      setPreviewWarming(false)
      return
    }
    let cancelled = false
    setPreviewWarming(true)
    void api
      .prepareSessionMedia(lipsyncPath)
      .then((res) => {
        if (cancelled) return
        // Bust URL after optimize so player reloads streamable file
        setPreviewBust(res.optimized ? Date.now() : session.lipsync_mtime ?? Date.now())
      })
      .catch(() => {
        if (!cancelled) setPreviewBust(session.lipsync_mtime ?? Date.now())
      })
      .finally(() => {
        if (!cancelled) setPreviewWarming(false)
      })
    return () => {
      cancelled = true
    }
  }, [lipsyncPath, session.lipsync_mtime, session.path])

  const video = lipsyncPath ? mediaUrl(lipsyncPath, previewBust ?? session.lipsync_mtime) : null

  // Sync target aspect from HeyGem reference video when known (user can still override).
  useEffect(() => {
    if (!avatarAspect || backend !== 'heygem') return
    setTargetAspect(avatarAspect)
  }, [avatarAspect, backend])

  const aspectMismatch =
    backend === 'heygem' && avatarAspect != null && targetAspect !== avatarAspect
  const qualityHint = QUALITY_OPTIONS.find((q) => q.id === quality)?.hint ?? ''
  const dubSec = session.dubbing_duration

  return (
    <>
      {session.lipsync_stale && (
        <div className="mb-4 rounded-xl border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-900 dark:text-amber-100">
          ② 配音已更新
          {dubSec ? `（约 ${Math.round(dubSec)} 秒）` : ''}
          ，但当前口播视频仍是旧版（约 58 秒时会卡在「全场景」附近）。
          请确认上方音轨为「当前成片」，再点下方「生成口播」重新合成。
        </div>
      )}
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(260px,300px)]">
        <Panel title="04 口播 · 参数">
          <DubbingSourcePanel
            sessionPath={session.path}
            dubs={session.dubs || []}
            latestPath={session.dubbing_audio}
            selectedPath={selectedDubPath}
            onSelectedChange={onDubSelect}
            onSessionRefresh={refreshSession}
            cacheBust={session.dubbing_mtime}
            segments={session.dubbing_segments}
            title="配音来源（默认最新成片，可录音/上传）"
            compact
          />

          <div className="mt-4 space-y-3">
            <div>
              <p className="mb-1.5 text-xs font-medium text-[var(--text)]">轨道</p>
              <div className="grid gap-2 sm:grid-cols-2">
                {TRACK_OPTIONS.map((opt) => (
                  <ChoiceChip
                    key={opt.id}
                    checked={trackMode === opt.id}
                    label={opt.label}
                    hint={opt.hint}
                    onSelect={() => setTrackMode(opt.id)}
                  />
                ))}
              </div>
            </div>
            <div>
              <p className="mb-1.5 text-xs font-medium text-[var(--text)]">画质档位</p>
              <div className="grid gap-2 sm:grid-cols-3">
                {QUALITY_OPTIONS.map((q) => (
                  <ChoiceChip
                    key={q.id}
                    checked={quality === q.id}
                    label={q.label}
                    hint={q.hint}
                    onSelect={() => setQuality(q.id)}
                  />
                ))}
              </div>
              {qualityHint ? <p className="mt-1 text-[10px] text-[var(--muted)]">{qualityHint}</p> : null}
            </div>
          </div>

          {trackMode === 'digital' && (
            <>
              <div className="mt-3">
                <p className="mb-1.5 text-xs font-medium text-[var(--text)]">引擎</p>
                <div className="grid gap-2 sm:grid-cols-2">
                  {ENGINE_OPTIONS.map((opt) => (
                    <ChoiceChip
                      key={opt.id}
                      checked={backend === opt.id}
                      label={opt.label}
                      hint={opt.hint}
                      onSelect={() => onBackendChange(opt.id)}
                    />
                  ))}
                </div>
              </div>

              <div className="mt-3 rounded-xl border border-[var(--accent)]/30 bg-[var(--select-bg)] px-3 py-2 text-[10px] leading-relaxed text-[var(--muted)]">
                <strong className="text-[var(--text)]">想要自然效果：</strong>
                用 HeyGem + 10–20 秒正脸口播视频。SadTalker 只能「动一下」，边缘穿模、表情假是模型本身限制，不是设置没开好。
              </div>

              {trackMode === 'digital' && backend === 'heygem' && (
                <div className="mt-3 rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3">
                  <p className="mb-1.5 text-xs font-medium text-[var(--text)]">口播画幅</p>
                  <div className="grid gap-2 sm:grid-cols-2">
                    <ChoiceChip
                      checked={targetAspect === '9:16'}
                      label="竖屏 9:16"
                      hint="抖音/短视频 · 用竖屏参考视频"
                      onSelect={() => onTargetAspectChange('9:16')}
                    />
                    <ChoiceChip
                      checked={targetAspect === '16:9'}
                      label="横屏 16:9"
                      hint="课件/横版口播 · 用横屏参考视频"
                      onSelect={() => onTargetAspectChange('16:9')}
                    />
                  </div>
                  <p className="mt-2 text-[10px] leading-relaxed text-[var(--muted)]">
                    HeyGem 成片画幅跟<strong className="text-[var(--text)]">参考视频</strong>
                    走：选 16:9 请注册/选用横屏形象。此处主要控制预览框与提醒。
                  </p>
                  {avatarAspect && (
                    <p className="mt-1 text-[10px] text-[var(--muted)]">
                      当前形象参考画幅：{avatarAspect === '16:9' ? '横屏' : '竖屏'}
                    </p>
                  )}
                  {aspectMismatch && (
                    <p className="mt-1.5 text-[10px] text-[var(--warn-text)]">
                      所选画幅与参考视频不一致，成片仍以参考视频为准。请更换对应画幅的形象，或改选上方画幅。
                    </p>
                  )}
                </div>
              )}

              {backend === 'heygem' && (
                <HeyGemServicePanel onReadyChange={setHeygemReady} />
              )}
              <div className="mt-3">
                <p className="mb-1.5 text-xs font-medium text-[var(--text)]">数字人形象</p>
                <div className="grid gap-2 sm:grid-cols-2">
                  <ChoiceChip
                    checked={Boolean(avatar)}
                    label={avatar ? avatar.name : '未选择形象'}
                    hint={
                      avatar
                        ? avatar.source_kind === 'video'
                          ? 'HeyGem 视频形象'
                          : 'SadTalker 肖像形象'
                        : backend === 'heygem'
                          ? '点击右侧注册 / 选择视频形象'
                          : '选择肖像形象，或下方上传图片'
                    }
                    onSelect={() => setPickerOpen(true)}
                  />
                  <button
                    type="button"
                    onClick={() => setPickerOpen(true)}
                    className="rounded-xl border border-[var(--select-border)] bg-[var(--select-bg)] px-3 py-2 text-left text-xs font-medium text-[var(--accent)] hover:opacity-90"
                  >
                    {avatar ? '更换 / 注册形象' : '选择 / 注册数字人'}
                    <span className="mt-0.5 block text-[10px] font-normal text-[var(--muted)]">
                      {backend === 'heygem'
                        ? targetAspect === '16:9'
                          ? '上传 10–20 秒横屏参考视频 → 横屏口播'
                          : '上传 10–20 秒竖屏参考视频 → 竖屏口播'
                        : '肖像图或 AI 生成图'}
                    </span>
                  </button>
                </div>
                {avatar?.source_kind === 'portrait' && backend === 'heygem' && (
                  <p className="mt-1.5 text-xs text-[var(--warn-text)]">
                    当前是肖像形象，请切换 SadTalker，或注册 HeyGem 参考视频。
                  </p>
                )}
                {avatar?.source_kind === 'video' && PORTRAIT_BACKENDS.has(backend) && (
                  <p className="mt-1.5 text-xs text-[var(--warn-text)]">
                    当前是 HeyGem 视频形象，本引擎不能用。请选择/上传肖像图，或改回 HeyGem。
                  </p>
                )}
              </div>

              {PORTRAIT_BACKENDS.has(backend) && (
                <div className="mt-3 space-y-3 rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3">
                  <p className="text-[10px] leading-relaxed text-[var(--warn-text)]">
                    SadTalker 效果上限较低：适合「只有一张图」时应急。有实拍视频请改用 HeyGem。
                  </p>

                  <div className={`grid gap-3 ${refPoseOpen ? 'md:grid-cols-2' : 'grid-cols-1'}`}>
                    <div className="space-y-2">
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-xs font-medium text-[var(--text)]">肖像图（必填）</p>
                        <button
                          type="button"
                          onClick={() => setAssetPicker('media')}
                          className="rounded-lg border border-[var(--border)] px-2 py-1 text-[10px] hover:bg-[var(--panel)]"
                        >
                          素材中心
                        </button>
                      </div>
                      {libraryMedia && (
                        <p className="text-[11px] text-[var(--accent)]">
                          素材中心：{libraryMedia.name}
                          <button
                            type="button"
                            className="ml-2 text-[var(--muted)] underline"
                            onClick={() => setLibraryMedia(null)}
                          >
                            清除
                          </button>
                        </p>
                      )}
                      <FileDropZone
                        file={media && isImageUploadFile(media) ? media : null}
                        onFile={(f) => {
                          setLibraryMedia(null)
                          setMedia(f)
                        }}
                        accept="image/*,.jpg,.jpeg,.png,.webp"
                        icon="🖼️"
                        emptyTitle="拖拽肖像图到此处"
                        emptyHint="正脸半身 · jpg / png · 光线均匀"
                        chooseLabel="选择本地肖像图"
                        replaceLabel="更换图片"
                      />
                    </div>

                    {refPoseOpen && (
                      <div className="space-y-2">
                        <div className="flex items-center justify-between gap-2">
                          <p className="text-xs font-medium text-[var(--text)]">动作参考视频</p>
                          <div className="flex items-center gap-1">
                            <button
                              type="button"
                              onClick={() => setAssetPicker('ref_pose')}
                              className="rounded-lg border border-[var(--border)] px-2 py-1 text-[10px] hover:bg-[var(--panel)]"
                            >
                              素材中心
                            </button>
                            <button
                              type="button"
                              onClick={() => {
                                setRefPoseOpen(false)
                                setRefPose(null)
                                setLibraryRefPose(null)
                              }}
                              className="rounded-lg px-2 py-1 text-[10px] text-[var(--muted)] underline"
                            >
                              收起
                            </button>
                          </div>
                        </div>
                        {libraryRefPose && (
                          <p className="text-[11px] text-[var(--accent)]">
                            素材中心：{libraryRefPose.name}
                            <button
                              type="button"
                              className="ml-2 text-[var(--muted)] underline"
                              onClick={() => setLibraryRefPose(null)}
                            >
                              清除
                            </button>
                          </p>
                        )}
                        <FileDropZone
                          file={refPose}
                          onFile={(f) => {
                            setLibraryRefPose(null)
                            setRefPose(f)
                          }}
                          accept="video/*,.mp4,.mov,.webm"
                          icon="🎥"
                          emptyTitle="拖拽参考视频"
                          emptyHint="5–15 秒正脸轻动 · mp4 / mov"
                          chooseLabel="选择本地参考视频"
                          replaceLabel="更换视频"
                        />
                        <ul className="space-y-0.5 rounded-lg border border-[var(--border)] bg-[var(--panel)] px-2.5 py-2 text-[10px] leading-relaxed text-[var(--muted)]">
                          <li>
                            · 只借用头姿/轻微晃动，
                            <strong className="text-[var(--text)]">不能</strong>
                            变成 HeyGem 那种真人驱动
                          </li>
                          <li>· 建议 5–15 秒，单人正脸，光线稳，动作自然（点头即可）</li>
                          <li>· 避免剧烈甩头、遮挡嘴部、多人入镜</li>
                          <li>· 人物朝向尽量与肖像一致；过长视频更慢、收益有限</li>
                        </ul>
                      </div>
                    )}
                  </div>

                  {!refPoseOpen && (
                    <button
                      type="button"
                      onClick={() => setRefPoseOpen(true)}
                      className="w-full rounded-xl border border-dashed border-[var(--border)] px-3 py-2 text-left text-xs text-[var(--accent)] hover:bg-[var(--select-bg)]"
                    >
                      上传动作参考视频（可选）
                      <span className="mt-0.5 block text-[10px] font-normal text-[var(--muted)]">
                        略改善头动；默认不必传。展开后与肖像并排显示
                      </span>
                    </button>
                  )}

                  <label className="flex items-center gap-2 text-xs text-[var(--muted)]">
                    <input type="checkbox" checked={stillHead} onChange={(e) => setStillHead(e.target.checked)} />
                    固定头部（只动嘴，更快）
                  </label>
                  <label className="block text-xs text-[var(--muted)]">
                    表情幅度 {expressionScale.toFixed(2)}
                    <input
                      type="range"
                      min={0.6}
                      max={1.4}
                      step={0.05}
                      value={expressionScale}
                      onChange={(e) => setExpressionScale(Number(e.target.value))}
                      className="mt-1 w-full"
                    />
                  </label>
                </div>
              )}
            </>
          )}

          {trackMode === 'real' && (
            <>
              <div className="mt-3">
                <p className="mb-1.5 text-xs font-medium text-[var(--text)]">引擎</p>
                <ChoiceChip
                  checked={backend === 'latentsync'}
                  label="LatentSync"
                  hint="精修换嘴 · 很慢（约成片时长×十几～几十倍）"
                  onSelect={() => setBackend('latentsync')}
                />
              </div>

              <div className="mt-4 space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-sm font-semibold text-[var(--text)]">实拍视频</p>
                  {hasMediaSource && (
                    <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] font-medium text-emerald-700 dark:text-emerald-300">
                      已就绪
                    </span>
                  )}
                </div>
                <p className="text-[11px] leading-relaxed text-[var(--muted)]">
                  正脸口播实拍 mp4/mov，用 ② 配音换嘴。支持<strong className="text-[var(--text)]">素材中心</strong>、拖拽或本地上传。
                </p>
                <button
                  type="button"
                  onClick={() => setAssetPicker('media')}
                  className="rounded-lg border border-[var(--accent)] px-3 py-1.5 text-xs text-[var(--accent)] hover:bg-[var(--select-bg)]"
                >
                  从素材中心选择
                </button>
                {libraryMedia && (
                  <p className="text-[11px] text-[var(--accent)]">
                    素材中心：{libraryMedia.name}
                    <button
                      type="button"
                      className="ml-2 text-[var(--muted)] underline"
                      onClick={() => setLibraryMedia(null)}
                    >
                      清除
                    </button>
                  </p>
                )}
                <FileDropZone
                  file={media}
                  onFile={onRealVideoPick}
                  accept="video/*,.mp4,.mov,.webm,.mkv,.m4v"
                  icon="🎬"
                  emptyTitle="拖拽实拍视频到此处"
                  emptyHint="或点击选择本地文件 · mp4 / mov / webm · 建议正脸、光线均匀"
                  chooseLabel="选择本地视频"
                  replaceLabel="更换视频"
                  accent
                  meta={
                    mediaDurationSec != null ? (
                      <p className="text-[var(--muted)]">
                        时长 {mediaDurationSec.toFixed(1)} 秒
                        {mediaDurationSec < 3 ? (
                          <span className="ml-1 text-[var(--warn-text)]">· 过短，建议 5 秒以上</span>
                        ) : null}
                      </p>
                    ) : media ? (
                      <p className="text-[var(--warn-text)]">无法读取时长，请确认视频可正常播放</p>
                    ) : null
                  }
                />
              </div>
            </>
          )}

          <div className="mt-4 flex flex-wrap items-center gap-2">
            <ActionBtn primary disabled={busy} onClick={run}>
              {enqueueBusy ? '加入队列…' : avatarJob ? '生成中…' : '生成口播视频'}
            </ActionBtn>
            {avatarJob && (
              <ActionBtn
                onClick={() => void jobQueue.cancelJob(avatarJob.id)}
              >
                终止任务
              </ActionBtn>
            )}
            {avatarJob && (
              <ActionBtn onClick={() => jobQueue.setCenterOpen(true)}>
                任务中心
              </ActionBtn>
            )}
            {busy && (
              <p className="w-full text-[10px] text-[var(--muted)]">
                进度见任务中心 · {progress?.msg || '排队/处理中…'}
                {progress != null ? ` (${Math.round(progress.pct * 100)}%)` : ''}
              </p>
            )}
          </div>

          {log && (
            <pre className="mt-3 max-h-40 overflow-auto rounded-xl bg-[var(--bg)] p-3 text-xs text-[var(--muted)]">
              {log}
            </pre>
          )}
        </Panel>

        <PhonePreviewColumn aspect="9:16">
          <PhonePreviewSlot
            label={
              previewWarming
                ? '口播成片 · 正在优化历史视频…'
                : targetAspect === '16:9'
                  ? '口播成片 · 横屏素材（9:16 框内自适应）'
                  : '口播成片 · 竖屏'
            }
            aspect="9:16"
            onExpand={video ? () => setTheaterOpen(true) : undefined}
          >
            {video ? (
              <PhoneFitVideo key={video} src={video} controls preload="auto" />
            ) : (
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 px-4 text-center text-xs text-[var(--muted)]">
                <span className="text-2xl opacity-40">▶</span>
                <span>生成对口型后</span>
                <span>在此预览（目标 {targetAspect}，框固定 9:16）</span>
              </div>
            )}
          </PhonePreviewSlot>

          {lipsyncTakes.length > 0 && (
            <div className="mx-auto w-full max-w-[280px] rounded-xl border border-[var(--border)] bg-[var(--panel)] p-2">
              <div className="mb-1.5 flex items-center justify-between px-1">
                <span className="text-xs font-medium text-[var(--text)]">口播版本</span>
                <span className="text-[10px] text-[var(--muted)]">{lipsyncTakes.length} 条</span>
              </div>
              <ul className="max-h-52 space-y-1 overflow-auto">
                {lipsyncTakes.map((take) => {
                  const active = selectedLipsyncPath === take.path
                  return (
                    <li key={take.id || take.path} className="flex items-stretch gap-1">
                      <button
                        type="button"
                        onClick={() => void onLipsyncSelect(take.path)}
                        className={`min-w-0 flex-1 rounded-lg border px-2 py-1.5 text-left text-[11px] leading-snug ${
                          active
                            ? 'border-[var(--accent)] bg-[var(--select-bg)] text-[var(--accent)]'
                            : 'border-transparent text-[var(--text)] hover:bg-[var(--bg)]'
                        }`}
                      >
                        <span className="block truncate font-medium">{take.name}</span>
                        <span className="text-[10px] text-[var(--muted)]">
                          {take.source === 'current'
                            ? '正在预览 / 发布'
                            : take.source === 'legacy'
                              ? '会话遗留文件'
                              : '历史归档'}
                        </span>
                      </button>
                      <button
                        type="button"
                        title="删除此版本"
                        onClick={() => void onLipsyncDelete(take.id || '', take.name)}
                        className="shrink-0 rounded-lg px-2 text-[11px] text-[var(--muted)] hover:bg-red-500/10 hover:text-red-600"
                      >
                        删
                      </button>
                    </li>
                  )
                })}
              </ul>
              <p className="mt-1.5 px-1 text-[10px] text-[var(--muted)]">
                点选切换预览；「删」可移除该版本
              </p>
            </div>
          )}

          {video && (
            <div className="mx-auto flex w-full max-w-[280px] flex-col gap-1.5">
              <button
                type="button"
                className="w-full rounded-lg border border-[var(--border)] px-3 py-1.5 text-center text-xs hover:bg-[var(--panel)]"
                onClick={() => {
                  const desktop = (
                    window as unknown as {
                      agentDesktop?: { openPath?: (p: string) => Promise<{ ok: boolean; message?: string }> }
                    }
                  ).agentDesktop
                  const local = selectedLipsyncPath || session.lipsync_video || ''
                  if (desktop?.openPath && local) {
                    void desktop.openPath(local)
                    return
                  }
                  window.open(video, '_blank')
                }}
              >
                系统播放器打开
              </button>
              <a
                href={video}
                download
                className="block w-full rounded-lg border border-[var(--border)] px-3 py-1.5 text-center text-xs hover:bg-[var(--panel)]"
              >
                导出口播视频
              </a>
            </div>
          )}
        </PhonePreviewColumn>
      </div>

      <AvatarPickerModal
        open={pickerOpen}
        selectedId={avatar?.id || ''}
        backend={backend}
        onClose={() => setPickerOpen(false)}
        onSelect={onPickAvatar}
        onRegistered={onRegistered}
      />

      <AssetPickerModal
        open={assetPicker != null}
        onClose={() => setAssetPicker(null)}
        onPick={onLibraryAssetPick}
        mediaKind={
          assetPicker === 'ref_pose'
            ? 'video'
            : trackMode === 'real'
              ? 'video'
            : PORTRAIT_BACKENDS.has(backend)
                ? 'image'
                : 'all'
        }
        title="从素材中心选择"
        subtitle={
          assetPicker === 'ref_pose'
            ? '选择动作参考 / 驱动视频'
            : trackMode === 'real'
              ? '选择实拍视频（LatentSync）'
              : PORTRAIT_BACKENDS.has(backend)
                ? '选择肖像图片'
                : '选择素材'
        }
      />

      <InAppVideoTheater
        open={theaterOpen && !!video}
        src={video || ''}
        title="口播成片 · 应用内全屏"
        onClose={() => setTheaterOpen(false)}
      />

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

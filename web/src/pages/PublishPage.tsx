import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { api, mediaUrl, playableUrl } from '../api/client'
import { useJobQueue } from '../context/JobQueueContext'
import type { SessionSnapshot } from '../types'
import { CoverEditor, CoverPreviewCanvas, type CoverPreviewBridge } from '../components/CoverEditor'
import { HyperFrameThemePicker, type HyperAspectMeta, type HyperLayoutMeta, type HyperThemeMeta } from '../components/HyperFrameThemePicker'
import { StylePackFields, type StylePackOption } from '../components/StylePackFields'
import { AssetPickerModal, type PickerAsset } from '../components/AssetPickerModal'
import { LecturerCropModal, type CropBox } from '../components/LecturerCropModal'
import { PhonePreviewColumn, PhonePreviewSlot, type PreviewAspect } from '../components/PhonePreviewColumn'
import { PhoneFitVideo } from '../components/PhonePreviewFrame'
import { InAppVideoTheater } from '../components/InAppVideoTheater'
import { detectVideoAspectFromUrl, detectVideoDuration, pathsRoughlyEqual } from '../utils/mediaFileMeta'
import { sameSessionPath } from '../utils/sessionPath'
import { ActionBtn, Panel, TabBtn } from './ScriptPage'


type Props = { session: SessionSnapshot; onUpdate?: (s: SessionSnapshot) => void }

type SubCue = { index: number; start: number; end: number; text: string }

type ComposeMode = 'fusion' | 'cover'

type PipAssignment = {
  id: string
  cue_indices: number[]
  start: number
  end: number
  media_path: string
  media_type: 'image' | 'video'
  preview_url: string | null
  position: string
  scale: number
  display_duration_sec: number
  play_full_video: boolean
  /** Source video in-point (seconds). Default 0. */
  source_start_sec: number
  /** Probed source media duration (videos). */
  source_duration_sec?: number | null
  /** Normalized crop box for image/video. */
  crop?: CropBox | null
  auto_hyperframe?: boolean
  /** fusion = 透明叠原视频；cover = 主体内容覆盖 */
  compose_mode?: ComposeMode
  content_style?: string
  scene_layout?: string
}

const FUSION_LAYOUT_IDS = new Set(['glass_card', 'text_card', 'plain_text'])

function mapApiAssignmentToPip(
  a: {
    cue_indices: number[]
    start: number
    end: number
    media_path: string
    play_full_video?: boolean
    display_duration_sec?: number
    position?: string
    scale?: number
    compose_mode?: string
    content_style?: string
    scene_layout?: string
    auto_hyperframe?: boolean
  },
  id: string,
): PipAssignment {
  const isVideo = /\.(mp4|mov|webm|mkv)$/i.test(a.media_path)
  const layout = String(a.content_style || a.scene_layout || '')
  let compose: ComposeMode =
    a.compose_mode === 'fusion' || a.compose_mode === 'cover'
      ? a.compose_mode
      : FUSION_LAYOUT_IDS.has(layout)
        ? 'fusion'
        : 'cover'
  const isFusion = compose === 'fusion'
  let position = a.position || (isFusion ? 'fullscreen' : 'fullscreen')
  if (isFusion) position = 'fullscreen'
  return {
    id,
    cue_indices: a.cue_indices,
    start: a.start,
    end: a.end,
    media_path: a.media_path,
    media_type: (isVideo ? 'video' : 'image') as 'video' | 'image',
    preview_url: mediaUrl(a.media_path),
    position,
    scale: isFusion ? 1 : (a.scale ?? 1),
    play_full_video: isVideo ? (a.play_full_video ?? true) : false,
    display_duration_sec: isVideo
      ? Math.max(0.8, a.end - a.start)
      : (a.display_duration_sec ?? Math.max(0.8, a.end - a.start)),
    source_start_sec: 0,
    source_duration_sec: null,
    crop: null,
    auto_hyperframe: a.auto_hyperframe !== false,
    compose_mode: compose,
    content_style: layout || undefined,
    scene_layout: a.scene_layout || layout || undefined,
  }
}

const SUBTITLE_COLORS = [
  { value: '#FFFFFF', label: '白色' },
  { value: '#FFFF00', label: '黄色' },
  { value: '#C084FC', label: '紫色' },
  { value: '#67E8F9', label: '青色' },
  { value: '#FDE68A', label: '金色' },
]

function coverTitleFromScript(script: string): string {
  const text = script.trim()
  if (!text) return '未命名'
  const first = text.split(/[。！？\n]/)[0]?.trim() || text
  const compact = first.replace(/\s+/g, '')
  if (compact.length <= 18) return compact
  return `${compact.slice(0, 17)}…`
}

const PIP_POSITIONS = [
  { value: 'top_right', label: '右上' },
  { value: 'top_left', label: '左上' },
  { value: 'bottom_right', label: '右下' },
  { value: 'bottom_left', label: '左下' },
  { value: 'center', label: '居中' },
  { value: 'fullscreen', label: '全屏' },
]

/** 画中画 only — no corner presets; default center. 口播窗口仍用 PIP_POSITIONS。 */
const CONTENT_PIP_POSITIONS = [
  { value: 'center', label: '居中' },
  { value: 'fullscreen', label: '全屏' },
]

function normalizeContentPipPosition(pos: string | undefined | null): 'center' | 'fullscreen' {
  if (pos === 'fullscreen') return 'fullscreen'
  return 'center'
}

/** Mini schematic of canvas + PiP slot for live preview. */
function PipSlotPreview({
  position,
  scale,
  aspect = '9:16',
}: {
  position: string
  scale: number
  aspect?: PreviewAspect
}) {
  const landscape = aspect === '16:9'
  const box = Math.max(0.12, Math.min(0.5, scale))
  const style: CSSProperties = (() => {
    const w = `${box * 100}%`
    const h = `${box * 100}%` // 1:1 square lecturer / content preview
    const m = '6%'
    if (position === 'fullscreen') return { inset: '4%' }
    if (position === 'top_left') return { top: m, left: m, width: w, height: h }
    if (position === 'top_right') return { top: m, right: m, width: w, height: h }
    if (position === 'bottom_left') return { bottom: m, left: m, width: w, height: h }
    if (position === 'center') return { top: '50%', left: '50%', width: w, height: h, transform: 'translate(-50%, -50%)' }
    return { bottom: m, right: m, width: w, height: h }
  })()
  return (
    <div
      className={`relative mx-auto overflow-hidden rounded-lg border border-[var(--border)] bg-[#1a1f2a] ${
        landscape ? 'aspect-video w-36' : 'aspect-[9/16] w-20'
      }`}
    >
      <div className="absolute inset-0 bg-gradient-to-br from-[var(--accent)]/15 to-transparent" />
      <div
        className={`absolute rounded border-2 border-[var(--accent)] bg-[var(--accent)]/35 ${
          position === 'fullscreen' ? '' : ''
        }`}
        style={style}
      />
      <span className="absolute bottom-0.5 left-0 right-0 text-center text-[8px] text-[var(--muted)]">
        {PIP_POSITIONS.find((p) => p.value === position)?.label || position}
      </span>
    </div>
  )
}

function mergeRange(cues: SubCue[], indices: number[]): { start: number; end: number } | null {
  const picked = indices
    .map((i) => cues.find((c) => c.index === i))
    .filter(Boolean) as SubCue[]
  if (!picked.length) return null
  return { start: picked[0].start, end: picked[picked.length - 1].end }
}

function isVideoFile(file: File) {
  return file.type.startsWith('video/') || /\.(mp4|mov|webm|mkv)$/i.test(file.name)
}

type LecturerCropBox = CropBox

/** Horizontal card: poster + center play; click shows native controls. */
function PipMediaCard({
  url,
  mediaType,
  aspect,
  label,
}: {
  url: string
  mediaType: 'image' | 'video'
  aspect: PreviewAspect
  label: string
}) {
  const [playing, setPlaying] = useState(false)
  const landscape = aspect === '16:9'
  return (
    <div
      className={`relative shrink-0 overflow-hidden rounded-xl border border-[var(--border)] bg-black ${
        landscape ? 'aspect-video w-56' : 'aspect-[9/16] w-36'
      }`}
    >
      {mediaType === 'image' || !playing ? (
        <>
          {mediaType === 'video' ? (
            <video
              src={url}
              muted
              preload="metadata"
              playsInline
              className="absolute inset-0 h-full w-full object-contain bg-black"
            />
          ) : (
            <img src={url} alt="" className="absolute inset-0 h-full w-full object-cover" />
          )}
          {mediaType === 'video' && (
            <button
              type="button"
              onClick={() => setPlaying(true)}
              className="absolute inset-0 flex items-center justify-center bg-black/35 transition hover:bg-black/45"
              aria-label="播放"
            >
              <span className="flex h-11 w-11 items-center justify-center rounded-full bg-white/90 text-lg text-black shadow">
                ▶
              </span>
            </button>
          )}
        </>
      ) : (
        <video
          src={url}
          controls
          autoPlay
          playsInline
          className="absolute inset-0 h-full w-full object-contain bg-black"
        />
      )}
      <p className="pointer-events-none absolute bottom-0 left-0 right-0 truncate bg-black/55 px-1.5 py-0.5 text-[9px] text-white">
        {label}
      </p>
    </div>
  )
}

export function PublishPage({ session, onUpdate }: Props) {
  const jobQueue = useJobQueue()
  const [script, setScript] = useState(session.script || '')

  useEffect(() => {
    setScript(session.script || '')
  }, [session.path, session.script])

  const [log, setLog] = useState('')
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState<{ pct: number; msg: string } | null>(null)
  const publishAbortRef = useRef<AbortController | null>(null)
  const [styleModalOpen, setStyleModalOpen] = useState(false)
  const [fullFilmConfirmOpen, setFullFilmConfirmOpen] = useState(false)
  const [oneClickConfirmTarget, setOneClickConfirmTarget] = useState<number[] | 'all'>('all')
  const oneClickTargetRef = useRef<number[] | 'all'>('all')
  const styleModalModeRef = useRef<'oneclick' | 'pip_ai'>('oneclick')
  const [resultVideo, setResultVideo] = useState<string | null>(null)
  const [resultVideoPath, setResultVideoPath] = useState<string | null>(null)
  const coverTitle = useMemo(() => {
    if (session.publish_title?.trim()) return session.publish_title.trim()
    return coverTitleFromScript(script)
  }, [session.publish_title, script])
  const [coverPath, setCoverPath] = useState<string | null>(null)
  const [editTab, setEditTab] = useState<'subtitle' | 'cover' | 'post'>('subtitle')
  const [coverPreview, setCoverPreview] = useState<CoverPreviewBridge | null>(null)
  const [customCover, setCustomCover] = useState(() => {
    try {
      return sessionStorage.getItem(`jy_custom_cover:${session.path}`) === '1'
    } catch {
      return false
    }
  })

  useEffect(() => {
    try {
      sessionStorage.setItem(`jy_custom_cover:${session.path}`, customCover ? '1' : '0')
    } catch {
      /* ignore */
    }
  }, [customCover, session.path])
  const [postPlatforms, setPostPlatforms] = useState<string[]>(['douyin'])
  const [publishPlatformOptions, setPublishPlatformOptions] = useState<
    { id: string; name: string; login_url: string }[]
  >([])
  const [loginGuide, setLoginGuide] = useState<{
    platform: string
    platformName: string
    remaining: string[]
    videoPath?: string | null
  } | null>(null)
  const [loginBusy, setLoginBusy] = useState(false)
  const [postTitle, setPostTitle] = useState(session.publish_title || '')
  const [postDesc, setPostDesc] = useState(session.publish_description || '')
  const [postTopics, setPostTopics] = useState(
    (session.publish_topics || []).join(' ') || '',
  )
  const [autoPostAfter, setAutoPostAfter] = useState(false)
  const [postBusy, setPostBusy] = useState(false)
  const [cues, setCues] = useState<SubCue[]>([])
  const [timingNote, setTimingNote] = useState('')

  useEffect(() => {
    if (session.publish_title?.trim()) setPostTitle(session.publish_title.trim())
    else if (!postTitle.trim() && coverTitle) setPostTitle(coverTitle)
    if (session.publish_description?.trim()) setPostDesc(session.publish_description.trim())
    else if (!postDesc.trim() && script.trim()) setPostDesc(script.trim().slice(0, 300))
    if (session.publish_topics?.length) setPostTopics(session.publish_topics.join(' '))
  }, [session.path, session.publish_title, session.publish_description, session.publish_topics, coverTitle, script]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    api.browserPlatforms()
      .then((res) => {
        if (res.platforms?.length) setPublishPlatformOptions(res.platforms)
      })
      .catch(() => {})
  }, [])

  const togglePostPlatform = (id: string) => {
    setPostPlatforms((prev) => {
      if (prev.includes(id)) {
        const next = prev.filter((p) => p !== id)
        return next.length ? next : prev
      }
      return [...prev, id]
    })
  }

  const movePostPlatform = (id: string, dir: -1 | 1) => {
    setPostPlatforms((prev) => {
      const i = prev.indexOf(id)
      if (i < 0) return prev
      const j = i + dir
      if (j < 0 || j >= prev.length) return prev
      const next = [...prev]
      ;[next[i], next[j]] = [next[j], next[i]]
      return next
    })
  }

  const prepareCoverForPublish = async (): Promise<{ coverPath: string | null; title: string }> => {
    if (!customCover) {
      return { coverPath: null, title: postTitle.trim() || coverTitle }
    }
    let path = coverPath
    if (coverPreview?.saveCover) {
      path = (await coverPreview.saveCover()) || path
      if (path) setCoverPath(path)
    }
    const title = (coverPreview?.title || postTitle || coverTitle).trim()
    if (title) setPostTitle(title)
    return { coverPath: path, title }
  }

  const runAutoPost = async (videoPath?: string | null, platformsOverride?: string[]) => {
    const platforms = platformsOverride?.length ? platformsOverride : postPlatforms
    if (!platforms.length) {
      setLog('请至少选择一个发布平台')
      return
    }
    setPostBusy(true)
    try {
      const topics = postTopics
        .split(/[,，#\s]+/)
        .map((t) => t.trim())
        .filter(Boolean)
        .slice(0, 5)
      if (
        postTopics
          .split(/[,，#\s]+/)
          .map((t) => t.trim())
          .filter(Boolean).length > 5
      ) {
        setPostTopics(topics.join(' '))
      }
      const res = await api.publishAutoPost({
        session_path: session.path,
        video_path: videoPath || resultVideoPath || undefined,
        title: postTitle || coverTitle,
        description: postDesc || script.slice(0, 300),
        topics,
        platforms,
      })
      const data = (res.data || {}) as {
        need_login?: boolean
        platform?: string
        platform_name?: string
        remaining?: string[]
        message?: string
      }
      if (data.need_login && data.platform) {
        setLoginGuide({
          platform: data.platform,
          platformName: data.platform_name || data.platform,
          remaining: data.remaining?.length ? data.remaining : platforms,
          videoPath: videoPath || resultVideoPath,
        })
        setLog(data.message || res.message || `未登录${data.platform_name || data.platform}，请先登录`)
        return
      }
      setLoginGuide(null)
      setLog(res.message || res.log || data.message || '已按序打开发布页，请确认发布')
    } catch (e) {
      setLog(e instanceof Error ? e.message : String(e))
    } finally {
      setPostBusy(false)
    }
  }

  const waitForPlatformLogin = async (platform: string, timeoutMs = 180000) => {
    const start = Date.now()
    while (Date.now() - start < timeoutMs) {
      try {
        const st = await api.browserStatus(platform)
        if (st.logged_in) return true
      } catch {
        /* ignore poll errors */
      }
      await new Promise((r) => window.setTimeout(r, 2000))
    }
    return false
  }

  const handleLoginAndContinue = async () => {
    if (!loginGuide) return
    setLoginBusy(true)
    try {
      setLog(`正在打开${loginGuide.platformName}登录页，请在浏览器中完成登录…`)
      await api.browserLogin(false, loginGuide.platform)
      setLog(`等待${loginGuide.platformName}登录完成…`)
      const ok = await waitForPlatformLogin(loginGuide.platform)
      if (!ok) {
        setLog(`${loginGuide.platformName}登录超时，请登录后点击「已登录，继续发布」`)
        return
      }
      setLog(`${loginGuide.platformName}已登录，继续按序发布…`)
      const remaining = loginGuide.remaining
      const videoPath = loginGuide.videoPath
      setLoginGuide(null)
      await runAutoPost(videoPath, remaining)
    } catch (e) {
      setLog(e instanceof Error ? e.message : String(e))
    } finally {
      setLoginBusy(false)
    }
  }
  const [selectedCueIndices, setSelectedCueIndices] = useState<number[]>([])
  const [pipAssignments, setPipAssignments] = useState<PipAssignment[]>([])
  const [editingPipId, setEditingPipId] = useState<string | null>(null)
  const [subtitleFontSize, setSubtitleFontSize] = useState(16)
  const [subtitleColor, setSubtitleColor] = useState('#FFFFFF')
  const [subtitleOutline, setSubtitleOutline] = useState(1)
  const [subtitleShadow, setSubtitleShadow] = useState(0)
  const [subtitlePosition, setSubtitlePosition] = useState<'bottom' | 'top'>('bottom')
  const [enableSubtitles, setEnableSubtitles] = useState(false)
  const [enablePipTimeline, setEnablePipTimeline] = useState(false)
  const [cuesLoading, setCuesLoading] = useState(false)
  const [extractLoading, setExtractLoading] = useState(false)
  const [extractFeedback, setExtractFeedback] = useState<{
    kind: 'ok' | 'error' | 'info'
    text: string
  } | null>(null)
  const [previewCueIndex, setPreviewCueIndex] = useState<number | null>(null)
  const [subtitlePreviewUrl, setSubtitlePreviewUrl] = useState<string | null>(null)
  const [subtitlePreviewLoading, setSubtitlePreviewLoading] = useState(false)
  const [subtitlePreviewNote, setSubtitlePreviewNote] = useState('')
  const [subtitlePreviewStale, setSubtitlePreviewStale] = useState(false)
  const [previewLightboxOpen, setPreviewLightboxOpen] = useState(false)
  const [videoTheaterSrc, setVideoTheaterSrc] = useState<string | null>(null)
  const [videoTheaterTitle, setVideoTheaterTitle] = useState('应用内全屏预览')
  const [rightPreviewTab, setRightPreviewTab] = useState<'mix' | 'lipsync'>('mix')
  const [cuesEdited, setCuesEdited] = useState(false)
  const [enableBgm, setEnableBgm] = useState(false)
  const [bgmId, setBgmId] = useState('hook_drop')
  const [bgmVolume, setBgmVolume] = useState(0.22)
  const [bgmStart, setBgmStart] = useState(0)
  const [bgmTracks, setBgmTracks] = useState<
    Array<{
      id: string
      name: string
      mood: string
      category?: string
      ready: boolean
      source?: string
      clip_start?: number
      duration_sec?: number
      preview_url: string | null
      local_path?: string | null
      user?: boolean
      from_asset?: boolean
    }>
  >([])
  const [bgmUploadBusy, setBgmUploadBusy] = useState(false)
  const bgmFileRef = useRef<HTMLInputElement>(null)
  const [pipPosition, setPipPosition] = useState('bottom_right')
  const [pipScale, setPipScale] = useState(0.28)
  const [pipMargin, setPipMargin] = useState(24)
  const [lecturerCrop, setLecturerCrop] = useState<LecturerCropBox | null>(null)
  const [lecturerCropPreview, setLecturerCropPreview] = useState<string | null>(null)
  const [lecturerCropBusy, setLecturerCropBusy] = useState(false)
  const [lecturerCropModalOpen, setLecturerCropModalOpen] = useState(false)
  const [lecturerCropFrameUrl, setLecturerCropFrameUrl] = useState<string | null>(null)
  const [pipCropTargetId, setPipCropTargetId] = useState<string | null>(null)
  const [pipCropFrameUrl, setPipCropFrameUrl] = useState<string | null>(null)
  const [pipCropBusy, setPipCropBusy] = useState(false)
  const [contentPipPosition, setContentPipPosition] = useState('center')
  const [contentPipScale, setContentPipScale] = useState(0.32)
  const [layoutMode, setLayoutMode] = useState<'short' | 'education'>('short')
  const [educationBgFile, setEducationBgFile] = useState<File | null>(null)
  const [hyperframesConsent, setHyperframesConsent] = useState(false)
  const [hyperframesTheme, setHyperframesTheme] = useState('tokyo_night')
  const [hyperframesLayout, setHyperframesLayout] = useState('kinetic')
  const [hyperframesAspect, setHyperframesAspect] = useState('portrait_9_16')
  const [publishAspect, setPublishAspect] = useState('portrait_9_16')
  const [hfThemes, setHfThemes] = useState<HyperThemeMeta[]>([])
  const [hfLayouts, setHfLayouts] = useState<HyperLayoutMeta[]>([])
  const [hfAspects, setHfAspects] = useState<HyperAspectMeta[]>([])
  const [hfSmartLayout, setHfSmartLayout] = useState(true)
  const [hfSmartTheme, setHfSmartTheme] = useState(true)
  const [hfSmartKeywords, setHfSmartKeywords] = useState(true)
  const [hfSmartBg, setHfSmartBg] = useState(true)
  const [hfFonts, setHfFonts] = useState<StylePackOption[]>([])
  const [hfBgModes, setHfBgModes] = useState<StylePackOption[]>([])
  const [hfRemThemes, setHfRemThemes] = useState<StylePackOption[]>([])
  const [hfFontId, setHfFontId] = useState('noto_sc')
  const [hfFontScale, setHfFontScale] = useState(1)
  const [hfBgMode, setHfBgMode] = useState('generative')
  const [hfBgPrompt, setHfBgPrompt] = useState('')
  const [hfRemotionTheme, setHfRemotionTheme] = useState('off')
  const [composeMode, setComposeMode] = useState<ComposeMode>('fusion')
  const [hfCardPosition, setHfCardPosition] = useState('auto')
  const [hfCardScale, setHfCardScale] = useState(0.58)
  const [hfMoreOpen, setHfMoreOpen] = useState(false)
  const [hfSuggestReasons, setHfSuggestReasons] = useState<string[]>([])
  const [hfSuggestBusy, setHfSuggestBusy] = useState(false)
  const [pendingDisplaySec, setPendingDisplaySec] = useState(3)
  const [pendingPlayFull, setPendingPlayFull] = useState(false)
  const pipInputRef = useRef<HTMLInputElement>(null)
  const educationBgInputRef = useRef<HTMLInputElement>(null)
  const [assetPickerOpen, setAssetPickerOpen] = useState(false)
  const bgmAudioRef = useRef<HTMLAudioElement>(null)
  const lastClickedRef = useRef<number | null>(null)

  const activeBgm = bgmTracks.find((t) => t.id === bgmId)
  const bgmMaxStart = Math.max(0, (activeBgm?.duration_sec ?? 75) - 8)

  const selectionRange = mergeRange(cues, selectedCueIndices)
  const previewCue =
    cues.find((c) => c.index === previewCueIndex) || cues[0] || null

  const cropProbeTime = () => (previewCue ? (previewCue.start + previewCue.end) / 2 : 0.8)

  const openLecturerCropModal = async () => {
    if (!session.path) return
    setLecturerCropModalOpen(true)
    setLecturerCropBusy(true)
    try {
      const res = await api.publishLecturerCropFrame(session.path, cropProbeTime())
      setLecturerCropFrameUrl(mediaUrl(res.frame_path, res.mtime))
    } catch (e) {
      setLog(e instanceof Error ? e.message : String(e))
      setLecturerCropModalOpen(false)
    } finally {
      setLecturerCropBusy(false)
    }
  }

  const autoDetectLecturerCropInModal = async (): Promise<LecturerCropBox | null> => {
    if (!session.path) return null
    setLecturerCropBusy(true)
    try {
      const res = await api.publishLecturerCropAuto(session.path, cropProbeTime())
      // Keep same frame URL — reloading used to wipe the crop overlay via modal effect
      return res.crop
    } catch (e) {
      setLog(e instanceof Error ? e.message : String(e))
      throw e instanceof Error ? e : new Error(String(e))
    } finally {
      setLecturerCropBusy(false)
    }
  }

  useEffect(() => {
    if (composeMode === 'cover' && FUSION_LAYOUT_IDS.has(hyperframesLayout)) {
      setHyperframesLayout('kinetic')
    }
  }, [composeMode, hyperframesLayout])

  useEffect(() => {
    if (layoutMode === 'education' && pipPosition === 'top_right') {
      setPipPosition('bottom_right')
    }
  }, [layoutMode, pipPosition])

  // Landscape mouth window 20% of canvas; portrait stays 28%
  useEffect(() => {
    if (layoutMode !== 'education') return
    setPipScale(publishAspect === 'landscape_16_9' ? 0.2 : 0.28)
  }, [publishAspect, layoutMode])

  useEffect(() => {
    setHyperframesAspect(publishAspect)
  }, [publishAspect])

  useEffect(() => {
    const loadBgm = () => {
      void api.bgmLibrary().then(setBgmTracks).catch(() => setBgmTracks([]))
    }
    loadBgm()
    const onFocus = () => loadBgm()
    window.addEventListener('focus', onFocus)
    return () => window.removeEventListener('focus', onFocus)
  }, [])

  useEffect(() => {
    void api.hyperframeThemes().then((r) => {
      setHfThemes(r.themes)
      setHfLayouts(r.layouts || [])
      setHfAspects(r.aspects || [])
      setHfFonts(r.fonts || [])
      setHfBgModes(r.bg_modes || [])
      setHfRemThemes(
        (r.remotion_themes || []).filter(
          (t) => t.id !== 'side' && t.id !== 'side_kinetic',
        ),
      )
    }).catch(() => {})
    void api
      .getHyperframeActiveStyle()
      .then((s) => {
        setHyperframesTheme(s.theme)
        setHyperframesLayout(s.layout)
        setHyperframesAspect(s.aspect)
        setPublishAspect(s.aspect)
        if (s.font_id) setHfFontId(s.font_id)
        if (typeof s.font_scale === 'number') setHfFontScale(s.font_scale)
        if (s.bg_mode) setHfBgMode(s.bg_mode)
        if (s.bg_prompt != null) setHfBgPrompt(s.bg_prompt)
        if (s.remotion_theme) {
          // Remotion is burn-in only; ignore legacy style-pack remotion for scene cards
        }
      })
      .catch(() => {})
    void api
      .publishPipAssignments(session.path)
      .then((r) => {
        const list = r.assignments || []
        if (!list.length) {
          setPipAssignments([])
          return
        }
        const stamp = Date.now()
        setPipAssignments(
          list.map((a, i) =>
            mapApiAssignmentToPip(
              a as Parameters<typeof mapApiAssignmentToPip>[0],
              `hf_loaded_${a.cue_indices.join('_')}_${stamp}_${i}`,
            ),
          ),
        )
        setEnablePipTimeline(true)
        if (r.work_dir) {
          setLog(`已恢复 ${list.length} 个历史智能场景（文件仍在：${r.work_dir}）`)
        }
      })
      .catch(() => {})
  }, [session.path])

  useEffect(() => {
    if (jobQueue.assignmentsTick <= 0 || !session.path) return
    void api
      .publishPipAssignments(session.path)
      .then((r) => {
        const list = r.assignments || []
        if (!list.length) {
          setPipAssignments([])
          setEditingPipId(null)
          setLog('已清除废弃智能场景（源文件已删除）')
          return
        }
        const stamp = Date.now()
        setPipAssignments(
          list.map((a, i) =>
            mapApiAssignmentToPip(
              a as Parameters<typeof mapApiAssignmentToPip>[0],
              `hf_purge_${a.cue_indices.join('_')}_${stamp}_${i}`,
            ),
          ),
        )
        setLog(`智能场景已同步 · 仍保留 ${list.length} 段`)
      })
      .catch(() => {})
  }, [jobQueue.assignmentsTick, session.path])

  useEffect(() => {
    const onPipChanged = (ev: Event) => {
      const detail = (ev as CustomEvent<{ sessionPath?: string }>).detail
      if (detail?.sessionPath && detail.sessionPath !== session.path) return
      if (!session.path) return
      void api
        .publishPipAssignments(session.path)
        .then((r) => {
          const list = r.assignments || []
          if (!list.length) {
            setPipAssignments([])
            setEditingPipId(null)
            return
          }
          const stamp = Date.now()
          setPipAssignments(
            list.map((a, i) =>
              mapApiAssignmentToPip(
                a as Parameters<typeof mapApiAssignmentToPip>[0],
                `hf_evt_${a.cue_indices.join('_')}_${stamp}_${i}`,
              ),
            ),
          )
        })
        .catch(() => {})
    }
    window.addEventListener('agent:pip-assignments-changed', onPipChanged)
    return () => window.removeEventListener('agent:pip-assignments-changed', onPipChanged)
  }, [session.path])

  useEffect(() => {
    const onRefresh = (ev: Event) => {
      const detail = (ev as CustomEvent<{ sessionPath?: string }>).detail
      if (detail?.sessionPath && detail.sessionPath !== session.path) return
      if (!session.path || !onUpdate) return
      void api.sessionSnapshot(session.path).then(onUpdate).catch(() => {})
    }
    window.addEventListener('agent:session-refresh', onRefresh)
    return () => window.removeEventListener('agent:session-refresh', onRefresh)
  }, [session.path, onUpdate])

  useEffect(() => {
    const job = jobQueue.lastFinished
    if (!job || jobQueue.completionTick <= 0) return
    if (job.status === 'failed') {
      setLog(job.error || job.message || '任务失败')
      return
    }
    if (job.status === 'cancelled') {
      setLog('任务已取消')
      return
    }
    if (job.status !== 'done') return

    if (job.type === 'hyperframe_fill_cues' || job.type === 'hyperframe_restyle') {
      void api
        .publishPipAssignments(session.path)
        .then((r) => {
          const list = r.assignments || []
          if (!list.length) {
            setPipAssignments([])
            return
          }
          const stamp = Date.now()
          const mapped = list.map((a, i) =>
            mapApiAssignmentToPip(
              a as Parameters<typeof mapApiAssignmentToPip>[0],
              `hf_job_${a.cue_indices.join('_')}_${stamp}_${i}`,
            ),
          )
          setPipAssignments(mapped)
          setEnablePipTimeline(true)
          setHyperframesConsent(true)
          const firstIdx = mapped[0]?.cue_indices?.[0]
          if (typeof firstIdx === 'number' && firstIdx > 0) {
            setPreviewCueIndex(firstIdx)
            setSelectedCueIndices((prev) =>
              prev.length ? prev : [...new Set(mapped.flatMap((p) => p.cue_indices))],
            )
          }
          const n = list.length
          const modeNote =
            mapped.some((p) => p.compose_mode === 'fusion') ? '融合' : '覆盖'
          setLog(
            job.type === 'hyperframe_restyle'
              ? `换肤完成 · ${n} 个场景已更新（见任务中心）`
              : `智能场景完成 · ${n} 段已写入时间轴（${modeNote}）`,
          )
        })
        .catch(() => {})
      const pub = job.result?.publish as { video_path?: string; log?: string } | undefined
      if (pub?.video_path) {
        setResultVideoPath(pub.video_path)
        setResultVideo(mediaUrl(pub.video_path))
        if (pub.log) setLog(pub.log)
      }
    }
    if (job.type === 'publish_run') {
      const vp = job.result?.video_path as string | undefined
      if (vp) {
        setResultVideoPath(vp)
        setResultVideo(mediaUrl(vp))
      }
      const plog = job.result?.log as string | undefined
      setLog(plog || '成片完成（见任务中心）')
      if (autoPostAfter && (vp || resultVideoPath)) {
        void runAutoPost(vp || resultVideoPath)
      }
    }
    if (job.type === 'subtitle_asr') {
      const payload = job.payload as { session_path?: string }
      const jobPath = payload.session_path || job.session_path
      if (!sameSessionPath(jobPath, session.path)) return
      const cues = (job.result?.cues || []) as SubCue[]
      const n = cues.length
      if (!n) {
        const msg = '提取完成但没有有效字幕条，请检查口播音频或本地 ASR 是否可用'
        setExtractFeedback({ kind: 'error', text: msg })
        setLog(msg)
        return
      }
      setCues(cues)
      setTimingNote(String(job.result?.timing_note || '一键提取 · 以音频为准'))
      setCuesEdited(true)
      setEnableSubtitles(true)
      setEnablePipTimeline(true)
      setSubtitlePreviewStale(true)
      const scriptText = String(job.result?.script || '')
      if (scriptText) {
        setScript(scriptText)
        if (onUpdate) {
          void api.sessionSnapshot(session.path).then(onUpdate).catch(() => {})
        }
      }
      setPreviewCueIndex(cues[0].index)
      setSelectedCueIndices([])
      const okMsg =
        `提取成功：${n} 条字幕` +
        (job.result?.script_updated ? ' · 会话文案已同步为识别结果' : '') +
        (job.result?.timing_note ? ` · ${String(job.result.timing_note)}` : '')
      setExtractFeedback({ kind: 'ok', text: okMsg })
      setLog(okMsg)
    }
  }, [jobQueue.completionTick, jobQueue.lastFinished, session.path])

  useEffect(() => {
    setBgmStart(0)
  }, [bgmId])

  // Legacy「侧向动效」已移除 → 口播混剪改用底部条融合
  useEffect(() => {
    if (hfRemotionTheme === 'side' || hfRemotionTheme === 'side_kinetic') {
      setHfRemotionTheme('bar')
    }
  }, [hfRemotionTheme])

  const loadCues = useCallback(async () => {
    if (!script.trim() || !session.path) return
    if (cuesEdited) return
    setCuesLoading(true)
    try {
      const res = await api.publishCues({
        session_path: session.path,
        script,
        subtitle_font_size: subtitleFontSize,
        output_aspect: publishAspect,
      })
      setCues(res.cues)
      setTimingNote(res.timing_note)
      setCuesEdited(false)
      if (res.cues.length > 0) {
        setPreviewCueIndex((prev) => {
          if (prev != null && res.cues.some((c) => c.index === prev)) return prev
          return res.cues[0].index
        })
      }
    } catch (e) {
      setLog(e instanceof Error ? e.message : String(e))
    } finally {
      setCuesLoading(false)
    }
  }, [script, session.path, subtitleFontSize, publishAspect, cuesEdited])

  const extractSubtitlesFromAudio = async () => {
    if (!session.path) return
    if (
      !window.confirm(
        '将从口播成片（或配音）重新识别字幕。文案与时间轴以识别结果为准，会覆盖当前字幕条目；是否继续？',
      )
    ) {
      return
    }
    setExtractLoading(true)
    setExtractFeedback({ kind: 'info', text: '已提交本地 ASR 到任务中心…' })
    setLog('字幕 ASR 已加入任务中心…')
    try {
      const outcome = await jobQueue.enqueue({
        type: 'subtitle_asr',
        title: '字幕 ASR 提取',
        force: true,
        payload: {
          session_path: session.path,
          use_video_audio: true,
          update_script: true,
          subtitle_font_size: subtitleFontSize,
          output_aspect: publishAspect,
        },
      })
      if (outcome.ok) {
        setExtractFeedback({
          kind: 'info',
          text: '已加入任务中心，本地引擎识别完成后自动回填字幕。',
        })
        setLog('字幕 ASR 已加入任务中心（见任务中心进度）')
        jobQueue.setCenterOpen(true)
      } else {
        const msg = outcome.message || '当前已有相同字幕提取任务'
        setExtractFeedback({ kind: 'error', text: msg })
        setLog(msg)
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setExtractFeedback({ kind: 'error', text: `提交失败：${msg}` })
      setLog(`提取字幕失败：${msg}`)
    } finally {
      setExtractLoading(false)
    }
  }

  const restoreScriptAlignedCues = async () => {
    if (!script.trim() || !session.path) return
    setCuesLoading(true)
    setExtractFeedback({ kind: 'info', text: '正在按会话文案重新对齐时间轴…' })
    try {
      const res = await api.publishCues({
        session_path: session.path,
        script,
        subtitle_font_size: subtitleFontSize,
        output_aspect: publishAspect,
      })
      setCues(res.cues)
      setTimingNote(res.timing_note)
      setCuesEdited(false)
      if (res.cues.length > 0) {
        setPreviewCueIndex(res.cues[0].index)
      }
      const msg = `已恢复文案对齐 · ${res.cues.length} 条 · ${res.timing_note}`
      setExtractFeedback({ kind: 'ok', text: msg })
      setLog(msg)
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setExtractFeedback({ kind: 'error', text: `恢复失败：${msg}` })
      setLog(msg)
    } finally {
      setCuesLoading(false)
    }
  }

  const updateCueField = (
    index: number,
    patch: Partial<Pick<SubCue, 'text' | 'start' | 'end'>>,
  ) => {
    setCues((prev) =>
      prev.map((c) => {
        if (c.index !== index) return c
        const next = { ...c, ...patch }
        if (typeof next.start === 'number' && typeof next.end === 'number' && next.end < next.start) {
          next.end = next.start
        }
        return next
      }),
    )
    setCuesEdited(true)
    setSubtitlePreviewStale(true)
  }

  useEffect(() => {
    const t = window.setTimeout(() => void loadCues(), 400)
    return () => window.clearTimeout(t)
  }, [loadCues])

  // Large subtitle font → shorter ASR-mapped cues (skip when user edited timeline manually)
  useEffect(() => {
    if (cuesEdited || !script.trim() || !session.path) return
    const t = window.setTimeout(() => void loadCues(), 700)
    return () => window.clearTimeout(t)
  }, [subtitleFontSize, publishAspect, cuesEdited, script, session.path, loadCues])

  const applyDefaultMixDefaults = () => {
    setLayoutMode('short')
    setEnableSubtitles(true)
    setHfRemotionTheme((prev) =>
      prev === 'off' || prev === 'side' || prev === 'side_kinetic' ? 'bar' : prev,
    )
    setPublishAspect('portrait_9_16')
    setHyperframesAspect('portrait_9_16')
    setComposeMode('fusion')
    setEnablePipTimeline(false)
    setEnableBgm(false)
    setHyperframesConsent(false)
    setPipPosition('bottom_right')
    setPipScale(0.28)
    setPipMargin(24)
    setContentPipPosition('center')
    setContentPipScale(0.32)
    setHfCardPosition('auto')
    setHfCardScale(0.58)
    setSelectedCueIndices([])
    setPipAssignments([])
    setEditingPipId(null)
    setPreviewCueIndex(null)
    setSubtitlePreviewUrl(null)
    setSubtitlePreviewNote('')
    setSubtitlePreviewStale(false)
    setSubtitlePreviewLoading(false)
    setPreviewLightboxOpen(false)
    setCuesEdited(false)
    setEducationBgFile(null)
    setLecturerCrop(null)
    setLecturerCropPreview(null)
    setLecturerCropModalOpen(false)
    setLecturerCropFrameUrl(null)
    setPipCropTargetId(null)
    setPipCropFrameUrl(null)
    setPipCropBusy(false)
    setResultVideo(null)
    setResultVideoPath(null)
    setProgress(null)
    setStyleModalOpen(false)
    setFullFilmConfirmOpen(false)
    setOneClickConfirmTarget('all')
    oneClickTargetRef.current = 'all'
    setHfSuggestReasons([])
    setPendingDisplaySec(3)
    setPendingPlayFull(false)
    setEditTab('subtitle')
  }

  const resetMixWorkspace = async () => {
    if (!session.path) return
    if (
      !window.confirm(
        '将清空画中画时间轴、智能场景与当前混剪选项，字幕将按文案重新对齐。封面与发布设置会保留。确定重新混剪？',
      )
    ) {
      return
    }
    try {
      const res = await api.resetPublishMix(session.path, true)
      applyDefaultMixDefaults()
      window.dispatchEvent(
        new CustomEvent('agent:pip-assignments-changed', { detail: { sessionPath: session.path } }),
      )
      await loadCues()
      const nFiles = res.removed_files ?? 0
      const nDirs = res.removed_dirs ?? 0
      setLog(
        res.message ||
          `已重置混剪工作区（清理 ${nFiles} 个文件、${nDirs} 个目录），可从头配置后再次一键成片`,
      )
    } catch (e) {
      setLog(e instanceof Error ? e.message : String(e))
    }
  }

  const previewPip = useMemo(
    () =>
      previewCue
        ? pipAssignments.find((p) => p.cue_indices.includes(previewCue.index)) ?? null
        : null,
    [pipAssignments, previewCue],
  )

  const previewAspect: PreviewAspect =
    publishAspect === 'landscape_16_9' ? '16:9' : '9:16'

  const refreshSubtitlePreview = useCallback(async () => {
    if (!session.path) return
    const text = enableSubtitles
      ? previewCue?.text?.trim() || script.trim().slice(0, 24) || '字幕预览'
      : ''
    const timeSec = previewCue ? (previewCue.start + previewCue.end) / 2 : 0.5
    setSubtitlePreviewLoading(true)
    try {
      const fd = new FormData()
      fd.append('session_path', session.path)
      fd.append('text', text || ' ')
      fd.append('time_sec', String(timeSec))
      if (previewCue) {
        fd.append('cue_start', String(previewCue.start))
        fd.append('cue_end', String(previewCue.end))
      }
      fd.append('subtitle_font_size', String(subtitleFontSize))
      fd.append('subtitle_color', subtitleColor)
      fd.append('subtitle_outline', String(enableSubtitles ? subtitleOutline : 0))
      fd.append('subtitle_shadow', String(enableSubtitles ? subtitleShadow : 0))
      fd.append('subtitle_position', subtitlePosition)
      fd.append('subtitle_style', 'bottom_clean')
      fd.append('layout_mode', layoutMode)
      fd.append('output_aspect', publishAspect)
      fd.append('pip_position', pipPosition)
      fd.append('pip_scale', String(pipScale))
      fd.append('pip_margin', String(pipMargin))
      if (lecturerCrop) {
        fd.append('lecturer_crop_json', JSON.stringify(lecturerCrop))
      }
      if (!enableSubtitles) fd.append('hide_subtitles', 'true')
      if (previewPip?.media_path) {
        fd.append('pip_bg_media', previewPip.media_path)
        const compose =
          previewPip.compose_mode === 'fusion' || previewPip.compose_mode === 'cover'
            ? previewPip.compose_mode
            : FUSION_LAYOUT_IDS.has(
                String(previewPip.content_style || previewPip.scene_layout || ''),
              )
              ? 'fusion'
              : 'cover'
        const isFusion = compose === 'fusion'
        let contentPos = 'center'
        if (isFusion) {
          // Fusion: transparent text card keyed over lipsync (not cover)
          contentPos = 'fullscreen'
          fd.append('content_key_black', 'true')
        } else if (previewPip.auto_hyperframe) {
          // Cover: opaque fullscreen scene; lecturer PiP stacks on top in education mode
          contentPos = 'fullscreen'
        } else {
          contentPos = normalizeContentPipPosition(previewPip.position)
        }
        fd.append('content_pip_position', contentPos)
        fd.append(
          'content_pip_scale',
          String(contentPos === 'fullscreen' ? 1 : previewPip.scale ?? contentPipScale),
        )
      }
      if (hyperframesConsent) {
        fd.append('hyperframes_consent', 'true')
        fd.append('hyperframes_theme', hyperframesTheme)
        const previewCompose: ComposeMode =
          previewPip?.compose_mode === 'fusion' || previewPip?.compose_mode === 'cover'
            ? previewPip.compose_mode
            : composeMode
        const hfLayout =
          previewCompose === 'cover' && FUSION_LAYOUT_IDS.has(hyperframesLayout)
            ? 'kinetic'
            : hyperframesLayout
        fd.append('hyperframes_layout', hfLayout)
        fd.append('hyperframes_aspect', publishAspect)
      }
      if (educationBgFile) fd.append('education_bg', educationBgFile)
      const remTheme =
        enableSubtitles && hfRemotionTheme && hfRemotionTheme !== 'off' ? hfRemotionTheme : 'off'
      if (remTheme !== 'off') fd.append('remotion_theme', remTheme)
      fd.append('smart_keywords', hfSmartKeywords ? 'true' : 'false')
      const res = await api.publishSubtitlePreview(fd)
      setSubtitlePreviewUrl(mediaUrl(res.preview_path, res.mtime))
      setSubtitlePreviewStale(false)
      const aspectNote = res.aspect_label ? `${res.aspect_label} · ` : ''
      const remLabel =
        remTheme !== 'off'
          ? remTheme === 'auto'
            ? `Remotion 智能 → ${
                hfRemThemes.find((t) => t.id === res.remotion_theme_resolved)?.label ||
                res.remotion_theme_resolved ||
                '自动'
              }`
            : `Remotion · ${
                hfRemThemes.find((t) => t.id === remTheme)?.label || remTheme
              }`
          : ''
      if (layoutMode === 'education') {
        const bgNote = previewPip
          ? previewPip.auto_hyperframe
            ? previewPip.compose_mode === 'fusion'
              ? 'HyperFrames 融合透明层'
              : 'HyperFrames 全屏场景 · 口播角窗置顶'
            : previewPip.position === 'fullscreen'
              ? '教学素材全屏'
              : `画中画${PIP_POSITIONS.find((p) => p.value === previewPip.position)?.label || ''}·${Math.round((previewPip.scale ?? 0.32) * 100)}%`
          : educationBgFile
            ? '固定底图'
            : hyperframesConsent
              ? 'HyperFrames 场景'
              : '深色讲解底'
        const subNote = enableSubtitles
          ? remLabel
            ? ` · ${remLabel}`
            : ` · 字幕${subtitlePosition === 'top' ? '顶部' : '底部'}`
          : ' · 无字幕'
        setSubtitlePreviewNote(
          previewPip?.auto_hyperframe
            ? `${aspectNote}${bgNote}${subNote}`
            : res.used_placeholder
              ? `${aspectNote}无口播视频 · ${bgNote} + 口播${PIP_POSITIONS.find((p) => p.value === pipPosition)?.label || '右下'}${subNote}`
              : `${aspectNote}${bgNote} · 口播${PIP_POSITIONS.find((p) => p.value === pipPosition)?.label || '右下'}${subNote}`,
        )
      } else {
        setSubtitlePreviewNote(
          res.used_placeholder
            ? '无口播视频，使用默认竖屏背景预览'
            : enableSubtitles
              ? `竖屏${previewPip ? ` · 画中画${PIP_POSITIONS.find((p) => p.value === previewPip.position)?.label || ''}` : '全屏'} · 截取 ${timeSec.toFixed(1)}s · ${
                  remLabel || `字幕${subtitlePosition === 'top' ? '顶部' : '底部'}`
                }`
              : `竖屏${previewPip ? ` · 画中画${PIP_POSITIONS.find((p) => p.value === previewPip.position)?.label || ''}` : '全屏'} · 截取 ${timeSec.toFixed(1)}s · 无字幕`,
        )
      }
    } catch (e) {
      setSubtitlePreviewNote(e instanceof Error ? e.message : String(e))
    } finally {
      setSubtitlePreviewLoading(false)
    }
  }, [
    session.path,
    previewCue,
    script,
    enableSubtitles,
    subtitleFontSize,
    subtitleColor,
    subtitleOutline,
    subtitleShadow,
    subtitlePosition,
    layoutMode,
    publishAspect,
    pipPosition,
    pipScale,
    pipMargin,
    lecturerCrop,
    previewPip,
    contentPipScale,
    hyperframesConsent,
    hyperframesTheme,
    hyperframesLayout,
    hyperframesAspect,
    educationBgFile,
    hfRemotionTheme,
    hfRemThemes,
    hfSmartKeywords,
  ])

  useEffect(() => {
    if (editTab !== 'subtitle' || rightPreviewTab !== 'mix') return
    if (!enableSubtitles) {
      setSubtitlePreviewUrl(null)
    }
    setSubtitlePreviewStale(true)
  }, [
    editTab,
    rightPreviewTab,
    enableSubtitles,
    session.path,
    previewCue,
    script,
    subtitleFontSize,
    subtitleColor,
    subtitleOutline,
    subtitleShadow,
    subtitlePosition,
    layoutMode,
    publishAspect,
    pipPosition,
    pipScale,
    pipMargin,
    lecturerCrop,
    previewPip,
    contentPipScale,
    hyperframesConsent,
    hyperframesTheme,
    hyperframesLayout,
    hyperframesAspect,
    educationBgFile,
    hfRemotionTheme,
    hfSmartKeywords,
  ])

  useEffect(() => {
    if (selectionRange) {
      const span = Math.max(0.5, selectionRange.end - selectionRange.start)
      setPendingDisplaySec(Math.round(span * 10) / 10)
    }
  }, [selectionRange?.start, selectionRange?.end])

  const toggleCueSelection = (index: number, e?: React.MouseEvent) => {
    // Shift：以锚点连选一段；普通点击/勾选：直接加选或反选（无需 Ctrl）
    if (e?.shiftKey && lastClickedRef.current !== null) {
      const a = cues.findIndex((c) => c.index === lastClickedRef.current)
      const b = cues.findIndex((c) => c.index === index)
      if (a >= 0 && b >= 0) {
        const [lo, hi] = a < b ? [a, b] : [b, a]
        const range = cues.slice(lo, hi + 1).map((c) => c.index)
        setSelectedCueIndices((prev) => {
          const set = new Set([...prev, ...range])
          return [...set].sort((x, y) => x - y)
        })
        lastClickedRef.current = index
        setPreviewCueIndex(index)
        return
      }
    }
    setSelectedCueIndices((prev) =>
      prev.includes(index) ? prev.filter((i) => i !== index) : [...prev, index].sort((x, y) => x - y),
    )
    setPreviewCueIndex(index)
    lastClickedRef.current = index
  }

  const assignPipToSelection = async (file: File) => {
    if (!selectionRange || selectedCueIndices.length === 0) return
    setBusy(true)
    try {
      const res = await api.uploadPipAsset(session.path, selectedCueIndices[0], file)
      if (res.ok) {
        const isVid =
          res.media_type === 'video' ||
          isVideoFile(file) ||
          /\.(mp4|mov|webm|mkv|m4v)$/i.test(res.media_path)
        let sourceDur: number | null = null
        if (isVid) {
          sourceDur = await detectVideoDuration(file)
        }
        addPipAssignmentFromPath({
          media_path: res.media_path,
          media_type: isVid ? 'video' : 'image',
          play_full_video: false,
          source_start_sec: 0,
          source_duration_sec: sourceDur,
        })
      }
    } catch (e) {
      setLog(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const addPipAssignmentFromPath = (opts: {
    media_path: string
    media_type: 'image' | 'video'
    play_full_video?: boolean
    auto_hyperframe?: boolean
    position?: string
    scale?: number
    source_start_sec?: number
    source_duration_sec?: number | null
    crop?: CropBox | null
  }) => {
    if (!selectionRange || selectedCueIndices.length === 0) return
    const span = Math.max(0.5, selectionRange.end - selectionRange.start)
    const assignment: PipAssignment = {
      id: `pip_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
      cue_indices: [...selectedCueIndices],
      start: selectionRange.start,
      end: selectionRange.end,
      media_path: opts.media_path,
      media_type: opts.media_type,
      preview_url: mediaUrl(opts.media_path),
      position: opts.auto_hyperframe
        ? 'fullscreen'
        : normalizeContentPipPosition(opts.position || contentPipPosition),
      scale: opts.scale ?? contentPipScale,
      display_duration_sec: opts.media_type === 'video' ? span : pendingDisplaySec,
      play_full_video: opts.auto_hyperframe ? true : Boolean(opts.play_full_video),
      source_start_sec: opts.source_start_sec ?? 0,
      source_duration_sec: opts.source_duration_sec ?? null,
      crop: opts.crop ?? null,
      auto_hyperframe: opts.auto_hyperframe,
    }
    setPipAssignments((prev) => {
      const overlap = new Set(assignment.cue_indices)
      const kept = prev.filter((p) => !p.cue_indices.some((i) => overlap.has(i)))
      return [...kept, assignment]
    })
    setEditingPipId(assignment.id)
    setLog(
      layoutMode === 'education'
        ? `已为 ${selectedCueIndices.length} 条字幕绑定教学素材`
        : `已为 ${selectedCueIndices.length} 条字幕绑定画中画`,
    )
  }

  const assignPipFromLibrary = async (asset: PickerAsset) => {
    if (!selectionRange || selectedCueIndices.length === 0) return
    setBusy(true)
    try {
      const res = await api.publishPipFromLibrary(session.path, selectedCueIndices[0], asset.id)
      if (res.ok) {
        addPipAssignmentFromPath({
          media_path: res.media_path,
          media_type: res.media_type,
          play_full_video: false,
          source_start_sec: 0,
        })
      }
    } catch (e) {
      setLog(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const fillHyperframes = async (opts: {
    theme: string
    layout: string
    aspect: string
    position: string
    scale?: number
    composeMode?: ComposeMode
    assignments: PipAssignment[]
    targetIndices?: number[]
    smartStyle?: boolean
    remotionCaptions?: boolean
    chainPublish?: Record<string, unknown>
  }): Promise<{ enqueued: boolean; message: string }> => {
    const skip = [
      ...new Set(opts.assignments.filter((p) => !p.auto_hyperframe).flatMap((p) => p.cue_indices)),
    ]
    const mode = opts.composeMode || composeMode
    const outcome = await jobQueue.enqueue({
      type: 'hyperframe_fill_cues',
      title: opts.chainPublish ? '智能生成并成片' : '智能时间段场景',
      payload: {
        session_path: session.path,
        theme: opts.theme,
        layout: opts.layout,
        aspect: opts.aspect,
        compose_mode: mode,
        cues,
        skip_indices: skip,
        target_indices: opts.targetIndices?.length ? opts.targetIndices : [],
        smart_merge: true,
        force_contiguous: !!(opts.targetIndices && opts.targetIndices.length),
        smart_style: mode === 'fusion' ? !!opts.smartStyle : opts.smartStyle !== false,
        smart_layout: hfSmartLayout,
        smart_theme: hfSmartTheme,
        smart_keywords: hfSmartKeywords,
        remotion_captions: false,
        remotion_theme: 'off',
        font_id: hfFontId,
        font_scale: hfFontScale,
        bg_mode: mode === 'fusion' ? 'transparent' : hfBgMode,
        bg_prompt: mode === 'fusion' ? '' : hfBgPrompt,
        save_to_library: true,
        merge_meta: {
          position: mode === 'fusion' ? 'fullscreen' : opts.position,
          scale: 1,
        },
        ...(opts.chainPublish ? { chain_publish: opts.chainPublish } : {}),
      },
    })
    if (outcome.ok) {
      setLog(outcome.message + ' · 可在任务中心查看进度')
      return { enqueued: true, message: outcome.message }
    }
    setLog(outcome.message)
    return { enqueued: false, message: outcome.message }
  }

  const selectedLipsyncPath = session.selected_lipsync ?? session.lipsync_video
  const lipsyncTakes = session.lipsyncs || []
  const lipsyncPreviewUrl = mediaUrl(
    selectedLipsyncPath || session.lipsync_video,
    session.lipsync_mtime,
  )

  // Sync 成片画幅 / 预览比例 with the currently selected lipsync take
  useEffect(() => {
    const path = selectedLipsyncPath || session.lipsync_video
    if (!path) return
    let cancelled = false
    const url = mediaUrl(path, session.lipsync_mtime)
    if (!url) return
    void detectVideoAspectFromUrl(url).then((asp) => {
      if (cancelled || !asp) return
      setPublishAspect((prev) => (prev === asp ? prev : asp))
      setSubtitlePreviewStale(true)
    })
    return () => {
      cancelled = true
    }
  }, [selectedLipsyncPath, session.lipsync_video, session.lipsync_mtime])

  const onLipsyncSelect = async (path: string) => {
    if (!path || !session.path || !onUpdate) return
    if (pathsRoughlyEqual(path, selectedLipsyncPath)) return
    try {
      await api.prepareSessionMedia(path).catch(() => null)
      await api.selectSessionLipsync(session.path, path)
      const snap = await api.sessionSnapshot(session.path)
      onUpdate(snap)
      const url = mediaUrl(path, snap.lipsync_mtime)
      const asp = url ? await detectVideoAspectFromUrl(url) : null
      if (asp) {
        setPublishAspect(asp)
        setRightPreviewTab('lipsync')
        setSubtitlePreviewStale(true)
        setLog(
          `已切换口播 · ${asp === 'landscape_16_9' ? '横屏 16:9' : '竖屏 9:16'}`,
        )
      } else {
        setLog('已切换口播版本')
      }
    } catch (e) {
      setLog(e instanceof Error ? e.message : String(e))
    }
  }

  const enableFullContentAuto = () => {
    setHfSmartLayout(true)
    setHfSmartTheme(true)
    setHfSmartKeywords(true)
    if (composeMode !== 'fusion') setHfSmartBg(true)
    setHfRemotionTheme('auto')
    const indices =
      selectedCueIndices.length > 0
        ? selectedCueIndices
        : previewCue
          ? [previewCue.index]
          : cues.slice(0, 3).map((c) => c.index)
    if (indices.length) void refreshHfSuggest(indices)
    setSubtitlePreviewStale(true)
  }

  const refreshHfSuggest = async (indices: number[]) => {
    const sample = indices
      .map((i) => cues.find((c) => c.index === i)?.text || '')
      .filter(Boolean)
      .join(' ')
      .slice(0, 200)
    setHfSuggestBusy(true)
    try {
      const sug = await api.publishHyperframeSuggest(sample, publishAspect)
      if (hfSmartTheme) setHyperframesTheme(sug.theme)
      if (hfSmartLayout) setHyperframesLayout(sug.layout)
      if (hfRemotionTheme === 'auto' && sug.remotion_theme) {
        setHfSuggestReasons([
          ...(sug.remotion_reasons || []),
          ...(sug.reasons || []),
        ])
      } else {
        setHfSuggestReasons(sug.reasons || [])
      }
    } catch {
      setHfSuggestReasons([])
    } finally {
      setHfSuggestBusy(false)
    }
  }

  const openAiPipModal = () => {
    if (selectedCueIndices.length === 0) {
      setLog('请先在时间轴勾选要生成字幕场景的字幕')
      return
    }
    styleModalModeRef.current = 'pip_ai'
    const sorted = [...selectedCueIndices].sort((a, b) => a - b)
    oneClickTargetRef.current = sorted
    const mode: ComposeMode = layoutMode === 'short' ? 'fusion' : 'cover'
    setComposeMode(mode)
    if (mode === 'fusion') {
      setHyperframesLayout('glass_card')
      setHfSmartLayout(false)
      setHfSmartTheme(true)
      setHfSmartBg(false)
      setHfBgMode('transparent')
      setHfCardPosition('auto')
      setHfCardScale(0.42)
      setHfMoreOpen(true)
    } else {
      setHyperframesLayout('kinetic')
      setHfSmartLayout(true)
      setHfSmartTheme(true)
      setHfSmartBg(true)
      if (hfBgMode === 'transparent') setHfBgMode('generative')
      setHfMoreOpen(false)
    }
    setHfSmartKeywords(true)
    setStyleModalOpen(true)
    if (mode === 'cover') void refreshHfSuggest(sorted)
  }

  const generateAiPipForSelection = async (opts: {
    theme: string
    layout: string
    aspect: string
    composeMode?: ComposeMode
    targetIndices?: number[]
    smartStyle?: boolean
    remotionCaptions?: boolean
  }) => {
    const indices = (
      opts.targetIndices?.length ? opts.targetIndices : selectedCueIndices
    )
      .slice()
      .sort((a, b) => a - b)
    if (indices.length === 0) return
    const mode = opts.composeMode || composeMode
    const isFusion = mode === 'fusion'
    setLog('')
    try {
      await fillHyperframes({
        theme: opts.theme,
        layout: opts.layout,
        aspect: opts.aspect,
        composeMode: mode,
        position: isFusion ? 'fullscreen' : 'fullscreen',
        scale: 1,
        assignments: pipAssignments,
        targetIndices: indices,
        smartStyle: opts.smartStyle,
        remotionCaptions: opts.remotionCaptions,
      })
      if (isFusion) {
        setContentPipPosition('center')
        setContentPipScale(0.32)
        setHfCardPosition('auto')
      } else {
        setContentPipPosition('fullscreen')
        setContentPipScale(1)
      }
      setEnablePipTimeline(true)
      setHyperframesConsent(true)
    } catch (e) {
      setLog(e instanceof Error ? e.message : String(e))
    }
  }

  const updatePip = (id: string, patch: Partial<PipAssignment>) => {
    setPipAssignments((prev) => prev.map((p) => (p.id === id ? { ...p, ...patch } : p)))
    setSubtitlePreviewStale(true)
  }

  const removePipAssignment = async (p: PipAssignment) => {
    if (!session.path) return
    setPipAssignments((prev) => prev.filter((x) => x.id !== p.id))
    if (editingPipId === p.id) setEditingPipId(null)
    setSubtitlePreviewStale(true)
    try {
      const res = await api.deletePipAssignment(session.path, {
        cue_indices: p.cue_indices,
        media_path: p.media_path,
        delete_media: p.auto_hyperframe,
      })
      const list = res.assignments || []
      const stamp = Date.now()
      setPipAssignments(
        list.map((a, i) =>
          mapApiAssignmentToPip(
            a as Parameters<typeof mapApiAssignmentToPip>[0],
            `hf_del_${(a.cue_indices as number[] | undefined)?.join('_') || i}_${stamp}`,
          ),
        ),
      )
      setLog(res.message || `已删除画中画 #${p.cue_indices.join(',')}`)
    } catch (e) {
      setLog(e instanceof Error ? e.message : String(e))
      void api.publishPipAssignments(session.path).then((r) => {
        const stamp = Date.now()
        setPipAssignments(
          (r.assignments || []).map((a, i) =>
            mapApiAssignmentToPip(
              a as Parameters<typeof mapApiAssignmentToPip>[0],
              `hf_reload_${i}_${stamp}`,
            ),
          ),
        )
      })
    }
  }

  const buildPublishPayload = (opts: {
    layoutMode: 'short' | 'education'
    hyperframesConsent: boolean
    hyperframesTheme: string
    hyperframesLayout: string
    publishAspect: string
    pipPosition: string
    pipAssignments: PipAssignment[]
    pipScaleOverride?: number
    hyperframesTargetIndices?: number[]
    coverImagePath?: string | null
  }): Record<string, unknown> => {
    const scaleToSend =
      opts.pipScaleOverride ??
      (opts.layoutMode === 'education' && opts.publishAspect === 'landscape_16_9' ? 0.2 : pipScale)
    const hasPip = opts.pipAssignments.length > 0
    const hasFusion = opts.pipAssignments.some(
      (p) =>
        p.compose_mode === 'fusion' ||
        FUSION_LAYOUT_IDS.has(String(p.content_style || p.scene_layout || '')),
    )
    const pipCues = opts.pipAssignments.map((p) => {
      const isFusion =
        p.compose_mode === 'fusion' ||
        FUSION_LAYOUT_IDS.has(String(p.content_style || p.scene_layout || ''))
      let position = p.position
      if (isFusion) position = 'fullscreen'
      else if (p.auto_hyperframe) position = 'fullscreen'
      else position = normalizeContentPipPosition(p.position)
      return {
        cue_indices: p.cue_indices,
        start: p.start,
        end: p.end,
        media_path: p.media_path,
        position,
        scale: isFusion ? 1 : (p.scale ?? 0.32),
        display_duration_sec: p.media_type === 'image' ? p.display_duration_sec : undefined,
        play_full_video: p.media_type === 'video' ? p.play_full_video : false,
        source_start_sec: p.media_type === 'video' ? p.source_start_sec ?? 0 : 0,
        crop: p.media_type === 'image' ? p.crop || undefined : undefined,
        auto_hyperframe: !!p.auto_hyperframe,
        compose_mode: isFusion ? 'fusion' : p.compose_mode || 'cover',
        content_style: p.content_style || p.scene_layout,
        scene_layout: p.scene_layout || p.content_style,
      }
    })
    let pipMode = 'none'
    if (opts.layoutMode === 'education') {
      const useTimed = hasPip || (opts.hyperframesConsent && cues.length > 0)
      pipMode = useTimed ? 'education_timed' : 'education'
    } else {
      pipMode = hasPip ? 'timed' : 'none'
    }
    const remotionTheme = enableSubtitles ? hfRemotionTheme || 'off' : 'off'
    return {
      session_path: session.path,
      script,
      title: postTitle.trim() || coverTitle || '口播成片',
      cover_time: 0.5,
      template: 'dy_bottom',
      subtitle_style: 'bottom_clean',
      subtitle_pause: 0.35,
      subtitle_font_size: subtitleFontSize,
      subtitle_color: subtitleColor,
      subtitle_outline: subtitleOutline,
      subtitle_shadow: subtitleShadow,
      subtitle_position: subtitlePosition,
      burn_subtitles: enableSubtitles,
      remotion_theme: remotionTheme,
      remotion_smart_keywords: hfSmartKeywords,
      layout_mode: opts.layoutMode,
      hf_text_cards: opts.layoutMode === 'short' && hasFusion,
      glass_cards: [],
      hf_card_position: opts.layoutMode === 'short' ? hfCardPosition : 'auto',
      hf_card_scale: opts.layoutMode === 'short' ? hfCardScale : 0.58,
      embed_cover: true,
      cover_image_path: opts.coverImagePath || '',
      cues: cuesEdited && cues.length > 0 ? cues : undefined,
      pip_mode: pipMode,
      pip_position: opts.pipPosition,
      pip_scale: scaleToSend,
      pip_margin: pipMargin,
      lecturer_crop: lecturerCrop || undefined,
      hyperframes_consent: !!opts.hyperframesConsent,
      hyperframes_theme: opts.hyperframesTheme,
      hyperframes_layout: opts.hyperframesLayout,
      hyperframes_aspect: opts.publishAspect,
      hyperframes_target_indices: opts.hyperframesTargetIndices || [],
      pip_cues: hasPip ? pipCues : [],
      enable_bgm: enableBgm,
      bgm_id: enableBgm && bgmId ? bgmId : '',
      bgm_volume: bgmVolume,
      bgm_start: bgmStart,
    }
  }

  const runPublish = async (opts: {
    layoutMode: 'short' | 'education'
    hyperframesConsent: boolean
    hyperframesTheme: string
    hyperframesLayout: string
    publishAspect: string
    pipPosition: string
    pipAssignments: PipAssignment[]
    progressLabel?: string
    pipScaleOverride?: number
    hyperframesTargetIndices?: number[]
  }) => {
    setLog('')
    try {
      const prepared = await prepareCoverForPublish()
      const payload = buildPublishPayload({
        ...opts,
        coverImagePath: prepared.coverPath,
      })
      const outcome = await jobQueue.enqueue({
        type: 'publish_run',
        title: opts.progressLabel || '一键成片',
        payload,
      })
      setLog(outcome.ok ? outcome.message + ' · 可在任务中心查看进度' : outcome.message)
    } catch (e) {
      setLog(e instanceof Error ? e.message : String(e))
    }
  }

  const cancelPublish = async () => {
    const running = jobQueue.jobs.find((j) => j.status === 'running' && j.type === 'publish_run')
    if (running) {
      await jobQueue.cancelJob(running.id)
      setLog('已请求取消成片任务')
      return
    }
    try {
      await api.cancelPublish()
    } catch {
      await api.cancelTask().catch(() => undefined)
    }
    publishAbortRef.current?.abort()
    setProgress((p) => (p ? { ...p, msg: '正在终止…' } : p))
  }

  const run = async () => {
    setLog('')
    if (hyperframesConsent && layoutMode === 'education' && selectedCueIndices.length === 0) {
      setLog('已开启 HyperFrames：请先在时间轴勾选字幕（不支持未选时全文生成）')
      return
    }
    await runPublish({
      layoutMode,
      hyperframesConsent: hyperframesConsent && selectedCueIndices.length > 0,
      hyperframesTheme,
      hyperframesLayout,
      publishAspect,
      pipPosition,
      pipAssignments,
      hyperframesTargetIndices:
        selectedCueIndices.length > 0
          ? [...selectedCueIndices].sort((a, b) => a - b)
          : undefined,
    })
  }

  const runOneClickExport = async (opts?: {
    theme?: string
    layout?: string
    aspect?: string
    targetIndices?: number[]
    smartStyle?: boolean
    remotionCaptions?: boolean
  }) => {
    const theme = opts?.theme ?? hyperframesTheme
    const layout = opts?.layout ?? hyperframesLayout
    const aspect = opts?.aspect ?? publishAspect
    const targetIndices = opts?.targetIndices
    const useHf =
      layoutMode === 'education' &&
      hyperframesConsent &&
      !!targetIndices &&
      targetIndices.length > 0

    setLog('')
    try {
      if (useHf) {
        const chainPublish = buildPublishPayload({
          layoutMode,
          hyperframesConsent: true,
          hyperframesTheme: theme,
          hyperframesLayout: layout,
          publishAspect: aspect,
          pipPosition,
          pipAssignments: [],
          hyperframesTargetIndices: targetIndices,
        })
        await fillHyperframes({
          theme,
          layout,
          aspect,
          position: 'fullscreen',
          scale: 1,
          assignments: pipAssignments,
          targetIndices,
          smartStyle: opts?.smartStyle !== false,
          remotionCaptions: opts?.remotionCaptions !== false,
          chainPublish,
        })
        setContentPipPosition('fullscreen')
        setContentPipScale(1)
        setEnablePipTimeline(true)
        return
      }
      if (hyperframesConsent && layoutMode === 'education' && !(targetIndices && targetIndices.length)) {
        setLog('已勾选 HyperFrames 但未选时间轴：本次不生成/补洞 HyperFrames，按其余预设导出…')
      }
      await runPublish({
        layoutMode,
        hyperframesConsent: useHf,
        hyperframesTheme: theme,
        hyperframesLayout: layout,
        publishAspect: aspect,
        pipPosition,
        pipAssignments,
        progressLabel: '一键成片导出中…',
        hyperframesTargetIndices: targetIndices,
      })
    } catch (e) {
      setLog(e instanceof Error ? e.message : String(e))
    }
  }

  const openOneClickPresetConfirm = (target: number[] | 'all') => {
    oneClickTargetRef.current = target
    setOneClickConfirmTarget(target)
    setFullFilmConfirmOpen(true)
  }

  const oneClickFilm = () => {
    if (!selectedLipsyncPath && !session.lipsync_video) {
      setLog('请先完成④口播成片，或在上方选择口播版本')
      return
    }
    if (!cues.length) {
      setLog('暂无字幕时间轴，请等待识别完成或检查口播音频')
      return
    }
    if (hyperframesConsent && layoutMode === 'education' && selectedCueIndices.length === 0) {
      setLog('已开启 HyperFrames：请先在时间轴勾选要生成的字幕（不支持未选全文）')
      return
    }
    const target =
      selectedCueIndices.length > 0
        ? [...selectedCueIndices].sort((a, b) => a - b)
        : 'all'
    openOneClickPresetConfirm(target)
  }

  const confirmOneClickExport = () => {
    setFullFilmConfirmOpen(false)
    const target = oneClickTargetRef.current
    void runOneClickExport({
      targetIndices: target === 'all' ? undefined : target,
    })
  }

  const openOneClickStylePicker = () => {
    setFullFilmConfirmOpen(false)
    styleModalModeRef.current = 'oneclick'
    setHfMoreOpen(false)
    setStyleModalOpen(true)
    const target = oneClickTargetRef.current
    if (Array.isArray(target) && target.length) {
      void refreshHfSuggest(target)
    }
  }

  const restyleExistingScenes = async () => {
    const autos = pipAssignments.filter((p) => p.auto_hyperframe)
    if (!autos.length) {
      setLog('没有可换肤的智能场景，请先生成一次')
      return
    }
    setStyleModalOpen(false)
    setLog('')
    try {
      const outcome = await jobQueue.enqueue({
        type: 'hyperframe_restyle',
        title: '场景换肤',
        payload: {
          session_path: session.path,
          cues,
          assignments: autos.map((a) => ({
            cue_indices: a.cue_indices,
            start: a.start,
            end: a.end,
            auto_hyperframe: true,
            media_path: a.media_path,
          })),
          theme: hyperframesTheme,
          layout: hyperframesLayout,
          aspect: publishAspect,
          font_id: hfFontId,
          font_scale: hfFontScale,
          bg_mode: hfBgMode,
          bg_prompt: hfBgPrompt,
          remotion_theme: 'off',
          remotion_captions: false,
          save_to_library: true,
        },
      })
      setLog(outcome.ok ? outcome.message + ' · 可在任务中心查看进度' : outcome.message)
    } catch (e) {
      setLog(e instanceof Error ? e.message : String(e))
    }
  }

  const confirmStyleAndExport = () => {
    setStyleModalOpen(false)
    const mode = styleModalModeRef.current
    const target = oneClickTargetRef.current
    const useSmart = hfSmartLayout || hfSmartTheme
    if (mode === 'pip_ai') {
      void generateAiPipForSelection({
        theme: hyperframesTheme,
        layout: hyperframesLayout,
        aspect: publishAspect,
        composeMode,
        targetIndices: Array.isArray(target) ? target : undefined,
        smartStyle: composeMode === 'fusion' ? hfSmartTheme : useSmart,
      })
      return
    }
    void runOneClickExport({
      theme: hyperframesTheme,
      layout: hyperframesLayout,
      aspect: publishAspect,
      targetIndices: target === 'all' ? undefined : target,
      smartStyle: useSmart,
    })
  }

  const styleSummary =
    hfThemes.find((t) => t.id === hyperframesTheme)?.label || hyperframesTheme
  const layoutSummary =
    hfLayouts.find((l) => l.id === hyperframesLayout)?.label || hyperframesLayout
  const aspectSummary =
    hfAspects.find((a) => a.id === publishAspect)?.label || publishAspect

  const modalLayouts = useMemo(() => {
    const dim = { width: 1080, height: 1920 }
    if (composeMode === 'fusion') {
      const fusion = hfLayouts.filter((l) => FUSION_LAYOUT_IDS.has(l.id))
      const ids = new Set(fusion.map((l) => l.id))
      const extras: HyperLayoutMeta[] = []
      if (!ids.has('glass_card'))
        extras.push({ id: 'glass_card', label: '透明玻璃字卡', animated: true, ...dim })
      if (!ids.has('plain_text'))
        extras.push({ id: 'plain_text', label: '纯透明文字', animated: true, ...dim })
      // Prefer glass_card over legacy text_card duplicate label
      const list = fusion.filter((l) => l.id !== 'text_card' || !ids.has('glass_card'))
      return [...list, ...extras]
    }
    return hfLayouts.filter((l) => !FUSION_LAYOUT_IDS.has(l.id))
  }, [hfLayouts, composeMode])

  const oneClickPresetRows = useMemo(() => {
    const scope =
      oneClickConfirmTarget === 'all'
        ? `未勾选时间轴 · 不生成 HyperFrames`
        : `已选 ${oneClickConfirmTarget.length} 条字幕`
    const pipLabel =
      pipAssignments.length > 0
        ? `已绑定 ${pipAssignments.length} 段`
        : enablePipTimeline
          ? '已开时间轴 · 尚未绑定素材'
          : '未开启'
    const hfOn =
      hyperframesConsent &&
      layoutMode === 'education' &&
      oneClickConfirmTarget !== 'all' &&
      oneClickConfirmTarget.length > 0
    const rows: { label: string; value: string; on?: boolean }[] = [
      {
        label: '成片模式',
        value: layoutMode === 'education' ? '网课混剪' : '口播混剪',
        on: true,
      },
      {
        label: '画幅',
        value: aspectSummary,
        on: true,
      },
      {
        label: '口播窗口',
        value:
          layoutMode === 'education'
            ? `${PIP_POSITIONS.find((p) => p.value === pipPosition)?.label || pipPosition} · ${Math.round(pipScale * 100)}%`
            : '全屏口播',
        on: true,
      },
      {
        label: '字幕烧录',
        value: enableSubtitles
          ? hfRemotionTheme !== 'off'
            ? `Remotion · ${hfRemThemes.find((t) => t.id === hfRemotionTheme)?.label || hfRemotionTheme} · ${subtitleColor}`
            : `${subtitleFontSize}px · ${SUBTITLE_COLORS.find((c) => c.value === subtitleColor)?.label || subtitleColor} · ${subtitlePosition === 'bottom' ? '底部' : '顶部'}`
          : '未开启',
        on: enableSubtitles,
      },
      {
        label: '背景音乐',
        value: enableBgm
          ? `${activeBgm?.name || bgmId} · 音量 ${Math.round(bgmVolume * 100)}%`
          : '未开启',
        on: enableBgm,
      },
      {
        label: '画中画 / 讲解',
        value: pipLabel,
        on: pipAssignments.length > 0,
      },
      {
        label: 'HyperFrames',
        value: hfOn
          ? `${styleSummary} · ${layoutSummary}（仅所选时段）`
          : hyperframesConsent && layoutMode === 'education'
            ? '已勾选但未选时间轴 · 本次跳过'
            : layoutMode === 'education'
              ? '未开启（仅用已绑定素材）'
              : '口播混剪模式不适用',
        on: hfOn,
      },
      {
        label: '生成范围',
        value: scope,
        on: true,
      },
    ]
    return rows
  }, [
    oneClickConfirmTarget,
    cues.length,
    pipAssignments,
    enablePipTimeline,
    layoutMode,
    aspectSummary,
    pipPosition,
    pipScale,
    enableSubtitles,
    subtitleFontSize,
    subtitleColor,
    subtitlePosition,
    hfRemotionTheme,
    hfRemThemes,
    enableBgm,
    activeBgm,
    bgmId,
    bgmVolume,
    hyperframesConsent,
    styleSummary,
    layoutSummary,
  ])

  const oneClickHasWeakPresets =
    !enableSubtitles &&
    !enableBgm &&
    pipAssignments.length === 0 &&
    !(hyperframesConsent && layoutMode === 'education')


  const cueHasPip = (idx: number) =>
    pipAssignments.some((p) => p.cue_indices.includes(idx))

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-[var(--info-border)] bg-[var(--info-bg)] px-4 py-3 text-sm text-[var(--info-text)]">
        字幕与画中画共用一条时间轴。进入本页会按会话文案对齐；音频不一致时点「一键提取字幕」（以识别为准，结果有绿/红提示）。烧录仅管样式。右侧预览需手动点「生成混剪预览」。
        {cuesLoading && ' · 正在对齐时间轴…'}
        {extractLoading && ' · 正在从音频提取字幕…'}
        {!cuesLoading && !extractLoading && timingNote && ` · ${timingNote}`}
        {cuesEdited && ' · 已手动改字幕 / 以识别为准'}
      </div>

      {lipsyncTakes.length > 0 && (
        <div className="rounded-xl border border-[var(--border)] bg-[var(--panel)] p-3">
          <div className="mb-1.5 flex items-center justify-between gap-2">
            <p className="text-xs font-medium text-[var(--text)]">口播版本（发布源）</p>
            <span className="text-[10px] text-[var(--muted)]">{lipsyncTakes.length} 条</span>
          </div>
          <ul className="max-h-36 space-y-1 overflow-auto">
            {lipsyncTakes.map((take) => {
              const active = pathsRoughlyEqual(selectedLipsyncPath, take.path)
              return (
                <li key={take.id || take.path}>
                  <button
                    type="button"
                    onClick={() => void onLipsyncSelect(take.path)}
                    className={`w-full rounded-lg border px-2.5 py-1.5 text-left text-[11px] ${
                      active
                        ? 'border-[var(--accent)] bg-[var(--select-bg)] text-[var(--accent)]'
                        : 'border-transparent text-[var(--text)] hover:bg-[var(--bg)]'
                    }`}
                  >
                    <span className="block font-medium">{take.name}</span>
                    <span className="text-[10px] text-[var(--muted)]">
                      {take.source === 'current'
                        ? '当前选用 · 发布将基于此片'
                        : take.source === 'legacy'
                          ? '会话遗留'
                          : '历史归档'}
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
          <p className="mt-1.5 text-[10px] text-[var(--muted)]">
            点选切换发布源；画幅自动跟随口播（当前{' '}
            {publishAspect === 'landscape_16_9' ? '16:9 横屏' : '9:16 竖屏'}）
          </p>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(260px,300px)]">
        <Panel title="05 发布 · 剪辑">
          <div className="flex overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--bg)]">
            <TabBtn active={editTab === 'subtitle'} onClick={() => setEditTab('subtitle')}>
              混剪成片
            </TabBtn>
            <TabBtn
              active={editTab === 'cover'}
              onClick={() => {
                setCustomCover(true)
                setEditTab('cover')
              }}
            >
              封面
            </TabBtn>
            <TabBtn active={editTab === 'post'} onClick={() => setEditTab('post')}>
              发布
            </TabBtn>
          </div>

          {editTab === 'subtitle' && (
            <div className="mt-4 space-y-4">
              <div className="rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3">
                <p className="mb-2 text-xs font-medium text-[var(--text)]">成片布局</p>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    className={`rounded-lg border px-3 py-1.5 text-xs ${
                      layoutMode === 'short'
                        ? 'border-[var(--accent)] bg-[var(--select-bg)] text-[var(--accent)]'
                        : 'border-[var(--border)] text-[var(--muted)] hover:bg-[var(--panel)]'
                    }`}
                    onClick={() => {
                      setLayoutMode('short')
                      setEnableSubtitles(true)
                      // 口播混剪：默认 Remotion 底部条叠在口播上（不再用侧向动效）
                      if (hfRemotionTheme === 'off' || hfRemotionTheme === 'side') {
                        setHfRemotionTheme('bar')
                      }
                    }}
                  >
                    口播混剪（默认）
                  </button>
                  <button
                    type="button"
                    className={`rounded-lg border px-3 py-1.5 text-xs ${
                      layoutMode === 'education'
                        ? 'border-[var(--accent)] bg-[var(--select-bg)] text-[var(--accent)]'
                        : 'border-[var(--border)] text-[var(--muted)] hover:bg-[var(--panel)]'
                    }`}
                    onClick={() => {
                      setLayoutMode('education')
                      setPipPosition('bottom_right')
                    }}
                  >
                    网课讲解 · 口播右下
                  </button>
                </div>
                {layoutMode === 'education' && (
                  <div className="mt-3 space-y-3 border-t border-dashed border-[var(--border)] pt-3">
                    <p className="text-[10px] leading-relaxed text-[var(--muted)]">
                      <strong className="text-[var(--text)]">核心口播</strong>
                      叠在角落（可自动 1:1 裁切）。主画面优先用时间轴教学素材 / HyperFrames；
                      <strong className="text-[var(--text)]">固定底图</strong>
                      是「整段没有讲解素材时」的全片静态垫底，不是画中画。
                    </p>
                    {hfAspects.length > 0 && (
                      <div>
                        <p className="mb-1.5 text-[10px] font-medium text-[var(--text)]">成片画幅</p>
                        <div className="flex flex-wrap gap-2">
                          {hfAspects.map((a) => {
                            const active = publishAspect === a.id
                            const landscape = a.width > a.height
                            return (
                              <button
                                key={a.id}
                                type="button"
                                onClick={() => {
                                  setPublishAspect(a.id)
                                  setHyperframesAspect(a.id)
                                }}
                                className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-left transition ${
                                  active
                                    ? 'border-[var(--accent)] bg-[var(--select-bg)] ring-1 ring-[var(--select-border)]'
                                    : 'border-[var(--border)] hover:border-[var(--muted)]'
                                }`}
                              >
                                <span
                                  className={`inline-block shrink-0 rounded border border-white/20 bg-gradient-to-br from-[var(--accent)]/30 to-transparent ${
                                    landscape ? 'h-5 w-9' : 'h-9 w-5'
                                  }`}
                                />
                                <span>
                                  <span className="block text-[10px] font-medium">{a.label}</span>
                                  <span className="text-[9px] text-[var(--muted)]">{a.ratio}</span>
                                </span>
                              </button>
                            )
                          })}
                        </div>
                      </div>
                    )}
                    <div className="flex flex-wrap items-center gap-2">
                      <input
                        ref={educationBgInputRef}
                        type="file"
                        accept="image/*,video/*"
                        className="hidden"
                        onChange={(e) => {
                          const f = e.target.files?.[0]
                          if (f) setEducationBgFile(f)
                          e.target.value = ''
                        }}
                      />
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => educationBgInputRef.current?.click()}
                        className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs hover:bg-[var(--panel)] disabled:opacity-40"
                      >
                        固定底图（可选·全片垫底）
                      </button>
                      {educationBgFile && (
                        <span className="text-xs text-[var(--accent)]">{educationBgFile.name}</span>
                      )}
                      {educationBgFile && (
                        <button
                          type="button"
                          className="text-[10px] text-[var(--muted)] underline"
                          onClick={() => setEducationBgFile(null)}
                        >
                          清除底图
                        </button>
                      )}
                      <label className="flex items-center gap-1.5 text-xs text-[var(--muted)]">
                        <input
                          type="checkbox"
                          checked={hyperframesConsent}
                          onChange={(e) => setHyperframesConsent(e.target.checked)}
                        />
                        导出时按时间轴勾选范围生成 HyperFrames（必须先勾选字幕，不支持未选全文）
                      </label>
                    </div>
                    {hyperframesConsent && (
                      <p className="text-[10px] leading-relaxed text-[var(--muted)]">
                        当前风格：{styleSummary} · {layoutSummary} · {aspectSummary}。可在素材中心改成片风格，或在一键成片确认里改版式。
                      </p>
                    )}
                    <div className="grid gap-3 sm:grid-cols-3">
                      <label className="block text-xs text-[var(--muted)]">
                        口播窗口位置
                        <select
                          value={pipPosition}
                          onChange={(e) => setPipPosition(e.target.value)}
                          className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--panel)] px-2 py-1.5 text-xs"
                        >
                          {PIP_POSITIONS.filter((p) => p.value !== 'fullscreen').map((p) => (
                            <option key={p.value} value={p.value}>
                              {p.label}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="block text-xs text-[var(--muted)]">
                        口播窗口大小 {Math.round(pipScale * 100)}%
                        <input
                          type="range"
                          min={0.15}
                          max={0.4}
                          step={0.01}
                          value={pipScale}
                          onChange={(e) => setPipScale(Number(e.target.value))}
                          className="mt-1 w-full"
                        />
                        <span className="mt-0.5 block text-[10px] text-[var(--muted)]">
                          横屏默认 20%，竖屏默认 28%
                        </span>
                      </label>
                      <label className="block text-xs text-[var(--muted)]">
                        边距 {pipMargin}px
                        <input
                          type="range"
                          min={8}
                          max={64}
                          step={2}
                          value={pipMargin}
                          onChange={(e) => setPipMargin(Number(e.target.value))}
                          className="mt-1 w-full"
                        />
                      </label>
                    </div>
                    <div className="rounded-lg border border-dashed border-[var(--border)] p-3 space-y-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <button
                          type="button"
                          disabled={busy || lecturerCropBusy || !(selectedLipsyncPath || session.lipsync_video)}
                          onClick={() => void openLecturerCropModal()}
                          className="rounded-lg border border-[var(--accent)] bg-[var(--select-bg)] px-3 py-1.5 text-xs text-[var(--accent)] hover:brightness-110 disabled:opacity-40"
                        >
                          {lecturerCropBusy ? '加载中…' : '选择口播区域'}
                        </button>
                        {lecturerCrop && (
                          <button
                            type="button"
                            onClick={() => {
                              setLecturerCrop(null)
                              setLecturerCropPreview(null)
                            }}
                            className="text-[10px] text-[var(--muted)] underline"
                          >
                            清除裁切（用整帧）
                          </button>
                        )}
                      </div>
                      <p className="text-[10px] text-[var(--muted)]">
                        默认用整帧口播 cover 进<strong className="text-[var(--text)]">1:1 小窗</strong>
                        。点「选择口播区域」后可拖拽框选，或在弹框内「一键自动 1:1」再确认才会裁切。
                      </p>
                      {lecturerCropPreview && (
                        <img
                          src={lecturerCropPreview}
                          alt="口播裁切预览"
                          className="h-28 rounded-lg border border-[var(--border)] object-contain bg-[var(--bg)]"
                        />
                      )}
                    </div>
                  </div>
                )}
              </div>

              <div className="rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3">
                <label className="flex items-center gap-2 text-xs font-medium text-[var(--text)]">
                  <input
                    type="checkbox"
                    checked={enableSubtitles}
                    onChange={(e) => setEnableSubtitles(e.target.checked)}
                  />
                  烧录字幕
                </label>
                {enableSubtitles && (
                  <>
                    <p className="mb-2 mt-3 text-[10px] text-[var(--muted)]">
                      {layoutMode === 'short'
                        ? '口播混剪：Remotion 字幕直接叠在口播画面上（你要的融合）。经典 ASS 为备选。'
                        : '成片字幕：经典 ASS，或 Remotion 模板；预览在右侧手机框。'}
                    </p>
                    <div className="mb-3 flex flex-wrap items-center gap-2">
                      <button
                        type="button"
                        onClick={enableFullContentAuto}
                        className="rounded-lg border border-[var(--accent)] bg-[var(--select-bg)] px-2.5 py-1.5 text-[11px] text-[var(--accent)]"
                      >
                        智能全自动（按内容）
                      </button>
                      <span className="text-[10px] text-[var(--muted)]">
                        版式 / 配色 / 关键词色 / Remotion 模板一并按字幕推荐
                      </span>
                    </div>
                    <div className="mb-3 flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => setHfRemotionTheme('off')}
                        className={`rounded-lg border px-2.5 py-1.5 text-[11px] ${
                          hfRemotionTheme === 'off'
                            ? 'border-[var(--accent)] bg-[var(--select-bg)] text-[var(--accent)]'
                            : 'border-[var(--border)] text-[var(--muted)]'
                        }`}
                      >
                        经典 ASS
                      </button>
                      {(hfRemThemes.length
                        ? hfRemThemes.filter(
                            (t) => t.id !== 'off' && t.id !== 'side' && t.id !== 'side_kinetic',
                          )
                        : [
                            { id: 'auto', label: '智能自动（按内容）' },
                            { id: 'glass', label: '毛玻璃底牌' },
                            { id: 'pill', label: '胶囊强调' },
                            { id: 'bar', label: '底部字幕条' },
                            { id: 'kinetic', label: '居中动感字' },
                            { id: 'pop', label: '弹跳强调' },
                          ]
                      ).map((t) => (
                        <button
                          key={t.id}
                          type="button"
                          onClick={() => setHfRemotionTheme(t.id)}
                          className={`rounded-lg border px-2.5 py-1.5 text-[11px] ${
                            hfRemotionTheme === t.id
                              ? 'border-[var(--accent)] bg-[var(--select-bg)] text-[var(--accent)]'
                              : 'border-[var(--border)] text-[var(--muted)]'
                          }`}
                        >
                          Remotion · {t.label}
                        </button>
                      ))}
                    </div>
                    {hfRemotionTheme !== 'off' && (
                      <p className="mb-3 text-[10px] text-[var(--muted)]">
                        混剪预览需手动点击右侧「生成混剪预览」，调整参数不会自动重渲。
                      </p>
                    )}
                    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                      <label className="block text-xs text-[var(--muted)]">
                        字号 {subtitleFontSize}
                        <input
                          type="range"
                          min={12}
                          max={26}
                          value={subtitleFontSize}
                          onChange={(e) => setSubtitleFontSize(Number(e.target.value))}
                          className="mt-1 w-full"
                        />
                        <span className="mt-0.5 block text-[10px] text-[var(--muted)]">
                          {hfRemotionTheme !== 'off'
                            ? 'Remotion 与经典 ASS 共用此字号（预览合成已接入）'
                            : '默认 16 · 范围 12–26 · 字号越大自动切更短字幕并对齐音频'}
                        </span>
                      </label>
                      <label className="block text-xs text-[var(--muted)]">
                        颜色
                        <div className="mt-1 flex flex-wrap gap-1.5">
                          {SUBTITLE_COLORS.map((c) => (
                            <button
                              key={c.value}
                              type="button"
                              title={c.label}
                              onClick={() => setSubtitleColor(c.value)}
                              className={`h-7 w-7 rounded-full border-2 ${
                                subtitleColor === c.value
                                  ? 'border-[var(--accent)]'
                                  : 'border-[var(--border)]'
                              }`}
                              style={{ background: c.value }}
                            />
                          ))}
                          <input
                            type="color"
                            value={subtitleColor}
                            onChange={(e) => setSubtitleColor(e.target.value)}
                            className="h-7 w-10 cursor-pointer rounded border border-[var(--border)] bg-transparent"
                          />
                        </div>
                      </label>
                      <label className="block text-xs text-[var(--muted)]">
                        描边 {subtitleOutline}
                        <input
                          type="range"
                          min={0}
                          max={4}
                          step={1}
                          value={subtitleOutline}
                          onChange={(e) => setSubtitleOutline(Number(e.target.value))}
                          className="mt-1 w-full"
                        />
                      </label>
                      <label className="block text-xs text-[var(--muted)]">
                        阴影 {subtitleShadow}
                        <input
                          type="range"
                          min={0}
                          max={4}
                          step={1}
                          value={subtitleShadow}
                          onChange={(e) => setSubtitleShadow(Number(e.target.value))}
                          className="mt-1 w-full"
                        />
                      </label>
                    </div>
                    <div className="mt-3 flex flex-wrap items-center gap-3 text-xs">
                      <span className="text-[var(--muted)]">位置（点选后右侧预览）</span>
                      <button
                        type="button"
                        className={`rounded-lg border px-2.5 py-1 ${
                          subtitlePosition === 'bottom'
                            ? 'border-[var(--accent)] bg-[var(--select-bg)] text-[var(--accent)]'
                            : 'border-[var(--border)]'
                        }`}
                        onClick={() => setSubtitlePosition('bottom')}
                      >
                        底部
                      </button>
                      <button
                        type="button"
                        className={`rounded-lg border px-2.5 py-1 ${
                          subtitlePosition === 'top'
                            ? 'border-[var(--accent)] bg-[var(--select-bg)] text-[var(--accent)]'
                            : 'border-[var(--border)]'
                        }`}
                        onClick={() => setSubtitlePosition('top')}
                      >
                        顶部
                      </button>
                    </div>
                  </>
                )}
              </div>

          <div className="rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <p className="text-xs font-medium text-[var(--text)]">字幕 / 画中画时间轴</p>
                <p className="mt-0.5 text-[10px] text-[var(--muted)]">
                  共用一条时间轴：编辑字幕、勾选后绑定素材或智能场景。音频与文案不一致时点「一键提取」。
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  disabled={extractLoading || busy || !session.path}
                  onClick={() => void extractSubtitlesFromAudio()}
                  className="rounded-lg border border-[var(--accent)] bg-[var(--select-bg)] px-2.5 py-1 text-[11px] text-[var(--accent)] disabled:opacity-40"
                >
                  {extractLoading ? '提取中…' : '一键提取字幕'}
                </button>
                {cuesEdited && (
                  <button
                    type="button"
                    disabled={cuesLoading || !script.trim()}
                    onClick={() => void restoreScriptAlignedCues()}
                    className="text-[10px] text-[var(--muted)] underline disabled:opacity-40"
                  >
                    恢复文案对齐
                  </button>
                )}
              </div>
            </div>

            {extractFeedback && (
              <div
                className={`mt-2 rounded-lg border px-3 py-2 text-[11px] ${
                  extractFeedback.kind === 'ok'
                    ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-600'
                    : extractFeedback.kind === 'error'
                      ? 'border-rose-500/40 bg-rose-500/10 text-rose-600'
                      : 'border-[var(--info-border)] bg-[var(--info-bg)] text-[var(--info-text)]'
                }`}
                role="status"
              >
                {extractFeedback.text}
                <button
                  type="button"
                  className="ml-2 underline opacity-70"
                  onClick={() => setExtractFeedback(null)}
                >
                  关闭
                </button>
              </div>
            )}

            {(timingNote || cuesLoading || extractLoading) && !extractFeedback && (
              <p className="mt-2 text-[10px] text-[var(--muted)]">
                {timingNote}
                {cuesEdited ? ' · 已编辑' : ''}
                {(cuesLoading || extractLoading) && ' · 处理中…'}
                {cues.length > 0 ? ` · ${cues.length} 条` : ''}
              </p>
            )}

            <label className="mt-3 flex items-center gap-2 text-xs text-[var(--muted)]">
              <input
                type="checkbox"
                checked={enablePipTimeline}
                onChange={(e) => {
                  setEnablePipTimeline(e.target.checked)
                  if (!e.target.checked) setSelectedCueIndices([])
                }}
              />
              启用画中画 / 讲解绑定（勾选时间轴条目后上传素材或生成智能场景）
            </label>

            <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
              <p className="text-[10px] text-[var(--muted)]">
                {enablePipTimeline
                  ? '点选勾选 / 再点反选 · Shift 连选 · 可直接改时间与文字'
                  : '可直接改时间与文字；需要绑定素材时请勾选上方「启用画中画」'}
              </p>
              {enablePipTimeline && cues.length > 0 && (
                <div className="flex items-center gap-2 text-[10px]">
                  <button
                    type="button"
                    className="text-[var(--accent)] underline"
                    onClick={() => {
                      setSelectedCueIndices(cues.map((c) => c.index))
                      lastClickedRef.current = cues[cues.length - 1]?.index ?? null
                    }}
                  >
                    全选
                  </button>
                  <button
                    type="button"
                    className="text-[var(--muted)] underline"
                    onClick={() => setSelectedCueIndices([])}
                  >
                    清空
                  </button>
                  <span className="text-[var(--muted)]">
                    {selectedCueIndices.length}/{cues.length}
                  </span>
                </div>
              )}
            </div>

            <div className="mt-2 max-h-64 overflow-auto rounded-xl border border-[var(--border)] bg-[var(--panel)]">
              {cues.length === 0 ? (
                <p className="p-3 text-xs text-[var(--muted)]">
                  暂无字幕条 · 点「一键提取字幕」从口播音频生成，或等待文案自动对齐
                </p>
              ) : (
                <>
                  {enablePipTimeline && (
                    <label className="flex cursor-pointer items-center gap-2 border-b border-[var(--border)] bg-[var(--bg)]/60 px-3 py-1.5 text-[11px] text-[var(--muted)]">
                      <input
                        type="checkbox"
                        checked={cues.length > 0 && selectedCueIndices.length === cues.length}
                        ref={(el) => {
                          if (!el) return
                          el.indeterminate =
                            selectedCueIndices.length > 0 &&
                            selectedCueIndices.length < cues.length
                        }}
                        onChange={(e) => {
                          if (e.target.checked) {
                            setSelectedCueIndices(cues.map((c) => c.index))
                          } else {
                            setSelectedCueIndices([])
                          }
                        }}
                      />
                      全选字幕（{cues.length} 条）
                    </label>
                  )}
                  {cues.map((c) => {
                    const selected = selectedCueIndices.includes(c.index)
                    return (
                      <div
                        key={c.index}
                        onClick={(e) => {
                          if (enablePipTimeline) toggleCueSelection(c.index, e)
                          else setPreviewCueIndex(c.index)
                        }}
                        className={`flex flex-wrap items-center gap-1.5 border-b border-[var(--border)] px-2 py-1.5 text-sm last:border-0 ${
                          selected || previewCueIndex === c.index
                            ? 'bg-[var(--select-bg)]'
                            : 'hover:bg-[var(--bg)]'
                        } ${enablePipTimeline ? 'cursor-pointer' : ''}`}
                      >
                        {enablePipTimeline && (
                          <input
                            type="checkbox"
                            checked={selected}
                            onClick={(e) => e.stopPropagation()}
                            onChange={(e) => {
                              e.stopPropagation()
                              toggleCueSelection(c.index)
                            }}
                            className="shrink-0"
                          />
                        )}
                        <span className="w-5 shrink-0 text-center font-mono text-[10px] text-[var(--muted)]">
                          {c.index}
                        </span>
                        <input
                          type="number"
                          step={0.1}
                          min={0}
                          value={c.start}
                          onClick={(e) => e.stopPropagation()}
                          onChange={(e) =>
                            updateCueField(c.index, {
                              start: Math.max(0, Number(e.target.value) || 0),
                            })
                          }
                          onFocus={() => setPreviewCueIndex(c.index)}
                          className="w-14 rounded border border-[var(--border)] bg-[var(--bg)] px-1 py-0.5 font-mono text-[10px]"
                          title="开始秒"
                        />
                        <span className="text-[10px] text-[var(--muted)]">–</span>
                        <input
                          type="number"
                          step={0.1}
                          min={0}
                          value={c.end}
                          onClick={(e) => e.stopPropagation()}
                          onChange={(e) =>
                            updateCueField(c.index, {
                              end: Math.max(0, Number(e.target.value) || 0),
                            })
                          }
                          onFocus={() => setPreviewCueIndex(c.index)}
                          className="w-14 rounded border border-[var(--border)] bg-[var(--bg)] px-1 py-0.5 font-mono text-[10px]"
                          title="结束秒"
                        />
                        <input
                          type="text"
                          value={c.text}
                          onClick={(e) => e.stopPropagation()}
                          onChange={(e) => {
                            e.stopPropagation()
                            updateCueField(c.index, { text: e.target.value })
                          }}
                          onFocus={() => setPreviewCueIndex(c.index)}
                          className="min-w-[8rem] flex-1 rounded border border-[var(--border)] bg-[var(--bg)] px-1.5 py-0.5 text-xs text-[var(--text)]"
                        />
                        {cueHasPip(c.index) && (
                          <span className="shrink-0 rounded bg-violet-500/20 px-1.5 text-[10px] text-violet-300">
                            {(() => {
                              const hit = pipAssignments.find((p) =>
                                p.cue_indices.includes(c.index),
                              )
                              if (!hit) return 'PiP'
                              if (
                                hit.compose_mode === 'fusion' ||
                                FUSION_LAYOUT_IDS.has(
                                  String(hit.content_style || hit.scene_layout || ''),
                                )
                              )
                                return '融合'
                              if (hit.auto_hyperframe) return '覆盖'
                              return layoutMode === 'education' ? '讲解' : 'PiP'
                            })()}
                          </span>
                        )}
                      </div>
                    )
                  })}
                </>
              )}
            </div>

            {enablePipTimeline && selectedCueIndices.length > 0 && selectionRange && (
            <div className="space-y-2 rounded-lg border border-dashed border-[var(--border)] p-3">
              <p className="text-xs text-[var(--muted)]">
                已选 {selectedCueIndices.length} 条 · 区间{' '}
                <strong className="text-[var(--text)]">
                  {selectionRange.start.toFixed(1)}s – {selectionRange.end.toFixed(1)}s
                </strong>
                （{(selectionRange.end - selectionRange.start).toFixed(1)}s）
              </p>
              <div className="grid gap-3 sm:grid-cols-[1fr_auto]">
                <div className="space-y-2">
                  <div className="flex flex-wrap items-center gap-3">
                    <label className="text-xs text-[var(--muted)]">
                      图片显示
                      <input
                        type="range"
                        min={0.5}
                        max={Math.max(8, selectionRange.end - selectionRange.start + 4)}
                        step={0.1}
                        value={pendingDisplaySec}
                        onChange={(e) => setPendingDisplaySec(Number(e.target.value))}
                        className="ml-2 w-24 align-middle"
                      />
                      <span className="ml-1 text-[var(--accent)]">{pendingDisplaySec.toFixed(1)}s</span>
                    </label>
                    <label className="flex items-center gap-1.5 text-xs text-[var(--muted)]">
                      <input
                        type="checkbox"
                        checked={pendingPlayFull}
                        onChange={(e) => setPendingPlayFull(e.target.checked)}
                      />
                      视频全段播放（不截断到区间）
                    </label>
                  </div>
                  <p className="text-[10px] leading-relaxed text-[var(--muted)]">
                    上传素材时可调居中/全屏；「智能时间段场景 · 融合」会自动避让人脸定位，不使用下面的画中画槽位。
                  </p>
                  <div className="grid gap-2 sm:grid-cols-2">
                    <label className="block text-xs text-[var(--muted)]">
                      上传素材 · 位置
                      <select
                        value={normalizeContentPipPosition(contentPipPosition)}
                        onChange={(e) => {
                          const v = normalizeContentPipPosition(e.target.value)
                          setContentPipPosition(v)
                          if (v === 'fullscreen') setContentPipScale(1)
                          else if (contentPipScale >= 0.95) setContentPipScale(0.32)
                        }}
                        className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--panel)] px-2 py-1.5 text-xs"
                      >
                        {CONTENT_PIP_POSITIONS.map((p) => (
                          <option key={p.value} value={p.value}>
                            {p.label}
                          </option>
                        ))}
                      </select>
                    </label>
                    {normalizeContentPipPosition(contentPipPosition) !== 'fullscreen' && (
                      <label className="block text-xs text-[var(--muted)]">
                        上传素材 · 大小 {Math.round(contentPipScale * 100)}%
                        <input
                          type="range"
                          min={0.15}
                          max={0.55}
                          step={0.01}
                          value={contentPipScale}
                          onChange={(e) => setContentPipScale(Number(e.target.value))}
                          className="mt-1 w-full"
                        />
                      </label>
                    )}
                  </div>
                </div>
                <PipSlotPreview
                  position={normalizeContentPipPosition(contentPipPosition)}
                  scale={contentPipScale}
                  aspect={previewAspect}
                />
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <input
                  ref={pipInputRef}
                  type="file"
                  accept="image/*,video/*"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0]
                    if (f) void assignPipToSelection(f)
                    e.target.value = ''
                  }}
                />
                <button
                  type="button"
                  disabled={busy || selectedCueIndices.length === 0}
                  onClick={() => setAssetPickerOpen(true)}
                  className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs hover:bg-[var(--panel)] disabled:opacity-40"
                >
                  从素材中心选择
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => pipInputRef.current?.click()}
                  className="rounded-lg bg-violet-600 px-3 py-1.5 text-xs text-white hover:bg-violet-500 disabled:opacity-40"
                >
                  {layoutMode === 'education' ? '上传教学素材' : '上传画中画'}
                </button>
                <button
                  type="button"
                  disabled={busy || selectedCueIndices.length === 0}
                  onClick={openAiPipModal}
                  className="rounded-lg border border-[var(--accent)] bg-[var(--select-bg)] px-3 py-1.5 text-xs font-medium text-[var(--accent)] hover:brightness-110 disabled:opacity-40"
                >
                  智能时间段场景
                </button>
              </div>
            </div>
          )}

          {(() => {
            const visiblePip = pipAssignments
            if (visiblePip.length === 0) return null
            const stripItems = visiblePip.filter((p) => p.preview_url)
            return (
            <div className="space-y-2 rounded-xl border border-[var(--border)] bg-[var(--panel)] p-3">
              <p className="text-xs font-medium text-[var(--accent)]">
                {layoutMode === 'education' ? '讲解页 / 画中画列表' : '画中画列表'} ({visiblePip.length})
              </p>
              {stripItems.length > 0 && (
                <div className="space-y-1">
                  <p className="text-[10px] text-[var(--muted)]">
                    横向预览（{previewAspect}）· 点播放按钮后显示控件
                  </p>
                  <div className="flex gap-3 overflow-x-auto pb-1">
                    {stripItems.map((p) => (
                      <PipMediaCard
                        key={`card-${p.id}`}
                        url={p.preview_url!}
                        mediaType={p.media_type}
                        aspect={previewAspect}
                        label={`#${p.cue_indices.join(',')} ${p.auto_hyperframe ? 'AI' : p.media_type === 'image' ? '图' : '视频'}`}
                      />
                    ))}
                  </div>
                </div>
              )}
              {visiblePip.map((p) => (
                <div
                  key={p.id}
                  className={`rounded-lg border p-2 text-xs ${
                    editingPipId === p.id ? 'border-[var(--accent)] bg-[var(--select-bg)]' : 'border-[var(--border)]'
                  }`}
                >
                  <div className="flex items-start gap-2">
                    <button
                      type="button"
                      className="min-w-0 flex-1 text-left"
                      onClick={() => setEditingPipId(p.id)}
                    >
                      <span className="text-[var(--muted)]">
                        #{p.cue_indices.join(',')} · {p.start.toFixed(1)}–{p.end.toFixed(1)}s ·{' '}
                        {p.compose_mode === 'fusion' ||
                        FUSION_LAYOUT_IDS.has(String(p.content_style || p.scene_layout || ''))
                          ? '融合 · 全幅透明叠层'
                          : p.auto_hyperframe
                            ? '覆盖'
                            : p.media_type === 'image'
                              ? '图片'
                              : '视频'}
                        {!(
                          p.compose_mode === 'fusion' ||
                          FUSION_LAYOUT_IDS.has(String(p.content_style || p.scene_layout || ''))
                        ) && (
                          <>
                            ·{' '}
                            {CONTENT_PIP_POSITIONS.find(
                              (x) => x.value === normalizeContentPipPosition(p.position),
                            )?.label || '居中'}
                          </>
                        )}
                      </span>
                    </button>
                    <button
                      type="button"
                      title="删除此画中画"
                      className="shrink-0 rounded px-1.5 py-0.5 text-[10px] text-red-400 hover:bg-red-500/10"
                      onClick={() => void removePipAssignment(p)}
                    >
                      删
                    </button>
                  </div>
                  {editingPipId === p.id && (
                    <div className="mt-2 space-y-2">
                      {(p.compose_mode === 'fusion' ||
                        FUSION_LAYOUT_IDS.has(String(p.content_style || p.scene_layout || ''))) && (
                        <p className="text-[10px] text-[var(--muted)]">
                          融合层为全幅透明叠层（字号与预览一致），不使用画中画位置/大小。
                        </p>
                      )}
                      <div className="grid gap-2 sm:grid-cols-[1fr_auto]">
                        <div className="grid gap-2 sm:grid-cols-2">
                          {!(
                            p.compose_mode === 'fusion' ||
                            FUSION_LAYOUT_IDS.has(String(p.content_style || p.scene_layout || ''))
                          ) && (
                            <>
                          <label className="block text-[var(--muted)]">
                            画中画位置
                            <select
                              value={normalizeContentPipPosition(p.position)}
                              onChange={(e) => {
                                const v = normalizeContentPipPosition(e.target.value)
                                updatePip(p.id, {
                                  position: v,
                                  ...(v === 'fullscreen' ? { scale: 1 } : {}),
                                })
                              }}
                              className="mt-1 w-full rounded border border-[var(--border)] bg-[var(--bg)] px-2 py-1"
                            >
                              {CONTENT_PIP_POSITIONS.map((pos) => (
                                <option key={pos.value} value={pos.value}>
                                  {pos.label}
                                </option>
                              ))}
                            </select>
                          </label>
                          {normalizeContentPipPosition(p.position) !== 'fullscreen' && (
                            <label className="block text-[var(--muted)]">
                              画中画大小 {Math.round((p.scale ?? 0.32) * 100)}%
                              <input
                                type="range"
                                min={0.15}
                                max={0.55}
                                step={0.01}
                                value={p.scale ?? 0.32}
                                onChange={(e) => updatePip(p.id, { scale: Number(e.target.value) })}
                                className="mt-1 w-full"
                              />
                            </label>
                          )}
                            </>
                          )}
                          {p.media_type === 'image' ? (
                            <label className="block text-[var(--muted)] sm:col-span-2">
                              图片显示 {p.display_duration_sec.toFixed(1)}s
                              <input
                                type="range"
                                min={0.5}
                                max={12}
                                step={0.1}
                                value={p.display_duration_sec}
                                onChange={(e) =>
                                  updatePip(p.id, { display_duration_sec: Number(e.target.value) })
                                }
                                className="mt-1 w-full"
                              />
                            </label>
                          ) : (
                            <div className="space-y-2 sm:col-span-2">
                              <label className="block text-[var(--muted)]">
                                素材入点 {Number(p.source_start_sec || 0).toFixed(1)}s
                                <span className="ml-1 text-[10px] opacity-70">
                                  （默认 0 · 从该秒起截取填满字幕时段）
                                </span>
                                <input
                                  type="range"
                                  min={0}
                                  max={Math.max(
                                    0.1,
                                    (p.source_duration_sec ?? 120) -
                                      Math.max(0.5, p.end - p.start),
                                  )}
                                  step={0.1}
                                  value={p.source_start_sec ?? 0}
                                  onChange={(e) =>
                                    updatePip(p.id, { source_start_sec: Number(e.target.value) })
                                  }
                                  className="mt-1 w-full"
                                />
                              </label>
                              {p.preview_url && (
                                <video
                                  key={`${p.id}_${p.source_start_sec}`}
                                  src={p.preview_url}
                                  muted
                                  playsInline
                                  preload="metadata"
                                  className="mx-auto max-h-28 rounded border border-[var(--border)]"
                                  onLoadedMetadata={(e) => {
                                    const el = e.currentTarget
                                    const dur = Number.isFinite(el.duration) ? el.duration : null
                                    if (dur && dur !== p.source_duration_sec) {
                                      updatePip(p.id, { source_duration_sec: dur })
                                    }
                                    try {
                                      el.currentTime = Math.min(
                                        p.source_start_sec || 0,
                                        Math.max(0, (dur || 1) - 0.05),
                                      )
                                    } catch {
                                      /* ignore */
                                    }
                                  }}
                                />
                              )}
                              <label className="flex items-center gap-2 text-[var(--muted)]">
                                <input
                                  type="checkbox"
                                  checked={p.play_full_video}
                                  onChange={(e) =>
                                    updatePip(p.id, { play_full_video: e.target.checked })
                                  }
                                />
                                从入点起播完整段（不截断到字幕时长）
                              </label>
                            </div>
                          )}
                          {!p.auto_hyperframe && p.media_type === 'image' && (
                            <div className="flex flex-wrap items-center gap-2 sm:col-span-2">
                              <button
                                type="button"
                                disabled={pipCropBusy}
                                onClick={() => {
                                  setPipCropBusy(true)
                                  void api
                                    .publishPipFrame(session.path, p.media_path, 0)
                                    .then((r) => {
                                      setPipCropTargetId(p.id)
                                      setPipCropFrameUrl(mediaUrl(r.frame_path, Date.now()))
                                    })
                                    .catch((e) =>
                                      setLog(e instanceof Error ? e.message : String(e)),
                                    )
                                    .finally(() => setPipCropBusy(false))
                                }}
                                className="rounded border border-[var(--accent)] px-2 py-1 text-[11px] text-[var(--accent)]"
                              >
                                {pipCropBusy ? '加载中…' : '裁剪图片区域'}
                              </button>
                              {p.crop && (
                                <button
                                  type="button"
                                  onClick={() => updatePip(p.id, { crop: null })}
                                  className="text-[11px] text-[var(--muted)] underline"
                                >
                                  清除裁剪
                                </button>
                              )}
                              {p.crop && (
                                <span className="text-[10px] text-[var(--accent)]">已设裁剪框</span>
                              )}
                            </div>
                          )}
                          {!p.auto_hyperframe && p.media_type === 'video' && (
                            <p className="text-[10px] text-[var(--muted)] sm:col-span-2">
                              画中画视频仅按位置/大小等比缩放，不做画面裁剪；可用入点选择从哪一秒起播。
                            </p>
                          )}
                        </div>
                        <PipSlotPreview
                          position={normalizeContentPipPosition(p.position)}
                          scale={
                            normalizeContentPipPosition(p.position) === 'fullscreen'
                              ? 1
                              : (p.scale ?? 0.32)
                          }
                          aspect={previewAspect}
                        />
                      </div>
                      <button
                        type="button"
                        className="text-left text-red-400 hover:underline"
                        onClick={() => void removePipAssignment(p)}
                      >
                        删除此画中画{p.auto_hyperframe ? '（含生成文件）' : ''}
                      </button>
                    </div>
                  )}
                </div>
              ))}
            </div>
            )
          })()}

          </div>

          <div className="rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3">
            <label className="flex items-center gap-2 text-xs font-medium text-[var(--text)]">
              <input
                type="checkbox"
                checked={enableBgm}
                onChange={(e) => setEnableBgm(e.target.checked)}
              />
              背景音乐
            </label>
            {enableBgm && (
              <div className="mt-3 space-y-3">
                <div className="grid gap-3 sm:grid-cols-2">
                  <label className="block text-xs text-[var(--muted)]">
                    BGM 曲目（短视频 / 口播 / 我的上传）
                    <select
                      value={bgmId}
                      onChange={(e) => setBgmId(e.target.value)}
                      className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--panel)] px-2 py-2 text-sm"
                    >
                      {bgmTracks.length === 0 && <option value="hook_drop">爆款开场</option>}
                      {bgmTracks.map((t) => (
                        <option key={t.id} value={t.id} disabled={!t.ready}>
                          {t.from_asset
                            ? '[素材] '
                            : t.user
                              ? '[我的] '
                              : t.category
                                ? `[${t.category}] `
                                : ''}
                          {t.name} · {t.mood}
                          {!t.ready ? '（未下载）' : ''}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="block text-xs text-[var(--muted)]">
                    BGM 音量 {Math.round(bgmVolume * 100)}%（口播为主）
                    <input
                      type="range"
                      min={0.05}
                      max={0.45}
                      step={0.01}
                      value={bgmVolume}
                      onChange={(e) => setBgmVolume(Number(e.target.value))}
                      className="mt-1 w-full"
                    />
                  </label>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <input
                    ref={bgmFileRef}
                    type="file"
                    accept="audio/*,.mp3,.wav,.m4a,.aac,.ogg,.flac"
                    className="hidden"
                    onChange={(e) => {
                      const f = e.target.files?.[0]
                      e.target.value = ''
                      if (!f) return
                      setBgmUploadBusy(true)
                      void api
                        .bgmUpload(f, f.name.replace(/\.[^.]+$/, ''))
                        .then((row) => {
                          setBgmTracks((prev) => {
                            const rest = prev.filter((t) => t.id !== row.id)
                            return [{ ...row, ready: true, user: true }, ...rest]
                          })
                          setBgmId(row.id)
                          setBgmStart(0)
                        })
                        .catch((err) => {
                          window.alert(err instanceof Error ? err.message : String(err))
                        })
                        .finally(() => setBgmUploadBusy(false))
                    }}
                  />
                  <button
                    type="button"
                    disabled={bgmUploadBusy}
                    onClick={() => bgmFileRef.current?.click()}
                    className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs font-medium hover:bg-[var(--panel)] disabled:opacity-40"
                  >
                    {bgmUploadBusy ? '上传中…' : '上传我的 BGM'}
                  </button>
                  {activeBgm?.user && !activeBgm?.from_asset && (
                    <button
                      type="button"
                      className="rounded-lg border border-red-400/40 px-3 py-1.5 text-xs text-red-600 hover:bg-red-500/10"
                      onClick={() => {
                        if (!window.confirm(`删除上传曲目「${activeBgm.name}」？`)) return
                        void api
                          .bgmDelete(activeBgm.id)
                          .then(() => api.bgmLibrary())
                          .then((rows) => {
                            setBgmTracks(rows)
                            const next = rows.find((t) => t.ready)?.id || 'hook_drop'
                            setBgmId(next)
                          })
                          .catch((err) => {
                            window.alert(err instanceof Error ? err.message : String(err))
                          })
                      }}
                    >
                      删除此上传
                    </button>
                  )}
                  <span className="text-[10px] text-[var(--muted)]">
                    也可在素材中心「背景音乐 / 音频」上传；窗口切回后会自动刷新曲库
                  </span>
                </div>
                <div className="rounded-lg border border-dashed border-[var(--border)] px-3 py-2">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <label className="block flex-1 text-xs text-[var(--muted)]">
                      片段起点 {bgmStart.toFixed(1)}s
                      {activeBgm?.clip_start != null && activeBgm.clip_start > 0 && (
                        <span className="ml-1 text-[10px] text-[var(--muted)]">
                          （下载时已跳过前奏约 {activeBgm.clip_start}s）
                        </span>
                      )}
                      <input
                        type="range"
                        min={0}
                        max={bgmMaxStart}
                        step={0.5}
                        value={Math.min(bgmStart, bgmMaxStart)}
                        onChange={(e) => setBgmStart(Number(e.target.value))}
                        className="mt-1 w-full"
                      />
                    </label>
                    <button
                      type="button"
                      className="rounded-lg border border-[var(--border)] px-2 py-1 text-[10px] hover:bg-[var(--panel)]"
                      onClick={() => setBgmStart(0)}
                    >
                      从头播放
                    </button>
                  </div>
                  <p className="mt-1 text-[10px] text-[var(--muted)]">
                    拖动选择 BGM 入点；试听会从该秒开始。曲库为裁好的短视频片段，避免五六分钟长前奏。
                  </p>
                </div>
              </div>
            )}
            {enableBgm && bgmTracks.some((t) => t.source === 'generated') && (
              <p className="mt-2 text-[10px] text-[var(--warn-text)]">
                当前曲库为旧版合成音轨，音质较差。重启服务会自动下载真实 BGM，或运行：py -3.11 scripts/download_bgm.py --force
              </p>
            )}
            {enableBgm && (activeBgm?.local_path || activeBgm?.preview_url) && (
              <audio
                ref={bgmAudioRef}
                key={`${bgmId}-${bgmStart}`}
                className="mt-2 w-full"
                controls
                preload="auto"
                src={
                  playableUrl(activeBgm.preview_url, { localPath: activeBgm.local_path }) || undefined
                }
                onLoadedMetadata={(e) => {
                  e.currentTarget.currentTime = bgmStart
                }}
                onPlay={(e) => {
                  if (e.currentTarget.currentTime < bgmStart - 0.2) {
                    e.currentTarget.currentTime = bgmStart
                  }
                }}
              />
            )}
          </div>

          {layoutMode === 'education' && (
            <div className="mt-4 rounded-xl border border-[var(--info-border)] bg-[var(--info-bg)] px-3 py-2 text-xs text-[var(--info-text)]">
              当前成片风格：{styleSummary} · {layoutSummary} · {aspectSummary}
              <span className="ml-1 text-[var(--muted)]">（素材中心可「设为成片风格」）</span>
            </div>
          )}

          {layoutMode === 'short' && (
            <div className="mt-4 rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3 space-y-2">
              <p className="text-xs font-medium text-[var(--text)]">口播混剪</p>
              <p className="mt-1 text-[10px] leading-relaxed text-[var(--muted)]">
                口播为底；字幕用上方 Remotion 跟读。内容特效（透明玻璃 / 纯文字等融合层）在「画中画时间轴」勾选字幕后点「智能时间段场景」。
              </p>
              <label className="flex items-center gap-2 text-xs text-[var(--text)]">
                <input
                  type="checkbox"
                  checked={customCover}
                  onChange={(e) => {
                    const on = e.target.checked
                    setCustomCover(on)
                    if (on) setEditTab('cover')
                  }}
                />
                自定义封面（勾选后去设置；不勾选则成片时用默认抽帧封面）
              </label>
              {customCover && coverPath && (
                <p className="text-[10px] text-emerald-500">已保存自定义封面，将随一键成片嵌入</p>
              )}
            </div>
          )}

          {layoutMode === 'education' && (
            <div className="mt-3 rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3">
              <label className="flex items-center gap-2 text-xs text-[var(--text)]">
                <input
                  type="checkbox"
                  checked={customCover}
                  onChange={(e) => {
                    const on = e.target.checked
                    setCustomCover(on)
                    if (on) setEditTab('cover')
                  }}
                />
                自定义封面（勾选后去设置；不勾选则用默认封面）
              </label>
            </div>
          )}

          <div className="mt-4 flex flex-wrap items-center gap-2">
            <ActionBtn
              primary
              disabled={busy || cuesLoading || !(selectedLipsyncPath || session.lipsync_video) || cues.length === 0}
              onClick={() => oneClickFilm()}
            >
              {busy ? '一键成片中…' : autoPostAfter ? '一键成片并发布' : '一键成片'}
            </ActionBtn>
            {(enableSubtitles || enableBgm || pipAssignments.length > 0) && (
              <ActionBtn disabled={busy || cuesLoading} onClick={run}>
                导出成片
              </ActionBtn>
            )}
            <ActionBtn
              disabled={busy || cuesLoading}
              onClick={() => void resetMixWorkspace()}
            >
              重新混剪
            </ActionBtn>
            {busy && (
              <ActionBtn onClick={() => void cancelPublish()}>终止任务</ActionBtn>
            )}
            <span className="text-[10px] text-[var(--muted)]">
              一键成片会汇总当前字幕 / BGM / 画中画 / HyperFrames 等预设后再导出；「重新混剪」清空时间轴与智能场景，从头配置
            </span>
          </div>
          {progress && busy && (
            <div className="mt-3 rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3 py-2">
              <div className="mb-1 flex justify-between text-[10px] text-[var(--muted)]">
                <span className="truncate pr-2">{progress.msg || '字幕刻录中…'}</span>
                <span className="shrink-0">{Math.round(progress.pct * 100)}%</span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-[var(--panel)]">
                <div
                  className="h-full rounded-full bg-[var(--accent)] transition-all duration-300"
                  style={{ width: `${Math.max(3, progress.pct * 100)}%` }}
                />
              </div>
            </div>
          )}
            </div>
          )}

          {editTab === 'cover' && (
            <div className="mt-4 space-y-2">
              <p className="text-[11px] text-[var(--muted)]">
                勾选「自定义封面」后在此设置；保存后随一键成片嵌入。不勾选则用默认抽帧封面。
                切换到混剪等标签不会清空封面编辑（保持后台状态）。
              </p>
              <label className="flex items-center gap-2 text-xs text-[var(--text)]">
                <input
                  type="checkbox"
                  checked={customCover}
                  onChange={(e) => setCustomCover(e.target.checked)}
                />
                启用自定义封面
              </label>
              {!customCover && (
                <p className="rounded-xl border border-dashed border-[var(--border)] px-3 py-6 text-center text-xs text-[var(--muted)]">
                  未勾选自定义封面 · 一键成片将自动抽帧生成默认封面
                </p>
              )}
            </div>
          )}

          {customCover && (
            <div
              className={editTab === 'cover' ? 'mt-4 space-y-2' : 'hidden'}
              aria-hidden={editTab !== 'cover'}
            >
              <CoverEditor
                embedded
                sessionPath={session.path}
                aspect={publishAspect}
                previewVideo={selectedLipsyncPath || session.lipsync_video || session.preview_video}
                videoSources={[
                  ...(selectedLipsyncPath || session.lipsync_video
                    ? [
                        {
                          id: 'lipsync',
                          label: '口播成片',
                          path: (selectedLipsyncPath || session.lipsync_video) as string,
                        },
                      ]
                    : []),
                  ...(resultVideoPath
                    ? [{ id: 'publish', label: '发布成片', path: resultVideoPath }]
                    : []),
                ]}
                initialTitle={session.publish_title || coverTitle}
                initialSubtitle={session.publish_subtitle || ''}
                script={script}
                onCoverChange={setCoverPath}
                onPreviewBridge={setCoverPreview}
              />
            </div>
          )}

          {editTab === 'post' && (
            <div className="mt-4 space-y-3">
              <div className="rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3 space-y-3">
                <p className="text-xs font-medium text-[var(--text)]">自动发布</p>
                <p className="text-[10px] leading-relaxed text-[var(--muted)]">
                  可多选平台，按下方顺序依次打开发布页；未登录会引导登录，登录后自动继续。请在浏览器中最终确认发布。
                </p>
                <div className="space-y-2">
                  <p className="text-xs text-[var(--muted)]">平台（按选择顺序发布）</p>
                  <div className="flex flex-wrap gap-2">
                    {(publishPlatformOptions.length
                      ? publishPlatformOptions
                      : [
                          { id: 'douyin', name: '抖音', login_url: '' },
                          { id: 'kuaishou', name: '快手', login_url: '' },
                          { id: 'xiaohongshu', name: '小红书', login_url: '' },
                          { id: 'bilibili', name: 'B站', login_url: '' },
                        ]
                    ).map((p) => {
                      const checked = postPlatforms.includes(p.id)
                      return (
                        <label
                          key={p.id}
                          className={`inline-flex cursor-pointer items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs ${
                            checked
                              ? 'border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--text)]'
                              : 'border-[var(--border)] text-[var(--muted)]'
                          }`}
                        >
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() => togglePostPlatform(p.id)}
                          />
                          {p.name}
                        </label>
                      )
                    })}
                  </div>
                  {postPlatforms.length > 1 && (
                    <ol className="space-y-1 rounded-lg border border-[var(--border)] bg-[var(--panel)] p-2">
                      {postPlatforms.map((id, idx) => {
                        const name =
                          publishPlatformOptions.find((p) => p.id === id)?.name || id
                        return (
                          <li
                            key={id}
                            className="flex items-center justify-between gap-2 text-xs text-[var(--text)]"
                          >
                            <span>
                              {idx + 1}. {name}
                            </span>
                            <span className="flex gap-1">
                              <button
                                type="button"
                                className="rounded border border-[var(--border)] px-1.5 py-0.5 text-[10px] text-[var(--muted)] disabled:opacity-40"
                                disabled={idx === 0}
                                onClick={() => movePostPlatform(id, -1)}
                              >
                                上移
                              </button>
                              <button
                                type="button"
                                className="rounded border border-[var(--border)] px-1.5 py-0.5 text-[10px] text-[var(--muted)] disabled:opacity-40"
                                disabled={idx === postPlatforms.length - 1}
                                onClick={() => movePostPlatform(id, 1)}
                              >
                                下移
                              </button>
                            </span>
                          </li>
                        )
                      })}
                    </ol>
                  )}
                </div>
                <label className="block text-xs text-[var(--muted)]">
                  标题
                  <input
                    value={postTitle}
                    onChange={(e) => setPostTitle(e.target.value)}
                    className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--panel)] px-2 py-2 text-sm"
                    placeholder="自动从封面/文案生成"
                  />
                </label>
                <label className="block text-xs text-[var(--muted)]">
                  正文 / 文案
                  <textarea
                    value={postDesc}
                    onChange={(e) => setPostDesc(e.target.value)}
                    rows={4}
                    className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--panel)] px-2 py-2 text-sm"
                    placeholder="口播文案摘要"
                  />
                </label>
                <label className="block text-xs text-[var(--muted)]">
                  话题（空格或逗号分隔，最多 5 个）
                  <input
                    value={postTopics}
                    onChange={(e) => {
                      const raw = e.target.value
                      const parts = raw
                        .split(/[,，#\s]+/)
                        .map((t) => t.trim())
                        .filter(Boolean)
                      if (parts.length > 5) {
                        // Keep typing spaces/commas while capping tags
                        setPostTopics(parts.slice(0, 5).join(' '))
                        return
                      }
                      setPostTopics(raw)
                    }}
                    className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--panel)] px-2 py-2 text-sm"
                    placeholder="例如：干货分享 职场避坑（抖音等平台最多 5 个）"
                  />
                  <span className="mt-1 block text-[10px] text-[var(--muted)]">
                    已填{' '}
                    {
                      postTopics
                        .split(/[,，#\s]+/)
                        .map((t) => t.trim())
                        .filter(Boolean).length
                    }
                    /5 · 超过会被截断，避免创作者中心卡在选话题
                  </span>
                </label>
                {loginGuide && (
                  <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 space-y-2">
                    <p className="text-xs font-medium text-[var(--text)]">
                      未登录{loginGuide.platformName}
                    </p>
                    <p className="text-[10px] leading-relaxed text-[var(--muted)]">
                      请先登录，登录成功后将按顺序继续发布剩余平台
                      {loginGuide.remaining.length
                        ? `（${loginGuide.remaining
                            .map(
                              (id) =>
                                publishPlatformOptions.find((p) => p.id === id)?.name || id,
                            )
                            .join(' → ')}）`
                        : ''}
                      。
                    </p>
                    <div className="flex flex-wrap gap-2">
                      <ActionBtn
                        primary
                        disabled={loginBusy || postBusy}
                        onClick={() => void handleLoginAndContinue()}
                      >
                        {loginBusy ? '等待登录…' : `登录${loginGuide.platformName}并继续`}
                      </ActionBtn>
                      <ActionBtn
                        disabled={loginBusy || postBusy}
                        onClick={() => {
                          void (async () => {
                            setLoginBusy(true)
                            try {
                              const ok = await waitForPlatformLogin(loginGuide.platform, 5000)
                              if (!ok) {
                                setLog(`仍未检测到${loginGuide.platformName}登录，请先完成登录`)
                                return
                              }
                              const remaining = loginGuide.remaining
                              const videoPath = loginGuide.videoPath
                              setLoginGuide(null)
                              await runAutoPost(videoPath, remaining)
                            } finally {
                              setLoginBusy(false)
                            }
                          })()
                        }}
                      >
                        已登录，继续发布
                      </ActionBtn>
                      <ActionBtn disabled={loginBusy} onClick={() => setLoginGuide(null)}>
                        取消
                      </ActionBtn>
                    </div>
                  </div>
                )}
                <div className="flex flex-wrap gap-2">
                  <ActionBtn
                    onClick={async () => {
                      try {
                        const sug = await api.coverSuggest(script, session.path, true)
                        if (sug.ok) {
                          if (sug.title) setPostTitle(sug.title)
                          if (sug.description) setPostDesc(sug.description)
                          if (sug.topics?.length) setPostTopics(sug.topics.slice(0, 5).join(' '))
                          else if (sug.subtitle) setPostTopics((prev) => prev || sug.subtitle || '')
                          setLog(
                            sug.topics && sug.topics.length > 5
                              ? '已自动填写标题/简介/话题（话题已限制为 5 个）'
                              : '已根据文案自动填写标题/简介/话题',
                          )
                        } else setLog(sug.message || '自动填写失败')
                      } catch (e) {
                        setLog(e instanceof Error ? e.message : String(e))
                      }
                    }}
                  >
                    AI 自动填写
                  </ActionBtn>
                  <ActionBtn
                    primary
                    disabled={postBusy || loginBusy || !(resultVideoPath || resultVideo)}
                    onClick={() => void runAutoPost(resultVideoPath)}
                  >
                    {postBusy
                      ? '发布中…'
                      : postPlatforms.length > 1
                        ? `按序发布（${postPlatforms.length}）`
                        : '立即发布到平台'}
                  </ActionBtn>
                </div>
                <label className="flex items-center gap-2 text-xs text-[var(--text)]">
                  <input
                    type="checkbox"
                    checked={autoPostAfter}
                    onChange={(e) => setAutoPostAfter(e.target.checked)}
                  />
                  一键成片完成后自动按序发布
                </label>
              </div>
            </div>
          )}

          {log && (
            <pre className="mt-3 max-h-40 overflow-auto rounded-xl bg-[var(--bg)] p-3 text-xs text-[var(--muted)]">
              {log}
            </pre>
          )}
        </Panel>

        <PhonePreviewColumn aspect={previewAspect}>
          {editTab === 'subtitle' && (
            <>
              <div className="mb-2 flex rounded-lg border border-[var(--border)] bg-[var(--bg)] p-0.5">
                <button
                  type="button"
                  onClick={() => setRightPreviewTab('mix')}
                  className={`flex-1 rounded-md px-2 py-1.5 text-[11px] font-medium transition ${
                    rightPreviewTab === 'mix'
                      ? 'bg-[var(--select-bg)] text-[var(--accent)]'
                      : 'text-[var(--muted)] hover:text-[var(--text)]'
                  }`}
                >
                  混剪预览
                </button>
                <button
                  type="button"
                  onClick={() => setRightPreviewTab('lipsync')}
                  disabled={!lipsyncPreviewUrl}
                  className={`flex-1 rounded-md px-2 py-1.5 text-[11px] font-medium transition disabled:opacity-40 ${
                    rightPreviewTab === 'lipsync'
                      ? 'bg-[var(--select-bg)] text-[var(--accent)]'
                      : 'text-[var(--muted)] hover:text-[var(--text)]'
                  }`}
                >
                  口播原片
                </button>
              </div>
              {rightPreviewTab === 'lipsync' ? (
                <PhonePreviewSlot
                  aspect="9:16"
                  label="数字人口播"
                  note={
                    lipsyncTakes.length > 0
                      ? `当前发布源 · 导出 ${publishAspect === 'landscape_16_9' ? '16:9' : '9:16'} · 预览框固定 9:16`
                      : '横屏素材在 9:16 框内宽度铺满、高度自适应'
                  }
                  onExpand={
                    lipsyncPreviewUrl
                      ? () => {
                          setVideoTheaterTitle('口播原片 · 应用内全屏')
                          setVideoTheaterSrc(lipsyncPreviewUrl)
                        }
                      : undefined
                  }
                >
                  {lipsyncPreviewUrl ? (
                    <PhoneFitVideo key={lipsyncPreviewUrl} src={lipsyncPreviewUrl} controls preload="auto" />
                  ) : (
                    <div className="absolute inset-0 flex items-center justify-center px-3 text-center text-xs text-[var(--muted)]">
                      暂无口播视频
                    </div>
                  )}
                </PhonePreviewSlot>
              ) : (
            <PhonePreviewSlot
              aspect={previewAspect}
              onExpand={
                subtitlePreviewUrl ? () => setPreviewLightboxOpen(true) : undefined
              }
              label={
                enableSubtitles
                  ? hfRemotionTheme !== 'off'
                    ? previewCue
                      ? `Remotion 烧录 · 第 ${previewCue.index} 条`
                      : 'Remotion 烧录预览'
                    : layoutMode === 'education'
                      ? previewCue
                        ? `字幕预览 · 第 ${previewCue.index} 条`
                        : '字幕预览'
                      : previewCue
                        ? `字幕烧录 · 第 ${previewCue.index} 条`
                        : '字幕烧录预览'
                  : layoutMode === 'education'
                    ? '网课布局预览（无字幕）'
                    : '布局预览（无字幕）'
              }
              note={
                subtitlePreviewStale
                  ? subtitlePreviewUrl
                    ? '参数已变 · 点击下方「生成混剪预览」'
                    : '点击下方「生成混剪预览」查看布局与字幕'
                  : subtitlePreviewNote
              }
            >
              {!enableSubtitles && !subtitlePreviewUrl && !subtitlePreviewLoading ? (
                <div className="absolute inset-0 flex items-center justify-center bg-[#141820]/90 px-3 text-center text-xs text-[var(--muted)]">
                  未勾选烧录字幕 · 仅布局预览
                </div>
              ) : subtitlePreviewLoading ? (
                <div className="absolute inset-0 flex items-center justify-center bg-[#141820]/90 px-3 text-center text-xs text-[var(--muted)]">
                  合成混剪预览…
                </div>
              ) : subtitlePreviewUrl ? (
                <img
                  src={subtitlePreviewUrl}
                  alt="发布预览"
                  className={`absolute inset-0 h-full w-full object-contain bg-[#141820] ${
                    subtitlePreviewStale ? 'opacity-55' : ''
                  }`}
                />
              ) : (
                <div className="absolute inset-0 flex items-center justify-center bg-[#141820]/90 px-3 text-center text-xs text-[var(--muted)]">
                  调整字幕 / 画中画 / 字号后，点击下方「生成混剪预览」
                </div>
              )}
            </PhonePreviewSlot>
              )}
            </>
          )}

          {editTab === 'subtitle' && rightPreviewTab === 'mix' && (
              <button
                type="button"
                disabled={subtitlePreviewLoading || !session.path}
                onClick={() => void refreshSubtitlePreview()}
                className="mt-2 w-full rounded-xl border border-[var(--accent)] bg-[var(--select-bg)] px-3 py-2.5 text-sm font-medium text-[var(--accent)] transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {subtitlePreviewLoading
                  ? '正在生成预览…'
                  : subtitlePreviewStale || !subtitlePreviewUrl
                    ? '生成混剪预览'
                    : '重新生成混剪预览'}
              </button>
            )}

          {editTab === 'cover' && coverPreview && (
            <PhonePreviewSlot
              aspect={publishAspect === 'landscape_16_9' ? '16:9' : '9:16'}
              label="封面编辑预览"
            >
              <CoverPreviewCanvas {...coverPreview} />
            </PhonePreviewSlot>
          )}

          {resultVideo && (
            <PhonePreviewSlot
              aspect="9:16"
              label="发布后成片"
              onExpand={() => {
                setVideoTheaterTitle('发布成片 · 应用内全屏')
                setVideoTheaterSrc(resultVideo)
              }}
            >
              <PhoneFitVideo src={resultVideo} controls preload="auto" />
            </PhonePreviewSlot>
          )}
        </PhonePreviewColumn>
      </div>

      <AssetPickerModal
        open={assetPickerOpen}
        onClose={() => setAssetPickerOpen(false)}
        onPick={(asset) => void assignPipFromLibrary(asset)}
      />

      {fullFilmConfirmOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--panel)] p-4 shadow-xl">
            <p className="text-sm font-medium text-[var(--text)]">一键成片 · 确认当前预设</p>
            <p className="mt-1 text-[10px] text-[var(--muted)]">
              将按下列已开启功能导出成片（不会强制打开 HyperFrames）。可先返回勾选字幕 / BGM / 画中画等再导出。
            </p>
            <ul className="mt-3 max-h-[50vh] space-y-1.5 overflow-auto rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3">
              {oneClickPresetRows.map((row) => (
                <li
                  key={row.label}
                  className="flex items-start justify-between gap-3 text-xs"
                >
                  <span className="shrink-0 text-[var(--muted)]">{row.label}</span>
                  <span
                    className={`min-w-0 text-right ${
                      row.on ? 'text-[var(--text)]' : 'text-[var(--muted)]'
                    }`}
                  >
                    {row.on ? '✓ ' : '○ '}
                    {row.value}
                  </span>
                </li>
              ))}
            </ul>
            {oneClickHasWeakPresets && (
              <p className="mt-2 text-[10px] leading-relaxed text-amber-400/90">
                当前几乎未开启扩展功能，成片将主要是口播布局。若只要预览场景，请用「智能时间段场景」；正式成片建议勾选字幕 / BGM / 画中画或 HyperFrames。
              </p>
            )}
            {hyperframesConsent && layoutMode === 'education' && (
              <button
                type="button"
                className="mt-2 text-[10px] text-[var(--accent)] underline"
                onClick={openOneClickStylePicker}
              >
                先修改 HyperFrames 版式再导出
              </button>
            )}
            <div className="mt-4 flex justify-end gap-2">
              <ActionBtn onClick={() => setFullFilmConfirmOpen(false)}>返回调整</ActionBtn>
              <ActionBtn primary onClick={confirmOneClickExport}>
                确认按预设导出
              </ActionBtn>
            </div>
          </div>
        </div>
      )}

      {styleModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="max-h-[90vh] w-full max-w-2xl overflow-auto rounded-2xl border border-[var(--border)] bg-[var(--panel)] p-4 shadow-xl">
            <div className="mb-3 flex items-start justify-between gap-3">
              <div>
                <p className="text-sm font-medium text-[var(--text)]">
                  {styleModalModeRef.current === 'pip_ai' ? '智能时间段场景' : '一键成片 · 场景风格'}
                </p>
                <p className="mt-1 text-[10px] text-[var(--muted)]">
                  {styleModalModeRef.current === 'pip_ai'
                    ? `范围：已选 ${Array.isArray(oneClickTargetRef.current) ? oneClickTargetRef.current.length : 0} 条 · 内容特效（非字幕 Remotion）`
                    : oneClickTargetRef.current === 'all'
                      ? '范围：未勾选时间轴 · 导出时不会生成 HyperFrames'
                      : `范围：已选 ${Array.isArray(oneClickTargetRef.current) ? oneClickTargetRef.current.length : 0} 条 · 可智能或手动指定版式`}
                </p>
              </div>
              <button
                type="button"
                className="text-xs text-[var(--muted)] underline"
                onClick={() => setStyleModalOpen(false)}
              >
                关闭
              </button>
            </div>

            {styleModalModeRef.current === 'pip_ai' && (
              <div className="mb-3 space-y-2 rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3">
                <p className="text-[11px] font-medium text-[var(--text)]">合成方式</p>
                <div className="flex flex-wrap gap-3 text-xs text-[var(--text)]">
                  <label className="flex items-center gap-1.5">
                    <input
                      type="radio"
                      name="compose_mode"
                      checked={composeMode === 'fusion'}
                      onChange={() => {
                        setComposeMode('fusion')
                        setHyperframesLayout('glass_card')
                        setHfSmartLayout(false)
                        setHfSmartBg(false)
                        setHfBgMode('transparent')
                        setHfMoreOpen(true)
                      }}
                    />
                    原视频融合
                    <span className="text-[10px] text-[var(--muted)]">（透明叠回口播）</span>
                  </label>
                  <label className="flex items-center gap-1.5">
                    <input
                      type="radio"
                      name="compose_mode"
                      checked={composeMode === 'cover'}
                      onChange={() => {
                        setComposeMode('cover')
                        setHyperframesLayout('kinetic')
                        setHfSmartLayout(true)
                        setHfSmartBg(true)
                        if (hfBgMode === 'transparent') setHfBgMode('generative')
                        if (Array.isArray(oneClickTargetRef.current)) {
                          void refreshHfSuggest(oneClickTargetRef.current)
                        }
                      }}
                    />
                    主体画中画覆盖
                    <span className="text-[10px] text-[var(--muted)]">
                      （网课默认；口播角窗置顶）
                    </span>
                  </label>
                </div>
                {composeMode === 'fusion' && (
                  <p className="pt-1 text-[10px] text-[var(--muted)]">
                    融合定位：自动避让人脸（成片时探测）；此处无需选手动画中画槽位。
                  </p>
                )}
              </div>
            )}

            <div className="space-y-2 rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3">
              <p className="text-[11px] font-medium text-[var(--text)]">智能选项（默认开启）</p>
              <div className="grid gap-2 sm:grid-cols-2">
                <label className="flex items-center gap-2 text-xs text-[var(--muted)]">
                  <input
                    type="checkbox"
                    checked={hfSmartLayout}
                    onChange={(e) => {
                      setHfSmartLayout(e.target.checked)
                      if (e.target.checked && Array.isArray(oneClickTargetRef.current)) {
                        void refreshHfSuggest(oneClickTargetRef.current)
                      }
                    }}
                  />
                  智能判断场景版式
                </label>
                <label className="flex items-center gap-2 text-xs text-[var(--muted)]">
                  <input
                    type="checkbox"
                    checked={hfSmartTheme}
                    onChange={(e) => {
                      setHfSmartTheme(e.target.checked)
                      if (e.target.checked && Array.isArray(oneClickTargetRef.current)) {
                        void refreshHfSuggest(oneClickTargetRef.current)
                      }
                    }}
                  />
                  智能选择配色主题
                </label>
                <label className="flex items-center gap-2 text-xs text-[var(--muted)]">
                  <input
                    type="checkbox"
                    checked={hfSmartKeywords}
                    onChange={(e) => setHfSmartKeywords(e.target.checked)}
                  />
                  关键字自动改色
                </label>
                <label
                  className={`flex items-center gap-2 text-xs ${
                    composeMode === 'fusion' && styleModalModeRef.current === 'pip_ai'
                      ? 'text-[var(--muted)]/50'
                      : 'text-[var(--muted)]'
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={composeMode === 'fusion' && styleModalModeRef.current === 'pip_ai' ? false : hfSmartBg}
                    disabled={composeMode === 'fusion' && styleModalModeRef.current === 'pip_ai'}
                    onChange={(e) => setHfSmartBg(e.target.checked)}
                  />
                  自动场景背景
                  {composeMode === 'fusion' && styleModalModeRef.current === 'pip_ai' && (
                    <span className="text-[10px]">（融合固定透明底）</span>
                  )}
                </label>
              </div>
              <div className="mt-3 border-t border-[var(--border)] pt-3">
                {composeMode === 'fusion' && styleModalModeRef.current === 'pip_ai' ? (
                  <p className="text-[10px] text-[var(--muted)]">
                    融合模式：黑底抠透明，仅渲染玻璃/纯文字层；配色主题仍可用。
                  </p>
                ) : (
                  <StylePackFields
                    fonts={hfFonts}
                    bgModes={hfBgModes}
                    fontId={hfFontId}
                    fontScale={hfFontScale}
                    bgMode={hfBgMode}
                    bgPrompt={hfBgPrompt}
                    onFontId={setHfFontId}
                    onFontScale={setHfFontScale}
                    onBgMode={setHfBgMode}
                    onBgPrompt={setHfBgPrompt}
                    compact
                  />
                )}
              </div>
              <p className="text-[10px] leading-relaxed text-[var(--muted)]">
                {hfSuggestBusy
                  ? '正在根据字幕智能推荐…'
                  : `当前：${layoutSummary} · ${styleSummary} · ${hfFontId} · ${hfBgMode}${
                      hfSuggestReasons.length ? ` · ${hfSuggestReasons.slice(0, 2).join('；')}` : ''
                    }`}
              </p>
              <p className="text-[10px] text-[var(--muted)]">
                与素材中心共用 Style Pack。已有场景可点「仅换肤重渲」，无需重选字幕。
                {styleModalModeRef.current === 'pip_ai' && composeMode === 'cover' && (
                  <> 展开下方「更多」后手动点击「生成场景预览」，字号滑块才会反映在预览里。</>
                )}
              </p>
            </div>

            <div className="mt-3">
              <button
                type="button"
                className="text-xs text-[var(--accent)] underline"
                onClick={() => setHfMoreOpen((v) => !v)}
              >
                {hfMoreOpen ? '收起更多（手动选择）' : '更多 · 手动选择版式 / 主题 / 画幅'}
              </button>
              {hfMoreOpen && (
                <div className="mt-2 rounded-xl border border-dashed border-[var(--border)] p-3">
                  <p className="mb-2 text-[10px] text-[var(--muted)]">
                    手动选择会覆盖对应智能项：改版式会关闭智能版式，改主题会关闭智能配色。
                  </p>
                  <HyperFrameThemePicker
                    themes={hfThemes}
                    layouts={
                      styleModalModeRef.current === 'pip_ai' ? modalLayouts : hfLayouts
                    }
                    aspects={hfAspects}
                    value={hyperframesTheme}
                    onChange={(id) => {
                      setHyperframesTheme(id)
                      setHfSmartTheme(false)
                    }}
                    layout={hyperframesLayout}
                    onLayoutChange={(id) => {
                      setHyperframesLayout(id)
                      setHfSmartLayout(false)
                      if (FUSION_LAYOUT_IDS.has(id)) setComposeMode('fusion')
                    }}
                    aspect={hyperframesAspect}
                    onAspectChange={(id) => {
                      setHyperframesAspect(id)
                      setPublishAspect(id)
                    }}
                    previewText={
                      previewCue?.text ||
                      cues
                        .filter((c) => selectedCueIndices.includes(c.index))
                        .slice(0, 3)
                        .map((c) => c.text)
                        .join(' ') ||
                      script.slice(0, 160) ||
                      'HyperFrames 场景预览'
                    }
                    fontScale={hfFontScale}
                    composeMode={
                      styleModalModeRef.current === 'pip_ai' ? composeMode : ''
                    }
                    manualPreview={styleModalModeRef.current === 'pip_ai'}
                  />
                </div>
              )}
            </div>

            <div className="mt-4 flex flex-wrap justify-end gap-2">
              <ActionBtn onClick={() => setStyleModalOpen(false)}>取消</ActionBtn>
              {styleModalModeRef.current === 'pip_ai' &&
                pipAssignments.some((p) => p.auto_hyperframe) && (
                  <ActionBtn onClick={() => void restyleExistingScenes()}>仅换肤重渲</ActionBtn>
                )}
              <ActionBtn primary onClick={confirmStyleAndExport}>
                {styleModalModeRef.current === 'pip_ai'
                  ? '确认并生成时间段场景'
                  : '确认并导出成片'}
              </ActionBtn>
            </div>
          </div>
        </div>
      )}

      <LecturerCropModal
        open={lecturerCropModalOpen}
        frameUrl={lecturerCropFrameUrl}
        initialCrop={lecturerCrop}
        busy={lecturerCropBusy}
        onClose={() => setLecturerCropModalOpen(false)}
        onAuto={() => autoDetectLecturerCropInModal()}
        onConfirm={(crop, previewDataUrl) => {
          setLecturerCrop(crop)
          setLecturerCropPreview(previewDataUrl)
          setLecturerCropModalOpen(false)
          setLog('已确认口播 1:1 裁切区域（预览/导出将使用该区域）')
        }}
      />

      <LecturerCropModal
        open={!!pipCropTargetId && !!pipCropFrameUrl}
        frameUrl={pipCropFrameUrl}
        initialCrop={
          pipCropTargetId
            ? pipAssignments.find((x) => x.id === pipCropTargetId)?.crop ?? null
            : null
        }
        busy={pipCropBusy}
        onClose={() => {
          setPipCropTargetId(null)
          setPipCropFrameUrl(null)
        }}
        onAuto={async () => null}
        onConfirm={(crop) => {
          if (pipCropTargetId) updatePip(pipCropTargetId, { crop })
          setPipCropTargetId(null)
          setPipCropFrameUrl(null)
          setLog('已确认画中画裁剪区域')
        }}
      />

      {previewLightboxOpen && subtitlePreviewUrl && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/75 p-4">
          <div className="relative max-h-[92vh] max-w-[min(96vw,960px)] overflow-auto rounded-2xl border border-[var(--border)] bg-[#141820] p-2 shadow-xl">
            <button
              type="button"
              className="absolute right-3 top-3 z-10 rounded-lg bg-black/50 px-2 py-1 text-xs text-white underline"
              onClick={() => setPreviewLightboxOpen(false)}
            >
              关闭
            </button>
            <img
              src={subtitlePreviewUrl}
              alt="预览放大"
              className={`mx-auto max-h-[88vh] w-auto object-contain ${
                previewAspect === '16:9' ? 'max-w-full' : 'max-w-[min(100%,420px)]'
              }`}
            />
          </div>
        </div>
      )}

      <InAppVideoTheater
        open={!!videoTheaterSrc}
        src={videoTheaterSrc || ''}
        title={videoTheaterTitle}
        onClose={() => setVideoTheaterSrc(null)}
      />
    </div>
  )
}

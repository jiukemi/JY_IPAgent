import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { api, mediaUrl } from '../api/client'
import type { CoverLayer, CoverSubject, CoverTemplate } from '../types'
import { ActionBtn, Panel } from '../pages/ScriptPage'
import { AssetPickerModal, type PickerAsset } from './AssetPickerModal'
import { CoverFramePickerModal } from './CoverFramePickerModal'
import { useJobQueue } from '../context/JobQueueContext'

function coverImageDisplaySrc(src: string | null | undefined): string | null {
  const s = (src || '').trim()
  if (!s) return null
  if (/^https?:\/\//i.test(s)) return s
  return mediaUrl(s)
}

/** Static border + glowing dash flush on the input edge (no gap). */
function CoverFieldNudge({ active, children }: { active: boolean; children: React.ReactNode }) {
  const ref = useRef<HTMLDivElement>(null)
  const [box, setBox] = useState({ w: 0, h: 0 })
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const measure = () => {
      const r = el.getBoundingClientRect()
      setBox({ w: Math.max(1, Math.round(r.width)), h: Math.max(1, Math.round(r.height)) })
    }
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  // Match Tailwind rounded-lg (8px). Stroke centered on the element edge.
  const stroke = 2
  const rx = 8
  const inset = stroke / 2
  return (
    <div ref={ref} className={`cover-field-nudge${active ? ' is-active' : ''}`}>
      {children}
      {active && box.w > 0 && (
        <svg
          className="cover-field-nudge-svg"
          aria-hidden
          width={box.w}
          height={box.h}
          viewBox={`0 0 ${box.w} ${box.h}`}
        >
          <rect
            className="cover-field-nudge-track"
            x={inset}
            y={inset}
            width={box.w - stroke}
            height={box.h - stroke}
            rx={rx}
            pathLength={100}
          />
          <rect
            className="cover-field-nudge-glow"
            x={inset}
            y={inset}
            width={box.w - stroke}
            height={box.h - stroke}
            rx={rx}
            pathLength={100}
          />
        </svg>
      )}
    </div>
  )
}

type CoverVideoSource = { id: string; label: string; path: string }

type Props = {
  sessionPath: string
  previewVideo?: string | null
  /** Optional finished videos (lipsync / publish) for frame pick */
  videoSources?: CoverVideoSource[]
  /** Follow publish aspect: portrait_9_16 (default) or landscape_16_9 */
  aspect?: string
  initialTitle?: string
  initialSubtitle?: string
  script?: string
  onCoverChange?: (path: string | null) => void
  /** 嵌入 05 发布页：编辑区占满左侧，预览交给右侧手机栏 */
  embedded?: boolean
  onPreviewBridge?: (bridge: CoverPreviewBridge) => void
}

export type CutoutPreviewAssets = {
  bgUrl: string
  stickerUrl: string
  stickerWRatio: number
  stickerHRatio: number
  preparedFill: number
}

export type CoverPreviewBridge = {
  active: CoverTemplate
  title: string
  subtitle: string
  baseBg: string | null
  framePath: string | null
  selectedLayerId: string | null
  onSelectLayer: (id: string) => void
  patchLayer: (id: string, partial: Partial<CoverLayer>) => void
  patchSubject?: (partial: Partial<CoverSubject>) => void
  /** Render & persist cover image; returns absolute path */
  saveCover: () => Promise<string | null>
  /** Interactive cutout: blurred bg + draggable sticker */
  cutoutAssets?: CutoutPreviewAssets | null
  cutoutPreparing?: boolean
  /** portrait_9_16 | landscape_16_9 */
  aspect?: string
}

const SUBJECT_LAYER_ID = '__cover_subject__'

export function CoverPreviewCanvas({
  active,
  title,
  subtitle,
  baseBg,
  selectedLayerId,
  onSelectLayer,
  patchLayer,
  patchSubject,
  cutoutAssets = null,
  cutoutPreparing = false,
}: CoverPreviewBridge) {
  const canvasRef = useRef<HTMLDivElement>(null)
  const dragRef = useRef<{
    mode: 'move' | 'resize' | 'subject-move' | 'subject-resize'
    corner?: 'nw' | 'ne' | 'sw' | 'se'
    layerId: string
    startX: number
    startY: number
    origX: number
    origY: number
    origFont: number
    origMaxW: number
    origBand: number
    origWidthRatio: number
    origFill?: number
  } | null>(null)
  const patchLayerRef = useRef(patchLayer)
  const patchSubjectRef = useRef(patchSubject)
  const activeRef = useRef(active)
  const cutoutAssetsRef = useRef(cutoutAssets)
  const [canvasH, setCanvasH] = useState(462)
  /** 拖拽时本地即时预览，避免等父组件 bridge 回传才刷新 */
  const [liveSubject, setLiveSubject] = useState<{
    x_offset: number
    y_offset: number
    fill_ratio: number
  } | null>(null)

  useEffect(() => {
    patchLayerRef.current = patchLayer
  }, [patchLayer])

  useEffect(() => {
    patchSubjectRef.current = patchSubject
  }, [patchSubject])

  useEffect(() => {
    activeRef.current = active
  }, [active])

  useEffect(() => {
    cutoutAssetsRef.current = cutoutAssets
  }, [cutoutAssets])

  useEffect(() => {
    const el = canvasRef.current
    if (!el) return
    const sync = () => setCanvasH(el.clientHeight || 462)
    sync()
    const ro = new ResizeObserver(sync)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const beginDrag = (
    clientX: number,
    clientY: number,
    layerId: string,
    mode: 'move' | 'resize',
    corner?: 'nw' | 'ne' | 'sw' | 'se',
  ) => {
    const layer = activeRef.current.layers.find((l) => l.id === layerId)
    if (!layer) return
    dragRef.current = {
      mode,
      corner,
      layerId,
      startX: clientX,
      startY: clientY,
      origX: layer.x,
      origY: layer.y,
      origFont: layer.font_size_ratio || 0.048,
      origMaxW: layer.max_width_ratio || 0.86,
      origBand: layer.band_height_ratio || 0.12,
      origWidthRatio: layer.width_ratio ?? 0.2,
    }
  }

  const beginSubjectDrag = (
    clientX: number,
    clientY: number,
    mode: 'subject-move' | 'subject-resize',
    corner?: 'nw' | 'ne' | 'sw' | 'se',
  ) => {
    const sub = activeRef.current.subject
    if (!sub?.enabled) return
    dragRef.current = {
      mode,
      corner,
      layerId: SUBJECT_LAYER_ID,
      startX: clientX,
      startY: clientY,
      origX: sub.x_offset ?? -0.06,
      origY: sub.y_offset ?? 0.08,
      origFont: 0,
      origMaxW: 0,
      origBand: 0,
      origWidthRatio: 0,
      origFill: sub.fill_ratio ?? 0.5,
    }
  }

  const onCanvasMouseDown = (e: React.MouseEvent, layerId: string) => {
    e.preventDefault()
    e.stopPropagation()
    onSelectLayer(layerId)
    beginDrag(e.clientX, e.clientY, layerId, 'move')
  }

  const onCanvasTouchStart = (e: React.TouchEvent, layerId: string) => {
    const t = e.touches[0]
    if (!t) return
    e.stopPropagation()
    onSelectLayer(layerId)
    beginDrag(t.clientX, t.clientY, layerId, 'move')
  }

  const onResizeMouseDown = (
    e: React.MouseEvent,
    layerId: string,
    corner: 'nw' | 'ne' | 'sw' | 'se',
  ) => {
    e.preventDefault()
    e.stopPropagation()
    onSelectLayer(layerId)
    beginDrag(e.clientX, e.clientY, layerId, 'resize', corner)
  }

  useEffect(() => {
    const applyDelta = (clientX: number, clientY: number) => {
      const d = dragRef.current
      if (!d || !canvasRef.current) return
      const rect = canvasRef.current.getBoundingClientRect()
      if (rect.width <= 0 || rect.height <= 0) return
      const dx = (clientX - d.startX) / rect.width
      const dy = (clientY - d.startY) / rect.height
      if (d.mode === 'subject-move') {
        const next = {
          x_offset: Math.max(-0.25, Math.min(0.25, d.origX + dx)),
          y_offset: Math.max(-0.15, Math.min(0.2, d.origY + dy)),
          fill_ratio: d.origFill ?? activeRef.current.subject?.fill_ratio ?? 0.5,
        }
        setLiveSubject(next)
        patchSubjectRef.current?.({
          x_offset: next.x_offset,
          y_offset: next.y_offset,
        })
        return
      }
      if (d.mode === 'subject-resize') {
        const sx = d.corner === 'ne' || d.corner === 'se' ? 1 : -1
        const sy = d.corner === 'sw' || d.corner === 'se' ? 1 : -1
        const delta = sx * dx * 0.55 + sy * dy * 0.55
        const fill = Math.max(0.28, Math.min(0.85, (d.origFill ?? 0.5) + delta))
        const next = {
          x_offset: d.origX,
          y_offset: d.origY,
          fill_ratio: fill,
        }
        setLiveSubject(next)
        patchSubjectRef.current?.({ fill_ratio: fill })
        return
      }
      if (d.mode === 'move') {
        patchLayerRef.current(d.layerId, {
          x: Math.max(0, Math.min(1, d.origX + dx)),
          y: Math.max(0, Math.min(1, d.origY + dy)),
        })
        return
      }
      // resize: 只改展示区域（宽/高），字号由滑条单独控制
      const sx = d.corner === 'ne' || d.corner === 'se' ? 1 : -1
      const sy = d.corner === 'sw' || d.corner === 'se' ? 1 : -1
      const layer = activeRef.current.layers.find((l) => l.id === d.layerId)
      if (layer?.type === 'image') {
        const delta = sx * dx * 0.55 + sy * dy * 0.55
        patchLayerRef.current(d.layerId, {
          width_ratio: Math.max(0.05, Math.min(1, d.origWidthRatio + delta)),
        })
        return
      }
      patchLayerRef.current(d.layerId, {
        max_width_ratio: Math.max(0.12, Math.min(1, d.origMaxW + sx * dx)),
        band_height_ratio: Math.max(0.04, Math.min(0.7, d.origBand + sy * dy)),
      })
    }
    const onMove = (e: MouseEvent) => applyDelta(e.clientX, e.clientY)
    const onUp = () => {
      dragRef.current = null
      setLiveSubject(null)
    }
    const onTouchMove = (e: TouchEvent) => {
      if (!dragRef.current) return
      const t = e.touches[0]
      if (!t) return
      e.preventDefault()
      applyDelta(t.clientX, t.clientY)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    window.addEventListener('touchmove', onTouchMove, { passive: false })
    window.addEventListener('touchend', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
      window.removeEventListener('touchmove', onTouchMove)
      window.removeEventListener('touchend', onUp)
    }
  }, [])

  const handleBox = (corner: 'nw' | 'ne' | 'sw' | 'se') => {
    const pos: Record<string, React.CSSProperties> = {
      nw: { left: -5, top: -5, cursor: 'nwse-resize' },
      ne: { right: -5, top: -5, cursor: 'nesw-resize' },
      sw: { left: -5, bottom: -5, cursor: 'nesw-resize' },
      se: { right: -5, bottom: -5, cursor: 'nwse-resize' },
    }
    return pos[corner]
  }

  const subjectOn = !!active.subject?.enabled
  const previewBg = subjectOn && cutoutAssets ? cutoutAssets.bgUrl : baseBg
  const fill = liveSubject?.fill_ratio ?? active.subject?.fill_ratio ?? 0.5
  const preparedFill = cutoutAssets?.preparedFill || fill
  const scale = preparedFill > 0 ? fill / preparedFill : 1
  const stickerW = (cutoutAssets?.stickerWRatio || 0.4) * scale
  const stickerH = (cutoutAssets?.stickerHRatio || 0.5) * scale
  const xOff = liveSubject?.x_offset ?? active.subject?.x_offset ?? -0.06
  const yOff = liveSubject?.y_offset ?? active.subject?.y_offset ?? 0.08
  const subjectLeft = 0.5 - stickerW / 2 + xOff
  const subjectTop = 0.5 - stickerH / 2 + yOff
  const subjectSelected = selectedLayerId === SUBJECT_LAYER_ID

  return (
    <div
      ref={canvasRef}
      className="absolute inset-0 overflow-hidden bg-[#141820]"
      style={{
        backgroundImage: previewBg ? `url(${previewBg})` : undefined,
        backgroundSize: 'cover',
        backgroundPosition: 'center',
      }}
    >
      {!previewBg && <div className="absolute inset-0 bg-gradient-to-b from-slate-800 to-slate-950" />}
      {subjectOn && cutoutPreparing && !cutoutAssets && (
        <div className="absolute inset-0 z-40 flex items-center justify-center bg-slate-900/80 text-xs text-slate-200">
          正在抠像…首次稍慢，之后可拖拽人像
        </div>
      )}
      {subjectOn && cutoutAssets && (
        <div
          className="absolute"
          style={{
            left: `${subjectLeft * 100}%`,
            top: `${subjectTop * 100}%`,
            width: `${stickerW * 100}%`,
            height: `${stickerH * 100}%`,
            zIndex: subjectSelected ? 15 : 8,
            touchAction: 'none',
          }}
        >
          <img
            src={cutoutAssets.stickerUrl}
            alt="人像"
            draggable={false}
            onMouseDown={(e) => {
              e.preventDefault()
              e.stopPropagation()
              onSelectLayer(SUBJECT_LAYER_ID)
              beginSubjectDrag(e.clientX, e.clientY, 'subject-move')
            }}
            onTouchStart={(e) => {
              const t = e.touches[0]
              if (!t) return
              e.stopPropagation()
              onSelectLayer(SUBJECT_LAYER_ID)
              beginSubjectDrag(t.clientX, t.clientY, 'subject-move')
            }}
            className={`h-full w-full cursor-move select-none object-contain ${
              subjectSelected ? 'outline outline-2 outline-amber-400' : ''
            }`}
          />
          {subjectSelected &&
            (['nw', 'ne', 'sw', 'se'] as const).map((c) => (
              <span
                key={c}
                onMouseDown={(e) => {
                  e.preventDefault()
                  e.stopPropagation()
                  onSelectLayer(SUBJECT_LAYER_ID)
                  beginSubjectDrag(e.clientX, e.clientY, 'subject-resize', c)
                }}
                className="absolute z-30 h-2.5 w-2.5 rounded-sm border border-white bg-amber-400 shadow"
                style={handleBox(c)}
              />
            ))}
        </div>
      )}
      {overlayStyle(active.background) && (
        <div className="pointer-events-none absolute inset-0 z-[9]" style={overlayStyle(active.background)} />
      )}
      {active.layers.map((layer) => {
        const isSelected = layer.id === selectedLayerId
        const rot = layer.rotation || 0
        const depthBehind = String(layer.depth || 'front') === 'behind'
        const posStyle: React.CSSProperties = {
          left: `${layer.x * 100}%`,
          top: `${layer.y * 100}%`,
          transform: layerBoxTransform(layer.anchor, rot),
          touchAction: 'none',
          zIndex: isSelected ? 20 : depthBehind ? 6 : 10,
        }

        if (layer.type === 'image') {
          const src = coverImageDisplaySrc(layer.image_src)
          if (!src) return null
          return (
            <div key={layer.id} className="absolute" style={posStyle}>
              <img
                src={src}
                alt={layer.label}
                draggable={false}
                onMouseDown={(e) => onCanvasMouseDown(e, layer.id)}
                onTouchStart={(e) => onCanvasTouchStart(e, layer.id)}
                className={`cursor-move select-none object-contain ${
                  isSelected ? 'outline outline-2 outline-cyan-400' : ''
                }`}
                style={{ width: `${(layer.width_ratio ?? 0.2) * 100}%`, height: 'auto', display: 'block' }}
              />
              {isSelected &&
                (['nw', 'ne', 'sw', 'se'] as const).map((c) => (
                  <span
                    key={c}
                    onMouseDown={(e) => onResizeMouseDown(e, layer.id, c)}
                    className="absolute z-30 h-2.5 w-2.5 rounded-sm border border-white bg-cyan-400 shadow"
                    style={handleBox(c)}
                  />
                ))}
            </div>
          )
        }

        const bind = layerBind(layer)
        const text = layerDisplayText(layer, title, subtitle)
        const placeholder =
          !text.trim() && bind === 'title'
            ? '主标题'
            : !text.trim() && bind === 'subtitle'
              ? '副标题'
              : ''
        const display = text.trim() || placeholder
        if (!display) return null
        const band = Math.min(0.7, Math.max(0.04, layer.band_height_ratio || 0.12))
        const vertical = layer.writing_mode === 'vertical'
        const fontPx = Math.max(
          11,
          Math.round(Math.min(0.18, Math.max(0.018, layer.font_size_ratio || 0.048)) * canvasH),
        )
        const boxStyle: React.CSSProperties = {
          ...posStyle,
          // 固定展示容器：宽=max_width，高=band；角点贴在此框四角
          width: vertical ? `${Math.round(fontPx * 1.35)}px` : `${(layer.max_width_ratio || 0.86) * 100}%`,
          height: `${Math.round(band * canvasH)}px`,
          boxSizing: 'border-box',
        }
        return (
          <div key={layer.id} className="absolute" style={boxStyle}>
            <div
              onMouseDown={(e) => onCanvasMouseDown(e, layer.id)}
              onTouchStart={(e) => onCanvasTouchStart(e, layer.id)}
              className={`h-full w-full cursor-move select-none ${
                isSelected ? 'outline outline-2 outline-cyan-400 outline-offset-[-1px]' : ''
              } ${placeholder ? 'opacity-40' : ''}`}
              style={layerTextStyle(layer, canvasH, { fillBox: true })}
            >
              {display}
            </div>
            {isSelected &&
              (['nw', 'ne', 'sw', 'se'] as const).map((c) => (
                <span
                  key={c}
                  onMouseDown={(e) => onResizeMouseDown(e, layer.id, c)}
                  onTouchStart={(e) => {
                    const t = e.touches[0]
                    if (!t) return
                    e.preventDefault()
                    e.stopPropagation()
                    onSelectLayer(layer.id)
                    beginDrag(t.clientX, t.clientY, layer.id, 'resize', c)
                  }}
                  className="absolute z-30 h-2.5 w-2.5 rounded-sm border border-white bg-cyan-400 shadow"
                  style={handleBox(c)}
                />
              ))}
          </div>
        )
      })}
    </div>
  )
}

type LayerBind = 'title' | 'subtitle' | 'custom'
type ExtraKind = 'text' | 'tag' | 'image'

const EXPORT_CANVAS_H = 1920

function coverExportLabel(aspect: string): string {
  return aspect === 'landscape_16_9' ? '1920×1080' : '1080×1920'
}

const EFFECTS: CoverLayer['effect'][] = ['none', 'shadow', 'outline', 'glow', 'neon', 'pill']

const OVERLAYS: CoverTemplate['background']['overlay'][] = [
  'none',
  'light_flat',
  'dark_flat',
  'bottom_gradient',
  'top_gradient',
]

const OVERLAY_LABELS: Record<CoverTemplate['background']['overlay'], string> = {
  none: '无遮罩',
  light_flat: '白色遮罩',
  dark_flat: '暗色遮罩',
  bottom_gradient: '底部渐变',
  top_gradient: '顶部渐变',
}

const COPY_INPUT =
  'w-full rounded-lg border-2 border-slate-300 bg-white px-3 py-2.5 text-[15px] font-semibold leading-snug text-slate-900 shadow-sm placeholder:text-slate-400 placeholder:font-normal focus:border-teal-500 focus:outline-none focus:ring-2 focus:ring-teal-500/25'

const FIELD_INPUT =
  'w-full rounded-lg border border-[var(--border)] bg-[var(--panel)] px-2.5 py-1.5 text-sm text-[var(--text)] focus:border-[var(--accent)] focus:outline-none'

function layerBind(layer: CoverLayer): LayerBind {
  if (layer.type === 'image') return 'custom'
  if (layer.text === '{{title}}') return 'title'
  if (layer.text === '{{subtitle}}') return 'subtitle'
  return 'custom'
}

function extraKind(layer: CoverLayer): ExtraKind {
  if (layer.type === 'image') return 'image'
  if (layer.effect === 'pill') return 'tag'
  return 'text'
}

function extraKindLabel(kind: ExtraKind): string {
  if (kind === 'tag') return '标签'
  if (kind === 'image') return '图片'
  return '文本'
}

function layerDisplayText(layer: CoverLayer, title: string, subtitle: string): string {
  const bind = layerBind(layer)
  if (bind === 'title') return title
  if (bind === 'subtitle') return subtitle
  return layer.text
}

function bindLabel(bind: LayerBind): string {
  if (bind === 'title') return '主标题'
  if (bind === 'subtitle') return '副标题'
  return '自定义'
}

function anchorTransform(anchor: CoverLayer['anchor']): string {
  if (anchor === 'center') return 'translate(-50%, -50%)'
  if (anchor.includes('center') && anchor.includes('bottom')) return 'translate(-50%, -100%)'
  if (anchor.includes('center') && anchor.includes('top')) return 'translateX(-50%)'
  if (anchor.includes('right') && anchor.includes('bottom')) return 'translate(-100%, -100%)'
  if (anchor.includes('right')) return 'translateX(-100%)'
  if (anchor.includes('bottom')) return 'translateY(-100%)'
  return ''
}

function layerBoxTransform(anchor: CoverLayer['anchor'], rotationDeg: number): string {
  const base = anchorTransform(anchor)
  const rot = Math.abs(rotationDeg) >= 0.3 ? `rotate(${rotationDeg}deg)` : ''
  if (base && rot) return `${base} ${rot}`
  return base || rot || 'none'
}

function hexAlpha(color: string, alpha: number): string {
  const a = Math.max(0, Math.min(255, Math.round(alpha)))
  const hex = a.toString(16).padStart(2, '0')
  const c = color.startsWith('#') && color.length >= 7 ? color.slice(0, 7) : '#000000'
  return `${c}${hex}`
}

function layerTextStyle(
  layer: CoverLayer,
  canvasH: number,
  opts?: { fillBox?: boolean },
): React.CSSProperties {
  const scale = canvasH / EXPORT_CANVAS_H
  const ratio = Math.min(0.18, Math.max(0.018, layer.font_size_ratio || 0.048))
  const size = Math.max(11, Math.round(ratio * canvasH))
  const color = layer.color || '#FFFFFF'
  const stroke = layer.stroke_color || '#000000'
  const vertical = layer.writing_mode === 'vertical'
  const fillBox = !!opts?.fillBox
  const style: React.CSSProperties = {
    color,
    fontSize: size,
    fontFamily: '"Microsoft YaHei", "PingFang SC", sans-serif',
    fontWeight: layer.font_weight === 'bold' ? 700 : 400,
    ...(fillBox
      ? { width: '100%', height: '100%', maxHeight: 'none' }
      : {
          width: vertical ? undefined : `${(layer.max_width_ratio || 0.86) * 100}%`,
          maxHeight: `${Math.round(Math.min(0.7, Math.max(0.04, layer.band_height_ratio || 0.12)) * canvasH)}px`,
        }),
    overflow: 'hidden',
    boxSizing: 'border-box',
    lineHeight: vertical ? 1.12 : 1.25,
    textAlign: vertical
      ? 'center'
      : layer.anchor.includes('center')
        ? 'center'
        : layer.anchor.includes('right')
          ? 'right'
          : 'left',
    whiteSpace: vertical ? 'nowrap' : 'pre-wrap',
    wordBreak: vertical ? 'keep-all' : 'break-word',
    ...(vertical
      ? {
          writingMode: 'vertical-rl',
          textOrientation: 'upright',
          letterSpacing: '0.08em',
        }
      : {
          display: '-webkit-box',
          WebkitBoxOrient: 'vertical',
          WebkitLineClamp: Math.max(1, Math.min(8, layer.max_lines || 3)),
        }),
  }
  const strokeW = Math.max(layer.stroke_width, layer.effect === 'outline' ? 3 : 0) * scale
  if (layer.effect === 'shadow') {
    const off = Math.max(2, Math.floor(size / 12))
    style.textShadow = `${off}px ${off}px 0 rgba(0,0,0,0.92), ${off + 1}px ${off + 1}px ${Math.max(2, Math.floor(size / 14))}px rgba(0,0,0,0.55)`
  }
  if (strokeW > 0) {
    style.WebkitTextStroke = `${strokeW}px ${stroke}`
    ;(style as Record<string, string>).paintOrder = 'stroke fill'
  }
  if (layer.effect === 'glow' || layer.effect === 'neon') {
    const glow = layer.glow_color || '#22D3EE'
    const blur1 = Math.round(size / 4)
    const blur2 = Math.round(size / 2)
    style.textShadow = `0 0 ${blur1}px ${glow}, 0 0 ${blur2}px ${glow}`
  }
  if (layer.effect === 'pill') {
    style.background = hexAlpha(layer.pill_color || '#FFFFFF', layer.pill_alpha ?? 230)
    style.padding = `${Math.round(size * 0.25)}px ${Math.round(size * 0.4)}px`
    style.borderRadius = `${Math.round(size * 0.4)}px`
    if (!fillBox) style.display = 'inline-block'
  }
  return style
}

function overlayStyle(bg: CoverTemplate['background']): React.CSSProperties | undefined {
  const a = (bg.overlay_alpha ?? 160) / 255
  if (bg.overlay === 'dark_flat') {
    return { background: `rgba(0,0,0,${a})` }
  }
  if (bg.overlay === 'light_flat') {
    return { background: `rgba(255,255,255,${a})` }
  }
  if (bg.overlay === 'bottom_gradient') {
    return {
      background: `linear-gradient(to top, rgba(0,0,0,${a}) 0%, rgba(0,0,0,${a * 0.35}) 40%, transparent 60%)`,
    }
  }
  if (bg.overlay === 'top_gradient') {
    return {
      background: `linear-gradient(to bottom, rgba(0,0,0,${a}) 0%, rgba(0,0,0,${a * 0.35}) 40%, transparent 45%)`,
    }
  }
  return undefined
}

const baseTextLayer = (partial: Partial<CoverLayer>): CoverLayer => ({
  id: `extra_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
  type: 'text',
  label: '装饰',
  text: '',
  x: 0.08,
  y: 0.06,
  anchor: 'top_left',
  font_size_ratio: 0.045,
  font_weight: 'bold',
  color: '#111111',
  stroke_color: '#000000',
  stroke_width: 0,
  effect: 'none',
  glow_color: '#22D3EE',
  pill_color: '#FFFFFF',
  pill_alpha: 230,
  max_width_ratio: 0.5,
  rotation: 0,
  ...partial,
})

const newExtraTextLayer = (n: number): CoverLayer =>
  baseTextLayer({
    label: `文本 ${n}`,
    text: '必看',
    color: '#FFFFFF',
    stroke_color: '#000000',
    stroke_width: 2,
    effect: 'shadow',
  })

const newExtraTagLayer = (n: number): CoverLayer =>
  baseTextLayer({
    label: `标签 ${n}`,
    text: '热门',
    color: '#111111',
    stroke_width: 0,
    effect: 'pill',
    pill_color: '#FFFFFF',
    pill_alpha: 235,
  })

const newExtraImageLayer = (n: number): CoverLayer => ({
  id: `img_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
  type: 'image',
  label: `图片 ${n}`,
  text: '',
  image_src: '',
  width_ratio: 0.22,
  x: 0.08,
  y: 0.06,
  anchor: 'top_left',
  font_size_ratio: 0.05,
  font_weight: 'normal',
  color: '#FFFFFF',
  stroke_color: '#000000',
  stroke_width: 0,
  effect: 'none',
  max_width_ratio: 1,
  rotation: 0,
})

const defaultSubject = (): CoverSubject => ({
  enabled: false,
  bg_mode: 'blur',
  blur_radius: 56,
  outline: 'none',
  outline_color: '#FFFFFF',
  outline_width: 10,
  glow_color: '#FFFFFF',
  scale: 1,
  fill_ratio: 0.5,
  x_offset: -0.06,
  y_offset: 0.08,
})

const blankTemplate = (): CoverTemplate => ({
  id: '',
  name: '我的模板',
  builtin: false,
  subject: defaultSubject(),
  background: { overlay: 'light_flat', overlay_alpha: 120 },
  layers: [],
})

function defaultCoverSubtitle(title: string): string {
  const t = title.trim()
  if (!t) return ''
  const parts = t.split(/[，,。！？\n|·]/).map((s) => s.trim()).filter(Boolean)
  if (parts.length >= 2) {
    const sub = parts.slice(1).join(' · ')
    return sub.length > 40 ? `${sub.slice(0, 39)}…` : sub
  }
  if (t.length > 14) return `${t.slice(0, 13)}…`
  return `精选 · ${t}`
}

type LayerDesignBase = {
  font: number
  maxW: number
  band: number
  maxLines: number
  vertical: boolean
}

function charLen(text: string): number {
  return [...text.replace(/\s+/g, '')].length
}

function clampNum(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v))
}

/** 按主/副标题字数，相对模板设计尺寸自动调字号与容器 */
function autoFitBoundLayer(
  text: string,
  role: 'title' | 'subtitle',
  base: LayerDesignBase,
): Pick<CoverLayer, 'font_size_ratio' | 'max_width_ratio' | 'band_height_ratio'> | null {
  const len = charLen(text)
  if (!len) return null

  const ideal = role === 'title' ? (base.vertical ? 5 : 6) : 8
  let fontScale = 1
  if (len <= 2) fontScale = role === 'title' ? 1.35 : 1.15
  else if (len <= 4) fontScale = role === 'title' ? 1.2 : 1.08
  else if (len <= ideal) fontScale = 1.05
  else if (len <= ideal + 4) fontScale = 0.92
  else if (len <= ideal + 8) fontScale = 0.78
  else if (len <= ideal + 14) fontScale = 0.66
  else fontScale = 0.55

  const fontLo = role === 'title' ? 0.028 : 0.022
  const fontHi = role === 'title' ? 0.18 : 0.08
  const font = clampNum(base.font * fontScale, fontLo, Math.max(fontHi, base.font))

  let maxW = base.maxW
  if (base.vertical) {
    maxW = base.maxW
  } else if (len <= 4) {
    maxW = clampNum(base.maxW * 0.72, 0.32, base.maxW)
  } else if (len > ideal + 2) {
    maxW = clampNum(base.maxW * Math.min(1.25, 0.9 + (len - ideal) * 0.03), base.maxW, 0.96)
  }

  const approxCharsPerLine = base.vertical
    ? Math.max(3, Math.floor(base.band / Math.max(font, 0.03)))
    : Math.max(3, Math.floor(maxW * 14))
  const linesNeeded = Math.min(
    Math.max(1, base.maxLines || 2),
    Math.max(1, Math.ceil(len / approxCharsPerLine)),
  )
  const bandFromFont = font * linesNeeded * (base.vertical ? 1.15 : 1.4)
  const band = clampNum(Math.max(base.band * (font / Math.max(base.font, 0.02)), bandFromFont), 0.045, 0.48)

  return {
    font_size_ratio: Math.round(font * 1000) / 1000,
    max_width_ratio: Math.round(maxW * 1000) / 1000,
    band_height_ratio: Math.round(band * 1000) / 1000,
  }
}

function captureLayerDesignBases(tpl: CoverTemplate): Record<string, LayerDesignBase> {
  const map: Record<string, LayerDesignBase> = {}
  for (const l of tpl.layers) {
    if (l.type === 'image') continue
    map[l.id] = {
      font: l.font_size_ratio || 0.048,
      maxW: l.max_width_ratio || 0.86,
      band: l.band_height_ratio || 0.12,
      maxLines: l.max_lines || 2,
      vertical: l.writing_mode === 'vertical',
    }
  }
  return map
}

function applyAutoFitToTemplate(
  tpl: CoverTemplate,
  titleText: string,
  subtitleText: string,
  bases: Record<string, LayerDesignBase>,
  /** Only fit these binds; default both (template / AI). */
  only?: Array<'title' | 'subtitle'>,
): CoverTemplate {
  const allow = new Set(only && only.length ? only : (['title', 'subtitle'] as const))
  let changed = false
  const layers = tpl.layers.map((l) => {
    const bind = layerBind(l)
    if (bind === 'custom' || l.type === 'image') return l
    if (!allow.has(bind)) return l
    const base =
      bases[l.id] ||
      ({
        font: l.font_size_ratio || 0.048,
        maxW: l.max_width_ratio || 0.86,
        band: l.band_height_ratio || 0.12,
        maxLines: l.max_lines || 2,
        vertical: l.writing_mode === 'vertical',
      } satisfies LayerDesignBase)
    const text = bind === 'title' ? titleText : subtitleText
    const next = autoFitBoundLayer(text, bind, base)
    if (!next) return l
    if (
      Math.abs((l.font_size_ratio || 0) - (next.font_size_ratio || 0)) < 0.0005 &&
      Math.abs((l.max_width_ratio || 0) - (next.max_width_ratio || 0)) < 0.0005 &&
      Math.abs((l.band_height_ratio || 0) - (next.band_height_ratio || 0)) < 0.0005
    ) {
      return l
    }
    changed = true
    return { ...l, ...next }
  })
  return changed ? { ...tpl, layers } : tpl
}

const SYNC_COLOR_KEYS = ['color', 'stroke_color', 'glow_color'] as const
const SYNC_STYLE_KEYS = [
  'color',
  'stroke_color',
  'stroke_width',
  'glow_color',
  'effect',
  'font_weight',
  'font_size_ratio',
  'writing_mode',
  'pill_color',
  'pill_alpha',
] as const

function syncBoundLayerFields(
  tpl: CoverTemplate,
  fromBind: 'title' | 'subtitle',
  keys: readonly (keyof CoverLayer)[],
): CoverTemplate {
  const source = tpl.layers.find((l) => layerBind(l) === fromBind && l.type !== 'image')
  const toBind = fromBind === 'title' ? 'subtitle' : 'title'
  if (!source) return tpl
  let changed = false
  const layers = tpl.layers.map((l) => {
    if (layerBind(l) !== toBind || l.type === 'image') return l
    const partial: Partial<CoverLayer> = {}
    for (const k of keys) {
      const v = source[k]
      if (v !== undefined) {
        ;(partial as CoverLayer)[k] = v as never
      }
    }
    changed = true
    return { ...l, ...partial }
  })
  return changed ? { ...tpl, layers } : tpl
}

type CoverDraft = {
  template: CoverTemplate
  title: string
  subtitle: string
  framePath: string | null
  frameTime: number
  selectedLayerId: string | null
}

function coverDraftKey(sessionPath: string): string {
  return `jy_cover_draft:${sessionPath}`
}

function loadCoverDraft(sessionPath: string): CoverDraft | null {
  try {
    const raw = sessionStorage.getItem(coverDraftKey(sessionPath))
    if (!raw) return null
    const data = JSON.parse(raw) as CoverDraft
    if (!data?.template?.layers) return null
    return data
  } catch {
    return null
  }
}

function saveCoverDraft(sessionPath: string, draft: CoverDraft): void {
  try {
    sessionStorage.setItem(coverDraftKey(sessionPath), JSON.stringify(draft))
  } catch {
    /* quota / private mode */
  }
}

export function CoverEditor({
  sessionPath,
  previewVideo,
  videoSources,
  aspect = 'portrait_9_16',
  initialTitle,
  initialSubtitle,
  script,
  onCoverChange,
  embedded = false,
  onPreviewBridge,
}: Props) {
  const jobQueue = useJobQueue()
  const [templates, setTemplates] = useState<CoverTemplate[]>([])
  const [active, setActive] = useState<CoverTemplate>(blankTemplate())
  const [selectedLayerId, setSelectedLayerId] = useState<string | null>(null)
  const [title, setTitle] = useState(initialTitle || '')
  const [subtitle, setSubtitle] = useState(initialSubtitle || '')
  const [exportUrl, setExportUrl] = useState<string | null>(null)
  const [busy, setBusy] = useState('')
  const [rendering, setRendering] = useState(false)
  const [log, setLog] = useState('')
  const [needRembgInstall, setNeedRembgInstall] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [cutoutAssets, setCutoutAssets] = useState<CutoutPreviewAssets | null>(null)
  const [cutoutPreparing, setCutoutPreparing] = useState(false)
  const didInitTemplate = useRef(false)
  const layerDesignBaseRef = useRef<Record<string, LayerDesignBase>>({})
  const imageInputRef = useRef<HTMLInputElement>(null)
  const [framePath, setFramePath] = useState<string | null>(null)
  const [frameTime, setFrameTime] = useState(0.5)
  const [frameSourceId, setFrameSourceId] = useState('')
  const [framePickerOpen, setFramePickerOpen] = useState(false)
  const [imageUrlDraft, setImageUrlDraft] = useState('')
  const [assetPickerOpen, setAssetPickerOpen] = useState(false)
  const autoFrameDone = useRef(false)
  const lastEditedRoleRef = useRef<'title' | 'subtitle'>('title')
  const draftHydrated = useRef(false)

  const sources = useMemo(() => {
    const list: CoverVideoSource[] = []
    const seen = new Set<string>()
    for (const s of videoSources || []) {
      if (!s.path || seen.has(s.path)) continue
      seen.add(s.path)
      list.push(s)
    }
    if (previewVideo && !seen.has(previewVideo)) {
      list.unshift({ id: 'preview', label: '口播成片', path: previewVideo })
    }
    return list
  }, [videoSources, previewVideo])

  const activeSource = sources.find((s) => s.id === frameSourceId) || sources[0] || null

  useEffect(() => {
    if (!sources.length) return
    if (!frameSourceId || !sources.some((s) => s.id === frameSourceId)) {
      setFrameSourceId(sources[0].id)
    }
  }, [sources, frameSourceId])

  const baseBg = framePath ? mediaUrl(framePath) : null

  const templateLayers = active.layers.filter((l) => layerBind(l) !== 'custom')
  const extraLayers = active.layers.filter((l) => layerBind(l) === 'custom')
  const selectedLayer = active.layers.find((l) => l.id === selectedLayerId) ?? null
  const selectedBind = selectedLayer ? layerBind(selectedLayer) : null
  const selectedExtraKind = selectedLayer && selectedBind === 'custom' ? extraKind(selectedLayer) : null

  const loadTemplates = useCallback(async () => {
    try {
      const res = await api.coverTemplates()
      setTemplates(res.templates)
      if (!didInitTemplate.current && res.templates.length > 0) {
        didInitTemplate.current = true
        const draft = loadCoverDraft(sessionPath)
        if (draft?.template?.layers?.length) {
          draftHydrated.current = true
          layerDesignBaseRef.current = captureLayerDesignBases(draft.template)
          setActive(draft.template)
          setTitle(draft.title || initialTitle || '')
          setSubtitle(draft.subtitle || initialSubtitle || '')
          if (draft.framePath) {
            setFramePath(draft.framePath)
            setFrameTime(draft.frameTime || 0.5)
            autoFrameDone.current = true
          }
          setSelectedLayerId(
            draft.selectedLayerId || draft.template.layers[0]?.id || null,
          )
          return
        }
        const preferred =
          (res.templates.find((t) => t.id === 'dy_hook_yellow') as CoverTemplate | undefined) ||
          (res.templates[0] as CoverTemplate)
        const clone: CoverTemplate = JSON.parse(JSON.stringify(preferred))
        layerDesignBaseRef.current = captureLayerDesignBases(clone)
        const t0 = initialTitle || ''
        const s0 = initialSubtitle || ''
        const fitted = applyAutoFitToTemplate(clone, t0, s0, layerDesignBaseRef.current)
        setActive(fitted)
        const firstLayer = fitted.layers[0]
        if (firstLayer) setSelectedLayerId(firstLayer.id)
      }
    } catch (e) {
      setLog(e instanceof Error ? e.message : String(e))
    }
  }, [sessionPath, initialTitle, initialSubtitle])

  useEffect(() => {
    void loadTemplates()
  }, [loadTemplates])

  useEffect(() => {
    if (initialTitle && !draftHydrated.current) setTitle(initialTitle)
  }, [initialTitle])

  useEffect(() => {
    if (initialSubtitle && !draftHydrated.current) setSubtitle(initialSubtitle)
  }, [initialSubtitle])

  useEffect(() => {
    if (!title.trim()) return
    setSubtitle((prev) => (prev.trim() ? prev : defaultCoverSubtitle(title)))
  }, [title])

  // Persist draft so tab switch / remount keeps layout (manual text edits do NOT auto-fit font).
  useEffect(() => {
    if (!didInitTemplate.current) return
    const t = window.setTimeout(() => {
      saveCoverDraft(sessionPath, {
        template: active,
        title,
        subtitle,
        framePath,
        frameTime,
        selectedLayerId,
      })
    }, 400)
    return () => window.clearTimeout(t)
  }, [sessionPath, active, title, subtitle, framePath, frameTime, selectedLayerId])

  const syncFromCurrent = useCallback(
    (mode: 'color' | 'style') => {
      const from =
        selectedBind === 'title' || selectedBind === 'subtitle'
          ? selectedBind
          : lastEditedRoleRef.current
      const keys = mode === 'color' ? SYNC_COLOR_KEYS : SYNC_STYLE_KEYS
      setActive((prev) => syncBoundLayerFields(prev, from, keys))
      setDirty(true)
      const to = from === 'title' ? '副标题' : '主标题'
      setLog(
        mode === 'color'
          ? `已以当前${from === 'title' ? '主标题' : '副标题'}为准，同步颜色到${to}`
          : `已以当前${from === 'title' ? '主标题' : '副标题'}为准，同步样式到${to}`,
      )
    },
    [selectedBind],
  )
  const extractFrame = useCallback(
    async (timeSec: number, sourcePath?: string) => {
      const path = sourcePath || activeSource?.path
      if (!path) {
        setLog('暂无成片视频可抽帧')
        return
      }
      setBusy('抽帧')
      try {
        const res = await api.coverExtractFrame({
          session_path: sessionPath,
          time_sec: timeSec,
          video_path: path,
        })
        setFramePath(res.frame_path)
        setFrameTime(res.time_sec)
        setLog(`已抽帧 ${res.time_sec.toFixed(1)}s 作为封面底图`)
      } catch (e) {
        setLog(e instanceof Error ? e.message : String(e))
      } finally {
        setBusy('')
      }
    },
    [activeSource?.path, sessionPath],
  )

  useEffect(() => {
    if (autoFrameDone.current || framePath || !activeSource?.path) return
    autoFrameDone.current = true
    void extractFrame(0.5, activeSource.path)
  }, [activeSource?.path, extractFrame, framePath])

  const patch = (next: CoverTemplate) => {
    setActive(next)
    setDirty(true)
  }

  const patchLayer = useCallback((id: string, partial: Partial<CoverLayer>) => {
    setActive((prev) => ({
      ...prev,
      layers: prev.layers.map((l) => (l.id === id ? { ...l, ...partial } : l)),
    }))
    setDirty(true)
  }, [])

  const patchSubject = useCallback((partial: Partial<CoverSubject>) => {
    setActive((prev) => ({
      ...prev,
      subject: {
        ...(prev.subject || defaultSubject()),
        ...partial,
      },
    }))
    setDirty(true)
  }, [])

  const prepareCutoutPreview = useCallback(
    async (tplOverride?: CoverTemplate) => {
      const tpl = tplOverride || active
      if (!tpl.subject?.enabled) {
        setCutoutAssets(null)
        return
      }
      setCutoutPreparing(true)
      setLog('')
      setNeedRembgInstall(false)
      try {
        const fd = new FormData()
        fd.append('session_path', sessionPath)
        fd.append('subject_json', JSON.stringify(tpl.subject))
        fd.append('output_aspect', aspect)
        if (framePath) fd.append('base_path', framePath)
        const res = await api.prepareCoverSubject(fd)
        const bg = res.data.bg_path as string
        const sticker = res.data.sticker_path as string
        const stamp = Date.now()
        setCutoutAssets({
          bgUrl: mediaUrl(bg, stamp) || '',
          stickerUrl: mediaUrl(sticker, stamp) || '',
          stickerWRatio: Number(res.data.sticker_w_ratio) || 0.4,
          stickerHRatio: Number(res.data.sticker_h_ratio) || 0.5,
          preparedFill: Number(res.data.fill_ratio) || tpl.subject.fill_ratio || 0.5,
        })
        setLog(res.log || '抠像样片就绪，可拖拽人像')
      } catch (e) {
        setCutoutAssets(null)
        const msg = e instanceof Error ? e.message : String(e)
        setLog(msg)
        if (/NEED_INSTALL:rembg|未安装 rembg|No module named ['\"]rembg['\"]/i.test(msg)) {
          setNeedRembgInstall(true)
        }
      } finally {
        setCutoutPreparing(false)
      }
    },
    [active, sessionPath, framePath, aspect],
  )

  const addExtraLayer = (kind: ExtraKind) => {
    const n = extraLayers.length + 1
    const layer =
      kind === 'image'
        ? newExtraImageLayer(n)
        : kind === 'tag'
          ? newExtraTagLayer(n)
          : newExtraTextLayer(n)
    patch({ ...active, layers: [...active.layers, layer] })
    setSelectedLayerId(layer.id)
  }

  const removeLayer = (id: string, e?: React.MouseEvent) => {
    e?.stopPropagation()
    const layer = active.layers.find((l) => l.id === id)
    if (!layer || layerBind(layer) !== 'custom') return
    const layers = active.layers.filter((l) => l.id !== id)
    patch({ ...active, layers })
    if (selectedLayerId === id) setSelectedLayerId(layers[0]?.id ?? null)
  }

  const uploadLayerImage = async (layerId: string, file: File) => {
    setBusy('上传图片')
    try {
      const res = await api.uploadCoverAsset(sessionPath, file)
      if (res.ok && res.path) {
        patchLayer(layerId, { image_src: res.path })
        setLog(file.type.includes('gif') ? 'GIF 已上传（预览可动，导出取首帧）' : '装饰图片已上传')
      }
    } catch (e) {
      setLog(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy('')
    }
  }

  const applyImageUrl = async (layerId: string, url: string) => {
    const u = url.trim()
    if (!u) return
    setBusy('拉取图片')
    try {
      const res = await api.coverAssetFromUrl(sessionPath, u)
      if (res.ok && res.path) {
        patchLayer(layerId, { image_src: res.path })
        setImageUrlDraft('')
        setLog('网络图片已导入')
      }
    } catch (e) {
      setLog(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy('')
    }
  }

  const applyAssetImage = (layerId: string, asset: PickerAsset) => {
    const path = (asset.media_path || '').trim()
    if (!path) {
      setLog('该素材没有可用图片路径')
      return
    }
    patchLayer(layerId, { image_src: path })
    setAssetPickerOpen(false)
    setLog(`已选用素材「${asset.name}」`)
  }

  const selectTemplate = (tpl: CoverTemplate) => {
    const clone: CoverTemplate = JSON.parse(JSON.stringify(tpl))
    if (!clone.subject) clone.subject = defaultSubject()
    if (clone.builtin) {
      clone.id = ''
      clone.name = `${clone.name} · 副本`
      clone.builtin = false
    }
    layerDesignBaseRef.current = captureLayerDesignBases(clone)
    const fitted = applyAutoFitToTemplate(clone, title, subtitle, layerDesignBaseRef.current)
    setActive(fitted)
    setSelectedLayerId(fitted.layers[0]?.id ?? null)
    setDirty(true)
    setExportUrl(null)
    if (fitted.subject?.enabled) {
      void prepareCutoutPreview(fitted)
    } else {
      setCutoutAssets(null)
    }
  }

  const saveTemplate = async () => {
    setBusy('保存模板')
    try {
      const res = await api.saveCoverTemplate(active)
      setActive(res.template)
      setDirty(false)
      await loadTemplates()
      setLog(`模板已保存：${res.template.name}`)
    } catch (e) {
      setLog(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy('')
    }
  }

  const exportHdCover = useCallback(async (tplOverride?: CoverTemplate): Promise<string | null> => {
    setRendering(true)
    setLog('')
    const tpl = tplOverride || active
    try {
      const fd = new FormData()
      fd.append('session_path', sessionPath)
      fd.append('template_json', JSON.stringify(tpl))
      fd.append('title', title)
      fd.append('subtitle', subtitle)
      fd.append('output_aspect', aspect)
      if (framePath) fd.append('base_path', framePath)
      const res = await api.renderCover(fd)
      const path = (res.data.cover_path as string) || null
      const url = path ? mediaUrl(path, Date.now()) : null
      setExportUrl(url)
      onCoverChange?.(path)
      setLog(
        tpl.subject?.enabled
          ? res.log || '抠像封面已生成，预览区已更新'
          : res.log || '封面已保存，将随一键成片嵌入',
      )
      return path
    } catch (e) {
      setExportUrl(null)
      setLog(e instanceof Error ? e.message : String(e))
      return null
    } finally {
      setRendering(false)
    }
  }, [sessionPath, active, title, subtitle, framePath, onCoverChange, aspect])

  const saveCoverRef = useRef(exportHdCover)
  saveCoverRef.current = exportHdCover

  // 换帧或开关抠像 / 改模糊描边：重新准备样片（位置拖拽不重抠）
  const subjectStyleKey = active.subject?.enabled
    ? [
        active.subject.bg_mode,
        active.subject.blur_radius,
        active.subject.outline,
        active.subject.outline_color,
        active.subject.outline_width,
        framePath || '',
      ].join('|')
    : ''

  useEffect(() => {
    if (!active.subject?.enabled) {
      setCutoutAssets(null)
      return
    }
    if (!framePath && !activeSource?.path) return
    const t = window.setTimeout(() => {
      void prepareCutoutPreview()
    }, 280)
    return () => window.clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- style key drives refresh; avoid offset/fill loops
  }, [subjectStyleKey, active.subject?.enabled, framePath])

  useLayoutEffect(() => {
    if (!embedded || !onPreviewBridge) return
    onPreviewBridge({
      active,
      title,
      subtitle,
      baseBg,
      framePath,
      selectedLayerId,
      onSelectLayer: setSelectedLayerId,
      patchLayer,
      patchSubject,
      saveCover: () => saveCoverRef.current(),
      cutoutAssets,
      cutoutPreparing,
      aspect,
    })
  }, [
    embedded,
    onPreviewBridge,
    active,
    title,
    subtitle,
    baseBg,
    framePath,
    selectedLayerId,
    patchLayer,
    patchSubject,
    cutoutAssets,
    cutoutPreparing,
    aspect,
  ])

  const previewBridge: CoverPreviewBridge = {
    active,
    title,
    subtitle,
    baseBg,
    framePath,
    selectedLayerId,
    onSelectLayer: setSelectedLayerId,
    patchLayer,
    patchSubject,
    saveCover: exportHdCover,
    cutoutAssets,
    cutoutPreparing,
    aspect,
  }

  const templateLibrary = (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3">
      <div className="mb-2 flex items-center justify-between text-xs text-[var(--muted)]">
        <span>默认样式库</span>
        <span>{templates.length} 个 · 含人像抠图</span>
      </div>
      <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 lg:grid-cols-5">
        {templates.map((t) => (
          <button
            key={t.id + t.name}
            onClick={() => selectTemplate(t)}
            className={`rounded-lg border px-2 py-2 text-left text-xs transition ${
              active.id === t.id || active.name.startsWith(t.name.split(' · ')[0])
                ? 'border-[var(--accent)] bg-[var(--select-bg)] text-[var(--accent)]'
                : 'border-[var(--border)] hover:bg-[var(--panel)]'
            }`}
          >
            <div className="truncate font-medium">{t.name}</div>
            <div className="mt-0.5 flex flex-wrap gap-1">
              {t.builtin && (
                <span className="rounded bg-[var(--badge-bg)] px-1 text-[9px] text-[var(--badge-text)]">系统</span>
              )}
              {t.subject?.enabled && (
                <span className="rounded bg-[var(--select-bg)] px-1 text-[9px] text-[var(--accent)]">抠人像</span>
              )}
            </div>
          </button>
        ))}
      </div>
      <p className="mt-2 text-[10px] leading-relaxed text-[var(--muted)]">
        前 6 个为非抠像样板（大黄字 / 倾斜黄白 / 粉描边等）。带「抠人像」的会自动精抠。
      </p>
    </div>
  )

  const downloadCoverFile = useCallback(async () => {
    const path = await exportHdCover()
    if (!path) return
    const url = mediaUrl(path, Date.now())
    if (!url) return
    try {
      const res = await fetch(url)
      const blob = await res.blob()
      const objectUrl = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = objectUrl
      a.download = `cover_${Date.now()}.jpg`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(objectUrl)
      setLog('封面已单独导出到下载目录')
    } catch (e) {
      // Fallback: open in new tab if blob download blocked
      window.open(url, '_blank', 'noopener,noreferrer')
      setLog(e instanceof Error ? e.message : '已尝试在新窗口打开封面')
    }
  }, [exportHdCover])

  const exportRow = (
    <div className="flex flex-wrap items-center gap-2">
      <ActionBtn primary disabled={rendering} onClick={() => void exportHdCover()}>
        {rendering
          ? active.subject?.enabled
            ? '抠像生成中…'
            : '保存中…'
          : active.subject?.enabled
            ? '生成抠像封面'
            : '保存封面设置'}
      </ActionBtn>
      <ActionBtn disabled={rendering} onClick={() => void downloadCoverFile()}>
        {rendering ? '导出中…' : '⬇ 导出封面 JPG'}
      </ActionBtn>
      <ActionBtn disabled={!!busy} onClick={() => void saveTemplate()}>
        {busy === '保存模板' ? '保存中…' : '保存为模板'}
      </ActionBtn>
      {exportUrl && (
        <a href={exportUrl} target="_blank" rel="noreferrer" className="text-xs text-[var(--accent)] hover:underline">
          新窗口打开成品
        </a>
      )}
      {dirty && <span className="text-xs text-amber-500">未保存修改</span>}
      <span className="w-full text-[10px] text-[var(--muted)]">
        「保存封面设置」写入会话供一键成片嵌入；「导出封面」单独下载 JPG，不依赖成片。
      </span>
    </div>
  )

  const inlinePreview = !embedded ? (
    <div className="flex flex-col items-center gap-2 rounded-xl border border-[var(--border)] bg-white p-4">
      <p className="text-xs text-slate-500">
        {active.subject?.enabled
          ? `抠像实时预览 · 拖人像 · 保存后为 ${coverExportLabel(aspect)}`
          : `实时预览 · 保存后为 ${coverExportLabel(aspect)}`}
      </p>
      <div
        className={`relative w-full max-w-[260px] overflow-hidden rounded-xl border border-slate-200 shadow-inner ${
          aspect === 'landscape_16_9' ? 'aspect-video' : 'aspect-[9/16]'
        }`}
      >
        <CoverPreviewCanvas {...previewBridge} />
      </div>
      {exportRow}
    </div>
  ) : null

  const coverSettings = (
        <div className="space-y-3">
          {sources.length > 0 && (
            <div className="rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3 space-y-2">
              <span className="text-xs font-medium text-[var(--text)]">成片抽帧底图</span>
              <p className="text-[11px] text-[var(--muted)]">
                打开弹框像翻幻灯片一样预览视频，选好时间点后确认，再由 ffmpeg 截取该帧。
              </p>
              <div className="flex flex-wrap items-center gap-2">
                <ActionBtn
                  primary
                  disabled={!!busy}
                  onClick={() => setFramePickerOpen(true)}
                >
                  {busy === '抽帧' ? '截取中…' : '打开选帧弹框'}
                </ActionBtn>
                {framePath && (
                  <span className="text-[11px] text-emerald-500">
                    已选 {frameTime.toFixed(2)}s 帧为底图
                  </span>
                )}
              </div>
            </div>
          )}

          <div className="rounded-xl border-2 border-teal-200/60 bg-white p-3 space-y-3 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-sm font-semibold text-slate-800">封面文案</span>
                <button
                  type="button"
                  onClick={() => syncFromCurrent('style')}
                  className="rounded-md border border-slate-300 bg-slate-50 px-2 py-1 text-[10px] font-medium text-slate-700 hover:bg-slate-100"
                  title="以当前正在编辑的主/副标题为准，把字号、特效等样式同步到另一侧"
                >
                  同步主副标题
                </button>
                <button
                  type="button"
                  onClick={() => syncFromCurrent('color')}
                  className="rounded-md border border-slate-300 bg-slate-50 px-2 py-1 text-[10px] font-medium text-slate-700 hover:bg-slate-100"
                  title="以当前正在编辑的主/副标题为准，同步文字色与描边色"
                >
                  同步颜色
                </button>
              </div>
              <button
                disabled={!!busy || !script?.trim()}
                onClick={async () => {
                  setBusy('AI生成')
                  setLog('')
                  try {
                    const res = await api.coverSuggest(script || '', sessionPath)
                    if (res.ok && res.title) {
                      const nextTitle = res.title
                      const nextSub = res.subtitle || ''
                      setTitle(nextTitle)
                      setSubtitle(nextSub)
                      setActive((prev) =>
                        applyAutoFitToTemplate(
                          prev,
                          nextTitle,
                          nextSub,
                          layerDesignBaseRef.current,
                        ),
                      )
                      setLog(
                        res.saved
                          ? 'AI 已生成标题/副标题，并写入会话（发布页将自动带入）'
                          : 'AI 已根据口播文案生成标题',
                      )
                    } else {
                      setLog(res.message || '生成失败')
                    }
                  } catch (e) {
                    setLog(e instanceof Error ? e.message : String(e))
                  } finally {
                    setBusy('')
                  }
                }}
                className="rounded-lg bg-gradient-to-r from-violet-500 to-indigo-500 px-3 py-1.5 text-xs font-medium text-white hover:opacity-90 disabled:opacity-40"
              >
                {busy === 'AI生成' ? '✨ 生成中…' : '✨ AI 生成'}
              </button>
            </div>
            <Field label="主标题" light>
              <div>
                <CoverFieldNudge active={selectedBind === 'title'}>
                  <textarea
                    value={title}
                    onFocus={() => {
                      lastEditedRoleRef.current = 'title'
                      const layer = active.layers.find((l) => layerBind(l) === 'title')
                      if (layer) setSelectedLayerId(layer.id)
                    }}
                    onChange={(e) => setTitle(e.target.value)}
                    rows={2}
                    className={`${COPY_INPUT} min-h-[3.5rem] resize-y`}
                    placeholder="AI 生成或手动填写主标题…"
                  />
                </CoverFieldNudge>
                {selectedBind === 'title' && (
                  <p className="cover-field-nudge-hint">已选中右侧主标题 · 在此修改文案</p>
                )}
              </div>
            </Field>
            <Field label="副标题" light>
              <div>
                <CoverFieldNudge active={selectedBind === 'subtitle'}>
                  <input
                    value={subtitle}
                    onFocus={() => {
                      lastEditedRoleRef.current = 'subtitle'
                      const layer = active.layers.find((l) => layerBind(l) === 'subtitle')
                      if (layer) setSelectedLayerId(layer.id)
                    }}
                    onChange={(e) => setSubtitle(e.target.value)}
                    className={COPY_INPUT}
                    placeholder="补充说明、钩子语…"
                  />
                </CoverFieldNudge>
                {selectedBind === 'subtitle' && (
                  <p className="cover-field-nudge-hint">已选中右侧副标题 · 在此修改文案</p>
                )}
              </div>
            </Field>
            <p className="text-[11px] text-slate-500">
              自适应字号仅在选用模板或 AI 生成时生效；手动改字不会再动字号。可用「同步主副标题 / 同步颜色」以当前编辑侧为准同步另一侧。
            </p>
          </div>

          {templateLayers.length > 0 && (
            <div className="rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3 space-y-2">
              <span className="text-xs text-[var(--muted)]">模板文字样式（内容来自上方文案）</span>
              <div className="flex flex-wrap gap-1.5">
                {templateLayers.map((l) => (
                  <button
                    key={l.id}
                    onClick={() => setSelectedLayerId(l.id)}
                    className={`rounded-md border px-2 py-1 text-xs ${
                      selectedLayerId === l.id
                        ? 'border-[var(--accent)] bg-[var(--select-bg)] text-[var(--accent)]'
                        : 'border-[var(--border)]'
                    }`}
                  >
                    {bindLabel(layerBind(l))}
                  </button>
                ))}
              </div>
              {selectedLayer && selectedBind && selectedBind !== 'custom' && (
                <div className="rounded-lg border border-dashed border-slate-300 bg-white px-3 py-2 text-sm text-slate-800">
                  <span className="text-xs text-slate-500">当前文案 · </span>
                  {layerDisplayText(selectedLayer, title, subtitle) || '（空）'}
                </div>
              )}
            </div>
          )}

          <div className="rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <span className="text-xs text-[var(--muted)]">额外装饰</span>
              <div className="flex flex-wrap gap-1">
                <MiniBtn onClick={() => addExtraLayer('text')}>+ 文本</MiniBtn>
                <MiniBtn onClick={() => addExtraLayer('tag')}>+ 标签</MiniBtn>
                <MiniBtn onClick={() => addExtraLayer('image')}>+ 图片</MiniBtn>
              </div>
            </div>
            {extraLayers.length === 0 ? (
              <p className="text-xs text-[var(--muted)] opacity-70">
                文本（带描边）、标签（白底胶囊）、图片贴纸，均可拖拽与删除
              </p>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {extraLayers.map((l) => (
                  <div
                    key={l.id}
                    className={`inline-flex items-center gap-0.5 rounded-md border text-xs ${
                      selectedLayerId === l.id
                        ? 'border-[var(--accent)] bg-[var(--select-bg)]'
                        : 'border-[var(--border)] bg-[var(--panel)]'
                    }`}
                  >
                    <button
                      onClick={() => setSelectedLayerId(l.id)}
                      className={`px-2 py-1 ${
                        selectedLayerId === l.id ? 'text-[var(--accent)]' : 'text-[var(--text)]'
                      }`}
                    >
                      {l.label}
                      <span className="ml-1 opacity-50">({extraKindLabel(extraKind(l))})</span>
                    </button>
                    <button
                      type="button"
                      title="删除"
                      onClick={(e) => removeLayer(l.id, e)}
                      className="px-1.5 py-1 text-red-400 hover:bg-red-500/10 hover:text-red-500"
                    >
                      ×
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3 space-y-2">
            <Field label="模板名称">
              <input
                value={active.name}
                onChange={(e) => patch({ ...active, name: e.target.value })}
                className={FIELD_INPUT}
              />
            </Field>
            <Field label="人像抠图">
              <label className="flex items-center gap-2 text-xs text-[var(--text)]">
                <input
                  type="checkbox"
                  checked={!!active.subject?.enabled}
                  onChange={(e) =>
                    patch({
                      ...active,
                      subject: {
                        ...(active.subject || defaultSubject()),
                        enabled: e.target.checked,
                      },
                    })
                  }
                />
                启用（模糊底 + 可拖拽人像，预览即时改）
              </label>
              {needRembgInstall && (
                <div className="mt-2 flex flex-wrap items-center gap-2 rounded-lg border border-amber-400/40 bg-amber-50 px-2.5 py-2 text-xs text-amber-950 dark:bg-amber-950/30 dark:text-amber-100">
                  <span>首次未装抠图组件。点下方一键安装（约数百 MB，装完后重新启用预览）。</span>
                  <ActionBtn
                    primary
                    disabled={!!busy}
                    onClick={() => {
                      void (async () => {
                        setBusy('安装抠图')
                        setLog('正在安装 rembg… 请到任务中心看进度')
                        try {
                          const outcome = await jobQueue.enqueue({
                            type: 'engine_install',
                            title: '安装封面抠图 rembg',
                            force: true,
                            priority: 20,
                            payload: { engine: 'rembg' },
                          })
                          jobQueue.setCenterOpen(true)
                          setLog(
                            outcome.ok
                              ? '已加入任务中心安装 rembg，完成后请再开关一次「人像抠图」'
                              : outcome.message || '安装任务未能加入',
                          )
                          if (outcome.ok) setNeedRembgInstall(false)
                        } catch (err) {
                          setLog(err instanceof Error ? err.message : String(err))
                        } finally {
                          setBusy('')
                        }
                      })()
                    }}
                  >
                    {busy === '安装抠图' ? '安装中…' : '一键安装抠图组件'}
                  </ActionBtn>
                </div>
              )}
            </Field>
            {active.subject?.enabled && (
              <>
                <Field label={`人像水平 ${((active.subject.x_offset ?? 0) * 100).toFixed(0)}%`}>
                  <input
                    type="range"
                    min={-25}
                    max={25}
                    value={Math.round((active.subject.x_offset ?? -0.06) * 100)}
                    onChange={(e) =>
                      patchSubject({ x_offset: Number(e.target.value) / 100 })
                    }
                    className="w-full"
                  />
                </Field>
                <Field label={`人像垂直 ${((active.subject.y_offset ?? 0) * 100).toFixed(0)}%`}>
                  <input
                    type="range"
                    min={-15}
                    max={20}
                    value={Math.round((active.subject.y_offset ?? 0.08) * 100)}
                    onChange={(e) =>
                      patchSubject({ y_offset: Number(e.target.value) / 100 })
                    }
                    className="w-full"
                  />
                </Field>
                <Field label={`人像大小 ${Math.round((active.subject.fill_ratio ?? 0.5) * 100)}%`}>
                  <input
                    type="range"
                    min={28}
                    max={85}
                    value={Math.round((active.subject.fill_ratio ?? 0.5) * 100)}
                    onChange={(e) =>
                      patchSubject({ fill_ratio: Number(e.target.value) / 100 })
                    }
                    className="w-full"
                  />
                </Field>
                <Field label="背景">
                  <select
                    value={active.subject.bg_mode}
                    onChange={(e) =>
                      patch({
                        ...active,
                        subject: {
                          ...(active.subject || defaultSubject()),
                          bg_mode: e.target.value as CoverSubject['bg_mode'],
                        },
                      })
                    }
                    className={FIELD_INPUT}
                  >
                    <option value="blur">高斯模糊</option>
                    <option value="original">保留原图</option>
                    <option value="white">纯白</option>
                    <option value="black">纯黑</option>
                  </select>
                </Field>
                <Field label={`模糊半径 ${active.subject.blur_radius}`}>
                  <input
                    type="range"
                    min={4}
                    max={80}
                    value={active.subject.blur_radius}
                    onChange={(e) =>
                      patch({
                        ...active,
                        subject: {
                          ...(active.subject || defaultSubject()),
                          blur_radius: Number(e.target.value),
                        },
                      })
                    }
                    className="w-full"
                  />
                </Field>
                <Field label="人像描边">
                  <select
                    value={active.subject.outline}
                    onChange={(e) =>
                      patch({
                        ...active,
                        subject: {
                          ...(active.subject || defaultSubject()),
                          outline: e.target.value as CoverSubject['outline'],
                        },
                      })
                    }
                    className={FIELD_INPUT}
                  >
                    <option value="none">无</option>
                    <option value="solid">实线描边</option>
                    <option value="dashed">虚线描边</option>
                    <option value="glow">外发光</option>
                  </select>
                </Field>
                {active.subject.outline !== 'none' && (
                  <Field label="描边颜色">
                    <input
                      type="color"
                      value={active.subject.outline_color}
                      onChange={(e) =>
                        patch({
                          ...active,
                          subject: {
                            ...(active.subject || defaultSubject()),
                            outline_color: e.target.value,
                            glow_color: e.target.value,
                          },
                        })
                      }
                      className="h-8 w-full cursor-pointer rounded border border-[var(--border)] bg-transparent"
                    />
                  </Field>
                )}
              </>
            )}
            <Field label="背景遮罩">
              <select
                value={active.background.overlay}
                onChange={(e) =>
                  patch({
                    ...active,
                    background: {
                      ...active.background,
                      overlay: e.target.value as CoverTemplate['background']['overlay'],
                    },
                  })
                }
                className={FIELD_INPUT}
              >
                {OVERLAYS.map((o) => (
                  <option key={o} value={o}>
                    {OVERLAY_LABELS[o]}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={`遮罩透明度 ${active.background.overlay_alpha}`}>
              <input
                type="range"
                min={0}
                max={255}
                value={active.background.overlay_alpha}
                onChange={(e) =>
                  patch({
                    ...active,
                    background: { ...active.background, overlay_alpha: Number(e.target.value) },
                  })
                }
                className="w-full"
              />
            </Field>
          </div>

          {selectedLayer && (
            <div className="rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3 space-y-2">
              <div className="text-xs font-medium text-[var(--accent)]">
                {selectedBind === 'custom'
                  ? `装饰层 · ${extraKindLabel(selectedExtraKind!)}`
                  : `${bindLabel(selectedBind!)}样式`}
              </div>

              {selectedBind === 'custom' && (
                <>
                  <Field label="层名称">
                    <input
                      value={selectedLayer.label}
                      onChange={(e) => patchLayer(selectedLayer.id, { label: e.target.value })}
                      className={FIELD_INPUT}
                    />
                  </Field>

                  {selectedExtraKind === 'image' ? (
                    <>
                      <Field label="装饰图片（本地 / 链接 / 素材中心 · 支持 GIF）">
                        <input
                          ref={imageInputRef}
                          type="file"
                          accept="image/png,image/jpeg,image/webp,image/gif,.gif,.png,.jpg,.jpeg,.webp"
                          className="hidden"
                          onChange={(e) => {
                            const f = e.target.files?.[0]
                            if (f) void uploadLayerImage(selectedLayer.id, f)
                            e.target.value = ''
                          }}
                        />
                        <div className="flex flex-wrap gap-2">
                          <button
                            type="button"
                            disabled={!!busy}
                            onClick={() => imageInputRef.current?.click()}
                            className="rounded-lg border border-dashed border-[var(--border)] bg-[var(--panel)] px-3 py-2 text-xs hover:border-[var(--accent)] disabled:opacity-50"
                          >
                            {busy === '上传图片' ? '上传中…' : '本地上传（含 GIF）'}
                          </button>
                          <button
                            type="button"
                            disabled={!!busy}
                            onClick={() => setAssetPickerOpen(true)}
                            className="rounded-lg border border-[var(--select-border)] bg-[var(--select-bg)] px-3 py-2 text-xs text-[var(--accent)] disabled:opacity-50"
                          >
                            素材中心
                          </button>
                        </div>
                        <div className="mt-2 flex gap-2">
                          <input
                            value={imageUrlDraft}
                            onChange={(e) => setImageUrlDraft(e.target.value)}
                            placeholder="https://… 图片或 GIF 链接"
                            className={FIELD_INPUT}
                          />
                          <button
                            type="button"
                            disabled={!!busy || !imageUrlDraft.trim()}
                            onClick={() => void applyImageUrl(selectedLayer.id, imageUrlDraft)}
                            className="shrink-0 rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs hover:bg-[var(--panel)] disabled:opacity-50"
                          >
                            {busy === '拉取图片' ? '拉取中…' : '导入链接'}
                          </button>
                        </div>
                      </Field>
                      {selectedLayer.image_src && (
                        <img
                          src={coverImageDisplaySrc(selectedLayer.image_src) || ''}
                          alt="预览"
                          className="max-h-24 rounded border border-[var(--border)] object-contain"
                        />
                      )}
                      <Field label={`宽度 ${((selectedLayer.width_ratio ?? 0.2) * 100).toFixed(0)}%`}>
                        <input
                          type="range"
                          min={0.05}
                          max={0.8}
                          step={0.01}
                          value={selectedLayer.width_ratio ?? 0.2}
                          onChange={(e) =>
                            patchLayer(selectedLayer.id, { width_ratio: Number(e.target.value) })
                          }
                          className="w-full"
                        />
                      </Field>
                    </>
                  ) : (
                    <>
                      <Field label={selectedExtraKind === 'tag' ? '标签文字' : '装饰文字'}>
                        <input
                          value={selectedLayer.text}
                          onChange={(e) => patchLayer(selectedLayer.id, { text: e.target.value })}
                          className={FIELD_INPUT}
                          placeholder="如：热门、干货、必看"
                        />
                      </Field>
                      {selectedExtraKind === 'tag' && (
                        <Field label="标签底色">
                          <input
                            type="color"
                            value={selectedLayer.pill_color || '#FFFFFF'}
                            onChange={(e) => patchLayer(selectedLayer.id, { pill_color: e.target.value })}
                            className="h-8 w-full rounded"
                          />
                        </Field>
                      )}
                    </>
                  )}

                  <button
                    type="button"
                    onClick={() => removeLayer(selectedLayer.id)}
                    className="text-xs text-red-400 hover:underline"
                  >
                    删除此装饰层
                  </button>
                </>
              )}

              <div className="grid grid-cols-2 gap-2">
                <Field label={`X ${(selectedLayer.x * 100).toFixed(0)}%`}>
                  <input
                    type="range"
                    min={0}
                    max={1}
                    step={0.01}
                    value={selectedLayer.x}
                    onChange={(e) => patchLayer(selectedLayer.id, { x: Number(e.target.value) })}
                    className="w-full"
                  />
                </Field>
                <Field label={`Y ${(selectedLayer.y * 100).toFixed(0)}%`}>
                  <input
                    type="range"
                    min={0}
                    max={1}
                    step={0.01}
                    value={selectedLayer.y}
                    onChange={(e) => patchLayer(selectedLayer.id, { y: Number(e.target.value) })}
                    className="w-full"
                  />
                </Field>
              </div>

              {selectedLayer.type !== 'image' && (
                <>
                  <Field label={`字号 ${(selectedLayer.font_size_ratio * 100).toFixed(1)}%（仅滑条调节）`}>
                    <input
                      type="range"
                      min={0.02}
                      max={0.18}
                      step={0.005}
                      value={selectedLayer.font_size_ratio}
                      onChange={(e) =>
                        patchLayer(selectedLayer.id, { font_size_ratio: Number(e.target.value) })
                      }
                      className="w-full"
                    />
                  </Field>
                  <Field label={`倾斜 ${Math.round(selectedLayer.rotation || 0)}°`}>
                    <input
                      type="range"
                      min={-30}
                      max={30}
                      step={1}
                      value={selectedLayer.rotation || 0}
                      onChange={(e) =>
                        patchLayer(selectedLayer.id, { rotation: Number(e.target.value) })
                      }
                      className="w-full"
                    />
                  </Field>
                  <p className="text-[10px] text-[var(--muted)]">
                    预览框四角拖拽只改文字展示宽高，不会改字号。
                  </p>
                  <Field label="排版">
                    <select
                      value={selectedLayer.writing_mode || 'horizontal'}
                      onChange={(e) =>
                        patchLayer(selectedLayer.id, {
                          writing_mode: e.target.value as 'horizontal' | 'vertical',
                        })
                      }
                      className={FIELD_INPUT}
                    >
                      <option value="horizontal">横排</option>
                      <option value="vertical">竖排</option>
                    </select>
                  </Field>
                  {selectedExtraKind !== 'tag' && (
                    <Field label="文字特效">
                      <select
                        value={selectedLayer.effect}
                        onChange={(e) =>
                          patchLayer(selectedLayer.id, {
                            effect: e.target.value as CoverLayer['effect'],
                          })
                        }
                        className={FIELD_INPUT}
                      >
                        {EFFECTS.filter((ef) => ef !== 'pill').map((ef) => (
                          <option key={ef} value={ef}>
                            {ef}
                          </option>
                        ))}
                      </select>
                    </Field>
                  )}
                  <div className="grid grid-cols-2 gap-2">
                    <Field label="文字颜色">
                      <input
                        type="color"
                        value={selectedLayer.color}
                        onChange={(e) => patchLayer(selectedLayer.id, { color: e.target.value })}
                        className="h-8 w-full rounded"
                      />
                    </Field>
                    <Field label="描边颜色">
                      <input
                        type="color"
                        value={selectedLayer.stroke_color}
                        onChange={(e) => patchLayer(selectedLayer.id, { stroke_color: e.target.value })}
                        className="h-8 w-full rounded"
                      />
                    </Field>
                  </div>
                  {selectedExtraKind !== 'tag' && (
                    <Field label={`描边粗细 ${selectedLayer.stroke_width}`}>
                      <input
                        type="range"
                        min={0}
                        max={8}
                        step={1}
                        value={selectedLayer.stroke_width}
                        onChange={(e) =>
                          patchLayer(selectedLayer.id, { stroke_width: Number(e.target.value) })
                        }
                        className="w-full"
                      />
                    </Field>
                  )}
                </>
              )}
            </div>
          )}
        </div>
  )

  if (embedded) {
    return (
      <div className="space-y-4">
        <div className="sticky top-0 z-20 rounded-xl border border-[var(--border)] bg-[var(--panel)]/95 p-3 shadow-sm backdrop-blur">
          <p className="mb-2 text-xs font-medium text-[var(--text)]">封面操作</p>
          {exportRow}
        </div>
        {templateLibrary}
        {coverSettings}
        {log && (
          <pre className="max-h-24 overflow-auto rounded-xl bg-[var(--bg)] p-3 text-xs text-[var(--muted)]">
            {log}
          </pre>
        )}
        <CoverFramePickerModal
          open={framePickerOpen}
          sources={sources}
          initialSourceId={activeSource?.id}
          initialTime={frameTime}
          confirming={busy === '抽帧'}
          onClose={() => setFramePickerOpen(false)}
          onConfirm={({ videoPath, sourceId, timeSec }) => {
            setFrameSourceId(sourceId)
            setFrameTime(timeSec)
            void extractFrame(timeSec, videoPath).then(() => setFramePickerOpen(false))
          }}
        />
        <AssetPickerModal
          open={assetPickerOpen}
          onClose={() => setAssetPickerOpen(false)}
          mediaKind="image"
          title="从素材中心选封面装饰图"
          subtitle="支持图片与 GIF · 选中后贴到当前装饰层"
          onPick={(asset) => {
            if (selectedLayer && layerBind(selectedLayer) === 'custom' && extraKind(selectedLayer) === 'image') {
              applyAssetImage(selectedLayer.id, asset)
            } else {
              setLog('请先选中一个图片装饰层')
              setAssetPickerOpen(false)
            }
          }}
        />
      </div>
    )
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(280px,360px)]">
      <Panel title="封面编辑器">
        <div className="space-y-3">
          {templateLibrary}
          {inlinePreview}
          {log && (
            <pre className="max-h-24 overflow-auto rounded-xl bg-[var(--bg)] p-3 text-xs text-[var(--muted)]">
              {log}
            </pre>
          )}
        </div>
      </Panel>
      <Panel title="封面设置">{coverSettings}</Panel>
      <CoverFramePickerModal
        open={framePickerOpen}
        sources={sources}
        initialSourceId={activeSource?.id}
        initialTime={frameTime}
        confirming={busy === '抽帧'}
        onClose={() => setFramePickerOpen(false)}
        onConfirm={({ videoPath, sourceId, timeSec }) => {
          setFrameSourceId(sourceId)
          setFrameTime(timeSec)
          void extractFrame(timeSec, videoPath).then(() => setFramePickerOpen(false))
        }}
      />
      <AssetPickerModal
        open={assetPickerOpen}
        onClose={() => setAssetPickerOpen(false)}
        mediaKind="image"
        title="从素材中心选封面装饰图"
        subtitle="支持图片与 GIF · 选中后贴到当前装饰层"
        onPick={(asset) => {
          if (selectedLayer && layerBind(selectedLayer) === 'custom' && extraKind(selectedLayer) === 'image') {
            applyAssetImage(selectedLayer.id, asset)
          } else {
            setLog('请先选中一个图片装饰层')
            setAssetPickerOpen(false)
          }
        }}
      />
    </div>
  )
}

function Field({
  label,
  children,
  light,
}: {
  label: string
  children: React.ReactNode
  light?: boolean
}) {
  return (
    <label className={`block text-xs ${light ? 'font-medium text-slate-600' : 'text-[var(--muted)]'}`}>
      {label}
      <div className="mt-1">{children}</div>
    </label>
  )
}

function MiniBtn({ children, onClick }: { children: React.ReactNode; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="rounded border border-[var(--border)] bg-[var(--panel)] px-2 py-0.5 text-[11px] text-[var(--accent)] hover:bg-[var(--select-bg)]"
    >
      {children}
    </button>
  )
}

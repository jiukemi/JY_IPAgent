import { useCallback, useEffect, useRef, useState } from 'react'

export type CropBox = { x: number; y: number; w: number; h: number }

type Props = {
  open: boolean
  frameUrl: string | null
  initialCrop?: CropBox | null
  busy?: boolean
  onClose: () => void
  onAuto: () => Promise<CropBox | null> | CropBox | null
  onConfirm: (crop: CropBox, previewDataUrl: string) => void
}

function clampCrop(c: CropBox): CropBox {
  const w = Math.max(0.08, Math.min(1, c.w))
  const h = Math.max(0.08, Math.min(1, c.h))
  return {
    x: Math.max(0, Math.min(1 - w, c.x)),
    y: Math.max(0, Math.min(1 - h, c.y)),
    w,
    h,
  }
}

/** Force 1:1 in pixel space relative to displayed image box. */
function toSquareNorm(
  x0: number,
  y0: number,
  x1: number,
  y1: number,
  natW: number,
  natH: number,
): CropBox {
  const left = Math.min(x0, x1)
  const top = Math.min(y0, y1)
  const right = Math.max(x0, x1)
  const bottom = Math.max(y0, y1)
  let pw = Math.max(8, (right - left) * natW)
  let ph = Math.max(8, (bottom - top) * natH)
  const side = Math.max(pw, ph)
  pw = side
  ph = side
  let px = ((left + right) / 2) * natW - side / 2
  let py = ((top + bottom) / 2) * natH - side / 2
  px = Math.max(0, Math.min(natW - side, px))
  py = Math.max(0, Math.min(natH - side, py))
  return clampCrop({
    x: px / natW,
    y: py / natH,
    w: side / natW,
    h: side / natH,
  })
}

export function LecturerCropModal({
  open,
  frameUrl,
  initialCrop,
  busy,
  onClose,
  onAuto,
  onConfirm,
}: Props) {
  const imgRef = useRef<HTMLImageElement>(null)
  const [crop, setCrop] = useState<CropBox | null>(initialCrop ?? null)
  const dragRef = useRef<{
    startX: number
    startY: number
    active: boolean
  } | null>(null)
  const [draft, setDraft] = useState<CropBox | null>(null)
  const [autoError, setAutoError] = useState('')

  // Only seed when modal opens — do NOT reset when frameUrl changes after「一键自动」
  useEffect(() => {
    if (!open) return
    setCrop(initialCrop ?? null)
    setDraft(null)
    setAutoError('')
    // eslint-disable-next-line react-hooks/exhaustive-deps -- intentionally open-only
  }, [open])

  const relPos = useCallback((e: React.MouseEvent | MouseEvent) => {
    const img = imgRef.current
    if (!img) return null
    const rect = img.getBoundingClientRect()
    const x = (e.clientX - rect.left) / rect.width
    const y = (e.clientY - rect.top) / rect.height
    return {
      x: Math.max(0, Math.min(1, x)),
      y: Math.max(0, Math.min(1, y)),
      natW: img.naturalWidth || 1,
      natH: img.naturalHeight || 1,
    }
  }, [])

  const onPointerDown = (e: React.MouseEvent) => {
    const p = relPos(e)
    if (!p) return
    e.preventDefault()
    dragRef.current = { startX: p.x, startY: p.y, active: true }
    setDraft(toSquareNorm(p.x, p.y, p.x, p.y, p.natW, p.natH))
  }

  useEffect(() => {
    if (!open) return
    const move = (e: MouseEvent) => {
      if (!dragRef.current?.active) return
      const p = relPos(e)
      if (!p) return
      setDraft(
        toSquareNorm(dragRef.current.startX, dragRef.current.startY, p.x, p.y, p.natW, p.natH),
      )
    }
    const up = (e: MouseEvent) => {
      if (!dragRef.current?.active) return
      const p = relPos(e)
      if (p) {
        const box = toSquareNorm(
          dragRef.current.startX,
          dragRef.current.startY,
          p.x,
          p.y,
          p.natW,
          p.natH,
        )
        setCrop(box)
        setDraft(null)
      }
      dragRef.current = null
    }
    window.addEventListener('mousemove', move)
    window.addEventListener('mouseup', up)
    return () => {
      window.removeEventListener('mousemove', move)
      window.removeEventListener('mouseup', up)
    }
  }, [open, relPos])

  const confirm = () => {
    const box = draft || crop
    const img = imgRef.current
    if (!box || !img) return
    const canvas = document.createElement('canvas')
    const sx = Math.round(box.x * img.naturalWidth)
    const sy = Math.round(box.y * img.naturalHeight)
    const sw = Math.round(box.w * img.naturalWidth)
    const sh = Math.round(box.h * img.naturalHeight)
    canvas.width = Math.max(2, sw)
    canvas.height = Math.max(2, sh)
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    ctx.drawImage(img, sx, sy, sw, sh, 0, 0, canvas.width, canvas.height)
    onConfirm(box, canvas.toDataURL('image/jpeg', 0.9))
  }

  if (!open) return null
  const shown = draft || crop

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 p-4">
      <div className="max-h-[92vh] w-full max-w-3xl overflow-auto rounded-2xl border border-[var(--border)] bg-[var(--panel)] p-4 shadow-xl">
        <div className="mb-3 flex items-start justify-between gap-3">
          <div>
            <p className="text-sm font-medium text-[var(--text)]">选择口播 1:1 区域</p>
            <p className="mt-1 text-[10px] text-[var(--muted)]">
              在画面上拖拽框选（强制正方形）；或点「一键自动」后确认。未确认前成片仍用整帧口播。
            </p>
          </div>
          <button type="button" className="text-xs text-[var(--muted)] underline" onClick={onClose}>
            关闭
          </button>
        </div>
        <div className="flex justify-center overflow-auto rounded-xl border border-[var(--border)] bg-[#141820] p-2">
          {frameUrl ? (
            <div className="relative inline-block max-w-full">
              <img
                ref={imgRef}
                src={frameUrl}
                alt="口播帧"
                draggable={false}
                onMouseDown={onPointerDown}
                className="max-h-[55vh] w-auto max-w-full select-none cursor-crosshair object-contain"
              />
              {shown && (
                <div
                  className="pointer-events-none absolute border-2 border-[var(--accent)] bg-[var(--accent)]/20"
                  style={{
                    left: `${shown.x * 100}%`,
                    top: `${shown.y * 100}%`,
                    width: `${shown.w * 100}%`,
                    height: `${shown.h * 100}%`,
                  }}
                />
              )}
            </div>
          ) : (
            <p className="p-8 text-center text-xs text-[var(--muted)]">加载口播帧…</p>
          )}
        </div>
        {autoError && (
          <p className="mt-2 text-[11px] text-amber-400">{autoError}</p>
        )}
        <div className="mt-4 flex flex-wrap justify-end gap-2">
          <button
            type="button"
            disabled={busy || !frameUrl}
            onClick={() => {
              void (async () => {
                setAutoError('')
                try {
                  const box = await onAuto()
                  if (box) {
                    setCrop(clampCrop(box))
                    setDraft(null)
                  } else {
                    setAutoError('自动识别未返回区域，可手动拖拽框选后确认')
                  }
                } catch (err) {
                  setAutoError(err instanceof Error ? err.message : String(err))
                }
              })()
            }}
            className="rounded-lg border border-[var(--accent)] px-3 py-1.5 text-xs text-[var(--accent)] disabled:opacity-40"
          >
            {busy ? '自动识别中…' : '一键自动 1:1'}
          </button>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs"
          >
            取消
          </button>
          <button
            type="button"
            disabled={!shown}
            onClick={confirm}
            className="rounded-lg bg-[var(--accent)] px-3 py-1.5 text-xs text-white disabled:opacity-40"
          >
            确认裁切
          </button>
        </div>
      </div>
    </div>
  )
}

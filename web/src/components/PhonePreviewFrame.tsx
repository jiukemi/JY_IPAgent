import { forwardRef, type ReactNode, type VideoHTMLAttributes } from 'react'

/** ASS 烧录字号以 1080 宽竖屏为基准 */
export const PHONE_REF_WIDTH = 1080
export const PHONE_PREVIEW_WIDTH = 270

/** 9:16 手机框内：横/竖屏皆不裁切；横屏宽 100%、高度自适应（上下黑边） */
export const PHONE_FIT_VIDEO_CLASS =
  'absolute inset-0 h-full w-full bg-black object-contain object-center'

export function subtitlePreviewFontPx(fontSize: number, previewWidth = PHONE_PREVIEW_WIDTH): number {
  return Math.max(10, Math.round(fontSize * (previewWidth / PHONE_REF_WIDTH)))
}

type Props = {
  children: ReactNode
  label?: string
  maxWidth?: number
  className?: string
}

export function PhonePreviewFrame({
  children,
  label,
  maxWidth = PHONE_PREVIEW_WIDTH,
  className = '',
}: Props) {
  return (
    <div className={className}>
      {label && <p className="mb-1 text-xs text-[var(--muted)]">{label}</p>}
      <div className="mx-auto w-full" style={{ maxWidth }}>
        <div className="relative aspect-[9/16] overflow-hidden rounded-2xl border border-[var(--border)] bg-black shadow-lg">
          {children}
        </div>
      </div>
    </div>
  )
}

/** 竖屏手机框内播放：横屏素材 letterbox，竖屏素材完整可见 */
export const PhoneFitVideo = forwardRef<HTMLVideoElement, VideoHTMLAttributes<HTMLVideoElement>>(
  function PhoneFitVideo({ className = '', playsInline = true, ...rest }, ref) {
    return (
      <video
        ref={ref}
        playsInline={playsInline}
        className={`${PHONE_FIT_VIDEO_CLASS} ${className}`.trim()}
        {...rest}
      />
    )
  },
)

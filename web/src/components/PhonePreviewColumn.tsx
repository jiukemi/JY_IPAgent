import type { ReactNode } from 'react'

import { Panel } from '../pages/ScriptPage'

export type PreviewAspect = '9:16' | '16:9'

type SlotProps = {
  label?: string
  note?: string
  aspect?: PreviewAspect
  onExpand?: () => void
  children: ReactNode
}

export function PhonePreviewSlot({ label, note, aspect = '9:16', onExpand, children }: SlotProps) {
  const landscape = aspect === '16:9'
  const frameClass = `relative block w-full overflow-hidden rounded-2xl border border-[var(--border)] bg-[#141820] shadow-lg ${
    landscape ? 'aspect-video' : 'aspect-[9/16]'
  }`

  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center justify-between gap-2">
        {label && <p className="text-[11px] font-medium text-[var(--text)]">{label}</p>}
        {onExpand && (
          <button
            type="button"
            onClick={onExpand}
            className="text-[10px] text-[var(--accent)] underline"
          >
            弹框放大
          </button>
        )}
      </div>
      <div className={`mx-auto w-full ${landscape ? 'max-w-[360px]' : 'max-w-[280px]'}`}>
        {/* Must be a div (not disabled button) so children can receive drag/mouse events */}
        {onExpand ? (
          <button type="button" onClick={onExpand} className={`${frameClass} cursor-zoom-in text-left hover:brightness-110`}>
            {children}
          </button>
        ) : (
          <div className={frameClass}>{children}</div>
        )}
      </div>
      {note && <p className="text-[10px] leading-relaxed text-[var(--muted)]">{note}</p>}
    </div>
  )
}

type ColumnProps = {
  title?: string
  aspect?: PreviewAspect
  children: ReactNode
  className?: string
}

export function PhonePreviewColumn({
  title,
  aspect = '9:16',
  children,
  className = '',
}: ColumnProps) {
  const resolvedTitle = title ?? (aspect === '16:9' ? '横屏预览 16:9' : '竖屏预览 9:16')
  return (
    <Panel title={resolvedTitle} className={`lg:sticky lg:top-4 lg:self-start ${className}`}>
      <div className="flex flex-col gap-5">{children}</div>
    </Panel>
  )
}

import { useRef, useState, type ReactNode } from 'react'
import { formatFileSize } from '../utils/mediaFileMeta'

type Props = {
  file: File | null
  onFile: (file: File | null) => void
  accept: string
  icon?: string
  emptyTitle: string
  emptyHint: string
  chooseLabel?: string
  replaceLabel?: string
  disabled?: boolean
  meta?: ReactNode
  accent?: boolean
}

export function FileDropZone({
  file,
  onFile,
  accept,
  icon = '📁',
  emptyTitle,
  emptyHint,
  chooseLabel = '选择文件',
  replaceLabel = '更换文件',
  disabled = false,
  meta,
  accent = false,
}: Props) {
  const [dragOver, setDragOver] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const pick = (f: File | null) => {
    if (!f || disabled) return
    onFile(f)
  }

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    if (disabled) return
    pick(e.dataTransfer.files?.[0] || null)
  }

  const clear = (e: React.MouseEvent) => {
    e.stopPropagation()
    onFile(null)
    if (inputRef.current) inputRef.current.value = ''
  }

  const openPicker = (e?: React.MouseEvent) => {
    e?.stopPropagation()
    if (!disabled) inputRef.current?.click()
  }

  const borderClass = dragOver
    ? 'border-[var(--accent)] bg-[var(--select-bg)]'
    : file
      ? accent
        ? 'border-emerald-500/50 bg-emerald-500/5'
        : 'border-[var(--accent)]/45 bg-[var(--select-bg)]/40'
      : accent
        ? 'border-[var(--accent)]/40 bg-[var(--bg)] hover:border-[var(--accent)] hover:bg-[var(--select-bg)]'
        : 'border-[var(--border)] bg-[var(--bg)] hover:border-[var(--accent)] hover:bg-[var(--panel)]'

  return (
    <div
      role="button"
      tabIndex={disabled ? -1 : 0}
      aria-disabled={disabled}
      onDragOver={(e) => {
        e.preventDefault()
        if (!disabled) setDragOver(true)
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={onDrop}
      onClick={() => openPicker()}
      onKeyDown={(e) => {
        if (!disabled && (e.key === 'Enter' || e.key === ' ')) {
          e.preventDefault()
          openPicker()
        }
      }}
      className={`cursor-pointer rounded-2xl border-2 border-dashed px-5 py-8 text-center transition ${borderClass} ${
        disabled ? 'cursor-not-allowed opacity-60' : ''
      }`}
    >
      <div className="text-4xl">{file ? '✅' : icon}</div>
      <p className="mt-3 text-base font-semibold text-[var(--text)]">
        {file ? file.name : emptyTitle}
      </p>
      <p className="mt-1 text-xs text-[var(--muted)]">{emptyHint}</p>

      <button
        type="button"
        disabled={disabled}
        onClick={openPicker}
        className="btn-primary mt-4 inline-flex items-center gap-2 rounded-xl px-6 py-3 text-sm font-semibold shadow-md disabled:opacity-50"
      >
        <span className="text-lg">📂</span>
        {file ? replaceLabel : chooseLabel}
      </button>

      {file && (
        <div className="mt-4 space-y-2 rounded-xl bg-[var(--panel)] px-4 py-3 text-left text-xs">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-[var(--accent)]">
              已选 · {formatFileSize(file.size)}
            </span>
            <button
              type="button"
              onClick={clear}
              className="rounded-lg border border-[var(--border)] px-2 py-1 text-[10px] text-[var(--muted)] hover:border-red-400/50 hover:text-red-500"
            >
              清除重选
            </button>
          </div>
          {meta}
        </div>
      )}

      <input
        ref={inputRef}
        type="file"
        accept={accept}
        className="hidden"
        disabled={disabled}
        onChange={(e) => pick(e.target.files?.[0] || null)}
      />
    </div>
  )
}

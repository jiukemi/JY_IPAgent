import { createPortal } from 'react-dom'

type Props = {
  open: boolean
  title: string
  message: string
  variant?: 'error' | 'warning' | 'success' | 'info'
  onClose: () => void
  /** When set, shows Cancel + confirm instead of single 「知道了」 */
  confirmLabel?: string
  cancelLabel?: string
  onConfirm?: () => void
  confirmBusy?: boolean
}

const panelStyles = {
  error: 'border-red-600/80 bg-red-50 dark:border-red-500/50 dark:bg-red-950/40',
  warning: 'border-amber-600/80 bg-amber-50 dark:border-amber-500/50 dark:bg-amber-950/40',
  success: 'border-emerald-600/80 bg-emerald-50 dark:border-emerald-500/50 dark:bg-emerald-950/40',
  info: 'border-[var(--border)] bg-[var(--panel-2)]',
}

const titleStyles = {
  error: 'text-red-900 dark:text-red-100',
  warning: 'text-amber-900 dark:text-amber-100',
  success: 'text-emerald-900 dark:text-emerald-100',
  info: 'text-[var(--text)]',
}

const bodyStyles = {
  error: 'text-red-800 dark:text-red-200/90',
  warning: 'text-amber-900 dark:text-amber-100/90',
  success: 'text-emerald-900 dark:text-emerald-100/90',
  info: 'text-[var(--muted)]',
}

function renderMessage(message: string, bodyClass: string) {
  const blocks = message.split(/\n\n+/).filter(Boolean)
  if (blocks.length <= 1) {
    return (
      <p className={`max-h-72 overflow-y-auto whitespace-pre-wrap text-sm leading-relaxed ${bodyClass}`}>
        {message}
      </p>
    )
  }
  return (
    <div className={`max-h-72 space-y-3 overflow-y-auto text-sm leading-relaxed ${bodyClass}`}>
      {blocks.map((block, i) => {
        const lines = block.split('\n')
        const isList = lines.some((l) => /^\d+\.\s/.test(l.trim()))
        if (isList) {
          return (
            <ul key={i} className="list-none space-y-1.5 pl-0">
              {lines.map((line, j) => (
                <li key={j} className={/^\d+\./.test(line.trim()) ? 'pl-1' : 'font-medium'}>
                  {line}
                </li>
              ))}
            </ul>
          )
        }
        return (
          <p key={i} className={i === 0 ? 'font-medium' : ''}>
            {block}
          </p>
        )
      })}
    </div>
  )
}

export function AlertModal({
  open,
  title,
  message,
  variant = 'info',
  onClose,
  confirmLabel,
  cancelLabel = '取消',
  onConfirm,
  confirmBusy = false,
}: Props) {
  if (!open || typeof document === 'undefined') return null

  const isConfirm = Boolean(confirmLabel && onConfirm)

  return createPortal(
    <div
      className="fixed inset-0 z-[80] flex items-center justify-center bg-black/50 p-4 backdrop-blur-[2px]"
      role="presentation"
    >
      <div
        role="alertdialog"
        aria-labelledby="alert-title"
        aria-modal="true"
        className={`w-full max-w-lg rounded-2xl border p-5 shadow-2xl ${panelStyles[variant]}`}
      >
        <div className="flex items-start gap-3">
          <span className="text-xl leading-none" aria-hidden>
            {variant === 'error' ? '⛔' : variant === 'warning' ? '⚠️' : variant === 'success' ? '✅' : 'ℹ️'}
          </span>
          <div className="min-w-0 flex-1">
            <h3 id="alert-title" className={`text-base font-bold ${titleStyles[variant]}`}>
              {title}
            </h3>
            <div className="mt-3">{renderMessage(message, bodyStyles[variant])}</div>
          </div>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          {isConfirm ? (
            <>
              <button
                type="button"
                disabled={confirmBusy}
                onClick={onClose}
                className="rounded-lg border border-[var(--border)] px-4 py-2 text-sm text-[var(--muted)] hover:bg-[var(--bg)] disabled:opacity-50"
              >
                {cancelLabel}
              </button>
              <button
                type="button"
                disabled={confirmBusy}
                onClick={() => onConfirm?.()}
                className="rounded-lg border border-red-700/50 bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-500 disabled:opacity-50"
              >
                {confirmBusy ? '处理中…' : confirmLabel}
              </button>
            </>
          ) : (
            <button
              type="button"
              onClick={onClose}
              className="btn-primary rounded-lg px-5 py-2 text-sm font-medium"
            >
              知道了
            </button>
          )}
        </div>
      </div>
    </div>,
    document.body,
  )
}

export function parseApiError(err: unknown, fallbackTitle = '操作失败'): { title: string; message: string } {
  const raw = err instanceof Error ? err.message : String(err)
  let message = raw.replace(/^400:\s*/, '').trim()
  if (message.startsWith('{')) {
    try {
      const j = JSON.parse(message) as { detail?: string }
      message = j.detail || message
    } catch {
      /* keep */
    }
  }
  const firstLine = message.split('\n')[0]?.trim() || fallbackTitle
  const title =
    firstLine.length <= 40 && !firstLine.includes('：')
      ? firstLine
      : fallbackTitle
  return { title, message }
}

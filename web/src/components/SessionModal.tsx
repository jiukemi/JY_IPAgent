import { useEffect, useState } from 'react'
import type { SessionItem } from '../types'

type Props = {
  open: boolean
  sessions: SessionItem[]
  currentPath: string
  onClose: () => void
  onSwitch: (path: string) => void
  onDelete: (path: string) => void
  onRename: (path: string, name: string) => void
  onNewSession: () => void
}

export function SessionModal({
  open,
  sessions,
  currentPath,
  onClose,
  onSwitch,
  onDelete,
  onRename,
  onNewSession,
}: Props) {
  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-4 backdrop-blur-[2px]"
      role="presentation"
    >
      <div
        className="ui-card flex max-h-[80vh] w-full max-w-lg flex-col overflow-hidden"
        role="dialog"
        aria-modal="true"
        aria-labelledby="session-modal-title"
      >
        <div className="flex items-center justify-between gap-3 border-b border-[var(--border)] px-5 py-4">
          <div className="min-w-0">
            <h2 id="session-modal-title" className="text-base font-semibold text-[var(--text)]">
              工作会话
            </h2>
            <p className="mt-0.5 text-xs text-[var(--muted)]">新建或切换当前制作会话</p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <button
              type="button"
              onClick={() => {
                onNewSession()
                onClose()
              }}
              className="btn-primary inline-flex items-center gap-1.5 rounded-xl px-3.5 py-2 text-xs font-semibold"
            >
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden>
                <path
                  d="M8 3v10M3 8h10"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                />
              </svg>
              新建会话
            </button>
            <button
              type="button"
              onClick={onClose}
              className="rounded-xl border border-[var(--border)] px-2.5 py-2 text-sm text-[var(--muted)] transition hover:bg-[var(--bg)] hover:text-[var(--text)]"
              aria-label="关闭"
            >
              ✕
            </button>
          </div>
        </div>

        <div className="overflow-y-auto p-4">
          {sessions.length === 0 ? (
            <div className="rounded-[var(--card-radius)] border border-dashed border-[var(--border)] bg-[var(--bg)] px-4 py-10 text-center">
              <p className="text-sm text-[var(--muted)]">还没有会话</p>
              <button
                type="button"
                onClick={() => {
                  onNewSession()
                  onClose()
                }}
                className="btn-primary mt-4 rounded-xl px-4 py-2 text-xs font-semibold"
              >
                创建第一个会话
              </button>
            </div>
          ) : (
            <ul className="space-y-2.5">
              {sessions.map((s) => (
                <SessionRow
                  key={s.path}
                  session={s}
                  active={s.path === currentPath}
                  onSwitch={() => {
                    onSwitch(s.path)
                    onClose()
                  }}
                  onDelete={() => onDelete(s.path)}
                  onRename={(name) => onRename(s.path, name)}
                />
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  )
}

function SessionRow({
  session,
  active,
  onSwitch,
  onDelete,
  onRename,
}: {
  session: SessionItem
  active: boolean
  onSwitch: () => void
  onDelete: () => void
  onRename: (name: string) => void
}) {
  const [name, setName] = useState(session.name)

  useEffect(() => setName(session.name), [session.name])

  return (
    <li
      className={`rounded-[var(--card-radius)] border p-3.5 transition ${
        active
          ? 'border-[var(--select-border)] bg-[var(--select-bg)] shadow-sm'
          : 'border-[var(--border)] bg-[var(--panel)] hover:border-[var(--select-border)]/60'
      }`}
    >
      <div className="flex flex-wrap items-start gap-2">
        <div className="min-w-0 flex-1 space-y-1.5">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            onBlur={() => name.trim() && name !== session.name && onRename(name.trim())}
            className="ui-input w-full px-2.5 py-1.5 text-sm font-medium"
            aria-label="会话名称"
          />
          <div className="flex flex-wrap items-center gap-1.5">
            {session.badges.map((b) => (
              <span
                key={b}
                className="rounded-full bg-[var(--badge-bg)] px-2 py-0.5 text-[10px] font-medium text-[var(--badge-text)]"
              >
                {b}
              </span>
            ))}
            <span className="text-[10px] text-[var(--muted)]">{session.created_at}</span>
          </div>
        </div>
        <div className="flex shrink-0 gap-1.5">
          {active ? (
            <span className="rounded-xl bg-[var(--accent)]/10 px-3 py-1.5 text-xs font-semibold text-[var(--accent)]">
              当前
            </span>
          ) : (
            <button
              type="button"
              onClick={onSwitch}
              className="btn-primary rounded-xl px-3 py-1.5 text-xs font-semibold"
            >
              打开
            </button>
          )}
          <button
            type="button"
            onClick={() => {
              if (window.confirm('确定删除该会话？')) onDelete()
            }}
            className="rounded-xl border border-red-200 px-3 py-1.5 text-xs font-medium text-red-600 transition hover:bg-red-50"
          >
            删除
          </button>
        </div>
      </div>
    </li>
  )
}

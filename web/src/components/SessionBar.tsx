import type { SessionItem } from '../types'
import type { ThemeId } from '../theme'
import { ThemeToggle } from './ThemeToggle'

type Props = {
  name: string
  path: string
  sessions: SessionItem[]
  theme: ThemeId
  activeJobCount?: number
  onThemeChange: (theme: ThemeId) => void
  onOpenSessions: () => void
  onOpenSettings: () => void
  onOpenAssets?: () => void
  onOpenTasks?: () => void
}

export function SessionBar({
  name,
  path: _path,
  sessions,
  theme,
  activeJobCount = 0,
  onThemeChange,
  onOpenSessions,
  onOpenSettings,
  onOpenAssets,
  onOpenTasks,
}: Props) {
  const count = sessions.length
  const chip =
    'rounded-xl border border-[var(--border)] bg-[var(--panel)] px-3 py-1.5 text-sm text-[var(--text)] shadow-sm transition hover:border-[var(--select-border)] hover:bg-[var(--select-bg)]'

  return (
    <header className="flex items-center justify-between gap-4 border-b border-[var(--border)] bg-[var(--panel)]/95 px-5 py-3 backdrop-blur-sm">
      <button
        type="button"
        onClick={onOpenSessions}
        title="管理会话 · 新建 / 切换"
        className="group flex min-w-0 max-w-[min(100%,28rem)] items-center gap-3 rounded-[var(--card-radius)] border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-left shadow-sm transition hover:border-[var(--select-border)] hover:bg-[var(--select-bg)]"
      >
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[var(--select-bg)] text-[var(--accent)]">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
            <path
              d="M4 7.5A2.5 2.5 0 0 1 6.5 5H14l2 2h1.5A2.5 2.5 0 0 1 20 9.5v7A2.5 2.5 0 0 1 17.5 19h-11A2.5 2.5 0 0 1 4 16.5v-9Z"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinejoin="round"
            />
          </svg>
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-[10px] font-medium uppercase tracking-wider text-[var(--muted)]">
            会话
          </span>
          <span className="block truncate text-sm font-semibold text-[var(--text)] group-hover:text-[var(--accent)]">
            {name || '未命名'}
          </span>
        </span>
        <span className="hidden shrink-0 items-center gap-1.5 sm:flex">
          <span className="rounded-full bg-[var(--badge-bg)] px-2 py-0.5 text-[10px] font-semibold text-[var(--badge-text)]">
            {count}
          </span>
          <svg
            width="14"
            height="14"
            viewBox="0 0 16 16"
            className="text-[var(--muted)] transition group-hover:text-[var(--accent)]"
            aria-hidden
          >
            <path
              d="M4 6l4 4 4-4"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
              fill="none"
            />
          </svg>
        </span>
      </button>

      <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
        <ThemeToggle theme={theme} onChange={onThemeChange} />
        <button type="button" onClick={onOpenAssets} className={chip}>
          素材中心
        </button>
        <button type="button" onClick={onOpenTasks} className={`relative ${chip}`}>
          任务中心
          {activeJobCount > 0 && (
            <span className="absolute -right-1.5 -top-1.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-[var(--accent)] px-1 text-[10px] font-bold text-[var(--accent-contrast)]">
              {activeJobCount > 9 ? '9+' : activeJobCount}
            </span>
          )}
        </button>
        <button
          type="button"
          onClick={onOpenSettings}
          className="btn-primary rounded-xl px-3.5 py-1.5 text-sm font-semibold"
        >
          设置
        </button>
      </div>
    </header>
  )
}

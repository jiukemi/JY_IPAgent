import { THEME_OPTIONS, type ThemeId } from '../theme'

type Props = {
  theme: ThemeId
  onChange: (theme: ThemeId) => void
}

export function ThemeToggle({ theme, onChange }: Props) {
  const active = THEME_OPTIONS.find((t) => t.id === theme)
  return (
    <label className="flex items-center gap-1.5 text-xs text-[var(--muted)]">
      <span className="hidden sm:inline">主题</span>
      <select
        value={theme}
        onChange={(e) => onChange(e.target.value as ThemeId)}
        title={active?.hint}
        className="max-w-[9.5rem] rounded-lg border border-[var(--border)] bg-[var(--panel)] px-2 py-1.5 text-xs text-[var(--text)]"
      >
        {THEME_OPTIONS.map((t) => (
          <option key={t.id} value={t.id}>
            {t.label}
          </option>
        ))}
      </select>
    </label>
  )
}

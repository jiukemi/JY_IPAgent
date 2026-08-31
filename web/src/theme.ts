export type ThemeId = 'light' | 'nord'

const STORAGE_KEY = 'agent-ui-theme-v2'

export const THEME_OPTIONS: { id: ThemeId; label: string; hint: string }[] = [
  { id: 'light', label: '暖橙系', hint: '浅灰底 · 白卡片 · 活力橙' },
  { id: 'nord', label: '北欧', hint: '冷灰 · 暖橙点缀' },
]

/** Themes removed from picker — map to warm-orange / nord. */
const LEGACY_THEME_MAP: Record<string, ThemeId> = {
  dark: 'light',
  'tokyo-night': 'light',
  dracula: 'light',
  catppuccin: 'nord',
}

export function getInitialTheme(): ThemeId {
  if (typeof window === 'undefined') return 'light'
  const saved = localStorage.getItem(STORAGE_KEY)
  if (saved && LEGACY_THEME_MAP[saved]) return LEGACY_THEME_MAP[saved]
  if (THEME_OPTIONS.some((t) => t.id === saved)) return saved as ThemeId
  return 'light'
}

export function applyTheme(theme: ThemeId) {
  document.documentElement.dataset.theme = theme
  localStorage.setItem(STORAGE_KEY, theme)
}

export type StylePackOption = { id: string; label: string }

type Props = {
  fonts: StylePackOption[]
  bgModes: StylePackOption[]
  remotionThemes?: StylePackOption[]
  fontId: string
  fontScale: number
  bgMode: string
  bgPrompt: string
  remotionTheme?: string
  onFontId: (id: string) => void
  onFontScale: (v: number) => void
  onBgMode: (id: string) => void
  onBgPrompt: (v: string) => void
  onRemotionTheme?: (id: string) => void
  /** Remotion belongs to publish burn-in — hide on scene Style Pack by default */
  showRemotion?: boolean
  compact?: boolean
}

/** Shared Style Pack knobs for Asset Center + Publish (scene cards). */
export function StylePackFields({
  fonts,
  bgModes,
  remotionThemes = [],
  fontId,
  fontScale,
  bgMode,
  bgPrompt,
  remotionTheme = 'off',
  onFontId,
  onFontScale,
  onBgMode,
  onBgPrompt,
  onRemotionTheme,
  showRemotion = false,
  compact,
}: Props) {
  const grid = compact ? 'grid gap-2 sm:grid-cols-2' : 'grid gap-2 sm:grid-cols-2 lg:grid-cols-3'
  return (
    <div className="space-y-2">
      <p className="text-[11px] font-medium text-[var(--text)]">高级样式（场景卡 · 与素材中心共用）</p>
      <div className={grid}>
        <label className="block text-[10px] text-[var(--muted)]">
          字体
          <select
            value={fontId}
            onChange={(e) => onFontId(e.target.value)}
            className="mt-1 w-full rounded border border-[var(--border)] bg-[var(--panel)] px-2 py-1.5 text-xs"
          >
            {(fonts.length ? fonts : [{ id: 'noto_sc', label: 'Noto 黑体' }]).map((f) => (
              <option key={f.id} value={f.id}>
                {f.label}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-[10px] text-[var(--muted)]">
          字号 {Math.round(fontScale * 100)}%
          <input
            type="range"
            min={70}
            max={160}
            step={5}
            value={Math.round(fontScale * 100)}
            onChange={(e) => onFontScale(Number(e.target.value) / 100)}
            className="mt-2 w-full"
          />
        </label>
        <label className="block text-[10px] text-[var(--muted)]">
          底图模式
          <select
            value={bgMode}
            onChange={(e) => onBgMode(e.target.value)}
            className="mt-1 w-full rounded border border-[var(--border)] bg-[var(--panel)] px-2 py-1.5 text-xs"
          >
            {(bgModes.length ? bgModes : [{ id: 'generative', label: '生成式底图' }]).map((b) => (
              <option key={b.id} value={b.id}>
                {b.label}
              </option>
            ))}
          </select>
        </label>
        {showRemotion && onRemotionTheme ? (
          <label className="block text-[10px] text-[var(--muted)]">
            Remotion 字幕主题
            <select
              value={remotionTheme}
              onChange={(e) => onRemotionTheme(e.target.value)}
              className="mt-1 w-full rounded border border-[var(--border)] bg-[var(--panel)] px-2 py-1.5 text-xs"
            >
              {(remotionThemes.length
                ? remotionThemes
                : [
                    { id: 'off', label: '关闭（经典 ASS）' },
                    { id: 'bar', label: '底部字幕条' },
                  ]
              ).map((r) => (
                <option key={r.id} value={r.id}>
                  {r.label}
                </option>
              ))}
            </select>
          </label>
        ) : null}
      </div>
      {(bgMode === 'generative' || bgMode === 'texture') && (
        <label className="block text-[10px] text-[var(--muted)]">
          底图提示词（关键词生效：科技网格 / 粒子 / 光晕 / 暖色…）
          <input
            value={bgPrompt}
            onChange={(e) => onBgPrompt(e.target.value)}
            placeholder="例如：科技网格、冷色粒子、暖色光晕"
            className="mt-1 w-full rounded border border-[var(--border)] bg-[var(--panel)] px-2 py-1.5 text-xs"
          />
        </label>
      )}
      {!showRemotion && (
        <p className="text-[10px] text-[var(--muted)]">
          Remotion 动效字幕已并入「烧录字幕」，不在场景卡上叠加。
        </p>
      )}
    </div>
  )
}

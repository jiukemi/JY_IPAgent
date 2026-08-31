import type { StepId } from '../types'

const STEPS: { id: StepId; label: string; short: string }[] = [
  { id: 'script', label: '文案策划', short: '01' },
  { id: 'tts', label: '配音 · 音色', short: '02' },
  { id: 'avatar', label: '数字人口播', short: '03' },
  { id: 'publish', label: '智能剪辑', short: '04' },
]

type Props = {
  active: StepId
  onChange: (step: StepId) => void
}

export function Sidebar({ active, onChange }: Props) {
  const navActive: StepId = active === 'clone' ? 'tts' : active
  const activeIdx = Math.max(
    0,
    STEPS.findIndex((s) => s.id === navActive),
  )

  return (
    <nav aria-label="制作流程" className="mx-auto mt-4 w-full max-w-[1600px] px-5">
      <div className="ui-card overflow-x-auto px-3 py-3 sm:px-5">
        <ol className="flex w-full items-stretch gap-0">
          {STEPS.map((step, idx) => {
            const done = idx < activeIdx
            const selected = idx === activeIdx
            return (
              <li key={step.id} className="flex min-w-0 flex-1 items-center">
                <button
                  type="button"
                  onClick={() => onChange(step.id)}
                  className="group flex w-full min-w-0 items-center gap-2 rounded-xl px-1.5 py-1 text-left transition hover:bg-[var(--select-bg)]/60 sm:gap-2.5 sm:px-2"
                >
                  <span
                    className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-bold transition ${
                      done
                        ? 'bg-[var(--success)] text-white'
                        : selected
                          ? 'bg-[var(--accent)] text-[var(--accent-contrast)] shadow-[0_2px_10px_var(--select-shadow)]'
                          : 'border border-[var(--border)] bg-[var(--bg)] text-[var(--muted)] group-hover:border-[var(--select-border)]'
                    }`}
                  >
                    {done ? (
                      <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden>
                        <path
                          d="M3.5 8.2L6.4 11l6.1-6.5"
                          stroke="currentColor"
                          strokeWidth="2.2"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                      </svg>
                    ) : (
                      step.short.replace(/^0/, '')
                    )}
                  </span>
                  <span className="min-w-0">
                    <span
                      className={`block truncate text-xs font-semibold sm:text-sm ${
                        selected
                          ? 'text-[var(--accent)]'
                          : done
                            ? 'text-[var(--text)]'
                            : 'text-[var(--muted)]'
                      }`}
                    >
                      {step.label}
                    </span>
                    <span className="hidden text-[10px] text-[var(--muted)] sm:block">
                      步骤 {step.short}
                    </span>
                  </span>
                </button>
                {idx < STEPS.length - 1 && (
                  <span
                    className={`mx-0.5 hidden h-px w-4 shrink-0 sm:mx-1 sm:block sm:w-6 md:w-8 ${
                      idx < activeIdx ? 'bg-[var(--success)]' : 'bg-[var(--border)]'
                    }`}
                    aria-hidden
                  />
                )}
              </li>
            )
          })}
        </ol>
      </div>
    </nav>
  )
}

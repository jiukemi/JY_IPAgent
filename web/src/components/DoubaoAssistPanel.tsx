import { useState } from 'react'
import {
  DOUBAO_PROMPT_DOCKER_AND_PULL,
  DOUBAO_PROMPT_DOCKER_ONLY,
  DOUBAO_PROMPT_PULL_ONLY,
} from '../content/doubaoPrompts'

type Variant = 'docker' | 'full' | 'pull'

const VARIANTS: Record<
  Variant,
  { title: string; hint: string; prompt: string; copyLabel: string }
> = {
  docker: {
    title: '备选：豆包电脑本地模式 · 只装 Docker',
    hint: '打开豆包桌面端最新版 → 电脑本地模式 → 粘贴下方提示词。装好后回本页点「重新检测」。UAC 需你本地点确认。',
    prompt: DOUBAO_PROMPT_DOCKER_ONLY,
    copyLabel: '复制豆包提示词（只装 Docker）',
  },
  full: {
    title: '备选：豆包电脑本地模式 · Docker + 拉镜像',
    hint: '有稳定外网/梯子时可用：豆包装 Docker 并 docker pull 正确镜像，再回本页「重新检测」→「一键启动」。不要用错误镜像名 heygem.ai。',
    prompt: DOUBAO_PROMPT_DOCKER_AND_PULL,
    copyLabel: '复制豆包提示词（Docker + pull）',
  },
  pull: {
    title: '备选：豆包电脑本地模式 · 只拉镜像',
    hint: 'Docker 已通、有外网时：让豆包 docker pull（跳过夸克 zip）。完成后回本页重新检测并一键启动。',
    prompt: DOUBAO_PROMPT_PULL_ONLY,
    copyLabel: '复制豆包提示词（只拉镜像）',
  },
}

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    try {
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.left = '-9999px'
      document.body.appendChild(ta)
      ta.select()
      const ok = document.execCommand('copy')
      document.body.removeChild(ta)
      return ok
    } catch {
      return false
    }
  }
}

type Props = {
  variant: Variant
  className?: string
}

/** Inline guide + one-click copy for 豆包 local-PC install prompts. */
export function DoubaoAssistPanel({ variant, className = '' }: Props) {
  const v = VARIANTS[variant]
  const [copied, setCopied] = useState(false)
  const [expanded, setExpanded] = useState(false)

  const onCopy = async () => {
    const ok = await copyText(v.prompt)
    if (ok) {
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    }
  }

  return (
    <div
      className={`rounded-lg border border-dashed border-[var(--border)] bg-[var(--panel)]/40 px-2.5 py-2 ${className}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <p className="text-[11px] font-medium text-[var(--text)]">{v.title}</p>
          <p className="mt-0.5 text-[10px] leading-relaxed text-[var(--muted)]">{v.hint}</p>
        </div>
        <button
          type="button"
          onClick={() => void onCopy()}
          className="shrink-0 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-2.5 py-1.5 text-[11px] font-medium text-[var(--text)] hover:bg-[var(--panel)]"
        >
          {copied ? '已复制' : v.copyLabel}
        </button>
      </div>
      <button
        type="button"
        onClick={() => setExpanded((e) => !e)}
        className="mt-1.5 text-[10px] text-[var(--muted)] underline"
      >
        {expanded ? '收起提示词' : '预览提示词'}
      </button>
      {expanded && (
        <pre className="mt-1.5 max-h-40 overflow-auto whitespace-pre-wrap rounded border border-[var(--border)] bg-[var(--bg)] p-2 text-[10px] leading-relaxed text-[var(--muted)]">
          {v.prompt}
        </pre>
      )}
    </div>
  )
}

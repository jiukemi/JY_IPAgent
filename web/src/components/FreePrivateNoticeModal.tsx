import { useEffect, useState } from 'react'

const STORAGE_KEY = 'agent-free-private-notice-v1'

const NOTICE_TITLE = '重要声明'
const NOTICE_BODY =
  '本软件免费供个人私下使用。\n\n' +
  '任何人以本软件、安装包、激活码、会员或「官方售后」向您收费的行为，均为诈骗或未经授权的倒卖。\n\n' +
  '请勿向陌生人转账；请勿轻信第三方网盘/群聊里的「付费版」「破解版」。\n\n' +
  '点击「我知道了」表示您已阅读并理解本声明。'

/** First-launch notice: free for private use; paid offers are scams. */
export function FreePrivateNoticeModal() {
  const [open, setOpen] = useState(false)

  useEffect(() => {
    try {
      // Packaged Electron shows a native dialog once; skip duplicate web modal.
      const desktop = (window as unknown as { agentDesktop?: { isDesktop?: boolean } }).agentDesktop
      if (desktop?.isDesktop) return
      if (localStorage.getItem(STORAGE_KEY) === '1') return
      setOpen(true)
    } catch {
      setOpen(true)
    }
  }, [])

  const dismiss = () => {
    try {
      localStorage.setItem(STORAGE_KEY, '1')
    } catch {
      /* ignore */
    }
    setOpen(false)
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="free-notice-title"
        className="w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--panel)] p-5 shadow-xl"
      >
        <h2 id="free-notice-title" className="text-lg font-semibold text-[var(--text)]">
          {NOTICE_TITLE}
        </h2>
        <p className="mt-3 whitespace-pre-line text-sm leading-relaxed text-[var(--muted)]">{NOTICE_BODY}</p>
        <div className="mt-5 flex justify-end">
          <button type="button" className="btn-primary rounded-lg px-4 py-2 text-sm font-medium" onClick={dismiss}>
            我知道了
          </button>
        </div>
      </div>
    </div>
  )
}

import { useCallback, useEffect, useState } from 'react'
import { api, playableUrl } from '../api/client'

export type PickerAsset = {
  id: string
  name: string
  group_id: string
  asset_type: string
  media_type: 'image' | 'video'
  preview_url?: string | null
  local_path?: string | null
  media_path?: string
}

type Props = {
  open: boolean
  onClose: () => void
  onPick: (asset: PickerAsset) => void
  /** Prefer media type for 口播 / 参考素材；publish timeline keeps default all */
  mediaKind?: 'all' | 'image' | 'video'
  title?: string
  subtitle?: string
}

export function AssetPickerModal({
  open,
  onClose,
  onPick,
  mediaKind = 'all',
  title = '从素材中心选择',
  subtitle = '文案卡片、图片、短视频 · 插入当前选中字幕区间',
}: Props) {
  const [items, setItems] = useState<PickerAsset[]>([])
  const [loading, setLoading] = useState(false)
  const [filter, setFilter] = useState<'all' | 'card' | 'video'>(
    mediaKind === 'video' ? 'video' : mediaKind === 'image' ? 'card' : 'all',
  )

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const res = await api.assetPickerItems()
      setItems(res.items as PickerAsset[])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!open) return
    setFilter(mediaKind === 'video' ? 'video' : mediaKind === 'image' ? 'card' : 'all')
    void refresh()
  }, [open, refresh, mediaKind])

  if (!open) return null

  const shown = items.filter((item) => {
    if (mediaKind === 'video' && item.media_type !== 'video') return false
    if (mediaKind === 'image' && item.media_type !== 'image') return false
    if (filter === 'card') return item.group_id === 'card' || item.media_type === 'image'
    if (filter === 'video') return item.media_type === 'video'
    return true
  })

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/55 p-4">
      <div className="flex max-h-[85vh] w-full max-w-3xl flex-col rounded-2xl border border-[var(--border)] bg-[var(--panel)] shadow-2xl">
        <div className="flex items-center justify-between border-b border-[var(--border)] px-4 py-3">
          <div>
            <h3 className="text-sm font-semibold">{title}</h3>
            <p className="text-[10px] text-[var(--muted)]">{subtitle}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-[var(--border)] px-2.5 py-1 text-xs hover:bg-[var(--panel-2)]"
          >
            关闭
          </button>
        </div>

        <div className="flex gap-2 border-b border-[var(--border)] px-4 py-2">
          {(['all', 'card', 'video'] as const).map((f) => (
            <button
              key={f}
              type="button"
              onClick={() => setFilter(f)}
              className={`rounded-lg px-2.5 py-1 text-[10px] ${
                filter === f
                  ? 'bg-[var(--select-bg)] text-[var(--accent)]'
                  : 'text-[var(--muted)] hover:bg-[var(--panel-2)]'
              }`}
            >
              {f === 'all' ? '全部' : f === 'card' ? '卡片/图片' : '视频'}
            </button>
          ))}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          {loading ? (
            <p className="text-sm text-[var(--muted)]">加载素材…</p>
          ) : shown.length === 0 ? (
            <p className="text-sm text-[var(--muted)]">
              暂无可用素材。请先在顶栏「素材中心」生成 HyperFrames 场景或上传文件。
            </p>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {shown.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => {
                    onPick(item)
                    onClose()
                  }}
                  className="rounded-xl border border-[var(--border)] bg-[var(--bg)] p-2 text-left hover:border-[var(--accent)]"
                >
                  <div className="mb-2 flex aspect-video items-center justify-center overflow-hidden rounded-lg bg-[var(--panel)]">
                    {item.media_type === 'video' &&
                    playableUrl(item.preview_url, { localPath: item.local_path || item.media_path }) ? (
                      <video
                        src={
                          playableUrl(item.preview_url, {
                            localPath: item.local_path || item.media_path,
                          })!
                        }
                        className="max-h-full max-w-full"
                        muted
                        preload="metadata"
                      />
                    ) : playableUrl(item.preview_url, { localPath: item.local_path || item.media_path }) ? (
                      <img
                        src={
                          playableUrl(item.preview_url, {
                            localPath: item.local_path || item.media_path,
                          })!
                        }
                        alt=""
                        className="max-h-full max-w-full object-contain"
                      />
                    ) : (
                      <span className="text-2xl opacity-40">📄</span>
                    )}
                  </div>
                  <p className="truncate text-xs font-medium">{item.name}</p>
                  <p className="text-[10px] text-[var(--muted)]">
                    {item.media_type === 'video' ? '视频' : '图片'}
                  </p>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

/** Shared download link buttons for accel packs (GitHub/直链优先，夸克备用). */

type PackLinks = {
  download_url?: string
  download_label?: string
  share_url?: string
  share_extract_code?: string
}

export function packPrimaryUrl(p: PackLinks): string {
  return (p.download_url || p.share_url || '').trim()
}

export function AccelPackLinks({ pack }: { pack: PackLinks }) {
  const direct = (pack.download_url || '').trim()
  const quark = (pack.share_url || '').trim()
  if (!direct && !quark) {
    return (
      <p className="mt-1 text-[10px] text-amber-700/90">
        下载链接未配置（运营填 data/quark/catalog.json 的 download_url）
      </p>
    )
  }
  return (
    <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px]">
      {direct ? (
        <a href={direct} target="_blank" rel="noreferrer" className="font-medium text-[var(--accent)] underline">
          {pack.download_label || '仓库/直链下载（推荐）'}
        </a>
      ) : null}
      {quark ? (
        <a href={quark} target="_blank" rel="noreferrer" className="text-[var(--muted)] underline">
          夸克备用
          {pack.share_extract_code ? `（${pack.share_extract_code}）` : ''}
        </a>
      ) : null}
    </div>
  )
}

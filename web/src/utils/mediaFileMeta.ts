export type VideoFileMeta = {
  durationSec: number | null
}

/** Publish / HyperFrames aspect ids derived from video pixel size. */
export type VideoAspectId = 'landscape_16_9' | 'portrait_9_16'

export function detectVideoDuration(file: File): Promise<number | null> {
  const ext = file.name.split('.').pop()?.toLowerCase() || ''
  const videoExt = new Set(['mp4', 'mov', 'webm', 'mkv', 'm4v', 'avi'])
  if (!videoExt.has(ext) && !file.type.startsWith('video/')) {
    return Promise.resolve(null)
  }
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file)
    const el = document.createElement('video')
    el.preload = 'metadata'
    el.onloadedmetadata = () => {
      const d = Number.isFinite(el.duration) ? el.duration : null
      URL.revokeObjectURL(url)
      resolve(d)
    }
    el.onerror = () => {
      URL.revokeObjectURL(url)
      resolve(null)
    }
    el.src = url
  })
}

/** Probe width/height from a playable media URL (session lipsync, etc.). */
export function detectVideoAspectFromUrl(url: string): Promise<VideoAspectId | null> {
  if (!url) return Promise.resolve(null)
  return new Promise((resolve) => {
    const el = document.createElement('video')
    el.preload = 'metadata'
    let settled = false
    const finish = (value: VideoAspectId | null) => {
      if (settled) return
      settled = true
      el.removeAttribute('src')
      el.load()
      resolve(value)
    }
    el.onloadedmetadata = () => {
      if (el.videoWidth > 0 && el.videoHeight > 0) {
        finish(el.videoWidth >= el.videoHeight ? 'landscape_16_9' : 'portrait_9_16')
      } else {
        finish(null)
      }
    }
    el.onerror = () => finish(null)
    window.setTimeout(() => finish(null), 8000)
    el.src = url
  })
}

export function pathsRoughlyEqual(a?: string | null, b?: string | null): boolean {
  if (!a || !b) return false
  const norm = (p: string) => p.replace(/\\/g, '/').replace(/\/+/g, '/').toLowerCase()
  return norm(a) === norm(b)
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`
}

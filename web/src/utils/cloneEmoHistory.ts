export type CloneVoiceEmoItem = {
  label: string
  value: string
  engine: string
  voiceUid: string
  at: string
  previewPath?: string
  dubbingPath?: string
}

const STORAGE_KEY = 'agent-clone-emo-voice-v2'
const LAST_KEY_PREFIX = 'agent-clone-emo-last-v2-'
const PLAIN_PREVIEW_PREFIX = 'agent-clone-emo-plain-preview-v2-'
const PLAIN_DUB_PREFIX = 'agent-clone-emo-plain-dub-v2-'

function readAll(): CloneVoiceEmoItem[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw) as CloneVoiceEmoItem[]
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function writeAll(items: CloneVoiceEmoItem[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(items.slice(0, 300)))
  } catch {
    /* ignore quota */
  }
}

export function normalizeEmoEngine(engine: string): string {
  return (engine || 'indextts').toLowerCase()
}

function lastKey(engine: string, voiceUid: string): string {
  return `${LAST_KEY_PREFIX}${normalizeEmoEngine(engine)}::${voiceUid.trim()}`
}

function plainPreviewKey(engine: string, voiceUid: string): string {
  return `${PLAIN_PREVIEW_PREFIX}${normalizeEmoEngine(engine)}::${voiceUid.trim()}`
}

function plainDubKey(engine: string, voiceUid: string): string {
  return `${PLAIN_DUB_PREFIX}${normalizeEmoEngine(engine)}::${voiceUid.trim()}`
}

function emoLabel(value: string, label?: string): string {
  const v = (value || '').trim()
  if (!v) return '无情感'
  const l = (label || '').trim()
  return l || v.slice(0, 18) + (v.length > 18 ? '…' : '')
}

function findItem(engine: string, voiceUid: string, value: string): CloneVoiceEmoItem | undefined {
  const eng = normalizeEmoEngine(engine)
  const uid = (voiceUid || '').trim()
  const v = (value || '').trim()
  return readAll().find(
    (x) => x.engine === eng && x.voiceUid === uid && (x.value || '').trim() === v,
  )
}

/** 试听缓存 key：每个音色 + 情感独立目录，避免互相覆盖 */
export function emoPreviewKey(
  voiceUid: string,
  styleExtra: string,
  mode: 'plain' | 'styled',
): string {
  const raw = `${voiceUid}|${(styleExtra || '').trim()}|${mode}`
  let h = 0
  for (let i = 0; i < raw.length; i++) h = ((h << 5) - h + raw.charCodeAt(i)) | 0
  const slug = (h >>> 0).toString(36)
  return mode === 'plain' ? `plain_${slug}` : `emo_${slug}`
}

export function sessionAudioUrl(path: string): string {
  return `/api/files/session?path=${encodeURIComponent(path)}&t=${Date.now()}`
}

/** 该音色下已成功生成过的情感（不含「无情感」空值） */
export function loadEmoStylesForVoice(engine: string, voiceUid: string): CloneVoiceEmoItem[] {
  const eng = normalizeEmoEngine(engine)
  const uid = (voiceUid || '').trim()
  if (!uid) return []
  const seen = new Set<string>()
  const out: CloneVoiceEmoItem[] = []
  for (const x of readAll()) {
    if (x.engine !== eng || x.voiceUid !== uid) continue
    const v = (x.value || '').trim()
    if (!v || seen.has(v)) continue
    seen.add(v)
    out.push(x)
  }
  return out.sort((a, b) => (b.at || '').localeCompare(a.at || ''))
}

/** 取该情感对应的试听或成片路径（优先短试听） */
export function getEmoAudioPath(engine: string, voiceUid: string, value: string): string | undefined {
  const eng = normalizeEmoEngine(engine)
  const uid = (voiceUid || '').trim()
  if (!uid) return undefined
  const v = (value || '').trim()
  if (!v) {
    try {
      return (
        localStorage.getItem(plainPreviewKey(eng, uid)) ||
        localStorage.getItem(plainDubKey(eng, uid)) ||
        undefined
      )
    } catch {
      return undefined
    }
  }
  const item = findItem(eng, uid, v)
  return item?.previewPath || item?.dubbingPath || undefined
}

/** 取该情感对应的成片路径（用于切换配音音轨） */
export function getEmoDubbingPath(engine: string, voiceUid: string, value: string): string | undefined {
  const eng = normalizeEmoEngine(engine)
  const uid = (voiceUid || '').trim()
  if (!uid) return undefined
  const v = (value || '').trim()
  if (!v) {
    try {
      return localStorage.getItem(plainDubKey(eng, uid)) || undefined
    } catch {
      return undefined
    }
  }
  const item = findItem(eng, uid, v)
  return item?.dubbingPath || undefined
}

/** 生成成功后写入：同一音色 + 情感组合会保留 */
export function rememberEmoForVoice(
  engine: string,
  voiceUid: string,
  value: string,
  label?: string,
  paths?: { previewPath?: string; dubbingPath?: string },
) {
  const eng = normalizeEmoEngine(engine)
  const uid = (voiceUid || '').trim()
  if (!uid) return
  const v = (value || '').trim()
  setLastEmoForVoice(eng, uid, v)

  if (!v) {
    if (paths?.previewPath) {
      try {
        localStorage.setItem(plainPreviewKey(eng, uid), paths.previewPath)
      } catch {
        /* ignore */
      }
    }
    if (paths?.dubbingPath) {
      try {
        localStorage.setItem(plainDubKey(eng, uid), paths.dubbingPath)
      } catch {
        /* ignore */
      }
    }
    return
  }

  const prev = findItem(eng, uid, v)
  const items = readAll().filter((x) => {
    if (x.engine !== eng || x.voiceUid !== uid) return true
    return (x.value || '').trim() !== v
  })
  items.unshift({
    label: emoLabel(v, label || prev?.label),
    value: v,
    engine: eng,
    voiceUid: uid,
    at: new Date().toISOString(),
    previewPath: paths?.previewPath || prev?.previewPath,
    dubbingPath: paths?.dubbingPath || prev?.dubbingPath,
  })
  writeAll(items)
}

export function setLastEmoForVoice(engine: string, voiceUid: string, value: string) {
  const uid = (voiceUid || '').trim()
  if (!uid) return
  try {
    localStorage.setItem(lastKey(engine, uid), (value || '').trim())
  } catch {
    /* ignore */
  }
}

export function loadLastEmoForVoice(engine: string, voiceUid: string): string {
  const uid = (voiceUid || '').trim()
  if (!uid) return ''
  try {
    return localStorage.getItem(lastKey(engine, uid)) || ''
  } catch {
    return ''
  }
}

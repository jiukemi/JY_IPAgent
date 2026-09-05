import type {
  CoverTemplate,
  SessionItem,
  SessionSnapshot,
  SettingsPayload,
  StageResult,
  TtsOptions,
  VoiceItem,
} from '../types'

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init)
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail || JSON.stringify(body)
    } catch {
      /* ignore */
    }
    throw new Error(detail)
  }
  return res.json() as Promise<T>
}

function isDesktopShell(): boolean {
  if (typeof window === 'undefined') return false
  return Boolean((window as unknown as { agentDesktop?: { isDesktop?: boolean } }).agentDesktop?.isDesktop)
}

function isAbsoluteFsPath(p: string): boolean {
  return /^[a-zA-Z]:[\\/]/.test(p) || p.startsWith('\\\\') || (p.startsWith('/') && !p.startsWith('//'))
}

/** Desktop: map absolute disk path → agent-media:// (direct disk read). */
export function mediaUrl(path: string | null | undefined, cacheBust?: number | null): string | null {
  if (!path) return null
  if (path.startsWith('data:') || path.startsWith('blob:') || path.startsWith('agent-media:')) return path
  if (isDesktopShell() && isAbsoluteFsPath(path) && !path.startsWith('http')) {
    let u = `agent-media://local/?p=${encodeURIComponent(path)}`
    if (cacheBust != null) u += `&v=${cacheBust}`
    return u
  }
  const base = `/api/files/session?path=${encodeURIComponent(path)}`
  if (cacheBust == null) return base
  return `${base}&v=${cacheBust}`
}

/**
 * Turn any preview src (HTTP API / abs path / data URL) into the fastest playable URL.
 * Prefer local_path on desktop so audio/video never round-trip through FastAPI.
 */
export function playableUrl(
  urlOrPath: string | null | undefined,
  opts?: { localPath?: string | null; cacheBust?: number | null },
): string | null {
  const bust = opts?.cacheBust ?? null
  if (opts?.localPath) {
    const local = mediaUrl(opts.localPath, bust)
    if (local) return local
  }
  if (!urlOrPath) return null
  if (
    urlOrPath.startsWith('data:') ||
    urlOrPath.startsWith('blob:') ||
    urlOrPath.startsWith('agent-media:')
  ) {
    return urlOrPath
  }
  if (isAbsoluteFsPath(urlOrPath)) {
    return mediaUrl(urlOrPath, bust) || urlOrPath
  }
  // Rewrite session file proxy → disk
  try {
    const q = urlOrPath.includes('?') ? urlOrPath.slice(urlOrPath.indexOf('?') + 1) : ''
    if (urlOrPath.includes('/api/files/session') && q) {
      const params = new URLSearchParams(q)
      const p = params.get('path')
      if (p) return mediaUrl(p, bust ?? (params.get('v') ? Number(params.get('v')) : null)) || urlOrPath
    }
  } catch {
    /* ignore */
  }
  return urlOrPath
}

export type JobStatus = 'queued' | 'running' | 'done' | 'failed' | 'cancelled'

export type JobRecord = {
  id: string
  session_path: string
  type: string
  title: string
  status: JobStatus
  progress: number
  message: string
  params_hash?: string
  payload?: Record<string, unknown>
  result?: Record<string, unknown> | null
  error?: string | null
  priority?: number
  created_at?: string
  started_at?: string | null
  finished_at?: string | null
  duration_sec?: number | null
  cancel_requested?: boolean
}

export type CompetitorItem = {
  id: string
  nickname: string
  signature: string
  profile_url: string
  videos_found: number
  sample_count: number
  updated_at: string
  platform: string
}

export type UpdateRelease = {
  source: string
  version: string
  tag: string
  name: string
  download_url: string
  html_url: string
  size: number
  notes: string
}

export type UpdateCheckResult = {
  ok: boolean
  current_version: string
  update_available: boolean
  latest: UpdateRelease | null
  mirrors: UpdateRelease[]
}

export const api = {
  checkUpdates: () => request<UpdateCheckResult>('/api/updates/check'),
  appVersion: () => request<{ version: string }>('/api/updates/version'),

  browserStatus: (platform?: string) =>
    request<{
      ready: boolean
      logged_in: boolean
      message: string
      deferred?: boolean
      profile_dir?: string
      playwright_installed?: boolean
      platform?: string
      platform_name?: string
      login_running?: boolean
      login_error?: string
    }>(`/api/browser/status${platform ? '?platform=' + platform : ''}`),

  browserLogin: (force?: boolean, platform?: string) =>
    request<{
      ok: boolean
      message: string
      profile_dir?: string
      platform_name?: string
      need_install?: string
      login_running?: boolean
    }>('/api/browser/login', {
      method: 'POST',
      body: JSON.stringify({ force: !!force, platform: platform || '' }),
      headers: { 'Content-Type': 'application/json' },
    }),

  browserPlatforms: () =>
    request<{
      platforms: { id: string; name: string; login_url: string; creator_upload_url?: string }[]
    }>('/api/browser/platforms'),

  browserDetect: (url: string) =>
    request<{ platform: string; url: string }>(`/api/browser/detect?url=${encodeURIComponent(url)}`),

  funasrWorkerStatus: () =>
    request<{ enabled: boolean; running: boolean; model?: string }>('/api/funasr/worker/status'),

  funasrWorkerStart: () =>
    request<{ ok: boolean; running: boolean; message?: string }>('/api/funasr/worker/start', {
      method: 'POST',
    }),

  funasrWorkerStop: () =>
    request<{ ok: boolean; running: boolean }>('/api/funasr/worker/stop', { method: 'POST' }),

  ttsWorkerStatus: () =>
    request<{ enabled: boolean; running: boolean }>('/api/tts/worker/status'),

  ttsWorkerStart: () =>
    request<{ ok: boolean; running: boolean; message?: string }>('/api/tts/worker/start', {
      method: 'POST',
    }),

  ttsWorkerStop: () =>
    request<{ ok: boolean; running: boolean }>('/api/tts/worker/stop', { method: 'POST' }),

  getSettings: () =>
    request<{ settings: SettingsPayload; engines: Record<string, unknown> }>(
      '/api/config/settings',
    ),

  saveSettings: (body: SettingsPayload) =>
    request<{ settings: SettingsPayload; summary_md: string }>('/api/config/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),

  getTextPrompts: () =>
    request<{
      items: Array<{
        id: string
        label: string
        hint?: string
        value: string
        default: string
        modified: boolean
      }>
    }>('/api/config/prompts'),

  saveTextPrompts: (prompts: Record<string, string>) =>
    request<{
      ok: boolean
      items: Array<{
        id: string
        label: string
        hint?: string
        value: string
        default: string
        modified: boolean
      }>
    }>('/api/config/prompts', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompts }),
    }),

  resetTextPrompts: (ids?: string[]) =>
    request<{
      ok: boolean
      items: Array<{
        id: string
        label: string
        hint?: string
        value: string
        default: string
        modified: boolean
      }>
    }>('/api/config/prompts/reset', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(ids?.length ? { ids } : {}),
    }),

  listSessions: (current?: string) =>
    request<SessionItem[]>(`/api/sessions${current ? `?current=${encodeURIComponent(current)}` : ''}`),

  activeSession: () => request<{ path: string; name: string }>('/api/sessions/active'),

  systemJobsSession: () =>
    request<{ ok: boolean; path: string; name: string }>('/api/sessions/system-jobs'),

  createSession: () => request<SessionSnapshot>('/api/sessions', { method: 'POST' }),

  sessionSnapshot: (path: string) =>
    request<SessionSnapshot>(`/api/sessions/snapshot?path=${encodeURIComponent(path)}`),

  prepareSessionMedia: (path: string) =>
    request<{ ok: boolean; path: string; optimized: boolean }>(
      `/api/files/prepare?path=${encodeURIComponent(path)}`,
      { method: 'POST' },
    ),

  renameSession: (path: string, name: string) =>
    request<{ path: string; name: string }>(
      `/api/sessions?path=${encodeURIComponent(path)}`,
      {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      },
    ),

  deleteSession: (path: string) =>
    request<{ ok: boolean }>(`/api/sessions?path=${encodeURIComponent(path)}`, { method: 'DELETE' }),

  scriptPanel: (sessionPath: string) =>
    request<Record<string, unknown>>(`/api/script/panel?session_path=${encodeURIComponent(sessionPath)}`),

  scriptCdn: (sessionPath: string, shareUrl: string) =>
    request<StageResult>('/api/script/cdn', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_path: sessionPath, share_url: shareUrl }),
    }),

  scriptTranscript: (sessionPath: string, shareUrl: string, file?: File) => {
    const fd = new FormData()
    fd.append('session_path', sessionPath)
    fd.append('share_url', shareUrl)
    if (file) fd.append('media', file)
    return request<StageResult>('/api/script/transcript', { method: 'POST', body: fd })
  },

  scriptPrepareMedia: (sessionPath: string, file: File) => {
    const fd = new FormData()
    fd.append('session_path', sessionPath)
    fd.append('media', file)
    return request<{ ok: boolean; ref_media: string }>('/api/script/prepare_media', {
      method: 'POST',
      body: fd,
    })
  },

  scriptExtract: (sessionPath: string, shareUrl: string, file?: File) => {
    const fd = new FormData()
    fd.append('session_path', sessionPath)
    fd.append('share_url', shareUrl)
    if (file) fd.append('media', file)
    return request<StageResult>('/api/script/extract', { method: 'POST', body: fd })
  },

  scriptExtractStream: (
    sessionPath: string,
    shareUrl: string,
    file: File | undefined,
    onProgress: (pct: number, desc: string) => void,
  ): Promise<{ log: string; data: Record<string, unknown> }> => {
    const fd = new FormData()
    fd.append('session_path', sessionPath)
    fd.append('share_url', shareUrl)
    if (file) fd.append('media', file)
    return fetch('/api/script/extract_stream', { method: 'POST', body: fd }).then(async (resp) => {
      if (!resp.ok) {
        let detail = resp.statusText
        try {
          const body = await resp.json()
          detail = body.detail || JSON.stringify(body)
        } catch {
          /* ignore */
        }
        throw new Error(detail || `提取失败 HTTP ${resp.status}`)
      }
      const reader = resp.body?.getReader()
      if (!reader) throw new Error('no stream body')
      const decoder = new TextDecoder()
      let buf = ''
      let result = { log: '', data: {} as Record<string, unknown> }
      let sawDone = false
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const lines = buf.split('\n')
        buf = lines.pop() || ''
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          let ev: { type?: string; pct?: number; desc?: string; data?: Record<string, unknown>; message?: string }
          try {
            ev = JSON.parse(line.slice(6))
          } catch {
            // ignore parse errors on partial lines
            continue
          }
          if (ev.type === 'progress') onProgress(Number(ev.pct) || 0, ev.desc || '')
          else if (ev.type === 'done') {
            sawDone = true
            result = { log: (ev.data?.log as string) || '', data: ev.data || {} }
          } else if (ev.type === 'error') throw new Error(ev.message || '提取失败')
          else if (ev.type === 'end') {
            if (!sawDone && !result.log) throw new Error('提取未返回结果，请重试或查看后端日志')
            return result
          }
        }
      }
      if (!sawDone && !result.log) throw new Error('提取中断：未收到完成事件')
      return result
    })
  },

  scriptRewrite: (sessionPath: string, script: string, intensity: string) =>
    request<StageResult>('/api/script/rewrite', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_path: sessionPath, script, intensity }),
    }),

  scriptHotwords: (payload: {
    identity?: string
    profession?: string
    industry?: string
    product?: string
    audience?: string
    roles?: Record<string, string>[]
    mix_roles?: boolean
  }) =>
    request<StageResult>('/api/script/hotwords', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  scriptGenerate: (payload: {
    session_path: string
    identity?: string
    profession?: string
    industry?: string
    product?: string
    audience?: string
    selling_points?: string
    duration_sec?: number
    hotwords?: string[]
    extra?: string
    roles?: Record<string, string>[]
    mix_roles?: boolean
    auto_hotwords?: boolean
    save_as?: 'extract' | 'rewritten'
    continue_from?: string
  }) =>
    request<StageResult>('/api/script/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  scriptGenerateStream: async (
    payload: {
      session_path: string
      identity?: string
      profession?: string
      industry?: string
      product?: string
      audience?: string
      selling_points?: string
      duration_sec?: number
      hotwords?: string[]
      extra?: string
      roles?: Record<string, string>[]
      mix_roles?: boolean
      auto_hotwords?: boolean
      save_as?: 'extract' | 'rewritten'
      continue_from?: string
    },
    handlers: {
      onDelta?: (text: string) => void
      onProgress?: (pct: number, desc: string) => void
      signal?: AbortSignal
    } = {},
  ) => {
    const res = await fetch('/api/script/generate/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: handlers.signal,
    })
    if (!res.ok) {
      const t = await res.text()
      throw new Error(t || `HTTP ${res.status}`)
    }
    const reader = res.body?.getReader()
    if (!reader) throw new Error('no stream body')
    const decoder = new TextDecoder()
    let buf = ''
    let finalData: Record<string, unknown> | null = null
    let paused = false
    let log = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      const parts = buf.split('\n')
      buf = parts.pop() || ''
      for (const line of parts) {
        const trimmed = line.trim()
        if (!trimmed.startsWith('data:')) continue
        const raw = trimmed.slice(5).trim()
        if (!raw || raw === '[DONE]') continue
        let ev: {
          type?: string
          text?: string
          pct?: number
          desc?: string
          message?: string
          data?: Record<string, unknown>
        }
        try {
          ev = JSON.parse(raw)
        } catch {
          continue
        }
        if (ev.type === 'delta' && ev.text) handlers.onDelta?.(ev.text)
        else if (ev.type === 'progress' && typeof ev.pct === 'number') {
          handlers.onProgress?.(ev.pct, ev.desc || '')
        } else if (ev.type === 'done' || ev.type === 'paused') {
          finalData = ev.data || null
          paused = ev.type === 'paused'
          log = String(finalData?.log || '')
        } else if (ev.type === 'error') {
          throw new Error(ev.message || '生成失败')
        }
      }
    }
    return { data: finalData, paused, log }
  },

  scriptCompetitorAnalyze: (payload: {
    session_path: string
    profile_url?: string
    competitor_id?: string
    roles: Record<string, string>[]
    mix_roles?: boolean
    duration_sec?: number
    hotwords?: string[]
    extra?: string
    deep_transcript?: boolean
    save_as?: 'extract' | 'rewritten'
  }) =>
    request<StageResult>('/api/script/competitor-analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  competitorsList: () =>
    request<{ items: CompetitorItem[] }>('/api/competitors'),

  competitorsSave: (payload: {
    profile_url: string
    session_path?: string
    deep_transcript?: boolean
  }) =>
    request<StageResult>('/api/competitors/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  competitorsDelete: (id: string) =>
    request<StageResult>(`/api/competitors/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    }),

  scriptLegal: (sessionPath: string, script: string, source: 'extract' | 'rewritten' = 'extract') =>
    request<StageResult>('/api/script/legal', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_path: sessionPath, script, source }),
    }),

  saveScriptText: (sessionPath: string, variant: 'extract' | 'rewritten' | 'legal' | 'manual', text: string) =>
    request<StageResult>('/api/script/text', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_path: sessionPath, variant, text }),
    }),

  systemVoices: (backend?: string) =>
    request<VoiceItem[]>(
      `/api/voices/system${backend ? `?backend=${encodeURIComponent(backend)}` : ''}`,
    ),
  cloneVoices: (backend?: string) =>
    request<VoiceItem[]>(
      `/api/voices/clone${backend ? `?backend=${encodeURIComponent(backend)}` : ''}`,
    ),
  voiceLibrary: () =>
    request<
      {
        id: string
        uid?: string
        name: string
        source_type?: string
        created_at?: string
        backend?: string
        preview_url?: string | null
      }[]
    >('/api/voices/library'),
  nextVoiceName: (source: 'upload' | 'record') =>
    request<{ name: string }>(`/api/voices/next-name?source=${source}`),
  deleteVoice: (id: string) => request<{ ok: boolean }>(`/api/voices/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  ttsSpeeds: (engine?: string) =>
    request<{ value: string; label: string }[]>(
      `/api/tts/speeds${engine ? `?engine=${encodeURIComponent(engine)}` : ''}`,
    ),

  previewStatus: (engine?: string) =>
    request<{ engine: string; total: number; cached: number; missing: number }>(
      `/api/tts/previews/status${engine ? `?engine=${encodeURIComponent(engine)}` : ''}`,
    ),

  buildPreviewsStream: async (
    engine: string | undefined,
    onProgress: (p: { i: number; total: number; label: string; pct: number }) => void,
  ): Promise<{ ok: number; skip: number; fail: number; errors?: string[] }> => {
    const url = `/api/tts/previews/build/stream${engine ? `?engine=${encodeURIComponent(engine)}` : ''}`
    const res = await fetch(url, { method: 'POST' })
    if (!res.ok) {
      let detail = res.statusText
      try {
        detail = await res.text()
      } catch {
        /* ignore */
      }
      throw new Error(detail || '试听生成请求失败')
    }
    if (!res.body) throw new Error('无响应流')
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    let result = { ok: 0, skip: 0, fail: 0, errors: [] as string[] }
    let displayPct = 0
    let lastRealAt = Date.now()
    const simTimer = window.setInterval(() => {
      if (Date.now() - lastRealAt > 1500 && displayPct < 0.92) {
        displayPct = Math.min(displayPct + 0.008, 0.92)
        onProgress({ i: 0, total: 0, label: '生成中…', pct: displayPct })
      }
    }, 700)

    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const blocks = buf.split('\n\n')
        buf = blocks.pop() || ''
        for (const block of blocks) {
          const line = block.trim()
          if (!line.startsWith('data: ')) continue
          const data = JSON.parse(line.slice(6)) as {
            type: string
            i?: number
            total?: number
            label?: string
            p?: number
            ok?: number
            skip?: number
            fail?: number
            errors?: string[]
            msg?: string
          }
          if (data.type === 'error') {
            throw new Error(data.msg || '试听生成失败')
          }
          if (data.type === 'progress' && data.total != null && data.i != null) {
            lastRealAt = Date.now()
            const pct =
              typeof data.p === 'number'
                ? data.p
                : data.total > 0
                  ? data.i / data.total
                  : 0
            displayPct = Math.max(displayPct, pct)
            onProgress({
              i: data.i,
              total: data.total,
              label: data.label || '',
              pct: displayPct,
            })
          }
          if (data.type === 'done') {
            result = {
              ok: data.ok || 0,
              skip: data.skip || 0,
              fail: data.fail || 0,
              errors: data.errors || [],
            }
            onProgress({ i: data.ok || 0, total: (data.ok || 0) + (data.fail || 0), label: '完成', pct: 1 })
          }
        }
      }
    } finally {
      window.clearInterval(simTimer)
    }
    return result
  },

  ttsOptions: (engine?: string) =>
    request<TtsOptions>(`/api/tts/options${engine ? `?engine=${encodeURIComponent(engine)}` : ''}`),

  saveTtsSettings: (payload: { engine?: string; values?: Record<string, string | number | boolean> }) =>
    request<TtsOptions>('/api/tts/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  verifyTts: (engine?: string) =>
    request<import('../types').TtsEngineHealth>(
      `/api/tts/verify${engine ? `?engine=${encodeURIComponent(engine)}` : ''}`,
      { method: 'POST' },
    ),

  setupEngines: () =>
    request<{
      hardware: { summary: string; max_vram_gb?: number; ram_gb?: number; source?: string }
      engines: import('../components/ModelSetupPanel').EngineSetupStatus[]
      recommend?: {
        asr?: string
        tts?: string
        avatar?: string
        summary?: string
        source?: string
        max_vram_gb?: number
      }
    }>('/api/setup/engines'),

  systemStats: () =>
    request<{
      source: string
      cpu_percent: number
      ram_used_gb: number
      ram_total_gb: number
      ram_percent: number
      gpus: Array<{
        name: string
        util_percent: number
        vram_used_gb: number
        vram_total_gb: number
        vram_percent: number
        temp_c?: number | null
      }>
      cuda_available: boolean
      timestamp_ms: number
    }>('/api/system/stats'),

  quarkCatalog: () =>
    request<{
      ok: boolean
      machine: {
        gpu_family: string
        label: string
        hint: string
        heygem_image: string
        summary?: string
        max_vram_gb?: number
        gpu_names?: string[]
      }
      packs: Array<{
        id: string
        name: string
        pack_kind: string
        gpu_family: string
        approx_size_gb?: number
        share_url?: string
        zip_name?: string
        note?: string
        docker_image?: string
        recommended?: boolean
        matches_machine?: boolean
        match_message?: string
      }>
      portal_note?: string
      share_root_url?: string
      share_extract_code?: string
      installed?: Record<string, unknown> | null
      scan_dirs?: string[]
    }>('/api/system/quark/catalog'),

  quarkScan: () =>
    request<{
      ok: boolean
      count: number
      machine?: { gpu_family?: string; label?: string; hint?: string }
      candidates: Array<{
        path: string
        bytes: number
        bundle_name?: string
        pack_id?: string
        pack_kind?: string
        gpu_family?: string
        scan_dir?: string
      }>
      scan_dirs: string[]
      note?: string
    }>('/api/system/quark/scan'),

  quarkInstall: (opts?: { path?: string; force?: boolean }) =>
    request<{
      ok: boolean
      message?: string
      gpu_mismatch?: boolean
      hint?: string
      installed?: string[]
      post_install_hint?: string
      found?: string
      runtime?: string
    }>('/api/system/quark/install', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(opts || {}),
    }),

  quarkUpload: (file: File, force = false) => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('force', force ? 'true' : 'false')
    return request<{
      ok: boolean
      message?: string
      gpu_mismatch?: boolean
      hint?: string
      installed?: string[]
      post_install_hint?: string
      runtime?: string
    }>('/api/system/quark/upload', { method: 'POST', body: fd })
  },

  installEngineStream: async (
    engine: string,
    callbacks: {
      onLog?: (line: string) => void
      onProgress?: (p: number) => void
    },
  ): Promise<{ ready?: boolean; missing?: string[]; exit_code?: number }> => {
    const res = await fetch(`/api/setup/install/stream?engine=${encodeURIComponent(engine)}`, {
      method: 'POST',
    })
    if (!res.ok) {
      let detail = res.statusText
      try {
        const body = await res.json()
        detail = body.detail || JSON.stringify(body)
      } catch {
        /* ignore */
      }
      throw new Error(detail)
    }
    if (!res.body) throw new Error('无安装日志流')
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    let displayPct = 0.02
    let lastRealAt = Date.now()
    let donePayload: { ready?: boolean; missing?: string[]; exit_code?: number } = {}
    const simTimer = window.setInterval(() => {
      if (Date.now() - lastRealAt > 2000 && displayPct < 0.9) {
        displayPct = Math.min(displayPct + 0.006, 0.9)
        callbacks.onProgress?.(displayPct)
      }
    }, 800)

    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const blocks = buf.split('\n\n')
        buf = blocks.pop() || ''
        for (const block of blocks) {
          const line = block.trim()
          if (!line.startsWith('data: ')) continue
          const data = JSON.parse(line.slice(6)) as {
            type: string
            line?: string
            p?: number
            exit_code?: number
            ready?: boolean
            missing?: string[]
          }
          if (data.type === 'start' && typeof data.p === 'number') {
            lastRealAt = Date.now()
            displayPct = Math.max(displayPct, data.p)
            callbacks.onProgress?.(displayPct)
          }
          if (data.type === 'log' && data.line) {
            lastRealAt = Date.now()
            callbacks.onLog?.(data.line)
            if (typeof data.p === 'number') {
              displayPct = Math.max(displayPct, data.p)
              callbacks.onProgress?.(displayPct)
            }
          }
          if (data.type === 'done') {
            donePayload = {
              exit_code: data.exit_code,
              ready: data.ready,
              missing: data.missing,
            }
            callbacks.onProgress?.(1)
          }
        }
      }
    } finally {
      window.clearInterval(simTimer)
    }

    if (donePayload.ready) {
      return donePayload
    }
    if (donePayload.exit_code !== 0) {
      const hint = donePayload.missing?.length
        ? `\n仍缺失：${donePayload.missing.join('；')}`
        : ''
      throw new Error(`安装脚本退出码 ${donePayload.exit_code}${hint}`)
    }
    return donePayload
  },

  synthesize: (payload: {
    session_path: string
    text: string
    voice_uid: string
    speed_mode: string
    backend?: string
    style_extra?: string
  }) =>
    request<StageResult>('/api/tts/synthesize', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  previewCloneEmo: (payload: {
    session_path: string
    voice_uid: string
    text?: string
    style_extra?: string
    speed_mode?: string
    backend?: string
    preview_key?: string
  }) =>
    request<StageResult>('/api/tts/preview-emo', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  synthesizeStream: async (
    payload: {
      session_path: string
      text: string
      voice_uid: string
      speed_mode: string
      backend?: string
      style_extra?: string
    },
    onProgress: (p: number, msg?: string) => void,
    signal?: AbortSignal,
  ): Promise<StageResult> => {
    const res = await fetch('/api/tts/synthesize/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal,
    })
    if (!res.ok) {
      let detail = res.statusText
      try {
        const body = await res.json()
        detail = body.detail || JSON.stringify(body)
      } catch {
        /* ignore */
      }
      throw new Error(detail)
    }
    if (!res.body) throw new Error('无响应流')

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    let result: StageResult | null = null
    let displayPct = 0
    let lastRealAt = Date.now()
    const simTimer = window.setInterval(() => {
      if (Date.now() - lastRealAt > 1500 && displayPct < 0.92) {
        displayPct = Math.min(displayPct + 0.006, 0.92)
        onProgress(displayPct)
      }
    }, 700)

    const onAbort = () => {
      void reader.cancel().catch(() => undefined)
    }
    signal?.addEventListener('abort', onAbort)

    try {
      while (true) {
        if (signal?.aborted) throw new DOMException('任务已取消', 'AbortError')
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const blocks = buf.split('\n\n')
        buf = blocks.pop() || ''
        for (const block of blocks) {
          const line = block.trim()
          if (!line.startsWith('data: ')) continue
          const data = JSON.parse(line.slice(6)) as {
            type: string
            p?: number
            msg?: string
            data?: { log?: string } & Record<string, unknown>
          }
          if (data.type === 'progress' && typeof data.p === 'number') {
            lastRealAt = Date.now()
            displayPct = Math.max(displayPct, data.p)
            onProgress(data.p)
          } else if (data.type === 'done' && data.data) {
            result = { log: data.data.log || '', data: data.data }
            onProgress(1)
          } else if (data.type === 'error') {
            throw new Error(data.msg || '合成失败')
          }
        }
      }
    } finally {
      signal?.removeEventListener('abort', onAbort)
      window.clearInterval(simTimer)
    }
    if (!result) throw new Error(signal?.aborted ? '任务已取消' : '合成未返回结果')
    return result
  },

  uploadSessionDubbing: (sessionPath: string, file: File, sourceType: 'upload' | 'record' = 'upload') => {
    const fd = new FormData()
    fd.append('session_path', sessionPath)
    fd.append('source_type', sourceType)
    fd.append('audio', file)
    return request<StageResult>('/api/sessions/dubbing/upload', { method: 'POST', body: fd })
  },

  patchDubbingSegment: (opts: {
    sessionPath: string
    segmentIndex: number
    mode: 'resynth' | 'replace' | 'record'
    text?: string
    voiceUid?: string
    speedMode?: string
    crossfadeMs?: number
    audio?: File
  }) => {
    const fd = new FormData()
    fd.append('session_path', opts.sessionPath)
    fd.append('segment_index', String(opts.segmentIndex))
    fd.append('mode', opts.mode)
    if (opts.text != null) fd.append('text', opts.text)
    if (opts.voiceUid) fd.append('voice_uid', opts.voiceUid)
    if (opts.speedMode) fd.append('speed_mode', opts.speedMode)
    if (opts.crossfadeMs != null) fd.append('crossfade_ms', String(opts.crossfadeMs))
    if (opts.audio) fd.append('audio', opts.audio)
    return request<StageResult>('/api/sessions/dubbing/patch', { method: 'POST', body: fd })
  },

  saveSessionDubbing: (sessionPath: string, name: string, audioPath?: string) => {
    const fd = new FormData()
    fd.append('session_path', sessionPath)
    fd.append('name', name)
    if (audioPath) fd.append('audio_path', audioPath)
    return request<StageResult>('/api/sessions/dubbing/save', { method: 'POST', body: fd })
  },

  deleteSessionDubbing: (sessionPath: string, dubId: string) =>
    request<StageResult>(
      `/api/sessions/dubbing?session_path=${encodeURIComponent(sessionPath)}&dub_id=${encodeURIComponent(dubId)}`,
      { method: 'DELETE' },
    ),

  selectSessionDubbing: (sessionPath: string, audioPath: string) =>
    request<StageResult>(
      `/api/sessions/dubbing/select?session_path=${encodeURIComponent(sessionPath)}&audio_path=${encodeURIComponent(audioPath)}`,
      { method: 'PUT' },
    ),

  selectSessionLipsync: (sessionPath: string, videoPath: string) =>
    request<StageResult>(
      `/api/sessions/lipsync/select?session_path=${encodeURIComponent(sessionPath)}&video_path=${encodeURIComponent(videoPath)}`,
      { method: 'PUT' },
    ),

  deleteSessionLipsync: (sessionPath: string, takeId: string) =>
    request<StageResult>(
      `/api/sessions/lipsync?session_path=${encodeURIComponent(sessionPath)}&take_id=${encodeURIComponent(takeId)}`,
      { method: 'DELETE' },
    ),

  cloneVoice: (name: string, file: File, sourceType = 'upload', promptText = '') => {
    const fd = new FormData()
    fd.append('name', name)
    fd.append('source_type', sourceType)
    if (promptText.trim()) fd.append('prompt_text', promptText.trim())
    fd.append('audio', file)
    return request<StageResult>('/api/voices/clone', { method: 'POST', body: fd })
  },

  avatarChoices: () => request<{ id: string; label: string }[]>('/api/avatar/choices'),

  avatarLibrary: () => request<import('../components/AvatarPickerModal').AvatarItem[]>('/api/avatar/library'),

  prepareAvatar: (id: string) =>
    request<{
      ok: boolean
      thumb_url: string
      media_url: string
      poster_ready: boolean
      streamable: boolean
    }>(`/api/avatar/prepare/${encodeURIComponent(id)}`, { method: 'POST' }),

  getEdition: () =>
    request<{
      edition: string
      label: string
      local_avatar: boolean
      cloud_avatar_reserved: boolean
      built_with_duix: boolean
    }>('/api/components/edition'),

  heygemStatus: () =>
    request<{
      ready: boolean
      state: string
      api: string
      docker_available: boolean
      duix_present: boolean
      component_installed?: boolean
      can_start?: boolean
      hint: string
      note: string
      runtime: string
    }>('/api/avatar/heygem/status'),

  heygemWizard: () =>
    request<{
      ok: boolean
      machine: { gpu_family: string; label: string; hint?: string; heygem_image?: string }
      heygem: {
        ready?: boolean
        state?: string
        hint?: string
        docker_available?: boolean
        docker_cli?: boolean
        gpu_hint?: string
      }
      recommended_pack?: {
        id: string
        name: string
        share_url?: string
        zip_name?: string
        note?: string
        approx_size_gb?: number
        gpu_family?: string
      } | null
      share_root_url?: string
      share_extract_code?: string
      portal_note?: string
      steps: Array<{ id: number; title: string; done: boolean; detail: string }>
      current_step: number
      docker_product_url?: string
      docker_installer_url?: string
      docker_acceptance_note?: string
      install_drives?: Array<{
        letter: string
        root: string
        free_bytes: number
        free_gb: number
        total_gb: number
        recommended?: boolean
        enough_space?: boolean
        default?: boolean
        label: string
      }>
      local_docker_installers?: Array<{
        path: string
        name: string
        label: string
        size_gb?: number
        bytes?: number
      }>
      docker_install?: {
        phase?: string
        message?: string
        drive?: string
        install_root?: string
        progress_pct?: number
      }
      tars?: Array<{ family: string; name: string; path: string; bytes: number }>
      image?: string
      image_loaded?: boolean
      can_load?: boolean
      can_start?: boolean
      general_pack_ops_note?: string
    }>('/api/avatar/heygem/wizard'),

  heygemWizardOpenDocker: () =>
    request<{
      ok: boolean
      opened?: boolean
      product_url: string
      installer_url: string
      message: string
    }>('/api/avatar/heygem/wizard/open-docker', { method: 'POST' }),

  heygemWizardInstallDocker: (opts: {
    drive: string
    installer_path?: string
    allow_download?: boolean
    prepare_only?: boolean
  }) =>
    request<{
      ok: boolean
      message: string
      drive?: string
      installer?: string
      install_root?: string
      cmd_path?: string
      local_installers?: Array<{ path: string; name: string; label: string; size_gb?: number }>
      docker_install?: {
        phase?: string
        message?: string
        drive?: string
        progress_pct?: number
      }
    }>('/api/avatar/heygem/wizard/install-docker', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(opts),
    }),

  heygemWizardScanDockerInstaller: () =>
    request<{
      ok: boolean
      message: string
      local_installers: Array<{ path: string; name: string; label: string; size_gb?: number }>
    }>('/api/avatar/heygem/wizard/scan-docker-installer', { method: 'POST' }),

  heygemWizardLaunchDocker: () =>
    request<{ ok: boolean; message: string; path?: string; need_install?: boolean }>(
      '/api/avatar/heygem/wizard/launch-docker',
      { method: 'POST' },
    ),

  heygemWizardLoadImage: (opts?: { family?: string; path?: string }) =>
    request<{
      ok: boolean
      message: string
      already?: boolean
      need_docker?: boolean
      need_pack?: boolean
      image?: string
      image_present?: boolean
    }>('/api/avatar/heygem/wizard/load-image', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(opts || {}),
    }),

  heygemStop: () => request<{ ok: boolean; message: string }>('/api/avatar/heygem/stop', { method: 'POST' }),

  heygemStartStream: async (
    handlers: { onLog?: (line: string) => void; onProgress?: (p: number, msg?: string) => void },
  ): Promise<{ ready: boolean; exit_code: number; error?: string; hint?: string }> => {
    const res = await fetch('/api/avatar/heygem/start/stream', { method: 'POST' })
    if (!res.ok) {
      let detail = res.statusText
      try {
        const body = await res.json()
        detail = body.detail || JSON.stringify(body)
      } catch {
        /* ignore */
      }
      throw new Error(detail)
    }
    if (!res.body) throw new Error('无响应流')

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    let ready = false
    let exitCode = 1
    let error: string | undefined
    let hint: string | undefined

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      const blocks = buf.split('\n\n')
      buf = blocks.pop() || ''
      for (const block of blocks) {
        const line = block.trim()
        if (!line.startsWith('data: ')) continue
        const data = JSON.parse(line.slice(6)) as {
          type: string
          line?: string
          p?: number
          msg?: string
          ready?: boolean
          exit_code?: number
          error?: string
          hint?: string
        }
        if (data.type === 'log' && data.line) handlers.onLog?.(data.line)
        if (data.type === 'progress' && typeof data.p === 'number') handlers.onProgress?.(data.p, data.msg)
        if (data.type === 'log' && typeof data.p === 'number') handlers.onProgress?.(data.p)
        if (data.type === 'done') {
          ready = !!data.ready
          exitCode = data.exit_code ?? 0
          error = data.error
          hint = data.hint
          handlers.onProgress?.(1)
        }
      }
    }
    return { ready, exit_code: exitCode, error, hint }
  },

  registerAvatar: (name: string, file: File) => {
    const fd = new FormData()
    fd.append('name', name)
    fd.append('media', file)
    return request<StageResult>('/api/avatar/register', { method: 'POST', body: fd })
  },

  generateAvatar: (prompt: string, name?: string) => {
    const fd = new FormData()
    fd.append('prompt', prompt)
    if (name) fd.append('name', name)
    fd.append('save_to_library', 'true')
    return request<StageResult>('/api/avatar/generate', { method: 'POST', body: fd })
  },

  deleteAvatar: (id: string) => request<{ ok: boolean }>(`/api/avatar/${encodeURIComponent(id)}`, { method: 'DELETE' }),

  lipsync: (fd: FormData) => request<StageResult>('/api/avatar/lipsync', { method: 'POST', body: fd }),

  lipsyncEnqueue: (fd: FormData) =>
    request<{
      ok: boolean
      duplicate?: boolean
      message?: string
      existing_job_id?: string
      job?: JobRecord
      existing_job?: JobRecord
    }>('/api/avatar/lipsync/enqueue', { method: 'POST', body: fd }),

  cancelLipsync: () =>
    request<{ ok: boolean; message?: string; killed_pids?: number[] }>('/api/avatar/lipsync/cancel', {
      method: 'POST',
    }),

  cancelTask: () =>
    request<{ ok: boolean; message?: string; killed_pids?: number[] }>('/api/system/tasks/cancel', {
      method: 'POST',
    }),

  cancelPublish: () =>
    request<{ ok: boolean; message?: string }>('/api/publish/run/cancel', { method: 'POST' }),

  cancelTts: () =>
    request<{ ok: boolean; message?: string }>('/api/tts/synthesize/cancel', { method: 'POST' }),

  lipsyncStream: async (
    fd: FormData,
    onProgress: (p: number, msg?: string) => void,
    signal?: AbortSignal,
  ): Promise<StageResult> => {
    const res = await fetch('/api/avatar/lipsync/stream', { method: 'POST', body: fd, signal })
    if (!res.ok) {
      let detail = res.statusText
      try {
        const body = await res.json()
        detail = body.detail || JSON.stringify(body)
      } catch {
        /* ignore */
      }
      throw new Error(detail)
    }
    if (!res.body) throw new Error('无响应流')

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    let result: StageResult | null = null
    let displayPct = 0
    let lastRealAt = Date.now()
    const simTimer = window.setInterval(() => {
      if (Date.now() - lastRealAt > 2000 && displayPct < 0.9) {
        displayPct = Math.min(displayPct + 0.005, 0.9)
        onProgress(displayPct)
      }
    }, 800)

    const onAbort = () => {
      void reader.cancel().catch(() => undefined)
    }
    signal?.addEventListener('abort', onAbort)

    try {
      while (true) {
        if (signal?.aborted) throw new DOMException('任务已取消', 'AbortError')
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const blocks = buf.split('\n\n')
        buf = blocks.pop() || ''
        for (const block of blocks) {
          const line = block.trim()
          if (!line.startsWith('data: ')) continue
          const data = JSON.parse(line.slice(6)) as {
            type: string
            p?: number
            msg?: string
            data?: { log?: string; video_path?: string } & Record<string, unknown>
          }
          if (data.type === 'progress' && typeof data.p === 'number') {
            lastRealAt = Date.now()
            displayPct = Math.max(displayPct, data.p)
            onProgress(data.p, data.msg)
          } else if (data.type === 'done' && data.data) {
            result = { log: data.data.log || '', data: data.data }
            onProgress(1, '完成')
          } else if (data.type === 'error') {
            throw new Error(data.msg || '口播生成失败')
          }
        }
      }
    } finally {
      signal?.removeEventListener('abort', onAbort)
      window.clearInterval(simTimer)
    }
    if (!result) throw new Error(signal?.aborted ? '任务已取消' : '口播生成未返回结果')
    return result
  },

  publishSubtitlePreview: (fd: FormData) =>
    request<{
      preview_path: string
      mtime: number
      used_placeholder: boolean
      layout_mode?: string
      remotion_theme?: string
      remotion_theme_resolved?: string
      output_aspect?: string
      aspect_label?: string
    }>(
      '/api/publish/subtitle_preview',
      { method: 'POST', body: fd },
    ),

  glassCardsSuggest: (payload: {
    session_path: string
    cues: Array<{ index: number; start: number; end: number; text: string }>
    cue_indices: number[]
    use_llm?: boolean
  }) => {
    const fd = new FormData()
    fd.append('session_path', payload.session_path)
    fd.append('cues_json', JSON.stringify(payload.cues))
    fd.append('cue_indices_json', JSON.stringify(payload.cue_indices))
    fd.append('use_llm', payload.use_llm === false ? 'false' : 'true')
    return request<{
      ok: boolean
      cards: Array<{
        id: string
        cue_indices: number[]
        start: number
        end: number
        title: string
        bullets: string[]
        source_text?: string
      }>
      count: number
    }>('/api/publish/glass_cards/suggest', { method: 'POST', body: fd })
  },

  publishRemotionPreview: (payload: {
    session_path: string
    text: string
    remotion_theme: string
    accent?: string
  }) => {
    const fd = new FormData()
    fd.append('session_path', payload.session_path)
    fd.append('text', payload.text)
    fd.append('remotion_theme', payload.remotion_theme)
    if (payload.accent) fd.append('accent', payload.accent)
    return request<{
      ok: boolean
      theme: string
      preview_path: string
      preview_url?: string
    }>('/api/publish/remotion_preview', { method: 'POST', body: fd })
  },

  publishLecturerCropAuto: (sessionPath: string, timeSec = 0.8) => {
    const fd = new FormData()
    fd.append('session_path', sessionPath)
    fd.append('time_sec', String(timeSec))
    return request<{
      ok: boolean
      crop: { x: number; y: number; w: number; h: number }
      preview_path: string
      frame_path?: string
      mtime: number
      source_size: { w: number; h: number }
    }>('/api/publish/lecturer_crop_auto', { method: 'POST', body: fd })
  },

  publishLecturerCropFrame: (sessionPath: string, timeSec = 0.8) => {
    const fd = new FormData()
    fd.append('session_path', sessionPath)
    fd.append('time_sec', String(timeSec))
    return request<{
      ok: boolean
      frame_path: string
      mtime: number
      source_size: { w: number; h: number }
    }>('/api/publish/lecturer_crop_frame', { method: 'POST', body: fd })
  },

  publishStream: async (
    fd: FormData,
    onProgress: (p: number, msg?: string) => void,
    signal?: AbortSignal,
  ): Promise<StageResult> => {
    const res = await fetch('/api/publish/run/stream', { method: 'POST', body: fd, signal })
    if (!res.ok) {
      let detail = res.statusText
      try {
        const body = await res.json()
        detail = body.detail || JSON.stringify(body)
      } catch {
        /* ignore */
      }
      throw new Error(detail)
    }
    if (!res.body) throw new Error('无响应流')

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    let result: StageResult | null = null
    let displayPct = 0
    let lastRealAt = Date.now()
    const simTimer = window.setInterval(() => {
      if (Date.now() - lastRealAt > 2000 && displayPct < 0.9) {
        displayPct = Math.min(displayPct + 0.005, 0.9)
        onProgress(displayPct)
      }
    }, 800)

    const onAbort = () => {
      void reader.cancel().catch(() => undefined)
    }
    signal?.addEventListener('abort', onAbort)

    try {
      while (true) {
        if (signal?.aborted) throw new DOMException('任务已取消', 'AbortError')
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const blocks = buf.split('\n\n')
        buf = blocks.pop() || ''
        for (const block of blocks) {
          const line = block.trim()
          if (!line.startsWith('data: ')) continue
          const data = JSON.parse(line.slice(6)) as {
            type: string
            p?: number
            msg?: string
            data?: { log?: string; video_path?: string } & Record<string, unknown>
          }
          if (data.type === 'progress' && typeof data.p === 'number') {
            lastRealAt = Date.now()
            displayPct = Math.max(displayPct, data.p)
            onProgress(data.p, data.msg)
          } else if (data.type === 'done' && data.data) {
            result = { log: data.data.log || '', data: data.data }
            onProgress(1, '完成')
          } else if (data.type === 'error') {
            throw new Error(data.msg || '字幕刻录失败')
          }
        }
      }
    } finally {
      signal?.removeEventListener('abort', onAbort)
      window.clearInterval(simTimer)
    }
    if (!result) throw new Error(signal?.aborted ? '任务已取消' : '字幕刻录未返回结果')
    return result
  },

  publish: (fd: FormData) => request<StageResult>('/api/publish/run', { method: 'POST', body: fd }),

  publishAutoPost: (payload: {
    session_path: string
    video_path?: string
    title?: string
    description?: string
    topics?: string[] | string
    platforms?: string[]
    platform?: string
  }) =>
    request<StageResult>('/api/publish/auto_post', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  bgmLibrary: () =>
    request<Array<{
      id: string
      name: string
      mood: string
      category?: string
      ready: boolean
      clip_start?: number
      duration_sec?: number
      preview_url: string | null
      source?: string
      user?: boolean
    }>>(
      '/api/publish/bgm',
    ),

  bgmUpload: (file: File, name = '') => {
    const fd = new FormData()
    fd.append('file', file)
    if (name) fd.append('name', name)
    return request<{
      id: string
      name: string
      mood: string
      category?: string
      ready: boolean
      duration_sec?: number
      preview_url: string | null
      user?: boolean
    }>('/api/publish/bgm/upload', { method: 'POST', body: fd })
  },

  bgmDelete: (bgmId: string) =>
    request<{ ok: boolean }>(`/api/publish/bgm/${encodeURIComponent(bgmId)}`, { method: 'DELETE' }),

  publishCues: (payload: {
    session_path: string
    script: string
    subtitle_pause?: number
    subtitle_max_chars?: number
    subtitle_font_size?: number
    output_aspect?: string
    prefer_tts?: boolean
  }) =>
    request<{
      cues: { index: number; start: number; end: number; text: string }[]
      duration: number
      timing_note: string
      timing_mode: string
      has_dubbing: boolean
      pause_mode?: string
      split_chars?: number
    }>('/api/publish/cues', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  alignPublishDubbing: (sessionPath: string) =>
    request<{ ok: boolean; segment_count: number; duration: number; source: string }>(
      '/api/publish/align',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_path: sessionPath, script: '' }),
      },
    ),

  alignPublishVideoAudio: (sessionPath: string) =>
    request<{ ok: boolean; segment_count: number; duration: number; source: string }>(
      '/api/publish/align_video',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_path: sessionPath, script: '' }),
      },
    ),

  extractPublishSubtitles: (payload: {
    session_path: string
    use_video_audio?: boolean
    update_script?: boolean
    subtitle_font_size?: number
    output_aspect?: string
  }) =>
    request<{
      ok: boolean
      cues: { index: number; start: number; end: number; text: string }[]
      script: string
      script_updated: boolean
      duration: number
      timing_note: string
      timing_mode: string
      split_chars?: number
      segment_count?: number
    }>('/api/publish/extract_subtitles', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  uploadPipAsset: (sessionPath: string, cueIndex: number, file: File) => {
    const fd = new FormData()
    fd.append('session_path', sessionPath)
    fd.append('cue_index', String(cueIndex))
    fd.append('media', file)
    return request<{
      ok: boolean
      cue_index: number
      media_path: string
      media_type: 'image' | 'video'
    }>('/api/publish/pip_asset', { method: 'POST', body: fd })
  },

  publishPipFrame: (sessionPath: string, mediaPath: string, timeSec = 0) => {
    const fd = new FormData()
    fd.append('session_path', sessionPath)
    fd.append('media_path', mediaPath)
    fd.append('time_sec', String(timeSec))
    return request<{
      ok: boolean
      frame_path: string
      duration_sec: number | null
      time_sec: number
    }>('/api/publish/pip_frame', { method: 'POST', body: fd })
  },

  publishPipFromLibrary: (sessionPath: string, cueIndex: number, assetId: string) => {
    const fd = new FormData()
    fd.append('session_path', sessionPath)
    fd.append('cue_index', String(cueIndex))
    fd.append('asset_id', assetId)
    return request<{
      ok: boolean
      cue_index: number
      media_path: string
      media_type: 'image' | 'video'
      asset_id: string
      name: string
    }>('/api/publish/pip_asset_from_library', { method: 'POST', body: fd })
  },

  publishHyperframeSuggest: (text: string, aspect = 'portrait_9_16') => {
    const fd = new FormData()
    fd.append('text', text)
    fd.append('aspect', aspect)
    return request<{
      ok: boolean
      theme: string
      layout: string
      aspect: string
      reasons: string[]
      color_keywords: boolean
      auto_background: boolean
      sample: string
      remotion_theme?: string
      remotion_reasons?: string[]
    }>('/api/publish/hyperframe_suggest', { method: 'POST', body: fd })
  },

  publishHyperframeFillCues: (payload: {
    session_path: string
    theme: string
    layout?: string
    aspect?: string
    cues_json: string
    skip_indices_json: string
    target_indices_json?: string
    smart_merge?: boolean
    force_contiguous?: boolean
    smart_style?: boolean
    remotion_captions?: boolean
    font_id?: string
    font_scale?: number
    bg_mode?: string
    bg_prompt?: string
    remotion_theme?: string
  }) => {
    const fd = new FormData()
    fd.append('session_path', payload.session_path)
    fd.append('theme', payload.theme)
    if (payload.layout) fd.append('layout', payload.layout)
    if (payload.aspect) fd.append('aspect', payload.aspect)
    fd.append('cues_json', payload.cues_json)
    fd.append('skip_indices_json', payload.skip_indices_json)
    if (payload.target_indices_json) fd.append('target_indices_json', payload.target_indices_json)
    fd.append('smart_merge', payload.smart_merge === false ? 'false' : 'true')
    const force =
      payload.force_contiguous === true ||
      (payload.force_contiguous !== false && !!payload.target_indices_json)
    fd.append('force_contiguous', force ? 'true' : 'false')
    fd.append('smart_style', payload.smart_style === false ? 'false' : 'true')
    fd.append('remotion_captions', payload.remotion_captions === false ? 'false' : 'true')
    if (payload.font_id) fd.append('font_id', payload.font_id)
    if (payload.font_scale != null) fd.append('font_scale', String(payload.font_scale))
    if (payload.bg_mode) fd.append('bg_mode', payload.bg_mode)
    if (payload.bg_prompt != null) fd.append('bg_prompt', payload.bg_prompt)
    if (payload.remotion_theme) fd.append('remotion_theme', payload.remotion_theme)
    return request<{
      ok: boolean
      count: number
      layout?: string
      force_contiguous?: boolean
      smart_style?: boolean
      remotion_captions?: boolean
      work_dir?: string
      library_saved?: number
      note?: string
      assignments: Array<{
        cue_indices: number[]
        start: number
        end: number
        media_path: string
        display_duration_sec?: number
        play_full_video?: boolean
        auto_hyperframe?: boolean
        scene_layout?: string
      }>
    }>('/api/publish/hyperframe_fill_cues', { method: 'POST', body: fd })
  },

  publishHyperframeRestyle: (payload: {
    session_path: string
    cues_json: string
    assignments_json: string
    theme: string
    layout?: string
    aspect?: string
    font_id?: string
    font_scale?: number
    bg_mode?: string
    bg_prompt?: string
    remotion_theme?: string
    remotion_captions?: boolean
  }) => {
    const fd = new FormData()
    fd.append('session_path', payload.session_path)
    fd.append('cues_json', payload.cues_json)
    fd.append('assignments_json', payload.assignments_json)
    fd.append('theme', payload.theme)
    if (payload.layout) fd.append('layout', payload.layout)
    if (payload.aspect) fd.append('aspect', payload.aspect)
    if (payload.font_id) fd.append('font_id', payload.font_id)
    if (payload.font_scale != null) fd.append('font_scale', String(payload.font_scale))
    if (payload.bg_mode) fd.append('bg_mode', payload.bg_mode)
    if (payload.bg_prompt != null) fd.append('bg_prompt', payload.bg_prompt)
    if (payload.remotion_theme) fd.append('remotion_theme', payload.remotion_theme)
    fd.append('remotion_captions', payload.remotion_captions === false ? 'false' : 'true')
    return request<{
      ok: boolean
      count: number
      style_pack?: Record<string, string>
      work_dir?: string
      library_saved?: number
      note?: string
      assignments: Array<{
        cue_indices: number[]
        start: number
        end: number
        media_path: string
        display_duration_sec?: number
        play_full_video?: boolean
        auto_hyperframe?: boolean
        scene_layout?: string
      }>
    }>('/api/publish/hyperframe_restyle', { method: 'POST', body: fd })
  },

  assetPickerItems: () =>
    request<{
      items: Array<{
        id: string
        name: string
        group_id: string
        asset_type: string
        media_type: 'image' | 'video'
        preview_url?: string | null
        media_path?: string
      }>
    }>('/api/assets/picker'),

  coverTemplates: () =>
    request<{ templates: CoverTemplate[] }>('/api/cover/templates'),

  coverTemplateDetail: (id: string) =>
    request<{ template: CoverTemplate | null }>(
      `/api/cover/template?tid=${encodeURIComponent(id)}`,
    ),

  saveCoverTemplate: (template: CoverTemplate) =>
    request<{ template: CoverTemplate }>('/api/cover/template', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ template_json: template }),
    }),

  deleteCoverTemplate: (id: string) =>
    request<{ ok: boolean }>(
      `/api/cover/template?tid=${encodeURIComponent(id)}`,
      { method: 'DELETE' },
    ),

  renderCover: (fd: FormData) =>
    request<StageResult>('/api/cover/render', { method: 'POST', body: fd }),

  prepareCoverSubject: (fd: FormData) =>
    request<StageResult>('/api/cover/prepare_subject', { method: 'POST', body: fd }),

  coverExtractFrame: (payload: {
    session_path: string
    time_sec?: number
    video_path?: string
  }) => {
    const fd = new FormData()
    fd.append('session_path', payload.session_path)
    fd.append('time_sec', String(payload.time_sec ?? 0.5))
    if (payload.video_path) fd.append('video_path', payload.video_path)
    return request<{
      ok: boolean
      frame_path: string
      mtime: number
      video_path: string
      time_sec: number
    }>('/api/cover/frame', { method: 'POST', body: fd })
  },

  uploadCoverAsset: (sessionPath: string, file: File) => {
    const fd = new FormData()
    fd.append('session_path', sessionPath)
    fd.append('image', file)
    return request<{ ok: boolean; path: string }>('/api/cover/asset', { method: 'POST', body: fd })
  },

  coverAssetFromUrl: (sessionPath: string, url: string) =>
    request<{ ok: boolean; path: string; url: string }>('/api/cover/asset_url', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_path: sessionPath, url }),
    }),

  coverSuggest: (script: string, sessionPath?: string, save = true) =>
    request<{
      ok: boolean
      title?: string
      subtitle?: string
      description?: string
      topics?: string[]
      saved?: boolean
      message?: string
    }>('/api/cover/suggest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        script,
        session_path: sessionPath || '',
        save: !!sessionPath && save,
      }),
    }),

  assetLibrary: () =>
    request<{
      groups: Array<{ id: string; name: string; builtin?: boolean }>
      items: Array<{
        id: string
        group_id: string
        name: string
        asset_type: string
        kind: 'file' | 'url'
        preview_url?: string | null
        url?: string
      }>
    }>('/api/assets'),

  createAssetGroup: (name: string) =>
    request<{ id: string; name: string }>('/api/assets/groups', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    }),

  deleteAssetGroup: (groupId: string) =>
    request<{ ok: boolean }>(`/api/assets/groups/${encodeURIComponent(groupId)}`, { method: 'DELETE' }),

  uploadAsset: (groupId: string, name: string, file: File) => {
    const fd = new FormData()
    fd.append('group_id', groupId)
    fd.append('name', name)
    fd.append('file', file)
    return request<{ ok: boolean; item: unknown }>('/api/assets/upload', { method: 'POST', body: fd })
  },

  addAssetUrl: (groupId: string, name: string, url: string) =>
    request<{ ok: boolean; item: unknown }>('/api/assets/url', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ group_id: groupId, name, url }),
    }),

  updateAssetItem: (itemId: string, patch: { name?: string; group_id?: string }) =>
    request<{ ok: boolean }>(`/api/assets/items/${encodeURIComponent(itemId)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    }),

  deleteAssetItem: (itemId: string) =>
    request<{ ok: boolean }>(`/api/assets/items/${encodeURIComponent(itemId)}`, { method: 'DELETE' }),

  getHyperframeActiveStyle: () =>
    request<{
      theme: string
      layout: string
      aspect: string
      font_id?: string
      font_scale?: number
      bg_mode?: string
      bg_asset?: string
      bg_prompt?: string
      remotion_theme?: string
      updated_at: number
    }>('/api/assets/hyperframe/active_style'),

  setHyperframeActiveStyle: (payload: {
    theme: string
    layout: string
    aspect: string
    font_id?: string
    font_scale?: number
    bg_mode?: string
    bg_asset?: string
    bg_prompt?: string
    remotion_theme?: string
  }) =>
    request<{
      theme: string
      layout: string
      aspect: string
      font_id?: string
      font_scale?: number
      bg_mode?: string
      bg_prompt?: string
      remotion_theme?: string
      updated_at: number
    }>('/api/assets/hyperframe/active_style', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  publishPipAssignments: (session_path: string) =>
    request<{
      ok: boolean
      assignments: Array<{
        cue_indices: number[]
        start: number
        end: number
        media_path: string
        display_duration_sec?: number
        play_full_video?: boolean
        auto_hyperframe?: boolean
        scene_layout?: string
        content_style?: string
        compose_mode?: string
        position?: string
        scale?: number
      }>
      work_dir?: string
      note?: string
    }>(`/api/publish/pip_assignments?session_path=${encodeURIComponent(session_path)}`),

  resetPublishMix: (session_path: string, delete_generated = true) =>
    request<{
      ok: boolean
      message?: string
      assignments: unknown[]
      removed_files?: number
      removed_dirs?: number
    }>('/api/publish/reset_mix', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_path, delete_generated }),
    }),

  deletePipAssignment: (
    session_path: string,
    payload: { cue_indices?: number[]; media_path?: string; delete_media?: boolean },
  ) =>
    request<{
      ok: boolean
      message?: string
      assignments: Array<Record<string, unknown>>
      removed?: number
      deleted_files?: number
    }>('/api/publish/pip_assignments/delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_path,
        cue_indices: payload.cue_indices || [],
        media_path: payload.media_path || '',
        delete_media: payload.delete_media !== false,
      }),
    }),

  hyperframeThemes: () =>
    request<{
      themes: Array<{
        id: string
        label: string
        top: string
        bottom: string
        text: string
        accent: string
        outline: string
      }>
      fonts?: Array<{ id: string; label: string }>
      bg_modes?: Array<{ id: string; label: string }>
      remotion_themes?: Array<{ id: string; label: string }>
      layouts: Array<{
        id: string
        label: string
        animated: boolean
        width: number
        height: number
      }>
      aspects: Array<{
        id: string
        label: string
        width: number
        height: number
        ratio: string
      }>
    }>('/api/assets/hyperframe/themes'),

  hyperframePreviewUrl: (
    theme: string,
    text: string,
    layout = 'kinetic',
    aspect = 'portrait_9_16',
    fontScale = 1,
    composeMode = '',
  ) => {
    const q = new URLSearchParams({
      theme,
      layout,
      aspect,
      text: text.trim().slice(0, 160) || 'HyperFrames 预览',
      font_scale: String(Math.max(0.7, Math.min(2, fontScale || 1))),
    })
    if (composeMode) q.set('compose_mode', composeMode)
    return `/api/assets/hyperframe/preview?${q}`
  },

  hyperframePreviewMotionUrl: (
    theme: string,
    text: string,
    layout = 'kinetic',
    aspect = 'portrait_9_16',
    fontScale = 1,
    composeMode = '',
  ) => {
    const q = new URLSearchParams({
      theme,
      layout,
      aspect,
      text: text.trim().slice(0, 160) || 'HyperFrames 预览',
      font_scale: String(Math.max(0.7, Math.min(2, fontScale || 1))),
    })
    if (composeMode) q.set('compose_mode', composeMode)
    return `/api/assets/hyperframe/preview_motion?${q}`
  },

  generateHyperframeAsset: (payload: {
    text: string
    mode: 'image' | 'video' | 'slideshow'
    theme: string
    layout?: string
    aspect?: string
    group_id?: string
    name?: string
    duration_sec?: number
    pause_sec?: number
    max_chars?: number
  }) => {
    const fd = new FormData()
    fd.append('text', payload.text)
    fd.append('mode', payload.mode)
    fd.append('theme', payload.theme)
    if (payload.layout) fd.append('layout', payload.layout)
    if (payload.aspect) fd.append('aspect', payload.aspect)
    fd.append('group_id', payload.group_id || 'card')
    if (payload.name) fd.append('name', payload.name)
    if (payload.duration_sec != null) fd.append('duration_sec', String(payload.duration_sec))
    if (payload.pause_sec != null) fd.append('pause_sec', String(payload.pause_sec))
    if (payload.max_chars != null) fd.append('max_chars', String(payload.max_chars))
    return request<{ ok: boolean; item: unknown; mode: string; theme: string }>(
      '/api/assets/hyperframe',
      { method: 'POST', body: fd },
    )
  },

  jobsEnqueue: (body: {
    session_path: string
    type:
      | 'hyperframe_fill_cues'
      | 'hyperframe_restyle'
      | 'publish_run'
      | 'tts_synthesize'
      | 'avatar_lipsync'
      | 'engine_install'
      | 'script_extract'
      | 'subtitle_asr'
    payload: Record<string, unknown>
    title?: string
    force?: boolean
    priority?: number
  }) =>
    request<{
      ok: boolean
      duplicate?: boolean
      message?: string
      existing_job_id?: string
      job?: JobRecord
      existing_job?: JobRecord
    }>('/api/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),

  jobsList: (session_path: string, status?: string) =>
    request<{ ok: boolean; jobs: JobRecord[]; active_count: number }>(
      `/api/jobs?session_path=${encodeURIComponent(session_path)}${
        status ? `&status=${encodeURIComponent(status)}` : ''
      }`,
    ),

  jobsGet: (session_path: string, job_id: string) =>
    request<{ ok: boolean; job: JobRecord }>(
      `/api/jobs/${encodeURIComponent(job_id)}?session_path=${encodeURIComponent(session_path)}`,
    ),

  jobsCancel: (session_path: string, job_id: string) =>
    request<{ ok: boolean; job?: JobRecord; message?: string; cancel_requested?: boolean }>(
      `/api/jobs/${encodeURIComponent(job_id)}/cancel?session_path=${encodeURIComponent(session_path)}`,
      { method: 'POST' },
    ),

  jobsPrioritize: (session_path: string, job_id: string) =>
    request<{ ok: boolean; job?: JobRecord; message?: string }>(
      `/api/jobs/${encodeURIComponent(job_id)}/prioritize?session_path=${encodeURIComponent(session_path)}`,
      { method: 'POST' },
    ),

  jobsRequeue: (session_path: string, job_id: string) =>
    request<{ ok: boolean; job?: JobRecord; message?: string }>(
      `/api/jobs/${encodeURIComponent(job_id)}/requeue?session_path=${encodeURIComponent(session_path)}`,
      { method: 'POST' },
    ),

  jobsDelete: (session_path: string, job_id: string, delete_sources = false) =>
    request<{
      ok: boolean
      deleted_sources?: boolean
      removed_files?: number
      removed_dirs?: number
      pruned_assignments?: number
      pruned_lipsyncs?: number
    }>(
      `/api/jobs/${encodeURIComponent(job_id)}?session_path=${encodeURIComponent(session_path)}${
        delete_sources ? '&delete_sources=true' : ''
      }`,
      { method: 'DELETE' },
    ),

  jobsClearHistory: (session_path: string) =>
    request<{ ok: boolean; removed: number }>(
      `/api/jobs/clear_history?session_path=${encodeURIComponent(session_path)}`,
      { method: 'POST' },
    ),
}

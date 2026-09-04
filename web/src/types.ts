export type SessionItem = {
  path: string
  id: string
  name: string
  created_at: string
  badges: string[]
  status: string
  is_current?: boolean
}

export type SessionSnapshot = {
  path: string
  name: string
    script: string
    script_extract?: string
    script_rewritten?: string
    script_legal?: string
    script_manual?: string
    dubbing_duration?: number | null
    dubbing_mtime?: number | null
    lipsync_mtime?: number | null
    lipsync_stale?: boolean
    share_url: string
  cdn_md: string
  preview_video: string | null
  dubbing_audio: string | null
  selected_dub: string | null
  selected_lipsync?: string | null
  dubs: { id?: string; name: string; path: string; created_at?: string; duration_sec?: number | null; segment_count?: number | null; source?: string }[]
  lipsyncs?: { id?: string; name: string; path: string; created_at?: string; source?: string; backend?: string; mode?: string }[]
  dubbing_segments?: { index: number; start: number; end: number; text: string }[]
  lipsync_video: string | null
  media_input: string | null
  tts_log: string
  lipsync_log: string
  publish_title?: string
  publish_subtitle?: string
  publish_description?: string
  publish_topics?: string[]
}

export type SettingsPayload = {
  script_mode: string
  script_engine: string
  whisper_model: string
  tts_mode: string
  tts_engine: string
  avatar_mode: string
  avatar_engine: string
  publish_mode: string
  publish_engine: string
  cdn_api_key: string
  cdn_provider?: string
  cdn_api_url?: string
  transcript_api_key: string
  transcript_provider?: string
  transcript_api_url?: string
  rewrite_api_key: string
  qwen3_tts_api_key: string
}

export type VoiceItem = {
  uid: string
  label: string
  kind: string
  preview_url?: string | null
  local_path?: string | null
  category?: string
  hint?: string
}

export type StageResult = {
  log: string
  message?: string
  data: Record<string, unknown>
}

export type TtsFieldOption = { value: string; label: string }

export type TtsModelField = {
  key: string
  section: string
  name: string
  label: string
  type: 'text' | 'number' | 'boolean' | 'select' | 'password'
  value: string | number | boolean
  step?: number
  choices?: TtsFieldOption[]
  configured?: boolean
  hint?: string
}

export type TtsEngineHealth = {
  ok: boolean
  preset_ready?: boolean
  configured?: boolean
  reachable?: boolean | null
  model?: string
  api_key_hint?: string
  message: string
}

export type TtsEngineProfile = {
  engine: string
  label: string
  hardware: string
  supports_clone: boolean
  supports_dialect: boolean
  supports_speed: boolean
  online: boolean
  summary: string
  setup: string | null
}

export type TtsOptions = {
  mode: 'local' | 'cloud'
  mode_label: string
  engine: string
  engine_label: string
  profile?: TtsEngineProfile
  engines: (TtsFieldOption & { hardware?: string; summary?: string })[]
  fields: TtsModelField[]
  cloud_hint: {
    title: string
    description: string
    ready: boolean
    missing: string
    settings_keys: string[]
  } | null
  health?: TtsEngineHealth
  ready: boolean
  preset_ready?: boolean
  default_voice_uid?: string
  clone_prompt_required?: boolean
  clone_default_prompt?: string
  clone_hint?: string
}

export type StepId = 'script' | 'clone' | 'tts' | 'avatar' | 'publish'

export type CoverLayer = {
  id: string
  type: 'text' | 'image'
  label: string
  text: string
  /** behind = draw under cutout subject (big hook text) */
  depth?: 'front' | 'behind'
  x: number
  y: number
  anchor:
    | 'top_left'
    | 'top_center'
    | 'top_right'
    | 'center'
    | 'bottom_left'
    | 'bottom_center'
    | 'bottom_right'
  font_size_ratio: number
  font_weight: 'normal' | 'bold'
  color: string
  stroke_color: string
  stroke_width: number
  effect: 'none' | 'shadow' | 'outline' | 'glow' | 'neon' | 'pill'
  glow_color?: string
  pill_color?: string
  pill_alpha?: number
  max_width_ratio: number
  /** Soft cap on wrapped lines; renderer shrinks / truncates to fit. */
  max_lines?: number
  /** Vertical budget as fraction of canvas height (auto-shrink). */
  band_height_ratio?: number
  rotation?: number
  /** vertical = 竖排标题（参考剪映/奇异） */
  writing_mode?: 'horizontal' | 'vertical'
  image_src?: string
  width_ratio?: number
}

export type CoverSubject = {
  enabled: boolean
  bg_mode: 'blur' | 'original' | 'white' | 'black'
  blur_radius: number
  outline: 'none' | 'solid' | 'dashed' | 'glow'
  outline_color: string
  outline_width: number
  glow_color: string
  scale: number
  fill_ratio: number
  x_offset: number
  y_offset: number
}

export type CoverTemplate = {
  id: string
  name: string
  builtin: boolean
  subject?: CoverSubject
  background: {
    overlay: 'none' | 'dark_flat' | 'light_flat' | 'bottom_gradient' | 'top_gradient'
    overlay_alpha: number
  }
  layers: CoverLayer[]
}

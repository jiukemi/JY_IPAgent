"""Pydantic schemas for REST API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ApiOk(BaseModel):
    ok: bool = True


class DeploymentStep(BaseModel):
    mode: str
    engine: str
    label: str


class DeploymentSummary(BaseModel):
    steps: list[DeploymentStep]


class SettingsPayload(BaseModel):
    script_mode: str
    script_engine: str
    whisper_model: str = "small"
    tts_mode: str
    tts_engine: str
    avatar_mode: str
    avatar_engine: str
    publish_mode: str
    publish_engine: str
    cdn_api_key: str = ""
    cdn_provider: str = ""
    cdn_api_url: str = ""
    transcript_api_key: str = ""
    transcript_provider: str = ""
    transcript_api_url: str = ""
    rewrite_api_key: str = ""
    qwen3_tts_api_key: str = ""


class SettingsResponse(BaseModel):
    settings: SettingsPayload
    summary_md: str


class SessionItem(BaseModel):
    path: str
    id: str
    name: str
    created_at: str
    badges: list[str]
    status: str
    is_current: bool = False


class SessionSnapshot(BaseModel):
    path: str
    name: str
    script: str = ""
    script_extract: str = ""
    script_rewritten: str = ""
    script_legal: str = ""
    share_url: str = ""
    cdn_md: str = ""
    preview_video: str | None = None
    dubbing_audio: str | None = None
    selected_dub: str | None = None
    selected_lipsync: str | None = None
    dubs: list[dict] = Field(default_factory=list)
    lipsyncs: list[dict] = Field(default_factory=list)
    lipsync_video: str | None = None
    media_input: str | None = None
    tts_log: str = ""
    lipsync_log: str = ""
    dubbing_mtime: int | None = None
    lipsync_mtime: int | None = None
    lipsync_stale: bool = False
    publish_title: str = ""
    publish_subtitle: str = ""
    publish_description: str = ""
    publish_topics: list[str] = Field(default_factory=list)


class SessionRename(BaseModel):
    name: str


class ShareUrlBody(BaseModel):
    session_path: str
    share_url: str = ""


class RewriteBody(BaseModel):
    session_path: str
    script: str = ""
    intensity: str = "medium"


class HotwordBody(BaseModel):
    session_path: str = ""
    identity: str = ""
    profession: str = ""
    industry: str = ""
    product: str = ""
    audience: str = ""
    roles: list[dict] = Field(default_factory=list)
    mix_roles: bool = False


class GenerateScriptBody(BaseModel):
    session_path: str
    identity: str = ""
    profession: str = ""
    industry: str = ""
    product: str = ""
    audience: str = ""
    selling_points: str = ""
    duration_sec: int = 45
    hotwords: list[str] = Field(default_factory=list)
    extra: str = ""
    roles: list[dict] = Field(default_factory=list)
    mix_roles: bool = False
    # True = 拉热词生成文案（先热词再成稿）
    auto_hotwords: bool = False
    # extract | rewritten — where to save generated script
    save_as: str = "rewritten"
    # Resume after pause: pass already-generated draft
    continue_from: str = ""


class CompetitorAnalyzeBody(BaseModel):
    session_path: str
    profile_url: str = ""
    competitor_id: str = ""
    roles: list[dict] = Field(default_factory=list)
    mix_roles: bool = False
    duration_sec: int = 45
    hotwords: list[str] = Field(default_factory=list)
    extra: str = ""
    deep_transcript: bool = True
    save_as: str = "rewritten"


class LegalBody(BaseModel):
    session_path: str
    script: str = ""
    source: str = "extract"


class CoverTemplateBody(BaseModel):
    template_json: str | dict = "{}"


class CoverRenderBody(BaseModel):
    session_path: str
    template_json: str = "{}"
    title: str = ""
    subtitle: str = ""


class ScriptSaveBody(BaseModel):
    session_path: str
    variant: str = Field(..., description="extract | rewritten | legal | manual")
    text: str = ""


class TtsBody(BaseModel):
    session_path: str
    text: str
    voice_uid: str
    speed_mode: str = "balanced"
    backend: str | None = None
    style_extra: str = ""


class TtsPreviewBody(BaseModel):
    session_path: str
    voice_uid: str
    text: str = ""
    style_extra: str = ""
    speed_mode: str = "balanced"
    backend: str | None = None
    preview_key: str = "styled"


class TtsSettingsPayload(BaseModel):
    engine: str | None = None
    values: dict[str, str | bool | float | int] = Field(default_factory=dict)


class LipsyncBody(BaseModel):
    session_path: str
    track_mode: str = "digital"
    backend: str = ""
    quality: str = "natural"
    avatar_id: str | None = None
    audio_path: str | None = None
    pose_style: float = 0
    still_head: bool = False
    expression_scale: float = 1.0


class PublishBody(BaseModel):
    session_path: str
    script: str = ""
    title: str = ""
    cover_time: float = 0.5
    template: str = "classic_bottom"
    subtitle_style: str = "bottom_white"
    subtitle_pause: float = 0.35
    subtitle_font_size: int = 16
    subtitle_color: str = "#FFFFFF"
    subtitle_outline: int = 1
    subtitle_shadow: int = 0
    subtitle_position: str = "bottom"
    burn_subtitles: bool = True
    embed_cover: bool = True
    pip_mode: str = "none"
    pip_position: str = "top_right"
    pip_scale: float = 0.28
    pip_margin: int = 24
    hyperframes_consent: bool = False
    pip_cues_json: str = "[]"
    cues_json: str = ""


class PublishCuesBody(BaseModel):
    session_path: str
    script: str = ""
    subtitle_pause: float = 0.35
    subtitle_max_chars: int = 12
    subtitle_font_size: int = 16
    output_aspect: str = "portrait_9_16"


class StageResult(BaseModel):
    log: str = ""
    message: str = ""
    data: dict = Field(default_factory=dict)


class VoiceItem(BaseModel):
    uid: str
    label: str
    kind: str
    preview_url: str | None = None
    category: str = ""
    hint: str = ""

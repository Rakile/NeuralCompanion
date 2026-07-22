export type RemoteConnectionStatus = 'disconnected' | 'connecting' | 'connected' | 'error';
export type RemoteTransport = 'none' | 'polling' | 'websocket';

export type ChatMessage = {
  id: string;
  index: number;
  role: string;
  origin?: string;
  content: string;
  created_at?: number | string | null;
  image_url_path?: string;
  image_content_type?: string;
};

export type RuntimeStatus = {
  lifecycle_state?: string;
  running?: boolean;
  engine_connected?: boolean;
  chat_provider?: string;
  model_name?: string;
  tts_backend?: string;
  avatar_engine?: string;
  microphone_state?: string;
};

export type RuntimeSettingsSummary = {
  chat_provider?: string;
  model_name?: string;
  stt_backend?: string;
  stt_model_size?: string;
  tts_backend?: string;
  visual_reply_provider?: string;
};

export type AudioChunk = {
  id: string;
  url_path: string;
  index: number;
  sequence_index?: number;
  text?: string;
  speaker?: string;
  duration_seconds?: number;
  content_type?: string;
  created_at?: number;
};

export type AudioState = {
  available?: boolean;
  status?: string;
  generation?: number;
  backend_playback_suppressed?: boolean;
  items?: AudioChunk[];
};

export type VisualRemoteRequest = {
  request_id?: string;
  status?: string;
  accepted?: boolean;
  message?: string;
  prompt_preview?: string;
  image_available?: boolean;
  created_at?: number;
  updated_at?: number;
};

export type VisualState = {
  service_available?: boolean;
  state?: {
    status?: string;
    image_url_path?: string;
    image_cache_key?: string;
    image_content_type?: string;
    caption?: string;
    updated_at?: number;
  };
  settings?: Record<string, unknown>;
  requests?: VisualRemoteRequest[];
  latest_request?: VisualRemoteRequest;
};

export type MuseTalkState = {
  available?: boolean;
  state?: {
    status?: string;
    frame_url_path?: string;
    stream_url_path?: string;
    text?: string;
    fps?: number;
    chunk_id?: string;
    preview_frame_index?: number;
    updated_at?: number;
  };
  frames?: Array<{ id: string; url_path: string; index: number; content_type?: string }>;
  feed?: Array<{ _seq?: number; frame_url_path?: string; status?: string; frame_index?: number }>;
  pipeline?: Record<string, unknown>;
  stream_url_path?: string;
};

export type MprcPersona = {
  id: string;
  display_name?: string;
  role?: string;
  enabled?: boolean;
  active?: boolean;
  current_speaker?: boolean;
  narrator?: boolean;
  description?: string;
  visual_enabled?: boolean;
  voice_enabled?: boolean;
};

export type MprcSegment = {
  segment_id?: number | string;
  speaker_id?: string;
  speaker_name?: string;
  role?: string;
  text?: string;
};

export type MprcChoice = {
  id?: string;
  text?: string;
};

export type MprcCastDevice = {
  name?: string;
  label?: string;
  uuid?: string;
  cast_type?: string;
  model_name?: string;
  host?: string;
};

export type MprcCastState = {
  available?: boolean;
  dependency_error?: string;
  devices?: MprcCastDevice[];
  selected_device?: string;
  active_device?: string;
  casting?: boolean;
  busy?: boolean;
  status?: string;
  stream?: {
    running?: boolean;
    url?: string;
    port?: number;
  };
};

export type MprcMemoryState = {
  available?: boolean;
  backend?: string;
  configured_backend?: string;
  database_available?: boolean;
  database_status?: string;
  databank_available?: boolean;
  configured_databank_source_count?: number;
  indexed_databank_source_count?: number;
  event_count?: number;
  chapter_count?: number;
  pinned_fact_count?: number;
  character_memory_count?: number;
  location_memory_count?: number;
  fallback_note?: string;
  message?: string;
};

export type MprcState = {
  available?: boolean;
  message?: string;
  schema_version?: number;
  remote?: Record<string, unknown>;
  session?: {
    enabled?: boolean;
    mode?: string;
    turn_index?: number;
    active_persona_id?: string;
    current_speaker_id?: string;
    scene_title?: string;
    location?: string;
    time_of_day?: string;
    mood?: string;
    objective?: string;
    scene_summary?: string;
    ar_state?: Record<string, unknown>;
    character_state_summaries?: Record<string, string>;
  };
  personas?: MprcPersona[];
  latest_reply?: string;
  segments?: MprcSegment[];
  choices?: MprcChoice[];
  speech_audio?: AudioState;
  audio_cues?: Array<Record<string, unknown>>;
  memory?: MprcMemoryState;
  cast?: MprcCastState;
  visual?: {
    latest_prompt?: string;
    last_visual_reply_at?: number;
    auto_image_count?: number;
  };
};

export type BuddyChatPersonaState = {
  id?: string;
  display_name?: string;
  enabled?: boolean;
  source?: string;
  provider_id?: string;
  model?: string;
  voice_enabled?: boolean;
};

export type BuddyChatState = {
  available?: boolean;
  enabled?: boolean;
  reply_mode?: string;
  llm_mode?: string;
  persona_count?: number;
  active_persona_count?: number;
  max_speakers?: number;
  per_persona_provider_count?: number;
  shared_provider?: {
    provider_id?: string;
    model?: string;
  };
  personas?: BuddyChatPersonaState[];
  message?: string;
  last_provider_error?: string;
  last_provider_error_at?: number;
};

export type RemoteState = {
  status_line?: string;
  runtime_status?: RuntimeStatus;
  runtime_settings?: RuntimeSettingsSummary;
  engine?: RuntimeStatus;
  controls?: { actions?: string[]; last_action?: string };
  chat?: { message_count?: number; messages?: ChatMessage[] };
  media?: AudioState;
  visual?: VisualState;
  musetalk?: MuseTalkState;
  mprc?: MprcState;
  buddy_chat?: BuddyChatState;
  features?: Record<string, boolean>;
};

export type PublicRemoteStatus = {
  running?: boolean;
  host?: string;
  port?: number;
  url?: string;
  pairing_code_digits?: number;
  connected_clients?: number;
  started_at?: number;
};

export type RemoteHealth = {
  service?: string;
  status?: string;
  bridge?: {
    ok?: boolean;
    status?: number | string;
    error?: string;
  };
  remote?: PublicRemoteStatus;
};

export type RemoteEnvelope<T> = {
  ok: boolean;
  status?: number | string;
  error?: string;
} & T;

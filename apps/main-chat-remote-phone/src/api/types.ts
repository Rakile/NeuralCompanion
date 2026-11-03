export type RemoteConnectionStatus = 'disconnected' | 'connecting' | 'connected' | 'error';
export type PhoneReplyReceipt = {
  phone_request_id: string;
  interruption_id: string;
  started_chunk_ids: string[];
};
export type RemoteTransport = 'none' | 'polling' | 'websocket' | 'webrtc';
export type AudioMode = 'backend_hq' | 'phone_native';
export type PhoneSendResult = { accepted?: boolean; audio_mode?: AudioMode; phone_request_id?: string; state?: RemoteState };
export type PhoneSendEnvelope = RemoteEnvelope<{ result?: PhoneSendResult }>;

export type ChatMessage = {
  id: string;
  turn_id?: string;
  index: number;
  role: string;
  origin?: string;
  phone_request_id?: string;
  phone_audio_mode?: 'phone_native';
  stream_key?: string;
  provisional?: boolean;
  content: string;
  created_at?: number | string | null;
  image_url_path?: string;
  image_content_type?: string;
  display_name?: string;
  avatar_initials?: string;
  avatar_url_path?: string;
  neutral_avatar_url_path?: string;
  mood_avatar_url_paths?: Record<string, string>;
  portrait_key?: string;
  mood?: string;
  visual_replies?: InlineVisualReply[];
};

export type StreamingReplyPreview = {
  /** Text generation finished; audio and canonical commit may still be pending. */
  generation_complete?: boolean;
  id: string;
  stream_key: string;
  normal_chat_transaction_id: string;
  content: string;
  phone_request_id?: string;
  phone_audio_mode?: 'phone_native';
  display_name?: string;
  avatar_initials?: string;
};

export type InlineVisualReply = {
  id: string;
  status: 'generating' | 'ready' | 'failed';
  url_path?: string;
  content_type?: string;
  caption?: string;
  prompt_preview?: string;
  error?: string;
  created_at?: number | string | null;
  updated_at?: number | string | null;
  turn_id?: string;
  normal_chat_transaction_id?: string;
};

export type PresenceActivity = 'stopped' | 'ready' | 'listening' | 'thinking' | 'speaking' | 'failure';

export type PresenceAvatar = {
  kind: 'musetalk' | 'mood' | 'neutral' | 'initials';
  mood: string;
  url_path?: string;
  mood_url_path?: string;
  neutral_url_path?: string;
  content_type?: string;
};

export type PresenceState = {
  schema_version: 1;
  stream_id: string;
  revision: number;
  updated_at: number;
  activity: PresenceActivity;
  state_label: string;
  audio_level: number;
  mood: string;
  persona: { id: string; name: string; initials: string };
  avatar: PresenceAvatar;
  musetalk: { available: boolean; healthy: boolean };
  portrait_playback?: { message_id: string; portrait_key: string; mood: string };
};

export type QuickPersonaChoice = {
  slot: number;
  id: string;
  name: string;
  initials: string;
  active: boolean;
  avatar_url_path?: string;
  avatar_content_type?: string;
};

export type QuickPersonaState = {
  schema_version: 1;
  active_slot: number;
  items: QuickPersonaChoice[];
};

export type LlmModelChoice = { id: string; label: string; selected: boolean };
export type LlmProviderChoice = {
  id: string;
  label: string;
  selected: boolean;
  available: boolean;
  loading: boolean;
  message: string;
  models: LlmModelChoice[];
};
export type LlmModelState = {
  schema_version: 1;
  available: boolean;
  loading: boolean;
  message: string;
  selected_provider_id: string;
  selected_model_id: string;
  providers: LlmProviderChoice[];
};

export type LlmModelSelectionResponse = {
  ok: boolean;
  result: { accepted: boolean; message: string };
};

export type VoiceChoice = { id: string; label: string; selected: boolean };
export type TtsProviderChoice = {
  id: string;
  label: string;
  selected: boolean;
  available: boolean;
  story_voices: boolean;
  progressive_audio: boolean;
  message: string;
};
export type TtsProviderState = {
  schema_version: 1;
  available: boolean;
  selected_provider_id: string;
  loading: boolean;
  busy: boolean;
  message: string;
  providers: TtsProviderChoice[];
};
export type TtsProviderSelectionResponse = {
  ok: boolean;
  result: { accepted: boolean; message: string };
};
export type VoiceState = {
  schema_version: 1;
  available: boolean;
  loading: boolean;
  message: string;
  items: VoiceChoice[];
};

export type RuntimeStatus = {
  starting?: boolean;
  initializing?: boolean;
  stopping?: boolean;
  cancelling?: boolean;
  cleanup_pending?: boolean;
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
  progressive_audio?: {version:1;sample_rate:24000;channels:1};
  // Phone-local playback generation; never used as server authorization.
  playback_recovery_epoch?: number;
  id: string;
  phone_request_id?: string;
  url_path: string;
  index: number;
  sequence_index?: number;
  text?: string;
  speaker?: string;
  emotion?: string;
  duration_seconds?: number;
  content_type?: string;
  created_at?: number;
  spectrum_url_path?: string;
  spectrum_status?: 'pending' | 'ready' | 'unavailable' | string;
  spectrum_version?: number;
};

export type ProgressivePcmRead = {
  version:1; sample_rate:24000; channels:1; cursor:number; next_cursor:number;
  pcm_base64:string; finished:boolean; total_frames:number|null;
};

export type ChatCharacter = {
  automation?: {id?:string;mode?:'create'|'remake';status:string;voice_status?:string;portrait_status?:string;
    added_event_id?:string;added_at?:number;error?:string};
  id: string; conversation_id: string; revision: number; name: string; role: string; description: string; system_prompt: string;
  aliases: string[]; created_at: number; source_message_id: string; source_character_id: string; voice_description: string; preview_text: string;
  voice_id: string; voice_name?: string; voice_available?: boolean; portrait_prompt: string; portrait_asset_id: string; portrait_revision: number;
  portrait_url_path?: string; copied_persona_id: string; notice_dismissed: boolean; jobs: Record<string, string>;
};
export type CharacterJob = {
  id: string; operation_id: string; character_id: string; source_revision: number; kind: 'voice' | 'portrait';
  status: 'queued' | 'running' | 'ready' | 'failed' | 'cancelled' | 'unknown'; error: string;
  candidates: { id: string; url_path: string; name?: string; saved?: boolean; voice_id?: string; available?: boolean }[];
};
export type CharacterVoiceRemoval = {
  voice_id: string; name: string; revision: number; characters: {id:string;name:string}[];
};
export type SavedCharacterVoice = {
  id:string; name:string; description:string; url_path?:string;
  category?:string; favorite?:boolean; metadata_revision?:number;
};
export type VoiceOrganizationPatch = {category?:string; favorite?:boolean; description?:string};
export type CharacterProvider = { id: string; label: string; model_id: string; instruction_mode: string; vocabulary?: string[] };
export type ChatCharacterSnapshot = {
  automatic_creation_available?:boolean;automatic_creation_error?:string;
  automatic_add_enabled?:boolean;automatic_add_sound?:boolean;server_time?:number;
  version: 1; revision: number; conversation_id: string; allow_new_characters: boolean; voice_playback_available: boolean;
  max_characters?: number;
  character_voices_enabled?: boolean;
  structured_character_voices_available?: boolean;
  candidates?: {id:string; name:string; excerpt:string}[];
  portrait_available?: boolean; providers?: CharacterProvider[]; characters: ChatCharacter[];
  total: number; next_offset: number | null;
};

export type AudioSpectrumTimelinePayload = {
  version: 1;
  fps: 24;
  bars: 48;
  frame_count: number;
  encoding: 'uint8-base64';
  data: string;
};

export type AudioState = {
  available?: boolean;
  status?: string;
  error?: string;
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
  supported_actions?: string[];
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
    active?: boolean;
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

export type PhoneReplyAuth = { client_key: string; connection_epoch: string; shared_queue_version?: 1; reply_continuation_version?: 1 };
export type PhoneReplyContinuationStatus = PhoneReplyStatus & {
  continuation: { version: 1; available: boolean; reason?: 'expired' | 'capacity' | 'media_missing';
    items: AudioChunk[]; next_cursor: number | null; remaining_seconds: number };
};
export type PhoneReplyAction =
  | { kind: 'skip'; phone_request_id: string; operation_id: string }
  | { kind: 'playback_finished'; phone_request_id: string; operation_id: string }
  | { kind: 'onset'; receipt: PhoneReplyReceipt }
  | { kind: 'abandon'; phone_request_id: string; interruption_id: string };
export type PhoneReplyResult = {
  status: 'accepted' | 'duplicate' | 'stale' | 'unavailable' | 'busy';
  phone_request_id: string;
  next_phone_request_id: string | null;
};
export type PhoneReplyStatus = {
  phone_request_id: string;
  phase: 'pending' | 'generating' | 'complete' | 'cancelled' | 'superseded';
  last_sequence_index: number | null;
  playback_stop_requested?: boolean;
};

export type ConversationActionTarget = { message_id: string; revision: number; session_generation: number };
export type ConversationActionKind = 'regenerate' | 'retry' | 'end_waiting';
export type ConversationActionBody = { kind: ConversationActionKind; operation_id: string; target: ConversationActionTarget };
export type ConversationActionResult = { status: 'accepted' | 'stale' | 'busy' | 'unavailable'; phone_request_id: string | null; reason: string };
export type ConversationActionsSnapshot = {
  revision: number; session_generation: number; disabled_reason: string;
  regenerate: ConversationActionTarget | null; retry: ConversationActionTarget | null; end_waiting: ConversationActionTarget | null;
};

export type StoryBeat = { title: string; summary: string };
export type StoryPlanDraft = { title: string; premise: string; constraints: string; opening_cue: string; beats: StoryBeat[]; pace?: StoryPace };
export type StoryPace = 'slow' | 'medium' | 'fast';
export type StoryRefineOptions = { beat_count: number; pace: StoryPace; provider_id?: string; model_id?: string;
  plan_id?: string; revision?: number; temperature?: number;
  follow_prompt?: 'closely' | 'balanced' | 'flexible'; beat_detail?: 'short' | 'standard' | 'detailed';
  reference_plan?: StoryPlanDraft };
export type StoryPlan = StoryPlanDraft & { status: 'saved' | 'active' | 'complete'; progression: 'automatic' | 'manual';
  pace: StoryPace; replies_in_beat: number; current_beat: number; revision: number;
  last_assessed_reply_id?: string; plan_id?: string; beat_visit_id?: string };
export type StoryPlanAction = { action: 'status' | 'save' | 'start' | 'progression' | 'pace' | 'beat' | 'remove' | 'append';
  session_generation: number; revision?: number; plan?: StoryPlanDraft; mode?: 'automatic' | 'manual';
  pace?: StoryPace; index?: number; plan_id?: string; operation_id?: string; beats?: StoryBeat[] };
export type VisualAutoMode = 'off' | 'user' | 'assistant' | 'story';
export type VisualAutoStatus = { mode: VisualAutoMode; images_per_beat: number; revision: number;
  beat_count: number; active: string; story_dormant: boolean };
export type VisualAutoAction = { action: 'status' | 'update'; session_generation: number;
  revision?: number; mode?: VisualAutoMode; images_per_beat?: number };
export type StoryLibraryEntry = { entry_id: string; name: string; saved_at: string; version: number;
  current_beat: number | null; beat_count: number; character_names: string[] };
export type StoryLibraryAction = { action: 'list' | 'status' | 'save' | 'save_as' | 'open' | 'rename' | 'delete' | 'recover';
  session_generation: number; operation_id?: string; entry_id?: string; name?: string; recovery_id?: string };
export type StoryLibraryResult = { entries?: StoryLibraryEntry[]; active_entry_id?: string | null;
  entry_id?: string; name?: string; saved_at?: string; version?: number; state?: 'paused'; deleted?: boolean;
  conversation_id?: string; recovered?: boolean };
export type CommandDraftResult = { id: string; status: 'working' | 'ready' | 'error' | 'cancelled';
  text?: string; plan?: StoryPlanDraft; error?: string };

export type RemoteState = {
  /** Public identity of the desktop's in-memory ordered-output authority. */
  ordered_output_instance?: string;
  command_drafts?: Array<{ name: string; description: string }>;
  conversation_actions?: ConversationActionsSnapshot;
  status_line?: string;
  runtime_status?: RuntimeStatus;
  runtime_settings?: RuntimeSettingsSummary;
  engine?: RuntimeStatus;
  controls?: { actions?: string[]; last_action?: string; web_search?: { available: boolean; enabled: boolean; online: boolean } };
  chat?: { message_count?: number; messages?: ChatMessage[]; streaming_preview?: StreamingReplyPreview };
  media?: AudioState;
  presence?: PresenceState;
  visual?: VisualState;
  musetalk?: MuseTalkState;
  mprc?: MprcState;
  buddy_chat?: BuddyChatState;
  features?: Record<string, boolean | string | number> & { phone_native_audio?: boolean; phone_native_audio_reason?: string; phone_reply_controls_version?: number; shared_manual_queue_version?: number };
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
  gateway_id?: string;
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
export type PersonaTechnicalRules = {
  legacy_enabled: boolean;
  avatar: Record<string, { enabled: boolean; text: string }>;
  tts: Record<string, { enabled: boolean; text: string }>;
};
export type PersonaRuleCatalog = {
  activeAvatar: string; activeTts: string; hasLegacy: boolean;
  avatar: { id: string; label: string; defaultText: string }[];
  tts: { id: string; label: string; defaultText: string }[];
};
export type PersonaPrompts = {
  id: string;
  name: string;
  revision: string;
  active: boolean;
  system_prompt: string;
  technical_prompt: string;
  technical_rules?: PersonaTechnicalRules;
  rule_catalog?: PersonaRuleCatalog;
  defaults: { system_prompt: string; technical_prompt: string };
};
export type ContinuousSettings = {
  speak_user_messages?: boolean; user_voice?: string; speak_guidance_and_example?: boolean;
  mode: 'off' | 'simple' | 'ai_guided'; default_reply: string; guidance: string;
  use_premade?: boolean; guidance_preset?: string;
  guidance_strength?: number;
  separate_model: boolean; provider_id: string; model_id: string;
  context_chars: number; recent_turns: number; max_output_tokens: number;
  temperature: number; delay_seconds: number; max_turns: number; fallback: boolean;
};
export type GuidancePreset = {id:string; label:string; prompt:string; category?:string; category_label?:string};
export type ContinuousState = {
  story_complete?: boolean;
  version: 1; owned: boolean; revision: number;
  state: 'stopped' | 'paused' | 'suspended' | 'waiting' | 'delay' | 'generating' | 'ready' | 'submitting';
  reason?: string; settings?: ContinuousSettings; queue?: {id: string; text: string}[];
  force_continuation_supported?: boolean;
  structured_auto_reply_supported?: boolean;
  guidance_presets?: GuidancePreset[];
  guidance_strength_supported?: boolean;
  completed_turns?: number; remaining_seconds?: number; prepared_id?: string | null; pending_reply?: string;
  user_speech?: {text: string; voice_id: string; operation_id:string; transport:'backend_hq'} | null;
};

export type ContinuousSpeechState = {
  operation_id:string; done:boolean; error:string; played?:boolean;
  chunks:{id:string;url_path:string;sequence_index:number;duration_seconds:number;text?:string}[];
};

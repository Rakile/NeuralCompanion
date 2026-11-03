"""Implementation-grounded presentation help for speech, avatars and senses."""
from __future__ import annotations

import re

HELP: dict[str, str] = {
    "tts_seed": "Seed for Chatterbox speech. 0 uses the randomized default; a positive integer helps compare generation settings with the same starting seed.",
    "tts_temperature": "Sampling temperature for Chatterbox. Lower values favor predictable delivery; higher values permit more variation and can reduce stability.",
    "tts_top_p": "Cumulative-probability limit for English Turbo audio-token sampling (0–1). Lower values narrow the candidate pool; 0 retains the most likely token and 1 disables this filter.",
    "tts_top_k": "Maximum likely English Turbo audio-token candidates considered during sampling. Lower positive values constrain variation. Set 0 to disable the Top K filter.",
    "tts_repeat_penalty": "Penalty for repeated audio tokens. 1 is neutral; larger values discourage repetition, while extreme values can distort speech. The normal runtime substitutes 1.2 when this is 0.",
    "tts_min_p": "Legacy saved setting only. English Chatterbox Turbo ignores Min P, so NC does not expose or forward it. Multilingual has its own separate Min P setting.",
    "tts_use_cloned_voice": "Condition Chatterbox on the active voice-reference audio when available. Disable to use its built-in voice conditioning instead.",
    "tts_normalize_loudness": "Normalize the reference recording to -27 LUFS when English Turbo prepares voice conditioning. This does not normalize generated speech or change desktop playback volume.",
    "tts_apply_watermark": "Enable Chatterbox's audio watermark on generated speech. This changes generated audio rather than adding visible text.",
    "tts_prewarm_on_start": "Run a short Chatterbox warm-up at runtime startup to reduce first-sentence delay. This moves model and voice preparation earlier, using startup time and model memory.",
    "chatterbox_multilingual_language": "Pronunciation language supplied to multilingual Chatterbox. Choose the language of the text; this does not translate the reply.",
    "chatterbox_multilingual_seed": "Seed setting saved for multilingual speech. Seed handling depends on the runtime; identical audio is not guaranteed.",
    "chatterbox_multilingual_temperature": "Sampling temperature for multilingual speech. Lower values constrain variation; higher values can give more varied delivery but less stable pronunciation.",
    "chatterbox_multilingual_top_p": "Cumulative-probability cutoff for multilingual audio sampling (0–1). Lower values narrow the candidate pool. 0 is passed through to the provider rather than replaced with a default.",
    "chatterbox_multilingual_exaggeration": "Expressiveness of multilingual speech. Higher values emphasize delivery and may reduce stability; 0.5 is the provider default.",
    "chatterbox_multilingual_cfg_weight": "Classifier-free guidance strength for multilingual speech. 0 disables guidance and can help when the reference voice and generated text use different languages; 0.5 is the default.",
    "chatterbox_multilingual_min_p": "Minimum token probability relative to the most likely token (0–1). 0 disables this filter; larger values remove less likely candidates. The default is 0.05.",
    "chatterbox_multilingual_repeat_penalty": "Penalty for repeated multilingual audio tokens. 1 is neutral; larger values discourage repetition. 0 currently uses the provider default penalty.",
    "chatterbox_multilingual_use_cloned_voice": "Use the active voice-reference audio for multilingual cloning when available. Disable to use built-in voice conditioning.",
    "chatterbox_multilingual_apply_watermark": "Include the multilingual Chatterbox provider's audio watermark in generated speech.",
    "chatterbox_multilingual_prewarm_on_start": "Prepare multilingual speech at runtime startup to reduce first-sentence waiting. Startup does more work and holds model memory earlier.",
    "pocket_tts_python": "Optional python.exe for the separate PocketTTS worker. Leave blank for the bundled interpreter; an override must contain the required PocketTTS environment.",
    "clipboard_source_auto_attach_next_user_turn": "Attach the newest copied image to your next submitted user message. The image is delivered to the configured vision path with that message.",
    "clipboard_source_auto_send_immediately": "Submit newly copied images immediately instead of waiting for a message. Copying an image can therefore trigger a model response and provider usage.",
    "clipboard_source_hidden_loop_enabled": "Make copied images available to the hidden sensory loop for background awareness. Clipboard image content can be included in configured sensory-model requests when that loop runs.",
    "mock_heart_rate_bpm": "Publish a simulated heart-rate signal in beats per minute (0–200) for testing behavior. This manually supplied mock value is not a reading from a physical sensor.",
    "mock_heart_rate_window_visible": "Show or hide the floating monitor for the mock signal. Its value comes from the manual BPM setting.",
    "screen_source_capture_mode": "Capture the whole selected screen, a selected rectangle, or a selected square. Use the region/square selection action to define a cropped area.",
    "screen_source_capture_screen_index": "Monitor used by screen capture. All screens (stored as -1) captures the combined desktop; a numbered choice targets that monitor.",
    "screen_source_max_width": "Maximum screen-image width in pixels. Larger images retain small text but increase image payload and vision processing requirements.",
    "screen_source_max_height": "Maximum screen-image height in pixels. Larger images preserve detail but increase image payload and vision processing requirements.",
    "screen_source_jpeg_quality": "JPEG quality for screen images (40–95%). Higher quality preserves fine text with a larger payload; lower quality reduces payload with more compression artifacts.",
    "screen_source_auto_attach_next_user_turn": "Capture and attach the selected screen area on each subsequent user turn while enabled. Screen content is included in the configured vision request.",
    "webcam_source_device_id": "Camera used by the webcam sensory source. Select an available camera before capturing; a saved entry may remain listed while its camera is disconnected.",
    "scenic_pack_id": "Discovered prepared Scenic avatar pack used by the Scenic renderer. Create or install a pack before selecting it here.",
    "musetalk_avatar_pack_id": "Prepared MuseTalk pack used for avatar playback. Packs contain a default avatar and may map reply emotions to additional prepared variants.",
    "musetalk_fps": "Requested MuseTalk frame rate in frames per second. Higher rates require more frame generation and processing; coordinate with the source avatar and GPU capacity.",
    "musetalk_vram_mode": "GPU-memory preset: Quality, Balanced, Low VRAM or Very Low VRAM. More restrictive modes reduce memory demand through runtime processing settings, trading throughput for memory headroom.",
    "musetalk_loop_fade_ms": "Milliseconds used to smooth avatar loop transitions. 0 disables the loop fade; larger values blend over a longer transition.",
    "ua_companion_orb_send_musetalk_face_mask": "Send MuseTalk face-mask frames to Companion Orb and suppress the normal MuseTalk preview while enabled. Use this with the Orb integration; turning it off restores normal preview routing.",
    "musetalk_target_pack_combo": "Destination pack for prepared avatars. Standalone Avatars uses the compatibility workspace outside a named pack; named packs group avatars and emotion mappings.",
    "musetalk_avatar_combo": "Prepared avatar to inspect or edit with the preparation tools. Selecting an entry loads that avatar's preparation settings.",
    "musetalk_source_edit": "Source image, video, or frame-folder path for preprocessing. Choose media with a visible face; preprocessing derives avatar assets from it.",
    "musetalk_avatar_id_edit": "Identifier for the prepared avatar folder inside the destination. Use a distinct ID to prepare a separate avatar rather than targeting an existing one.",
    "musetalk_recreate_checkbox": "Allow preprocessing to recreate an existing avatar destination. This can replace prepared assets; check the destination and confirmation before preprocessing.",
    "musetalk_create_frame_cache_checkbox": "Build a frame cache during preparation for faster later loading. This uses additional disk space and preparation time.",
    "musetalk_emotion_tags_edit": "Comma-separated reply-emotion tags that select this avatar in its pack. Save tag mapping and mask metadata to persist changes.",
    "musetalk_preprocess_tab.unnamed_qlabel_qlabel": "Read-only summary of prepared emotion variants and their enable states. Use emotion controls to change which optional variants are available.",
    "musetalk_bbox_shift_spin": "Pixel adjustment to the detected face bounding box used for mouth preparation. Preview the mask to check alignment before preprocessing.",
    "musetalk_parsing_mode_combo": "Jaw uses the recommended jaw-aware mask shaping; Raw uses the parsed mask directly. Inspect a preview before preparing the avatar.",
    "musetalk_extra_margin_spin": "Additional margin used to shape the mouth mask. Increasing it covers more surrounding face area; inspect the overlay for visible blending edges.",
    "musetalk_left_cheek_width_spin": "Left-cheek boundary offset in pixels on the 512-pixel parsing mask. Changes the jaw-mask geometry; inspect the preview before preprocessing.",
    "musetalk_right_cheek_width_spin": "Right-cheek boundary offset in pixels on the 512-pixel parsing mask. Changes the jaw-mask geometry; inspect both edges in the preview.",
    "musetalk_debug_show_mask_overlay_quick_checkbox": "Show the debug mask overlay to inspect the area used for blending. Shares its setting with Show mask overlay in Debug.",
    "musetalk_mask_range_start_spin": "First source-frame index in the mask range being edited. Frame 0 is the first frame; start must fit the source and be at or before the end.",
    "musetalk_mask_range_end_spin": "Last source-frame index in the mask range being edited. Frames start at 0; bounds are checked against the known source length.",
    "musetalk_mask_range_passthrough_checkbox": "Use the unmodified source face for this range instead of the generated mouth mask. Add or update the range to store this exception.",
    "musetalk_mask_ranges_table": "Select a frame-specific range to load, update or remove. Matching ranges override the global mask profile; -1 means no row selected.",
    "musetalk_mask_overrides_table": "Select an exact-frame edited-mask override to inspect or remove. These store manual edits for individual source frames; -1 means no selection.",
    "musetalk_debug_frame_index_spin": "Source frame used for mask debugging. Frame 0 is the first; preview it to inspect crop and mask before preprocessing.",
    "musetalk_debug_show_mask_overlay_checkbox": "Display the mouth-mask overlay on the debug preview. Changes the inspection view and shares the quick mask-overlay setting.",
    "musetalk_debug_brush_size_spin": "Brush radius in source-image pixels for editing the debug mask. Larger values cover more area per stroke; save an exact-frame override to retain an edit.",
    "musetalk_debug_brush_feather_spin": "Feather width in source-image pixels around brush strokes. 0 gives a hard edge; larger values soften transitions toward the brush radius.",
    "musetalk_debug_brush_transparency_spin": "Transparency percentage for mask-brush edits. 0 gives full strength; higher values weaken each stroke. Internally capped at 99, so 100 still applies a small edit.",
    "musetalk_test_audio_edit": "Audio used for the MuseTalk audio-frame test. Tests mouth rendering against sample audio without changing the conversation's voice reference.",
    "musetalk_native_preview_details": "Read-only diagnostic details from the latest preprocessing preview for inspecting crop and mask results.",
}

# Shared semantics, separate provider settings.
for _prefix in ("pocket_tts_", "pocket_tts_multilingual_"):
    HELP.update({_prefix + key: value for key, value in {
        "builtin_voice": "Built-in PocketTTS voice used when no cloned reference is applied. Auto selects the language default; a named voice chooses that built-in reference.",
        "use_cloned_voice": "Use active voice-reference audio when available. Disable to use the selected built-in voice instead; this does not create or edit the reference file.",
        "prewarm_on_start": "Prepare this PocketTTS backend at runtime startup to reduce first-sentence delay. Startup does more work and starts the separate speech worker earlier.",
        "temperature": "Sampling temperature for PocketTTS. Lower values favor consistent delivery; higher values permit more variation and can reduce stability.",
        "lsd_decode_steps": "Latent speech decoding steps. More steps add decoding work and may increase synthesis delay; 1 is the lightweight default.",
        "eos_threshold": "Model threshold for detecting end of speech, not volume or time. Change cautiously if speech stops too early or continues too long; default is -4.0. The provider currently substitutes -4.0 when set to 0.",
        "frames_after_eos": "Extra audio frames after end-of-speech detection. 0 leaves this to the model default; positive values request an explicit trailing-frame count.",
    }.items()})
HELP["pocket_tts_multilingual_language"] = "Language for multilingual PocketTTS: English, French, German, Spanish, Portuguese or Italian. Auto voice follows this language; this does not translate reply text."

HELP.update({
    "ditto_pack_id": "Select a prepared package or Standalone prepared avatar for a compatibility path. Animation/generation tuning is saved per selected package and shared by its emotion avatars.",
    "ditto_variant_id": "Prepared source avatar used when Source avatar selection is Fixed. Reply-emotion selection can choose a mapped variant instead.",
    "ditto_avatar_selection": "Fixed always uses the chosen source avatar. From reply emotion selects a mapped prepared variant, independently of generated expression selection.",
    "ditto_emotion_selection": "Manual uses the selected native expression. From reply emotion maps each speech chunk's emotion to a generated expression, independently of its prepared source avatar.",
    "ditto_emotion": "Native expression used when generated expression selection is Manual. Changes facial animation rather than reply text or source-avatar mapping.",
    "ditto_expression": "Facial-expression motion multiplier (0–2). 1 is normal strength; 0 suppresses it. New render jobs use this setting; queued frames retain their captured settings.",
    "ditto_pitch_strength": "Multiplier for up/down head rotation (0–2). 1 keeps normal pitch motion; 0 suppresses this motion component.",
    "ditto_yaw_strength": "Multiplier for left/right head rotation (0–2). 1 keeps normal yaw motion; 0 suppresses this motion component.",
    "ditto_roll_strength": "Multiplier for sideways head tilt (0–2). 1 keeps normal roll motion; 0 suppresses this motion component.",
    "ditto_translation_strength": "Multiplier for head-position movement (0–2). 1 keeps normal translation; 0 suppresses this motion component.",
    "ditto_motion": "Use automatic motion handling, expression-only animation, or head-and-expression animation. Expression only limits head movement while retaining facial animation.",
    "ditto_relative": "Retain the source expression as the relative-motion baseline. Disable when comparing sustained generated emotional expressions against that baseline.",
    "ditto_conditioning": "Motion-conditioning reference: the prepared source face or the checkpoint reference. Can change pose/expression behavior without preparing the source again.",
    "ditto_eyes": "Automatic, explicitly enabled, or disabled eye animation. Checkpoint blink controls require active eye animation.",
    "ditto_blink_style": "Use the checkpoint blink sequence or generated eye motion. Open-eye spacing applies only to the checkpoint sequence.",
    "ditto_pitch_offset": "Static up/down head-angle offset in degrees, added alongside pitch motion. 0 adds no pitch offset.",
    "ditto_yaw_offset": "Static left/right head-angle offset in degrees, added alongside yaw motion. 0 adds no yaw offset.",
    "ditto_roll_offset": "Static sideways head-tilt offset in degrees, added alongside roll motion. 0 adds no roll offset.",
    "ditto_blink_open": "Open-eye frames between checkpoint blinks at 25 FPS. 0 chooses random spacing; -1 disables the blink sequence. Requires eye animation and Checkpoint blink sequence.",
    "ditto_eye_first_frame": "Condition eye opening and gaze on the first source frame rather than following source-video eye changes. Blink controls still apply.",
    "ditto_steps": "Sampling iterations per render job. More steps add generation work and can delay ready frames. Changes affect subsequent speech chunks.",
    "ditto_smoothing": "Smoothing window for generated motion. Larger windows reduce rapid changes but can soften expression detail; 1 uses the smallest window.",
    "ditto_source_smoothing": "Smoothing window for source motion. Larger windows reduce jitter but can soften quick changes; 1 uses the smallest window.",
    "ditto_seed": "Random seed. Blank chooses randomly; enter an integer from 0 to 4294967295 for comparable runs. 0 is a valid fixed seed here.",
    "ditto_fade_in": "Fade-in frames per rendered speech chunk at 25 FPS. 0 disables it; 25 frames is one second. Fade reference/components determine what is blended.",
    "ditto_fade_out": "Fade-out frames per rendered speech chunk at 25 FPS. 0 disables it; 25 frames is one second. Applies per chunk rather than once per conversation.",
    "ditto_fade_target": "Fade reference: the initial generated pose or source pose. Relevant when fade-in or fade-out is nonzero.",
    "ditto_fade_keys": "Blend expression alone or expression plus head motion during chunk fades. Requires nonzero fade-in or fade-out.",
    "ditto_stitching": "Apply final alignment correction between animated face and source. Usually keep enabled to reduce visible mismatches at the boundary.",
    "ditto_repo_path": "Ditto installation folder containing required runtime assets. The separate worker uses this installation for preparation and rendering.",
    "ditto_python_path": "Python executable for the Ditto worker. Blank uses .venv/Scripts/python.exe inside the installation; an override needs Ditto's dependencies.",
    "ditto_avatar_path": "Folder containing a prepared Ditto avatar for standalone use. Selecting a managed package fills its corresponding prepared-avatar path automatically.",
    "ditto_creator_pack": "Existing package to edit or add prepared variants to. Selects the creator destination and its emotion mappings.",
    "ditto_package_name": "Display name for the package being created or edited. Save package and emotion mapping to persist creator changes.",
    "ditto_creator_variant": "Avatar entry in the selected package to edit, prepare or replace. Labels indicate whether the source has been prepared.",
    "ditto_variant_name": "Display name for this avatar entry. Separate entries let different source images/videos represent different reply emotions.",
    "ditto_variant_tags": "Comma-separated reply-emotion tags selecting this source avatar, such as happy, joyful. Each tag can map to only one avatar in a package.",
    "ditto_variant_default": "Use this package avatar as the default fallback when reply-emotion selection finds no matching variant.",
    "ditto_source_path": "Still image, video, or numerically ordered PNG-frame folder to prepare. Source preparation is separate from runtime expression tuning.",
    "ditto_loop_mode": "Pingpong plays a forward-only source forwards and backwards. Forward loops it as supplied; choose Forward when input already contains its reverse half.",
    "ditto_source_frames": "Maximum frames to prepare. -1 uses every available frame; positive values limit preparation/storage. 0 is invalid. A still image produces one frame.",
    "ditto_import_path": "Existing prepared-avatar folder to copy into the selected package entry instead of preparing original media again.",
    "ditto_preview_muted": "Mute the creator preview's audio while retaining its animation. Affects preview playback.",
    "ditto_test_emotion": "Reply-emotion text for testing the package. Preview follows runtime source-avatar and generated-expression selection modes.",
    "ditto_test_audio": "WAV audio used for a local speaking preview. A short sample helps compare animation settings without a full conversation.",
    "ditto_output_path": "Standalone preparation destination outside packages. Existing prepared avatars are not overwritten; use a new destination for separate preparation.",
    "ditto_max_size": "Maximum source dimension in pixels during preparation. Larger sources retain detail but increase preprocessing memory and work.",
    "ditto_crop_scale": "Face-crop scale during preparation. Larger values include more surrounding area; inspect the crop preview before preparing.",
    "ditto_crop_x": "Horizontal offset in Ditto's normalized crop coordinates. 0 retains the detected horizontal center; check positioning with the crop preview.",
    "ditto_crop_y": "Vertical offset in normalized crop coordinates. 0 retains the detected vertical center; preview forehead, mouth and chin coverage.",
    "ditto_crop_rotate": "Align the prepared crop with detected face rotation. Preview to inspect framing for a tilted source.",
    "elevenlabs_tts_tab.api_key": "ElevenLabs credential for cloud speech and voice discovery. Requests use your provider account and speech quota; keep the key private.",
    "elevenlabs_tts_tab.base_url": "ElevenLabs API base URL for voice discovery and speech. Change only for a compatible endpoint; speech text and credentials are sent there.",
    "elevenlabs_tts_tab.model": "Speech model: Flash v2.5 favors fast starts, Multilingual v2 stable long-form speech, and v3 expressive delivery. Supported controls and latency depend on the model.",
    "elevenlabs_tts_tab.voice_id": "Cloud voice ID used for generated speech. Refresh voices for choices available to your account; this supplies the speaker identity.",
    "elevenlabs_tts_tab.language_code": "Optional ISO 639-1 language code, such as en. Blank omits the override and leaves language handling to ElevenLabs.",
    "elevenlabs_tts_tab.stability": "Provider stability on a 0–100 scale, sent as 0–1. Lower values allow more expressive variation; higher values favor consistency. Support depends on the model.",
    "elevenlabs_tts_tab.similarity_boost": "Voice-identity similarity on a 0–100 scale, sent as 0–1. Higher values request a closer match to the selected speaker.",
    "elevenlabs_tts_tab.style": "Style exaggeration on a 0–100 scale, sent as 0–1. 0 requests no exaggeration; higher values request stronger style. Support depends on the model.",
    "elevenlabs_tts_tab.speed": "Speech speed shown on a 70–120 scale: 100 is normal (1.0×), 70 is 0.7× and 120 is 1.2×. Lower values request slower delivery.",
    "elevenlabs_tts_tab.use_speaker_boost": "Ask ElevenLabs to boost similarity to the selected speaker. Provider support depends on the selected model.",
    "gemini_tts_preview_tab.api_key": "Gemini credential for cloud speech. Requests use your provider account and may incur usage charges; keep the key private.",
    "gemini_tts_preview_tab.base_url": "Gemini endpoint for speech generation. Change only for a compatible endpoint; speech text and credentials are sent there.",
    "gemini_tts_preview_tab.model": "Gemini preview speech model for synthesis. Determines availability, latency and usage cost; separate from the conversation chat model.",
    "gemini_tts_preview_tab.voice_name": "Named Gemini prebuilt voice. Labels describe its vocal character; the style prompt can further guide delivery.",
    "gemini_tts_preview_tab.language_code": "Optional BCP-47 speech-language code, such as en-US. Blank omits languageCode and lets Gemini handle text language.",
    "gemini_tts_preview_tab.style_prompt": "Delivery instructions included with Gemini speech text, such as a calm or energetic reading. Guides voice performance rather than the conversation system prompt.",
    "rag_context_tab.enabled": "Allow ready Document Memory notes into chat context. Select and prepare a knowledge package first; enabling recall can activate pending local indexing.",
    "rag_context_files": "Registered Document Memory files. Select one for file actions; removing registration does not delete your original source document.",
    "rag_context_tab.base_url": "Local embedding endpoint for indexing documents and embedding queries. Only loopback addresses are accepted; the embedding setup must match the stored index.",
    "rag_context_tab.model": "Semantic-search embedding model, separate from chat. Changing it requires re-indexing so stored document vectors match query vectors.",
    "rag_context_tab.prefix_scheme": "Preprocessing expected by the embedding model: plain/BGE-M3, Nomic, Qwen3 query instruction, or custom prefixes. Match the model; changing preprocessing requires a compatible rebuilt index.",
    "rag_context_tab.context_tokens": "Embedding-model context size in tokens, used to budget document chunks. Match the local embedding model; separate from chat-model context size.",
    "rag_context_tab.semantic_min_score": "Minimum semantic similarity required for a match. Higher values filter loosely related notes but may produce no results.",
    "rag_context_tab.deadline_ms": "Retrieval budget in milliseconds. Smaller budgets limit chat waiting but can cause fallback or finish without semantic results.",
    "rag_context_tab.top_k": "Maximum document notes per query. More notes improve coverage but use more chat-input context and tokens.",
    "rag_context_tab.min_score": "Minimum overlapping query keywords for lexical retrieval. Higher values filter weak matches; at least one overlap is always required, including when this setting is 0.",
    "rag_context_tab.max_context_chars": "Character limit for retrieved document text added to chat. Larger limits retain more evidence but use more of the model input budget.",
    "rag_context_test_query": "Test query against the active ready index. Run the test to inspect matches without submitting a conversation turn.",
    "rag_context_result_preview": "Read-only retrieval-test results, including context and available timing, source and fallback diagnostics.",
})

_SUPERVISOR_HELP = {
    "supervisor_enabled": "Enable this sensory supervisor's reactions. Its source and sensory processing must provide observations before rules can match.",
    "supervisor_persona": "Active reaction profile and its speaking style/rules. Choosing another profile changes the rule set used for reactions.",
    "supervisor_style": "Speaking-style guidance for reactions from this profile. Shapes delivery while each individual rule supplies its trigger and action.",
    "supervisor_behavior": "Rule to inspect/edit in the active profile. Selecting a rule does not enable it; use its Enabled switch.",
    "supervisor_behavior_enabled": "Allow this rule to participate in reactions. The supervisor/source must also be active; disabling preserves the rule.",
    "supervisor_trigger": "Condition to recognize in incoming observations. Describe the signal or situation that should trigger this rule's Action.",
    "supervisor_action": "Response or behavior requested when the rule matches. Strictness controls how freely the model interprets this instruction.",
    "supervisor_strictness": "Interpret freely allows adaptation, Follow closely stays nearer the action's intent/phrasing, and Say almost exactly requests near-verbatim delivery.",
    "supervisor_emotion": "Emotion override for this reaction. Auto uses normal response emotion selection; a named emotion requests that reaction emotion.",
    "supervisor_repeat_mode": "When a matching rule may react again: One-off limits repeats, Every Nth match counts matching observations, and Meaningful change only requires a meaningful change in the observation.",
    "supervisor_repeat_interval": "Matching observations per reaction in Every Nth match mode (1–999). Counts matches rather than elapsed seconds; relevant only to that mode.",
    "supervisor_prompt_template": "Advanced review/reaction prompt template for this supervisor. Preserve required placeholders and inspect the rendered preview after editing.",
    "supervisor_preview": "Read-only rendered review prompt for the selected profile/rules. Check how the template, speaking style and rule instructions combine.",
}
for _surface, _source in (
    ("screen_supervisor_tab", "screen observations"),
    ("webcam_supervisor_tab", "webcam observations"),
    ("clipboard_supervisor_tab", "clipboard-image observations"),
    ("heart_rate_behavior_tab", "heart-rate signal observations"),
):
    for _key, _copy in _SUPERVISOR_HELP.items():
        HELP[f"{_surface}.{_key}"] = _copy
    HELP[f"{_surface}.supervisor_trigger"] = (
        f"Condition to match against {_source} for this rule. "
        "Describe the situation that should trigger its Action; rule and supervisor must both be enabled."
    )

HELP.update({
    "web_intelligence_enabled": "Global web-search switch. Off immediately blocks search-intent calls and all searches, including chat, LocalRoom, /web and tests. Server settings and running server processes are retained.",
    "web_intelligence_mode": "Normal-chat search policy: Off blocks chat searches including /web; Automatic searches when current information is needed; Every turn searches each normal turn. Global web search must also be on.",
    "web_intelligence_use_llm_context_intent": "In Automatic mode, ask the selected chat model whether to search and form a query. Adds a model call per incoming turn when a backend is available. Off uses keyword matching; /web and Every turn bypass this check.",
    "web_intelligence_max_results": "Maximum results per search (1–10). More results improve potential coverage but add search work and evidence volume.",
    "web_intelligence_fetch_pages": "Maximum pages to fetch for full-text evidence (0–3). 0 skips fetching; larger values add network work and latency. Read result pages must also be enabled.",
    "web_intelligence_include_page_text": "Fetch result-page text for evidence beyond snippets. Pages to read limits fetching; this adds network work and may delay replies.",
    "web_intelligence_include_images": "Allow image-search results when requested. This permits search results rather than enabling image generation.",
    "web_intelligence_include_videos": "Allow video-search results when requested. Supplies links/results rather than automatically playing or analyzing video.",
    "web_intelligence_evidence_prefix": "Instructions prepended to chat web evidence, limited to 8,000 characters. Query, backend and sources are added automatically. Edits save when you leave the field.",
    "web_intelligence_searxng_status": "Read-only primary SearXNG MCP endpoint status. This backend uses the configured local SearXNG instance.",
    "web_intelligence_duck_status": "Read-only status of the no-key DuckDuckGo MCP fallback used when SearXNG is unavailable.",
    "web_intelligence_install_status": "Read-only installation progress/results. Search-server packages live in addon-local storage, separate from NeuralCompanion's Python environment.",
    "web_intelligence_test_query": "Query for a one-result backend diagnostic without a conversation turn. Global web search must be enabled to run the test.",
    "web_intelligence_action_result": "Read-only result of the latest server action or search test, including diagnostic/failure details.",
    "spotify_sense_enabled": "Enable Spotify Sense. A connected account is also required to read metadata or control playback.",
    "spotify_sense_client_id": "Spotify application's client ID for account authorization. Register a redirect URI matching this addon's callback before connecting.",
    "spotify_sense_redirect_uri": "OAuth callback URI for Spotify connection. Must match the URI registered for your application, including scheme, host, port and path.",
    "spotify_sense_allow_llm_control": "Allow model-initiated playback changes. Direct user commands can still run when off if Spotify Sense is enabled/connected. Confirmation and queue/playlist permissions still apply.",
    "spotify_sense_require_confirmation": "Block autonomous/tool-triggered playback changes unless confirmed. Direct user commands count as confirmed requests.",
    "spotify_sense_allow_queue_changes": "Permit NC tools to add tracks to the queue. Changes upcoming playback and still depends on connection/control permissions.",
    "spotify_sense_allow_playlist_changes": "Permit tools to start playlists or playlist contexts, potentially replacing current playback. This does not grant unrestricted editing of playlist contents.",
    "spotify_sense_default_device": "Device for playback commands. Empty Active device / default uses Spotify's active/default device; refresh after available players change.",
    "spotify_sense_default_volume": "Fallback Spotify volume percentage (0–100) for tests and relative-volume calculations when current volume is unavailable. Not a continuous volume lock.",
    "spotify_sense_comment_on_song_changes": "Allow optional short track-change acknowledgements. Song-change detection and cooldowns still determine whether a comment may occur.",
    "spotify_sense_song_change_monitor_enabled": "Poll Spotify for track changes to update context and optional acknowledgements. Requires connection and adds periodic Spotify requests.",
    "spotify_sense_music_awareness_enabled": "Add compact track metadata to normal chat. Uses track information rather than recording/analyzing raw music audio.",
    "spotify_sense_music_awareness_relevance_only": "Guide the model to mention music only when useful to the current reply or task. Music awareness must supply context.",
    "spotify_sense_include_paused_track_context": "Keep paused-track metadata available. Disable if music awareness should ignore Spotify while paused.",
    "spotify_sense_album_art_thumbnail_enabled": "Show available album/single artwork as a thumbnail in Spotify Sense.",
    "spotify_sense_music_response_mode": "How track metadata shapes replies: Off, restrained Subtle use, Companion, DJ / Music Critic, or Story soundtrack guidance. Story background music selects Story soundtrack mode.",
    "spotify_sense_proactive_comment_cooldown_seconds": "Minimum seconds between ordinary song-change acknowledgement opportunities (15–3600). Longer intervals reduce proactive chatter.",
    "spotify_sense_hidden_response_cooldown_seconds": "Minimum seconds between hidden Spotify sensory responses (15–7200). Increase to make background reactions less frequent.",
    "spotify_sense_user_music_change_cooldown_seconds": "Seconds to wait after a user/external track change before NC may change playback (0–3600). 0 removes this interval.",
    "spotify_sense_duck_while_speaking": "Temporarily lower Spotify during NC speech. Active device must support volume control; Duck volume and fade durations set target/timing.",
    "spotify_sense_restore_volume_after_speech": "Restore saved Spotify volume after speech. Relevant when Lower music while NC speaks is enabled.",
    "spotify_sense_duck_volume_percent": "Target Spotify volume percentage during speech (0–100), subject to device support. This is a target rather than a percentage subtracted from current volume.",
    "spotify_sense_duck_fade_down_ms": "Milliseconds to lower music when speech starts (0–5000). 0 requests an immediate change.",
    "spotify_sense_duck_fade_up_ms": "Milliseconds to restore music after speech (0–5000). 0 requests immediate restoration; Restore volume after speech must be on.",
    "spotify_sense_story_mode_background_music": "Allow story hooks to choose music. Autonomous music must also permit the event; enabling selects Story soundtrack response mode.",
    "spotify_sense_story_music_prefer_ambient": "Favor ambient playlists unless a story beat calls for other music. Requires background music and permitted autonomy.",
    "spotify_sense_autonomous_music": "Off blocks story autonomy. Routines only permits story, scene and coding starts; Full also permits other supported story events. Other control permissions still apply.",
    "spotify_sense_story_music_target_volume": "Target Spotify volume percentage after story-music transitions (0–100), when background music/autonomy permit changes.",
    "spotify_sense_story_music_transition_floor_volume": "Temporary low volume percentage during story-music switching (0–100), before fading toward the target volume.",
    "spotify_sense_story_music_fade_down_ms": "Milliseconds to fade down before a story-music switch (0–8000). 0 skips the timed fade.",
    "spotify_sense_story_music_fade_up_ms": "Milliseconds to fade up after a story-music switch (0–8000). 0 requests the target without a timed fade.",
    "spotify_sense_coding_query": "Spotify search phrase used by coding/focus hooks to find background music, such as relaxing focus music.",
    "spotify_sense_hidden_preset_combo": "Hidden sensory style preset to load into reaction guidance. Presets shape commentary; playback permissions are separate.",
    "spotify_sense_hidden_commentary_style": "Hidden sensory commentary instructions, such as tone, length and questions. Save Style persists edited guidance.",
    "spotify_sense_music_conversation_prompt": "Guidance for normal music-aware replies, separate from hidden commentary. Save Conversation Prompt persists edits.",
    "spotify_sense_source_guidance": "Guidance for interpreting Spotify source information in sensory context. Save Guidance persists edits; recommended guidance can be restored.",
    "spotify_sense_debug_logging_enabled": "Write route, playback and volume diagnostics to the local addon log. Enable for investigation; logs can include playback/request details.",
    "spotify_sense_intent_test": "Example command for Preview Intent to inspect routing before issuing a playback command.",
})
for _slot in range(1, 7):
    HELP[f"spotify_sense_hidden_quick_{_slot}"] = (
        f"Load the hidden sensory style assigned to quick slot {_slot}. "
        "An empty slot has no preset to apply; use Add Quick to populate the list."
    )

HELP.update({
    "audio_story_tts_startup_buffer_spin": "Seconds of TTS narration prepared before playback starts. A larger buffer delays startup but provides more ready audio to prevent early gaps.",
    "audio_story_tts_render_ahead_spin": "Seconds of TTS narration kept rendered ahead of playback. Larger buffers reduce speech gaps but synthesize more in advance and retain more audio.",
    "audio_story_position_slider": "Seek within the audio timeline. Preview changes to the image window matching the selected playback time.",
    "audio_story_stream_enabled_checkbox": "Serve current story visuals as a LAN web page for browsers/casting. Exposes the stream through the configured local HTTP port.",
    "audio_story_stream_port_spin": "HTTP port for the visual stream page. Choose an unused port; LAN devices connect to the host through it when sharing is enabled.",
    "audio_story_cast_device_combo": "Device to receive the visual stream. Discover devices and enable the LAN stream before starting casting.",
    "audio_story_cast_prompt_checkbox": "Show the current image prompt on the cast screen alongside the visual. Disable to hide generation instructions from viewers.",
    "audio_story_pin_location_button": "Pin the detected location as a continuity anchor for later prompts. Turn off when future scenes should stop retaining that location pin.",
    "audio_story_force_fresh_button": "Treat this image window as a fresh scene, overriding automatic detection when it continues the previous scene too long.",
    "audio_story_force_continuation_button": "Treat this image window as continuation of the previous scene when automatic detection splits too aggressively.",
    "audio_story_scene_anchor_edit": "Positive visual-focus override for this scene. Apply the override to refresh matching prompts/images; pin to reuse across future scenes.",
    "audio_story_scene_negative_prompt_edit": "Things this scene's image should avoid, added to its Avoid block. Apply the override to refresh matching prompts/images.",
    "audio_story_scene_anchor_pin_button": "Reuse this positive anchor for every future scene until unpinned, rather than only the selected scene.",
    "audio_story_negative_prompt_anchor_button": "Reuse this avoid list as a persistent negative anchor for future scenes until unpinned.",
    "audio_story_transcript_edit": "Read-only transcript for reviewing words aligned to the audio-story session. Transcription and novel actions produce source text.",
    "audio_story_style_live_checkbox": "Apply style edits during playback, potentially regenerating visuals and using image-provider calls. Off saves edits without regenerating playback visuals.",
    "audio_story_prompt_safety_cap_spin": "Maximum combined image-prompt characters. Lower limits reduce payload; higher limits preserve more scene and continuity detail.",
    "audio_story_xai_aspect_ratio_combo": "Audio Story image aspect ratio for xAI / Grok. Other providers ignore xAI-specific settings; Auto delegates ratio selection.",
    "audio_story_xai_resolution_combo": "xAI / Grok image resolution: 1k or 2k. Higher resolution can take longer or cost more; other providers ignore it.",
    "audio_story_xai_response_format_combo": "xAI response format. b64_json supplies image data for stable local playback/casting files; relevant only for xAI / Grok.",
    "audio_story_xai_n_spin": "Images requested per xAI API call. More can increase work/cost, while the timeline still uses one image per scene.",
    "audio_story_image_frequency_slider": "Seconds between images in Fixed Seconds mode, up to 60. Shorter intervals generate more images and can increase provider cost.",
    "audio_story_image_timing_combo": "Fixed Seconds uses the cadence slider. Scene Changes groups transcript chunks by detected boundaries so visuals follow scene structure.",
    "audio_story_continuity_slider": "Continuity strength as a percentage. Higher values retain recurring characters, locations, props and style more strongly but can constrain major scene changes.",
    "audio_story_generate_ahead_slider": "Future images to prepare ahead of playback. Higher values reduce waiting but can use provider calls before those scenes are reached.",
    "audio_story_llm_analysis_checkbox": "Extra model planning pass for scene structure and reusable character/location details. Adds local model work or cloud calls through the planner provider.",
    "audio_story_analysis_mode_combo": "Scene Only plans individual scenes; Story Bible also persists character/location/prop/style memory for consistency. Requires LLM scene planning.",
    "audio_story_analysis_provider_combo": "Provider for transcript/prompt planning: current chat, DeepSeek or local LM Studio. Cloud planning uses provider quota; image generation has its own provider.",
    "audio_story_analysis_model_combo": "Model override only for story planning. Auto uses the planner provider default; a manual ID must be available from that provider.",
    "audio_story_instructor_beats_checkbox": "Use Instructor-backed structured validation for story-beat planning. Requires the planner and available structured-output support; does not validate audio.",
    "audio_story_master_prompt_button": "Temporarily drive the global Visuals master prompt from the story. Off restores the previous Visuals master prompt when possible.",
    "audio_story_master_prompt_mode_combo": "Strength of the story master-prompt anchor: Simple, Medium, Strong or Strongest. Stronger modes preserve more identity guidance but lengthen prompts.",
    "audio_story_novel_outline_tree": "Select a chapter/scene to inspect its plan and prose. Later novel actions target the selected outline item.",
    "audio_story_path_edit": "Current audio source. Import audio and transcribe it to build the timeline/prompts before playback or image generation.",
    "audio_story_source_list": "Imported project audio sources. Select one for source-specific actions; -1 means no source selected.",
    "audio_story_playback_mode_combo": "Imported Audio plays the original without new narration work. TTS Narration synthesizes a track from the transcript using the configured speech backend.",
    "audio_story_cost_profile_combo": "Combined planning/image quality preset. Economy uses fewer images and avoids extra analysis; Detailed/Cinematic use richer prompts and denser timing. Custom keeps manual tuning.",
    "audio_story_settings_preset_combo": "Reusable setup to save/load, excluding imported audio. Loading can rebuild existing transcript windows and prompts.",
    "audio_story_transcribe_seconds_slider": "Transcript analysis window in seconds. Smaller windows give finer scene detail but create more processing chunks.",
    "audio_story_selected_range_checkbox": "Limit transcription to the selected start/end portion instead of full audio. Set valid bounds before transcribing.",
    "audio_story_transcription_start_spin": "Start in source-audio seconds. 0 starts at the beginning; selected-range end must follow the start.",
    "audio_story_transcription_end_spin": "End in source-audio seconds. Use source duration to include the end; selected-range end must follow the start.",
    "audio_story_transcription_console": "Read-only current-session transcription activity/errors. Transcript text appears in the transcript view instead.",
    "audio_story_project_list": "Saved project selected for project actions. Opening restores its sources, chapters and planning state.",
    "audio_story_project_chapter_list": "Chapter selected for chapter-specific project actions and restored story state.",
})

for _style, _suffix in (("Realistic", ""), ("Cartoon", "#2"), ("Retro", "#3"), ("Cyberpunk", "#4")):
    HELP[f"audio_story_mode_runtime.unnamed_qpushbutton_{_style.lower()}"] = (
        f"Include the {_style} visual-style layer in story-image prompts. "
        "Multiple layers can be enabled; adjacent prompt fields supply their actual instructions."
    )
    HELP[f"audio_story_mode_runtime.unnamed_qlineedit_qlineedit{_suffix}"] = (
        f"Image-prompt instructions for the {_style} layer when enabled. "
        "Live style application determines whether current playback visuals regenerate."
    )
HELP.update({
    "audio_story_mode_runtime.unnamed_qlineedit_qlineedit#5": "Name of the novel project being created/managed. Names the project rather than changing its imported source.",
    "audio_story_mode_runtime.unnamed_qlineedit_message_collection": "Path/key locating messages in imported chat-log JSON. Match the source layout so the novel importer can find its message collection.",
    "audio_story_mode_runtime.unnamed_qlineedit_speaker_field": "Chat-log field containing speaker names, used when adapting imported messages into novel source material.",
    "audio_story_mode_runtime.unnamed_qlineedit_text_field": "Chat-log field containing message text. Match the actual field so dialogue content is retained.",
    "audio_story_mode_runtime.unnamed_qlineedit_role_field": "Chat-log field containing roles such as user/assistant, used to interpret participants in imported source material.",
    "audio_story_mode_runtime.unnamed_qlineedit_timestamp_field": "Chat-log timestamp field, used to preserve available message timing in the imported source.",
    "audio_story_mode_runtime.unnamed_qlineedit_thread_field": "Chat-log thread/conversation identifier field. Map when imported messages belong to separate threads.",
    "audio_story_mode_runtime.unnamed_qcombobox_adaptation_style": "How closely writing follows the source: Faithful account, Lightly novelized, or Creative fiction. Greater creative freedom allows more adaptation.",
    "audio_story_mode_runtime.unnamed_qplaintextedit_novel_instructions": "Additional writing instructions such as viewpoint, tone or constraints for source-to-novel adaptation. Separate from image style.",
    "audio_story_mode_runtime.unnamed_qgroupbox_advanced_prompt_additions": "Show the advanced prompt-addition controls in the Novel Workshop. This switch stores whether those advanced controls are visible.",
    "audio_story_mode_runtime.unnamed_qplaintextedit_story_map": "Editable story-map JSON object. Preserve valid JSON and expected fields; invalid JSON is rejected before applying.",
    "audio_story_mode_runtime.unnamed_qplaintextedit_outline": "Editable outline JSON object. Preserve valid JSON and chapter/scene structure because selection and generation use these identifiers.",
    "audio_story_mode_runtime.unnamed_qplaintextedit_scene_plans": "Read-only generated scene plans. Select a chapter/scene in the outline to review its planning material.",
    "audio_story_mode_runtime.unnamed_qplaintextedit_prose": "Read-only generated prose for review. Novel generation actions produce prose for the selected outline material.",
})

_HOTKEYS = {
    "push_to_talk": "Hold this binding to record speech when input mode is Push-to-Talk.",
    "regenerate_response": "Replace the latest assistant reply using current chat context.",
    "retry_user_input": "Remove the latest user turn and accept that input again.",
    "pause_speech": "Pause current speech playback or resume it when paused.",
    "skip_speech": "Stop current speech playback while keeping the accepted reply in chat.",
    "skip_user_reply": "Ask the assistant to continue without a new visible user message.",
    "start_engine": "Start the runtime with current Host settings; this can load models/workers.",
    "stop_engine": "Cleanly stop the active runtime and its current work.",
    "reset_chat_session": "Clear active conversation context and the visible transcript to start fresh.",
    "clear_console": "Clear the visible System Console log without clearing context or stopping runtime.",
    "clear_chat": "Clear the visible transcript while retaining underlying conversation context.",
    "show_musetalk_preview": "Show or bring forward the MuseTalk preview window.",
    "toggle_musetalk_avatar_focus": "Toggle keyboard-focus behavior for the MuseTalk avatar window.",
    "show_visual_reply": "Show or bring forward the latest Visual Reply window.",
}
for _key, _copy in _HOTKEYS.items():
    if _key == "push_to_talk":
        _binding_help = "Global key binding; default Right Ctrl. Blank falls back to that default. "
    elif _key in {"regenerate_response", "retry_user_input", "pause_speech", "skip_speech", "skip_user_reply"}:
        _binding_help = "Global and application shortcut, for example Alt+R. Blank leaves this action unbound. "
    else:
        _binding_help = "Application-window shortcut, for example Ctrl+Shift+L. Blank leaves this action unbound. "
    HELP[f"hotkeys_tab.{_key}"] = _binding_help + _copy


def help_for(control_id: str, surface_id: str = "") -> str:
    """Return known help only; unknown IDs never get label-derived filler."""
    qualified = f"{surface_id}.{control_id}" if surface_id else control_id
    if qualified in HELP:
        return HELP[qualified]
    if control_id in HELP:
        return HELP[control_id]
    # Narrow dynamic families emitted by the native avatar adapters.
    if (not surface_id or surface_id == "ditto_avatar_tab") and re.fullmatch(r"ditto_enable_.+", control_id):
        return "Allow this reply-emotion tag to select its mapped source avatar in the current Ditto package when From reply emotion source selection is active."
    if (not surface_id or surface_id == "ditto_preprocess_tab") and re.fullmatch(r"ditto_map_.+", control_id):
        return "Generated expression mapped to this reply-emotion tag. Automatic uses normal emotion mapping; a named native emotion overrides it independently of source-avatar selection."
    if (not surface_id or surface_id == "musetalk_avatar_tab") and re.fullmatch(r"musetalk_runtime_emotion_[0-9a-f]{16}", control_id):
        return "Allow this pack emotion to select its mapped prepared MuseTalk avatar. Base-avatar emotion mappings remain enabled."
    if (not surface_id or surface_id == "musetalk_preprocess_tab") and re.fullmatch(r"musetalk_pack_emotion_[a-z0-9_]+_[0-9a-f]{10}", control_id):
        return "Enable this optional prepared emotion variant in the selected pack. Base-avatar emotion mappings remain enabled."
    return ""

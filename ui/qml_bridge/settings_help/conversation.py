"""Reviewed help for conversation, identity, rooms, and remote settings."""

from __future__ import annotations

import re

# The schema-owned Discord copy below follows the adapter's explicit setting bindings.

HELP: dict[str, str] = {'discord_dead_air_enabled_checkbox': 'When a completed routed turn selects no next speaker, let the '
                                      'selected Moderator bot step in.',
 'discord_dead_air_cooldown_spin': 'Minimum time between automatic Moderator recovery turns. Use 0 for no '
                                   'cooldown.',
 'discord_dead_air_silence_timeout_spin': 'Quiet-room grace period before automatic Moderator recovery runs. '
                                          'Use 0 only for immediate recovery after a no-route turn.',
 'discord_dead_air_trigger_combo': 'Choose whether dead-air recovery triggers only after bot speech or also '
                                   'after unrouted human speech.',
 'discord_dead_air_action_combo': 'Choose whether the Moderator speaks and hands off, speaks without '
                                  'handoff, or silently calls the next bot.',
 'discord_dead_air_strategy_combo': 'Choose how the recovery system selects the next bot after the Moderator '
                                    'bridge.',
 'discord_dead_air_fallback_target_combo': 'Optional bot id used by the selected-fallback next-speaker '
                                           'strategy.',
 'discord_route_protected_mic_speech_checkbox': 'When a moderator Current speaker is protected, still '
                                                'transcribe and route microphone speech into context without '
                                                'stopping playback or stealing the floor.',
 'discord_runtime_host_edit': 'Local host for the addon runtime endpoint. Keep this on 127.0.0.1, localhost, '
                              'or ::1 so the bridge is not exposed to the network.',
 'discord_runtime_port_spin': 'Local runtime port for the single-bot setup. Multi-bot instances should each '
                              'use a unique port.',
 'discord_session_mode_combo': 'Discord voice uses its own isolated context and does not append to the '
                               'normal Chat tab history.',
 'discord_use_selected_stt_checkbox': 'Use the STT provider currently selected in Neural Companion for '
                                      'Discord speech transcription.',
 'discord_use_selected_chat_checkbox': 'Use the chat provider currently selected in Neural Companion for '
                                       'Discord replies.',
 'discord_use_selected_tts_checkbox': 'Use the TTS provider currently selected in Neural Companion for '
                                      'Discord reply audio.',
 'discord_allow_non_localhost_checkbox': 'Advanced safety override. Leave off for normal use. When off, '
                                         'Start Bridge refuses runtime hosts outside loopback addresses such '
                                         'as 127.0.0.1, localhost, or ::1.',
 'discord_wav_max_age_minutes_spin': 'Deletes old Discord capture and reply WAV files after this many '
                                     'minutes. Use 0 to disable cleanup for debugging.',
 'discord_cleanup_interval_minutes_spin': 'How often the bridge checks for old scratch WAV files while it is '
                                          'running.',
 'discord_use_rag_context_checkbox': "When enabled, Discord turns may receive context from NC's active RAG "
                                     'Context addon if that addon is enabled and has matching chunks. This '
                                     'does not modify the RAG database.',
 'discord_bots_json_edit': 'Optional array of bot override objects. Each enabled bot gets its own Discord '
                           'token/channel settings, persona, localhost runtime port, Node process, and '
                           'isolated chat history.',
 'discord_replace_nc_prompt_checkbox': 'When enabled, the Discord persona prompt replaces the currently '
                                       'selected NC system prompt and NC visual/emotional instruction block '
                                       'for this bridge instance.',
 'discord_persona_prompt_edit': 'Optional Discord-only personality instructions appended to, or replacing, '
                                'the selected NC system prompt.',
 'discord_room_speech_prompt_edit': 'Visible model-facing guidance for how bridge replies should sound. Edit '
                                    'this if you want a scenario-specific room framing.',
 'discord_transcript_safety_prompt_edit': 'Visible model-facing safety rule for treating room transcripts '
                                          'and labels as data rather than instructions.',
 'discord_voice_clone_wav_edit': 'Optional per-bot WAV reference voice. Relative names such as echo.wav are '
                                 "loaded from NC's root voices folder. Leave blank to use the voice selected "
                                 "in NC's global Persona tab.",
 'discord_room_router_enabled_checkbox': 'In multi-bot rooms, make one shared routing decision per Discord '
                                         'utterance before any individual bot generates a reply.',
 'discord_room_router_human_to_bot_checkbox': 'Allows human Discord utterances to be routed to a bot. '
                                              'Disable to ignore human speech at the shared room-router '
                                              'layer.',
 'discord_room_router_bot_to_bot_checkbox': "Allows one NC Discord bot's completed reply to be routed to "
                                            'another NC Discord bot.',
 'discord_room_router_exclude_speaker_checkbox': 'Removes the speaking bot from eligible routing targets '
                                                 'before asking the router. This prevents most accidental '
                                                 'self-routes.',
 'discord_room_router_group_invite_checkbox': 'Allows invitations to multiple named bots, candidate bots, or '
                                              'the bot group to select one best bot instead of returning no '
                                              'route.',
 'discord_room_router_open_room_checkbox': 'Allows open invitations to the room or all participants to '
                                           'select one best non-human bot. Disable if open room talk should '
                                           'stay human-to-human unless a bot is named.',
 'discord_room_router_text_routing_checkbox': 'After a bot finishes generating a reply, route the known '
                                              'reply text directly to the next bot instead of waiting for '
                                              'Discord audio capture and STT.',
 'discord_room_router_prebuffer_checkbox': 'With LLM router, direct bot-text routing, and shared reply-floor '
                                           'coordination enabled, route a completed bot reply as soon as '
                                           'generation finishes so the selected next bot can generate/TTS '
                                           'while the current bot is still speaking. Playback still waits '
                                           'for the floor.',
 'discord_room_router_mode_combo': 'LLM router asks the selected chat provider which bot, if any, should '
                                   'answer. Mention/question is a local fallback based on configured bot '
                                   'call names.',
 'discord_room_router_self_route_combo': 'Controls what happens if the router selects the same bot that '
                                         'spoke. Ignore blocks it, allow permits it, error blocks it with an '
                                         'explicit self-route reason.',
 'discord_room_router_uncertain_target_combo': 'When Answer when uncertain is enabled, choose whether '
                                               'uncertainty falls back to this bot, the first eligible '
                                               'candidate, or nobody.',
 'discord_room_router_competing_policy_combo': 'Policy label for how simultaneous bot replies should be '
                                               'handled. The current Node bridge implements first_ready_wins '
                                               'through the shared reply floor.',
 'discord_room_router_floor_mode_combo': 'Policy label for the shared playback floor. first_ready_wins lets '
                                         'the first bot with playable audio speak while competitors are '
                                         'dropped.',
 'discord_room_router_uncertain_checkbox': 'If the shared router fails or returns an unclear decision, allow '
                                           'the current bot to continue instead of staying silent.',
 'discord_room_router_decision_timeout_spin': 'How long non-owner bot instances wait for the shared room '
                                              'routing decision file.',
 'discord_room_router_text_age_spin': 'Discard text-routed bot turns older than this. Routed text is live '
                                      'handoff state, not saved conversation history.',
 'discord_room_router_decision_tokens_spin': 'Token budget for the small LLM router JSON decision. '
                                             'Reasoning-capable models may need more than the visible JSON '
                                             'because hidden reasoning can consume output tokens.',
 'discord_room_router_route_window_spin': 'Time bucket used to group the same utterance captured by multiple '
                                          'bot instances. Larger values are more tolerant of capture timing '
                                          'differences.',
 'discord_room_router_poll_ms_spin': 'How often each bot process checks for text-routed turns addressed to '
                                     'it.',
 'discord_room_router_rules_prompt_edit': 'Optional editable LLM router rules. Leave blank to use the '
                                          'transparent built-in default rules shown in the addon '
                                          'documentation/state.',
 'discord_play_test_tone_checkbox': 'Plays a short tone when the bot joins the channel to verify Discord '
                                    'output.',
 'discord_queue_replies_checkbox': 'Serializes outgoing reply audio so Discord playback does not overlap.',
 'discord_interrupt_reply_checkbox': 'Stops the current Discord reply, clears queued chunks, and aborts the '
                                     'active NC turn stream when the user starts speaking.',
 'discord_interrupt_after_seconds_spin': 'Stops current reply audio after this many seconds of continuous '
                                         'user speech, even before STT confirms words. Use 0 to disable.',
 'discord_reply_immunity_seconds_spin': 'Prevents immediate interruption during the first seconds of a bot '
                                        'reply. Continuous user speech can still interrupt once this window '
                                        'expires. Use 0 to disable.',
 'discord_discard_bot_speech_checkbox': 'When a human starts speaking, active captures of other bots are '
                                        'discarded instead of being sent as partial bot-to-bot turns. This '
                                        'keeps human interruptions from cascading between multiple NC bots.',
 'discord_coordinate_bot_replies_checkbox': 'When multiple NC Discord bots answer the same room turn, the '
                                            'first bot with playable audio gets the floor and later '
                                            'simultaneous bot replies are discarded.',
 'discord_reply_floor_stale_seconds_spin': 'How long a shared bot reply-floor claim may live before another '
                                           'bot treats it as stale. This prevents crashed/stopped bots from '
                                           'holding the floor forever.',
 'discord_initial_buffer_chunks_spin': 'How many rendered TTS chunks are buffered before Discord playback '
                                       'starts. Lower values reduce latency; higher values reduce stutter '
                                       'risk.',
 'discord_silence_ms_spin': 'How long Discord must be silent before a voice turn is considered complete.',
 'discord_min_turn_seconds_spin': 'Captures shorter than this are ignored before STT/mock processing.',
 'discord_max_turn_seconds_spin': 'Safety cap for one Discord voice turn. Use -1 for no hard cap; '
                                  'silence/idle detection still ends the turn.',
 'discord_bot_max_turn_seconds_spin': 'Safety cap for voice turns spoken by other Discord bots. Use -1 for '
                                      'no hard cap; this can be higher than human turns because TTS replies '
                                      'may be long.',
 'discord_bot_idle_finalize_ms_spin': 'How long decoded bot audio must be idle before finalizing another '
                                      "bot's utterance. Higher values reduce premature bot-to-bot turn "
                                      'taking when TTS chunks pause between sentences.',
 'discord_ignore_low_information_checkbox': "Drops short Whisper hallucinations such as 'and' or '1' before "
                                            'they reach the chat provider.',
 'discord_low_information_max_seconds_spin': 'Only transcripts at or below this capture duration are checked '
                                             'against the low-information phrase list. Use 0 to apply the '
                                             'phrase list regardless of duration.',
 'discord_low_information_transcripts_edit': 'Exact normalized transcripts to ignore when the capture is '
                                             "short. Keep real short answers such as 'no' out of this list.",
 'discord_wav_sample_rate_combo': 'Sample rate for saved/STT capture WAV files. Discord is decoded at 48 kHz '
                                  'stereo, but 16 kHz mono is usually enough for speech recognition and '
                                  'keeps files smaller.',
 'discord_wav_channels_combo': 'Channel count for saved/STT capture WAV files. Mono is recommended for '
                               'speech recognition and lower disk use.',
 'discord_save_captures_checkbox': 'Keeps captured voice turns on disk for debugging the bridge.',
 'discord_shared_capture_owner_checkbox': 'When multiple NC Discord bots are in the same voice channel, only '
                                          'one active bot captures and forwards human speech to NC. Other '
                                          'bots remain available for speaking and routing.',
 'discord_capture_owner_ttl_spin': 'How long the shared capture owner claim may live without a heartbeat '
                                   'before another active bot may take over.',
 'discord_token_env_edit': 'Name of the environment variable containing the Discord bot token. The token '
                           'itself should not be stored in session files.',
 'discord_local_token_edit': 'Optional write-only local token for private local testing. Prefer '
                             'token_env_var for normal use; this value must remain in ignored local '
                             'settings.',
 'discord_guild_id_edit': 'Discord server/guild ID. Can be copied with Discord Developer Mode.',
 'discord_voice_channel_id_edit': 'Discord voice channel ID to join.',
 'discord_allowed_user_id_edit': 'Optional Discord user IDs. Use one ID or a comma/space separated list. '
                                 'Only used when Answer mode is allowed_user_only.',
 'discord_answer_mode_combo': 'Controls whose voice turns can trigger NC replies.',
 'discord_start_on_launch_checkbox': 'Starts the bundled Node bridge as soon as this addon initializes.',
 'discord_bridge_mode_combo': 'Mock mode proves Discord transport. HTTP mode uses the real Discord Node '
                              'bridge. TinyMVP mode uses a local fake voice-room bridge for testing without '
                              'Discord.',
 'discord_context_entries_spin': 'How many prior Discord history entries this bot sends to the chat '
                                 'provider. User and assistant messages each count as one entry. Use 0 to '
                                 'send all retained Discord history.',
 'discord_persist_room_context_checkbox': 'When enabled, the Node bridge keeps its shared Discord room '
                                          'context JSON across bridge/app restarts. Leave off to start each '
                                          'bridge launch with a clean shared room context.',
 'discord_tiny_mvp_url_edit': 'Local TinyMVP fake voice-room server URL used when Bridge mode is TinyMVP.',
 'discord_tiny_mvp_start_with_gui_checkbox': 'When NC auto-starts the bundled TinyMVP room server, open its '
                                             'passive monitor window by default.',
 'discord_tiny_mvp_bridge_script_edit': 'Optional path to tiny_voice_bridge.py. Leave blank to use a TinyMVP '
                                        'folder next to the NC repo.',
 'discord_tiny_mvp_poll_seconds_spin': 'How often the TinyMVP bridge polls the fake voice-room state.',
 'discord_tiny_mvp_capture_mic_checkbox': 'When TinyMVP mode is active, adds the configured local user to '
                                          "the room and uses NC's microphone for that participant.",
 'discord_tiny_mvp_mic_user_id_edit': 'Stable fake human participant ID used for local microphone speech in '
                                      'TinyMVP.',
 'discord_tiny_mvp_mic_user_name_edit': 'Display name used for local microphone speech in TinyMVP.',
 'discord_tiny_mvp_mic_seconds_spin': 'Maximum phrase length for NC microphone input in TinyMVP mode.',
 'discord_tiny_mvp_mic_sample_rate_spin': 'Sample rate for TinyMVP microphone WAV captures. 16000 Hz mono is '
                                          'usually enough for STT testing.',
 'discord_tiny_mvp_mic_device_edit': 'Optional microphone name fragment or index. Leave blank for the '
                                     'default microphone.'}

HELP.update({
    'buddy_adult_nsfw_toggle': 'Enable the adult conversation prompt layer only for adult personas and participants. The normal intimacy layer is used when this is off.',
    'buddy_setup_buddy_count': 'Choose one focused companion, two balanced voices, or three for a livelier group preview. Review and Apply group to replace the active setup.',
    'buddy_setup_participation': 'Choose focused, balanced, or lively participation for the group preview. Apply the preview to use the proposed behavior.',
    'buddy_setup_trait_practical': 'Ask the setup builder for buddies who offer concrete, practical help. This shapes the preview rather than directly editing active buddies.',
    'buddy_setup_trait_warm': 'Ask the setup builder for more emotional warmth and supportive interaction in the proposed buddies.',
    'buddy_setup_trait_playful': 'Ask the setup builder for more humor and playful energy in the proposed group.',
    'buddy_setup_trait_expressive': 'Ask the setup builder for buddies who show more emotion and expressive reactions.',
    'buddy_setup_trait_honest': 'Ask the setup builder for buddies willing to disagree honestly rather than automatically agree.',
    'buddy_setup_trait_creative': 'Ask the setup builder for more imaginative ideas and creative conversation.',
    'buddy_setup_trait_flirtatious': 'Ask the setup builder for a more flirtatious conversational style in the proposed buddies.',
    'buddy_setup_preview_text': 'Read-only summary of the generated group. Review it before applying the setup.',
    'buddy_group_max_speakers': 'Maximum buddies allowed in one reply after this preview is applied. The upper limit follows the number of buddies in the preview.',
    'buddy_group_allow_buddy_to_buddy': 'Allow buddies to react to one another as well as to the user. Takes effect when the group preview is applied.',
    'buddy_group_natural_second_speaker': 'Invite a natural second speaker every N Buddy turns, subject to the speaker limit. 0 disables this periodic invitation. This edits the staged group.',
    'buddy_group_forced_buddy': 'Force a direct Buddy response every N completed replies, including in natural main-conversation mode. 0 disables forced replies. This edits the staged group.',
    'buddy_setup_shared_prompt': 'Shared Buddy instructions in the staged group. These can replace main persona instructions while Buddy Chat and its system override are enabled. Apply group to use this version.',
    'buddy_setup_normal_prompt': 'Normal intimacy and relationship instructions for the staged group, used when Adult / NSFW is off. Apply group to use this version.',
    'buddy_setup_adult_prompt': 'Adult conversation instructions for the staged group, used when Adult / NSFW is enabled. Apply group to use this version.',
    'buddy_refine_scope': 'Limit LLM refinement to the entire staged group, one buddy, or one field. Refinement changes the preview; Apply group activates it.',
    'buddy_refine_persona': 'Choose the staged buddy to refine when scope is One buddy or One field.',
    'buddy_refine_field': 'Choose the single persona field the refinement model may change. Used only with One field scope.',
    'buddy_refine_instruction': 'Describe the changes you want the LLM to propose within the selected refinement scope.',
    'buddy_enabled': 'Enable Buddy Chat participation in the main conversation using the active buddy profiles and reply mode.',
    'buddy_reply_mode': 'Natural main conversation adds Buddy context to the main LLM request. Direct Buddy-generated replies lets Buddy Chat generate replies itself; periodic forced replies can also run in natural mode.',
    'buddy_llm_mode': 'Choose the main LLM runtime, one shared Buddy provider, or each persona\'s provider for direct Buddy generation.',
    'buddy_max_speakers': 'Maximum buddies selected for one Buddy reply. Fewer active buddies can reduce the actual number of speakers.',
    'buddy_forced_every': 'Force a direct Buddy response every N completed replies while Buddy Chat is enabled. 0 disables this; it also works in natural main-conversation mode.',
    'buddy_structured_outputs': 'Use Instructor-assisted structured output for Buddy generation so speaker and reply fields can be validated.',
    'buddy_persona_window': 'Control the legacy active-persona window. The active persona is already represented natively in the Conversation workspace.',
    'buddy_persona_window_top': 'Keep the legacy active-persona window above other windows when that window is used.',
    'buddy_provider': 'Provider for shared direct Buddy generation. Main and Inherit use the main runtime. Other providers are used in shared provider mode and by inheriting personas in per-persona mode.',
    'buddy_model': 'Model ID for the shared Buddy provider. Use a model available from that provider; refresh discovery to inspect local choices.',
    'buddy_base_url': 'Endpoint URL for the shared Buddy provider, such as the address of your local model server.',
    'buddy_api_key': 'Credential for the shared Buddy provider. Use a key issued by the selected provider.',
    'buddy_system_override_enabled': 'Replace main persona instructions with the shared Buddy system override while Buddy Chat is enabled.',
    'buddy_system_override_prompt': 'Shared instructions used by the Buddy system override. They affect the main conversation while Buddy Chat and the override switch are enabled.',
    'chat_replay_messages': 'Select a message in the loaded saved conversation as the starting point for Replay from selected.',
    'chat_replay_assistant_voice': 'Voice sample used for assistant messages during replay. The empty option uses the current TTS voice.',
    'chat_replay_user_voice': 'Voice sample used for user messages during replay. The empty option uses the current TTS voice.',
    'identity_relay_owner_override': 'Allow explicitly selected identity records to be sent to external providers despite their owner restriction. This does not select or automatically send all stored artifacts.',
    'identity_relay_source_label': 'Optional provider or source label attached to the next imported identity artifact.',
    'identity_relay_pasted_artifact': 'Paste source-native NC_IDENTITY_EXPORT text, then import it. The raw export is preserved alongside a best-effort structured extraction.',
    'identity_relay_artifacts': 'Select a stored identity artifact to inspect its source, extracted structure, and warnings, or to target re-extraction and deletion.',
    'identity_relay_raw': 'Read-only original imported artifact, preserved for comparison with its structured extraction.',
    'identity_relay_structured': 'Read-only best-effort extraction of the selected artifact. Compare with the preserved raw source when details matter.',
    'identity_relay_warnings': 'Read-only mechanical validation and extraction warnings for the selected artifact.',
    'user_identity_enabled': 'Master switch for this local user profile, user avatar, and user image references. Profile context is attached to requests rather than saved into chat history or memory.',
    'user_identity_name': 'Name the companion should associate with the human user. Included in requests when User Identity and profile context are enabled.',
    'user_identity_preferred_address': 'Optional nickname, title, or form of address for the companion to use for you.',
    'user_identity_short_bio': 'Compact background information for normal conversation. Included as temporary request context when profile context is enabled.',
    'user_identity_interaction_notes': 'Conversation preferences the companion should know, such as how direct or detailed you prefer replies.',
    'user_identity_visual_prompt': 'Describe stable appearance and style for your visual identity. Avoid a temporary pose or scene; this guides user portrait generation.',
    'user_identity_transparent_portrait': 'Request real PNG transparency for newly generated user portraits. Imported portraits are left unchanged.',
    'user_identity_show_avatar': 'Show the saved user portrait beside user messages when User Identity is enabled.',
    'user_identity_visual_reference': 'Allow Visual Replies to use the saved user portrait as a reference, subject to the user appearance policy.',
    'user_identity_visual_policy': 'Requested includes the user when asked; allowed permits the user when appropriate; never excludes the user. User Identity and portrait references must also be enabled to supply the portrait.',
    'user_identity_reference_strength': 'User portrait reference strength from 0 to 1. Higher values request stronger visual resemblance; actual support depends on the image provider.',
    'user_identity_include_context': 'Attach the profile name, bio, address preference, and interaction notes to current LLM requests. This temporary context is not appended to canonical history or memory.',
    'main_chat_remote_idle_enabled': 'Allow the phone to cache idle avatar animations for reuse during pauses in speech.',
    'main_chat_remote_quality_preset': 'Set audio and video quality together. Low reduces bandwidth; Balanced uses 32 kbit/s audio and 500 kbit/s video; High uses 64 and 1000 kbit/s. Individual edits produce Custom. New authenticated connections sample these settings.',
    'main_chat_remote_quality_opus_kbps': 'Opus audio bitrate in kbit/s, from 16 to 96. Higher values use more bandwidth. Applies when a new authenticated peer connects.',
    'main_chat_remote_quality_video_kbps': 'H.264 video target bitrate in kbit/s, from 100 to 2000. Higher values allow more detail and use more bandwidth. Applies to new authenticated connections.',
    'main_chat_remote_quality_video_width': 'Maximum remote video width in pixels, from 160 to 448; use an even number. Lower widths reduce detail and bandwidth. Applies to new authenticated connections.',
    'main_chat_remote_quality_video_fps': 'Remote video frame rate: 6, 8, 12, or 24 frames per second. Higher rates make motion smoother and require more work and bandwidth. Applies to new authenticated connections.',
    'main_chat_remote_enabled': 'Enable the desktop bridge used by Main Chat Remote for phone connections.',
    'main_chat_remote_pairing_code': 'Pending LAN pairing code used when pairing a phone with this desktop. Generate a code or enter one before starting the pairing flow.',
    'main_chat_remote_show_backend_command': 'Reveal the generated backend command for advanced setup and diagnostics.',
    'main_chat_remote_backend_command': 'Read-only generated command for the remote backend. Use it as setup information; editing is not supported here.',
    'main_chat_internet_enabled': 'Enable Internet Remote using the saved configuration. Changing this switch applies the current Internet settings draft.',
    'main_chat_internet_ddns': 'Dynamic DNS hostname pointing to this desktop\'s public address. Save Internet settings to apply this draft field.',
    'main_chat_internet_public_ip': 'Public address used for Internet Remote setup and IP-change checks. Detect public IP can fill it. Save Internet settings to apply this draft field.',
    'main_chat_internet_external_port': 'Public HTTPS port phones connect to, usually 443. This is the external router-facing port. Save Internet settings to apply it.',
    'main_chat_internet_email': 'ACME account email used when requesting the HTTPS certificate. Save Internet settings to apply it.',
    'main_chat_internet_terms': 'Record acceptance of the certificate authority terms required for certificate setup. Save Internet settings to apply it.',
    'main_chat_internet_confirm_ip': 'Require confirmation before accepting a changed public IP for Internet Remote. Save Internet settings to apply it.',
    'main_chat_internet_show_advanced': 'Reveal the local HTTPS gateway and HTTP certificate-challenge ports.',
    'main_chat_internet_gateway_port': 'Local port for the HTTPS gateway, normally 8788. Keep it distinct from other local services. Save Internet settings to apply it.',
    'main_chat_internet_acme_port': 'Local HTTP port for ACME certificate challenges, normally 8780. Save Internet settings to apply it.',
    'main_chat_internet_enrollment_uri': 'Read-only setup link for a phone enrollment request. Creating enrollment produces this link and QR flow.',
    'main_chat_internet_pending': 'Select a pending phone enrollment before approving or rejecting it.',
    'main_chat_internet_devices': 'Select an already paired Internet device before revoking its access.',
})

HELP.update({
    'discord_moderator_target_combo': 'Select the running bot targeted by moderator controls, such as choosing the moderator bot or controlling its speaker floor.',
    'discord_moderator_enforce_mute_checkbox': 'Let the Discord moderator enforce the current speaker by muting other participants. Requires appropriate Discord permissions.',
    'discord_moderator_instances_table': 'Select a bridge instance as the target for moderator controls.',
    'discord_moderator_participants_table': 'Select a room participant for speaker, mute, or next-speaker controls.',
    'discord_moderator_allow_interrupt_current_checkbox': 'Allow a moderator handoff to interrupt the current speaker instead of waiting for the protected turn to finish.',
    'discord_moderator_announcement_edit': 'Text for the moderator announcement action. Enter the guidance or announcement before invoking the corresponding control.',
    'discord_instances_table': 'Select a bridge instance to target its live and moderator controls.',
    'discord_live_bot_combo': 'Choose the running bot that should answer a live test message.',
    'discord_live_message_edit': 'Type a live test message for the selected running bot. Sending exercises that bot\'s isolated reply path.',
    'discord_bot_list': 'Select the standalone bot entry whose connection, persona, model, and voice overrides you want to edit.',
    'discord_bot_enabled_checkbox': 'Include this bot entry when launching the standalone multi-bot bridge.',
    'discord_bot_id_edit': 'Stable identifier for this standalone bot entry. Bot IDs must be unique within the configured bot list.',
    'discord_bot_display_name_edit': 'Display name for this bot in the bridge\'s bot and room information.',
    'discord_bot_token_env_edit': 'Environment variable holding this bot\'s token. Each bot must have a valid token source; a missing per-bot token does not fall back to DISCORD_TOKEN.',
    'discord_bot_local_token_edit': 'Optional local token for this bot, kept in ignored local settings. Prefer an environment variable for normal standalone use.',
    'discord_bot_guild_id_edit': 'Override the shared Discord server/guild ID for this bot. Leave blank to inherit the shared connection settings.',
    'discord_bot_voice_channel_id_edit': 'Override the shared voice channel ID for this bot. Leave blank to inherit the shared connection settings.',
    'discord_bot_runtime_port_spin': 'Local runtime port for this bot\'s isolated endpoint. Running bots must use distinct ports.',
    'discord_bot_context_entries_spin': 'Maximum prior history entries sent with this bot\'s request. Each user or assistant message counts as one; 0 keeps all retained history.',
    'discord_bot_use_global_chat_model_checkbox': 'Use NC\'s selected global chat model instead of this bot\'s provider and model override.',
    'discord_bot_chat_provider_combo': 'Chat provider override for this bot when Use global chat model is off.',
    'discord_bot_chat_model_combo': 'Model ID for this bot\'s selected provider when Use global chat model is off.',
    'discord_bot_call_names_edit': 'Names or aliases used to recognize when this bot is addressed by room routing.',
    'discord_bot_voice_clone_wav_edit': 'Voice sample override for this bot. Relative filenames resolve from NC\'s voices folder. Empty uses the global voice fallback; linked room Personas use their saved voice settings.',
    'discord_bot_replace_nc_prompt_checkbox': 'Replace the selected NC system prompt and visual/emotional instruction block for this bot with its Discord persona prompt.',
    'discord_bot_persona_prompt_edit': 'Personality instructions for this bot\'s Discord turns. Appended to the NC prompt, or used in its place when Replace NC prompt is enabled.',
    'discord_filter_enabled_checkbox': 'Gate individual bot replies through the response filter so the bot can stay silent when an utterance is not addressed to it.',
    'discord_filter_mode_combo': 'Choose LLM sentinel, LLM judge, or local name/question detection to decide whether this individual bot should answer.',
    'discord_bot_names_edit': 'Names and call words the response filter recognizes as addressing this bot.',
    'discord_answer_uncertain_checkbox': 'Allow this bot to answer when its individual response filter cannot make a confident decision.',
    'discord_room_mode': 'Choose a managed desktop Local room or a Discord voice-channel room. Change transport while stopped; Discord requires prepared bot accounts.',
    'discord_room_anonymous': 'Hide human-versus-AI participant labels in the room presentation.',
    'discord_local_room_message': 'Draft text for the running room. Send submits room context; in Discord transport it does not post a Discord text-channel message.',
    'discord_local_room_participant': 'Participant identifier selected for room speaker, membership, mute, and history controls.',
    'discord_local_room_persona': 'Saved Persona selected for adding to the room or replacing the selected participant.',
    'discord_local_room_announcement': 'Draft moderator text. Guide conversation gives the moderator direction; Say it aloud requests the exact announcement.',
    'discord_accounts_view': 'Manage reusable Discord bot accounts for room Personas. Add a token and check the account before assigning it as a Prepared bot.',
    'discord_connection_advanced_toggle': 'Show legacy shared connection credentials used by standalone bridge setups.',
    'discord_router_advanced_toggle': 'Reveal routing policy, timeouts, grouping, and model instruction settings.',
    'discord_playback_advanced_toggle': 'Reveal reply buffering, interruption, and shared speaker coordination settings.',
    'discord_capture_advanced_toggle': 'Reveal audio capture, saved WAV, and shared capture ownership settings.',
    'discord_moderator_route_flow_view': 'Read-only view of the room routing flow and moderator handoffs.',
    'discord_logs_preview': 'Read-only preview of recent bridge logs. Diagnostics can help explain connection, routing, and playback failures.',
    'discord_runtime_http_endpoint_edit': 'Read-only HTTP endpoint for sending isolated Discord turns to the NC runtime. Host and port settings determine the address.',
    'discord_runtime_ws_endpoint_edit': 'Read-only WebSocket endpoint for the Discord runtime. Host and port settings determine the address.',
    'discord_allowed_user_id_edit': 'Incoming Discord user IDs accepted in Listed users mode, separated by commas, spaces, or semicolons. An empty list accepts everyone. Save settings and restart the bridge to apply changes.',
    'discord_answer_mode_combo': 'Everyone ignores the incoming-user ID list. Listed users uses that list, and an empty list also accepts everyone. Save settings and restart the bridge to apply changes.',
})

# Units are explicit where the schema text relied on the field label.
for _control_id, _unit in {
    'discord_tiny_mvp_poll_seconds_spin': 'seconds',
    'discord_tiny_mvp_mic_seconds_spin': 'seconds',
    'discord_tiny_mvp_mic_sample_rate_spin': 'Hz',
    'discord_max_turn_seconds_spin': 'seconds',
    'discord_bot_max_turn_seconds_spin': 'seconds',
    'discord_silence_ms_spin': 'milliseconds',
    'discord_min_turn_seconds_spin': 'seconds',
    'discord_bot_idle_finalize_ms_spin': 'milliseconds',
    'discord_room_router_route_window_spin': 'milliseconds',
    'discord_room_router_poll_ms_spin': 'milliseconds',
    'discord_room_router_text_age_spin': 'seconds',
    'discord_dead_air_cooldown_spin': 'seconds',
    'discord_dead_air_silence_timeout_spin': 'seconds',
    'discord_capture_owner_ttl_spin': 'seconds',
    'discord_reply_floor_stale_seconds_spin': 'seconds',
    'discord_room_router_decision_timeout_spin': 'seconds',
}.items():
    HELP[_control_id] += f' Measured in {_unit}.'
HELP['discord_initial_buffer_chunks_spin'] += ' 0 removes the initial chunk prebuffer.'

HELP.update({
    'mprc_enabled_checkbox': 'Enable roleplay framing for the current session using its selected persona, mode, and scene state.',
    'mprc_show_character_checkbox': 'Track the current story speaker in the character preview. Story-scene image generation is controlled separately in Story Images.',
    'mprc_ar_mode_checkbox': 'Switch to narrator-led AlternativeReality mode and enable roleplay. Turning this off restores the previous non-AR mode.',
    'mprc_active_persona_combo': 'Choose the active roleplay persona and select its profile for editing.',
    'mprc_current_character_view_mode': 'Limit character preview choices to the active story cast, or show all saved personas.',
    'mprc_visual_enabled': 'Allow the selected persona to request story-scene images through Visual Reply. A configured Visual Reply provider is still required.',
    'mprc_visual_mode': 'Choose manual images or automatic triggers such as scene changes, locations, characters, choices, story beats, reply intervals, or explicit image requests. Off prevents story image requests.',
    'mprc_visual_provider': 'Image provider override for the selected persona. Inherit uses the existing Visual Reply provider configuration.',
    'mprc_visual_model': 'Optional image model override for this persona. Leave blank to use the configured Visual Reply model.',
    'mprc_visual_size': 'Requested image dimensions for this persona. Inherit follows Visual Reply; Auto lets the provider choose. Supported dimensions depend on the provider.',
    'mprc_visual_style': 'Style preset added to this persona\'s story image prompts. Default leaves the preset unspecified.',
    'mprc_visual_character': 'Stable character appearance and scene-look details added to this persona\'s story image prompts.',
    'mprc_visual_clothing': 'Clothing and props to include in this persona\'s story image prompts.',
    'mprc_visual_environment': 'Place, atmosphere, and environment style to include in this persona\'s story images.',
    'mprc_visual_negative': 'Things to avoid in this persona\'s generated story images. Provider support for negative instructions varies.',
    'mprc_visual_continuity': 'Ask story image prompts to preserve the character\'s appearance across scenes.',
    'mprc_visual_appearance_freedom': 'Strict preserves the established appearance. Flexible allows scene-led changes to hair, makeup, clothing, and facial styling without changing the saved avatar.',
    'mprc_visual_scene': 'Include the latest scene summary when composing this persona\'s story image prompt.',
    'mprc_visual_speaker': 'Include the active speaker when composing this persona\'s story image prompt.',
    'mprc_visual_interval': 'Number of replies between periodic image checks when the generation mode is Every N replies.',
    'mprc_visual_cooldown': 'Minimum seconds between automatic story image requests for this persona. 0 removes this wait; manual requests bypass the cooldown.',
    'mprc_visual_max_auto': 'Image limit checked against the session image count for this persona\'s requests. 0 means no limit. The current generation gate also checks this limit for manual requests.',
    'mprc_visual_auto_show': 'Show the Visual Reply dock automatically when this persona requests a story image.',
    'mprc_audio_story_sounds': 'Allow matching story audio tags to play local Story Sound files during narration. Tags are removed from spoken narration.',
    'mprc_audiofx_volume': 'Story sound playback volume from 0 to 100 percent, including manual previews. 0 mutes story sounds.',
    'mprc_audiofx_test_mode': 'Store the Story Sounds test-mode preference. Use Create Test Sounds to create sample cues in the native interface.',
    'mprc_audio_sound_description': 'Describe the music, ambience, effect, or stinger to turn into a sound prompt or Story Sound entry.',
    'mprc_audio_type': 'Sound category for prompt generation: music, background ambience, effect, or short stinger. Auto asks generation to infer the type.',
    'mprc_audio_prompt_output': 'Review or edit the generated sound prompt before saving or copying it for audio creation.',
    'mprc_audio_saved_prompts': 'Select a saved sound prompt for load, copy, or deletion. -1 is the empty-list placeholder when no prompts are saved.',
    'mprc_audiofx_list': 'Select a Story Sound entry for preview, description loading, file attachment, or removal. -1 is the placeholder when no entries exist.',
    'mprc_master_story_list': 'Select a saved Story Library entry for load, export, or library actions. Selection alone does not apply a new draft.',
    'mprc_master_story_prompt': 'Premise and requirements for generating a Master Story setup. Preserve required names, relationships, and conflicts; review the resulting draft before applying it.',
    'mprc_master_story_mode': 'Mode requested in the generated draft: one persona, group conversation, narrator with characters, game master, or AlternativeReality.',
    'mprc_master_story_scene_title': 'Opening scene title supplied to Master Story generation.',
    'mprc_master_story_location': 'Opening location supplied to Master Story generation.',
    'mprc_master_story_time_of_day': 'Opening time of day or atmosphere supplied to Master Story generation.',
    'mprc_master_story_mood': 'Opening mood supplied to Master Story generation.',
    'mprc_master_story_visual_direction': 'Visual direction for avatars created from the Master Story draft, such as style, lighting, and character presentation.',
    'mprc_master_story_sfw_mode': 'Request a safe-for-work story brief and draft from Master Story generation.',
    'mprc_master_story_native_persona_count': 'Requested native story persona count in the draft, from 0 to 24. 0 asks only for characters explicitly required by the premise. This differs from the Apply Draft creation limit.',
    'mprc_master_story_max_created_characters': 'Maximum new character profiles Apply Draft may create, from 1 to 40, unless exceeding the limit is allowed.',
    'mprc_master_story_allow_exceed_max_created_characters': 'Permit Apply Draft to create more characters than the configured maximum.',
    'mprc_master_story_use_existing_personas': 'Allow Master Story setup to reuse personas already saved in the registry.',
    'mprc_master_story_auto_create': 'Allow Apply Draft to create missing persona profiles required by the story.',
    'mprc_master_story_auto_assign_voices': 'Assign distinct available voices to newly created story personas when applying the draft.',
    'mprc_master_story_update_existing': 'Allow Apply Draft to update matching saved persona profiles. Review the draft before applying changes to existing characters.',
    'mprc_master_story_auto_avatars': 'Request avatar images for newly created personas when applying the draft. Requires an available image provider.',
    'mprc_master_story_avatar_style_sheets': 'Request avatar style sheets for new personas as part of Master Story avatar creation.',
    'mprc_master_story_clear_memory': 'Start with clean story memory when Apply Draft activates the new setup. Review this before reapplying a story whose continuity you want to keep.',
    'mprc_master_story_draft': 'Editable Master Story draft as a JSON object. Editing saves the draft; Apply Draft activates it. Malformed JSON is rejected.',
    'mprc_ar_enabled': 'Enable narrator-led AlternativeReality mode for this session. Turning it off restores the previous non-AR mode.',
    'mprc_ar_use_persona_profiles': 'Use each persona\'s enabled AR description and AR system prompt in AlternativeReality mode instead of its normal companion profile.',
    'mprc_ar_pacing': 'Guide AR narration toward slower audiobook scenes, balanced progression, or faster game-like turns.',
    'mprc_ar_interaction': 'Guide how frequently AR narration asks for your input: often, sometimes, or only at important choices.',
    'mprc_ar_dialogue_density': 'Guide the balance between narrator prose and character dialogue, from narrator-led scenes to a high-dialogue ensemble.',
    'mprc_ar_tension': 'Story tension level from 0 to 10 in the AR scene state. Higher values describe a more tense scene.',
    'mprc_ar_current_scene': 'Current scene description in the persistent AlternativeReality state.',
    'mprc_ar_location': 'Current location in the AlternativeReality scene state.',
    'mprc_ar_time_of_day': 'Current time of day in the AlternativeReality scene state.',
    'mprc_ar_mood': 'Current atmosphere or mood in the AlternativeReality scene state.',
    'mprc_ar_story_goal': 'Current overarching story goal supplied to AR narration.',
    'mprc_ar_active_characters': 'Comma-separated persona IDs active in the AR scene. Up to eight entries are retained.',
    'mprc_ar_player_intent': 'Current player intention supplied to AR narration as scene-state context.',
    'mprc_ar_pending_choices': 'Pending AR choices, one per line. Up to six nonempty choices are retained.',
    'mprc_session_mode': 'Choose one-persona roleplay, group dialogue, narrator with characters, game-master play, or narrator-led AlternativeReality. Choosing AR also enables the session.',
    'mprc_scene_title': 'Title of the current roleplay scene, included in scene prompt context.',
    'mprc_location': 'Current roleplay location, included in scene prompt context.',
    'mprc_time_of_day': 'Time of day for the current roleplay scene.',
    'mprc_mood': 'Mood or atmosphere for the current roleplay scene.',
    'mprc_objective': 'Current objective that should guide the roleplay scene.',
    'mprc_scene_summary': 'Compact continuity summary supplied with the current roleplay scene.',
    'mprc_auto_select': 'Allow roleplay speaker selection to choose the next character automatically rather than relying on your manual choice.',
    'mprc_next_speaker': 'Set the session\'s current speaker manually. Automatic speaker selection can choose speakers when enabled.',
    'mprc_continuity': 'Include continuity guidance so the current roleplay scene stays consistent with its established state.',
    'mprc_update_scene': 'Allow scene-state updates after assistant replies so roleplay context can follow story progression.',
    'mprc_narrator_persona': 'Explicit persona used for narrator voice routing. This is separate from the selected character\'s voice profile.',
    'mprc_voice_follow_active': 'Edit voice settings for the active persona. Turn off to select another persona\'s voice independently.',
    'mprc_voice_persona': 'Choose the persona whose voice profile you are editing. Selecting one turns off Follow active persona.',
    'mprc_voice_enabled': 'Enable this voice profile for the persona selected in the voice editor.',
    'mprc_voice_backend': 'TTS backend override for the selected voice persona. Inherit follows NC\'s current TTS backend.',
    'mprc_voice_sample': 'Reference audio path for the selected persona\'s voice. The TTS backend must support that reference format.',
    'mprc_voice_sample_picker': 'Choose a known local voice sample and assign its path to the selected persona\'s voice profile.',
    'mprc_voice_preset': 'Optional voice preset name for the selected persona. Interpretation depends on the TTS backend.',
    'mprc_voice_language': 'Optional language code for this persona\'s voice, such as en, fr, or ja. Empty leaves the language unspecified; support depends on the backend.',
    'mprc_persona_id': 'Stable ID of the selected persona. Edits are normalized and made unique; current session, narrator, and voice-editor references are updated.',
    'mprc_persona_enabled': 'Include this persona among enabled roleplay characters.',
    'mprc_master_narrator': 'Mark this persona as a master narrator candidate for story narration.',
    'mprc_display_name': 'Visible name for the selected persona, used in the cast and speaker labels.',
    'mprc_role': 'Character role or archetype included in the selected persona\'s roleplay instructions.',
    'mprc_description': 'Background and identity description for the selected persona\'s normal roleplay profile.',
    'mprc_character_image_path': 'Local image path used as the selected persona\'s character portrait.',
    'mprc_system_prompt': 'Persona-specific instructions added to roleplay requests for this character. Normal NC safety and runtime instructions still apply.',
    'mprc_ar_profile_enabled': 'Use this persona\'s AR-specific profile when AlternativeReality and Use AR persona prompts are enabled.',
    'mprc_ar_description': 'Story-specific identity and background for this persona in AlternativeReality mode.',
    'mprc_ar_system_prompt': 'Story-specific instructions for this persona when its AR profile is used.',
    'mprc_speaking_style': 'Wording, rhythm, and conversational manner to request from this persona.',
    'mprc_allowed_tone': 'Tone guidance included in this persona\'s prompt, such as restrained, warm, or formal.',
    'mprc_response_length': 'Prompt preference for short, balanced, or detailed replies from this persona. It is not an exact token limit.',
    'mprc_temperature_hint': 'Optional saved style note for this persona\'s randomness or energy. This text field is not a numeric model temperature control.',
    'mprc_memory_scope': 'Prompt guidance for shared, persona-only, session-only, or disabled persona continuity. This choice does not itself delete saved memory.',
    'mprc_behavior_mode': 'Roleplay framing for this persona: companion, RPG character, narrator, game master, or group participant.',
    'mprc_tags': 'Comma-separated tags for the selected persona. Entries are trimmed and stored in lowercase.',
    'mprc_persona_list': 'Select the saved persona to edit. This editor selection alone does not change the session\'s active persona.',
    'mprc_story_template': 'Choose a built-in story template for the template load action, such as fantasy mystery, sci-fi horror, or cozy tavern.',
    'mprc_story_pinned_facts': 'Story facts to retain, one per line. Up to 80 nonempty lines are saved as pinned-fact text.',
    'mprc_story_memory_list': 'Select a story memory snapshot for inspection or memory actions.',
    'mprc_chat_director_pacing_combo': 'Change the current AR pacing preference from slow audiobook narration to faster game-like turns.',
    'mprc_chat_director_tone_combo': 'Story director tone preference for upcoming play turns. Keep current leaves the existing tone in place.',
    'mprc_chat_director_agency_combo': 'Guide player agency toward guided progression, open choices, or stricter consequences.',
    'mprc_chat_director_choice_mode_combo': 'Choose between a list of story choices and asking the player for their next move.',
    'mprc_chat_next_actions_list': 'Select a pending AR action for the next-action controls. Selection stores the choice without submitting a turn.',
    'mprc_chat_recent_events_list': 'Select a recent story event for event-related play controls.',
    'mprc_chat_present_characters_list': 'Select an enabled character from the present-character list for play controls.',
    'mprc_chat_input_legacy': 'Draft player input for the legacy roleplay chat control.',
    'mprc_chat_use_ar_checkbox': 'Switch play to narrator-led AlternativeReality. Turning it off restores the saved non-AR session mode.',
    'mprc_chat_visuals_checkbox': 'Allow story image requests during play, in addition to each persona\'s image-generation settings.',
    'mprc_chat_input': 'Draft your next roleplay input. Select intent and speaker if needed, then send to advance the story.',
    'mprc_chat_voice_volume_slider': 'Roleplay narration voice volume from 0 to 100 percent. 0 mutes the story voice.',
    'mprc_chat_intent_combo': 'Classify player input as action, speech, direction, or out-of-character discussion. Auto infers intent from your text.',
    'mprc_chat_speaker_combo': 'Choose the persona targeted as the current play speaker. This also updates the session\'s current speaker ID.',
    'mprc_chat_structured_output_checkbox': 'Request structured JSON story replies so play can extract narration, state, and choices from defined fields.',
    'mprc_chat_structured_output_scope_combo': 'Request structured story output on every turn or only the first turn.',
    'mprc_chat_instructor_structured_outputs_checkbox': 'Enable Instructor-assisted validation for supported structured roleplay outputs.',
    'mprc_chat_instructor_ar_turn_checkbox': 'Enable Instructor assistance specifically for structured AlternativeReality turns.',
    'mprc_chat_story_font_size_spin': 'Text size for the story playback display, from 8 to 48 points.',
    'mprc_chat_remote_enabled_checkbox': 'Enable the roleplay LAN Remote server. Editing this switch or its host, port, or code resynchronizes the remote backend.',
    'mprc_chat_remote_host_input': 'Bind address for roleplay LAN Remote. Loopback restricts access to this computer; a LAN bind permits other devices to connect. Changes resynchronize the server.',
    'mprc_chat_remote_port_spin': 'Listening port for roleplay LAN Remote, from 1 to 65535. Keep it distinct from other local services. Changes resynchronize the server.',
    'mprc_chat_remote_code_spin': 'Six-digit access code for roleplay LAN Remote. Changes resynchronize the remote backend.',
    'mprc_chat_chromecast_device_combo': 'Select a discovered Chromecast device for roleplay casting controls.',
    'mprc_chat_play_toolbar_advanced_toggle': 'Show advanced roleplay playback controls in the play toolbar.',
    'mprc_debug_prompt': 'Read-only snapshot of the persona prompt prepared for the roleplay request.',
    'mprc_debug_visual': 'Read-only snapshot of story image prompt diagnostics.',
    'mprc_debug_voice': 'Read-only voice routing diagnostics for current story playback.',
    'mprc_debug_state': 'Read-only serialized roleplay session state for checking continuity.',
    'mprc_debug_visual_calls': 'Read-only log of recorded Visual Reply requests and their outcomes.',
    'mprc_ar_recent_events': 'Read-only recent event context in the AlternativeReality state.',
    'mprc_roster': 'Read-only enabled persona roster with IDs and roleplay behavior modes.',
    'mprc_story_status': 'Read-only story readiness and active setup status.',
    'mprc_story_validation': 'Read-only validation results for the story setup.',
    'mprc_story_voice_routes': 'Read-only explanation of narrator and character voice routes.',
    'mprc_story_next_inspector': 'Read-only inspection of the next story request and its routing context.',
    'mprc_story_event_log': 'Read-only history of recent story events.',
    'mprc_chat_spotify_music_summary': 'Read-only summary of story music and Spotify state available to playback.',
    'mprc_chat_voice_segments_summary': 'Read-only summary of narration and character voice segments for playback.',
    'mprc_chat_visual_beat_summary': 'Read-only summary of the current story image beat.',
    'mprc_chat_memory_databank_summary': 'Read-only summary of story memory available to play.',
    'mprc_chat_story_director_summary': 'Read-only summary of story director preferences.',
    'mprc_visual_prompt_debug_text': 'Read-only story image prompt diagnostics for checking the generated request.',
    'mprc_chat_transcript': 'Read-only roleplay conversation transcript.',
})

# Surface-qualified legacy IDs: other addon surfaces reuse anonymous widget names.
for _suffix, _contents in {
    'story_setup_session_state': 'the story setup and session state',
    'story_library_entry_story_metadata': 'the Story Library entry and metadata',
    'personas_used_by_this_story_4': 'persona profiles used by this story',
    'persona_visual_settings': 'persona visual-generation settings',
    'persona_avatar_image_files': 'local persona avatar image files',
    'persona_voice_settings': 'persona voice routing settings',
    'voice_sample_audio_files': 'local reference voice audio files',
    'story_memory': 'story memory records',
    'recent_story_events_story_log_4': 'recent story events and the story log',
    'sound_effects_audiofx_settings': 'Story Sounds and AudioFX settings',
    'sound_effect_audio_files': 'local Story Sound audio files',
    'visual_styles_used_by_story': 'visual styles referenced by the story',
    'master_story_draft_setup_data_if_available': 'Master Story draft and setup data when available',
    'story_prompt_template_data_if_available': 'story prompt and template data when available',
}.items():
    HELP['multi_persona_roleplay_tab.unnamed_qcheckbox_' + _suffix] = (
        'Include ' + _contents + ' in the next Story Library export package. '
        'This selects package contents without changing the active story.'
    )

for _suffix, _purpose in {
    'persona_prompt': 'persona prompt',
    'image_prompt': 'image prompt',
    'voice_routing': 'voice routing',
    'story_state_summary': 'story-state summary',
    'visual_reply_request_log': 'Visual Reply request log',
}.items():
    HELP['multi_persona_roleplay_tab.unnamed_qgroupbox_advanced_' + _suffix] = (
        'Expand or collapse the read-only ' + _purpose + ' diagnostics for the current roleplay session.'
    )

for _index, _purpose in enumerate((
    'Story Health and readiness checks',
    'AlternativeReality setup and narration',
    'Master Story drafting, refinement, and applying',
    'story images and Visual Reply',
    'Story Sounds and local audio tags',
    'the Master, Scenarios, Registry, and playback workspaces',
    'troubleshooting story images, voices, and sounds',
    'the Lantern Archive demonstration story',
), start=1):
    _guide_id = 'unnamed_qplaintextedit_qplaintextedit' + ('' if _index == 1 else f'#{_index}')
    HELP[f'multi_persona_roleplay_tab.{_guide_id}'] = 'Read-only guide to ' + _purpose + '.'

_BUDDY_PERSONA_HELP: dict[str, str] = {
    'enabled': 'Include this buddy among active speakers.',
    'name': 'Visible buddy name used in conversation and speaker selection.',
    'role': 'Role or specialty supplied in this buddy\'s personality instructions.',
    'description': 'Detailed identity, background, and personality for this buddy.',
    'system_prompt': 'Complete persona-specific instructions used when building this buddy\'s conversation context or direct reply.',
    'style': 'Speaking style supplied in this buddy\'s prompt, such as concise, warm, or playful.',
    'helpfulness': 'Helpfulness preference from 0 to 100; higher values request more active practical assistance.',
    'warmth': 'Warmth preference from 0 to 100; higher values request more supportive and affectionate wording.',
    'humor': 'Humor preference from 0 to 100; higher values request more jokes and playful wording.',
    'expressiveness': 'Expressiveness preference from 0 to 100; higher values request more visible emotion in replies.',
    'initiative': 'Initiative preference from 0 to 100; higher values request more proactive contributions.',
    'directness': 'Directness preference from 0 to 100; higher values request more straightforward wording.',
    'disagreement': 'Disagreement preference from 0 to 100; higher values encourage honest pushback rather than automatic agreement.',
    'flirtation': 'Flirtation preference from 0 to 100, used as style guidance within the active intimacy layer.',
    'participation_weight': 'Relative speaker-selection weight from 0 to 100. Higher values favor this buddy, with recent speakers ranked lower. 0 does not disable the buddy; this is not a percentage of replies.',
    'reply_length': 'Prompt preference for short, balanced, or detailed replies. It is not an exact token count.',
    'voice_enabled': 'Use this buddy\'s reference voice sample when routing speech for its replies.',
    'voice_path': 'Local reference voice audio path for this buddy. The TTS backend must support reference audio.',
    'avatar_preset': 'Select a prompt template used to prepare this buddy\'s avatar image prompt.',
    'avatar_prompt': 'Image-generation instructions used when generating this buddy\'s avatar.',
    'avatar_path': 'Local image path used as this buddy\'s avatar.',
    'provider': 'Provider override for this buddy in per-persona provider mode. Inherit follows the shared Buddy provider.',
    'model': 'Model ID for this buddy\'s provider override. Use a model available from that provider.',
    'base_url': 'Endpoint URL for this buddy\'s provider override, such as a local model server address.',
    'api_key': 'Credential for this buddy\'s provider override.',
}


def help_for(control_id: str, surface_id: str = '') -> str:
    """Return reviewed copy for explicit IDs and known semantic families."""
    key = str(control_id or '')
    exact = HELP.get(f'{surface_id}.{key}', '') or HELP.get(key, '')
    if exact:
        return exact
    match = re.fullmatch(r'buddy_(setup_)?persona_[0-9]+_(.+)', key)
    if match:
        text = _BUDDY_PERSONA_HELP.get(match.group(2), '')
        if text and match.group(1):
            return text + ' This edits the staged preview; Apply group activates it.'
        return text
    return ''

.pragma library

// Presentation-only ordering for the frozen MPRC native control contract.
// Runtime IDs, values, options, enabled state, and action metadata stay on the
// original field objects owned by the bridge.

var SECTION_ORDER = [
    "Master", "Scenarios & Lore", "Registry", "Editor", "Voice",
    "Story Images", "Story Sounds", "Story Health", "Play", "Session", "AR",
    "Guide", "Troubleshooting", "Status"
]

function block(key, title, ids, columns, fold, expanded, span) {
    return {
        "key": key,
        "title": title,
        "ids": ids,
        "columns": columns || 1,
        "fold": Boolean(fold),
        "expanded": expanded !== false,
        "span": span === 1 ? 1 : 2
    }
}

var GROUPS = ({
    "Guide": [
        block("intro", "", ["unnamed_qlabel_qlabel#12"], 1),
        block("quick_start", "Quick Start", [
            "mprc_guide_read_all", "mprc_guide_stop_speech",
            "unnamed_qlabel_qlabel#13", "unnamed_qlabel_qlabel#14",
            "unnamed_qlabel_qlabel#15", "unnamed_qlabel_qlabel#16",
            "unnamed_qlabel_qlabel#17", "unnamed_qlabel_qlabel#18",
            "unnamed_qlabel_qlabel#19", "unnamed_qlabel_qlabel#20",
            "unnamed_qlabel_qlabel#21", "unnamed_qlabel_qlabel#22",
            "mprc_guide_read_quick_start"
        ], 1),
        block("story_health", "Story Health", [
            "unnamed_qplaintextedit_qplaintextedit", "mprc_guide_read_story_health"
        ], 1, true, false),
        block("ar_mode", "Alternative Reality Mode", [
            "unnamed_qplaintextedit_qplaintextedit#2",
            "mprc_guide_read_alternativereality_mode"
        ], 1, true, false),
        block("master_builder", "Master Story Builder", [
            "unnamed_qplaintextedit_qplaintextedit#3",
            "mprc_guide_read_master_story_builder"
        ], 1, true, false),
        block("story_images", "Visual Reply & Story Images", [
            "unnamed_qplaintextedit_qplaintextedit#4",
            "mprc_guide_read_visual_reply_story_images"
        ], 1, true, false),
        block("story_sounds", "Story Sounds", [
            "unnamed_qplaintextedit_qplaintextedit#5",
            "mprc_guide_read_audio_tab_and_story_sounds"
        ], 1, true, false),
        block("which_tab", "Which Tab to Use", [
            "unnamed_qplaintextedit_qplaintextedit#6",
            "mprc_guide_read_which_tab_to_use"
        ], 1, true, false),
        block("troubleshooting", "Troubleshooting", [
            "unnamed_qplaintextedit_qplaintextedit#7",
            "mprc_guide_read_troubleshooting"
        ], 1, true, false),
        block("default_scenario", "Default Saved Scenario", [
            "unnamed_qplaintextedit_qplaintextedit#8",
            "mprc_guide_read_default_saved_scenario", "mprc_load_default_scenario"
        ], 1, true, false)
    ],
    "Registry": [
        block("intro", "", ["unnamed_qlabel_qlabel#10"], 1),
        block("personas", "Persona Registry", ["mprc_persona_list"], 1),
        block("manage", "Persona actions", [
            "mprc_add_persona", "mprc_duplicate_persona", "mprc_delete_persona",
            "mprc_import_personas", "mprc_export_personas"
        ], 2),
        block("reset", "Reset registry", ["mprc_reset_defaults"], 1, true, false)
    ],
    "Editor": [
        block("intro", "", ["unnamed_qlabel_qlabel#9"], 1),
        block("identity", "Persona Editor", [
            "mprc_display_name", "mprc_persona_id", "mprc_persona_enabled",
            "mprc_master_narrator", "mprc_role", "mprc_tags", "mprc_description"
        ], 2),
        block("character_picture", "Character picture", [
            "mprc_character_image_path", "mprc_character_image_browse",
            "mprc_character_image_generate", "mprc_character_image_clear"
        ], 1, true, true),
        block("persona_prompts", "Persona & AR prompts", [
            "mprc_system_prompt", "mprc_ar_profile_enabled", "mprc_ar_description",
            "mprc_ar_system_prompt"
        ], 1),
        block("speaking_behavior", "Speaking style & behavior", [
            "mprc_speaking_style", "mprc_allowed_tone", "mprc_response_length",
            "mprc_temperature_hint", "mprc_memory_scope", "mprc_behavior_mode"
        ], 2, true, true)
    ],
    "Voice": [
        block("intro", "", ["unnamed_qlabel_qlabel#8"], 1),
        block("narrator_routing", "Narrator routing", [
            "mprc_narrator_persona", "mprc_voice_follow_active",
            "mprc_voice_current_persona"
        ], 1, false, true, 1),
        block("voice_persona", "Voice Per Persona", [
            "mprc_voice_persona", "mprc_voice_enabled", "mprc_voice_backend",
            "mprc_voice_preset", "mprc_voice_language"
        ], 2, false, true, 1),
        block("voice_sample", "Voice sample & test", [
            "mprc_voice_sample", "mprc_voice_browse", "mprc_voice_clear",
            "mprc_voice_sample_picker", "mprc_voice_test"
        ], 2),
        block("voice_routing_preview", "Voice routing preview", [
            "unnamed_qlabel_qlabel#25", "mprc_chat_voice_segments_summary"
        ], 1, true, false)
    ],
    "Session": [
        block("intro", "", ["unnamed_qlabel_qlabel#7"], 1),
        block("session", "Roleplay Session", [
            "mprc_session_mode", "mprc_session_mode_note", "mprc_scene_title",
            "mprc_location", "mprc_time_of_day", "mprc_mood", "mprc_objective",
            "mprc_scene_summary", "mprc_roster"
        ], 2),
        block("speaker_continuity", "Speaker & continuity", [
            "mprc_auto_select", "mprc_next_speaker", "mprc_continuity",
            "mprc_update_scene"
        ], 2, true, true),
        block("actions", "", [
            "mprc_reset_scene", "mprc_export_session", "mprc_import_session"
        ], 2)
    ],
    "AR": [
        block("intro", "", ["unnamed_qlabel_qlabel#5"], 1),
        block("runtime", "AR Runtime", [
            "mprc_ar_enabled", "mprc_ar_use_persona_profiles", "mprc_ar_pacing",
            "mprc_ar_interaction", "mprc_ar_dialogue_density", "mprc_ar_tension",
            "unnamed_qlabel_qlabel#6", "mprc_ar_seed", "mprc_ar_fill_profiles"
        ], 1, false, true, 1),
        block("state", "AR State", [
            "mprc_ar_current_scene", "mprc_ar_location", "mprc_ar_time_of_day",
            "mprc_ar_mood", "mprc_ar_story_goal", "mprc_ar_active_characters",
            "mprc_ar_player_intent", "mprc_ar_pending_choices",
            "mprc_ar_recent_events", "mprc_ar_clear"
        ], 2, false, true, 1)
    ],
    "Master": [
        block("intro", "", ["unnamed_qlabel_qlabel#3"], 1),
        block("library", "Story Library", [
            "mprc_master_story_list", "mprc_master_story_load",
            "mprc_master_story_delete", "mprc_master_story_status"
        ], 2),
        block("builder", "Master Story Builder", [
            "mprc_master_story_prompt", "mprc_master_story_mode",
            "mprc_master_story_scene_title", "mprc_master_story_location",
            "mprc_master_story_time_of_day", "mprc_master_story_mood",
            "mprc_master_story_visual_direction", "mprc_master_story_sfw_mode",
            "mprc_story_brief"
        ], 2),
        block("cast_generation", "Cast generation", [
            "mprc_master_story_native_persona_count",
            "mprc_master_story_max_created_characters",
            "mprc_master_story_allow_exceed_max_created_characters",
            "mprc_master_story_use_existing_personas", "mprc_master_story_auto_create",
            "mprc_master_story_auto_assign_voices", "mprc_master_story_update_existing",
            "mprc_master_story_auto_avatars", "mprc_master_story_avatar_style_sheets",
            "mprc_master_story_clear_memory"
        ], 2, true, false),
        block("draft", "", [
            "mprc_master_story_generate", "mprc_master_story_draft",
            "mprc_master_story_apply", "mprc_master_story_save",
            "mprc_master_story_restart"
        ], 1),
        block("library_export", "Story Library Export", [
            "unnamed_qlabel_qlabel#4", "unnamed_qcheckbox_story_setup_session_state",
            "unnamed_qcheckbox_story_library_entry_story_metadata",
            "unnamed_qcheckbox_personas_used_by_this_story_4",
            "unnamed_qcheckbox_persona_visual_settings",
            "unnamed_qcheckbox_persona_avatar_image_files",
            "unnamed_qcheckbox_persona_voice_settings",
            "unnamed_qcheckbox_voice_sample_audio_files",
            "unnamed_qcheckbox_story_memory",
            "unnamed_qcheckbox_recent_story_events_story_log_4",
            "unnamed_qcheckbox_sound_effects_audiofx_settings",
            "unnamed_qcheckbox_sound_effect_audio_files",
            "unnamed_qcheckbox_visual_styles_used_by_story",
            "unnamed_qcheckbox_master_story_draft_setup_data_if_available",
            "unnamed_qcheckbox_story_prompt_template_data_if_available",
            "mprc_story_export_status", "mprc_story_export_button",
            "mprc_story_import_button", "mprc_story_export_preview"
        ], 2, true, false)
    ],
    "Story Sounds": [
        block("intro", "", ["mprc_audio_intro"], 1),
        block("story_sounds", "Story Sounds", [
            "mprc_audio_story_sounds", "mprc_audiofx_volume", "mprc_audio_story_note"
        ], 1),
        block("sound_test", "Sound test tools", [
            "mprc_audiofx_test_mode", "mprc_audiofx_create_test_sounds",
            "mprc_audiofx_play_test_tag"
        ], 2, true, false),
        block("prompt", "Create Prompt for Audio", [
            "mprc_audio_sound_description", "mprc_audio_examples", "mprc_audio_type",
            "mprc_audio_create_prompt", "mprc_audio_prompt_output",
            "mprc_audio_variation_ambience", "mprc_audio_variation_horror",
            "mprc_audio_variation_calm", "mprc_audio_variation_action",
            "mprc_audio_copy_prompt", "mprc_audio_save_prompt",
            "mprc_audio_save_item_description", "mprc_audio_clear_prompt"
        ], 2),
        block("saved_prompts", "Saved Audio Prompts", [
            "mprc_audio_saved_prompts", "mprc_audio_load_saved",
            "mprc_audio_delete_saved"
        ], 1, false, true, 1),
        block("sound_library", "Story Sound Library", [
            "mprc_audiofx_list", "mprc_audiofx_status", "mprc_audiofx_create",
            "mprc_audiofx_import_pack", "mprc_audiofx_add_file", "mprc_audiofx_play",
            "mprc_audiofx_load", "mprc_audiofx_delete"
        ], 1, false, true, 1)
    ],
    "Story Images": [
        block("intro", "", ["unnamed_qlabel_qlabel#2"], 1),
        block("story_images", "Story Images", [
            "mprc_visual_enabled", "mprc_visual_mode", "mprc_visual_provider",
            "mprc_visual_model", "mprc_visual_size", "mprc_visual_style"
        ], 2),
        block("image_direction", "Image direction", [
            "mprc_visual_character", "mprc_visual_clothing",
            "mprc_visual_environment", "mprc_visual_negative",
            "mprc_visual_appearance_freedom",
            "mprc_visual_continuity", "mprc_visual_scene", "mprc_visual_speaker"
        ], 2),
        block("generation_limits", "Generation limits & display", [
            "mprc_visual_interval", "mprc_visual_cooldown", "mprc_visual_max_auto",
            "mprc_visual_auto_show"
        ], 2, true, true),
        block("actions", "", ["mprc_visual_generate", "mprc_visual_preview"], 2)
    ],
    "Story Health": [
        block("intro", "", ["unnamed_qlabel_qlabel#11"], 1),
        block("health", "Story Health", [
            "mprc_story_status", "mprc_story_first_run", "mprc_story_status_refresh",
            "mprc_story_validate"
        ], 1),
        block("demo_bundle", "Demo, template & bundle", [
            "mprc_story_template", "mprc_story_load_template", "mprc_story_demo",
            "mprc_story_import_bundle", "mprc_story_export_bundle",
            "mprc_story_restore_backup", "mprc_story_reset_only"
        ], 2, true, false),
        block("setup_checks", "Setup Checks", [
            "mprc_story_validation", "mprc_story_test_narrator_voice",
            "mprc_story_test_character_voice", "mprc_story_test_visual",
            "mprc_story_test_audio"
        ], 1, false, true, 1),
        block("voice_routing", "Voice Routing Check", [
            "mprc_story_voice_routes", "mprc_story_preview_next",
            "mprc_story_explain_next", "mprc_story_next_inspector"
        ], 1, false, true, 1),
        block("repair_tools", "Repair tools", [
            "mprc_story_repair_narrator", "mprc_story_repair_voice",
            "mprc_story_repair_audio", "mprc_story_repair_image",
            "mprc_story_repair_memory", "mprc_story_repair_personas",
            "mprc_story_repair_overrides"
        ], 2, true, false),
        block("story_memory", "Story Memory", [
            "mprc_story_pinned_facts", "mprc_story_memory_list",
            "mprc_story_memory_refresh", "mprc_story_memory_save_pins",
            "mprc_story_memory_delete", "mprc_story_memory_reset_character",
            "mprc_story_memory_reset_story"
        ], 1),
        block("attention", "What Needs Attention", [
            "mprc_story_event_log", "mprc_story_clear_log"
        ], 1)
    ],
    "Troubleshooting": [
        block("intro", "", ["unnamed_qlabel_qlabel"], 1),
        block("persona_prompt", "Advanced: persona prompt", [
            "unnamed_qgroupbox_advanced_persona_prompt", "mprc_debug_prompt",
            "unnamed_qpushbutton_copy"
        ], 1, true, true),
        block("image_prompt", "Advanced: image prompt", [
            "unnamed_qgroupbox_advanced_image_prompt", "mprc_debug_visual",
            "unnamed_qpushbutton_copy#2"
        ], 1, true, false),
        block("voice_routing", "Advanced: voice routing", [
            "unnamed_qgroupbox_advanced_voice_routing", "mprc_debug_voice",
            "unnamed_qpushbutton_copy#3"
        ], 1, true, false),
        block("story_state", "Advanced: story state summary", [
            "unnamed_qgroupbox_advanced_story_state_summary", "mprc_debug_state",
            "unnamed_qpushbutton_copy#4"
        ], 1, true, false),
        block("visual_log", "Advanced: Visual Reply request log", [
            "unnamed_qgroupbox_advanced_visual_reply_request_log",
            "mprc_debug_visual_calls", "mprc_debug_visual_calls_copy",
            "mprc_debug_visual_calls_clear"
        ], 1, true, false),
        block("actions", "", ["mprc_debug_clear"], 1)
    ],
    "Status": [
        block("runtime", "Roleplay status", [
            "mprc_enabled_checkbox", "mprc_show_character_checkbox",
            "mprc_ar_mode_checkbox"
        ], 2),
        block("current_character", "Current Character", [
            "mprc_active_persona_combo", "mprc_current_character_view_label",
            "mprc_current_character_view_mode", "mprc_current_character_name"
        ], 2),
        block("quick_actions", "Persona actions", [
            "mprc_quick_change_avatar", "mprc_quick_save_persona",
            "mprc_quick_import_persona", "mprc_quick_export_personas",
            "mprc_quick_duplicate_persona", "mprc_quick_edit_persona"
        ], 2)
    ],
    "Play": [
        block("toolbar", "", [
            "mprc_chat_start_button", "mprc_chat_pause_button",
            "mprc_chat_restart_button", "mprc_chat_clear_button",
            "mprc_chat_float_button", "mprc_chat_story_font_size_spin",
            "mprc_chat_voice_volume_slider", "mprc_chat_voice_volume_popout_button"
        ], 2),
        block("advanced", "Advanced · Structured output, phone & Chromecast", [
            "mprc_chat_play_toolbar_advanced_toggle",
            "mprc_chat_structured_output_checkbox",
            "mprc_chat_structured_output_scope_combo",
            "mprc_chat_instructor_structured_outputs_checkbox",
            "mprc_chat_instructor_ar_turn_checkbox",
            "mprc_chat_export_structured_output_button", "mprc_chat_remote_install_button",
            "mprc_chat_remote_enabled_checkbox", "mprc_chat_remote_regenerate_token_button",
            "mprc_chat_remote_host_input", "mprc_chat_remote_port_spin",
            "mprc_chat_remote_code_spin", "mprc_chat_chromecast_device_combo",
            "mprc_chat_chromecast_refresh_button", "mprc_chat_chromecast_install_button",
            "mprc_chat_chromecast_start_button", "mprc_chat_chromecast_stop_button",
            "mprc_chat_chromecast_status_label"
        ], 2, true, false),
        block("feed", "Story Feed", ["mprc_chat_transcript"], 1),
        block("choices", "Pending choices", ["mprc_chat_next_actions_list"], 1),
        block("composer", "Player Action", [
            "mprc_chat_intent_combo", "mprc_chat_speaker_combo",
            "mprc_chat_use_ar_checkbox", "mprc_chat_visuals_checkbox",
            "mprc_chat_input", "mprc_chat_send_button", "mprc_chat_status_label"
        ], 2),
        block("story_state", "Story State", [
            "mprc_chat_recent_events_list", "mprc_chat_present_characters_list",
            "mprc_chat_scene_state_label"
        ], 1),
        block("director", "Story Director", [
            "mprc_chat_director_pacing_combo", "mprc_chat_director_tone_combo",
            "mprc_chat_director_agency_combo", "mprc_chat_director_choice_mode_combo",
            "mprc_chat_advance_scene_button", "mprc_chat_summarize_button",
            "mprc_chat_repair_button", "unnamed_qlabel_qlabel#28",
            "mprc_chat_story_director_summary"
        ], 2),
        block("engine", "Engine & Story Tools", [
            "unnamed_qlabel_qlabel#23", "unnamed_qlabel_qlabel#24",
            "mprc_chat_spotify_music_summary", "unnamed_qlabel_qlabel#26",
            "mprc_chat_visual_beat_summary", "unnamed_qlabel_qlabel#27",
            "mprc_chat_memory_databank_summary"
        ], 1),
        block("diagnostics", "Diagnostics", [
            "mprc_visual_prompt_debug_text", "mprc_chat_input_legacy",
            "mprc_buffer_race_summary", "mprc_buffer_race_render_bar",
            "mprc_buffer_race_playback_bar"
        ], 1, true, false)
    ]
})

var LABELS = ({
    "mprc_character_image_path": "Picture path",
    "mprc_voice_sample": "Voice sample path",
    "mprc_voice_sample_picker": "Voice files in \\voices",
    "mprc_chat_voice_segments_summary": "Voice segments",
    "mprc_session_mode_note": "",
    "mprc_master_story_list": "Saved story",
    "mprc_master_story_status": "",
    "mprc_master_story_draft": "Editable draft",
    "mprc_story_export_status": "",
    "mprc_audio_intro": "",
    "mprc_audiofx_volume": "Story sound volume",
    "mprc_audio_story_note": "",
    "mprc_audio_examples": "",
    "mprc_audio_saved_prompts": "Saved Audio Prompts",
    "mprc_audiofx_list": "Story Sound Library",
    "mprc_audiofx_status": "",
    "mprc_visual_enabled": "Enable Visual Reply for this persona",
    "mprc_visual_interval": "Every N replies",
    "mprc_visual_cooldown": "Cooldown (seconds)",
    "mprc_visual_max_auto": "Session image maximum (0 = unlimited)",
    "mprc_visual_auto_show": "Auto-show image dock",
    "mprc_story_status": "",
    "mprc_story_template": "Story template",
    "mprc_story_validation": "Setup checks",
    "mprc_story_voice_routes": "Voice routing check",
    "mprc_story_next_inspector": "Request / routing preview",
    "mprc_story_pinned_facts": "Pinned story facts",
    "mprc_story_memory_list": "Recent story memory",
    "mprc_story_event_log": "Notes",
    "mprc_chat_transcript": "",
    "mprc_chat_input": "Player action",
    "mprc_chat_next_actions_list": "",
    "mprc_chat_recent_events_list": "Recent Events",
    "mprc_chat_present_characters_list": "Present Cast",
    "mprc_chat_scene_state_label": "Scene",
    "mprc_chat_story_font_size_spin": "Story Font",
    "mprc_chat_voice_volume_slider": "Voice",
    "mprc_chat_director_pacing_combo": "Pacing",
    "mprc_chat_director_tone_combo": "Tone",
    "mprc_chat_director_agency_combo": "Player agency",
    "mprc_chat_director_choice_mode_combo": "Choice style",
    "mprc_persona_list": "Personas",
    "mprc_active_persona_combo": "Active persona",
    "mprc_current_character_view_label": "",
    "mprc_current_character_view_mode": "Character view",
    "mprc_current_character_name": "Current Character"
})

function sections(available) {
    var source = available || []
    var present = ({})
    var result = []
    var index
    for (index = 0; index < source.length; ++index)
        present[String(source[index])] = true
    for (index = 0; index < SECTION_ORDER.length; ++index) {
        var approved = SECTION_ORDER[index]
        if (present[approved]) {
            result.push(approved)
            delete present[approved]
        }
    }
    for (index = 0; index < source.length; ++index) {
        var extra = String(source[index])
        if (present[extra]) {
            result.push(extra)
            delete present[extra]
        }
    }
    return result
}

function groups(section, controls) {
    var source = controls || []
    var available = ({})
    var sourceOrder = []
    var index
    for (index = 0; index < source.length; ++index) {
        var sourceId = String(source[index].id || source[index].objectName || "")
        if (sourceId && available[sourceId] === undefined) {
            available[sourceId] = true
            sourceOrder.push(sourceId)
        }
    }

    var definitions = GROUPS[String(section)] || []
    var used = ({})
    var result = []
    for (index = 0; index < definitions.length; ++index) {
        var definition = definitions[index]
        var presentIds = []
        for (var idIndex = 0; idIndex < definition.ids.length; ++idIndex) {
            var controlId = definition.ids[idIndex]
            if (available[controlId] && !used[controlId]) {
                presentIds.push(controlId)
                used[controlId] = true
            }
        }
        if (presentIds.length > 0) {
            result.push(block(
                definition.key, definition.title, presentIds,
                definition.columns, definition.fold,
                definition.expanded, definition.span
            ))
        }
    }

    var additional = []
    for (index = 0; index < sourceOrder.length; ++index) {
        if (!used[sourceOrder[index]])
            additional.push(sourceOrder[index])
    }
    if (additional.length > 0)
        result.push(block("additional", "Additional controls", additional, 1))
    return result
}

function label(field) {
    var source = field || ({})
    var controlId = String(source.id || source.objectName || "")
    if (LABELS[controlId] !== undefined)
        return LABELS[controlId]
    if (controlId.indexOf("unnamed_qlabel_") === 0)
        return ""
    if (controlId.indexOf("unnamed_qplaintextedit_") === 0)
        return ""
    return String(source.label || source.objectName || "")
}

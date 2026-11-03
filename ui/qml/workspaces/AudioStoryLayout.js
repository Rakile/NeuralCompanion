.pragma library

// Presentation-only workflow for the frozen Audio Story native contract.
// Runtime values, enabled state, picker metadata, and actions remain owned by
// the bridge. Any control not listed below is appended to Additional controls.

var SECTION_ORDER = [
    "Project", "Audio", "Story", "Review", "Images", "Play / Cast", "Novel"
]

var WORKFLOW_STEPS = [
    {"label": "Project", "section": "Project", "number": "1"},
    {"label": "Sources", "section": "Audio", "number": "2"},
    {"label": "Plan", "section": "Story", "number": "3"},
    {"label": "Review", "section": "Review", "number": "4"},
    {"label": "Images", "section": "Images", "number": "5"},
    {"label": "Play", "section": "Play / Cast", "number": "6"}
]

var SECTION_TITLES = ({
    "Project": "Project & chapters",
    "Audio": "Audio & transcript",
    "Story": "Story planner",
    "Review": "Scene review",
    "Images": "Image style",
    "Play / Cast": "Play & cast",
    "Novel": "Novel workshop"
})

var SECTION_DESCRIPTIONS = ({
    "Project": "Create or open a project, then arrange its chapters.",
    "Audio": "Import source audio, choose a range, and create the transcript.",
    "Story": "Set pacing, continuity, and the planning model before generation.",
    "Review": "Check the current scene and refine what the next image should show.",
    "Images": "Choose the visual direction and image-provider output settings.",
    "Play / Cast": "Listen to the finished story locally or share it to another screen.",
    "Novel": "Turn chat logs or Markdown into an editable long-form story."
})

function block(key, title, description, ids, columns, fold, expanded, span) {
    return {
        "key": key,
        "title": title,
        "description": description || "",
        "ids": ids,
        "columns": columns || 1,
        "fold": Boolean(fold),
        "expanded": expanded !== false,
        "span": span === 1 ? 1 : 2
    }
}

var GROUPS = ({
    "Project": [
        block("projects", "Your projects", "Start a new story or resume one already saved.", [
            "audio_story_project_autosave_label", "audio_story_project_recovery_label",
            "audio_story_project_list", "audio_story_project_new_button",
            "audio_story_project_open_button", "audio_story_project_save_current_button"
        ], 2, false, true, 1),
        block("chapters", "Chapters", "Select a chapter, attach its audio, and set the reading order.", [
            "audio_story_project_chapter_list", "audio_story_project_chapter_status_label",
            "audio_story_project_add_audio_button", "audio_story_project_chapter_rename_button",
            "audio_story_project_chapter_move_up_button", "audio_story_project_chapter_move_down_button",
            "audio_story_project_relink_button"
        ], 2, false, true, 1),
        block("project_maintenance", "Project maintenance", "Recovery and lifecycle tools for the current project.", [
            "audio_story_project_rename_button", "audio_story_project_close_button",
            "audio_story_project_archive_button", "audio_story_project_restore_button",
            "audio_story_project_resume_all_button", "audio_story_project_retry_button"
        ], 2, true, false, 1),
        block("project_delete", "Delete project", "Permanently remove the selected project.", [
            "audio_story_project_delete_button"
        ], 1, true, false, 1)
    ],
    "Audio": [
        block("sources", "1. Source audio", "Import one or more files and arrange them in story order.", [
            "audio_story_intro_label", "audio_story_path_edit", "audio_story_import_button",
            "audio_story_source_list", "audio_story_source_move_up_button",
            "audio_story_source_move_down_button", "audio_story_source_remove_button",
            "audio_story_source_clear_button", "audio_story_source_hint"
        ], 2, false, true, 1),
        block("transcription", "2. Transcribe", "Process the full source or only the selected time range.", [
            "audio_story_transcribe_seconds_slider", "audio_story_transcription_range_label",
            "audio_story_selected_range_checkbox", "audio_story_transcription_start_label",
            "audio_story_transcription_start_spin", "audio_story_transcription_end_label",
            "audio_story_transcription_end_spin", "audio_story_transcribe_button",
            "audio_story_transcription_progress_bar"
        ], 2, false, true, 1),
        block("transcript", "3. Transcript", "Review or copy the text produced from the source audio.", [
            "audio_story_transcription_console", "audio_story_transcription_console_copy_button",
            "audio_story_transcription_console_clear_button"
        ], 2, false, true, 2),
        block("audio_settings", "Playback, quality & presets", "Settings reused when processing this story.", [
            "audio_story_playback_mode_combo", "audio_story_cost_profile_combo",
            "audio_story_settings_preset_combo", "audio_story_settings_preset_save_button",
            "audio_story_settings_preset_load_button", "audio_story_workflow_strip"
        ], 2, true, true, 2)
    ],
    "Story": [
        block("pacing", "Pacing & image cadence", "Control when scenes change and how far generation stays ahead.", [
            "audio_story_image_frequency_slider", "audio_story_image_timing_combo",
            "audio_story_continuity_slider", "audio_story_generate_ahead_slider"
        ], 2, false, true, 1),
        block("planner", "Planner model", "Use the configured language provider to identify visual story beats.", [
            "audio_story_llm_analysis_checkbox", "audio_story_analysis_mode_combo",
            "audio_story_analysis_provider_combo", "audio_story_analysis_model_combo",
            "audio_story_instructor_beats_checkbox", "audio_story_instructor_status_label"
        ], 2, false, true, 1),
        block("story_direction", "Continuity & visual direction", "Apply the recommended continuity and master prompt choices together.", [
            "audio_story_recommended_continuity_button", "audio_story_master_prompt_button",
            "audio_story_master_prompt_mode_combo", "audio_story_xai_image_settings_hint"
        ], 2, false, true, 2),
        block("planner_apply", "Apply planner changes", "Commit or discard the current planner draft.", [
            "audio_story_planner_apply_status_label", "audio_story_planner_cancel_button",
            "audio_story_planner_apply_button"
        ], 2, false, true, 2)
    ],
    "Review": [
        block("scene_source", "Scene source", "Read the selected scene in context before changing its image direction.", [
            "audio_story_scene_status_label", "audio_story_summary_label",
            "audio_story_transcript_edit", "audio_story_pin_location_button",
            "audio_story_force_fresh_button", "audio_story_force_continuation_button"
        ], 2, false, true, 1),
        block("image_focus", "Image focus", "Describe what the generated image must keep in frame.", [
            "audio_story_scene_anchor_edit", "audio_story_scene_anchor_pin_button",
            "audio_story_scene_anchor_refine_button", "audio_story_scene_anchor_apply_button"
        ], 2, false, true, 1),
        block("avoid", "Avoid in the image", "Keep unwanted details out of this scene's prompt.", [
            "audio_story_scene_negative_prompt_edit", "audio_story_negative_prompt_anchor_button",
            "audio_story_scene_negative_prompt_refine_button",
            "audio_story_scene_negative_prompt_apply_button", "audio_story_scene_hint"
        ], 2, false, true, 2)
    ],
    "Images": [
        block("realistic", "Realistic", "Photographic visual direction.", [
            "unnamed_qpushbutton_realistic", "unnamed_qlineedit_qlineedit", "unnamed_qpushbutton_refine"
        ], 1, false, true, 1),
        block("cartoon", "Cartoon", "Illustrated visual direction.", [
            "unnamed_qpushbutton_cartoon", "unnamed_qlineedit_qlineedit#2", "unnamed_qpushbutton_refine#2"
        ], 1, false, true, 1),
        block("retro", "Retro", "Vintage visual direction.", [
            "unnamed_qpushbutton_retro", "unnamed_qlineedit_qlineedit#3", "unnamed_qpushbutton_refine#3"
        ], 1, false, true, 1),
        block("cyberpunk", "Cyberpunk", "Neon science-fiction visual direction.", [
            "unnamed_qpushbutton_cyberpunk", "unnamed_qlineedit_qlineedit#4", "unnamed_qpushbutton_refine#4"
        ], 1, false, true, 1),
        block("image_output", "Provider output", "Size and response options sent to the active image provider.", [
            "audio_story_xai_aspect_ratio_combo", "audio_story_xai_resolution_combo",
            "audio_story_xai_response_format_label", "audio_story_xai_response_format_combo",
            "audio_story_xai_n_spin"
        ], 2, true, true, 1),
        block("image_apply", "Live style & safety", "Preview style changes live or apply the complete draft when ready.", [
            "audio_story_style_live_checkbox", "audio_story_prompt_safety_cap_spin",
            "audio_story_style_apply_status_label", "audio_story_style_cancel_button",
            "audio_story_style_apply_button"
        ], 2, false, true, 1)
    ],
    "Play / Cast": [
        block("player", "Story player", "Listen from the current position and monitor playback state.", [
            "audio_story_status_label", "audio_story_position_slider", "audio_story_play_button",
            "audio_story_pause_button", "audio_story_stop_button"
        ], 3, false, true, 2),
        block("voice_buffer", "Voice rendering", "Tune the initial buffer and how far speech renders ahead.", [
            "audio_story_tts_state_label", "audio_story_tts_startup_buffer_spin",
            "audio_story_tts_render_ahead_spin", "audio_story_tts_retry_button",
            "audio_story_tts_clear_cache_button"
        ], 2, false, true, 1),
        block("cast", "Cast to a screen", "Discover a Chromecast and send the visual story to it.", [
            "audio_story_cast_device_combo", "audio_story_cast_refresh_button",
            "audio_story_cast_button", "audio_story_cast_stop_button",
            "audio_story_cast_prompt_checkbox", "audio_story_cast_status_label",
            "audio_story_cast_install_button"
        ], 2, false, true, 1),
        block("lan", "LAN sharing", "Publish the visual stream for other devices on the local network.", [
            "audio_story_stream_enabled_checkbox", "audio_story_stream_port_spin"
        ], 2, true, false, 2)
    ],
    "Novel": [
        block("novel_progress", "Novel workshop", "Follow the stages from source import through narration.", [
            "unnamed_qlabel_qlabel", "audio_story_novel_status_label",
            "unnamed_qprogressbar_qprogressbar", "unnamed_qpushbutton_cancel"
        ], 2, false, true, 2),
        block("novel_source", "1. Choose source", "Start a project from a chat export or a Markdown document.", [
            "unnamed_qpushbutton_new_novel_project", "unnamed_qpushbutton_choose_chatlog_json",
            "unnamed_qpushbutton_choose_markdown", "unnamed_qlineedit_qlineedit#5"
        ], 2, false, true, 1),
        block("novel_mapping", "2. Map chat fields", "Tell the importer where to find each part of a chat message.", [
            "unnamed_qlineedit_message_collection", "unnamed_qlineedit_speaker_field",
            "unnamed_qlineedit_text_field", "unnamed_qlineedit_role_field",
            "unnamed_qlineedit_timestamp_field", "unnamed_qlineedit_thread_field",
            "unnamed_qpushbutton_inspect_with_this_mapping",
            "unnamed_qpushbutton_import_confirmed_source"
        ], 2, true, true, 1),
        block("adaptation", "3. Adaptation", "Choose how faithfully the source becomes a novel.", [
            "unnamed_qcombobox_adaptation_style", "unnamed_qplaintextedit_novel_instructions",
            "unnamed_qgroupbox_advanced_prompt_additions", "unnamed_qpushbutton_reset_to_defaults"
        ], 1, false, true, 2),
        block("story_map", "4. Story map & outline", "Build the structure, then approve it before prose generation.", [
            "unnamed_qplaintextedit_story_map", "unnamed_qplaintextedit_outline",
            "unnamed_qpushbutton_build_story_map", "unnamed_qpushbutton_build_outline",
            "unnamed_qpushbutton_save_outline", "unnamed_qpushbutton_approve_and_generate"
        ], 2, false, true, 2),
        block("outline_editor", "5. Outline editor", "Reorder, split, or merge the selected outline entry.", [
            "audio_story_novel_outline_tree", "unnamed_qpushbutton_move_up",
            "unnamed_qpushbutton_move_down", "unnamed_qpushbutton_split_selected",
            "unnamed_qpushbutton_merge_with_next"
        ], 2, false, true, 1),
        block("novel_output", "6. Scene plans & prose", "Review generated scene plans and assemble the finished novel.", [
            "unnamed_qplaintextedit_scene_plans", "unnamed_qplaintextedit_prose",
            "unnamed_qpushbutton_assemble_novel", "unnamed_qpushbutton_assemble_partial_preview",
            "unnamed_qpushbutton_retry_selected_scene",
            "unnamed_qpushbutton_narrate_selected_chapter",
            "unnamed_qpushbutton_use_in_story_images"
        ], 2, false, true, 1)
    ]
})

var LABELS = ({
    "audio_story_project_autosave_label": "",
    "audio_story_project_recovery_label": "",
    "audio_story_project_chapter_status_label": "",
    "audio_story_intro_label": "",
    "audio_story_path_edit": "Source path",
    "audio_story_source_list": "Imported sources",
    "audio_story_settings_preset_combo": "Preset",
    "audio_story_transcribe_seconds_slider": "Transcription sample (seconds)",
    "audio_story_transcription_range_label": "",
    "audio_story_transcription_start_label": "",
    "audio_story_transcription_start_spin": "Start time",
    "audio_story_transcription_end_label": "",
    "audio_story_transcription_end_spin": "End time",
    "audio_story_transcription_progress_bar": "Progress",
    "audio_story_transcription_console": "Transcript",
    "audio_story_source_hint": "",
    "audio_story_workflow_strip": "",
    "audio_story_project_list": "Projects",
    "audio_story_project_chapter_list": "Chapters",
    "audio_story_instructor_status_label": "",
    "audio_story_planner_apply_status_label": "",
    "audio_story_xai_image_settings_hint": "",
    "audio_story_image_frequency_slider": "Image frequency",
    "audio_story_continuity_slider": "Scene continuity",
    "audio_story_generate_ahead_slider": "Generate ahead",
    "audio_story_master_prompt_mode_combo": "Style anchor mode",
    "audio_story_scene_status_label": "",
    "audio_story_summary_label": "Scene summary",
    "audio_story_transcript_edit": "Scene transcript",
    "audio_story_scene_anchor_edit": "Image focus",
    "audio_story_scene_negative_prompt_edit": "Avoid",
    "audio_story_scene_hint": "",
    "unnamed_qpushbutton_realistic": "Use Realistic",
    "unnamed_qlineedit_qlineedit": "Realistic prompt",
    "unnamed_qpushbutton_refine": "Refine Realistic",
    "unnamed_qpushbutton_cartoon": "Use Cartoon",
    "unnamed_qlineedit_qlineedit#2": "Cartoon prompt",
    "unnamed_qpushbutton_refine#2": "Refine Cartoon",
    "unnamed_qpushbutton_retro": "Use Retro",
    "unnamed_qlineedit_qlineedit#3": "Retro prompt",
    "unnamed_qpushbutton_refine#3": "Refine Retro",
    "unnamed_qpushbutton_cyberpunk": "Use Cyberpunk",
    "unnamed_qlineedit_qlineedit#4": "Cyberpunk prompt",
    "unnamed_qpushbutton_refine#4": "Refine Cyberpunk",
    "audio_story_xai_response_format_label": "",
    "audio_story_xai_aspect_ratio_combo": "Aspect ratio",
    "audio_story_xai_resolution_combo": "Resolution",
    "audio_story_xai_response_format_combo": "Response format",
    "audio_story_xai_n_spin": "Images per request",
    "audio_story_style_apply_status_label": "",
    "audio_story_status_label": "",
    "audio_story_tts_state_label": "Voice state",
    "audio_story_position_slider": "Position",
    "audio_story_stream_port_spin": "Port",
    "audio_story_cast_device_combo": "Cast device",
    "audio_story_cast_status_label": "",
    "unnamed_qlabel_qlabel": "",
    "audio_story_novel_status_label": "",
    "unnamed_qprogressbar_qprogressbar": "Novel progress",
    "unnamed_qpushbutton_cancel": "Cancel current task",
    "unnamed_qpushbutton_new_novel_project": "New novel project",
    "unnamed_qpushbutton_choose_chatlog_json": "Choose chatlog JSON",
    "unnamed_qpushbutton_choose_markdown": "Choose Markdown",
    "unnamed_qlineedit_qlineedit#5": "Source file",
    "unnamed_qlineedit_message_collection": "Message collection",
    "unnamed_qlineedit_speaker_field": "Speaker field",
    "unnamed_qlineedit_text_field": "Text field",
    "unnamed_qlineedit_role_field": "Role field",
    "unnamed_qlineedit_timestamp_field": "Timestamp field",
    "unnamed_qlineedit_thread_field": "Thread field",
    "unnamed_qcombobox_adaptation_style": "Adaptation style",
    "unnamed_qplaintextedit_novel_instructions": "Novel instructions",
    "unnamed_qgroupbox_advanced_prompt_additions": "Advanced prompt additions",
    "unnamed_qplaintextedit_story_map": "Story map",
    "unnamed_qplaintextedit_outline": "Outline",
    "unnamed_qplaintextedit_scene_plans": "Scene plans",
    "unnamed_qplaintextedit_prose": "Generated prose",
    "audio_story_novel_outline_tree": "Outline structure"
})

var DISPLAY_TEXT = ({
    "audio_story_intro_label": "Import a story or audiobook, turn it into scenes, generate matching images, then play or cast the result."
})

function workflowSteps() { return WORKFLOW_STEPS }
function sectionTitle(section) { return SECTION_TITLES[String(section)] || String(section) }
function sectionDescription(section) { return SECTION_DESCRIPTIONS[String(section)] || "" }

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
                definition.key, definition.title, definition.description,
                presentIds, definition.columns, definition.fold,
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
        result.push(block("additional", "Additional controls", "Controls added by the current runtime.", additional, 1, true, false, 2))
    return result
}

function label(field) {
    var source = field || ({})
    var controlId = String(source.id || source.objectName || "")
    if (LABELS[controlId] !== undefined)
        return LABELS[controlId]
    return String(source.label || source.objectName || "")
}

function value(field) {
    var source = field || ({})
    var controlId = String(source.id || source.objectName || "")
    if (DISPLAY_TEXT[controlId] !== undefined)
        return DISPLAY_TEXT[controlId]
    return source.value
}

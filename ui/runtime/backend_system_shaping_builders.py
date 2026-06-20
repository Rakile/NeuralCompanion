from PySide6 import QtCore, QtGui, QtWidgets

from ui.runtime.shell_session_config import _ui_shell_combo_select_label, _ui_shell_combo_set_items
from ui.runtime.shell_status_layout import _ui_shell_audio_device_labels
from ui.runtime.shell_addon_services import addon_id_for_service, addon_id_for_ui_role
from ui.runtime.addon_disabled_placeholders import (
    ensure_musetalk_legacy_placeholders,
    ensure_vam_legacy_placeholders,
    ensure_visual_reply_legacy_placeholders,
)
from ui.shell_specs import UI_SHELL_DEFAULT_CHUNKING_VALUES
from ui.widgets.basic import CollapsibleSection, ContextTokenStepper, DecimalStepper, LabeledSlider, NoWheelComboBox, NoWheelSpinBox, NoWheelTabWidget


from ui.runtime.engine_access import engine_module as _engine


def _update_runtime_config(key, value):
    from ui.runtime.engine_access import update_runtime_config

    return update_runtime_config(key, value)


def _default_chat_provider_id():
    from core import chat_providers

    return chat_providers.DEFAULT_PROVIDER_ID


SYSTEM_SHAPING_TOOLTIPS = {
    "engine_combo": "Avatar output provider. Use None for voice/chat only, or choose MuseTalk/VSeeFace/VaM when that addon/runtime is configured.",
    "input_mode_combo": "How user turns enter the session. Voice Activation listens after startup; Push-to-Talk only listens while the hotkey/button is held; Text Only disables microphone STT.",
    "input_role_combo": "Chat role used for live input. User Message is normal; System/Assistant are advanced prompt-routing modes.",
    "stream_mode_combo": "When On, NC streams the model reply and starts chunked TTS sooner. When Off, NC waits for the full reply first.",
    "musetalk_loop_fade_spin": "MuseTalk preview crossfade duration when switching avatar/emotion frames. 0 disables the fade; higher values smooth changes but can delay visible updates.",
    "musetalk_use_frame_cache_checkbox": "Use/create MuseTalk NumPy frame caches for faster avatar startup. Disable to save disk space and always read PNG frames.",
    "musetalk_avatar_pack_combo": "Prepared MuseTalk avatar pack and variant used for rendering visual speech.",
    "btn_musetalk_avatar_pack_refresh": "Rescan installed MuseTalk avatar packs under avatar_packs/.",
    "scenic_pack_combo": "Portable Scenic Pack used by the Scenic avatar engine to map tags to still images.",
    "btn_scenic_pack_refresh": "Rescan ScenicPacks/ for portable Scenic Pack folders.",
    "preset_combo": "Saved companion preset. Presets store persona/runtime choices such as model, voice, avatar, and generation settings.",
    "btn_preset_refresh": "Reload the preset list from disk.",
}

CHAT_TAB_TOOLTIPS = {
    "chat_provider_combo": "Active chat provider used for assistant replies. Provider tabs can be inspected without changing this active selection.",
    "model_combo": "Model selected for the current chat provider. Use Refresh after starting or changing the provider server.",
    "btn_model_refresh": "Refresh the model list for the selected chat provider.",
    "model_requires_vision_checkbox": "Only list or prefer models that can process images when the provider exposes that capability.",
    "allow_proactive_checkbox": "Allow the assistant to speak after a silence window instead of waiting forever for the next user turn.",
    "require_first_user_checkbox": "Prevent proactive replies until the user has sent at least one message in the session.",
    "listen_idle_window_spin": "How long the microphone/input loop waits before considering the session idle.",
    "proactive_delay_spin": "How long the assistant waits after idle detection before sending a proactive reply.",
    "chat_context_window_spin": "How many recent chat messages are sent to the model for normal reply context.",
    "stored_chat_history_limit_spin": "How many chat messages are kept when saving context. Use 0 to save the full conversation history.",
    "chat_overflow_policy_combo": "What NC should do when the active chat context grows beyond the context window sent to the model.",
    "spellcheck_enabled_checkbox": "Enable red underline spellcheck in the normal typed chat input and Chat Edit Mode when PyEnchant dictionaries are available.",
    "spellcheck_language_combo": "Dictionary language used for chat spellcheck. The list contains dictionaries visible to PyEnchant in the active NC environment.",
    "btn_install_spellcheck_dependency": "Install only the PyEnchant package into the active NC Python environment when spellcheck is unavailable after an update.",
    "spellcheck_dependency_hint": "Shows whether the optional PyEnchant spellcheck package and dictionaries are available in the active NC Python environment.",
    "long_term_memory_enabled_checkbox": "Maintain a compact Continuity Memory summary for this saved chat context.",
    "long_term_memory_update_on_save_checkbox": "Automatically summarize continuity after the configured number of new saved-chat messages has accumulated.",
    "continuity_memory_auto_turns_spin": "Number of new chat messages required before automatic Continuity Memory summarization runs. Save Chat Context flushes all pending messages immediately, even one.",
    "long_term_memory_inject_checkbox": "Include the Continuity Memory summary in normal model requests so the assistant can remember older context.",
    "long_term_memory_max_chars_spin": "Maximum character budget for the Continuity Memory summary.",
    "btn_review_long_term_memory": "Open the current Continuity Memory summary for inspection.",
    "btn_batch_update_long_term_memory": "Summarize the latest N messages manually. Useful when importing or catching up an older long chat.",
    "btn_forget_long_term_memory": "Clear the Continuity Memory summary for the current chat context.",
    "btn_search_long_term_memory_archive": "Search extracted memory records and raw archived chat chunks without injecting them into chat.",
    "btn_review_long_term_memory_archive": "Review the currently stored Long-Term Memory archive records.",
    "long_term_memory_archive_hint": "Shows Long-Term Memory archive record counts and storage location.",
    "long_term_memory_retrieval_enabled_checkbox": "Allow NC to retrieve relevant Long-Term Memory archive items and inject a compact recall block into chat requests.",
    "long_term_memory_retrieval_max_items_spin": "Maximum number of Long-Term Memory archive matches injected into a chat request.",
    "long_term_memory_archive_batch_turns_spin": "Number of new chat messages required before automatic Long-Term Memory archive storage runs. Save Chat Context archives all pending messages immediately, even one.",
    "long_term_memory_embedding_enabled_checkbox": "Use LM Studio embeddings for semantic Long-Term Memory archive retrieval. Keyword search remains available as fallback.",
    "long_term_memory_embedding_model_edit": "Embedding model served by LM Studio. Use Refresh after starting or changing the LM Studio embedding server.",
    "btn_long_term_memory_embedding_model_refresh": "Refresh LM Studio embedding models.",
    "long_term_memory_embedding_base_url_edit": "OpenAI-compatible LM Studio base URL for embeddings, usually http://127.0.0.1:1234/v1.",
    "long_term_memory_embedding_context_length_spin": "Context length NC will request when loading the LM Studio embedding model. This is stored with the chat session and used as part of the embedding index identity.",
    "btn_save_chat_session": "Save changes to the currently loaded/saved chat context file.",
    "btn_save_chat_session_as": "Choose a new chat context file and save the current conversation there.",
    "btn_load_chat_session": "Load a saved chat context file into the current session.",
    "btn_reset_chat_session": "Clear the current in-memory chat history and start a fresh unsaved chat.",
    "chat_session_hint": "Explains the current conversation-flow settings.",
    "long_term_memory_hint": "Shows Continuity Memory status, summarized message counts, and auto-summary readiness.",
    "limit_response_checkbox": "Enable a hard maximum response-token cap for providers that support it.",
    "max_response_tokens_spin": "Maximum response tokens used when response length limiting is enabled.",
    "chat_font_size_combo": "Display font size for the chat transcript.",
    "system_prompt_text": "Main system prompt sent to the chat model.",
}


def _set_tooltip(widget, text):
    if widget is not None and hasattr(widget, "setToolTip"):
        widget.setToolTip(str(text or "").strip())


class BackendSystemShapingPanelMixin:
    """Build the backend System Shaping and Workspace panels."""

class BackendSystemShapingBuilderMixin:
    def _chat_tab_tooltip_map(self):
        return dict(CHAT_TAB_TOOLTIPS)

    def _apply_chat_tab_tooltips(self):
        for object_name, tooltip in self._chat_tab_tooltip_map().items():
            widget = getattr(self, object_name, None)
            _set_tooltip(widget, tooltip)

    def _invoke_initialized_addon_capability(self, addon_id, capability, payload=None, default=None):
        """Invoke an addon capability through the initialized addon manager."""
        manager = getattr(self, "_addon_manager", None)
        if manager is None:
            return default
        try:
            result = manager.invoke_addon_capability(str(addon_id), str(capability), dict(payload or {}))
            return default if result is None else result
        except Exception:
            return default

    def _invoke_avatar_legacy_capability(self, provider_id, capability, payload=None, default=None):
        provider = str(provider_id or "").strip().lower()
        result = self._invoke_addon_service_capability(
            "avatar_provider_registry",
            capability,
            payload,
            default=None,
            provider_id=provider,
        )
        if result is not None:
            return result
        addon_id = addon_id_for_service("avatar_provider_registry", provider_id=provider)
        if not addon_id:
            return default
        return self._invoke_initialized_addon_capability(addon_id, capability, payload, default=default)

    def _invoke_visual_reply_capability(self, capability, payload=None, default=None):
        result = self._invoke_addon_capability(
            self._addon_id_for_ui_role("visual_reply", fallback=addon_id_for_ui_role("visual_reply")),
            capability,
            payload,
            default=None,
        )
        if result is not None:
            return result
        return self._invoke_initialized_addon_capability(
            addon_id_for_ui_role("visual_reply"),
            capability,
            payload,
            default=default,
        )

    def _build_runtime_shell_tab(self):
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignLeft)
        form.addRow("Avatar Engine", self.engine_combo)
        form.addRow("Input Mode", self.input_mode_combo)
        form.addRow("Input Role", self.input_role_combo)
        form.addRow("Stream Mode", self.stream_mode_combo)
        self.musetalk_vram_label = QtWidgets.QLabel("MuseTalk VRAM")
        form.addRow(self.musetalk_vram_label, self.musetalk_vram_combo)
        self.musetalk_loop_fade_label = QtWidgets.QLabel("Loop Fade (ms)")
        _set_tooltip(self.musetalk_loop_fade_label, SYSTEM_SHAPING_TOOLTIPS["musetalk_loop_fade_spin"])
        form.addRow(self.musetalk_loop_fade_label, self._wrap_compact_form_field(self.musetalk_loop_fade_spin))
        self.musetalk_frame_cache_label = QtWidgets.QLabel("Frame Cache")
        _set_tooltip(self.musetalk_frame_cache_label, SYSTEM_SHAPING_TOOLTIPS["musetalk_use_frame_cache_checkbox"])
        form.addRow(self.musetalk_frame_cache_label, self.musetalk_use_frame_cache_checkbox)
        self.musetalk_avatar_label = QtWidgets.QLabel("MuseTalk Avatar")
        _set_tooltip(self.musetalk_avatar_label, SYSTEM_SHAPING_TOOLTIPS["musetalk_avatar_pack_combo"])
        form.addRow(self.musetalk_avatar_label, self.musetalk_avatar_pack_row_widget)
        if hasattr(self, "scenic_pack_row_widget"):
            self.scenic_pack_label = QtWidgets.QLabel("Scenic Pack")
            _set_tooltip(self.scenic_pack_label, SYSTEM_SHAPING_TOOLTIPS["scenic_pack_combo"])
            form.addRow(self.scenic_pack_label, self.scenic_pack_row_widget)
        form.addRow("Preset", self.preset_row_widget if hasattr(self, "preset_row_widget") else self.preset_combo)
        layout.addLayout(form)
        self._refresh_musetalk_vram_visibility()
        layout.addWidget(self._build_chat_runtime_card())
        layout.addWidget(self._build_stt_runtime_card())
        layout.addWidget(self._build_tts_runtime_card())
        visual_reply_card = self._build_visual_reply_runtime_card()
        if visual_reply_card is not None:
            layout.addWidget(visual_reply_card)

        preset_buttons = QtWidgets.QHBoxLayout()
        for label, object_name, handler in [
            ("Load", "btn_preset_load", self.load_preset),
            ("Save", "btn_preset_save", self.save_current_preset),
            ("Save As", "btn_preset_save_as", self.save_preset_dialog),
            ("Delete", "btn_preset_delete", self.delete_current_preset),
        ]:
            button = QtWidgets.QPushButton(label)
            button.setObjectName(object_name)
            button.clicked.connect(handler)
            if object_name == "btn_preset_load":
                self.btn_preset_load = button
                self._refresh_preset_load_button_state()
            elif object_name == "btn_preset_save":
                self.btn_preset_save = button
            elif object_name == "btn_preset_save_as":
                self.btn_preset_save_as = button
            preset_buttons.addWidget(button)
        layout.addLayout(preset_buttons)

        self.input_mode_hint = QtWidgets.QLabel("Push-to-Talk hotkey: Right Ctrl. Text Only disables microphone STT.")
        self.input_mode_hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        layout.addWidget(self.input_mode_hint)

        utility_row = QtWidgets.QHBoxLayout()
        utility_row.setSpacing(8)
        self.btn_push_to_talk = QtWidgets.QPushButton("Hold To Talk")
        self.btn_push_to_talk.setObjectName("btn_push_to_talk")
        self.btn_push_to_talk.pressed.connect(lambda: _engine().set_push_to_talk_hold(True))
        self.btn_push_to_talk.released.connect(lambda: _engine().set_push_to_talk_hold(False))
        self.btn_push_to_talk.setEnabled(False)
        musetalk_buttons = self._invoke_avatar_legacy_capability(
            "musetalk",
            "legacy.build_utility_buttons",
            {"backend": self},
            default=None,
        )
        for button in list(musetalk_buttons or []):
            utility_row.addWidget(button)
        visual_reply_button = self._invoke_visual_reply_capability(
            "legacy.build_utility_button",
            {"backend": self},
            default=None,
        )
        if visual_reply_button is not None:
            utility_row.addWidget(visual_reply_button)
        utility_row.addWidget(self.btn_push_to_talk)
        layout.addLayout(utility_row)

        self.performance_guidance_toggle = QtWidgets.QPushButton("Show Performance Guidance")
        self.performance_guidance_toggle.setObjectName("btn_toggle_performance_guidance")
        self.performance_guidance_toggle.setCheckable(True)
        self.performance_guidance_toggle.toggled.connect(self._toggle_performance_guidance)
        layout.addWidget(self.performance_guidance_toggle)

        self.guidance_box = QtWidgets.QGroupBox("Performance Guidance")
        guidance_layout = QtWidgets.QVBoxLayout(self.guidance_box)
        guidance_layout.setContentsMargins(12, 14, 12, 12)
        guidance_layout.setSpacing(8)

        self.stream_hint_label = QtWidgets.QLabel("Chatterbox sounds more expressive; PocketTTS may start faster.")
        self.stream_hint_label.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        self.stream_hint_label.setWordWrap(True)
        guidance_layout.addWidget(self.stream_hint_label)

        self.musetalk_vram_hint = QtWidgets.QLabel(
            "Quality keeps Whisper on GPU and larger batches; lower VRAM modes trade speed/quality for memory."
        )
        self.musetalk_vram_hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        self.musetalk_vram_hint.setWordWrap(True)
        guidance_layout.addWidget(self.musetalk_vram_hint)

        context_row = QtWidgets.QHBoxLayout()
        context_row.setSpacing(8)
        context_label = QtWidgets.QLabel("Check context:")
        context_label.setStyleSheet("color: #9fb3c8; font-size: 11px; font-weight: 600;")
        self.model_context_input = ContextTokenStepper()
        self.model_context_input.setObjectName("model_context_input")
        self.model_context_input.setRange(512, 131072)
        self.model_context_input.setSingleStep(512)
        self.model_context_input.setAccelerated(True)
        self.model_context_input.setValue(8192)
        self.model_context_input.valueChanged.connect(self.on_model_context_input_changed)
        self.model_context_input.setMinimumWidth(132)
        context_suffix = QtWidgets.QLabel("tokens")
        context_suffix.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        context_row.addWidget(context_label)
        context_row.addWidget(self.model_context_input, 0)
        context_row.addWidget(context_suffix)
        context_row.addStretch(1)
        guidance_layout.addLayout(context_row)

        self.model_budget_label = QtWidgets.QLabel("Model advisor: checking hardware budget...")
        self.model_budget_label.setObjectName("model_budget_label")
        self.model_budget_label.setWordWrap(True)
        self.model_budget_label.setTextFormat(QtCore.Qt.RichText)
        self.model_budget_label.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        guidance_layout.addWidget(self.model_budget_label)

        self.guidance_box.setVisible(False)
        layout.addWidget(self.guidance_box)
        layout.addStretch(1)
        return tab

    def _build_visual_reply_settings_tab(self):
        tab = self._invoke_visual_reply_capability(
            "legacy.build_settings_tab",
            {"backend": self},
            default=None,
        )
        if tab is not None:
            return tab
        fallback = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(fallback)
        layout.addWidget(QtWidgets.QLabel("Visual Reply addon is not available."))
        layout.addStretch(1)
        return fallback

    def _build_visual_reply_runtime_card(self):
        settings_tab = self._build_visual_reply_settings_tab()
        if settings_tab is None:
            return None
        self.visual_reply_runtime_box = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(self.visual_reply_runtime_box)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        layout.addWidget(settings_tab)
        self.visual_reply_runtime_section = CollapsibleSection(
            "Visual Reply Runtime",
            self.visual_reply_runtime_box,
            expanded=True,
        )
        self.visual_reply_runtime_section.toggle_button.toggled.connect(lambda _checked: self._on_runtime_section_toggled())
        try:
            self._refresh_visual_reply_hint()
        except Exception:
            pass
        return self.visual_reply_runtime_section

    def _build_ai_presence_runtime_card(self):
        runtime_config = _engine().RUNTIME_CONFIG
        self.ai_presence_runtime_box = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(self.ai_presence_runtime_box)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.ai_presence_enabled_checkbox = QtWidgets.QCheckBox("Enable AI Presence Mode")
        self.ai_presence_enabled_checkbox.setObjectName("ai_presence_enabled_checkbox")
        self.ai_presence_enabled_checkbox.setChecked(bool(runtime_config.get("ai_presence_enabled", False)))
        self.ai_presence_enabled_checkbox.setToolTip("Show a native Qt Quick fullscreen presence animation while the AI is thinking or speaking.")
        self.ai_presence_enabled_checkbox.toggled.connect(self.on_ai_presence_enabled_changed)

        self.ai_presence_display_mode_combo = NoWheelComboBox()
        self.ai_presence_display_mode_combo.setObjectName("ai_presence_display_mode_combo")
        self.ai_presence_display_mode_combo.setToolTip("Choose whether AI Presence is off, fullscreen, floating, or both.")
        for label, value in [
            ("Off", "off"),
            ("Fullscreen", "fullscreen"),
            ("Floating Window", "floating"),
            ("Both", "both"),
        ]:
            self.ai_presence_display_mode_combo.addItem(label, value)
        display_mode = str(runtime_config.get("ai_presence_display_mode", "fullscreen") or "fullscreen").strip().lower()
        if display_mode not in {"off", "fullscreen", "floating", "both"}:
            display_mode = "fullscreen"
        for index in range(self.ai_presence_display_mode_combo.count()):
            if str(self.ai_presence_display_mode_combo.itemData(index) or "") == display_mode:
                self.ai_presence_display_mode_combo.setCurrentIndex(index)
                break
        self.ai_presence_display_mode_combo.currentIndexChanged.connect(lambda _index: self.on_ai_presence_display_mode_changed(self.ai_presence_display_mode_combo.currentData()))

        self.ai_presence_visual_style_combo = NoWheelComboBox()
        self.ai_presence_visual_style_combo.setObjectName("ai_presence_visual_style_combo")
        self.ai_presence_visual_style_combo.setToolTip("Select the AI Presence animation style.")
        for label, value in [
            ("Neural Network Pulse", "neural_network_pulse"),
        ]:
            self.ai_presence_visual_style_combo.addItem(label, value)
        visual_style = str(runtime_config.get("ai_presence_visual_style", "neural_network_pulse") or "neural_network_pulse").strip().lower()
        for index in range(self.ai_presence_visual_style_combo.count()):
            if str(self.ai_presence_visual_style_combo.itemData(index) or "") == visual_style:
                self.ai_presence_visual_style_combo.setCurrentIndex(index)
                break
        self.ai_presence_visual_style_combo.currentIndexChanged.connect(lambda _index: self.on_ai_presence_visual_style_changed(self.ai_presence_visual_style_combo.currentData()))

        self.ai_presence_fullscreen_checkbox = QtWidgets.QCheckBox("Fullscreen overlay")
        self.ai_presence_fullscreen_checkbox.setObjectName("ai_presence_fullscreen_checkbox")
        self.ai_presence_fullscreen_checkbox.setChecked(bool(runtime_config.get("ai_presence_fullscreen", True)))
        self.ai_presence_fullscreen_checkbox.setToolTip("Cover the active screen during thinking and speaking. Disable to cover only the NC window.")
        self.ai_presence_fullscreen_checkbox.toggled.connect(lambda checked: self.on_ai_presence_setting_changed("ai_presence_fullscreen", bool(checked)))

        self.ai_presence_reduced_effects_checkbox = QtWidgets.QCheckBox("Reduced effects")
        self.ai_presence_reduced_effects_checkbox.setObjectName("ai_presence_reduced_effects_checkbox")
        self.ai_presence_reduced_effects_checkbox.setChecked(bool(runtime_config.get("ai_presence_reduced_effects", False)))
        self.ai_presence_reduced_effects_checkbox.setToolTip("Use fewer particles and slower animation updates.")
        self.ai_presence_reduced_effects_checkbox.toggled.connect(lambda checked: self.on_ai_presence_setting_changed("ai_presence_reduced_effects", bool(checked)))

        self.ai_presence_preview_button = QtWidgets.QPushButton("Show Fullscreen")
        self.ai_presence_preview_button.setObjectName("ai_presence_preview_button")
        self.ai_presence_preview_button.setToolTip("Show the AI Presence fullscreen overlay now. Shortcut: Ctrl+Alt+P.")
        self.ai_presence_preview_button.clicked.connect(self.on_ai_presence_preview_requested)

        self.ai_presence_floating_button = QtWidgets.QPushButton("Show Floating")
        self.ai_presence_floating_button.setObjectName("ai_presence_floating_button")
        self.ai_presence_floating_button.setToolTip("Open the resizable floating AI Presence window.")
        self.ai_presence_floating_button.clicked.connect(self.on_ai_presence_show_floating_requested)

        self.ai_presence_floating_always_on_top_checkbox = QtWidgets.QCheckBox("Floating always on top")
        self.ai_presence_floating_always_on_top_checkbox.setObjectName("ai_presence_floating_always_on_top_checkbox")
        self.ai_presence_floating_always_on_top_checkbox.setChecked(bool(runtime_config.get("ai_presence_floating_always_on_top", True)))
        self.ai_presence_floating_always_on_top_checkbox.setToolTip("Keep the floating presence window above other windows.")
        self.ai_presence_floating_always_on_top_checkbox.toggled.connect(lambda checked: self.on_ai_presence_setting_changed("ai_presence_floating_always_on_top", bool(checked)))

        self.ai_presence_remember_floating_geometry_checkbox = QtWidgets.QCheckBox("Remember floating size")
        self.ai_presence_remember_floating_geometry_checkbox.setObjectName("ai_presence_remember_floating_geometry_checkbox")
        self.ai_presence_remember_floating_geometry_checkbox.setChecked(bool(runtime_config.get("ai_presence_remember_floating_geometry", True)))
        self.ai_presence_remember_floating_geometry_checkbox.setToolTip("Remember the floating window position and size.")
        self.ai_presence_remember_floating_geometry_checkbox.toggled.connect(lambda checked: self.on_ai_presence_setting_changed("ai_presence_remember_floating_geometry", bool(checked)))

        self.ai_presence_transparent_background_checkbox = QtWidgets.QCheckBox("Transparent background")
        self.ai_presence_transparent_background_checkbox.setObjectName("ai_presence_transparent_background_checkbox")
        self.ai_presence_transparent_background_checkbox.setChecked(bool(runtime_config.get("ai_presence_transparent_background", False)))
        self.ai_presence_transparent_background_checkbox.setToolTip("Make AI Presence render without a painted background. The floating window stays frameless either way.")
        self.ai_presence_transparent_background_checkbox.toggled.connect(lambda checked: self.on_ai_presence_setting_changed("ai_presence_transparent_background", bool(checked)))

        self.ai_presence_shaders_enabled_checkbox = QtWidgets.QCheckBox("Soft glow")
        self.ai_presence_shaders_enabled_checkbox.setObjectName("ai_presence_shaders_enabled_checkbox")
        self.ai_presence_shaders_enabled_checkbox.setChecked(bool(runtime_config.get("ai_presence_shaders_enabled", True)))
        self.ai_presence_shaders_enabled_checkbox.setToolTip("Use soft glow backgrounds when available.")
        self.ai_presence_shaders_enabled_checkbox.toggled.connect(lambda checked: self.on_ai_presence_setting_changed("ai_presence_shaders_enabled", bool(checked)))

        self.ai_presence_particles_enabled_checkbox = QtWidgets.QCheckBox("Particles")
        self.ai_presence_particles_enabled_checkbox.setObjectName("ai_presence_particles_enabled_checkbox")
        self.ai_presence_particles_enabled_checkbox.setChecked(bool(runtime_config.get("ai_presence_particles_enabled", True)))
        self.ai_presence_particles_enabled_checkbox.setToolTip("Show small moving particles around the presence animation.")
        self.ai_presence_particles_enabled_checkbox.toggled.connect(lambda checked: self.on_ai_presence_setting_changed("ai_presence_particles_enabled", bool(checked)))

        self.ai_presence_space_closes_fullscreen_checkbox = QtWidgets.QCheckBox("Space exits fullscreen")
        self.ai_presence_space_closes_fullscreen_checkbox.setObjectName("ai_presence_space_closes_fullscreen_checkbox")
        self.ai_presence_space_closes_fullscreen_checkbox.setChecked(bool(runtime_config.get("ai_presence_space_closes_fullscreen", True)))
        self.ai_presence_space_closes_fullscreen_checkbox.setToolTip("Escape or mouse click hides fullscreen. Enable this to let Space hide it too.")
        self.ai_presence_space_closes_fullscreen_checkbox.toggled.connect(lambda checked: self.on_ai_presence_setting_changed("ai_presence_space_closes_fullscreen", bool(checked)))

        self.ai_presence_music_reactivity_enabled_checkbox = QtWidgets.QCheckBox("Computer audio sync")
        self.ai_presence_music_reactivity_enabled_checkbox.setObjectName("ai_presence_music_reactivity_enabled_checkbox")
        self.ai_presence_music_reactivity_enabled_checkbox.setChecked(bool(runtime_config.get("ai_presence_music_reactivity_enabled", False)))
        self.ai_presence_music_reactivity_enabled_checkbox.setToolTip("React the outer AI Presence animation to desktop/music output when WASAPI loopback is available.")
        self.ai_presence_music_reactivity_enabled_checkbox.toggled.connect(lambda checked: self.on_ai_presence_setting_changed("ai_presence_music_reactivity_enabled", bool(checked)))

        selector_grid = QtWidgets.QGridLayout()
        selector_grid.setContentsMargins(0, 0, 0, 0)
        selector_grid.setHorizontalSpacing(10)
        selector_grid.setVerticalSpacing(6)
        selector_grid.addWidget(QtWidgets.QLabel("Display"), 0, 0)
        selector_grid.addWidget(self.ai_presence_display_mode_combo, 0, 1)
        selector_grid.addWidget(QtWidgets.QLabel("Style"), 0, 2)
        selector_grid.addWidget(self.ai_presence_visual_style_combo, 0, 3)
        selector_grid.setColumnStretch(1, 1)
        selector_grid.setColumnStretch(3, 1)
        layout.addLayout(selector_grid)

        toggle_row = QtWidgets.QHBoxLayout()
        toggle_row.setSpacing(12)
        toggle_row.addWidget(self.ai_presence_enabled_checkbox)
        toggle_row.addWidget(self.ai_presence_fullscreen_checkbox)
        toggle_row.addWidget(self.ai_presence_reduced_effects_checkbox)
        toggle_row.addWidget(self.ai_presence_preview_button)
        toggle_row.addWidget(self.ai_presence_floating_button)
        toggle_row.addStretch(1)
        layout.addLayout(toggle_row)

        options_row = QtWidgets.QHBoxLayout()
        options_row.setSpacing(12)
        options_row.addWidget(self.ai_presence_floating_always_on_top_checkbox)
        options_row.addWidget(self.ai_presence_remember_floating_geometry_checkbox)
        options_row.addWidget(self.ai_presence_transparent_background_checkbox)
        options_row.addWidget(self.ai_presence_shaders_enabled_checkbox)
        options_row.addWidget(self.ai_presence_particles_enabled_checkbox)
        options_row.addWidget(self.ai_presence_music_reactivity_enabled_checkbox)
        options_row.addWidget(self.ai_presence_space_closes_fullscreen_checkbox)
        options_row.addStretch(1)
        layout.addLayout(options_row)

        self.ai_presence_opacity_slider = LabeledSlider(
            "Opacity",
            0.10,
            1.00,
            float(runtime_config.get("ai_presence_overlay_opacity", 0.72) or 0.72),
        )
        self.ai_presence_opacity_slider.setObjectName("ai_presence_opacity_slider")
        self.ai_presence_opacity_slider.value_changed.connect(lambda value: self.on_ai_presence_setting_changed("ai_presence_overlay_opacity", float(value)))

        self.ai_presence_thinking_slider = LabeledSlider(
            "Thinking Pulse",
            0.10,
            1.00,
            float(runtime_config.get("ai_presence_thinking_pulse", 0.55) or 0.55),
        )
        self.ai_presence_thinking_slider.setObjectName("ai_presence_thinking_slider")
        self.ai_presence_thinking_slider.value_changed.connect(lambda value: self.on_ai_presence_setting_changed("ai_presence_thinking_pulse", float(value)))

        self.ai_presence_speaking_slider = LabeledSlider(
            "Speaking Reactivity",
            0.10,
            1.50,
            float(runtime_config.get("ai_presence_speaking_reactivity", 0.85) or 0.85),
        )
        self.ai_presence_speaking_slider.setObjectName("ai_presence_speaking_slider")
        self.ai_presence_speaking_slider.value_changed.connect(lambda value: self.on_ai_presence_setting_changed("ai_presence_speaking_reactivity", float(value)))

        self.ai_presence_audio_refresh_slider = LabeledSlider(
            "Audio Sync Rate",
            5,
            30,
            int(runtime_config.get("ai_presence_audio_refresh_hz", 30) or 30),
            is_int=True,
        )
        self.ai_presence_audio_refresh_slider.setObjectName("ai_presence_audio_refresh_slider")
        self.ai_presence_audio_refresh_slider.setToolTip("How many audio-level updates per second are sent to AI Presence while speech is playing.")
        self.ai_presence_audio_refresh_slider.value_changed.connect(lambda value: self.on_ai_presence_setting_changed("ai_presence_audio_refresh_hz", int(value)))

        self.ai_presence_density_slider = LabeledSlider(
            "Neural Node Density",
            8,
            96,
            int(runtime_config.get("ai_presence_node_density", 32) or 32),
            is_int=True,
        )
        self.ai_presence_density_slider.setObjectName("ai_presence_density_slider")
        self.ai_presence_density_slider.value_changed.connect(lambda value: self.on_ai_presence_setting_changed("ai_presence_node_density", int(value)))

        self.ai_presence_floating_opacity_slider = LabeledSlider(
            "Floating Opacity",
            0.35,
            1.00,
            float(runtime_config.get("ai_presence_floating_opacity", 0.92) or 0.92),
        )
        self.ai_presence_floating_opacity_slider.setObjectName("ai_presence_floating_opacity_slider")
        self.ai_presence_floating_opacity_slider.value_changed.connect(lambda value: self.on_ai_presence_setting_changed("ai_presence_floating_opacity", float(value)))

        self.ai_presence_particle_density_slider = LabeledSlider(
            "Particle Density",
            0,
            120,
            int(runtime_config.get("ai_presence_particle_density", 28) or 28),
            is_int=True,
        )
        self.ai_presence_particle_density_slider.setObjectName("ai_presence_particle_density_slider")
        self.ai_presence_particle_density_slider.value_changed.connect(lambda value: self.on_ai_presence_setting_changed("ai_presence_particle_density", int(value)))

        self.ai_presence_music_reactivity_slider = LabeledSlider(
            "Music Reactivity",
            0.00,
            1.50,
            float(runtime_config.get("ai_presence_music_reactivity", 0.65)),
        )
        self.ai_presence_music_reactivity_slider.setObjectName("ai_presence_music_reactivity_slider")
        self.ai_presence_music_reactivity_slider.setToolTip("How strongly computer/music output moves the outer AI Presence animation.")
        self.ai_presence_music_reactivity_slider.value_changed.connect(lambda value: self.on_ai_presence_setting_changed("ai_presence_music_reactivity", float(value)))

        slider_grid = QtWidgets.QGridLayout()
        slider_grid.setContentsMargins(0, 0, 0, 0)
        slider_grid.setHorizontalSpacing(12)
        slider_grid.setVerticalSpacing(8)
        slider_grid.addWidget(self.ai_presence_opacity_slider, 0, 0)
        slider_grid.addWidget(self.ai_presence_thinking_slider, 0, 1)
        slider_grid.addWidget(self.ai_presence_speaking_slider, 1, 0)
        slider_grid.addWidget(self.ai_presence_audio_refresh_slider, 1, 1)
        slider_grid.addWidget(self.ai_presence_density_slider, 2, 0)
        slider_grid.addWidget(self.ai_presence_particle_density_slider, 2, 1)
        slider_grid.addWidget(self.ai_presence_floating_opacity_slider, 3, 0)
        slider_grid.addWidget(self.ai_presence_music_reactivity_slider, 3, 1)
        layout.addLayout(slider_grid)

        self.ai_presence_status_label = QtWidgets.QLabel("Uses Qt Quick when available; Fullscreen appears during thinking/speaking. Escape or mouse click hides fullscreen. Floating Window can be resized.")
        self.ai_presence_status_label.setObjectName("ai_presence_status_label")
        self.ai_presence_status_label.setWordWrap(True)
        self.ai_presence_status_label.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        layout.addWidget(self.ai_presence_status_label)

        self.ai_presence_runtime_section = CollapsibleSection(
            "AI PRESENCE MODE",
            self.ai_presence_runtime_box,
            expanded=True,
        )
        self.ai_presence_runtime_section.toggle_button.toggled.connect(lambda _checked: self._on_runtime_section_toggled())
        return self.ai_presence_runtime_section

    def _build_chat_runtime_card(self):
        self.chat_runtime_box = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(self.chat_runtime_box)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        def _make_inner_card(object_name):
            card = QtWidgets.QFrame()
            card.setObjectName(object_name)
            card.setStyleSheet(
                f"QFrame#{object_name} {{"
                "  background: rgba(12, 18, 26, 0.35);"
                "  border: 1px solid #273342;"
                "  border-radius: 10px;"
                "}"
            )
            card_layout = QtWidgets.QVBoxLayout(card)
            card_layout.setContentsMargins(10, 10, 10, 10)
            card_layout.setSpacing(8)
            return card, card_layout

        self.chat_runtime_inner_card = QtWidgets.QFrame()
        self.chat_runtime_inner_card.setObjectName("chat_runtime_inner_card")
        self.chat_runtime_inner_card.setStyleSheet(
            "QFrame#chat_runtime_inner_card {"
            "  background: rgba(12, 18, 26, 0.55);"
            "  border: 1px solid #273342;"
            "  border-radius: 12px;"
            "}"
        )
        inner_layout = QtWidgets.QVBoxLayout(self.chat_runtime_inner_card)
        inner_layout.setContentsMargins(12, 12, 12, 12)
        inner_layout.setSpacing(10)

        selector_grid = QtWidgets.QGridLayout()
        selector_grid.setContentsMargins(0, 0, 0, 0)
        selector_grid.setHorizontalSpacing(12)
        selector_grid.setVerticalSpacing(8)
        selector_grid.addWidget(QtWidgets.QLabel("Chat Provider"), 0, 0, QtCore.Qt.AlignVCenter)
        selector_grid.addWidget(self.chat_provider_combo, 0, 1)
        selector_grid.addWidget(QtWidgets.QLabel("LLM Model"), 0, 2, QtCore.Qt.AlignVCenter)
        selector_grid.addWidget(self.model_row_widget, 0, 3)
        selector_grid.setColumnStretch(1, 1)
        selector_grid.setColumnStretch(3, 2)
        inner_layout.addLayout(selector_grid)

        self.chat_provider_fields_widget = QtWidgets.QWidget()
        self.chat_provider_fields_layout = QtWidgets.QFormLayout(self.chat_provider_fields_widget)
        self.chat_provider_fields_layout.setContentsMargins(0, 0, 0, 0)
        self.chat_provider_fields_layout.setSpacing(8)
        self.chat_provider_fields_layout.setLabelAlignment(QtCore.Qt.AlignLeft)
        self.chat_provider_fields_layout.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)
        self.chat_provider_settings_card, self.chat_provider_settings_card_layout = _make_inner_card(
            "chat_provider_settings_card"
        )
        self.chat_provider_settings_card_layout.addWidget(self.chat_provider_fields_widget)
        self.chat_provider_settings_section = CollapsibleSection(
            "Provider Settings",
            self.chat_provider_settings_card,
            expanded=True,
        )
        inner_layout.addWidget(self.chat_provider_settings_section)

        self.chat_provider_generation_fields_widget = QtWidgets.QWidget()
        self.chat_provider_generation_fields_layout = QtWidgets.QFormLayout(self.chat_provider_generation_fields_widget)
        self.chat_provider_generation_fields_layout.setContentsMargins(0, 0, 0, 0)
        self.chat_provider_generation_fields_layout.setSpacing(8)
        self.chat_provider_generation_fields_layout.setLabelAlignment(QtCore.Qt.AlignLeft)
        self.chat_provider_generation_fields_layout.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)
        self.chat_provider_generation_card, self.chat_provider_generation_card_layout = _make_inner_card(
            "chat_provider_generation_card"
        )
        self.chat_provider_generation_card_layout.addWidget(self.chat_provider_generation_fields_widget)
        self.chat_provider_generation_section = CollapsibleSection(
            "Generation Settings",
            self.chat_provider_generation_card,
            expanded=False,
        )
        inner_layout.addWidget(self.chat_provider_generation_section)

        self.chat_provider_hint_label = QtWidgets.QLabel()
        self.chat_provider_hint_label.setWordWrap(True)
        self.chat_provider_hint_label.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        inner_layout.addWidget(self.chat_provider_hint_label)

        layout.addWidget(self.chat_runtime_inner_card)

        self._refresh_chat_provider_card()
        self.chat_runtime_section = CollapsibleSection("LLM Runtime", self.chat_runtime_box, expanded=True)
        self.chat_runtime_section.toggle_button.toggled.connect(lambda _checked: self._on_runtime_section_toggled())
        self._refresh_chat_runtime_summary()
        return self.chat_runtime_section

    def _build_stt_runtime_card(self):
        self.stt_runtime_box = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(self.stt_runtime_box)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.stt_runtime_inner_card = QtWidgets.QFrame()
        self.stt_runtime_inner_card.setObjectName("stt_runtime_inner_card")
        self.stt_runtime_inner_card.setStyleSheet(
            "QFrame#stt_runtime_inner_card {"
            "  background: rgba(12, 18, 26, 0.35);"
            "  border: 1px solid #273342;"
            "  border-radius: 10px;"
            "}"
        )
        inner_layout = QtWidgets.QVBoxLayout(self.stt_runtime_inner_card)
        inner_layout.setContentsMargins(10, 10, 10, 10)
        inner_layout.setSpacing(10)

        selector_grid = QtWidgets.QGridLayout()
        selector_grid.setContentsMargins(0, 0, 0, 0)
        selector_grid.setHorizontalSpacing(12)
        selector_grid.setVerticalSpacing(8)
        selector_grid.addWidget(QtWidgets.QLabel("STT Backend"), 0, 0, QtCore.Qt.AlignVCenter)
        selector_grid.addWidget(self.stt_backend_combo, 0, 1)
        selector_grid.addWidget(QtWidgets.QLabel("Whisper Model"), 0, 2, QtCore.Qt.AlignVCenter)
        selector_grid.addWidget(self.stt_model_combo, 0, 3)
        selector_grid.addWidget(QtWidgets.QLabel("Input Language"), 1, 0, QtCore.Qt.AlignVCenter)
        selector_grid.addWidget(self.stt_language_combo, 1, 1)
        selector_grid.setColumnStretch(1, 1)
        selector_grid.setColumnStretch(3, 1)
        inner_layout.addLayout(selector_grid)

        self.stt_runtime_hint_label = QtWidgets.QLabel(
            "Use a multilingual Whisper model, such as tiny/base/small, for non-English speech. Auto Detect lets Whisper infer the spoken language."
        )
        self.stt_runtime_hint_label.setWordWrap(True)
        self.stt_runtime_hint_label.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        inner_layout.addWidget(self.stt_runtime_hint_label)
        layout.addWidget(self.stt_runtime_inner_card)

        self.stt_runtime_section = CollapsibleSection("STT Runtime", self.stt_runtime_box, expanded=True)
        self.stt_runtime_section.toggle_button.toggled.connect(lambda _checked: self._on_runtime_section_toggled())
        self._refresh_stt_runtime_summary()
        return self.stt_runtime_section

    def _build_tts_runtime_card(self):
        self.tts_runtime_box = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(self.tts_runtime_box)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.tts_runtime_inner_card = QtWidgets.QFrame()
        self.tts_runtime_inner_card.setObjectName("tts_runtime_inner_card")
        self.tts_runtime_inner_card.setStyleSheet(
            "QFrame#tts_runtime_inner_card {"
            "  background: rgba(12, 18, 26, 0.35);"
            "  border: 1px solid #273342;"
            "  border-radius: 10px;"
            "}"
        )
        inner_layout = QtWidgets.QVBoxLayout(self.tts_runtime_inner_card)
        inner_layout.setContentsMargins(10, 10, 10, 10)
        inner_layout.setSpacing(12)

        backend_block = QtWidgets.QWidget()
        backend_form = QtWidgets.QFormLayout(backend_block)
        backend_form.setContentsMargins(0, 0, 0, 0)
        backend_form.setSpacing(8)
        backend_form.setLabelAlignment(QtCore.Qt.AlignLeft)
        backend_form.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)
        backend_form.addRow("TTS Backend", self.tts_backend_combo)
        inner_layout.addWidget(backend_block)
        inner_layout.addSpacing(2)

        self.tts_runtime_addon_tabs = QtWidgets.QTabWidget()
        self.tts_runtime_addon_tabs.setDocumentMode(False)
        self.tts_runtime_addon_tabs.setMinimumHeight(0)
        self.tts_runtime_addon_tabs.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        self.tts_runtime_addon_tabs.currentChanged.connect(self._on_tts_runtime_addon_tab_changed)
        self.tts_runtime_addon_tabs.setVisible(False)
        inner_layout.addWidget(self.tts_runtime_addon_tabs)

        self.tts_runtime_hint_label = QtWidgets.QLabel(
            "TTS backend controls are now provided by addon tabs in this card."
        )
        self.tts_runtime_hint_label.setWordWrap(True)
        self.tts_runtime_hint_label.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        inner_layout.addWidget(self.tts_runtime_hint_label)

        layout.addWidget(self.tts_runtime_inner_card)

        self._refresh_tts_runtime_card()
        self.tts_runtime_section = CollapsibleSection("TTS Runtime", self.tts_runtime_box, expanded=True)
        self.tts_runtime_section.toggle_button.toggled.connect(lambda _checked: self._on_runtime_section_toggled())
        self._refresh_tts_runtime_summary()
        return self.tts_runtime_section

    def _build_sensory_feedback_tab(self):
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        self.sensory_feedback_tabs = NoWheelTabWidget()
        self.sensory_feedback_tabs.setObjectName("sensory_feedback_tabs")
        self.sensory_feedback_tabs.setMinimumSize(0, 0)
        self.sensory_feedback_tabs.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        self._apply_vision_tab_button_style(self.sensory_feedback_tabs)
        self.sensory_feedback_tabs.currentChanged.connect(lambda _index, tabs=self.sensory_feedback_tabs: self._sync_tab_widget_height(tabs))

        core_tab = QtWidgets.QWidget()
        core_layout = QtWidgets.QVBoxLayout(core_tab)
        core_layout.setContentsMargins(8, 8, 8, 8)
        core_layout.setSpacing(10)

        sensory_box = QtWidgets.QGroupBox("Background Awareness")
        sensory_box.setObjectName("vision_background_awareness_group")
        sensory_box.setStyleSheet(
            "QGroupBox {"
            "  color: #dbeafe;"
            "  font-weight: 700;"
            "  border: 1px solid rgba(96, 165, 250, 0.32);"
            "  border-radius: 7px;"
            "  margin-top: 10px;"
            "  padding-top: 10px;"
            "}"
            "QGroupBox::title {"
            "  subcontrol-origin: margin;"
            "  left: 10px;"
            "  padding: 0 4px;"
            "}"
        )
        sensory_layout = QtWidgets.QVBoxLayout(sensory_box)
        sensory_layout.setContentsMargins(10, 10, 10, 10)
        sensory_layout.setSpacing(10)

        intro_label = QtWidgets.QLabel(
            "Choose what NC may quietly observe in the background. Observations are added as context; they are not sent as user messages."
        )
        intro_label.setObjectName("sensory_feedback_intro")
        intro_label.setWordWrap(True)
        intro_label.setStyleSheet("color: #b8c8d9; font-size: 11px;")
        sensory_layout.addWidget(intro_label)

        def make_card(title, object_name):
            card = QtWidgets.QGroupBox(title)
            card.setObjectName(object_name)
            card.setStyleSheet(
                "QGroupBox {"
                "  color: #dbeafe;"
                "  font-weight: 700;"
                "  border: 1px solid rgba(96, 165, 250, 0.32);"
                "  border-radius: 7px;"
                "  margin-top: 10px;"
                "  padding-top: 10px;"
                "}"
                "QGroupBox::title {"
                "  subcontrol-origin: margin;"
                "  left: 10px;"
                "  padding: 0 4px;"
                "}"
            )
            card.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Maximum)
            card_layout = QtWidgets.QVBoxLayout(card)
            card_layout.setContentsMargins(10, 10, 10, 10)
            card_layout.setSpacing(8)
            return card, card_layout

        def field_with_suffix(widget, suffix):
            container = QtWidgets.QWidget()
            row = QtWidgets.QHBoxLayout(container)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)
            row.addWidget(self._wrap_compact_form_field(widget), 0)
            suffix_label = QtWidgets.QLabel(suffix)
            suffix_label.setStyleSheet("color: #9fb3c8; font-size: 11px;")
            row.addWidget(suffix_label, 0)
            row.addStretch(1)
            return container

        review_card, review_layout = make_card("Background Review", "vision_overview_review_group")
        review_layout.addWidget(self.sensory_pingpong_checkbox)
        review_form = QtWidgets.QFormLayout()
        review_form.setLabelAlignment(QtCore.Qt.AlignLeft)
        review_form.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldsStayAtSizeHint)
        review_form.setFormAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        review_form.addRow("Review every", field_with_suffix(self.sensory_feedback_interval_spin, "seconds"))
        review_form.addRow("Keep recent observations", self._wrap_compact_form_field(self.sensory_pingpong_history_spin))
        review_layout.addLayout(review_form)
        sensory_layout.addWidget(review_card)

        sources_card, sources_layout = make_card("Sources to observe", "vision_overview_sources_group")
        sources_hint = QtWidgets.QLabel("Select the background inputs NC may include when building context.")
        sources_hint.setWordWrap(True)
        sources_hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        sources_layout.addWidget(sources_hint)
        sources_layout.addWidget(self.sensory_feedback_sources_widget)
        companion_orb_target_row = QtWidgets.QHBoxLayout()
        companion_orb_target_row.setContentsMargins(0, 0, 0, 0)
        companion_orb_target_row.setSpacing(8)
        companion_orb_target_row.addWidget(self.companion_orb_sensory_target_checkbox)
        companion_orb_target_row.addWidget(self.btn_companion_orb_clear_sensory_target)
        companion_orb_target_row.addStretch(1)
        sources_layout.addLayout(companion_orb_target_row)
        sensory_layout.addWidget(sources_card)

        actions_card, actions_layout = make_card("What NC may do", "vision_overview_actions_group")
        actions_layout.addWidget(self.sensory_allow_hidden_proactive_checkbox)
        actions_layout.addWidget(self.sensory_allow_hidden_visual_checkbox)
        sensory_layout.addWidget(actions_card)

        self.sensory_feedback_hint = QtWidgets.QLabel()
        self.sensory_feedback_hint.setObjectName("sensory_feedback_hint")
        self.sensory_feedback_hint.setWordWrap(True)
        self.sensory_feedback_hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        sensory_layout.addWidget(self.sensory_feedback_hint)
        self._refresh_sensory_feedback_hint()

        advanced_widget = QtWidgets.QWidget()
        advanced_layout = QtWidgets.QVBoxLayout(advanced_widget)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        advanced_layout.setSpacing(8)

        self.sensory_pingpong_prompt_label = QtWidgets.QLabel("Developer prompt JSON contract")
        self.sensory_pingpong_prompt_label.setStyleSheet("color: #9fb3c8; font-size: 11px; font-weight: 600;")
        prompt_header = QtWidgets.QHBoxLayout()
        prompt_header.setContentsMargins(0, 0, 0, 0)
        prompt_header.setSpacing(8)
        prompt_header.addWidget(self.sensory_pingpong_prompt_label)
        prompt_header.addStretch(1)
        prompt_header.addWidget(self.btn_sensory_pingpong_prompt_reset, 0)
        advanced_layout.addLayout(prompt_header)
        advanced_layout.addWidget(self.sensory_pingpong_prompt_text)

        self.sensory_pingpong_prompt_hint = QtWidgets.QLabel("Advanced: this prompt defines the JSON contract for background review. Source tabs add source-specific guidance. Use __EMOTION_LIST__ to inject the currently available avatar emotion tags.")
        self.sensory_pingpong_prompt_hint.setWordWrap(True)
        self.sensory_pingpong_prompt_hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        advanced_layout.addWidget(self.sensory_pingpong_prompt_hint)
        self.sensory_pingpong_prompt_section = CollapsibleSection("Advanced / Developer Prompt", advanced_widget, expanded=False)
        self.sensory_pingpong_prompt_section.setSummary("JSON contract and source guidance")
        sensory_layout.addWidget(self.sensory_pingpong_prompt_section)

        core_layout.addWidget(sensory_box)
        style = QtWidgets.QApplication.style()
        overview_icon = style.standardIcon(QtWidgets.QStyle.SP_MessageBoxInformation) if style is not None else QtGui.QIcon()
        self.sensory_feedback_tabs.addTab(core_tab, overview_icon, "Overview")
        self._refresh_sensory_feedback_source_tabs()
        self._update_sensory_feedback_tab_bar_visibility()
        layout.addWidget(self.sensory_feedback_tabs, 0, QtCore.Qt.AlignTop)
        return tab

    def _build_chat_session_tab(self):
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        behavior_box = QtWidgets.QGroupBox("Conversation Flow")
        behavior_layout = QtWidgets.QVBoxLayout(behavior_box)
        behavior_layout.setContentsMargins(12, 14, 12, 12)
        behavior_layout.setSpacing(8)
        behavior_layout.addWidget(self.allow_proactive_checkbox)
        behavior_layout.addWidget(self.require_first_user_checkbox)

        timing_form = QtWidgets.QFormLayout()
        timing_form.setLabelAlignment(QtCore.Qt.AlignLeft)
        timing_form.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldsStayAtSizeHint)
        timing_form.setFormAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        timing_form.addRow("Idle wait window (s)", self.listen_idle_window_spin)
        timing_form.addRow("Proactive delay (s)", self.proactive_delay_spin)
        timing_form.addRow("Context window (msgs)", self.chat_context_window_spin)
        timing_form.addRow("Stored history limit", self.stored_chat_history_limit_spin)
        timing_form.addRow("Overflow policy", self.chat_overflow_policy_combo)
        timing_form.addRow("Dictionary language", self.spellcheck_language_combo)
        behavior_layout.addLayout(timing_form)
        behavior_layout.addWidget(self.spellcheck_enabled_checkbox)
        spellcheck_repair_row = QtWidgets.QHBoxLayout()
        spellcheck_repair_row.setSpacing(8)
        spellcheck_repair_row.addWidget(self.btn_install_spellcheck_dependency)
        spellcheck_repair_row.addWidget(self.spellcheck_dependency_hint, 1)
        behavior_layout.addLayout(spellcheck_repair_row)
        behavior_layout.addWidget(self.chat_session_hint)
        layout.addWidget(behavior_box)

        memory_box = QtWidgets.QGroupBox("Continuity Memory")
        memory_layout = QtWidgets.QVBoxLayout(memory_box)
        memory_layout.setContentsMargins(12, 14, 12, 12)
        memory_layout.setSpacing(8)
        memory_layout.addWidget(self.long_term_memory_enabled_checkbox)
        memory_layout.addWidget(self.long_term_memory_update_on_save_checkbox)
        memory_layout.addWidget(self.long_term_memory_inject_checkbox)
        memory_form = QtWidgets.QFormLayout()
        memory_form.setLabelAlignment(QtCore.Qt.AlignLeft)
        memory_form.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldsStayAtSizeHint)
        memory_form.setFormAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        memory_form.addRow("Auto summary interval (msgs)", self.continuity_memory_auto_turns_spin)
        memory_form.addRow("Summary budget (chars)", self.long_term_memory_max_chars_spin)
        memory_layout.addLayout(memory_form)
        memory_button_row = QtWidgets.QHBoxLayout()
        memory_button_row.setSpacing(8)
        memory_button_row.addWidget(self.btn_review_long_term_memory)
        memory_button_row.addWidget(self.btn_batch_update_long_term_memory)
        memory_button_row.addWidget(self.btn_forget_long_term_memory)
        memory_button_row.addStretch(1)
        memory_layout.addLayout(memory_button_row)
        memory_layout.addWidget(self.long_term_memory_hint)
        layout.addWidget(memory_box)

        archive_box = QtWidgets.QGroupBox("Long-Term Memory Archive")
        archive_layout = QtWidgets.QVBoxLayout(archive_box)
        archive_layout.setContentsMargins(12, 14, 12, 12)
        archive_layout.setSpacing(8)
        archive_hint = QtWidgets.QLabel("Long-Term Memory stores raw chat archive chunks on Save Chat Context or after the archive interval. Retrieval can inject matching archive recall into chat requests.")
        archive_hint.setWordWrap(True)
        archive_hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        archive_layout.addWidget(archive_hint)
        archive_layout.addWidget(self.long_term_memory_retrieval_enabled_checkbox)
        retrieval_form = QtWidgets.QFormLayout()
        retrieval_form.setLabelAlignment(QtCore.Qt.AlignLeft)
        retrieval_form.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldsStayAtSizeHint)
        retrieval_form.setFormAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        retrieval_form.addRow("Archive interval (msgs)", self.long_term_memory_archive_batch_turns_spin)
        retrieval_form.addRow("Max recall items", self.long_term_memory_retrieval_max_items_spin)
        embedding_model_row = QtWidgets.QHBoxLayout()
        embedding_model_row.setSpacing(8)
        embedding_model_row.addWidget(self.long_term_memory_embedding_model_edit, 1)
        embedding_model_row.addWidget(self.btn_long_term_memory_embedding_model_refresh)
        retrieval_form.addRow("Embedding model", embedding_model_row)
        retrieval_form.addRow("Embedding context", self.long_term_memory_embedding_context_length_spin)
        retrieval_form.addRow("Embedding base URL", self.long_term_memory_embedding_base_url_edit)
        archive_layout.addLayout(retrieval_form)
        archive_layout.addWidget(self.long_term_memory_embedding_enabled_checkbox)
        archive_button_row = QtWidgets.QHBoxLayout()
        archive_button_row.setSpacing(8)
        archive_button_row.addWidget(self.btn_search_long_term_memory_archive)
        archive_button_row.addWidget(self.btn_review_long_term_memory_archive)
        archive_button_row.addStretch(1)
        archive_layout.addLayout(archive_button_row)
        archive_layout.addWidget(self.long_term_memory_archive_hint)
        layout.addWidget(archive_box)

        actions_box = QtWidgets.QGroupBox("Session")
        actions_layout = QtWidgets.QVBoxLayout(actions_box)
        actions_layout.setContentsMargins(12, 14, 12, 12)
        actions_layout.setSpacing(8)
        reset_hint = QtWidgets.QLabel("Clear conversation memory when you want to restart the current chat without restarting the whole app.")
        reset_hint.setWordWrap(True)
        reset_hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        actions_layout.addWidget(reset_hint)
        button_row = QtWidgets.QHBoxLayout()
        button_row.setSpacing(8)
        button_row.addWidget(self.btn_save_chat_session)
        button_row.addWidget(self.btn_save_chat_session_as)
        button_row.addWidget(self.btn_load_chat_session)
        button_row.addWidget(self.btn_reset_chat_session)
        button_row.addStretch(1)
        actions_layout.addLayout(button_row)
        layout.addWidget(actions_box)

        register_memory_callback = getattr(self, "_register_continuity_memory_update_callback", None)
        if callable(register_memory_callback):
            register_memory_callback()
        self._refresh_chat_session_hint()
        layout.addStretch(1)
        return tab

    def _build_left_panel(self):
        engine_module = _engine()
        runtime_config = engine_module.RUNTIME_CONFIG
        shaping_panel = self._wrap_panel()
        shaping_panel.setMinimumSize(0, 0)
        shaping_panel.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Ignored)
        shaping_outer_layout = QtWidgets.QVBoxLayout(shaping_panel)
        shaping_outer_layout.setContentsMargins(0, 0, 0, 0)
        shaping_outer_layout.setSpacing(0)

        shaping_scroll = QtWidgets.QScrollArea()
        shaping_scroll.setWidgetResizable(True)
        shaping_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        shaping_scroll.setMinimumSize(0, 0)
        shaping_scroll.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Ignored)
        self.system_shaping_scroll = shaping_scroll
        shaping_outer_layout.addWidget(shaping_scroll)

        shaping_content = QtWidgets.QWidget()
        shaping_content.setMinimumSize(0, 0)
        shaping_scroll.setWidget(shaping_content)

        layout = QtWidgets.QVBoxLayout(shaping_content)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        layout.addWidget(self._make_header("Experimental Qt Shell", "System Shaping"))

        mic_row_widget = QtWidgets.QWidget()
        mic_row_widget.setObjectName("micStatusRow")
        mic_row = QtWidgets.QHBoxLayout(mic_row_widget)
        mic_row.setContentsMargins(0, 0, 0, 0)
        mic_row.setSpacing(8)
        self.listen_diode = QtWidgets.QFrame()
        self.listen_diode.setFixedSize(16, 16)
        self.listen_diode.setStyleSheet(self._status_diode_style(False, "#39d98a", "#92f0bf"))
        self.mic_diode = QtWidgets.QFrame()
        self.mic_diode.setFixedSize(16, 16)
        self.mic_diode.setStyleSheet(self._status_diode_style(False, "#ff4d5e", "#ff96a0"))
        self.mic_status_label = QtWidgets.QLabel("Microphone idle")
        self.mic_status_label.setStyleSheet("color: #9fb3c8; font-weight: 600;")
        mic_row.addWidget(self.listen_diode)
        mic_row.addWidget(self.mic_diode)
        mic_row.addWidget(self.mic_status_label)

        self.show_all_audio_inputs_checkbox = QtWidgets.QCheckBox("All inputs")
        self.show_all_audio_inputs_checkbox.setObjectName("show_all_audio_inputs_checkbox")
        self.show_all_audio_inputs_checkbox.setToolTip("Show virtual, line, loopback, and mixer input devices.")
        self.show_all_audio_inputs_checkbox.setChecked(bool(runtime_config.get("show_all_audio_input_devices", False)))
        self.show_all_audio_inputs_checkbox.toggled.connect(self.on_show_all_audio_inputs_change)

        audio_devices = _ui_shell_audio_device_labels(
            show_all_inputs=self.show_all_audio_inputs_checkbox.isChecked(),
            include_input_mode_actions=True,
        )
        self.audio_input_device_combo = NoWheelComboBox()
        self.audio_input_device_combo.setObjectName("audio_input_device_combo")
        _ui_shell_combo_set_items(self.audio_input_device_combo, list(audio_devices.get("inputs") or ["Default Input"]))
        _ui_shell_combo_select_label(self.audio_input_device_combo, str(runtime_config.get("audio_input_device", "Default Input") or "Default Input"))
        self.audio_input_device_combo.currentTextChanged.connect(self.on_audio_input_device_change)

        self.audio_output_device_combo = NoWheelComboBox()
        self.audio_output_device_combo.setObjectName("audio_output_device_combo")
        _ui_shell_combo_set_items(self.audio_output_device_combo, list(audio_devices.get("outputs") or ["Default Output"]))
        _ui_shell_combo_select_label(self.audio_output_device_combo, str(runtime_config.get("audio_output_device", "Default Output") or "Default Output"))
        self.audio_output_device_combo.currentTextChanged.connect(self.on_audio_output_device_change)

        mic_row.addWidget(QtWidgets.QLabel("Input"))
        mic_row.addWidget(self.audio_input_device_combo, 1)
        mic_row.addWidget(self.show_all_audio_inputs_checkbox)
        mic_row.addWidget(QtWidgets.QLabel("Output"))
        mic_row.addWidget(self.audio_output_device_combo, 1)
        mic_row.addStretch(1)
        self.mic_status_row_widget = mic_row_widget

        self.engine_combo = NoWheelComboBox()
        self.engine_combo.setObjectName("engine_combo")
        _set_tooltip(self.engine_combo, SYSTEM_SHAPING_TOOLTIPS["engine_combo"])
        self.refresh_avatar_engine_options()
        self.engine_combo.currentTextChanged.connect(self.on_engine_change)

        self.input_mode_combo = NoWheelComboBox()
        self.input_mode_combo.setObjectName("input_mode_combo")
        self.input_mode_combo.addItems(["Voice Activation", "Push-to-Talk", "Text Only"])
        _set_tooltip(self.input_mode_combo, SYSTEM_SHAPING_TOOLTIPS["input_mode_combo"])
        self.input_mode_combo.currentTextChanged.connect(self.on_input_mode_change)

        self.input_role_combo = NoWheelComboBox()
        self.input_role_combo.setObjectName("input_role_combo")
        self.input_role_combo.addItems(["User Message", "System Message", "Assistant Message"])
        _set_tooltip(self.input_role_combo, SYSTEM_SHAPING_TOOLTIPS["input_role_combo"])
        self.input_role_combo.currentTextChanged.connect(self.on_input_role_change)

        self.stream_mode_combo = NoWheelComboBox()
        self.stream_mode_combo.setObjectName("stream_mode_combo")
        self.stream_mode_combo.addItems(["Off", "On"])
        _set_tooltip(self.stream_mode_combo, SYSTEM_SHAPING_TOOLTIPS["stream_mode_combo"])
        self.stream_mode_combo.currentTextChanged.connect(self.on_stream_mode_change)

        self.stt_backend_combo = NoWheelComboBox()
        self.stt_backend_combo.setObjectName("stt_backend_combo")
        self.stt_backend_combo.currentTextChanged.connect(self.on_stt_backend_change)
        self._populate_stt_backend_combo()

        self.stt_model_combo = NoWheelComboBox()
        self.stt_model_combo.setObjectName("stt_model_combo")
        self.stt_model_combo.currentTextChanged.connect(self.on_stt_model_change)
        self._populate_stt_model_combo()

        self.stt_language_combo = NoWheelComboBox()
        self.stt_language_combo.setObjectName("stt_language_combo")
        self.stt_language_combo.currentTextChanged.connect(self.on_stt_language_change)
        self._populate_stt_language_combo()

        self.tts_backend_combo = NoWheelComboBox()
        self.tts_backend_combo.setObjectName("tts_backend_combo")
        self.tts_backend_combo.currentTextChanged.connect(self.on_tts_backend_change)
        self._populate_tts_backend_combo()

        built = self._invoke_avatar_legacy_capability(
            "musetalk",
            "legacy.build_runtime_widgets",
            {"backend": self, "runtime_config": runtime_config},
            default=False,
        )
        if not built:
            ensure_musetalk_legacy_placeholders(self, runtime_config)
        self._invoke_avatar_legacy_capability(
            "scenic",
            "legacy.build_runtime_widgets",
            {"backend": self, "runtime_config": runtime_config},
            default=False,
        )
        built = self._invoke_visual_reply_capability(
            "legacy.build_runtime_widgets",
            {"backend": self, "runtime_config": runtime_config},
            default=False,
        )
        if not built:
            ensure_visual_reply_legacy_placeholders(self, runtime_config)

        self.sensory_feedback_source_combo = NoWheelComboBox()
        self.sensory_feedback_source_combo.setObjectName("sensory_feedback_source_combo")
        self.sensory_feedback_source_combo.setEnabled(False)
        self.sensory_feedback_source_combo.currentTextChanged.connect(self.on_sensory_feedback_source_changed)
        self.sensory_feedback_sources_widget = QtWidgets.QWidget()
        self.sensory_feedback_sources_widget.setObjectName("sensory_feedback_sources_widget")
        self.sensory_feedback_sources_layout = QtWidgets.QVBoxLayout(self.sensory_feedback_sources_widget)
        self.sensory_feedback_sources_layout.setContentsMargins(0, 0, 0, 0)
        self.sensory_feedback_sources_layout.setSpacing(4)
        self._sensory_feedback_source_checkboxes = {}
        self._sensory_source_prompt_editors = {}
        self._sensory_source_prompt_tabs = {}
        self.refresh_sensory_feedback_source_options(selected_value=str(runtime_config.get("sensory_feedback_source", "off") or "off"))

        self.sensory_feedback_interval_spin = DecimalStepper()
        self.sensory_feedback_interval_spin.setObjectName("sensory_feedback_interval_spin")
        self.sensory_feedback_interval_spin.setRange(2.0, 60.0)
        self.sensory_feedback_interval_spin.setSingleStep(0.5)
        self.sensory_feedback_interval_spin.setDecimals(1)
        self.sensory_feedback_interval_spin.setValue(float(runtime_config.get("sensory_feedback_interval_seconds", 7.0) or 7.0))
        self.sensory_feedback_interval_spin.valueChanged.connect(self.on_sensory_feedback_interval_changed)
        self.sensory_feedback_interval_spin.setMinimumWidth(112)
        self.sensory_feedback_interval_spin.setMaximumWidth(132)

        self.sensory_pingpong_checkbox = QtWidgets.QCheckBox("Enable background review")
        self.sensory_pingpong_checkbox.setObjectName("sensory_pingpong_checkbox")
        self.sensory_pingpong_checkbox.setToolTip("Lets NC quietly review selected sources while idle, then keep useful observation notes.")
        self.sensory_pingpong_checkbox.setChecked(bool(runtime_config.get("sensory_pingpong_enabled", False)))
        self.sensory_pingpong_checkbox.toggled.connect(self.on_sensory_pingpong_enabled_changed)

        self.sensory_allow_hidden_proactive_checkbox = QtWidgets.QCheckBox("Allow NC to speak about observations")
        self.sensory_allow_hidden_proactive_checkbox.setObjectName("sensory_allow_hidden_proactive_checkbox")
        self.sensory_allow_hidden_proactive_checkbox.setToolTip("Allows a background observation to become a spoken proactive comment when the prompt marks it as worth saying.")
        self.sensory_allow_hidden_proactive_checkbox.setChecked(bool(runtime_config.get("sensory_allow_hidden_proactive_speech", False)))
        self.sensory_allow_hidden_proactive_checkbox.toggled.connect(self.on_sensory_allow_hidden_proactive_changed)

        self.sensory_allow_hidden_visual_checkbox = QtWidgets.QCheckBox("Use observations for Visual Reply images")
        self.sensory_allow_hidden_visual_checkbox.setObjectName("sensory_allow_hidden_visual_checkbox")
        self.sensory_allow_hidden_visual_checkbox.setToolTip("Allows selected sensory context to trigger automatic Visual Reply image generation when the prompt explicitly requests it.")
        self.sensory_allow_hidden_visual_checkbox.setChecked(bool(runtime_config.get("sensory_allow_hidden_visual_generation", False)))
        self.sensory_allow_hidden_visual_checkbox.toggled.connect(self.on_sensory_allow_hidden_visual_changed)

        self.companion_orb_sensory_target_checkbox = QtWidgets.QCheckBox("Use Orb target as a source")
        self.companion_orb_sensory_target_checkbox.setObjectName("companion_orb_sensory_target_checkbox")
        self.companion_orb_sensory_target_checkbox.setToolTip(
            "Uses the Companion Orb selected window/region as a background source. "
            "It never silently falls back to full-screen capture."
        )
        self.companion_orb_sensory_target_checkbox.setChecked(bool(runtime_config.get("companion_orb_sensory_target_enabled", False)))
        self.companion_orb_sensory_target_checkbox.toggled.connect(self.on_companion_orb_sensory_target_changed)

        self.btn_companion_orb_clear_sensory_target = QtWidgets.QPushButton("Clear orb target")
        self.btn_companion_orb_clear_sensory_target.setObjectName("btn_companion_orb_clear_sensory_target")
        self.btn_companion_orb_clear_sensory_target.setToolTip("Clears the selected Companion Orb sensory target.")
        self.btn_companion_orb_clear_sensory_target.clicked.connect(self.clear_companion_orb_sensory_target)

        self.sensory_pingpong_history_spin = ContextTokenStepper()
        self.sensory_pingpong_history_spin.setObjectName("sensory_pingpong_history_spin")
        self.sensory_pingpong_history_spin.setRange(0, 20)
        self.sensory_pingpong_history_spin.setSingleStep(1)
        self.sensory_pingpong_history_spin.setValue(max(0, int(runtime_config.get("sensory_pingpong_history_depth", 3) or 3)))
        self.sensory_pingpong_history_spin.valueChanged.connect(self.on_sensory_pingpong_history_depth_changed)
        self.sensory_pingpong_history_spin.setMinimumWidth(112)
        self.sensory_pingpong_history_spin.setMaximumWidth(132)

        self.sensory_pingpong_prompt_text = QtWidgets.QPlainTextEdit()
        self.sensory_pingpong_prompt_text.setObjectName("sensory_pingpong_prompt_text")
        self.sensory_pingpong_prompt_text.setPlainText(str(runtime_config.get("sensory_pingpong_prompt", getattr(engine_module, "DEFAULT_SENSORY_PINGPONG_PROMPT", "")) or getattr(engine_module, "DEFAULT_SENSORY_PINGPONG_PROMPT", "")))
        self.sensory_pingpong_prompt_text.setPlaceholderText("Advanced background review prompt")
        self.sensory_pingpong_prompt_text.setMinimumHeight(0)
        self.sensory_pingpong_prompt_text.textChanged.connect(self.on_sensory_pingpong_prompt_changed)
        self.btn_sensory_pingpong_prompt_reset = QtWidgets.QPushButton("Restore recommended prompt")
        self.btn_sensory_pingpong_prompt_reset.setObjectName("btn_sensory_pingpong_prompt_reset")
        self.btn_sensory_pingpong_prompt_reset.clicked.connect(self.reset_sensory_pingpong_prompt_to_default)

        built = self._invoke_avatar_legacy_capability(
            "vam",
            "legacy.build_runtime_widgets",
            {"backend": self, "runtime_config": runtime_config},
            default=False,
        )
        if not built:
            ensure_vam_legacy_placeholders(self, runtime_config)

        self.chat_provider_combo = NoWheelComboBox()
        self.chat_provider_combo.setObjectName("chat_provider_combo")
        self._populate_chat_provider_combo(runtime_config.get("chat_provider", _default_chat_provider_id()))
        self.chat_provider_combo.currentTextChanged.connect(self.on_chat_provider_changed)

        self.model_combo = NoWheelComboBox()
        self.model_combo.setObjectName("model_combo")
        self.model_combo.addItem("Scanning...")
        self.model_combo.currentTextChanged.connect(self.on_model_selection_changed)
        self.btn_model_refresh = QtWidgets.QPushButton("Refresh")
        self.btn_model_refresh.setObjectName("btn_model_refresh")
        self.btn_model_refresh.clicked.connect(lambda: self.request_model_list_refresh(quiet=False, wait_for_reachable=True))
        self.model_requires_vision_checkbox = QtWidgets.QCheckBox("Must have image processing capabilities")
        self.model_requires_vision_checkbox.setObjectName("model_requires_vision_checkbox")
        self.model_requires_vision_checkbox.toggled.connect(self.on_model_requires_vision_changed)
        model_row = QtWidgets.QHBoxLayout()
        model_row.setContentsMargins(0, 0, 0, 0)
        model_row.setSpacing(8)
        model_row.addWidget(self.model_combo, 1)
        model_row.addWidget(self.btn_model_refresh, 0)
        model_row_widget = QtWidgets.QWidget()
        model_row_widget.setLayout(model_row)
        model_column = QtWidgets.QVBoxLayout()
        model_column.setContentsMargins(0, 0, 0, 0)
        model_column.setSpacing(4)
        model_column.addWidget(model_row_widget)
        model_column.addWidget(self.model_requires_vision_checkbox)
        self.model_row_widget = QtWidgets.QWidget()
        self.model_row_widget.setLayout(model_column)

        self.preset_combo = NoWheelComboBox()
        self.preset_combo.setObjectName("preset_combo")
        self.preset_combo.addItem("Select Preset...")
        _set_tooltip(self.preset_combo, SYSTEM_SHAPING_TOOLTIPS["preset_combo"])
        self.preset_combo.currentTextChanged.connect(self.on_preset_selection_changed)
        self.btn_preset_refresh = QtWidgets.QPushButton("Refresh")
        self.btn_preset_refresh.setObjectName("btn_preset_refresh")
        _set_tooltip(self.btn_preset_refresh, SYSTEM_SHAPING_TOOLTIPS["btn_preset_refresh"])
        self.btn_preset_refresh.clicked.connect(self.refresh_preset_list)
        preset_row = QtWidgets.QHBoxLayout()
        preset_row.setContentsMargins(0, 0, 0, 0)
        preset_row.setSpacing(8)
        preset_row.addWidget(self.preset_combo, 1)
        preset_row.addWidget(self.btn_preset_refresh, 0)
        preset_row_widget = QtWidgets.QWidget()
        preset_row_widget.setLayout(preset_row)
        self.preset_row_widget = preset_row_widget

        self.allow_proactive_checkbox = QtWidgets.QCheckBox("Allow proactive replies after silence")
        self.allow_proactive_checkbox.setObjectName("allow_proactive_checkbox")
        self.allow_proactive_checkbox.setChecked(bool(runtime_config.get("allow_proactive_replies", False)))
        self.allow_proactive_checkbox.toggled.connect(self.on_allow_proactive_replies_changed)

        self.require_first_user_checkbox = QtWidgets.QCheckBox("Wait for the first user message before any proactive reply")
        self.require_first_user_checkbox.setObjectName("require_first_user_checkbox")
        self.require_first_user_checkbox.setChecked(bool(runtime_config.get("require_first_user_before_proactive", False)))
        self.require_first_user_checkbox.toggled.connect(self.on_require_first_user_before_proactive_changed)

        self.listen_idle_window_spin = DecimalStepper()
        self.listen_idle_window_spin.setObjectName("listen_idle_window_spin")
        self.listen_idle_window_spin.setRange(0.5, 30.0)
        self.listen_idle_window_spin.setSingleStep(0.5)
        self.listen_idle_window_spin.setDecimals(1)
        self.listen_idle_window_spin.setValue(float(runtime_config.get("listen_idle_window_seconds", 5.0) or 5.0))
        self.listen_idle_window_spin.valueChanged.connect(self.on_listen_idle_window_changed)
        self.listen_idle_window_spin.setMinimumWidth(112)
        self.listen_idle_window_spin.setMaximumWidth(132)

        self.proactive_delay_spin = DecimalStepper()
        self.proactive_delay_spin.setObjectName("proactive_delay_spin")
        self.proactive_delay_spin.setRange(0.5, 180.0)
        self.proactive_delay_spin.setSingleStep(0.5)
        self.proactive_delay_spin.setDecimals(1)
        self.proactive_delay_spin.setValue(float(runtime_config.get("proactive_delay_seconds", 10.0) or 10.0))
        self.proactive_delay_spin.valueChanged.connect(self.on_proactive_delay_changed)
        self.proactive_delay_spin.setMinimumWidth(112)
        self.proactive_delay_spin.setMaximumWidth(132)

        self.chat_context_window_spin = ContextTokenStepper()
        self.chat_context_window_spin.setObjectName("chat_context_window_spin")
        self.chat_context_window_spin.setRange(4, 2147483647)
        self.chat_context_window_spin.setSingleStep(1)
        self.chat_context_window_spin.setValue(int(runtime_config.get("chat_context_window_messages", 20) or 20))
        self.chat_context_window_spin.valueChanged.connect(self.on_chat_context_window_changed)
        self.chat_context_window_spin.setMinimumWidth(112)
        self.chat_context_window_spin.setMaximumWidth(132)

        self.stored_chat_history_limit_spin = ContextTokenStepper()
        self.stored_chat_history_limit_spin.setObjectName("stored_chat_history_limit_spin")
        self.stored_chat_history_limit_spin.setRange(0, 5000)
        self.stored_chat_history_limit_spin.setSingleStep(1)
        self.stored_chat_history_limit_spin.setValue(max(0, int(runtime_config.get("stored_chat_history_limit", 0) or 0)))
        self.stored_chat_history_limit_spin.valueChanged.connect(self.on_stored_chat_history_limit_changed)
        self.stored_chat_history_limit_spin.setMinimumWidth(112)
        self.stored_chat_history_limit_spin.setMaximumWidth(132)

        self.chat_overflow_policy_combo = NoWheelComboBox()
        self.chat_overflow_policy_combo.setObjectName("chat_overflow_policy_combo")
        self.chat_overflow_policy_combo.addItems(["Rolling Window", "Truncate Middle", "Stop At Limit"])
        self.chat_overflow_policy_combo.setCurrentText(self._chat_overflow_policy_label_from_value(runtime_config.get("chat_context_overflow_policy", "rolling_window")))
        self.chat_overflow_policy_combo.currentTextChanged.connect(self.on_chat_overflow_policy_changed)

        self.spellcheck_enabled_checkbox = QtWidgets.QCheckBox("Enable spell checking")
        self.spellcheck_enabled_checkbox.setObjectName("spellcheck_enabled_checkbox")
        self.spellcheck_enabled_checkbox.setChecked(bool(runtime_config.get("spellcheck_enabled", True)))
        self.spellcheck_enabled_checkbox.toggled.connect(self.on_spellcheck_enabled_changed)

        self.spellcheck_language_combo = NoWheelComboBox()
        self.spellcheck_language_combo.setObjectName("spellcheck_language_combo")
        try:
            from ui.runtime.spellcheck import available_languages

            languages = available_languages()
        except Exception:
            languages = []
        selected_spellcheck_language = str(runtime_config.get("spellcheck_language", "en_US") or "en_US").strip() or "en_US"
        if selected_spellcheck_language not in languages:
            languages.insert(0, selected_spellcheck_language)
        for language in languages or [selected_spellcheck_language]:
            self.spellcheck_language_combo.addItem(str(language or "en_US"))
        self.spellcheck_language_combo.setCurrentText(selected_spellcheck_language)
        self.spellcheck_language_combo.currentTextChanged.connect(self.on_spellcheck_language_changed)
        self.spellcheck_language_combo.setMinimumWidth(112)
        self.spellcheck_language_combo.setMaximumWidth(180)

        self.btn_install_spellcheck_dependency = QtWidgets.QPushButton("Install PyEnchant")
        self.btn_install_spellcheck_dependency.setObjectName("btn_install_spellcheck_dependency")
        self.btn_install_spellcheck_dependency.clicked.connect(self.on_install_spellcheck_dependency_requested)
        self.btn_install_spellcheck_dependency.setVisible(False)

        self.spellcheck_dependency_hint = QtWidgets.QLabel("")
        self.spellcheck_dependency_hint.setObjectName("spellcheck_dependency_hint")
        self.spellcheck_dependency_hint.setWordWrap(True)
        self.spellcheck_dependency_hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        self.spellcheck_dependency_hint.setVisible(False)
        self._refresh_spellcheck_dependency_controls()

        self.long_term_memory_enabled_checkbox = QtWidgets.QCheckBox("Enable continuity memory summary")
        self.long_term_memory_enabled_checkbox.setObjectName("long_term_memory_enabled_checkbox")
        self.long_term_memory_enabled_checkbox.setChecked(bool(runtime_config.get("continuity_memory_enabled", runtime_config.get("long_term_memory_enabled", False))))
        self.long_term_memory_enabled_checkbox.toggled.connect(self.on_long_term_memory_enabled_changed)

        self.long_term_memory_update_on_save_checkbox = QtWidgets.QCheckBox("Auto summarize at interval")
        self.long_term_memory_update_on_save_checkbox.setObjectName("long_term_memory_update_on_save_checkbox")
        self.long_term_memory_update_on_save_checkbox.setChecked(bool(runtime_config.get("continuity_memory_auto_summarize", runtime_config.get("continuity_memory_update_on_save", runtime_config.get("long_term_memory_update_on_save", False)))))
        self.long_term_memory_update_on_save_checkbox.toggled.connect(self.on_long_term_memory_update_on_save_changed)

        self.long_term_memory_inject_checkbox = QtWidgets.QCheckBox("Inject continuity summary into chat")
        self.long_term_memory_inject_checkbox.setObjectName("long_term_memory_inject_checkbox")
        self.long_term_memory_inject_checkbox.setChecked(bool(runtime_config.get("continuity_memory_inject", runtime_config.get("long_term_memory_inject", False))))
        self.long_term_memory_inject_checkbox.toggled.connect(self.on_long_term_memory_inject_changed)

        self.continuity_memory_auto_turns_spin = ContextTokenStepper()
        self.continuity_memory_auto_turns_spin.setObjectName("continuity_memory_auto_turns_spin")
        self.continuity_memory_auto_turns_spin.setRange(1, 10000)
        self.continuity_memory_auto_turns_spin.setSingleStep(10)
        self.continuity_memory_auto_turns_spin.setValue(max(1, min(10000, int(runtime_config.get("continuity_memory_auto_turns", 120) or 120))))
        self.continuity_memory_auto_turns_spin.valueChanged.connect(self.on_continuity_memory_auto_turns_changed)
        self.continuity_memory_auto_turns_spin.setMinimumWidth(112)
        self.continuity_memory_auto_turns_spin.setMaximumWidth(132)

        self.long_term_memory_max_chars_spin = ContextTokenStepper()
        self.long_term_memory_max_chars_spin.setObjectName("long_term_memory_max_chars_spin")
        self.long_term_memory_max_chars_spin.setRange(500, 20000)
        self.long_term_memory_max_chars_spin.setSingleStep(250)
        self.long_term_memory_max_chars_spin.setValue(max(500, int(runtime_config.get("continuity_memory_max_chars", runtime_config.get("long_term_memory_max_chars", 3000)) or 3000)))
        self.long_term_memory_max_chars_spin.valueChanged.connect(self.on_long_term_memory_max_chars_changed)
        self.long_term_memory_max_chars_spin.setMinimumWidth(112)
        self.long_term_memory_max_chars_spin.setMaximumWidth(132)

        self.btn_review_long_term_memory = QtWidgets.QPushButton("Review Summary")
        self.btn_review_long_term_memory.setObjectName("btn_review_long_term_memory")
        self.btn_review_long_term_memory.clicked.connect(self.review_long_term_memory)

        self.btn_batch_update_long_term_memory = QtWidgets.QPushButton("Summarize Recent...")
        self.btn_batch_update_long_term_memory.setObjectName("btn_batch_update_long_term_memory")
        self.btn_batch_update_long_term_memory.clicked.connect(self.batch_update_long_term_memory_now)

        self.btn_forget_long_term_memory = QtWidgets.QPushButton("Forget Summary")
        self.btn_forget_long_term_memory.setObjectName("btn_forget_long_term_memory")
        self.btn_forget_long_term_memory.clicked.connect(self.forget_long_term_memory)

        self.long_term_memory_hint = QtWidgets.QLabel()
        self.long_term_memory_hint.setObjectName("long_term_memory_hint")
        self.long_term_memory_hint.setWordWrap(True)
        self.long_term_memory_hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        self._refresh_long_term_memory_hint()

        self.btn_review_long_term_memory_archive = QtWidgets.QPushButton("Review Archive")
        self.btn_review_long_term_memory_archive.setObjectName("btn_review_long_term_memory_archive")
        self.btn_review_long_term_memory_archive.clicked.connect(self.review_long_term_memory_archive)

        self.btn_search_long_term_memory_archive = QtWidgets.QPushButton("Search Archive...")
        self.btn_search_long_term_memory_archive.setObjectName("btn_search_long_term_memory_archive")
        self.btn_search_long_term_memory_archive.clicked.connect(self.search_long_term_memory_archive)

        self.long_term_memory_retrieval_enabled_checkbox = QtWidgets.QCheckBox("Use archive retrieval in chat")
        self.long_term_memory_retrieval_enabled_checkbox.setObjectName("long_term_memory_retrieval_enabled_checkbox")
        self.long_term_memory_retrieval_enabled_checkbox.setChecked(bool(runtime_config.get("long_term_memory_retrieval_enabled", False)))
        self.long_term_memory_retrieval_enabled_checkbox.toggled.connect(self.on_long_term_memory_retrieval_enabled_changed)

        self.long_term_memory_retrieval_max_items_spin = ContextTokenStepper()
        self.long_term_memory_retrieval_max_items_spin.setObjectName("long_term_memory_retrieval_max_items_spin")
        self.long_term_memory_retrieval_max_items_spin.setRange(1, 12)
        self.long_term_memory_retrieval_max_items_spin.setSingleStep(1)
        self.long_term_memory_retrieval_max_items_spin.setValue(max(1, min(12, int(runtime_config.get("long_term_memory_retrieval_max_items", 6) or 6))))
        self.long_term_memory_retrieval_max_items_spin.valueChanged.connect(self.on_long_term_memory_retrieval_max_items_changed)
        self.long_term_memory_retrieval_max_items_spin.setMinimumWidth(112)
        self.long_term_memory_retrieval_max_items_spin.setMaximumWidth(132)

        self.long_term_memory_archive_batch_turns_spin = ContextTokenStepper()
        self.long_term_memory_archive_batch_turns_spin.setObjectName("long_term_memory_archive_batch_turns_spin")
        self.long_term_memory_archive_batch_turns_spin.setRange(1, 10000)
        self.long_term_memory_archive_batch_turns_spin.setSingleStep(10)
        self.long_term_memory_archive_batch_turns_spin.setValue(max(1, min(10000, int(runtime_config.get("long_term_memory_archive_batch_turns", 120) or 120))))
        self.long_term_memory_archive_batch_turns_spin.valueChanged.connect(self.on_long_term_memory_archive_batch_turns_changed)
        self.long_term_memory_archive_batch_turns_spin.setMinimumWidth(112)
        self.long_term_memory_archive_batch_turns_spin.setMaximumWidth(132)

        self.long_term_memory_embedding_enabled_checkbox = QtWidgets.QCheckBox("Use LM Studio embeddings for semantic retrieval")
        self.long_term_memory_embedding_enabled_checkbox.setObjectName("long_term_memory_embedding_enabled_checkbox")
        self.long_term_memory_embedding_enabled_checkbox.setChecked(bool(runtime_config.get("long_term_memory_embedding_enabled", False)))
        self.long_term_memory_embedding_enabled_checkbox.toggled.connect(self.on_long_term_memory_embedding_enabled_changed)

        self.long_term_memory_embedding_model_edit = NoWheelComboBox()
        self.long_term_memory_embedding_model_edit.setObjectName("long_term_memory_embedding_model_edit")
        self.long_term_memory_embedding_model_edit.setEditable(True)
        self.long_term_memory_embedding_model_edit.addItem(str(runtime_config.get("long_term_memory_embedding_model", "text-embedding-bge-m3") or "text-embedding-bge-m3"))
        self.long_term_memory_embedding_model_edit.currentTextChanged.connect(self.on_long_term_memory_embedding_model_changed)
        self.long_term_memory_embedding_model_edit.setMinimumWidth(220)

        self.btn_long_term_memory_embedding_model_refresh = QtWidgets.QPushButton("Refresh")
        self.btn_long_term_memory_embedding_model_refresh.setObjectName("btn_long_term_memory_embedding_model_refresh")
        self.btn_long_term_memory_embedding_model_refresh.clicked.connect(self.refresh_long_term_memory_embedding_models)

        self.long_term_memory_embedding_context_length_spin = ContextTokenStepper()
        self.long_term_memory_embedding_context_length_spin.setObjectName("long_term_memory_embedding_context_length_spin")
        self.long_term_memory_embedding_context_length_spin.setRange(512, 262144)
        self.long_term_memory_embedding_context_length_spin.setSingleStep(512)
        self.long_term_memory_embedding_context_length_spin.setValue(max(512, min(262144, int(runtime_config.get("long_term_memory_embedding_context_length", 8192) or 8192))))
        self.long_term_memory_embedding_context_length_spin.valueChanged.connect(self.on_long_term_memory_embedding_context_length_changed)
        self.long_term_memory_embedding_context_length_spin.setMinimumWidth(112)
        self.long_term_memory_embedding_context_length_spin.setMaximumWidth(132)

        self.long_term_memory_embedding_base_url_edit = QtWidgets.QLineEdit(str(runtime_config.get("long_term_memory_embedding_base_url", "http://127.0.0.1:1234/v1") or "http://127.0.0.1:1234/v1"))
        self.long_term_memory_embedding_base_url_edit.setObjectName("long_term_memory_embedding_base_url_edit")
        self.long_term_memory_embedding_base_url_edit.editingFinished.connect(self.on_long_term_memory_embedding_base_url_changed)
        self.long_term_memory_embedding_base_url_edit.setMinimumWidth(220)

        self.long_term_memory_archive_hint = QtWidgets.QLabel()
        self.long_term_memory_archive_hint.setObjectName("long_term_memory_archive_hint")
        self.long_term_memory_archive_hint.setWordWrap(True)
        self.long_term_memory_archive_hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        self._refresh_long_term_memory_archive_hint()

        self.btn_save_chat_session = QtWidgets.QPushButton("Save Chat Context")
        self.btn_save_chat_session.setObjectName("btn_save_chat_session")
        self.btn_save_chat_session.setEnabled(bool(str(runtime_config.get("active_chat_context_path", "") or "").strip()))
        self.btn_save_chat_session.clicked.connect(self.save_chat_context)

        self.btn_save_chat_session_as = QtWidgets.QPushButton("Save Chat Context As...")
        self.btn_save_chat_session_as.setObjectName("btn_save_chat_session_as")
        self.btn_save_chat_session_as.clicked.connect(self.save_chat_context_as)

        self.btn_load_chat_session = QtWidgets.QPushButton("Load Chat Context")
        self.btn_load_chat_session.setObjectName("btn_load_chat_session")
        self.btn_load_chat_session.clicked.connect(self.load_chat_context)

        self.btn_reset_chat_session = QtWidgets.QPushButton("Reset Chat Memory")
        self.btn_reset_chat_session.setObjectName("btn_reset_chat_session")
        self.btn_reset_chat_session.clicked.connect(self.reset_chat_session)

        self.chat_session_hint = QtWidgets.QLabel()
        self.chat_session_hint.setObjectName("chat_session_hint")
        self.chat_session_hint.setWordWrap(True)
        self.chat_session_hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        self._apply_chat_tab_tooltips()

        self.refresh_musetalk_avatar_pack_list()

        self.host_settings_tabs = NoWheelTabWidget()
        self.host_settings_tabs.setObjectName("host_settings_tabs")
        self.host_settings_tabs.setMinimumSize(0, 0)
        self.host_settings_tabs.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Maximum)
        self.host_settings_tabs.currentChanged.connect(lambda _index, tabs=self.host_settings_tabs: self._sync_tab_widget_height(tabs))
        self.host_settings_tabs.addTab(self._build_runtime_shell_tab(), "Host")
        self.host_settings_tabs.addTab(self._build_sensory_feedback_tab(), "Vision")
        self.host_settings_tabs.addTab(self._build_chat_session_tab(), "Chat")
        layout.addWidget(self.host_settings_tabs, 0, QtCore.Qt.AlignTop)
        QtCore.QTimer.singleShot(0, lambda tabs=self.host_settings_tabs: self._sync_tab_widget_height(tabs))
        layout.addStretch(1)

        self.tabs = NoWheelTabWidget()
        self.tabs.setObjectName("left_tabs")
        self.tabs.setMinimumSize(0, 0)
        self.tabs.currentChanged.connect(self._on_left_tab_changed)
        self.tabs.addTab(self._build_persona_tab(), "Persona")
        self._legacy_brain_tab = self._build_brain_tab()
        self._legacy_brain_tab.setVisible(False)
        self.tabs.addTab(self._build_chunking_tab(), "Chunking")
        self.tabs.addTab(self._build_dry_run_tab(), "Dry Run")
        self.tabs.addTab(self._build_tutorials_tab(), "Tutorials")
        self.tabs.addTab(self._build_addons_tab(), "Addons")
        self.tabs.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Ignored)
        workspace_panel = self._wrap_panel()
        workspace_panel.setMinimumSize(0, 0)
        workspace_panel.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Ignored)
        workspace_outer_layout = QtWidgets.QVBoxLayout(workspace_panel)
        workspace_outer_layout.setContentsMargins(0, 0, 0, 0)
        workspace_outer_layout.setSpacing(0)
        workspace_outer_layout.addWidget(self.tabs, 1)

        return shaping_panel, workspace_panel

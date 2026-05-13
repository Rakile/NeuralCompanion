from PySide6 import QtCore, QtWidgets

from ui.runtime.shell_session_config import _ui_shell_combo_select_label, _ui_shell_combo_set_items
from ui.runtime.shell_status_layout import _ui_shell_audio_device_labels
from ui.runtime.shell_addon_services import addon_id_for_service, addon_id_for_ui_role
from ui.runtime.addon_disabled_placeholders import (
    ensure_musetalk_legacy_placeholders,
    ensure_vam_legacy_placeholders,
    ensure_visual_reply_legacy_placeholders,
)
from ui.shell_specs import UI_SHELL_DEFAULT_CHUNKING_VALUES
from ui.widgets.basic import CollapsibleSection, ContextTokenStepper, DecimalStepper, NoWheelComboBox, NoWheelSpinBox, NoWheelTabWidget


from ui.runtime.engine_access import engine_module as _engine


def _update_runtime_config(key, value):
    from ui.runtime.engine_access import update_runtime_config

    return update_runtime_config(key, value)


def _default_chat_provider_id():
    from core import chat_providers

    return chat_providers.DEFAULT_PROVIDER_ID


SYSTEM_SHAPING_TOOLTIPS = {
    "engine_combo": "Avatar output provider. Use None for voice/chat only, or choose MuseTalk/VSeeFace/VaM when that addon/runtime is configured.",
    "input_mode_combo": "How user turns enter the session. Voice Activation listens after startup; Push-to-Talk only listens while the hotkey/button is held.",
    "input_role_combo": "Chat role used for live input. User Message is normal; System/Assistant are advanced prompt-routing modes.",
    "stream_mode_combo": "When On, NC streams the model reply and starts chunked TTS sooner. When Off, NC waits for the full reply first.",
    "musetalk_loop_fade_spin": "MuseTalk preview crossfade duration when switching avatar/emotion frames. 0 disables the fade; higher values smooth changes but can delay visible updates.",
    "musetalk_use_frame_cache_checkbox": "Use/create MuseTalk NumPy frame caches for faster avatar startup. Disable to save disk space and always read PNG frames.",
    "musetalk_avatar_pack_combo": "Prepared MuseTalk avatar pack and variant used for rendering visual speech.",
    "btn_musetalk_avatar_pack_refresh": "Rescan installed MuseTalk avatar packs under avatar_packs/.",
    "preset_combo": "Saved companion preset. Presets store persona/runtime choices such as model, voice, avatar, and generation settings.",
    "btn_preset_refresh": "Reload the preset list from disk.",
}


def _set_tooltip(widget, text):
    if widget is not None and hasattr(widget, "setToolTip"):
        widget.setToolTip(str(text or "").strip())


class BackendSystemShapingPanelMixin:
    """Build the backend System Shaping and Workspace panels."""

class BackendSystemShapingBuilderMixin:
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
        addon_id = addon_id_for_service("avatar_provider_registry", provider_id=provider)
        if not addon_id:
            return default
        result = self._invoke_addon_service_capability(
            "avatar_provider_registry",
            capability,
            payload,
            default=None,
            provider_id=provider,
        )
        if result is not None:
            return result
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
        form.addRow("Preset", self.preset_row_widget if hasattr(self, "preset_row_widget") else self.preset_combo)
        layout.addLayout(form)
        self._refresh_musetalk_vram_visibility()
        layout.addWidget(self._build_chat_runtime_card())
        layout.addWidget(self._build_tts_runtime_card())

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
            if object_name == "btn_preset_save":
                self.btn_preset_save = button
            elif object_name == "btn_preset_save_as":
                self.btn_preset_save_as = button
            preset_buttons.addWidget(button)
        layout.addLayout(preset_buttons)

        self.input_mode_hint = QtWidgets.QLabel("Push-to-Talk hotkey: Right Ctrl (fallback button below)")
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

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignLeft)
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)
        form.setFormAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        form.addRow("Chat Provider", self.chat_provider_combo)
        form.addRow("LLM Model", self.model_row_widget)
        inner_layout.addLayout(form)

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
        self.chat_runtime_section = CollapsibleSection("Chat Runtime", self.chat_runtime_box, expanded=True)
        self.chat_runtime_section.toggle_button.toggled.connect(lambda _checked: self._on_runtime_section_toggled())
        self._refresh_chat_runtime_summary()
        return self.chat_runtime_section

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
        self.tts_runtime_addon_tabs.setDocumentMode(True)
        self.tts_runtime_addon_tabs.setMinimumHeight(420)
        self.tts_runtime_addon_tabs.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
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
        self.sensory_feedback_tabs.currentChanged.connect(lambda _index, tabs=self.sensory_feedback_tabs: self._sync_tab_widget_height(tabs))

        core_tab = QtWidgets.QWidget()
        core_layout = QtWidgets.QVBoxLayout(core_tab)
        core_layout.setContentsMargins(8, 8, 8, 8)
        core_layout.setSpacing(10)

        sensory_box = QtWidgets.QGroupBox("Hidden Sensory Feedback")
        sensory_layout = QtWidgets.QVBoxLayout(sensory_box)
        sensory_layout.setContentsMargins(12, 14, 12, 12)
        sensory_layout.setSpacing(8)

        sensory_form = QtWidgets.QFormLayout()
        sensory_form.setLabelAlignment(QtCore.Qt.AlignLeft)
        sensory_form.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldsStayAtSizeHint)
        sensory_form.setFormAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        sensory_form.addRow("Include", self.sensory_feedback_sources_widget)
        sensory_form.addRow("Refresh (s)", self._wrap_compact_form_field(self.sensory_feedback_interval_spin))
        sensory_form.addRow("Retain PONGs", self._wrap_compact_form_field(self.sensory_pingpong_history_spin))
        sensory_layout.addWidget(self.sensory_pingpong_checkbox)
        sensory_layout.addWidget(self.sensory_allow_hidden_proactive_checkbox)
        sensory_layout.addWidget(self.sensory_allow_hidden_visual_checkbox)
        sensory_layout.addLayout(sensory_form)

        self.sensory_feedback_hint = QtWidgets.QLabel()
        self.sensory_feedback_hint.setObjectName("sensory_feedback_hint")
        self.sensory_feedback_hint.setWordWrap(True)
        self.sensory_feedback_hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        sensory_layout.addWidget(self.sensory_feedback_hint)
        self._refresh_sensory_feedback_hint()

        self.sensory_pingpong_prompt_label = QtWidgets.QLabel("Core Hidden PING/PONG Prompt")
        self.sensory_pingpong_prompt_label.setStyleSheet("color: #9fb3c8; font-size: 11px; font-weight: 600;")
        prompt_header = QtWidgets.QHBoxLayout()
        prompt_header.setContentsMargins(0, 0, 0, 0)
        prompt_header.setSpacing(8)
        prompt_header.addWidget(self.sensory_pingpong_prompt_label)
        prompt_header.addStretch(1)
        prompt_header.addWidget(self.btn_sensory_pingpong_prompt_reset, 0)
        sensory_layout.addLayout(prompt_header)
        sensory_layout.addWidget(self.sensory_pingpong_prompt_text)

        self.sensory_pingpong_prompt_hint = QtWidgets.QLabel("Core prompt defines the shared JSON contract. Source tabs add source-specific guidance. Use __EMOTION_LIST__ to inject the currently available avatar emotion tags.")
        self.sensory_pingpong_prompt_hint.setWordWrap(True)
        self.sensory_pingpong_prompt_hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        sensory_layout.addWidget(self.sensory_pingpong_prompt_hint)

        core_layout.addWidget(sensory_box)
        self.sensory_feedback_tabs.addTab(core_tab, "Core")
        self._refresh_sensory_feedback_source_tabs()
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
        behavior_layout.addLayout(timing_form)
        behavior_layout.addWidget(self.chat_session_hint)
        layout.addWidget(behavior_box)

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
        button_row.addWidget(self.btn_load_chat_session)
        button_row.addWidget(self.btn_reset_chat_session)
        button_row.addStretch(1)
        actions_layout.addLayout(button_row)
        layout.addWidget(actions_box)

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

        audio_devices = _ui_shell_audio_device_labels()
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
        self.input_mode_combo.addItems(["Voice Activation", "Push-to-Talk"])
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

        self.sensory_pingpong_checkbox = QtWidgets.QCheckBox("Enable hidden PING/PONG loop")
        self.sensory_pingpong_checkbox.setObjectName("sensory_pingpong_checkbox")
        self.sensory_pingpong_checkbox.setChecked(bool(runtime_config.get("sensory_pingpong_enabled", False)))
        self.sensory_pingpong_checkbox.toggled.connect(self.on_sensory_pingpong_enabled_changed)

        self.sensory_allow_hidden_proactive_checkbox = QtWidgets.QCheckBox("Allow hidden PONGs to trigger proactive speech")
        self.sensory_allow_hidden_proactive_checkbox.setObjectName("sensory_allow_hidden_proactive_checkbox")
        self.sensory_allow_hidden_proactive_checkbox.setChecked(bool(runtime_config.get("sensory_allow_hidden_proactive_speech", False)))
        self.sensory_allow_hidden_proactive_checkbox.toggled.connect(self.on_sensory_allow_hidden_proactive_changed)

        self.sensory_allow_hidden_visual_checkbox = QtWidgets.QCheckBox("Allow NC to generate visual replies automatically")
        self.sensory_allow_hidden_visual_checkbox.setObjectName("sensory_allow_hidden_visual_checkbox")
        self.sensory_allow_hidden_visual_checkbox.setChecked(bool(runtime_config.get("sensory_allow_hidden_visual_generation", False)))
        self.sensory_allow_hidden_visual_checkbox.toggled.connect(self.on_sensory_allow_hidden_visual_changed)

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
        self.sensory_pingpong_prompt_text.setPlaceholderText("Hidden PING/PONG prompt")
        self.sensory_pingpong_prompt_text.setMinimumHeight(0)
        self.sensory_pingpong_prompt_text.textChanged.connect(self.on_sensory_pingpong_prompt_changed)
        self.btn_sensory_pingpong_prompt_reset = QtWidgets.QPushButton("Use Recommended")
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

        self.btn_save_chat_session = QtWidgets.QPushButton("Save Chat Context")
        self.btn_save_chat_session.setObjectName("btn_save_chat_session")
        self.btn_save_chat_session.clicked.connect(self.save_chat_context)

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

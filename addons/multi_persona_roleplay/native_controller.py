from __future__ import annotations

import copy
import hashlib
import html
import json
import math
import platform
import queue
import re
import shutil
import struct
import threading
import time
import wave
import zipfile
from pathlib import Path
from typing import Any, Callable

from PySide6 import QtCore, QtGui

from addons.multi_persona_roleplay.audio_prompts import AUDIO_TYPES, create_audio_prompt
from addons.multi_persona_roleplay import instructor_adapter
from addons.multi_persona_roleplay import prompting
from addons.multi_persona_roleplay import story_director
from addons.multi_persona_roleplay import structured_models
from addons.multi_persona_roleplay.chromecast_bridge import DEFAULT_MPRC_CAST_STREAM_PORT, MprcChromecastBridge
from addons.multi_persona_roleplay.models import (
    AR_DIALOGUE_DENSITY_MODES,
    AR_INTERACTION_FREQUENCIES,
    AR_MODE,
    AR_PACING_MODES,
    BEHAVIOR_MODES,
    MEMORY_SCOPES,
    SESSION_MODES,
    SESSION_MODE_DESCRIPTIONS,
    VISUAL_MODE_DESCRIPTIONS,
    VISUAL_MODE_LABELS,
    VISUAL_MODES,
    VISUAL_PROVIDERS,
    VISUAL_SIZES,
    VOICE_BACKENDS,
    PersonaConfig,
    RoleplaySessionState,
    normalize_persona_id,
    personas_from_payload,
    unique_persona_id,
)
from addons.multi_persona_roleplay.long_memory import RoleplayLongMemory
from addons.multi_persona_roleplay.remote_backend import DEFAULT_REMOTE_PORT, MPRCRemoteBackend, generate_remote_code, lan_ip_address
from addons.multi_persona_roleplay.roleplay_engine import RoleplayEngine
from addons.multi_persona_roleplay.storage import RoleplayStorage
from addons.multi_persona_roleplay.structured_output import STRUCTURED_STORY_SCHEMA_VERSION, build_structured_story_output_schema
from addons.multi_persona_roleplay.visual_reply_runtime import PersonaVisualReply
from addons.multi_persona_roleplay.voice_routing import PersonaVoiceRouter, VOICE_REFERENCE_BACKENDS, normalize_tts_backend


class _MprcRefineBridge(QtCore.QObject):
    finished = QtCore.Signal(str, str, str, str)

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.finished.connect(self._on_finished)

    @QtCore.Slot(str, str, str, str)
    def _on_finished(self, token: str, field_label: str, refined_text: str, error: str):
        controller = getattr(self, "controller", None)
        if controller is not None:
            controller._on_field_refined(str(token or ""), str(field_label or ""), str(refined_text or ""), str(error or ""))


class _MprcStoryBridge(QtCore.QObject):
    finished = QtCore.Signal(str, str, str)

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.finished.connect(self._on_finished)

    @QtCore.Slot(str, str, str)
    def _on_finished(self, token: str, payload_text: str, error: str):
        controller = getattr(self, "controller", None)
        if controller is not None:
            controller._on_master_story_generated(str(token or ""), str(payload_text or ""), str(error or ""))


class _MprcChatTurnBridge(QtCore.QObject):
    finished = QtCore.Signal(str, str, str)

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.finished.connect(self._on_finished)

    @QtCore.Slot(str, str, str)
    def _on_finished(self, token: str, reply_text: str, error: str):
        controller = getattr(self, "controller", None)
        if controller is not None:
            controller._on_mprc_chat_turn_finished(str(token or ""), str(reply_text or ""), str(error or ""))


class _MprcVoicePreviewBridge(QtCore.QObject):
    finished = QtCore.Signal(str, str)

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.finished.connect(self._on_finished)

    @QtCore.Slot(str, str)
    def _on_finished(self, token: str, error: str):
        controller = getattr(self, "controller", None)
        if controller is not None:
            controller._on_voice_preview_finished(str(token or ""), str(error or ""))


class _MprcObjectResultBridge(QtCore.QObject):
    finished = QtCore.Signal(object, object)

    def __init__(self, callback, parent=None):
        super().__init__(parent)
        self._callback = callback
        self.finished.connect(self._on_finished)

    @QtCore.Slot(object, object)
    def _on_finished(self, key, result):
        callback = getattr(self, "_callback", None)
        if callable(callback):
            callback(key, result)


class _MprcStoryAudioBridge(QtCore.QObject):
    play_requested = QtCore.Signal(object)

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.play_requested.connect(self._on_play_requested)

    @QtCore.Slot(object)
    def _on_play_requested(self, entry):
        controller = getattr(self, "controller", None)
        if controller is not None and not controller.is_shutdown():
            controller._play_story_audio_entry(entry)


class _MprcUiBridge(QtCore.QObject):
    refresh_requested = QtCore.Signal()
    debug_refresh_requested = QtCore.Signal()
    event_log_refresh_requested = QtCore.Signal()
    visual_reply_requested = QtCore.Signal(str, str)
    tts_character_image_requested = QtCore.Signal(str)
    tts_visual_reply_requested = QtCore.Signal(str, str)
    manual_visual_finished = QtCore.Signal(str, str, object)
    remote_request = QtCore.Signal(object)
    shutdown_requested = QtCore.Signal()

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.refresh_requested.connect(self._on_refresh_requested)
        self.debug_refresh_requested.connect(self._on_debug_refresh_requested)
        self.event_log_refresh_requested.connect(self._on_event_log_refresh_requested)
        self.visual_reply_requested.connect(self._on_visual_reply_requested)
        self.tts_character_image_requested.connect(self._on_tts_character_image_requested)
        self.tts_visual_reply_requested.connect(self._on_tts_visual_reply_requested)
        self.manual_visual_finished.connect(self._on_manual_visual_finished)
        self.remote_request.connect(self._on_remote_request)
        self.shutdown_requested.connect(self._on_shutdown_requested)

    @QtCore.Slot()
    def _on_refresh_requested(self):
        controller = getattr(self, "controller", None)
        if controller is not None and not controller.is_shutdown():
            controller.refresh_ui()

    @QtCore.Slot()
    def _on_debug_refresh_requested(self):
        controller = getattr(self, "controller", None)
        if controller is not None and not controller.is_shutdown():
            controller._refresh_debug()

    @QtCore.Slot()
    def _on_event_log_refresh_requested(self):
        controller = getattr(self, "controller", None)
        if controller is not None and not controller.is_shutdown():
            controller._refresh_event_log_panel()

    @QtCore.Slot(str, str)
    def _on_visual_reply_requested(self, persona_id: str, reason: str):
        controller = getattr(self, "controller", None)
        if controller is not None and not controller.is_shutdown():
            controller._queue_visual_worker(
                "mprc_visual_reply",
                lambda commit_guard: controller._run_auto_visual_reply_request(
                    str(persona_id or ""),
                    str(reason or "manual"),
                    commit_guard=commit_guard,
                ),
            )

    @QtCore.Slot(str)
    def _on_tts_character_image_requested(self, persona_id: str):
        controller = getattr(self, "controller", None)
        if controller is not None and not controller.is_shutdown():
            controller._queue_visual_worker(
                "mprc_tts_character_image",
                lambda commit_guard: controller._run_tts_character_image_request(
                    str(persona_id or ""),
                    commit_guard=commit_guard,
                ),
            )

    @QtCore.Slot(str, str)
    def _on_tts_visual_reply_requested(self, persona_id: str, spoken_text: str):
        controller = getattr(self, "controller", None)
        if controller is not None and not controller.is_shutdown():
            controller._queue_visual_worker(
                "mprc_tts_visual_reply",
                lambda commit_guard: controller._run_tts_visual_reply_request(
                    str(persona_id or ""),
                    str(spoken_text or ""),
                    commit_guard=commit_guard,
                ),
            )

    @QtCore.Slot(str, str, object)
    def _on_manual_visual_finished(self, kind: str, persona_id: str, result):
        controller = getattr(self, "controller", None)
        if controller is not None and not controller.is_shutdown():
            controller._on_manual_visual_finished(str(kind or ""), str(persona_id or ""), result)

    @QtCore.Slot(object)
    def _on_remote_request(self, payload):
        controller = getattr(self, "controller", None)
        if controller is not None and not controller.is_shutdown():
            controller._handle_remote_thread_request(payload)

    @QtCore.Slot()
    def _on_shutdown_requested(self):
        controller = getattr(self, "controller", None)
        if controller is not None:
            controller._shutdown_qt_objects()


class _VisualCommitAuthority:
    """Admits one short Visual Reply side effect or rejects it after cancellation."""

    def __init__(self, controller, token: str, cancellation) -> None:
        self._controller = controller
        self._token = str(token or "")
        self._cancellation = cancellation

    def __call__(self) -> bool:
        return (
            not self._controller._shutdown_requested.is_set()
            and not bool(getattr(self._cancellation, "cancelled", False))
            and self._controller._worker_should_emit(self._token)
        )

    def run(self, effect):
        admission_scope = getattr(self._cancellation, "admission_scope", None)
        if callable(admission_scope):
            with admission_scope() as admitted:
                if not admitted:
                    return False, None
                return self._controller._run_visual_commit(self._token, effect)
        return self._controller._run_visual_commit(self._token, effect)


class MultiPersonaRoleplayController:
    STATE_KEY = "multi_persona_roleplay"

    def __init__(self, context):
        self.context = context
        self.tasks = context.tasks
        self._state_lock = threading.RLock()
        self._shutting_down = False
        self._shutdown_requested = threading.Event()
        self._visual_commit_lock = threading.RLock()
        self._worker_token_lock = threading.Lock()
        self._worker_sequence = 0
        self._active_worker_tokens: set[str] = set()
        self._assistant_reply_serial_lock = threading.Lock()
        self._state_save_queue_lock = threading.RLock()
        self._state_save_pending = False
        self._state_save_worker_active = False
        self._refine_widgets: dict[str, Any] = {}
        self.storage = RoleplayStorage(context)
        self.storage.ensure_defaults()
        self.personas: list[PersonaConfig] = self.storage.load_personas()
        self.session: RoleplaySessionState = self.storage.load_session()
        self._last_session_export_state: dict[str, Any] = self._session_export_payload_unlocked()
        self.visual_styles = self.storage.load_visual_styles()
        self.settings = self.storage.load_settings()
        self._mprc_play_active = bool(self.settings.get("mprc_play_isolated_active", False)) and bool(self.session.enabled)
        self._ensure_instructor_settings_defaults()
        self._ensure_remote_settings_defaults()
        self._ensure_chromecast_settings_defaults()
        self.long_memory = RoleplayLongMemory(self.storage, logger=getattr(context, "logger", None))
        self.voice_router = PersonaVoiceRouter(self)
        self.roleplay_engine = RoleplayEngine(self)
        self.visual_reply = PersonaVisualReply(self)
        self.visual_reply_service = context.capabilities.visual_reply
        self.dialog_service = context.capabilities.dialogs
        self.runtime_config = context.capabilities.runtime_config
        self.providers = context.capabilities.providers
        self.speech = context.capabilities.speech
        self.playback = context.capabilities.playback
        self.accepted_turns = context.capabilities.accepted_turns
        self.prompt_refinement = context.capabilities.prompt_refinement
        self.runtime_controls = context.capabilities.playback
        self.shell = context.capabilities.shell
        self._debug_prompt = ""
        self._debug_visual_prompt = ""
        self._chat_visual_prompt_debug = ""
        self._debug_voice = ""
        self._validation_result = ""
        self._story_event_log: list[dict[str, str]] = self._load_story_event_log()
        self._visual_debug_log: list[dict[str, str]] = self._load_visual_debug_log()
        self._audiofx_player = None
        self._audiofx_output = None
        self._guide_speech_process = None
        self._guide_speech_command_cache: dict[str, Any] | None = None
        self._guide_speech_command_checked = False
        self._story_audio_block_active = False
        self._story_audio_pending_text = ""
        self._last_story_audio_cues: dict[str, float] = {}
        self._syncing = False
        self._refine_bridge = _MprcRefineBridge(self)
        self._story_bridge = _MprcStoryBridge(self)
        self._chat_turn_bridge = _MprcChatTurnBridge(self)
        self._voice_preview_bridge = _MprcVoicePreviewBridge(self)
        self._story_audio_bridge = _MprcStoryAudioBridge(self)
        self._structured_export_bridge = _MprcObjectResultBridge(self._on_mprc_structured_output_export_finished)
        self._ui_bridge = _MprcUiBridge(self)
        self._adopt_qobject_bridges(self._qt_application_instance())
        self._commit_timers: dict[str, QtCore.QTimer] = {}
        self._master_story_draft: dict[str, Any] = {}
        self._master_story_generation_snapshots: dict[str, dict[str, Any]] = {}
        self._manual_character_image_inflight: set[str] = set()
        self._tts_persona_visual_inflight: set[str] = set()
        self._tts_visual_reply_inflight: set[str] = set()
        self._tts_generation_ids: set[str] = set()
        self._pending_tts_persona_visuals: list[tuple[str, str]] = []
        self._last_tts_visual_reply_at: dict[str, float] = {}
        self._suppress_next_auto_visual_reply = False
        self._mprc_tts_lock = threading.RLock()
        self._mprc_tts_state_lock = threading.RLock()
        self._mprc_tts_controller = None
        self._mprc_tts_token = ""
        self._voice_preview_status_widgets: dict[str, Any] = {}
        self._mprc_chat_history: list[dict[str, str]] = []
        self._mprc_pending_chat_users: dict[str, dict[str, str]] = {}
        self._structured_output_export_token = ""
        self._remote_backend: MPRCRemoteBackend | None = None
        self._remote_latest_reply_text = ""
        self._remote_audio_lock = threading.RLock()
        self._remote_audio_generation = 0
        self._remote_audio_capture_until = 0.0
        self._remote_audio_capture_index = 0
        self._remote_audio_items: list[dict[str, Any]] = []
        self._remote_audio_status = "idle"
        self._remote_audio_source_excerpt = ""
        self._remote_audio_copy_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=64)
        self._remote_audio_copy_worker_active = False
        self._chromecast_bridge = MprcChromecastBridge(self)
        self._chromecast_ui_busy = False
        self._chromecast_ui_status = ""
        self._last_spotify_story_music_key = ""
        self._last_spotify_story_music_at = 0.0
        self._last_spotify_story_music_payload: dict[str, Any] = {}
        self._last_spotify_story_music_result: dict[str, Any] = {}
        self._native_revision = 0
        self._native_last_warning: dict[str, str] = {}
        self._native_pending_confirmation: dict[str, Any] = {}
        self._native_persona_registry: list[dict[str, Any]] = []
        self._native_audio_saved_prompts: list[dict[str, Any]] = []
        self._native_audiofx_items: list[dict[str, Any]] = []
        self._native_audiofx_summary: dict[str, Any] = {}
        self._native_memory_browser: dict[str, Any] = {}
        self._native_character_preview: dict[str, Any] = {}
        self._native_character_roster: list[dict[str, Any]] = []
        self._native_chat_status = "MPRC native play controls are ready."
        self._native_chat_transcript: list[dict[str, Any]] = []
        self._native_chat_speaker: dict[str, Any] = {}
        self._native_chat_line_serial = 0
        self._native_play_controls: dict[str, Any] = {}
        self._native_guide_speech_status = ""
        self._native_master_story_status = ""
        self._native_debug_state: dict[str, Any] = {}
        self._native_story_export_preview: dict[str, Any] = {}
        self._native_story_import_review: dict[str, Any] = {}
        self._native_master_story_apply_review: dict[str, Any] = {}
        self._native_refinement_result: dict[str, Any] = {}
        self._native_clipboard_suggestion = ""
        self._native_remote_controls: dict[str, Any] = {}
        self._native_chromecast_controls: dict[str, Any] = {}
        self._native_story_index: list[dict[str, Any]] = []
        self._native_master_story_actions: dict[str, Any] = {}
        self._native_master_story_image: dict[str, Any] = {}
        self._native_action_result: dict[str, Any] = {}
        self._native_requested_section = ""
        self._native_window_request: dict[str, Any] = {}
        self._native_story_inspector = ""
        self._native_voice_status = ""
        self._ensure_session_persona()
        if self._assign_missing_master_story_voices():
            try:
                self.save_state()
            except Exception as exc:
                logger = getattr(self.context, "logger", None)
                if logger is not None:
                    logger.warning("[MPRC] Deferred state save failed: %s", exc)
        self._sync_remote_backend_from_settings()
        self.refresh_ui()

    def _current_provider_model(self) -> str:
        return str(self.runtime_config.get("model_name", "") or "").strip()

    def _complete_provider_request(
        self,
        params: dict[str, Any],
        additional_params: dict[str, Any] | None = None,
    ) -> str:
        return str(
            self.providers.complete(
                dict(params or {}),
                dict(additional_params or {}),
            )
            or ""
        ).strip()

    def _structured_provider_request(self, params, response_model):
        return self.providers.structured_complete(
            dict(params or {}),
            response_model,
        )

    def _spotify_sense_service(self):
        return self.context.capabilities.music_commands

    def _remote_server_installed(self) -> bool:
        return bool(self.settings.get("remote_server_installed", False))

    def _ensure_remote_settings_defaults(self, *, installed: bool | None = None) -> None:
        changed = False
        installed = self._remote_server_installed() if installed is None else bool(installed)
        if self.settings.get("remote_server_installed") != installed:
            self.settings["remote_server_installed"] = installed
            changed = True
        if self.settings.pop("remote_token", None) is not None:
            changed = True
        if not installed:
            if bool(self.settings.get("remote_enabled", False)):
                self.settings["remote_enabled"] = False
                changed = True
            if changed:
                self.storage.save_settings(self.settings)
            return
        if "remote_enabled" not in self.settings:
            self.settings["remote_enabled"] = False
            changed = True
        if not str(self.settings.get("remote_host") or "").strip():
            self.settings["remote_host"] = "0.0.0.0"
            changed = True
        try:
            port = int(self.settings.get("remote_port", DEFAULT_REMOTE_PORT) or DEFAULT_REMOTE_PORT)
        except Exception:
            port = DEFAULT_REMOTE_PORT
        port = max(1, min(65535, port))
        if self.settings.get("remote_port") != port:
            self.settings["remote_port"] = port
            changed = True
        code = self._normalized_remote_code(self.settings.get("remote_code"))
        if not code:
            self.settings["remote_code"] = generate_remote_code()
            changed = True
        elif self.settings.get("remote_code") != code:
            self.settings["remote_code"] = code
            changed = True
        if changed:
            self.storage.save_settings(self.settings)

    def _ensure_chromecast_settings_defaults(self) -> None:
        changed = False
        if "chromecast_device_name" not in self.settings:
            self.settings["chromecast_device_name"] = ""
            changed = True
        try:
            port = int(self.settings.get("chromecast_stream_port", DEFAULT_MPRC_CAST_STREAM_PORT) or DEFAULT_MPRC_CAST_STREAM_PORT)
        except Exception:
            port = DEFAULT_MPRC_CAST_STREAM_PORT
        port = max(1024, min(65535, port))
        if self.settings.get("chromecast_stream_port") != port:
            self.settings["chromecast_stream_port"] = port
            changed = True
        if changed:
            self.storage.save_settings(self.settings)

    def _ensure_instructor_settings_defaults(self) -> None:
        changed = False
        for key, default_value in structured_models.INSTRUCTOR_SETTING_DEFAULTS.items():
            if key not in self.settings:
                self.settings[key] = default_value
                changed = True
        if changed:
            self.storage.save_settings(self.settings)

    def _mprc_instructor_feature_enabled(self, feature_key: str) -> bool:
        return structured_models.structured_feature_enabled(getattr(self, "settings", {}), feature_key)

    def is_shutdown(self) -> bool:
        with self._state_lock:
            return bool(self._shutting_down)

    @staticmethod
    def _qt_application_instance() -> QtCore.QObject | None:
        try:
            instance = getattr(QtCore.QCoreApplication, "instance", None)
            return instance() if callable(instance) else None
        except Exception:
            return None

    def _is_ui_thread(self) -> bool:
        app = self._qt_application_instance()
        try:
            return bool(app is not None and QtCore.QThread.currentThread() == app.thread())
        except Exception:
            return False

    def _adopt_qobject_bridges(self, parent: QtCore.QObject | None) -> None:
        app = self._qt_application_instance()
        ui_thread = app.thread() if app is not None else None
        for bridge in (
            getattr(self, "_refine_bridge", None),
            getattr(self, "_story_bridge", None),
            getattr(self, "_chat_turn_bridge", None),
            getattr(self, "_story_audio_bridge", None),
            getattr(self, "_structured_export_bridge", None),
            getattr(self, "_ui_bridge", None),
        ):
            if bridge is None:
                continue
            try:
                if ui_thread is not None and bridge.thread() != ui_thread and bridge.parent() is None:
                    bridge.moveToThread(ui_thread)
                if parent is not None and bridge.parent() is not parent and bridge.thread() == parent.thread():
                    bridge.setParent(parent)
            except RuntimeError:
                pass

    def _new_worker_token(self, prefix: str) -> str:
        with self._worker_token_lock:
            if self._shutting_down:
                return ""
            self._worker_sequence += 1
            token = f"{str(prefix or 'worker')}_{self._worker_sequence}"
            self._active_worker_tokens.add(token)
            return token

    def _worker_should_emit(self, token: str) -> bool:
        with self._worker_token_lock:
            return bool(token and token in self._active_worker_tokens and not self._shutting_down)

    def _finish_worker_token(self, token: str) -> bool:
        with self._worker_token_lock:
            if not token or token not in self._active_worker_tokens or self._shutting_down:
                self._active_worker_tokens.discard(str(token or ""))
                return False
            self._active_worker_tokens.discard(token)
        self._request_ui_refresh()
        return True

    def _cancel_worker_token(self, token: str) -> None:
        with self._worker_token_lock:
            self._active_worker_tokens.discard(str(token or ""))

    def _start_daemon_worker(self, token: str, target, *, name: str) -> bool:
        if not token or not callable(target):
            return False
        with self._worker_token_lock:
            if self._shutting_down or token not in self._active_worker_tokens:
                self._active_worker_tokens.discard(token)
                return False

        def supervised(cancellation) -> None:
            if cancellation.cancelled or not self._worker_should_emit(token):
                self._cancel_worker_token(token)
                return
            target()

        try:
            self.tasks.spawn(f"{name}:{token}", supervised)
        except Exception:
            self._cancel_worker_token(token)
            return False
        self._request_ui_refresh()
        return True

    def _roleplay_capability_active(self) -> bool:
        return not bool(self._shutting_down) and bool(self.session.enabled)

    def assistant_reply(self, text):
        content = str(text or "").strip()
        if content and not self._shutting_down and not self.session.enabled:
            runtime = self._chat_character_runtime()
            if runtime is not None:
                runtime.discover_reply(content)
            return None
        if (
            not content
            or bool(self._shutting_down)
            or not bool(self.session.enabled)
            or self.mprc_play_isolated_active()
        ):
            return None
        return self._queue_main_chat_assistant_reply(content)

    def tts_generation_started(self, payload):
        if self._shutting_down:
            return None
        self.handle_tts_generation_started(dict(payload or {}))
        return True

    def tts_generation_finished(self, payload):
        if self._shutting_down:
            return None
        self.handle_tts_generation_finished(dict(payload or {}))
        return True

    def tts_segment_started(self, persona_id, text):
        if not self._roleplay_capability_active():
            return None
        # Only the playback-start callback owns this identity. Generation and
        # selected/current persona changes must not advance the speaking dock.
        with self._state_lock:
            self._native_chat_speaker = {
                "personaId": str(persona_id or "").strip(),
                "text": str(text or "").strip(),
                "armed": True,
            }
        self.handle_tts_persona_visual(str(persona_id or ""), str(text or ""))
        return True

    def collect_chat_context(self, payload):
        if not self._roleplay_capability_active():
            runtime = self._chat_character_runtime()
            return runtime.context() if runtime is not None else None
        with self._state_lock:
            return self.roleplay_engine.chat_context(dict(payload or {}))

    def voice_route(self, payload):
        if not self._roleplay_capability_active():
            return None
        with self._state_lock:
            return self.voice_router.effective_voice_config(dict(payload or {}))

    def voice_segments(self, payload):
        if not self._roleplay_capability_active():
            runtime = self._chat_character_runtime()
            return runtime.segments(dict(payload or {})) if runtime is not None else None
        with self._state_lock:
            return self.voice_router.split_text_by_persona(dict(payload or {}))

    def _chat_character_runtime(self):
        if self._shutting_down:
            return None
        with self._state_lock:
            if not hasattr(self, "_chat_characters_runtime"):
                from .chat_character_runtime import ChatCharacterRuntime
                try:
                    self._chat_characters_runtime = ChatCharacterRuntime(
                        self.storage, self.runtime_config.get, self.tasks.spawn,
                        self._complete_provider_request, Path(__file__).resolve().parents[2])
                except (OSError, ValueError):
                    # Optional library corruption must never stop existing chat/audio.
                    self._chat_characters_runtime = None
            return self._chat_characters_runtime

    def chat_characters(self, payload):
        if payload.get('action') == 'voice-context' and self._roleplay_capability_active():
            return {'character_voices_enabled': False}
        runtime = self._chat_character_runtime()
        if runtime is None:
            return {"available": False, "message": "Chat character storage is unavailable."}
        return runtime.invoke(dict(payload or {}))

    def tts_audio_chunk_ready(self, payload):
        if not self._roleplay_capability_active():
            return None
        with self._state_lock:
            return self.handle_tts_audio_chunk_ready(dict(payload or {}))

    def play_audio_cues(self, cue_ids):
        if not self._roleplay_capability_active():
            return None
        with self._state_lock:
            return self.play_story_audio_cue_ids(list(cue_ids or []))

    def audio_settings(self):
        if not self._roleplay_capability_active():
            return None
        with self._state_lock:
            return self.audio_settings_snapshot()

    def remote_state(self):
        return None if self._shutting_down else self.remote_snapshot()

    def remote_send(self, text, *, intent="Auto", speaker_id=""):
        content = str(text or "").strip()
        if not content:
            return {"accepted": False, "message": "text is required"}
        return self.remote_send_user_text(
            content,
            intent=str(intent or "Auto"),
            speaker_id=str(speaker_id or ""),
        )

    def remote_choice(self, choice):
        selected = str(choice or "").strip()
        if not selected:
            return {"accepted": False, "message": "choice is required"}
        return self.remote_select_choice(selected)

    def remote_play_command(self):
        return self.remote_play()

    def remote_pause_command(self):
        return self.remote_pause()

    def remote_visual(self):
        return self.remote_request_visual()

    def remote_cast(self, payload):
        return self.remote_chromecast_action(dict(payload or {}))

    def _queue_main_chat_assistant_reply(self, text: str) -> dict[str, Any]:
        content = str(text or "").strip()
        if not content:
            return {"queued": False, "reason": "shutdown_or_empty"}
        token = self._new_worker_token("main_chat_reply")
        if not token:
            return {"queued": False, "reason": "shutdown_or_empty"}

        def worker() -> None:
            try:
                with self._assistant_reply_serial_lock:
                    if (
                        not self._worker_should_emit(token)
                        or not self.session.enabled
                        or self.mprc_play_isolated_active()
                    ):
                        return
                    self.roleplay_engine.record_assistant_text(content, source="main_chat")
            except Exception as exc:
                logger = getattr(self.context, "logger", None)
                if logger is not None:
                    logger.warning("[MPRC] Deferred assistant-reply bookkeeping failed: %s", exc)
            finally:
                self._finish_worker_token(token)

        if not self._start_daemon_worker(
            token,
            worker,
            name="nc-mprc-main-chat-reply",
        ):
            return {"queued": False, "reason": "thread_start_failed"}
        return {"queued": True}

    def begin_shutdown(self) -> None:
        self._shutdown_requested.set()
        runtime = getattr(self, "_chat_characters_runtime", None)
        if runtime is not None:
            runtime.close()

    def shutdown(self) -> None:
        self.begin_shutdown()
        brief = getattr(self, "_story_brief", None)
        if brief is not None:
            brief.cancel.cancel("MPRC shutdown")
        with self._visual_commit_lock:
            with self._state_lock:
                if self._shutting_down:
                    return
                self._shutting_down = True
                self._refine_widgets.clear()
                self._tts_generation_ids.clear()
                self._pending_tts_persona_visuals.clear()
            with self._worker_token_lock:
                self._active_worker_tokens.clear()
        remote_backend = getattr(self, "_remote_backend", None)
        begin_remote_shutdown = getattr(remote_backend, "begin_shutdown", None)
        if callable(begin_remote_shutdown):
            begin_remote_shutdown()
        chromecast_bridge = getattr(self, "_chromecast_bridge", None)
        begin_chromecast_shutdown = getattr(chromecast_bridge, "begin_shutdown", None)
        if callable(begin_chromecast_shutdown):
            begin_chromecast_shutdown()
        self.tasks.cancel_and_join("multi_persona_roleplay_shutdown")
        if chromecast_bridge is not None:
            try:
                chromecast_bridge.stop_stream()
            except Exception:
                pass
        self._stop_remote_backend()
        if self._is_ui_thread():
            self._shutdown_qt_objects()
            return
        bridge = getattr(self, "_ui_bridge", None)
        if bridge is not None:
            try:
                bridge.shutdown_requested.emit()
            except RuntimeError:
                pass

    def _shutdown_qt_objects(self) -> None:
        backend = getattr(self, "_scenario_workbench", None)
        if backend is not None:
            backend.close()
            backend.deleteLater()
            self._scenario_workbench = None
        play = getattr(self, "_scenario_play", None)
        if play is not None:
            play.runtime.invalidate()
        self._stop_guide_speech()
        player = getattr(self, "_audiofx_player", None)
        if player is not None:
            try:
                player.stop()
            except Exception:
                pass
            try:
                player.setAudioOutput(None)
            except Exception:
                pass
            try:
                player.deleteLater()
            except RuntimeError:
                pass
        output = getattr(self, "_audiofx_output", None)
        if output is not None:
            try:
                output.deleteLater()
            except RuntimeError:
                pass
        self._audiofx_player = None
        self._audiofx_output = None
        for attr in ("_refine_bridge", "_story_bridge", "_chat_turn_bridge", "_voice_preview_bridge", "_story_audio_bridge", "_ui_bridge"):
            bridge = getattr(self, attr, None)
            if bridge is None:
                continue
            try:
                bridge.disconnect()
            except Exception:
                pass
            try:
                bridge.controller = None
            except Exception:
                pass
            try:
                bridge.setParent(None)
                bridge.deleteLater()
            except RuntimeError:
                pass
            setattr(self, attr, None)

    def _notify_changed(self):
        notifier = getattr(self.shell, "notify_settings_changed", None) if self.shell is not None else None
        if callable(notifier):
            notifier()

    def save_state(self):
        with self._state_lock:
            if self._shutting_down:
                return
            self._last_session_export_state = self._session_export_payload_unlocked()
            personas_snapshot = copy.deepcopy(self.personas)
            session_snapshot = copy.deepcopy(self.session)
        self.storage.save_personas(personas_snapshot)
        self.storage.save_session(session_snapshot)

    def _queue_state_save(self) -> None:
        if self._shutting_down:
            return
        with self._state_save_queue_lock:
            self._state_save_pending = True
            if self._state_save_worker_active:
                return
            self._state_save_worker_active = True
        try:
            self.tasks.spawn("state-writer", self._state_save_worker)
        except Exception:
            with self._state_save_queue_lock:
                self._state_save_worker_active = False
            raise

    def _state_save_worker(self, cancellation) -> None:
        while True:
            with self._state_save_queue_lock:
                if not self._state_save_pending:
                    self._state_save_worker_active = False
                    return
                self._state_save_pending = False
            if cancellation.cancelled or self.is_shutdown():
                with self._state_save_queue_lock:
                    self._state_save_worker_active = False
                return
            self.save_state()

    def mprc_play_isolated_active(self) -> bool:
        return bool(getattr(self, "_mprc_play_active", False))

    def _set_mprc_play_isolated_active(self, active: bool, *, persist: bool = False) -> None:
        value = bool(active)
        changed = bool(getattr(self, "_mprc_play_active", False)) != value
        self._mprc_play_active = value
        if self.settings.get("mprc_play_isolated_active") != value:
            self.settings["mprc_play_isolated_active"] = value
            changed = True
        if value and bool(self.settings.get("master_story_ready_to_start", False)):
            self.settings["master_story_ready_to_start"] = False
            changed = True
        if persist and changed:
            self.storage.save_settings(self.settings)

    def _remote_host(self) -> str:
        return str(self.settings.get("remote_host") or "0.0.0.0").strip() or "0.0.0.0"

    def _remote_port(self) -> int:
        try:
            port = int(self.settings.get("remote_port", DEFAULT_REMOTE_PORT) or DEFAULT_REMOTE_PORT)
        except Exception:
            port = DEFAULT_REMOTE_PORT
        return max(1, min(65535, port))

    @staticmethod
    def _normalized_remote_code(value: Any) -> str:
        digits = re.sub(r"\D+", "", str(value or ""))
        if not digits:
            return ""
        try:
            numeric = int(digits)
        except Exception:
            return ""
        return f"{numeric:06d}" if 100000 <= numeric <= 999999 else ""

    def _remote_code(self) -> str:
        code = self._normalized_remote_code(self.settings.get("remote_code"))
        if code:
            return code
        code = generate_remote_code()
        self.settings["remote_code"] = code
        self.settings.pop("remote_token", None)
        self.storage.save_settings(self.settings)
        return code

    def _sync_remote_backend_from_settings(self) -> None:
        if not self._remote_server_installed():
            if bool(self.settings.get("remote_enabled", False)):
                self.settings["remote_enabled"] = False
                self.storage.save_settings(self.settings)
            self._stop_remote_backend()
            self._refresh_remote_controls()
            return
        self._ensure_remote_settings_defaults(installed=True)
        if bool(self.settings.get("remote_enabled", False)):
            self._start_remote_backend()
        else:
            self._stop_remote_backend()
        self._refresh_remote_controls()

    def _start_remote_backend(self) -> None:
        if not self._remote_server_installed():
            return
        host = self._remote_host()
        port = self._remote_port()
        code = self._remote_code()
        backend = getattr(self, "_remote_backend", None)
        if backend is not None and backend.running and backend.host == host and backend.port == port and backend.code == code:
            return
        if backend is not None:
            backend.stop()
        try:
            backend = MPRCRemoteBackend(self, host=host, port=port, code=code)
            backend.start()
            self._remote_backend = backend
            self._record_story_event(f"remote backend started at {backend.display_url}", severity="info", kind="runtime", persist=True)
        except Exception as exc:
            self._remote_backend = None
            self.settings["remote_enabled"] = False
            self.storage.save_settings(self.settings)
            logger = getattr(self.context, "logger", None)
            if logger is not None:
                logger.warning("[MPRC Remote] Could not start remote backend: %s", exc)
            self._record_story_event(f"remote backend failed to start: {exc}", severity="warning", kind="runtime", persist=True)

    def _stop_remote_backend(self) -> None:
        backend = getattr(self, "_remote_backend", None)
        self._remote_backend = None
        if backend is not None:
            backend.stop()

    def remote_status_snapshot(self) -> dict[str, Any]:
        if not self._remote_server_installed():
            return {
                "installed": False,
                "enabled": False,
                "running": False,
                "host": "",
                "port": int(DEFAULT_REMOTE_PORT),
                "url": "",
                "code_configured": False,
                "pairing_code": "",
                "connected_clients": 0,
                "clients": [],
                "started_at": 0.0,
            }
        backend = getattr(self, "_remote_backend", None)
        if backend is not None:
            status = backend.status_snapshot()
        else:
            status = {
                "installed": True,
                "enabled": bool(self.settings.get("remote_enabled", False)),
                "running": False,
                "host": self._remote_host(),
                "port": self._remote_port(),
                "url": f"http://{lan_ip_address() if self._remote_host() in {'', '0.0.0.0', '::'} else self._remote_host()}:{self._remote_port()}",
                "code_configured": bool(self._normalized_remote_code(self.settings.get("remote_code"))),
                "connected_clients": 0,
                "clients": [],
                "started_at": 0.0,
            }
        status["installed"] = True
        status["pairing_code"] = self._remote_code()
        status.update(self._engine_speech_status())
        return status

    def _engine_speech_status(self, *, strict: bool = False) -> dict[str, Any]:
        try:
            snapshot = dict(self.playback.snapshot() or {})
            if strict and "speech_playing" not in snapshot:
                raise RuntimeError("Speech ownership status is unavailable.")
            return snapshot
        except Exception:
            if strict:
                raise
            return {"speech_playing": False, "speech_paused": False}

    def _set_engine_speech_paused(self, paused: bool) -> bool:
        try:
            return bool(self.playback.set_paused(bool(paused)))
        except Exception:
            return False

    def _remote_audio_cache_dir(self) -> Path:
        root = Path(__file__).resolve().parents[2] / "runtime" / "mprc_remote_audio"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _begin_remote_speech_audio_capture(self, reply_text: str) -> None:
        if not self._remote_server_installed() or not bool(self.settings.get("remote_enabled", False)):
            return
        with self._remote_audio_lock:
            self._remote_audio_generation += 1
            self._remote_audio_capture_index = 0
            old_items = list(self._remote_audio_items or [])
            self._remote_audio_items = []
            self._remote_audio_status = "rendering"
            self._remote_audio_capture_until = time.time() + 900.0
            self._remote_audio_source_excerpt = self._mprc_compact(str(reply_text or ""), 240)
        for item in old_items:
            path = Path(str(item.get("_file_path") or ""))
            if path.exists():
                try:
                    path.unlink()
                except Exception:
                    pass

    def handle_tts_audio_chunk_ready(self, payload: dict[str, Any] | None = None):
        if not self._remote_server_installed() or not bool(self.settings.get("remote_enabled", False)):
            return None
        data = dict(payload or {})
        source_path = Path(str(data.get("audio_path") or ""))
        if not source_path.exists() or source_path.suffix.lower() != ".wav":
            return None
        now = time.time()
        with self._remote_audio_lock:
            if now > float(self._remote_audio_capture_until or 0.0):
                return None
            generation = int(self._remote_audio_generation or 0)
            self._remote_audio_capture_index += 1
            index = int(self._remote_audio_capture_index)
        task = {
            "source_path": str(source_path),
            "generation": generation,
            "index": index,
            "created_at": now,
            "text": str(data.get("text") or "").strip(),
            "source_meta": dict(data.get("source_meta") or {}) if isinstance(data.get("source_meta"), dict) else {},
        }
        return True if self._queue_remote_audio_copy(task) else None

    def _queue_remote_audio_copy(self, task: dict[str, Any]) -> bool:
        try:
            self._remote_audio_copy_queue.put_nowait(dict(task or {}))
        except queue.Full:
            logger = getattr(self.context, "logger", None)
            if logger is not None:
                logger.warning("[MPRC Remote] Phone audio queue is full; dropping one TTS chunk.")
            return False
        with self._remote_audio_lock:
            if self._remote_audio_copy_worker_active:
                return True
            self._remote_audio_copy_worker_active = True
        try:
            self.tasks.spawn("remote-audio-copy", self._remote_audio_copy_worker)
        except Exception:
            with self._remote_audio_lock:
                self._remote_audio_copy_worker_active = False
            return False
        return True

    def _remote_audio_copy_worker(self, cancellation) -> None:
        while True:
            if cancellation.cancelled or self.is_shutdown():
                with self._remote_audio_lock:
                    self._remote_audio_copy_worker_active = False
                return
            try:
                task = self._remote_audio_copy_queue.get(timeout=0.25)
            except queue.Empty:
                with self._remote_audio_lock:
                    if self._remote_audio_copy_queue.empty():
                        self._remote_audio_copy_worker_active = False
                        return
                continue
            try:
                if not cancellation.cancelled and not self.is_shutdown():
                    self._store_remote_audio_chunk(task)
            except Exception as exc:
                logger = getattr(self.context, "logger", None)
                if logger is not None:
                    logger.warning("[MPRC Remote] Phone audio copy worker failed: %s", exc)
            finally:
                self._remote_audio_copy_queue.task_done()

    def _store_remote_audio_chunk(self, task: dict[str, Any]) -> None:
        source_path = Path(str(task.get("source_path") or ""))
        generation = int(task.get("generation") or 0)
        index = int(task.get("index") or 0)
        now = float(task.get("created_at") or time.time())
        with self._remote_audio_lock:
            if generation != int(self._remote_audio_generation or 0):
                return
        target_id = f"g{generation:04d}_{index:03d}_{int(now * 1000)}"
        target_path = self._remote_audio_cache_dir() / f"{target_id}.wav"
        try:
            shutil.copy2(source_path, target_path)
        except Exception as exc:
            logger = getattr(self.context, "logger", None)
            if logger is not None:
                logger.warning("[MPRC Remote] Could not copy TTS chunk for phone audio: %s", exc)
            return
        duration = self._wav_duration_seconds(target_path)
        meta = dict(task.get("source_meta") or {})
        item = {
            "id": target_id,
            "_file_path": str(target_path),
            "url_path": f"/api/speech-audio/file/{target_id}",
            "index": index,
            "text": str(task.get("text") or "").strip(),
            "persona_id": str(meta.get("persona_id") or ""),
            "speaker": str(meta.get("display_name") or meta.get("persona_id") or "Narrator").strip() or "Narrator",
            "duration_seconds": duration,
            "created_at": now,
        }
        with self._remote_audio_lock:
            if generation != int(self._remote_audio_generation or 0):
                try:
                    target_path.unlink()
                except Exception:
                    pass
                return
            self._remote_audio_items.append(item)
            self._remote_audio_items = self._remote_audio_items[-48:]
            self._remote_audio_status = "ready"

    @staticmethod
    def _wav_duration_seconds(path: Path) -> float:
        try:
            with wave.open(str(path), "rb") as handle:
                frames = int(handle.getnframes() or 0)
                rate = int(handle.getframerate() or 0)
            return round(frames / rate, 3) if rate > 0 else 0.0
        except Exception:
            return 0.0

    def remote_speech_audio_snapshot(self) -> dict[str, Any]:
        with self._remote_audio_lock:
            items = [
                {key: value for key, value in dict(item).items() if not str(key).startswith("_")}
                for item in list(self._remote_audio_items or [])
            ]
            status = str(self._remote_audio_status or "idle")
            capture_active = time.time() <= float(self._remote_audio_capture_until or 0.0)
            generation = int(self._remote_audio_generation or 0)
            source_excerpt = str(self._remote_audio_source_excerpt or "")
        if not items and not capture_active:
            status = "idle"
        return {
            "available": bool(items),
            "status": status,
            "generation": generation,
            "capture_active": bool(capture_active),
            "source_excerpt": source_excerpt,
            "items": items,
        }

    def remote_speech_audio_file_path(self, audio_id: str) -> Path:
        wanted = re.sub(r"[^A-Za-z0-9_.-]+", "", str(audio_id or ""))
        if not wanted:
            raise FileNotFoundError("speech audio id is required")
        with self._remote_audio_lock:
            for item in list(self._remote_audio_items or []):
                if str(item.get("id") or "") == wanted:
                    path = Path(str(item.get("_file_path") or ""))
                    if path.exists() and path.is_file():
                        return path
        raise FileNotFoundError("speech audio chunk not found")

    def _handle_remote_thread_request(self, payload) -> None:
        data = payload if isinstance(payload, dict) else {}
        event = data.get("event")
        try:
            if self.is_shutdown():
                raise RuntimeError("MPRC remote request was cancelled during shutdown")
            func = data.get("func")
            if not callable(func):
                raise RuntimeError("remote request is missing callable")
            data["result"] = func()
        except Exception as exc:
            data["error"] = str(exc) or repr(exc)
        finally:
            if event is not None and hasattr(event, "set"):
                event.set()

    def _run_remote_on_ui_thread(self, func, *, timeout: float = 30.0):
        if not callable(func):
            raise RuntimeError("remote UI request is not callable")
        if self.is_shutdown():
            raise RuntimeError("MPRC remote request was cancelled during shutdown")
        if self._is_ui_thread():
            return func()
        bridge = getattr(self, "_ui_bridge", None)
        if bridge is None:
            raise RuntimeError("MPRC UI bridge is unavailable")
        event = threading.Event()
        payload: dict[str, Any] = {"func": func, "event": event, "result": None, "error": ""}
        try:
            bridge.remote_request.emit(payload)
        except RuntimeError as exc:
            raise RuntimeError(f"MPRC UI bridge rejected remote request: {exc}") from exc
        if not event.wait(max(1.0, float(timeout or 30.0))):
            raise RuntimeError("MPRC remote request timed out waiting for UI thread")
        if payload.get("error"):
            raise RuntimeError(str(payload.get("error") or "MPRC remote request failed"))
        return payload.get("result")

    def remote_personas_snapshot(self) -> list[dict[str, Any]]:
        active_id = str(self.session.active_persona_id or "")
        current_id = str(self.session.current_speaker_id or "")
        narrator_id = self.selected_narrator_persona_id()
        items: list[dict[str, Any]] = []
        for persona in list(self.personas or []):
            items.append(
                {
                    "id": persona.id,
                    "display_name": persona.display_name,
                    "role": persona.role or persona.behavior_mode,
                    "enabled": bool(persona.enabled),
                    "active": persona.id == active_id,
                    "current_speaker": persona.id == current_id,
                    "narrator": persona.id == narrator_id,
                    "description": self._mprc_compact(persona.ar_description or persona.description, 400),
                    "visual_enabled": bool(persona.visual.enabled),
                    "voice_enabled": bool(persona.voice.enabled),
                }
            )
        return items

    def remote_session_snapshot(self) -> dict[str, Any]:
        state = self.session.ar_state
        return {
            "enabled": bool(self.session.enabled),
            "mode": self.session.mode,
            "turn_index": int(self.session.turn_index or 0),
            "active_persona_id": self.session.active_persona_id,
            "current_speaker_id": self.session.current_speaker_id,
            "scene_title": self.session.scene_title,
            "location": state.location or self.session.location,
            "time_of_day": state.time_of_day or self.session.time_of_day,
            "mood": state.mood or self.session.mood,
            "objective": state.story_goal or self.session.objective,
            "scene_summary": self.session.scene_summary,
            "ar_state": state.to_dict(),
            "character_state_summaries": dict(self.session.character_state_summaries or {}),
        }

    def remote_memory_snapshot(self) -> dict[str, Any]:
        memory = getattr(self, "long_memory", None)
        if memory is None:
            return {
                "available": False,
                "backend": "unavailable",
                "status": "unavailable",
                "message": "Story memory is not available.",
            }
        try:
            payload = memory.load()
        except Exception as exc:
            return {
                "available": False,
                "backend": "unavailable",
                "status": "error",
                "message": f"Story memory could not be read: {exc}",
            }

        settings = dict(getattr(self, "settings", {}) or {})
        database = getattr(memory, "database", None)
        backend = self._remote_memory_backend_label(database, settings)
        configured_sources = self._remote_memory_databank_sources(settings)
        event_count = len([item for item in list(payload.get("events") or []) if isinstance(item, dict)])
        chapter_count = len([item for item in list(payload.get("chapters") or []) if isinstance(item, dict)])
        pinned = [str(item).strip() for item in list(payload.get("pinned_facts") or []) if str(item).strip()]
        character_memory = payload.get("character_memory") if isinstance(payload.get("character_memory"), dict) else {}
        location_memory = payload.get("location_memory") if isinstance(payload.get("location_memory"), dict) else {}
        database_available = database is not None
        databank = getattr(memory, "databank", None)
        indexed_sources = getattr(memory, "_indexed_databank_sources", set()) or set()
        configured_backend = str(
            settings.get("long_memory_database_backend")
            or settings.get("memory_database_backend")
            or ""
        ).strip().lower()
        fallback_note = ""
        if configured_backend in {"postgres", "postgresql"} and backend == "sqlite":
            fallback_note = "PostgreSQL is configured but SQLite is active."
        return {
            "available": True,
            "backend": backend,
            "configured_backend": configured_backend or "sqlite",
            "database_available": bool(database_available),
            "database_status": "ready" if database_available else "json_only",
            "databank_available": databank is not None,
            "configured_databank_source_count": len(configured_sources),
            "indexed_databank_source_count": len(indexed_sources),
            "event_count": event_count,
            "chapter_count": chapter_count,
            "pinned_fact_count": len(pinned),
            "character_memory_count": len(character_memory),
            "location_memory_count": len(location_memory),
            "fallback_note": fallback_note,
        }

    @staticmethod
    def _remote_memory_backend_label(database, settings: dict[str, Any]) -> str:
        type_name = type(database).__name__.lower() if database is not None else ""
        if "postgres" in type_name:
            return "postgresql"
        if "sqlite" in type_name:
            return "sqlite"
        configured = str(
            settings.get("long_memory_database_backend")
            or settings.get("memory_database_backend")
            or ""
        ).strip().lower()
        if configured in {"postgres", "postgresql"}:
            return "postgresql"
        if configured == "sqlite":
            return "sqlite"
        return "json"

    @staticmethod
    def _remote_memory_databank_sources(settings: dict[str, Any]) -> list[str]:
        sources = settings.get("long_memory_databank_sources") or settings.get("memory_databank_sources") or []
        if isinstance(sources, str):
            return [line.strip() for line in sources.splitlines() if line.strip()]
        return [str(item).strip() for item in list(sources or []) if str(item or "").strip()]

    def remote_snapshot(self) -> dict[str, Any]:
        latest_reply = self._remote_latest_reply()
        choices = self._extract_ar_choices(latest_reply) or [
            str(item)
            for item in list(self.session.ar_state.pending_choices or [])
            if str(item or "").strip()
        ]
        return {
            "schema_version": 1,
            "remote": self.remote_status_snapshot(),
            "session": self.remote_session_snapshot(),
            "personas": self.remote_personas_snapshot(),
            "latest_reply": latest_reply,
            "segments": self._remote_story_segments(latest_reply),
            "choices": [
                {"id": str(index), "text": choice}
                for index, choice in enumerate(choices[:6], start=1)
            ],
            "memory": self.remote_memory_snapshot(),
            "speech_audio": self.remote_speech_audio_snapshot(),
            "audio_cues": self.available_story_audio_files(),
            "cast": self.remote_chromecast_snapshot(),
            "visual": {
                "latest_prompt": str(self._debug_visual_prompt or self._chat_visual_prompt_debug or ""),
                "last_visual_reply_at": float(self.session.last_visual_reply_at or 0.0),
                "auto_image_count": int(self.session.auto_image_count or 0),
            },
        }

    def _remote_latest_reply(self) -> str:
        if str(self._remote_latest_reply_text or "").strip():
            return str(self._remote_latest_reply_text or "").strip()
        for message in reversed(list(self._mprc_chat_history or [])):
            if str((message or {}).get("role") or "").strip().lower() == "assistant":
                return str((message or {}).get("content") or "").strip()
        return ""

    def _remote_story_segments(self, text: str) -> list[dict[str, Any]]:
        raw = str(text or "").strip()
        if not raw:
            return []
        tag_pattern = re.compile(
            r"\[(NARRATOR|CHARACTER:\s*[^\]]+|AMBIENCE:\s*[^\]]+|AMBIENT:\s*[^\]]+|MUSIC:\s*[^\]]+|FX:\s*[^\]]+|SFX:\s*[^\]]+|STINGER:\s*[^\]]+|AUDIO:\s*[^\]]+|CHOICES)\]",
            flags=re.IGNORECASE,
        )
        matches = list(tag_pattern.finditer(raw))
        if not matches:
            return [{"segment_id": 1, "speaker_id": "narrator", "speaker_name": "Narrator", "role": "narrator", "text": raw}]
        segments: list[dict[str, Any]] = []
        for index, match in enumerate(matches):
            tag = str(match.group(1) or "").strip()
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(raw)
            body = raw[start:end].strip()
            lowered = tag.lower()
            if lowered == "choices":
                continue
            role = "narrator"
            speaker_name = "Narrator"
            speaker_id = "narrator"
            if lowered.startswith("character:"):
                role = "character"
                speaker_name = re.sub(r"^character:\s*", "", tag, flags=re.IGNORECASE).strip()
                speaker_id = self._remote_persona_id_for_name(speaker_name)
            elif ":" in tag:
                role = "audio"
                speaker_name = tag.split(":", 1)[0].strip().upper()
                speaker_id = "audio"
                body = f"[{tag}] {body}".strip()
            if body:
                segments.append(
                    {
                        "segment_id": len(segments) + 1,
                        "speaker_id": speaker_id,
                        "speaker_name": speaker_name,
                        "role": role,
                        "text": body,
                    }
                )
        return segments

    def _remote_persona_id_for_name(self, name: str) -> str:
        wanted = str(name or "").strip().lower()
        for persona in list(self.personas or []):
            if wanted in {persona.id.lower(), persona.display_name.strip().lower()}:
                return persona.id
        return normalize_persona_id(name) or "unknown_speaker"

    def remote_update_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        def apply_update():
            data = dict(payload or {})
            state = self.session.ar_state
            for key in ("scene_title", "location", "time_of_day", "mood", "objective", "scene_summary"):
                if key in data:
                    setattr(self.session, key, str(data.get(key) or "").strip())
            ar_payload = data.get("ar_state") if isinstance(data.get("ar_state"), dict) else data
            for key, attr in (
                ("current_scene", "current_scene"),
                ("location", "location"),
                ("time_of_day", "time_of_day"),
                ("mood", "mood"),
                ("story_goal", "story_goal"),
                ("player_intent", "player_intent"),
            ):
                if key in ar_payload:
                    setattr(state, attr, str(ar_payload.get(key) or "").strip())
            if "active_characters" in ar_payload and isinstance(ar_payload.get("active_characters"), list):
                state.active_characters = [
                    normalize_persona_id(item)
                    for item in ar_payload.get("active_characters")
                    if str(item or "").strip()
                ][:8]
            if "pending_choices" in ar_payload and isinstance(ar_payload.get("pending_choices"), list):
                state.pending_choices = [str(item or "").strip() for item in ar_payload.get("pending_choices") if str(item or "").strip()][:6]
            if "enabled" in data:
                self.session.enabled = bool(data.get("enabled"))
            if "mode" in data:
                mode = str(data.get("mode") or "").strip()
                if mode in SESSION_MODES:
                    self.session.mode = mode
            self.save_state()
            self._request_ui_refresh()
            return self.remote_snapshot()

        return self._run_remote_on_ui_thread(apply_update)

    def remote_send_user_text(self, text: str, *, intent: str = "Auto", speaker_id: str = "") -> dict[str, Any]:
        def send():
            player_text = str(text or "").strip()
            if not player_text:
                raise RuntimeError("text is required")
            if self._mprc_pending_chat_users:
                raise RuntimeError("MPRC turn is already running")
            self._stop_mprc_chat_speech()
            intent_text = self._infer_mprc_chat_intent(player_text, intent)
            latest_user_text = f"{intent_text}: {player_text}"
            self.session.ar_state.player_intent = latest_user_text
            speaker = self.persona_by_id(str(speaker_id or "").strip())
            if speaker is not None:
                self.session.current_speaker_id = speaker.id
            self._set_mprc_play_isolated_active(True, persist=True)
            self.session.enabled = True
            if self.session.mode == AR_MODE:
                self.ensure_ar_state(latest_user_text)
            self.save_state()
            self._append_chat_play_line("Remote [{0}]".format(intent_text), player_text, role="user")
            self._start_mprc_chat_turn(intent=intent_text, player_text=player_text, speaker_id=str(speaker_id or "").strip())
            return self.remote_snapshot()

        return self._run_remote_on_ui_thread(send)

    def remote_select_choice(self, choice: str) -> dict[str, Any]:
        text = str(choice or "").strip()
        if text.isdigit():
            index = int(text) - 1
            choices = [str(item or "").strip() for item in list(self.session.ar_state.pending_choices or []) if str(item or "").strip()]
            if 0 <= index < len(choices):
                text = choices[index]
        return self.remote_send_user_text(text, intent="Auto")

    def remote_play(self) -> dict[str, Any]:
        def play():
            self.session.enabled = True
            self._set_mprc_play_isolated_active(True, persist=True)
            was_paused = bool(self._engine_speech_status().get("speech_paused", False))
            if was_paused and self._set_engine_speech_paused(False):
                self.save_state()
                self._append_chat_play_line("Remote", "Speech resume requested.", role="system")
                self._set_chat_play_status("MPRC Remote speech resume requested.")
                return self.remote_snapshot()
            if self.session.mode == AR_MODE:
                self.ensure_ar_state("Continue")
            self.save_state()
            if int(getattr(self.session, "turn_index", 0) or 0) <= 0 and not self._mprc_pending_chat_users:
                self._start_mprc_opening_turn()
            else:
                self._append_chat_play_line("Remote", "Play/resume requested.", role="system")
                self._set_chat_play_status("MPRC Remote play/resume requested.")
            return self.remote_snapshot()

        return self._run_remote_on_ui_thread(play)

    def remote_pause(self) -> dict[str, Any]:
        def pause():
            self._set_engine_speech_paused(True)
            self._append_chat_play_line("Remote", "Speech pause requested.", role="system")
            self._set_chat_play_status("MPRC Remote speech pause requested. Current speech can resume from the remote app or PC Pause / Resume.")
            return self.remote_snapshot()

        return self._run_remote_on_ui_thread(pause)

    def remote_request_visual(self) -> dict[str, Any]:
        def request():
            persona = self.current_speaker_persona() or self.active_persona()
            if persona is None:
                raise RuntimeError("No active persona for Visual Reply")
            self.request_auto_visual_reply(persona.id, "manual", self._remote_latest_reply())
            self._set_chat_play_status("MPRC Remote Visual Reply requested.")
            return self.remote_snapshot()

        return self._run_remote_on_ui_thread(request)

    def remote_chromecast_snapshot(self) -> dict[str, Any]:
        bridge = getattr(self, "_chromecast_bridge", None)
        if bridge is None:
            return {
                "available": False,
                "dependency_error": "MPRC Chromecast bridge is unavailable.",
                "devices": [],
                "selected_device": "",
                "active_device": "",
                "casting": False,
                "busy": False,
                "status": "MPRC Chromecast bridge is unavailable.",
                "stream": {"running": False, "url": "", "port": DEFAULT_MPRC_CAST_STREAM_PORT},
            }
        return dict(bridge.snapshot() or {})

    def remote_chromecast_action(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.is_shutdown():
            return {"accepted": False, "message": "MPRC is shutting down.", "cast": {}}
        bridge = getattr(self, "_chromecast_bridge", None)
        if bridge is None:
            return {"accepted": False, "message": "MPRC Chromecast bridge is unavailable.", "cast": self.remote_chromecast_snapshot()}
        return dict(bridge.action(dict(payload or {})) or {})

    def _session_export_payload_unlocked(self) -> dict[str, Any]:
        return {
            self.STATE_KEY: {
                "session": self.session.to_dict(),
                "active_persona_id": self.session.active_persona_id,
            }
        }

    def export_session_state(self) -> dict[str, Any]:
        acquired = self._state_lock.acquire(blocking=False)
        if not acquired:
            return copy.deepcopy(getattr(self, "_last_session_export_state", {}) or {})
        try:
            if self._shutting_down:
                return copy.deepcopy(getattr(self, "_last_session_export_state", {}) or {})
            self._last_session_export_state = self._session_export_payload_unlocked()
            return copy.deepcopy(self._last_session_export_state)
        finally:
            self._state_lock.release()

    def native_snapshot(self) -> dict[str, Any]:
        """Return the complete editable MPRC model without reading widgets."""

        from addons.multi_persona_roleplay.native_controls import native_control_state
        from addons.multi_persona_roleplay.native_chat_avatars import chat_presentation
        from addons.multi_persona_roleplay.story_brief import get_brief

        with self._state_lock:
            return {
                "session": copy.deepcopy(self.session.to_dict()),
                "personas": [persona.to_dict() for persona in self.personas],
                "settings": copy.deepcopy(self.settings),
                "visual_styles": copy.deepcopy(self.visual_styles),
                "story_index": copy.deepcopy(self.storage.load_story_index()),
                "event_log": copy.deepcopy(self._story_event_log),
                "visual_debug_log": copy.deepcopy(self._visual_debug_log),
                "presentation": {
                    "revision": int(self._native_revision),
                    "warning": copy.deepcopy(self._native_last_warning),
                    "pending_confirmation": copy.deepcopy(self._native_pending_confirmation),
                    "personas": copy.deepcopy(self._native_persona_registry),
                    "saved_audio_prompts": copy.deepcopy(self._native_audio_saved_prompts),
                    "audiofx_items": copy.deepcopy(self._native_audiofx_items),
                    "audiofx_summary": copy.deepcopy(self._native_audiofx_summary),
                    "memory": copy.deepcopy(self._native_memory_browser),
                    "character_preview": copy.deepcopy(self._native_character_preview),
                    "character_roster": copy.deepcopy(self._native_character_roster),
                    "chat_status": str(self._native_chat_status or ""),
                    "chat_transcript": copy.deepcopy(self._native_chat_transcript),
                    "chat_avatars": chat_presentation(self),
                    "scenario_builder": copy.deepcopy(getattr(self, "_scenario_native_snapshot", {})),
                    "story_brief": get_brief(self).snapshot(),
                    "play_controls": copy.deepcopy(self._native_play_controls),
                    "guide_speech_status": str(self._native_guide_speech_status or ""),
                    "master_story_status": str(self._native_master_story_status or ""),
                    "debug": copy.deepcopy(self._native_debug_state),
                    "story_export_preview": copy.deepcopy(self._native_story_export_preview),
                    "story_import_review": copy.deepcopy(self._native_story_import_review),
                    "master_story_apply_review": copy.deepcopy(self._native_master_story_apply_review),
                    "refinement": copy.deepcopy(self._native_refinement_result),
                    "clipboard_suggestion": str(self._native_clipboard_suggestion or ""),
                    "remote": copy.deepcopy(self._native_remote_controls),
                    "chromecast": copy.deepcopy(self._native_chromecast_controls),
                    "action_result": copy.deepcopy(self._native_action_result),
                    "requested_section": str(self._native_requested_section or ""),
                    "window_request": copy.deepcopy(self._native_window_request),
                    "story_inspector": str(self._native_story_inspector or ""),
                    "voice_status": str(self._native_voice_status or ""),
                    "story_index": copy.deepcopy(self._native_story_index),
                    "master_story_actions": copy.deepcopy(self._native_master_story_actions),
                    "master_story_image": copy.deepcopy(self._native_master_story_image),
                },
                "controls": native_control_state(self),
                "runtime": {
                    "play_active": bool(self._mprc_play_active),
                    "shutting_down": bool(self._shutting_down),
                },
            }

    @staticmethod
    def _native_path_parts(path: str) -> list[str | int]:
        parts: list[str | int] = []
        for raw_part in str(path or "").split("."):
            part = raw_part.strip()
            if not part:
                continue
            parts.append(int(part) if part.isdigit() else part)
        return parts

    @classmethod
    def _native_assign_path(
        cls,
        payload: dict[str, Any],
        path: str,
        value: Any,
    ) -> None:
        parts = cls._native_path_parts(path)
        if len(parts) < 2 or parts[0] not in {
            "session",
            "personas",
            "settings",
            "visual_styles",
        }:
            raise KeyError(f"Unknown MPRC native state path: {path!r}")
        current: Any = payload
        for part in parts[:-1]:
            if isinstance(part, int):
                if not isinstance(current, list) or not 0 <= part < len(current):
                    raise KeyError(f"Unknown MPRC native state path: {path!r}")
                current = current[part]
            else:
                if not isinstance(current, dict) or part not in current:
                    raise KeyError(f"Unknown MPRC native state path: {path!r}")
                current = current[part]
        leaf = parts[-1]
        if isinstance(leaf, int):
            if not isinstance(current, list) or not 0 <= leaf < len(current):
                raise KeyError(f"Unknown MPRC native state path: {path!r}")
            current[leaf] = copy.deepcopy(value)
        else:
            if not isinstance(current, dict) or leaf not in current:
                raise KeyError(f"Unknown MPRC native state path: {path!r}")
            current[leaf] = copy.deepcopy(value)

    def native_update(self, path: str, value: Any) -> dict[str, Any]:
        """Validate and persist one native field through authoritative models."""

        payload = self.native_snapshot()
        self._native_assign_path(payload, path, value)
        with self._state_lock:
            self.session = RoleplaySessionState.from_dict(payload["session"])
            self.personas = personas_from_payload(payload["personas"])
            self.settings = dict(payload["settings"] or {})
            self.visual_styles = [
                dict(item or {})
                for item in list(payload["visual_styles"] or [])
                if isinstance(item, dict)
            ]
            self._ensure_session_persona()
            self.storage.save_session(self.session)
            self.storage.save_personas(self.personas)
            self.storage.save_settings(self.settings)
            self.storage.save_visual_styles(self.visual_styles)
            self._last_session_export_state = self._session_export_payload_unlocked()
        self._request_ui_refresh()
        return self.native_snapshot()

    def native_action(
        self,
        action: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run bounded widget-independent MPRC operations for native QML."""

        action_name = str(action or "").strip().lower()
        request = dict(payload or {})
        if action_name in {"mprc_scenario_builder", "mprc_scenario_play_panel"}:
            from .native_actions import dispatch_native_action
            dispatch_native_action(self, action_name, request)
            # GUI-owned draft commands return the cached form, never a disk-backed
            # full native snapshot. The adapter refreshes other controls off-thread.
            return {"presentation": {"scenario_builder": copy.deepcopy(
                getattr(self, "_scenario_native_snapshot", {})
            )}}
        if action_name == "start_play":
            with self._state_lock:
                self.session.enabled = True
                self._mprc_play_active = True
                self.settings["mprc_play_isolated_active"] = True
                self.storage.save_session(self.session)
                self.storage.save_settings(self.settings)
        elif action_name == "pause_play":
            self._stop_mprc_chat_playback()
            with self._state_lock:
                self._mprc_play_active = False
                self.settings["mprc_play_isolated_active"] = False
                self.storage.save_settings(self.settings)
        elif action_name == "clear_chat":
            self._reset_mprc_chat_history()
        elif action_name == "clear_event_log":
            self._clear_story_event_log()
        elif action_name == "clear_visual_log":
            self._clear_visual_debug_log()
        elif action_name == "validate_story":
            return {
                "result": copy.deepcopy(self.validate_story_setup()),
                "state": self.native_snapshot(),
            }
        elif action_name == "save_memory_snapshot":
            self.save_active_story_memory_snapshot()
        elif action_name == "request_visual":
            self.remote_visual()
        else:
            from addons.multi_persona_roleplay.native_actions import (
                dispatch_native_action,
            )

            result = dispatch_native_action(self, action_name, request)
            self._native_action_result = {
                "action": action_name,
                **dict(result or {}),
            }
            self._request_ui_refresh()
        return self.native_snapshot()

    def native_update_control(self, control_id: str, value: Any) -> dict[str, Any]:
        """Validate and persist one frozen native-QML control binding."""

        from addons.multi_persona_roleplay.native_controls import native_update_control

        native_update_control(self, str(control_id or ""), value)
        return self.native_snapshot()

    def native_generate_master_story(self, prompt: str) -> dict[str, Any]:
        """Queue Master Story generation from persisted native-QML fields."""

        clean_prompt = str(prompt or "").strip()
        if not clean_prompt:
            raise ValueError("Add a Master Story prompt first.")
        if self.is_shutdown():
            raise RuntimeError("MPRC is shutting down.")
        if any(str(token).startswith("master_story_") for token in self._active_worker_tokens):
            return {"accepted": False, "message": "Master Story generation is already running."}
        brief = getattr(self, "_story_brief", None)
        if brief is not None and brief.token and brief.building:
            return {"accepted": False, "message": "Complete draft generation is already running."}
        self._commit_master_story_options()
        snapshot = self._master_story_generation_snapshot(clean_prompt)
        token = self._new_worker_token("master_story")
        if not token:
            return {"accepted": False, "message": "Could not reserve a Master Story worker."}
        self._master_story_generation_snapshots[token] = copy.deepcopy(snapshot)
        self._set_master_story_status("Generating story setup with the current chat provider...")

        def worker() -> None:
            error = ""
            result = ""
            try:
                result = self._generate_master_story_payload(snapshot)
            except Exception as exc:
                error = str(exc) or repr(exc)
            if not self._worker_should_emit(token):
                return
            try:
                self._story_bridge.finished.emit(token, result, error)
            except RuntimeError:
                self._cancel_worker_token(token)

        if not self._start_daemon_worker(token, worker, name="nc-mprc-master-story"):
            self._master_story_generation_snapshots.pop(token, None)
            self._cancel_worker_token(token)
            return {"accepted": False, "message": "Could not start the Master Story worker."}
        return {"accepted": True, "message": "Master Story generation queued.", "token": token}

    def native_load_demo_story(self) -> dict[str, Any]:
        self._load_demo_story()
        return {
            "accepted": True,
            "story_id": str(self.settings.get("last_master_story_id") or ""),
        }

    def native_load_story_template(self, template_id: str) -> dict[str, Any]:
        clean_id = str(template_id or "").strip()
        valid_ids = {item[0] for item in self._story_template_choices()}
        if clean_id not in valid_ids:
            raise ValueError(f"Unknown story template: {clean_id!r}")
        self._load_story_template(clean_id)
        return {
            "accepted": True,
            "template_id": clean_id,
            "story_id": str(self.settings.get("last_master_story_id") or ""),
        }

    def native_import_story_bundle(
        self,
        bundle: dict[str, Any],
        *,
        source_path: str = "",
    ) -> dict[str, Any]:
        """Apply a validated compact story bundle without opening a dialog."""

        payload = dict(bundle or {})
        if str(payload.get("bundle_type") or "") != "mprc_story_bundle":
            raise ValueError("This file is not an MPRC story bundle.")
        from .scenario_transfer import clone_story_extension, preflight_story_extension, preflight_scenario_apply
        content_id_map: dict[str, str] = {}
        payload["story"] = clone_story_extension(dict(payload.get("story") or {}), content_id_map=content_id_map)
        if "scenario_extension" in payload["story"]:
            payload["story"]["id"] = self._unique_story_id(str(payload["story"].get("id") or "imported_story"))
        prompts = payload.get("prompts")
        if isinstance(prompts, dict) and isinstance(prompts.get("master_story_draft"), dict):
            preflight_story_extension(prompts["master_story_draft"])
            prompts = copy.deepcopy(prompts)
            prompts["master_story_draft"] = clone_story_extension(prompts["master_story_draft"], content_id_map=content_id_map)
            if "scenario_extension" in payload["story"] or "scenario_extension" in prompts["master_story_draft"]:
                prompts["master_story_draft"]["id"] = payload["story"]["id"]
            payload["prompts"] = prompts
        imported = personas_from_payload(payload.get("personas"))
        by_id = {persona.id: persona for persona in self.personas}
        for persona in imported:
            by_id[persona.id] = persona
        story = self.storage._migrate_story_payload(
            dict(payload.get("story") or {}),
            str(payload.get("story_id") or "imported_story"),
        )
        if not story:
            raise ValueError("The bundle did not contain a valid story payload.")
        preflight_scenario_apply(self, story, {"auto_create": False}, prospective_personas=list(by_id.values()))
        try:
            schema_version = int(payload.get("schema_version", 1) or 1)
        except (TypeError, ValueError):
            schema_version = 1
        if schema_version > 1:
            self._record_story_event(
                f"bundle schema {schema_version} loaded with v1 fallback",
                severity="warning",
                kind="schema",
                persist=True,
            )
        self._save_pre_apply_backup("Import Story Bundle")
        self.personas = list(by_id.values())
        story_id = self.storage.save_story(story)
        imported_settings = payload.get("settings") if isinstance(payload.get("settings"), dict) else {}
        allowed_settings = set(self._story_bundle_settings()) | {
            "last_master_story_id",
            "last_master_story_title",
            "master_story_linked_persona_ids",
            "master_story_created_persona_ids",
            "master_story_persona_overrides",
            "master_story_avatar_style_sheets",
            "persona_avatar_style_sheets",
            "narrator_persona_id",
            "narrator_persona_mode",
            "story_sounds_enabled",
            "audio_fx_items",
            "available_audio_files",
            "saved_audio_prompts",
            "audiofx_volume",
            "audiofx_test_mode",
        }
        for key, value in imported_settings.items():
            if key not in allowed_settings:
                continue
            if key == "persona_avatar_style_sheets":
                self._merge_story_avatar_style_sheet_settings(value)
            else:
                self.settings[key] = copy.deepcopy(value)
        self.settings["last_master_story_id"] = story_id
        self.settings["last_master_story_title"] = story.get("title") or story_id
        self.settings["native_selected_story_id"] = story_id
        memory = payload.get("memory_snapshot")
        if isinstance(memory, dict) and memory:
            memory = dict(memory)
            memory["story_id"] = story_id
            self.storage.save_story_memory(story_id, memory)
        prompts = payload.get("prompts") if isinstance(payload.get("prompts"), dict) else {}
        draft = prompts.get("master_story_draft")
        self._master_story_draft = copy.deepcopy(draft) if isinstance(draft, dict) else story
        self._apply_master_story_payload(
            story,
            apply_plan={
                "clear_memory": True,
                "auto_create": False,
                "skip_backup": True,
                "persist_memory_snapshot": False,
            },
        )
        self._restore_story_memory_snapshot(story_id)
        self.storage.save_settings(self.settings)
        self.save_state()
        self._populate_master_stories()
        location = str(source_path or "bundle")
        self._record_story_event(
            f"imported story bundle: {location}",
            severity="info",
            kind="bundle",
            persist=True,
        )
        self.refresh_ui()
        self._set_master_story_status(f"Imported story bundle '{story.get('title') or story_id}'.")
        return {
            "accepted": True,
            "message": f"Imported story bundle '{story.get('title') or story_id}'.",
            "story_id": story_id,
        }

    def import_session_state(self, payload: dict[str, Any] | None):
        data = dict(payload or {}).get(self.STATE_KEY)
        if isinstance(data, dict) and isinstance(data.get("session"), dict):
            with self._state_lock:
                if self._shutting_down:
                    return
                self.session = RoleplaySessionState.from_dict(data.get("session"))
                self._ensure_session_persona()
                self.save_state()
                self._last_session_export_state = self._session_export_payload_unlocked()
            self._request_ui_refresh()

    def current_tts_backend(self) -> str:
        try:
            if self.runtime_config is not None:
                return normalize_tts_backend(self.runtime_config.get("tts_backend", ""))
        except Exception:
            return ""
        try:
            snapshot = self.context.tts.snapshot()
            return normalize_tts_backend(snapshot.get("tts_backend") or snapshot.get("backend") or "")
        except Exception:
            return ""

    def story_sounds_enabled(self) -> bool:
        with self._state_lock:
            return bool(self.settings.get("story_sounds_enabled", True))

    def audio_settings_snapshot(self) -> dict[str, Any]:
        with self._state_lock:
            items = self._audiofx_items()
            available = self.available_story_audio_files()
            return {
                "story_sounds_enabled": self.story_sounds_enabled(),
                "audio_fx_items": items,
                "ready_audio_fx_items": [item for item in items if self._audiofx_file_ready(item)],
                "available_audio_files": available,
            }

    def _load_story_event_log(self) -> list[dict[str, str]]:
        raw = self.settings.get("story_event_log")
        if not isinstance(raw, list):
            return []
        entries: list[dict[str, str]] = []
        for item in raw[-80:]:
            if not isinstance(item, dict):
                continue
            message = str(item.get("message") or "").strip()
            if not message:
                continue
            entries.append({
                "time": str(item.get("time") or "").strip(),
                "severity": str(item.get("severity") or "info").strip() or "info",
                "kind": str(item.get("kind") or "").strip(),
                "message": message[:500],
            })
        return entries

    def _record_story_event(
        self,
        message: str,
        *,
        severity: str = "info",
        kind: str = "",
        persist: bool = False,
        commit_guard=None,
    ) -> None:
        text = str(message or "").strip()
        if not text:
            return

        def record() -> bool:
            with self._state_lock:
                if self._shutting_down:
                    return False
                entry = {
                    "time": QtCore.QDateTime.currentDateTimeUtc().toString(QtCore.Qt.ISODate),
                    "severity": str(severity or "info").strip() or "info",
                    "kind": str(kind or "").strip(),
                    "message": text[:500],
                }
                self._story_event_log.append(entry)
                self._story_event_log = self._story_event_log[-80:]
                if persist:
                    self.settings["story_event_log"] = list(self._story_event_log)
                    self.storage.save_settings(self.settings)
                return True

        committed, recorded = self._visual_commit(commit_guard, record)
        if committed and recorded:
            self._request_event_log_refresh()

    def _story_event_log_text(self) -> str:
        if not self._story_event_log:
            return "No skipped or failed story actions have been recorded yet."
        lines = []
        for item in self._story_event_log[-40:]:
            stamp = str(item.get("time") or "").replace("T", " ")[:19]
            severity = str(item.get("severity") or "info").upper()
            kind = str(item.get("kind") or "").strip()
            prefix = f"{stamp} [{severity}]"
            if kind:
                prefix += f" {kind}:"
            lines.append(f"{prefix} {item.get('message') or ''}".strip())
        return "\n".join(lines)

    def _refresh_event_log_panel(self) -> None:
        self._native_event_log_text = self._story_event_log_text()

    def _request_event_log_refresh(self) -> None:
        bridge = getattr(self, "_ui_bridge", None)
        if bridge is None:
            return
        try:
            bridge.event_log_refresh_requested.emit()
        except RuntimeError:
            pass

    def _load_visual_debug_log(self) -> list[dict[str, str]]:
        raw = self.settings.get("visual_reply_debug_log")
        if not isinstance(raw, list):
            return []
        entries: list[dict[str, str]] = []
        for item in raw[-120:]:
            if not isinstance(item, dict):
                continue
            source = str(item.get("source") or "").strip()
            message = str(item.get("message") or "").strip()
            prompt = str(item.get("prompt") or "").strip()
            if not source and not message and not prompt:
                continue
            entries.append({
                "time": str(item.get("time") or "").strip(),
                "status": str(item.get("status") or "info").strip() or "info",
                "source": source[:120],
                "reason": str(item.get("reason") or "").strip()[:80],
                "persona_id": str(item.get("persona_id") or "").strip()[:80],
                "persona": str(item.get("persona") or "").strip()[:120],
                "message": message[:500],
                "prompt": prompt[:1200],
            })
        return entries

    def _record_visual_debug(
        self,
        *,
        source: str,
        reason: str = "",
        persona: PersonaConfig | None = None,
        accepted: bool | None = None,
        message: str = "",
        prompt: str = "",
        persist: bool = True,
        commit_guard=None,
    ) -> None:
        def record() -> bool:
            with self._state_lock:
                if self._shutting_down:
                    return False
                raw_message = str(message or "").strip()
                if accepted is None:
                    status = "queued"
                elif accepted:
                    status = "accepted"
                else:
                    lowered = raw_message.lower()
                    status = "failed" if any(word in lowered for word in ("failed", "error", "exception", "crash")) else "skipped"
                entry = {
                    "time": QtCore.QDateTime.currentDateTimeUtc().toString(QtCore.Qt.ISODate),
                    "status": status,
                    "source": str(source or "").strip()[:120],
                    "reason": str(reason or "").strip()[:80],
                    "persona_id": str(getattr(persona, "id", "") or "").strip()[:80],
                    "persona": str(getattr(persona, "display_name", "") or "").strip()[:120],
                    "message": raw_message[:500],
                    "prompt": str(prompt or "").strip()[:1200],
                }
                self._visual_debug_log.append(entry)
                self._visual_debug_log = self._visual_debug_log[-120:]
                if persist:
                    self.settings["visual_reply_debug_log"] = list(self._visual_debug_log)
                    self.storage.save_settings(self.settings)
                return True

        committed, recorded = self._visual_commit(commit_guard, record)
        if committed and recorded:
            self._request_debug_refresh()

    def _visual_debug_log_text(self) -> str:
        if not self._visual_debug_log:
            return "No Visual Reply calls have been recorded yet."
        lines = []
        for item in self._visual_debug_log[-60:]:
            stamp = str(item.get("time") or "").replace("T", " ")[:19]
            status = str(item.get("status") or "info").upper()
            source = str(item.get("source") or "visual_reply")
            reason = str(item.get("reason") or "").strip()
            persona = str(item.get("persona") or item.get("persona_id") or "").strip()
            message = str(item.get("message") or "").strip()
            head = f"{stamp} [{status}] {source}"
            if reason:
                head += f" reason={reason}"
            if persona:
                head += f" persona={persona}"
            if message:
                head += f" - {message}"
            lines.append(head)
            prompt = str(item.get("prompt") or "").strip()
            if prompt:
                preview = " ".join(prompt.split())
                preview_text = prompting._compact(preview, 420)
                suffix = f" ({len(prompt)} chars)" if len(preview_text) < len(preview) else ""
                lines.append(f"    prompt preview{suffix}: {preview_text}")
        return "\n".join(lines)

    def _clear_visual_debug_log(self):
        with self._state_lock:
            self._visual_debug_log = []
            self.settings["visual_reply_debug_log"] = []
            self.storage.save_settings(self.settings)
        self._request_debug_refresh()

    def available_story_audio_files(self) -> list[dict[str, Any]]:
        items = self._audiofx_items()
        available = self._available_audio_files()
        if items:
            available = self._sync_available_audio_database(items, persist=False)
        return [item for item in available if bool(item.get("ready", False))]

    def active_persona(self) -> PersonaConfig | None:
        self._ensure_session_persona()
        active_id = str(self.session.active_persona_id or "").strip()
        for persona in self.personas:
            if persona.id == active_id:
                return persona
        return self.personas[0] if self.personas else None

    def selected_narrator_persona_id(self) -> str:
        mode = self._narrator_selection_mode()
        wanted = self._stored_narrator_persona_id()
        if mode == "explicit" and wanted and any(persona.id == wanted for persona in self.personas):
            return wanted
        auto = self._auto_ar_narrator_persona()
        return auto.id if auto is not None else ""

    def selected_narrator_persona(self) -> PersonaConfig | None:
        wanted = self.selected_narrator_persona_id()
        return self.persona_by_id(wanted) if wanted else None

    def _stored_narrator_persona_id(self) -> str:
        wanted = normalize_persona_id(self.settings.get("narrator_persona_id", ""))
        return wanted if any(persona.id == wanted for persona in self.personas) else ""

    def _narrator_selection_mode(self) -> str:
        mode = str(self.settings.get("narrator_persona_mode", "") or "").strip().lower()
        if mode in {"auto", "explicit"}:
            return mode
        wanted = self._stored_narrator_persona_id()
        if not wanted:
            return "auto"
        selected = next((persona for persona in self.personas if persona.id == wanted), None)
        if selected is None:
            return "auto"
        if self.session.mode == AR_MODE and self._looks_like_legacy_current_speaker_narrator_setting(selected):
            return "auto"
        return "explicit"

    def _looks_like_legacy_current_speaker_narrator_setting(self, persona: PersonaConfig | None) -> bool:
        if persona is None or self._persona_looks_like_narrator(persona):
            return False
        stale_ids = {
            str(self.session.active_persona_id or "").strip(),
            str(self.session.current_speaker_id or "").strip(),
        }
        if persona.id not in stale_ids:
            return False
        auto = self._auto_ar_narrator_persona()
        return auto is not None and auto.id != persona.id

    def _auto_ar_narrator_persona(self) -> PersonaConfig | None:
        active_ids = [normalize_persona_id(item) for item in list(self.session.ar_state.active_characters or []) if str(item or "").strip()]
        active_order = {persona_id: index for index, persona_id in enumerate(active_ids)}
        ranked: list[tuple[int, int, PersonaConfig]] = []
        for index, persona in enumerate(self.personas):
            if not bool(getattr(persona, "enabled", True)):
                continue
            score = self._persona_narrator_score(persona)
            if score <= 0:
                continue
            if persona.id in active_order:
                score += 30
                order = active_order[persona.id]
            else:
                order = 1000 + index
            voice = getattr(persona, "voice", None)
            if bool(getattr(voice, "enabled", False)) and str(getattr(voice, "sample_path", "") or "").strip():
                score += 5
            ranked.append((score, -order, persona))
        if not ranked:
            return None
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return ranked[0][2]

    def _ordered_narrator_selector_personas(self) -> list[PersonaConfig]:
        scored: list[tuple[int, int, PersonaConfig]] = []
        rest: list[tuple[int, PersonaConfig]] = []
        for index, persona in enumerate(self.personas):
            score = self._persona_narrator_score(persona)
            if score > 0:
                scored.append((score, -index, persona))
            else:
                rest.append((index, persona))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [item[2] for item in scored] + [item[1] for item in rest]

    def _ordered_voice_selector_personas(self) -> list[PersonaConfig]:
        master = [(self._master_narrator_number(persona), index, persona) for index, persona in enumerate(self.personas) if self._persona_is_master_narrator(persona)]
        rest = [(index, persona) for index, persona in enumerate(self.personas) if not self._persona_is_master_narrator(persona)]
        master.sort(key=lambda item: (item[0], item[1]))
        return [item[2] for item in master] + [item[1] for item in rest]

    def _master_narrator_personas(self) -> list[PersonaConfig]:
        return [persona for persona in self.personas if self._persona_is_master_narrator(persona)]

    def _master_narrator_number(self, persona: PersonaConfig | None) -> int:
        if persona is None or not self._persona_is_master_narrator(persona):
            return 0
        for index, item in enumerate(self._master_narrator_personas(), start=1):
            if item.id == persona.id:
                return index
        return 0

    @staticmethod
    def _persona_is_master_narrator(persona: PersonaConfig | None) -> bool:
        return bool(getattr(persona, "master_narrator", False))

    @classmethod
    def _persona_narrator_score(cls, persona: PersonaConfig | None) -> int:
        if persona is None:
            return 0
        display = str(persona.display_name or "").strip().lower()
        role = str(persona.role or "").strip().lower()
        behavior = str(persona.behavior_mode or "").strip().lower()
        tags = {str(tag or "").strip().lower() for tag in list(persona.tags or []) if str(tag or "").strip()}
        text = " ".join(
            [
                str(persona.id or ""),
                display,
                role,
                behavior,
                " ".join(tags),
            ]
        ).lower()
        if cls._persona_is_master_narrator(persona):
            return 140
        if display == "story narrator":
            return 100
        if behavior == "narrator":
            return 90
        if "narrator" in tags:
            return 85
        if "narrator" in role:
            return 82
        if any(token in text for token in ("narration", "immersive-narration", "storyteller", "story teller")):
            return 75
        if "narrator" in text:
            return 70
        return 0

    @staticmethod
    def _persona_looks_like_narrator(persona: PersonaConfig | None) -> bool:
        return MultiPersonaRoleplayController._persona_narrator_score(persona) > 0

    def persona_by_id(self, persona_id: str) -> PersonaConfig | None:
        self._ensure_session_persona()
        target = str(persona_id or "").strip()
        if not target:
            return None
        for persona in self.personas:
            if persona.id == target:
                return persona
        return None

    def current_speaker_persona(self) -> PersonaConfig | None:
        return self.persona_by_id(self.session.current_speaker_id) or self.active_persona()

    def prompt_persona(self) -> PersonaConfig | None:
        if self.session.mode != "Single active persona":
            return self.current_speaker_persona()
        return self.active_persona()

    def ensure_ar_state(self, latest_user_text: str = ""):
        state = self.session.ar_state
        changed = False
        if state.current_scene == "" and self.session.scene_title:
            state.current_scene = self.session.scene_title
            changed = True
        if state.location == "" and self.session.location:
            state.location = self.session.location
            changed = True
        if state.story_goal == "" and self.session.objective:
            state.story_goal = self.session.objective
            changed = True
        if state.mood == "" and self.session.mood:
            state.mood = self.session.mood
            changed = True
        if state.time_of_day == "" and self.session.time_of_day:
            state.time_of_day = self.session.time_of_day
            changed = True
        known = {persona.id for persona in self.personas}
        active = [item for item in list(state.active_characters or []) if item in known]
        if not active:
            narrator = self._ar_narrator_persona()
            seed = []
            if narrator is not None:
                seed.append(narrator.id)
            if self.session.current_speaker_id in known and self.session.current_speaker_id not in seed:
                seed.append(self.session.current_speaker_id)
            for persona in self.personas:
                if persona.enabled and persona.id not in seed:
                    seed.append(persona.id)
                if len(seed) >= 4:
                    break
            state.active_characters = seed
            changed = True
        cleaned_intent = str(latest_user_text or "").strip()
        if cleaned_intent:
            state.player_intent = cleaned_intent[:220]
            changed = True
        if changed:
            logger = getattr(self.context, "logger", None)
            if logger is not None and self.session.mode == AR_MODE:
                logger.info("[AR_MODE] AR state prepared: scene=%s location=%s", state.current_scene, state.location)

    def record_ar_reply(self, assistant_text: str):
        state = self.session.ar_state
        event = str(assistant_text or "").strip()
        if not event:
            return
        self._remote_latest_reply_text = event
        previous_choices = list(state.pending_choices or [])
        changed = self._update_ar_state_from_reply(event)
        changed = self._apply_ar_progression_fallback(event) or changed
        extracted_choices = self._extract_ar_choices(event)
        if extracted_choices and list(state.pending_choices or []) == previous_choices:
            state.pending_choices = extracted_choices
            changed = True
        if not changed:
            compact = event.replace("\r", " ").replace("\n", " ")
            while "  " in compact:
                compact = compact.replace("  ", " ")
            state.recent_events.append(compact[:260])
            state.recent_events = state.recent_events[-12:]
            state.pending_choices = extracted_choices
        if changed:
            self._request_ui_refresh()
        logger = getattr(self.context, "logger", None)
        if logger is not None:
            logger.info("[AR_MODE] Recorded AR reply event; choices=%s", len(state.pending_choices))

    def _update_ar_state_from_reply(self, assistant_text: str) -> bool:
        if self.is_shutdown() or not str(assistant_text or "").strip():
            return False
        try:
            model_name = self._current_provider_model()
            if not model_name:
                return False
            prompt = prompting.build_scene_update_prompt(self.session, self._mprc_strip_audio_tags(assistant_text))
            params = {
                "model": model_name,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are NeuralCompanion's hidden MPRC AR state updater. "
                            "Return strict JSON only, no markdown and no prose. "
                            "Track visible story progression for the next turn and Visual Reply prompts."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.1,
                "max_tokens": 800,
                "response_format": {"type": "json_object"},
                "timeout": 45,
            }
            additional_params: dict[str, Any] = {}
            params["temperature"] = 0.1
            params["max_tokens"] = 800
            params["response_format"] = {"type": "json_object"}
            params["timeout"] = max(45, int(float(params.get("timeout", 0) or 0)))
            known_ids = {persona.id for persona in list(self.personas or [])}
            if self._mprc_instructor_feature_enabled("mprc_instructor_scene_patch_enabled"):
                structured_payload = instructor_adapter.generate_structured_output(
                    provider_execution=self.providers,
                    params=params,
                    response_model=structured_models.ARSceneStatePatch,
                    max_retries=2,
                    logger=getattr(self.context, "logger", None),
                )
                if isinstance(structured_payload, dict) and structured_payload:
                    payload = structured_models.sanitize_scene_patch(structured_payload, known_persona_ids=known_ids)
                    return self._apply_ar_scene_update_payload(payload)
            raw_text = ""
            last_error = None
            for _attempt in range(2):
                try:
                    raw_text = self._complete_provider_request(params, additional_params)
                    break
                except Exception as exc:
                    last_error = exc
                    message = str(exc).lower()
                    changed = False
                    if "response_format" in message or "json_object" in message:
                        changed = "response_format" in params
                        params.pop("response_format", None)
                    if ("timeout" in message or "unsupported" in message) and "timeout" in params:
                        params.pop("timeout", None)
                        changed = True
                    if not changed:
                        raise
            if not raw_text and last_error is not None:
                raise last_error
            payload = prompting.parse_json_object(raw_text) or {}
            if self._mprc_instructor_feature_enabled("mprc_instructor_scene_patch_enabled"):
                payload = structured_models.sanitize_scene_patch(payload, known_persona_ids=known_ids)
            return self._apply_ar_scene_update_payload(payload)
        except Exception as exc:
            logger = getattr(self.context, "logger", None)
            if logger is not None:
                logger.info("[MPRC] Hidden AR state update skipped: %s", exc)
            return False

    def _apply_ar_scene_update_payload(self, payload: dict[str, Any]) -> bool:
        if not isinstance(payload, dict):
            return False
        state = self.session.ar_state
        changed = False

        def assign_text(target: Any, attr: str, value: Any, limit: int) -> bool:
            text = prompting._compact(str(value or "").strip(), limit)
            if not text or text == str(getattr(target, attr, "") or ""):
                return False
            setattr(target, attr, text)
            return True

        changed = assign_text(self.session, "scene_summary", payload.get("scene_summary"), 1400) or changed
        changed = assign_text(state, "current_scene", payload.get("current_scene"), 360) or changed
        changed = assign_text(state, "location", payload.get("location"), 180) or changed
        changed = assign_text(state, "time_of_day", payload.get("time_of_day"), 120) or changed
        changed = assign_text(state, "mood", payload.get("mood"), 180) or changed
        changed = assign_text(state, "story_goal", payload.get("story_goal") or payload.get("current_objective"), 300) or changed

        try:
            tension = int(payload.get("tension_level"))
            tension = max(0, min(10, tension))
            if tension != int(getattr(state, "tension_level", 0) or 0):
                state.tension_level = tension
                changed = True
        except Exception:
            pass

        recent_event = prompting._compact(str(payload.get("recent_event") or "").strip(), 260)
        if recent_event:
            events = [str(item or "").strip() for item in list(state.recent_events or []) if str(item or "").strip()]
            if not events or events[-1] != recent_event:
                events.append(recent_event)
                state.recent_events = events[-12:]
                changed = True

        raw_choices = payload.get("pending_choices")
        if isinstance(raw_choices, list):
            choices = [prompting._compact(str(item or "").strip(), 180) for item in raw_choices if str(item or "").strip()]
            choices = choices[:6]
            if choices != list(state.pending_choices or []):
                state.pending_choices = choices
                changed = True

        summaries = payload.get("character_state_summaries")
        if isinstance(summaries, dict):
            known_ids = {persona.id for persona in self.personas}
            current = dict(self.session.character_state_summaries or {})
            for persona_id, summary in summaries.items():
                normalized = normalize_persona_id(str(persona_id or ""))
                if normalized not in known_ids:
                    continue
                text = prompting._compact(str(summary or "").strip(), 360)
                if text and current.get(normalized) != text:
                    current[normalized] = text
                    changed = True
            if changed:
                self.session.character_state_summaries = current
        return changed

    def _apply_ar_progression_fallback(self, assistant_text: str) -> bool:
        visible = self._mprc_latest_visible_story_beat(assistant_text)
        if not visible:
            return False
        state = self.session.ar_state
        changed = False
        compact_scene = prompting._compact(visible, 360)
        current_scene = str(getattr(state, "current_scene", "") or "").strip()
        if compact_scene and compact_scene.lower() != current_scene.lower():
            state.current_scene = compact_scene
            changed = True
        visible_reply = self._strip_mprc_choices_block(self._mprc_strip_audio_tags(str(assistant_text or "")))
        inferred_location = self._infer_mprc_progression_location(
            "\n".join(
                part
                for part in (
                    str(getattr(state, "player_intent", "") or ""),
                    visible_reply,
                    visible,
                )
                if part.strip()
            )
        )
        current_location = str(getattr(state, "location", "") or "").strip()
        if inferred_location and inferred_location.lower() != current_location.lower():
            state.location = inferred_location
            changed = True
        recent_event = prompting._compact(visible, 260)
        if recent_event:
            events = [str(item or "").strip() for item in list(state.recent_events or []) if str(item or "").strip()]
            if not events or events[-1] != recent_event:
                events.append(recent_event)
                state.recent_events = events[-12:]
                changed = True
        return changed

    @staticmethod
    def _mprc_latest_visible_story_beat(text: str) -> str:
        raw = str(text or "").strip()
        if not raw:
            return ""
        raw = re.sub(
            r"\[(?:AMBIENCE|AMBIENT|MUSIC|FX|SFX|STINGER|AUDIO):[^\]]+\]",
            " ",
            raw,
            flags=re.IGNORECASE,
        )
        raw = re.sub(r"(?is)\[CHOICES\].*$", " ", raw)
        raw = re.sub(r"\[(?:/?NARRATOR|CHARACTER:\s*[^\]]+)\]", "\n", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\b(?:Story|Assistant)\s*:\s*", " ", raw, flags=re.IGNORECASE)
        paragraphs = [
            re.sub(r"\s+", " ", part).strip(" -")
            for part in re.split(r"\n{2,}|\r?\n", raw)
        ]
        blocked_starts = ("what do you do", "what's your next move", "whats your next move")
        for paragraph in reversed(paragraphs):
            lowered = paragraph.lower()
            if len(paragraph) < 24 or lowered.startswith(blocked_starts):
                continue
            return prompting._compact(paragraph, 700)
        compact = re.sub(r"\s+", " ", raw).strip()
        return prompting._compact(compact, 700)

    def _infer_mprc_progression_location(self, text: str) -> str:
        value = re.sub(r"\s+", " ", str(text or "").strip().lower())
        if not value:
            return ""
        if re.search(r"\b(forest|woods|woodland|wilds|wilderness|grove|tree line|treeline)\b", value):
            return "Wilds outside the tavern" if re.search(r"\b(tavern|inn)\b", value) else "Forest"
        if re.search(r"\b(street|road|lane|alley|market|square|courtyard|stable yard)\b", value):
            return "Street outside the tavern" if re.search(r"\b(tavern|inn)\b", value) else "Street"
        if re.search(r"\b(outside|outdoors|open air|threshold|through the door|out the door|leaves? the tavern|leaves? the inn|leaving the tavern|leaving the inn|steps? out|walks? out|push(?:es)? .*door open)\b", value):
            return "Outside the tavern" if re.search(r"\b(tavern|inn)\b", value) else "Outside"
        for pattern in (
            r"\b(?:enter|enters|entered|step into|steps into|walk into|walks into|move into|moves into)\s+the\s+([a-z][a-z0-9 '\-]{2,42})",
            r"\b(?:arrive at|arrives at|reach|reaches|reached)\s+the\s+([a-z][a-z0-9 '\-]{2,42})",
        ):
            match = re.search(pattern, value)
            if match:
                location = re.split(r"\b(?:and|as|while|where|before|with)\b|[,.]", match.group(1))[0].strip(" ',-")
                words = [word for word in location.split() if word]
                if 1 <= len(words) <= 6:
                    return " ".join(word.capitalize() for word in words)
        return ""

    def ensure_personas_from_assistant_text(self, assistant_text: str, *, source: str = "assistant_reply") -> list[str]:
        text = str(assistant_text or "")
        if not text.strip():
            return []
        created_ids: list[str] = []
        for name, context_text in self._character_contexts_from_text(text):
            before_auto = self._chat_auto_created_persona_ids()
            persona = self.ensure_persona_for_character_label(name, context_text=context_text, source=source, save=False)
            after_auto = self._chat_auto_created_persona_ids()
            if persona is not None and persona.id not in before_auto and persona.id in after_auto and persona.id not in created_ids:
                created_ids.append(persona.id)
        if created_ids:
            self._mark_auto_personas(created_ids)
            self.save_state()
            self._request_ui_refresh()
            logger = getattr(self.context, "logger", None)
            if logger is not None:
                logger.info("[MPRC] Auto-created persona(s) from chat: %s", ", ".join(created_ids))
        return created_ids

    def ensure_persona_for_character_label(self, name: str, *, context_text: str = "", source: str = "chat", save: bool = True) -> PersonaConfig | None:
        display_name = self._clean_character_name(name)
        if not display_name:
            return None
        existing = self._find_persona_by_name_or_id(display_name)
        if existing is not None:
            self._add_persona_to_active_character_state(existing.id)
            if save:
                self.save_state()
            return existing
        if not self._character_label_looks_auto_creatable(display_name):
            logger = getattr(self.context, "logger", None)
            if logger is not None:
                logger.info("[MPRC] Ignored non-name character label from %s: %s", source, display_name)
            return None
        persona = self._build_auto_chat_persona(display_name, context_text=context_text, source=source)
        self.personas.append(persona)
        self._mark_auto_personas([persona.id])
        self._add_persona_to_active_character_state(persona.id)
        if not self.session.active_persona_id:
            self.session.active_persona_id = persona.id
        if not self.session.current_speaker_id:
            self.session.current_speaker_id = persona.id
        if save:
            self.save_state()
            self._request_ui_refresh()
            logger = getattr(self.context, "logger", None)
            if logger is not None:
                logger.info("[MPRC] Auto-created persona from %s: %s (%s)", source, persona.display_name, persona.id)
        return persona

    def _character_contexts_from_text(self, text: str) -> list[tuple[str, str]]:
        value = str(text or "")
        pattern = re.compile(r"\[CHARACTER\s*:\s*([^\]]{1,120})\]\s*", re.IGNORECASE)
        matches = list(pattern.finditer(value))
        contexts: list[tuple[str, str]] = []
        seen: set[str] = set()
        section_pattern = re.compile(
            r"\n\s*\[(?:CHARACTER\s*:\s*[^\]]+|NARRATOR|CHOICES|AMBIENCE\s*:?[^\]]*|AMBIENT\s*:?[^\]]*|MUSIC\s*:?[^\]]*|FX\s*:?[^\]]*|SFX\s*:?[^\]]*|STINGER\s*:?[^\]]*|AUDIO\s*:?[^\]]*|SOUND\s*:?[^\]]*)\]",
            re.IGNORECASE,
        )
        for index, match in enumerate(matches):
            name = self._clean_character_name(match.group(1))
            if not name:
                continue
            key = normalize_persona_id(name)
            if key in seen:
                continue
            seen.add(key)
            next_start = matches[index + 1].start() if index + 1 < len(matches) else len(value)
            section_match = section_pattern.search(value, match.end())
            if section_match is not None:
                next_start = min(next_start, section_match.start())
            before = value[max(0, match.start() - 420) : match.start()]
            after = value[match.end() : min(len(value), next_start, match.end() + 700)]
            context = self._compact_character_context(before, after)
            contexts.append((name, context))
        return contexts

    def _compact_character_context(self, before: str, after: str) -> str:
        pieces = []
        before_text = self._strip_story_control_tags(before)
        if before_text:
            sentences = re.split(r"(?<=[.!?])\s+", before_text)
            pieces.append(" ".join(sentence for sentence in sentences[-2:] if sentence).strip())
        after_text = self._strip_story_control_tags(after)
        if after_text:
            pieces.append(after_text)
        compact = " ".join(piece for piece in pieces if piece)
        compact = re.sub(r"\s+", " ", compact).strip()
        return compact[:700]

    @staticmethod
    def _strip_story_control_tags(text: str) -> str:
        value = str(text or "")
        value = re.sub(r"\[(?:NARRATOR|CHOICES|AMBIENCE\s*:?[^\]]*|AMBIENT\s*:?[^\]]*|MUSIC\s*:?[^\]]*|FX\s*:?[^\]]*|SFX\s*:?[^\]]*|STINGER\s*:?[^\]]*|AUDIO\s*:?[^\]]*|SOUND\s*:?[^\]]*)\]", " ", value, flags=re.IGNORECASE)
        value = re.sub(r"\[(?:neutral|laugh|chuckle|sigh|groan|gasp|clear throat|sniff)\]", " ", value, flags=re.IGNORECASE)
        return value.strip()

    def _clean_character_name(self, name: Any) -> str:
        value = str(name or "").strip()
        value = re.sub(r"\s+", " ", value).strip(" \t\r\n:;,.")
        if not value or len(value) > 80:
            return ""
        lowered = value.lower()
        blocked = {
            "narrator",
            "choices",
            "choice",
            "ambience",
            "ambient",
            "music",
            "fx",
            "sfx",
            "stinger",
            "audio",
            "sound",
            "you",
            "assistant",
            "user",
        }
        if lowered in blocked:
            return ""
        if not re.search(r"[A-Za-z]", value):
            return ""
        return value

    @staticmethod
    def _character_label_looks_auto_creatable(name: str) -> bool:
        value = str(name or "").strip()
        if not value:
            return False
        if re.search(r"[.!?\"“”]", value):
            return False
        words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'_-]*", value)
        if not words or len(words) > 5:
            return False
        lowered_words = {word.lower().strip("_-") for word in words}
        phrase_markers = {
            "and",
            "or",
            "but",
            "you",
            "your",
            "yours",
            "me",
            "my",
            "mine",
            "we",
            "our",
            "ours",
            "they",
            "their",
            "it",
            "its",
            "will",
            "would",
            "should",
            "could",
            "can",
            "can't",
            "cannot",
            "have",
            "has",
            "had",
            "are",
            "is",
            "was",
            "were",
            "look",
            "tell",
            "whisper",
            "again",
        }
        if lowered_words & phrase_markers:
            return False
        first_alpha = re.search(r"[A-Za-z]", value)
        if first_alpha is not None and not first_alpha.group(0).isupper():
            return False
        return True

    @staticmethod
    def _persona_name_aliases(persona: PersonaConfig) -> set[str]:
        aliases: set[str] = set()

        def add(value: Any) -> None:
            text = str(value or "").strip()
            if not text:
                return
            aliases.add(text.lower())
            aliases.add(normalize_persona_id(text))

        add(getattr(persona, "id", ""))
        display_name = str(getattr(persona, "display_name", "") or "").strip()
        add(display_name)
        without_parenthetical = re.sub(r"\s*\([^)]*\)\s*", " ", display_name).strip()
        add(without_parenthetical)
        for alias in re.findall(r"\(([^)]{1,80})\)", display_name):
            add(alias)
        return {alias for alias in aliases if alias}

    def _find_persona_by_name_or_id(self, name: str) -> PersonaConfig | None:
        wanted_id = normalize_persona_id(name)
        wanted_name = str(name or "").strip().lower()
        wanted_aliases = {wanted_id, wanted_name}
        for persona in self.personas:
            if persona.id == wanted_id or wanted_id in self._persona_name_aliases(persona):
                return persona
        for persona in self.personas:
            if wanted_aliases & self._persona_name_aliases(persona):
                return persona
        return None

    def _build_auto_chat_persona(self, display_name: str, *, context_text: str = "", source: str = "chat") -> PersonaConfig:
        existing_ids = {p.id for p in self.personas}
        persona_id = unique_persona_id(display_name, existing_ids)
        context = self._compact_auto_persona_description(display_name, context_text)
        role = self._infer_auto_persona_role(display_name, context)
        tags = self._infer_auto_persona_tags(context)
        description = context or f"Auto-created story character introduced in the active chat as {display_name}."
        ar_description = description
        system_prompt = (
            f"You are {display_name}. Stay consistent with the established story description and speak only as this character. "
            "Keep replies grounded in the current scene, preserve user agency, and avoid taking over the user's actions."
        )
        ar_system_prompt = (
            f"In AlternativeReality mode, portray {display_name} as a cinematic story character. "
            "Use the established scene description, speak in a distinct voice when tagged, and let the narrator handle action narration unless this character is directly speaking."
        )
        persona = PersonaConfig(
            id=persona_id,
            enabled=True,
            display_name=display_name,
            role=role,
            description=description,
            system_prompt=system_prompt,
            ar_profile_enabled=True,
            ar_description=ar_description,
            ar_system_prompt=ar_system_prompt,
            speaking_style=self._infer_auto_speaking_style(context),
            allowed_tone="consistent with the active story, consensual, non-explicit, and user-agency friendly",
            response_length="balanced",
            memory_scope="persona-only",
            behavior_mode="group participant",
            tags=tags,
        )
        persona.visual.enabled = True
        persona.visual.mode = "manual"
        persona.visual.provider = "inherit"
        persona.visual.size = "inherit"
        persona.visual.character_description = self._auto_visual_description(display_name, context)
        persona.visual.clothing_props = self._auto_visual_clothing(context)
        persona.visual.environment_style = self.session.location or self.session.ar_state.location or self.session.scene_title
        persona.visual.negative_prompt = "text, watermark, logo, distorted face, extra limbs"
        return persona

    def _compact_auto_persona_description(self, display_name: str, context_text: str) -> str:
        context = re.sub(r"\s+", " ", str(context_text or "")).strip()
        if not context:
            return ""
        context = re.sub(rf"^\s*{re.escape(display_name)}\s*[:\-]\s*", "", context, flags=re.IGNORECASE)
        return f"Auto-created from active chat: {context[:460].strip()}"

    def _infer_auto_persona_role(self, display_name: str, context: str) -> str:
        lowered = str(context or "").lower()
        role_markers = (
            ("captain", "captain"),
            ("detective", "detective"),
            ("merchant", "merchant"),
            ("vendor", "vendor"),
            ("guard", "guard"),
            ("queen", "queen"),
            ("king", "king"),
            ("mage", "mage"),
            ("wizard", "wizard"),
            ("orc", "orc character"),
            ("goblin", "goblin character"),
            ("demon", "demon character"),
            ("robot", "robot character"),
            ("android", "android character"),
            ("guide", "guide"),
            ("ally", "ally"),
            ("enemy", "rival"),
            ("villain", "antagonist"),
        )
        for marker, role in role_markers:
            if marker in lowered or marker in display_name.lower():
                return role
        return "story character"

    def _infer_auto_persona_tags(self, context: str) -> list[str]:
        lowered = str(context or "").lower()
        tags = ["auto", "story", "chat-created"]
        for marker, tag in (
            ("fantasy", "fantasy"),
            ("magic", "fantasy"),
            ("orc", "fantasy"),
            ("goblin", "fantasy"),
            ("cyber", "sci-fi"),
            ("neon", "sci-fi"),
            ("submarine", "adventure"),
            ("captain", "adventure"),
            ("mystery", "mystery"),
            ("detective", "mystery"),
            ("horror", "horror"),
        ):
            if marker in lowered and tag not in tags:
                tags.append(tag)
        return tags[:10]

    def _infer_auto_speaking_style(self, context: str) -> str:
        lowered = str(context or "").lower()
        if "gruff" in lowered:
            return "gruff, direct, and grounded"
        if "snark" in lowered or "sarcastic" in lowered:
            return "snarky, quick, and expressive"
        if "whisper" in lowered or "quiet" in lowered:
            return "quiet, careful, and atmospheric"
        if "captain" in lowered or "command" in lowered:
            return "controlled, authoritative, and deliberate"
        return "distinct, consistent, and scene-aware"

    def _auto_visual_description(self, display_name: str, context: str) -> str:
        pieces = [
            f"{display_name}, story character portrait",
            context,
            "clear face, readable silhouette, expressive eyes",
        ]
        return ". ".join(str(piece or "").strip(" .") for piece in pieces if str(piece or "").strip())[:900]

    def _auto_visual_clothing(self, context: str) -> str:
        lowered = str(context or "").lower()
        if any(word in lowered for word in ("fantasy", "orc", "goblin", "mage", "wizard", "castle")):
            return "fantasy costume and props inferred from the story description"
        if any(word in lowered for word in ("cyber", "neon", "hologram", "android")):
            return "futuristic clothing, cyberpunk details, and story-appropriate gear"
        if any(word in lowered for word in ("captain", "submarine", "sea", "nautilus")):
            return "nautical adventure clothing and story-appropriate equipment"
        return "story-appropriate outfit and props"

    def _chat_auto_created_persona_ids(self) -> set[str]:
        raw = self.settings.get("chat_auto_created_persona_ids")
        if not isinstance(raw, list):
            return set()
        return {normalize_persona_id(item) for item in raw if str(item or "").strip()}

    def _mark_auto_personas(self, persona_ids: list[str]) -> None:
        current = self._chat_auto_created_persona_ids()
        for persona_id in list(persona_ids or []):
            normalized = normalize_persona_id(persona_id)
            if normalized:
                current.add(normalized)
        self.settings["chat_auto_created_persona_ids"] = sorted(current)
        self.storage.save_settings(self.settings)

    def _remove_chat_auto_personas(self) -> int:
        auto_ids = self._chat_auto_created_persona_ids()
        if not auto_ids:
            return 0
        existing_ids = {persona.id for persona in self.personas}
        removed_ids = {persona_id for persona_id in auto_ids if persona_id in existing_ids}
        if removed_ids:
            self.personas = [persona for persona in self.personas if persona.id not in removed_ids]
            self.session.character_state_summaries = {
                str(persona_id): summary
                for persona_id, summary in dict(self.session.character_state_summaries or {}).items()
                if normalize_persona_id(persona_id) not in removed_ids
            }
            state = self.session.ar_state
            state.active_characters = [
                normalize_persona_id(persona_id)
                for persona_id in list(state.active_characters or [])
                if normalize_persona_id(persona_id) not in removed_ids
            ]
            if self.session.active_persona_id in removed_ids:
                self.session.active_persona_id = ""
            if self.session.current_speaker_id in removed_ids:
                self.session.current_speaker_id = ""
            self._ensure_session_persona()
        for key in (
            "chat_auto_created_persona_ids",
            "master_story_created_persona_ids",
            "master_story_linked_persona_ids",
        ):
            raw = self.settings.get(key)
            if isinstance(raw, list):
                self.settings[key] = [
                    normalize_persona_id(item)
                    for item in raw
                    if normalize_persona_id(item) and normalize_persona_id(item) not in auto_ids
                ]
        for key in ("narrator_persona_id", "selected_narrator_id"):
            if normalize_persona_id(self.settings.get(key)) in removed_ids:
                self.settings[key] = ""
        self.storage.save_settings(self.settings)
        return len(removed_ids)

    def _link_persona_to_current_story(self, persona_id: str) -> None:
        normalized = normalize_persona_id(persona_id)
        if not normalized:
            return
        linked = self._master_story_linked_persona_ids()
        linked.add(normalized)
        self.settings["master_story_linked_persona_ids"] = sorted(linked)
        created = self._master_story_created_persona_ids()
        if normalized in self._chat_auto_created_persona_ids():
            created.add(normalized)
            self.settings["master_story_created_persona_ids"] = sorted(created)
        self.storage.save_settings(self.settings)

    def _add_persona_to_active_character_state(self, persona_id: str) -> None:
        normalized = normalize_persona_id(persona_id)
        if not normalized:
            return
        if normalized not in self.session.character_state_summaries:
            persona = self.persona_by_id(normalized)
            if persona is not None:
                self.session.character_state_summaries[normalized] = ". ".join(
                    part for part in (persona.role, persona.description or persona.ar_description) if part
                )[:300]
        state = self.session.ar_state
        active = [item for item in list(state.active_characters or []) if item]
        if normalized not in active:
            active.append(normalized)
            state.active_characters = active[-8:]

    def _request_ui_refresh(self) -> None:
        if self.is_shutdown():
            return
        bridge = getattr(self, "_ui_bridge", None)
        if bridge is not None:
            try:
                bridge.refresh_requested.emit()
            except RuntimeError:
                pass

    def request_auto_visual_reply(
        self,
        persona_id: str,
        reason: str,
        source_text: str = "",
        *,
        policy_persona_id: str = "",
        scene_focused: bool = False,
    ) -> None:
        if self.is_shutdown():
            return
        persona = self.persona_by_id(str(persona_id or "").strip())
        self._record_visual_debug(
            source="auto_visual_trigger",
            reason=str(reason or "manual"),
            persona=persona,
            accepted=None,
            message="Auto Visual Reply request queued for a background worker.",
        )
        if not self._queue_visual_worker(
            "mprc_visual_reply",
            lambda commit_guard: self._run_auto_visual_reply_request(
                str(persona_id or ""),
                str(reason or "manual"),
                str(source_text or ""),
                str(policy_persona_id or ""),
                bool(scene_focused),
                commit_guard=commit_guard,
            ),
        ):
            self._record_visual_debug(
                source="auto_visual_trigger",
                reason=str(reason or "manual"),
                persona=persona,
                accepted=False,
                message="Auto Visual Reply request could not start a background worker.",
            )

    def _queue_visual_worker(self, prefix: str, target) -> bool:
        token = self._new_worker_token(str(prefix or "mprc_visual"))
        if not token:
            return False

        def worker(cancellation):
            commit_guard = _VisualCommitAuthority(self, token, cancellation)
            try:
                if commit_guard():
                    target(commit_guard)
            except Exception as exc:
                logger = getattr(self.context, "logger", None)
                if logger is not None:
                    logger.warning("[MPRC] Background visual worker failed: %s", exc)
            finally:
                self._finish_worker_token(token)

        try:
            self.tasks.spawn(f"{str(prefix or 'mprc-visual-worker')}:{token}", worker)
        except Exception:
            self._cancel_worker_token(token)
            return False
        self._request_ui_refresh()
        return True

    def _visual_commit_allowed(self, commit_guard=None) -> bool:
        if self.is_shutdown():
            return False
        try:
            return commit_guard is None or bool(commit_guard())
        except Exception:
            return False

    def _run_visual_commit(self, token: str, effect):
        with self._visual_commit_lock:
            if (
                self._shutdown_requested.is_set()
                or self._shutting_down
                or not self._worker_should_emit(token)
            ):
                return False, None
            result = effect()
            if self._shutdown_requested.is_set() or self._shutting_down:
                return False, None
            return True, result

    def _visual_commit(self, commit_guard, effect):
        runner = getattr(commit_guard, "run", None)
        if callable(runner):
            return runner(effect)
        with self._visual_commit_lock:
            if not self._visual_commit_allowed(commit_guard):
                return False, None
            return True, effect()

    def _emit_manual_visual_finished(
        self,
        kind: str,
        persona_id: str,
        result: Any,
        *,
        commit_guard=None,
    ) -> None:
        bridge = getattr(self, "_ui_bridge", None)
        if bridge is None:
            return
        try:
            self._visual_commit(
                commit_guard,
                lambda: bridge.manual_visual_finished.emit(str(kind or ""), str(persona_id or ""), result),
            )
        except RuntimeError:
            pass

    def _on_manual_visual_finished(self, kind: str, persona_id: str, result: Any) -> None:
        result_dict = dict(result or {}) if isinstance(result, dict) else {"message": str(result or "")}
        key = str(persona_id or "").strip()
        if kind == "character_picture":
            with self._state_lock:
                self._manual_character_image_inflight.discard(key)
            if not bool(result_dict.get("ok")):
                self._warn("Create Character Picture", result_dict.get("message") or "Character picture generation was not accepted.")
            return
        if kind in {"manual_visual_reply", "status_visual_reply"}:
            self._debug_visual_prompt = json.dumps(result_dict, indent=2, ensure_ascii=True)
            self._refresh_debug()
        if kind == "status_visual_reply":
            persona = self.persona_by_id(key)
            persona_name = str(getattr(persona, "display_name", "") or key or "selected persona")
            accepted = bool(result_dict.get("accepted"))
            message = str(result_dict.get("message") or "submitted")
            self._record_story_event(
                f"visual test {'accepted' if accepted else 'skipped'} for {persona_name}: {message}",
                severity="info" if accepted else "warning",
                kind="visual",
                persist=True,
            )
            self._set_master_story_status(f"Visual Reply test for {persona_name}: {message}.")
        if kind == "story_avatar_batch":
            message = str(result_dict.get("message") or "").strip() or "Story avatar generation finished."
            accepted = bool(result_dict.get("accepted", True))
            lowered = message.lower()
            severity = "warning" if not accepted or any(word in lowered for word in ("failed", "skipped", "unavailable")) else "info"
            self._record_story_event(
                f"avatar generation batch: {message}",
                severity=severity,
                kind="visual",
                persist=True,
            )
            self._set_master_story_status(f"Story avatar generation finished: {message}")
            self._request_ui_refresh()

    def _run_manual_visual_reply_request(self, persona_id: str, *, kind: str, commit_guard=None) -> None:
        result: dict[str, Any]
        try:
            persona = self.persona_by_id(str(persona_id or "").strip()) if str(persona_id or "").strip() else None
            result = self.visual_reply.request_generation(
                persona=persona,
                reason="manual",
                source_text=self._remote_latest_reply() if persona is not None and prompting.flexible_visual_appearance(persona) else "",
                commit_guard=commit_guard,
            )
        except Exception as exc:
            result = {"accepted": False, "message": f"Visual Reply request failed: {exc}"}
        self._emit_manual_visual_finished(
            kind,
            str(persona_id or ""),
            result,
            commit_guard=commit_guard,
        )

    def _run_auto_visual_reply_request(
        self,
        persona_id: str,
        reason: str,
        source_text: str = "",
        policy_persona_id: str = "",
        scene_focused: bool = False,
        *,
        commit_guard=None,
    ) -> None:
        if not self._visual_commit_allowed(commit_guard):
            return
        persona = self.persona_by_id(persona_id)
        if persona is None:
            self._record_visual_debug(
                source="auto_visual_request",
                reason=str(reason or "manual"),
                accepted=False,
                message=f"No persona matched Visual Reply request id '{persona_id}'.",
                commit_guard=commit_guard,
            )
            return
        policy_persona = self.persona_by_id(policy_persona_id) if policy_persona_id else persona
        result = self.visual_reply.request_generation(
            persona=persona,
            policy_persona=policy_persona or persona,
            reason=reason,
            source_text=source_text,
            scene_focused=scene_focused,
            commit_guard=commit_guard,
        )
        if not self._visual_commit_allowed(commit_guard):
            return
        logger = getattr(self.context, "logger", None)
        if logger is not None and not bool(result.get("accepted")):
            logger.info("MPRC auto Visual Reply skipped: %s", result.get("message", "not accepted"))
        if not bool(result.get("accepted")):
            self._record_story_event(
                f"image skipped: {result.get('message', 'not accepted')}",
                severity="info",
                kind="visual",
                persist=True,
                commit_guard=commit_guard,
            )

    def build_visual_action_prompt(
        self,
        *,
        persona: PersonaConfig,
        source_text: str,
        base_prompt: str,
        reason: str = "manual",
        provider: str = "",
        scene_focused: bool = False,
    ) -> str:
        reply_text = self._mprc_strip_audio_tags(str(source_text or "").strip())
        if not reply_text or persona is None or self.is_shutdown():
            return ""
        provider_id = prompting.normalize_visual_provider_id(provider or "inherit") or "inherit"
        prompt_style = prompting.visual_prompt_style(provider_id)
        try:
            model_name = self._current_provider_model()
            if not model_name:
                return ""
            state = self.session.ar_state
            active_ids = [normalize_persona_id(item) for item in list(state.active_characters or []) if str(item or "").strip()]
            if not active_ids:
                active_ids = [self.session.current_speaker_id, self.session.active_persona_id, persona.id]
            active_cast = []
            seen = set()
            for persona_id in active_ids:
                cast_persona = self.persona_by_id(persona_id)
                if cast_persona is None or cast_persona.id in seen:
                    continue
                if scene_focused and self._persona_looks_like_narrator(cast_persona):
                    continue
                seen.add(cast_persona.id)
                active_cast.append(
                    {
                        "id": cast_persona.id,
                        "name": cast_persona.display_name,
                        "role": cast_persona.role or cast_persona.behavior_mode,
                        "appearance": (
                            cast_persona.visual.character_description
                            or cast_persona.ar_description
                            or cast_persona.description
                        ),
                        "clothing_props": cast_persona.visual.clothing_props,
                        "appearance_freedom": "flexible" if prompting.flexible_visual_appearance(cast_persona) else "strict",
                        "keep_continuity": bool(cast_persona.visual.keep_continuity),
                    }
                )
            visual = persona.visual
            flexible_appearance = prompting.flexible_visual_appearance(persona)
            prompt_payload = {
                "task": "Create one image prompt for the current MPRC story reply.",
                "appearance_freedom": "flexible" if flexible_appearance else "strict",
                "keep_continuity": bool(visual.keep_continuity),
                "provider": provider_id,
                "prompt_style": prompt_style,
                "trigger_reason": str(reason or "manual"),
                "selected_visual_persona": None
                if scene_focused
                else {
                    "id": persona.id,
                    "name": persona.display_name,
                    "role": persona.role or persona.behavior_mode,
                    "appearance": visual.character_description or persona.ar_description or persona.description,
                    "clothing_props": visual.clothing_props,
                    "environment_style": visual.environment_style,
                    "negative_prompt": visual.negative_prompt,
                    "include_active_speaker_focus": bool(visual.include_active_speaker),
                },
                "scene_focused": bool(scene_focused),
                "scene_state": {
                    "title": self.session.scene_title,
                    "summary": self._mprc_compact(self.session.scene_summary, 600),
                    "current_scene": self._mprc_compact(state.current_scene or self.session.scene_title, 360),
                    "location": state.location or self.session.location,
                    "time_of_day": state.time_of_day or self.session.time_of_day,
                    "mood": state.mood or self.session.mood,
                    "objective": state.story_goal or self.session.objective,
                    "recent_events": [
                        self._mprc_compact(item, 220)
                        for item in list(state.recent_events or self.session.recent_events or [])[-4:]
                        if str(item or "").strip()
                    ],
                    "pending_choices": [
                        self._mprc_compact(item, 160)
                        for item in list(state.pending_choices or [])[:4]
                        if str(item or "").strip()
                    ],
                },
                "active_cast": active_cast[:6],
                "current_story_reply": self._mprc_compact(reply_text, 2400),
                "fallback_prompt": self._mprc_compact(base_prompt, 900),
            }
            policy_cast = list(prompt_payload["active_cast"])
            if not scene_focused and not any(item["id"] == persona.id for item in policy_cast):
                policy_cast.append({
                    "id": persona.id, "name": persona.display_name,
                    "appearance_freedom": prompt_payload["appearance_freedom"],
                    "keep_continuity": bool(visual.keep_continuity),
                })
            flexible_names = [
                prompting._compact(item["name"], 32) for item in policy_cast
                if item["appearance_freedom"] == "flexible"
            ]
            strict_names = [
                prompting._compact(item["name"], 32) for item in policy_cast
                if item["appearance_freedom"] != "flexible" and item["keep_continuity"]
            ]
            if self._mprc_instructor_feature_enabled("mprc_instructor_visual_beat_enabled"):
                visual_beat = structured_models.sanitize_visual_beat(
                    {
                        "subject": "" if scene_focused else persona.display_name,
                        "action": reply_text,
                        "setting": state.location or self.session.location or state.current_scene or self.session.scene_title,
                        "mood": state.mood or self.session.mood,
                        "source_excerpt": reply_text,
                        "what_to_avoid": "choices text, hidden prompt notes, stale scene summary",
                    },
                    latest_turn_text=reply_text,
                )
                if visual_beat:
                    prompt_payload["validated_current_visual_beat"] = visual_beat
            system_prompt = (
                "You are NeuralCompanion's hidden MPRC visual-action prompt planner. "
                "Return strict JSON only, no markdown and no prose. "
                "Focus on the visible action happening in current_story_reply. "
                "Use scene_state and active_cast only to keep identity, setting, and continuity grounded. "
                "current_story_reply overrides older scene_state summary, selected_visual_persona environment_style, and stale location memory. "
                "When selected_visual_persona is present, use it as character identity inside the current scene, not as a static portrait subject. "
                "When scene_focused is true, do not depict the narrator or invent a foreground character. "
                "If selected_visual_persona.include_active_speaker_focus is false, do not make the active speaker name or face the main composition unless the current story reply visibly requires it. "
                "Do not invent new characters, props, injuries, weapons, monsters, or location changes unless visible in the current story reply. "
                "Do not include hidden reasoning."
            )
            if flexible_names:
                system_prompt += (
                    " Appearance freedom takes priority over saved appearance and wardrobe. "
                    "For flexible cast entries, keep only a few defining identity traits and their age; "
                    "allow changes to hair, makeup, clothing, facial styling and presentation. "
                    "Treat their saved appearance/clothing as optional inspiration, not requirements. "
                    "The current reply overrides those saved details. Do not copy avatar pose or framing. "
                    "Keep other cast members' own appearance policies."
                )
            continuity_rule = (
                "- Keep recurring character identity consistent using active_cast and selected_visual_persona when present, but never replace the scene with a character-card description.\n"
                if visual.keep_continuity and not flexible_names
                else "- Follow appearance_freedom and keep_continuity; current scene appearance overrides optional saved descriptions. Never replace the scene with a character-card description.\n"
            )
            style_rule = {
                "runware": (
                    "- Provider style is Runware: return one compact direct positive prompt, preferably comma-separated visual phrases. "
                    "Keep it under 520 characters and avoid multi-step narrative instructions or hidden metadata."
                ),
                "grok": (
                    "- Provider style is xAI/Grok: return a richer natural-language image prompt with visible action, persona identity, "
                    "appearance, location, mood/lighting, style, and continuity. Avoid JSON in the final image_prompt."
                ),
                "comfyui": (
                    "- Provider style is ComfyUI: use a direct compact positive prompt without labels like 'Story scene image' or 'Current story moment'."
                ),
            }.get(
                prompt_style,
                "- Provider style is general Visual Reply: return a clear story-scene prompt under 900 characters.",
            )
            prompt_limit_label = "520" if prompt_style == "runware" else "1300" if prompt_style == "grok" else "760" if prompt_style == "comfyui" else "900"
            user_prompt = (
                "Return this exact JSON shape:\n"
                '{"image_prompt":"ready image prompt focused on the current visible action","negative_prompt":"optional concise avoid list"}\n\n'
                "Rules:\n"
                "- image_prompt must describe who is visibly doing what, where, with mood/lighting/camera.\n"
                "- Start from current_story_reply/current scene action, then add character appearance as continuity detail.\n"
                "- Prioritize action, body language, object interaction, threat, discovery, movement, or reaction from current_story_reply.\n"
                f"{continuity_rule}"
                "- When scene_focused is true, compose the visible location/action without a narrator portrait.\n"
                "- If no concrete action is visible, show the current scene state and atmosphere instead of a portrait.\n"
                f"{style_rule}\n"
                f"- Keep image_prompt under {prompt_limit_label} characters.\n\n"
                "Input JSON:\n"
                f"{json.dumps(prompt_payload, ensure_ascii=False, indent=2)}"
            )
            params = {
                "model": model_name,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.2,
                "max_tokens": 700,
                "response_format": {"type": "json_object"},
                "timeout": 45,
            }
            additional_params: dict[str, Any] = {}
            params["temperature"] = 0.2
            params["max_tokens"] = 700
            params["response_format"] = {"type": "json_object"}
            params["timeout"] = max(45, int(float(params.get("timeout", 0) or 0)))
            last_error = None
            raw_text = ""
            for _attempt in range(2):
                try:
                    raw_text = self._complete_provider_request(params, additional_params)
                    break
                except Exception as exc:
                    last_error = exc
                    message = str(exc).lower()
                    changed = False
                    if "response_format" in message or "json_object" in message:
                        changed = "response_format" in params
                        params.pop("response_format", None)
                    if ("timeout" in message or "unsupported" in message) and "timeout" in params:
                        params.pop("timeout", None)
                        changed = True
                    if not changed:
                        raise
            if not raw_text and last_error is not None:
                raise last_error
            payload = prompting.parse_json_object(raw_text) or {}
            if self._mprc_instructor_feature_enabled("mprc_instructor_visual_beat_enabled"):
                visual_beat = structured_models.sanitize_visual_beat(payload, latest_turn_text=reply_text)
                if visual_beat:
                    prompt_payload["validated_model_visual_beat"] = visual_beat
            prompt = str(payload.get("image_prompt") or payload.get("prompt") or "").strip()
            if len(prompt) < 20:
                return ""
            prompt_limit = 520 if prompt_style == "runware" else 1300 if prompt_style == "grok" else 760 if prompt_style == "comfyui" else 900
            if flexible_names:
                prompt_limit = min(prompt_limit, 760)
                appearance_guidance = (
                    f"Flexible appearance for {', '.join(flexible_names)}: basic identity and age only; "
                    "vary hair, makeup, clothing and facial styling. Scene overrides avatar. "
                )
                if strict_names:
                    appearance_guidance += f"Strict continuity for {', '.join(strict_names)}; preserve their saved appearance. "
                if scene_focused:
                    appearance_guidance += "Scene-wide view; no narrator portrait. "
                prompt = appearance_guidance + prompt
            prompt = prompting._compact(prompt, prompt_limit)
            self.set_chat_visual_prompt_debug_from_parts(
                persona=persona,
                reason=str(reason or "manual"),
                provider=provider_id,
                stage="hidden LLM current-reply action prompt",
                final_prompt=prompt,
                base_prompt=base_prompt,
                source_text=reply_text,
                request_payload=prompt_payload,
            )
            self._record_visual_debug(
                source="visual_action_prompt",
                reason=str(reason or "manual"),
                persona=persona,
                accepted=None,
                message="Hidden LLM built current-reply visual action prompt.",
                prompt=prompt,
            )
            return prompt
        except Exception as exc:
            logger = getattr(self.context, "logger", None)
            if logger is not None:
                logger.info("[MPRC] Visual action prompt refinement skipped: %s", exc)
            self._record_visual_debug(
                source="visual_action_prompt",
                reason=str(reason or "manual"),
                persona=persona,
                accepted=False,
                message=f"Hidden LLM visual action prompt skipped: {exc}",
                prompt=base_prompt,
            )
            return ""

    def _extract_ar_choices(self, text: str) -> list[str]:
        raw = str(text or "")
        marker = raw.lower().find("[choices]")
        if marker < 0:
            return []
        block = raw[marker + len("[choices]") :]
        next_section = block.find("[")
        if next_section >= 0:
            block = block[:next_section]
        choices = []
        for line in block.splitlines():
            clean = str(line or "").strip()
            clean = re.sub(r"^\s*(?:[-*]\s+|\d+[.)]\s+)", "", clean)
            if clean:
                choices.append(clean[:180])
            if len(choices) >= 6:
                break
        return choices

    def _ar_narrator_persona(self) -> PersonaConfig | None:
        selected = self.selected_narrator_persona()
        if selected is not None:
            return selected
        for persona in self.personas:
            if persona.display_name.strip().lower() == "story narrator":
                return persona
        for persona in self.personas:
            text = " ".join([persona.id, persona.role, persona.behavior_mode, ",".join(persona.tags)]).lower()
            if "narrator" in text:
                return persona
        return None

    def _ensure_session_persona(self):
        if not self.personas:
            self.personas = self.storage.load_personas()
        known = {persona.id for persona in self.personas}
        if self.session.active_persona_id not in known:
            self.session.active_persona_id = self.personas[0].id if self.personas else ""
        if self.session.current_speaker_id not in known:
            self.session.current_speaker_id = self.session.active_persona_id

    def set_debug_prompt(self, prompt: str) -> None:
        with self._state_lock:
            if self._shutting_down:
                return
            self._debug_prompt = str(prompt or "")
        self._request_debug_refresh()

    def set_chat_visual_prompt_debug_from_parts(
        self,
        *,
        persona: PersonaConfig | None,
        reason: str = "manual",
        provider: str = "",
        stage: str = "",
        final_prompt: str = "",
        base_prompt: str = "",
        source_text: str = "",
        request_payload: dict[str, Any] | None = None,
    ) -> None:
        payload = dict(request_payload or {}) if isinstance(request_payload, dict) else {}
        provider_info = payload.get("provider_info") if isinstance(payload.get("provider_info"), dict) else {}
        prompt_style = str(provider_info.get("prompt_style") or prompting.visual_prompt_style(provider or "inherit"))
        lines = [
            "MPRC Visual Prompt Debug",
            f"Stage: {stage or 'base prompt'}",
            f"Reason: {reason or 'manual'}",
            f"Effective provider: {provider or provider_info.get('effective_provider') or 'inherit'}",
            f"Prompt style: {prompt_style}",
            f"Persona provider override: {provider_info.get('persona_provider_override', 'inherit')}",
            f"Active Visual Reply provider snapshot: {provider_info.get('active_provider_snapshot') or provider_info.get('active_provider_raw') or 'unknown'}",
        ]
        if persona is not None:
            visual = getattr(persona, "visual", None)
            lines.extend(
                [
                    "",
                    "[Persona / Visual Settings]",
                    f"Persona: {persona.display_name} ({persona.id})",
                    f"Role: {persona.role or persona.behavior_mode}",
                    f"Visual mode: {getattr(visual, 'mode', '')}",
                    f"Provider override: {getattr(visual, 'provider', '')}",
                    f"Model override: {getattr(visual, 'model', '')}",
                    f"Size override: {getattr(visual, 'size', '')}",
                    f"Style preset: {getattr(visual, 'style_preset', '')}",
                    f"Include scene summary: {bool(getattr(visual, 'include_scene_summary', False))}",
                    f"Include active speaker: {bool(getattr(visual, 'include_active_speaker', False))}",
                    f"Character description: {self._mprc_compact(getattr(visual, 'character_description', ''), 420)}",
                    f"Clothing / props: {self._mprc_compact(getattr(visual, 'clothing_props', ''), 260)}",
                    f"Environment style: {self._mprc_compact(getattr(visual, 'environment_style', ''), 260)}",
                    f"Negative prompt: {self._mprc_compact(getattr(visual, 'negative_prompt', ''), 260)}",
                ]
            )
        state = self.session.ar_state
        lines.extend(
            [
                "",
                "[AR State Inputs]",
                f"Current scene: {self._mprc_compact(state.current_scene or self.session.scene_title, 420)}",
                f"Location: {self._mprc_compact(state.location or self.session.location, 260)}",
                f"Time: {self._mprc_compact(state.time_of_day or self.session.time_of_day, 160)}",
                f"Mood: {self._mprc_compact(state.mood or self.session.mood, 220)}",
                f"Story goal: {self._mprc_compact(state.story_goal or self.session.objective, 320)}",
                f"Active characters: {', '.join(list(state.active_characters or []))}",
                f"Pending choices: {self._mprc_join_compact(list(state.pending_choices or []), 6, 140)}",
                f"Recent events: {self._mprc_join_compact(list(state.recent_events or [])[-4:], 4, 180)}",
                f"Scene summary: {self._mprc_compact(self.session.scene_summary, 700)}",
            ]
        )
        if source_text:
            lines.extend(["", "[Current Story Reply Input]", self._mprc_compact(source_text, 1800)])
        if payload:
            lines.extend(["", "[Hidden LLM Request Payload]", json.dumps(payload, indent=2, ensure_ascii=False)])
        if base_prompt:
            lines.extend(["", "[Fallback/Base Prompt]", self._mprc_compact(base_prompt, 1200)])
        if final_prompt:
            lines.extend(["", "[Final Image Prompt Sent]", final_prompt])
        with self._state_lock:
            if self._shutting_down:
                return
            self._chat_visual_prompt_debug = "\n".join(str(item) for item in lines if item is not None).strip()
        self._request_debug_refresh()

    def _request_debug_refresh(self) -> None:
        bridge = getattr(self, "_ui_bridge", None)
        if bridge is None:
            return
        try:
            bridge.debug_refresh_requested.emit()
        except RuntimeError:
            pass

    def _apply_mprc_tab_button_order(self, *, persist: bool = False, order_keys: list[str] | None = None) -> None:
        layout = self._controls.get("tab_button_layout")
        all_buttons = list(self._controls.get("tab_buttons_all") or [])
        if layout is None or not all_buttons:
            return
        by_key = {
            str(button.property("_mprc_tab_key") or ""): button
            for button in all_buttons
            if str(button.property("_mprc_tab_key") or "").strip()
        }
        default_order = [str(button.property("_mprc_tab_key") or "") for button in all_buttons]
        raw_order = order_keys if order_keys is not None else self.settings.get("mprc_tab_button_order")
        requested = [str(item or "").strip() for item in list(raw_order or []) if str(item or "").strip()]
        ordered_keys = [key for key in requested if key in by_key]
        ordered_keys.extend(key for key in default_order if key and key not in ordered_keys)
        ordered_buttons = [by_key[key] for key in ordered_keys if key in by_key]
        while layout.count():
            layout.takeAt(0)
        for button in ordered_buttons:
            layout.addWidget(button)
        layout.addStretch(1)
        self._controls["tab_buttons"] = ordered_buttons
        if persist:
            self.settings["mprc_tab_button_order"] = ordered_keys
            self.storage.save_settings(self.settings)
        try:
            parent = layout.parentWidget()
            if parent is not None:
                parent.adjustSize()
                parent.updateGeometry()
            nav_scroll = self._controls.get("tab_nav_scroll")
            if nav_scroll is not None and nav_scroll.widget() is not None:
                nav_scroll.widget().adjustSize()
        except Exception:
            pass
        current = self._controls.get("tab_stack").currentIndex() if self._controls.get("tab_stack") is not None else 0
        self._select_mprc_tab(current)

    def _move_mprc_tab_button(self, source_index: int, target_index: int) -> None:
        buttons = list(self._controls.get("tab_buttons") or [])
        if source_index == target_index or not buttons:
            return
        source_pos = next((index for index, button in enumerate(buttons) if int(getattr(button, "_index", -1)) == int(source_index)), -1)
        target_pos = next((index for index, button in enumerate(buttons) if int(getattr(button, "_index", -1)) == int(target_index)), -1)
        if source_pos < 0 or target_pos < 0:
            return
        button = buttons.pop(source_pos)
        insert_pos = target_pos if source_pos > target_pos else target_pos
        insert_pos = max(0, min(len(buttons), insert_pos))
        buttons.insert(insert_pos, button)
        order_keys = [str(item.property("_mprc_tab_key") or "") for item in buttons]
        self._apply_mprc_tab_button_order(persist=True, order_keys=order_keys)

    def _select_mprc_tab(self, index: int):
        stack = self._controls.get("tab_stack")
        buttons = self._controls.get("tab_buttons") or []
        if stack is not None:
            stack.setCurrentIndex(index)
            try:
                self._sync_mprc_tab_stack_height()
                stack.updateGeometry()
                parent = stack.parentWidget()
                while parent is not None:
                    parent.updateGeometry()
                    parent = parent.parentWidget()
            except Exception:
                pass
        for button in buttons:
            if hasattr(button, "set_selected"):
                button.set_selected(int(getattr(button, "_index", -1)) == int(index))
        self._ensure_mprc_tab_button_visible(index)
        self._update_mprc_tab_nav_buttons()

    def _scroll_mprc_tab_nav(self, direction: int) -> None:
        nav_scroll = self._controls.get("tab_nav_scroll")
        if nav_scroll is None:
            return
        try:
            scrollbar = nav_scroll.horizontalScrollBar()
            step = max(90, int(nav_scroll.viewport().width() * 0.65))
            scrollbar.setValue(scrollbar.value() + (step if int(direction or 0) > 0 else -step))
            self._update_mprc_tab_nav_buttons()
        except Exception:
            pass

    def _ensure_mprc_tab_button_visible(self, index: int) -> None:
        nav_scroll = self._controls.get("tab_nav_scroll")
        buttons = self._controls.get("tab_buttons") or []
        if nav_scroll is None:
            return
        button = next((item for item in buttons if int(getattr(item, "_index", -1)) == int(index)), None)
        if button is None:
            return
        try:
            nav_scroll.ensureWidgetVisible(button, 12, 0)
        except Exception:
            pass

    def _update_mprc_tab_nav_buttons(self) -> None:
        nav_scroll = self._controls.get("tab_nav_scroll")
        prev_button = self._controls.get("tab_nav_prev")
        next_button = self._controls.get("tab_nav_next")
        if nav_scroll is None or prev_button is None or next_button is None:
            return
        try:
            scrollbar = nav_scroll.horizontalScrollBar()
            has_overflow = scrollbar.maximum() > scrollbar.minimum()
            prev_button.setVisible(has_overflow)
            next_button.setVisible(has_overflow)
            prev_button.setEnabled(scrollbar.value() > scrollbar.minimum())
            next_button.setEnabled(scrollbar.value() < scrollbar.maximum())
        except Exception:
            pass

    def _sync_mprc_tab_stack_height(self) -> None:
        # Legacy layout hook retained as a harmless native compatibility seam.
        return None
    def _assign_control_object_names(self):
        for key, widget in list(self._controls.items()):
            if not isinstance(widget, QtCore.QObject):
                continue
            try:
                if not str(widget.objectName() or "").strip():
                    widget.setObjectName(f"mprc_{key}")
            except Exception:
                continue

    def _tab_icon(self, kind: str, color: str):
        from PySide6 import QtCore, QtGui

        pixmap = QtGui.QPixmap(50, 50)
        pixmap.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        accent = QtGui.QColor(color)
        painter.setPen(QtGui.QPen(accent, 3))
        painter.setBrush(QtGui.QColor(17, 27, 40))
        painter.drawRoundedRect(4, 4, 42, 42, 10, 10)
        painter.setBrush(accent)
        painter.setPen(QtGui.QPen(accent, 3))
        key = str(kind or "").lower()
        if key == "play":
            points = [
                QtCore.QPointF(18, 13),
                QtCore.QPointF(18, 37),
                QtCore.QPointF(36, 25),
            ]
            painter.drawPolygon(QtGui.QPolygonF(points))
        elif key == "guide":
            painter.drawEllipse(14, 10, 22, 22)
            painter.drawLine(25, 32, 25, 39)
        elif key == "status":
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawEllipse(12, 12, 26, 26)
            painter.drawLine(25, 17, 25, 27)
            painter.drawLine(25, 32, 25, 33)
        elif key == "registry":
            for y in (13, 24, 35):
                painter.drawEllipse(12, y, 6, 6)
                painter.drawLine(23, y + 3, 38, y + 3)
        elif key == "cast":
            painter.drawEllipse(15, 13, 9, 9)
            painter.drawEllipse(27, 13, 9, 9)
            painter.drawRoundedRect(12, 26, 13, 12, 4, 4)
            painter.drawRoundedRect(27, 26, 13, 12, 4, 4)
        elif key == "editor":
            painter.drawLine(15, 35, 34, 16)
            painter.drawLine(30, 12, 38, 20)
            painter.drawLine(13, 38, 22, 35)
        elif key == "voice":
            painter.drawRect(14, 19, 7, 13)
            painter.drawArc(19, 14, 18, 24, -45 * 16, 90 * 16)
            painter.drawArc(24, 10, 18, 32, -45 * 16, 90 * 16)
        elif key == "session":
            painter.drawEllipse(11, 12, 28, 28)
            painter.drawLine(25, 25, 25, 15)
            painter.drawLine(25, 25, 34, 30)
        elif key == "events":
            painter.drawLine(18, 12, 18, 38)
            for y in (15, 25, 35):
                painter.drawEllipse(15, y - 3, 6, 6)
                painter.drawLine(24, y, 37, y)
        elif key == "ar":
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawRoundedRect(12, 14, 26, 22, 6, 6)
            painter.drawLine(18, 14, 18, 10)
            painter.drawLine(32, 14, 32, 10)
            painter.drawEllipse(18, 23, 4, 4)
            painter.drawEllipse(28, 23, 4, 4)
        elif key == "audio":
            painter.drawEllipse(13, 20, 6, 10)
            painter.drawEllipse(29, 20, 6, 10)
            painter.drawLine(19, 25, 29, 25)
            painter.drawArc(14, 11, 20, 24, 20 * 16, 140 * 16)
        elif key == "visual":
            painter.drawRect(11, 14, 28, 22)
            painter.drawEllipse(28, 18, 5, 5)
            painter.drawLine(14, 34, 22, 27)
            painter.drawLine(22, 27, 29, 33)
            painter.drawLine(29, 33, 37, 25)
        elif key == "choices":
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawRoundedRect(12, 12, 27, 26, 6, 6)
            painter.drawLine(18, 19, 31, 19)
            painter.drawLine(18, 27, 31, 27)
            painter.drawLine(18, 35, 27, 35)
        elif key == "master":
            painter.drawLine(15, 15, 35, 15)
            painter.drawLine(15, 23, 35, 23)
            painter.drawLine(15, 31, 29, 31)
            painter.drawEllipse(31, 29, 7, 7)
        elif key == "debug":
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawEllipse(14, 14, 22, 22)
            painter.drawEllipse(22, 22, 6, 6)
            for x1, y1, x2, y2 in ((25, 8, 25, 14), (25, 36, 25, 42), (8, 25, 14, 25), (36, 25, 42, 25)):
                painter.drawLine(x1, y1, x2, y2)
        else:
            painter.drawRoundedRect(14, 13, 22, 24, 5, 5)
            painter.drawLine(18, 20, 32, 20)
            painter.drawLine(18, 27, 32, 27)
        painter.end()
        return QtGui.QIcon(pixmap)

    @staticmethod
    def _story_state_tab_stylesheet() -> str:
        return """
        QTabWidget#mprc_story_state_tabs {
            background: #122033;
            border: none;
        }
        QTabWidget#mprc_story_state_tabs::pane {
            background: #122033;
            border: 1px solid #2d4561;
            border-radius: 10px;
            top: -1px;
        }
        QTabWidget#mprc_story_state_tabs QTabBar {
            background: #122033;
        }
        QTabWidget#mprc_story_state_tabs QTabBar::tab {
            background: #111b28;
            border: 1px solid #36506d;
            border-radius: 9px;
            min-width: 86px;
            min-height: 68px;
            padding: 0px;
            margin-right: 4px;
            margin-bottom: 2px;
        }
        QTabWidget#mprc_story_state_tabs QTabBar::tab:selected {
            background: #1c2d43;
            border-color: #4f78a2;
        }
        QTabWidget#mprc_story_state_tabs QTabBar::tab:hover {
            background: #17263a;
            border-color: #5f8bb8;
        }
        """

    def _configure_chat_play_toolbar_advanced_toggle(self, toggle, advanced) -> None:
        expanded = bool(self.settings.get("chat_toolbar_advanced_expanded", True))
        self._apply_chat_play_toolbar_advanced_state(toggle, advanced, expanded)
        toggle.clicked.connect(lambda checked: self._on_chat_play_toolbar_advanced_toggled(toggle, advanced, bool(checked)))

    def _on_chat_play_toolbar_advanced_toggled(self, toggle, advanced, expanded: bool) -> None:
        self.settings["chat_toolbar_advanced_expanded"] = bool(expanded)
        self.storage.save_settings(self.settings)
        self._apply_chat_play_toolbar_advanced_state(toggle, advanced, bool(expanded))

    def _apply_chat_play_toolbar_advanced_state(self, toggle, advanced, expanded: bool) -> None:
        if advanced is not None:
            advanced.setVisible(bool(expanded))
            advanced.setMaximumHeight(16777215 if expanded else 0)
        if toggle is not None:
            toggle.blockSignals(True)
            toggle.setChecked(bool(expanded))
            toggle.blockSignals(False)
            toggle.setText("Advanced ^" if expanded else "Advanced v")

    def _find_layout_containing_widget(self, layout, widget):
        if layout is None or widget is None:
            return None
        for index in range(layout.count()):
            item = layout.itemAt(index)
            if item is None:
                continue
            if item.widget() is widget:
                return layout
            nested = item.layout()
            if nested is not None:
                found = self._find_layout_containing_widget(nested, widget)
                if found is not None:
                    return found
        return None

    def _chat_play_is_floating(self) -> bool:
        window = getattr(self, "_chat_play_floating_window", None)
        return window is not None

    def _set_chat_play_float_button_text(self) -> None:
        return None

    def _toggle_chat_play_floating(self):
        if self._chat_play_is_floating():
            self._dock_chat_play_tab()
        else:
            self._float_chat_play_tab()

    def _dock_chat_play_tab(self) -> None:
        return None

    def _append_chat_play_line(self, speaker: str, text: str, *, role: str = "note") -> None:
        from addons.multi_persona_roleplay.native_chat_avatars import authored_rows

        speaker_text = str(speaker or "").strip() or "MPRC"
        body = str(text or "").strip()
        if not body:
            return
        self._native_chat_line_serial += 1
        self._native_chat_transcript.append(
            {
                "line_id": self._native_chat_line_serial,
                "avatar_rows": authored_rows(self, speaker_text, body, role),
                "speaker": speaker_text,
                "text": body,
                "role": str(role or "note").strip().lower() or "note",
                "created_at": QtCore.QDateTime.currentDateTimeUtc().toString(QtCore.Qt.ISODate),
            }
        )
        self._native_chat_transcript = self._native_chat_transcript[-240:]
        self._native_revision += 1

    def _restore_chat_play_feed_from_state(self) -> None:
        transcript = self._controls.get("chat_transcript")
        if transcript is None or bool(transcript.property("_mprc_state_restored")):
            return
        turn_index = int(getattr(self.session, "turn_index", 0) or 0)
        restored_beats = self._restored_chat_play_beats()
        if turn_index <= 0 and not restored_beats:
            return
        transcript.setProperty("_mprc_state_restored", True)
        self._append_chat_play_line(
            "System",
            "Restored an ongoing MPRC story from saved state. The full Play transcript is not persisted; fuller archived story beats are shown below when available.",
            role="system",
        )
        for beat in restored_beats:
            self._append_chat_play_line("Restored Beat", beat, role="assistant")

    def _restored_chat_play_beats(self) -> list[str]:
        beats: list[str] = []
        try:
            payload = self.long_memory.load()
        except Exception:
            payload = {}
        events = list(payload.get("events") or []) if isinstance(payload, dict) else []
        for event in events[-6:]:
            if not isinstance(event, dict):
                continue
            text = str(event.get("assistant_text") or event.get("summary") or "").strip()
            if text:
                beats.append(self._mprc_compact(self._mprc_strip_audio_tags(text), 1600))
        if beats:
            return beats
        ar_events = list(getattr(self.session.ar_state, "recent_events", []) or [])
        events = ar_events or list(getattr(self.session, "recent_events", []) or [])
        for event in events[-6:]:
            text = str(event or "").strip()
            if text:
                beats.append(self._mprc_strip_audio_tags(text))
        return beats

    def _set_chat_play_status(self, message: str) -> None:
        self._native_chat_status = str(message or "")
        self._native_revision += 1

    def _on_mprc_chat_start_clicked(self):
        use_ar = self._controls.get("chat_use_ar")
        self._set_mprc_play_isolated_active(True, persist=True)
        self.session.enabled = True
        if use_ar is not None and use_ar.isChecked():
            self.session.mode = AR_MODE
        if int(getattr(self.session, "turn_index", 0) or 0) <= 0:
            self._reset_mprc_chat_history()
        self.save_state()
        self._set_chat_play_status("MPRC Play session is active.")
        self._append_chat_play_line("System", "Play session armed inside MPRC.", role="system")
        if self._mprc_story_should_open_on_start():
            self._start_mprc_opening_turn()
        else:
            self.refresh_ui()

    def _mprc_story_should_open_on_start(self) -> bool:
        if int(getattr(self.session, "turn_index", 0) or 0) > 0:
            return False
        send_button = self._controls.get("chat_send")
        if send_button is not None and bool(send_button.property("_mprc_in_flight")):
            return False
        return True

    def _start_mprc_opening_turn(self) -> None:
        from .scenario_play import start_if_enabled
        if start_if_enabled(self):
            return
        message = (
            "Continue. Open the current story from the stored scene and Master Story setup. "
            "Include a concise [NARRATOR] opening/backstory beat, introduce the immediate situation, "
            "show who is present, and end at a natural point for player action or [CHOICES]."
        )
        self.session.ar_state.player_intent = message
        self.ensure_ar_state(message)
        self.save_state()
        self._append_chat_play_line("System", "Opening current story from MPRC Play.", role="system")
        self._start_mprc_chat_turn(
            intent="System",
            player_text=message,
            speaker_id="",
            display_user=False,
            status="Opening MPRC story through the selected chat provider...",
        )

    def _on_mprc_chat_pause_clicked(self):
        self._stop_mprc_chat_playback()
        self._set_mprc_play_isolated_active(False, persist=True)
        self.session.enabled = False
        self.save_state()
        self._set_chat_play_status("MPRC Play stopped.")
        self._append_chat_play_line("System", "Play session stopped.", role="system")
        self._refresh_chat_play_controls()

    def _on_mprc_chat_restart_clicked(self):
        self._stop_mprc_chat_playback()
        self._reset_mprc_chat_history()
        removed_auto_personas = self._remove_chat_auto_personas()
        transcript = self._controls.get("chat_transcript")
        if transcript is not None:
            transcript.clear()
        self._set_mprc_play_isolated_active(True, persist=True)
        self.session.enabled = True
        self.session.turn_index = 0
        self.session.recent_events = []
        self.session.character_state_summaries = {}
        self.session.last_visual_reply_at = 0.0
        self.session.auto_image_count = 0
        self.session.ar_state.recent_events = []
        self.session.ar_state.pending_choices = []
        self.session.ar_state.player_intent = ""
        self.session.ar_state.tension_level = 2
        use_ar = self._controls.get("chat_use_ar")
        if use_ar is not None and hasattr(use_ar, "isChecked") and bool(use_ar.isChecked()):
            self.session.mode = AR_MODE
        self.ensure_ar_state()
        try:
            self.roleplay_engine._recent_assistant_texts = []
        except Exception:
            pass
        self._clear_story_memory_preserving_pins()
        self.save_state()
        restart_note = "Story restarted from the current setup. Story and character memory were reset."
        status_note = "MPRC story restarted. Saved story setup was left intact; story memory was reset."
        if removed_auto_personas:
            restart_note += f" Removed {removed_auto_personas} auto-created chat persona(s)."
            status_note += f" Removed {removed_auto_personas} [Auto Chat] persona(s)."
        self._append_chat_play_line("System", restart_note, role="system")
        self._set_chat_play_status(status_note)
        self._refresh_memory_browser()
        self._refresh_persona_selectors()
        self._refresh_reliability_panels()
        self._refresh_chat_play_controls()

    def _on_mprc_chat_clear_clicked(self):
        transcript = self._controls.get("chat_transcript")
        if transcript is not None:
            transcript.clear()
        self._set_chat_play_status("MPRC Play transcript cleared.")

    def _reset_mprc_chat_history(self) -> None:
        self._mprc_chat_history = []
        self._mprc_pending_chat_users = {}

    def _stop_mprc_chat_playback(self) -> None:
        scenario = getattr(self, "_scenario_play", None)
        if scenario is not None:
            scenario.stop()
        for token in list(self._mprc_pending_chat_users):
            self._cancel_worker_token(str(token or ""))
        self._mprc_pending_chat_users.clear()
        self._stop_mprc_chat_speech()

    def _stop_mprc_chat_speech(self) -> None:
        with self._mprc_tts_state_lock:
            tts_controller = self._mprc_tts_controller
            self._mprc_tts_controller = None
            tts_token = str(self._mprc_tts_token or "")
            self._mprc_tts_token = ""
        if tts_token:
            self._cancel_worker_token(tts_token)
        try:
            if tts_controller is not None and hasattr(tts_controller, "cancel"):
                tts_controller.cancel()
        except Exception:
            pass
        try:
            player = getattr(self, "_audiofx_player", None)
            if player is not None:
                player.stop()
        except Exception:
            pass
        try:
            self.playback.interrupt(reason="mprc_stop", cancel_llm_streams=False)
        except Exception as exc:
            logger = getattr(self.context, "logger", None)
            if logger is not None:
                logger.warning("[MPRC] Could not stop MPRC playback: %s", exc)
        with self._state_lock:
            self._native_chat_speaker = {}

    def _on_mprc_chat_send_clicked(self):
        input_widget = self._controls.get("chat_input")
        text = str(input_widget.toPlainText() if input_widget is not None and hasattr(input_widget, "toPlainText") else "").strip()
        if not text:
            self._set_chat_play_status("Add a player action before sending.")
            return
        send_button = self._controls.get("chat_send")
        if send_button is not None and bool(send_button.property("_mprc_in_flight")):
            self._set_chat_play_status("MPRC turn is already running.")
            return
        self._stop_mprc_chat_speech()
        intent_choice = "Auto"
        intent_combo = self._controls.get("chat_intent")
        if intent_combo is not None and hasattr(intent_combo, "currentText"):
            intent_choice = str(intent_combo.currentText() or "Auto").strip() or "Auto"
        intent = self._infer_mprc_chat_intent(text, intent_choice)
        speaker = "Player"
        speaker_id = ""
        combo = self._controls.get("chat_speaker")
        if combo is not None and hasattr(combo, "currentText"):
            selected = str(combo.currentText() or "").strip()
            if selected:
                speaker = selected
            if hasattr(combo, "currentData"):
                speaker_id = str(combo.currentData() or "").strip()
        latest_user_text = f"{intent}: {text}"
        self.session.ar_state.player_intent = latest_user_text
        if speaker_id:
            self.session.current_speaker_id = speaker_id
        use_ar = self._controls.get("chat_use_ar")
        if use_ar is not None and hasattr(use_ar, "isChecked") and bool(use_ar.isChecked()):
            self.session.mode = AR_MODE
        self._set_mprc_play_isolated_active(True, persist=True)
        self.session.enabled = True
        self.ensure_ar_state(latest_user_text)
        self.save_state()
        self._append_chat_play_line(f"{speaker} [{intent}]", text, role="user")
        if input_widget is not None and hasattr(input_widget, "clear"):
            input_widget.clear()
        self._start_mprc_chat_turn(intent=intent, player_text=text, speaker_id=speaker_id)

    def _start_mprc_chat_turn(
        self,
        *,
        intent: str,
        player_text: str,
        speaker_id: str = "",
        display_user: bool = True,
        status: str = "MPRC turn running through the selected chat provider...",
    ) -> None:
        scenario = getattr(self, "_scenario_play", None)
        authored = self.settings.get("active_scenario_extension")
        if isinstance(authored, dict) and authored.get("enabled") is True and (scenario is None or not scenario.ready):
            self._set_chat_play_status("Start the scenario and wait for its current action to finish before sending a turn.")
            return
        if self._mprc_pending_chat_users:
            self._set_chat_play_status("MPRC turn is already running.")
            return
        try:
            messages = self._build_mprc_chat_turn_messages(intent=intent, player_text=player_text, speaker_id=speaker_id)
        except Exception as exc:
            self._set_chat_play_status(f"Could not build MPRC turn prompt: {exc}")
            return
        token = self._new_worker_token("mprc_chat")
        if not token:
            return
        user_message = next((item for item in reversed(messages) if str(item.get("role", "") or "") == "user"), {})
        if user_message:
            self._mprc_pending_chat_users[token] = dict(user_message)
        self._set_chat_play_status(status)

        scenario_context = scenario.capture_prompt() if scenario is not None else None

        def worker():
            error = ""
            reply = ""
            try:
                reply = (self._run_mprc_chat_provider(messages, scenario_context=scenario_context)
                         if scenario_context is not None else self._run_mprc_chat_provider(messages))
            except Exception as exc:
                error = str(exc) or repr(exc)
            if not self._worker_should_emit(token):
                return
            try:
                bridge = getattr(self, "_chat_turn_bridge", None)
                if bridge is not None:
                    bridge.finished.emit(token, reply, error)
                else:
                    self._cancel_worker_token(token)
            except RuntimeError:
                self._cancel_worker_token(token)

        if not self._start_daemon_worker(token, worker, name="nc-mprc-chat-turn"):
            self._mprc_pending_chat_users.pop(token, None)
            self._set_chat_play_status("Could not start MPRC turn worker.")

    def _on_mprc_choice_selected(self, item, *, send: bool = False):
        choice = str(item.text() if item is not None and hasattr(item, "text") else "").strip()
        if not choice:
            return
        input_widget = self._controls.get("chat_input")
        if input_widget is not None and hasattr(input_widget, "setPlainText"):
            input_widget.setPlainText(choice)
            try:
                input_widget.setFocus()
                cursor = input_widget.textCursor()
                cursor.movePosition(QtGui.QTextCursor.End)
                input_widget.setTextCursor(cursor)
            except Exception:
                pass
        intent_combo = self._controls.get("chat_intent")
        if intent_combo is not None and hasattr(intent_combo, "setCurrentText"):
            intent_combo.setCurrentText("Auto")
        if send:
            self._set_chat_play_status("Choice selected and sent.")
            self._on_mprc_chat_send_clicked()
        else:
            self._set_chat_play_status("Choice loaded into Player Action. Edit or Send.")

    def _infer_mprc_chat_intent(self, text: str, selected_intent: str = "Auto") -> str:
        selected = str(selected_intent or "Auto").strip()
        if selected and selected.lower() != "auto":
            return selected
        value = str(text or "").strip()
        lowered = value.lower()
        if not value:
            return "Act"
        if lowered.startswith(("ooc:", "[ooc]", "out of character:", "out-of-character:")):
            return "OOC"
        if lowered.startswith(("direct:", "director:", "scene:", "pace:", "tone:", "camera:")):
            return "Direct"
        if lowered.startswith(("say ", "ask ", "tell ", "reply ", "answer ", "whisper ", "shout ")):
            return "Say"
        if value.startswith(('"', "'")):
            return "Say"
        return "Act"

    def _build_mprc_chat_turn_messages(self, *, intent: str, player_text: str, speaker_id: str = "") -> list[dict[str, str]]:
        player_action = str(player_text or "").strip()
        if not player_action:
            raise ValueError("Player action is empty.")
        intent_text = str(intent or "Act").strip() or "Act"
        latest_user_text = player_action if intent_text.lower() == "system" else f"{intent_text}: {player_action}"
        director_text = self._mprc_chat_director_context()
        full_setup = not bool(self._mprc_chat_history) and int(getattr(self.session, "turn_index", 0) or 0) <= 0
        structured_output_rules = (
            self._mprc_structured_output_prompt_rules()
            if self._mprc_chat_structured_output_applies(full_setup=full_setup)
            else ""
        )
        if full_setup:
            context_text = self._mprc_chat_full_context(
                latest_user_text,
                cast_mode=story_director.CAST_MODE_JOINED_CAST,
            )
            system_parts = [
                "You are NeuralCompanion's dedicated Multi Persona Roleplay story runtime. This is separate from normal chat history.",
                "Write only the next story response to the player's action. Do not summarize these instructions or expose prompt structure.",
                "Preserve player agency: never decide major player actions, private thoughts, or consent for the player.",
                "Use clear story-native formatting. In AR mode, prefer [NARRATOR], [CHARACTER: Exact Name], exact listed story audio tags when needed, and follow the Director response ending mode.",
                "Treat the user payload's focus instruction as binding for who performs or frames the latest action.",
                structured_output_rules,
                context_text,
                director_text,
            ]
        else:
            story_director_context = ""
            if prompting.is_alternative_reality_mode(self.session):
                story_director_context = self._mprc_chat_full_context(
                    latest_user_text,
                    cast_mode=self._mprc_chat_followup_cast_mode(),
                )
            system_parts = [
                "You are NeuralCompanion's dedicated Multi Persona Roleplay story runtime. Continue the existing MPRC Play conversation below.",
                "Write only the next story response to the player's latest action. Do not recap the full setup unless the player asks.",
                "Preserve player agency: never decide major player actions, private thoughts, or consent for the player.",
                "In AR mode, use [NARRATOR], [CHARACTER: Exact Name], exact listed story audio tags when needed, and follow the Director response ending mode.",
                "Treat the user payload's focus instruction as binding for who performs or frames the latest action.",
                structured_output_rules,
                story_director_context,
                self._mprc_chat_compact_turn_context(latest_user_text),
                director_text,
            ]
        system_prompt = "\n\n".join(part for part in system_parts if str(part or "").strip())
        self.set_debug_prompt(system_prompt)
        focused = self.persona_by_id(speaker_id) if speaker_id else None
        if focused is not None and self._persona_looks_like_narrator(focused):
            focus_instruction = (
                f"The player is directing the scene through narrator focus '{focused.display_name}'. "
                "Treat the player_action as scene-level narration or direction unless it explicitly names another speaker."
            )
        elif focused is not None:
            focus_instruction = (
                f"The player is acting through or speaking as '{focused.display_name}' for this turn. "
                "Treat the player_action as that character's intended action or dialogue unless it explicitly names another actor."
            )
        else:
            focus_instruction = (
                "No character focus is selected. Treat the player_action as the player's own action or director instruction, "
                "depending on the intent."
            )
        user_payload = {
            "intent": intent_text,
            "player_action": player_action,
            "focused_speaker": focused.display_name if focused is not None else "Player",
            "focus_instruction": focus_instruction,
            "instruction": "Advance the MPRC scene by one coherent turn without touching normal chat continuity.",
        }
        messages = [{"role": "system", "content": system_prompt}]
        messages.append({"role": "user", "content": json.dumps(user_payload, ensure_ascii=True, indent=2)})
        return messages

    def _mprc_chat_full_context(
        self,
        latest_user_text: str,
        *,
        cast_mode: str = story_director.CAST_MODE_FOCUSED_SPEAKER,
    ) -> str:
        prompt_personas = self.story_prompt_personas()
        if prompting.is_alternative_reality_mode(self.session):
            return prompting.build_alternative_reality_prompt(
                prompt_personas,
                self.session,
                latest_user_text=latest_user_text,
                available_audio=self.available_story_audio_files(),
                narrator_persona_id=self.selected_narrator_persona_id(),
                cast_mode=cast_mode,
                dialogue_density=self.session.ar_dialogue_density,
            )
        persona = self.current_speaker_persona() or self.active_persona()
        context_text = prompting.build_persona_system_prompt(persona, self.session) if persona is not None else ""
        if self.session.mode != "Single active persona":
            context_text = (context_text + "\n\n" + prompting.build_multi_character_prompt(prompt_personas, self.session)).strip()
        return context_text

    def _mprc_chat_followup_cast_mode(self) -> str:
        if not prompting.is_alternative_reality_mode(self.session):
            return story_director.CAST_MODE_FOCUSED_SPEAKER
        if self._mprc_active_non_narrator_character_count() >= 2:
            return story_director.CAST_MODE_JOINED_CAST
        return story_director.CAST_MODE_FOCUSED_SPEAKER

    def _mprc_active_non_narrator_character_count(self) -> int:
        state = getattr(self.session, "ar_state", None)
        active_ids = [
            normalize_persona_id(item)
            for item in list(getattr(state, "active_characters", []) or [])
            if str(item or "").strip()
        ]
        seen: set[str] = set()
        count = 0
        for persona_id in active_ids:
            if persona_id in seen:
                continue
            seen.add(persona_id)
            persona = self.persona_by_id(persona_id)
            if persona is None:
                continue
            if self._persona_looks_like_narrator(persona):
                continue
            count += 1
        return count

    def _mprc_chat_compact_turn_context(self, latest_user_text: str) -> str:
        state = self.session.ar_state
        active_lines = self._mprc_chat_active_character_lines()
        cue_lines = self._mprc_chat_audio_activation_lines()
        history_lines = self._mprc_chat_history_lines()
        parts = [
            "MPRC compact turn state:",
            "Progression rule: latest player intent and latest visible story beat override older scene summary/location memory.",
            f"Scene: {self._mprc_compact(state.current_scene or self.session.scene_title, 180)}",
            f"Location: {self._mprc_compact(state.location or self.session.location, 140)}",
            f"Time: {self._mprc_compact(state.time_of_day or self.session.time_of_day, 80)}",
            f"Mood: {self._mprc_compact(state.mood or self.session.mood, 100)}",
            f"Tension: {int(getattr(state, 'tension_level', 0) or 0)}",
            f"Goal: {self._mprc_compact(state.story_goal or self.session.objective, 220)}",
            f"Latest player intent: {self._mprc_compact(latest_user_text or state.player_intent, 220)}",
            f"Pending choices: {self._mprc_join_compact(state.pending_choices, 4, 120)}",
            f"Recent events: {self._mprc_join_compact(list(state.recent_events or [])[-4:], 4, 150)}",
            f"Scene summary: {self._mprc_compact(self.session.scene_summary, 700)}",
        ]
        if active_lines:
            parts.append("Active cast:\n" + "\n".join(active_lines))
        if cue_lines:
            parts.append("Allowed story audio tags:\n" + "\n".join(cue_lines))
        if history_lines:
            parts.append("Recent play transcript (compact):\n" + "\n".join(history_lines))
        return "\n".join(item for item in parts if str(item or "").strip()).strip()

    def _mprc_chat_active_character_lines(self) -> list[str]:
        state = self.session.ar_state
        active_ids = [normalize_persona_id(item) for item in list(state.active_characters or []) if str(item or "").strip()]
        if not active_ids:
            active_ids = [self.session.current_speaker_id, self.session.active_persona_id]
        lines = []
        seen = set()
        for persona_id in active_ids:
            persona = self.persona_by_id(persona_id)
            if persona is None or persona.id in seen:
                continue
            seen.add(persona.id)
            role = self._mprc_compact(persona.role or persona.behavior_mode, 80)
            desc = self._mprc_compact(getattr(persona, "ar_description", "") or persona.description, 180)
            instruction = self._mprc_compact(getattr(persona, "ar_system_prompt", ""), 220)
            line = f"- {persona.display_name} ({persona.id})"
            if role:
                line += f": {role}"
            if desc:
                line += f"; {desc}"
            if instruction:
                line += f"; instruction={instruction}"
            lines.append(line)
        return lines[:6]

    def _mprc_chat_audio_activation_lines(self) -> list[str]:
        lines = []
        for item in list(self.available_story_audio_files() or [])[:16]:
            if not isinstance(item, dict) or not item.get("ready", True):
                continue
            audio_type = str(item.get("type") or "Audio").strip().upper() or "AUDIO"
            if audio_type in {"SFX"}:
                audio_type = "FX"
            if audio_type not in {"AMBIENCE", "AMBIENT", "MUSIC", "FX", "STINGER", "AUDIO"}:
                audio_type = "AUDIO"
            if audio_type == "AMBIENT":
                audio_type = "AMBIENCE"
            description = self._mprc_compact(str(item.get("description") or item.get("prompt") or item.get("id") or ""), 120)
            if description:
                lines.append(f"- [{audio_type}: {description}]")
        return lines

    def _mprc_chat_history_lines(self) -> list[str]:
        lines = []
        for message in list(self._mprc_chat_history or [])[-8:]:
            role = str((message or {}).get("role") or "").strip().lower()
            content = str((message or {}).get("content") or "").strip()
            if not role or not content:
                continue
            if role == "user":
                label = "Player"
                try:
                    payload = json.loads(content)
                except Exception:
                    payload = {}
                if isinstance(payload, dict):
                    intent = str(payload.get("intent") or "Action").strip() or "Action"
                    action = str(payload.get("player_action") or "").strip()
                    content = f"{intent}: {action}" if action else content
                lines.append(f"- {label}: {self._mprc_compact(content, 180)}")
            elif role == "assistant":
                lines.append(f"- Story: {self._mprc_compact(self._mprc_strip_audio_tags(content), 240)}")
        return lines

    @staticmethod
    def _mprc_strip_audio_tags(text: str) -> str:
        return re.sub(
            r"\[(?:AMBIENCE|AMBIENT|MUSIC|FX|SFX|STINGER|AUDIO):[^\]]+\]",
            " ",
            str(text or ""),
            flags=re.IGNORECASE,
        )

    @staticmethod
    def _mprc_compact(text: Any, limit: int) -> str:
        value = re.sub(r"\s+", " ", str(text or "")).strip()
        if len(value) <= max(0, int(limit or 0)):
            return value
        return value[: max(0, int(limit or 0) - 1)].rstrip() + "..."

    def _mprc_join_compact(self, items: list[Any], count: int, limit: int) -> str:
        values = [self._mprc_compact(item, limit) for item in list(items or []) if str(item or "").strip()]
        return "; ".join(values[-max(0, int(count or 0)):]) or "none"

    def _mprc_chat_director_context(self) -> str:
        tone = self._control_current_text("chat_director_tone")
        agency = self._control_current_text("chat_director_agency")
        pacing = str(self.session.ar_pacing or self._control_current_text("chat_director_pacing") or "Balanced").strip()
        dialogue_density = str(self.session.ar_dialogue_density or "Balanced narrator + character dialogue").strip()
        choice_mode = self._mprc_chat_choice_mode()
        lines = [
            f"Director pacing: {pacing}",
            f"Director cast energy / dialogue density: {dialogue_density}",
            f"Director tone: {tone or 'Keep current'}",
            f"Player agency mode: {agency or 'Guided'}",
            (
                'Response ending mode: Ask "What\'s your next move?" Do not include [CHOICES].'
                if choice_mode == "ask_next_move"
                else "Response ending mode: Always end with [CHOICES] containing 2 to 4 concrete playable next actions."
            ),
            "Progression priority: the latest player action overrides older scene summary/location memory. If the player leaves, enters, travels, or moves to a new place, transition there unless a concrete immediate obstacle blocks it.",
        ]
        return "MPRC Play director controls:\n" + "\n".join(lines)

    def _control_current_text(self, key: str, default: str = "") -> str:
        value = self.settings.get(str(key or ""), default)
        return str(value if value is not None else default)

    def _mprc_structured_output_cast(self) -> dict[str, dict[str, str]]:
        cast: dict[str, dict[str, str]] = {}
        try:
            personas = list(self.story_prompt_personas() or [])
        except Exception:
            personas = []
        if not personas:
            personas = list(getattr(self, "personas", []) or [])
        for persona in personas:
            persona_id = normalize_persona_id(getattr(persona, "id", "") or "")
            if not persona_id or persona_id in {"narrator", "unknown_speaker"}:
                continue
            if self._persona_looks_like_narrator(persona):
                continue
            display_name = re.sub(r"\s+", " ", str(getattr(persona, "display_name", "") or persona_id)).strip()
            if display_name:
                cast[persona_id] = {"speaker_name": display_name}
        return cast

    def _mprc_structured_output_schema(self) -> dict[str, Any]:
        return build_structured_story_output_schema(
            self._mprc_structured_output_cast(),
            require_choices=self._mprc_chat_should_offer_choices(),
        )

    def _mprc_chat_structured_output_enabled(self) -> bool:
        return bool(self.settings.get("chat_structured_output_enabled", True))

    def _mprc_chat_structured_output_scope(self) -> str:
        scope = str(self.settings.get("chat_structured_output_scope") or "every_turn").strip().lower()
        return scope if scope in {"every_turn", "first_turn"} else "every_turn"

    def _mprc_chat_choice_mode(self) -> str:
        mode = str(self.settings.get("chat_choice_mode") or "choices").strip().lower()
        return mode if mode in {"choices", "ask_next_move"} else "choices"

    def _mprc_chat_should_offer_choices(self) -> bool:
        return self._mprc_chat_choice_mode() != "ask_next_move"

    def _mprc_chat_structured_output_applies(self, *, full_setup: bool) -> bool:
        if not self._mprc_chat_structured_output_enabled():
            return False
        scope = self._mprc_chat_structured_output_scope()
        return scope == "every_turn" or bool(full_setup)

    def _mprc_chat_structured_response_format(self) -> dict[str, Any]:
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "mprc_story_turn",
                "strict": True,
                "schema": self._mprc_structured_output_schema(),
            },
        }

    def _apply_mprc_chat_structured_response_format(self, params: dict[str, Any], *, full_setup: bool) -> bool:
        if not self._mprc_chat_structured_output_applies(full_setup=full_setup):
            return False
        params["response_format"] = self._mprc_chat_structured_response_format()
        self._apply_mprc_chat_structured_token_cap(params)
        return True

    @staticmethod
    def _apply_mprc_chat_structured_token_cap(params: dict[str, Any]) -> None:
        cap = 2400
        for key in ("max_completion_tokens", "max_tokens"):
            if key not in params:
                continue
            try:
                current = int(params.get(key))
            except Exception:
                current = cap
            if current <= 0 or current > cap:
                params[key] = cap
            return
        params["max_tokens"] = cap

    def _mprc_structured_output_prompt_rules(self) -> str:
        cast = {"narrator": {"speaker_name": "Narrator"}}
        cast.update(self._mprc_structured_output_cast())
        cast["unknown_speaker"] = {"speaker_name": "Unknown Speaker"}
        cast_lines = [
            f"- {speaker_id}: {item.get('speaker_name') or speaker_id}"
            for speaker_id, item in cast.items()
        ]
        choice_rule = (
            "- The choices array must contain 2 to 4 concise playable next actions. These become [CHOICES] at the end of the reply."
            if self._mprc_chat_should_offer_choices()
            else '- The choices array must be empty. End the final narrator segment by asking "What\'s your next move?"'
        )
        return "\n".join(
            [
                "Structured Output rules:",
                f"- Return one compact JSON object matching schema_version {STRUCTURED_STORY_SCHEMA_VERSION}. No markdown or usage metadata.",
                "- Use only these speaker_id values; do not output speaker_name because voice routing maps speaker_id locally:",
                *cast_lines,
                "- Never output voice IDs, voice file paths, or made-up voice keys.",
                "Story Director segment discipline:",
                "- Put one speaker per segment; split quoted dialogue into character segments, not narrator text.",
                "- Character segment text must contain only the spoken words or first-person thought. Put attribution, movement, facial expression, and consequences in narrator segments.",
                "- If two characters speak, use two character segments. Do not combine multiple speakers in one segment.",
                "- If narration surrounds dialogue, alternate narrator and character segments so multi-TTS can route every chunk cleanly.",
                "- Narrator segments must carry scene action, setting, visible consequences, attribution, and pacing beats.",
                "- Keep the turn short: no more than 6 story segments; put playable options only in choices.",
                choice_rule,
            ]
        )

    def _on_export_mprc_structured_output_clicked(self) -> None:
        path = self._save_file(
            "Export MPRC Structured LLM Output Schema",
            str(Path.home() / "mprc_structured_llm_output_schema.json"),
            "JSON Schema (*.json);;JSON files (*.json)",
            non_native=True,
        )
        if not path:
            self._set_chat_play_status("Structured Output export cancelled.")
            return
        try:
            cast = self._mprc_structured_output_cast()
            require_choices = self._mprc_chat_should_offer_choices()
        except Exception as exc:
            self._warn("Export Structured Output", f"Export could not prepare schema data:\n\n{exc}")
            self._set_chat_play_status(f"Structured Output export failed before start: {exc}")
            return
        if self._queue_mprc_structured_output_export(path, cast, require_choices):
            self._set_chat_play_status(f"Structured Output export queued: {path}.")

    @staticmethod
    def _write_mprc_structured_output_schema_file(
        path: str | Path,
        cast: dict[str, dict[str, str]],
        *,
        require_choices: bool,
    ) -> None:
        target = Path(str(path or "")).expanduser()
        if not str(target).strip():
            raise ValueError("No export path was provided.")
        target.parent.mkdir(parents=True, exist_ok=True)
        schema = build_structured_story_output_schema(cast, require_choices=bool(require_choices))
        target.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")

    def _set_mprc_structured_export_busy(self, token: str = "") -> None:
        self._structured_output_export_token = str(token or "")
        self._native_revision += 1

    def _queue_mprc_structured_output_export(
        self,
        path: str | Path,
        cast: dict[str, dict[str, str]],
        require_choices: bool,
    ) -> bool:
        if str(getattr(self, "_structured_output_export_token", "") or "").strip():
            self._set_chat_play_status("Structured Output export is already running.")
            return False
        token = self._new_worker_token("mprc_structured_export")
        if not token:
            self._set_chat_play_status("Could not start Structured Output export worker.")
            return False
        path_text = str(path or "")
        cast_snapshot = {
            str(speaker_id): {"speaker_name": str((item or {}).get("speaker_name") or "")}
            for speaker_id, item in dict(cast or {}).items()
            if str(speaker_id or "").strip()
        }
        require_choices_snapshot = bool(require_choices)
        bridge = getattr(self, "_structured_export_bridge", None)
        if bridge is None:
            bridge = _MprcObjectResultBridge(self._on_mprc_structured_output_export_finished)
            self._structured_export_bridge = bridge
            self._adopt_qobject_bridges(self._qt_application_instance())
        self._set_mprc_structured_export_busy(token)

        def worker():
            result: dict[str, Any]
            try:
                self._write_mprc_structured_output_schema_file(
                    path_text,
                    cast_snapshot,
                    require_choices=require_choices_snapshot,
                )
                result = {"ok": True, "path": path_text}
            except Exception as exc:
                result = {"ok": False, "path": path_text, "error": str(exc) or repr(exc)}
            if not self._worker_should_emit(token):
                return
            try:
                bridge.finished.emit(token, result)
            except RuntimeError:
                self._cancel_worker_token(token)

        if self._start_daemon_worker(token, worker, name="nc-mprc-structured-export"):
            return True
        self._set_mprc_structured_export_busy("")
        self._cancel_worker_token(token)
        self._set_chat_play_status("Could not start Structured Output export worker.")
        return False

    def _on_mprc_structured_output_export_finished(self, token, result) -> None:
        token_text = str(token or "")
        result_dict = dict(result or {}) if isinstance(result, dict) else {"ok": False, "error": str(result or "")}
        if not self._finish_worker_token(token_text):
            return
        self._set_mprc_structured_export_busy("")
        if bool(result_dict.get("ok")):
            self._set_chat_play_status(f"Exported Structured Output schema to {result_dict.get('path') or ''}.")
            return
        error = str(result_dict.get("error") or "Unknown export error.")
        self._warn("Export Structured Output", f"Export failed:\n\n{error}")
        self._set_chat_play_status(f"Structured Output export failed: {error}")

    def _run_mprc_chat_provider(self, messages: list[dict[str, str]], *, scenario_context=None) -> str:
        model_name = self._current_provider_model()
        if not model_name:
            raise RuntimeError("Choose a chat model before running MPRC Play.")
        params = {
            "model": model_name,
            "messages": list(messages or []),
        }
        additional_params: dict[str, Any] = {}
        scenario = getattr(self, "_scenario_play", None)
        if scenario_context is not None and scenario is not None:
            from .scenario_lore import estimate_tokens
            schema_params = {}
            self._apply_mprc_chat_structured_response_format(schema_params, full_setup=True)
            overhead = estimate_tokens(json.dumps(schema_params, ensure_ascii=False))
            if self._mprc_instructor_feature_enabled("mprc_instructor_ar_turn_enabled"):
                overhead += estimate_tokens(json.dumps(structured_models.StructuredStoryTurn.model_json_schema())) + 2048
            player_text = str(messages[-1].get("content", "")) if messages else ""
            params["messages"] = scenario.overlay(messages, player_text, captured=scenario_context, extra_tokens=overhead)
        if self._mprc_instructor_feature_enabled("mprc_instructor_ar_turn_enabled"):
            structured_payload = instructor_adapter.generate_structured_output(
                provider_execution=self.providers,
                params=params,
                response_model=structured_models.StructuredStoryTurn,
                max_retries=2,
                logger=getattr(self.context, "logger", None),
            )
            if isinstance(structured_payload, dict) and structured_payload:
                structured_turn = structured_models.sanitize_structured_story_turn(
                    structured_payload,
                    cast=self._mprc_structured_output_cast(),
                    require_choices=self._mprc_chat_should_offer_choices(),
                    available_cues=self.available_story_audio_files(),
                )
                if structured_turn.get("segments"):
                    return json.dumps(structured_turn, ensure_ascii=True)
        full_setup = not bool(self._mprc_chat_history) and int(getattr(self.session, "turn_index", 0) or 0) <= 0
        structured_output_applied = self._apply_mprc_chat_structured_response_format(params, full_setup=full_setup)
        try:
            reply = self._complete_provider_request(params, additional_params)
        except Exception as exc:
            if not structured_output_applied or not self._mprc_chat_provider_error_is_structured_output_compatibility(exc):
                raise
            fallback_params = dict(params)
            fallback_params.pop("response_format", None)
            logger = getattr(self.context, "logger", None)
            if logger is not None:
                logger.warning("[MPRC] MPRC Play structured output rejected by provider; retrying without schema: %s", exc)
            self._record_story_event(
                f"structured output fallback: provider rejected request-scoped schema ({exc})",
                severity="warning",
                kind="runtime",
                persist=True,
            )
            reply = self._complete_provider_request(fallback_params, additional_params)
        if not reply:
            raise RuntimeError("The selected chat provider returned an empty MPRC reply.")
        return reply

    @staticmethod
    def _mprc_chat_provider_error_is_structured_output_compatibility(exc: Exception) -> bool:
        text = str(exc or "").lower()
        markers = (
            "response_format",
            "json_schema",
            "structured output",
            "structured_output",
            "schema",
        )
        return any(marker in text for marker in markers)

    def _finalize_mprc_chat_reply_choice_mode(self, reply: str) -> str:
        text = str(reply or "").strip()
        if not text:
            return ""
        if not self._mprc_chat_should_offer_choices():
            return self._ensure_mprc_next_move_reply(text)
        if self._extract_ar_choices(text):
            return text
        choices = self._mprc_fallback_reply_choices()
        if not choices:
            return text
        return f"{text.rstrip()}\n\n[CHOICES]\n" + "\n".join(
            f"{index}. {choice}" for index, choice in enumerate(choices, start=1)
        )

    def _ensure_mprc_next_move_reply(self, reply: str) -> str:
        text = self._strip_mprc_choices_block(str(reply or "").strip())
        if not text:
            text = "[NARRATOR]"
        if re.search(r"what(?:'|’)?s your next move\?\s*$", text, flags=re.IGNORECASE):
            return text.strip()
        return f"{text.rstrip()}\n\n[NARRATOR]\nWhat's your next move?"

    @staticmethod
    def _strip_mprc_choices_block(text: str) -> str:
        raw = str(text or "").strip()
        if not raw:
            return ""
        match = re.search(r"(?ims)\n?\s*\[CHOICES\]\s*.*$", raw)
        return raw[: match.start()].rstrip() if match else raw

    def _mprc_fallback_reply_choices(self) -> list[str]:
        state = self.session.ar_state
        choices: list[str] = []
        objective = self._mprc_compact(state.story_goal or self.session.objective, 120)
        if objective:
            choices.append(f"Pursue objective: {objective}")
        active = self.current_speaker_persona() or self.active_persona()
        if active is not None and not self._persona_looks_like_narrator(active):
            choices.append(f"Ask {active.display_name} what they notice")
        choices.extend(["Investigate the scene", "Proceed cautiously"])
        normalized: list[str] = []
        seen: set[str] = set()
        for choice in choices:
            clean = re.sub(r"\s+", " ", str(choice or "")).strip()
            if not clean:
                continue
            key = clean.lower()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(clean[:180])
            if len(normalized) >= 4:
                break
        return normalized

    def _on_mprc_chat_turn_finished(self, token: str, reply_text: str, error: str):
        token = str(token or "")
        if not self._finish_worker_token(str(token or "")):
            self._mprc_pending_chat_users.pop(token, None)
            return
        if error:
            self._mprc_pending_chat_users.pop(token, None)
            self._set_chat_play_status(f"MPRC turn failed: {error}")
            self._append_chat_play_line("System", f"MPRC turn failed: {error}", role="system")
            return
        reply = self._normalize_mprc_structured_reply(
            str(reply_text or "").strip(),
            cast=self._mprc_structured_output_cast(),
            sanitize_story_turn=(
                self._mprc_instructor_feature_enabled("mprc_instructor_ar_turn_enabled")
                or self._mprc_instructor_feature_enabled("mprc_instructor_audio_cue_selection_enabled")
            ),
            require_choices=self._mprc_chat_should_offer_choices(),
            available_cues=self.available_story_audio_files(),
        )
        reply = self._finalize_mprc_chat_reply_choice_mode(reply)
        if not reply:
            self._mprc_pending_chat_users.pop(token, None)
            self._set_chat_play_status("MPRC turn returned no story text.")
            return
        self._remote_latest_reply_text = reply
        user_message = self._mprc_pending_chat_users.pop(token, None)
        user_text = self._mprc_chat_message_text(user_message)
        if user_message:
            self._remember_mprc_chat_message(user_message)
        self._remember_mprc_chat_message({"role": "assistant", "content": reply})
        self._append_chat_play_line("Story", reply, role="assistant")
        allow_visuals = bool(self.settings.get("chat_play_allow_story_visuals", False))
        self._suppress_next_auto_visual_reply = not allow_visuals
        try:
            self.roleplay_engine.record_assistant_text(reply, source="mprc_play", user_text=user_text)
        except Exception as exc:
            logger = getattr(self.context, "logger", None)
            if logger is not None:
                logger.warning("[MPRC] Reply hook update failed: %s", exc)
        finally:
            self._suppress_next_auto_visual_reply = False
        scenario = getattr(self, "_scenario_play", None)
        if scenario is not None:
            scenario.restore_scene()
        self._maybe_request_spotify_story_music(reply, user_text=user_text)
        self._speak_mprc_chat_reply(reply)
        self._set_chat_play_status("MPRC turn complete.")
        scenario = getattr(self, "_scenario_play", None)
        if scenario is not None:
            scenario.turn_completed(token)
        self.refresh_ui()

    @staticmethod
    def _normalize_mprc_structured_reply(
        text: str,
        cast: dict[str, dict[str, str]] | None = None,
        *,
        sanitize_story_turn: bool = False,
        require_choices: bool = False,
        available_cues: list[dict[str, Any]] | None = None,
    ) -> str:
        raw = str(text or "").strip()
        if not raw:
            return ""
        payload = MultiPersonaRoleplayController._extract_mprc_structured_reply_payload(raw)
        if payload is None:
            recovered = MultiPersonaRoleplayController._recover_mprc_partial_structured_reply(
                raw,
                cast=cast,
                sanitize_story_turn=sanitize_story_turn,
                require_choices=require_choices,
                available_cues=available_cues,
            )
            if recovered:
                return recovered
            if MultiPersonaRoleplayController._mprc_reply_looks_like_structured_json(raw):
                return (
                    "[NARRATOR]\n"
                    "The structured story response was incomplete and could not be converted. "
                    "Please continue with a shorter story turn."
                )
            return raw
        if sanitize_story_turn:
            payload = structured_models.sanitize_structured_story_turn(
                payload,
                cast=cast,
                require_choices=require_choices,
                available_cues=available_cues,
            )
        converted = MultiPersonaRoleplayController._mprc_structured_reply_to_ar_text(payload, cast=cast)
        if converted:
            return converted
        if MultiPersonaRoleplayController._mprc_reply_looks_like_structured_json(raw):
            return (
                "[NARRATOR]\n"
                "The structured story response did not contain usable story segments. "
                "Please continue with a shorter story turn."
            )
        return raw

    @staticmethod
    def _recover_mprc_partial_structured_reply(
        text: str,
        cast: dict[str, dict[str, str]] | None = None,
        *,
        sanitize_story_turn: bool = False,
        require_choices: bool = False,
        available_cues: list[dict[str, Any]] | None = None,
    ) -> str:
        raw = str(text or "").strip()
        if not MultiPersonaRoleplayController._mprc_reply_looks_like_structured_json(raw):
            return ""
        segments = [
            item
            for item in MultiPersonaRoleplayController._recover_mprc_json_array_items(raw, "segments")
            if isinstance(item, dict)
        ]
        if not segments:
            return ""
        choices = MultiPersonaRoleplayController._recover_mprc_json_array_items(raw, "choices")
        payload: dict[str, Any] = {"segments": segments, "choices": choices}
        if sanitize_story_turn:
            payload = structured_models.sanitize_structured_story_turn(
                payload,
                cast=cast,
                require_choices=require_choices,
                available_cues=available_cues,
            )
        converted = MultiPersonaRoleplayController._mprc_structured_reply_to_ar_text(payload, cast=cast)
        if not converted:
            return ""
        if not choices and MultiPersonaRoleplayController._mprc_structured_json_probably_truncated(raw):
            converted = (
                f"{converted}\n\n"
                "[NARRATOR]\n"
                "The structured response was cut off before it finished. Continue with a shorter turn."
            )
        return converted

    @staticmethod
    def _recover_mprc_json_array_items(text: str, key: str) -> list[Any]:
        raw = str(text or "")
        match = re.search(rf'"{re.escape(str(key or ""))}"\s*:\s*\[', raw)
        if not match:
            return []
        decoder = json.JSONDecoder()
        items: list[Any] = []
        pos = match.end()
        while pos < len(raw):
            while pos < len(raw) and raw[pos] in " \t\r\n,":
                pos += 1
            if pos >= len(raw) or raw[pos] == "]":
                break
            try:
                item, end = decoder.raw_decode(raw[pos:])
            except Exception:
                break
            items.append(item)
            pos += end
        return items

    @staticmethod
    def _mprc_reply_looks_like_structured_json(text: str) -> bool:
        raw = str(text or "")
        head = raw[:5000]
        if STRUCTURED_STORY_SCHEMA_VERSION in head:
            return True
        return '"segments"' in head and ('"speaker_id"' in head or '"response_type"' in head)

    @staticmethod
    def _mprc_structured_json_probably_truncated(text: str) -> bool:
        raw = str(text or "")
        return raw.count("{") != raw.count("}") or raw.count("[") != raw.count("]")

    @staticmethod
    def _extract_mprc_structured_reply_payload(text: str) -> dict[str, Any] | None:
        raw = str(text or "").strip()
        if not raw or "{" not in raw:
            return None
        decoder = json.JSONDecoder()
        for start in [match.start() for match in re.finditer(r"\{", raw)]:
            try:
                payload, _end = decoder.raw_decode(raw[start:])
            except Exception:
                continue
            if isinstance(payload, dict) and MultiPersonaRoleplayController._is_mprc_structured_reply_payload(payload):
                return payload
        return None

    @staticmethod
    def _is_mprc_structured_reply_payload(payload: dict[str, Any]) -> bool:
        if not isinstance(payload, dict):
            return False
        if isinstance(payload.get("segments"), list):
            return True
        story = payload.get("story")
        if isinstance(story, dict) and isinstance(story.get("segments"), list):
            return True
        return isinstance(payload.get("choices"), list) and any(
            key in payload for key in ("segments", "story", "reply", "response")
        )

    @staticmethod
    def _mprc_structured_reply_to_ar_text(payload: dict[str, Any], cast: dict[str, dict[str, str]] | None = None) -> str:
        if not isinstance(payload, dict):
            return ""
        story = payload.get("story")
        source = story if isinstance(story, dict) else payload
        parts: list[str] = []
        choices: list[str] = []
        for item in list(source.get("segments") or []):
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind") or item.get("type") or item.get("role") or "").strip().lower()
            text = str(item.get("text") or item.get("content") or item.get("body") or "").strip()
            if not text:
                continue
            if kind in {"choice", "choices", "option", "options"}:
                choices.extend(MultiPersonaRoleplayController._mprc_structured_choice_lines(text))
                continue
            section = MultiPersonaRoleplayController._mprc_structured_segment_to_ar_text(kind, item, text, cast=cast)
            if section:
                parts.append(section)
        for item in list(source.get("choices") or payload.get("choices") or []):
            choice = MultiPersonaRoleplayController._mprc_structured_choice_text(item)
            if choice:
                choices.append(choice)
        if choices:
            normalized_choices = list(dict.fromkeys(choice for choice in choices if choice))
            if normalized_choices:
                lines = ["[CHOICES]"]
                lines.extend(f"{index}. {choice}" for index, choice in enumerate(normalized_choices, start=1))
                parts.append("\n".join(lines))
        return "\n\n".join(part for part in parts if str(part or "").strip()).strip()

    @staticmethod
    def _mprc_structured_segment_to_ar_text(
        kind: str,
        item: dict[str, Any],
        text: str,
        cast: dict[str, dict[str, str]] | None = None,
    ) -> str:
        if MultiPersonaRoleplayController._mprc_structured_text_starts_with_ar_tag(text):
            return text.strip()
        speaker_id = normalize_persona_id(item.get("speaker_id") or "")
        speaker = MultiPersonaRoleplayController._mprc_structured_speaker_name(
            item.get("speaker") or item.get("speaker_name") or item.get("name") or item.get("character")
        )
        cast_map = dict(cast or {})
        cast_map.setdefault("narrator", {"speaker_name": "Narrator"})
        cast_map.setdefault("unknown_speaker", {"speaker_name": "Unknown Speaker"})
        if speaker_id in cast_map:
            speaker = str(cast_map[speaker_id].get("speaker_name") or speaker or speaker_id).strip()
        if kind == "sfx":
            tags = [
                f"[FX: {tag}]"
                for tag in (
                    re.sub(r"\s+", " ", str(tag or "")).strip()
                    for tag in list(item.get("sfx_tags") or [])
                )
                if tag
            ]
            if not tags:
                tags.append(f"[SFX: {text.strip()}]")
            else:
                tags.append(f"[NARRATOR]\n{text.strip()}")
            return "\n".join(tags)
        if kind in {"music", "ambience", "ambient", "fx", "sfx", "stinger", "audio", "sound"}:
            audio_type = {
                "ambient": "AMBIENCE",
                "ambience": "AMBIENCE",
                "music": "MUSIC",
                "fx": "FX",
                "sfx": "SFX",
                "stinger": "STINGER",
                "audio": "AUDIO",
                "sound": "AUDIO",
            }.get(kind, "AUDIO")
            return f"[{audio_type}: {text.strip()}]"
        if kind == "narrator" or speaker_id in {"narrator", "unknown_speaker"}:
            return f"[NARRATOR]\n{text.strip()}"
        if speaker and not MultiPersonaRoleplayController._mprc_structured_speaker_is_narrator(speaker):
            spoken = MultiPersonaRoleplayController._mprc_structured_character_spoken_text(text)
            return f"[CHARACTER: {speaker}]\n{spoken.strip()}"
        return f"[NARRATOR]\n{text.strip()}"

    @staticmethod
    def _mprc_structured_character_spoken_text(text: str) -> str:
        raw = re.sub(r"\s+", " ", str(text or "")).strip()
        if not raw:
            return ""
        quoted = [
            re.sub(r"\s+", " ", match).strip()
            for match in re.findall(r'["“](.+?)["”]', raw, flags=re.DOTALL)
            if re.sub(r"\s+", " ", match).strip()
        ]
        if quoted:
            return " ".join(quoted).strip()
        return raw.strip(" \"“”")

    @staticmethod
    def _mprc_structured_speaker_name(value: Any) -> str:
        speaker = re.sub(r"\s+", " ", str(value or "")).strip()
        if not speaker:
            return ""
        speaker = re.sub(r"^\[?\s*(?:character|speaker)\s*:\s*", "", speaker, flags=re.IGNORECASE).strip()
        speaker = re.sub(r"\s*\]$", "", speaker).strip()
        return speaker.strip(" :")

    @staticmethod
    def _mprc_structured_speaker_is_narrator(speaker: str) -> bool:
        value = str(speaker or "").strip().lower()
        return not value or value in {"narrator", "story narrator", "master narrator"} or value.startswith("narrator #")

    @staticmethod
    def _mprc_structured_text_starts_with_ar_tag(text: str) -> bool:
        return bool(
            re.match(
                r"^\s*\[/?(?:NARRATOR|CHARACTER|CHOICES|AMBIENCE|AMBIENT|MUSIC|FX|SFX|STINGER|AUDIO)\b",
                str(text or ""),
                flags=re.IGNORECASE,
            )
        )

    @staticmethod
    def _mprc_structured_choice_lines(text: str) -> list[str]:
        return [
            choice
            for choice in (
                MultiPersonaRoleplayController._mprc_structured_choice_text(line)
                for line in str(text or "").splitlines()
            )
            if choice
        ]

    @staticmethod
    def _mprc_structured_choice_text(item: Any) -> str:
        if isinstance(item, dict):
            for key in ("text", "content", "label", "title", "action", "choice"):
                value = str(item.get(key) or "").strip()
                if value:
                    item = value
                    break
            else:
                return ""
        choice = re.sub(r"\s+", " ", str(item or "")).strip()
        choice = re.sub(r"^(?:[-*]\s+|\d+[\.)]\s*)", "", choice).strip()
        return choice

    def _remember_mprc_chat_message(self, message: dict[str, str]) -> None:
        role = str((message or {}).get("role") or "").strip().lower()
        content = str((message or {}).get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            return
        self._mprc_chat_history.append({"role": role, "content": content})
        self._mprc_chat_history = self._mprc_chat_history[-16:]

    def _speak_mprc_chat_reply(self, reply: str, *, on_admitted=None, guard=None) -> None:
        text = str(reply or "").strip()
        if not text:
            return
        voice_segments = self._mprc_chat_reply_voice_segments(text)
        self._begin_remote_speech_audio_capture(text)
        token = self._new_worker_token("mprc_tts")
        if not token:
            if on_admitted is not None:
                on_admitted(False, "MPRC is shutting down.")
            return
        with self._mprc_tts_state_lock:
            self._mprc_tts_token = token

        def worker():
            logger = getattr(self.context, "logger", None)
            try:
                with self._mprc_tts_lock:
                    ready = bool(self.speech.ensure_ready())
                if not ready:
                    if on_admitted is not None:
                        on_admitted(False, "TTS could not be initialized.")
                    if logger is not None:
                        logger.info("[MPRC] TTS could not be initialized; skipping MPRC Play reply speech.")
                    return
                if self._worker_should_emit(token) and (guard is None or guard()):
                    if guard is not None:
                        busy = self._engine_speech_status(strict=True)
                        if busy.get("speech_playing") or busy.get("speech_paused"):
                            on_admitted(False, "Speech became busy before narration admission.")
                            return
                    controller = self.speech.speak(text, segments=list(voice_segments or []))
                    with self._mprc_tts_state_lock:
                        admitted = (
                            self._mprc_tts_token == token
                            and self._worker_should_emit(token)
                            and (guard is None or guard())
                        )
                        if admitted:
                            self._mprc_tts_controller = controller
                    if not admitted:
                        if controller is not None and callable(getattr(controller, "cancel", None)):
                            controller.cancel()
                        return
                    if on_admitted is not None:
                        on_admitted(controller is not None, "Narration admitted." if controller is not None else "Speech admission returned no controller.")
            except Exception as exc:
                if on_admitted is not None:
                    on_admitted(False, str(exc))
                if logger is not None:
                    logger.warning("[MPRC] Could not speak MPRC Play reply: %s", exc)
            finally:
                if self._worker_should_emit(token):
                    with self._mprc_tts_state_lock:
                        if self._mprc_tts_token == token:
                            self._mprc_tts_token = ""
                    self._finish_worker_token(token)
                else:
                    self._cancel_worker_token(token)

        if not self._start_daemon_worker(token, worker, name="nc-mprc-tts"):
            if on_admitted is not None:
                on_admitted(False, "Could not start narration worker.")
            with self._mprc_tts_state_lock:
                if self._mprc_tts_token == token:
                    self._mprc_tts_token = ""
            self._cancel_worker_token(token)

    def _mprc_chat_reply_voice_segments(self, text: str) -> list[dict[str, Any]]:
        content = str(text or "").strip()
        if not content:
            return []
        volume_percent = self.mprc_voice_volume_percent()
        volume = volume_percent / 100.0
        backend = self.current_tts_backend()

        def with_volume(segment: dict[str, Any]) -> dict[str, Any]:
            item = dict(segment or {})
            item["voice_volume"] = volume
            item["voice_volume_percent"] = volume_percent
            route = item.get("voice_route")
            if isinstance(route, dict):
                route = dict(route)
            else:
                route = {}
            route["volume"] = volume
            route["volume_percent"] = volume_percent
            item["voice_route"] = route
            return item

        try:
            routed = self.voice_router.split_text_by_persona(
                {
                    "text": content,
                    "tts_backend": backend,
                    "streaming": False,
                }
            )
            segments = [with_volume(item) for item in list((routed or {}).get("segments") or []) if isinstance(item, dict)]
            if segments:
                return segments
        except Exception as exc:
            logger = getattr(self.context, "logger", None)
            if logger is not None:
                logger.warning("[MPRC] Could not prepare routed Play voice segments: %s", exc)

        route = {}
        try:
            route = self.voice_router.effective_voice_config(
                {
                    "text": content,
                    "tts_backend": backend,
                    "streaming": False,
                }
            )
        except Exception:
            route = {}
        segment = {
            "text": content,
            "persona_id": str((route or {}).get("persona_id") or ""),
            "display_name": str((route or {}).get("display_name") or ""),
            "voice_path": str((route or {}).get("sample_path") or "") if (route or {}).get("supported") else "",
            "voice_route": route if isinstance(route, dict) else {},
        }
        return [with_volume(segment)]

    def _on_mprc_chat_speaker_changed(self):
        combo = self._controls.get("chat_speaker")
        raw_speaker_id = combo.currentData() if combo is not None and hasattr(combo, "currentData") else ""
        speaker_id = str(raw_speaker_id or "").strip()
        if speaker_id:
            self.session.current_speaker_id = speaker_id
            self.save_state()
            self._set_chat_play_status(f"Current MPRC speaker set to {combo.currentText()}.")
        self._refresh_chat_play_story_engine_cards()

    def _on_mprc_chat_visuals_changed(self, checked: bool):
        self.settings["chat_play_allow_story_visuals"] = bool(checked)
        self.storage.save_settings(self.settings)
        self._set_chat_play_status(
            "MPRC Play story visuals enabled." if checked else "MPRC Play story visuals disabled."
        )

    def _on_mprc_chat_structured_output_changed(self, checked: bool):
        if self._syncing:
            return
        self.settings["chat_structured_output_enabled"] = bool(checked)
        self.storage.save_settings(self.settings)
        scope = self._controls.get("chat_structured_output_scope")
        if scope is not None and hasattr(scope, "setEnabled"):
            scope.setEnabled(bool(checked))
        self._refresh_chat_play_story_engine_cards()
        self._set_chat_play_status(
            "MPRC Play request-scoped Structured JSON enabled." if checked else "MPRC Play Structured JSON disabled."
        )

    def _on_mprc_chat_structured_output_scope_changed(self):
        if self._syncing:
            return
        combo = self._controls.get("chat_structured_output_scope")
        scope = str(combo.currentData() or "every_turn").strip() if combo is not None and hasattr(combo, "currentData") else "every_turn"
        if scope not in {"every_turn", "first_turn"}:
            scope = "every_turn"
        self.settings["chat_structured_output_scope"] = scope
        self.storage.save_settings(self.settings)
        label = "every MPRC Play turn" if scope == "every_turn" else "only the first/opening MPRC Play turn"
        self._refresh_chat_play_story_engine_cards()
        self._set_chat_play_status(f"MPRC Play Structured JSON scope: {label}.")

    def _on_mprc_instructor_structured_outputs_changed(self, checked: bool):
        if self._syncing:
            return
        self.settings["mprc_instructor_structured_outputs_enabled"] = bool(checked)
        self.storage.save_settings(self.settings)
        ar_toggle = self._controls.get("chat_instructor_ar_turn")
        if ar_toggle is not None and hasattr(ar_toggle, "setEnabled"):
            ar_toggle.setEnabled(bool(checked))
        self._refresh_chat_play_story_engine_cards()
        availability = instructor_adapter.instructor_availability()
        if checked and not availability.available:
            self._set_chat_play_status(f"Instructor assist enabled, but unavailable now: {availability.reason}. Existing MPRC fallbacks remain active.")
        else:
            self._set_chat_play_status("Instructor assist enabled." if checked else "Instructor assist disabled.")

    def _on_mprc_instructor_ar_turn_changed(self, checked: bool):
        if self._syncing:
            return
        self.settings["mprc_instructor_ar_turn_enabled"] = bool(checked)
        self.storage.save_settings(self.settings)
        self._refresh_chat_play_story_engine_cards()
        self._set_chat_play_status(
            "Instructor AR-turn generation enabled." if checked else "Instructor AR-turn generation disabled."
        )

    def _refresh_remote_controls(self) -> None:
        status = self.remote_status_snapshot()
        installed = self._remote_server_installed()
        code = self._remote_code()
        self._native_remote_controls = {
            "installed": bool(installed),
            "enabled": bool(self.settings.get("remote_enabled", False)) if installed else False,
            "host": self._remote_host(),
            "port": self._remote_port(),
            "pairing_code": code,
            "running": bool(status.get("running")),
            "url": str(status.get("url") or ""),
            "connected_clients": int(status.get("connected_clients") or 0),
            "status": dict(status),
        }

    @staticmethod
    def _chromecast_device_name(device: dict[str, Any]) -> str:
        return str((device or {}).get("name") or (device or {}).get("label") or (device or {}).get("uuid") or "").strip()

    @staticmethod
    def _chromecast_device_tooltip(device: dict[str, Any]) -> str:
        parts = []
        for key, label in (("model_name", "Model"), ("host", "Host"), ("cast_type", "Type"), ("uuid", "UUID")):
            value = str((device or {}).get(key) or "").strip()
            if value:
                parts.append(f"{label}: {value}")
        return "\n".join(parts)

    def _selected_chromecast_device_name(self) -> str:
        return str(self.settings.get("chromecast_device_name") or "").strip()

    def _refresh_chromecast_controls(self) -> None:
        try:
            snapshot = dict(self.remote_chromecast_snapshot() or {})
        except Exception as exc:
            snapshot = {"available": False, "dependency_error": str(exc), "devices": []}
        devices = [
            dict(item)
            for item in list(snapshot.get("devices") or [])
            if isinstance(item, dict)
        ]
        selected = str(
            snapshot.get("selected_device")
            or snapshot.get("active_device")
            or self.settings.get("chromecast_device_name")
            or ""
        ).strip()
        with self._state_lock:
            ui_busy = bool(self._chromecast_ui_busy)
            ui_status = str(self._chromecast_ui_status or "").strip()
        snapshot["devices"] = devices
        snapshot["selected_device"] = selected
        snapshot["busy"] = bool(ui_busy or snapshot.get("busy"))
        if ui_status:
            snapshot["status"] = ui_status
        self._native_chromecast_controls = snapshot

    def _queue_mprc_chromecast_action(self, action: str, device_name: str = "") -> None:
        normalized = str(action or "").strip().lower()
        if normalized not in {"refresh", "install", "start", "stop", "status"}:
            return
        already_busy = False
        with self._state_lock:
            if self._chromecast_ui_busy:
                self._chromecast_ui_status = "Chromecast action is already running."
                already_busy = True
            else:
                self._chromecast_ui_busy = True
                self._chromecast_ui_status = f"Chromecast {normalized} requested..."
        if already_busy:
            self._request_ui_refresh()
            return
        token = self._new_worker_token("mprc_cast")
        if not token:
            with self._state_lock:
                self._chromecast_ui_busy = False
                self._chromecast_ui_status = "Could not start Chromecast worker."
            self._request_ui_refresh()
            return

        def worker():
            message = ""
            try:
                payload: dict[str, Any] = {"action": normalized}
                clean_device = str(device_name or "").strip()
                if clean_device:
                    payload["device_name"] = clean_device
                result = self.remote_chromecast_action(payload)
                accepted = bool((result or {}).get("accepted", False)) if isinstance(result, dict) else False
                cast_state = (result or {}).get("cast") if isinstance(result, dict) else {}
                cast_state = cast_state if isinstance(cast_state, dict) else {}
                message = str((result or {}).get("message") or (result or {}).get("status") or "").strip() if isinstance(result, dict) else ""
                if not message:
                    if normalized == "start" and bool(cast_state.get("casting")):
                        message = f"Casting to {cast_state.get('active_device') or clean_device or 'Chromecast'}."
                    elif normalized == "stop":
                        message = "Chromecast stopped."
                    elif normalized == "refresh":
                        count = len(list(cast_state.get("devices") or []))
                        message = f"Chromecast discovery found {count} device{'s' if count != 1 else ''}."
                    elif normalized == "install":
                        message = "Chromecast dependency install finished."
                    else:
                        message = "Chromecast action finished."
                if not accepted and isinstance(result, dict):
                    message = str(result.get("message") or result.get("error") or message or "Chromecast action was not accepted.")
            except Exception as exc:
                message = f"Chromecast {normalized} failed: {exc}"
                logger = getattr(self.context, "logger", None)
                if logger is not None:
                    logger.warning("[MPRC Chromecast] %s failed: %s", normalized, exc)
            finally:
                if not self._worker_should_emit(token):
                    self._cancel_worker_token(token)
                    return
                with self._state_lock:
                    self._chromecast_ui_busy = False
                    self._chromecast_ui_status = message
                self._finish_worker_token(token)

        if not self._start_daemon_worker(token, worker, name=f"nc-mprc-chromecast-{normalized}"):
            with self._state_lock:
                self._chromecast_ui_busy = False
                self._chromecast_ui_status = "Could not start Chromecast worker."
            self._cancel_worker_token(token)
            self._request_ui_refresh()

    def _on_mprc_chromecast_device_changed(self):
        if self._syncing:
            return
        device_name = self._selected_chromecast_device_name()
        if not device_name:
            return
        if str(self.settings.get("chromecast_device_name") or "").strip() == device_name:
            return
        self.settings["chromecast_device_name"] = device_name
        self.storage.save_settings(self.settings)
        self._refresh_chromecast_controls()

    def _on_mprc_chromecast_refresh_clicked(self):
        if self._syncing:
            return
        self._queue_mprc_chromecast_action("refresh")

    def _on_mprc_chromecast_install_clicked(self):
        if self._syncing:
            return
        self._queue_mprc_chromecast_action("install")

    def _on_mprc_chromecast_start_clicked(self):
        if self._syncing:
            return
        device_name = self._selected_chromecast_device_name()
        if not device_name:
            with self._state_lock:
                self._chromecast_ui_status = "Choose a Chromecast device first."
            self._refresh_chromecast_controls()
            return
        self.settings["chromecast_device_name"] = device_name
        self.storage.save_settings(self.settings)
        self._queue_mprc_chromecast_action("start", device_name)

    def _on_mprc_chromecast_stop_clicked(self):
        if self._syncing:
            return
        self._queue_mprc_chromecast_action("stop")

    def _on_mprc_remote_install_clicked(self):
        if self._syncing:
            return
        self.settings["remote_server_installed"] = True
        self.settings["remote_enabled"] = False
        self._ensure_remote_settings_defaults(installed=True)
        self.storage.save_settings(self.settings)
        self._refresh_remote_controls()
        self._set_chat_play_status("MPRC Remote controls installed. Enable LAN Remote when you want to use the Android companion app.")

    def _on_mprc_remote_enabled_changed(self, checked: bool):
        if self._syncing:
            return
        if not self._remote_server_installed():
            self.settings["remote_enabled"] = False
            self.storage.save_settings(self.settings)
            self._refresh_remote_controls()
            self._set_chat_play_status("Install MPRC Remote controls before enabling the LAN server.")
            return
        self.settings["remote_enabled"] = bool(checked)
        self.storage.save_settings(self.settings)
        self._sync_remote_backend_from_settings()
        status = self.remote_status_snapshot()
        if bool(status.get("running")):
            self._set_chat_play_status(f"MPRC Remote enabled at {status.get('url')}.")
        else:
            self._set_chat_play_status("MPRC Remote disabled.")

    def _on_mprc_remote_endpoint_changed(self):
        if self._syncing:
            return
        if not self._remote_server_installed():
            return
        host_widget = self._controls.get("chat_remote_host")
        port_widget = self._controls.get("chat_remote_port")
        host = str(host_widget.text() if host_widget is not None and hasattr(host_widget, "text") else self._remote_host()).strip() or "0.0.0.0"
        try:
            port = int(port_widget.value() if port_widget is not None and hasattr(port_widget, "value") else self._remote_port())
        except Exception:
            port = DEFAULT_REMOTE_PORT
        port = max(1, min(65535, port))
        changed = host != self._remote_host() or port != self._remote_port()
        self.settings["remote_host"] = host
        self.settings["remote_port"] = port
        self.storage.save_settings(self.settings)
        if changed and bool(self.settings.get("remote_enabled", False)):
            self._sync_remote_backend_from_settings()
        else:
            self._refresh_remote_controls()

    def _on_mprc_remote_code_changed(self):
        if self._syncing:
            return
        if not self._remote_server_installed():
            return
        code_widget = self._controls.get("chat_remote_code")
        try:
            code = self._normalized_remote_code(code_widget.value() if code_widget is not None and hasattr(code_widget, "value") else self._remote_code())
        except Exception:
            code = ""
        if not code:
            code = generate_remote_code()
        changed = code != self._remote_code()
        self.settings["remote_code"] = code
        self.settings.pop("remote_token", None)
        self.storage.save_settings(self.settings)
        if changed and bool(self.settings.get("remote_enabled", False)):
            self._sync_remote_backend_from_settings()
        else:
            self._refresh_remote_controls()
        self._set_chat_play_status(f"MPRC Remote pairing code set to {code}.")

    def _on_mprc_remote_regenerate_token(self):
        if self._syncing:
            return
        if not self._remote_server_installed():
            return
        self.settings["remote_code"] = generate_remote_code()
        self.settings.pop("remote_token", None)
        self.storage.save_settings(self.settings)
        if bool(self.settings.get("remote_enabled", False)):
            self._sync_remote_backend_from_settings()
        else:
            self._refresh_remote_controls()
        self._set_chat_play_status("MPRC Remote pairing code changed. Android clients must reconnect.")

    def _on_mprc_chat_pacing_changed(self, value: str):
        if self._syncing:
            return
        choice = str(value or "").strip()
        if choice:
            self.session.ar_pacing = choice
            self.save_state()
            self._refresh_chat_play_story_engine_cards()
            self._set_chat_play_status(f"Director pacing set to {choice}.")

    def _on_mprc_chat_choice_mode_changed(self):
        if self._syncing:
            return
        combo = self._controls.get("chat_director_choice_mode")
        mode = str(combo.currentData() or "choices").strip() if combo is not None and hasattr(combo, "currentData") else "choices"
        if mode not in {"choices", "ask_next_move"}:
            mode = "choices"
        self.settings["chat_choice_mode"] = mode
        self.storage.save_settings(self.settings)
        self._refresh_chat_play_state_sidebar()
        label = 'ask "What\'s your next move?" without fixed choices' if mode == "ask_next_move" else "offer fixed choices at the end"
        self._set_chat_play_status(f"Director choice mode set to {label}.")

    def _on_mprc_director_action(self, action: str):
        label = {
            "advance": "Advance scene requested.",
            "summarize": "Story summary requested.",
            "repair": "Continuity repair requested.",
        }.get(str(action or "").strip().lower(), "Director action requested.")
        self._append_chat_play_line("Director", label, role="system")
        self._set_chat_play_status(f"{label} Dedicated director execution is the next wiring step.")

    def _guide_speech_command(self) -> dict[str, Any] | None:
        if self._guide_speech_command_checked:
            return self._guide_speech_command_cache
        self._guide_speech_command_checked = True
        system = platform.system().lower()
        if system == "windows":
            for executable in ("powershell.exe", "powershell", "pwsh.exe", "pwsh"):
                program = shutil.which(executable)
                if not program:
                    continue
                script = (
                    "$text = [Console]::In.ReadToEnd(); "
                    "Add-Type -AssemblyName System.Speech; "
                    "$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                    "$speaker.Speak($text)"
                )
                self._guide_speech_command_cache = {
                    "program": program,
                    "arguments": ["-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                    "stdin": True,
                }
                return self._guide_speech_command_cache
        if system == "darwin":
            program = shutil.which("say")
            if program:
                self._guide_speech_command_cache = {"program": program, "arguments": [], "stdin": False}
                return self._guide_speech_command_cache
        for executable, arguments in (("spd-say", ["--wait"]), ("espeak", [])):
            program = shutil.which(executable)
            if program:
                self._guide_speech_command_cache = {"program": program, "arguments": arguments, "stdin": False}
                return self._guide_speech_command_cache
        self._guide_speech_command_cache = None
        return None

    def _set_guide_speech_status(self, message: str) -> None:
        self._native_guide_speech_status = str(message or "")
        self._native_revision += 1

    def _speak_guide_section(self, title: str, text: str) -> None:
        if self.is_shutdown():
            return
        command = self._guide_speech_command()
        if command is None:
            self._warn("Guide Speech", "No supported system speech command was found.")
            return
        speech_text = "\n\n".join(part for part in (str(title or "").strip(), str(text or "").strip()) if part).strip()
        if not speech_text:
            self._set_guide_speech_status("Nothing to read.")
            return
        self._stop_guide_speech()
        process = QtCore.QProcess(self._qt_application_instance())
        self._guide_speech_process = process
        try:
            process.finished.connect(lambda *_args, p=process: self._on_guide_speech_finished(p))
            process.errorOccurred.connect(lambda *_args, p=process: self._on_guide_speech_finished(p))
        except Exception:
            pass
        arguments = list(command.get("arguments") or [])
        if not command.get("stdin"):
            arguments.append(speech_text)
        try:
            process.start(str(command.get("program") or ""), arguments)
            if command.get("stdin"):
                process.write(speech_text.encode("utf-8"))
                process.closeWriteChannel()
            self._set_guide_speech_status(f"Reading: {title}")
        except Exception as exc:
            self._guide_speech_process = None
            self._set_guide_speech_status("Guide speech failed.")
            logger = getattr(self.context, "logger", None)
            if logger is not None:
                logger.warning("[MPRC] Guide speech failed: %s", exc)

    def _on_guide_speech_finished(self, process=None) -> None:
        if process is not None and process is not getattr(self, "_guide_speech_process", None):
            try:
                process.deleteLater()
            except Exception:
                pass
            return
        if self._guide_speech_process is not None:
            try:
                self._guide_speech_process.deleteLater()
            except Exception:
                pass
        self._guide_speech_process = None
        self._set_guide_speech_status("Guide speech stopped.")

    def _stop_guide_speech(self) -> None:
        process = getattr(self, "_guide_speech_process", None)
        self._guide_speech_process = None
        if process is not None:
            try:
                process.kill()
                process.deleteLater()
            except Exception:
                pass
        self._set_guide_speech_status("")

    def _install_tooltips_and_refine(self):
        tooltip_map = {
            "enabled": "Turn MPRC prompt and voice routing on or off. Off restores normal NC chat behavior, normal chat history, and normal voice routing.",
            "active": "Choose the persona that currently shapes MPRC replies, voice routing, character preview, and Visual Reply prompts. In AR Play, Focus can temporarily direct a turn without changing this saved active persona.",
            "ar_mode": "Switch MPRC into AlternativeReality, a narrator-led interactive audiobook/adventure runtime. AR mode expects [NARRATOR], [CHARACTER: Name], [CHOICES], and story audio tags.",
            "chat_start": "Arm the MPRC Play runtime. If an active story exists, the narrator opens or continues that story inside the isolated Play feed instead of normal NC chat.",
            "chat_pause": "Stop the current MPRC Play speech/playback path. Use this when you want to interrupt spoken story output before sending another action.",
            "chat_restart": "Restart the active story from the current setup. This clears story/character memory for the active run and removes auto-created chat characters, while keeping saved personas and saved story files.",
            "chat_clear": "Clear the visible Play transcript. This does not delete personas, story setup, saved memory, or normal NC chat history.",
            "chat_float": "Move the MPRC Play surface into its own floating window, or dock it back into the addon tab when already floating.",
            "chat_export_structured_output": "Export one strict JSON Schema file for LM Studio or another provider Structured Output field. The schema is built from the current MPRC cast.",
            "chat_story_font_size_label": "Font-size setting for the MPRC Story Feed response window.",
            "chat_story_font_size": "Set the font size used by the MPRC Story Feed response window.",
            "chat_remote_install": "Install optional LAN Remote controls for the Android companion app. This does not start the server.",
            "chat_remote_enabled": "Enable the local LAN-only MPRC Remote HTTP backend for the Android companion app.",
            "chat_remote_host": "Bind host for the remote backend. Use 0.0.0.0 for LAN access; requests are still limited to local/private clients.",
            "chat_remote_port": "TCP port for the remote backend. Default is 8765.",
            "chat_remote_code": "Six-digit pairing code for the Android remote app. You can type your own number.",
            "chat_remote_regenerate_token": "Generate a new six-digit remote pairing code. Android clients must reconnect with the new code.",
            "chat_remote_status": "Shows the remote LAN URL, six-digit pairing code, and recent client count.",
            "chat_structured_output": "Attach the MPRC story JSON Schema directly to MPRC Play chat requests only. This does not affect Master Story, persona generation, normal chat, or Visual Reply.",
            "chat_structured_output_scope": "Choose whether request-scoped Structured JSON is used on every MPRC Play turn or only on the opening turn.",
            "chat_instructor_structured_outputs": "Optional Instructor/Pydantic assist for Master Story validation, scene patches, Visual Reply beat grounding, and AudioFX cue sanitizing. Disabled by default and falls back safely when Instructor is unavailable.",
            "chat_instructor_ar_turn": "Optional Instructor/Pydantic generation for full MPRC AR turns. This remains separately disabled by default because it can affect turn style and latency.",
            "chat_runtime_splitter": "Resizable divider between the Story Feed/player action area and the scene-state sidebar.",
            "chat_story_feed_box": "Isolated MPRC story transcript. It shows narrator/character output, choices, selected player actions, and restored memory beats without writing into normal NC chat.",
            "chat_transcript": "Live MPRC Story Feed. Spoken narrator/character chunks are derived from this structured story text and routed by [NARRATOR] and [CHARACTER: Name] tags.",
            "chat_player_action_box": "Player input area for acting, speaking, directing the scene, or asking out-of-character questions inside the MPRC Play runtime.",
            "chat_input": "Type the next player action, dialogue, director note, or OOC request. Choice clicks can fill this field; double-clicking a choice sends it.",
            "chat_use_ar": "Use AlternativeReality prompting for this Play turn. Keep enabled for narrator-led story play; disable only when testing non-AR MPRC behavior.",
            "chat_visuals": "Allow this Play turn to request story-scene Visual Reply images when persona visual settings, cooldowns, and provider readiness allow it.",
            "chat_send": "Send the Player Action to the MPRC-only turn pipeline. If speech is still playing, MPRC stops it before continuing so replies do not overlap.",
            "chat_visual_prompt_debug_box": "Debug-only breakdown of the latest MPRC Visual Reply prompt request. Use this to see which story reply, AR state, persona visual settings, and fallback prompt contributed to the final image prompt.",
            "chat_visual_prompt_debug": "Read-only Visual Reply prompt audit for MPRC Play. It shows the final image prompt plus the current story reply, AR state inputs, persona visual settings, and hidden LLM payload when available.",
            "chat_intent_label": "Intent controls how MPRC interprets the Player Action before building the Play prompt.",
            "chat_intent": "Auto lets MPRC infer Act, Say, Direct, or OOC from the text. Choose a mode only when you want to force how the next Player Action is framed.",
            "chat_speaker_label": "Focus chooses whose perspective or scope the next Player Action targets.",
            "chat_speaker": "Focus for the next Play turn. Player means user/director action; Narrator means scene-level direction; a character means the player acts or speaks through that character for this turn.",
            "chat_status": "Short Play status line for isolated runtime state, send locks, restore notices, visual request state, and story start/stop messages.",
            "chat_scene_state_box": "Compact current scene card used as prompt context: scene, location, time, mood, objective, and active speaker.",
            "chat_scene_state": "Current scene fields carried into the next MPRC Play prompt.",
            "chat_active_speaker": "Resolved active speaker for the current story moment. This can differ from Active persona when Focus or story routing chooses another character.",
            "chat_story_state_tabs": "Cast, Events, and Choices for the current Play scene. These tabs expose enough structured state to understand who is present, what just happened, and what can be done next.",
            "chat_present_characters": "Characters currently present in the story scene. [Auto Chat] entries were created from story labels and are removed by Restart Story.",
            "chat_recent_events": "Recent story events remembered by MPRC. These are compact visible continuity beats, not hidden chain-of-thought.",
            "chat_next_actions": "Current player choices. Click a choice to copy it into Player Action; double-click or press Enter to send it immediately.",
            "chat_director_box": "Director controls for pacing, tone, agency, and maintenance actions that steer the next Play request without editing the story draft.",
            "chat_director_pacing_label": "Pacing controls how quickly the narrator moves from description to consequence or choice.",
            "chat_director_pacing": "Pacing hint for the next Play request. Balanced keeps normal rhythm; faster modes reach choices sooner; slower/audiobook modes allow more narration.",
            "chat_director_tone_label": "Tone controls the emotional color requested for the next scene beat.",
            "chat_director_tone": "Tone hint for the next Play request. Keep current preserves the story's present mood; other choices nudge the narrator for the next beat.",
            "chat_director_agency_label": "Agency controls how strongly MPRC constrains player options and consequences.",
            "chat_director_agency": "Agency hint for the next Play request. Guided offers clear options; Open leaves more room; Strict consequences asks the narrator to enforce outcomes more firmly.",
            "chat_director_choice_mode_label": "Choose whether story replies end with fixed choices or a freeform move prompt.",
            "chat_director_choice_mode": "Offer choices guarantees [CHOICES] at the end. Ask next move removes fixed choices and ends with a freeform prompt.",
            "chat_advance_scene": "Queue a director action asking the narrator to move the scene forward while preserving current continuity.",
            "chat_summarize": "Queue an out-of-character story summary request inside the Play feed.",
            "chat_repair": "Queue a director repair request asking MPRC to restate/repair confusing story state, choices, or speaker routing.",
            "character_preview_panel": "Current-character dashboard. It follows the active persona or current speaker when tracking is enabled, and gives quick access to avatar, save/import/export, duplicate, and edit actions.",
            "current_character_image": "The active persona picture. This updates when the active persona changes or when Track current speaker in character preview follows a story speaker.",
            "current_character_name": "Display name of the persona currently shown in the preview panel.",
            "current_character_role": "Role/archetype for the previewed persona, such as narrator, companion, story character, or auto-created chat participant.",
            "current_character_meta": "Quick status for the current character: ID, behavior, memory scope, voice readiness, visual readiness, and whether an AR profile is active.",
            "current_character_story": "Shows which active and saved Master Stories include this character, and whether the character is active/speaking in the current story.",
            "current_character_quick_status": "Status messages from quick persona actions such as save, import, duplicate, avatar changes, and editor jumps.",
            "current_character_view_mode": "Choose whether the Current Character card shows only personas linked to the loaded story roster or all saved personas.",
            "character_roster_frame": "Horizontal preview strip for the story/persona roster. It is a visual selector, separate from the Registry list.",
            "character_roster_strip": "Scroll through character picture tiles. Click a tile to switch the active persona.",
            "character_roster_content": "Container for the current story/persona picture tiles.",
            "quick_change_avatar": "Choose a new avatar image for the current character.",
            "quick_save_persona": "Save persona, session, and addon settings immediately.",
            "quick_import_persona": "Import persona JSON from disk. This uses the same import flow as the Registry tab.",
            "quick_export_personas": "Export all current personas to a JSON file.",
            "quick_duplicate_persona": "Duplicate the current character as a new editable persona.",
            "quick_edit_persona": "Jump to the Persona Editor for the current character.",
            "show_character": "Keep the character preview panel synchronized with the current speaker. This is only the preview/highlight behavior; story-scene images are controlled by each persona's Visual tab.",
            "persona_list": "All saved personas. Select one to edit it or make it active. [Story] means linked to a saved/active story; [Auto Chat] means MPRC created it from a new character label in the current chat.",
            "add_persona": "Create a new neutral editable persona.",
            "duplicate_persona": "Copy the selected persona as a starting point for a variant.",
            "delete_persona": "Delete the selected persona. At least one persona is always kept.",
            "import_personas": "Import personas from a JSON file.",
            "export_personas": "Export all personas to a JSON file.",
            "reset_defaults": "Restore the bundled neutral defaults and clear the current roleplay scene.",
            "load_default_scenario": "Load the bundled touch-and-go group scenario with all default personas represented.",
            "persona_id": "Stable local ID for this persona. Keep it short and lowercase. Right-click to refine if needed.",
            "persona_enabled": "Enable or disable this persona without deleting it. Disabled personas are kept in storage but ignored by normal routing and story cast selection.",
            "master_narrator": "Mark this persona as a favorite Master narrator. Master narrators are numbered in selectors, prioritized for narrator auto-pick, and protected from deletion.",
            "display_name": "Name shown in the Roleplay UI and prompts. Right-click to refine.",
            "role": "Short archetype or role, such as mentor, narrator, technician, or explorer. Right-click to refine.",
            "description": "Compact visible description of who this persona is. Right-click to refine this Short Description field.",
            "character_image": "Preview of the selected character picture.",
            "character_image_path": "Path to the active persona picture. MPRC stores only the path.",
            "character_image_browse": "Choose a character picture from your drive.",
            "character_image_generate": "Generate a character picture from this persona's prompt/description through Visual Reply.",
            "character_image_clear": "Clear this persona's character picture path.",
            "system_prompt": "Core persona instruction injected into chat when roleplay is enabled. Right-click to refine.",
            "ar_profile_enabled": "Use this persona's AR-specific description and system prompt when AlternativeReality mode is active.",
            "ar_description": "AlternativeReality-only character description. Right-click to refine into cinematic adventure style.",
            "ar_system_prompt": "AlternativeReality-only persona instruction. Right-click to refine for AR pacing, intimacy, and adventure tone.",
            "speaking_style": "How this persona should sound in normal replies. Right-click to refine.",
            "allowed_tone": "Tone boundaries for this persona. Right-click to refine.",
            "response_length": "Preferred length of replies for this persona.",
            "temperature_hint": "Optional style note for randomness or energy. Right-click to refine.",
            "memory_scope": "Controls how the prompt frames persona-specific continuity.",
            "behavior_mode": "Sets the persona's roleplay framing.",
            "tags": "Comma-separated tags for organizing personas. Right-click to refine.",
            "guide_read_all": "Read every section of the Guide tab aloud using the local system speech helper, if one is available.",
            "guide_stop_speech": "Stop Guide tab speech playback.",
            "guide_speech_status": "Shows whether the Guide tab is speaking, stopped, or unavailable on this system.",
            "voice_enabled": "Use this persona's voice sample when roleplay mode is enabled. If disabled or unsupported, NC falls back to the active TTS backend's normal voice.",
            "narrator_persona": "Choose which persona voice is used for [NARRATOR]. Auto uses the Story Narrator/narrator-tagged persona, then falls back to the active persona.",
            "voice_follow_active": "Keep the Voice tab locked to the current active persona. Disable this only when you intentionally want to edit another persona's voice.",
            "voice_current_persona": "Shows the exact persona whose voice fields will be changed.",
            "voice_persona": "Choose which persona's voice settings are shown in the fields below.",
            "voice_backend": "Backend preference. Inherit is safest; overrides warn if they do not match the active NC TTS backend.",
            "voice_sample": "Path to a local reference audio file. MPRC stores only the path. Right-click to refine path text only if needed.",
            "voice_sample_picker": "Fast picker for audio files in the local voices folder. Selecting one writes its full path into Voice sample path.",
            "voice_browse": "Browse for a local voice sample.",
            "voice_clear": "Clear the voice sample path.",
            "voice_preset": "Optional backend-specific voice preset name. Right-click to refine.",
            "voice_language": "Optional language hint for backends that support per-request language.",
            "voice_test": "Check the selected voice routing setup and show warnings if it cannot be applied.",
            "voice_warning": "Voice routing status and fallback warnings.",
            "session_mode": "Choose how active personas participate in the scene.",
            "scene_title": "Short name for the current scene. Right-click to refine.",
            "location": "Current scene location. Right-click to refine.",
            "time_of_day": "Current time, era, or timing cue. Right-click to refine.",
            "mood": "Current mood or atmosphere. Right-click to refine.",
            "objective": "Current scene goal or task. Right-click to refine.",
            "scene_summary": "Compact visible scene continuity summary. Right-click to refine.",
            "roster": "Read-only list of enabled personas in the current group.",
            "auto_select": "Allow the addon to frame speaker selection automatically in multi-character modes.",
            "next_speaker": "Manual next speaker for group or narrator modes.",
            "continuity": "Include continuity guidance in the roleplay prompt.",
            "update_scene": "Keep compact recent event summaries after assistant replies.",
            "ar_enabled": "Switch MPRC into AlternativeReality from inside the dedicated AR tab.",
            "ar_use_persona_profiles": "When enabled, AR uses each persona's AR description and AR system prompt instead of normal companion/tabletop wording.",
            "ar_pacing": "AlternativeReality pacing. Audiobook mode allows longer narration before asking the user.",
            "ar_interaction": "How often AlternativeReality should pause for player choices.",
            "ar_dialogue_density": "Controls how narrator-led or character-dialogue-heavy AR turns should be.",
            "ar_tension": "Compact 0-10 tension hint for the AR prompt.",
            "ar_current_scene": "Current AR scene beat used when the player says continue.",
            "ar_location": "Current AR location carried into the next Play prompt. Keep it concise and visible, not secret.",
            "ar_time_of_day": "Current AR time, lighting, era, or timing cue carried into the next Play prompt.",
            "ar_mood": "Current AR mood/atmosphere hint. This steers tone but should stay short enough to remain prompt-safe.",
            "ar_story_goal": "Current story objective used by Play and Continue requests.",
            "ar_active_characters": "Comma-separated persona IDs active in the AR scene. Characters still speak only when relevant.",
            "ar_player_intent": "Latest player intent/action summary for AR continuity.",
            "ar_pending_choices": "Optional player choices shown or remembered by AR mode.",
            "ar_recent_events": "Read-only compact AR event history. These are visible continuity beats, not hidden reasoning.",
            "ar_seed": "Copy scene, location, mood, time, and objective from the regular Session tab into AR state.",
            "ar_fill_profiles": "Fill missing AR descriptions and AR system prompts from the bundled cinematic adventure defaults.",
            "ar_clear": "Clear AR state and reseed safe defaults if AR mode is active.",
            "story_status": "Readable status of the active story pipeline: story, AR, narrator, personas, memory, voices, visuals, and AudioFX.",
            "story_first_run": "One-click first-run path: load the demo story, validate it, test AudioFX/Visual Reply, and queue Continue.",
            "story_template": "Choose a polished built-in story template to load into AR.",
            "story_load_template": "Load the selected built-in template with narrator, one character, memory seed, visual profile, and AudioFX cue.",
            "story_export_bundle": "Export the current story, linked cast, narrator setup, memory snapshot, AudioFX links, visual settings, and voice routing as a portable JSON bundle.",
            "story_import_bundle": "Import a portable MPRC story bundle and apply it after saving a recovery backup.",
            "story_export_status": "Story Library Export summary. Green option rows have data available to save into the portable story package.",
            "story_export_button": "Create a zip story package from the selected Story Library Export sections. Selected avatar, voice, and AudioFX files are copied into the package when available.",
            "story_import_button": "Import a zip story package, extract assets into this addon's runtime assets folder, remap file paths, and protect existing personas with unique imported IDs.",
            "story_export_preview": "Preview which selected Story Library Export sections currently have data before creating a package.",
            "story_status_refresh": "Recalculate the runtime status and voice routing inspector.",
            "story_validate": "Check the active story for broken narrator, persona, voice, image, memory, AudioFX, and schema/resource issues.",
            "story_restore_backup": "Restore the latest recovery snapshot made automatically before Apply Draft changes story/persona state.",
            "story_reset_only": "Clear only the active story runtime memory and recent scene state without deleting saved personas or unrelated stories.",
            "story_demo": "Load a small local demo story with a narrator, one character, Visual Reply trigger settings, AudioFX cue, and story memory seed.",
            "story_test_narrator_voice": "Queue a short narrator-labelled voice test through the normal chat/TTS path.",
            "story_test_character_voice": "Queue a short character-labelled voice test for the selected or active story character.",
            "story_test_visual": "Request one Visual Reply image using the active story character's visual profile.",
            "story_test_audio": "Play one ready AudioFX cue, creating the local test cues first if needed.",
            "story_validation": "Validation results are shown here so setup problems are visible without opening logs.",
            "story_repair_narrator": "Lock the current story to a usable narrator persona.",
            "story_repair_voice": "Browse for a voice sample for the story narrator or selected voice persona.",
            "story_repair_audio": "Remove missing-file AudioFX items from the active AudioFX list so validation stops routing to broken cues.",
            "story_repair_image": "Browse for a replacement image path for the first broken story persona image or the active persona.",
            "story_repair_memory": "Create or refresh the active story's memory snapshot.",
            "story_repair_personas": "Create safe placeholder personas for missing story persona links.",
            "story_repair_overrides": "Remove persona overrides that point to missing personas or malformed data.",
            "story_voice_routes": "Shows which persona and voice sample each narrator/character role will route to.",
            "story_preview_next": "Preview the next AR prompt request using Continue as the next player action.",
            "story_explain_next": "Explain narrator, active character, voice, memory, Visual Reply, and AudioFX routing for the next turn.",
            "story_next_inspector": "Next-turn inspector output for prompt preview and routing explanation.",
            "story_pinned_facts": "Pinned story facts inserted into long memory context. Keep one compact fact per line.",
            "story_memory_list": "Recent addon-local story memories. Select one to inspect or delete it.",
            "story_memory_refresh": "Reload pinned facts and recent memory from addon storage.",
            "story_memory_save_pins": "Save the pinned facts field into addon-local long memory.",
            "story_memory_delete": "Delete the selected recent memory event and rebuild compact memory indexes.",
            "story_memory_reset_character": "Clear character-specific memory summaries while keeping story events.",
            "story_memory_reset_story": "Clear story event memory while keeping pinned facts.",
            "story_event_log": "Readable reasons for skipped or failed story actions, such as missing AudioFX, unsupported voice backend, cooldowns, or missing memory.",
            "story_clear_log": "Clear the readable skipped-action log.",
            "master_story_prompt": "Describe the full story you want. MPRC asks the current chat provider to draft personas and session state from this.",
            "master_story_visual_direction": "Optional visual art direction for generated persona appearances and avatar portraits.",
            "master_story_sfw_mode": "Keep generated Master Story drafts non-explicit. Romance and mature emotional themes are allowed, but explicit sexual content is avoided.",
            "master_story_native_persona_count": "Target number of story-native persona profiles the Master generator should draft when the prompt does not already name them.",
            "master_story_max_created_characters": "Hard limit for how many new personas can be created from one Master Story apply.",
            "master_story_allow_exceed_max_created_characters": "Override the Master Story apply limit and allow more new personas than Maximum created characters.",
            "master_story_use_existing_personas": "Let the Master generator consider your already saved personas and let Apply Draft map story characters onto them.",
            "master_story_mode": "Choose the mode for this Master Story. It is independent from the Roleplay Session tab mode.",
            "master_story_scene_title": "Optional opening scene title supplied directly to the story generator.",
            "master_story_location": "Optional opening location supplied directly to the story generator.",
            "master_story_time_of_day": "Optional time, period, weather, or timing cue supplied directly to the story generator.",
            "master_story_mood": "Optional opening atmosphere or emotional tone supplied directly to the story generator.",
            "master_story_auto_create": "Create missing personas from the story draft when no existing persona matches.",
            "master_story_auto_assign_voices": "Assign distinct local .wav reference samples to newly created story personas that do not already have a voice. Explicit selections are preserved.",
            "master_story_update_existing": "Update matching personas with non-empty story fields while preserving voice samples and images unless explicitly provided.",
            "master_story_auto_avatars": "After applying a story, request avatar pictures for newly created personas through the existing Visual Reply service.",
            "master_story_avatar_style_sheets": "Optional and default off. After new personas have avatar images, request character reference sheets for image-to-image capable Visual Reply runtimes.",
            "master_story_clear_memory": "Clear old MPRC long memory and start a fresh roleplay session before applying this draft.",
            "master_story_generate": "Generate a reviewable JSON story setup from the prompt.",
            "master_story_apply": "Review character links, then apply the JSON draft to MPRC personas and the current roleplay session.",
            "master_story_save": "Save the current draft as a reusable story in addon storage.",
            "master_story_restart": "Clear current story memory, recent scene state, and Master Story links while keeping saved personas and saved story files.",
            "master_story_draft": "Review or edit the generated story JSON before applying or saving.",
            "master_story_list": "Saved Master Story setups. Loading one relinks existing personas or creates missing ones when enabled.",
            "master_story_load": "Load and apply the selected saved story.",
            "master_story_delete": "Delete the selected saved story from addon storage.",
            "master_story_status": "Status for story generation, save, load, and persona linking.",
            "master_story_image_frame": "Framed 180x180 story image preview for the selected saved story.",
            "master_story_image": "Story image preview. MPRC creates a local fallback cover when a saved story has no image yet.",
            "audio_intro": "Overview for the Audio tab. Story Sounds turns written audio tags into background playback when a matching ready AudioFX item exists.",
            "audio_story_box": "Top-level on/off control for story-triggered AR sounds. Keep this enabled when you want ambience, music, FX, and stingers to play from story tags.",
            "audio_story_note": "Explains what Story Sounds affects. Manual preview buttons still work even when story-triggered playback is disabled.",
            "audiofx_volume_label": "Volume for MPRC AudioFX playback.",
            "audiofx_volume": "Set the volume for addon AudioFX playback. This affects automatic story/background sounds and manual AudioFX previews, but not NC's main TTS voice volume.",
            "audiofx_volume_value": "Current AudioFX volume percentage.",
            "chat_voice_volume_label": "Volume for MPRC-routed Play voice.",
            "chat_voice_volume": "Set the volume for addon-routed story voice in the Play tab. This does not change AudioFX/background sounds.",
            "chat_voice_volume_value": "Current MPRC Play voice volume percentage.",
            "chat_voice_volume_popout": "Open a wider voice-volume control if the toolbar slider is too compact.",
            "audiofx_test_mode": "Create and keep a small local test AudioFX set active for checking tag playback without needing a full external sound library.",
            "audiofx_create_test_sounds": "Generate local WAV test sounds and register them as ready AudioFX items for Ambience, Music, FX, and Stinger tag testing.",
            "audiofx_play_test_tag": "Manually trigger the exact test tag [AMBIENCE: pub ambient]. Use this to confirm playback before relying on generated story text.",
            "audio_prompt_box": "Local prompt builder for reusable audio-generation prompts. It does not generate audio by itself; it creates descriptions you can save or use elsewhere.",
            "audio_story_sounds": "Enable or disable AR story-triggered audio playback. When enabled, tags like [AMBIENCE: pub ambient] are removed from TTS and used to play matching AudioFX files.",
            "audio_sound_description": "Describe the music, ambience, FX, emotion, environment, or sound you want. This can become a saved prompt or AudioFX description. Right-click to refine.",
            "audio_examples": "Example Sound Description inputs you can type or adapt.",
            "audio_type": "Choose how the description should be shaped and categorized: Auto, Music, Ambience, FX, or Stinger.",
            "audio_create_prompt": "Create a polished cinematic Suno-style audio prompt from the description.",
            "audio_prompt_output": "Editable generated prompt. Right-click to refine or edit by hand.",
            "audio_copy_prompt": "Copy the generated audio prompt to the clipboard.",
            "audio_save_prompt": "Save the generated prompt in addon settings for later reuse.",
            "audio_save_item_description": "Store the generated prompt as the addon audio item description and update/create the selected AudioFX item.",
            "audio_clear_prompt": "Clear the audio prompt builder fields.",
            "audio_variation_ambience": "Generate an environment-first variation from the current description.",
            "audio_variation_horror": "Generate a darker horror version from the current description.",
            "audio_variation_calm": "Generate a calmer version from the current description.",
            "audio_variation_action": "Generate a more action-focused version from the current description.",
            "audio_saved_box": "Saved prompt manager for prompts stored in addon settings.",
            "audio_saved_count": "Shows how many audio prompts are saved.",
            "audio_saved_prompts": "Saved audio prompts. Double-click a prompt to load it into the editor.",
            "audio_load_saved": "Load the selected saved prompt into the description, type, and output fields.",
            "audio_delete_saved": "Delete the selected saved prompt from addon settings.",
            "audiofx_box": "Manage reusable AudioFX items that connect a sound description to a local audio file. Ready items are available to AR prompts and story audio tags.",
            "audiofx_count": "Shows how many AudioFX items are saved, how many have ready files, and how many story audio cues are available.",
            "audiofx_list": "AudioFX items. Green text means the attached local audio file exists and is indexed for story use. Double-click an item to load its description into the prompt builder.",
            "audiofx_status": "Shows the selected AudioFX file path and ready/missing status, plus import results after loading a sound pack.",
            "audiofx_create": "Create a new AudioFX item from the current Sound Description and generated prompt.",
            "audiofx_import_pack": "Import a prepared AudioFX sound pack folder containing mprc_audio_pack.json or audio_pack.json. This bulk-adds ready sounds, updates existing matching cues, and avoids duplicate entries.",
            "audiofx_add_file": "Attach or replace the local audio file for the selected AudioFX item and add it to the story audio database.",
            "audiofx_play": "Play the selected AudioFX file as a manual preview. This works even when Story Sounds is off.",
            "audiofx_load": "Load the selected AudioFX description and prompt into the prompt builder.",
            "audiofx_delete": "Delete the selected AudioFX item from addon settings. The audio file on disk is not deleted.",
            "reset_scene": "Clear current scene state while keeping the active persona.",
            "export_session": "Export the current roleplay session JSON.",
            "import_session": "Import a roleplay session JSON.",
            "visual_enabled": "Allow this persona to request story-scene images in the existing Visual Reply window.",
            "visual_mode": "Controls when this persona may automatically request Visual Reply story images.",
            "visual_mode_note": "Explains the selected automatic image trigger.",
            "visual_provider": "Visual Reply provider override. Inherit uses NC's current Visual Reply provider.",
            "visual_model": "Optional image model override. Right-click to refine only if the model name is descriptive text.",
            "visual_size": "Image size override for this persona.",
            "visual_style": "Persona-specific visual style preset.",
            "visual_character": "Visual identity and appearance for this persona. Right-click to refine.",
            "visual_clothing": "Recurring clothing, tools, or props. Right-click to refine.",
            "visual_environment": "Environment style for images. Right-click to refine.",
            "visual_negative": "Things image generation should avoid. Right-click to refine.",
            "visual_continuity": "Preserve recurring character and scene details across image prompts.",
            "visual_appearance_freedom": "Flexible allows scene-led changes to hair, makeup, clothing and facial styling. The saved chat avatar is unchanged.",
            "visual_scene": "Include the latest roleplay scene summary in image prompts.",
            "visual_speaker": "Include active speaker identity in image prompts.",
            "visual_interval": "When Visual mode is auto_every_n_replies, generate after this many assistant replies.",
            "visual_cooldown": "Minimum seconds between automatic image requests.",
            "visual_max_auto": "Maximum automatic images allowed in one roleplay session. Zero means no auto limit.",
            "visual_auto_show": "Show the existing Visual Reply dock when an image is requested.",
            "visual_generate": "Request a story-scene image in the existing Visual Reply window using the selected persona's effective image prompt.",
            "visual_preview": "Show the generated image prompt in the debug panel without requesting an image.",
            "debug_prompt": "Effective persona prompt/context used by MPRC for the current or last routed request. Use this to verify persona, AR, memory, scene, and instruction text before blaming the model.",
            "debug_visual": "Effective Visual Reply payload/prompt for the current persona or last story image request. Use this to inspect provider, model, size, persona visual fields, scene context, and skip reasons.",
            "debug_voice": "Effective voice routing config for the current or last persona route. Use this to verify persona ID, selected voice sample, backend support, route reason, warning, and fallback behavior.",
            "debug_state": "Compact JSON state snapshot for MPRC: session, AR state, active persona, memory, story links, and runtime flags that feed prompt/routing decisions.",
            "debug_clear": "Clear the Debug tab panes. This only clears the displayed debug output, not story state, memory, generated images, or Visual Reply settings.",
            "debug_visual_calls": "Live Visual Reply audit log for MPRC. It shows queued, accepted, skipped, and failed image requests with persona, reason, source, and prompt preview.",
            "debug_visual_calls_copy": "Copy the Visual Reply call log to the clipboard.",
            "debug_visual_calls_clear": "Clear the MPRC Visual Reply call log. This does not delete generated images or change Visual Reply settings.",
        }
        for key, tooltip in tooltip_map.items():
            widget = self._controls.get(key)
            if widget is not None and hasattr(widget, "setToolTip"):
                widget.setToolTip(tooltip)

        refine_map = {
            "persona_id": ("Persona ID", "Refine into a stable lowercase identifier. Use words separated by underscores."),
            "display_name": ("Display Name", "Refine into a short user-facing character name."),
            "role": ("Role / Archetype", "Refine into a compact role or archetype label."),
            "description": ("Short Description", "Refine into a concise persona description. Keep it short and prompt-ready."),
            "character_image_path": ("Character Picture Path", "Clean up the local image path only. Do not invent a file path."),
            "system_prompt": ("System Prompt", "Refine into a clear persona prompt. Preserve all constraints and roleplay intent."),
            "ar_description": ("AR Description", "Refine into a cinematic, suggestive, non-explicit adventure character description."),
            "ar_system_prompt": ("AR System Prompt", "Refine into AlternativeReality persona instructions: adventurous, intimate, consensual, stylish, and not tabletop/DnD-specific."),
            "master_story_prompt": ("Master Story Prompt", "Refine into a complete story setup request with premise, tone, characters, scene, objective, and pacing. Keep it non-explicit and user-agency friendly."),
            "master_story_visual_direction": ("Avatar Visual Direction", "Refine into concise art direction for persona portraits. Include genre, costume, mood, and medium without over-constraining the image model."),
            "master_story_draft": ("Master Story JSON Draft", "Clean up this story JSON while preserving schema, persona IDs, and all user-authored story intent."),
            "speaking_style": ("Speaking Style", "Refine into compact voice and phrasing guidance."),
            "allowed_tone": ("Allowed Tone", "Refine into concise tone boundaries."),
            "temperature_hint": ("Temperature / Style Hint", "Refine into a short style-control hint without inventing settings."),
            "tags": ("Tags", "Refine into comma-separated lowercase tags."),
            "voice_sample": ("Voice Sample Path", "Clean up the path text only. Do not invent a file path."),
            "voice_preset": ("Voice Preset Name", "Refine into a short backend preset label."),
            "scene_title": ("Scene Title", "Refine into a short title for the roleplay scene."),
            "location": ("Location", "Refine into a compact scene location."),
            "time_of_day": ("Time / Mood", "Refine into a compact timing cue."),
            "mood": ("Mood", "Refine into concise atmosphere guidance."),
            "objective": ("Current Objective", "Refine into a clear current scene goal."),
            "scene_summary": ("Scene Summary", "Refine into compact visible continuity notes. Do not add hidden reasoning."),
            "audio_sound_description": ("Sound Description", "Refine into a compact audio-generation description. Preserve the user's intended sound."),
            "audio_prompt_output": ("Audio Prompt", "Improve this Suno-style prompt while preserving type, mood, environment, and no-vocals constraints."),
            "visual_model": ("Image Model Override", "Clean up the model name only. Do not invent a different model."),
            "visual_character": ("Character Visual Description", "Refine into a concise visual identity prompt."),
            "visual_clothing": ("Clothing / Props", "Refine into compact recurring wardrobe and prop details."),
            "visual_environment": ("Environment Style", "Refine into concise image environment guidance."),
            "visual_negative": ("Negative Prompt / Avoid List", "Refine into clear image-generation exclusions."),
        }
        for key, (label, guidance) in refine_map.items():
            self._install_refine_menu(self._controls.get(key), label, guidance)

    def _install_refine_menu(self, widget, field_label: str, guidance: str = ""):
        if widget is None or bool(getattr(widget, "isReadOnly", lambda: False)()):
            return
        if not (hasattr(widget, "text") or hasattr(widget, "toPlainText")):
            return
        widget.setProperty("_mprc_refine_label", str(field_label or "Field"))
        widget.setProperty("_mprc_refine_guidance", str(guidance or ""))
        try:
            widget.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
            widget.customContextMenuRequested.connect(
                lambda point, edit=widget: self._show_refine_menu(edit, point)
            )
        except Exception:
            return
        existing_tip = str(widget.toolTip() or "").strip()
        refine_tip = "Right-click this field and choose Refine to improve it with the current chat provider."
        widget.setToolTip(f"{existing_tip}\n\n{refine_tip}" if existing_tip else refine_tip)

    def _install_spellcheck_widgets(self) -> None:
        spellcheck_keys = (
            "chat_input",
            "description",
            "system_prompt",
            "ar_description",
            "ar_system_prompt",
            "scene_summary",
            "ar_pending_choices",
            "audio_sound_description",
            "audio_prompt_output",
            "master_story_prompt",
            "master_story_visual_direction",
            "visual_character",
        )
        for key in spellcheck_keys:
            self._attach_spellcheck_to_widget(self._controls.get(key))

    def _refinable_widget_text(self, widget) -> str:
        if widget is None:
            return ""
        if hasattr(widget, "toPlainText"):
            return str(widget.toPlainText() or "").strip()
        if hasattr(widget, "text"):
            return str(widget.text() or "").strip()
        return ""

    def _set_refinable_widget_text(self, widget, text: str) -> None:
        if widget is None:
            return
        if hasattr(widget, "setPlainText"):
            widget.setPlainText(str(text or ""))
        elif hasattr(widget, "setText"):
            widget.setText(str(text or ""))

    def _refine_field(self, widget):
        if widget is None or self.is_shutdown() or bool(widget.property("_nc_refine_in_flight")):
            return
        original = self._refinable_widget_text(widget)
        if not original:
            return
        label = str(widget.property("_mprc_refine_label") or "Field")
        guidance = str(widget.property("_mprc_refine_guidance") or "")
        if widget is self._controls.get("master_story_prompt"):
            guidance = (guidance + "\n\n" + self._master_story_generation_constraints_text()).strip()
        token = self._new_worker_token("refine")
        if not token:
            return
        widget.setProperty("_nc_refine_in_flight", True)
        widget.setProperty("_nc_refine_token", token)
        try:
            self._refine_widgets[token] = weakref.ref(widget)
        except TypeError:
            self._refine_widgets[token] = lambda widget=widget: widget

        def worker():
            error = ""
            result = ""
            try:
                result = str(
                    self.prompt_refinement.refine(
                        original,
                        label=label,
                        guidance=guidance,
                    )
                    or ""
                ).strip()
            except Exception as exc:
                error = str(exc) or repr(exc)
            if not self._worker_should_emit(token):
                return
            try:
                bridge = getattr(self, "_refine_bridge", None)
                if bridge is not None:
                    bridge.finished.emit(token, label, result, error)
                else:
                    self._cancel_worker_token(token)
            except RuntimeError:
                self._cancel_worker_token(token)

        if not self._start_daemon_worker(token, worker, name="nc-mprc-refine"):
            self._refine_widgets.pop(token, None)
            widget.setProperty("_nc_refine_in_flight", False)
            widget.setProperty("_nc_refine_token", "")

    def _on_field_refined(self, token: str, field_label: str, refined_text: str, error: str) -> None:
        token_text = str(token or "")
        self._refine_widgets.pop(token_text, None)
        if not self._finish_worker_token(token_text):
            return
        refined = str(refined_text or "").strip()
        result = {
            "token": token_text,
            "field_label": str(field_label or ""),
            "text": refined,
            "error": str(error or ""),
            "accepted": bool(refined and not error and not self._refined_text_looks_like_mprc_structured_output(refined)),
        }
        if error:
            self._warn(f"Refine {field_label}", f"Refinement failed: {error}")
        elif refined and self._refined_text_looks_like_mprc_structured_output(refined):
            result["error"] = "The provider returned structured MPRC output instead of refined field text."
            self._warn(f"Refine {field_label}", result["error"])
        self._native_refinement_result = result
    @staticmethod
    def _refined_text_looks_like_mprc_structured_output(text: str) -> bool:
        raw = str(text or "").strip()
        if not raw.startswith("{"):
            return False
        lowered = raw.lower()
        return (
            '"schema_version"' in lowered
            and "mprc.story_output" in lowered
            and '"segments"' in lowered
        ) or (
            '"response_type"' in lowered
            and '"story_turn"' in lowered
            and '"segments"' in lowered
        )

    def refresh_ui(self):
        if self.is_shutdown():
            return
        self._ensure_session_persona()
        self._refresh_persona_selectors()
        self._populate_audio_saved_prompts()
        self._populate_audiofx_items()
        self._refresh_memory_browser()
        self._refresh_character_preview()
        self._refresh_debug()
        self._refresh_remote_controls()
        self._refresh_chromecast_controls()
        self._refresh_event_log_panel()
        self._native_revision += 1

    def _refresh_persona_selectors(self) -> None:
        active_id = str(self.session.active_persona_id or "")
        current_id = str(self.session.current_speaker_id or active_id)
        self._native_persona_registry = [
            {
                "id": persona.id,
                "label": self._persona_story_label(persona),
                "display_name": persona.display_name,
                "enabled": bool(persona.enabled),
                "active": persona.id == active_id,
                "current_speaker": persona.id == current_id,
                "protected": bool(self._persona_is_master_narrator(persona)),
                "tooltip": self._persona_story_tooltip(persona),
                "character_image_path": str(persona.character_image_path or ""),
            }
            for persona in self.personas
        ]
    def _refresh_chat_play_controls(self):
        self._native_play_controls = {
            "speaker_id": str(self.session.current_speaker_id or ""),
            "use_ar": self.session.mode == AR_MODE,
            "allow_story_visuals": bool(self.settings.get("chat_play_allow_story_visuals", False)),
            "structured_output": self._mprc_chat_structured_output_enabled(),
            "structured_output_scope": self._mprc_chat_structured_output_scope(),
            "instructor_structured_outputs": bool(
                self.settings.get("mprc_instructor_structured_outputs_enabled", False)
            ),
            "instructor_ar_turn": bool(
                self.settings.get("mprc_instructor_ar_turn_enabled", False)
            ),
            "pacing": str(self.session.ar_pacing or "Balanced"),
            "choice_mode": self._mprc_chat_choice_mode(),
            "pending": bool(self._mprc_pending_chat_users),
        }
        self._refresh_remote_controls()
        self._refresh_chromecast_controls()

    def _chat_story_font_size(self) -> int:
        try:
            value = int(self.settings.get("chat_story_font_size", 13))
        except Exception:
            value = 13
        return max(9, min(28, value))

    def _sync_chat_play_story_font_controls(self, *, spin=None) -> None:
        spin = spin or self._controls.get("chat_story_font_size")
        value = self._chat_story_font_size()
        if spin is not None and hasattr(spin, "setValue"):
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)
        self._apply_chat_play_story_font_size(value)

    def _apply_chat_play_story_font_size(self, size: int | None = None, *, transcript=None) -> None:
        try:
            value = int(size if size is not None else self._chat_story_font_size())
        except Exception:
            value = 13
        value = max(9, min(28, value))
        transcript = transcript or self._controls.get("chat_transcript")
        if transcript is None:
            return
        try:
            font = QtGui.QFont(transcript.font())
            font.setPointSize(value)
            transcript.setFont(font)
            document = transcript.document() if hasattr(transcript, "document") else None
            if document is not None and hasattr(document, "setDefaultFont"):
                document.setDefaultFont(font)
        except RuntimeError:
            return
        except Exception:
            return

    def _on_mprc_story_font_size_changed(self, value: int) -> None:
        if self._syncing:
            return
        try:
            size = int(value)
        except Exception:
            size = 13
        size = max(9, min(28, size))
        self.settings["chat_story_font_size"] = size
        self.storage.save_settings(self.settings)
        self._apply_chat_play_story_font_size(size)

    def mprc_voice_volume_percent(self) -> int:
        try:
            value = int(self.settings.get("mprc_voice_volume", 100))
        except Exception:
            value = 100
        return max(0, min(100, value))

    def mprc_voice_volume_factor(self) -> float:
        return self.mprc_voice_volume_percent() / 100.0

    def _sync_chat_play_voice_volume_controls(self, *, slider=None, value_label=None) -> None:
        slider = slider or self._controls.get("chat_voice_volume")
        value_label = value_label or self._controls.get("chat_voice_volume_value")
        volume = self.mprc_voice_volume_percent()
        if slider is not None and hasattr(slider, "setValue"):
            slider.blockSignals(True)
            slider.setValue(volume)
            slider.blockSignals(False)
        if value_label is not None and hasattr(value_label, "setText"):
            value_label.setText(f"{volume}%")

    def _on_mprc_voice_volume_changed(self, value: int) -> None:
        if self._syncing:
            return
        try:
            volume = int(value)
        except Exception:
            volume = 100
        volume = max(0, min(100, volume))
        self.settings["mprc_voice_volume"] = volume
        self.storage.save_settings(self.settings)
        label = self._controls.get("chat_voice_volume_value")
        if label is not None and hasattr(label, "setText"):
            label.setText(f"{volume}%")
        self._refresh_debug()

    def _refresh_chat_play_buffer_race(self) -> None:
        summary = self._controls.get("chat_buffer_race_summary")
        render_bar = self._controls.get("chat_buffer_race_render")
        playback_bar = self._controls.get("chat_buffer_race_playback")
        if summary is None and render_bar is None and playback_bar is None:
            return
        counts = self._chat_play_buffer_race_counts()
        render_active = counts["render_active"]
        playback_active = counts["playback_active"]
        total_active = render_active + playback_active
        if summary is not None and hasattr(summary, "setText"):
            if total_active:
                summary.setText(f"Active: render {render_active}, preview/playback {playback_active}.")
            else:
                summary.setText("Idle: render and playback buffers are clear.")
        if render_bar is not None and hasattr(render_bar, "setValue"):
            render_bar.setValue(100 if render_active == 0 else 38)
            render_bar.setFormat("Render Ready: ready" if render_active == 0 else f"Render Ready: {render_active} running")
        if playback_bar is not None and hasattr(playback_bar, "setValue"):
            playback_bar.setValue(100 if playback_active == 0 else 38)
            playback_bar.setFormat(
                "Preview / Playback: ready" if playback_active == 0 else f"Preview / Playback: {playback_active} running"
            )

    def _chat_play_buffer_race_counts(self) -> dict[str, int]:
        with self._state_lock:
            tokens = [str(token or "") for token in self._active_worker_tokens]
            manual_images = len(self._manual_character_image_inflight)
            tts_persona_visuals = len(self._tts_persona_visual_inflight)
            tts_visual_replies = len(self._tts_visual_reply_inflight)
            story_audio_active = bool(self._story_audio_block_active)
        with self._mprc_tts_state_lock:
            tts_active = bool(self._mprc_tts_token or self._mprc_tts_controller is not None)

        render_prefixes = (
            "mprc_chat",
            "mprc_visual",
            "mprc_manual_visual",
            "mprc_draft_avatar",
            "mprc_story_avatar",
            "mprc_tts_character_image",
            "mprc_tts_visual_reply",
            "master_story",
            "refine",
        )
        playback_prefixes = ("mprc_tts", "voice_preview")
        render_active = sum(1 for token in tokens if token.startswith(render_prefixes))
        playback_active = sum(
            1
            for token in tokens
            if token.startswith(playback_prefixes)
            and not token.startswith(("mprc_tts_character_image", "mprc_tts_visual_reply"))
        )
        render_active = max(render_active, manual_images + tts_persona_visuals + tts_visual_replies)
        playback_active = max(playback_active, 1 if tts_active else 0)
        playback_active += 1 if story_audio_active else 0
        return {
            "render_active": max(0, int(render_active)),
            "playback_active": max(0, int(playback_active)),
        }

    def _set_list_items(self, widget, items: list[str], *, empty_text: str = ""):
        if widget is None:
            return
        widget.clear()
        visible = [str(item or "").strip() for item in list(items or []) if str(item or "").strip()]
        if not visible and empty_text:
            visible = [empty_text]
        for text in visible:
            widget.addItem(text)

    def _set_chat_play_summary_text(self, key: str, text: str) -> None:
        widget = self._controls.get(key)
        if widget is None or not hasattr(widget, "setPlainText"):
            return
        widget.setPlainText(str(text or "").strip())

    def _refresh_chat_play_story_engine_cards(self) -> None:
        if not self._controls.get("chat_story_engine_tabs"):
            return
        self._set_chat_play_summary_text("chat_story_director_summary", self._chat_play_story_director_summary_text())
        self._set_chat_play_summary_text("chat_memory_databank_summary", self._chat_play_memory_databank_summary_text())
        self._set_chat_play_summary_text("chat_visual_beat_summary", self._chat_play_visual_beat_summary_text())
        self._set_chat_play_summary_text("chat_voice_segments_summary", self._chat_play_voice_segments_summary_text())
        self._set_chat_play_summary_text("chat_spotify_music_summary", self._chat_play_spotify_music_summary_text())

    def _chat_play_story_director_summary_text(self) -> str:
        full_setup = not bool(self._mprc_chat_history) and int(getattr(self.session, "turn_index", 0) or 0) <= 0
        speaker = self.current_speaker_persona()
        narrator = self.selected_narrator_persona()
        pacing = str(self.session.ar_pacing or self._control_current_text("chat_director_pacing") or "Balanced").strip()
        dialogue_density = str(self.session.ar_dialogue_density or "Balanced narrator + character dialogue").strip()
        tone = str(self._control_current_text("chat_director_tone") or "Keep current").strip()
        agency = str(self._control_current_text("chat_director_agency") or "Guided").strip()
        choice_mode = "Ask next move" if self._mprc_chat_choice_mode() == "ask_next_move" else "Offer choices"
        structured = "on" if self._mprc_chat_structured_output_enabled() else "off"
        structured_scope = self._mprc_chat_structured_output_scope().replace("_", " ")
        instructor_state = "on" if bool(self.settings.get("mprc_instructor_structured_outputs_enabled", False)) else "off"
        instructor_ar = "on" if bool(self.settings.get("mprc_instructor_ar_turn_enabled", False)) else "off"
        followup_cast_label = (
            "Joined cast"
            if self._mprc_chat_followup_cast_mode() == story_director.CAST_MODE_JOINED_CAST
            else "Focused speaker"
        )
        lines = [
            "Cast mode: Focused speaker for single-character Play turns; Joined cast for opening/setup and auto ensemble turns.",
            f"Current prompt mode: {'Joined cast' if full_setup else followup_cast_label}.",
            f"Focused speaker: {speaker.display_name if speaker is not None else 'Player'}.",
            f"Narrator voice/persona: {narrator.display_name if narrator is not None else 'auto / not resolved yet'}.",
            f"Director controls: pacing={pacing}, dialogue={dialogue_density}, tone={tone}, agency={agency}, ending={choice_mode}.",
            f"Structured JSON: {structured}, scope={structured_scope}.",
            f"Instructor assist: {instructor_state}, AR turns={instructor_ar}.",
            "Speaker discipline: narration, character dialogue, choices, and story audio tags are kept in separate blocks for routing.",
        ]
        return "\n".join(lines)

    def _chat_play_memory_databank_summary_text(self) -> str:
        backend_raw = str(
            self.settings.get("long_memory_database_backend")
            or self.settings.get("memory_database_backend")
            or "sqlite"
        ).strip().lower()
        backend_label = {
            "sqlite": "SQLite",
            "postgres": "PostgreSQL",
            "postgresql": "PostgreSQL",
        }.get(backend_raw, backend_raw or "SQLite")
        sources = self._remote_memory_databank_sources(self.settings)
        memory = getattr(self, "long_memory", None)
        payload: dict[str, Any] = {}
        if memory is not None and hasattr(memory, "load"):
            try:
                loaded = memory.load()
                payload = loaded if isinstance(loaded, dict) else {}
            except Exception:
                payload = {}
        events = list(payload.get("events") or []) if isinstance(payload.get("events"), list) else []
        chapters = list(payload.get("chapters") or []) if isinstance(payload.get("chapters"), list) else []
        pinned_raw = payload.get("pinned_facts")
        if isinstance(pinned_raw, str):
            pinned = [item.strip() for item in pinned_raw.splitlines() if item.strip()]
        else:
            pinned = [str(item).strip() for item in list(pinned_raw or []) if str(item).strip()]
        character_memory = dict(payload.get("character_memory") or {}) if isinstance(payload.get("character_memory"), dict) else {}
        indexed_sources = sorted(str(item) for item in list(getattr(memory, "_indexed_databank_sources", set()) or []) if str(item).strip())
        database_available = bool(getattr(memory, "database", None) is not None)
        databank_available = bool(getattr(memory, "databank", None) is not None)
        lines = [
            f"Database backend: {backend_label} ({'available' if database_available else 'not open'}).",
            f"Data bank: {'available' if databank_available else 'not available'}.",
            f"Pinned facts: {len(pinned)}.",
            f"Remembered story events: {len(events)}.",
            f"Chapter summaries: {len(chapters)}.",
            f"Character memory entries: {len(character_memory)}.",
            "Configured data-bank sources: " + (", ".join(sources) if sources else "none configured."),
            "Indexed data-bank sources: " + (", ".join(indexed_sources) if indexed_sources else "none indexed yet."),
            "Prompt use: relevant memory and data-bank snippets are read into hidden MPRC story context; this card does not change memory.",
        ]
        return "\n".join(lines)

    def _chat_play_visual_beat_summary_text(self) -> str:
        persona = self.current_speaker_persona() or self.active_persona()
        latest = self._latest_mprc_story_reply_text()
        beat = story_director.build_visual_beat_context(
            persona=persona,
            personas=self.story_prompt_personas(),
            session=self.session,
            reason="assistant_reply" if latest else "manual",
            source_text=latest,
        )
        prompt, prompt_reason, prompt_persona = self._chat_play_visual_prompt_snapshot()
        lines = [
            f"Latest visible beat: {beat.get('latest_visible_action') or 'No latest visible action yet.'}",
            f"Visual subject: {beat.get('visual_subject') or 'current scene'}.",
            f"Location: {beat.get('location') or 'unknown'}.",
            f"Time: {beat.get('time_of_day') or 'not set'}.",
            f"Mood: {beat.get('mood') or 'not set'}.",
            f"Story goal: {beat.get('story_goal') or 'not set'}.",
            f"Image intent: {prompt or 'No Visual Reply prompt has been generated yet.'}",
        ]
        if prompt_reason or prompt_persona:
            lines.append(
                "Prompt snapshot: "
                + ", ".join(
                    item for item in (f"reason={prompt_reason}" if prompt_reason else "", f"persona={prompt_persona}" if prompt_persona else "") if item
                )
            )
        lines.append("Selection rule: prefer the newest visible scene beat; ignore choices, hidden prompt text, and stale setup.")
        return "\n".join(lines)

    def _chat_play_voice_segments_summary_text(self) -> str:
        latest = self._latest_mprc_story_reply_text()
        tag_speakers = self._mprc_story_reply_tagged_speakers(latest)
        lines = [
            "Multi-voice contract: [NARRATOR] carries narration; [CHARACTER: Exact Name] carries only that speaker's spoken line.",
            "Tagged speakers: " + (", ".join(tag_speakers) if tag_speakers else "none in latest reply yet."),
        ]
        if not latest:
            lines.append("Latest reply: no Play story reply has been produced yet.")
            return "\n".join(lines)
        try:
            segments = self._mprc_chat_reply_voice_segments(latest)
        except Exception as exc:
            segments = []
            lines.append(f"Route preview unavailable: {exc}")
        lines.append(f"Route preview segments: {len(segments)}.")
        for index, segment in enumerate(list(segments or [])[:8], start=1):
            route = dict(segment.get("voice_route") or {}) if isinstance(segment, dict) else {}
            persona_id = str(segment.get("persona_id") or route.get("persona_id") or "").strip()
            display = str(segment.get("display_name") or route.get("display_name") or persona_id or "Narrator").strip()
            sample = str(segment.get("voice_path") or route.get("sample_path") or "").strip()
            sample_label = Path(sample).name if sample else "no voice sample"
            reason = str(route.get("route_reason") or "route").strip()
            text = self._mprc_compact(segment.get("text", ""), 110) if isinstance(segment, dict) else ""
            lines.append(f"{index}. {display}: {sample_label}, {reason}, {text}")
        return "\n".join(lines)

    def _chat_play_spotify_music_summary_text(self) -> str:
        service = self._spotify_sense_service()
        payload = dict(getattr(self, "_last_spotify_story_music_payload", {}) or {})
        result = dict(getattr(self, "_last_spotify_story_music_result", {}) or {})
        lines = [
            "Spotify Sense: " + ("available" if service is not None else "not loaded"),
            "Story music: MPRC only sends scene intent; Spotify Sense owns playback, device selection, and fades.",
        ]
        if not payload:
            lines.append("Last request: none yet.")
            lines.append("Default selection rule: prefer cinematic ambience unless the story beat clearly needs active music.")
            return "\n".join(lines)
        lines.extend(
            [
                f"Last request mood: {payload.get('mood') or 'unknown'}.",
                f"Music kind: {payload.get('music_kind') or 'ambient'}.",
                f"Spotify query: {payload.get('query') or 'not set'}.",
                f"Latest visible beat: {payload.get('latest_visible_beat') or 'none captured'}.",
            ]
        )
        if result:
            if result.get("ok"):
                state = "transitioning" if result.get("transitioning") else ("started" if result.get("started") else "accepted")
                if result.get("skipped"):
                    state = "skipped"
                lines.append(f"Last result: {state}.")
            else:
                lines.append(f"Last result: blocked or failed: {result.get('error') or result.get('error_code') or 'unknown error'}.")
        else:
            lines.append("Last result: pending or not sent.")
        return "\n".join(lines)

    @staticmethod
    def _mprc_chat_message_text(message: dict[str, str] | None) -> str:
        if not isinstance(message, dict):
            return ""
        return str(message.get("content") or message.get("text") or "").strip()

    def _spotify_story_music_payload_for_reply(self, assistant_text: str, *, user_text: str = "") -> dict[str, Any]:
        persona = self.current_speaker_persona() or self.active_persona()
        beat = story_director.build_visual_beat_context(
            persona=persona,
            session=self.session,
            reason="spotify_story_music",
            source_text=str(assistant_text or ""),
        )
        ar_state = getattr(self.session, "ar_state", None)
        latest_visible = str(beat.get("latest_visible_action") or "").strip()
        scene = str(
            getattr(ar_state, "current_scene", "")
            or getattr(self.session, "scene_summary", "")
            or getattr(self.session, "scene_title", "")
            or ""
        ).strip()
        location = str(beat.get("location") or getattr(self.session, "location", "") or "").strip()
        mood = self._spotify_story_music_mood(
            assistant_text,
            user_text=user_text,
            beat=beat,
        )
        music_kind = self._spotify_story_music_kind(
            assistant_text,
            user_text=user_text,
            beat=beat,
            mood=mood,
        )
        prompt, prompt_reason, prompt_persona = self._chat_play_visual_prompt_snapshot()
        query = self._spotify_story_music_query(mood, music_kind)
        payload: dict[str, Any] = {
            "event": "story_turn",
            "source": "multi_persona_roleplay",
            "mood": mood,
            "music_kind": music_kind,
            "query": query,
            "prefer_ambient": music_kind == "ambient",
            "scene": scene,
            "location": location,
            "time_of_day": str(beat.get("time_of_day") or "").strip(),
            "story_goal": str(beat.get("story_goal") or "").strip(),
            "latest_visible_beat": latest_visible,
            "visual_subject": str(beat.get("visual_subject") or "").strip(),
            "image_intent": prompt,
            "image_intent_reason": prompt_reason,
            "image_intent_persona": prompt_persona,
            "user_text": str(user_text or "").strip(),
            "reply_excerpt": self._mprc_compact(assistant_text, 600),
            "tension_level": self._spotify_story_tension_level(),
        }
        active_cast = [
            self._persona_story_label(persona)
            for persona in self.story_prompt_personas()
            if getattr(persona, "id", "")
        ]
        if active_cast:
            payload["active_cast"] = active_cast[:8]
        return payload

    def _maybe_request_spotify_story_music(self, assistant_text: str, *, user_text: str = "") -> None:
        payload = self._spotify_story_music_payload_for_reply(assistant_text, user_text=user_text)
        self._last_spotify_story_music_payload = dict(payload)
        service = self._spotify_sense_service()
        if service is None or not hasattr(service, "spotify_story_hook"):
            self._last_spotify_story_music_result = {
                "ok": True,
                "started": False,
                "skipped": True,
                "reason": "spotify_sense_unavailable",
                "message": "Spotify Sense service is not loaded.",
            }
            self._request_ui_refresh()
            return
        key = "|".join(str(payload.get(item) or "") for item in ("query", "mood", "music_kind"))
        cooldown_seconds = self._spotify_story_music_cooldown_seconds()
        now = time.time()
        if (
            key
            and key == str(getattr(self, "_last_spotify_story_music_key", "") or "")
            and now - float(getattr(self, "_last_spotify_story_music_at", 0.0) or 0.0) < cooldown_seconds
        ):
            self._last_spotify_story_music_result = {
                "ok": True,
                "started": False,
                "skipped": True,
                "reason": "cooldown",
                "query": payload.get("query"),
            }
            self._request_ui_refresh()
            return
        token = self._new_worker_token("mprc_spotify_music")
        if not token:
            return

        def worker() -> None:
            result: dict[str, Any]
            try:
                raw = service.spotify_story_hook(dict(payload))
                result = dict(raw or {}) if isinstance(raw, dict) else {"ok": False, "error": "Spotify Sense returned no result."}
            except Exception as exc:
                result = {"ok": False, "error": str(exc)}
            if not self._worker_should_emit(token):
                self._cancel_worker_token(token)
                return
            self._last_spotify_story_music_result = result
            if bool(result.get("ok")) and not bool(result.get("skipped")) and key:
                self._last_spotify_story_music_key = key
                self._last_spotify_story_music_at = time.time()
            self._finish_worker_token(token)

        if not self._start_daemon_worker(token, worker, name="nc-mprc-spotify-story-music"):
            self._cancel_worker_token(token)

    def _spotify_story_music_cooldown_seconds(self) -> float:
        try:
            return max(0.0, float(self.settings.get("spotify_story_music_cooldown_seconds", 45)))
        except Exception:
            return 45.0

    def _spotify_story_tension_level(self) -> int:
        state = getattr(self.session, "ar_state", None)
        for source in (state, self.session):
            try:
                return max(0, min(10, int(float(getattr(source, "tension_level", 0) or 0))))
            except Exception:
                continue
        return 3

    def _spotify_story_music_mood(self, assistant_text: str, *, user_text: str = "", beat: dict[str, Any] | None = None) -> str:
        beat = dict(beat or {})
        text = " ".join(
            str(item or "")
            for item in (
                assistant_text,
                user_text,
                beat.get("mood"),
                beat.get("latest_visible_action"),
                beat.get("current_scene"),
                beat.get("location"),
                beat.get("story_goal"),
                beat.get("recent_visible_events"),
            )
        ).lower()
        tension = self._spotify_story_tension_level()
        if self._spotify_story_text_has_word(text, ("battle", "chase", "attack", "dragon", "war", "explosion")) or tension >= 8:
            return "epic"
        if any(word in text for word in ("horror", "terror", "dread", "monster", "haunted", "blood")):
            return "dark"
        if any(word in text for word in ("mystery", "tense curiosity", "archive", "sigil", "sealed", "lantern", "secret", "unknown")):
            return "mystery"
        if any(word in text for word in ("sad", "grief", "loss", "lonely", "melancholy")):
            return "sad"
        if any(word in text for word in ("calm", "peaceful", "safe", "rest", "tavern", "gentle")) and tension <= 4:
            return "calm"
        if tension >= 6:
            return "mystery"
        return "fantasy"

    def _spotify_story_music_kind(
        self,
        assistant_text: str,
        *,
        user_text: str = "",
        beat: dict[str, Any] | None = None,
        mood: str = "",
    ) -> str:
        text = " ".join([assistant_text, user_text, str((beat or {}).get("latest_visible_action") or "")]).lower()
        if (
            "[music:" in text
            or self._spotify_story_text_has_word(text, ("battle", "chase", "song"))
            or "theme swells" in text
            or "music rises" in text
        ):
            return "music"
        if str(mood or "").strip().lower() == "epic" and self._spotify_story_tension_level() >= 8:
            return "music"
        return "ambient"

    @staticmethod
    def _spotify_story_music_query(mood: str, music_kind: str) -> str:
        normalized_mood = str(mood or "fantasy").strip().lower()
        normalized_kind = str(music_kind or "ambient").strip().lower()
        ambient = {
            "dark": "dark cinematic ambient story ambience",
            "mystery": "mysterious cinematic ambient story ambience",
            "epic": "epic fantasy adventure story ambience",
            "calm": "calm cinematic fantasy story ambience",
            "sad": "melancholy cinematic ambient story ambience",
            "fantasy": "cinematic fantasy story ambience",
        }
        music = {
            "dark": "dark cinematic story music",
            "mystery": "mysterious cinematic story music",
            "epic": "epic fantasy adventure story music",
            "calm": "calm fantasy story music",
            "sad": "melancholy orchestral story music",
            "fantasy": "cinematic fantasy story music",
        }
        return (music if normalized_kind == "music" else ambient).get(
            normalized_mood,
            "cinematic fantasy story music" if normalized_kind == "music" else "cinematic fantasy story ambience",
        )

    @staticmethod
    def _spotify_story_text_has_word(text: str, words: tuple[str, ...]) -> bool:
        haystack = str(text or "").lower()
        for word in words:
            needle = str(word or "").strip().lower()
            if needle and re.search(rf"\b{re.escape(needle)}\b", haystack):
                return True
        return False

    def _latest_mprc_story_reply_text(self) -> str:
        latest = str(getattr(self, "_remote_latest_reply_text", "") or "").strip()
        if latest:
            return latest
        for message in reversed(list(getattr(self, "_mprc_chat_history", []) or [])):
            if not isinstance(message, dict):
                continue
            if str(message.get("role") or "").strip().lower() == "assistant":
                content = str(message.get("content") or "").strip()
                if content:
                    return content
        return ""

    def _chat_play_visual_prompt_snapshot(self) -> tuple[str, str, str]:
        raw = str(getattr(self, "_debug_visual_prompt", "") or "").strip()
        if raw.startswith("{"):
            try:
                payload = json.loads(raw)
            except Exception:
                payload = {}
            if isinstance(payload, dict):
                prompt = str(payload.get("prompt") or payload.get("final_prompt") or payload.get("image_prompt") or "").strip()
                reason = str(payload.get("reason") or "").strip()
                persona_id = str(payload.get("persona_id") or payload.get("visual_subject") or "").strip()
                return self._mprc_compact(prompt, 260), self._mprc_compact(reason, 80), self._mprc_compact(persona_id, 80)
        debug = str(getattr(self, "_chat_visual_prompt_debug", "") or "").strip()
        if debug:
            one_line = self._mprc_compact(debug, 260)
            return one_line, "", ""
        return "", "", ""

    @staticmethod
    def _mprc_story_reply_tagged_speakers(text: str) -> list[str]:
        speakers: list[str] = []
        for match in re.finditer(r"\[(NARRATOR|CHARACTER\s*:\s*([^\]]+))\]", str(text or ""), flags=re.IGNORECASE):
            raw = match.group(2) if match.group(2) is not None else match.group(1)
            speaker = re.sub(r"\s+", " ", str(raw or "")).strip()
            if speaker.lower() == "narrator":
                speaker = "Narrator"
            if speaker and speaker not in speakers:
                speakers.append(speaker)
        return speakers

    def _refresh_chat_play_state_sidebar(self):
        active = self.active_persona()
        speaker = self.current_speaker_persona()
        ar_state = self.session.ar_state
        scene = str(ar_state.current_scene or self.session.scene_title or "Untitled scene").strip()
        location = str(ar_state.location or self.session.location or "Unknown location").strip()
        time_of_day = str(ar_state.time_of_day or self.session.time_of_day or "").strip()
        mood = str(ar_state.mood or self.session.mood or "").strip()
        objective = str(ar_state.story_goal or self.session.objective or "").strip()
        scene_lines = [
            f"Scene: {scene}",
            f"Location: {location}",
        ]
        if time_of_day:
            scene_lines.append(f"Time: {time_of_day}")
        if mood:
            scene_lines.append(f"Mood: {mood}")
        if objective:
            scene_lines.append(f"Objective: {objective}")
        scene_label = self._controls.get("chat_scene_state")
        if scene_label is not None and hasattr(scene_label, "setText"):
            scene_label.setText("\n".join(scene_lines))
        speaker_label = self._controls.get("chat_active_speaker")
        if speaker_label is not None and hasattr(speaker_label, "setText"):
            speaker_text = speaker.display_name if speaker is not None else "none"
            if active is not None and speaker is not None and active.id != speaker.id:
                speaker_text += f" (active persona: {active.display_name})"
            speaker_label.setText(f"Active speaker: {speaker_text}")

        active_ids = [normalize_persona_id(item) for item in list(ar_state.active_characters or []) if str(item or "").strip()]
        present = []
        if active_ids:
            for persona_id in active_ids:
                persona = self.persona_by_id(persona_id)
                present.append(self._persona_story_label(persona) if persona is not None else persona_id)
        else:
            for persona in self.personas:
                if persona.enabled:
                    present.append(self._persona_story_label(persona))
        self._set_list_items(
            self._controls.get("chat_present_characters"),
            present[:8],
            empty_text="No present characters marked.",
        )

        events = list(ar_state.recent_events or self.session.recent_events or [])
        self._set_list_items(
            self._controls.get("chat_recent_events"),
            [str(item) for item in events[-6:]],
            empty_text="No recent story events yet.",
        )

        choices = [str(item) for item in list(ar_state.pending_choices or []) if str(item or "").strip()]
        if not choices and self._mprc_chat_should_offer_choices():
            if objective:
                choices.append(f"Pursue objective: {objective}")
            choices.extend(["Ask the active speaker", "Investigate the scene", "Direct the pacing or tone"])
        self._set_list_items(
            self._controls.get("chat_next_actions"),
            choices[:6],
            empty_text="" if not self._mprc_chat_should_offer_choices() else "No suggested next actions yet.",
        )
        self._refresh_chat_play_story_engine_cards()

    def _refresh_narrator_selector(self):
        combo = self._controls.get("narrator_persona")
        if combo is None:
            return
        mode = self._narrator_selection_mode()
        selected = self._stored_narrator_persona_id() if mode == "explicit" else ""
        auto = self._auto_ar_narrator_persona()
        combo.blockSignals(True)
        combo.clear()
        auto_label = "Auto narrator"
        if auto is not None:
            auto_label = f"Auto narrator ({auto.display_name})"
        combo.addItem(auto_label, "")
        combo.setItemData(
            0,
            "Automatically choose the best narrator persona for AR. Use an explicit persona below to lock [NARRATOR] to one voice.",
            QtCore.Qt.ToolTipRole,
        )
        for persona in self._ordered_narrator_selector_personas():
            label = self._persona_voice_selector_label(persona)
            if self._persona_looks_like_narrator(persona) and not self._persona_is_master_narrator(persona):
                label += " [Narrator]"
            combo.addItem(label, persona.id)
            combo.setItemData(
                combo.count() - 1,
                f"Use {persona.display_name} for [NARRATOR] voice routing.",
                QtCore.Qt.ToolTipRole,
            )
        index = combo.findData(selected)
        combo.setCurrentIndex(max(0, index))
        combo.blockSignals(False)

    def _voice_follows_active(self) -> bool:
        return bool(self.settings.get("voice_follow_active_persona", True))

    def _stored_voice_persona_id(self) -> str:
        if self._voice_follows_active():
            active = self.active_persona()
            return active.id if active is not None else ""
        wanted = normalize_persona_id(self.settings.get("voice_edit_persona_id", ""))
        if wanted and any(persona.id == wanted for persona in self.personas):
            return wanted
        active = self.active_persona()
        return active.id if active is not None else ""

    def _selected_voice_persona(self) -> PersonaConfig | None:
        wanted = self._stored_voice_persona_id()
        return self.persona_by_id(wanted) if wanted else self.active_persona()

    def _refresh_voice_persona_selector(self):
        combo = self._controls.get("voice_persona")
        if combo is None:
            return
        follow = self._voice_follows_active()
        follow_widget = self._controls.get("voice_follow_active")
        if follow_widget is not None and hasattr(follow_widget, "setChecked"):
            follow_widget.blockSignals(True)
            follow_widget.setChecked(follow)
            follow_widget.blockSignals(False)
        combo.setEnabled(not follow)
        selected = self._stored_voice_persona_id()
        combo.blockSignals(True)
        combo.clear()
        narrator_id = self.selected_narrator_persona_id()
        for persona in self._ordered_voice_selector_personas():
            label = self._persona_voice_selector_label(persona)
            if persona.id == narrator_id:
                label += " [AR narrator]"
            combo.addItem(label, persona.id)
            combo.setItemData(
                combo.count() - 1,
                f"Edit voice settings for {persona.display_name}.",
                QtCore.Qt.ToolTipRole,
            )
        index = combo.findData(selected)
        combo.setCurrentIndex(max(0, index))
        combo.blockSignals(False)
        self._update_voice_target_label()

    def _update_voice_target_label(self):
        label = self._controls.get("voice_current_persona")
        if label is None or not hasattr(label, "setText"):
            return
        persona = self._selected_voice_persona()
        if persona is None:
            label.setText("No persona selected.")
            return
        mode = "following active persona" if self._voice_follows_active() else "manual voice selection"
        active_note = "active" if persona.id == self.session.active_persona_id else "not active"
        sample = str(getattr(persona.voice, "sample_path", "") or "").strip()
        sample_note = Path(sample).name if sample else "no voice sample"
        label.setText(f"{persona.display_name} ({persona.id}) - {mode}, {active_note}, {sample_note}")

    def _persona_story_label(self, persona: PersonaConfig) -> str:
        label = str(persona.display_name or persona.id).strip() or persona.id
        master_number = self._master_narrator_number(persona)
        if master_number:
            label += f" #{master_number} [Master Narrator]"
        linked = self._master_story_linked_persona_ids()
        created = self._master_story_created_persona_ids()
        auto_chat = self._chat_auto_created_persona_ids()
        if persona.id in auto_chat:
            label += " [Auto Chat]"
        elif persona.id == self.session.active_persona_id and persona.id in linked:
            label += " [Active Story]"
        elif persona.id in created:
            label += " [New Story]"
        elif persona.id in linked:
            label += " [Story]"
        return label

    def _persona_voice_selector_label(self, persona: PersonaConfig) -> str:
        label = str(persona.display_name or persona.id).strip() or persona.id
        master_number = self._master_narrator_number(persona)
        if master_number:
            return f"{label} #{master_number} ({persona.id} #{master_number}) [Master Narrator]"
        return f"{label} ({persona.id})"

    def _persona_story_tooltip(self, persona: PersonaConfig) -> str:
        pieces = [f"{persona.display_name} ({persona.id})"]
        master_number = self._master_narrator_number(persona)
        if master_number:
            pieces.append(f"Master narrator #{master_number}. Protected from deletion and prioritized for narrator voice selection.")
        if persona.id in self._chat_auto_created_persona_ids():
            pieces.append("Auto-created from a [CHARACTER: Name] tag in the active chat. Edit this persona to add voice, prompts, and pictures.")
        if persona.id in self._master_story_linked_persona_ids():
            title = str(self.settings.get("last_master_story_title") or self.settings.get("last_master_story_id") or "current Master Story").strip()
            pieces.append(f"Linked to {title}.")
        if persona.id in self._master_story_created_persona_ids():
            pieces.append("Created by the current Master Story apply/load action.")
        if persona.character_image_path:
            pieces.append(f"Character picture: {persona.character_image_path}")
        return "\n".join(pieces)

    def _master_story_linked_persona_ids(self) -> set[str]:
        raw = self.settings.get("master_story_linked_persona_ids")
        if not isinstance(raw, list):
            return set()
        return {normalize_persona_id(item) for item in raw if str(item or "").strip()}

    def _master_story_created_persona_ids(self) -> set[str]:
        raw = self.settings.get("master_story_created_persona_ids")
        if not isinstance(raw, list):
            return set()
        return {normalize_persona_id(item) for item in raw if str(item or "").strip()}

    def _populate_editor(self, persona: PersonaConfig):
        widgets = self._controls
        widgets["persona_id"].setText(persona.id)
        widgets["persona_enabled"].setChecked(bool(persona.enabled))
        widgets["master_narrator"].setChecked(self._persona_is_master_narrator(persona))
        widgets["display_name"].setText(persona.display_name)
        widgets["role"].setText(persona.role)
        widgets["description"].setPlainText(persona.description)
        widgets["character_image_path"].setText(persona.character_image_path)
        self._set_image_label(widgets.get("character_image"), persona.character_image_path, fallback_text="No picture")
        widgets["system_prompt"].setPlainText(persona.system_prompt)
        widgets["ar_profile_enabled"].setChecked(bool(persona.ar_profile_enabled))
        widgets["ar_description"].setPlainText(persona.ar_description)
        widgets["ar_system_prompt"].setPlainText(persona.ar_system_prompt)
        widgets["speaking_style"].setText(persona.speaking_style)
        widgets["allowed_tone"].setText(persona.allowed_tone)
        widgets["response_length"].setCurrentText(persona.response_length)
        widgets["temperature_hint"].setText(persona.temperature_hint)
        widgets["memory_scope"].setCurrentText(persona.memory_scope)
        widgets["behavior_mode"].setCurrentText(persona.behavior_mode)
        widgets["tags"].setText(", ".join(persona.tags))

    def _populate_voice(self, persona: PersonaConfig):
        voice = persona.voice
        self._controls["voice_enabled"].setChecked(voice.enabled)
        self._controls["voice_backend"].setCurrentText(voice.backend)
        self._controls["voice_sample"].setText(voice.sample_path)
        self._sync_voice_sample_picker(voice.sample_path)
        self._controls["voice_preset"].setText(voice.preset_name)
        self._controls["voice_language"].setCurrentText(voice.language if voice.language else "")
        self._update_voice_target_label()
        self._update_voice_warning()

    def _populate_visual(self, persona: PersonaConfig):
        visual = persona.visual
        self._controls["visual_enabled"].setChecked(visual.enabled)
        mode_combo = self._controls["visual_mode"]
        mode_index = mode_combo.findData(visual.mode)
        if mode_index < 0:
            mode_index = mode_combo.findText(visual.mode)
        mode_combo.setCurrentIndex(max(0, mode_index))
        self._controls["visual_provider"].setCurrentText(visual.provider)
        self._controls["visual_model"].setText(visual.model)
        self._controls["visual_size"].setCurrentText(visual.size)
        index = self._controls["visual_style"].findData(visual.style_preset)
        self._controls["visual_style"].setCurrentIndex(max(0, index))
        self._controls["visual_character"].setPlainText(visual.character_description)
        self._controls["visual_clothing"].setText(visual.clothing_props)
        self._controls["visual_environment"].setText(visual.environment_style)
        self._controls["visual_negative"].setText(visual.negative_prompt)
        self._controls["visual_continuity"].setChecked(visual.keep_continuity)
        appearance_combo = self._controls.get("visual_appearance_freedom")
        if appearance_combo is not None:
            appearance_combo.setCurrentIndex(max(0, appearance_combo.findData(visual.appearance_freedom)))
        self._controls["visual_scene"].setChecked(visual.include_scene_summary)
        self._controls["visual_speaker"].setChecked(visual.include_active_speaker)
        self._controls["visual_interval"].setValue(visual.auto_reply_interval)
        self._controls["visual_cooldown"].setValue(visual.cooldown_seconds)
        self._controls["visual_max_auto"].setValue(visual.max_auto_images_per_session)
        self._controls["visual_auto_show"].setChecked(visual.auto_show_dock)
        self._update_visual_mode_note()

    def _update_visual_mode_note(self):
        label = self._controls.get("visual_mode_note")
        combo = self._controls.get("visual_mode")
        if label is None or combo is None:
            return
        mode = str(combo.currentData() or combo.currentText() or "off").strip()
        label.setText(VISUAL_MODE_DESCRIPTIONS.get(mode, "Controls when this persona can request Visual Reply story images."))

    def _update_session_mode_note(self, mode: str | None = None) -> None:
        label = self._controls.get("session_mode_note")
        combo = self._controls.get("session_mode")
        if label is None:
            return
        selected = str(mode or "").strip()
        if not selected and combo is not None and hasattr(combo, "currentText"):
            selected = str(combo.currentText() or "").strip()
        label.setText(SESSION_MODE_DESCRIPTIONS.get(selected, "Choose how personas, narration, and story direction are framed for the current scene."))

    def _populate_session(self):
        c = self._controls
        c["session_mode"].setCurrentText(self.session.mode)
        self._update_session_mode_note(self.session.mode)
        c["scene_title"].setText(self.session.scene_title)
        c["location"].setText(self.session.location)
        c["time_of_day"].setText(self.session.time_of_day)
        c["mood"].setText(self.session.mood)
        c["objective"].setText(self.session.objective)
        c["scene_summary"].setPlainText(self.session.scene_summary)
        c["auto_select"].setChecked(self.session.auto_select_speaker)
        c["continuity"].setChecked(self.session.keep_scene_continuity)
        c["update_scene"].setChecked(self.session.update_scene_after_reply)
        roster = "\n".join(f"{persona.display_name} ({persona.id}) - {persona.behavior_mode}" for persona in self.personas if persona.enabled)
        c["roster"].setPlainText(roster)

    def _populate_ar(self):
        c = self._controls
        state = self.session.ar_state
        c["ar_enabled"].setChecked(self.session.mode == AR_MODE)
        c["ar_use_persona_profiles"].setChecked(bool(self.session.ar_use_persona_profiles))
        c["ar_pacing"].setCurrentText(self.session.ar_pacing)
        c["ar_interaction"].setCurrentText(self.session.ar_interaction_frequency)
        c["ar_dialogue_density"].setCurrentText(self.session.ar_dialogue_density)
        c["ar_tension"].setValue(int(state.tension_level or 0))
        c["ar_current_scene"].setText(state.current_scene)
        c["ar_location"].setText(state.location)
        c["ar_time_of_day"].setText(state.time_of_day)
        c["ar_mood"].setText(state.mood)
        c["ar_story_goal"].setText(state.story_goal)
        c["ar_active_characters"].setText(", ".join(state.active_characters))
        c["ar_player_intent"].setText(state.player_intent)
        c["ar_pending_choices"].setPlainText("\n".join(state.pending_choices))
        c["ar_recent_events"].setPlainText("\n".join(state.recent_events))

    def _populate_audio(self):
        c = self._controls
        if "audio_story_sounds" not in c:
            return
        c["audio_story_sounds"].setChecked(self.story_sounds_enabled())
        if "audiofx_volume" in c:
            volume = self._audiofx_volume_percent()
            c["audiofx_volume"].blockSignals(True)
            c["audiofx_volume"].setValue(volume)
            c["audiofx_volume"].blockSignals(False)
            if "audiofx_volume_value" in c:
                c["audiofx_volume_value"].setText(f"{volume}%")
            self._apply_audiofx_volume()
        if "audiofx_test_mode" in c:
            c["audiofx_test_mode"].setChecked(bool(self.settings.get("audiofx_test_mode", False)))
        c["audio_sound_description"].setPlainText(str(self.settings.get("audio_prompt_description") or ""))
        audio_type = str(self.settings.get("audio_prompt_type") or "Auto").strip()
        c["audio_type"].setCurrentText(audio_type if audio_type in AUDIO_TYPES else "Auto")
        c["audio_prompt_output"].setPlainText(str(self.settings.get("audio_prompt_output") or ""))
        self._populate_audio_saved_prompts()
        self._populate_audiofx_items()

    def _saved_audio_prompts(self) -> list[dict[str, str]]:
        saved = self.settings.get("saved_audio_prompts")
        if not isinstance(saved, list):
            return []
        prompts: list[dict[str, str]] = []
        for item in saved:
            if not isinstance(item, dict):
                continue
            prompt = str(item.get("prompt") or "").strip()
            if not prompt:
                continue
            prompts.append({
                "created_at": str(item.get("created_at") or "").strip(),
                "type": str(item.get("type") or "Auto").strip() or "Auto",
                "description": str(item.get("description") or "").strip(),
                "prompt": prompt,
            })
        return prompts

    def _populate_audio_saved_prompts(self) -> None:
        self._native_audio_saved_prompts = [
            {
                **dict(item),
                "index": index,
                "label": self._audio_saved_prompt_label(item, index),
            }
            for index, item in enumerate(self._saved_audio_prompts())
        ]
    def _audio_saved_prompt_label(self, item: dict[str, str], index: int) -> str:
        audio_type = str(item.get("type") or "Auto").strip() or "Auto"
        description = str(item.get("description") or "").strip()
        prompt = str(item.get("prompt") or "").strip()
        title = description or prompt
        title = title.replace("\r", " ").replace("\n", " ")
        while "  " in title:
            title = title.replace("  ", " ")
        if len(title) > 86:
            title = title[:83].rstrip() + "..."
        return f"{index + 1}. [{audio_type}] {title}"

    def _selected_audio_prompt_index(self) -> int:
        saved_list = self._controls.get("audio_saved_prompts")
        if saved_list is None:
            return -1
        item = saved_list.currentItem()
        if item is None:
            return -1
        try:
            return int(item.data(32))
        except Exception:
            return -1

    def _update_audio_saved_buttons(self):
        selected = self._selected_audio_prompt_index() >= 0
        for key in ("audio_load_saved", "audio_delete_saved"):
            button = self._controls.get(key)
            if button is not None:
                button.setEnabled(selected)

    def _audiofx_items(self) -> list[dict[str, str]]:
        raw = self.settings.get("audio_fx_items")
        if not isinstance(raw, list):
            return []
        items: list[dict[str, str]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            description = str(item.get("description") or "").strip()
            prompt = str(item.get("prompt") or "").strip()
            file_path = str(item.get("file_path") or "").strip()
            if not description and not prompt and not file_path:
                continue
            items.append({
                "id": str(item.get("id") or "").strip() or self._new_audiofx_id(items),
                "type": str(item.get("type") or "Auto").strip() or "Auto",
                "description": description,
                "prompt": prompt,
                "file_path": file_path,
                "created_at": str(item.get("created_at") or "").strip(),
                "updated_at": str(item.get("updated_at") or "").strip(),
            })
        return items

    def _available_audio_files(self) -> list[dict[str, Any]]:
        raw = self.settings.get("available_audio_files")
        if not isinstance(raw, list):
            return []
        files: list[dict[str, Any]] = []
        seen_paths: set[str] = set()
        for item in raw:
            if not isinstance(item, dict):
                continue
            file_path = str(item.get("file_path") or "").strip()
            if not file_path:
                continue
            path_key = self._audio_file_key(file_path)
            if path_key in seen_paths:
                continue
            seen_paths.add(path_key)
            files.append({
                "id": str(item.get("id") or "").strip() or self._audio_cue_id_from_path(file_path),
                "type": str(item.get("type") or "Audio").strip() or "Audio",
                "description": str(item.get("description") or "").strip(),
                "prompt": str(item.get("prompt") or "").strip(),
                "file_path": file_path,
                "file_name": str(item.get("file_name") or "").strip() or Path(file_path).name,
                "source": str(item.get("source") or "manual").strip() or "manual",
                "source_audiofx_id": str(item.get("source_audiofx_id") or "").strip(),
                "ready": bool(file_path and Path(file_path).exists()),
                "created_at": str(item.get("created_at") or "").strip(),
                "updated_at": str(item.get("updated_at") or "").strip(),
            })
        return files

    def _audiofx_available_entry(self, item: dict[str, str]) -> dict[str, Any] | None:
        file_path = str(item.get("file_path") or "").strip()
        if not file_path:
            return None
        path = Path(file_path)
        if not path.exists():
            return None
        cue_id = str(item.get("id") or "").strip() or self._audio_cue_id_from_path(file_path)
        return {
            "id": cue_id,
            "type": str(item.get("type") or "Audio").strip() or "Audio",
            "description": str(item.get("description") or "").strip(),
            "prompt": str(item.get("prompt") or "").strip(),
            "file_path": str(path.resolve()),
            "file_name": path.name,
            "source": "audiofx",
            "source_audiofx_id": cue_id,
            "ready": True,
            "created_at": str(item.get("created_at") or "").strip(),
            "updated_at": str(item.get("updated_at") or "").strip(),
        }

    def _sync_available_audio_database(self, items: list[dict[str, str]] | None = None, *, persist: bool = True) -> list[dict[str, Any]]:
        items = list(items if items is not None else self._audiofx_items())
        existing = self._available_audio_files()
        audiofx_ids = {str(item.get("id") or "").strip() for item in items}
        merged: list[dict[str, Any]] = []
        by_path: dict[str, dict[str, Any]] = {}

        for entry in existing:
            if entry.get("source") == "audiofx" and str(entry.get("source_audiofx_id") or "") not in audiofx_ids:
                continue
            key = self._audio_file_key(entry.get("file_path", ""))
            if key:
                by_path[key] = dict(entry)

        for item in items:
            entry = self._audiofx_available_entry(item)
            if entry is None:
                continue
            by_path[self._audio_file_key(entry["file_path"])] = entry

        for key in sorted(by_path):
            merged.append(by_path[key])
        if persist:
            self.settings["available_audio_files"] = merged
        return merged

    def _audio_file_key(self, file_path: str) -> str:
        raw = str(file_path or "").strip()
        if not raw:
            return ""
        try:
            return str(Path(raw).resolve()).lower()
        except Exception:
            return raw.lower()

    def strip_story_audio_for_tts(self, text: str, *, streaming: bool = False, collect_cues: bool = False):
        """Remove non-spoken story audio cues and optionally defer playback."""
        collected_cues: list[str] = []

        def handle_cues(cue_text: str, *, warn_unmatched: bool = False) -> bool:
            if not collect_cues:
                return self._trigger_story_audio_cues(cue_text, warn_unmatched=warn_unmatched)
            cue_ids = self._story_audio_cue_ids(cue_text)
            if not cue_ids:
                if warn_unmatched:
                    logger = getattr(self.context, "logger", None)
                    if logger is not None:
                        logger.warning("[AR_MODE] Ignored unmatched ambience tag: %s", str(cue_text or "").strip()[:160])
                return False
            seen = {str(cue_id).lower() for cue_id in collected_cues}
            for cue_id in cue_ids:
                key = str(cue_id).lower()
                if key not in seen:
                    collected_cues.append(cue_id)
                    seen.add(key)
            return True

        original = str(text or "")
        if not original:
            return ("", False, collected_cues) if collect_cues else ("", False)
        if streaming:
            original = self._story_audio_pending_text + original
            self._story_audio_pending_text = ""
            original, pending = self._split_pending_story_audio_tag(original)
            if pending:
                self._story_audio_pending_text = pending
                if not original.strip():
                    return ("", True, collected_cues) if collect_cues else ("", True)
        else:
            self._story_audio_pending_text = ""
        lines = original.splitlines()
        cleaned: list[str] = []
        changed = False
        in_audio_block = bool(self._story_audio_block_active) if streaming else False

        for raw_line in lines:
            line = str(raw_line or "")
            audio_command = re.match(r"^\s*\[(AMBIENCE|AMBIENT|MUSIC|FX|SFX|STINGER|AUDIO|SOUND)(?:\s*:\s*([^\]]+))?\]\s*(.*)$", line, re.IGNORECASE)
            section = re.match(r"^\s*\[(NARRATOR|CHOICES)\]\s*(.*)$", line, re.IGNORECASE)
            character = re.match(r"^\s*\[CHARACTER\s*:\s*([^\]]+)\]\s*(.*)$", line, re.IGNORECASE)
            if audio_command:
                changed = True
                cue_name = str(audio_command.group(2) or "").strip()
                body = str(audio_command.group(3) or "").strip()
                handle_cues(" ".join(part for part in (cue_name, body) if part), warn_unmatched=bool(cue_name))
                in_audio_block = not bool(cue_name)
                continue
            if section:
                label = section.group(1).strip().upper()
                in_audio_block = False
                cleaned.append(line)
                continue
            if character:
                in_audio_block = False
                cleaned.append(line)
                continue
            if in_audio_block:
                cue_ids = self._story_audio_cue_ids(line)
                if cue_ids or not line.strip():
                    changed = True
                    handle_cues(line)
                    continue
                if line.lstrip().startswith(("*", "-", "•")) and re.search(r"\b(?:file|ready|ambience|ambient|music|stinger|fx|sfx|audiofx|audio|sound)\b", line, re.IGNORECASE):
                    changed = True
                    handle_cues(line)
                    continue
                in_audio_block = False
            stripped = self._strip_inline_story_audio_cues(line, collected_cues=collected_cues if collect_cues else None)
            if stripped != line:
                changed = True
                if stripped.strip():
                    cleaned.append(stripped)
                continue
            cleaned.append(line)

        if streaming:
            self._story_audio_block_active = in_audio_block
        else:
            self._story_audio_block_active = False
        cleaned_text = "\n".join(cleaned).strip()
        return (cleaned_text, changed, collected_cues) if collect_cues else (cleaned_text, changed)

    @staticmethod
    def _split_pending_story_audio_tag(text: str) -> tuple[str, str]:
        value = str(text or "")
        start = value.rfind("[")
        if start < 0:
            return value, ""
        tail = value[start:]
        if "]" in tail:
            return value, ""
        if re.match(r"^\[(?:A|AM|AMB|AMBI|AMBIEN|AMBIENC|AMBIENCE|AMBIENT|M|MU|MUS|MUSI|MUSIC|F|FX|S|SF|SFX|ST|STI|STIN|STING|STINGE|STINGER|SO|SOU|SOUN|SOUND|AU|AUD|AUDI|AUDIO)(?:\s*:\s*)?[^\]]*$", tail, re.IGNORECASE):
            return value[:start], tail
        return value, ""

    def play_story_audio_from_reply(self, text: str) -> int:
        """Scan a complete assistant reply for audio tags missed by streaming chunks."""
        played = 0
        for cue_text in re.findall(r"\[(?:AMBIENCE|AMBIENT|MUSIC|FX|SFX|STINGER|AUDIO|SOUND)\s*:\s*([^\]]+)\]", str(text or ""), re.IGNORECASE):
            if self._trigger_story_audio_cues(cue_text, warn_unmatched=True):
                played += 1
        return played

    def play_story_audio_cue_ids(self, cue_ids: list[str] | tuple[str, ...] | set[str]) -> int:
        played = 0
        for cue_id in list(cue_ids or []):
            if self._play_story_audio_cue(str(cue_id or "")):
                played += 1
        return played

    def _strip_inline_story_audio_cues(self, line: str, *, collected_cues: list[str] | None = None) -> str:
        text = str(line or "")
        cue_ids = self._story_audio_cue_ids(text)
        if not cue_ids:
            return text
        if collected_cues is None:
            for cue_id in cue_ids:
                self._play_story_audio_cue(cue_id)
        else:
            seen = {str(cue_id).lower() for cue_id in collected_cues}
            for cue_id in cue_ids:
                key = str(cue_id).lower()
                if key not in seen:
                    collected_cues.append(cue_id)
                    seen.add(key)
        stripped = text
        for cue_id in cue_ids:
            stripped = re.sub(rf"[\*\s\-\u2022]*{re.escape(cue_id)}\s*:?.*$", "", stripped, flags=re.IGNORECASE)
        return stripped.strip(" \t*-")

    def _story_audio_cue_ids(self, text: str) -> list[str]:
        entries = self._story_audio_entries()
        known: dict[str, str] = {}
        for entry in entries:
            for key in ("id", "source_audiofx_id"):
                value = str(entry.get(key) or "").strip()
                if value:
                    known[value.lower()] = value
        found: list[str] = []
        seen: set[str] = set()
        for match in re.finditer(r"\b(?:audiofx|audio)[_-][A-Za-z0-9_:-]{3,}\b", str(text or ""), re.IGNORECASE):
            raw = match.group(0).strip().rstrip(".,;:*)]")
            key = raw.lower()
            cue_id = known.get(key)
            if cue_id and cue_id.lower() not in seen:
                found.append(cue_id)
                seen.add(cue_id.lower())
        if found:
            return found
        cue_id = self._story_audio_cue_id_for_query(text, entries)
        if cue_id:
            found.append(cue_id)
        return found

    def _story_audio_cue_id_for_query(self, query: str, entries: list[dict[str, Any]]) -> str:
        wanted = self._audio_match_key(query)
        wanted_tokens = self._audio_match_tokens(query)
        if not wanted and not wanted_tokens:
            return ""
        scored: list[tuple[float, str]] = []
        for entry in entries:
            if not bool(entry.get("ready", True)):
                continue
            cue_id = str(entry.get("id") or entry.get("source_audiofx_id") or "").strip()
            if not cue_id:
                continue
            labels = [
                entry.get("id"),
                entry.get("source_audiofx_id"),
                entry.get("description"),
                entry.get("file_name"),
                Path(str(entry.get("file_name") or "")).stem,
                entry.get("prompt"),
                entry.get("type"),
            ]
            best = 0.0
            for label in labels:
                label_text = str(label or "").strip()
                label_key = self._audio_match_key(label_text)
                label_tokens = self._audio_match_tokens(label_text)
                if not label_key and not label_tokens:
                    continue
                if wanted and label_key and wanted == label_key:
                    best = max(best, 100.0)
                elif wanted and label_key and (wanted in label_key or label_key in wanted):
                    best = max(best, 88.0)
                elif wanted_tokens and label_tokens:
                    overlap = len(wanted_tokens & label_tokens)
                    if overlap:
                        if wanted_tokens <= label_tokens or label_tokens <= wanted_tokens:
                            best = max(best, 82.0 + min(8.0, overlap))
                        else:
                            best = max(best, 70.0 * (overlap / max(1, len(wanted_tokens | label_tokens))))
            if best >= 60.0:
                scored.append((best, cue_id))
        if not scored:
            return ""
        scored.sort(key=lambda item: item[0], reverse=True)
        if len(scored) > 1 and scored[0][0] == scored[1][0]:
            return ""
        return scored[0][1]

    @staticmethod
    def _audio_match_key(value: Any) -> str:
        text = str(value or "").lower()
        text = re.sub(r"^\s*\[?ambience\s*:?", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(?:file|ready|missing|prompt|description|status)\b", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"\.[a-z0-9]{2,5}\b", " ", text)
        return re.sub(r"[^a-z0-9]+", " ", text).strip()

    @classmethod
    def _audio_match_tokens(cls, value: Any) -> set[str]:
        stop = {"ambience", "ambient", "audio", "sound", "file", "ready", "missing", "prompt", "description", "status"}
        return {
            token
            for token in cls._audio_match_key(value).split()
            if len(token) >= 3 and token not in stop
        }

    def _trigger_story_audio_cues(self, text: str, *, warn_unmatched: bool = False) -> bool:
        cue_ids = self._story_audio_cue_ids(text)
        if not cue_ids:
            if warn_unmatched:
                logger = getattr(self.context, "logger", None)
                if logger is not None:
                    logger.warning("[AR_MODE] Ignored unmatched ambience tag: %s", str(text or "").strip()[:160])
                self._record_story_event(
                    f"sound skipped: no matching AudioFX for '{str(text or '').strip()[:120]}'",
                    severity="warning",
                    kind="audiofx",
                    persist=True,
                )
            return False
        for cue_id in cue_ids:
            self._play_story_audio_cue(cue_id)
        return True

    def _play_story_audio_cue(self, cue_id: str) -> bool:
        logger = getattr(self.context, "logger", None)
        if not self.story_sounds_enabled():
            if logger is not None:
                logger.info("[AR_MODE] Story Sounds disabled; skipped AudioFX cue %s", cue_id)
            self._record_story_event(f"sound skipped: Story Sounds disabled for {cue_id}", severity="info", kind="audiofx", persist=True)
            return False
        entry = self._story_audio_entry(cue_id)
        if entry is None:
            if logger is not None:
                logger.warning("[AR_MODE] AudioFX cue was requested but not ready: %s", cue_id)
            self._record_story_event(f"sound skipped: no matching ready AudioFX for {cue_id}", severity="warning", kind="audiofx", persist=True)
            return False
        now = time.monotonic()
        cue_key = str(entry.get("id") or cue_id).lower()
        with self._state_lock:
            if self._shutting_down:
                return False
            if now - float(self._last_story_audio_cues.get(cue_key, 0.0) or 0.0) < 1.5:
                self._record_story_event(f"sound skipped: cooldown for {cue_key}", severity="info", kind="audiofx", persist=False)
                return True
            self._last_story_audio_cues[cue_key] = now
        try:
            bridge = getattr(self, "_story_audio_bridge", None)
            if bridge is None:
                return False
            bridge.play_requested.emit(dict(entry))
            if logger is not None:
                logger.info("[AR_MODE] Queued story AudioFX cue %s: %s", entry.get("id") or cue_id, entry.get("file_path") or "")
            return True
        except RuntimeError as exc:
            self._record_story_event(f"sound skipped: playback bridge unavailable for {cue_id}: {exc}", severity="warning", kind="audiofx", persist=True)
            return False

    def _story_audio_entry(self, cue_id: str) -> dict[str, Any] | None:
        wanted = str(cue_id or "").strip().lower()
        if not wanted:
            return None
        for entry in self._story_audio_entries():
            ids = {
                str(entry.get("id") or "").strip().lower(),
                str(entry.get("source_audiofx_id") or "").strip().lower(),
            }
            file_path = str(entry.get("file_path") or "").strip()
            if wanted in ids and file_path and Path(file_path).exists():
                return dict(entry)
        return None

    def _story_audio_entries(self) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        seen: set[str] = set()
        for entry in self.available_story_audio_files():
            if not isinstance(entry, dict):
                continue
            key = self._audio_file_key(entry.get("file_path", "")) or str(entry.get("id") or "").lower()
            if key and key not in seen:
                entries.append(dict(entry))
                seen.add(key)
        for item in self._audiofx_items():
            entry = self._audiofx_available_entry(item)
            if entry is None:
                continue
            key = self._audio_file_key(entry.get("file_path", "")) or str(entry.get("id") or "").lower()
            if key and key not in seen:
                entries.append(entry)
                seen.add(key)
        return entries

    def _audio_cue_id_from_path(self, file_path: str) -> str:
        name = Path(str(file_path or "audio")).stem.lower()
        cue = []
        previous = False
        for char in name:
            if char.isalnum():
                cue.append(char)
                previous = False
            elif not previous:
                cue.append("_")
                previous = True
        text = "".join(cue).strip("_") or "audio"
        return f"audio_{text[:48]}"

    def _save_audiofx_items(self, items: list[dict[str, str]]) -> None:
        self.settings["audio_fx_items"] = [dict(item) for item in list(items or [])]
        self._sync_available_audio_database(items)
        self.storage.save_settings(self.settings)

    def _populate_audiofx_items(self) -> None:
        entries: list[dict[str, Any]] = []
        for index, item in enumerate(self._audiofx_items()):
            ready = self._audiofx_file_ready(item)
            entries.append(
                {
                    **dict(item),
                    "index": index,
                    "ready": bool(ready),
                    "label": self._audiofx_label(item, index, ready),
                    "tooltip": self._audiofx_tooltip(item, ready),
                }
            )
        self._native_audiofx_items = entries
        self._native_audiofx_summary = {
            "items": len(entries),
            "ready": sum(1 for item in entries if item.get("ready")),
            "available_story_audio_files": len(self.available_story_audio_files()),
        }
    def _audiofx_label(self, item: dict[str, str], index: int, ready: bool) -> str:
        audio_type = str(item.get("type") or "Auto").strip() or "Auto"
        description = str(item.get("description") or "").strip()
        prompt = str(item.get("prompt") or "").strip()
        title = (description or prompt or "Untitled AudioFX").replace("\r", " ").replace("\n", " ")
        while "  " in title:
            title = title.replace("  ", " ")
        if len(title) > 80:
            title = title[:77].rstrip() + "..."
        status = "ready" if ready else "needs file"
        return f"AudioFX {index + 1} - [{audio_type}] {title} ({status})"

    def _audiofx_tooltip(self, item: dict[str, str], ready: bool) -> str:
        status = "Ready" if ready else "Needs a valid local sound file"
        parts = [
            f"Status: {status}",
            f"Description: {str(item.get('description') or '').strip()}",
            f"File: {str(item.get('file_path') or '').strip()}",
            f"Prompt: {str(item.get('prompt') or '').strip()}",
        ]
        return "\n".join(part for part in parts if not part.endswith(": "))

    def _audiofx_file_ready(self, item: dict[str, str]) -> bool:
        file_path = str(item.get("file_path") or "").strip()
        return bool(file_path and Path(file_path).exists())

    def _audiofx_volume_percent(self) -> int:
        try:
            value = int(self.settings.get("audiofx_volume", 60))
        except Exception:
            value = 60
        return max(0, min(100, value))

    def _apply_audiofx_volume(self) -> None:
        if self._audiofx_output is None:
            return
        try:
            self._audiofx_output.setVolume(self._audiofx_volume_percent() / 100.0)
        except Exception:
            pass

    def _selected_audiofx_index(self) -> int:
        try:
            return int(self.settings.get("native_selected_audiofx_index", -1))
        except (TypeError, ValueError):
            return -1

    def _select_audiofx_index(self, index: int):
        items = self._audiofx_items()
        selected = int(index)
        self.settings["native_selected_audiofx_index"] = (
            selected if 0 <= selected < len(items) else -1
        )
        self.storage.save_settings(self.settings)

    def _update_audiofx_buttons(self):
        index = self._selected_audiofx_index()
        items = self._audiofx_items()
        selected = 0 <= index < len(items)
        ready = bool(selected and self._audiofx_file_ready(items[index]))
        for key in ("audiofx_load", "audiofx_delete"):
            button = self._controls.get(key)
            if button is not None:
                button.setEnabled(selected)
        create_button = self._controls.get("audiofx_create")
        if create_button is not None:
            create_button.setEnabled(True)
        add_file_button = self._controls.get("audiofx_add_file")
        if add_file_button is not None:
            add_file_button.setEnabled(True)
        play_button = self._controls.get("audiofx_play")
        if play_button is not None:
            play_button.setEnabled(ready)
        status = self._controls.get("audiofx_status")
        if status is not None:
            if selected:
                file_path = str(items[index].get("file_path") or "").strip()
                status_text = "Ready and indexed: " + file_path if ready else "Needs sound file: " + (file_path or "none attached")
                status.setText(status_text)
                status.setStyleSheet("color: #22c55e;" if ready else "color: #facc15;")
            else:
                status.setText("Create an AudioFX item from the current sound description, then attach a local audio file.")
                status.setStyleSheet("")

    def _new_audiofx_id(self, existing_items: list[dict[str, str]] | None = None) -> str:
        stamp = QtCore.QDateTime.currentDateTimeUtc().toString("yyyyMMddHHmmsszzz")
        base = f"audiofx_{stamp}"
        known = {str(item.get("id") or "") for item in list(existing_items or [])}
        if base not in known:
            return base
        suffix = 2
        while f"{base}_{suffix}" in known:
            suffix += 1
        return f"{base}_{suffix}"

    def _audiofx_pack_id(self, pack_id: str, item_id: str, existing_items: list[dict[str, str]]) -> str:
        raw_pack = re.sub(r"[^a-z0-9_]+", "_", str(pack_id or "audio_pack").lower()).strip("_") or "audio_pack"
        raw_item = re.sub(r"[^a-z0-9_]+", "_", str(item_id or "item").lower()).strip("_") or "item"
        return f"{raw_pack}_{raw_item}"[:96].strip("_") or "audio_pack_item"

    def _import_audio_pack_resources(self):
        start = r"Q:\Sounds" if Path(r"Q:\Sounds").exists() else str(Path.home())
        path = self._open_directory("Import Audio Pack Resources", start)
        if not path:
            return
        try:
            added, updated, skipped = self._import_audio_pack_from_path(path)
        except Exception as exc:
            self._warn("Import Audio Pack Resources", f"Audio pack import failed:\n\n{exc}")
            return
        status = self._controls.get("audiofx_status")
        if status is not None:
            status.setStyleSheet("color: #22c55e;" if added or updated else "color: #facc15;")
            status.setText(f"Imported audio pack: {added} added, {updated} updated, {skipped} skipped.")
        logger = getattr(self.context, "logger", None)
        if logger is not None:
            logger.info("[AR_MODE] Imported AudioFX pack from %s: added=%s updated=%s skipped=%s", path, added, updated, skipped)

    def _import_audio_pack_from_path(self, pack_path: str | Path) -> tuple[int, int, int]:
        manifest_path = self._find_audio_pack_manifest(Path(pack_path))
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        entries = payload.get("entries")
        if not isinstance(entries, list):
            entries = payload.get("items")
        if not isinstance(entries, list):
            raise ValueError("The selected folder does not contain an MPRC audio pack manifest with entries.")
        pack_id = str(payload.get("pack_id") or payload.get("id") or manifest_path.parent.name or "audio_pack").strip()
        items = self._audiofx_items()
        by_id = {str(item.get("id") or "").strip().lower(): index for index, item in enumerate(items)}
        by_path = {self._audio_file_key(item.get("file_path", "")): index for index, item in enumerate(items) if item.get("file_path")}
        now = QtCore.QDateTime.currentDateTimeUtc().toString(QtCore.Qt.ISODate)
        added = 0
        updated = 0
        skipped = 0

        for entry in entries:
            if not isinstance(entry, dict):
                skipped += 1
                continue
            file_path = self._resolve_audio_pack_file(manifest_path.parent, entry)
            if not file_path:
                skipped += 1
                continue
            item_id = self._audiofx_pack_id(pack_id, str(entry.get("id") or Path(file_path).stem), items)
            audio_type = str(entry.get("type") or "Auto").strip()
            description = str(entry.get("description") or entry.get("name") or Path(file_path).stem).strip()
            prompt = str(entry.get("prompt") or description).strip()
            incoming = {
                "id": item_id,
                "type": audio_type if audio_type in AUDIO_TYPES else "Auto",
                "description": description,
                "prompt": prompt,
                "file_path": str(Path(file_path).resolve()),
                "created_at": now,
                "updated_at": now,
            }
            path_key = self._audio_file_key(incoming["file_path"])
            index = by_path.get(path_key)
            if index is None:
                index = by_id.get(item_id.lower())
            if index is None:
                items.append(incoming)
                by_id[incoming["id"].lower()] = len(items) - 1
                by_path[path_key] = len(items) - 1
                added += 1
            else:
                created_at = str(items[index].get("created_at") or "").strip()
                incoming["created_at"] = created_at or now
                items[index] = incoming
                by_id[incoming["id"].lower()] = index
                by_path[path_key] = index
                updated += 1

        if not added and not updated:
            return added, updated, skipped
        self.settings["story_sounds_enabled"] = True
        self._save_audiofx_items(items)
        self._populate_audiofx_items()
        if added:
            self._select_audiofx_index(len(items) - added)
        return added, updated, skipped

    def _find_audio_pack_manifest(self, pack_path: Path) -> Path:
        path = pack_path.expanduser()
        if path.is_file():
            return path
        if not path.exists() or not path.is_dir():
            raise FileNotFoundError(f"Audio pack folder was not found: {path}")
        candidates = [
            path / "mprc_audio_pack.json",
            path / "audio_pack.json",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        for candidate in sorted(path.glob("*.json")):
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(data, dict) and isinstance(data.get("entries") or data.get("items"), list):
                return candidate
        raise FileNotFoundError("No audio pack manifest was found. Expected mprc_audio_pack.json or audio_pack.json.")

    def _resolve_audio_pack_file(self, pack_root: Path, entry: dict[str, Any]) -> str:
        raw_candidates = [
            entry.get("relative_path"),
            entry.get("file_path"),
            entry.get("file_name"),
        ]
        for raw in raw_candidates:
            value = str(raw or "").strip()
            if not value:
                continue
            candidate = Path(value)
            if not candidate.is_absolute():
                candidate = pack_root / candidate
            if candidate.exists() and candidate.is_file():
                return str(candidate)
        file_name = str(entry.get("file_name") or "").strip()
        if file_name:
            matches = list(pack_root.rglob(file_name))
            for match in matches:
                if match.is_file():
                    return str(match)
        return ""

    def _selected_persona(self) -> PersonaConfig | None:
        return self.active_persona()

    def _schedule_delayed_commit(self, key: str, callback, *, delay_ms: int = 450) -> None:
        if self._syncing:
            return
        timer_key = str(key or "").strip()
        if not timer_key:
            return
        timer = self._commit_timers.get(timer_key)
        if timer is None:
            timer = QtCore.QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(callback)
            self._commit_timers[timer_key] = timer
        timer.start(max(0, int(delay_ms)))

    def _commit_delayed_now(self, key: str, callback) -> None:
        timer = self._commit_timers.get(str(key or "").strip())
        if timer is not None and timer.isActive():
            timer.stop()
        callback()

    def _schedule_editor_commit(self, *, include_identity: bool = False, delay_ms: int = 450) -> None:
        if self._syncing:
            return
        self._editor_commit_include_identity = bool(self._editor_commit_include_identity or include_identity)
        timer = getattr(self, "_editor_commit_timer", None)
        if timer is not None:
            timer.start(max(0, int(delay_ms)))
        else:
            self._commit_editor(include_identity=include_identity)

    def _commit_scheduled_editor(self) -> None:
        include_identity = bool(getattr(self, "_editor_commit_include_identity", False))
        self._editor_commit_include_identity = False
        self._commit_editor(include_identity=include_identity)

    def _commit_editor_now(self, *, include_identity: bool = True) -> None:
        timer = getattr(self, "_editor_commit_timer", None)
        if timer is not None and timer.isActive():
            timer.stop()
        self._editor_commit_include_identity = False
        self._commit_editor(include_identity=include_identity)

    def _schedule_voice_commit(self) -> None:
        self._schedule_delayed_commit("voice", self._commit_voice)

    def _commit_voice_now(self) -> None:
        self._commit_delayed_now("voice", self._commit_voice)

    def _schedule_visual_commit(self) -> None:
        self._schedule_delayed_commit("visual", self._commit_visual)

    def _commit_visual_now(self) -> None:
        self._commit_delayed_now("visual", self._commit_visual)

    def _schedule_session_commit(self) -> None:
        self._schedule_delayed_commit("session", lambda: self._commit_session(refresh_ui=False))

    def _commit_session_now(self, *, refresh_ui: bool = True) -> None:
        self._commit_delayed_now("session", lambda: self._commit_session(refresh_ui=refresh_ui))

    def _schedule_ar_state_commit(self) -> None:
        self._schedule_delayed_commit("ar_state", self._commit_ar_state)

    def _commit_ar_state_now(self) -> None:
        self._commit_delayed_now("ar_state", self._commit_ar_state)

    def _schedule_audio_settings_commit(self) -> None:
        self._schedule_delayed_commit("audio_settings", self._commit_audio_settings)

    def _commit_audio_settings_now(self) -> None:
        self._commit_delayed_now("audio_settings", self._commit_audio_settings)

    def _commit_editor(self, *, include_identity: bool = True):
        if self._syncing:
            return
        persona = self._selected_persona()
        if persona is None:
            return
        old_id = persona.id
        old_display_name = persona.display_name
        old_image_path = persona.character_image_path
        old_master_narrator = self._persona_is_master_narrator(persona)
        if include_identity:
            requested_id = unique_persona_id(self._controls["persona_id"].text(), {p.id for p in self.personas if p is not persona})
            persona.id = requested_id
        persona.enabled = self._controls["persona_enabled"].isChecked()
        persona.master_narrator = bool(self._controls["master_narrator"].isChecked())
        if include_identity:
            persona.display_name = self._controls["display_name"].text().strip() or persona.id.replace("_", " ").title()
        persona.role = self._controls["role"].text().strip()
        persona.description = self._controls["description"].toPlainText().strip()
        persona.character_image_path = self._controls["character_image_path"].text().strip()
        persona.system_prompt = self._controls["system_prompt"].toPlainText().strip()
        persona.ar_profile_enabled = self._controls["ar_profile_enabled"].isChecked()
        persona.ar_description = self._controls["ar_description"].toPlainText().strip()
        persona.ar_system_prompt = self._controls["ar_system_prompt"].toPlainText().strip()
        persona.speaking_style = self._controls["speaking_style"].text().strip()
        persona.allowed_tone = self._controls["allowed_tone"].text().strip()
        persona.response_length = self._controls["response_length"].currentText().strip() or "balanced"
        persona.temperature_hint = self._controls["temperature_hint"].text().strip()
        persona.memory_scope = self._controls["memory_scope"].currentText().strip()
        persona.behavior_mode = self._controls["behavior_mode"].currentText().strip()
        persona.tags = [item.strip().lower() for item in self._controls["tags"].text().split(",") if item.strip()]
        if self.session.active_persona_id == old_id:
            self.session.active_persona_id = persona.id
        if self.session.current_speaker_id == old_id:
            self.session.current_speaker_id = persona.id
        settings_changed = False
        if normalize_persona_id(self.settings.get("narrator_persona_id", "")) == old_id:
            self.settings["narrator_persona_id"] = persona.id
            self.settings["narrator_persona_mode"] = "explicit"
            settings_changed = True
        if normalize_persona_id(self.settings.get("voice_edit_persona_id", "")) == old_id:
            self.settings["voice_edit_persona_id"] = persona.id
            settings_changed = True
        if settings_changed:
            self.storage.save_settings(self.settings)
        self.save_state()
        self._notify_changed()
        identity_changed = old_id != persona.id or old_display_name != persona.display_name
        if identity_changed or old_master_narrator != self._persona_is_master_narrator(persona):
            self._refresh_persona_selectors()
            if "session_mode" in self._controls:
                self._populate_session()
            self._refresh_narrator_selector()
            self._refresh_voice_persona_selector()
        if old_image_path != persona.character_image_path:
            self._set_image_label(self._controls.get("character_image"), persona.character_image_path, fallback_text="No picture")
        self._refresh_character_preview()
        self._refresh_debug()

    def _commit_voice(self):
        if self._syncing:
            return
        persona = self._selected_voice_persona()
        if persona is None:
            return
        voice = persona.voice
        voice.enabled = self._controls["voice_enabled"].isChecked()
        voice.backend = self._controls["voice_backend"].currentText().strip() or "inherit"
        voice.sample_path = self._controls["voice_sample"].text().strip()
        voice.preset_name = self._controls["voice_preset"].text().strip()
        voice.language = self._controls["voice_language"].currentText().strip().lower()
        self.save_state()
        self._sync_voice_sample_picker(voice.sample_path)
        self._update_voice_target_label()
        self._update_voice_warning()

    def _commit_voice_follow_active(self):
        if self._syncing:
            return
        previous_target = self._selected_voice_persona()
        widget = self._controls.get("voice_follow_active")
        follow = bool(widget.isChecked()) if widget is not None and hasattr(widget, "isChecked") else True
        self.settings["voice_follow_active_persona"] = follow
        target = self.active_persona() if follow else (previous_target or self.active_persona())
        if target is not None:
            self.settings["voice_edit_persona_id"] = target.id
        self.storage.save_settings(self.settings)
        persona = self._selected_voice_persona()
        was_syncing = self._syncing
        self._syncing = True
        try:
            self._refresh_voice_persona_selector()
            if persona is not None:
                self._populate_voice(persona)
        finally:
            self._syncing = was_syncing
        self._update_voice_target_label()
        self._update_voice_warning()
        self._refresh_debug()

    def _commit_voice_persona(self):
        if self._syncing:
            return
        if self._voice_follows_active():
            self._refresh_voice_persona_selector()
            return
        combo = self._controls.get("voice_persona")
        if combo is None:
            return
        selected = normalize_persona_id(combo.currentData() or "")
        if not selected or self.persona_by_id(selected) is None:
            return
        self.settings["voice_edit_persona_id"] = selected
        self.storage.save_settings(self.settings)
        persona = self.persona_by_id(selected)
        if persona is not None:
            was_syncing = self._syncing
            self._syncing = True
            try:
                self._populate_voice(persona)
            finally:
                self._syncing = was_syncing
        self._update_voice_target_label()
        self._update_voice_warning()
        self._refresh_debug()

    def _commit_narrator_persona(self):
        if self._syncing:
            return
        combo = self._controls.get("narrator_persona")
        if combo is None:
            return
        selected = str(combo.currentData() or "").strip()
        self.settings["narrator_persona_id"] = selected
        self.settings["narrator_persona_mode"] = "explicit" if selected else "auto"
        narrator = self.persona_by_id(selected) if selected else self.selected_narrator_persona()
        if narrator is not None and not self._voice_follows_active():
            self.settings["voice_edit_persona_id"] = narrator.id
        self.storage.save_settings(self.settings)
        was_syncing = self._syncing
        self._syncing = True
        try:
            self._refresh_voice_persona_selector()
            voice_target = self._selected_voice_persona()
            if voice_target is not None:
                self._populate_voice(voice_target)
        finally:
            self._syncing = was_syncing
        self._persist_current_story_narrator_lock()
        self._update_voice_warning()
        self._refresh_debug()

    def _commit_visual(self):
        if self._syncing:
            return
        persona = self._selected_persona()
        if persona is None:
            return
        visual = persona.visual
        visual.enabled = self._controls["visual_enabled"].isChecked()
        visual.mode = str(self._controls["visual_mode"].currentData() or self._controls["visual_mode"].currentText()).strip() or "off"
        visual.provider = self._controls["visual_provider"].currentText().strip() or "inherit"
        visual.model = self._controls["visual_model"].text().strip()
        visual.size = self._controls["visual_size"].currentText().strip() or "inherit"
        visual.style_preset = str(self._controls["visual_style"].currentData() or "").strip()
        visual.character_description = self._controls["visual_character"].toPlainText().strip()
        visual.clothing_props = self._controls["visual_clothing"].text().strip()
        visual.environment_style = self._controls["visual_environment"].text().strip()
        visual.negative_prompt = self._controls["visual_negative"].text().strip()
        visual.keep_continuity = self._controls["visual_continuity"].isChecked()
        appearance_combo = self._controls.get("visual_appearance_freedom")
        if appearance_combo is not None:
            visual.appearance_freedom = "flexible" if appearance_combo.currentData() == "flexible" else "strict"
        visual.include_scene_summary = self._controls["visual_scene"].isChecked()
        visual.include_active_speaker = self._controls["visual_speaker"].isChecked()
        visual.auto_reply_interval = int(self._controls["visual_interval"].value())
        visual.cooldown_seconds = int(self._controls["visual_cooldown"].value())
        visual.max_auto_images_per_session = int(self._controls["visual_max_auto"].value())
        visual.auto_show_dock = self._controls["visual_auto_show"].isChecked()
        self.save_state()
        self._refresh_debug()

    def _commit_session(self, *, refresh_ui: bool = True):
        if self._syncing:
            return
        c = self._controls
        previous_mode = self.session.mode
        self.session.mode = c["session_mode"].currentText().strip() or "Single active persona"
        self.session.scene_title = c["scene_title"].text().strip()
        self.session.location = c["location"].text().strip()
        self.session.time_of_day = c["time_of_day"].text().strip()
        self.session.mood = c["mood"].text().strip()
        self.session.objective = c["objective"].text().strip()
        self.session.scene_summary = c["scene_summary"].toPlainText().strip()
        self.session.auto_select_speaker = c["auto_select"].isChecked()
        self.session.current_speaker_id = str(c["next_speaker"].currentData() or self.session.active_persona_id).strip()
        self.session.keep_scene_continuity = c["continuity"].isChecked()
        self.session.update_scene_after_reply = c["update_scene"].isChecked()
        if self.session.mode == AR_MODE:
            if previous_mode != AR_MODE:
                self.settings["last_non_ar_mode"] = previous_mode or "Narrator + characters"
                self.storage.save_settings(self.settings)
            self.session.enabled = True
            self.ensure_ar_state()
        else:
            self.settings["last_non_ar_mode"] = self.session.mode
            self.storage.save_settings(self.settings)
        self.save_state()
        if refresh_ui:
            self.refresh_ui()
        else:
            self._refresh_chat_play_state_sidebar()
            self._refresh_story_export_card()
        self._refresh_debug()

    def _commit_ar_state(self):
        if self._syncing:
            return
        c = self._controls
        state = self.session.ar_state
        self.session.ar_use_persona_profiles = c["ar_use_persona_profiles"].isChecked()
        self.session.ar_pacing = c["ar_pacing"].currentText().strip() or "Balanced"
        self.session.ar_interaction_frequency = c["ar_interaction"].currentText().strip() or "Ask sometimes"
        self.session.ar_dialogue_density = c["ar_dialogue_density"].currentText().strip() or "Balanced narrator + character dialogue"
        state.tension_level = int(c["ar_tension"].value())
        state.current_scene = c["ar_current_scene"].text().strip()
        state.location = c["ar_location"].text().strip()
        state.time_of_day = c["ar_time_of_day"].text().strip()
        state.mood = c["ar_mood"].text().strip()
        state.story_goal = c["ar_story_goal"].text().strip()
        state.active_characters = [
            normalize_persona_id(item)
            for item in c["ar_active_characters"].text().split(",")
            if item.strip()
        ][:8]
        state.player_intent = c["ar_player_intent"].text().strip()
        state.pending_choices = [
            item.strip()
            for item in c["ar_pending_choices"].toPlainText().splitlines()
            if item.strip()
        ][:6]
        if self.session.mode == AR_MODE:
            self.ensure_ar_state()
        self.save_state()
        self._refresh_debug()

    def _seed_ar_state_from_session(self):
        if self._syncing:
            return
        state = self.session.ar_state
        state.current_scene = self.session.scene_title or state.current_scene
        state.location = self.session.location or state.location
        state.time_of_day = self.session.time_of_day or state.time_of_day
        state.mood = self.session.mood or state.mood
        state.story_goal = self.session.objective or state.story_goal
        self.ensure_ar_state()
        self.save_state()
        self.refresh_ui()

    def _fill_ar_persona_profiles(self):
        if self._syncing:
            return
        defaults = [PersonaConfig.from_dict(item) for item in self.storage._default_json("personas.json", [])]
        defaults_by_id = {persona.id: persona for persona in defaults}
        changed = False
        for persona in self.personas:
            default = defaults_by_id.get(persona.id)
            if default is None:
                continue
            if not str(persona.ar_description or "").strip() and str(default.ar_description or "").strip():
                persona.ar_description = default.ar_description
                changed = True
            if not str(persona.ar_system_prompt or "").strip() and str(default.ar_system_prompt or "").strip():
                persona.ar_system_prompt = default.ar_system_prompt
                changed = True
        if changed:
            self.save_state()
            self.refresh_ui()
        else:
            self._warn("AR Persona Prompts", "All matching default personas already have AR prompt profiles filled.")

    def _clear_ar_state(self):
        if self._syncing:
            return
        from addons.multi_persona_roleplay.models import AlternativeRealityState

        self.session.ar_state = AlternativeRealityState()
        self.ensure_ar_state()
        self.save_state()
        self.refresh_ui()

    def _populate_master_stories(self):
        current_id = self._selected_master_story_id()
        stories = self.storage.load_story_index()
        story_ids = {
            self.storage.story_id(story.get("id") or "")
            for story in stories
            if isinstance(story, dict)
        }
        if current_id not in story_ids:
            current_id = ""
            self.settings["native_selected_story_id"] = ""
        self._native_story_index = [
            {
                **dict(story),
                "id": self.storage.story_id(story.get("id") or ""),
                "label": (
                    f"{str(story.get('title') or story.get('id') or 'Story').strip()}  "
                    f"({str(story.get('updated_at') or '').strip()[:10]})"
                    if str(story.get("updated_at") or "").strip()
                    else str(story.get("title") or story.get("id") or "Story").strip()
                ),
            }
            for story in stories
            if isinstance(story, dict)
        ]
        self._update_master_story_buttons()

    def _selected_master_story_id(self) -> str:
        selected = str(self.settings.get("native_selected_story_id") or "").strip()
        return self.storage.story_id(selected) if selected else ""

    def _update_master_story_buttons(self):
        story_id = self._selected_master_story_id()
        self._native_master_story_actions = {
            "story_id": story_id,
            "can_load": bool(story_id),
            "can_delete": bool(story_id),
        }
        self._refresh_master_story_image_preview()

    def _on_master_story_selection_changed(self):
        self._update_master_story_buttons()
        self._refresh_master_story_image_preview()
        self._refresh_story_export_card()

    def _refresh_master_story_image_preview(self):
        story_id = self._selected_master_story_id()
        payload = self.storage.load_story(story_id) if story_id else {}
        image_path = str(payload.get("story_image_path") or payload.get("cover_image_path") or "").strip() if isinstance(payload, dict) else ""
        if story_id and not image_path:
            payload = self._ensure_master_story_image(dict(payload or {}), save_story=True)
            image_path = str(payload.get("story_image_path") or "").strip()
        self._set_master_story_image(image_path, payload if isinstance(payload, dict) else {})

    def _set_master_story_image(self, image_path: str, payload: dict[str, Any] | None = None) -> None:
        path = Path(str(image_path or "").strip())
        title = str((payload or {}).get("title") or "No story image").strip()
        ready = bool(str(image_path or "").strip() and path.exists())
        self._native_master_story_image = {
            "path": str(path.resolve()) if ready else "",
            "title": title[:80] or "No story image",
            "ready": ready,
        }

    def _ensure_master_story_image(self, payload: dict[str, Any], *, save_story: bool = False) -> dict[str, Any]:
        story = dict(payload or {})
        story_id = self.storage.story_id(story.get("id") or story.get("title") or "")
        if not story_id:
            return story
        existing = str(story.get("story_image_path") or story.get("cover_image_path") or "").strip()
        if existing and Path(existing).exists():
            story["story_image_path"] = existing
            return story
        image_path = self._create_master_story_cover_image(story)
        if image_path:
            story["story_image_path"] = image_path
            if save_story:
                self.storage.save_story(story)
        return story

    def _create_master_story_cover_image(self, payload: dict[str, Any]) -> str:
        story_id = self.storage.story_id(payload.get("id") or payload.get("title") or "story")
        if not story_id:
            return ""
        try:
            path = self.context.storage.resolve(f"stories/covers/{story_id}.svg")
            path.parent.mkdir(parents=True, exist_ok=True)
            title = str(payload.get("title") or "Story").strip() or "Story"
            summary = str(payload.get("summary") or "").strip()
            session = dict(payload.get("session") or {}) if isinstance(payload.get("session"), dict) else {}
            mood_text = " ".join([title, summary, str(session.get("location") or ""), str(session.get("mood") or "")]).lower()
            top, bottom, accent = self._story_cover_colors(mood_text)
            subtitle = str(session.get("location") or session.get("mood") or payload.get("mode") or "").strip()
            title_svg = html.escape(title[:70])
            subtitle_svg = html.escape(subtitle[:36])
            svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="180" height="180" viewBox="0 0 180 180">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop stop-color="{top}"/><stop offset="1" stop-color="{bottom}"/></linearGradient></defs>
<rect width="180" height="180" rx="10" fill="url(#g)"/>
<path d="M22 142L54 106L88 142M46 142L78 106L112 142M70 142L102 106L136 142" fill="none" stroke="#ffffff" stroke-opacity=".36" stroke-width="2"/>
<rect x="54" y="80" width="72" height="70" rx="6" fill="none" stroke="{accent}" stroke-width="2"/>
<path d="M66 80V150M114 80V150" stroke="{accent}" stroke-width="2"/>
<path d="M116 28A21 21 0 0 1 151 56" fill="none" stroke="{accent}" stroke-width="3"/>
<text x="14" y="25" fill="#f8fafc" font-family="sans-serif" font-size="15" font-weight="700">{title_svg}</text>
<text x="14" y="170" fill="#f8fafc" font-family="sans-serif" font-size="10">{subtitle_svg}</text>
</svg>'''
            path.write_text(svg, encoding="utf-8")
            return str(path)
        except Exception as exc:
            logger = getattr(self.context, "logger", None)
            if logger is not None:
                logger.warning("[MPRC] Could not create story cover image: %s", exc)
        return ""

    @staticmethod
    def _story_cover_colors(text: str) -> tuple[str, str, str]:
        lowered = str(text or "").lower()
        if any(word in lowered for word in ("rain", "night", "mystery", "hotel", "noir")):
            return "#14213d", "#0f172a", "#60a5fa"
        if any(word in lowered for word in ("forest", "cave", "dragon", "magic", "fantasy", "castle")):
            return "#183a2c", "#111827", "#22c55e"
        if any(word in lowered for word in ("space", "cyber", "neon", "future", "star")):
            return "#20123a", "#0f172a", "#e879f9"
        if any(word in lowered for word in ("tavern", "warm", "sun", "desert")):
            return "#3b2f1b", "#111827", "#f59e0b"
        return "#172033", "#0f172a", "#38bdf8"

    def _set_master_story_status(self, message: str) -> None:
        self._native_master_story_status = str(message or "")
        self._native_revision += 1

    def _current_story_id(self) -> str:
        return self.storage.story_id(self.settings.get("last_master_story_id") or self.settings.get("last_master_story_title") or "")

    def _current_linked_persona_ids(self) -> list[str]:
        linked = [
            normalize_persona_id(item)
            for item in list(self.settings.get("master_story_linked_persona_ids") or [])
            if str(item or "").strip()
        ]
        if linked:
            return linked
        state = self.session.ar_state
        active = [normalize_persona_id(item) for item in list(getattr(state, "active_characters", []) or []) if str(item or "").strip()]
        if active:
            return active
        fallback = [item for item in (self.session.active_persona_id, self.session.current_speaker_id) if str(item or "").strip()]
        return list(dict.fromkeys(normalize_persona_id(item) for item in fallback if item))

    def _story_memory_snapshot_exists(self, story_id: str | None = None) -> bool:
        normalized = self.storage.story_id(story_id or self._current_story_id())
        if not normalized:
            return False
        try:
            return bool(self.context.storage.resolve(f"stories/{normalized}.memory.json").exists())
        except Exception:
            return bool(self.storage.load_story_memory(normalized))

    def _active_story_payload(self) -> dict[str, Any]:
        story_id = self._current_story_id()
        payload = self.storage.load_story(story_id) if story_id else {}
        return payload if isinstance(payload, dict) else {}

    def _refresh_reliability_panels(self):
        status = self._controls.get("story_status")
        if status is not None:
            status.setPlainText(self._story_runtime_status_text())
        routes = self._controls.get("story_voice_routes")
        if routes is not None:
            routes.setPlainText(self._build_voice_routing_inspector_text())
        validation = self._controls.get("story_validation")
        if validation is not None and self._validation_result:
            validation.setPlainText(self._validation_result)
        self._refresh_memory_browser()
        self._refresh_event_log_panel()

    def _story_runtime_status_text(self) -> str:
        story_id = self._current_story_id()
        story_title = str(self.settings.get("last_master_story_title") or story_id or "No active story").strip()
        narrator = self.selected_narrator_persona()
        linked = self._current_linked_persona_ids()
        known = {persona.id for persona in self.personas}
        valid_linked = [item for item in linked if item in known]
        voice_summary = self._voice_readiness_summary(valid_linked)
        visual_summary = self._visual_readiness_summary(valid_linked)
        audio_summary = self._audiofx_readiness_summary()
        memory_status = "loaded/saved" if story_id and self._story_memory_snapshot_exists(story_id) else "no saved memory snapshot"
        if not story_id:
            memory_status = "no active story"
        lines = [
            f"Active story: {story_title}",
            f"Story id: {story_id or 'none'}",
            f"Roleplay enabled: {'yes' if self.session.enabled else 'no'}",
            f"AR mode: {'on' if self.session.mode == AR_MODE else 'off'}",
            f"This story uses narrator: {narrator.display_name + ' (' + narrator.id + ')' if narrator else 'none'}",
            f"Narrator lock: {self._narrator_selection_mode()}",
            f"Active persona: {self.session.active_persona_id or 'none'}",
            f"Current speaker: {self.session.current_speaker_id or 'none'}",
            f"Active/linked personas: {', '.join(valid_linked) if valid_linked else 'none'}",
            f"Loaded memory status: {memory_status}",
            f"Voice/TTS readiness: {voice_summary}",
            f"Visual Reply readiness: {visual_summary}",
            f"AudioFX readiness: {audio_summary}",
            f"Last pre-apply backup: {'available' if self._last_pre_apply_backup_exists() else 'not found'}",
        ]
        return "\n".join(lines)

    def _voice_readiness_summary(self, persona_ids: list[str]) -> str:
        backend = self.current_tts_backend()
        if not backend:
            return "unknown TTS backend"
        ids = list(dict.fromkeys([self.selected_narrator_persona_id()] + list(persona_ids or [])))
        ids = [item for item in ids if item]
        if not ids:
            return "no routed personas"
        ready = 0
        configured = 0
        warnings = 0
        for persona_id in ids:
            route = self.voice_router.effective_voice_config({"persona_id": persona_id, "tts_backend": backend})
            if route.get("enabled"):
                configured += 1
            if route.get("supported") and route.get("sample_path"):
                ready += 1
            elif route.get("warning"):
                warnings += 1
        return f"{ready}/{len(ids)} ready, {configured} configured, backend={backend or 'unknown'}, warnings={warnings}"

    def _visual_readiness_summary(self, persona_ids: list[str]) -> str:
        service_ready = self.visual_reply_service is not None and hasattr(self.visual_reply_service, "request_generation")
        personas = [self.persona_by_id(item) for item in list(persona_ids or [])]
        personas = [item for item in personas if item is not None]
        enabled = sum(1 for persona in personas if bool(getattr(persona.visual, "enabled", False)))
        broken_images = sum(
            1
            for persona in personas
            if str(getattr(persona, "character_image_path", "") or "").strip()
            and not Path(str(persona.character_image_path)).exists()
        )
        return f"service={'ready' if service_ready else 'unavailable'}, {enabled}/{len(personas)} personas enabled, broken avatar paths={broken_images}"

    def _audiofx_readiness_summary(self) -> str:
        items = self._audiofx_items()
        ready = sum(1 for item in items if self._audiofx_file_ready(item))
        available = len(self.available_story_audio_files())
        return f"{ready}/{len(items)} AudioFX ready, {available} story cues indexed, Story Sounds={'on' if self.story_sounds_enabled() else 'off'}"

    def _build_voice_routing_inspector_text(self) -> str:
        backend = self.current_tts_backend()
        lines = [f"Active TTS backend: {backend or 'unknown'}"]
        narrator = self.selected_narrator_persona()
        if narrator is not None:
            lines.append(self._voice_route_line("[NARRATOR]", narrator, backend))
        else:
            lines.append("[NARRATOR] -> none -> missing narrator")
        for persona_id in self._current_linked_persona_ids():
            persona = self.persona_by_id(persona_id)
            if persona is None:
                lines.append(f"[CHARACTER: {persona_id}] -> missing persona -> no voice")
                continue
            display = str((self.story_prompt_persona(persona.id) or persona).display_name or persona.display_name)
            lines.append(self._voice_route_line(f"[CHARACTER: {display}]", persona, backend))
        return "\n".join(dict.fromkeys(lines))

    def _voice_route_line(self, label: str, persona: PersonaConfig, backend: str) -> str:
        route = self.voice_router.effective_voice_config({"persona_id": persona.id, "tts_backend": backend})
        sample = str(route.get("sample_path") or "").strip()
        voice_text = Path(sample).name if sample else (str(route.get("warning") or "").strip() or "voice not configured")
        return f"{label} -> {persona.display_name} ({persona.id}) -> {voice_text}"

    def _validate_story_setup_to_ui(self):
        result = self.validate_story_setup()
        self._validation_result = self._format_validation_result(result)
        widget = self._controls.get("story_validation")
        if widget is not None:
            widget.setPlainText(self._validation_result)
        self._record_story_event("Story setup validation completed.", severity="info", kind="validation", persist=True)
        self._refresh_reliability_panels()

    def validate_story_setup(self) -> dict[str, Any]:
        issues: list[dict[str, str]] = []

        def add(severity: str, message: str, kind: str = "validation") -> None:
            issues.append({"severity": severity, "kind": kind, "message": message})

        story_id = self._current_story_id()
        payload = self._active_story_payload()
        if story_id and not payload:
            add("error", f"Active story '{story_id}' could not be loaded.", "story")
        for note in list(payload.get("_migration_log") or []):
            add("warning", f"Story migration/fallback: {note}", "schema")
        if story_id and not self._story_memory_snapshot_exists(story_id):
            add("warning", f"Story memory snapshot is missing for '{story_id}'.", "memory")
        if self.session.mode == AR_MODE and self.selected_narrator_persona() is None:
            add("error", "AR mode is active but no narrator persona can be resolved.", "narrator")
        backend = self.current_tts_backend()
        if not backend:
            add("warning", "Active TTS backend is unknown.", "voice")
        elif backend not in VOICE_REFERENCE_BACKENDS:
            add("warning", f"Active TTS backend '{backend}' does not support persona voice samples.", "voice")
        known = {persona.id for persona in self.personas}
        linked = self._current_linked_persona_ids()
        for persona_id in linked:
            if persona_id not in known:
                add("error", f"Invalid linked persona id: {persona_id}", "persona")
        overrides = self._master_story_persona_overrides()
        for persona_id, override in overrides.items():
            if persona_id not in known:
                add("error", f"Persona override points to missing base persona: {persona_id}", "persona_override")
            if not isinstance(override, dict):
                add("error", f"Persona override for {persona_id} is not an object.", "persona_override")
        route_ids = list(dict.fromkeys([self.selected_narrator_persona_id()] + [item for item in linked if item in known]))
        for persona_id in route_ids:
            route = self.voice_router.effective_voice_config({"persona_id": persona_id, "tts_backend": backend})
            persona_name = str(route.get("display_name") or persona_id)
            voice = self.persona_by_id(persona_id).voice if self.persona_by_id(persona_id) is not None else None
            if voice is not None and bool(voice.enabled):
                sample = str(voice.sample_path or "").strip()
                if not sample:
                    add("warning", f"{persona_name} voice is enabled but no voice sample path is set.", "voice")
                elif not Path(sample).exists():
                    add("error", f"{persona_name} voice sample cannot be loaded: {sample}", "voice")
                elif route.get("warning"):
                    add("warning", str(route.get("warning")), "voice")
            elif persona_id == self.selected_narrator_persona_id():
                add("warning", f"Narrator {persona_name} has voice disabled.", "voice")
        story_persona_ids = list(dict.fromkeys(route_ids + linked + [self.session.active_persona_id, self.session.current_speaker_id]))
        for persona_id in story_persona_ids:
            persona = self.persona_by_id(persona_id)
            if persona is None:
                continue
            image = str(getattr(persona, "character_image_path", "") or "").strip()
            if image and not Path(image).exists():
                add("warning", f"Broken avatar image path for {persona.display_name}: {image}", "visual")
            if persona.visual.enabled and not (self.visual_reply_service is not None and hasattr(self.visual_reply_service, "request_generation")):
                add("warning", f"{persona.display_name} has Visual Reply enabled, but Visual Reply service is unavailable.", "visual")
        story_image = str(payload.get("story_image_path") or payload.get("cover_image_path") or "").strip() if payload else ""
        if story_image and not Path(story_image).exists():
            add("warning", f"Story image cannot be loaded: {story_image}", "story")
        for item in self._audiofx_items():
            file_path = str(item.get("file_path") or "").strip()
            label = str(item.get("description") or item.get("id") or "AudioFX")
            if not file_path:
                add("warning", f"AudioFX '{label}' has no audio file attached.", "audiofx")
            elif not Path(file_path).exists():
                add("error", f"AudioFX '{label}' file cannot be loaded: {file_path}", "audiofx")
        if self.story_sounds_enabled() and self._audiofx_items() and not self.available_story_audio_files():
            add("warning", "Story Sounds is enabled, but no ready AudioFX cues are indexed.", "audiofx")
        if not self.story_sounds_enabled() and self._audiofx_items():
            add("info", "Story Sounds is disabled, so LLM sound tags will be ignored.", "audiofx")
        if story_id:
            memory_payload = self.storage.load_story_memory(story_id)
            for note in list(memory_payload.get("_migration_log") or []):
                add("warning", f"Story memory migration/fallback: {note}", "schema")
        return {
            "ok": not any(item.get("severity") == "error" for item in issues),
            "issues": issues,
            "story_id": story_id,
            "checked_at": QtCore.QDateTime.currentDateTimeUtc().toString(QtCore.Qt.ISODate),
        }

    def _format_validation_result(self, result: dict[str, Any]) -> str:
        issues = list(result.get("issues") or [])
        if not issues:
            return f"OK: Story setup validation passed for {result.get('story_id') or 'current session'}."
        counts: dict[str, int] = {}
        for item in issues:
            key = str(item.get("severity") or "info").lower()
            counts[key] = counts.get(key, 0) + 1
        lines = [
            f"Validation for {result.get('story_id') or 'current session'} at {result.get('checked_at') or ''}",
            f"Errors: {counts.get('error', 0)} | Warnings: {counts.get('warning', 0)} | Info: {counts.get('info', 0)}",
            "",
        ]
        for item in issues:
            severity = str(item.get("severity") or "info").upper()
            kind = str(item.get("kind") or "validation")
            lines.append(f"[{severity}] {kind}: {item.get('message') or ''}")
        return "\n".join(lines)

    def _clear_story_event_log(self):
        self._story_event_log = []
        self.settings["story_event_log"] = []
        self.storage.save_settings(self.settings)
        self._refresh_event_log_panel()

    def _pre_apply_backup_relative_path(self) -> str:
        return "backups/pre_apply_latest.json"

    def _last_pre_apply_backup_exists(self) -> bool:
        try:
            return bool(self.context.storage.resolve(self._pre_apply_backup_relative_path()).exists())
        except Exception:
            return bool(self.storage._read_json(self._pre_apply_backup_relative_path(), {}))

    def _save_pre_apply_backup(self, reason: str = "Apply Draft") -> bool:
        try:
            memory = self.long_memory.load()
        except Exception:
            memory = {}
        payload = {
            "schema_version": 1,
            "created_at": QtCore.QDateTime.currentDateTimeUtc().toString(QtCore.Qt.ISODate),
            "reason": str(reason or "Apply Draft"),
            "active_story_id": self._current_story_id(),
            "active_story_payload": self._active_story_payload(),
            "personas": [persona.to_dict() for persona in self.personas],
            "session": self.session.to_dict(),
            "settings": copy.deepcopy(dict(self.settings or {})),
            "master_story_draft": copy.deepcopy(self._master_story_draft if isinstance(self._master_story_draft, dict) else {}),
            "long_memory": memory if isinstance(memory, dict) else {},
        }
        try:
            self.storage._write_json(self._pre_apply_backup_relative_path(), payload)
            self._record_story_event("pre-apply backup saved", severity="info", kind="recovery", persist=True)
            return True
        except Exception as exc:
            logger = getattr(self.context, "logger", None)
            if logger is not None:
                logger.warning("[MPRC] Failed to save pre-apply backup: %s", exc)
            self._record_story_event(f"backup skipped: {exc}", severity="warning", kind="recovery", persist=True)
            return False

    def _restore_last_pre_apply_backup(self):
        payload = self.storage._read_json(self._pre_apply_backup_relative_path(), {})
        if not isinstance(payload, dict) or not payload:
            self._warn("Restore Backup", "No pre-apply backup was found yet.")
            self._record_story_event("restore skipped: no pre-apply backup found", severity="warning", kind="recovery", persist=True)
            return
        personas = personas_from_payload(payload.get("personas"))
        if not personas:
            self._warn("Restore Backup", "The latest pre-apply backup does not contain a valid persona snapshot.")
            self._record_story_event("restore skipped: backup has no valid personas", severity="error", kind="recovery", persist=True)
            return
        session_payload = payload.get("session") if isinstance(payload.get("session"), dict) else {}
        settings_payload = payload.get("settings") if isinstance(payload.get("settings"), dict) else {}
        from .scenario_models import validate_story_extension
        if isinstance(settings_payload.get("active_scenario_extension"), dict):
            validate_story_extension({"scenario_extension": settings_payload["active_scenario_extension"], "personas": payload.get("personas", [])})
        self._stop_mprc_chat_playback()
        self.personas = personas
        self.session = RoleplaySessionState.from_dict(session_payload)
        self.settings = dict(settings_payload)
        self._mprc_play_active = bool(self.settings.get("mprc_play_isolated_active", False)) and bool(self.session.enabled)
        if isinstance(self.settings.get("active_scenario_extension"), dict):
            self._mprc_play_active = False
            self.settings["mprc_play_isolated_active"] = False
        self._story_event_log = self._load_story_event_log()
        draft = payload.get("master_story_draft")
        self._master_story_draft = copy.deepcopy(draft) if isinstance(draft, dict) else {}
        memory = payload.get("long_memory")
        if isinstance(memory, dict):
            self.long_memory.save(memory)
        self._ensure_session_persona()
        self.storage.save_settings(self.settings)
        self.save_state()
        self._story_audio_block_active = False
        self._story_audio_pending_text = ""
        self._last_story_audio_cues.clear()
        self._record_story_event("restored latest pre-apply backup", severity="info", kind="recovery", persist=True)
        self.refresh_ui()
        self._set_master_story_status("Restored latest pre-apply backup.")

    def _reset_current_story_only(
        self,
        _checked: bool = False,
        *,
        confirm: bool = True,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        story_id = self._current_story_id()
        if not story_id:
            self._warn("Reset Story", "No active story is loaded.")
            self._record_story_event("story reset skipped: no active story", severity="warning", kind="memory", persist=True)
            return {"accepted": False, "reason": "no_active_story"}
        if confirm and not confirmed:
            self._native_pending_confirmation = {
                "action": "reset_current_story",
                "title": "Reset This Story",
                "message": "Reset only this story's memory and runtime scene state? Personas, global app settings, and other saved stories will be kept.",
            }
            return {"accepted": False, "reason": "confirmation_required"}
        payload = self._active_story_payload()
        linked_ids = self._current_linked_persona_ids()
        try:
            self.long_memory.clear()
        except Exception as exc:
            self._record_story_event(f"memory reset warning: {exc}", severity="warning", kind="memory", persist=True)
        session_payload = payload.get("session") if isinstance(payload.get("session"), dict) else {}
        if session_payload:
            self.session = RoleplaySessionState.from_dict(session_payload)
            self.session.enabled = False
            if str(payload.get("mode") or "") in SESSION_MODES:
                self.session.mode = str(payload.get("mode"))
            if linked_ids:
                self.session.active_persona_id = self._story_persona_id(self.session.active_persona_id, linked_ids)
                self.session.current_speaker_id = self._story_persona_id(
                    self.session.current_speaker_id,
                    linked_ids,
                    fallback=self.session.active_persona_id,
                )
        else:
            self.session.turn_index = 0
            self.session.recent_events = []
            self.session.character_state_summaries = self._story_character_summaries(linked_ids)
            self.session.last_visual_reply_at = 0.0
            self.session.auto_image_count = 0
            self.session.ar_state.recent_events = []
            self.session.ar_state.pending_choices = []
            self.session.ar_state.player_intent = ""
            self.session.enabled = False
        self.settings["last_master_story_id"] = story_id
        self.settings["master_story_ready_to_start"] = True
        self._set_mprc_play_isolated_active(False)
        if payload.get("title"):
            self.settings["last_master_story_title"] = payload.get("title")
        if linked_ids:
            self.settings["master_story_linked_persona_ids"] = linked_ids
        self._story_audio_block_active = False
        self._story_audio_pending_text = ""
        self._last_story_audio_cues.clear()
        self._ensure_session_persona()
        self._save_story_memory_snapshot(story_id)
        self.storage.save_settings(self.settings)
        self.save_state()
        self._record_story_event(f"reset only this story: {story_id}", severity="info", kind="memory", persist=True)
        self.refresh_ui()
        message = f"Reset only story '{self.settings.get('last_master_story_title') or story_id}'. Other stories and global settings were kept."
        self._set_master_story_status(message)
        self._native_pending_confirmation = {}
        return {"accepted": True, "story_id": story_id, "message": message}
    def _ensure_demo_voice_samples(self) -> dict[str, str]:
        base_dir = self.context.storage.resolve("demo_story")
        base_dir.mkdir(parents=True, exist_ok=True)
        paths = {
            "narrator": base_dir / "demo_narrator_reference.wav",
            "character": base_dir / "demo_mira_reference.wav",
        }
        if not paths["narrator"].exists():
            self._write_test_audio_file(paths["narrator"], "hum")
        if not paths["character"].exists():
            self._write_test_audio_file(paths["character"], "magic")
        return {key: str(path) for key, path in paths.items()}

    def _demo_story_payload(self, voice_paths: dict[str, str] | None = None) -> dict[str, Any]:
        voices = dict(voice_paths or {})
        now = QtCore.QDateTime.currentDateTimeUtc().toString(QtCore.Qt.ISODate)
        return {
            "schema_version": RoleplayStorage.STORY_SCHEMA_VERSION,
            "id": "mprc_pipeline_demo",
            "title": "MPRC Pipeline Demo",
            "summary": "A compact built-in demo that exercises narrator routing, one character, Visual Reply story beats, AudioFX cues, and story memory.",
            "mode": AR_MODE,
            "updated_at": now,
            "active_persona_id": "mprc_demo_mira",
            "current_speaker_id": "mprc_demo_narrator",
            "avatar_visual_direction": "cinematic fantasy mystery portraits, warm lantern light, painterly realism, clear faces, no text",
            "session": {
                "enabled": True,
                "mode": AR_MODE,
                "scene_title": "The Lantern Door",
                "location": "A rain-soaked archive beneath an old inn",
                "time_of_day": "late night",
                "mood": "curious, tense, atmospheric",
                "objective": "Open the lantern-marked door and discover why it is humming.",
                "scene_summary": "The player and Mira stand before a lantern-marked archive door while rain taps through cracked stone above.",
                "ar_pacing": "Balanced",
                "ar_interaction_frequency": "Ask sometimes",
                "ar_dialogue_density": "Balanced narrator + character dialogue",
                "ar_state": {
                    "current_scene": "The lantern-marked door glows faintly at the end of the archive corridor.",
                    "location": "Rain-soaked archive",
                    "active_characters": ["mprc_demo_narrator", "mprc_demo_mira"],
                    "tension_level": 3,
                    "story_goal": "Learn what is behind the lantern-marked door.",
                    "recent_events": ["Mira found a wet key with a lantern symbol."],
                    "player_intent": "",
                    "pending_choices": ["Open the lantern door", "Ask Mira what she hears", "Wait and listen"],
                    "mood": "rainy mystery",
                    "time_of_day": "late night",
                },
            },
            "personas": [
                {
                    "id": "mprc_demo_narrator",
                    "display_name": "Demo Narrator",
                    "role": "narrator",
                    "description": "A clear cinematic narrator for the built-in MPRC demo story.",
                    "system_prompt": "Narrate the scene with concise audiobook pacing and clear consequences.",
                    "ar_profile_enabled": True,
                    "ar_description": "Primary narrator for the demo. Controls continuity, mood, camera-like framing, and pacing.",
                    "ar_system_prompt": "Use [NARRATOR] for scene framing. Characters only speak in their own [CHARACTER: Name] sections.",
                    "speaking_style": "calm, cinematic, atmospheric",
                    "behavior_mode": "narrator",
                    "memory_scope": "shared",
                    "tags": ["demo", "narrator"],
                    "voice": {
                        "enabled": True,
                        "backend": "chatterbox",
                        "sample_path": voices.get("narrator", ""),
                    },
                    "visual": {
                        "enabled": False,
                        "mode": "manual",
                        "provider": "inherit",
                        "size": "inherit",
                    },
                },
                {
                    "id": "mprc_demo_mira",
                    "display_name": "Mira",
                    "role": "archive guide",
                    "description": "A practical guide with a lantern and a dry sense of wonder.",
                    "system_prompt": "Speak as Mira only when the scene calls for her. Keep dialogue short and grounded.",
                    "ar_profile_enabled": True,
                    "ar_description": "Mira is the player's first companion in the demo: observant, brave, and lightly nervous.",
                    "ar_system_prompt": "Use [CHARACTER: Mira] only for Mira's dialogue or immediate reactions.",
                    "speaking_style": "warm, direct, quietly excited",
                    "behavior_mode": "group participant",
                    "memory_scope": "persona-only",
                    "tags": ["demo", "guide"],
                    "voice": {
                        "enabled": True,
                        "backend": "chatterbox",
                        "sample_path": voices.get("character", ""),
                    },
                    "visual": {
                        "enabled": True,
                        "mode": "auto_story_beat",
                        "provider": "inherit",
                        "size": "inherit",
                        "character_description": "young archive guide with a brass lantern, rain-damp cloak, expressive eyes, practical adventurer clothing",
                        "clothing_props": "brass lantern, wet cloak, leather satchel, old key",
                        "environment_style": "rain-soaked underground archive, warm lantern light, old stone, dust and water",
                        "negative_prompt": "text, watermark, logo, distorted hands, extra limbs",
                    },
                },
            ],
            "available_audio_cues": ["pub ambient", "rain storm", "magic shimmer", "danger stinger"],
        }

    def _load_demo_story(self):
        self._create_test_audiofx(show_status=False)
        voice_paths = self._ensure_demo_voice_samples()
        payload = self._normalize_master_story_payload(self._demo_story_payload(voice_paths))
        story_id = self.storage.save_story(payload)
        self._master_story_draft = payload
        self._set_master_story_sfw_from_payload(payload)
        actions: dict[str, str] = {}
        choices: dict[str, str] = {}
        for index, persona_payload in enumerate(list(payload.get("personas") or [])):
            persona_id = normalize_persona_id(persona_payload.get("id") or "")
            existing = self.persona_by_id(persona_id)
            actions[str(index)] = "reuse_update" if existing is not None else "__create__"
            choices[str(index)] = persona_id if existing is not None else "__create__"
        self._apply_master_story_payload(
            payload,
            apply_plan={
                "clear_memory": True,
                "auto_create": True,
                "auto_avatars": False,
                "backup_reason": "Load Demo Story",
                "persona_actions_by_row": actions,
                "persona_choices_by_row": choices,
            },
        )
        narrator = self.persona_by_id("mprc_demo_narrator")
        if narrator is not None:
            self.settings["narrator_persona_id"] = narrator.id
            self.settings["narrator_persona_mode"] = "explicit"
        try:
            self.long_memory.record_turn(
                session=self.session,
                personas=self.story_prompt_personas(),
                user_text="Demo story loaded.",
                assistant_text=(
                    "[NARRATOR]\nRain ticks through the cracked archive ceiling while the lantern-marked door hums.\n"
                    "[CHARACTER: Mira]\nIf it starts singing, I am blaming the key.\n"
                    "[AMBIENCE: rain storm]\n[CHOICES]\n- Open the lantern door\n- Ask Mira what she hears\n- Wait and listen"
                ),
            )
        except Exception as exc:
            self._record_story_event(f"demo memory warning: {exc}", severity="warning", kind="memory", persist=True)
        self._save_story_memory_snapshot(story_id)
        self.settings["native_selected_story_id"] = story_id
        self.storage.save_settings(self.settings)
        self.save_state()
        self._populate_master_stories()
        self._record_story_event("demo story loaded with narrator, Mira, Visual Reply trigger, AudioFX, and memory", severity="info", kind="demo", persist=True)
        self.refresh_ui()
        self._set_master_story_status("Loaded MPRC Pipeline Demo. Press Continue to test narrator, Mira, memory, Visual Reply policy, and AudioFX cues.")

    def _story_template_choices(self) -> list[tuple[str, str]]:
        return [
            ("fantasy_mystery", "Fantasy mystery"),
            ("sci_fi_horror", "Sci-fi horror"),
            ("cozy_tavern", "Cozy tavern adventure"),
        ]

    def _story_template_payload(self, template_id: str, voice_paths: dict[str, str] | None = None) -> dict[str, Any]:
        voices = dict(voice_paths or {})
        now = QtCore.QDateTime.currentDateTimeUtc().toString(QtCore.Qt.ISODate)
        specs = {
            "fantasy_mystery": {
                "id": "mprc_template_fantasy_mystery",
                "title": "The Lantern Ledger",
                "summary": "A fantasy mystery about a sealed inn cellar, a missing guest ledger, and a lantern that glows when someone lies.",
                "scene": "The Lantern Ledger",
                "location": "The cellar beneath the Rainwake Inn",
                "mood": "rainy, secretive, candlelit",
                "goal": "Discover who altered the guest ledger before dawn.",
                "character_id": "mprc_template_elara",
                "character": "Elara",
                "role": "innkeeper's sharp-eyed daughter",
                "character_description": "Elara carries a brass keyring and notices details others miss.",
                "voice_style": "quick, observant, quietly brave",
                "visual": "young fantasy innkeeper's daughter with brass keys, rain-dark hair, candlelit cellar, practical dress and leather apron",
                "audio": "rain storm",
                "recent": "Elara found wax on the ledger lock even though nobody lit candles near it.",
                "choice": "Ask Elara who had the cellar key",
            },
            "sci_fi_horror": {
                "id": "mprc_template_sci_fi_horror",
                "title": "Signal Under Deck Nine",
                "summary": "A sci-fi horror setup inside a damaged freighter where an impossible signal keeps answering before anyone speaks.",
                "scene": "Deck Nine Signal",
                "location": "A dark maintenance spine aboard the freighter Vesper",
                "mood": "claustrophobic, metallic, tense",
                "goal": "Find the source of the signal before the ship wakes something sealed below deck nine.",
                "character_id": "mprc_template_kade",
                "character": "Kade",
                "role": "ship engineer",
                "character_description": "Kade is a tired engineer who masks fear with procedure.",
                "voice_style": "low, clipped, technical, nervous",
                "visual": "sci-fi engineer in worn pressure jacket, handheld scanner, dark spaceship corridor, emergency red light, condensation on metal",
                "audio": "deep engine hum",
                "recent": "Kade heard the signal repeat the player's last breath pattern.",
                "choice": "Ask Kade to isolate the signal",
            },
            "cozy_tavern": {
                "id": "mprc_template_cozy_tavern",
                "title": "The Hearth That Remembered",
                "summary": "A cozy tavern adventure where the old hearth remembers every promise made beside it and one promise has gone missing.",
                "scene": "Remembering Hearth",
                "location": "The Amber Cup tavern during a gentle snowstorm",
                "mood": "warm, curious, comforting",
                "goal": "Learn which forgotten promise made the hearth dim.",
                "character_id": "mprc_template_brindle",
                "character": "Brindle",
                "role": "friendly tavern keeper",
                "character_description": "Brindle runs the tavern with warmth, humor, and a careful memory for regulars.",
                "voice_style": "warm, conversational, amused",
                "visual": "cozy fantasy tavern keeper with rolled sleeves, warm hearth glow, wooden mugs, snow outside the window, gentle smile",
                "audio": "pub ambient",
                "recent": "Brindle noticed the hearth went quiet when the old promise-stone cracked.",
                "choice": "Ask Brindle about the promise-stone",
            },
        }
        spec = specs.get(str(template_id or "").strip()) or specs["fantasy_mystery"]
        narrator_id = f"{spec['id']}_narrator"
        character_id = str(spec["character_id"])
        return {
            "schema_version": RoleplayStorage.STORY_SCHEMA_VERSION,
            "id": spec["id"],
            "title": spec["title"],
            "summary": spec["summary"],
            "mode": AR_MODE,
            "updated_at": now,
            "active_persona_id": character_id,
            "current_speaker_id": narrator_id,
            "narrator_persona_id": narrator_id,
            "narrator_persona_mode": "explicit",
            "avatar_visual_direction": "cinematic story portrait, expressive face, clear composition, no text, polished local adventure game style",
            "session": {
                "enabled": True,
                "mode": AR_MODE,
                "scene_title": spec["scene"],
                "location": spec["location"],
                "time_of_day": "opening scene",
                "mood": spec["mood"],
                "objective": spec["goal"],
                "scene_summary": spec["summary"],
                "ar_pacing": "Balanced",
                "ar_interaction_frequency": "Ask sometimes",
                "ar_dialogue_density": "Balanced narrator + character dialogue",
                "ar_state": {
                    "current_scene": spec["summary"],
                    "location": spec["location"],
                    "active_characters": [narrator_id, character_id],
                    "tension_level": 3,
                    "story_goal": spec["goal"],
                    "recent_events": [spec["recent"]],
                    "player_intent": "",
                    "pending_choices": [spec["choice"], "Continue listening", "Inspect the room"],
                    "mood": spec["mood"],
                    "time_of_day": "opening scene",
                },
            },
            "personas": [
                {
                    "id": narrator_id,
                    "display_name": f"{spec['title']} Narrator",
                    "role": "narrator",
                    "description": f"A cinematic narrator for {spec['title']}.",
                    "system_prompt": "Narrate with clear audiobook pacing, scene continuity, and visible consequences.",
                    "ar_profile_enabled": True,
                    "ar_description": "Story-owned narrator. Controls continuity, framing, pacing, and consequences.",
                    "ar_system_prompt": "Use [NARRATOR] for narration. Characters only speak in their own [CHARACTER: Name] sections.",
                    "speaking_style": "cinematic, clear, grounded",
                    "behavior_mode": "narrator",
                    "memory_scope": "shared",
                    "tags": ["template", "narrator"],
                    "voice": {"enabled": True, "backend": "chatterbox", "sample_path": voices.get("narrator", "")},
                    "visual": {"enabled": False, "mode": "manual", "provider": "inherit", "size": "inherit"},
                },
                {
                    "id": character_id,
                    "display_name": spec["character"],
                    "role": spec["role"],
                    "description": spec["character_description"],
                    "system_prompt": f"Speak as {spec['character']} only when the scene calls for direct dialogue.",
                    "ar_profile_enabled": True,
                    "ar_description": f"{spec['character']} is the first active character in this template. {spec['character_description']}",
                    "ar_system_prompt": f"Use [CHARACTER: {spec['character']}] only for direct spoken dialogue.",
                    "speaking_style": spec["voice_style"],
                    "behavior_mode": "group participant",
                    "memory_scope": "persona-only",
                    "tags": ["template", "story-character"],
                    "voice": {"enabled": True, "backend": "chatterbox", "sample_path": voices.get("character", "")},
                    "visual": {
                        "enabled": True,
                        "mode": "auto_story_beat",
                        "provider": "inherit",
                        "size": "inherit",
                        "character_description": spec["visual"],
                        "clothing_props": spec["visual"],
                        "environment_style": spec["location"],
                        "negative_prompt": "text, watermark, logo, distorted face, extra limbs",
                    },
                },
            ],
            "available_audio_cues": [spec["audio"], "magic shimmer", "danger stinger", "adventure music"],
        }

    def _load_selected_story_template(self):
        combo = self._controls.get("story_template")
        template_id = str(combo.currentData() if combo is not None else "fantasy_mystery").strip() or "fantasy_mystery"
        self._load_story_template(template_id)

    def _load_story_template(self, template_id: str):
        self._create_test_audiofx(show_status=False)
        voice_paths = self._ensure_demo_voice_samples()
        payload = self._normalize_master_story_payload(self._story_template_payload(template_id, voice_paths))
        story_id = self.storage.save_story(payload)
        self._master_story_draft = payload
        self._set_master_story_sfw_from_payload(payload)
        actions = {str(index): ("reuse_update" if self.persona_by_id(str(item.get("id") or "")) is not None else "__create__") for index, item in enumerate(payload.get("personas") or []) if isinstance(item, dict)}
        choices = {key: (normalize_persona_id((payload.get("personas") or [])[int(key)].get("id")) if action == "reuse_update" else "__create__") for key, action in actions.items()}
        self._apply_master_story_payload(
            payload,
            apply_plan={
                "clear_memory": True,
                "auto_create": True,
                "auto_avatars": False,
                "backup_reason": "Load Story Template",
                "persona_actions_by_row": actions,
                "persona_choices_by_row": choices,
            },
        )
        narrator_id = normalize_persona_id(payload.get("narrator_persona_id") or "")
        if narrator_id and self.persona_by_id(narrator_id) is not None:
            self.settings["narrator_persona_id"] = narrator_id
            self.settings["narrator_persona_mode"] = "explicit"
            self._persist_current_story_narrator_lock()
        try:
            self.long_memory.record_turn(
                session=self.session,
                personas=self.story_prompt_personas(),
                user_text="Story template loaded.",
                assistant_text=f"[NARRATOR]\n{payload.get('summary')}\n[AMBIENCE: {((payload.get('available_audio_cues') or ['pub ambient'])[0])}]\n[CHOICES]\n- Continue",
            )
        except Exception as exc:
            self._record_story_event(f"template memory warning: {exc}", severity="warning", kind="memory", persist=True)
        self._save_story_memory_snapshot(story_id)
        self.settings["native_selected_story_id"] = story_id
        self.storage.save_settings(self.settings)
        self.save_state()
        self._populate_master_stories()
        self._record_story_event(f"template loaded: {payload.get('title')}", severity="info", kind="template", persist=True)
        self.refresh_ui()
        self._set_master_story_status(f"Loaded template '{payload.get('title')}'. Validate it, then press Continue.")

    def _start_demo_validate_continue(self):
        self._load_demo_story()
        self._validate_story_setup_to_ui()
        self._test_audiofx_from_status()
        self._test_visual_reply_from_status()
        self._queue_continue_story(
            "Continue. Include one short [NARRATOR] beat and one short [CHARACTER: Mira] line if Mira is present."
        )
        self._record_story_event("first-run demo path started: demo loaded, validated, AudioFX/Visual tested, Continue queued", severity="info", kind="demo", persist=True)
        self._set_master_story_status("Started demo, validated setup, tested AudioFX/Visual Reply, and queued Continue.")

    def _queue_continue_story(self, text: str = "Continue") -> bool:
        message = str(text or "Continue").strip() or "Continue"
        try:
            result = dict(self.accepted_turns.submit(message, role="user") or {})
            if result.get("queued"):
                self._record_story_event(f"queued story input: {message[:120]}", severity="info", kind="runtime", persist=True)
                return True
            self._record_story_event(f"continue not queued: {result.get('reason', 'unknown')}", severity="warning", kind="runtime", persist=True)
        except Exception as exc:
            self._record_story_event(f"continue not queued: {exc}", severity="warning", kind="runtime", persist=True)
        self._native_clipboard_suggestion = message
        return False
    def _story_export_option_specs(self) -> list[dict[str, Any]]:
        return [
            {"key": "story_setup", "label": "Story setup / session state", "default": True, "file": "session.json"},
            {"key": "story_metadata", "label": "Story Library entry / story metadata", "default": True, "file": "story.json"},
            {"key": "personas", "label": "Personas used by this story", "default": True, "file": "personas.json"},
            {"key": "persona_visual", "label": "Persona visual settings", "default": True, "file": "persona_visual_settings.json"},
            {"key": "avatar_assets", "label": "Persona avatar image files", "default": True, "file": "assets/visuals/"},
            {"key": "persona_voice", "label": "Persona voice settings", "default": True, "file": "persona_voice_settings.json"},
            {"key": "voice_assets", "label": "Voice sample/audio files", "default": True, "file": "assets/voices/"},
            {"key": "story_memory", "label": "Story memory", "default": True, "file": "story_memory.json"},
            {"key": "story_events", "label": "Recent story events / story log", "default": True, "file": "story_events.json"},
            {"key": "audiofx", "label": "Sound effects / AudioFX settings", "default": True, "file": "audiofx.json"},
            {"key": "audiofx_assets", "label": "Sound effect audio files", "default": True, "file": "assets/audiofx/"},
            {"key": "visual_styles", "label": "Visual styles used by story", "default": True, "file": "visual_styles.json"},
            {"key": "master_story", "label": "Master Story draft/setup data if available", "default": True, "file": "master_story.json"},
            {"key": "templates", "label": "Story prompt/template data if available", "default": True, "file": "templates.json"},
        ]

    def _story_export_spec_by_key(self) -> dict[str, dict[str, Any]]:
        return {str(item.get("key") or ""): dict(item) for item in self._story_export_option_specs()}

    def _on_story_export_option_changed(self) -> None:
        if self._syncing:
            return
        self.settings["story_library_export_sections"] = self._story_export_selected_sections()
        self.storage.save_settings(self.settings)
        self._refresh_story_export_card()

    def _story_export_selected_sections(self) -> list[str]:
        raw = self.settings.get("story_library_export_sections")
        if isinstance(raw, list):
            selected = {str(item or "").strip() for item in raw}
            return [item for item in self._story_export_spec_by_key() if item in selected]
        return [str(item.get("key") or "") for item in self._story_export_option_specs() if bool(item.get("default", True))]

    def _story_export_story_id(self) -> str:
        selected = self._selected_master_story_id()
        return self.storage.story_id(selected or self._current_story_id() or "")

    def _story_export_story_payload(self) -> dict[str, Any]:
        story_id = self._story_export_story_id()
        payload = self.storage.load_story(story_id) if story_id else {}
        if isinstance(payload, dict) and payload:
            return payload
        snapshot = self._current_master_story_snapshot()
        return snapshot if isinstance(snapshot, dict) else {}

    def _story_export_persona_ids_from_story(self, story: dict[str, Any] | None = None) -> list[str]:
        story = dict(story or self._story_export_story_payload() or {})
        ids: list[str] = []

        def add(value: Any) -> None:
            persona_id = normalize_persona_id(value)
            if persona_id and persona_id not in ids:
                ids.append(persona_id)

        for key in ("narrator_persona_id", "active_persona_id", "current_speaker_id"):
            add(story.get(key))
        session = dict(story.get("session") or {}) if isinstance(story.get("session"), dict) else {}
        for key in ("narrator_persona_id", "active_persona_id", "current_speaker_id"):
            add(session.get(key))
        ar_state = dict(session.get("ar_state") or {}) if isinstance(session.get("ar_state"), dict) else {}
        for item in list(ar_state.get("active_characters") or []):
            add(item)
        for item in list(story.get("personas") or []):
            if isinstance(item, dict):
                add(item.get("id") or item.get("display_name"))
        overrides = story.get("persona_overrides")
        if isinstance(overrides, dict):
            for key in overrides:
                add(key)
        for item in [self.selected_narrator_persona_id(), *self._current_linked_persona_ids()]:
            add(item)
        return ids

    def _story_export_persona_configs(self, story: dict[str, Any] | None = None) -> list[PersonaConfig]:
        story = dict(story or self._story_export_story_payload() or {})
        ids = self._story_export_persona_ids_from_story(story)
        by_id = {persona.id: persona for persona in self.personas}
        result: list[PersonaConfig] = []
        seen: set[str] = set()
        for persona_id in ids:
            persona = by_id.get(persona_id)
            if persona is None:
                for item in list(story.get("personas") or []):
                    if isinstance(item, dict) and normalize_persona_id(item.get("id") or item.get("display_name")) == persona_id:
                        persona = PersonaConfig.from_dict(item)
                        break
            if persona is not None and persona.id not in seen:
                result.append(persona)
                seen.add(persona.id)
        if not result and self.personas:
            active = self.active_persona()
            if active is not None:
                result.append(active)
        return result

    def _story_export_visual_styles_for_personas(self, personas: list[PersonaConfig]) -> list[dict[str, str]]:
        used = {
            str(getattr(getattr(persona, "visual", None), "style_preset", "") or "").strip()
            for persona in list(personas or [])
        }
        used = {item for item in used if item}
        if not used:
            return []
        return [dict(item) for item in list(self.visual_styles or []) if str(item.get("id") or "").strip() in used]

    def _story_export_templates_payload(self) -> dict[str, Any]:
        templates = self.storage._read_json("roleplay_templates.json", {})
        payload: dict[str, Any] = {}
        if isinstance(templates, dict) and templates:
            payload["roleplay_templates"] = copy.deepcopy(templates)
        saved_prompts = self.settings.get("saved_audio_prompts")
        if isinstance(saved_prompts, list) and saved_prompts:
            payload["saved_audio_prompts"] = copy.deepcopy(saved_prompts)
        prompt = str(self.settings.get("master_story_prompt") or "").strip()
        if prompt:
            payload["current_master_story_prompt"] = prompt
        return payload

    def _story_export_availability(self) -> dict[str, dict[str, Any]]:
        story = self._story_export_story_payload()
        story_id = self.storage.story_id(story.get("id") or self._story_export_story_id() or "")
        personas = self._story_export_persona_configs(story)
        voice_paths = [
            str(getattr(getattr(persona, "voice", None), "sample_path", "") or "").strip()
            for persona in personas
        ]
        audio_items = self._audiofx_items()
        available_audio = self.available_story_audio_files()
        memory = self.storage.load_story_memory(story_id) if story_id else {}
        if not memory:
            try:
                loaded = self.long_memory.load()
                memory = loaded if isinstance(loaded, dict) else {}
            except Exception:
                memory = {}
        story_events = list(self._story_event_log or [])
        ar_state = getattr(self.session, "ar_state", None)
        session_events = list(getattr(self.session, "recent_events", []) or []) + list(getattr(ar_state, "recent_events", []) or [])
        visual_styles = self._story_export_visual_styles_for_personas(personas)
        templates = self._story_export_templates_payload()
        draft = self._master_story_draft if isinstance(self._master_story_draft, dict) else {}

        def item(available: bool, count: int = 0, detail: str = "") -> dict[str, Any]:
            return {"available": bool(available), "count": int(count or 0), "detail": str(detail or "")}

        return {
            "story_setup": item(bool(self.session), 1, "Current roleplay session state"),
            "story_metadata": item(bool(story), 1 if story else 0, story.get("title") or story_id),
            "personas": item(bool(personas), len(personas), f"{len(personas)} linked persona(s)"),
            "persona_visual": item(
                any(
                    bool(getattr(persona.visual, "enabled", False))
                    or any(str(getattr(persona.visual, field, "") or "").strip() for field in ("style_preset", "character_description", "clothing_props", "environment_style", "negative_prompt"))
                    for persona in personas
                ),
                len(personas),
                "Visual profile data",
            ),
            "avatar_assets": item(
                any(
                    str(getattr(persona, "character_image_path", "") or "").strip()
                    and Path(str(persona.character_image_path)).exists()
                    for persona in personas
                ),
                len([
                    persona
                    for persona in personas
                    if str(getattr(persona, "character_image_path", "") or "").strip()
                    and Path(str(persona.character_image_path)).exists()
                ]),
                "Existing local character/avatar image files",
            ),
            "persona_voice": item(
                any(bool(getattr(persona.voice, "enabled", False)) or str(getattr(persona.voice, "sample_path", "") or "").strip() for persona in personas),
                len([persona for persona in personas if bool(getattr(persona.voice, "enabled", False)) or str(getattr(persona.voice, "sample_path", "") or "").strip()]),
                "Per-persona voice routing settings",
            ),
            "voice_assets": item(
                any(path and Path(path).exists() for path in voice_paths),
                len([path for path in voice_paths if path and Path(path).exists()]),
                "Existing local voice sample files",
            ),
            "story_memory": item(bool(memory), 1 if memory else 0, "Saved story memory or active long memory"),
            "story_events": item(bool(story_events or session_events), len(story_events) + len(session_events), "Recent story events and story log"),
            "audiofx": item(bool(audio_items or available_audio or self.settings.get("saved_audio_prompts")), len(audio_items), "AudioFX settings and saved audio prompts"),
            "audiofx_assets": item(
                any(self._audiofx_file_ready(item) for item in audio_items) or any(Path(str(item.get("file_path") or "")).exists() for item in available_audio if isinstance(item, dict)),
                sum(1 for item in audio_items if self._audiofx_file_ready(item)),
                "Existing local AudioFX files",
            ),
            "visual_styles": item(bool(visual_styles), len(visual_styles), "Style presets referenced by linked personas"),
            "master_story": item(bool(story or draft), 1 if story or draft else 0, "Saved story payload and current draft"),
            "templates": item(bool(templates), len(templates), "Roleplay templates, saved prompts, or current story prompt"),
        }

    def _refresh_story_export_card(self) -> None:
        controls = self._controls.get("story_export_options")
        status = self._controls.get("story_export_status")
        if not isinstance(controls, dict) or not controls:
            return
        availability = self._story_export_availability()
        selected = set(self._story_export_selected_sections())
        spec_by_key = self._story_export_spec_by_key()
        available_selected = 0
        selected_count = 0
        for key, checkbox in controls.items():
            info = availability.get(str(key), {})
            available = bool(info.get("available"))
            if str(key) in selected:
                selected_count += 1
                if available:
                    available_selected += 1
            label = str(spec_by_key.get(str(key), {}).get("label") or key)
            detail = str(info.get("detail") or "")
            count = int(info.get("count") or 0)
            checkbox.setToolTip(f"{label}\n{'Available' if available else 'No data detected'}" + (f": {detail}" if detail else ""))
            checkbox.setStyleSheet(
                _mprc_checkbox_stylesheet("#22c55e", "700")
                if available
                else _mprc_checkbox_stylesheet("#9fb3c8", "600")
            )
            checkbox.setText(f"{label} ({count})" if available and count > 1 else label)
        if status is not None:
            story = self._story_export_story_payload()
            title = str(story.get("title") or self._story_export_story_id() or "current story").strip()
            status.setText(
                f"{available_selected}/{selected_count or len(selected)} selected sections have data for '{title}'. "
                "Green rows have data available to save; neutral rows have no matching data right now."
            )

    def _preview_story_package_contents(self) -> dict[str, Any]:
        availability = self._story_export_availability()
        selected = set(self._story_export_selected_sections())
        spec_by_key = self._story_export_spec_by_key()
        sections = []
        for key, spec in spec_by_key.items():
            if key not in selected:
                continue
            info = dict(availability.get(key, {}))
            sections.append(
                {
                    "key": key,
                    "label": str(spec.get("label") or key),
                    "available": bool(info.get("available")),
                    "detail": str(info.get("detail") or ""),
                }
            )
        self._native_story_export_preview = {"sections": sections}
        return copy.deepcopy(self._native_story_export_preview)
    def _story_bundle_settings(self) -> dict[str, Any]:
        keys = (
            "last_master_story_id",
            "last_master_story_title",
            "master_story_linked_persona_ids",
            "master_story_created_persona_ids",
            "master_story_persona_overrides",
            "master_story_avatar_style_sheets",
            "narrator_persona_id",
            "narrator_persona_mode",
            "story_sounds_enabled",
            "audio_fx_items",
            "available_audio_files",
            "saved_audio_prompts",
            "audiofx_volume",
            "audiofx_test_mode",
        )
        settings = {key: copy.deepcopy(self.settings.get(key)) for key in keys if key in self.settings}
        style_sheets = self._story_avatar_style_sheet_settings()
        if style_sheets:
            settings["persona_avatar_style_sheets"] = style_sheets
        return settings

    def _story_avatar_style_sheet_settings(self, story_id: str | None = None, persona_ids: list[str] | None = None) -> dict[str, Any]:
        raw = self.settings.get("persona_avatar_style_sheets")
        if not isinstance(raw, dict):
            return {}
        raw_story_id = str(story_id if story_id is not None else (self.settings.get("last_master_story_id") or self.settings.get("last_master_story_title") or "")).strip()
        normalized_story_id = self.storage.story_id(raw_story_id) if raw_story_id else ""
        linked = {
            normalize_persona_id(item)
            for item in list(persona_ids or self._current_linked_persona_ids())
            if str(item or "").strip()
        }
        result: dict[str, Any] = {}
        for persona_id, value in raw.items():
            normalized_persona_id = normalize_persona_id(persona_id)
            if not normalized_persona_id or not isinstance(value, dict):
                continue
            raw_item_story_id = str(value.get("story_id") or "").strip()
            item_story_id = self.storage.story_id(raw_item_story_id) if raw_item_story_id else ""
            if normalized_story_id and item_story_id == normalized_story_id:
                result[normalized_persona_id] = copy.deepcopy(value)
            elif normalized_persona_id in linked and not item_story_id:
                result[normalized_persona_id] = copy.deepcopy(value)
        return result

    def _merge_story_avatar_style_sheet_settings(self, value: Any) -> None:
        if not isinstance(value, dict):
            return
        current = self.settings.get("persona_avatar_style_sheets")
        merged: dict[str, Any] = dict(current or {}) if isinstance(current, dict) else {}
        changed = False
        for persona_id, item in value.items():
            normalized_persona_id = normalize_persona_id(persona_id)
            if not normalized_persona_id or not isinstance(item, dict):
                continue
            merged[normalized_persona_id] = copy.deepcopy(item)
            changed = True
        if changed:
            self.settings["persona_avatar_style_sheets"] = merged

    def _build_story_bundle(self) -> dict[str, Any]:
        story_id = self._current_story_id()
        story = self._active_story_payload() if story_id else self._current_master_story_snapshot()
        linked = self._current_linked_persona_ids()
        if not linked:
            linked = [persona.id for persona in self.personas]
        personas = [persona.to_dict() for persona in self.personas if persona.id in set(linked)]
        memory = self.storage.load_story_memory(story_id) if story_id else {}
        return {
            "schema_version": 1,
            "bundle_type": "mprc_story_bundle",
            "exported_at": QtCore.QDateTime.currentDateTimeUtc().toString(QtCore.Qt.ISODate),
            "story_id": story_id or story.get("id"),
            "story": story,
            "personas": personas,
            "settings": self._story_bundle_settings(),
            "session": self.session.to_dict(),
            "memory_snapshot": memory,
            "prompts": {
                "master_story_draft": copy.deepcopy(self._master_story_draft),
                "debug_prompt": self._debug_prompt,
                "debug_visual_prompt": self._debug_visual_prompt,
            },
            "audiofx": {
                "items": list(self._audiofx_items()),
                "available_audio_files": list(self.available_story_audio_files()),
                "saved_audio_prompts": list(self.settings.get("saved_audio_prompts") or []),
            },
            "visual_settings": {
                persona.id: persona.visual.to_dict() for persona in self.personas if persona.id in set(linked)
            },
            "voice_routing": self._build_voice_routing_inspector_text(),
            "narrator": {
                "persona_id": self.selected_narrator_persona_id(),
                "mode": self._narrator_selection_mode(),
                "display_name": self.selected_narrator_persona().display_name if self.selected_narrator_persona() is not None else "",
            },
        }

    def _story_package_safe_name(self, value: Any, fallback: str = "asset") -> str:
        text = str(value or "").strip()
        safe = []
        previous = False
        for char in text:
            if char.isalnum() or char in {".", "_", "-"}:
                safe.append(char)
                previous = False
            elif not previous:
                safe.append("_")
                previous = True
        result = "".join(safe).strip("._-")
        return result[:96] or fallback

    def _story_package_scrub_runtime_paths(self, value: Any) -> Any:
        path_keys = {"sample_path", "file_path", "character_image_path", "story_image_path", "cover_image_path", "image_path"}
        if isinstance(value, list):
            return [self._story_package_scrub_runtime_paths(item) for item in value]
        if not isinstance(value, dict):
            return copy.deepcopy(value)
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text in path_keys and isinstance(item, str):
                text = str(item or "").strip().replace("\\", "/")
                cleaned[key] = text if text.startswith("assets/") else ""
            else:
                cleaned[key] = self._story_package_scrub_runtime_paths(item)
        return cleaned

    def _story_package_unique_asset_path(self, folder: str, key: str, source_path: Path, used: set[str]) -> str:
        stem = self._story_package_safe_name(key, "asset")
        name = self._story_package_safe_name(source_path.name, "file")
        candidate = f"assets/{folder}/{stem}_{name}"
        counter = 2
        while candidate.lower() in used:
            candidate = f"assets/{folder}/{stem}_{counter}_{name}"
            counter += 1
        used.add(candidate.lower())
        return candidate

    def _copy_package_asset(
        self,
        zip_handle: zipfile.ZipFile,
        source_path: str,
        asset_path: str,
        asset_key: str,
        asset_file_map: dict[str, Any],
        warnings: list[str],
    ) -> bool:
        raw = str(source_path or "").strip()
        if not raw:
            return False
        path = Path(raw)
        if not path.exists() or not path.is_file():
            warnings.append(f"Missing asset for {asset_key}: {raw}")
            return False
        try:
            zip_handle.write(str(path), asset_path)
            asset_file_map[asset_key] = {
                "asset_path": asset_path,
                "file_name": path.name,
                "source_path": str(path),
            }
            return True
        except Exception as exc:
            warnings.append(f"Could not copy asset for {asset_key}: {exc}")
            return False

    def _build_story_package_manifest(
        self,
        *,
        story: dict[str, Any],
        included_sections: list[str],
        asset_file_map: dict[str, Any],
        warnings: list[str],
    ) -> dict[str, Any]:
        addon_version = str(self.context.addon_version or "")
        story_id = self.storage.story_id(story.get("id") or self._story_export_story_id() or "story")
        return {
            "package_schema_version": 1,
            "addon_id": "nc.multi_persona_roleplay",
            "addon_version": addon_version,
            "exported_at": QtCore.QDateTime.currentDateTimeUtc().toString(QtCore.Qt.ISODate),
            "story_title": str(story.get("title") or story_id).strip() or story_id,
            "story_id": story_id,
            "included_sections": list(included_sections or []),
            "asset_file_map": copy.deepcopy(asset_file_map),
            "warnings": list(warnings or []),
            "source_paths": {
                key: str(value.get("source_path") or "")
                for key, value in asset_file_map.items()
                if isinstance(value, dict) and str(value.get("source_path") or "").strip()
            },
        }

    def _story_package_persona_payloads(
        self,
        personas: list[PersonaConfig],
        sections: set[str],
        voice_asset_paths: dict[str, str],
        avatar_asset_paths: dict[str, str] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
        include_visual = "persona_visual" in sections
        include_voice = "persona_voice" in sections
        avatar_asset_paths = dict(avatar_asset_paths or {})
        personas_payload: list[dict[str, Any]] = []
        visual_settings: dict[str, Any] = {}
        voice_settings: dict[str, Any] = {}
        for persona in list(personas or []):
            payload = persona.to_dict()
            visual_payload = copy.deepcopy(payload.get("visual") or {})
            voice_payload = copy.deepcopy(payload.get("voice") or {})
            avatar_asset_path = str(avatar_asset_paths.get(persona.id, "") or "")
            asset_path = voice_asset_paths.get(persona.id, "")
            if asset_path:
                voice_payload["sample_path"] = asset_path
            elif str(voice_payload.get("sample_path") or "").strip():
                voice_payload["sample_path"] = ""
            if include_visual:
                visual_settings[persona.id] = {
                    "visual": visual_payload,
                    "character_image_path": avatar_asset_path,
                }
            else:
                payload.pop("visual", None)
            payload["character_image_path"] = avatar_asset_path
            if include_voice:
                voice_settings[persona.id] = voice_payload
                payload["voice"] = voice_payload
            else:
                payload.pop("voice", None)
            personas_payload.append(payload)
        return personas_payload, visual_settings, voice_settings

    def _story_package_audiofx_payload(
        self,
        sections: set[str],
        audiofx_asset_paths: dict[str, str],
    ) -> dict[str, Any]:
        items = []
        for item in self._audiofx_items():
            payload = dict(item)
            key = str(payload.get("id") or self._audio_file_key(payload.get("file_path", "")) or "").strip()
            asset_path = audiofx_asset_paths.get(key, "")
            if asset_path:
                payload["file_path"] = asset_path
            elif str(payload.get("file_path") or "").strip():
                payload["file_path"] = ""
            items.append(payload)
        available = []
        for item in self.available_story_audio_files():
            payload = dict(item)
            key = str(payload.get("source_audiofx_id") or payload.get("id") or self._audio_file_key(payload.get("file_path", "")) or "").strip()
            asset_path = audiofx_asset_paths.get(key, "")
            if asset_path:
                payload["file_path"] = asset_path
                payload["ready"] = True
            elif str(payload.get("file_path") or "").strip():
                payload["file_path"] = ""
                payload["ready"] = False
            available.append(payload)
        return {
            "items": items,
            "available_audio_files": available,
            "saved_audio_prompts": copy.deepcopy(list(self.settings.get("saved_audio_prompts") or [])),
            "story_sounds_enabled": bool(self.settings.get("story_sounds_enabled", True)),
            "audiofx_volume": self.settings.get("audiofx_volume"),
        }

    def _write_story_package(self, path: str | Path, sections: list[str] | None = None) -> tuple[dict[str, Any], list[str]]:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        selected = list(sections or self._story_export_selected_sections())
        section_set = set(selected)
        story = self._story_export_story_payload()
        story_id = self.storage.story_id(story.get("id") or self._story_export_story_id() or "story")
        if not story:
            story = self._current_master_story_snapshot()
        personas = self._story_export_persona_configs(story)
        warnings: list[str] = []
        asset_file_map: dict[str, Any] = {}
        used_assets: set[str] = set()
        voice_asset_paths: dict[str, str] = {}
        avatar_asset_paths: dict[str, str] = {}
        audiofx_asset_paths: dict[str, str] = {}
        voice_asset_sources: list[tuple[str, str, str]] = []
        avatar_asset_sources: list[tuple[str, str, str]] = []
        audio_asset_sources: list[tuple[str, str, str]] = []

        if "voice_assets" in section_set:
            for persona in personas:
                sample_path = str(getattr(getattr(persona, "voice", None), "sample_path", "") or "").strip()
                if not sample_path:
                    continue
                source = Path(sample_path)
                if source.exists() and source.is_file():
                    asset_path = self._story_package_unique_asset_path("voices", persona.id, source, used_assets)
                    voice_asset_paths[persona.id] = asset_path
                    voice_asset_sources.append((f"voice:{persona.id}", sample_path, asset_path))
                else:
                    warnings.append(f"Missing voice sample for {persona.display_name}: {sample_path}")

        if "avatar_assets" in section_set:
            for persona in personas:
                image_path = str(getattr(persona, "character_image_path", "") or "").strip()
                if not image_path:
                    continue
                source = Path(image_path)
                if source.exists() and source.is_file():
                    asset_path = self._story_package_unique_asset_path("visuals", persona.id, source, used_assets)
                    avatar_asset_paths[persona.id] = asset_path
                    avatar_asset_sources.append((f"avatar:{persona.id}", image_path, asset_path))
                else:
                    warnings.append(f"Missing avatar image for {persona.display_name}: {image_path}")

        if "audiofx_assets" in section_set:
            for item in self._audiofx_items():
                file_path = str(item.get("file_path") or "").strip()
                if not file_path:
                    continue
                source = Path(file_path)
                key = str(item.get("id") or self._audio_file_key(file_path) or source.stem).strip()
                if source.exists() and source.is_file():
                    asset_path = self._story_package_unique_asset_path("audiofx", key, source, used_assets)
                    audiofx_asset_paths[key] = asset_path
                    audio_asset_sources.append((f"audiofx:{key}", file_path, asset_path))
                else:
                    warnings.append(f"Missing AudioFX file for {item.get('description') or key}: {file_path}")

        personas_payload, visual_settings, voice_settings = self._story_package_persona_payloads(personas, section_set, voice_asset_paths, avatar_asset_paths)
        package_story = self._story_package_scrub_runtime_paths(story)
        json_files: dict[str, Any] = {}
        if "story_setup" in section_set:
            json_files["session.json"] = self.session.to_dict()
        if "story_metadata" in section_set:
            json_files["story.json"] = package_story
        if "personas" in section_set:
            json_files["personas.json"] = personas_payload
        if "persona_visual" in section_set:
            json_files["persona_visual_settings.json"] = visual_settings
        if "avatar_assets" in section_set:
            json_files["avatar_images.json"] = {
                persona.id: {
                    "display_name": persona.display_name,
                    "character_image_path": avatar_asset_paths.get(persona.id, ""),
                }
                for persona in personas
                if avatar_asset_paths.get(persona.id)
            }
        if "persona_voice" in section_set:
            json_files["persona_voice_settings.json"] = voice_settings
        if "story_memory" in section_set:
            memory = self.storage.load_story_memory(story_id) if story_id else {}
            if not memory:
                try:
                    memory = self.long_memory.load()
                except Exception:
                    memory = {}
            json_files["story_memory.json"] = self._story_package_scrub_runtime_paths(memory if isinstance(memory, dict) else {})
        if "story_events" in section_set:
            ar_state = getattr(self.session, "ar_state", None)
            json_files["story_events.json"] = {
                "story_event_log": copy.deepcopy(list(self._story_event_log or [])),
                "session_recent_events": list(getattr(self.session, "recent_events", []) or []),
                "ar_recent_events": list(getattr(ar_state, "recent_events", []) or []),
            }
        if "audiofx" in section_set:
            json_files["audiofx.json"] = self._story_package_audiofx_payload(section_set, audiofx_asset_paths)
        if "visual_styles" in section_set:
            json_files["visual_styles.json"] = self._story_export_visual_styles_for_personas(personas)
        if "master_story" in section_set:
            json_files["master_story.json"] = {
                "draft": self._story_package_scrub_runtime_paths(self._master_story_draft if isinstance(self._master_story_draft, dict) else {}),
                "active_story": package_story,
                "generation_constraints": self._master_story_generation_constraints(),
            }
        if "templates" in section_set:
            json_files["templates.json"] = self._story_export_templates_payload()

        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as handle:
            for asset_key, source_path, asset_path in voice_asset_sources + avatar_asset_sources + audio_asset_sources:
                self._copy_package_asset(handle, source_path, asset_path, asset_key, asset_file_map, warnings)
            manifest = self._build_story_package_manifest(
                story=story,
                included_sections=selected,
                asset_file_map=asset_file_map,
                warnings=warnings,
            )
            handle.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=True))
            for file_name, payload in json_files.items():
                handle.writestr(file_name, json.dumps(payload, indent=2, ensure_ascii=True))
        return manifest, warnings

    def _export_story_package(self):
        story_id = self._story_export_story_id() or "mprc_story"
        default_path = Path.home() / f"{story_id}.mprcstory.zip"
        path = self._save_file(
            "Export Story Library package",
            str(default_path),
            "MPRC story packages (*.mprcstory.zip *.storypackage.zip);;Zip files (*.zip)",
        )
        if not path:
            self._set_master_story_status("Story Library Export cancelled.")
            return
        if not str(path).lower().endswith((".mprcstory.zip", ".storypackage.zip", ".zip")):
            path = str(path) + ".mprcstory.zip"
        try:
            manifest, warnings = self._write_story_package(path, self._story_export_selected_sections())
        except Exception as exc:
            self._warn("Story Library Export", f"Export failed:\n\n{exc}")
            self._set_master_story_status(f"Story Library Export failed: {exc}")
            return
        warning_note = f" with {len(warnings)} warning{'s' if len(warnings) != 1 else ''}" if warnings else ""
        self._record_story_event(f"exported story library package: {path}{warning_note}", severity="info", kind="package", persist=True)
        self._set_master_story_status(f"Exported Story Library package '{manifest.get('story_title')}' to {path}{warning_note}.")
        self._refresh_story_export_card()

    def _read_package_json(self, zip_handle: zipfile.ZipFile, file_name: str, fallback: Any) -> Any:
        try:
            if file_name not in zip_handle.namelist():
                return fallback
            return json.loads(zip_handle.read(file_name).decode("utf-8"))
        except Exception:
            return fallback

    def _read_story_package_manifest(self, path: str | Path) -> tuple[dict[str, Any], list[str]]:
        warnings: list[str] = []
        try:
            with zipfile.ZipFile(path, "r") as handle:
                manifest = self._read_package_json(handle, "manifest.json", {})
        except Exception as exc:
            raise ValueError(f"Could not open story package: {exc}") from exc
        if not isinstance(manifest, dict) or not manifest:
            raise ValueError("Package is missing manifest.json.")
        try:
            schema_version = int(manifest.get("package_schema_version", 0) or 0)
        except Exception:
            schema_version = 0
        if schema_version < 1:
            raise ValueError("Package manifest has no supported schema version.")
        if schema_version > 1:
            warnings.append(f"Package schema {schema_version} is newer than this addon; importing with v1 fallback.")
        if str(manifest.get("addon_id") or "") not in {"", "nc.multi_persona_roleplay"}:
            warnings.append(f"Package addon id is {manifest.get('addon_id')}; expected nc.multi_persona_roleplay.")
        return manifest, warnings

    def _confirm_story_package_import(
        self,
        manifest: dict[str, Any],
        warnings: list[str],
        *,
        confirmed: bool = False,
    ) -> bool:
        self._native_story_import_review = {
            "title": str(manifest.get("story_title") or manifest.get("story_id") or "Untitled"),
            "included_sections": [str(item) for item in list(manifest.get("included_sections") or [])],
            "asset_count": len(dict(manifest.get("asset_file_map") or {})),
            "warnings": [str(item) for item in list(warnings or [])[:8]],
        }
        return bool(confirmed)
    def _import_story_package(self):
        path = self._open_file(
            "Import Story Library package",
            str(Path.home()),
            "MPRC story packages (*.mprcstory.zip *.storypackage.zip);;Zip files (*.zip)",
        )
        if not path:
            self._set_master_story_status("Story Library Import cancelled.")
            return
        try:
            manifest, warnings = self._read_story_package_manifest(path)
        except Exception as exc:
            self._warn("Story Library Import", str(exc))
            self._set_master_story_status(f"Story Library Import failed: {exc}")
            return
        all_warnings = warnings + [str(item) for item in list(manifest.get("warnings") or []) if str(item or "").strip()]
        if not self._confirm_story_package_import(manifest, all_warnings):
            self._set_master_story_status("Story Library Import cancelled.")
            return
        try:
            result = self._apply_story_package(path, manifest=manifest)
        except Exception as exc:
            self._warn("Story Library Import", f"Import failed:\n\n{exc}")
            self._set_master_story_status(f"Story Library Import failed: {exc}")
            return
        warnings = list(result.get("warnings") or [])
        story_title = str(result.get("story_title") or result.get("story_id") or "story").strip()
        warning_note = f" with {len(warnings)} warning{'s' if len(warnings) != 1 else ''}" if warnings else ""
        self._record_story_event(f"imported story library package: {path}{warning_note}", severity="info", kind="package", persist=True)
        self.refresh_ui()
        self._set_master_story_status(f"Imported Story Library package '{story_title}'{warning_note}.")

    def _story_package_import_asset_root(self, manifest: dict[str, Any]) -> Path:
        story_id = self.storage.story_id((manifest or {}).get("story_id") or (manifest or {}).get("story_title") or "imported_story")
        return self.context.storage.resolve(f"assets/story_packages/imported/{story_id}")

    def _extract_package_assets(self, zip_handle: zipfile.ZipFile, manifest: dict[str, Any], warnings: list[str]) -> dict[str, str]:
        asset_file_map = manifest.get("asset_file_map")
        if not isinstance(asset_file_map, dict) or not asset_file_map:
            return {}
        root = self._story_package_import_asset_root(manifest)
        extracted: dict[str, str] = {}
        names = set(zip_handle.namelist())
        for asset_key, item in asset_file_map.items():
            if not isinstance(item, dict):
                continue
            asset_path = str(item.get("asset_path") or "").replace("\\", "/").strip()
            if not asset_path or asset_path.startswith("/") or ".." in Path(asset_path).parts:
                warnings.append(f"Skipped unsafe asset path for {asset_key}: {asset_path}")
                continue
            if asset_path not in names:
                warnings.append(f"Package asset missing for {asset_key}: {asset_path}")
                continue
            if asset_path.startswith("assets/voices/"):
                folder = "voices"
            elif asset_path.startswith("assets/audiofx/"):
                folder = "audiofx"
            elif asset_path.startswith("assets/visuals/"):
                folder = "visuals"
            else:
                folder = "misc"
            target = root / folder / self._story_package_safe_name(Path(asset_path).name, "asset")
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zip_handle.read(asset_path))
                extracted[asset_path] = str(target)
            except Exception as exc:
                warnings.append(f"Could not extract {asset_path}: {exc}")
        return extracted

    def _remap_imported_asset_paths(self, value: Any, extracted_assets: dict[str, str]) -> Any:
        if isinstance(value, str):
            return extracted_assets.get(value, value)
        if isinstance(value, list):
            return [self._remap_imported_asset_paths(item, extracted_assets) for item in value]
        if isinstance(value, dict):
            return {key: self._remap_imported_asset_paths(item, extracted_assets) for key, item in value.items()}
        return value

    def _remap_persona_id_value(self, value: Any, id_map: dict[str, str]) -> Any:
        normalized = normalize_persona_id(value)
        return id_map.get(normalized, value)

    def _remap_story_payload_persona_ids(self, payload: dict[str, Any], id_map: dict[str, str]) -> dict[str, Any]:
        story = copy.deepcopy(dict(payload or {}))
        extension = story.get("scenario_extension")
        if isinstance(extension, dict):
            for role in extension.get("roles", []):
                role["persona_id"] = id_map.get(role["persona_id"], role["persona_id"])
        if not id_map:
            return story
        for key in ("narrator_persona_id", "active_persona_id", "current_speaker_id"):
            if key in story:
                story[key] = self._remap_persona_id_value(story.get(key), id_map)
        session = dict(story.get("session") or {}) if isinstance(story.get("session"), dict) else {}
        for key in ("narrator_persona_id", "active_persona_id", "current_speaker_id"):
            if key in session:
                session[key] = self._remap_persona_id_value(session.get(key), id_map)
        ar_state = dict(session.get("ar_state") or {}) if isinstance(session.get("ar_state"), dict) else {}
        if isinstance(ar_state.get("active_characters"), list):
            ar_state["active_characters"] = [self._remap_persona_id_value(item, id_map) for item in ar_state.get("active_characters") or []]
        session["ar_state"] = ar_state
        if session:
            story["session"] = session
        personas = []
        for item in list(story.get("personas") or []):
            if isinstance(item, dict):
                persona = dict(item)
                old_id = normalize_persona_id(persona.get("id") or persona.get("display_name"))
                if old_id in id_map:
                    persona["id"] = id_map[old_id]
                personas.append(persona)
        if personas:
            story["personas"] = personas
        overrides = story.get("persona_overrides")
        if isinstance(overrides, dict):
            remapped = {}
            for key, value in overrides.items():
                remapped[str(self._remap_persona_id_value(key, id_map))] = copy.deepcopy(value)
            story["persona_overrides"] = remapped
        return story

    def _remap_story_memory_persona_ids(self, payload: dict[str, Any], id_map: dict[str, str], story_id: str) -> dict[str, Any]:
        memory = copy.deepcopy(dict(payload or {}))
        memory["story_id"] = story_id
        if not id_map:
            return memory
        session = memory.get("session")
        if isinstance(session, dict):
            remapped_story = self._remap_story_payload_persona_ids({"session": session}, id_map)
            memory["session"] = remapped_story.get("session", session)
        settings = memory.get("settings")
        if isinstance(settings, dict):
            for key in ("narrator_persona_id",):
                if key in settings:
                    settings[key] = self._remap_persona_id_value(settings.get(key), id_map)
            for key in ("master_story_linked_persona_ids", "master_story_created_persona_ids"):
                if isinstance(settings.get(key), list):
                    settings[key] = [self._remap_persona_id_value(item, id_map) for item in settings.get(key) or []]
            overrides = settings.get("master_story_persona_overrides")
            if isinstance(overrides, dict):
                settings["master_story_persona_overrides"] = {
                    str(self._remap_persona_id_value(key, id_map)): copy.deepcopy(value)
                    for key, value in overrides.items()
                }
        long_memory = memory.get("long_memory")
        if isinstance(long_memory, dict):
            for key in ("character_memory",):
                value = long_memory.get(key)
                if isinstance(value, dict):
                    long_memory[key] = {
                        str(self._remap_persona_id_value(persona_id, id_map)): copy.deepcopy(item)
                        for persona_id, item in value.items()
                    }
            active = long_memory.get("active_character_ids")
            if isinstance(active, list):
                long_memory["active_character_ids"] = [self._remap_persona_id_value(item, id_map) for item in active]
        return memory

    def _unique_story_id(self, story_id: str) -> str:
        base = self.storage.story_id(story_id or "imported_story")
        existing = {str(item.get("id") or "").strip() for item in self.storage.load_story_index()}
        if base not in existing:
            return base
        candidate = f"{base}_imported"
        counter = 2
        while candidate in existing:
            candidate = f"{base}_imported_{counter}"
            counter += 1
        return candidate

    def _apply_imported_personas(self, payload: Any, warnings: list[str]) -> dict[str, str]:
        imported = personas_from_payload(payload)
        if not imported:
            return {}
        existing_ids = {persona.id for persona in self.personas}
        id_map: dict[str, str] = {}
        for persona in imported:
            original_id = persona.id
            if persona.id in existing_ids:
                persona.id = unique_persona_id(f"{persona.id}_imported", existing_ids)
                if "(Imported)" not in persona.display_name:
                    persona.display_name = f"{persona.display_name} (Imported)"
                warnings.append(f"Persona id '{original_id}' already existed; imported as '{persona.id}'.")
            id_map[original_id] = persona.id
            existing_ids.add(persona.id)
            self.personas.append(persona)
        return id_map

    def _apply_imported_voice_settings(self, payload: Any, id_map: dict[str, str]) -> None:
        if not isinstance(payload, dict):
            return
        by_id = {persona.id: persona for persona in self.personas}
        for key, voice in payload.items():
            persona_id = str(self._remap_persona_id_value(key, id_map))
            persona = by_id.get(persona_id)
            if persona is None or not isinstance(voice, dict):
                continue
            updated = PersonaConfig.from_dict({**persona.to_dict(), "voice": voice})
            persona.voice = updated.voice

    def _apply_imported_visual_settings(self, payload: Any, id_map: dict[str, str]) -> None:
        if not isinstance(payload, dict):
            return
        by_id = {persona.id: persona for persona in self.personas}
        for key, visual_payload in payload.items():
            persona_id = str(self._remap_persona_id_value(key, id_map))
            persona = by_id.get(persona_id)
            if persona is None or not isinstance(visual_payload, dict):
                continue
            merged = persona.to_dict()
            if isinstance(visual_payload.get("visual"), dict):
                merged["visual"] = visual_payload.get("visual")
            if "character_image_path" in visual_payload:
                merged["character_image_path"] = str(visual_payload.get("character_image_path") or "")
            updated = PersonaConfig.from_dict(merged)
            persona.visual = updated.visual
            persona.character_image_path = updated.character_image_path

    def _apply_imported_avatar_images(self, payload: Any, id_map: dict[str, str]) -> None:
        if not isinstance(payload, dict):
            return
        by_id = {persona.id: persona for persona in self.personas}
        for key, item in payload.items():
            persona_id = str(self._remap_persona_id_value(key, id_map))
            persona = by_id.get(persona_id)
            if persona is None:
                continue
            image_path = ""
            if isinstance(item, dict):
                image_path = str(item.get("character_image_path") or "").strip()
            elif isinstance(item, str):
                image_path = str(item or "").strip()
            if image_path:
                persona.character_image_path = image_path

    def _merge_imported_audiofx(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        imported_items = [dict(item) for item in list(payload.get("items") or []) if isinstance(item, dict)]
        if not imported_items:
            return
        existing = self._audiofx_items()
        existing_ids = {str(item.get("id") or "").strip() for item in existing}
        merged = list(existing)
        for item in imported_items:
            base = str(item.get("id") or self._new_audiofx_id(merged)).strip() or self._new_audiofx_id(merged)
            item_id = base
            counter = 2
            while item_id in existing_ids:
                item_id = f"{base}_imported_{counter}"
                counter += 1
            item["id"] = item_id
            existing_ids.add(item_id)
            merged.append(item)
        if "story_sounds_enabled" in payload:
            self.settings["story_sounds_enabled"] = bool(payload.get("story_sounds_enabled"))
        if payload.get("audiofx_volume") is not None:
            self.settings["audiofx_volume"] = payload.get("audiofx_volume")
        saved = payload.get("saved_audio_prompts")
        if isinstance(saved, list) and saved:
            current = [item for item in list(self.settings.get("saved_audio_prompts") or []) if isinstance(item, dict)]
            current.extend(dict(item) for item in saved if isinstance(item, dict))
            self.settings["saved_audio_prompts"] = current[-100:]
        self._save_audiofx_items(merged)

    def _merge_imported_visual_styles(self, payload: Any) -> None:
        if not isinstance(payload, list):
            return
        current = [dict(item) for item in list(self.visual_styles or []) if isinstance(item, dict)]
        seen = {str(item.get("id") or "").strip() for item in current}
        changed = False
        for item in payload:
            if not isinstance(item, dict):
                continue
            style_id = str(item.get("id") or "").strip()
            if not style_id or style_id in seen:
                continue
            current.append(dict(item))
            seen.add(style_id)
            changed = True
        if changed:
            self.visual_styles = current
            self.storage._write_json("visual_styles.json", current)

    def _merge_imported_templates(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        templates = payload.get("roleplay_templates")
        if isinstance(templates, dict):
            current = self.storage._read_json("roleplay_templates.json", {})
            current = dict(current or {}) if isinstance(current, dict) else {}
            changed = False
            for key, value in templates.items():
                if key not in current:
                    current[key] = copy.deepcopy(value)
                    changed = True
            if changed:
                self.storage._write_json("roleplay_templates.json", current)
        saved = payload.get("saved_audio_prompts")
        if isinstance(saved, list) and saved:
            current = [item for item in list(self.settings.get("saved_audio_prompts") or []) if isinstance(item, dict)]
            current.extend(dict(item) for item in saved if isinstance(item, dict))
            self.settings["saved_audio_prompts"] = current[-100:]

    def _apply_story_package(self, path: str | Path, *, manifest: dict[str, Any] | None = None) -> dict[str, Any]:
        warnings: list[str] = []
        if manifest is None:
            manifest, manifest_warnings = self._read_story_package_manifest(path)
            warnings.extend(manifest_warnings)
        warnings.extend(str(item) for item in list((manifest or {}).get("warnings") or []) if str(item or "").strip())
        included = {str(item or "").strip() for item in list((manifest or {}).get("included_sections") or []) if str(item or "").strip()}
        from .scenario_transfer import preflight_story_extension, clone_story_extension
        from .scenario_models import decode_scenario_json
        content_id_map: dict[str, str] = {}
        # Validate definitions before backup, asset extraction, persona import or settings writes.
        with zipfile.ZipFile(path, "r") as preflight:
            for member in ("story.json", "master_story.json"):
                if member not in preflight.namelist():
                    continue
                if preflight.namelist().count(member) != 1:
                    raise ValueError(f"Duplicate story package member: {member}")
                raw_story = decode_scenario_json(preflight.read(member).decode("utf-8-sig"))
                if isinstance(raw_story, dict):
                    preflight_story_extension(raw_story)
                    for key in ("draft", "active_story"):
                        if isinstance(raw_story.get(key), dict):
                            preflight_story_extension(raw_story[key])
        self._save_pre_apply_backup("Import Story Library Package")
        with zipfile.ZipFile(path, "r") as handle:
            extracted_assets = self._extract_package_assets(handle, manifest or {}, warnings)
            story_payload = self._remap_imported_asset_paths(self._read_package_json(handle, "story.json", {}), extracted_assets)
            session_payload = self._remap_imported_asset_paths(self._read_package_json(handle, "session.json", {}), extracted_assets)
            personas_payload = self._remap_imported_asset_paths(self._read_package_json(handle, "personas.json", []), extracted_assets)
            voice_payload = self._remap_imported_asset_paths(self._read_package_json(handle, "persona_voice_settings.json", {}), extracted_assets)
            visual_payload = self._remap_imported_asset_paths(self._read_package_json(handle, "persona_visual_settings.json", {}), extracted_assets)
            avatar_payload = self._remap_imported_asset_paths(self._read_package_json(handle, "avatar_images.json", {}), extracted_assets)
            memory_payload = self._remap_imported_asset_paths(self._read_package_json(handle, "story_memory.json", {}), extracted_assets)
            events_payload = self._read_package_json(handle, "story_events.json", {})
            audiofx_payload = self._remap_imported_asset_paths(self._read_package_json(handle, "audiofx.json", {}), extracted_assets)
            visual_styles_payload = self._read_package_json(handle, "visual_styles.json", [])
            master_story_payload = self._remap_imported_asset_paths(self._read_package_json(handle, "master_story.json", {}), extracted_assets)
            templates_payload = self._read_package_json(handle, "templates.json", {})

        id_map: dict[str, str] = {}
        if "personas" in included:
            id_map = self._apply_imported_personas(personas_payload, warnings)
        if "persona_voice" in included:
            self._apply_imported_voice_settings(voice_payload, id_map)
        if "persona_visual" in included:
            self._apply_imported_visual_settings(visual_payload, id_map)
        if "avatar_assets" in included:
            self._apply_imported_avatar_images(avatar_payload, id_map)

        story_id = ""
        story_title = str((manifest or {}).get("story_title") or "").strip()
        if "story_metadata" in included and isinstance(story_payload, dict) and story_payload:
            story_payload = clone_story_extension(story_payload, content_id_map=content_id_map)
            story = self._remap_story_payload_persona_ids(story_payload, id_map)
            original_story_id = self.storage.story_id(story.get("id") or (manifest or {}).get("story_id") or "imported_story")
            story_id = self._unique_story_id(original_story_id)
            if story_id != original_story_id:
                warnings.append(f"Story id '{original_story_id}' already existed; imported as '{story_id}'.")
            story["id"] = story_id
            story_title = str(story.get("title") or story_title or story_id).strip()
            story["updated_at"] = QtCore.QDateTime.currentDateTimeUtc().toString(QtCore.Qt.ISODate)
            self.storage.save_story(story)
            self.settings["last_master_story_id"] = story_id
            self.settings["last_master_story_title"] = story_title or story_id
            self._master_story_draft = copy.deepcopy(story)
            self.settings["active_scenario_extension"] = copy.deepcopy(story.get("scenario_extension"))
            self.settings["active_scenario_story_id"] = story_id
            self._stop_mprc_chat_playback()

        if "story_setup" in included and isinstance(session_payload, dict) and session_payload:
            session_story = self._remap_story_payload_persona_ids({"session": session_payload}, id_map)
            self.session = RoleplaySessionState.from_dict(session_story.get("session") or session_payload)
            self.session.enabled = True
            self._ensure_session_persona()

        if "story_memory" in included and isinstance(memory_payload, dict) and memory_payload:
            target_story_id = story_id or self._unique_story_id(str((manifest or {}).get("story_id") or "imported_story"))
            memory = self._remap_story_memory_persona_ids(memory_payload, id_map, target_story_id)
            self.storage.save_story_memory(target_story_id, memory)
            if isinstance(memory.get("long_memory"), dict):
                self.long_memory.save(memory.get("long_memory"))
            self.settings["last_master_story_id"] = target_story_id
            if story_title:
                self.settings["last_master_story_title"] = story_title

        if "story_events" in included and isinstance(events_payload, dict):
            imported_events = [item for item in list(events_payload.get("story_event_log") or []) if isinstance(item, dict)]
            if imported_events:
                self._story_event_log = (self._story_event_log + imported_events)[-80:]
                self.settings["story_event_log"] = list(self._story_event_log)

        if "audiofx" in included:
            self._merge_imported_audiofx(audiofx_payload)
        if "visual_styles" in included:
            self._merge_imported_visual_styles(visual_styles_payload)
        if "templates" in included:
            self._merge_imported_templates(templates_payload)
        if "master_story" in included and isinstance(master_story_payload, dict):
            draft = master_story_payload.get("draft")
            active_story = master_story_payload.get("active_story")
            if isinstance(draft, dict) and draft:
                imported_draft = clone_story_extension(draft, content_id_map=content_id_map)
                if story_id or "scenario_extension" in imported_draft:
                    imported_draft["id"] = story_id or self._unique_story_id(str(imported_draft.get("id") or "imported_story"))
                self._master_story_draft = self._remap_story_payload_persona_ids(imported_draft, id_map)
            elif isinstance(active_story, dict) and active_story:
                imported_draft = clone_story_extension(active_story, content_id_map=content_id_map)
                if story_id or "scenario_extension" in imported_draft:
                    imported_draft["id"] = story_id or self._unique_story_id(str(imported_draft.get("id") or "imported_story"))
                self._master_story_draft = self._remap_story_payload_persona_ids(imported_draft, id_map)

        self.storage.save_settings(self.settings)
        self.save_state()
        self._populate_master_stories()
        self._story_audio_block_active = False
        self._story_audio_pending_text = ""
        self._last_story_audio_cues.clear()
        return {
            "story_id": story_id or self.settings.get("last_master_story_id") or (manifest or {}).get("story_id") or "",
            "story_title": story_title or self.settings.get("last_master_story_title") or (manifest or {}).get("story_title") or "",
            "warnings": warnings,
        }

    def _export_story_bundle(self):
        story_id = self._current_story_id() or "mprc_story"
        path = self._save_file("Export MPRC story bundle", str(Path.home() / f"{story_id}.mprc_story_bundle.json"), "MPRC story bundles (*.json)")
        if not path:
            return
        bundle = self._build_story_bundle()
        Path(path).write_text(json.dumps(bundle, indent=2, ensure_ascii=True), encoding="utf-8")
        self._record_story_event(f"exported story bundle: {path}", severity="info", kind="bundle", persist=True)
        self._set_master_story_status(f"Exported story bundle to {path}.")

    def _import_story_bundle(self):
        path = self._open_file("Import MPRC story bundle", str(Path.home()), "MPRC story bundles (*.json)")
        if not path:
            return
        try:
            bundle = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as exc:
            self._warn("Import Story Bundle", f"Could not read bundle:\n\n{exc}")
            return
        if not isinstance(bundle, dict) or str(bundle.get("bundle_type") or "") != "mprc_story_bundle":
            self._warn("Import Story Bundle", "This file is not an MPRC story bundle.")
            return
        try:
            self.native_import_story_bundle(bundle, source_path=str(path))
        except Exception as exc:
            self._warn("Import Story Bundle", f"Could not import bundle:\n\n{exc}")

    def _test_narrator_voice_from_status(self):
        narrator = self.selected_narrator_persona()
        if narrator is None:
            self._warn("Test Narrator Voice", "No narrator persona is selected or available.")
            self._record_story_event("voice test skipped: missing narrator", severity="warning", kind="voice", persist=True)
            return
        self._queue_story_voice_test(narrator, "[NARRATOR]", "narrator")

    def _test_selected_character_voice_from_status(self):
        narrator_id = self.selected_narrator_persona_id()
        persona = self.active_persona()
        if persona is not None and persona.id == narrator_id:
            linked = [self.persona_by_id(item) for item in self._current_linked_persona_ids()]
            persona = next((item for item in linked if item is not None and item.id != narrator_id), persona)
        if persona is None:
            self._warn("Test Character Voice", "No character persona is available.")
            return
        self._queue_story_voice_test(persona, f"[CHARACTER: {persona.display_name}]", "character")

    def _queue_story_voice_test(self, persona: PersonaConfig, label: str, kind: str) -> None:
        route = self.voice_router.effective_voice_config({
            "persona_id": persona.id,
            "tts_backend": self.current_tts_backend(),
            "text": f"{label}\nVoice route test.",
        })
        sample = str(route.get("sample_path") or "").strip()
        if not sample:
            self._record_story_event(f"voice test queued with warning for {persona.display_name}: {route.get('warning') or 'no sample'}", severity="warning", kind="voice", persist=True)
        message = (
            "Voice route test. Reply with exactly these two lines and no extra text:\n"
            f"{label}\n"
            f"{kind.capitalize()} voice route test."
        )
        queued = self._queue_continue_story(message)
        if queued:
            self._set_master_story_status(f"Queued {kind} voice test for {persona.display_name}.")

    def _test_visual_reply_from_status(self):
        persona = self.active_persona()
        narrator_id = self.selected_narrator_persona_id()
        if persona is not None and persona.id == narrator_id:
            linked = [self.persona_by_id(item) for item in self._current_linked_persona_ids()]
            persona = next((item for item in linked if item is not None and item.id != narrator_id and item.visual.enabled), persona)
        if persona is None:
            self._warn("Test Visual Reply", "No persona is available for Visual Reply.")
            return
        self._debug_visual_prompt = json.dumps(
            {"queued": True, "message": "Visual Reply test queued for a background worker.", "persona_id": persona.id},
            indent=2,
            ensure_ascii=True,
        )
        self._refresh_debug()
        self._record_story_event(
            f"visual test queued for {persona.display_name}",
            severity="info",
            kind="visual",
            persist=True,
        )
        self._set_master_story_status(f"Queued Visual Reply test for {persona.display_name}.")
        if not self._queue_visual_worker(
            "mprc_status_visual_reply",
            lambda commit_guard: self._run_manual_visual_reply_request(
                str(persona.id or ""),
                kind="status_visual_reply",
                commit_guard=commit_guard,
            ),
        ):
            result = {"accepted": False, "message": "Visual Reply test could not start a background worker."}
            self._on_manual_visual_finished("status_visual_reply", str(persona.id or ""), result)

    def _test_audiofx_from_status(self):
        if not self.available_story_audio_files():
            self._create_test_audiofx(show_status=False)
        entries = self.available_story_audio_files()
        cue = str((entries[0] if entries else {}).get("id") or "").strip()
        if not cue:
            self._warn("Test AudioFX", "No ready AudioFX cue is available.")
            return
        ok = self._play_story_audio_cue(cue)
        self._record_story_event(f"AudioFX test {'played' if ok else 'skipped'}: {cue}", severity="info" if ok else "warning", kind="audiofx", persist=True)
        self._set_master_story_status(f"AudioFX test {'played' if ok else 'could not play'}: {cue}.")

    def _repair_choose_narrator(self):
        narrator = self.selected_narrator_persona() or self._auto_ar_narrator_persona() or self.active_persona()
        if narrator is None:
            self._warn("Choose Narrator", "No persona is available to use as narrator.")
            return
        self.settings["narrator_persona_id"] = narrator.id
        self.settings["narrator_persona_mode"] = "explicit"
        if not self._voice_follows_active():
            self.settings["voice_edit_persona_id"] = narrator.id
        self.storage.save_settings(self.settings)
        self._persist_current_story_narrator_lock()
        self._record_story_event(f"repair: narrator locked to {narrator.display_name}", severity="info", kind="repair", persist=True)
        self.refresh_ui()
        self._validate_story_setup_to_ui()

    def _repair_browse_voice_file(self):
        persona = self.selected_narrator_persona() if self.session.mode == AR_MODE else self._selected_voice_persona()
        persona = persona or self.active_persona()
        if persona is None:
            self._warn("Browse Voice File", "No persona is available for voice repair.")
            return
        path = self._open_file(
            "Choose voice sample",
            str(Path.home()),
            "Audio files (*.wav *.mp3 *.flac *.ogg *.m4a);;All files (*.*)",
            non_native=True,
        )
        if not path:
            return
        persona.voice.enabled = True
        persona.voice.sample_path = path
        if persona.voice.backend not in VOICE_BACKENDS:
            persona.voice.backend = "inherit"
        if not self._voice_follows_active():
            self.settings["voice_edit_persona_id"] = persona.id
            self.storage.save_settings(self.settings)
        self.save_state()
        self._record_story_event(f"repair: voice file set for {persona.display_name}", severity="info", kind="repair", persist=True)
        self.refresh_ui()
        self._validate_story_setup_to_ui()

    def _repair_disable_missing_audiofx(self):
        items = self._audiofx_items()
        kept = [item for item in items if self._audiofx_file_ready(item)]
        removed = len(items) - len(kept)
        self._save_audiofx_items(kept)
        self._record_story_event(f"repair: disabled {removed} missing AudioFX item(s)", severity="info", kind="repair", persist=True)
        self.refresh_ui()
        self._validate_story_setup_to_ui()

    def _repair_fix_broken_image_path(self):
        persona = next(
            (
                item for item in (self.persona_by_id(pid) for pid in self._current_linked_persona_ids())
                if item is not None and str(item.character_image_path or "").strip() and not Path(str(item.character_image_path)).exists()
            ),
            None,
        ) or self.active_persona()
        if persona is None:
            self._warn("Fix Image Path", "No persona is available for image repair.")
            return
        path = self._open_file("Choose character image", str(Path.home()), "Images (*.png *.jpg *.jpeg *.webp *.bmp);;All files (*.*)")
        if not path:
            return
        persona.character_image_path = path
        self.save_state()
        self._record_story_event(f"repair: image path set for {persona.display_name}", severity="info", kind="repair", persist=True)
        self.refresh_ui()
        self._validate_story_setup_to_ui()

    def _repair_create_memory_snapshot(self):
        story_id = self._current_story_id()
        if not story_id:
            self._warn("Create Memory Snapshot", "No active story is loaded.")
            return
        self._save_story_memory_snapshot(story_id)
        self._record_story_event(f"repair: memory snapshot created for {story_id}", severity="info", kind="repair", persist=True)
        self.refresh_ui()
        self._validate_story_setup_to_ui()

    def _repair_relink_personas(self):
        linked = self._current_linked_persona_ids()
        known = {persona.id for persona in self.personas}
        created = []
        for persona_id in linked:
            if persona_id in known:
                continue
            display = persona_id.replace("_", " ").title()
            persona = self.ensure_persona_for_character_label(display, context_text="Created by Story Setup repair for a missing persona link.", source="repair", save=False)
            if persona is not None:
                created.append(persona.id)
                known.add(persona.id)
        if created:
            self.save_state()
        self.settings["master_story_linked_persona_ids"] = [item for item in linked if item in known] + created
        self.storage.save_settings(self.settings)
        self._record_story_event(f"repair: relinked personas, created={', '.join(created) if created else 'none'}", severity="info", kind="repair", persist=True)
        self.refresh_ui()
        self._validate_story_setup_to_ui()

    def _repair_reset_invalid_overrides(self):
        overrides = self.settings.get("master_story_persona_overrides")
        if not isinstance(overrides, dict):
            self.settings["master_story_persona_overrides"] = {}
            removed = 1
        else:
            known = {persona.id for persona in self.personas}
            clean = {key: value for key, value in overrides.items() if normalize_persona_id(key) in known and isinstance(value, dict)}
            removed = len(overrides) - len(clean)
            self.settings["master_story_persona_overrides"] = clean
        self.storage.save_settings(self.settings)
        self._persist_current_story_narrator_lock()
        self._record_story_event(f"repair: reset {removed} invalid persona override(s)", severity="info", kind="repair", persist=True)
        self.refresh_ui()
        self._validate_story_setup_to_ui()

    def _memory_payload(self) -> dict[str, Any]:
        try:
            return self.long_memory.load()
        except Exception:
            return {}

    def _refresh_memory_browser(self) -> None:
        payload = self._memory_payload()
        events = [
            dict(item)
            for item in reversed(list(payload.get("events") or [])[-80:])
            if isinstance(item, dict)
        ]
        self._native_memory_browser = {
            "pinned_facts": [str(item) for item in list(payload.get("pinned_facts") or [])],
            "events": events,
        }
    def _save_pinned_facts(self):
        widget = self._controls.get("story_pinned_facts")
        if widget is None:
            return
        lines = [line.strip() for line in str(widget.toPlainText() or "").splitlines() if line.strip()]
        payload = self._memory_payload()
        payload["pinned_facts"] = lines[:80]
        self.long_memory.save(payload)
        self.save_active_story_memory_snapshot()
        self._record_story_event(f"memory edit: saved {len(lines[:80])} pinned fact(s)", severity="info", kind="memory", persist=True)
        self._refresh_memory_browser()

    def _delete_selected_memory(self):
        memory_list = self._controls.get("story_memory_list")
        item = memory_list.currentItem() if memory_list is not None else None
        event_id = str(item.data(32) or "") if item is not None else ""
        if not event_id:
            self._warn("Delete Memory", "Select a memory item first.")
            return
        payload = self._memory_payload()
        events = [event for event in list(payload.get("events") or []) if str(event.get("id") or "") != event_id]
        payload["events"] = events
        payload["chapters"] = self.long_memory._build_chapters(events)
        payload["character_memory"] = self.long_memory._build_character_memory(events, self.story_prompt_personas())
        payload["location_memory"] = self.long_memory._build_location_memory(events)
        self.long_memory.save(payload)
        self.save_active_story_memory_snapshot()
        self._record_story_event(f"memory edit: deleted event {event_id}", severity="info", kind="memory", persist=True)
        self._refresh_memory_browser()

    def _reset_character_memory_only(self):
        payload = self._memory_payload()
        payload["character_memory"] = {}
        self.long_memory.save(payload)
        self.save_active_story_memory_snapshot()
        self._record_story_event("memory edit: reset character memory only", severity="info", kind="memory", persist=True)
        self._refresh_memory_browser()

    def _reset_story_memory_only(self):
        self._clear_story_memory_preserving_pins()
        self._record_story_event("memory edit: reset story memory only", severity="info", kind="memory", persist=True)
        self._refresh_memory_browser()
        self._refresh_reliability_panels()

    def _clear_story_memory_preserving_pins(self) -> None:
        payload = self._memory_payload()
        pinned = list(payload.get("pinned_facts") or [])
        self.long_memory.save({"pinned_facts": pinned})
        self.save_active_story_memory_snapshot()

    def _preview_next_ar_request(self):
        widget = self._controls.get("story_next_inspector")
        if widget is not None:
            widget.setPlainText(self._next_ar_request_text())
        self._record_story_event("previewed next AR request", severity="info", kind="debug", persist=False)

    def _explain_next_routing(self):
        widget = self._controls.get("story_next_inspector")
        if widget is not None:
            widget.setPlainText(self._next_routing_explanation_text())
        self._record_story_event("explained next routing", severity="info", kind="debug", persist=False)

    def _next_ar_request_text(self) -> str:
        from . import prompting

        if self.session.mode != AR_MODE:
            return "AlternativeReality mode is not active. Enable AR to preview the next AR request."
        self.ensure_ar_state("Continue")
        prompt = prompting.build_alternative_reality_prompt(
            self.story_prompt_personas(),
            self.session,
            latest_user_text="Continue",
            available_audio=self.available_story_audio_files(),
            narrator_persona_id=self.selected_narrator_persona_id(),
            dialogue_density=self.session.ar_dialogue_density,
        )
        memory = self.long_memory.prompt_context(session=self.session, personas=self.story_prompt_personas(), query="Continue", limit=8)
        sections = [
            "Next AR request preview",
            "",
            self._next_routing_explanation_text(),
            "",
            "Prompt:",
            prompt,
        ]
        if memory:
            sections.extend(["", "Memory included:", memory])
        return "\n".join(sections)

    def _next_routing_explanation_text(self) -> str:
        narrator = self.selected_narrator_persona()
        active = self.active_persona()
        memory = self._memory_payload()
        events = len(list(memory.get("events") or []))
        pinned = len(list(memory.get("pinned_facts") or []))
        visual = active.visual if active is not None else None
        visual_status = "no active persona"
        if active is not None and visual is not None:
            visual_status = f"{active.display_name}: enabled={bool(visual.enabled)}, mode={visual.mode}, service={'ready' if self.visual_reply_service is not None else 'unavailable'}"
        audio_ready = self.available_story_audio_files()
        lines = [
            "Next routing explanation",
            f"This story uses narrator: {narrator.display_name + ' (' + narrator.id + ')' if narrator else 'none'}",
            f"Active character: {active.display_name + ' (' + active.id + ')' if active else 'none'}",
            "",
            "Voice routes:",
            self._build_voice_routing_inspector_text(),
            "",
            f"Memory included: {events} remembered event(s), {pinned} pinned fact(s)",
            f"Visual Reply trigger status: {visual_status}",
            f"AudioFX trigger status: {len(audio_ready)} ready cue(s); Story Sounds={'on' if self.story_sounds_enabled() else 'off'}",
            f"Important prompt sections: narrator role, active characters, AR state, recent events, persona roster, available audio cues, pinned/long memory",
        ]
        return "\n".join(lines)

    def _persist_current_story_narrator_lock(self):
        story_id = self._current_story_id()
        if not story_id:
            return
        payload = self.storage.load_story(story_id)
        if not isinstance(payload, dict) or not payload:
            return
        payload["narrator_persona_id"] = self.selected_narrator_persona_id()
        payload["narrator_persona_mode"] = self._narrator_selection_mode()
        session_payload = dict(payload.get("session") or {}) if isinstance(payload.get("session"), dict) else {}
        session_payload["narrator_persona_id"] = payload["narrator_persona_id"]
        session_payload["narrator_persona_mode"] = payload["narrator_persona_mode"]
        payload["session"] = session_payload
        payload["updated_at"] = QtCore.QDateTime.currentDateTimeUtc().toString(QtCore.Qt.ISODate)
        self.storage.save_story(payload)
        self._record_story_event(f"narrator routing locked for story: {payload['narrator_persona_id'] or 'auto'}", severity="info", kind="narrator", persist=True)

    def save_active_story_memory_snapshot(self) -> None:
        story_id = str(self.settings.get("last_master_story_id") or "").strip()
        if story_id:
            self._save_story_memory_snapshot(story_id)

    def _save_story_memory_snapshot(self, story_id: str) -> None:
        normalized = self.storage.story_id(story_id)
        if not normalized:
            return
        try:
            memory = self.long_memory.load()
        except Exception:
            memory = {}
        linked_persona_ids = list(self.settings.get("master_story_linked_persona_ids") or [])
        snapshot = {
            "schema_version": RoleplayStorage.MEMORY_SCHEMA_VERSION,
            "version": 1,
            "story_id": normalized,
            "updated_at": QtCore.QDateTime.currentDateTimeUtc().toString(QtCore.Qt.ISODate),
            "long_memory": memory if isinstance(memory, dict) else {},
            "session": self.session.to_dict(),
            "settings": {
                "last_master_story_id": self.settings.get("last_master_story_id"),
                "last_master_story_title": self.settings.get("last_master_story_title"),
                "master_story_linked_persona_ids": linked_persona_ids,
                "master_story_created_persona_ids": list(self.settings.get("master_story_created_persona_ids") or []),
                "master_story_persona_overrides": dict(self.settings.get("master_story_persona_overrides") or {}),
                "master_story_avatar_style_sheets": self.settings.get("master_story_avatar_style_sheets", False),
                "persona_avatar_style_sheets": self._story_avatar_style_sheet_settings(normalized, linked_persona_ids),
                "narrator_persona_id": self.settings.get("narrator_persona_id"),
                "narrator_persona_mode": self.settings.get("narrator_persona_mode"),
                "story_sounds_enabled": self.settings.get("story_sounds_enabled", True),
                "audio_fx_items": list(self.settings.get("audio_fx_items") or []),
                "available_audio_files": list(self.settings.get("available_audio_files") or []),
                "saved_audio_prompts": list(self.settings.get("saved_audio_prompts") or []),
                "audiofx_volume": self.settings.get("audiofx_volume"),
                "audiofx_test_mode": self.settings.get("audiofx_test_mode"),
            },
        }
        self.storage.save_story_memory(normalized, snapshot)

    def _restore_story_memory_snapshot(self, story_id: str) -> bool:
        normalized = self.storage.story_id(story_id)
        if not normalized:
            return False
        snapshot = self.storage.load_story_memory(normalized)
        if not isinstance(snapshot, dict) or not snapshot:
            self._record_story_event(f"memory not loaded: no saved snapshot for {normalized}", severity="warning", kind="memory", persist=True)
            return False
        for note in list(snapshot.get("_migration_log") or []):
            self._record_story_event(f"memory migration/fallback: {note}", severity="warning", kind="schema", persist=True)
        memory = snapshot.get("long_memory")
        if isinstance(memory, dict):
            self.long_memory.save(memory)
        session_payload = snapshot.get("session")
        if isinstance(session_payload, dict):
            self.session = RoleplaySessionState.from_dict(session_payload)
            self.session.enabled = False
            self._ensure_session_persona()
        settings = snapshot.get("settings")
        if isinstance(settings, dict):
            for key in (
                "master_story_linked_persona_ids",
                "master_story_created_persona_ids",
                "master_story_persona_overrides",
                "master_story_avatar_style_sheets",
                "persona_avatar_style_sheets",
                "narrator_persona_id",
                "narrator_persona_mode",
                "story_sounds_enabled",
                "audio_fx_items",
                "available_audio_files",
                "saved_audio_prompts",
                "audiofx_volume",
                "audiofx_test_mode",
            ):
                if key in settings:
                    if key == "persona_avatar_style_sheets":
                        self._merge_story_avatar_style_sheet_settings(settings.get(key))
                    else:
                        self.settings[key] = settings.get(key)
        self.settings["last_master_story_id"] = normalized
        self.settings["master_story_ready_to_start"] = True
        self._set_mprc_play_isolated_active(False)
        title = str(self.settings.get("last_master_story_title") or "").strip()
        snapshot_title = str((settings or {}).get("last_master_story_title") or "").strip() if isinstance(settings, dict) else ""
        if snapshot_title:
            self.settings["last_master_story_title"] = snapshot_title
        elif title:
            self.settings["last_master_story_title"] = title
        self._story_audio_block_active = False
        self._story_audio_pending_text = ""
        self._last_story_audio_cues.clear()
        self.storage.save_settings(self.settings)
        self.save_state()
        self._record_story_event(f"memory loaded: restored story snapshot for {normalized}", severity="info", kind="memory", persist=True)
        return True

    def _clear_master_story_runtime_state(self, *, clear_long_memory: bool, enabled: bool) -> None:
        scenario = getattr(self, "_scenario_play", None)
        if scenario is not None:
            scenario.stop()
        self._set_mprc_play_isolated_active(False)
        self._reset_mprc_chat_history()
        self.roleplay_engine._recent_assistant_texts = []
        if clear_long_memory:
            try:
                self.long_memory.clear()
            except Exception as exc:
                logger = getattr(self.context, "logger", None)
                if logger is not None:
                    logger.warning("[MPRC] Could not clear long memory: %s", exc)
        fallback = self.session.active_persona_id if self.session.active_persona_id else (self.personas[0].id if self.personas else "mentor")
        self.session = RoleplaySessionState(
            enabled=bool(enabled),
            active_persona_id=fallback,
            current_speaker_id=fallback,
        )
        self._story_audio_block_active = False
        self._story_audio_pending_text = ""
        self._last_story_audio_cues.clear()
        self._last_tts_visual_reply_at.clear()
        self._manual_character_image_inflight.clear()
        self._tts_persona_visual_inflight.clear()
        self._tts_visual_reply_inflight.clear()
        self._tts_generation_ids.clear()
        self._pending_tts_persona_visuals.clear()
        for key in (
            "last_master_story_id",
            "last_master_story_title",
            "master_story_linked_persona_ids",
            "master_story_created_persona_ids",
            "master_story_persona_overrides",
        ):
            self.settings.pop(key, None)

    def _restart_master_story(self, *, confirmed: bool = False) -> bool:
        if not confirmed:
            self._native_pending_confirmation = {
                "action": "restart_master_story",
                "title": "Clear / Restart Story",
                "message": "Clear MPRC long memory, recent scene state, current Master Story links, and the draft editor? Saved personas and saved story files will be kept.",
            }
            return False
        self._clear_master_story_runtime_state(clear_long_memory=True, enabled=False)
        self._master_story_draft = {}
        self.storage.save_settings(self.settings)
        self.save_state()
        self.refresh_ui()
        self._set_master_story_status("Restarted Master Story state. Old MPRC long memory and current scene state were cleared.")
        self._native_pending_confirmation = {}
        return True
    def _generate_master_story(self):
        if self.is_shutdown():
            return
        generate_button = self._controls.get("master_story_generate")
        if generate_button is not None and bool(generate_button.property("_mprc_in_flight")):
            return
        prompt_widget = self._controls.get("master_story_prompt")
        prompt = str(prompt_widget.toPlainText() if prompt_widget is not None else "").strip()
        if not prompt:
            self._warn("Generate Story Setup", "Add a Master Story prompt first.")
            return
        self._commit_master_story_options()
        snapshot = self._master_story_generation_snapshot(prompt)
        token = self._new_worker_token("master_story")
        if not token:
            return
        self._master_story_generation_snapshots[token] = copy.deepcopy(snapshot)
        if generate_button is not None:
            generate_button.setProperty("_mprc_in_flight", True)
            generate_button.setProperty("_mprc_worker_token", token)
            generate_button.setEnabled(False)
        self._set_master_story_status("Generating story setup with the current chat provider...")

        def worker():
            error = ""
            result = ""
            try:
                result = self._generate_master_story_payload(snapshot)
            except Exception as exc:
                error = str(exc) or repr(exc)
            if not self._worker_should_emit(token):
                return
            try:
                bridge = getattr(self, "_story_bridge", None)
                if bridge is not None:
                    bridge.finished.emit(token, result, error)
                else:
                    self._cancel_worker_token(token)
            except RuntimeError:
                self._cancel_worker_token(token)

        if not self._start_daemon_worker(token, worker, name="nc-mprc-master-story"):
            self._master_story_generation_snapshots.pop(token, None)
            if generate_button is not None:
                generate_button.setProperty("_mprc_in_flight", False)
                generate_button.setProperty("_mprc_worker_token", "")
                generate_button.setEnabled(True)

    def _master_story_generation_snapshot(self, prompt: str) -> dict[str, Any]:
        visual_direction = str(self.settings.get("master_story_visual_direction") or "").strip()
        constraints = self._master_story_generation_constraints()
        mode = self._master_story_mode()
        scene_context = self._master_story_creator_scene_context()
        with self._state_lock:
            roster = [
                {
                    "id": persona.id,
                    "display_name": persona.display_name,
                    "role": persona.role,
                    "description": str(persona.description or persona.ar_description or "")[:300],
                    "tags": list(persona.tags or []),
                }
                for persona in list(self.personas or [])
            ] if constraints["use_existing_personas"] else []
        return {
            "prompt": str(prompt or "").strip(),
            "safe_prompt": self._master_story_safety_normalized_prompt(prompt, sfw=bool(constraints.get("sfw_mode", True))),
            "visual_direction": visual_direction,
            "constraints": constraints,
            "generation_notes": self._master_story_generation_constraints_text(constraints),
            "content_safety": self._master_story_content_safety_payload(bool(constraints.get("sfw_mode", True))),
            "safety_instruction": self._master_story_safety_instruction(bool(constraints.get("sfw_mode", True))),
            "mode": mode,
            "scene_context": scene_context,
            "use_ar": mode == AR_MODE,
            "roster": roster,
            "include_scenario": bool(self.settings.get("master_story_include_scenario", False)),
        }

    def _generate_master_story_payload(self, snapshot: dict[str, Any], *,
                                       request: Callable[[dict[str, Any], dict[str, Any]], str] | None = None) -> str:
        snapshot = dict(snapshot or {})
        model_name = str(snapshot.get("model") or "") if request else self._current_provider_model()
        if not model_name:
            raise RuntimeError("Choose a chat model before generating a Master Story.")
        prompt = str(snapshot.get("safe_prompt") or snapshot.get("prompt") or "").strip()
        visual_direction = str(snapshot.get("visual_direction") or "").strip()
        constraints = dict(snapshot.get("constraints") or {})
        content_safety = dict(snapshot.get("content_safety") or self._master_story_content_safety_payload(bool(constraints.get("sfw_mode", True))))
        safety_instruction = str(snapshot.get("safety_instruction") or self._master_story_safety_instruction(bool(content_safety.get("sfw", True))))
        roster = list(snapshot.get("roster") or []) if constraints.get("use_existing_personas") else []
        selected_mode = str(snapshot.get("mode") or "").strip()
        if selected_mode not in SESSION_MODES:
            selected_mode = AR_MODE if bool(snapshot.get("use_ar", True)) else "Narrator + characters"
        scene_context = dict(snapshot.get("scene_context") or {})
        system = (
            "You create compact JSON story setup files for NeuralCompanion's Multi Persona Roleplay addon. "
            "Return one valid canonical story JSON object only, with no markdown and no wrapper unless the user explicitly asks for an envelope. "
            "Do not append a second fallback story object. Do not repeat top-level keys. Do not overwrite a populated personas array with an empty one. "
            "Reuse existing persona IDs when the user's requested character clearly matches an existing persona and existing-persona reuse is enabled. "
            "Create new persona objects only when needed. Keep all content fictional, consensual, adult-safe, and respectful of user agency. "
            f"{safety_instruction} "
            "Do not use DnD/tabletop rules, dice, stats, or classes unless the user explicitly asks for them or selected "
            "RPG / Game Master mode. For every persona, create a useful visual profile "
            "for avatar portrait generation. If the story is fantasy, make the visual descriptions read as strong fantasy "
            "character portraits that still follow the user's story premise. Follow the requested persona count exactly when possible, "
            "and respect the configured character creation limit."
            " Use the requested Master Story mode exactly. Treat non-empty creator scene fields as binding. "
            "Set narrator_persona_id only to a persona that is actually a narrator; never turn the first ordinary character into the narrator. "
            "Include every drafted opening cast member in session.ar_state.active_characters when AlternativeReality mode is selected."
        )
        user = {
            "task": "Draft a Master Story setup from the user's prompt.",
            "schema": {
                "id": "short_lowercase_story_id",
                "title": "short title",
                "summary": "one paragraph",
                "mode": selected_mode,
                "active_persona_id": "persona_id",
                "current_speaker_id": "persona_id",
                "narrator_persona_id": "actual_narrator_persona_id_or_empty",
                "session": {
                    "scene_title": str(scene_context.get("scene_title") or "short scene title"),
                    "location": str(scene_context.get("location") or "current location"),
                    "time_of_day": str(scene_context.get("time_of_day") or "time/era/timing cue"),
                    "mood": str(scene_context.get("mood") or "atmosphere"),
                    "objective": "clear opening objective",
                    "scene_summary": "compact visible continuity summary",
                    "ar_pacing": "Balanced",
                    "ar_interaction_frequency": "Ask sometimes",
                    "ar_dialogue_density": "Balanced narrator + character dialogue",
                    "ar_state": {
                        "current_scene": "opening beat",
                        "location": "same or more specific location",
                        "active_characters": ["persona_id_1", "persona_id_2"],
                        "tension_level": 2,
                        "story_goal": "story goal",
                        "recent_events": ["opening event"],
                        "pending_choices": ["optional choice"],
                        "mood": "mood",
                        "time_of_day": "time",
                    },
                },
                "personas": [
                    {
                        "id": "persona_id",
                        "display_name": "Name",
                        "role": "archetype",
                        "description": "normal short description",
                        "system_prompt": "normal persona prompt",
                        "ar_description": "cinematic AR character description",
                        "ar_system_prompt": "AR persona instruction",
                        "speaking_style": "voice and phrasing",
                        "allowed_tone": "tone limits",
                        "behavior_mode": "group participant",
                        "memory_scope": "persona-only",
                        "tags": ["story"],
                        "visual": {
                            "enabled": True,
                            "mode": "manual",
                            "provider": "inherit",
                            "size": "inherit",
                            "style_preset": "",
                            "character_description": "detailed visual appearance for avatar portrait generation",
                            "clothing_props": "costume, gear, props, silhouette",
                            "environment_style": "background or world style",
                            "negative_prompt": "avoid text, watermark, extra limbs, distorted face",
                        },
                    }
                ],
                "content_safety": {
                    "sfw": True,
                    "allow_romance": True,
                    "allow_mature_themes": False,
                    "allow_explicit_sexual_content": False,
                },
                "generation": {
                    "source": "master_story_creator",
                    "requested_story_native_personas": constraints.get("native_personas_to_draft", 4),
                    "maximum_new_personas_to_create": constraints.get("maximum_new_personas_to_create", 8),
                    "use_existing_personas": constraints.get("use_existing_personas", True),
                    "auto_create_missing_personas": constraints.get("auto_create_missing_personas", True),
                    "sfw_mode": content_safety.get("sfw", True),
                },
                "updated_at": "ISO-8601 timestamp or empty string",
            },
            "existing_personas": roster,
            "generation_constraints": constraints,
            "content_safety": content_safety,
            "content_safety_instruction": safety_instruction,
            "canonical_json_rules": [
                "Return exactly one story object at the JSON root.",
                "Do not include a second top-level id/title/summary/personas/session block after the story.",
                "Do not include duplicate top-level keys.",
                "Keep generated personas in the single personas array.",
                "Keep metadata in generation and safety flags in content_safety.",
            ],
            "persona_count_contract": {
                "requested_story_native_personas": constraints.get("native_personas_to_draft", 4),
                "return_exact_persona_count_when_possible": True,
                "persona_array_is_validated_against_requested_count": True,
                "ordinary_characters_must_not_be_repurposed_as_narrator": True,
            },
            "generation_notes": str(snapshot.get("generation_notes") or ""),
            "master_story_mode": selected_mode,
            "creator_scene_context": scene_context,
            "avatar_visual_direction": visual_direction,
            "user_story_prompt": prompt,
            "original_user_story_prompt_note": "If SFW mode rewrote prompt wording, preserve the user's adventure intent using non-explicit relationship conflict and emotional stakes.",
        }
        if snapshot.get("include_scenario"):
            from .scenario_demo import generation_guidance, lighthouse_example
            user["scenario_extension_instructions"] = generation_guidance()
            user["scenario_extension_example"] = lighthouse_example()
        else:
            user["scenario_extension_instructions"] = "Omit scenario_extension. This is a legacy Master Story draft."
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, ensure_ascii=True, indent=2)},
        ]
        params = {
            "model": model_name,
            "messages": messages,
            "response_format": {"type": "json_object"},
        }
        additional_params: dict[str, Any] = {}
        if request is None and self._mprc_instructor_feature_enabled("mprc_instructor_master_story_validation_enabled") and not snapshot.get("include_scenario"):
            structured_payload = instructor_adapter.generate_structured_output(
                provider_execution=self.providers,
                params=params,
                response_model=structured_models.MasterStoryDraft,
                max_retries=2,
                logger=getattr(self.context, "logger", None),
            )
            if isinstance(structured_payload, dict) and structured_payload:
                clean_payload, clean_errors = structured_models.validate_master_story_draft(structured_payload)
                if not clean_errors and clean_payload:
                    return json.dumps(clean_payload, ensure_ascii=True)
        response = (request(params, additional_params) if request else
                    self._run_master_story_generation_request(params, additional_params))
        if snapshot.get("include_scenario"):
            from .scenario_models import decode_scenario_json, validate_story_extension
            if validate_story_extension(decode_scenario_json(response)) is None:
                raise ValueError("The model omitted the requested scenario extension. Refine or regenerate the draft.")
        return response

    @staticmethod
    def _master_story_generation_error_is_provider_compatibility(exc: Exception) -> bool:
        message = str(exc or "").lower()
        if not message:
            return False
        return any(
            marker in message
            for marker in (
                "response_format",
                "json_object",
                "http error 400",
                "400 bad request",
                "bad request",
                "invalid request",
                "invalid parameter",
                "unknown parameter",
                "unsupported",
                "extra_body",
            )
        )

    @staticmethod
    def _master_story_relaxed_params(params: dict[str, Any]) -> dict[str, Any]:
        relaxed = dict(params or {})
        relaxed.pop("response_format", None)
        for key in ("max_tokens", "max_completion_tokens"):
            if key not in relaxed:
                continue
            try:
                if int(float(relaxed.get(key))) <= 0:
                    relaxed.pop(key, None)
            except Exception:
                pass
        return relaxed

    def _run_master_story_generation_request(self, params: dict[str, Any], additional_params: dict[str, Any]) -> str:
        base_params = dict(params or {})
        base_additional = dict(additional_params or {})
        attempts: list[tuple[str, dict[str, Any], dict[str, Any]]] = [("strict JSON mode", base_params, base_additional)]
        relaxed_params = self._master_story_relaxed_params(base_params)
        if relaxed_params != base_params:
            attempts.append(("plain JSON instructions", relaxed_params, base_additional))
        if base_additional:
            attempts.append(("plain JSON instructions without provider extras", relaxed_params, {}))

        last_error: Exception | None = None
        for label, request_params, request_additional in attempts:
            try:
                return self._complete_provider_request(
                    dict(request_params),
                    dict(request_additional),
                )
            except Exception as exc:
                last_error = exc
                if not self._master_story_generation_error_is_provider_compatibility(exc):
                    raise
                logger = getattr(getattr(self, "context", None), "logger", None)
                if logger is not None:
                    try:
                        logger.info("[MPRC] Master Story generation provider retry after %s failed: %s", label, exc)
                    except Exception:
                        pass
                continue
        if last_error is not None:
            raise RuntimeError(
                f"{last_error} (Master Story generation retried without JSON response_format"
                " and provider extra parameters.)"
            )
        return ""

    def _control_checked(self, key: str, default: bool = False) -> bool:
        return bool(self.settings.get(str(key or ""), default))

    def _master_story_mode(self) -> str:
        stored = str(self.settings.get("master_story_mode") or "").strip()
        if stored in SESSION_MODES:
            return stored
        return AR_MODE if bool(self.settings.get("master_story_use_ar", True)) else "Narrator + characters"

    def _master_story_creator_scene_context(self) -> dict[str, str]:
        context: dict[str, str] = {}
        for key, setting_key in (
            ("scene_title", "master_story_scene_title"),
            ("location", "master_story_location"),
            ("time_of_day", "master_story_time_of_day"),
            ("mood", "master_story_mood"),
        ):
            value = str(self.settings.get(setting_key) or "").strip()
            context[key] = value
        return context

    def _apply_master_story_creator_context(
        self,
        payload: dict[str, Any],
        scene_context: dict[str, Any] | None,
        *,
        mode: str | None = None,
    ) -> dict[str, Any]:
        story = copy.deepcopy(dict(payload or {}))
        selected_mode = str(mode or story.get("mode") or "").strip()
        if selected_mode not in SESSION_MODES:
            selected_mode = self._master_story_mode()
        story["mode"] = selected_mode
        session = dict(story.get("session") or {}) if isinstance(story.get("session"), dict) else {}
        session["mode"] = selected_mode
        context = dict(scene_context or {})
        for key in ("scene_title", "location", "time_of_day", "mood"):
            value = str(context.get(key) or "").strip()
            if value:
                session[key] = value
        if selected_mode == AR_MODE:
            ar_state = dict(session.get("ar_state") or {}) if isinstance(session.get("ar_state"), dict) else {}
            for key in ("location", "time_of_day", "mood"):
                value = str(context.get(key) or "").strip()
                if value:
                    ar_state[key] = value
            scene_title = str(context.get("scene_title") or "").strip()
            if scene_title and not str(ar_state.get("current_scene") or "").strip():
                ar_state["current_scene"] = scene_title
            session["ar_state"] = ar_state
        story["session"] = session
        return story

    def _set_master_story_creator_context_from_payload(self, payload: dict[str, Any]) -> None:
        story = dict(payload or {})
        session = dict(story.get("session") or {}) if isinstance(story.get("session"), dict) else {}
        mode = str(story.get("mode") or session.get("mode") or "").strip()
        if mode in SESSION_MODES:
            self.settings["master_story_mode"] = mode
            self.settings["master_story_use_ar"] = mode == AR_MODE
        for key in ("scene_title", "location", "time_of_day", "mood"):
            self.settings[f"master_story_{key}"] = str(session.get(key) or "").strip()

    def _master_story_allow_exceed_max_created_characters(self) -> bool:
        return self._control_checked("master_story_allow_exceed_max_created_characters", False)

    def _master_story_sfw_mode(self) -> bool:
        return self._control_checked("master_story_sfw_mode", True)

    def _control_int_value(self, key: str, default: int, minimum: int, maximum: int) -> int:
        try:
            value = int(self.settings.get(str(key or ""), default))
        except (TypeError, ValueError):
            value = int(default)
        return max(int(minimum), min(int(maximum), value))

    def _master_story_int_setting(self, key: str, default: int, minimum: int, maximum: int) -> int:
        try:
            value = int(float(self.settings.get(key, default)))
        except Exception:
            value = int(default)
        return max(int(minimum), min(int(maximum), value))

    def _commit_master_story_options(self):
        if self._syncing:
            return
        self.settings["master_story_native_persona_count"] = self._control_int_value("master_story_native_persona_count", 4, 0, 24)
        self.settings["master_story_max_created_characters"] = self._control_int_value("master_story_max_created_characters", 8, 1, 40)
        self.settings["master_story_allow_exceed_max_created_characters"] = self._control_checked("master_story_allow_exceed_max_created_characters", False)
        self.settings["master_story_sfw_mode"] = self._master_story_sfw_mode()
        mode = self._master_story_mode()
        self.settings["master_story_mode"] = mode
        self.settings["master_story_use_ar"] = mode == AR_MODE
        for key, value in self._master_story_creator_scene_context().items():
            self.settings[f"master_story_{key}"] = value
        for key in (
            "master_story_use_existing_personas",
            "master_story_auto_create",
            "master_story_auto_assign_voices",
            "master_story_update_existing",
            "master_story_auto_avatars",
            "master_story_clear_memory",
        ):
            self.settings[key] = self._control_checked(key, True)
        self.settings["master_story_avatar_style_sheets"] = self._control_checked("master_story_avatar_style_sheets", False)
        self.storage.save_settings(self.settings)

    def _master_story_generation_constraints(self) -> dict[str, Any]:
        native_count = self._control_int_value("master_story_native_persona_count", 4, 0, 24)
        max_created = self._control_int_value("master_story_max_created_characters", 8, 1, 40)
        return {
            "native_personas_to_draft": native_count,
            "maximum_new_personas_to_create": max_created,
            "allow_exceed_max_created_characters": self._master_story_allow_exceed_max_created_characters(),
            "sfw_mode": self._master_story_sfw_mode(),
            "use_existing_personas": self._control_checked("master_story_use_existing_personas", True),
            "auto_create_missing_personas": self._control_checked("master_story_auto_create", True),
        }

    def _master_story_content_safety_payload(self, sfw: bool | None = None) -> dict[str, Any]:
        sfw_enabled = self._master_story_sfw_mode() if sfw is None else bool(sfw)
        return {
            "sfw": sfw_enabled,
            "allow_romance": True,
            "allow_mature_themes": not sfw_enabled,
            "allow_explicit_sexual_content": False,
        }

    @staticmethod
    def _master_story_safety_instruction(sfw: bool) -> str:
        if bool(sfw):
            return (
                "Content safety: SFW mode is enabled. Keep the story suitable for general fantasy adventure. "
                "Romantic tension and mature emotional themes are allowed, but do not generate explicit sexual content, erotic descriptions, or graphic nudity. "
                "Rephrase sexual prompt elements into non-explicit relationship conflict, taboo, loyalty, intimacy, and emotional stakes."
            )
        return (
            "Content safety: SFW mode is disabled. Mature themes may be included when relevant, but do not generate illegal, underage, "
            "non-consensual, exploitative, or pornographic content. Keep story output narrative-focused and controllable."
        )

    @staticmethod
    def _master_story_safety_normalized_prompt(prompt: str, *, sfw: bool) -> str:
        text = str(prompt or "").strip()
        if not bool(sfw) or not text:
            return text
        replacements = (
            (r"\binter[\s-]?racial relationships?\s+and\s+sexual activity\b", "forbidden relationships, cultural taboos, and intimate bonds across enemy lines"),
            (r"\bsexual activity\b", "non-explicit intimate bonds and emotional stakes"),
            (r"\bexplicit sex(?:ual)?\b", "romantic tension and private emotional stakes"),
            (r"\berotic\b", "romantic"),
            (r"\bfetish(?:es|istic)?\b", "personal taboo"),
            (r"\bgraphic nudity\b", "vulnerable non-explicit intimacy"),
        )
        for pattern, replacement in replacements:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        return text

    def _master_story_generation_constraints_text(self, constraints: dict[str, Any] | None = None) -> str:
        constraints = dict(constraints or self._master_story_generation_constraints())
        existing = "may reuse already created personas" if constraints["use_existing_personas"] else "should not rely on already created personas"
        native_count = int(constraints.get("native_personas_to_draft", 4) or 0)
        if native_count <= 0:
            persona_count_line = "- Do not draft story-native persona objects unless the user's prompt explicitly requires them."
        else:
            persona_count_line = (
                f"- Draft exactly {native_count} story-native persona/character profile(s) in the personas array when possible. "
                "If you cannot safely reach that count, return the closest complete cast and note the reason in the summary instead of adding weak filler."
            )
        max_line = (
            f"- Apply Draft will create no more than {constraints['maximum_new_personas_to_create']} new persona/character profile(s) by default; "
            "still keep the requested draft cast visible so the user can review, map, reuse, or enable the override."
        )
        if constraints.get("allow_exceed_max_created_characters"):
            max_line = (
                f"- The user has enabled the max-created override; Apply Draft may create more than "
                f"{constraints['maximum_new_personas_to_create']} new persona/character profile(s) when the requested draft cast needs it."
            )
        return (
            "Master Story generation constraints:\n"
            f"{persona_count_line}\n"
            f"{max_line}\n"
            f"- {self._master_story_safety_instruction(bool(constraints.get('sfw_mode', True)))}\n"
            f"- Existing personas: {existing}.\n"
            "- When reusing an existing persona, keep a clear separation between using that persona as-is and a story-only alternate profile."
        )

    def _on_master_story_generated(self, token: str, payload_text: str, error: str):
        generation_snapshot = getattr(self, "_master_story_generation_snapshots", {}).pop(str(token or ""), {})
        if not self._finish_worker_token(str(token or "")):
            return
        if error:
            self._set_master_story_status(f"Generation failed: {error}")
            self._warn("Generate Story Setup", f"Master Story generation failed:\n\n{error}")
            return
        payload, parse_errors = self._parse_master_story_json_text(payload_text)
        if not isinstance(payload, dict):
            message = "Generation returned text, but not valid JSON. Review or regenerate before applying."
            if parse_errors:
                message += " " + parse_errors[0]
            self._set_master_story_status(message)
            draft = str(payload_text or "").strip()
            if draft:
                self.settings["master_story_draft_text"] = draft
            return
        canonical, canonical_errors = self._canonical_master_story_payload(payload)
        canonical, structured_errors = self._structured_master_story_validation_payload(canonical)
        validation_errors = parse_errors + canonical_errors + structured_errors + self._validate_master_story_payload(canonical)
        if validation_errors:
            self.settings["master_story_draft_text"] = str(payload_text or "").strip()
            self._set_master_story_status(self._master_story_validation_message(validation_errors).replace("\n", " "))
            return
        selected_mode = str(generation_snapshot.get("mode") or "").strip()
        normalized = self._normalize_master_story_payload(
            canonical,
            mode_override=selected_mode if selected_mode in SESSION_MODES else None,
        )
        normalized = self._apply_master_story_creator_context(
            normalized,
            dict(generation_snapshot.get("scene_context") or {}),
            mode=selected_mode if selected_mode in SESSION_MODES else normalized.get("mode"),
        )
        normalized = self._sanitize_master_story_overrides_for_options(normalized)
        normalized = self._limit_generated_master_story_personas(normalized)
        self._master_story_draft = normalized
        self._set_master_story_creator_context_from_payload(normalized)
        self._set_master_story_visual_direction(normalized.get("avatar_visual_direction"))
        self._set_master_story_sfw_from_payload(normalized)
        self.settings["master_story_draft_text"] = json.dumps(normalized, indent=2, ensure_ascii=True)
        status = "Story setup generated. Review it, then Apply Draft or Save Story."
        count_warning = self._master_story_persona_count_warning(normalized)
        if count_warning:
            status += " " + count_warning
        max_warning = self._master_story_generated_persona_limit_warning(normalized)
        if max_warning:
            status += " " + max_warning
        self._set_master_story_status(status)

    def _limit_generated_master_story_personas(self, payload: dict[str, Any]) -> dict[str, Any]:
        # Keep the full generated draft visible. The max-created setting is enforced during Apply Draft.
        return payload

    def _master_story_persona_count_warning(self, payload: dict[str, Any]) -> str:
        requested = self._control_int_value("master_story_native_persona_count", 4, 0, 24)
        personas = [item for item in list((payload or {}).get("personas") or []) if isinstance(item, dict)]
        actual = len(personas)
        if actual == requested:
            return ""
        return (
            f"Requested {requested} story-native persona(s); draft returned {actual}. "
            "Review or regenerate before applying if the cast count matters."
        )

    def _master_story_generated_persona_limit_warning(self, payload: dict[str, Any]) -> str:
        if self._master_story_allow_exceed_max_created_characters():
            return ""
        max_created = self._control_int_value("master_story_max_created_characters", 8, 1, 40)
        personas = [item for item in list((payload or {}).get("personas") or []) if isinstance(item, dict)]
        if len(personas) <= max_created:
            return ""
        return (
            f"This draft contains {len(personas)} personas, but only {max_created} new personas will be created unless override is enabled."
        )

    def _set_master_story_visual_direction(self, value: Any) -> None:
        text = str(value or "").strip()
        if text and not str(self.settings.get("master_story_visual_direction") or "").strip():
            self.settings["master_story_visual_direction"] = text

    def _set_master_story_sfw_from_payload(self, payload: dict[str, Any]) -> None:
        safety = payload.get("content_safety") if isinstance(payload.get("content_safety"), dict) else {}
        self.settings["master_story_sfw_mode"] = bool(safety.get("sfw", True))

    def _sanitize_master_story_overrides_for_options(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw = dict(payload or {})
        if not self._control_checked("master_story_use_existing_personas", True):
            raw.pop("persona_overrides", None)
            return raw
        overrides = raw.get("persona_overrides")
        if not isinstance(overrides, dict):
            return raw
        allowed_ids = self._master_story_payload_persona_ids(raw)
        if not allowed_ids:
            raw.pop("persona_overrides", None)
            return raw
        clean: dict[str, dict[str, Any]] = {}
        for key, value in overrides.items():
            persona_id = normalize_persona_id(key)
            if persona_id in allowed_ids and isinstance(value, dict):
                clean[persona_id] = dict(value)
        if clean:
            raw["persona_overrides"] = clean
        else:
            raw.pop("persona_overrides", None)
        return raw

    def _master_story_payload_persona_ids(self, payload: dict[str, Any]) -> set[str]:
        ids: set[str] = set()
        for key in ("active_persona_id", "current_speaker_id", "narrator_persona_id", "selected_narrator_id"):
            persona_id = normalize_persona_id(payload.get(key))
            if persona_id:
                ids.add(persona_id)
        session = payload.get("session") if isinstance(payload.get("session"), dict) else {}
        for key in ("active_persona_id", "current_speaker_id", "narrator_persona_id", "selected_narrator_id"):
            persona_id = normalize_persona_id(session.get(key))
            if persona_id:
                ids.add(persona_id)
        ar_state = session.get("ar_state") if isinstance(session.get("ar_state"), dict) else {}
        for item in list(ar_state.get("active_characters") or []):
            persona_id = normalize_persona_id(item)
            if persona_id:
                ids.add(persona_id)
        for item in list(payload.get("personas") or []):
            if not isinstance(item, dict):
                continue
            for key in ("id", "display_name"):
                persona_id = normalize_persona_id(item.get(key))
                if persona_id:
                    ids.add(persona_id)
        return ids

    def _parse_master_story_json_text(self, text: str) -> tuple[dict[str, Any] | None, list[str]]:
        raw = str(text or "").strip()
        if not raw:
            return None, ["Master Story draft is empty."]
        errors: list[str] = []

        def reject_duplicates(pairs):
            obj: dict[str, Any] = {}
            seen: set[str] = set()
            for key, value in pairs:
                key_text = str(key)
                if key_text in seen:
                    errors.append(f"Duplicate JSON key '{key_text}' was found. Remove duplicate keys before applying the draft.")
                seen.add(key_text)
                obj[key_text] = value
            return obj

        def load(candidate: str) -> dict[str, Any] | None:
            try:
                payload = json.loads(candidate, object_pairs_hook=reject_duplicates)
            except Exception as exc:
                errors.append(f"Invalid JSON: {exc}")
                return None
            if not isinstance(payload, dict):
                errors.append("Master Story draft must be a JSON object.")
                return None
            return payload

        payload = load(raw)
        if payload is None and "{" in raw and "}" in raw:
            errors.clear()
            start = raw.find("{")
            end = raw.rfind("}")
            payload = load(raw[start : end + 1])
        return payload, errors

    def _canonical_master_story_payload(self, payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        raw = dict(payload or {})
        errors: list[str] = []
        story_keys = {
            "id",
            "title",
            "summary",
            "mode",
            "active_persona_id",
            "current_speaker_id",
            "session",
            "personas",
            "content_safety",
        }
        if isinstance(raw.get("draft"), dict):
            mixed = sorted(key for key in story_keys if key in raw)
            if mixed:
                errors.append(
                    "Master Story JSON mixes wrapper fields with story fields at the same level: "
                    + ", ".join(mixed)
                    + ". Put the story only inside draft or return the story object directly."
                )
            draft = dict(raw.get("draft") or {})
            if isinstance(raw.get("generation_constraints"), dict) and not isinstance(draft.get("generation"), dict):
                draft["generation"] = dict(raw.get("generation_constraints") or {})
            return draft, errors
        return raw, errors

    def _validate_master_story_payload(self, payload: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        from .scenario_models import validate_story_extension, ScenarioValidationError
        try:
            validate_story_extension(payload)
        except ScenarioValidationError as exc:
            errors.append(str(exc))
        required = ("id", "title", "mode", "session", "personas")
        for key in required:
            if key not in payload:
                errors.append(f"Missing required field: {key}.")
        if "session" in payload and not isinstance(payload.get("session"), dict):
            errors.append("Field 'session' must be an object.")
        mode = str(payload.get("mode") or "").strip()
        if mode and mode not in SESSION_MODES:
            errors.append(f"Unsupported mode '{mode}'.")
        personas = payload.get("personas")
        if not isinstance(personas, list):
            errors.append("Field 'personas' must be an array.")
            personas = []
        requested = self._control_int_value("master_story_native_persona_count", 4, 0, 24)
        if requested > 0 and isinstance(personas, list) and not personas:
            errors.append(f"Draft requested {requested} story-native persona(s), but personas is empty.")
        ids: list[str] = []
        for index, item in enumerate(list(personas or []), start=1):
            if not isinstance(item, dict):
                errors.append(f"Persona {index} must be an object.")
                continue
            persona_id = normalize_persona_id(item.get("id"))
            if not persona_id:
                errors.append(f"Persona {index} is missing id.")
            else:
                ids.append(persona_id)
            if not str(item.get("display_name") or "").strip():
                errors.append(f"Persona {index} is missing display_name.")
            if not str(item.get("role") or "").strip():
                errors.append(f"Persona {index} is missing role.")
            if not str(item.get("system_prompt") or item.get("ar_system_prompt") or "").strip():
                errors.append(f"Persona {index} must include system_prompt or ar_system_prompt.")
        duplicates = sorted({persona_id for persona_id in ids if ids.count(persona_id) > 1})
        if duplicates:
            errors.append("Duplicate persona id(s) in draft: " + ", ".join(duplicates) + ".")
        known_ids = {persona.id for persona in self.personas}
        known_ids.update(ids)
        narrator_id = normalize_persona_id(payload.get("narrator_persona_id"))
        if narrator_id:
            known_ids.add(narrator_id)
        session = payload.get("session") if isinstance(payload.get("session"), dict) else {}
        for key in ("active_persona_id", "current_speaker_id"):
            value = normalize_persona_id(payload.get(key) or session.get(key))
            if value and value not in known_ids:
                errors.append(f"{key} '{value}' does not match a draft persona, existing persona, or narrator id.")
        return errors

    def _master_story_validation_message(self, errors: list[str]) -> str:
        return "Master Story draft validation failed:\n\n" + "\n".join(f"- {item}" for item in errors[:12])

    def _structured_master_story_validation_payload(self, payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        if not self._mprc_instructor_feature_enabled("mprc_instructor_master_story_validation_enabled"):
            return dict(payload or {}), []
        clean_payload, errors = structured_models.validate_master_story_draft(payload)
        return clean_payload if isinstance(clean_payload, dict) else {}, list(errors or [])

    def _normalize_master_story_payload(
        self,
        payload: dict[str, Any],
        *,
        mode_override: str | None = None,
    ) -> dict[str, Any]:
        raw, _errors = self._canonical_master_story_payload(payload)
        raw = dict(raw or {})
        title = str(raw.get("title") or raw.get("id") or "Master Story").strip() or "Master Story"
        story_id = self.storage.story_id(raw.get("id") or title)
        session = dict(raw.get("session") or {}) if isinstance(raw.get("session"), dict) else {}
        requested_mode = str(mode_override or "").strip()
        mode = requested_mode if requested_mode in SESSION_MODES else str(raw.get("mode") or session.get("mode") or "").strip()
        if mode not in SESSION_MODES:
            mode = self._master_story_mode()
        raw["id"] = story_id
        raw["title"] = title[:120]
        raw["summary"] = str(raw.get("summary") or session.get("scene_summary") or "").strip()
        if not str(raw.get("avatar_visual_direction") or "").strip():
            raw["avatar_visual_direction"] = str(
                self.settings.get("master_story_visual_direction") or ""
            ).strip()
        raw["mode"] = mode
        personas = []
        seen = set()
        for item in list(raw.get("personas") or []):
            if not isinstance(item, dict):
                continue
            persona_payload = dict(item)
            persona_id = normalize_persona_id(persona_payload.get("id") or persona_payload.get("display_name") or "story_persona")
            persona_id = unique_persona_id(persona_id, seen)
            seen.add(persona_id)
            persona_payload["id"] = persona_id
            if not str(persona_payload.get("display_name") or "").strip():
                persona_payload["display_name"] = persona_id.replace("_", " ").title()
            if not isinstance(persona_payload.get("visual"), dict):
                appearance = str(
                    persona_payload.get("visual_description")
                    or persona_payload.get("appearance")
                    or persona_payload.get("avatar_description")
                    or ""
                ).strip()
                if appearance:
                    persona_payload["visual"] = {
                        "enabled": True,
                        "mode": "manual",
                        "provider": "inherit",
                        "size": "inherit",
                        "character_description": appearance,
                        "negative_prompt": "text, watermark, logo, distorted face, extra limbs",
                    }
            personas.append(persona_payload)
        raw["personas"] = personas
        active_id = normalize_persona_id(raw.get("active_persona_id") or session.get("active_persona_id") or (personas[0]["id"] if personas else self.session.active_persona_id))
        speaker_id = normalize_persona_id(raw.get("current_speaker_id") or session.get("current_speaker_id") or active_id)
        raw["active_persona_id"] = active_id
        raw["current_speaker_id"] = speaker_id
        session["mode"] = mode
        raw["session"] = session
        content_safety = raw.get("content_safety") if isinstance(raw.get("content_safety"), dict) else {}
        sfw = bool(content_safety.get("sfw", True))
        raw["content_safety"] = {
            **self._master_story_content_safety_payload(sfw),
            **{key: value for key, value in content_safety.items() if key in {"sfw", "allow_romance", "allow_mature_themes", "allow_explicit_sexual_content"}},
        }
        raw["content_safety"]["allow_explicit_sexual_content"] = False
        generation = raw.get("generation") if isinstance(raw.get("generation"), dict) else {}
        raw["generation"] = {
            "source": "master_story_creator",
            "requested_story_native_personas": self._control_int_value("master_story_native_persona_count", 4, 0, 24),
            "maximum_new_personas_to_create": self._control_int_value("master_story_max_created_characters", 8, 1, 40),
            "use_existing_personas": self._control_checked("master_story_use_existing_personas", True),
            "auto_create_missing_personas": self._control_checked("master_story_auto_create", True),
            "sfw_mode": bool(raw["content_safety"].get("sfw", True)),
            **generation,
        }
        raw["updated_at"] = QtCore.QDateTime.currentDateTimeUtc().toString(QtCore.Qt.ISODate)
        return raw

    def _parse_master_story_draft(self) -> dict[str, Any] | None:
        draft = str(self._controls.get("master_story_draft").toPlainText() if self._controls.get("master_story_draft") is not None else "").strip()
        if not draft and self._master_story_draft:
            normalized = self._normalize_master_story_payload(self._master_story_draft, mode_override=self._master_story_mode())
            return self._apply_master_story_creator_context(
                normalized,
                self._master_story_creator_scene_context(),
                mode=self._master_story_mode(),
            )
        payload, parse_errors = self._parse_master_story_json_text(draft)
        if not isinstance(payload, dict):
            if parse_errors:
                self._set_master_story_status(self._master_story_validation_message(parse_errors).replace("\n", " "))
            return None
        canonical, canonical_errors = self._canonical_master_story_payload(payload)
        canonical, structured_errors = self._structured_master_story_validation_payload(canonical)
        errors = parse_errors + canonical_errors + structured_errors + self._validate_master_story_payload(canonical)
        if errors:
            self._set_master_story_status(self._master_story_validation_message(errors).replace("\n", " "))
            return None
        normalized = self._normalize_master_story_payload(canonical, mode_override=self._master_story_mode())
        normalized = self._apply_master_story_creator_context(
            normalized,
            self._master_story_creator_scene_context(),
            mode=self._master_story_mode(),
        )
        self._set_master_story_sfw_from_payload(normalized)
        return normalized

    def _apply_master_story_draft(self):
        payload = self._parse_master_story_draft()
        if not isinstance(payload, dict):
            self._warn("Apply Draft", "The Master Story draft is not valid or does not match the required story schema. Check the Master Story status message.")
            return
        payload = self._sanitize_master_story_overrides_for_options(payload)
        apply_plan = self._show_master_story_apply_dialog(payload)
        if apply_plan is None:
            self._set_master_story_status("Apply Draft cancelled.")
            return
        self._apply_master_story_payload(payload, apply_plan=apply_plan)

    def _show_master_story_apply_dialog(self, payload: dict[str, Any]) -> None:
        # Publish the apply review; native QML submits the explicit plan.
        normalized = self._normalize_master_story_payload(payload)
        rows: list[dict[str, Any]] = []
        persona_choices: dict[str, str] = {}
        actions_by_row: dict[str, str] = {}
        for row, item in enumerate(list(normalized.get("personas") or [])):
            if not isinstance(item, dict):
                continue
            draft_id = normalize_persona_id(item.get("id") or item.get("display_name") or f"story_persona_{row + 1}")
            match = self._find_persona_for_story(item)
            choice = match.id if match is not None else "__create__"
            action = "story_profile" if match is not None else "__create__"
            persona_choices[draft_id] = choice
            actions_by_row[str(row)] = action
            rows.append(
                {
                    "row": row,
                    "draft_id": draft_id,
                    "display_name": str(item.get("display_name") or draft_id),
                    "description": str(item.get("description") or ""),
                    "character_image_path": str(item.get("character_image_path") or ""),
                    "suggested_persona_id": choice,
                    "suggested_action": action,
                }
            )
        default_plan = {
            "persona_choices": persona_choices,
            "persona_actions_by_row": actions_by_row,
            "clear_memory": bool(self.settings.get("master_story_clear_memory", True)),
            "update_existing": bool(self.settings.get("master_story_update_existing", True)),
            "auto_avatars": bool(self.settings.get("master_story_auto_avatars", True)),
            "avatar_style_sheets": bool(self.settings.get("master_story_avatar_style_sheets", False)),
            "allow_exceed_max_created_characters": bool(self.settings.get("master_story_allow_exceed_max_created_characters", False)),
        }
        self._native_master_story_apply_review = {
            "payload": copy.deepcopy(normalized),
            "personas": rows,
            "default_plan": default_plan,
            "requires_confirmation": True,
        }
        return None
    def _apply_dialog_initial_icon(self, text: str, size: int = 64):
        from PySide6 import QtCore, QtGui

        size = max(24, int(size or 64))
        pixmap = QtGui.QPixmap(size, size)
        pixmap.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setBrush(QtGui.QColor("#162235"))
        painter.setPen(QtGui.QPen(QtGui.QColor("#36506d"), max(1, size // 28)))
        painter.drawRoundedRect(1, 1, size - 2, size - 2, max(6, size // 8), max(6, size // 8))
        initials = "".join(part[:1].upper() for part in str(text or "New").replace("_", " ").split()[:2]) or "?"
        font = painter.font()
        font.setBold(True)
        font.setPointSize(max(9, size // 4))
        painter.setFont(font)
        painter.setPen(QtGui.QColor("#dbeafe"))
        painter.drawText(pixmap.rect(), QtCore.Qt.AlignCenter, initials[:2])
        painter.end()
        return QtGui.QIcon(pixmap)

    def _apply_dialog_persona_icon(self, persona: PersonaConfig | None, size: int = 64):
        from PySide6 import QtCore, QtGui

        if persona is None:
            return self._apply_dialog_initial_icon("New", size)
        path = Path(str(getattr(persona, "character_image_path", "") or "").strip())
        if path.exists():
            pixmap = QtGui.QPixmap(str(path))
            if not pixmap.isNull():
                return QtGui.QIcon(pixmap.scaled(size, size, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
        return self._apply_dialog_initial_icon(str(persona.display_name or persona.id), size)

    def _apply_dialog_path_icon(self, image_path: str, size: int = 64, *, fallback_text: str = "Draft"):
        from PySide6 import QtCore, QtGui

        path = Path(str(image_path or "").strip())
        if path.exists():
            pixmap = QtGui.QPixmap(str(path))
            if not pixmap.isNull():
                return QtGui.QIcon(pixmap.scaled(size, size, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
        return self._apply_dialog_initial_icon(fallback_text, size)

    def _apply_dialog_default_alternate_profile(self, persona_payload: dict[str, Any]) -> str:
        draft_id = normalize_persona_id(persona_payload.get("id") or persona_payload.get("display_name") or "story_persona")
        lines = [
            f"Story name: {str(persona_payload.get('display_name') or draft_id.replace('_', ' ').title()).strip()}",
            f"Story role: {str(persona_payload.get('role') or persona_payload.get('behavior_mode') or '').strip()}",
        ]
        for label, key in (
            ("Story description", "description"),
            ("AR description", "ar_description"),
            ("Speaking style", "speaking_style"),
            ("Tone", "allowed_tone"),
        ):
            value = str(persona_payload.get(key) or "").strip()
            if value:
                lines.append(f"{label}: {value}")
        return "\n".join(line for line in lines if line.strip())

    def _apply_dialog_draft_summary(self, persona_payload: dict[str, Any], payload: dict[str, Any]) -> str:
        draft_id = normalize_persona_id(persona_payload.get("id") or persona_payload.get("display_name") or "story_persona")
        visual = persona_payload.get("visual") if isinstance(persona_payload.get("visual"), dict) else {}
        session = payload.get("session") if isinstance(payload.get("session"), dict) else {}
        lines = [
            f"Name: {str(persona_payload.get('display_name') or draft_id.replace('_', ' ').title()).strip()}",
            f"Draft ID: {draft_id}",
            f"Role: {str(persona_payload.get('role') or persona_payload.get('behavior_mode') or 'Not specified').strip()}",
            f"Behavior: {str(persona_payload.get('behavior_mode') or 'default').strip()}",
            f"Memory scope: {str(persona_payload.get('memory_scope') or 'persona-only').strip()}",
        ]
        description = str(persona_payload.get("description") or "").strip()
        if description:
            lines.append(f"Description: {description[:360]}")
        ar_description = str(persona_payload.get("ar_description") or "").strip()
        if ar_description:
            lines.append(f"AR description: {ar_description[:360]}")
        if visual:
            visual_lines = []
            for label, key in (
                ("Visual", "character_description"),
                ("Clothing / props", "clothing_props"),
                ("Environment", "environment_style"),
            ):
                value = str(visual.get(key) or "").strip()
                if value:
                    visual_lines.append(f"{label}: {value[:240]}")
            if visual_lines:
                lines.append("Draft visual profile:")
                lines.extend(visual_lines)
        story_bits = []
        for key in ("scene_title", "location", "objective", "mood"):
            value = str(session.get(key) or payload.get(key) or "").strip()
            if value:
                story_bits.append(f"{key.replace('_', ' ').title()}: {value[:180]}")
        if story_bits:
            lines.append("Story context:")
            lines.extend(story_bits)
        return "\n".join(lines)

    def _apply_dialog_persona_summary(self, persona: PersonaConfig | None) -> str:
        if persona is None:
            return (
                "Action: Create a new persona from the drafted character.\n"
                "The new persona will receive the draft prompt, AR profile, visual profile, tags, and story link. "
                "It will not have a real voice sample until you add one in the Voice tab."
            )
        voice_sample = str(getattr(persona.voice, "sample_path", "") or "").strip()
        voice_ready = bool(getattr(persona.voice, "enabled", False) and voice_sample and Path(voice_sample).exists())
        image_path = str(getattr(persona, "character_image_path", "") or "").strip()
        image_ready = bool(image_path and Path(image_path).exists())
        lines = [
            f"Existing persona: {persona.display_name} ({persona.id})",
            f"Role: {persona.role or persona.behavior_mode or 'Not specified'}",
            f"Voice: {'ready' if voice_ready else ('enabled but missing sample' if getattr(persona.voice, 'enabled', False) else 'off')}",
            f"Avatar image: {'ready' if image_ready else 'missing'}",
            f"Memory: {persona.memory_scope or 'default'}",
            f"Behavior: {persona.behavior_mode or 'default'}",
        ]
        if persona.description:
            lines.append(f"Description: {persona.description[:320]}")
        involvement = self._current_character_story_text(persona)
        if involvement:
            lines.append(involvement)
        return "\n".join(lines)

    def _apply_dialog_effect_summary(
        self,
        persona_payload: dict[str, Any],
        payload: dict[str, Any],
        *,
        choice: str,
        action: str = "",
        update_existing: bool,
        clean_start: bool,
        auto_avatars: bool,
        avatar_style_sheets: bool = False,
        allow_exceed_max: bool = False,
        draft_voice_path: str = "",
    ) -> str:
        action = str(action or ("__create__" if str(choice or "") in {"", "__create__"} else "story_profile")).strip()
        selected = self.persona_by_id(choice) if action != "__create__" and str(choice or "") not in {"", "__create__"} else None
        draft_name = str(persona_payload.get("display_name") or persona_payload.get("id") or "Draft character").strip()
        lines = []
        if action == "__create__" or selected is None:
            lines.extend(
                [
                    f"Create: {draft_name}",
                    "A fresh persona will be created from the draft.",
                    "Prompt, AR profile, visual profile, tags, behavior, and story link come from the draft.",
                    f"Avatar request: {'will be requested through Visual Reply' if auto_avatars else 'will be skipped'} for the new persona.",
                    f"Avatar style sheet: {'will be requested after an avatar image exists' if avatar_style_sheets else 'will be skipped'} for the new persona.",
                ]
            )
        elif action == "reuse_as_is":
            lines.extend(
                [
                    f"Use as-is: {selected.display_name} ({selected.id})",
                    "The story will link this drafted character to the selected existing persona.",
                    "No base persona prompt, visual profile, avatar, or voice fields will be changed.",
                    "No story-only alternate profile will be stored for this character.",
                ]
            )
        elif action == "reuse_update":
            draft_has_image = bool(str(persona_payload.get("character_image_path") or "").strip())
            lines.extend(
                [
                    f"Update: {selected.display_name} ({selected.id})",
                    "The story will link this drafted character to the selected existing persona.",
                    "Voice sample: kept from the existing persona.",
                    "Avatar picture: kept from the existing persona unless the draft contains a non-empty replacement path.",
                    f"Draft has replacement picture path: {'yes' if draft_has_image else 'no'}.",
                    "Prompt/profile update: draft fields will update this persona.",
                ]
            )
        else:
            draft_has_image = bool(str(persona_payload.get("character_image_path") or "").strip())
            lines.extend(
                [
                    f"Story-only alternate profile: {selected.display_name} ({selected.id})",
                    "The story will link this drafted character to the selected existing persona.",
                    "Base persona fields, voice, and avatar image stay unchanged.",
                    "The draft role, descriptions, AR profile, visual prompt, and editable story-only notes are saved as story-specific persona info.",
                    f"Draft has replacement picture path: {'yes' if draft_has_image else 'no'}.",
                    "Prompt/profile update: story-only for this Master Story.",
                ]
            )
        story_title = str(payload.get("title") or payload.get("id") or "this Master Story").strip()
        lines.append(f"Story link: character will be linked to {story_title}.")
        lines.append(f"Memory: {'old MPRC story memory will be cleared first' if clean_start else 'existing MPRC memory will be kept'} before applying.")
        if action == "__create__" or selected is None:
            max_created = self._control_int_value("master_story_max_created_characters", 8, 1, 40)
            lines.append(
                f"Creation limit: {'override enabled' if allow_exceed_max else f'max {max_created} new persona(s)'} for this apply."
            )
        voice_path = str(draft_voice_path or "").strip()
        if voice_path:
            lines.append(f"Voice: {Path(voice_path).name} will be assigned to the resulting persona.")
        else:
            lines.append("Voice: no new voice sample selected for this draft character.")
        return "\n".join(lines)

    def _draft_avatar_prompt_preview(self, persona_payload: dict[str, Any], payload: dict[str, Any]) -> str:
        override = str((persona_payload or {}).get("avatar_prompt_override") or "").strip()
        if override:
            return override
        persona = PersonaConfig.from_dict(persona_payload)
        self._fill_story_visual_profile(persona, persona_payload)
        return self._story_avatar_prompt(persona, payload)

    def _request_master_story_draft_avatar_image(
        self,
        persona_payload: dict[str, Any],
        payload: dict[str, Any],
        *,
        regenerate: bool = False,
        prompt_override: str = "",
        commit_guard=None,
    ) -> dict[str, Any]:
        if not self._visual_commit_allowed(commit_guard):
            return {"ok": False, "message": "Draft avatar generation was cancelled."}
        draft_id = normalize_persona_id(persona_payload.get("id") or persona_payload.get("display_name") or "story_persona")
        existing_path = str(persona_payload.get("character_image_path") or "").strip()
        if existing_path and Path(existing_path).exists() and not bool(regenerate):
            return {
                "ok": True,
                "image_path": existing_path,
                "message": "Draft avatar image is already ready. Use Regenerate to request a fresh one.",
            }
        service = self.visual_reply_service
        if service is None or not hasattr(service, "request_generation"):
            self._record_visual_debug(
                source="master_story_draft_avatar",
                reason="draft_avatar",
                accepted=False,
                message="Draft avatar generation skipped because the Visual Reply service is unavailable.",
                commit_guard=commit_guard,
            )
            return {
                "ok": False,
                "message": "Visual Reply generation service is unavailable. Open Visual Reply or choose an avatar image later.",
            }
        persona = PersonaConfig.from_dict(persona_payload)
        self._fill_story_visual_profile(persona, persona_payload)
        prompt = str(prompt_override or "").strip() or self._story_avatar_prompt(persona, payload)
        if not prompt:
            self._record_visual_debug(
                source="master_story_draft_avatar",
                reason="draft_avatar",
                persona=persona,
                accepted=False,
                message="Draft avatar generation skipped because the draft has no usable visual prompt.",
                commit_guard=commit_guard,
            )
            return {"ok": False, "message": "This draft persona does not have a usable avatar prompt yet."}
        self._record_visual_debug(
            source="master_story_draft_avatar",
            reason="draft_avatar",
            persona=persona,
            accepted=None,
            message="Master Story draft avatar request sent to Visual Reply.",
            prompt=prompt,
            commit_guard=commit_guard,
        )
        try:
            committed, result = self._visual_commit(
                commit_guard,
                lambda: service.request_generation(
                    prompt=prompt,
                    caption=f"MPRC draft avatar: {persona.display_name}",
                    provider=str(persona.visual.provider or "inherit"),
                    model=str(persona.visual.model or ""),
                    size="1024x1024",
                    source="nc.multi_persona_roleplay.master_story_draft_avatar",
                    metadata={
                        "draft_id": draft_id,
                        "story_id": str(payload.get("id") or ""),
                        "story_title": str(payload.get("title") or ""),
                        "purpose": "draft_story_avatar",
                        "regenerate": bool(regenerate),
                    },
                    auto_show=True,
                ),
            )
        except Exception as exc:
            if not self._visual_commit_allowed(commit_guard):
                return {"ok": False, "message": "Draft avatar generation was cancelled."}
            logger = getattr(self.context, "logger", None)
            if logger is not None:
                logger.warning("[MPRC] Master Story draft avatar generation failed for %s: %s", draft_id, exc)
            self._record_visual_debug(
                source="master_story_draft_avatar",
                reason="draft_avatar",
                persona=persona,
                accepted=False,
                message=f"Master Story draft avatar generation failed: {exc}",
                prompt=prompt,
                commit_guard=commit_guard,
            )
            return {"ok": False, "message": f"Draft avatar generation failed:\n\n{exc}"}
        if not committed:
            return {"ok": False, "message": "Draft avatar generation was cancelled."}
        image_path = str(result.get("image_path") or "").strip() if isinstance(result, dict) else ""
        if image_path and Path(image_path).exists():
            self._record_visual_debug(
                source="master_story_draft_avatar",
                reason="draft_avatar",
                persona=persona,
                accepted=True,
                message=f"Master Story draft avatar generated: {image_path}",
                prompt=prompt,
                commit_guard=commit_guard,
            )
            return {"ok": True, "image_path": image_path, "message": "Draft avatar image generated."}
        if result:
            self._record_visual_debug(
                source="master_story_draft_avatar",
                reason="draft_avatar",
                persona=persona,
                accepted=True,
                message="Visual Reply accepted the draft avatar request, but no image path was returned yet.",
                prompt=prompt,
                commit_guard=commit_guard,
            )
            return {
                "ok": True,
                "image_path": "",
                "message": "Visual Reply accepted the draft avatar request, but no image path was returned yet.",
            }
        self._record_visual_debug(
            source="master_story_draft_avatar",
            reason="draft_avatar",
            persona=persona,
            accepted=False,
            message="Visual Reply did not accept the Master Story draft avatar request.",
            prompt=prompt,
            commit_guard=commit_guard,
        )
        return {"ok": False, "message": "Visual Reply did not accept the draft avatar request."}

    def _apply_master_story_payload(self, payload: dict[str, Any], apply_plan: dict[str, Any] | None = None) -> dict[str, Any]:
        from .scenario_transfer import preflight_story_extension
        preflight_story_extension(payload)
        payload = self._normalize_master_story_payload(payload)
        preflight_story_extension(payload)
        apply_plan = dict(apply_plan or {})
        from .scenario_transfer import preflight_scenario_apply
        preflight_scenario_apply(self, payload, apply_plan)
        if hasattr(self, "_mprc_tts_state_lock"):
            self._stop_mprc_chat_playback()
        if not bool(apply_plan.get("skip_backup", False)):
            self._save_pre_apply_backup(str(apply_plan.get("backup_reason") or "Apply Draft"))
        auto_create = bool(apply_plan.get("auto_create", self._control_checked("master_story_auto_create", True)))
        update_existing = bool(apply_plan.get("update_existing", self._control_checked("master_story_update_existing", True)))
        auto_avatars = bool(apply_plan.get("auto_avatars", self._control_checked("master_story_auto_avatars", True)))
        avatar_style_sheets = bool(apply_plan.get("avatar_style_sheets", self._control_checked("master_story_avatar_style_sheets", False)))
        auto_assign_voices = bool(
            apply_plan.get(
                "auto_assign_voices",
                self._control_checked(
                    "master_story_auto_assign_voices",
                    bool(self.settings.get("master_story_auto_assign_voices", True)),
                ),
            )
        )
        allow_exceed_max = bool(apply_plan.get("allow_exceed_max_created_characters", self._master_story_allow_exceed_max_created_characters()))
        clear_memory = bool(apply_plan.get("clear_memory", self._control_checked("master_story_clear_memory", True)))
        persist_memory_snapshot = bool(apply_plan.get("persist_memory_snapshot", True))
        if clear_memory:
            self._clear_master_story_runtime_state(clear_long_memory=True, enabled=False)
        self._set_mprc_play_isolated_active(False)
        self._reset_mprc_chat_history()
        self.roleplay_engine._recent_assistant_texts = []
        persona_choices = dict(apply_plan.get("persona_choices") or {})
        persona_choices_by_row = dict(apply_plan.get("persona_choices_by_row") or {})
        persona_actions_by_row = dict(apply_plan.get("persona_actions_by_row") or {})
        persona_alternates_by_row = dict(apply_plan.get("persona_alternates_by_row") or {})
        draft_avatar_paths_by_row = dict(apply_plan.get("draft_avatar_paths_by_row") or {})
        draft_avatar_prompts_by_row = dict(apply_plan.get("draft_avatar_prompts_by_row") or {})
        draft_voice_paths_by_row = dict(apply_plan.get("draft_voice_paths_by_row") or {})
        saved_overrides = payload.get("persona_overrides") if isinstance(payload.get("persona_overrides"), dict) else {}
        max_created = self._control_int_value("master_story_max_created_characters", 8, 1, 40)
        linked_ids: list[str] = []
        created_ids: list[str] = []
        story_id_map: dict[str, str] = {}
        story_overrides: dict[str, dict[str, Any]] = {}
        created = 0
        created_characters = 0
        updated = 0
        voice_assigned = 0
        skipped: list[str] = []
        reserved_voice_paths = {
            self._normalized_path_text(getattr(getattr(persona, "voice", None), "sample_path", ""))
            for persona in self.personas
            if str(getattr(getattr(persona, "voice", None), "sample_path", "") or "").strip()
        }
        for row, item in enumerate(list(payload.get("personas") or [])):
            if not isinstance(item, dict):
                continue
            item = dict(item)
            if payload.get("mode") == AR_MODE and "ar_profile_enabled" not in item:
                item["ar_profile_enabled"] = True
            payload_personas = payload.get("personas")
            draft_avatar_path = str(draft_avatar_paths_by_row.get(str(row)) or draft_avatar_paths_by_row.get(row) or "").strip()
            if draft_avatar_path:
                item["character_image_path"] = draft_avatar_path
                if isinstance(payload_personas, list) and row < len(payload_personas) and isinstance(payload_personas[row], dict):
                    payload_personas[row]["character_image_path"] = draft_avatar_path
            draft_avatar_prompt = str(draft_avatar_prompts_by_row.get(str(row)) or draft_avatar_prompts_by_row.get(row) or "").strip()
            if draft_avatar_prompt:
                item["avatar_prompt_override"] = draft_avatar_prompt
                if isinstance(payload_personas, list) and row < len(payload_personas) and isinstance(payload_personas[row], dict):
                    payload_personas[row]["avatar_prompt_override"] = draft_avatar_prompt
            draft_voice_path = str(draft_voice_paths_by_row.get(str(row)) or draft_voice_paths_by_row.get(row) or "").strip()
            if draft_voice_path:
                voice_payload = dict(item.get("voice") or {}) if isinstance(item.get("voice"), dict) else {}
                voice_payload["enabled"] = True
                voice_payload["sample_path"] = draft_voice_path
                voice_payload.setdefault("backend", "inherit")
                item["voice"] = voice_payload
                if isinstance(payload_personas, list) and row < len(payload_personas) and isinstance(payload_personas[row], dict):
                    payload_personas[row]["voice"] = dict(voice_payload)
            draft_id = normalize_persona_id(item.get("id") or item.get("display_name") or "")
            choice = str(persona_choices_by_row.get(str(row), persona_choices.get(draft_id, "")) or "").strip()
            action = str(persona_actions_by_row.get(str(row), "") or "").strip()
            if not action:
                action = "__create__" if choice == "__create__" else ("reuse_update" if update_existing else "story_profile")
            match = None if action == "__create__" or choice == "__create__" else self.persona_by_id(choice)
            if action != "__create__" and match is None and choice not in {"__create__", ""}:
                skipped.append(str(item.get("display_name") or item.get("id") or "persona"))
                continue
            if match is None and action != "__create__" and choice != "__create__":
                match = self._find_persona_for_story(item)
            if draft_voice_path:
                reserved_voice_paths.add(self._normalized_path_text(draft_voice_path))
            elif auto_assign_voices and match is None:
                draft_voice_path = self._suggest_story_voice_sample(item, reserved_voice_paths)
                if draft_voice_path:
                    reserved_voice_paths.add(self._normalized_path_text(draft_voice_path))
                    voice_payload = dict(item.get("voice") or {}) if isinstance(item.get("voice"), dict) else {}
                    voice_payload.update({"enabled": True, "backend": "inherit", "sample_path": draft_voice_path})
                    item["voice"] = voice_payload
                    if isinstance(payload_personas, list) and row < len(payload_personas) and isinstance(payload_personas[row], dict):
                        payload_personas[row]["voice"] = dict(voice_payload)
            if action == "reuse_update" and match is not None and isinstance(saved_overrides.get(match.id), dict):
                action = "story_profile"
            if match is not None:
                linked_ids.append(match.id)
                if draft_id:
                    story_id_map[draft_id] = match.id
                if action == "reuse_update":
                    self._merge_story_persona(match, item)
                    updated += 1
                elif action == "story_profile":
                    if isinstance(saved_overrides.get(match.id), dict):
                        story_overrides[match.id] = dict(saved_overrides.get(match.id) or {})
                    else:
                        story_overrides[match.id] = self._story_persona_override_from_draft(
                            match,
                            item,
                            payload,
                            alternate_text=str(persona_alternates_by_row.get(str(row), "") or ""),
                        )
                if draft_voice_path and self._apply_story_voice_sample(match, draft_voice_path):
                    voice_assigned += 1
                continue
            create_allowed = bool(auto_create or action == "__create__" or choice == "__create__")
            if not create_allowed:
                skipped.append(str(item.get("display_name") or item.get("id") or "persona"))
                continue
            persona_payload = dict(item)
            persona_payload["id"] = unique_persona_id(persona_payload.get("id") or persona_payload.get("display_name") or "story_persona", {p.id for p in self.personas})
            if payload.get("mode") == AR_MODE:
                persona_payload["ar_profile_enabled"] = True
            persona = PersonaConfig.from_dict(persona_payload)
            is_narrator = self._persona_looks_like_narrator(persona)
            if not allow_exceed_max and not is_narrator and created_characters >= max_created:
                skipped.append(f"{str(item.get('display_name') or item.get('id') or 'persona')} (creation limit)")
                continue
            self._fill_story_visual_profile(persona, persona_payload)
            if draft_avatar_prompt:
                setattr(persona, "_mprc_avatar_prompt_override", draft_avatar_prompt)
            self.personas.append(persona)
            linked_ids.append(persona.id)
            created_ids.append(persona.id)
            if draft_voice_path and str(getattr(persona.voice, "sample_path", "") or "").strip():
                voice_assigned += 1
            if draft_id:
                story_id_map[draft_id] = persona.id
            created += 1
            if not is_narrator:
                created_characters += 1
        payload_overrides = payload.get("persona_overrides")
        if isinstance(payload_overrides, dict):
            for key, value in payload_overrides.items():
                persona_id = normalize_persona_id(key)
                if persona_id and isinstance(value, dict) and persona_id in linked_ids:
                    story_overrides.setdefault(persona_id, dict(value))
        session_payload = dict(payload.get("session") or {}) if isinstance(payload.get("session"), dict) else {}
        self.session.enabled = False
        self.session.mode = str(payload.get("mode") or session_payload.get("mode") or self.session.mode or "Narrator + characters")
        if self.session.mode not in SESSION_MODES:
            self.session.mode = self._master_story_mode()
        self.session.active_persona_id = self._story_persona_id(payload.get("active_persona_id"), linked_ids, id_map=story_id_map)
        self.session.current_speaker_id = self._story_persona_id(payload.get("current_speaker_id"), linked_ids, fallback=self.session.active_persona_id, id_map=story_id_map)
        for key in ("scene_title", "location", "time_of_day", "mood", "objective", "scene_summary"):
            value = str(session_payload.get(key) or "").strip()
            if value:
                setattr(self.session, key, value)
        if not self.session.scene_summary and str(payload.get("summary") or "").strip():
            self.session.scene_summary = str(payload.get("summary") or "").strip()
        self.session.auto_select_speaker = len(linked_ids) > 1
        self.session.keep_scene_continuity = True
        self.session.update_scene_after_reply = True
        self.session.character_state_summaries = self._story_character_summaries(linked_ids)

        if self.session.mode == AR_MODE:
            from addons.multi_persona_roleplay.models import AlternativeRealityState

            self.session.ar_use_persona_profiles = True
            pacing = str(session_payload.get("ar_pacing") or "").strip()
            interaction = str(session_payload.get("ar_interaction_frequency") or "").strip()
            dialogue_density = str(session_payload.get("ar_dialogue_density") or "").strip()
            if pacing in AR_PACING_MODES:
                self.session.ar_pacing = pacing
            if interaction in AR_INTERACTION_FREQUENCIES:
                self.session.ar_interaction_frequency = interaction
            if dialogue_density in AR_DIALOGUE_DENSITY_MODES:
                self.session.ar_dialogue_density = dialogue_density
            ar_payload = dict(session_payload.get("ar_state") or {}) if isinstance(session_payload.get("ar_state"), dict) else {}
            raw_characters = ar_payload.get("active_characters")
            if isinstance(raw_characters, list):
                mapped_characters: list[str] = []
                for item in raw_characters:
                    if not str(item or "").strip():
                        continue
                    mapped = story_id_map.get(normalize_persona_id(item), normalize_persona_id(item))
                    if mapped in linked_ids and mapped not in mapped_characters:
                        mapped_characters.append(mapped)
                ar_payload["active_characters"] = mapped_characters
            state = AlternativeRealityState.from_dict(ar_payload)
            if not state.active_characters:
                state.active_characters = linked_ids[:6]
            if not state.current_scene:
                state.current_scene = self.session.scene_title or self.session.scene_summary
            if not state.location:
                state.location = self.session.location
            if not state.story_goal:
                state.story_goal = self.session.objective
            if not state.mood:
                state.mood = self.session.mood
            if not state.time_of_day:
                state.time_of_day = self.session.time_of_day
            self.session.ar_state = state
            self.ensure_ar_state()

        narrator_raw = (
            payload.get("narrator_persona_id")
            or session_payload.get("narrator_persona_id")
            or payload.get("selected_narrator_id")
            or ""
        )
        narrator_id = story_id_map.get(normalize_persona_id(narrator_raw), normalize_persona_id(narrator_raw)) if str(narrator_raw or "").strip() else ""
        if not narrator_id or self.persona_by_id(narrator_id) is None:
            narrator_id = next(
                (
                    persona_id for persona_id in linked_ids
                    if self._persona_looks_like_narrator(self.persona_by_id(persona_id))
                ),
                "",
            )
        if not narrator_id and self.session.mode in {"Narrator + characters", "RPG / Game Master mode", AR_MODE}:
            preferred = self.selected_narrator_persona()
            if preferred is None or not self._persona_looks_like_narrator(preferred):
                preferred = next(
                    (
                        persona for persona in self._ordered_narrator_selector_personas()
                        if self._persona_looks_like_narrator(persona)
                    ),
                    None,
                )
            narrator_id = preferred.id if preferred is not None else ""
        if narrator_id and self.persona_by_id(narrator_id) is not None and narrator_id not in linked_ids:
            linked_ids.append(narrator_id)
        if narrator_id and self.persona_by_id(narrator_id) is not None:
            self.settings["narrator_persona_id"] = narrator_id
            self.settings["narrator_persona_mode"] = "explicit"
            payload["narrator_persona_id"] = narrator_id
            payload["narrator_persona_mode"] = "explicit"
            session_payload["narrator_persona_id"] = narrator_id
            session_payload["narrator_persona_mode"] = "explicit"
            payload["session"] = session_payload
        if self.session.mode == AR_MODE:
            active_characters = [
                normalize_persona_id(item)
                for item in list(self.session.ar_state.active_characters or [])
                if normalize_persona_id(item) in linked_ids
            ]
            for persona_id in linked_ids:
                if persona_id not in active_characters:
                    active_characters.append(persona_id)
            self.session.ar_state.active_characters = active_characters[:8]
        activation_result = self._sync_story_persona_activation(linked_ids, narrator_id=narrator_id)

        payload = self._remap_story_payload_persona_ids(payload, story_id_map)
        applied_personas: list[dict[str, Any]] = []
        applied_persona_ids: set[str] = set()
        for item in list(payload.get("personas") or []):
            if not isinstance(item, dict):
                continue
            persona_id = normalize_persona_id(item.get("id") or item.get("display_name") or "")
            if persona_id in linked_ids and persona_id not in applied_persona_ids:
                applied_personas.append(dict(item))
                applied_persona_ids.add(persona_id)
        for persona_id in linked_ids:
            if persona_id in applied_persona_ids:
                continue
            persona = self.persona_by_id(persona_id)
            if persona is not None:
                applied_personas.append(persona.to_dict())
                applied_persona_ids.add(persona_id)
        payload["personas"] = applied_personas
        payload["active_persona_id"] = self.session.active_persona_id
        payload["current_speaker_id"] = self.session.current_speaker_id
        payload["session"] = self.session.to_dict()
        if narrator_id:
            payload["narrator_persona_id"] = narrator_id
            payload["narrator_persona_mode"] = "explicit"
        payload["persona_overrides"] = story_overrides
        story_id = self.storage.save_story(payload)
        payload["id"] = story_id
        self._master_story_draft = payload
        self.settings["last_master_story_id"] = story_id
        self.settings["last_master_story_title"] = payload.get("title")
        self.settings["master_story_linked_persona_ids"] = linked_ids
        self.settings["master_story_created_persona_ids"] = created_ids
        self.settings["master_story_persona_overrides"] = story_overrides
        self.settings["master_story_ready_to_start"] = True
        self.settings["active_scenario_extension"] = copy.deepcopy(payload.get("scenario_extension"))
        self.settings["active_scenario_story_id"] = story_id
        self.storage.save_settings(self.settings)
        self.save_state()
        if persist_memory_snapshot:
            self._save_story_memory_snapshot(story_id)
        self.settings["master_story_draft"] = json.dumps(
            payload,
            indent=2,
            ensure_ascii=True,
        )
        self.settings["native_selected_story_id"] = story_id
        self._populate_master_stories()
        avatar_result = self._queue_story_avatar_generation(
            created_ids,
            payload,
            avatar_enabled=auto_avatars,
            style_sheet_enabled=avatar_style_sheets,
        )
        style_sheet_result = ""
        self.refresh_ui()
        story_character_ids = [persona_id for persona_id in linked_ids if persona_id != narrator_id]
        message = (
            f"Applied and saved story '{payload.get('title')}' as {story_id}. "
            f"Linked {len(story_character_ids)} story character(s)"
            f"{' plus narrator' if narrator_id else ''}, created {created}, updated {updated}. "
            "The story is paused and ready; press Start Play to begin."
        )
        if list(payload.get("personas") or []) and not story_character_ids:
            message += (
                " No non-narrator characters were linked. Check Auto-create missing personas, Maximum created characters, "
                "and each character action in Apply Story."
            )
        if not clear_memory:
            message += " Clean-start story memory was off, so the previous turn index and long-memory context were intentionally preserved."
        if voice_assigned:
            message += f" Assigned {voice_assigned} voice sample(s)."
        if activation_result.get("voices_enabled"):
            message += f" Enabled {activation_result.get('voices_enabled')} existing story voice(s)."
        if activation_result.get("enabled") or activation_result.get("disabled"):
            message += (
                f" Story persona filter enabled {activation_result.get('enabled', 0)}"
                f" and disabled {activation_result.get('disabled', 0)} non-story persona(s)."
            )
        if avatar_result:
            message += " " + avatar_result
        if style_sheet_result:
            message += " " + style_sheet_result
        limit_skipped = [item for item in skipped if "(creation limit)" in item]
        other_skipped = [item for item in skipped if "(creation limit)" not in item]
        if limit_skipped:
            message += (
                f" Creation limit {max_created} skipped {len(limit_skipped)} draft persona(s). "
                "Enable Allow exceeding max created characters to create more."
            )
        if other_skipped:
            message += f" Skipped personas: {', '.join(other_skipped[:5])}."
        if skipped:
            self._record_story_event(f"persona skipped: {', '.join(skipped[:8])}", severity="warning", kind="persona", persist=True)
        self._set_master_story_status(message)
        logger = getattr(self.context, "logger", None)
        if logger is not None:
            logger.info("[MPRC] Applied Master Story id=%s linked=%s created=%s updated=%s", payload.get("id"), len(linked_ids), created, updated)
        return {
            "linked": linked_ids,
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "story_id": story_id,
            "saved": True,
            "story_characters": story_character_ids,
        }

    def _find_persona_for_story(self, persona_payload: dict[str, Any], *, personas: list[PersonaConfig] | None = None) -> PersonaConfig | None:
        wanted_id = normalize_persona_id(persona_payload.get("id") or "")
        wanted_name = str(persona_payload.get("display_name") or "").strip().lower()
        roster = self.personas if personas is None else personas
        for persona in roster:
            if wanted_id and persona.id == wanted_id:
                return persona
        if wanted_name:
            for persona in roster:
                if persona.display_name.strip().lower() == wanted_name:
                    return persona
        return None

    def _apply_story_voice_sample(self, persona: PersonaConfig | None, sample_path: str) -> bool:
        if persona is None:
            return False
        sample = str(sample_path or "").strip()
        if not sample:
            return False
        persona.voice.enabled = True
        persona.voice.sample_path = sample
        if persona.voice.backend not in VOICE_BACKENDS:
            persona.voice.backend = "inherit"
        return True

    def _sync_story_persona_activation(self, linked_ids: list[str], *, narrator_id: str = "") -> dict[str, int]:
        known = {persona.id for persona in self.personas}
        active_ids = [
            persona_id
            for persona_id in list(dict.fromkeys(normalize_persona_id(item) for item in list(linked_ids or []) if str(item or "").strip()))
            if persona_id in known
        ]
        narrator = normalize_persona_id(narrator_id or self.selected_narrator_persona_id())
        if narrator and narrator in known and narrator not in active_ids:
            active_ids.append(narrator)
        if not active_ids:
            return {"enabled": 0, "disabled": 0, "voices_enabled": 0}
        active_set = set(active_ids)
        enabled_count = 0
        disabled_count = 0
        voices_enabled = 0
        for persona in self.personas:
            desired_enabled = persona.id in active_set
            if bool(getattr(persona, "enabled", True)) != desired_enabled:
                persona.enabled = desired_enabled
                if desired_enabled:
                    enabled_count += 1
                else:
                    disabled_count += 1
            voice = getattr(persona, "voice", None)
            if persona.id in active_set and voice is not None:
                sample = str(getattr(voice, "sample_path", "") or "").strip()
                if sample and not bool(getattr(voice, "enabled", False)):
                    voice.enabled = True
                    voices_enabled += 1
                if sample and str(getattr(voice, "backend", "") or "").strip() not in VOICE_BACKENDS:
                    voice.backend = "inherit"
        if self.session.active_persona_id not in active_set:
            self.session.active_persona_id = active_ids[0]
        if self.session.current_speaker_id not in active_set:
            self.session.current_speaker_id = self.session.active_persona_id
        if self._voice_follows_active():
            self.settings["voice_edit_persona_id"] = self.session.active_persona_id
        self.settings["current_character_view_mode"] = "active_story"
        return {"enabled": enabled_count, "disabled": disabled_count, "voices_enabled": voices_enabled}

    def _merge_story_persona(self, target: PersonaConfig, persona_payload: dict[str, Any]) -> None:
        text_fields = (
            "display_name",
            "role",
            "description",
            "character_image_path",
            "system_prompt",
            "ar_description",
            "ar_system_prompt",
            "speaking_style",
            "allowed_tone",
            "response_length",
            "temperature_hint",
            "memory_scope",
            "behavior_mode",
        )
        for field in text_fields:
            if field not in persona_payload:
                continue
            value = str(persona_payload.get(field) or "").strip()
            if value:
                setattr(target, field, value)
        if "ar_profile_enabled" in persona_payload:
            target.ar_profile_enabled = bool(persona_payload.get("ar_profile_enabled"))
        tags = persona_payload.get("tags")
        if isinstance(tags, list):
            cleaned = [str(item).strip().lower() for item in tags if str(item).strip()]
            if cleaned:
                target.tags = cleaned[:12]
        visual = persona_payload.get("visual")
        if isinstance(visual, dict):
            if any(str(visual.get(field) or "").strip() for field in ("character_description", "clothing_props", "environment_style")):
                target.visual.enabled = bool(visual.get("enabled", True))
                if not target.visual.mode or target.visual.mode == "off":
                    target.visual.mode = "manual"
            for field in ("character_description", "clothing_props", "environment_style", "negative_prompt", "style_preset"):
                value = str(visual.get(field) or "").strip()
                if value:
                    setattr(target.visual, field, value)

    def _fill_story_visual_profile(self, persona: PersonaConfig, persona_payload: dict[str, Any]) -> None:
        visual = persona_payload.get("visual")
        if isinstance(visual, dict) and any(str(visual.get(field) or "").strip() for field in ("character_description", "clothing_props", "environment_style")):
            persona.visual.enabled = bool(visual.get("enabled", True))
            if persona.visual.mode == "off":
                persona.visual.mode = "manual"
            return
        appearance = str(
            persona_payload.get("visual_description")
            or persona_payload.get("appearance")
            or persona_payload.get("avatar_description")
            or ""
        ).strip()
        if appearance:
            persona.visual.enabled = True
            persona.visual.mode = "manual"
            persona.visual.character_description = appearance

    def _queue_story_avatar_generation(
        self,
        created_ids: list[str],
        payload: dict[str, Any],
        *,
        avatar_enabled: bool,
        style_sheet_enabled: bool,
    ) -> str:
        persona_ids = [str(item or "").strip() for item in list(created_ids or []) if str(item or "").strip()]
        if not persona_ids or not (bool(avatar_enabled) or bool(style_sheet_enabled)):
            return ""
        service = self.visual_reply_service
        if service is None or not hasattr(service, "request_generation"):
            self._record_visual_debug(
                source="master_story_avatar",
                reason="story_avatar",
                accepted=False,
                message="Avatar generation skipped because the Visual Reply service is unavailable.",
            )
            return "Avatar generation skipped: Visual Reply service is unavailable."
        payload_snapshot = copy.deepcopy(payload)

        def worker(commit_guard):
            messages: list[str] = []
            accepted = False
            try:
                if avatar_enabled:
                    avatar_message = self._generate_story_avatar_images(
                        persona_ids,
                        payload_snapshot,
                        enabled=True,
                        commit_guard=commit_guard,
                    )
                    if avatar_message:
                        messages.append(avatar_message)
                        accepted = accepted or "failed" not in avatar_message.lower()
                if style_sheet_enabled:
                    sheet_message = self._generate_story_avatar_style_sheets(
                        persona_ids,
                        payload_snapshot,
                        enabled=True,
                        commit_guard=commit_guard,
                    )
                    if sheet_message:
                        messages.append(sheet_message)
                        accepted = accepted or "failed" not in sheet_message.lower()
            except Exception as exc:
                messages.append(f"Avatar generation failed: {exc}")
                accepted = False
            self._emit_manual_visual_finished(
                "story_avatar_batch",
                "",
                {
                    "accepted": accepted,
                    "message": " ".join(message for message in messages if message).strip() or "No avatar requests were needed.",
                },
                commit_guard=commit_guard,
            )

        if self._queue_visual_worker("mprc_story_avatar_batch", worker):
            queued = []
            if avatar_enabled:
                queued.append("avatar image")
            if style_sheet_enabled:
                queued.append("avatar style sheet")
            return f"Queued {' and '.join(queued)} generation in background."
        return "Avatar generation could not start a background worker."

    def _generate_story_avatar_images(
        self,
        created_ids: list[str],
        payload: dict[str, Any],
        *,
        enabled: bool | None = None,
        commit_guard=None,
    ) -> str:
        if enabled is None:
            enabled = self._control_checked("master_story_auto_avatars", True)
        if not created_ids or not bool(enabled):
            return ""
        service = self.visual_reply_service
        if service is None or not hasattr(service, "request_generation"):
            self._record_visual_debug(
                source="master_story_avatar",
                reason="story_avatar",
                accepted=False,
                message="Avatar generation skipped because the Visual Reply service is unavailable.",
                commit_guard=commit_guard,
            )
            return "Avatar generation skipped: Visual Reply service is unavailable."
        by_id = {persona.id: persona for persona in self.personas}
        generated = 0
        accepted = 0
        failed = 0
        for persona_id in created_ids[:6]:
            if not self._visual_commit_allowed(commit_guard):
                return ""
            persona = by_id.get(persona_id)
            if persona is None or str(persona.character_image_path or "").strip():
                continue
            prompt = self._story_avatar_prompt(persona, payload)
            if not prompt:
                continue
            self._record_visual_debug(
                source="master_story_avatar",
                reason="story_avatar",
                persona=persona,
                accepted=None,
                message="Master Story avatar request sent to Visual Reply.",
                prompt=prompt,
                commit_guard=commit_guard,
            )
            try:
                committed, result = self._visual_commit(
                    commit_guard,
                    lambda: service.request_generation(
                        prompt=prompt,
                        caption=f"MPRC avatar: {persona.display_name}",
                        provider=str(persona.visual.provider or "inherit"),
                        model=str(persona.visual.model or ""),
                        size="1024x1024",
                        source="nc.multi_persona_roleplay.master_story_avatar",
                        metadata={
                            "persona_id": persona.id,
                            "story_id": str(payload.get("id") or ""),
                            "purpose": "story_avatar",
                        },
                        auto_show=False,
                    ),
                )
            except Exception as exc:
                if not self._visual_commit_allowed(commit_guard):
                    return ""
                failed += 1
                logger = getattr(self.context, "logger", None)
                if logger is not None:
                    logger.warning("[MPRC] Master Story avatar generation failed for %s: %s", persona.id, exc)
                self._record_visual_debug(
                    source="master_story_avatar",
                    reason="story_avatar",
                    persona=persona,
                    accepted=False,
                    message=f"Master Story avatar generation failed: {exc}",
                    prompt=prompt,
                    commit_guard=commit_guard,
                )
                continue
            if not committed:
                return ""
            if not result:
                failed += 1
                self._record_visual_debug(
                    source="master_story_avatar",
                    reason="story_avatar",
                    persona=persona,
                    accepted=False,
                    message="Visual Reply did not accept the Master Story avatar request.",
                    prompt=prompt,
                    commit_guard=commit_guard,
                )
                continue
            accepted += 1
            image_path = str(result.get("image_path") or "").strip() if isinstance(result, dict) else ""
            self._record_visual_debug(
                source="master_story_avatar",
                reason="story_avatar",
                persona=persona,
                accepted=True,
                message=f"Master Story avatar accepted{': ' + image_path if image_path else '; no image path returned yet'}.",
                prompt=prompt,
                commit_guard=commit_guard,
            )
            if image_path and Path(image_path).exists():
                committed, _ = self._visual_commit(
                    commit_guard,
                    lambda: setattr(persona, "character_image_path", image_path),
                )
                if not committed:
                    return ""
                generated += 1
        if generated:
            committed, _ = self._visual_commit(commit_guard, self.save_state)
            if not committed:
                return ""
            return f"Created {generated} avatar image(s) for new persona(s)."
        if accepted:
            return "Avatar image requests were accepted; choose generated images from Visual Reply if no file path was returned."
        if failed:
            return f"Avatar generation failed for {failed} new persona(s)."
        return ""

    def _generate_story_avatar_style_sheets(
        self,
        created_ids: list[str],
        payload: dict[str, Any],
        *,
        enabled: bool | None = None,
        commit_guard=None,
    ) -> str:
        if enabled is None:
            enabled = self._control_checked("master_story_avatar_style_sheets", False)
        if not created_ids or not bool(enabled):
            return ""
        service = self.visual_reply_service
        if service is None or not hasattr(service, "request_generation"):
            return "Avatar style sheets skipped: Visual Reply service is unavailable."
        by_id = {persona.id: persona for persona in self.personas}
        accepted = 0
        generated = 0
        failed = 0
        skipped_no_image = 0
        saved: dict[str, Any] = dict(self.settings.get("persona_avatar_style_sheets") or {}) if isinstance(self.settings.get("persona_avatar_style_sheets"), dict) else {}
        for persona_id in created_ids[:6]:
            if not self._visual_commit_allowed(commit_guard):
                return ""
            persona = by_id.get(persona_id)
            if persona is None:
                continue
            image_path = str(persona.character_image_path or "").strip()
            if not image_path or not Path(image_path).exists():
                skipped_no_image += 1
                continue
            prompt = self._story_avatar_style_sheet_prompt(persona, payload, image_path=image_path)
            if not prompt:
                continue
            try:
                committed, result = self._visual_commit(
                    commit_guard,
                    lambda: service.request_generation(
                        prompt=prompt,
                        caption=f"MPRC avatar style sheet: {persona.display_name}",
                        provider=str(persona.visual.provider or "inherit"),
                        model=str(persona.visual.model or ""),
                        size="inherit",
                        source="nc.multi_persona_roleplay.avatar_style_sheet",
                        metadata={
                            "persona_id": persona.id,
                            "story_id": str(payload.get("id") or ""),
                            "purpose": "character_reference_sheet",
                            "reference_image_path": image_path,
                            "requires_image_to_image": True,
                        },
                        auto_show=False,
                    ),
                )
            except Exception as exc:
                if not self._visual_commit_allowed(commit_guard):
                    return ""
                failed += 1
                logger = getattr(self.context, "logger", None)
                if logger is not None:
                    logger.warning("[MPRC] Avatar style sheet generation failed for %s: %s", persona.id, exc)
                continue
            if not committed:
                return ""
            if not result:
                failed += 1
                continue
            accepted += 1
            result_path = str(result.get("image_path") or "").strip() if isinstance(result, dict) else ""
            saved[persona.id] = {
                "story_id": str(payload.get("id") or ""),
                "story_title": str(payload.get("title") or ""),
                "reference_image_path": image_path,
                "style_sheet_path": result_path,
                "prompt": prompt,
                "updated_at": QtCore.QDateTime.currentDateTimeUtc().toString(QtCore.Qt.ISODate),
            }
            if result_path and Path(result_path).exists():
                generated += 1
        if accepted or generated:
            committed, _ = self._visual_commit(
                commit_guard,
                lambda: (
                    self.settings.__setitem__("persona_avatar_style_sheets", saved),
                    self.storage.save_settings(self.settings),
                ),
            )
            if not committed:
                return ""
        if generated:
            return f"Created {generated} avatar style sheet(s) for new persona(s)."
        if accepted:
            return "Avatar style sheet requests were accepted; image-to-image quality depends on the Visual Reply provider/workflow."
        if skipped_no_image:
            return f"Avatar style sheets skipped for {skipped_no_image} new persona(s) without a ready avatar image."
        if failed:
            return f"Avatar style sheet generation failed for {failed} new persona(s)."
        return ""

    def _story_avatar_style_sheet_prompt(self, persona: PersonaConfig, payload: dict[str, Any], *, image_path: str = "") -> str:
        story_title = str(payload.get("title") or self.session.scene_title or "story").strip()
        visual_direction = str(
            self.settings.get("master_story_visual_direction") or ""
        ).strip()
        if not visual_direction:
            visual_direction = str(payload.get("avatar_visual_direction") or "").strip()
        description = ". ".join(
            str(item or "").strip(" .")
            for item in (
                persona.display_name,
                persona.role,
                persona.description,
                persona.ar_description,
                persona.visual.character_description,
                persona.visual.clothing_props,
                persona.visual.environment_style,
                visual_direction,
                f"story: {story_title}",
            )
            if str(item or "").strip()
        )
        reference_line = f"Main image reference path for image-to-image capable runtimes: {image_path}" if image_path else "Main image reference: use the current avatar image when the runtime supports image-to-image."
        prompt = f"""
Create a highly detailed, professional character reference sheet for an original avatar character.

The reference sheet must include at least 8 different facial expressions/emotions displayed clearly, plus multiple body angles.

Facial expressions, minimum 8:
- Neutral / calm
- Happy / smiling
- Grinning / playful
- Angry / furious
- Sad / tearful
- Surprised / shocked
- Smug / confident
- Disgusted / annoyed
- Bonus expressions if useful: flustered, seductive, determined, focused, wary, or embarrassed

Body and pose views:
- Front view, full body, standing naturally
- Side profile, left and right
- 3/4 angle, front and back
- Back view
- Dynamic/action pose

Visual requirements:
- Perfect consistency in character design across all angles and expressions
- Accurate hairstyle, hair color, eye color and shape, skin tone, facial features, markings, tattoos, scars, piercings, jewelry, clothing details, accessories, and signature items
- Clean close-up insets for important design elements such as eyes, unique accessories, clothing patterns, weapons, symbols, or props
- Clear color palette with excellent lighting

Style:
- Clean, modern anime/game/VTuber-style character reference sheet
- White or light neutral background
- Sharp lines, highly detailed, professional quality

Input provided:
- {reference_line}
- Short character description: {description}

Generate a comprehensive character card that fully showcases the avatar from every important angle while prominently featuring at least 8 distinct facial expressions and all unique design features.
""".strip()
        return prompt[:3600].rstrip(" \t\r\n,;:.-")

    def _story_avatar_prompt(self, persona: PersonaConfig, payload: dict[str, Any]) -> str:
        override = str(getattr(persona, "_mprc_avatar_prompt_override", "") or "").strip()
        if not override:
            override = self._story_avatar_prompt_override_for_persona(persona, payload)
        if override:
            return override[:1200].rstrip(" \t\r\n,;:.-")
        visual_direction = str(
            self.settings.get("master_story_visual_direction") or ""
        ).strip()
        if not visual_direction:
            visual_direction = str(payload.get("avatar_visual_direction") or "").strip()
        story_title = str(payload.get("title") or self.session.scene_title or "story").strip()
        story_summary = str(payload.get("summary") or self.session.scene_summary or "").strip()
        genre_hint = "fantasy character portrait" if self._looks_like_fantasy_story(payload) else "cinematic character portrait"
        pieces = [
            genre_hint,
            f"single avatar portrait of {persona.display_name}",
            persona.role,
            persona.visual.character_description or persona.description or persona.ar_description,
            persona.visual.clothing_props,
            persona.visual.environment_style,
            visual_direction,
            f"story: {story_title}",
            story_summary[:320],
            "clear face, expressive eyes, strong readable silhouette, cohesive costume, portrait framing",
            "no text, no watermark, no logo, no extra characters, no distorted hands or face",
        ]
        prompt = ". ".join(str(item or "").strip(" .") for item in pieces if str(item or "").strip())
        return prompt[:1200].rstrip(" \t\r\n,;:.-")

    def _story_avatar_prompt_override_for_persona(self, persona: PersonaConfig | None, payload: dict[str, Any]) -> str:
        if persona is None or not isinstance(payload, dict):
            return ""
        persona_id = normalize_persona_id(getattr(persona, "id", ""))
        display_name = str(getattr(persona, "display_name", "") or "").strip().lower()
        for item in list(payload.get("personas") or []):
            if not isinstance(item, dict):
                continue
            item_id = normalize_persona_id(item.get("id") or "")
            item_name = str(item.get("display_name") or "").strip().lower()
            if (persona_id and item_id == persona_id) or (display_name and item_name == display_name):
                return str(item.get("avatar_prompt_override") or "").strip()
        return ""

    @staticmethod
    def _looks_like_fantasy_story(payload: dict[str, Any]) -> bool:
        text = json.dumps(payload or {}, ensure_ascii=True).lower()
        markers = (
            "fantasy",
            "magic",
            "wizard",
            "sorcer",
            "dragon",
            "elf",
            "orc",
            "dwarf",
            "kingdom",
            "castle",
            "myth",
            "enchanted",
            "rune",
        )
        return any(marker in text for marker in markers)

    def _story_persona_id(self, value: Any, linked_ids: list[str], fallback: str = "", id_map: dict[str, str] | None = None) -> str:
        wanted = normalize_persona_id(value or "")
        mapped = dict(id_map or {}).get(wanted)
        if mapped:
            return mapped
        known_ids = {persona.id for persona in self.personas}
        if wanted in known_ids:
            return wanted
        wanted_name = str(value or "").strip().lower()
        for persona in self.personas:
            if wanted_name and persona.display_name.strip().lower() == wanted_name:
                return persona.id
        return str(fallback or (linked_ids[0] if linked_ids else self.session.active_persona_id) or "mentor").strip()

    def _story_persona_override_from_draft(
        self,
        target: PersonaConfig,
        persona_payload: dict[str, Any],
        payload: dict[str, Any],
        *,
        alternate_text: str = "",
    ) -> dict[str, Any]:
        draft_id = normalize_persona_id(persona_payload.get("id") or persona_payload.get("display_name") or target.id)
        override: dict[str, Any] = {
            "base_persona_id": target.id,
            "draft_id": draft_id,
            "story_id": self.storage.story_id(payload.get("id") or payload.get("title") or ""),
            "story_title": str(payload.get("title") or "").strip(),
            "mode": "story_profile",
        }
        for field in (
            "display_name",
            "role",
            "description",
            "system_prompt",
            "ar_description",
            "ar_system_prompt",
            "speaking_style",
            "allowed_tone",
            "response_length",
            "temperature_hint",
            "memory_scope",
            "behavior_mode",
            "character_image_path",
        ):
            value = str(persona_payload.get(field) or "").strip()
            if value:
                override[field] = value
        tags = persona_payload.get("tags")
        if isinstance(tags, list):
            cleaned = [str(item).strip().lower() for item in tags if str(item).strip()]
            if cleaned:
                override["tags"] = cleaned[:12]
        visual = persona_payload.get("visual")
        if isinstance(visual, dict):
            override["visual"] = {
                key: value
                for key, value in dict(visual).items()
                if isinstance(value, bool) or str(value or "").strip()
            }
        notes = str(alternate_text or "").strip()
        if notes:
            override["story_profile_notes"] = notes[:2400]
        return override

    def _master_story_persona_overrides(self) -> dict[str, dict[str, Any]]:
        raw = self.settings.get("master_story_persona_overrides")
        if not isinstance(raw, dict):
            draft_raw = self._master_story_draft.get("persona_overrides") if isinstance(self._master_story_draft, dict) else {}
            raw = draft_raw if isinstance(draft_raw, dict) else {}
        overrides: dict[str, dict[str, Any]] = {}
        for key, value in raw.items():
            persona_id = normalize_persona_id(key)
            if persona_id and isinstance(value, dict):
                overrides[persona_id] = dict(value)
        return overrides

    def story_prompt_personas(self) -> list[PersonaConfig]:
        return [self.story_prompt_persona(persona.id) or persona for persona in self.personas]

    def story_prompt_persona(self, persona_id: str) -> PersonaConfig | None:
        base = self.persona_by_id(persona_id)
        if base is None:
            return None
        override = self._master_story_persona_overrides().get(base.id)
        if not isinstance(override, dict) or not override:
            return base
        persona = copy.deepcopy(base)
        for field in (
            "display_name",
            "role",
            "description",
            "system_prompt",
            "ar_description",
            "ar_system_prompt",
            "speaking_style",
            "allowed_tone",
            "response_length",
            "temperature_hint",
            "memory_scope",
            "behavior_mode",
            "character_image_path",
        ):
            value = str(override.get(field) or "").strip()
            if value:
                setattr(persona, field, value)
        tags = override.get("tags")
        if isinstance(tags, list):
            cleaned = [str(item).strip().lower() for item in tags if str(item).strip()]
            if cleaned:
                persona.tags = cleaned[:12]
        visual = override.get("visual")
        if isinstance(visual, dict):
            if any(str(visual.get(field) or "").strip() for field in ("character_description", "clothing_props", "environment_style")):
                persona.visual.enabled = bool(visual.get("enabled", True))
                if persona.visual.mode == "off":
                    persona.visual.mode = "manual"
            for field in ("character_description", "clothing_props", "environment_style", "negative_prompt", "style_preset"):
                value = str(visual.get(field) or "").strip()
                if value:
                    setattr(persona.visual, field, value)
        notes = str(override.get("story_profile_notes") or "").strip()
        if notes:
            if notes not in persona.ar_description:
                persona.ar_description = ". ".join(part for part in (persona.ar_description, f"Story-only profile: {notes}") if part).strip()
            if notes not in persona.system_prompt:
                persona.system_prompt = "\n".join(part for part in (persona.system_prompt, f"Story-only persona notes for this Master Story:\n{notes}") if part).strip()
        return persona

    def resolve_story_persona_alias(self, value: Any) -> PersonaConfig | None:
        wanted = str(value or "").strip()
        if not wanted:
            return None
        wanted_id = normalize_persona_id(wanted)
        wanted_lower = wanted.lower()
        for persona_id, override in self._master_story_persona_overrides().items():
            candidates = [
                override.get("draft_id"),
                override.get("display_name"),
            ]
            for candidate in candidates:
                candidate_text = str(candidate or "").strip()
                if not candidate_text:
                    continue
                if normalize_persona_id(candidate_text) == wanted_id or candidate_text.lower() == wanted_lower:
                    return self.persona_by_id(persona_id)
        return None

    def _story_character_summaries(self, linked_ids: list[str]) -> dict[str, str]:
        by_id = {persona.id: persona for persona in self.story_prompt_personas()}
        summaries: dict[str, str] = {}
        for persona_id in linked_ids[:12]:
            persona = by_id.get(persona_id)
            if persona is None:
                continue
            summary = ". ".join(part for part in (persona.role, persona.description or persona.ar_description) if part)
            summaries[persona_id] = summary[:300]
        return summaries

    def _current_master_story_snapshot(self) -> dict[str, Any]:
        title = self.session.scene_title or "Current Roleplay Story"
        linked_ids = self._current_linked_persona_ids()
        narrator_id = self.selected_narrator_persona_id()
        if narrator_id and narrator_id not in linked_ids:
            linked_ids.append(narrator_id)
        story_personas = []
        for persona_id in linked_ids:
            persona = self.story_prompt_persona(persona_id) or self.persona_by_id(persona_id)
            if persona is not None:
                story_personas.append(persona.to_dict())
        return self._normalize_master_story_payload({
            "id": self.storage.story_id(title),
            "title": title,
            "summary": self.session.scene_summary,
            "mode": self.session.mode,
            "active_persona_id": self.session.active_persona_id,
            "current_speaker_id": self.session.current_speaker_id,
            "narrator_persona_id": self.selected_narrator_persona_id(),
            "narrator_persona_mode": self._narrator_selection_mode(),
            "session": self.session.to_dict(),
            "personas": story_personas,
            "persona_overrides": dict(self.settings.get("master_story_persona_overrides") or {}),
            **({"scenario_extension": copy.deepcopy(self.settings["active_scenario_extension"])}
               if isinstance(self.settings.get("active_scenario_extension"), dict) else {}),
        })

    def _compact_legacy_registry_story_snapshot(self, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
        candidate = dict(payload or {})
        personas = [dict(item) for item in list(candidate.get("personas") or []) if isinstance(item, dict)]
        generation = candidate.get("generation") if isinstance(candidate.get("generation"), dict) else {}
        if str(generation.get("source") or "").strip() != "master_story_creator":
            return candidate, 0

        try:
            requested = int(generation.get("requested_story_native_personas", generation.get("requested_persona_count", 0)) or 0)
        except (TypeError, ValueError):
            requested = 0
        try:
            maximum = int(generation.get("maximum_new_personas_to_create", generation.get("max_created_characters", 0)) or 0)
        except (TypeError, ValueError):
            maximum = 0
        expected_limit = max(requested, maximum, 1) + 2
        enabled = [item for item in personas if item.get("enabled") is True]
        disabled = [item for item in personas if item.get("enabled") is False]
        if not enabled or not disabled or len(personas) <= expected_limit or len(enabled) > expected_limit:
            return candidate, 0

        candidate["personas"] = enabled
        allowed_ids = {normalize_persona_id(item.get("id") or item.get("display_name") or "") for item in enabled}
        overrides = candidate.get("persona_overrides")
        if isinstance(overrides, dict):
            candidate["persona_overrides"] = {
                key: value for key, value in overrides.items() if normalize_persona_id(key) in allowed_ids
            }
        return candidate, len(personas) - len(enabled)

    def _restrict_restored_story_memory_to_cast(self, linked_persona_ids) -> bool:
        linked_ids: list[str] = []
        for item in list(linked_persona_ids or []):
            persona_id = normalize_persona_id(item)
            if persona_id and persona_id not in linked_ids and self.persona_by_id(persona_id) is not None:
                linked_ids.append(persona_id)
        if not linked_ids:
            return False

        changed = list(self.settings.get("master_story_linked_persona_ids") or []) != linked_ids
        self.settings["master_story_linked_persona_ids"] = linked_ids
        created_ids = [
            normalize_persona_id(item)
            for item in list(self.settings.get("master_story_created_persona_ids") or [])
            if normalize_persona_id(item) in linked_ids
        ]
        if created_ids != list(self.settings.get("master_story_created_persona_ids") or []):
            changed = True
        self.settings["master_story_created_persona_ids"] = created_ids

        overrides = self.settings.get("master_story_persona_overrides")
        if isinstance(overrides, dict):
            filtered_overrides = {
                key: value for key, value in overrides.items() if normalize_persona_id(key) in linked_ids
            }
            if filtered_overrides != overrides:
                changed = True
            self.settings["master_story_persona_overrides"] = filtered_overrides

        fallback = linked_ids[0]
        if self.session.active_persona_id not in linked_ids:
            self.session.active_persona_id = fallback
            changed = True
        if self.session.current_speaker_id not in linked_ids:
            self.session.current_speaker_id = self.session.active_persona_id
            changed = True
        active_characters = [
            normalize_persona_id(item)
            for item in list(self.session.ar_state.active_characters or [])
            if normalize_persona_id(item) in linked_ids
        ]
        if not active_characters:
            active_characters = [self.session.active_persona_id]
        if active_characters != list(self.session.ar_state.active_characters or []):
            self.session.ar_state.active_characters = active_characters
            changed = True
        filtered_summaries = {
            persona_id: summary
            for persona_id, summary in dict(self.session.character_state_summaries or {}).items()
            if normalize_persona_id(persona_id) in linked_ids
        }
        if filtered_summaries != dict(self.session.character_state_summaries or {}):
            self.session.character_state_summaries = filtered_summaries
            changed = True

        narrator_id = normalize_persona_id(self.settings.get("narrator_persona_id") or "")
        if narrator_id and narrator_id not in linked_ids:
            replacement = next(
                (
                    persona_id for persona_id in linked_ids
                    if self._persona_looks_like_narrator(self.persona_by_id(persona_id))
                ),
                "",
            )
            self.settings["narrator_persona_id"] = replacement
            self.settings["narrator_persona_mode"] = "explicit" if replacement else "auto"
            changed = True
        return changed

    def _save_master_story(self):
        payload = self._parse_master_story_draft() or self._current_master_story_snapshot()
        payload = self._sanitize_master_story_overrides_for_options(payload)
        if (
            self._control_checked("master_story_use_existing_personas", True)
            and not isinstance(payload.get("persona_overrides"), dict)
            and isinstance(self.settings.get("master_story_persona_overrides"), dict)
        ):
            candidate = dict(payload)
            candidate["persona_overrides"] = dict(self.settings.get("master_story_persona_overrides") or {})
            payload = self._sanitize_master_story_overrides_for_options(candidate)
        payload["narrator_persona_id"] = self.selected_narrator_persona_id()
        payload["narrator_persona_mode"] = self._narrator_selection_mode()
        session_payload = dict(payload.get("session") or {}) if isinstance(payload.get("session"), dict) else {}
        session_payload["narrator_persona_id"] = payload["narrator_persona_id"]
        session_payload["narrator_persona_mode"] = payload["narrator_persona_mode"]
        payload["session"] = session_payload
        payload["updated_at"] = QtCore.QDateTime.currentDateTimeUtc().toString(QtCore.Qt.ISODate)
        payload = self._ensure_master_story_image(payload)
        story_id = self.storage.save_story(payload)
        self._master_story_draft = payload
        self._set_master_story_sfw_from_payload(payload)
        self._controls["master_story_draft"].setPlainText(json.dumps(payload, indent=2, ensure_ascii=True))
        if self.storage.story_id(self.settings.get("last_master_story_id") or "") == story_id:
            self._save_story_memory_snapshot(story_id)
        self._populate_master_stories()
        combo = self._controls.get("master_story_list")
        if combo is not None:
            index = combo.findData(story_id)
            if index >= 0:
                combo.setCurrentIndex(index)
        self._set_master_story_status(f"Saved story '{payload.get('title')}' as {story_id}.")

    def _load_selected_master_story(self):
        story_id = self._selected_master_story_id()
        if not story_id:
            return
        current_story_id = self.storage.story_id(self.settings.get("last_master_story_id") or "")
        if current_story_id and current_story_id != story_id:
            self.save_active_story_memory_snapshot()
        payload = self.storage.load_story(story_id)
        if not payload:
            self._warn("Load Story", "The selected story could not be loaded.")
            return
        payload, removed_registry_personas = self._compact_legacy_registry_story_snapshot(payload)
        if removed_registry_personas:
            self._record_story_event(
                f"story migration/fallback: ignored {removed_registry_personas} unrelated disabled personas from a legacy registry snapshot",
                severity="warning",
                kind="schema",
                persist=True,
            )
        for note in list(payload.get("_migration_log") or []):
            self._record_story_event(f"story migration/fallback: {note}", severity="warning", kind="schema", persist=True)
        payload = self._normalize_master_story_payload(payload)
        payload = self._ensure_master_story_image(payload, save_story=True)
        self._master_story_draft = payload
        self._set_master_story_creator_context_from_payload(payload)
        self._set_master_story_visual_direction(payload.get("avatar_visual_direction"))
        self._set_master_story_sfw_from_payload(payload)
        self._controls["master_story_draft"].setPlainText(json.dumps(payload, indent=2, ensure_ascii=True))
        apply_result = self._apply_master_story_payload(
            payload,
            apply_plan={"clear_memory": True, "persist_memory_snapshot": False},
        )
        restored = self._restore_story_memory_snapshot(story_id)
        if restored:
            if self._restrict_restored_story_memory_to_cast(apply_result.get("linked") or []):
                self._record_story_event(
                    "story memory migration/fallback: removed persona links that are not part of the loaded story cast",
                    severity="warning",
                    kind="memory",
                    persist=True,
                )
            self.storage.save_settings(self.settings)
            self.save_state()
            self.refresh_ui()
            suffix = f" Ignored {removed_registry_personas} unrelated legacy personas." if removed_registry_personas else ""
            self._set_master_story_status(f"Loaded story '{payload.get('title')}' and restored its saved story memory.{suffix}")
        else:
            suffix = f" Ignored {removed_registry_personas} unrelated legacy personas." if removed_registry_personas else ""
            self._set_master_story_status(
                f"Loaded and applied story '{payload.get('title')}'. No saved story memory was found yet.{suffix}"
            )

    def _delete_selected_master_story(self):
        story_id = self._selected_master_story_id()
        if not story_id:
            return
        from .native_actions import _require_story_deletion_idle
        _require_story_deletion_idle(self, story_id)
        self.storage.delete_story(story_id)
        self._populate_master_stories()
        self._set_master_story_status(f"Deleted story {story_id}.")

    def _commit_audio_settings(self):
        if self._syncing:
            return
        c = self._controls
        if "audio_story_sounds" not in c:
            return
        self.settings["story_sounds_enabled"] = bool(c["audio_story_sounds"].isChecked())
        if "audiofx_volume" in c:
            self.settings["audiofx_volume"] = int(c["audiofx_volume"].value())
        self.settings["audio_prompt_type"] = c["audio_type"].currentText().strip() or "Auto"
        self.settings["audio_prompt_description"] = c["audio_sound_description"].toPlainText().strip()
        self.settings["audio_prompt_output"] = c["audio_prompt_output"].toPlainText().strip()
        self.storage.save_settings(self.settings)

    def _on_story_sounds_changed(self, checked: bool):
        if self._syncing:
            return
        self._commit_audio_settings()
        logger = getattr(self.context, "logger", None)
        if logger is not None:
            logger.info("[AR_MODE] Story Sounds enabled=%s", bool(checked))

    def _on_audiofx_volume_changed(self, value: int):
        if self._syncing:
            return
        volume = max(0, min(100, int(value or 0)))
        value_label = self._controls.get("audiofx_volume_value")
        if value_label is not None:
            value_label.setText(f"{volume}%")
        self.settings["audiofx_volume"] = volume
        self.storage.save_settings(self.settings)
        self._apply_audiofx_volume()

    def _on_audiofx_test_mode_changed(self, checked: bool):
        if self._syncing:
            return
        self.settings["audiofx_test_mode"] = bool(checked)
        if checked:
            self.settings["story_sounds_enabled"] = True
            self._create_test_audiofx(show_status=True)
        else:
            self.storage.save_settings(self.settings)
        self.refresh_ui()

    def _test_audiofx_specs(self) -> list[dict[str, str]]:
        return [
            {
                "id": "mprc_test_pub_ambient",
                "type": "Ambience",
                "description": "pub ambient",
                "prompt": "busy fantasy pub ambience, layered low crowd murmur, soft room tone, occasional glass clinks, seamless loop, no vocals",
                "file_name": "pub_ambient_test.wav",
                "profile": "pub",
            },
            {
                "id": "mprc_test_adventure_music",
                "type": "Music",
                "description": "adventure music",
                "prompt": "low fantasy adventure music bed, steady pulse, warm strings, subtle drums, seamless loop, no vocals",
                "file_name": "adventure_music_test.wav",
                "profile": "music",
            },
            {
                "id": "mprc_test_rain_storm",
                "type": "Ambience",
                "description": "rain storm",
                "prompt": "rain storm ambience, steady rainfall, distant thunder rumble, dark cinematic atmosphere, seamless loop, no vocals",
                "file_name": "rain_storm_test.wav",
                "profile": "rain",
            },
            {
                "id": "mprc_test_deep_engine_hum",
                "type": "Ambience",
                "description": "deep engine hum",
                "prompt": "deep submarine engine hum, low mechanical vibration, metal room resonance, seamless loop, no vocals",
                "file_name": "deep_engine_hum_test.wav",
                "profile": "hum",
            },
            {
                "id": "mprc_test_magic_shimmer",
                "type": "FX",
                "description": "magic shimmer",
                "prompt": "soft magic shimmer sound effect, sparkling arcane chimes, gentle fantasy energy, no vocals",
                "file_name": "magic_shimmer_test.wav",
                "profile": "magic",
            },
            {
                "id": "mprc_test_danger_stinger",
                "type": "Stinger",
                "description": "danger stinger",
                "prompt": "short danger stinger, cinematic hit, quick rising tension, no vocals",
                "file_name": "danger_stinger_test.wav",
                "profile": "stinger",
            },
        ]

    def _create_test_audiofx(self, *, show_status: bool = True):
        specs = self._test_audiofx_specs()
        base_dir = self.context.storage.resolve("test_audio")
        base_dir.mkdir(parents=True, exist_ok=True)
        items = [item for item in self._audiofx_items() if not str(item.get("id") or "").startswith("mprc_test_")]
        now = QtCore.QDateTime.currentDateTimeUtc().toString(QtCore.Qt.ISODate)
        for spec in specs:
            path = base_dir / spec["file_name"]
            self._write_test_audio_file(path, spec["profile"])
            items.append({
                "id": spec["id"],
                "type": spec["type"],
                "description": spec["description"],
                "prompt": spec["prompt"],
                "file_path": str(path),
                "created_at": now,
                "updated_at": now,
            })
        self.settings["audiofx_test_mode"] = bool(self.settings.get("audiofx_test_mode", True))
        self.settings["story_sounds_enabled"] = True
        self._save_audiofx_items(items)
        self._populate_audiofx_items()
        _ = show_status
        self._native_audiofx_summary = {
            "status": "Test sounds ready.",
            "examples": [
                "[AMBIENCE: pub ambient]",
                "[MUSIC: adventure music]",
                "[FX: magic shimmer]",
                "[STINGER: danger stinger]",
            ],
        }
        logger = getattr(self.context, "logger", None)
        if logger is not None:
            logger.info("[AR_MODE] Created %s MPRC AudioFX test sounds in %s", len(specs), base_dir)

    def _write_test_audio_file(self, path: Path, profile: str):
        sample_rate = 22050
        duration = 3.0
        total = int(sample_rate * duration)
        profile = str(profile or "pub")
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            frames = bytearray()
            seed = sum(ord(ch) for ch in profile) or 1
            noise = seed & 0x7fffffff
            for index in range(total):
                t = index / sample_rate
                noise = (1103515245 * noise + 12345) & 0x7fffffff
                n = ((noise / 0x7fffffff) * 2.0 - 1.0)
                if profile == "rain":
                    value = 0.16 * n + 0.08 * math.sin(2 * math.pi * 47 * t) + 0.04 * math.sin(2 * math.pi * 82 * t)
                    if int(t * 2) % 5 == 0:
                        value += 0.04 * math.sin(2 * math.pi * 31 * t)
                elif profile == "hum":
                    value = 0.34 * math.sin(2 * math.pi * 55 * t) + 0.15 * math.sin(2 * math.pi * 110 * t) + 0.04 * n
                elif profile == "music":
                    pulse = 0.5 + 0.5 * math.sin(2 * math.pi * 2.0 * t)
                    value = 0.16 * math.sin(2 * math.pi * 196 * t) + 0.12 * math.sin(2 * math.pi * 247 * t)
                    value += 0.10 * math.sin(2 * math.pi * 98 * t) * pulse + 0.03 * n
                elif profile == "magic":
                    value = 0.18 * math.sin(2 * math.pi * (440 + 60 * math.sin(2 * math.pi * 0.45 * t)) * t)
                    value += 0.12 * math.sin(2 * math.pi * 880 * t) * (0.5 + 0.5 * math.sin(2 * math.pi * 1.5 * t))
                    value += 0.03 * n
                elif profile == "stinger":
                    decay = max(0.0, 1.0 - (t / duration))
                    value = decay * (0.45 * math.sin(2 * math.pi * 82 * t) + 0.28 * math.sin(2 * math.pi * 330 * t))
                    value += 0.04 * n * decay
                else:
                    value = 0.12 * math.sin(2 * math.pi * 145 * t) + 0.08 * math.sin(2 * math.pi * 210 * t) + 0.06 * n
                    if (index % int(sample_rate * 0.7)) < 360:
                        value += 0.22 * math.sin(2 * math.pi * 1200 * t)
                sample = max(-0.85, min(0.85, value))
                frames.extend(struct.pack("<h", int(sample * 32767)))
            handle.writeframes(bytes(frames))

    def _play_test_ambience_tag(self):
        if not any(str(item.get("id") or "").startswith("mprc_test_") for item in self._audiofx_items()):
            self._create_test_audiofx(show_status=False)
        self.settings["story_sounds_enabled"] = True
        self.storage.save_settings(self.settings)
        self._trigger_story_audio_cues("pub ambient", warn_unmatched=True)

    def _create_audio_prompt(self, variant: str = ""):
        if self._syncing:
            return
        c = self._controls
        description = c["audio_sound_description"].toPlainText().strip()
        if not description:
            self._warn("Create Prompt for Audio", "Add a Sound Description first.")
            return
        prompt = create_audio_prompt(description, c["audio_type"].currentText(), variant=variant)
        c["audio_prompt_output"].setPlainText(prompt)
        self._commit_audio_settings()

    def _copy_audio_prompt(self) -> str:
        prompt = str(self.settings.get("audio_prompt_output") or "").strip()
        self._native_clipboard_suggestion = prompt
        return prompt
    def _save_audio_prompt(self):
        c = self._controls
        prompt = c["audio_prompt_output"].toPlainText().strip()
        if not prompt:
            self._warn("Save Prompt", "Create or enter an audio prompt before saving.")
            return
        self._commit_audio_settings()
        saved = self.settings.get("saved_audio_prompts")
        if not isinstance(saved, list):
            saved = []
        entry = {
            "created_at": QtCore.QDateTime.currentDateTimeUtc().toString(QtCore.Qt.ISODate),
            "type": c["audio_type"].currentText().strip() or "Auto",
            "description": c["audio_sound_description"].toPlainText().strip(),
            "prompt": prompt,
        }
        saved = [item for item in saved if isinstance(item, dict)]
        saved.append(entry)
        self.settings["saved_audio_prompts"] = saved[-100:]
        self.storage.save_settings(self.settings)
        self._populate_audio_saved_prompts()
        logger = getattr(self.context, "logger", None)
        if logger is not None:
            logger.info("[AR_MODE] Saved audio prompt type=%s", entry["type"])

    def _load_saved_audio_prompt(self):
        index = self._selected_audio_prompt_index()
        prompts = self._saved_audio_prompts()
        if index < 0 or index >= len(prompts):
            return
        item = prompts[index]
        audio_type = str(item.get("type") or "Auto").strip()
        self._controls["audio_sound_description"].setPlainText(str(item.get("description") or ""))
        self._controls["audio_type"].setCurrentText(audio_type if audio_type in AUDIO_TYPES else "Auto")
        self._controls["audio_prompt_output"].setPlainText(str(item.get("prompt") or ""))
        self._commit_audio_settings()

    def _delete_saved_audio_prompt(self):
        index = self._selected_audio_prompt_index()
        prompts = self._saved_audio_prompts()
        if index < 0 or index >= len(prompts):
            return
        del prompts[index]
        self.settings["saved_audio_prompts"] = prompts
        self.storage.save_settings(self.settings)
        self._populate_audio_saved_prompts()

    def _audiofx_payload_from_builder(self) -> dict[str, str]:
        c = self._controls
        description = c["audio_sound_description"].toPlainText().strip()
        audio_type = c["audio_type"].currentText().strip() or "Auto"
        prompt = c["audio_prompt_output"].toPlainText().strip()
        if not description and not prompt:
            saved_index = self._selected_audio_prompt_index()
            saved = self._saved_audio_prompts()
            if 0 <= saved_index < len(saved):
                selected = saved[saved_index]
                description = str(selected.get("description") or "").strip()
                prompt = str(selected.get("prompt") or "").strip()
                audio_type = str(selected.get("type") or audio_type).strip() or audio_type
        if description and not prompt:
            prompt = create_audio_prompt(description, audio_type)
            c["audio_prompt_output"].setPlainText(prompt)
        if prompt and not description:
            description = prompt[:120]
        return {
            "type": audio_type if audio_type in AUDIO_TYPES else "Auto",
            "description": description,
            "prompt": prompt,
        }

    def _create_new_audiofx(self):
        payload = self._audiofx_payload_from_builder()
        if not payload["description"] and not payload["prompt"]:
            self._warn("Create New AudioFX", "Add a Sound Description or select a saved audio prompt first.")
            return
        items = self._audiofx_items()
        now = QtCore.QDateTime.currentDateTimeUtc().toString(QtCore.Qt.ISODate)
        item = {
            "id": self._new_audiofx_id(items),
            "type": payload["type"],
            "description": payload["description"],
            "prompt": payload["prompt"],
            "file_path": "",
            "created_at": now,
            "updated_at": now,
        }
        items.append(item)
        self._save_audiofx_items(items)
        self._populate_audiofx_items()
        self._select_audiofx_index(len(items) - 1)

    def _update_selected_audiofx_from_builder(self) -> bool:
        index = self._selected_audiofx_index()
        items = self._audiofx_items()
        if index < 0 or index >= len(items):
            self._create_new_audiofx()
            return self._selected_audiofx_index() >= 0
        payload = self._audiofx_payload_from_builder()
        if not payload["description"] and not payload["prompt"]:
            return False
        items[index]["type"] = payload["type"]
        items[index]["description"] = payload["description"]
        items[index]["prompt"] = payload["prompt"]
        items[index]["updated_at"] = QtCore.QDateTime.currentDateTimeUtc().toString(QtCore.Qt.ISODate)
        self._save_audiofx_items(items)
        self._populate_audiofx_items()
        self._select_audiofx_index(index)
        return True

    def _add_audiofx_file(self):
        index = self._selected_audiofx_index()
        if index < 0:
            self._create_new_audiofx()
            index = self._selected_audiofx_index()
        items = self._audiofx_items()
        if index < 0 or index >= len(items):
            return
        current_path = str(items[index].get("file_path") or "").strip()
        start = str(Path(current_path).parent) if current_path else str(Path.home())
        path = self._open_file(
            "Choose AudioFX sound file",
            start,
            "Audio files (*.wav *.mp3 *.flac *.ogg *.m4a);;All files (*.*)",
        )
        if not path:
            return
        items[index]["file_path"] = path
        items[index]["updated_at"] = QtCore.QDateTime.currentDateTimeUtc().toString(QtCore.Qt.ISODate)
        self._save_audiofx_items(items)
        self._populate_audiofx_items()
        self._select_audiofx_index(index)
        logger = getattr(self.context, "logger", None)
        if logger is not None:
            logger.info("[AR_MODE] Indexed AudioFX file for story use: %s", path)

    def _load_selected_audiofx(self):
        index = self._selected_audiofx_index()
        items = self._audiofx_items()
        if index < 0 or index >= len(items):
            return
        item = items[index]
        audio_type = str(item.get("type") or "Auto").strip()
        self._controls["audio_sound_description"].setPlainText(str(item.get("description") or ""))
        self._controls["audio_type"].setCurrentText(audio_type if audio_type in AUDIO_TYPES else "Auto")
        self._controls["audio_prompt_output"].setPlainText(str(item.get("prompt") or ""))
        self._commit_audio_settings()

    def _delete_selected_audiofx(self):
        index = self._selected_audiofx_index()
        items = self._audiofx_items()
        if index < 0 or index >= len(items):
            return
        del items[index]
        self._save_audiofx_items(items)
        self._populate_audiofx_items()

    def _play_selected_audiofx(self):
        index = self._selected_audiofx_index()
        items = self._audiofx_items()
        if index < 0 or index >= len(items):
            return
        file_path = str(items[index].get("file_path") or "").strip()
        if not file_path or not Path(file_path).exists():
            self._warn("Play Sound", "Attach a valid local audio file before playing this AudioFX item.")
            return
        try:
            player = self._ensure_audiofx_player()
            self._apply_audiofx_volume()
            player.setSource(QtCore.QUrl.fromLocalFile(str(Path(file_path).resolve())))
            player.play()
        except Exception as exc:
            self._warn("Play Sound", f"AudioFX playback failed:\n\n{exc}")

    def _play_story_audio_entry(self, entry_obj):
        if self.is_shutdown():
            return
        entry = dict(entry_obj or {}) if isinstance(entry_obj, dict) else {}
        file_path = str(entry.get("file_path") or "").strip()
        if not file_path or not Path(file_path).exists():
            return
        try:
            player = self._ensure_audiofx_player()
            self._apply_audiofx_volume()
            player.setSource(QtCore.QUrl.fromLocalFile(str(Path(file_path).resolve())))
            player.play()
            logger = getattr(self.context, "logger", None)
            if logger is not None:
                logger.info("[AR_MODE] Playing story AudioFX cue %s: %s", entry.get("id") or "", file_path)
        except Exception as exc:
            logger = getattr(self.context, "logger", None)
            if logger is not None:
                logger.warning("[AR_MODE] Story AudioFX playback failed: %s", exc)

    def _ensure_audiofx_player(self):
        if self._audiofx_player is not None:
            return self._audiofx_player
        try:
            from PySide6 import QtMultimedia
        except Exception as exc:
            raise RuntimeError(f"Qt multimedia playback is unavailable: {exc}") from exc
        parent = self._qt_application_instance()
        self._audiofx_output = QtMultimedia.QAudioOutput(parent)
        self._apply_audiofx_volume()
        self._audiofx_player = QtMultimedia.QMediaPlayer(parent)
        self._audiofx_player.setAudioOutput(self._audiofx_output)
        return self._audiofx_player

    def _save_audio_item_description(self):
        prompt = self._controls["audio_prompt_output"].toPlainText().strip()
        if not prompt:
            self._warn("Save as Audio Item Description", "Create or enter an audio prompt first.")
            return
        self._commit_audio_settings()
        self.settings["audio_item_description"] = prompt
        self.storage.save_settings(self.settings)
        self._update_selected_audiofx_from_builder()

    def _clear_audio_prompt(self):
        if self._syncing:
            return
        self._controls["audio_sound_description"].setPlainText("")
        self._controls["audio_prompt_output"].setPlainText("")
        self._controls["audio_type"].setCurrentText("Auto")
        self._commit_audio_settings()

    def _on_enabled_changed(self, checked: bool):
        if self._syncing:
            return
        self._set_mprc_play_isolated_active(False, persist=True)
        self.session.enabled = bool(checked)
        self.save_state()
        self._refresh_debug()

    def _on_show_character_changed(self, checked: bool):
        if self._syncing:
            return
        self.settings["show_current_character_visual"] = bool(checked)
        self.storage.save_settings(self.settings)
        self._refresh_character_preview()

    def _on_current_character_view_mode_changed(self):
        if self._syncing:
            return
        combo = self._controls.get("current_character_view_mode")
        mode = str(combo.currentData() or "active_story").strip() if combo is not None and hasattr(combo, "currentData") else "active_story"
        if mode not in {"active_story", "all"}:
            mode = "active_story"
        self.settings["current_character_view_mode"] = mode
        self.storage.save_settings(self.settings)
        self._refresh_character_preview()

    def _on_ar_mode_changed(self, checked: bool):
        if self._syncing:
            return
        if checked:
            if self.session.mode != AR_MODE:
                self.settings["last_non_ar_mode"] = self.session.mode or "Narrator + characters"
            self.session.mode = AR_MODE
            self.session.enabled = True
            self.ensure_ar_state()
            logger = getattr(self.context, "logger", None)
            if logger is not None:
                logger.info("[AR_MODE] AlternativeReality Mode enabled")
        else:
            if self.session.mode == AR_MODE:
                fallback = str(self.settings.get("last_non_ar_mode") or "Narrator + characters").strip()
                self.session.mode = fallback if fallback and fallback != AR_MODE else "Narrator + characters"
                logger = getattr(self.context, "logger", None)
                if logger is not None:
                    logger.info("[AR_MODE] AlternativeReality Mode disabled; restored mode=%s", self.session.mode)
        self.storage.save_settings(self.settings)
        self.save_state()
        self.refresh_ui()

    def _on_active_persona_changed(self):
        if self._syncing:
            return
        combo = self._controls.get("active")
        persona_id = str(combo.currentData() or "").strip() if combo is not None else ""
        if persona_id:
            self.session.active_persona_id = persona_id
            self.session.current_speaker_id = persona_id
            if self._voice_follows_active():
                self.settings["voice_edit_persona_id"] = persona_id
                self.storage.save_settings(self.settings)
            self.save_state()
            self.refresh_ui()

    def _on_persona_list_changed(self):
        if self._syncing:
            return
        item = self._controls["persona_list"].currentItem()
        persona_id = str(item.data(32) if item is not None else "").strip()
        if persona_id:
            self.session.active_persona_id = persona_id
            self.session.current_speaker_id = persona_id
            if self._voice_follows_active():
                self.settings["voice_edit_persona_id"] = persona_id
                self.storage.save_settings(self.settings)
            self.save_state()
            self.refresh_ui()

    def _add_persona(self):
        new_id = unique_persona_id("custom_persona", {p.id for p in self.personas})
        persona = PersonaConfig(
            id=new_id,
            display_name="Custom Persona",
            role="custom",
            description="",
            system_prompt="Stay consistent with this persona and preserve user agency.",
            speaking_style="clear and consistent",
            allowed_tone="user-defined",
            tags=["custom"],
        )
        self.personas.append(persona)
        self.session.active_persona_id = persona.id
        self.session.current_speaker_id = persona.id
        self.save_state()
        self.refresh_ui()

    def _duplicate_persona(self):
        source = self._selected_persona()
        if source is None:
            return
        payload = source.to_dict()
        payload["id"] = unique_persona_id(source.id + "_copy", {p.id for p in self.personas})
        payload["display_name"] = source.display_name + " Copy"
        persona = PersonaConfig.from_dict(payload)
        self.personas.append(persona)
        self.session.active_persona_id = persona.id
        self.session.current_speaker_id = persona.id
        self.save_state()
        self.refresh_ui()

    def _delete_persona(self):
        if len(self.personas) <= 1:
            return
        persona = self._selected_persona()
        if persona is None:
            return
        if self._persona_is_master_narrator(persona):
            self._warn(
                "Delete persona",
                "This persona is marked as a Master narrator and is protected from deletion. Uncheck Master narrator in the Editor tab before deleting it.",
            )
            return
        self.personas = [item for item in self.personas if item.id != persona.id]
        self.session.active_persona_id = self.personas[0].id
        self.session.current_speaker_id = self.session.active_persona_id
        settings_changed = False
        if normalize_persona_id(self.settings.get("narrator_persona_id", "")) == persona.id:
            self.settings["narrator_persona_id"] = ""
            self.settings["narrator_persona_mode"] = "auto"
            settings_changed = True
        if normalize_persona_id(self.settings.get("voice_edit_persona_id", "")) == persona.id:
            self.settings["voice_edit_persona_id"] = self.session.active_persona_id
            settings_changed = True
        if settings_changed:
            self.storage.save_settings(self.settings)
        self.save_state()
        self.refresh_ui()

    def _reset_defaults(self):
        self.personas = [PersonaConfig.from_dict(item) for item in self.storage._default_json("personas.json", [])]
        self.session = self.storage.load_default_session()
        self.settings["narrator_persona_id"] = ""
        self.settings["narrator_persona_mode"] = "auto"
        self.settings["voice_edit_persona_id"] = ""
        self.settings["current_character_view_mode"] = "active_story"
        self.storage.save_settings(self.settings)
        self._ensure_session_persona()
        self.save_state()
        self.refresh_ui()

    def _load_default_scenario(self):
        self.session = self.storage.load_default_session()
        self._ensure_session_persona()
        self.save_state()
        self.refresh_ui()

    def _open_file(self, title: str, start: str, filter_text: str, *, non_native: bool = False) -> str:
        service = self.dialog_service
        picker = getattr(service, "open_file", None)
        if not callable(picker):
            return ""
        path, _selected = picker(title, start, filter_text)
        return str(path or "")
    def _open_directory(self, title: str, start: str) -> str:
        service = self.dialog_service
        picker = getattr(service, "open_directory", None)
        if not callable(picker):
            return ""
        path = picker(title, start)
        if isinstance(path, tuple):
            path = path[0]
        return str(path or "")
    def _save_file(self, title: str, start: str, filter_text: str, *, non_native: bool = False) -> str:
        service = self.dialog_service
        picker = getattr(service, "save_file", None)
        if not callable(picker):
            return ""
        path, _selected = picker(title, start, filter_text)
        return str(path or "")
    def _import_personas(self):
        path = self._open_file("Import persona JSON", str(Path.home()), "JSON files (*.json)")
        if not path:
            return
        personas = self.storage.import_personas_from_path(path)
        self.personas = personas
        self.session.active_persona_id = personas[0].id
        self.session.current_speaker_id = personas[0].id
        self.save_state()
        self.refresh_ui()

    def _export_personas(self):
        path = self._save_file("Export persona JSON", str(Path.home() / "mprc_personas.json"), "JSON files (*.json)")
        if path:
            self.storage.export_personas_to_path(path, self.personas)

    def _browse_voice_sample(self):
        voices_dir = self._voice_sample_folder()
        start = voices_dir if voices_dir.exists() and voices_dir.is_dir() else Path(__file__).resolve().parents[2]
        path = self._open_file(
            "Choose voice sample",
            str(start),
            "WAV files (*.wav);;Audio files (*.wav *.mp3 *.flac *.ogg *.m4a);;All files (*.*)",
            non_native=True,
        )
        if path:
            self._controls["voice_sample"].setText(path)
            self._populate_voice_sample_picker()
            self._sync_voice_sample_picker(path)
            self._commit_voice_now()

    def _voice_sample_folder(self) -> Path:
        return Path(__file__).resolve().parents[2] / "voices"

    def _voice_sample_files(self) -> list[Path]:
        folder = self._voice_sample_folder()
        if not folder.exists() or not folder.is_dir():
            return []
        audio_suffixes = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".wma"}
        return sorted(
            (path for path in folder.iterdir() if path.is_file() and path.suffix.lower() in audio_suffixes),
            key=lambda path: path.name.lower(),
        )

    def _voice_sample_wav_files(self) -> list[Path]:
        folder = self._voice_sample_folder()
        if not folder.exists() or not folder.is_dir():
            return []
        return sorted((path for path in folder.iterdir() if path.is_file() and path.suffix.lower() == ".wav"), key=lambda path: path.name.lower())

    def _suggest_story_voice_sample(self, persona_payload: dict[str, Any] | None, reserved_paths=()) -> str:
        payload = dict(persona_payload or {})
        files = [path for path in self._voice_sample_wav_files() if path.exists() and path.is_file()]
        reserved = {self._normalized_path_text(item) for item in list(reserved_paths or []) if str(item or "").strip()}
        candidates = [path for path in files if self._normalized_path_text(path) not in reserved]
        if not candidates:
            return ""
        descriptor = " ".join(
            str(payload.get(key) or "")
            for key in (
                "id",
                "display_name",
                "role",
                "description",
                "speaking_style",
                "allowed_tone",
                "system_prompt",
                "ar_description",
            )
        ).lower()
        descriptor_tokens = set(re.findall(r"[a-z0-9]+", descriptor))
        narrator = bool({"narrator", "narration", "storyteller"} & descriptor_tokens)
        female = bool({"female", "woman", "girl", "heroine", "goddess", "queen", "witch", "widow"} & descriptor_tokens)
        male = bool({"male", "man", "boy", "hero", "king", "wizard", "nobleman"} & descriptor_tokens)
        ignored = {
            "a", "an", "and", "character", "companion", "for", "in", "of", "persona", "story", "the", "to", "voice",
        }
        meaningful = descriptor_tokens - ignored

        def rank(path: Path) -> tuple[int, str, str]:
            name = path.stem.lower().replace("_", " ")
            name_tokens = set(re.findall(r"[a-z0-9]+", name))
            score = len(meaningful & name_tokens) * 12
            if narrator:
                score += 120 if "narrator" in name_tokens else 0
                score += 90 if {"story", "teller"}.issubset(name_tokens) or "audiobook" in name_tokens else 0
            elif "narrator" in name_tokens or "audiobook" in name_tokens:
                score -= 25
            if female:
                score += 35 if "female" in name_tokens else 0
                score -= 20 if "male" in name_tokens and "female" not in name_tokens else 0
            if male:
                score += 35 if "male" in name_tokens else 0
                score -= 20 if "female" in name_tokens else 0
            if "preview" in name_tokens or "converted" in name_tokens:
                score -= 8
            identity = str(payload.get("id") or payload.get("display_name") or "story_persona")
            tie = hashlib.sha256(f"{identity}|{path.name.lower()}".encode("utf-8")).hexdigest()
            return -score, tie, path.name.lower()

        return str(sorted(candidates, key=rank)[0])

    def _assign_missing_master_story_voices(self) -> int:
        if not bool(self.settings.get("master_story_auto_assign_voices", True)):
            return 0
        eligible = self._master_story_created_persona_ids()
        if not eligible:
            return 0
        active_ids = [persona_id for persona_id in self._current_linked_persona_ids() if persona_id in eligible]
        reserved = {
            self._normalized_path_text(getattr(getattr(persona, "voice", None), "sample_path", ""))
            for persona in self.personas
            if str(getattr(getattr(persona, "voice", None), "sample_path", "") or "").strip()
        }
        assigned = 0
        for persona_id in active_ids:
            persona = self.persona_by_id(persona_id)
            if persona is None or str(persona.voice.sample_path or "").strip():
                continue
            sample = self._suggest_story_voice_sample(persona.to_dict(), reserved)
            if not sample:
                continue
            persona.voice.enabled = True
            persona.voice.backend = "inherit"
            persona.voice.sample_path = sample
            reserved.add(self._normalized_path_text(sample))
            assigned += 1
        return assigned

    def _populate_voice_file_combo(self, combo, *, include_empty: bool = True, empty_label: str = "No voice selected") -> None:
        if combo is None or not hasattr(combo, "addItem"):
            return
        current = str(combo.currentData() or "").strip() if hasattr(combo, "currentData") else ""
        combo.blockSignals(True)
        combo.clear()
        if include_empty:
            combo.addItem(str(empty_label or "No voice selected"), "")
        files = self._voice_sample_wav_files()
        for path in files:
            combo.addItem(path.name, str(path))
            combo.setItemData(combo.count() - 1, str(path), QtCore.Qt.ToolTipRole)
        if not files and not include_empty:
            combo.addItem("No .wav files in \\voices", "")
            combo.setEnabled(False)
        else:
            combo.setEnabled(True)
        if current:
            for index in range(combo.count()):
                if self._normalized_path_text(combo.itemData(index)) == self._normalized_path_text(current):
                    combo.setCurrentIndex(index)
                    break
        combo.blockSignals(False)

    @staticmethod
    def _default_voice_preview_text() -> str:
        return (
            "Neutral: This is the voice I will use for this character.\n"
            "Warm: I am glad you found me here.\n"
            "Concerned: Wait, something changed in the room.\n"
            "Excited: That is exactly the clue we needed.\n"
            "Whispered: Keep your voice low and listen closely."
        )

    def _preview_voice_sample(self, sample_path: str, text: str, *, status_label=None) -> bool:
        sample = str(sample_path or "").strip()
        if not sample:
            if status_label is not None and hasattr(status_label, "setText"):
                status_label.setText("Choose a .wav voice sample first.")
            return False
        path = Path(sample)
        if not path.exists() or not path.is_file():
            if status_label is not None and hasattr(status_label, "setText"):
                status_label.setText(f"Voice sample not found: {sample}")
            return False
        preview_text = str(text or "").strip() or self._default_voice_preview_text()
        token = self._new_worker_token("voice_preview")
        if not token:
            return False
        if status_label is not None and hasattr(status_label, "setText"):
            status_label.setProperty("_mprc_voice_preview_token", token)
            status_label.setText(f"Loading TTS preview for {path.name}...")
            try:
                self._voice_preview_status_widgets[token] = weakref.ref(status_label)
            except TypeError:
                self._voice_preview_status_widgets[token] = lambda status_label=status_label: status_label

        def worker():
            error = ""
            try:
                with self._mprc_tts_lock:
                    if not self.speech.ensure_ready():
                        raise RuntimeError("The active TTS runtime could not be loaded.")
                if self._worker_should_emit(token):
                    self.speech.speak(preview_text, voice_path=str(path))
            except Exception as exc:
                error = str(exc) or repr(exc)
            if not self._worker_should_emit(token):
                return
            bridge = getattr(self, "_voice_preview_bridge", None)
            if bridge is not None:
                bridge.finished.emit(token, error)
            else:
                self._cancel_worker_token(token)

        if not self._start_daemon_worker(token, worker, name="nc-mprc-voice-preview"):
            self._voice_preview_status_widgets.pop(token, None)
            if status_label is not None and hasattr(status_label, "setText"):
                status_label.setText("Could not start voice preview worker.")
            return False
        return True

    def _on_voice_preview_finished(self, token: str, error: str) -> None:
        token = str(token or "")
        if not self._finish_worker_token(token):
            self._voice_preview_status_widgets.pop(token, None)
            return
        widget_ref = self._voice_preview_status_widgets.pop(token, None)
        widget = widget_ref() if callable(widget_ref) else None
        if widget is not None and hasattr(widget, "property"):
            current_token = str(widget.property("_mprc_voice_preview_token") or "")
            if current_token and current_token != token:
                widget = None
        if widget is not None and hasattr(widget, "setText"):
            widget.setProperty("_mprc_voice_preview_token", "")
            widget.setText(f"Voice preview failed: {error}" if str(error or "").strip() else "Voice preview queued.")
        if error:
            logger = getattr(self.context, "logger", None)
            if logger is not None:
                logger.warning("[MPRC] Voice preview failed: %s", error)

    def _populate_voice_sample_picker(self) -> None:
        combo = self._controls.get("voice_sample_picker")
        if combo is None or not hasattr(combo, "setModel"):
            return
        sample = self._controls.get("voice_sample")
        current_path = str(sample.text() if sample is not None and hasattr(sample, "text") else "").strip()
        combo.blockSignals(True)
        model = QtGui.QStandardItemModel(combo)
        model.setColumnCount(2)

        def add_voice_row(test_label: str, voice_label: str, full_path: str) -> None:
            test_item = QtGui.QStandardItem(test_label)
            voice_item = QtGui.QStandardItem(voice_label)
            for item in (test_item, voice_item):
                item.setEditable(False)
                item.setData(full_path, QtCore.Qt.UserRole)
                if full_path:
                    item.setData(full_path, QtCore.Qt.ToolTipRole)
            model.appendRow([test_item, voice_item])

        files = self._voice_sample_files()
        if files:
            add_voice_row("", "Choose from \\voices...", "")
            for path in files:
                add_voice_row("Test voice", path.name, str(path))
            combo.setEnabled(True)
        else:
            add_voice_row("", "No audio files in \\voices", "")
            combo.setEnabled(False)
        combo.setModel(model)
        combo.setModelColumn(1)
        view = combo.view()
        if hasattr(view, "setColumnWidth"):
            view.setColumnWidth(0, 92)
            view.setColumnWidth(1, 260)
        combo.blockSignals(False)
        self._sync_voice_sample_picker(current_path)

    def _sync_voice_sample_picker(self, sample_path: str) -> None:
        combo = self._controls.get("voice_sample_picker")
        if combo is None or not hasattr(combo, "count"):
            return
        target = self._normalized_path_text(sample_path)
        index = 0
        if target:
            for row in range(combo.count()):
                candidate = self._normalized_path_text(combo.itemData(row))
                if candidate and candidate == target:
                    index = row
                    break
        combo.blockSignals(True)
        combo.setCurrentIndex(index)
        combo.blockSignals(False)

    def _select_voice_sample_from_picker(self) -> None:
        combo = self._controls.get("voice_sample_picker")
        sample = self._controls.get("voice_sample")
        if combo is None or sample is None or not hasattr(combo, "currentData") or not hasattr(sample, "setText"):
            return
        path = str(combo.currentData() or "").strip()
        if path:
            sample.setText(path)
            self._commit_voice_now()

    @staticmethod
    def _normalized_path_text(value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        try:
            return str(Path(text).expanduser().resolve()).casefold()
        except Exception:
            return text.casefold()

    def _browse_character_image(self):
        path = self._open_file("Choose character picture", str(Path.home()), "Images (*.png *.jpg *.jpeg *.webp *.bmp);;All files (*.*)")
        if path:
            self._controls["character_image_path"].setText(path)
            self._commit_editor_now(include_identity=False)

    def _generate_character_image(self):
        persona = self._selected_persona()
        if persona is None:
            return
        key = str(persona.id or "").strip()
        if not key:
            return
        prompt = self._character_picture_prompt(persona)
        if not prompt:
            self._record_visual_debug(
                source="nc.multi_persona_roleplay.character_picture",
                reason="character_picture",
                persona=persona,
                accepted=False,
                message="Character picture skipped because the persona has no usable description or system prompt.",
            )
            self._warn("Create Character Picture", "Add a description or system prompt before generating a character picture.")
            return
        with self._state_lock:
            if key in self._manual_character_image_inflight:
                self._record_visual_debug(
                    source="nc.multi_persona_roleplay.character_picture",
                    reason="character_picture",
                    persona=persona,
                    accepted=None,
                    message="Character picture request is already running.",
                    prompt=prompt,
                )
                return
            self._manual_character_image_inflight.add(key)
        self._record_visual_debug(
            source="nc.multi_persona_roleplay.character_picture",
            reason="character_picture",
            persona=persona,
            accepted=None,
            message="Character picture request queued for a background worker.",
            prompt=prompt,
        )
        if not self._queue_visual_worker(
            "mprc_manual_character_image",
            lambda commit_guard: self._run_manual_character_image_request(
                key,
                commit_guard=commit_guard,
            ),
        ):
            with self._state_lock:
                self._manual_character_image_inflight.discard(key)
            self._record_visual_debug(
                source="nc.multi_persona_roleplay.character_picture",
                reason="character_picture",
                persona=persona,
                accepted=False,
                message="Character picture request could not start a background worker.",
                prompt=prompt,
            )
            self._warn("Create Character Picture", "Character picture generation could not start a background worker.")

    def _run_manual_character_image_request(self, persona_id: str, *, commit_guard=None) -> None:
        key = str(persona_id or "").strip()
        result: dict[str, Any]
        try:
            persona = self.persona_by_id(key)
            if persona is None:
                result = {"ok": False, "message": f"No persona matched character picture request id '{key}'."}
            else:
                result = self._request_character_image_generation(
                    persona,
                    auto_show=True,
                    source="nc.multi_persona_roleplay.character_picture",
                    commit_guard=commit_guard,
                )
        except Exception as exc:
            result = {"ok": False, "message": f"Character picture generation failed:\n\n{exc}"}
        self._emit_manual_visual_finished(
            "character_picture",
            key,
            result,
            commit_guard=commit_guard,
        )

    def _request_character_image_generation(
        self,
        persona: PersonaConfig,
        *,
        auto_show: bool,
        source: str,
        commit_guard=None,
    ) -> dict[str, Any]:
        if not self._visual_commit_allowed(commit_guard):
            return {"ok": False, "message": "Character picture generation was cancelled."}
        visual_service = self.visual_reply_service
        if visual_service is None or not hasattr(visual_service, "request_generation"):
            self._record_visual_debug(
                source=str(source or "character_picture"),
                reason="character_picture",
                persona=persona,
                accepted=False,
                message="Visual Reply generation service is unavailable. Choose a picture from your drive instead.",
                commit_guard=commit_guard,
            )
            return {"ok": False, "message": "Visual Reply generation service is unavailable. Choose a picture from your drive instead."}
        prompt = self._character_picture_prompt(persona)
        if not prompt:
            self._record_visual_debug(
                source=str(source or "character_picture"),
                reason="character_picture",
                persona=persona,
                accepted=False,
                message="Character picture skipped because the persona has no usable description or system prompt.",
                commit_guard=commit_guard,
            )
            return {"ok": False, "message": "Add a description or system prompt before generating a character picture."}
        self._record_visual_debug(
            source=str(source or "character_picture"),
            reason="character_picture",
            persona=persona,
            accepted=None,
            message="Character picture request sent to Visual Reply.",
            prompt=prompt,
            commit_guard=commit_guard,
        )
        try:
            committed, result = self._visual_commit(
                commit_guard,
                lambda: visual_service.request_generation(
                    prompt=prompt,
                    caption=f"Character picture: {persona.display_name}",
                    provider=str(persona.visual.provider or "inherit"),
                    model=str(persona.visual.model or ""),
                    size=str(persona.visual.size or "inherit"),
                    source=source,
                    metadata={"persona_id": persona.id, "purpose": "character_picture"},
                    auto_show=auto_show,
                ),
            )
        except Exception as exc:
            if not self._visual_commit_allowed(commit_guard):
                return {"ok": False, "message": "Character picture generation was cancelled."}
            self._record_visual_debug(
                source=str(source or "character_picture"),
                reason="character_picture",
                persona=persona,
                accepted=False,
                message=f"Character picture generation failed: {exc}",
                prompt=prompt,
                commit_guard=commit_guard,
            )
            return {"ok": False, "message": f"Character picture generation failed:\n\n{exc}"}
        if not committed:
            return {"ok": False, "message": "Character picture generation was cancelled."}
        image_path = ""
        if isinstance(result, dict):
            image_path = str(result.get("image_path") or "").strip()
        if image_path and Path(image_path).exists():
            def apply_image() -> None:
                persona.character_image_path = image_path

            committed, _ = self._visual_commit(commit_guard, apply_image)
            if not committed:
                return {"ok": False, "message": "Character picture generation was cancelled."}
            committed, _ = self._visual_commit(commit_guard, self.save_state)
            if not committed:
                return {"ok": False, "message": "Character picture generation was cancelled."}
            self._record_visual_debug(
                source=str(source or "character_picture"),
                reason="character_picture",
                persona=persona,
                accepted=True,
                message=f"Character picture generated: {image_path}",
                prompt=prompt,
                commit_guard=commit_guard,
            )
            self._visual_commit(commit_guard, self._request_ui_refresh)
            return {"ok": True, "image_path": image_path, "message": "Character picture generated."}
        if result:
            self._record_visual_debug(
                source=str(source or "character_picture"),
                reason="character_picture",
                persona=persona,
                accepted=True,
                message="Visual Reply accepted the character picture request, but no image path was returned yet.",
                prompt=prompt,
                commit_guard=commit_guard,
            )
            return {
                "ok": True,
                "image_path": "",
                "message": "Visual Reply was requested, but no image path was returned yet.",
            }
        self._record_visual_debug(
            source=str(source or "character_picture"),
            reason="character_picture",
            persona=persona,
            accepted=False,
            message="Visual Reply request was not accepted.",
            prompt=prompt,
            commit_guard=commit_guard,
        )
        return {"ok": False, "message": "Visual Reply request was not accepted."}

    @staticmethod
    def _tts_generation_id(payload: dict[str, Any] | None = None) -> str:
        data = dict(payload or {})
        return str(data.get("trace_id") or data.get("pipeline_id") or "default").strip() or "default"

    def handle_tts_generation_started(self, payload: dict[str, Any] | None = None) -> None:
        generation_id = self._tts_generation_id(payload)
        with self._state_lock:
            if self._shutting_down or not bool(self.session.enabled):
                return
            self._tts_generation_ids.add(generation_id)

    def handle_tts_generation_finished(self, payload: dict[str, Any] | None = None) -> None:
        generation_id = self._tts_generation_id(payload)
        with self._state_lock:
            self._tts_generation_ids.discard(generation_id)
            if self._shutting_down or self._tts_generation_ids:
                return
            pending = list(self._pending_tts_persona_visuals)
            self._pending_tts_persona_visuals.clear()
            enabled = bool(self.session.enabled)
        if not enabled:
            return
        for persona_id, spoken_text in pending:
            persona = self.persona_by_id(persona_id)
            if persona is not None:
                self._start_tts_persona_visuals(persona, spoken_text)

    def _start_tts_persona_visuals(self, persona: PersonaConfig, spoken_text: str = "") -> None:
        if bool(self.settings.get("show_current_character_visual", False)):
            self._maybe_generate_character_image_during_tts(persona)
        if not getattr(self, "mprc_play_isolated_active", lambda: False)():
            self._maybe_generate_visual_reply_during_tts(persona, spoken_text)

    def handle_tts_persona_visual(self, persona_id: str, spoken_text: str = "") -> None:
        with self._state_lock:
            if self._shutting_down:
                return
            persona = self.persona_by_id(persona_id)
            if persona is None:
                return
            before_characters = tuple(self.session.ar_state.active_characters or [])
            self._add_persona_to_active_character_state(persona.id)
            changed = before_characters != tuple(self.session.ar_state.active_characters or [])
            if self.session.current_speaker_id != persona.id:
                self.session.current_speaker_id = persona.id
                changed = True
            show_character_visual = bool(self.settings.get("show_current_character_visual", False))
            defer_visuals = bool(self._tts_generation_ids)
            if defer_visuals:
                self._pending_tts_persona_visuals.append((str(persona.id or ""), str(spoken_text or "")))
                self._pending_tts_persona_visuals = self._pending_tts_persona_visuals[-32:]
        if changed:
            self._queue_state_save()
        if show_character_visual and changed:
            self._request_ui_refresh()
        if not defer_visuals:
            self._start_tts_persona_visuals(persona, spoken_text)

    def _maybe_generate_character_image_during_tts(self, persona: PersonaConfig) -> None:
        if persona is None:
            return
        image_path = str(persona.character_image_path or "").strip()
        if image_path and Path(image_path).exists():
            return
        if not self._character_picture_prompt(persona):
            return
        key = str(persona.id or "").strip()
        with self._state_lock:
            if self._shutting_down or not key or key in self._tts_persona_visual_inflight:
                return
            self._tts_persona_visual_inflight.add(key)
        if not self._queue_visual_worker(
            "mprc_tts_character_image",
            lambda commit_guard: self._run_tts_character_image_request(
                key,
                commit_guard=commit_guard,
            ),
        ):
            with self._state_lock:
                self._tts_persona_visual_inflight.discard(key)

    def _run_tts_character_image_request(self, persona_id: str, *, commit_guard=None) -> None:
        if not self._visual_commit_allowed(commit_guard):
            return
        key = str(persona_id or "").strip()
        persona = self.persona_by_id(key)
        if persona is None:
            with self._state_lock:
                self._tts_persona_visual_inflight.discard(key)
            return
        try:
            result = self._request_character_image_generation(
                persona,
                auto_show=False,
                source="nc.multi_persona_roleplay.tts_character_picture",
                commit_guard=commit_guard,
            )
            logger = getattr(self.context, "logger", None)
            if logger is not None:
                if result.get("ok"):
                    logger.info("[MPRC] TTS persona image requested for %s", persona.display_name)
                else:
                    logger.info("[MPRC] TTS persona image skipped for %s: %s", persona.display_name, result.get("message", "not accepted"))
        finally:
            with self._state_lock:
                self._tts_persona_visual_inflight.discard(key)

    def _maybe_generate_visual_reply_during_tts(self, persona: PersonaConfig, spoken_text: str = "") -> None:
        if persona is None or not self.session.enabled:
            return
        if self.visual_reply_service is None:
            if bool(getattr(getattr(persona, "visual", None), "enabled", False)):
                self._record_visual_debug(
                    source="tts_visual_trigger",
                    reason="tts_reply",
                    persona=persona,
                    accepted=False,
                    message="TTS Visual Reply skipped because the Visual Reply service is unavailable.",
                )
            return
        visual = persona.visual
        if not bool(getattr(visual, "enabled", False)):
            return
        mode = str(getattr(visual, "mode", "off") or "off")
        if mode not in {"auto_every_reply", "auto_every_n_replies", "auto_scene_change", "auto_character_change", "auto_important_moment"}:
            self._record_visual_debug(
                source="tts_visual_trigger",
                reason="tts_reply",
                persona=persona,
                accepted=False,
                message=f"TTS Visual Reply skipped because mode '{mode}' is not a TTS-triggered mode.",
            )
            return
        key = str(persona.id or "").strip()
        with self._state_lock:
            if self._shutting_down or not key or key in self._tts_visual_reply_inflight:
                return
            now = time.time()
            cooldown = max(0, int(getattr(visual, "cooldown_seconds", 0) or 0))
            if now - float(self._last_tts_visual_reply_at.get(key, 0.0) or 0.0) < max(3, cooldown):
                self._record_visual_debug(
                    source="tts_visual_trigger",
                    reason="tts_reply",
                    persona=persona,
                    accepted=False,
                    message="TTS Visual Reply skipped because cooldown is active.",
                )
                return
            if visual.max_auto_images_per_session and self.session.auto_image_count >= visual.max_auto_images_per_session:
                self._record_visual_debug(
                    source="tts_visual_trigger",
                    reason="tts_reply",
                    persona=persona,
                    accepted=False,
                    message="TTS Visual Reply skipped because the auto image limit was reached.",
                )
                return
            self._last_tts_visual_reply_at[key] = now
            self._tts_visual_reply_inflight.add(key)
        self._record_visual_debug(
            source="tts_visual_trigger",
            reason="tts_reply",
            persona=persona,
            accepted=None,
            message="TTS Visual Reply request queued for a background worker.",
            prompt=str(spoken_text or "")[:800],
        )
        if not self._queue_visual_worker(
            "mprc_tts_visual_reply",
            lambda commit_guard: self._run_tts_visual_reply_request(
                key,
                str(spoken_text or ""),
                commit_guard=commit_guard,
            ),
        ):
            with self._state_lock:
                self._tts_visual_reply_inflight.discard(key)
            self._record_visual_debug(
                source="tts_visual_trigger",
                reason="tts_reply",
                persona=persona,
                accepted=False,
                message="TTS Visual Reply request could not start a background worker.",
            )

    def _run_tts_visual_reply_request(
        self,
        persona_id: str,
        spoken_text: str = "",
        *,
        commit_guard=None,
    ) -> None:
        if not self._visual_commit_allowed(commit_guard):
            return
        key = str(persona_id or "").strip()
        persona = self.persona_by_id(key)
        if persona is None:
            with self._state_lock:
                self._tts_visual_reply_inflight.discard(key)
            self._record_visual_debug(
                source="tts_visual_request",
                reason="tts_reply",
                accepted=False,
                message=f"No persona matched TTS Visual Reply request id '{persona_id}'.",
                commit_guard=commit_guard,
            )
            return
        try:
            result = self.visual_reply.request_generation(
                persona=persona,
                reason="tts_reply",
                source_text=spoken_text,
                commit_guard=commit_guard,
            )
            if not self._visual_commit_allowed(commit_guard):
                return
            logger = getattr(self.context, "logger", None)
            if logger is not None and not bool(result.get("accepted")):
                logger.info("[MPRC] TTS Visual Reply skipped for %s: %s", persona.display_name, result.get("message", "not accepted"))
        finally:
            with self._state_lock:
                self._tts_visual_reply_inflight.discard(key)

    def _warn(self, title: str, message: str) -> dict[str, str]:
        warning = {
            "title": str(title or "MPRC"),
            "message": str(message or ""),
        }
        self._native_last_warning = warning
        service = self.dialog_service
        reporter = getattr(service, "warning", None)
        if callable(reporter):
            try:
                reporter(warning["title"], warning["message"])
            except Exception:
                pass
        logger = getattr(self.context, "logger", None)
        if logger is not None:
            logger.warning("[MPRC] %s: %s", warning["title"], warning["message"])
        return dict(warning)
    def _character_picture_prompt(self, persona: PersonaConfig) -> str:
        pieces = [
            f"Character portrait of {persona.display_name}",
            persona.description,
            persona.ar_description,
            persona.visual.character_description,
            persona.visual.clothing_props,
            persona.visual.environment_style,
            persona.speaking_style,
            persona.role,
        ]
        if persona.system_prompt:
            pieces.append("Persona essence: " + persona.system_prompt[:360])
        pieces.append("single character, clear face, neutral background, no text, no watermark")
        prompt = ". ".join(str(item or "").strip(" .") for item in pieces if str(item or "").strip())
        return prompting._compact(prompt, 760)

    def _set_image_label(self, _label, image_path: str, *, fallback_text: str = "No picture") -> dict[str, Any]:
        # Return presentation-neutral image state for native QML consumers.
        path_text = str(image_path or "").strip()
        path = Path(path_text) if path_text else None
        return {
            "path": path_text,
            "exists": bool(path is not None and path.exists()),
            "fallback_text": str(fallback_text or "No picture"),
        }
    def _refresh_character_preview(self) -> None:
        active = self._current_character_preview_persona()
        self._native_character_preview = {
            "visible": bool(self.settings.get("show_current_character_visual", False)),
            "view_mode": self._current_character_view_mode(),
            "persona": active.to_dict() if active is not None else None,
            "image": self._set_image_label(
                None,
                str(getattr(active, "character_image_path", "") or ""),
                fallback_text="No picture",
            ),
        }
        self._refresh_character_roster_strip()
    def _current_character_view_mode(self) -> str:
        mode = str(self.settings.get("current_character_view_mode") or "active_story").strip().lower()
        return mode if mode in {"active_story", "all"} else "active_story"

    def _current_character_active_story_persona_ids(self) -> list[str]:
        known = {persona.id for persona in self.personas}
        ids = [persona_id for persona_id in self._current_linked_persona_ids() if persona_id in known]
        if not ids:
            ids = [
                normalize_persona_id(item)
                for item in list(getattr(self.session.ar_state, "active_characters", []) or [])
                if normalize_persona_id(item) in known
            ]
        if not ids:
            ids = [
                persona_id
                for persona_id in (self.session.current_speaker_id, self.session.active_persona_id)
                if str(persona_id or "").strip() and persona_id in known
            ]
        return list(dict.fromkeys(ids))

    def _current_character_roster_personas(self) -> list[PersonaConfig]:
        if self._current_character_view_mode() == "all":
            return list(self.personas)
        ids = self._current_character_active_story_persona_ids()
        by_id = {persona.id: persona for persona in self.personas}
        return [by_id[persona_id] for persona_id in ids if persona_id in by_id]

    def _current_character_preview_persona(self) -> PersonaConfig | None:
        personas = self._current_character_roster_personas()
        if not personas:
            return None
        current = self.current_speaker_persona() or self.active_persona()
        if current is not None and any(persona.id == current.id for persona in personas):
            return current
        return personas[0]

    def _refresh_current_character_quick_info(self, persona: PersonaConfig) -> None:
        meta = self._controls.get("current_character_meta")
        story = self._controls.get("current_character_story")
        if meta is not None:
            meta.setText(self._current_character_meta_text(persona))
        if story is not None:
            story.setText(self._current_character_story_text(persona))

    def _current_character_meta_text(self, persona: PersonaConfig) -> str:
        voice = persona.voice
        voice_sample = str(getattr(voice, "sample_path", "") or "").strip()
        voice_ready = bool(getattr(voice, "enabled", False) and voice_sample and Path(voice_sample).exists())
        if getattr(voice, "enabled", False):
            voice_text = "ready" if voice_ready else "needs sample"
        else:
            voice_text = "off"
        visual_ready = "image ready" if str(persona.character_image_path or "").strip() and Path(str(persona.character_image_path)).exists() else "no avatar image"
        ar_text = "AR profile on" if bool(getattr(persona, "ar_profile_enabled", False)) else "AR profile off"
        narrator = "Narrator" if persona.id == self.selected_narrator_persona_id() else "Character"
        pieces = [
            f"ID: {persona.id}",
            f"Type: {narrator}",
            f"Behavior: {persona.behavior_mode or 'default'}",
            f"Memory: {persona.memory_scope or 'default'}",
            f"Voice: {voice_text}",
            f"Visual: {visual_ready}",
            ar_text,
        ]
        return " | ".join(pieces)

    def _current_character_story_text(self, persona: PersonaConfig) -> str:
        current = self._current_story_involvement(persona)
        saved = self._saved_story_involvement(persona)
        if current and saved:
            return f"Stories: {current}. Also in saved: {', '.join(saved[:4])}"
        if current:
            return f"Stories: {current}"
        if saved:
            return f"Stories: saved in {', '.join(saved[:5])}"
        return "Stories: not linked to a saved Master Story yet."

    def _current_story_involvement(self, persona: PersonaConfig) -> str:
        title = str(self.settings.get("last_master_story_title") or self.settings.get("last_master_story_id") or "").strip()
        if not title:
            return ""
        roles = []
        if persona.id == self.session.active_persona_id:
            roles.append("active")
        if persona.id == self.session.current_speaker_id:
            roles.append("speaking")
        if persona.id in self._master_story_linked_persona_ids():
            roles.append("linked")
        if persona.id in self._master_story_created_persona_ids():
            roles.append("new")
        if not roles:
            return ""
        return f"{title} ({', '.join(dict.fromkeys(roles))})"

    def _saved_story_involvement(self, persona: PersonaConfig) -> list[str]:
        matches = []
        for item in self.storage.load_story_index():
            story_id = str(item.get("id") or "").strip()
            payload = self.storage.load_story(story_id)
            if self._story_payload_includes_persona(payload, persona):
                matches.append(str(item.get("title") or story_id).strip() or story_id)
        return matches

    def _story_payload_includes_persona(self, payload: dict[str, Any], persona: PersonaConfig) -> bool:
        if not isinstance(payload, dict):
            return False
        wanted = {persona.id, normalize_persona_id(persona.display_name)}
        for key in ("active_persona_id", "current_speaker_id"):
            if normalize_persona_id(payload.get(key)) in wanted:
                return True
        session = dict(payload.get("session") or {}) if isinstance(payload.get("session"), dict) else {}
        ar_state = dict(session.get("ar_state") or {}) if isinstance(session.get("ar_state"), dict) else {}
        for item in list(ar_state.get("active_characters") or []):
            if normalize_persona_id(item) in wanted:
                return True
        for item in list(payload.get("personas") or []):
            if not isinstance(item, dict):
                continue
            if normalize_persona_id(item.get("id")) in wanted:
                return True
            if normalize_persona_id(item.get("display_name")) in wanted:
                return True
        overrides = payload.get("persona_overrides")
        if isinstance(overrides, dict):
            for key, value in overrides.items():
                if normalize_persona_id(key) in wanted:
                    return True
                if isinstance(value, dict) and normalize_persona_id(value.get("display_name")) in wanted:
                    return True
        return False

    def _current_character_persona(self) -> PersonaConfig | None:
        return self._current_character_preview_persona()

    def _set_current_character_quick_status(self, message: str) -> None:
        label = self._controls.get("current_character_quick_status")
        if label is not None:
            label.setText(str(message or ""))

    def _quick_change_avatar_image(self):
        persona = self._current_character_persona()
        if persona is None:
            return
        start = str(Path(persona.character_image_path).parent) if str(persona.character_image_path or "").strip() else str(Path.home())
        path = self._open_file("Choose avatar image", start, "Images (*.png *.jpg *.jpeg *.webp *.bmp);;All files (*.*)")
        if not path:
            return
        persona.character_image_path = path
        self.save_state()
        self.refresh_ui()
        self._set_current_character_quick_status(f"Avatar image updated for {persona.display_name}.")

    def _quick_save_persona(self):
        persona = self._current_character_persona()
        self.storage.save_settings(self.settings)
        self.save_state()
        self._notify_changed()
        self._set_current_character_quick_status(f"Saved {persona.display_name if persona else 'persona settings'}.")

    def _quick_import_persona(self):
        try:
            path = self._open_file("Import persona JSON", str(Path.home()), "JSON files (*.json)")
            if not path:
                return
            personas = self.storage.import_personas_from_path(path)
            self.personas = personas
            self.session.active_persona_id = personas[0].id
            self.session.current_speaker_id = personas[0].id
            self.save_state()
            self.refresh_ui()
            self._set_current_character_quick_status(f"Imported {len(personas)} persona(s).")
        except Exception as exc:
            self._warn("Import Persona", f"Import failed:\n\n{exc}")

    def _quick_duplicate_persona(self):
        source = self._current_character_persona()
        if source is None:
            return
        payload = source.to_dict()
        payload["id"] = unique_persona_id(source.id + "_copy", {p.id for p in self.personas})
        payload["display_name"] = source.display_name + " Copy"
        persona = PersonaConfig.from_dict(payload)
        self.personas.append(persona)
        self.session.active_persona_id = persona.id
        self.session.current_speaker_id = persona.id
        self.save_state()
        self.refresh_ui()
        self._set_current_character_quick_status(f"Duplicated {source.display_name} as {persona.display_name}.")

    def _quick_edit_persona(self):
        persona = self._current_character_persona()
        if persona is None:
            return
        self.session.active_persona_id = persona.id
        self.session.current_speaker_id = persona.id
        self.save_state()
        self.refresh_ui()
        self._select_mprc_tab(2)
        self._set_current_character_quick_status(f"Editing {persona.display_name}.")

    def _refresh_character_roster_strip(self) -> None:
        active_id = str(self.session.current_speaker_id or self.session.active_persona_id or "")
        self._native_character_roster = [
            {
                "id": persona.id,
                "display_name": persona.display_name,
                "role": persona.role,
                "active": persona.id == active_id,
                "image": self._set_image_label(
                    None,
                    str(persona.character_image_path or ""),
                    fallback_text="No picture",
                ),
            }
            for persona in self._current_character_roster_personas()
        ]
    def _character_thumbnail_icon(self, persona: PersonaConfig):
        from PySide6 import QtCore, QtGui

        path = Path(str(persona.character_image_path or "").strip())
        if path.exists():
            pixmap = QtGui.QPixmap(str(path))
            if not pixmap.isNull():
                return QtGui.QIcon(pixmap.scaled(220, 170, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
        fallback = self._tab_icon("editor", "#a78bfa")
        return QtGui.QIcon(fallback.pixmap(QtCore.QSize(170, 170)))

    def _select_persona_id(self, persona_id: str):
        target = str(persona_id or "").strip()
        if not target:
            return
        self.session.active_persona_id = target
        self.session.current_speaker_id = target
        if self._voice_follows_active():
            self.settings["voice_edit_persona_id"] = target
            self.storage.save_settings(self.settings)
        self.save_state()
        self.refresh_ui()

    def _test_voice(self):
        self._update_voice_warning()
        warning_label = self._controls.get("voice_warning")
        warning = str(warning_label.text() if warning_label is not None and hasattr(warning_label, "text") else "").strip()
        persona = self._selected_voice_persona()
        if persona is None:
            if warning_label is not None and hasattr(warning_label, "setText"):
                warning_label.setText("No voice persona is selected.")
            return
        route = self.voice_router.effective_voice_config({
            "persona_id": persona.id,
            "tts_backend": self.current_tts_backend(),
            "text": f"[CHARACTER: {persona.display_name}]\nVoice preview.",
        })
        sample = str(route.get("sample_path") or getattr(persona.voice, "sample_path", "") or "").strip()
        if not sample:
            logger = getattr(self.context, "logger", None)
            if logger is not None:
                logger.warning("Voice test skipped: %s", warning)
            if warning_label is not None and hasattr(warning_label, "setText"):
                warning_label.setText(warning or f"{persona.display_name} has no usable voice sample.")
            return
        self._preview_voice_sample(sample, f"[CHARACTER: {persona.display_name}]\n{self._default_voice_preview_text()}", status_label=warning_label)

    def _update_voice_warning(self):
        persona = self._selected_voice_persona()
        payload = {"tts_backend": self.current_tts_backend()}
        if persona is not None:
            payload["persona_id"] = persona.id
        route = self.voice_router.effective_voice_config(payload)
        warning = str(route.get("warning") or "")
        if not warning and route.get("enabled") and route.get("supported"):
            warning = "Voice sample will be routed to the active TTS backend for new assistant replies."
        narrator_status = self._narrator_voice_status_text()
        if narrator_status:
            warning = f"{narrator_status}\n{warning}".strip()
        self._controls["voice_warning"].setText(warning)
        self._debug_voice = json.dumps(route, indent=2)
        self._refresh_debug()

    def _narrator_voice_status_text(self) -> str:
        if self.session.mode != AR_MODE:
            return ""
        narrator = self.selected_narrator_persona()
        if narrator is None:
            return "AR narrator: Auto could not find a narrator persona. Add a narrator-tagged persona or choose one explicitly."
        mode = "Auto" if self._narrator_selection_mode() == "auto" else "Selected"
        payload = {
            "persona_id": narrator.id,
            "tts_backend": self.current_tts_backend(),
            "text": "[NARRATOR] Voice route check.",
        }
        route = self.voice_router.effective_voice_config(payload)
        sample = str(route.get("sample_path") or "").strip()
        if sample:
            return f"AR narrator ({mode}): {narrator.display_name} -> {Path(sample).name}"
        warning = str(route.get("warning") or "").strip()
        if warning:
            return f"AR narrator ({mode}): {narrator.display_name}. {warning}"
        return f"AR narrator ({mode}): {narrator.display_name}."

    def _reset_scene(self):
        active_id = self.session.active_persona_id
        mode = self.session.mode
        ar_pacing = self.session.ar_pacing
        ar_interaction = self.session.ar_interaction_frequency
        ar_dialogue_density = self.session.ar_dialogue_density
        self.session = RoleplaySessionState(
            mode=mode,
            active_persona_id=active_id,
            current_speaker_id=active_id,
            ar_pacing=ar_pacing,
            ar_interaction_frequency=ar_interaction,
            ar_dialogue_density=ar_dialogue_density,
        )
        if self.session.mode == AR_MODE:
            self.ensure_ar_state()
        self.save_state()
        self.refresh_ui()

    def _export_session(self):
        path = self._save_file("Export roleplay session", str(Path.home() / "mprc_session.json"), "JSON files (*.json)")
        if path:
            Path(path).write_text(json.dumps(self.session.to_dict(), indent=2, ensure_ascii=True), encoding="utf-8")

    def _import_session(self):
        path = self._open_file("Import roleplay session", str(Path.home()), "JSON files (*.json)")
        if path:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            self.session = RoleplaySessionState.from_dict(payload if isinstance(payload, dict) else {})
            self._ensure_session_persona()
            self.save_state()
            self.refresh_ui()

    def _preview_visual_prompt(self):
        persona = self._selected_persona()
        payload = self.visual_reply.build_prompt(
            persona=persona, reason="manual", use_action_prompt=False,
            source_text=self._remote_latest_reply() if persona is not None and prompting.flexible_visual_appearance(persona) else "",
        )
        self._debug_visual_prompt = json.dumps(payload, indent=2)
        self._refresh_debug()

    def _generate_visual_reply(self):
        persona = self._selected_persona()
        persona_id = str(getattr(persona, "id", "") or "")
        self._debug_visual_prompt = json.dumps(
            {"queued": True, "message": "Visual Reply request queued for a background worker.", "persona_id": persona_id},
            indent=2,
            ensure_ascii=True,
        )
        self._refresh_debug()
        if not self._queue_visual_worker(
            "mprc_manual_visual_reply",
            lambda commit_guard: self._run_manual_visual_reply_request(
                persona_id,
                kind="manual_visual_reply",
                commit_guard=commit_guard,
            ),
        ):
            result = {"accepted": False, "message": "Visual Reply request could not start a background worker."}
            self._on_manual_visual_finished("manual_visual_reply", persona_id, result)

    def _clear_debug(self):
        self._debug_prompt = ""
        self._debug_visual_prompt = ""
        self._chat_visual_prompt_debug = ""
        self._debug_voice = ""
        self._refresh_debug()

    def _refresh_debug(self):
        persona = self.active_persona()
        if persona is not None and not self._debug_prompt:
            context = self.roleplay_engine.chat_context({}) if self.session.enabled else None
            self._debug_prompt = str((context or {}).get("context") or "")
        self._native_debug_state = {
            "prompt": str(self._debug_prompt or ""),
            "visual_prompt": str(self._debug_visual_prompt or ""),
            "voice": str(self._debug_voice or ""),
            "session": self.session.to_dict(),
            "visual_calls": self._visual_debug_log_text(),
            "chat_visual_prompt": str(
                self._chat_visual_prompt_debug
                or "Visual prompt debug will appear here after an MPRC Visual Reply request."
            ),
        }

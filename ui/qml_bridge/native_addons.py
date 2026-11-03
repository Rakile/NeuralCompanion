"""Process-owned addon lifecycle for the native QML application."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from core.addons.manager import AddonManager
from core.runtime_status import build_runtime_status_snapshot
from ui.qml_bridge.native_host_services import (
    build_native_host_services,
    facade_addon_runtime_operations,
)


class _NativeAddonHost:
    """Non-widget host object for finite addon services during extraction.

    Existing service classes accept a host object, but their domain operations
    are already routed through ``AddonRuntimeOperations``.  This object supplies
    only those finite snapshots and commands; it is deliberately not a QWidget
    and has no Designer surface.
    """

    def __init__(self, application_facade: Any) -> None:
        self._application = application_facade
        self._addon_manager: AddonManager | None = None
        self._addon_runtime_operations = facade_addon_runtime_operations(
            application_facade
        )
        self._focused_addon_ui_ports = None
        self._scenic_avatar_host_operations = None
        self._main_chat_remote_host_service = None
        self._runtime_controller: Any | None = None
        self.backend = self
        self.thread = None

    def bind_runtime_controller(self, controller: Any) -> None:
        self._runtime_controller = controller

    def runtime_running(self) -> bool:
        controller = self._runtime_controller
        return bool(controller is not None and getattr(controller, "running", False))

    def runtime_engine_state(self) -> dict[str, bool]:
        return {key: bool(getattr(self._runtime_controller, key, False)) for key in
                ('starting', 'initializing', 'stopping', 'cancelling', 'cleanup_pending')}

    def _require_runtime_controller(self) -> Any:
        controller = self._runtime_controller
        if controller is None:
            raise RuntimeError("Native runtime controller is unavailable.")
        return controller

    def _application_config(self) -> dict[str, Any]:
        return dict(self._application.config.snapshot().values)

    def _build_addon_llm_snapshot(self) -> dict[str, Any]:
        config = self._application_config()
        return {
            "chat_provider": str(config.get("chat_provider", "lmstudio") or "lmstudio"),
            "selected_model": str(config.get("model_name", "") or ""),
            "stream_mode": bool(config.get("stream_mode", False)),
            "input_mode": str(config.get("input_mode", "") or ""),
            "input_role": str(config.get("input_message_role", "") or ""),
            "temperature": float(config.get("temperature", 0.0) or 0.0),
            "top_p": float(config.get("top_p", 0.0) or 0.0),
            "top_k": int(config.get("top_k", 0) or 0),
            "min_p": float(config.get("min_p", 0.0) or 0.0),
            "repeat_penalty": float(config.get("repeat_penalty", 0.0) or 0.0),
        }

    def _build_addon_tts_snapshot(self) -> dict[str, Any]:
        config = self._application_config()
        try:
            speech = dict(self._application.addon_speech.snapshot() or {})
        except Exception:
            speech = {}
        return {
            "backend": str(config.get("tts_backend", "none") or "none"),
            "voice_path": str(config.get("voice_path", "") or ""),
            **speech,
        }

    def _build_addon_avatar_snapshot(self) -> dict[str, Any]:
        config = self._application_config()
        mode = str(config.get("avatar_mode", "none") or "none")
        try:
            adapter = self._application.addon_avatar_resources.adapter()
            adapter_state = dict(adapter.snapshot() or {}) if adapter is not None and hasattr(adapter, "snapshot") else {}
        except Exception:
            adapter_state = {}
        return {
            "engine": mode,
            **adapter_state,
            "sensory_feedback_source": str(config.get("sensory_feedback_source", "off") or "off"),
            "sensory_feedback_interval_seconds": float(config.get("sensory_feedback_interval_seconds", 7.0) or 7.0),
            "sensory_pingpong_enabled": bool(config.get("sensory_pingpong_enabled", False)),
        }

    def build_runtime_status_snapshot(self) -> dict[str, Any]:
        config = self._application_config()
        activity = self._application.status.activity()
        running = self.runtime_running()
        return build_runtime_status_snapshot(
            config,
            running=running,
            engine_connected=running,
            shell_mode=False,
            lifecycle_state="running" if running else "stopped",
            listening=bool(getattr(activity, "listening", False)),
            recording=bool(getattr(activity, "recording", False)),
            playback_paused=bool(getattr(activity, "paused", False)),
            source="qml_native",
        )

    def start_engine(self, *, offline_replay_only: bool = False) -> bool:
        return bool(
            self._require_runtime_controller().start(
                offline_replay_only=bool(offline_replay_only)
            )
        )

    def stop_engine(self) -> bool:
        return bool(self._require_runtime_controller().request_stop())

    def reset_chat_session(self) -> None:
        self._require_runtime_controller().reset_conversation()

    def trigger_control_action(self, action: str) -> dict[str, object]:
        return dict(
            self._require_runtime_controller().trigger_action(str(action or "").strip())
            or {}
        )

    def publish_main_chat_remote_status(self) -> None:
        service = self._main_chat_remote_host_service
        if service is not None:
            service.publish_status()

    def publish_main_chat_remote_history(self) -> None:
        service = self._main_chat_remote_host_service
        if service is not None:
            service.publish_history()

    def _bind_designer_widgets(self, _root_widget) -> None:
        raise RuntimeError("Designer widget binding was removed from the native QML host.")

    def save_session(self) -> None:
        # NativeSessionStore is the sole session writer. Addon-local changes
        # notify the QML shell through their normal finite contracts.
        return None

    def _invoke_addon_service_capability(
        self,
        service_id: str,
        capability: str,
        payload=None,
        default=None,
        **metadata_match,
    ):
        manager = self._addon_manager
        if manager is None:
            return default
        try:
            value = manager.invoke_service_capability(
                str(service_id),
                str(capability),
                dict(payload or {}),
                **dict(metadata_match or {}),
            )
        except Exception:
            return default
        return default if value is None else value

    def _invoke_addon_capability(self, addon_id, capability, payload=None, default=None):
        manager = self._addon_manager
        if manager is None:
            return default
        try:
            value = manager.invoke_addon_capability(
                str(addon_id), str(capability), dict(payload or {})
            )
        except Exception:
            return default
        return default if value is None else value

    def _current_chat_provider_value(self) -> str:
        return str(self._application_config().get("chat_provider", "lmstudio") or "lmstudio")

    def _current_tts_backend_value(self) -> str:
        return str(self._application_config().get("tts_backend", "none") or "none")

    def _current_avatar_mode_value(self) -> str:
        return str(self._application_config().get("avatar_mode", "none") or "none")

    def _current_sensory_feedback_source_value(self) -> str:
        return str(self._application_config().get("sensory_feedback_source", "off") or "off")

    def hotkey_catalog(self):
        return self._native_hotkey_service.list_bindings()

    def set_hotkey_binding(self, action, binding):
        return self._native_hotkey_service.set_binding(action, binding)

    def reset_hotkey_bindings(self):
        return self._native_hotkey_service.reset_defaults()

    def _refresh_hotkey_shortcuts(self) -> None:
        return None

    def _refresh_hotkey_labels(self) -> None:
        return None

    def send_typed_chat_message(self, text=None, metadata=None) -> bool:
        result = self._application.chat.submit_text(
            str(text or ""),
            metadata=dict(metadata or {}),
        )
        return bool(result.accepted)


class _NativeAudioStoryActions:
    """Widget-free broker shared by Audio Story and Visual Reply."""

    def __init__(self) -> None:
        self._actions: Any | None = None

    def bind_story_actions(self, actions: Any) -> None:
        self._actions = actions

    def unbind_story_actions(self, actions: Any) -> None:
        if self._actions is actions:
            self._actions = None

    def load_current_image(self):
        actions = self._actions
        if actions is None:
            return {"ok": False, "message": "Audio Story Mode is unavailable."}
        return actions.load_current_image()

    def refresh_master_style_anchor(self):
        actions = self._actions
        if actions is None:
            return {"ok": False, "message": "Audio Story Mode is unavailable."}
        return actions.refresh_master_style_anchor()


class NativeAddonRuntime:
    """Own discovery, initialization, facade binding, and deterministic close."""

    def __init__(
        self,
        application_facade: Any,
        *,
        app_root: Path,
        chat_persona_store: Any | None = None,
        persona_prompt_store: Any | None = None,
        persona_rule_catalog: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        apply_persona_prompts: Callable[[dict[str, Any]], None] | None = None,
        quick_persona_identity: Callable[[], str] | None = None,
        quick_persona_choices: Callable[[], list[dict[str, Any]]] | None = None,
        apply_quick_persona: Callable[[int], dict[str, Any]] | None = None,
        llm_model_choices: Callable[[], dict[str, Any]] | None = None,
        voice_choices: Callable[[], dict[str, Any]] | None = None,
        apply_voice: Callable[[str], dict[str, Any]] | None = None,
        tts_provider_choices: Callable[[], dict[str, Any]] | None = None,
        apply_tts_provider: Callable[[str], dict[str, Any]] | None = None,
        web_search_status: Callable[[], dict[str, Any] | None] | None = None,
        set_web_search_enabled: Callable[[bool], dict[str, Any]] | None = None,
        apply_llm_model: Callable[[str, str], dict[str, Any]] | None = None,
        toggle_main_window: Callable[[], object] | None = None,
        initialize_system: Callable[[], object] | None = None,
        terminate_system: Callable[[], object] | None = None,
        runtime_state: Callable[[], dict[str, bool]] | None = None,
        activate_floating_workspace: Callable[[str, bool], object] | None = None,
        on_phone_chat_load: Callable[[bool], None] | None = None,
        chat_persistence_enabled: bool = True,
    ) -> None:
        self._application = application_facade
        self._host = _NativeAddonHost(application_facade)
        host_services = build_native_host_services(
            self._host,
            application_facade,
            chat_persona_store=chat_persona_store,
            persona_prompt_store=persona_prompt_store,
            persona_rule_catalog=persona_rule_catalog,
            apply_persona_prompts=apply_persona_prompts,
            quick_persona_identity=quick_persona_identity,
            quick_persona_choices=quick_persona_choices,
            apply_quick_persona=apply_quick_persona,
            llm_model_choices=llm_model_choices,
            voice_choices=voice_choices,
            apply_voice=apply_voice,
            tts_provider_choices=tts_provider_choices,
            apply_tts_provider=apply_tts_provider,
            web_search_status=web_search_status,
            set_web_search_enabled=set_web_search_enabled,
            apply_llm_model=apply_llm_model,
            toggle_main_window=toggle_main_window,
            initialize_system=initialize_system,
            terminate_system=terminate_system,
            runtime_state=runtime_state,
            activate_floating_workspace=activate_floating_workspace,
            app_root=app_root,
            on_phone_chat_load=on_phone_chat_load,
            chat_persistence_enabled=chat_persistence_enabled,
        )
        host_services["qt.audio_story_actions"] = _NativeAudioStoryActions()
        self._manager = AddonManager(
            app_root=Path(app_root),
            llm_snapshot_getter=self._host._build_addon_llm_snapshot,
            tts_snapshot_getter=self._host._build_addon_tts_snapshot,
            avatar_snapshot_getter=self._host._build_addon_avatar_snapshot,
            host_services=host_services,
        )
        self._host._addon_manager = self._manager
        self._bindings: list[Any] = []
        self._started = False

    @property
    def manager(self) -> AddonManager:
        return self._manager

    def bind_runtime_controller(self, controller: Any) -> None:
        self._host.bind_runtime_controller(controller)
        self.publish_main_chat_remote_status()
        self.publish_main_chat_remote_history()

    def publish_main_chat_remote_status(self) -> None:
        self._host.publish_main_chat_remote_status()

    def publish_main_chat_remote_history(self) -> None:
        self._host.publish_main_chat_remote_history()

    def start(self) -> None:
        if self._started:
            return
        if not self._application.addons.install_identity_relay_runtime(self._manager):
            raise RuntimeError("Identity Relay runtime could not attach to the addon manager.")
        self._manager.discover()
        self._manager.load_all()
        self._bindings.append(
            self._application.addons.bind_manager_getter(lambda: self._manager)
        )
        try:
            self._manager.initialize_all()
            self._bindings.append(
                self._application.addons.bind_event_publisher(
                    self._manager.publish_event
                )
            )
        except BaseException:
            self.close()
            raise
        self._started = True

    def import_session_state(self, payload: dict[str, Any] | None) -> None:
        if not self._started:
            raise RuntimeError("Native addon runtime must start before session import.")
        self._manager.import_session_state(dict(payload or {}))

    def close(self) -> None:
        if self._manager is not None:
            self._manager.unload_all()
        for binding in reversed(self._bindings):
            try:
                binding.close() if hasattr(binding, "close") else binding()
            except Exception:
                pass
        self._bindings.clear()
        self._started = False


__all__ = ["NativeAddonRuntime"]

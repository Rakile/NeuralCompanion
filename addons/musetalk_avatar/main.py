from __future__ import annotations

from pathlib import Path

from core.addons.base import BaseAddon
from addons.musetalk_avatar.native_service import NativeMuseTalkService


PROVIDER_ID = "musetalk"


class Addon(BaseAddon):
    def initialize(self, context):
        super().initialize(context)
        self._musetalk_ui_service = NativeMuseTalkService(context)
        context.services.register('musetalk_resources', self._musetalk_ui_service,
                                  metadata={'kind': 'runtime_resource'})
        self._runtime_config = context.capabilities.runtime_config
        self._avatar_service = context.capabilities.avatar
        self._preview_lifecycle = _PreviewLifecycle()
        context.tasks.register_resource("preview_runtime", self._preview_lifecycle)
        if self._avatar_service is None:
            context.logger.warning("MuseTalk avatar addon could not find qt.avatar_providers service."); return None
        self._avatar_service.register_provider(
            provider_id=PROVIDER_ID,
            label="MuseTalk",
            description="MuseTalk avatar rendering and preview pipeline.",
            order=200,
            factory=self._musetalk_ui_service.create_adapter,
            construction_input_type=self._musetalk_ui_service.construction_input_type,
            metadata={
                "kind": "avatar",
                "transport": "musetalk_worker",
            },
        )
        context.logger.info("MuseTalk avatar provider addon initialized.")
        return None

    def export_session_state(self):
        service = getattr(self, "_musetalk_ui_service", None)
        if service is not None:
            try:
                return service.export_avatar_runtime_settings() or {}
            except AttributeError:
                pass
        return {}

    def export_preset_state(self):
        return self.export_session_state()

    def import_session_state(self, session):
        service = getattr(self, "_musetalk_ui_service", None)
        if service is not None:
            try:
                return service.import_avatar_runtime_settings(session)
            except AttributeError:
                pass
        return None

    def import_preset_state(self, preset):
        return self.import_session_state(preset)

    def invoke_capability(self, capability, payload=None):
        capability = str(capability or "").strip()
        payload = dict(payload or {})
        if capability == "runtime.delete_package":
            try:
                return self._musetalk_ui_service.delete_package(payload)
            except Exception as error:
                return {"ok": False, "error": str(error)}
        if capability == "runtime.discover_avatar_packs":
            from addons.musetalk_avatar import pack_runtime

            runtime_config = dict(self._runtime_config.snapshot() or {})
            return pack_runtime.pack_catalog(
                runtime_config,
                legacy_map=self._musetalk_ui_service.legacy_emotion_avatar_map(),
                legacy_transitions=self._musetalk_ui_service.legacy_avatar_transitions(),
                packs_dir=Path(self.context.app_root) / "avatar_packs",
            )
        if capability == "runtime.get_avatar_pack":
            from addons.musetalk_avatar import pack_runtime

            return pack_runtime.get_pack(**dict(payload.get("kwargs") or {}))
        if capability == "runtime.normalize_enabled_pack_emotions":
            from addons.musetalk_avatar import pack_runtime

            return pack_runtime.normalize_enabled_pack_emotions(payload.get("value"))
        if capability == "runtime.enabled_pack_emotions":
            from addons.musetalk_avatar import pack_runtime

            return pack_runtime.enabled_pack_emotions(
                payload.get("runtime_config") or {},
                payload.get("pack_id"),
            )
        if capability == "runtime.vram_mode":
            from addons.musetalk_avatar import text_policy

            return text_policy.vram_mode(
                payload.get("runtime_config") or {},
                default=str(payload.get("default") or "quality"),
            )
        if capability == "runtime.chunk_limits_for_index":
            from addons.musetalk_avatar import text_policy

            return text_policy.chunk_limits_for_index(
                int(payload.get("chunk_index", 0) or 0),
                payload.get("runtime_config") or {},
                payload.get("defaults") or {},
            )
        if capability == "runtime.preview.stream_frames":
            from addons.musetalk_avatar import preview_runtime, state as musetalk_state
            from core import runtime_files

            return self._preview_lifecycle.run(
                lambda stop_event: preview_runtime.stream_musetalk_preview_frames(
                    payload.get("playback_state") or {},
                    stop_event,
                    runtime_config=payload.get("runtime_config") or {},
                    list_png_frames=runtime_files.list_png_frames,
                    musetalk_state_module=musetalk_state,
                ),
                payload.get("stop_event"),
            )
        if capability == "runtime.preview.stream_delegated_audio_progress":
            from addons.musetalk_avatar import preview_runtime, state as musetalk_state

            return self._preview_lifecycle.run(
                lambda stop_event: preview_runtime.stream_delegated_audio_progress(
                    payload.get("playback_state") or {},
                    stop_event,
                    musetalk_state_module=musetalk_state,
                ),
                payload.get("stop_event"),
            )
        if capability == "runtime.preview.prime_frame":
            from addons.musetalk_avatar import preview_runtime, state as musetalk_state
            from core import runtime_files

            return self._preview_lifecycle.run(
                lambda _stop_event: preview_runtime.prime_musetalk_preview_frame(
                    payload.get("playback_state") or {},
                    runtime_config=payload.get("runtime_config") or {},
                    list_png_frames=runtime_files.list_png_frames,
                    musetalk_state_module=musetalk_state,
                )
            )
        if capability == "runtime.preview.estimate_displayed_frames":
            from addons.musetalk_avatar import preview_runtime

            return preview_runtime.estimate_displayed_musetalk_frames(
                payload.get("state") or {},
                payload.get("now"),
                runtime_config=payload.get("runtime_config") or {},
            )
        if capability == "runtime.preview.current_source_index":
            from addons.musetalk_avatar import preview_runtime, state as musetalk_state

            return preview_runtime.get_current_musetalk_source_index(
                payload.get("state"),
                runtime_config=payload.get("runtime_config") or {},
                musetalk_state_module=musetalk_state,
                advance_to_next_frame=bool(payload.get("advance_to_next_frame", False)),
                now=payload.get("now"),
            )
        if capability == "runtime.preview.current_state":
            from addons.musetalk_avatar import state as musetalk_state

            return dict(getattr(musetalk_state, "current_musetalk_frame_data", {}) or {})
        if capability == "runtime.preview.reset_zoom":
            return bool(self._musetalk_ui_service.reset_preview_zoom())
        if capability == "runtime.preview.toggle_focus":
            return self._musetalk_ui_service.toggle_avatar_focus()
        if capability == "runtime.preview.set_state":
            from addons.musetalk_avatar import state as musetalk_state

            if payload.get("persist") is False:
                return musetalk_state.update_musetalk_audio_clock(dict(payload.get("state") or {}))
            musetalk_state.set_current_musetalk_frame_data(dict(payload.get("state") or {}))
            return True
        if capability == "runtime.preview.write_frame":
            from addons.musetalk_avatar import state as musetalk_state

            musetalk_state.write_musetalk_preview_frame(
                dict(payload.get("frame") or {})
            )
            return True
        if capability == "runtime.pipeline.reset":
            from addons.musetalk_avatar import state as musetalk_state

            musetalk_state.reset_musetalk_pipeline_data()
            return True
        if capability == "runtime.pipeline.begin":
            from addons.musetalk_avatar import state as musetalk_state

            return musetalk_state.begin_musetalk_pipeline_reply(
                stream_mode=bool(payload.get("stream_mode", False))
            )
        if capability == "runtime.pipeline.update_chunk":
            from addons.musetalk_avatar import state as musetalk_state

            return musetalk_state.update_musetalk_pipeline_chunk(
                payload.get("sequence_index", 0),
                reply_id=payload.get("reply_id"),
                **dict(payload.get("updates") or {}),
            )
        if capability == "runtime.pipeline.update_flags":
            from addons.musetalk_avatar import state as musetalk_state

            return musetalk_state.update_musetalk_pipeline_flags(
                reply_id=payload.get("reply_id"),
                **dict(payload.get("updates") or {}),
            )
        if capability == "runtime.pipeline_snapshot":
            from addons.musetalk_avatar import state as musetalk_state

            return musetalk_state.get_musetalk_pipeline_snapshot()
        if capability == "runtime.preview.append_log":
            from addons.musetalk_avatar import state as musetalk_state

            musetalk_state.append_musetalk_preview_log(str(payload.get("message") or ""))
            return True
        if capability == "runtime.available_pack_emotion_names":
            from addons.musetalk_avatar import pack_runtime

            return pack_runtime.available_pack_emotion_names(
                payload.get("runtime_config") or {},
                default_names=set(payload.get("default_names") or []),
                avatar_profile=payload.get("avatar_profile") or {},
                legacy_map=payload.get("legacy_map") or {},
                legacy_transitions=payload.get("legacy_transitions") or {},
                avatars_dir=payload.get("avatars_dir"),
            )
        if capability == "runtime.pack_catalog":
            from addons.musetalk_avatar import pack_runtime

            return pack_runtime.pack_catalog(
                payload.get("runtime_config") or {},
                legacy_map=payload.get("legacy_map") or {},
                legacy_transitions=payload.get("legacy_transitions") or {},
                packs_dir=Path(self.context.app_root) / "avatar_packs",
            )
        if capability == "runtime.select_pack":
            from addons.musetalk_avatar import pack_runtime

            return pack_runtime.select_pack(
                payload.get("runtime_config") or {},
                payload.get("requested_pack_id"),
                legacy_map=payload.get("legacy_map") or {},
                legacy_transitions=payload.get("legacy_transitions") or {},
            )
        if capability == "ui.preview_panel_exports":
            return self._musetalk_ui_service.preview_panel_exports()
        return None

    def shutdown(self):
        preview_lifecycle = getattr(self, "_preview_lifecycle", None)
        if preview_lifecycle is not None:
            preview_lifecycle.close()
        avatar_service = getattr(self, "_avatar_service", None)
        if avatar_service is not None:
            try:
                avatar_service.unregister_provider(PROVIDER_ID)
            except Exception:
                pass
        return None

class _CombinedStopEvent:
    def __init__(self, owner_stop, caller_stop):
        self._owner_stop = owner_stop
        self._caller_stop = caller_stop

    def is_set(self):
        return self._owner_stop.is_set() or bool(
            self._caller_stop is not None and self._caller_stop.is_set()
        )

    def wait(self, timeout=None):
        if self.is_set():
            return True
        return self._owner_stop.wait(timeout)


class _PreviewLifecycle:
    def __init__(self, close_timeout_seconds=4.0):
        import threading

        self._condition = threading.Condition()
        self._owner_stop = threading.Event()
        self._close_timeout_seconds = float(close_timeout_seconds)
        self._active = 0
        self._closed = False

    def run(self, callback, caller_stop=None):
        with self._condition:
            if self._closed:
                raise RuntimeError("MuseTalk preview lifecycle is closed.")
            self._active += 1
        try:
            return callback(_CombinedStopEvent(self._owner_stop, caller_stop))
        finally:
            with self._condition:
                self._active -= 1
                self._condition.notify_all()

    def close(self):
        with self._condition:
            if self._closed:
                return
            self._closed = True
            self._owner_stop.set()
            self._condition.wait_for(
                lambda: self._active == 0,
                timeout=self._close_timeout_seconds,
            )

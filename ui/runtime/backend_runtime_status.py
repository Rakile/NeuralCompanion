import os

from PySide6 import QtCore

import shared_state as musetalk_state
from core.runtime_status import build_runtime_status_snapshot


def _engine():
    import engine

    return engine


def _runtime_config():
    return getattr(_engine(), "RUNTIME_CONFIG", {})


class BackendRuntimeStatusMixin:
    """Runtime status snapshots, addon event publishing, and live telemetry polling."""

    def _build_status_timer(self):
        self.status_timer = QtCore.QTimer(self)
        self.status_timer.timeout.connect(self._poll_runtime_status)
        self.status_timer.start(120)

    def build_runtime_status_snapshot(self):
        engine = _engine()
        config = dict(_runtime_config() or {})
        try:
            if hasattr(self, "chat_provider_combo"):
                config["chat_provider"] = self._current_chat_provider_value()
            if hasattr(self, "model_combo"):
                config["model_name"] = self.model_combo.currentText()
            if hasattr(self, "tts_backend_combo"):
                config["tts_backend"] = self._current_tts_backend_value()
            if hasattr(self, "engine_combo"):
                config["avatar_mode"] = self._current_avatar_mode_value()
        except Exception:
            pass
        running = bool(getattr(self, "thread", None) and self.thread.is_alive())
        listening = bool(getattr(engine, "listening_active", None) and engine.listening_active.is_set())
        recording = bool(getattr(engine, "microphone_active", None) and engine.microphone_active.is_set())
        paused = bool(getattr(engine, "playback_paused", None) and engine.playback_paused.is_set())
        paused = paused or bool(getattr(engine, "pause_after_chunk", None) and engine.pause_after_chunk.is_set())
        return build_runtime_status_snapshot(
            config,
            running=running,
            engine_connected=running,
            shell_mode=False,
            lifecycle_state="running" if running else "stopped",
            listening=listening,
            recording=recording,
            playback_paused=paused,
            source="qt_app",
        )

    def _build_addon_llm_snapshot(self):
        config = _runtime_config()
        return {
            "chat_provider": self._current_chat_provider_value() if hasattr(self, "chat_provider_combo") else str(config.get("chat_provider", "lmstudio") or "lmstudio"),
            "selected_model": self.model_combo.currentText() if hasattr(self, "model_combo") else "",
            "stream_mode": bool(config.get("stream_mode", False)),
            "input_mode": str(config.get("input_mode", "") or ""),
            "input_role": str(config.get("input_message_role", "") or ""),
            "temperature": float(config.get("temperature", 0.0) or 0.0),
            "top_p": float(config.get("top_p", 0.0) or 0.0),
            "top_k": int(config.get("top_k", 0) or 0),
            "min_p": float(config.get("min_p", 0.0) or 0.0),
            "repeat_penalty": float(config.get("repeat_penalty", 0.0) or 0.0),
        }

    def _build_addon_tts_snapshot(self):
        config = _runtime_config()
        tts_backend = self._current_tts_backend_value()
        tts_status = self._invoke_addon_service_capability(
            "tts_backend_service",
            "runtime.status_snapshot",
            {"backend": self, "runtime_config": config, "tts_backend": tts_backend},
            default={},
            backend_id=tts_backend,
        )
        return {
            "backend": tts_backend,
            "voice_path": str(config.get("voice_path", "") or ""),
            **dict(tts_status or {}),
        }

    def _build_addon_avatar_snapshot(self):
        engine = _engine()
        config = _runtime_config()
        avatar_mode = self._current_avatar_mode_value() if hasattr(self, "engine_combo") else ""
        avatar_status = self._invoke_addon_service_capability(
            "avatar_provider_registry",
            "runtime.status_snapshot",
            {"backend": self, "runtime_config": config, "avatar_mode": avatar_mode},
            default={},
            provider_id=avatar_mode,
        )
        visual_status = self._invoke_addon_capability(
            self._addon_id_for_ui_role("visual_reply", fallback=""),
            "runtime.status_snapshot",
            {"backend": self, "runtime_config": config},
            default={},
        )
        return {
            "engine": avatar_mode,
            **dict(avatar_status or {}),
            **dict(visual_status or {}),
            "sensory_feedback_source": self._sensory_feedback_source_value_from_label(self.sensory_feedback_source_combo.currentText()) if hasattr(self, "sensory_feedback_source_combo") else str(config.get("sensory_feedback_source", "off") or "off"),
            "sensory_feedback_interval_seconds": float(self.sensory_feedback_interval_spin.value()) if hasattr(self, "sensory_feedback_interval_spin") else float(config.get("sensory_feedback_interval_seconds", 7.0) or 7.0),
            "sensory_pingpong_enabled": bool(self.sensory_pingpong_checkbox.isChecked()) if hasattr(self, "sensory_pingpong_checkbox") else bool(config.get("sensory_pingpong_enabled", False)),
            "sensory_allow_hidden_proactive_speech": bool(self.sensory_allow_hidden_proactive_checkbox.isChecked()) if hasattr(self, "sensory_allow_hidden_proactive_checkbox") else bool(config.get("sensory_allow_hidden_proactive_speech", False)),
            "sensory_allow_hidden_visual_generation": bool(self.sensory_allow_hidden_visual_checkbox.isChecked()) if hasattr(self, "sensory_allow_hidden_visual_checkbox") else bool(config.get("sensory_allow_hidden_visual_generation", False)),
            "sensory_pingpong_history_depth": int(self.sensory_pingpong_history_spin.value()) if hasattr(self, "sensory_pingpong_history_spin") else int(config.get("sensory_pingpong_history_depth", 3) or 3),
            "sensory_pingpong_prompt": self.sensory_pingpong_prompt_text.toPlainText().strip() if hasattr(self, "sensory_pingpong_prompt_text") else str(config.get("sensory_pingpong_prompt", getattr(engine, "DEFAULT_SENSORY_PINGPONG_PROMPT", "")) or getattr(engine, "DEFAULT_SENSORY_PINGPONG_PROMPT", "")),
            "sensory_pingpong_source_prompts": self._current_sensory_pingpong_source_prompt_map() if hasattr(self, "_current_sensory_pingpong_source_prompt_map") else dict(config.get("sensory_pingpong_source_prompts", {}) or {}),
            "sensory_provider_metadata_overrides": self._current_sensory_provider_metadata_override_map() if hasattr(self, "_current_sensory_provider_metadata_override_map") else dict(config.get("sensory_provider_metadata_overrides", {}) or {}),
            "detected_gpu_vram_gib": self._detected_gpu_vram_gib(),
        }

    def _status_diode_style(self, active, active_fill, active_border):
        if active:
            return (
                f"background: {active_fill}; border: 1px solid {active_border}; border-radius: 8px;"
            )
        return "background: #4b5563; border: 1px solid #6b7280; border-radius: 8px;"

    def _poll_runtime_status(self):
        runtime_status = self.build_runtime_status_snapshot()
        listening = bool(runtime_status.listening)
        recording = bool(runtime_status.recording)
        if hasattr(self, "listen_diode"):
            self.listen_diode.setStyleSheet(self._status_diode_style(listening, "#39d98a", "#92f0bf"))
        if hasattr(self, "mic_diode"):
            self.mic_diode.setStyleSheet(self._status_diode_style(recording, "#ff4d5e", "#ff96a0"))
        if hasattr(self, "mic_status_label"):
            label = {"recording": "Recording", "listening": "Listening"}.get(runtime_status.microphone_state, "Microphone idle")
            self.mic_status_label.setText(label)
        if hasattr(self, "pipeline_telemetry_widget"):
            pipeline_snapshot = self._build_pipeline_visual_snapshot(
                musetalk_state.get_musetalk_pipeline_snapshot()
            )
            self.pipeline_telemetry_widget.update_snapshot(
                pipeline_snapshot,
                getattr(musetalk_state, "current_musetalk_frame_data", {}) or {},
            )
        paused = bool(runtime_status.playback_paused)
        if paused != self._chat_runtime_border_paused:
            self._chat_runtime_border_paused = paused
            border_style = "border: 2px solid #d84a4a; border-radius: 10px;" if paused else ""
            for widget in (getattr(self, "system_console_tab", None), getattr(self, "chat_tab", None)):
                if widget is not None:
                    widget.setStyleSheet(border_style)
        self._refresh_preset_dirty_state()
        self.refresh_dry_run_status()

    def _count_rendered_chunk_frames(self, frame_dir, use_cache=True):
        frame_dir = str(frame_dir or "").strip()
        if not frame_dir or not os.path.isdir(frame_dir):
            return 0
        try:
            if not use_cache:
                count = 0
                with os.scandir(frame_dir) as entries:
                    for entry in entries:
                        if entry.is_file() and entry.name.lower().endswith(".png"):
                            count += 1
                return count
            stat = os.stat(frame_dir)
            cache_key = os.path.abspath(frame_dir)
            signature = (int(stat.st_mtime_ns), int(stat.st_size))
            cached = self._pipeline_frame_count_cache.get(cache_key)
            if cached and cached.get("signature") == signature:
                return int(cached.get("count", 0) or 0)
            count = 0
            with os.scandir(frame_dir) as entries:
                for entry in entries:
                    if entry.is_file() and entry.name.lower().endswith(".png"):
                        count += 1
            self._pipeline_frame_count_cache[cache_key] = {"signature": signature, "count": count}
            return count
        except Exception:
            return 0

    def _build_pipeline_visual_snapshot(self, snapshot):
        snapshot = dict(snapshot or {})
        chunks = [dict(item or {}) for item in snapshot.get("chunks", [])]
        for chunk in chunks:
            frame_dir = str(chunk.get("frame_dir", "") or "")
            rendered_count = 0
            if frame_dir:
                status = str(chunk.get("status", "") or "")
                rendered_count = self._count_rendered_chunk_frames(
                    frame_dir,
                    use_cache=status not in {"rendering"},
                )
            chunk["rendered_frame_count"] = rendered_count
            expected = int(chunk.get("expected_frame_count", 0) or 0)
            fps = int(chunk.get("fps", 0) or 0)
            duration = float(chunk.get("duration_seconds", 0.0) or 0.0)
            if expected <= 0 and fps > 0 and duration > 0:
                chunk["expected_frame_count"] = max(1, int(round(duration * fps)))
            elif expected <= 0 and rendered_count > 0 and str(chunk.get("status", "") or "") in {"rendered", "ready", "playing", "completed"}:
                chunk["expected_frame_count"] = rendered_count
        snapshot["chunks"] = chunks
        return snapshot

    def _publish_addon_event(self, event_name, payload=None):
        manager = getattr(self, "_addon_manager", None)
        if manager is None:
            return
        try:
            manager.publish_event(str(event_name), dict(payload or {}))
        except Exception as exc:
            print(f"⚠️ [Addons] Event publish failed for {event_name}: {exc}")

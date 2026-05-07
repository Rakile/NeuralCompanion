import time

from PySide6 import QtWidgets

import dry_run
import shared_state
from addons.musetalk_avatar import real_ui_bridge as musetalk_real_ui_bridge
from addons.visual_reply import real_ui_bridge as visual_reply_real_ui_bridge
from ui.panels.input_dialog import QtInputDialog


DRY_RUN_MAX_RESPONSE_TOKENS = 600
PERFORMANCE_PROFILE_APPLY_KEYS = {
    "avatar_mode",
    "stream_mode",
    "tts_backend",
    "model_name",
    "chunk_target_chars",
    "chunk_max_chars",
    "stream_chunk_target_chars",
    "stream_chunk_max_chars",
    "stream_first_chunk_min_chars",
    "stream_force_flush_seconds",
    "stream_force_flush_later_seconds",
}.union(musetalk_real_ui_bridge.performance_profile_apply_keys())


def _runtime_config():
    import engine

    return engine.RUNTIME_CONFIG


def _update_runtime_config(key, value):
    from engine import update_runtime_config

    return update_runtime_config(key, value)


class BackendDryRunRuntimeMixin:
    """Dry Run sessions and performance/chunking profile management."""

    def _dry_run_is_active(self):
        status = dry_run.get_status()
        return bool(status and status.get("active"))

    def _toggle_performance_guidance(self, checked):
        if hasattr(self, "guidance_box"):
            self.guidance_box.setVisible(bool(checked))
        if hasattr(self, "performance_guidance_toggle"):
            self.performance_guidance_toggle.setText(
                "Hide Performance Guidance" if checked else "Show Performance Guidance"
            )
        self._sync_host_settings_tabs_height()

    def start_dry_run_session(self):
        self._publish_addon_event("runtime.heavy_task_starting", {"source": "dry_run"})
        status = dry_run.start_session(
            _runtime_config(),
            target_samples=self.dry_run_target_spin.value(),
            label=f"{self.engine_combo.currentText()} / {self.tts_backend_combo.currentText()} / {'Stream' if self.stream_mode_combo.currentText() == 'On' else 'Non-stream'}",
            auto_replies=self.dry_run_auto_replies_checkbox.isChecked(),
        )
        _update_runtime_config("limit_response_length", True)
        _update_runtime_config("max_response_tokens", DRY_RUN_MAX_RESPONSE_TOKENS)
        dry_run.log_event(
            "[DryRun] Brain snapshot "
            f"preset={self.preset_combo.currentText()} "
            f"model={self.model_combo.currentText()} "
            f"temperature={self.brain_sliders['temperature'].value()} "
            f"top_p={self.brain_sliders['top_p'].value()} "
            f"top_k={int(self.brain_sliders['top_k'].value())} "
            f"repeat_penalty={self.brain_sliders['repeat_penalty'].value()} "
            f"min_p={self.brain_sliders['min_p'].value()} "
            f"user_limit_response_length={self.limit_response_checkbox.isChecked()} "
            f"user_max_response_tokens={int(self.max_response_tokens_spin.value())} "
            f"dry_run_limit_response_length=True "
            f"dry_run_max_response_tokens={DRY_RUN_MAX_RESPONSE_TOKENS} "
            f"system_prompt={self.system_prompt_text.toPlainText().strip()[:220]!r} "
            f"emotional_instructions={self.emotional_text.toPlainText().strip()[:220]!r}"
        )
        shared_state.append_musetalk_preview_log(
            f"🧪 [DryRun] Session armed: id={status.get('session_id')} profile={status.get('profile_key')} target_samples={status.get('target_samples')} max_tokens={DRY_RUN_MAX_RESPONSE_TOKENS}"
        )
        if bool(status.get("auto_mode")):
            print("[QtGUI] Dry Run armed in auto mode.")
        else:
            print(f"[QtGUI] Dry Run armed for {status.get('target_samples')} reply sample(s).")
        self.emit_tutorial_event("dry_run_started", {"session_id": status.get("session_id"), "auto_mode": bool(status.get("auto_mode"))})
        self._apply_dry_run_candidate_settings()
        self.refresh_dry_run_status()

    def stop_dry_run_session(self):
        status = dry_run.stop_session(reason="manual_stop")
        if status:
            self.dry_run_last_applied_candidate_index = None
            self._apply_runtime_settings_dict(status.get("config_snapshot", {}) or {})
            self.save_session()
            shared_state.append_musetalk_preview_log(
                f"🧪 [DryRun] Session stopped: id={status.get('session_id')} confidence={status.get('confidence')}"
            )
            print("[QtGUI] Dry Run stopped.")
            self.emit_tutorial_event("dry_run_stopped", {"session_id": status.get("session_id"), "confidence": status.get("confidence")})
        self.refresh_dry_run_status()

    def apply_dry_run_recommendation(self):
        if not self.dry_run_recommended_settings:
            print("[QtGUI] Dry Run has no recommendation to apply yet.")
            return
        settings = dict(self.dry_run_recommended_settings)
        self._apply_runtime_settings_dict(settings)
        self.save_session()
        print("[QtGUI] Dry Run recommendation applied.")
        self.refresh_dry_run_status()

    def refresh_performance_profile_list(self):
        combos = []
        if hasattr(self, "performance_profile_combo"):
            combos.append(self.performance_profile_combo)
        if hasattr(self, "chunking_profile_combo"):
            combos.append(self.chunking_profile_combo)
        if not combos:
            return
        profiles = dry_run.list_performance_profiles()
        preferred_name = ""
        for combo in combos:
            data = combo.currentData()
            if data:
                preferred_name = str(data)
                break
        for combo in combos:
            combo.blockSignals(True)
            combo.clear()
            if not profiles:
                combo.addItem("No Saved Profiles")
            else:
                for item in profiles:
                    name = str(item.get("display_name") or item["name"])
                    prefix = "Recommended: " if item.get("recommended") else ("Starter: " if item.get("bundled") else "")
                    label = (
                        f"{prefix}{name} | "
                        f"{'Stream' if item.get('stream_mode') else 'Non-stream'} | "
                        f"{str(item.get('tts_backend') or '').title()} | "
                        f"{musetalk_real_ui_bridge.performance_profile_label_fragment(item)} | "
                        f"c={float(item.get('confidence', 0.0) or 0.0):.2f}"
                    )
                    combo.addItem(label, item["name"])
                target_index = 0
                if preferred_name:
                    for index in range(combo.count()):
                        if combo.itemData(index) == preferred_name:
                            target_index = index
                            break
                combo.setCurrentIndex(target_index)
            combo.blockSignals(False)
        has_profiles = bool(profiles)
        if hasattr(self, "btn_profile_load"):
            self.btn_profile_load.setEnabled(has_profiles)
        if hasattr(self, "btn_profile_delete"):
            self.btn_profile_delete.setEnabled(has_profiles)
        if hasattr(self, "btn_chunking_profile_load"):
            self.btn_chunking_profile_load.setEnabled(has_profiles)
        if hasattr(self, "btn_chunking_profile_delete"):
            self.btn_chunking_profile_delete.setEnabled(has_profiles)

    def _get_selected_performance_profile_name(self, source="dry_run"):
        if source == "chunking":
            combo = getattr(self, "chunking_profile_combo", None)
        else:
            combo = getattr(self, "performance_profile_combo", None)
        if combo is None:
            return ""
        return str(combo.currentData() or "").strip()

    def _build_current_performance_override(self, include_chunking=True):
        config = _runtime_config()
        override = {
            "avatar_mode": self._current_avatar_mode_value(),
            "stream_mode": self.stream_mode_combo.currentText() == "On",
            "tts_backend": self._current_tts_backend_value(),
            "model_name": self.model_combo.currentText(),
            "temperature": self.brain_sliders["temperature"].value(),
            "top_p": self.brain_sliders["top_p"].value(),
            "top_k": int(self.brain_sliders["top_k"].value()),
            "repeat_penalty": self.brain_sliders["repeat_penalty"].value(),
            "min_p": self.brain_sliders["min_p"].value(),
            "limit_response_length": self.limit_response_checkbox.isChecked(),
            "max_response_tokens": int(self.max_response_tokens_spin.value()),
        }
        musetalk_real_ui_bridge.add_performance_override(self, override, config)
        if include_chunking:
            override.update({key: slider.value() for key, slider in self.chunking_sliders.items()})
        return override

    def save_latest_performance_profile(self):
        latest = dry_run.get_latest_profile()
        if not latest:
            print("[QtGUI] No completed Dry Run profile is available to save.")
            return
        suggested = dry_run.suggest_profile_name(latest)
        name = QtInputDialog.get_text("Save Performance Profile", "Enter Profile Name:", self) or suggested
        name = str(name or "").strip()
        if not name:
            print("[QtGUI] Performance profile save cancelled.")
            return
        current_override = self._build_current_performance_override(include_chunking=False)
        dry_run.save_named_performance_profile(name, latest, settings_override=current_override)
        print(f"[QtGUI] Saved performance profile: {name}")
        self.refresh_performance_profile_list()

    def load_selected_performance_profile(self):
        name = self._get_selected_performance_profile_name("dry_run")
        if not name:
            print("[QtGUI] No performance profile selected.")
            return
        self.load_performance_profile_by_id(name)

    def delete_selected_performance_profile(self):
        name = self._get_selected_performance_profile_name("dry_run")
        if not name:
            return
        if QtWidgets.QMessageBox.question(self, "Delete Performance Profile", f"Delete '{name}'?") != QtWidgets.QMessageBox.Yes:
            return
        if dry_run.delete_performance_profile(name):
            print(f"[QtGUI] Deleted performance profile: {name}")
        self.refresh_performance_profile_list()

    def save_current_chunking_profile(self):
        source_name = self._get_selected_performance_profile_name("chunking")
        source_profile = dry_run.load_performance_profile(source_name) if source_name else dry_run.get_latest_profile()
        suggested = dry_run.suggest_profile_name(source_profile or {"profile_key": "manual_chunking", "config_snapshot": self._build_current_performance_override(include_chunking=True)})
        name = QtInputDialog.get_text("Save Chunking Profile", "Enter Profile Name:", self) or suggested
        name = str(name or "").strip()
        if not name:
            print("[QtGUI] Chunking profile save cancelled.")
            return
        if not source_profile:
            source_profile = {
                "profile_key": "manual_chunking",
                "hardware": {},
                "updated_at": time.time(),
                "sample_count": 0,
                "confidence": 0.0,
                "stability": 0.0,
                "completion_reason": "manual_save",
                "config_snapshot": self._build_current_performance_override(include_chunking=True),
                "recommendation": {},
                "summary": {},
            }
        current_override = self._build_current_performance_override(include_chunking=True)
        dry_run.save_named_performance_profile(name, source_profile=source_profile, settings_override=current_override)
        print(f"[QtGUI] Saved chunking profile: {name}")
        self.refresh_performance_profile_list()

    def load_selected_chunking_profile(self):
        name = self._get_selected_performance_profile_name("chunking")
        if not name:
            print("[QtGUI] No performance profile selected.")
            return
        self.load_performance_profile_by_id(name)

    def delete_selected_chunking_profile(self):
        name = self._get_selected_performance_profile_name("chunking")
        if not name:
            return
        if QtWidgets.QMessageBox.question(self, "Delete Performance Profile", f"Delete '{name}'?") != QtWidgets.QMessageBox.Yes:
            return
        if dry_run.delete_performance_profile(name):
            print(f"[QtGUI] Deleted performance profile: {name}")
        self.refresh_performance_profile_list()

    def load_performance_profile_by_id(self, name):
        if not name:
            return False
        payload = dry_run.load_performance_profile(name)
        if not payload:
            print(f"[QtGUI] Could not load performance profile: {name}")
            return False
        for combo_name in ("performance_profile_combo", "chunking_profile_combo"):
            combo = getattr(self, combo_name, None)
            if combo is None:
                continue
            for index in range(combo.count()):
                if combo.itemData(index) == name:
                    combo.setCurrentIndex(index)
                    break
        raw_settings = dict(payload.get("settings_to_apply") or {})
        settings = {key: value for key, value in raw_settings.items() if key in PERFORMANCE_PROFILE_APPLY_KEYS}
        self._apply_runtime_settings_dict(settings)
        self.save_session()
        print(f"[QtGUI] Loaded performance profile: {name}")
        self.emit_tutorial_event("performance_profile_loaded", {"name": name})
        self.refresh_dry_run_status()
        return True

    def _apply_runtime_settings_dict(self, settings):
        config = _runtime_config()
        for key, value in settings.items():
            _update_runtime_config(key, value)
            if key in self.chunking_sliders:
                self.chunking_sliders[key].set_value(value)
        if "tts_backend" in settings and hasattr(self, "tts_backend_combo"):
            desired_backend = str(settings["tts_backend"] or "").strip().lower()
            self._populate_tts_backend_combo(selected_value=desired_backend)
            index = self.tts_backend_combo.findData(desired_backend)
            if index >= 0:
                self.tts_backend_combo.setCurrentIndex(index)
            self.on_tts_backend_change(self.tts_backend_combo.currentText())
        if "stream_mode" in settings:
            self.stream_mode_combo.setCurrentText("On" if bool(settings["stream_mode"]) else "Off")
        musetalk_real_ui_bridge.apply_runtime_settings(self, settings)
        visual_reply_real_ui_bridge.apply_runtime_settings(self, settings)
        if "sensory_feedback_source" in settings and hasattr(self, "sensory_feedback_source_combo"):
            source_value = str(settings["sensory_feedback_source"] or "off")
            self.refresh_sensory_feedback_source_options(selected_value=source_value)
            self.on_sensory_feedback_source_changed(source_value)
        if "sensory_feedback_interval_seconds" in settings and hasattr(self, "sensory_feedback_interval_spin"):
            interval_seconds = max(2.0, float(settings["sensory_feedback_interval_seconds"] or 7.0))
            self.sensory_feedback_interval_spin.setValue(interval_seconds)
            self.on_sensory_feedback_interval_changed(interval_seconds)

    def _apply_dry_run_candidate_settings(self):
        candidate = dry_run.get_current_candidate_settings()
        if not candidate:
            return
        candidate_index = candidate.get("index")
        if candidate_index == self.dry_run_last_applied_candidate_index:
            return
        settings = candidate.get("settings") or {}
        self._apply_runtime_settings_dict(settings)
        self.dry_run_last_applied_candidate_index = candidate_index
        self.save_session()
        dry_run.log_event(
            "[DryRun] Applying candidate "
            f"label={candidate.get('label')} "
            f"stream_target={settings.get('stream_chunk_target_chars')} "
            f"stream_max={settings.get('stream_chunk_max_chars')} "
            f"first_min={settings.get('stream_first_chunk_min_chars')} "
            f"flush={settings.get('stream_force_flush_seconds')}/{settings.get('stream_force_flush_later_seconds')} "
            f"{musetalk_real_ui_bridge.performance_candidate_log_fragment(settings)}"
        )
        shared_state.append_musetalk_preview_log(
            f"🧪 [DryRun] Applying {candidate.get('label')}: "
            f"stream_target={settings.get('stream_chunk_target_chars')} "
            f"stream_max={settings.get('stream_chunk_max_chars')} "
            f"first_min={settings.get('stream_first_chunk_min_chars')} "
            f"flush={settings.get('stream_force_flush_seconds')}/{settings.get('stream_force_flush_later_seconds')} "
            f"{musetalk_real_ui_bridge.performance_candidate_log_fragment(settings)}"
        )

    def refresh_dry_run_status(self):
        if not hasattr(self, "dry_run_status_label"):
            return
        status = dry_run.get_status()
        self.dry_run_recommended_settings = {}
        if not status:
            self.dry_run_last_applied_candidate_index = None
            latest = dry_run.get_latest_profile()
            self.btn_dry_run_start.setEnabled(True)
            self.btn_dry_run_stop.setEnabled(False)
            self.btn_dry_run_apply.setEnabled(bool(latest and (latest.get("recommendation") or {}).get("settings")))
            self._update_control_action_buttons()
            if latest:
                recommendation = latest.get("recommendation", {}) or {}
                self.dry_run_recommended_settings = dict(recommendation.get("settings") or {})
                summary = latest.get("summary", {}) or {}
                self.dry_run_status_label.setText(
                    f"Dry Run idle. Last profile confidence {float(latest.get('confidence', 0.0) or 0.0):.2f}, stability {float(latest.get('stability', 0.0) or 0.0):.2f}."
                )
                self._update_readonly_text_safely(
                    self.dry_run_summary,
                    self._format_dry_run_summary(summary, recommendation, latest.get("completion_reason", ""), latest.get("stability"))
                )
            else:
                self.dry_run_status_label.setText("Dry Run idle.")
                self._update_readonly_text_safely(
                    self.dry_run_summary,
                    "Arm a Dry Run to collect reply samples and generate machine-specific recommendations.",
                )
            return

        recommendation = status.get("recommendation", {}) or {}
        self.dry_run_recommended_settings = dict(recommendation.get("settings") or {})
        observations = status.get("observations", []) or []
        sample_count = len(observations)
        target = int(status.get("target_samples", self.dry_run_target_spin.value()) or self.dry_run_target_spin.value())
        auto_mode = bool(status.get("auto_mode"))
        auto_replies = bool(status.get("auto_replies"))
        confidence = float(status.get("confidence", 0.0) or 0.0)
        stability = float(status.get("stability", 0.0) or 0.0)
        candidate_plan = status.get("candidate_plan", []) or []
        active_candidate_index = int(status.get("active_candidate_index", 0) or 0)
        candidate_label = ""
        if candidate_plan:
            candidate_index = max(0, min(active_candidate_index, len(candidate_plan) - 1))
            candidate_label = str((candidate_plan[candidate_index] or {}).get("label") or f"Candidate {candidate_index + 1}")
        state_text = "complete" if status.get("complete") else ("running" if status.get("active") else "idle")
        sample_text = f"{sample_count} samples" if auto_mode else f"{sample_count}/{target} samples"
        self.dry_run_status_label.setText(
            f"Dry Run {state_text}: {sample_text}, confidence {confidence:.2f}, stability {stability:.2f}"
            + (f" ({candidate_label})" if candidate_label and not status.get("complete") else "")
            + (" | hands-free" if auto_replies else "")
        )
        self.btn_dry_run_start.setEnabled(not status.get("active"))
        self.btn_dry_run_stop.setEnabled(bool(status.get("active")))
        self.btn_dry_run_apply.setEnabled(bool(self.dry_run_recommended_settings))
        self._update_control_action_buttons()
        self._update_readonly_text_safely(
            self.dry_run_summary,
            self._format_dry_run_summary(
                dry_run.summarize_observations(observations),
                recommendation,
                status.get("completion_reason", ""),
                stability,
            )
        )
        if status.get("active") and not status.get("complete"):
            self._apply_dry_run_candidate_settings()
        elif status.get("complete") and status.get("active"):
            final_status = dry_run.stop_session(reason="complete")
            if final_status:
                self.dry_run_last_applied_candidate_index = None
                self._apply_runtime_settings_dict(final_status.get("config_snapshot", {}) or {})
                self.save_session()
                self.emit_tutorial_event(
                    "dry_run_completed",
                    {
                        "session_id": final_status.get("session_id"),
                        "confidence": final_status.get("confidence"),
                        "stability": final_status.get("stability"),
                        "reason": final_status.get("completion_reason", ""),
                    },
                )
                if self.thread and self.thread.is_alive():
                    print("[QtGUI] Dry Run complete. Terminating active session...")
                    self.stop_engine()
            self.refresh_dry_run_status()

    def _format_dry_run_summary(self, summary, recommendation, completion_reason="", stability=None):
        summary = summary or {}
        recommendation = recommendation or {}
        settings = recommendation.get("settings", {}) or {}
        lines = [
            "Measured startup profile:",
            f"- Avg first audio chunk: {self._fmt_ms(summary.get('avg_first_audio_chunk_ms'))}",
            f"- Avg first visual buffer wait: {self._fmt_ms(summary.get('avg_buffer_wait_ms'))}",
            f"- Avg first chunk audio start: {self._fmt_ms(summary.get('avg_audio_start_ms'))}",
            f"- Avg first chunk render ready: {self._fmt_ms(summary.get('avg_render_ready_ms'))}",
            f"- Avg first chunk ms/frame: {self._fmt_ms(summary.get('avg_spf_ms'))}",
            f"- Avg plan sync wait: {self._fmt_ms(summary.get('avg_plan_sync_ms'))}",
            f"- Avg idle sync wait: {self._fmt_ms(summary.get('avg_idle_sync_ms'))}",
            f"- Avg chunk quality: {self._fmt_ratio(summary.get('avg_chunk_quality'))}",
            f"- Avg emitted chunk chars: {self._fmt_num(summary.get('avg_chunk_chars'))}",
        ]
        if stability is not None:
            lines.append(f"- Stability: {float(stability):.2f}")
        lines.extend([
            "",
            "Recommended settings:",
        ])
        for key in [
            "tts_backend",
            "stream_chunk_target_chars",
            "stream_chunk_max_chars",
            "stream_first_chunk_min_chars",
            "stream_force_flush_seconds",
            "stream_force_flush_later_seconds",
        ] + musetalk_real_ui_bridge.performance_summary_setting_keys():
            if key in settings:
                lines.append(f"- {key}: {settings[key]}")
        notes = recommendation.get("notes", []) or []
        if notes:
            lines.append("")
            lines.append("Notes:")
            for note in notes:
                lines.append(f"- {note}")
        if completion_reason:
            lines.append(f"- Completion reason: {completion_reason}")
        return "\n".join(lines)

    def _fmt_ms(self, value):
        if value is None:
            return "n/a"
        return f"{float(value):.1f} ms"

    def _fmt_ratio(self, value):
        if value is None:
            return "n/a"
        return f"{float(value):.2f}"

    def _fmt_num(self, value):
        if value is None:
            return "n/a"
        return f"{float(value):.1f}"

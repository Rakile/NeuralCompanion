from PySide6 import QtCore, QtWidgets

from addons.musetalk_avatar import real_ui_bridge as musetalk_real_ui_bridge
import dry_run
import tutorial_framework


class BackendTutorialRuntimeMixin:
    """Tutorial list, overlay lifecycle, and tutorial runtime-state helpers."""

    def emit_tutorial_event(self, event_name, payload=None):
        if not hasattr(self, "tutorial_event_bus") or self.tutorial_event_bus is None:
            return
        try:
            self.tutorial_event_bus.emit_event(str(event_name or ""), payload or {})
        except Exception:
            pass

    def _tutorial_last_error_text(self):
        if not hasattr(self, "console_edit"):
            return ""
        lines = [line.strip() for line in self.console_edit.toPlainText().splitlines() if line.strip()]
        error_lines = [
            line for line in lines[-120:]
            if any(marker in line for marker in ("ERROR", "Error", "Failed", "CRITICAL", "Traceback", "✗", "Exception"))
        ]
        return error_lines[-1] if error_lines else ""

    def get_tutorial_runtime_state(self):
        return {
            "lm_studio_running": bool(getattr(self, "_tutorial_lm_studio_running", False)),
            "model_loaded": self._tutorial_model_loaded(),
            "engine_running": bool(self.thread and self.thread.is_alive()),
            "avatar_mode": self._current_avatar_mode_value() if hasattr(self, "engine_combo") else "",
            "stream_mode": self.stream_mode_combo.currentText() if hasattr(self, "stream_mode_combo") else "",
            "tts_backend": self._current_tts_backend_value(),
            **musetalk_real_ui_bridge.build_tutorial_state(self),
            "preview_visible": bool(hasattr(self, "preview_dock") and self.preview_dock.isVisible()),
            "dry_run_active": bool((dry_run.get_status() or {}).get("active")),
            "dry_run_complete": bool((dry_run.get_status() or {}).get("complete")),
            "performance_profile": self.performance_profile_combo.currentData() if hasattr(self, "performance_profile_combo") else "",
            "active_preset": self.preset_combo.currentText() if hasattr(self, "preset_combo") else "",
            "last_error_text": self._tutorial_last_error_text(),
        }

    def apply_safe_tutorial_defaults(self):
        if hasattr(self, "engine_combo"):
            self.engine_combo.setCurrentText("MuseTalk")
        if hasattr(self, "stream_mode_combo"):
            self.stream_mode_combo.setCurrentText("On")
        musetalk_real_ui_bridge.apply_safe_tutorial_defaults(self)
        if hasattr(self, "tts_backend_combo"):
            self._populate_tts_backend_combo(selected_value="chatterbox")
            index = self.tts_backend_combo.findData("chatterbox")
            if index >= 0:
                self.tts_backend_combo.setCurrentIndex(index)
        self.save_session()
        print("[QtGUI] Applied safe tutorial defaults.")
        self.emit_tutorial_event("safe_defaults_applied", self.get_tutorial_runtime_state())

    def refresh_tutorial_list(self):
        if not hasattr(self, "tutorials_list"):
            return
        tutorials = tutorial_framework.list_tutorials()
        self.tutorials_list.clear()
        for item in tutorials:
            label = f"{item['title']} ({item['step_count']} steps)"
            list_item = QtWidgets.QListWidgetItem(label)
            list_item.setData(QtCore.Qt.UserRole, item["id"])
            list_item.setToolTip(item.get("description", ""))
            self.tutorials_list.addItem(list_item)
        if tutorials:
            self.tutorials_list.setCurrentRow(0)
            self.btn_tutorial_start.setEnabled(True)
        else:
            self.tutorial_description.setPlainText("No tutorials found in the tutorials folder.")
            self.btn_tutorial_start.setEnabled(False)

    def on_tutorial_selection_changed(self, row):
        if row < 0 or not hasattr(self, "tutorials_list"):
            if hasattr(self, "tutorial_description"):
                self.tutorial_description.clear()
            return
        item = self.tutorials_list.item(row)
        tutorial_id = item.data(QtCore.Qt.UserRole) if item else ""
        payload = tutorial_framework.load_tutorial(tutorial_id)
        if not payload:
            self.tutorial_description.setPlainText("Could not load the selected tutorial.")
            return
        text = (
            f"{payload.get('title', tutorial_id)}\n\n"
            f"{payload.get('description', '')}\n\n"
            f"Steps: {len(payload.get('steps') or [])}"
        )
        self.tutorial_description.setPlainText(text.strip())

    def start_selected_tutorial(self):
        if not hasattr(self, "tutorials_list") or self.tutorials_list.currentRow() < 0:
            print("[QtGUI] No tutorial selected.")
            return
        item = self.tutorials_list.currentItem()
        tutorial_id = item.data(QtCore.Qt.UserRole) if item else ""
        self.start_tutorial(tutorial_id)

    def start_tutorial(self, tutorial_id):
        payload = tutorial_framework.load_tutorial(tutorial_id)
        if not payload:
            print(f"[QtGUI] Could not load tutorial: {tutorial_id}")
            return
        if self.active_tutorial_overlay is not None:
            try:
                self.active_tutorial_overlay.finish("restarted")
            except Exception:
                pass
        self.active_tutorial_overlay = tutorial_framework.TutorialOverlay(self, payload, self)
        self.active_tutorial_overlay.finished.connect(self.on_tutorial_finished)
        self.active_tutorial_overlay.start()
        self.emit_tutorial_event("tutorial_started", {"id": payload.get("id", tutorial_id), "title": payload.get("title", tutorial_id)})
        print(f"[QtGUI] Tutorial started: {payload.get('title', tutorial_id)}")

    def on_tutorial_finished(self, reason):
        if self.active_tutorial_overlay is not None:
            self.active_tutorial_overlay.deleteLater()
            self.active_tutorial_overlay = None
        self.emit_tutorial_event("tutorial_finished", {"reason": reason})
        print(f"[QtGUI] Tutorial finished: {reason}")

    def maybe_prompt_first_run_tutorial(self):
        if not self.first_run:
            return
        self.first_run = False
        self.save_session()
        choice = QtWidgets.QMessageBox.question(
            self,
            "Quick Start Tutorial",
            "Would you like to start the interactive First Run tutorial?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.Yes,
        )
        if choice == QtWidgets.QMessageBox.Yes:
            self.start_tutorial("first_run")

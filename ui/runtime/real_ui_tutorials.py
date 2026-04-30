from PySide6 import QtCore, QtWidgets


def configure_real_ui_tutorial_dependencies(namespace):
    """Inject tutorial framework globals used by the extracted real-UI tutorial mixin."""
    globals().update(dict(namespace or {}))


class MainUiRealTutorialMixin:
    """Tutorial list, description, and overlay controls for the runtime-backed main.ui bridge."""

    def _selected_frontend_tutorial_id(self):
            tutorials_list = self._ui_object("tutorials_list")
            if tutorials_list is None or not hasattr(tutorials_list, "currentItem"):
                return ""
            item = tutorials_list.currentItem()
            if item is None:
                return ""
            try:
                return str(item.data(QtCore.Qt.UserRole) or "").strip()
            except Exception:
                return ""

    def _refresh_tutorials_from_ui_real(self):
            tutorials_list = self._ui_object("tutorials_list")
            description = self._ui_object("tutorial_description")
            start_button = self._ui_object("btn_tutorial_start")
            try:
                tutorials = list(tutorial_framework.list_tutorials() or [])
            except Exception:
                tutorials = []
            if tutorials_list is not None and hasattr(tutorials_list, "clear"):
                was_blocked = False
                try:
                    was_blocked = bool(tutorials_list.blockSignals(True))
                    tutorials_list.clear()
                    for item in tutorials:
                        label = f"{item.get('title', item.get('id', 'Tutorial'))} ({int(item.get('step_count', 0) or 0)} steps)"
                        list_item = QtWidgets.QListWidgetItem(label)
                        list_item.setData(QtCore.Qt.UserRole, str(item.get("id") or ""))
                        list_item.setToolTip(str(item.get("description") or ""))
                        tutorials_list.addItem(list_item)
                    if tutorials:
                        tutorials_list.setCurrentRow(0)
                finally:
                    try:
                        tutorials_list.blockSignals(was_blocked)
                    except Exception:
                        pass
            if start_button is not None and hasattr(start_button, "setEnabled"):
                try:
                    start_button.setEnabled(bool(tutorials))
                except Exception:
                    pass
            if not tutorials and description is not None and hasattr(description, "setPlainText"):
                description.setPlainText("No tutorials found in the tutorials folder.")
            self._render_frontend_tutorial_description()

    def _render_frontend_tutorial_description(self):
            description = self._ui_object("tutorial_description")
            if description is None or not hasattr(description, "setPlainText"):
                return
            tutorial_id = self._selected_frontend_tutorial_id()
            if not tutorial_id:
                description.setPlainText("Select a tutorial to see its description.")
                return
            try:
                payload = tutorial_framework.load_tutorial(tutorial_id) or {}
            except Exception:
                payload = {}
            if not payload:
                description.setPlainText("Could not load the selected tutorial.")
                return
            text = (
                f"{payload.get('title', tutorial_id)}\n\n"
                f"{payload.get('description', '')}\n\n"
                f"Steps: {len(payload.get('steps') or [])}"
            )
            description.setPlainText(text.strip())

    def _on_frontend_tutorial_selection_changed(self, _row=None):
            self._render_frontend_tutorial_description()

    def _start_selected_tutorial_from_ui_real(self):
            tutorial_id = self._selected_frontend_tutorial_id()
            if not tutorial_id:
                print("[UI Real] No tutorial selected.")
                return
            self._start_tutorial_from_ui_real(tutorial_id)

    def _start_tutorial_from_ui_real(self, tutorial_id):
            try:
                payload = tutorial_framework.load_tutorial(str(tutorial_id or "")) or {}
            except Exception:
                payload = {}
            if not payload:
                print(f"[UI Real] Could not load tutorial: {tutorial_id}")
                return
            overlay = getattr(self, "_frontend_active_tutorial_overlay", None)
            if overlay is not None:
                try:
                    overlay.finish("restarted")
                except Exception:
                    pass
            backend_overlay = getattr(self.backend, "active_tutorial_overlay", None)
            if backend_overlay is not None:
                try:
                    backend_overlay.finish("replaced-by-main-ui")
                except Exception:
                    pass
                try:
                    self.backend.active_tutorial_overlay = None
                except Exception:
                    pass
            self._frontend_active_tutorial_overlay = tutorial_framework.TutorialOverlay(self.window, payload, self.window)
            self._frontend_active_tutorial_overlay.finished.connect(self._on_frontend_tutorial_finished)
            self._frontend_active_tutorial_overlay.start()
            callback = getattr(self.backend, "emit_tutorial_event", None)
            if callable(callback):
                callback("tutorial_started", {"id": payload.get("id", tutorial_id), "title": payload.get("title", tutorial_id)})
            print(f"[UI Real] Tutorial started: {payload.get('title', tutorial_id)}")

    def _on_frontend_tutorial_finished(self, reason):
            overlay = getattr(self, "_frontend_active_tutorial_overlay", None)
            if overlay is not None:
                try:
                    overlay.deleteLater()
                except Exception:
                    pass
            self._frontend_active_tutorial_overlay = None
            callback = getattr(self.backend, "emit_tutorial_event", None)
            if callable(callback):
                callback("tutorial_finished", {"reason": reason})
            print(f"[UI Real] Tutorial finished: {reason}")

    def _apply_safe_tutorial_defaults_from_ui_real(self):
            callback = getattr(self.backend, "apply_safe_tutorial_defaults", None)
            if callable(callback):
                callback()
            self._sync_backend_to_ui(force=True)

    def _load_performance_profile_by_id_from_ui_real(self, profile_id):
            callback = getattr(self.backend, "load_performance_profile_by_id", None)
            if callable(callback):
                callback(str(profile_id or ""))
            self._sync_backend_to_ui(force=True)

    def _load_preset_from_tutorial_ui_real(self):
            self._sync_single_combo_to_backend("preset_combo")
            callback = getattr(self.backend, "load_preset", None)
            if callable(callback):
                callback()
            self._sync_backend_to_ui(force=True)

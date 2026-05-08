"""RealUiSyncCopyMixin extracted from real_ui_sync.py."""

from PySide6 import QtCore, QtGui, QtWidgets


def configure_real_ui_sync_copy_dependencies(namespace):
    globals().update(dict(namespace or {}))


class RealUiSyncCopyMixin:
    def _combo_items_snapshot(self, combo):
            if combo is None or not hasattr(combo, "count"):
                return []
            items = []
            for index in range(combo.count()):
                try:
                    text = str(combo.itemText(index) or "")
                    data = combo.itemData(index) if hasattr(combo, "itemData") else None
                    items.append((text, data))
                except Exception:
                    continue
            return items

    def _copy_combo_state(self, source, target):
            if source is None or target is None or not hasattr(source, "count") or not hasattr(target, "clear"):
                return False
            if self._combo_popup_is_open(target):
                return False
            items = self._combo_items_snapshot(source)
            existing_items = self._combo_items_snapshot(target)
            selected_data = None
            selected_text = ""
            try:
                if hasattr(source, "currentData"):
                    selected_data = source.currentData()
            except Exception:
                selected_data = None
            try:
                selected_text = str(source.currentText() or "").strip()
            except Exception:
                selected_text = ""
            target.blockSignals(True)
            try:
                if existing_items != items:
                    target.clear()
                    for text, data in items:
                        if hasattr(target, "addItem"):
                            target.addItem(text, data)
                applied = False
                if selected_data is not None and hasattr(target, "findData"):
                    try:
                        index = target.findData(selected_data)
                    except Exception:
                        index = -1
                    if index >= 0 and target.currentIndex() != index:
                        target.setCurrentIndex(index)
                    if index >= 0:
                        applied = True
                if not applied and selected_text:
                    try:
                        index = target.findText(selected_text)
                    except Exception:
                        index = -1
                    if index >= 0 and target.currentIndex() != index:
                        target.setCurrentIndex(index)
                    if index >= 0:
                        applied = True
                if not applied and target.count():
                    fallback_index = min(max(source.currentIndex(), 0), target.count() - 1)
                    if target.currentIndex() != fallback_index:
                        target.setCurrentIndex(fallback_index)
            finally:
                target.blockSignals(False)
            return True

    def _copy_text_state(self, source, target):
            if source is None or target is None:
                return False
            if hasattr(source, "toPlainText") and hasattr(target, "setPlainText"):
                text = str(source.toPlainText() or "")
                return self._set_text_widget_text(target, text)
            if hasattr(source, "text") and hasattr(target, "setText"):
                text = str(source.text() or "")
                return self._set_text_widget_text(target, text)
            return False

    def _set_text_widget_text(self, target, text):
            if target is None:
                return False
            value = str(text or "")
            try:
                if hasattr(target, "toPlainText"):
                    current = str(target.toPlainText() or "")
                    if current == value:
                        return True
                    was_blocked = bool(target.blockSignals(True)) if hasattr(target, "blockSignals") else False
                    try:
                        target.setPlainText(value)
                    finally:
                        if hasattr(target, "blockSignals"):
                            target.blockSignals(was_blocked)
                    return True
                if hasattr(target, "text") and hasattr(target, "setText"):
                    current = str(target.text() or "")
                    if current == value:
                        return True
                    was_blocked = bool(target.blockSignals(True)) if hasattr(target, "blockSignals") else False
                    try:
                        target.setText(value)
                    finally:
                        if hasattr(target, "blockSignals"):
                            target.blockSignals(was_blocked)
                    return True
            except Exception:
                return False
            return False

    def _copy_runtime_plain_text_state(self, object_name, config_key):
            front = self._ui_object(object_name)
            back = self._backend_widget(object_name)
            if front is None or back is None:
                return False
            if self._widget_or_child_has_focus(front):
                return False
            text = ""
            try:
                if hasattr(back, "toPlainText"):
                    text = str(back.toPlainText() or "")
            except Exception:
                text = ""
            try:
                runtime_text = str((RUNTIME_CONFIG or {}).get(config_key, "") or "")
            except Exception:
                runtime_text = ""
            designer_placeholders = {
                "emotional_text": "Technical rules / expressive tags",
                "system_prompt_text": "System prompt",
                "sensory_pingpong_prompt_text": "Hidden PING/PONG prompt",
            }
            if text == designer_placeholders.get(str(object_name), "") and runtime_text:
                text = ""
            if not text and runtime_text:
                text = runtime_text
                self._set_text_widget_text(back, text)
            return self._set_text_widget_text(front, text)

    def _copy_checkbox_state(self, source, target):
            if source is None or target is None or not hasattr(source, "isChecked") or not hasattr(target, "setChecked"):
                return False
            try:
                target.blockSignals(True)
                target.setChecked(bool(source.isChecked()))
                return True
            except Exception:
                return False
            finally:
                try:
                    target.blockSignals(False)
                except Exception:
                    pass

    def _copy_spin_state(self, source, target):
            if source is None or target is None or not hasattr(source, "value") or not hasattr(target, "setValue"):
                return False
            try:
                target.blockSignals(True)
                target.setValue(source.value())
                return True
            except Exception:
                return False
            finally:
                try:
                    target.blockSignals(False)
                except Exception:
                    pass

    def _set_readonly_text_if_changed(self, target, text):
            if target is None:
                return False
            value = str(text or "")
            current = ""
            try:
                if hasattr(target, "toPlainText"):
                    current = str(target.toPlainText() or "")
                elif hasattr(target, "text"):
                    current = str(target.text() or "")
            except Exception:
                current = ""
            if current == value:
                return False
            if hasattr(target, "setPlainText") and value.startswith(current):
                suffix = value[len(current):]
                if suffix:
                    try:
                        active_cursor = target.textCursor() if hasattr(target, "textCursor") else None
                        if hasattr(target, "blockSignals"):
                            target.blockSignals(True)
                        cursor = QtGui.QTextCursor(target.document())
                        cursor.movePosition(QtGui.QTextCursor.End)
                        cursor.insertText(suffix)
                        if active_cursor is not None and hasattr(target, "setTextCursor"):
                            target.setTextCursor(active_cursor)
                        return True
                    finally:
                        try:
                            target.blockSignals(False)
                        except Exception:
                            pass
            if hasattr(target, "setPlainText"):
                try:
                    if hasattr(target, "blockSignals"):
                        target.blockSignals(True)
                    target.setPlainText(value)
                    return True
                finally:
                    try:
                        target.blockSignals(False)
                    except Exception:
                        pass
            if hasattr(target, "setText"):
                target.setText(value)
                return True
            return False

    def _sync_backend_to_ui(self, *, force=False, lightweight=False):
            if lightweight and not force:
                # Keep MuseTalk preview rendering smooth in the Designer front-end:
                # status/diode mirroring is cheap, while full button/field mirroring
                # can steal UI-thread time from the 16 ms preview frame timer.
                self._mirror_runtime_status_widgets()
                self._mirror_pipeline_telemetry_widgets()
                return
            for object_name in self._combo_sync_names():
                front = self._ui_object(object_name)
                back = self._backend_widget(object_name)
                if front is None or back is None:
                    continue
                if self._combo_popup_is_open(front):
                    continue
                if force or not getattr(front, "hasFocus", lambda: False)():
                    self._copy_combo_state(back, front)
            for object_name in self._checkbox_sync_names():
                front = self._ui_object(object_name)
                back = self._backend_widget(object_name)
                if front is None or back is None:
                    continue
                self._copy_checkbox_state(back, front)
            for object_name in self._spin_sync_names():
                front = self._ui_object(object_name)
                back = self._backend_widget(object_name)
                if front is None or back is None:
                    continue
                self._copy_spin_state(back, front)
            for object_name in self._line_edit_sync_names():
                front = self._ui_object(object_name)
                back = self._backend_widget(object_name)
                if front is None or back is None:
                    continue
                if force or not getattr(front, "hasFocus", lambda: False)():
                    self._copy_text_state(back, front)
            self._mirror_runtime_text_views()
            self._mirror_pipeline_telemetry_widgets()
            self._mirror_runtime_status_widgets()
            self._mirror_runtime_button_state()
            self._mirror_runtime_selection_widgets()
            self._mirror_persona_runtime_widgets(force=force)
            self._copy_runtime_plain_text_state("sensory_pingpong_prompt_text", "sensory_pingpong_prompt")
            self._mirror_body_pose_runtime_widgets(force=force)
            self._mirror_addon_runtime_widgets(force=force)
            self._mirror_chunking_runtime_widgets(force=force)
            self._mirror_provider_runtime_labels()
            self._refresh_frontend_theme_controls()

import json
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets


TUTORIALS_DIR = Path(__file__).resolve().parent / "tutorials"


class TutorialEventBus(QtCore.QObject):
    event_emitted = QtCore.Signal(str, object)

    def emit_event(self, name, payload=None):
        self.event_emitted.emit(str(name or ""), payload if payload is not None else {})


def ensure_tutorials_dir():
    TUTORIALS_DIR.mkdir(parents=True, exist_ok=True)


def list_tutorials():
    ensure_tutorials_dir()
    items = []
    for path in sorted(TUTORIALS_DIR.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        items.append(
            {
                "id": str(payload.get("id") or path.stem),
                "title": str(payload.get("title") or path.stem.replace("_", " ").title()),
                "description": str(payload.get("description") or ""),
                "path": str(path),
                "step_count": len(payload.get("steps") or []),
            }
        )
    return items


def load_tutorial(tutorial_id):
    ensure_tutorials_dir()
    if not tutorial_id:
        return None
    candidates = [
        TUTORIALS_DIR / f"{tutorial_id}.json",
        TUTORIALS_DIR / tutorial_id,
    ]
    for path in candidates:
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload.setdefault("id", tutorial_id)
                payload.setdefault("title", tutorial_id.replace("_", " ").title())
                payload.setdefault("steps", [])
                return payload
            except Exception:
                return None
    for item in list_tutorials():
        if item["id"] == tutorial_id:
            return load_tutorial(Path(item["path"]).name)
    return None


class TutorialOverlay(QtWidgets.QWidget):
    finished = QtCore.Signal(str)

    def __init__(self, main_window, tutorial, parent=None):
        super().__init__(parent or main_window)
        self.main_window = main_window
        self.tutorial = dict(tutorial or {})
        self.steps = list(self.tutorial.get("steps") or [])
        self.step_lookup = {}
        for idx, raw_step in enumerate(self.steps):
            step_id = str((raw_step or {}).get("id") or f"step_{idx + 1}")
            self.step_lookup[step_id] = idx
        self.step_index = 0
        self.highlight_rect = QtCore.QRect()
        self.target_name = ""
        self.current_condition = {}
        self.current_target_widget = None
        self.current_step_complete = False
        self.current_button_click_count = 0
        self.auto_advance_pending = False
        self.current_hint_only = False
        self.current_manual_next_enabled = True
        self.seen_events = []
        self.last_event_name = ""
        self.last_event_payload = {}
        self.event_bus = getattr(main_window, "tutorial_event_bus", None)
        if self.event_bus is not None:
            self.event_bus.event_emitted.connect(self.on_tutorial_event)

        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, False)
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setStyleSheet("background: transparent;")

        self.panel = QtWidgets.QFrame(main_window)
        self.panel.setObjectName("TutorialPanel")
        self.panel.setStyleSheet(
            """
            QFrame#TutorialPanel {
                background: #0f141b;
                border: 1px solid #3b5a7a;
                border-radius: 14px;
            }
            QLabel { color: #e5e9f0; }
            QPushButton {
                background: #223247;
                border: 1px solid #324b69;
                border-radius: 10px;
                padding: 6px 12px;
                font-weight: 600;
            }
            QPushButton:hover { background: #29405b; }
            """
        )
        panel_layout = QtWidgets.QVBoxLayout(self.panel)
        panel_layout.setContentsMargins(14, 12, 14, 12)
        panel_layout.setSpacing(10)

        self.step_label = QtWidgets.QLabel("")
        self.step_label.setStyleSheet("color: #8bbcff; font-size: 11px; font-weight: 700;")
        self.title_label = QtWidgets.QLabel("")
        self.title_label.setWordWrap(True)
        self.title_label.setStyleSheet("font-size: 18px; font-weight: 700; color: #f7fafc;")
        self.body_label = QtWidgets.QLabel("")
        self.body_label.setWordWrap(True)
        self.body_label.setStyleSheet("font-size: 13px; line-height: 1.3;")
        self.target_label = QtWidgets.QLabel("")
        self.target_label.setWordWrap(True)
        self.target_label.setStyleSheet("color: #9fb3c8; font-size: 11px;")
        panel_layout.addWidget(self.step_label)
        panel_layout.addWidget(self.title_label)
        panel_layout.addWidget(self.body_label)
        panel_layout.addWidget(self.target_label)

        buttons = QtWidgets.QHBoxLayout()
        self.back_button = QtWidgets.QPushButton("Back")
        self.back_button.clicked.connect(self.previous_step)
        self.next_button = QtWidgets.QPushButton("Next")
        self.next_button.clicked.connect(self.next_step)
        self.skip_button = QtWidgets.QPushButton("Skip")
        self.skip_button.clicked.connect(lambda: self.finish("skipped"))
        buttons.addWidget(self.back_button)
        buttons.addStretch(1)
        buttons.addWidget(self.skip_button)
        buttons.addWidget(self.next_button)
        panel_layout.addLayout(buttons)

        self.main_window.installEventFilter(self)
        self.check_timer = QtCore.QTimer(self)
        self.check_timer.setInterval(150)
        self.check_timer.timeout.connect(self._poll_step_completion)
        self.hide()

    def start(self):
        self.step_index = 0
        self.setGeometry(self.main_window.rect())
        self.show()
        self._keep_overlay_visible()
        self.panel.show()
        self.check_timer.start()
        self.show_step(0)

    def _keep_overlay_visible(self):
        if not self.isVisible():
            return
        try:
            self.raise_()
            self.show()
        except Exception:
            pass
        try:
            if not self.panel.isHidden():
                self.panel.raise_()
                self.panel.show()
        except Exception:
            pass

    def eventFilter(self, watched, event):
        if watched is self.main_window and event.type() in (
            QtCore.QEvent.Resize,
            QtCore.QEvent.Move,
            QtCore.QEvent.Show,
            QtCore.QEvent.WindowActivate,
            QtCore.QEvent.LayoutRequest,
        ):
            self.setGeometry(self.main_window.rect())
            self._reposition_panel()
            self._keep_overlay_visible()
        if watched is self.current_target_widget and self.current_condition:
            req_type = str(self.current_condition.get("type") or "").lower()
            if req_type == "button_click" and event.type() == QtCore.QEvent.MouseButtonRelease:
                self.current_button_click_count += 1
                self._poll_step_completion(force=True)
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Escape:
            self.finish("skipped")
            return
        if event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter, QtCore.Qt.Key_Space):
            self.next_step()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), QtGui.QColor(5, 10, 16, 175))
        if not self.highlight_rect.isNull():
            glow_rect = self.highlight_rect.adjusted(-6, -6, 6, 6)
            painter.setPen(QtGui.QPen(QtGui.QColor(88, 166, 255), 3))
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawRoundedRect(glow_rect, 12, 12)
        super().paintEvent(event)

    def _select_tab_by_text(self, tab_widget, tab_title):
        if not tab_widget or not tab_title:
            return
        for index in range(tab_widget.count()):
            if tab_widget.tabText(index).strip().lower() == str(tab_title).strip().lower():
                tab_widget.setCurrentIndex(index)
                return

    def _resolve_target_widget(self, target_name):
        if not target_name or target_name == "main_window":
            return self.main_window
        return self.main_window.findChild(QtCore.QObject, str(target_name))

    def _current_state(self):
        provider = getattr(self.main_window, "get_tutorial_runtime_state", None)
        if callable(provider):
            try:
                state = provider() or {}
                if isinstance(state, dict):
                    return state
            except Exception:
                pass
        return {}

    def _coerce_bool(self, value):
        if isinstance(value, bool):
            return value
        text = str(value or "").strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off", ""}:
            return False
        return bool(value)

    def _compare_value(self, actual, condition):
        if not isinstance(condition, dict):
            return bool(actual) == bool(condition)
        if "value" in condition:
            expected = condition.get("value")
            return str(actual).strip().lower() == str(expected).strip().lower()
        if "value_not" in condition:
            forbidden = condition.get("value_not")
            return str(actual).strip().lower() != str(forbidden).strip().lower()
        if "contains" in condition:
            return str(condition.get("contains") or "").strip().lower() in str(actual or "").strip().lower()
        if "less_than" in condition:
            try:
                return float(actual) < float(condition.get("less_than"))
            except Exception:
                return False
        if "greater_than" in condition:
            try:
                return float(actual) > float(condition.get("greater_than"))
            except Exception:
                return False
        return bool(actual)

    def _evaluate_leaf_condition(self, condition):
        condition = dict(condition or {})
        cond_type = str(condition.get("type") or "").lower()
        target_name = str(condition.get("target") or self.target_name or "main_window")
        target_widget = self._resolve_target_widget(target_name)
        state = self._current_state()

        if cond_type in {"", "none"}:
            return True
        if cond_type == "combo_text" and isinstance(target_widget, QtWidgets.QComboBox):
            return self._compare_value(target_widget.currentText(), condition)
        if cond_type == "checkbox" and isinstance(target_widget, QtWidgets.QCheckBox):
            return self._coerce_bool(target_widget.isChecked()) == self._coerce_bool(condition.get("value"))
        if cond_type == "spin_value" and isinstance(target_widget, (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox)):
            return self._compare_value(target_widget.value(), condition)
        if cond_type == "tab_text":
            if isinstance(target_widget, QtWidgets.QTabWidget):
                return self._compare_value(target_widget.tabText(target_widget.currentIndex()), condition)
            return False
        if cond_type == "text_nonempty" and isinstance(target_widget, (QtWidgets.QLineEdit, QtWidgets.QPlainTextEdit, QtWidgets.QTextEdit)):
            if isinstance(target_widget, QtWidgets.QLineEdit):
                text = target_widget.text()
            else:
                text = target_widget.toPlainText()
            return bool(str(text).strip())
        if cond_type == "button_click" and isinstance(target_widget, QtWidgets.QAbstractButton):
            return self.current_button_click_count > 0
        if cond_type == "state":
            return self._compare_value(state.get(str(condition.get("key") or "")), condition)
        if cond_type == "lm_studio_running":
            return self._coerce_bool(state.get("lm_studio_running")) == self._coerce_bool(condition.get("value", True))
        if cond_type == "model_loaded":
            return self._coerce_bool(state.get("model_loaded")) == self._coerce_bool(condition.get("value", True))
        if cond_type == "engine_running":
            return self._coerce_bool(state.get("engine_running")) == self._coerce_bool(condition.get("value", True))
        if cond_type == "avatar_mode":
            return self._compare_value(state.get("avatar_mode"), condition)
        if cond_type == "stream_mode":
            return self._compare_value(state.get("stream_mode"), condition)
        if cond_type == "tts_backend":
            return self._compare_value(state.get("tts_backend"), condition)
        if cond_type == "vram_mode":
            return self._compare_value(state.get("musetalk_vram_mode"), condition)
        if cond_type == "preview_visible":
            return self._coerce_bool(state.get("preview_visible")) == self._coerce_bool(condition.get("value", True))
        if cond_type == "dry_run_active":
            return self._coerce_bool(state.get("dry_run_active")) == self._coerce_bool(condition.get("value", True))
        if cond_type == "dry_run_complete":
            return self._coerce_bool(state.get("dry_run_complete")) == self._coerce_bool(condition.get("value", True))
        if cond_type == "last_error_contains":
            needle = str(condition.get("value") or condition.get("contains") or "").strip().lower()
            return needle in str(state.get("last_error_text") or "").lower()
        if cond_type == "event_seen":
            wanted = str(condition.get("value") or "").strip().lower()
            return wanted in {name.lower() for name in self.seen_events}
        return False

    def _evaluate_condition(self, condition):
        if not condition:
            return True
        if isinstance(condition, list):
            return all(self._evaluate_condition(item) for item in condition)
        condition = dict(condition or {})
        if "all" in condition:
            return all(self._evaluate_condition(item) for item in list(condition.get("all") or []))
        if "any" in condition:
            return any(self._evaluate_condition(item) for item in list(condition.get("any") or []))
        if "not" in condition:
            return not self._evaluate_condition(condition.get("not"))
        return self._evaluate_leaf_condition(condition)

    def _goto_to_index(self, goto_value):
        if goto_value is None:
            return None
        if isinstance(goto_value, int):
            if 0 <= goto_value < len(self.steps):
                return goto_value
            return None
        text = str(goto_value).strip()
        if text.isdigit():
            idx = int(text)
            if 0 <= idx < len(self.steps):
                return idx
            if 1 <= idx <= len(self.steps):
                return idx - 1
        return self.step_lookup.get(text)

    def _resolve_transition_target(self, step, default_index=None):
        transitions = list((step or {}).get("transitions") or [])
        for transition in transitions:
            transition = dict(transition or {})
            cond = transition.get("condition")
            if cond is not None and not self._evaluate_condition(cond):
                continue
            goto_index = self._goto_to_index(transition.get("goto"))
            if goto_index is not None:
                return goto_index
        explicit_next = self._goto_to_index((step or {}).get("next"))
        if explicit_next is not None:
            return explicit_next
        return default_index

    def _update_highlight_for_target(self, target_widget):
        self._make_widget_visible(target_widget)
        self.highlight_rect = self._target_rect_for_widget(target_widget).adjusted(-4, -4, 4, 4)
        self._reposition_panel()
        self.update()

    def _make_widget_visible(self, widget):
        if widget is None or widget is self.main_window or not isinstance(widget, QtWidgets.QWidget):
            return
        current = widget
        while current is not None and current is not self.main_window:
            parent = current.parentWidget()
            if isinstance(parent, QtWidgets.QStackedWidget):
                try:
                    parent.setCurrentWidget(current)
                except Exception:
                    pass
                tab_widget = parent.parentWidget()
                if isinstance(tab_widget, QtWidgets.QTabWidget):
                    try:
                        index = tab_widget.indexOf(current)
                        if index >= 0:
                            tab_widget.setCurrentIndex(index)
                    except Exception:
                        pass
            if isinstance(parent, QtWidgets.QTabWidget):
                try:
                    index = parent.indexOf(current)
                    if index >= 0:
                        parent.setCurrentIndex(index)
                except Exception:
                    pass
            if isinstance(current, QtWidgets.QDockWidget):
                try:
                    current.setVisible(True)
                    current.raise_()
                except Exception:
                    pass
            elif hasattr(current, "setVisible"):
                try:
                    current.setVisible(True)
                except Exception:
                    pass
            current = parent
        try:
            widget.raise_()
            widget.setFocus(QtCore.Qt.OtherFocusReason)
        except Exception:
            pass

    def _apply_actions(self, step):
        for action in list(step.get("actions") or []):
            action = dict(action or {})
            action_type = str(action.get("type") or "").lower()
            target_name = str(action.get("target") or "")
            target_widget = self._resolve_target_widget(target_name) if target_name else None
            value = action.get("value")
            if action_type == "set_combo_text" and isinstance(target_widget, QtWidgets.QComboBox):
                target_widget.setCurrentText(str(value or ""))
            elif action_type == "set_checkbox" and isinstance(target_widget, QtWidgets.QCheckBox):
                target_widget.setChecked(bool(value))
            elif action_type == "set_spin_value" and isinstance(target_widget, (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox)):
                target_widget.setValue(value)
            elif action_type in {"set_tab", "open_tab"}:
                tab_widget_name = str(action.get("tab_widget") or "left_tabs")
                tab_widget = self.main_window.findChild(QtWidgets.QTabWidget, tab_widget_name)
                self._select_tab_by_text(tab_widget, value or target_name)
            elif action_type == "focus" and isinstance(target_widget, QtWidgets.QWidget):
                target_widget.setFocus()
            elif action_type == "highlight_ui" and isinstance(target_widget, QtWidgets.QWidget):
                self._update_highlight_for_target(target_widget)
            elif action_type == "load_profile":
                loader = getattr(self.main_window, "load_performance_profile_by_id", None)
                if callable(loader):
                    loader(str(value or target_name or ""))
            elif action_type == "load_preset":
                if value and hasattr(self.main_window, "preset_combo"):
                    self.main_window.preset_combo.setCurrentText(str(value))
                loader = getattr(self.main_window, "load_preset", None)
                if callable(loader):
                    loader()
            elif action_type == "reset_to_safe_state":
                resetter = getattr(self.main_window, "apply_safe_tutorial_defaults", None)
                if callable(resetter):
                    resetter()

    def _run_listeners_for_event(self, step, event_name, payload):
        listeners = list((step or {}).get("listen") or [])
        for listener in listeners:
            listener = dict(listener or {})
            wanted = str(listener.get("event") or "").strip().lower()
            if wanted and wanted != str(event_name or "").strip().lower():
                continue
            cond = listener.get("condition")
            if cond is not None and not self._evaluate_condition(cond):
                continue
            action = str(listener.get("action") or "advance").strip().lower()
            if action == "advance":
                QtCore.QTimer.singleShot(120, self.next_step)
                return True
            if action == "goto":
                goto_index = self._goto_to_index(listener.get("goto"))
                if goto_index is not None:
                    QtCore.QTimer.singleShot(120, lambda idx=goto_index: self.show_step(idx))
                    return True
            if action == "finish":
                QtCore.QTimer.singleShot(0, lambda: self.finish(str(listener.get("reason") or "completed")))
                return True
        return False

    def on_tutorial_event(self, event_name, payload):
        self.last_event_name = str(event_name or "")
        self.last_event_payload = payload if isinstance(payload, dict) else {"value": payload}
        if self.last_event_name:
            self.seen_events.append(self.last_event_name)
            self.seen_events = self.seen_events[-50:]
        if not self.isVisible() or self.step_index >= len(self.steps):
            return
        self._keep_overlay_visible()
        step = dict(self.steps[self.step_index] or {})
        if self._run_listeners_for_event(step, self.last_event_name, self.last_event_payload):
            return
        self._poll_step_completion(force=True)

    def _poll_step_completion(self, force=False):
        if not self.isVisible():
            return
        self._keep_overlay_visible()
        condition = dict(self.current_condition or {})
        if not condition:
            self.current_step_complete = True
            self.next_button.setEnabled(self.current_hint_only or self.current_manual_next_enabled)
            self.auto_advance_pending = False
            return
        previous_complete = bool(self.current_step_complete)
        complete = self._evaluate_condition(condition)
        self.current_step_complete = complete
        auto_advance = bool(condition.get("auto_advance", False))
        if self.current_hint_only:
            self.next_button.setEnabled(True)
        else:
            self.next_button.setEnabled(complete and self.current_manual_next_enabled)
        if not complete:
            self.auto_advance_pending = False
        if complete and auto_advance and not previous_complete and not self.auto_advance_pending and (force or self.step_index < len(self.steps)):
            self.auto_advance_pending = True
            QtCore.QTimer.singleShot(120, self.next_step)

    def _target_rect_for_widget(self, widget):
        if widget is None:
            return QtCore.QRect()
        if widget is self.main_window:
            return self.rect().adjusted(18, 18, -18, -18)
        top_left = self.mapFromGlobal(widget.mapToGlobal(QtCore.QPoint(0, 0)))
        return QtCore.QRect(top_left, widget.size())

    def _reposition_panel(self):
        if self.panel.isHidden():
            return
        margin = 18
        panel_size = self.panel.sizeHint()
        rect = self.highlight_rect
        if rect.isNull():
            x = max((self.width() - panel_size.width()) // 2, margin)
            y = max((self.height() - panel_size.height()) // 2, margin)
            self.panel.setGeometry(x, y, min(panel_size.width(), self.width() - margin * 2), panel_size.height())
            return

        x = min(rect.right() + 18, self.width() - panel_size.width() - margin)
        y = rect.top()
        if x < margin or x <= rect.right():
            x = max(rect.left() - panel_size.width() - 18, margin)
        if x < margin:
            x = max(min(rect.left(), self.width() - panel_size.width() - margin), margin)
            y = min(rect.bottom() + 18, self.height() - panel_size.height() - margin)
        if y + panel_size.height() > self.height() - margin:
            y = max(self.height() - panel_size.height() - margin, margin)
        self.panel.setGeometry(x, y, min(panel_size.width(), self.width() - margin * 2), panel_size.height())

    def show_step(self, index, _visited=None):
        if _visited is None:
            _visited = set()
        if index < 0 or index >= len(self.steps):
            self.finish("completed")
            return
        if index in _visited:
            self.finish("loop_detected")
            return
        _visited.add(index)

        step = dict(self.steps[index] or {})
        if bool(step.get("auto_route", False)):
            routed_index = self._resolve_transition_target(step, default_index=index)
            if routed_index is not None and routed_index != index:
                self.show_step(routed_index, _visited=_visited)
                return

        self.step_index = index
        if isinstance(self.current_target_widget, QtCore.QObject):
            try:
                self.current_target_widget.removeEventFilter(self)
            except Exception:
                pass
        self.current_button_click_count = 0
        self._select_tab_by_text(getattr(self.main_window, "tabs", None), step.get("tab"))
        self._select_tab_by_text(getattr(self.main_window, "right_tabs", None), step.get("right_tab"))
        self._apply_actions(step)

        self.target_name = str(step.get("target") or "main_window")
        target_widget = self._resolve_target_widget(self.target_name)
        self.current_target_widget = target_widget
        if isinstance(self.current_target_widget, QtCore.QObject):
            self.current_target_widget.installEventFilter(self)
        if isinstance(target_widget, QtWidgets.QWidget):
            self._make_widget_visible(target_widget)
        self.highlight_rect = self._target_rect_for_widget(target_widget).adjusted(-4, -4, 4, 4)
        self.current_condition = dict(step.get("condition") or step.get("require") or {})
        self.current_hint_only = bool(step.get("hint_only", False))
        self.current_manual_next_enabled = bool(step.get("manual_next", True))
        self.auto_advance_pending = False

        self.step_label.setText(
            f"{self.tutorial.get('title', 'Tutorial')} • Step {index + 1} / {max(len(self.steps), 1)}"
        )
        self.title_label.setText(str(step.get("title") or "Tutorial Step"))
        self.body_label.setText(str(step.get("body") or ""))
        target_lines = []
        if self.target_name and self.target_name != "main_window":
            target_lines.append(f"Target: {self.target_name}")
        if self.current_hint_only:
            target_lines.append("Hint only: you can continue even if this step is not completed.")
        if step.get("listen"):
            target_lines.append("This step can react to live app events.")
        self.target_label.setText("\n".join(target_lines).strip())
        self.back_button.setEnabled(index > 0)
        self.next_button.setText("Finish" if index >= len(self.steps) - 1 else "Next")
        self.panel.adjustSize()
        self._reposition_panel()
        self._keep_overlay_visible()
        self._poll_step_completion(force=True)
        self.update()

    def next_step(self):
        if self.step_index >= len(self.steps) - 1:
            self.finish("completed")
            return
        current_step = dict(self.steps[self.step_index] or {})
        next_index = self._resolve_transition_target(current_step, default_index=self.step_index + 1)
        if next_index is None:
            next_index = self.step_index + 1
        self.show_step(next_index)

    def previous_step(self):
        if self.step_index <= 0:
            return
        self.show_step(self.step_index - 1)

    def finish(self, reason):
        self.check_timer.stop()
        self.hide()
        self.panel.hide()
        try:
            self.main_window.removeEventFilter(self)
        except Exception:
            pass
        if self.event_bus is not None:
            try:
                self.event_bus.event_emitted.disconnect(self.on_tutorial_event)
            except Exception:
                pass
        self.finished.emit(str(reason))

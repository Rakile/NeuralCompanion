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
        self.current_target_signal_connections = []
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

        self.panel = QtWidgets.QFrame(
            None,
            QtCore.Qt.Tool
            | QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.WindowStaysOnTopHint,
        )
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

    def _debug(self, message):
        tutorial_id = str(self.tutorial.get("id") or self.tutorial.get("title") or "tutorial")
        print(f"[TutorialDebug:{tutorial_id}] {message}", flush=True)

    def _widget_debug_name(self, widget):
        if widget is None:
            return "None"
        try:
            class_name = widget.metaObject().className() if hasattr(widget, "metaObject") else widget.__class__.__name__
        except Exception:
            class_name = widget.__class__.__name__
        try:
            object_name = widget.objectName() if hasattr(widget, "objectName") else ""
        except Exception:
            object_name = ""
        try:
            title = widget.windowTitle() if hasattr(widget, "windowTitle") else ""
        except Exception:
            title = ""
        return f"{class_name}(objectName={object_name!r}, title={title!r})"

    def start(self):
        self._debug("overlay start() called")
        self.step_index = 0
        self.setGeometry(self.main_window.rect())
        self.panel.show()
        self.check_timer.start()
        self.show_step(0)

    def _keep_overlay_visible(self):
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
        if not self.highlight_rect.isNull():
            glow_rect = self.highlight_rect.adjusted(-6, -6, 6, 6)
            painter.setPen(QtGui.QPen(QtGui.QColor(88, 166, 255, 220), 3))
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawRoundedRect(glow_rect, 12, 12)
        super().paintEvent(event)

    def _select_tab_by_text(self, tab_widget, tab_title):
        if not tab_widget or not tab_title:
            self._debug(f"select_tab skipped: tab_widget={self._widget_debug_name(tab_widget)} tab_title={tab_title!r}")
            return
        wanted = str(tab_title).strip().lower()
        candidates = []
        for index in range(tab_widget.count()):
            page = tab_widget.widget(index)
            page_name = page.objectName().strip().lower() if isinstance(page, QtWidgets.QWidget) else ""
            text = tab_widget.tabText(index).strip()
            candidates.append(f"{index}:{text!r}/{page_name!r}")
            if text.lower() == wanted or page_name == wanted:
                tab_widget.setCurrentIndex(index)
                self._debug(
                    f"select_tab ok: tab_widget={self._widget_debug_name(tab_widget)} wanted={tab_title!r} "
                    f"index={index} text={text!r} page={page_name!r}"
                )
                return
        self._debug(
            f"select_tab miss: tab_widget={self._widget_debug_name(tab_widget)} wanted={tab_title!r} "
            f"candidates=[{', '.join(candidates)}]"
        )

    def _resolve_target_widget(self, target_name):
        if not target_name or target_name == "main_window":
            return self.main_window
        widget = self.main_window.findChild(QtCore.QObject, str(target_name))
        self._debug(f"resolve_target {target_name!r} -> {self._widget_debug_name(widget)}")
        return widget

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
            result = self._compare_value(target_widget.currentText(), condition)
            self._debug(
                f"condition combo_text: target={target_name!r} actual={target_widget.currentText()!r} "
                f"expected={condition.get('value')!r} result={result}"
            )
            return result
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

    def _show_dock(self, dock_name):
        name = str(dock_name or "").strip()
        if not name:
            self._debug("show_dock skipped: empty dock name")
            return
        dock = self.main_window.findChild(QtWidgets.QDockWidget, name)
        if dock is None:
            for candidate in self.main_window.findChildren(QtWidgets.QDockWidget):
                if candidate.windowTitle().strip().lower() == name.lower():
                    dock = candidate
                    break
        if dock is None:
            candidates = [
                f"{candidate.objectName()!r}/{candidate.windowTitle()!r}"
                for candidate in self.main_window.findChildren(QtWidgets.QDockWidget)
            ]
            self._debug(f"show_dock miss: wanted={name!r} candidates=[{', '.join(candidates)}]")
            return
        try:
            before = dock.isVisible()
            dock.setVisible(True)
            dock.show()
            dock.raise_()
            dock.activateWindow()
            QtCore.QTimer.singleShot(0, dock.raise_)
            self._debug(
                f"show_dock ok: wanted={name!r} dock={self._widget_debug_name(dock)} "
                f"visible {before}->{dock.isVisible()} floating={dock.isFloating()}"
            )
        except Exception:
            self._debug(f"show_dock failed: wanted={name!r}")

    def _make_widget_visible(self, widget):
        if widget is None or widget is self.main_window or not isinstance(widget, QtWidgets.QWidget):
            self._debug(f"make_visible skipped: widget={self._widget_debug_name(widget)}")
            return
        self._debug(f"make_visible start: widget={self._widget_debug_name(widget)} visible={widget.isVisible()}")
        current = widget
        scroll_areas = []
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
            if isinstance(parent, QtWidgets.QScrollArea):
                scroll_areas.append(parent)
            if isinstance(current, QtWidgets.QDockWidget):
                self._show_dock(current.objectName() or current.windowTitle())
            elif hasattr(current, "setVisible"):
                try:
                    current.setVisible(True)
                except Exception:
                    pass
            current = parent
        for area in reversed(scroll_areas):
            try:
                area.ensureWidgetVisible(widget, 24, 24)
            except Exception:
                pass
        try:
            widget.raise_()
            widget.setFocus(QtCore.Qt.OtherFocusReason)
        except Exception:
            pass
        self._debug(f"make_visible done: widget={self._widget_debug_name(widget)} visible={widget.isVisible()}")

    def _apply_actions(self, step):
        for action in list(step.get("actions") or []):
            action = dict(action or {})
            action_type = str(action.get("type") or "").lower()
            target_name = str(action.get("target") or "")
            target_widget = self._resolve_target_widget(target_name) if target_name else None
            value = action.get("value")
            self._debug(
                f"action start: type={action_type!r} target={target_name!r} value={value!r} "
                f"target_widget={self._widget_debug_name(target_widget)}"
            )
            if action_type == "set_combo_text" and isinstance(target_widget, QtWidgets.QComboBox):
                before = target_widget.currentText()
                target_widget.setCurrentText(str(value or ""))
                self._debug(f"action set_combo_text: {target_name!r} {before!r}->{target_widget.currentText()!r}")
            elif action_type == "set_checkbox" and isinstance(target_widget, QtWidgets.QCheckBox):
                target_widget.setChecked(bool(value))
            elif action_type == "set_spin_value" and isinstance(target_widget, (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox)):
                target_widget.setValue(value)
            elif action_type in {"set_tab", "open_tab"}:
                tab_widget_name = str(action.get("tab_widget") or "left_tabs")
                tab_widget = self.main_window.findChild(QtWidgets.QTabWidget, tab_widget_name)
                self._debug(f"action open_tab: tab_widget_name={tab_widget_name!r} tab_widget={self._widget_debug_name(tab_widget)}")
                self._select_tab_by_text(tab_widget, value or target_name)
            elif action_type == "show_dock":
                self._show_dock(value or target_name)
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
            else:
                self._debug(
                    f"action no-op: type={action_type!r} target={target_name!r} "
                    f"target_widget={self._widget_debug_name(target_widget)}"
                )

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
        if self.panel.isHidden():
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
            self._debug(f"auto_advance scheduled: step_index={self.step_index}")
            QtCore.QTimer.singleShot(120, self.next_step)

    def _disconnect_current_target_signals(self):
        for signal, slot in list(self.current_target_signal_connections):
            try:
                signal.disconnect(slot)
            except Exception:
                pass
        self.current_target_signal_connections = []

    def _connect_current_target_signals(self):
        self._disconnect_current_target_signals()
        widget = self.current_target_widget
        if isinstance(widget, QtWidgets.QComboBox):
            slot = lambda *_args: self._poll_step_completion(force=True)
            try:
                widget.currentTextChanged.connect(slot)
                self.current_target_signal_connections.append((widget.currentTextChanged, slot))
                self._debug(f"connected currentTextChanged for {self._widget_debug_name(widget)}")
            except Exception:
                pass

    def _target_rect_for_widget(self, widget):
        if widget is None:
            return QtCore.QRect()
        if widget is self.main_window:
            return self.main_window.rect().adjusted(18, 18, -18, -18)
        top_left = self.main_window.mapFromGlobal(widget.mapToGlobal(QtCore.QPoint(0, 0)))
        return QtCore.QRect(top_left, widget.size())

    def _set_panel_geometry(self, x, y, width, height):
        top_left = self.main_window.mapToGlobal(QtCore.QPoint(int(x), int(y)))
        self.panel.setGeometry(top_left.x(), top_left.y(), int(width), int(height))

    def _reposition_panel(self):
        if self.panel.isHidden():
            return
        margin = 18
        panel_size = self.panel.sizeHint()
        parent_rect = self.main_window.rect()
        rect = self.highlight_rect
        if rect.isNull():
            x = max((parent_rect.width() - panel_size.width()) // 2, margin)
            y = max((parent_rect.height() - panel_size.height()) // 2, margin)
            self._set_panel_geometry(x, y, min(panel_size.width(), parent_rect.width() - margin * 2), panel_size.height())
            return

        candidates = [
            (rect.right() + 18, rect.top()),
            (rect.left() - panel_size.width() - 18, rect.top()),
            (rect.left(), rect.bottom() + 18),
            (rect.left(), rect.top() - panel_size.height() - 18),
        ]
        x, y = margin, margin
        for candidate_x, candidate_y in candidates:
            candidate_x = max(min(candidate_x, parent_rect.width() - panel_size.width() - margin), margin)
            candidate_y = max(min(candidate_y, parent_rect.height() - panel_size.height() - margin), margin)
            candidate_rect = QtCore.QRect(candidate_x, candidate_y, panel_size.width(), panel_size.height())
            if not candidate_rect.intersects(rect.adjusted(-12, -12, 12, 12)):
                x, y = candidate_x, candidate_y
                break
        else:
            x = max(min(rect.left(), parent_rect.width() - panel_size.width() - margin), margin)
            y = max(min(rect.bottom() + 18, parent_rect.height() - panel_size.height() - margin), margin)
        if y + panel_size.height() > parent_rect.height() - margin:
            y = max(parent_rect.height() - panel_size.height() - margin, margin)
        self._set_panel_geometry(x, y, min(panel_size.width(), parent_rect.width() - margin * 2), panel_size.height())

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
        self._disconnect_current_target_signals()
        self.current_button_click_count = 0
        self._debug(
            f"show_step start: index={index} title={step.get('title')!r} target={step.get('target')!r} "
            f"tab={step.get('tab')!r} right_tab={step.get('right_tab')!r} actions={len(list(step.get('actions') or []))}"
        )
        self._select_tab_by_text(getattr(self.main_window, "tabs", None), step.get("tab"))
        self._select_tab_by_text(getattr(self.main_window, "right_tabs", None), step.get("right_tab"))
        self._apply_actions(step)

        self.target_name = str(step.get("target") or "main_window")
        target_widget = self._resolve_target_widget(self.target_name)
        self.current_target_widget = target_widget
        if isinstance(self.current_target_widget, QtCore.QObject):
            self.current_target_widget.installEventFilter(self)
        self._connect_current_target_signals()
        if isinstance(target_widget, QtWidgets.QWidget):
            self._make_widget_visible(target_widget)
        self.highlight_rect = self._target_rect_for_widget(target_widget).adjusted(-4, -4, 4, 4)
        self._debug(
            f"show_step target: name={self.target_name!r} widget={self._widget_debug_name(target_widget)} "
            f"visible={target_widget.isVisible() if isinstance(target_widget, QtWidgets.QWidget) else 'n/a'} "
            f"highlight={self.highlight_rect.getRect()}"
        )
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
        self._debug(f"finish called: reason={reason!r}")
        self.check_timer.stop()
        self._disconnect_current_target_signals()
        self.panel.hide()
        self.panel.close()
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

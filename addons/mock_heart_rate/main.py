import time

from core.addons import BaseAddon


class _Subscriber:
    def __init__(self, callback, interval_seconds: float, last_emitted_at: float = 0.0):
        self.callback = callback
        self.interval_seconds = float(interval_seconds)
        self.last_emitted_at = float(last_emitted_at)


class MockHeartRateService:
    def __init__(self, addon):
        self._addon = addon
        self._subscribers: dict[int, _Subscriber] = {}
        self._next_token = 1

    def current_bpm(self) -> int:
        return int(self._addon.current_bpm)

    def snapshot(self) -> dict:
        return {
            "bpm": int(self._addon.current_bpm),
            "updated_at": float(self._addon.last_updated_at),
            "window_visible": bool(self._addon.is_window_visible()),
            "source": "heart_rate",
        }

    def set_bpm(self, value: int) -> int:
        return int(self._addon.set_bpm(int(value)))

    def subscribe(self, callback, *, interval_seconds: float | None = None, per_second: float | None = None) -> int:
        if not callable(callback):
            raise ValueError("MockHeartRateService.subscribe requires a callable callback.")
        interval = interval_seconds if interval_seconds is not None else per_second
        try:
            interval_value = float(interval if interval is not None else 0.5)
        except Exception:
            interval_value = 0.5
        interval_value = max(0.05, interval_value)
        token = self._next_token
        self._next_token += 1
        self._subscribers[token] = _Subscriber(callback=callback, interval_seconds=interval_value)
        return token

    def unsubscribe(self, token: int) -> bool:
        return self._subscribers.pop(int(token), None) is not None

    def emit_if_due(self, *, force: bool = False) -> None:
        now = time.time()
        payload = self.snapshot()
        for token, subscriber in list(self._subscribers.items()):
            if not force and (now - float(subscriber.last_emitted_at or 0.0)) < float(subscriber.interval_seconds):
                continue
            try:
                subscriber.callback(dict(payload))
                subscriber.last_emitted_at = now
            except Exception:
                context = getattr(self._addon, "context", None)
                if context is not None:
                    context.logger.exception("Mock heart-rate subscriber failed for token %s", token)


class MockHeartRateWindow:
    def __init__(self, addon):
        from PySide6 import QtCore, QtWidgets

        self._addon = addon
        self.widget = QtWidgets.QWidget()
        self.widget.setWindowTitle("Mock Heart Rate")
        self.widget.setObjectName("mock_heart_rate_window")
        self.widget.setWindowFlag(QtCore.Qt.Tool, True)
        self.widget.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, True)
        self.widget.resize(170, 420)

        layout = QtWidgets.QVBoxLayout(self.widget)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QtWidgets.QLabel("BPM")
        title.setAlignment(QtCore.Qt.AlignCenter)
        title.setStyleSheet("font-size: 16px; font-weight: 700; color: #d8dee9;")
        layout.addWidget(title)

        self.value_label = QtWidgets.QLabel("72")
        self.value_label.setAlignment(QtCore.Qt.AlignCenter)
        self.value_label.setStyleSheet("font-size: 34px; font-weight: 800; color: #88c0d0;")
        layout.addWidget(self.value_label)

        self.state_label = QtWidgets.QLabel("idle")
        self.state_label.setAlignment(QtCore.Qt.AlignCenter)
        self.state_label.setStyleSheet("font-size: 11px; color: #8ea3b8;")
        layout.addWidget(self.state_label)

        self.slider = QtWidgets.QSlider(QtCore.Qt.Vertical)
        self.slider.setRange(0, 200)
        self.slider.setTickInterval(10)
        self.slider.setTickPosition(QtWidgets.QSlider.TicksBothSides)
        self.slider.setSingleStep(1)
        self.slider.setPageStep(5)
        self.slider.setMinimumHeight(240)
        self.slider.valueChanged.connect(self._handle_value_changed)
        layout.addWidget(self.slider, 1, QtCore.Qt.AlignHCenter)

        footer = QtWidgets.QLabel("Mock physiological stream")
        footer.setAlignment(QtCore.Qt.AlignCenter)
        footer.setStyleSheet("font-size: 11px; color: #81a1c1;")
        layout.addWidget(footer)

        self._close_callback = None
        self.widget.closeEvent = self._close_event

    def _close_event(self, event):
        self.widget.hide()
        if callable(self._close_callback):
            self._close_callback()
        event.ignore()

    def on_hide(self, callback):
        self._close_callback = callback

    def _handle_value_changed(self, value):
        self._addon.set_bpm(int(value), from_window=True)

    def set_bpm(self, value: int):
        current = int(self.slider.value())
        target = int(value)
        if current != target:
            self.slider.blockSignals(True)
            self.slider.setValue(target)
            self.slider.blockSignals(False)
        self.value_label.setText(str(target))
        if target <= 0:
            state = "offline"
        elif target < 55:
            state = "calm"
        elif target <= 95:
            state = "steady"
        elif target <= 130:
            state = "elevated"
        else:
            state = "spiking"
        self.state_label.setText(state)

    def show(self):
        self.widget.show()
        self.widget.raise_()
        self.widget.activateWindow()

    def hide(self):
        self.widget.hide()

    def is_visible(self) -> bool:
        return bool(self.widget.isVisible())


class Addon(BaseAddon):
    def initialize(self, context):
        super().initialize(context)
        from PySide6 import QtCore

        self.current_bpm = 72
        self.last_updated_at = time.time()
        self._window_visible = False
        self._tab_refreshers = []
        self.service = MockHeartRateService(self)
        self.window = MockHeartRateWindow(self)
        self.window.on_hide(self._on_window_hidden)
        self.window.set_bpm(self.current_bpm)

        context.services.register(
            "heart_rate.mock",
            self.service,
            metadata={
                "kind": "physiology",
                "unit": "bpm",
                "range": [0, 200],
            },
        )

        sensory_service = context.get_service("qt.sensory")
        if sensory_service is not None:
            sensory_service.register_provider(
                provider_id="heart_rate",
                label="Heart Rate",
                instruction="Hidden sensory input may include the user's current heart rate in BPM.",
                description="Text-only heart-rate provider published by the Mock Heart Rate addon.",
                order=280,
                capture_handler=self._capture_sensory_snapshot,
                metadata={
                    "kind": "physiology",
                    "unit": "bpm",
                    "prompt_fragment_enabled": False,
                    "ping_payload": [
                        {"field": "content", "description": "This is the user's current heart rate in BPM"},
                        {"field": "metadata.kind", "description": "physiology"},
                        {"field": "metadata.metric", "description": "heart_rate_bpm"},
                        {"field": "metadata.unit", "description": "bpm"},
                        {"field": "metadata.value", "description": "<current BPM integer>"},
                    ],
                },
            )

        context.ui.register_manifest_designer_tab(
            id="heart_rate_source_tab",
            binder=self._bind_designer_tab,
        )

        self._tick_timer = QtCore.QTimer()
        self._tick_timer.setInterval(100)
        self._tick_timer.timeout.connect(self._pump_subscribers)
        self._tick_timer.start()
        context.logger.info("Mock heart-rate addon initialized.")

    def _ui_child(self, root, name, cls=None):
        from PySide6 import QtCore

        if root is None:
            return None
        try:
            return root.findChild(cls or QtCore.QObject, name)
        except Exception:
            return None

    def _bind_designer_tab(self, widget, _context):
        from PySide6 import QtWidgets

        status_label = self._ui_child(widget, "mock_heart_rate_status_label", QtWidgets.QLabel)
        show_button = self._ui_child(widget, "btn_mock_heart_rate_show", QtWidgets.QPushButton)
        hide_button = self._ui_child(widget, "btn_mock_heart_rate_hide", QtWidgets.QPushButton)
        reset_button = self._ui_child(widget, "btn_mock_heart_rate_reset", QtWidgets.QPushButton)
        details = self._ui_child(widget, "mock_heart_rate_details", QtWidgets.QPlainTextEdit)

        if any(item is None for item in (status_label, show_button, hide_button, reset_button, details)):
            raise RuntimeError("Mock Heart Rate Designer UI is missing one or more required controls.")

        show_button.clicked.connect(lambda: self.show_window())
        hide_button.clicked.connect(lambda: self.hide_window())
        reset_button.clicked.connect(lambda: self.set_bpm(72))
        details.setReadOnly(True)
        details.setPlainText(
            "\n".join(
                [
                    "Peer service: heart_rate.mock",
                    "Provider id: heart_rate",
                    "Example addon usage:",
                    "  service = context.services.get('heart_rate.mock')",
                    "  bpm = service.current_bpm()",
                    "  token = service.subscribe(callback, interval_seconds=0.5)",
                ]
            )
        )

        def refresh_from_state():
            status_label.setText(
                f"Current BPM: {int(self.current_bpm)}\n"
                f"Window visible: {'yes' if self.is_window_visible() else 'no'}"
            )
            status_label.update()

        self._register_tab_refresher(refresh_from_state)
        widget.destroyed.connect(lambda *_args, cb=refresh_from_state: self._unregister_tab_refresher(cb))
        refresh_from_state()
        return widget

    def _build_tab(self, context):
        from PySide6 import QtCore, QtWidgets

        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)

        intro = QtWidgets.QLabel(
            "This addon exposes a floating BPM slider, a reusable peer service named "
            "`heart_rate.mock`, and a selectable text-based sensory provider for the hidden Vision loop."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        status_label = QtWidgets.QLabel()
        status_label.setAlignment(QtCore.Qt.AlignLeft)
        layout.addWidget(status_label)

        button_row = QtWidgets.QHBoxLayout()
        show_button = QtWidgets.QPushButton("Show Window")
        hide_button = QtWidgets.QPushButton("Hide Window")
        reset_button = QtWidgets.QPushButton("Reset 72")
        button_row.addWidget(show_button)
        button_row.addWidget(hide_button)
        button_row.addWidget(reset_button)
        layout.addLayout(button_row)

        show_button.clicked.connect(lambda: self.show_window())
        hide_button.clicked.connect(lambda: self.hide_window())
        reset_button.clicked.connect(lambda: self.set_bpm(72))

        details = QtWidgets.QPlainTextEdit()
        details.setReadOnly(True)
        details.setPlainText(
            "\n".join(
                [
                    "Peer service: heart_rate.mock",
                    "Provider id: heart_rate",
                    "Example addon usage:",
                    "  service = context.services.get('heart_rate.mock')",
                    "  bpm = service.current_bpm()",
                    "  token = service.subscribe(callback, interval_seconds=0.5)",
                ]
            )
        )
        layout.addWidget(details, 1)
        layout.addStretch(1)

        def refresh_from_state():
            status_label.setText(
                f"Current BPM: {int(self.current_bpm)}\n"
                f"Window visible: {'yes' if self.is_window_visible() else 'no'}"
            )
            status_label.update()

        self._register_tab_refresher(refresh_from_state)
        widget.destroyed.connect(lambda *_args, cb=refresh_from_state: self._unregister_tab_refresher(cb))
        refresh_from_state()
        return widget

    def _register_tab_refresher(self, callback):
        if callable(callback):
            self._tab_refreshers.append(callback)

    def _unregister_tab_refresher(self, callback):
        self._tab_refreshers = [item for item in list(self._tab_refreshers or []) if item is not callback]

    def _notify_tab_refreshers(self):
        keep = []
        for callback in list(self._tab_refreshers or []):
            try:
                callback()
                keep.append(callback)
            except RuntimeError:
                pass
            except Exception:
                pass
        self._tab_refreshers = keep

    def _capture_sensory_snapshot(self, capture_context=None):
        bpm = int(self.current_bpm)
        return {
            "source": "heart_rate",
            "captured_at": time.time(),
            "content": "This is the user's current heart rate in BPM",
            "metadata": {
                "kind": "physiology",
                "metric": "heart_rate_bpm",
                "unit": "bpm",
                "value": bpm,
            },
        }

    def _pump_subscribers(self):
        self.service.emit_if_due(force=False)

    def _on_window_hidden(self):
        self._window_visible = False
        self._refresh_tab_status()

    def _refresh_tab_status(self):
        self._notify_tab_refreshers()

    def is_window_visible(self) -> bool:
        window = getattr(self, "window", None)
        if window is None:
            return False
        return bool(window.is_visible())

    def show_window(self):
        window = getattr(self, "window", None)
        if window is None:
            return
        self._window_visible = True
        window.show()
        self._refresh_tab_status()

    def hide_window(self):
        window = getattr(self, "window", None)
        if window is None:
            return
        window.hide()
        self._window_visible = False
        self._refresh_tab_status()

    def set_bpm(self, value: int, *, from_window: bool = False) -> int:
        bpm = max(0, min(200, int(value)))
        self.current_bpm = bpm
        self.last_updated_at = time.time()
        if getattr(self, "window", None) is not None:
            self.window.set_bpm(bpm)
        self._refresh_tab_status()
        self.service.emit_if_due(force=True)
        if getattr(self, "context", None) is not None:
            self.context.events.publish(
                "sensor.heart_rate.updated",
                {
                    "source": "heart_rate",
                    "bpm": bpm,
                    "updated_at": self.last_updated_at,
                },
            )
        return bpm

    def export_session_state(self):
        return {
            "mock_heart_rate_bpm": int(self.current_bpm),
            "mock_heart_rate_window_visible": bool(self.is_window_visible()),
        }

    def export_preset_state(self):
        return self.export_session_state()

    def import_session_state(self, session):
        state = dict(session or {})
        bpm = int(state.get("mock_heart_rate_bpm", self.current_bpm) or self.current_bpm)
        self.set_bpm(bpm)
        visible = bool(state.get("mock_heart_rate_window_visible", False))
        if visible:
            self.show_window()
        else:
            self.hide_window()
        return None

    def import_preset_state(self, preset):
        return self.import_session_state(preset)

    def shutdown(self):
        timer = getattr(self, "_tick_timer", None)
        if timer is not None:
            timer.stop()
        sensory_service = self.context.get_service("qt.sensory") if getattr(self, "context", None) is not None else None
        if sensory_service is not None:
            try:
                sensory_service.unregister_provider("heart_rate")
            except Exception:
                pass
        window = getattr(self, "window", None)
        if window is not None:
            try:
                window.hide()
                window.widget.deleteLater()
            except Exception:
                pass
        self._tab_refreshers = []
        return None

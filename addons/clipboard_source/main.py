from pathlib import Path
import hashlib
import time

from PySide6 import QtCore, QtWidgets

from core.addons.base import BaseAddon


class Addon(BaseAddon):
    TAB_ID = "clipboard_source_tab"

    def initialize(self, context):
        super().initialize(context)
        self.auto_attach_next_user_turn = False
        self.auto_send_immediately = False
        self.hidden_loop_enabled = False
        self.latest_image_path = ""
        self.latest_image_hash = ""
        self.latest_captured_at = 0.0
        self.latest_image_is_new = False
        self.last_auto_attached_image_hash = ""
        self.last_delivery_status = "No clipboard image captured yet."
        self._tab_refreshers = []
        self._shell_preview = bool(context.get_service("qt.clipboard_source_shell_preview"))
        if self._shell_preview:
            self.last_delivery_status = "Shell preview: clipboard monitoring, capture, and send actions are disabled."

        sensory_service = context.get_service("qt.sensory")
        if sensory_service is not None and not self._shell_preview:
            sensory_service.register_provider(
                provider_id="clipboard",
                label="Clipboard",
                instruction=(
                    "Optional clipboard reference image may be attached as hidden ambient context or "
                    "armed for the next user turn when a copied image is available."
                ),
                order=120,
                capture_handler=self._capture_sensory_snapshot,
                metadata={
                    "kind": "image",
                    "prompt_fragment_enabled": False,
                },
            )

        context.ui.register_tab(
            id=self.TAB_ID,
            title="Source",
            area="vision_source",
            parent_tab_id="clipboard",
            order=100,
            tooltip="Clipboard image source controls and status.",
            factory=self._build_tab,
        )

        self._clipboard = None
        if not self._shell_preview:
            clipboard = QtWidgets.QApplication.clipboard()
            self._clipboard = clipboard
            if clipboard is not None:
                clipboard.dataChanged.connect(self._on_clipboard_changed)
        context.logger.info("Clipboard source addon initialized.")

    def shutdown(self):
        clipboard = getattr(self, "_clipboard", None)
        if clipboard is not None:
            try:
                clipboard.dataChanged.disconnect(self._on_clipboard_changed)
            except Exception:
                pass
        sensory_service = self.context.get_service("qt.sensory") if getattr(self, "context", None) is not None else None
        if sensory_service is not None:
            try:
                sensory_service.unregister_provider("clipboard")
            except Exception:
                pass
        if not getattr(self, "_shell_preview", False):
            self._clear_pending_next_user_turn()
        self._tab_refreshers = []
        return None

    def export_session_state(self):
        return {
            "clipboard_source_auto_attach_next_user_turn": bool(self.auto_attach_next_user_turn),
            "clipboard_source_auto_send_immediately": bool(self.auto_send_immediately),
            "clipboard_source_hidden_loop_enabled": bool(self.hidden_loop_enabled),
        }

    def export_preset_state(self):
        return self.export_session_state()

    def import_session_state(self, session):
        payload = dict(session or {})
        self.auto_attach_next_user_turn = bool(payload.get("clipboard_source_auto_attach_next_user_turn", self.auto_attach_next_user_turn))
        self.auto_send_immediately = bool(payload.get("clipboard_source_auto_send_immediately", self.auto_send_immediately))
        self.hidden_loop_enabled = bool(payload.get("clipboard_source_hidden_loop_enabled", self.hidden_loop_enabled))
        if self.auto_send_immediately and self.hidden_loop_enabled:
            self.hidden_loop_enabled = False
        if getattr(self, "_shell_preview", False):
            self.last_delivery_status = "Shell preview: clipboard source settings are display-only."
            self._notify_tab_refreshers()
            return None
        if self.auto_attach_next_user_turn and self._source_is_enabled() and self._has_latest_image():
            self._arm_latest_for_next_user_turn(silent_missing=True, require_new_image=True, mark_auto_attach=True)
        elif not self._source_is_enabled():
            self._clear_pending_next_user_turn()
        self._notify_tab_refreshers()
        return None

    def import_preset_state(self, preset):
        return self.import_session_state(preset)

    def _build_tab(self, _context):
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        intro = QtWidgets.QLabel(
            "Clipboard is a user-curated Vision source. Copy an image with Snipping Tool or another app, "
            "then use it as a manual image send, the next user-turn attachment, or optional hidden-loop context."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        checkbox_column = QtWidgets.QVBoxLayout()
        checkbox_column.setContentsMargins(0, 0, 0, 0)
        checkbox_column.setSpacing(6)

        attach_checkbox = QtWidgets.QCheckBox("Attach newest clipboard image to the next user turn")
        attach_checkbox.toggled.connect(self._on_auto_attach_toggled)
        checkbox_column.addWidget(attach_checkbox)

        send_now_checkbox = QtWidgets.QCheckBox("Send newest clipboard image immediately when it appears")
        send_now_checkbox.toggled.connect(self._on_auto_send_toggled)
        checkbox_column.addWidget(send_now_checkbox)

        hidden_loop_checkbox = QtWidgets.QCheckBox("Include the latest clipboard image in the hidden Vision loop")
        hidden_loop_checkbox.toggled.connect(self._on_hidden_loop_toggled)
        checkbox_column.addWidget(hidden_loop_checkbox)

        layout.addLayout(checkbox_column)

        button_row = QtWidgets.QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(8)
        send_button = QtWidgets.QPushButton("Send Now")
        send_button.clicked.connect(lambda: self._send_latest_now(print_if_missing=True))
        arm_button = QtWidgets.QPushButton("Arm Next Turn")
        arm_button.clicked.connect(lambda: self._arm_latest_for_next_user_turn(print_if_missing=True))
        clear_button = QtWidgets.QPushButton("Clear Latest")
        clear_button.clicked.connect(self._clear_latest_image)
        button_row.addWidget(send_button)
        button_row.addWidget(arm_button)
        button_row.addWidget(clear_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        status_label = QtWidgets.QLabel()
        status_label.setWordWrap(True)
        status_label.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        layout.addWidget(status_label)
        layout.addStretch(1)

        if getattr(self, "_shell_preview", False):
            for control in (attach_checkbox, send_now_checkbox, hidden_loop_checkbox, send_button, arm_button, clear_button):
                control.setEnabled(False)
                control.setToolTip("Disabled in the main.ui shell preview; clipboard monitoring and runtime delivery are not started.")

        def refresh_from_state():
            for checkbox, checked in [
                (attach_checkbox, self.auto_attach_next_user_turn),
                (send_now_checkbox, self.auto_send_immediately),
                (hidden_loop_checkbox, self.hidden_loop_enabled),
            ]:
                checkbox.blockSignals(True)
                checkbox.setChecked(bool(checked))
                checkbox.blockSignals(False)
            status_label.setText(self._status_text())
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

    def _notify_settings_changed(self):
        shell = self.context.get_service("qt.shell") if getattr(self, "context", None) is not None else None
        notifier = getattr(shell, "notify_settings_changed", None)
        if callable(notifier):
            try:
                notifier()
            except Exception:
                pass

    def _clipboard_image_dir(self) -> Path:
        target = Path("runtime") / "clipboard_inputs"
        target.mkdir(parents=True, exist_ok=True)
        return target

    def _clipboard_png_bytes(self):
        if getattr(self, "_shell_preview", False):
            return b""
        clipboard = getattr(self, "_clipboard", None) or QtWidgets.QApplication.clipboard()
        if clipboard is None:
            return b""
        image = clipboard.image()
        if image.isNull():
            pixmap = clipboard.pixmap()
            if not pixmap.isNull():
                image = pixmap.toImage()
        if image.isNull():
            return b""
        buffer = QtCore.QBuffer()
        if not buffer.open(QtCore.QIODevice.WriteOnly):
            return b""
        ok = image.save(buffer, "PNG")
        payload = bytes(buffer.data()) if ok else b""
        buffer.close()
        return payload

    def _capture_current_clipboard_image(self, *, trigger_actions: bool, allow_existing: bool = False) -> bool:
        if getattr(self, "_shell_preview", False):
            return False
        if not self._source_is_enabled():
            if trigger_actions:
                self._clear_pending_next_user_turn()
                self.last_delivery_status = "Clipboard source is disabled; copied images are ignored."
                self._notify_tab_refreshers()
            return False
        payload = self._clipboard_png_bytes()
        if not payload:
            return False
        digest = hashlib.sha256(payload).hexdigest()
        if not allow_existing and digest == self.latest_image_hash and self._has_latest_image():
            return False
        target = self._clipboard_image_dir() / f"clipboard_{int(time.time() * 1000)}.png"
        target.write_bytes(payload)
        self.latest_image_path = str(target.resolve())
        self.latest_image_hash = digest
        self.latest_captured_at = time.time()
        self.latest_image_is_new = True
        self.last_delivery_status = f"Captured clipboard image at {self._format_timestamp(self.latest_captured_at)}."
        print(f"📋 [Clipboard] Captured new clipboard image: {self.latest_image_path}")
        if trigger_actions:
            self._apply_new_image_delivery_rules()
        self._notify_tab_refreshers()
        return True

    def _apply_new_image_delivery_rules(self):
        if not self._source_is_enabled():
            self._clear_pending_next_user_turn()
            self.last_delivery_status = "Clipboard source is disabled, so copied images will not auto-send or arm."
            self._notify_tab_refreshers()
            return
        delivered = False
        if self.auto_send_immediately:
            delivered = self._send_latest_now(silent_missing=True, update_status=False)
            if not delivered and not self._is_engine_running():
                self.last_delivery_status = "New clipboard image captured, but auto-send is waiting for the engine to run."
        if self.auto_attach_next_user_turn and not delivered:
            armed = self._arm_latest_for_next_user_turn(
                silent_missing=True,
                update_status=False,
                require_new_image=True,
                mark_auto_attach=True,
            )
            if armed:
                self.last_delivery_status = "New clipboard image armed for the next user turn."
        self._notify_tab_refreshers()

    def _on_clipboard_changed(self):
        self._capture_current_clipboard_image(trigger_actions=True, allow_existing=False)

    def _has_latest_image(self) -> bool:
        path = str(self.latest_image_path or "").strip()
        return bool(path and Path(path).is_file())

    def _ensure_latest_image(self) -> bool:
        if self._has_latest_image():
            return True
        return self._capture_current_clipboard_image(trigger_actions=False, allow_existing=True)

    def _engine_module(self):
        import engine
        return engine

    def _source_is_enabled(self) -> bool:
        if getattr(self, "_shell_preview", False):
            return False
        try:
            raw_value = self._engine_module().RUNTIME_CONFIG.get("sensory_feedback_source", "off")
        except Exception:
            return False
        if isinstance(raw_value, (list, tuple, set)):
            tokens = [str(item or "").strip().lower() for item in list(raw_value or [])]
        else:
            tokens = [part.strip().lower() for part in str(raw_value or "off").split(",")]
        return "clipboard" in {token for token in tokens if token and token != "off"}

    def _is_engine_running(self) -> bool:
        replay = self.context.get_service("qt.chat_replay") if getattr(self, "context", None) is not None else None
        if replay is None:
            return False
        checker = getattr(replay, "is_engine_running", None)
        if callable(checker):
            try:
                return bool(checker())
            except Exception:
                return False
        return False

    def _clear_pending_next_user_turn(self):
        if getattr(self, "_shell_preview", False):
            return
        try:
            self._engine_module().clear_pending_user_image_attachment()
        except Exception:
            pass

    def _arm_latest_for_next_user_turn(
        self,
        *,
        print_if_missing: bool = False,
        silent_missing: bool = False,
        update_status: bool = True,
        require_new_image: bool = False,
        mark_auto_attach: bool = False,
    ) -> bool:
        if not self._ensure_latest_image():
            if print_if_missing and not silent_missing:
                print("[Clipboard] No clipboard image is available to arm for the next user turn.")
            return False
        latest_hash = str(self.latest_image_hash or "").strip()
        if require_new_image and latest_hash and latest_hash == str(self.last_auto_attached_image_hash or "").strip():
            self.last_delivery_status = "Latest clipboard image was already armed once; waiting for a new clipboard image."
            if update_status:
                self._notify_tab_refreshers()
            return False
        try:
            self._engine_module().set_pending_user_image_attachment(self.latest_image_path, source="clipboard")
        except Exception as exc:
            print(f"[Clipboard] Could not arm the clipboard image for the next user turn: {exc}")
            return False
        if mark_auto_attach:
            self.last_auto_attached_image_hash = latest_hash
        if update_status:
            self.last_delivery_status = f"Armed for the next user turn at {self._format_timestamp(time.time())}."
            self._notify_tab_refreshers()
        return True

    def _send_latest_now(self, *, print_if_missing: bool = False, silent_missing: bool = False, update_status: bool = True) -> bool:
        if not self._ensure_latest_image():
            if print_if_missing and not silent_missing:
                print("[Clipboard] No clipboard image is available to send.")
            return False
        if not self._is_engine_running():
            if print_if_missing and not silent_missing:
                print("[Clipboard] Start the engine before sending a clipboard image immediately.")
            return False
        try:
            self._engine_module().queue_user_image_turn(
                self.latest_image_path,
                content="Please respond to the image I just sent you.",
                source="clipboard",
            )
        except Exception as exc:
            print(f"[Clipboard] Clipboard image send failed: {exc}")
            return False
        if update_status:
            self.last_delivery_status = f"Sent immediately at {self._format_timestamp(time.time())}."
            self._notify_tab_refreshers()
        return True

    def _clear_latest_image(self):
        self.latest_image_path = ""
        self.latest_image_hash = ""
        self.latest_captured_at = 0.0
        self.latest_image_is_new = False
        self.last_auto_attached_image_hash = ""
        self.last_delivery_status = "Cleared the latest clipboard image."
        self._clear_pending_next_user_turn()
        self._notify_tab_refreshers()

    def _on_auto_attach_toggled(self, checked):
        if getattr(self, "_shell_preview", False):
            self.last_delivery_status = "Shell preview: next-turn clipboard attachment is disabled."
            self._notify_tab_refreshers()
            return
        self.auto_attach_next_user_turn = bool(checked)
        if self.auto_attach_next_user_turn:
            if self._source_is_enabled():
                self._arm_latest_for_next_user_turn(silent_missing=True, mark_auto_attach=True)
            else:
                self._clear_pending_next_user_turn()
                self.last_delivery_status = "Next-turn clipboard attach is configured, but Clipboard source is currently disabled."
                self._notify_tab_refreshers()
        else:
            self._clear_pending_next_user_turn()
            self.last_delivery_status = "Next-turn clipboard attachment disabled."
            self._notify_tab_refreshers()
        self._notify_settings_changed()

    def _on_auto_send_toggled(self, checked):
        if getattr(self, "_shell_preview", False):
            self.last_delivery_status = "Shell preview: immediate clipboard auto-send is disabled."
            self._notify_tab_refreshers()
            return
        self.auto_send_immediately = bool(checked)
        if self.auto_send_immediately and self.hidden_loop_enabled:
            self.hidden_loop_enabled = False
        self.last_delivery_status = "Immediate clipboard auto-send enabled." if self.auto_send_immediately else "Immediate clipboard auto-send disabled."
        self._notify_tab_refreshers()
        self._notify_settings_changed()

    def _on_hidden_loop_toggled(self, checked):
        if getattr(self, "_shell_preview", False):
            self.last_delivery_status = "Shell preview: hidden-loop clipboard feed is disabled."
            self._notify_tab_refreshers()
            return
        self.hidden_loop_enabled = bool(checked)
        if self.hidden_loop_enabled and self.auto_send_immediately:
            self.auto_send_immediately = False
        self.last_delivery_status = (
            "Clipboard source will now feed the hidden Vision loop when selected."
            if self.hidden_loop_enabled
            else "Clipboard source hidden-loop feed disabled."
        )
        self._notify_tab_refreshers()
        self._notify_settings_changed()

    def _status_text(self) -> str:
        latest_line = "Latest clipboard image: none captured yet."
        if self._has_latest_image():
            latest_line = (
                f"Latest clipboard image: {Path(self.latest_image_path).name} "
                f"(captured {self._format_timestamp(self.latest_captured_at)})."
            )
        return "\n".join(
            [
                latest_line,
                f"Clipboard source include: {'on' if self._source_is_enabled() else 'off'}",
                f"Next user turn attach: {'armed when possible' if self.auto_attach_next_user_turn else 'off'}",
                f"Immediate auto-send: {'on' if self.auto_send_immediately else 'off'}",
                f"Hidden Vision loop feed: {'on' if self.hidden_loop_enabled else 'off'}",
                self.last_delivery_status,
            ]
        )

    def _format_timestamp(self, stamp: float) -> str:
        try:
            if float(stamp or 0.0) <= 0:
                return "n/a"
            return time.strftime("%H:%M:%S", time.localtime(float(stamp)))
        except Exception:
            return "n/a"

    def _capture_sensory_snapshot(self, capture_context=None):
        if getattr(self, "_shell_preview", False):
            return None
        if not self._source_is_enabled() or not self.hidden_loop_enabled:
            return None
        if not self._has_latest_image() and not self._ensure_latest_image():
            return None
        is_new = bool(self.latest_image_is_new)
        snapshot = {
            "captured_at": float(self.latest_captured_at or time.time()),
            "image_path": str(self.latest_image_path),
            "source": "clipboard",
            "content_text": (
                "Hidden sensory feedback only, not a user request. Source: clipboard reference image. "
                + (
                    "This clipboard image is NEW since the last clipboard image."
                    if is_new
                    else "This clipboard image is unchanged from the previous clipboard image."
                )
            ),
        }
        self.latest_image_is_new = False
        return snapshot

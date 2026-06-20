from __future__ import annotations

import argparse
import json
import sys
import threading
from pathlib import Path
from typing import Any

from PySide6 import QtCore, QtWidgets


def _bootstrap_imports(app_root: Path) -> None:
    root = str(app_root)
    if root not in sys.path:
        sys.path.insert(0, root)


class _MessageRelay(QtCore.QObject):
    message_received = QtCore.Signal(dict)


class ExternalAIPresenceRuntime(QtCore.QObject):
    def __init__(self, app_root: Path):
        super().__init__()
        _bootstrap_imports(app_root)
        from visual_presence.visual_presence_controller import VisualPresenceController

        self.app_root = Path(app_root)
        self.controller = VisualPresenceController(None, {})

    def handle_message(self, message: dict[str, Any]) -> None:
        msg_type = str((message or {}).get("type") or "").strip().lower()
        if msg_type == "shutdown":
            self.shutdown()
            QtWidgets.QApplication.quit()
            return
        if msg_type == "settings":
            self.controller.request_settings(self._local_settings(dict(message.get("settings") or {})))
            return
        if msg_type == "state":
            self.controller.request_ai_state(message.get("state"))
            return
        if msg_type == "audio_level":
            self.controller.request_audio_level(message.get("level", 0.0))
            return
        if msg_type == "music_level":
            self.controller.request_music_level(message.get("level", 0.0))
            return
        if msg_type == "mood":
            self.controller.request_presence_mood(message.get("mood", "neutral"))
            return
        if msg_type == "reset_floating_position":
            self.controller.request_reset_floating_position()
            return

    def _local_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        payload = dict(settings or {})
        payload["ai_presence_external_runtime_enabled"] = False
        return payload

    def shutdown(self) -> None:
        try:
            self.controller.shutdown()
        except Exception:
            pass


def _read_stdin(relay: _MessageRelay) -> None:
    for line in sys.stdin:
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except Exception as exc:
            print(f"Invalid AI Presence external IPC payload: {exc}", flush=True)
            continue
        if isinstance(payload, dict):
            relay.message_received.emit(payload)
    relay.message_received.emit({"type": "shutdown"})


def main() -> int:
    parser = argparse.ArgumentParser(description="AI Presence external animation runtime")
    parser.add_argument("--app-root", required=True)
    parser.add_argument("--check", action="store_true", help="Verify imports and assets without opening overlay windows.")
    args = parser.parse_args()
    app_root = Path(args.app_root).resolve()
    _bootstrap_imports(app_root)
    if args.check:
        from visual_presence.visual_presence_bridge import VisualPresenceBridge

        qml_path = Path(__file__).with_name("visual_overlay.qml")
        if not qml_path.exists():
            print(f"Missing AI Presence QML: {qml_path}", flush=True)
            return 2
        bridge = VisualPresenceBridge()
        bridge.apply_settings({"ai_presence_enabled": True, "ai_presence_display_mode": "floating"})
        print("AI Presence external runtime check passed.", flush=True)
        return 0

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1])
    runtime = ExternalAIPresenceRuntime(app_root)
    relay = _MessageRelay()
    relay.message_received.connect(runtime.handle_message, QtCore.Qt.QueuedConnection)
    reader = threading.Thread(target=_read_stdin, args=(relay,), daemon=True, name="ai-presence-external-ipc")
    reader.start()
    print("AI Presence external runtime ready.", flush=True)
    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())

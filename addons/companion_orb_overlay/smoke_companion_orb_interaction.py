from __future__ import annotations

import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def main() -> None:
    from addons.companion_orb_overlay.companion_orb.external_runtime_client import _parse_event_line

    drop_event = _parse_event_line('{"type":"orb.dropped","center":[10,20],"top_left":[1,2],"button":"left"}')
    if drop_event != {"type": "orb.dropped", "center": [10, 20], "top_left": [1, 2], "button": "left"}:
        raise AssertionError(f"External event parser returned unexpected payload: {drop_event!r}")
    if _parse_event_line("Companion Orb external runtime ready.") is not None:
        raise AssertionError("External event parser should ignore non-JSON log lines")

    external_runtime = (
        ROOT_DIR
        / "addons"
        / "companion_orb_overlay"
        / "companion_orb"
        / "external_orb_runtime.py"
    ).read_text(encoding="utf-8")
    runtime_client = (
        ROOT_DIR
        / "addons"
        / "companion_orb_overlay"
        / "companion_orb"
        / "external_runtime_client.py"
    ).read_text(encoding="utf-8")
    main_controller = (
        ROOT_DIR
        / "addons"
        / "companion_orb_overlay"
        / "companion_orb"
        / "companion_orb_controller.py"
    ).read_text(encoding="utf-8")

    required_fragments = {
        "self.drag_offset": "external runtime keeps normal Qt drag state",
        "self.poll_drag_timer": "external runtime polls click-through drags",
        "def eventFilter(self, watched, event):": "external runtime handles direct mouse events",
        "def _poll_pointer_drag(self)": "external runtime handles click-through mouse drags",
        "window.grabMouse()": "external runtime captures mouse input for direct drags",
        "window.releaseMouse()": "external runtime releases mouse input after direct drags",
        "def _emit_position_changed(self)": "external runtime emits final position changes through a helper",
        "self._record_drag_position(point)": "dragged position updates the external runtime home point",
        "widget.installEventFilter(self)": "external runtime receives direct mouse events when click-through is off",
        "def _emit_event(": "external runtime can send structured events back to main NC",
        '"type": "orb.dropped"': "external runtime emits drop events",
        '"type": "orb.request_menu"': "external runtime emits menu request events",
        '"type": "orb.position_changed"': "external runtime emits position-change events",
        'if msg_type == "cloak":': "external runtime supports main-process snapshot cloaking",
    }
    missing = [
        description
        for fragment, description in required_fragments.items()
        if fragment not in external_runtime
    ]
    if missing:
        raise AssertionError("Missing Companion Orb external interaction support: " + ", ".join(missing))

    record_start = external_runtime.index("def _record_drag_position")
    record_end = external_runtime.index("def _emit_position_changed", record_start)
    record_body = external_runtime[record_start:record_end]
    if '"type": "orb.position_changed"' in record_body:
        raise AssertionError("Per-frame drag recording must not emit bridge position events during drag")

    client_fragments = {
        "event_handler": "external runtime client accepts an event handler",
        "stdout=subprocess.PIPE": "external runtime client keeps stdout for JSON event lines",
        "stderr=self._log_handle": "external runtime client keeps stderr/logs out of stdout",
        "def _read_events_loop": "external runtime client reads events on a background thread",
        "_parse_event_line": "external runtime client parses event JSON lines safely",
    }
    missing_client = [
        description
        for fragment, description in client_fragments.items()
        if fragment not in runtime_client
    ]
    if missing_client:
        raise AssertionError("Missing Companion Orb external IPC client support: " + ", ".join(missing_client))

    controller_fragments = {
        "event_handler=self._queue_external_runtime_event": "main controller subscribes to external runtime events through the queued Qt bridge",
        "external_event_requested.connect(self._handle_external_runtime_event": "main controller routes external events on the Qt thread",
        "def _handle_external_runtime_event": "main controller has an external event dispatcher",
        "def _handle_external_orb_drop": "main controller handles external drop events",
        "def _handle_external_orb_menu_request": "main controller handles external menu request events",
        "def _handle_external_orb_position_changed": "main controller handles external position-change events",
        '"type": "cloak"': "main controller can cloak the external orb during snapshots",
    }
    missing_controller = [
        description
        for fragment, description in controller_fragments.items()
        if fragment not in main_controller
    ]
    if missing_controller:
        raise AssertionError("Missing Companion Orb main controller event bridge support: " + ", ".join(missing_controller))

    print("Companion Orb interaction smoke passed.")


if __name__ == "__main__":
    main()

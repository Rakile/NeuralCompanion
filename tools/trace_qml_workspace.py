r"""Run NC with a bounded, opt-in trace for QML workspace creation failures.

From the repository root:
    .venv\Scripts\python.exe -B tools\trace_qml_workspace.py

Open Persona, then copy the [NC QML trace] block from the console. This uses
the normal application entry point and settings. No settings or chat contents
are included in the trace. Tracing adds overhead for this diagnostic run only.
"""

from __future__ import annotations

from collections import deque
from pathlib import Path
import sys
import time
from types import FrameType
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
BRIDGE_FILE = str(REPO_ROOT / "ui/qml_bridge/application_bridge.py").casefold()
WATCHED_CALLS = frozenset({
    "viewAddon", "openAddonWorkspaceSection", "currentWorkspace",
    "activateMainWorkspace", "rememberNavigationSelection", "refreshAddonState",
    "_apply_addon_rail_layout", "refreshLiveAddonControls",
    "refreshIdentityRelayState", "_apply_identity_relay_payload",
    "personaOverrideCatalog", "personaOverrideRecord", "detachWorkspace",
    "dockWorkspaceInMain", "setMainDockPaneActive",
})
NAVIGATION_ARGUMENTS = frozenset({
    "addon_id", "key", "value", "zone", "selection", "section",
})


class WorkspaceTrace:
    """Keep recent call boundaries in memory; print them only on failure."""

    def __init__(self) -> None:
        self.events: deque[str] = deque(maxlen=100)
        self.started = time.monotonic()
        self.failures = 0
        self.previous_message_handler: Any = None

    def profile(self, frame: FrameType, event: str, arg: Any) -> None:
        if event not in {"call", "return"}:
            return
        code = frame.f_code
        if code.co_name not in WATCHED_CALLS or code.co_filename.casefold() != BRIDGE_FILE:
            return
        owner = frame.f_locals.get("self")
        state = vars(owner) if owner is not None else {}
        details = ""
        if event == "call":
            # Only navigation identifiers, never arbitrary payloads or records.
            details = " ".join(
                f"{name}={frame.f_locals[name]!r}"
                for name in code.co_varnames[1:code.co_argcount]
                if name in NAVIGATION_ARGUMENTS
                and isinstance(frame.f_locals.get(name), str)
                and len(frame.f_locals[name]) < 160
            )
        self.events.append(
            f"{time.monotonic() - self.started:9.3f}s {event:6} {code.co_name} "
            f"workspace={state.get('_workspace', '')!r} "
            f"addon={state.get('_selected_addon', '')!r} {details}".rstrip()
        )

    def message(self, kind: Any, context: Any, message: str) -> None:
        previous = self.previous_message_handler
        if previous is not None:
            previous(kind, context, message)
        else:
            print(message, file=sys.stderr, flush=True)
        if not any(text in message for text in (
            "Cannot create delegate", "Object or context destroyed during incubation",
        )):
            return
        self.failures += 1
        print("[NC QML trace] recent workspace calls:", file=sys.stderr)
        for entry in tuple(self.events):
            print(entry, file=sys.stderr)
        print("[NC QML trace] active Python call chain:", file=sys.stderr)
        frame = sys._getframe(1)
        while frame is not None:
            code = frame.f_code
            print(f"  {code.co_filename}:{frame.f_lineno} {code.co_name}", file=sys.stderr)
            frame = frame.f_back
        print("[NC QML trace] end", file=sys.stderr, flush=True)


def main() -> int:
    # Preserve the production environment setup before importing Qt.
    sys.path.insert(0, str(REPO_ROOT))
    from ui.qml_bridge.runtime_environment import configure_runtime_environment

    configure_runtime_environment()
    from PySide6 import QtCore
    import qt_app

    trace = WorkspaceTrace()
    previous_profile = sys.getprofile()
    previous_argv0 = sys.argv[0]
    sys.argv[0] = str(REPO_ROOT / "qt_app.py")
    trace.previous_message_handler = QtCore.qInstallMessageHandler(trace.message)
    sys.setprofile(trace.profile)
    print(
        f"[NC QML trace] Qt {QtCore.qVersion()}; open Persona to reproduce. "
        "Diagnostic tracing is enabled for this run only.",
        flush=True,
    )
    try:
        return qt_app.main()
    finally:
        sys.setprofile(previous_profile)
        sys.argv[0] = previous_argv0
        QtCore.qInstallMessageHandler(trace.previous_message_handler)
        print(f"[NC QML trace] captured {trace.failures} matching warnings.", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())

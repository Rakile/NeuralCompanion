"""Production launcher for NeuralCompanion's native QML desktop application."""

from __future__ import annotations

import sys

from ui.qml_bridge.runtime_environment import configure_runtime_environment


def _maybe_create_debug_bundle(argv: list[str]) -> None:
    if "--codex-debug-bundle" not in {
        str(arg or "").strip().lower() for arg in argv
    }:
        return
    from core.crash_diagnostics import create_manual_debug_bundle

    print(f"Codex debug bundle created: {create_manual_debug_bundle()}")
    raise SystemExit(0)


def main() -> int:
    """Start the single supported desktop shell: native Qt Quick/QML."""

    _maybe_create_debug_bundle(list(sys.argv[1:]))
    configure_runtime_environment()

    from core.runtime.production_desktop_process import get_application_facade
    from ui.app_entry import run_qt_app

    result = int(run_qt_app(get_application_facade()) or 0)
    from pathlib import Path
    from ui.desktop_restart import handle_desktop_exit

    return handle_desktop_exit(result, Path(__file__))


if __name__ == "__main__":
    raise SystemExit(main())

"""Runtime app entry helpers for the Qt desktop application."""

import sys

from PySide6 import QtCore, QtWidgets


def configure_app_entry_dependencies(namespace):
    """Inject qt_app-owned launch dependencies without importing qt_app here."""
    globals().update(dict(namespace or {}))


def run_qt_app(argv=None):
    """Run the default Qt app entry path after early shell/validation modes."""
    argv = list(sys.argv[1:] if argv is None else argv)
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    _install_no_wheel_input_guard(app)

    if len(argv) >= 1 and str(argv[0] or "").strip().lower() in {"--ui-preview", "--ui-file"}:
        ui_path = _resolve_ui_path(argv[1] if len(argv) >= 2 else "main.ui")
        if not ui_path.exists():
            raise FileNotFoundError(f"UI file not found: {ui_path}")
        window = _load_ui_preview_window(ui_path)
        current_title = str(window.windowTitle() or "").strip()
        window.setWindowTitle(f"{current_title} [UI Preview]" if current_title else "UI Preview")
        if isinstance(window, QtWidgets.QMainWindow):
            _configure_main_window_docking(window)
            window.setTabPosition(QtCore.Qt.AllDockWidgetAreas, QtWidgets.QTabWidget.North)
        window.show()
        sys.exit(app.exec())

    if len(argv) >= 1 and str(argv[0] or "").strip().lower() == "--ui-real":
        ui_arg = argv[1] if len(argv) >= 2 and not str(argv[1] or "").startswith("--") else "main.ui"
        runtime_smoke = any(str(item or "").strip().lower() == "--runtime-smoke" for item in argv[1:])
        session_backup = None
        session_existed = False
        if runtime_smoke:
            try:
                session_existed = bool(SESSION_PATH.exists())
                session_backup = SESSION_PATH.read_bytes() if session_existed else None
            except Exception:
                session_backup = None
                session_existed = False
        _configure_real_ui_bridge_dependencies()
        bridge = MainUiRealRuntimeBridge(ui_arg, session_read_only=runtime_smoke)
        if runtime_smoke:
            try:
                summary = bridge.smoke_summary()
                print(f"[UI Real Smoke] File: {summary['ui_path']}")
                print(f"[UI Real Smoke] Window class: {summary['window_class']}")
                print(f"[UI Real Smoke] Hidden backend runtime window: {'yes' if summary['backend_hidden'] else 'no'}")
                print("[UI Real Smoke] Lifecycle buttons: " + ", ".join(summary["lifecycle_buttons"] or ["none"]))
                print("[UI Real Smoke] Runtime action buttons: " + ", ".join(summary["runtime_action_buttons"] or ["none"]))
                print("[UI Real Smoke] Chat-context buttons: " + ", ".join(summary["chat_context_buttons"] or ["none"]))
                print(f"[UI Real Smoke] Console/chat mirroring bound: {'yes' if summary['console_chat_bound'] else 'no'}")
                print(f"[UI Real Smoke] Provider runtime redirected: {'yes' if summary['provider_runtime_redirected'] else 'no'}")
                print(f"[UI Real Smoke] Chat/session runtime redirected: {'yes' if summary['chat_session_runtime_redirected'] else 'no'}")
                print(f"[UI Real Smoke] Sensory runtime redirected: {'yes' if summary['sensory_runtime_redirected'] else 'no'}")
                print(
                    "[UI Real Smoke] Visual Reply runtime redirected: "
                    + ("yes" if summary["visual_reply_runtime_redirected"] else "no")
                    + (
                        f" ({summary['visual_reply_panel_class']})"
                        if summary.get("visual_reply_panel_class")
                        else ""
                    )
                )
                if summary["adopted_runtime_tabs"]:
                    print("[UI Real Smoke] Adopted runtime tabs:")
                    for target_name, titles in summary["adopted_runtime_tabs"].items():
                        print(f"  - {target_name}: {', '.join(titles)}")
                print("[UI Real Smoke] Sensory runtime tabs: " + ", ".join(summary["sensory_runtime_tabs"] or ["none"]))
                print(f"[UI Real Smoke] Runtime status line: {summary['runtime_status']}")
            finally:
                bridge.close()
                try:
                    if session_existed and session_backup is not None:
                        SESSION_PATH.write_bytes(session_backup)
                    elif not session_existed and SESSION_PATH.exists():
                        SESSION_PATH.unlink()
                except Exception as exc:
                    print(f"[UI Real Smoke] WARNING: Could not restore session file after smoke run: {exc}")
            sys.exit(0)
        bridge.show()
        sys.exit(app.exec())

    window = CompanionQtMainWindow()
    window.show()
    sys.exit(app.exec())

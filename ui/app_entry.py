"""Runtime app entry helpers for the Qt desktop application."""

import atexit
import faulthandler
import os
import sys
import threading
import time
import traceback
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from core import crash_diagnostics

_CRASH_LOG_HANDLE = None
_CRASH_LOG_PATH = None
_CRASH_LOG_DIRTY = False
_CRASH_BUNDLE_PATH = None
_ORIGINAL_SYS_EXCEPTHOOK = sys.excepthook
_ORIGINAL_THREADING_EXCEPTHOOK = getattr(threading, "excepthook", None)
_STARTUP_ONLY_CRASH_LOG_MAX_BYTES = 1024


def configure_app_entry_dependencies(namespace):
    """Inject qt_app-owned launch dependencies without importing qt_app here."""
    globals().update(dict(namespace or {}))


def _cleanup_empty_crash_log():
    """Remove startup-only crash logs after a clean app exit."""
    global _CRASH_LOG_HANDLE
    handle = _CRASH_LOG_HANDLE
    path = _CRASH_LOG_PATH
    if handle is not None:
        try:
            handle.flush()
        except Exception:
            pass
        try:
            handle.close()
        except Exception:
            pass
        _CRASH_LOG_HANDLE = None
    if _CRASH_LOG_DIRTY or path is None:
        return
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return
    meaningful_lines = [line for line in text.splitlines() if line.strip()]
    if len(meaningful_lines) == 1 and meaningful_lines[0].startswith("[CrashDiag] Started "):
        try:
            Path(path).unlink()
        except Exception:
            pass


def _prune_startup_only_crash_logs(log_dir):
    """Delete tiny startup-only diagnostics left by older clean launches."""
    try:
        candidates = list(Path(log_dir).glob("nc_crash_*.log"))
    except Exception:
        return
    for path in candidates:
        try:
            if path.stat().st_size > _STARTUP_ONLY_CRASH_LOG_MAX_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        meaningful_lines = [line for line in text.splitlines() if line.strip()]
        if len(meaningful_lines) == 1 and meaningful_lines[0].startswith("[CrashDiag] Started "):
            try:
                path.unlink()
            except Exception:
                pass


def _crash_diag_app_root():
    try:
        return Path(SESSION_PATH).resolve().parent
    except Exception:
        return Path.cwd()


def _crash_diag_runtime_config():
    engine_module = sys.modules.get("engine")
    payload = getattr(engine_module, "RUNTIME_CONFIG", {}) if engine_module is not None else {}
    return dict(payload or {}) if isinstance(payload, dict) else {}


def _write_codex_debug_bundle(reason, extra_context=None):
    global _CRASH_BUNDLE_PATH, _CRASH_LOG_DIRTY
    if _CRASH_BUNDLE_PATH is not None:
        return _CRASH_BUNDLE_PATH
    try:
        bundle_path = crash_diagnostics.create_debug_bundle(
            app_root=_crash_diag_app_root(),
            reason=str(reason or "crash"),
            crash_log_path=_CRASH_LOG_PATH,
            runtime_config=_crash_diag_runtime_config(),
            extra_context=dict(extra_context or {}),
        )
        _CRASH_BUNDLE_PATH = bundle_path
        _CRASH_LOG_DIRTY = True
        message = f"[CrashDiag] Codex debug bundle created: {bundle_path}"
        if _CRASH_LOG_HANDLE is not None:
            _CRASH_LOG_HANDLE.write(message + "\n")
            _CRASH_LOG_HANDLE.flush()
        print(message)
        return bundle_path
    except Exception as exc:
        _CRASH_LOG_DIRTY = True
        message = f"[CrashDiag] WARNING: Could not create Codex debug bundle: {exc}"
        try:
            if _CRASH_LOG_HANDLE is not None:
                _CRASH_LOG_HANDLE.write(message + "\n")
                _CRASH_LOG_HANDLE.flush()
        except Exception:
            pass
        print(message)
        return None


def _install_crash_diagnostics():
    """Keep a lightweight crash recorder active for random native/Qt/runtime exits."""
    global _CRASH_LOG_DIRTY, _CRASH_LOG_HANDLE, _CRASH_LOG_PATH
    if _CRASH_LOG_HANDLE is not None:
        return
    try:
        root = Path(SESSION_PATH).resolve().parent
    except Exception:
        root = Path.cwd()
    log_dir = root / "runtime" / "crash_dumps"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        _prune_startup_only_crash_logs(log_dir)
        log_path = log_dir / f"nc_crash_{time.strftime('%Y%m%d_%H%M%S')}.log"
        _CRASH_LOG_HANDLE = open(log_path, "a", encoding="utf-8", buffering=1)
        _CRASH_LOG_PATH = log_path
        _CRASH_LOG_DIRTY = False
    except Exception as exc:
        print(f"[CrashDiag] WARNING: Could not open crash log: {exc}")
        return

    _CRASH_LOG_HANDLE.write(
        f"[CrashDiag] Started {time.strftime('%Y-%m-%d %H:%M:%S')} pid={os.getpid()} argv={sys.argv!r}\n"
    )
    crash_diagnostics.record_console_text(
        f"[CrashDiag] Started {time.strftime('%Y-%m-%d %H:%M:%S')} pid={os.getpid()} argv={sys.argv!r}\n"
    )
    try:
        faulthandler.enable(file=_CRASH_LOG_HANDLE, all_threads=True)
    except Exception as exc:
        _CRASH_LOG_DIRTY = True
        _CRASH_LOG_HANDLE.write(f"[CrashDiag] faulthandler.enable failed: {exc}\n")

    def _sys_excepthook(exc_type, exc_value, exc_tb):
        global _CRASH_LOG_DIRTY
        _CRASH_LOG_DIRTY = True
        try:
            _CRASH_LOG_HANDLE.write("[CrashDiag] Unhandled main-thread exception:\n")
            traceback.print_exception(exc_type, exc_value, exc_tb, file=_CRASH_LOG_HANDLE)
            _CRASH_LOG_HANDLE.flush()
            _write_codex_debug_bundle(
                "main_thread_exception",
                {
                    "exception_type": getattr(exc_type, "__name__", str(exc_type)),
                    "exception": str(exc_value),
                },
            )
            _CRASH_LOG_HANDLE.flush()
        except Exception:
            pass
        _ORIGINAL_SYS_EXCEPTHOOK(exc_type, exc_value, exc_tb)

    def _threading_excepthook(args):
        global _CRASH_LOG_DIRTY
        _CRASH_LOG_DIRTY = True
        try:
            _CRASH_LOG_HANDLE.write(
                f"[CrashDiag] Unhandled thread exception in {getattr(args.thread, 'name', '<unknown>')}:\n"
            )
            traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback, file=_CRASH_LOG_HANDLE)
            _CRASH_LOG_HANDLE.flush()
            _write_codex_debug_bundle(
                "thread_exception",
                {
                    "thread": getattr(args.thread, "name", "<unknown>"),
                    "exception_type": getattr(args.exc_type, "__name__", str(args.exc_type)),
                    "exception": str(args.exc_value),
                },
            )
            _CRASH_LOG_HANDLE.flush()
        except Exception:
            pass
        if _ORIGINAL_THREADING_EXCEPTHOOK is not None:
            _ORIGINAL_THREADING_EXCEPTHOOK(args)

    sys.excepthook = _sys_excepthook
    if hasattr(threading, "excepthook"):
        threading.excepthook = _threading_excepthook
    atexit.register(_cleanup_empty_crash_log)
    print(f"[CrashDiag] Crash diagnostics enabled: {log_path}")


def _run_real_ui(app, ui_arg="main.ui", *, runtime_smoke=False):
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
            if summary.get("adopted_runtime_tabs"):
                print("[UI Real Smoke] Adopted runtime tabs:")
                for target_name, titles in summary["adopted_runtime_tabs"].items():
                    print(f"  - {target_name}: {', '.join(titles)}")
            if "sensory_runtime_tabs" in summary:
                print("[UI Real Smoke] Sensory runtime tabs: " + ", ".join(summary["sensory_runtime_tabs"] or ["none"]))
            if "runtime_status" in summary:
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


def run_qt_app(argv=None):
    """Run the default Qt app entry path after early shell/validation modes."""
    argv = list(sys.argv[1:] if argv is None else argv)
    _install_crash_diagnostics()
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    try:
        icon = QtGui.QIcon(str(APP_ICON_PATH))
        if not icon.isNull():
            app.setWindowIcon(icon)
    except Exception:
        pass
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
        _run_real_ui(app, ui_arg, runtime_smoke=runtime_smoke)

    ui_arg = "main.ui"
    runtime_smoke = any(str(item or "").strip().lower() == "--runtime-smoke" for item in argv)
    _run_real_ui(app, ui_arg, runtime_smoke=runtime_smoke)

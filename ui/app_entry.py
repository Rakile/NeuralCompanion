"""Runtime app entry helpers for the Qt desktop application."""

import atexit
import faulthandler
import os
import sys
import threading
import time
import traceback
from pathlib import Path

from PySide6 import QtGui

from core import crash_diagnostics
from ui.app_constants import APP_ICON_PATH, APP_TITLE, SESSION_PATH

_CRASH_LOG_HANDLE = None
_CRASH_LOG_PATH = None
_CRASH_LOG_DIRTY = False
_CRASH_BUNDLE_PATH = None
_ORIGINAL_SYS_EXCEPTHOOK = sys.excepthook
_ORIGINAL_THREADING_EXCEPTHOOK = getattr(threading, "excepthook", None)
_STARTUP_ONLY_CRASH_LOG_MAX_BYTES = 1024


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


def _crash_diag_runtime_config(application_facade):
    try:
        return dict(application_facade.config.snapshot().values)
    except Exception:
        return {}


def _write_codex_debug_bundle(reason, extra_context=None, *, application_facade):
    global _CRASH_BUNDLE_PATH, _CRASH_LOG_DIRTY
    if _CRASH_BUNDLE_PATH is not None:
        return _CRASH_BUNDLE_PATH
    try:
        bundle_path = crash_diagnostics.create_debug_bundle(
            app_root=_crash_diag_app_root(),
            reason=str(reason or "crash"),
            crash_log_path=_CRASH_LOG_PATH,
            runtime_config=_crash_diag_runtime_config(application_facade),
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


def _install_crash_diagnostics(application_facade):
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
        # Windows also invokes this handler for recoverable COM/RPC errors on
        # native threads. Inspecting other live Python frames without the GIL
        # can crash CPython in PyCode_Addr2Line (python/cpython#116008).
        # Keep native dumps on the faulting thread; Python exception hooks below
        # still record full tracebacks and create debug bundles.
        faulthandler.enable(file=_CRASH_LOG_HANDLE, all_threads=(os.name != "nt"))
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
                application_facade=application_facade,
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
                application_facade=application_facade,
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


_REMOVED_LEGACY_UI_FLAGS = frozenset(
    {
        "--ui-file",
        "--ui-legacy",
        "--ui-preview",
        "--ui-real",
    }
)


def resolve_ui_launch_mode(argv) -> str:
    """Return the native QML launch mode and reject removed widget shells."""
    first_arg = str(argv[0] or "").strip().lower() if argv else ""
    if first_arg == "--qml-gallery":
        return "gallery"
    if first_arg in _REMOVED_LEGACY_UI_FLAGS:
        raise ValueError(
            f"{first_arg} was removed from the full-redesign branch. "
            "NeuralCompanion now exposes only the native QML application."
        )
    return "qml"


def run_qt_app(application_facade, argv=None):
    """Run the native QML desktop application."""
    argv = list(sys.argv[1:] if argv is None else argv)
    _install_crash_diagnostics(application_facade)
    app = QtGui.QGuiApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    try:
        icon = QtGui.QIcon(str(APP_ICON_PATH))
        if not icon.isNull():
            app.setWindowIcon(icon)
    except Exception:
        pass
    launch_mode = resolve_ui_launch_mode(argv)
    from ui.qml_app import run_qml_app

    return run_qml_app(
        app,
        application_facade,
        component_gallery=launch_mode == "gallery",
        runtime_smoke=any(
            str(item or "").strip().lower() == "--runtime-smoke"
            for item in argv
        ),
        visual_smoke=any(
            str(item or "").strip().lower() == "--qml-visual-smoke"
            for item in argv
        ),
    )

"""Qt Designer loading helpers used by shell and real UI entry paths."""

import sys


def install_no_wheel_input_guard(app):
    from PySide6 import QtCore as _QtCore
    from PySide6 import QtWidgets as _QtWidgets

    if app is None:
        return None
    existing_guard = getattr(app, "_nc_no_wheel_input_guard", None)
    if existing_guard is not None:
        return existing_guard

    class _NoWheelInputGuard(_QtCore.QObject):
        def eventFilter(self, watched, event):
            if event is None or watched is None or event.type() != _QtCore.QEvent.Wheel:
                return False
            if isinstance(watched, (_QtWidgets.QComboBox, _QtWidgets.QAbstractSpinBox)):
                event.ignore()
                return True
            if isinstance(watched, _QtWidgets.QAbstractSlider) and not isinstance(watched, _QtWidgets.QScrollBar):
                event.ignore()
                return True
            return False

    guard = _NoWheelInputGuard(app)
    setattr(app, "_nc_no_wheel_input_guard", guard)
    app.installEventFilter(guard)
    return guard


def load_ui_shell_for_smoke(ui_path):
    from PySide6 import QtCore as _QtCore
    from PySide6 import QtUiTools as _QtUiTools
    from PySide6 import QtWidgets as _QtWidgets

    app = _QtWidgets.QApplication.instance() or _QtWidgets.QApplication(sys.argv)
    install_no_wheel_input_guard(app)
    ui_file = _QtCore.QFile(str(ui_path))
    if not ui_file.open(_QtCore.QIODevice.ReadOnly):
        raise RuntimeError(f"Could not open UI file: {ui_path}")
    try:
        window = _QtUiTools.QUiLoader().load(ui_file)
    finally:
        ui_file.close()
    if window is None:
        raise RuntimeError(f"Qt Designer UI did not produce a window: {ui_path}")
    return app, window


def load_ui_preview_window(ui_path):
    from PySide6 import QtCore as _QtCore
    try:
        from PySide6 import QtUiTools as _QtUiTools
    except Exception as exc:
        raise RuntimeError("QtUiTools is unavailable, so Designer UI preview mode cannot start.") from exc

    ui_file = _QtCore.QFile(str(ui_path))
    if not ui_file.open(_QtCore.QIODevice.ReadOnly):
        raise RuntimeError(f"Could not open UI file: {ui_path}")
    try:
        window = _QtUiTools.QUiLoader().load(ui_file)
    finally:
        ui_file.close()
    if window is None:
        raise RuntimeError(f"Qt Designer UI did not produce a window: {ui_path}")
    return window


def ui_shell_find_object(window, object_name):
    from PySide6 import QtCore as _QtCore

    if str(window.objectName() or "") == object_name:
        return window
    return window.findChild(_QtCore.QObject, object_name)


def enable_stdio_unicode_fallback():
    """Shell mode may import modules that print emoji on Windows cp1252 consoles."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(errors="replace")
        except TypeError:
            try:
                reconfigure(encoding=getattr(stream, "encoding", None) or "utf-8", errors="replace")
            except Exception:
                pass
        except Exception:
            pass


def ui_shell_class_matches(obj, expected_class):
    if obj is None:
        return False
    return any(cls.__name__ == expected_class for cls in obj.__class__.mro())

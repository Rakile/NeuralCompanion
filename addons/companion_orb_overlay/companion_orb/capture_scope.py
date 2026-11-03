"""Orb-only monitor scope. Geometry snapshots are produced on the Qt GUI thread."""
from __future__ import annotations

import copy
import sys


def capture_mode(config: dict) -> str:
    if config.get('companion_orb_full_screen_context_enabled', False):
        return 'screen'
    return 'region' if config.get('companion_orb_target_mode') == 'region' else 'window'


def select_screen(point: tuple[float, float], monitors: list[dict]) -> dict | None:
    x, y = point
    matches = []
    for monitor in monitors:
        left, top, width, height = monitor['logical_bounds']
        if left <= x < left + width and top <= y < top + height:
            matches.append(monitor)
    return copy.deepcopy(matches[0]) if len(matches) == 1 else None


def resolve_screen(identity: dict, monitors: list[dict]) -> dict | None:
    matches = [m for m in monitors if identity and m['identity'] == identity]
    return copy.deepcopy(matches[0]) if len(matches) == 1 else None


def is_desktop_shell(root_class: str, shell_process: bool, child_class: str = '') -> bool:
    return bool(shell_process and root_class in {'Progman', 'WorkerW'})


def union_bounds(monitors: list[dict], key: str) -> list[int]:
    if not monitors:
        return []
    boxes = [m[key] for m in monitors]
    left, top = min(b[0] for b in boxes), min(b[1] for b in boxes)
    return [left, top, max(b[0] + b[2] for b in boxes) - left,
            max(b[1] + b[3] for b in boxes) - top]


def crop_screen(image, monitors: list[dict], identity: dict, include_all: bool):
    from PIL import Image
    physical = union_bounds(monitors, 'physical_bounds')
    if not physical or tuple(physical[2:]) != image.size:
        raise ValueError('Display geometry changed; waiting for a fresh monitor map.')

    def crop(monitor):
        x, y, width, height = monitor['physical_bounds']
        return image.crop((x - physical[0], y - physical[1], x - physical[0] + width, y - physical[1] + height))

    if not include_all:
        monitor = resolve_screen(identity, monitors)
        if monitor is None:
            raise ValueError('Selected screen is unavailable. Choose a capture target.')
        return crop(monitor), list(monitor['logical_bounds'])
    logical = union_bounds(monitors, 'logical_bounds')
    # A logical-coordinate mosaic keeps focus/OCR mapping correct across mixed DPI.
    result = Image.new('RGB', tuple(logical[2:]), 'black')
    for monitor in monitors:
        x, y, width, height = monitor['logical_bounds']
        tile = crop(monitor).resize((width, height), Image.Resampling.LANCZOS)
        result.paste(tile, (x - logical[0], y - logical[1]))
    return result, logical


def _windows_monitors() -> dict:
    import ctypes
    from ctypes import wintypes

    class MonitorInfo(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('monitor', wintypes.RECT),
                    ('work', wintypes.RECT), ('flags', wintypes.DWORD), ('device', wintypes.WCHAR * 32)]

    class DisplayDevice(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('name', wintypes.WCHAR * 32),
                    ('description', wintypes.WCHAR * 128), ('flags', wintypes.DWORD),
                    ('device_id', wintypes.WCHAR * 128), ('key', wintypes.WCHAR * 128)]

    user32 = ctypes.windll.user32
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HANDLE, wintypes.HDC,
                                      ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
    user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
    user32.GetMonitorInfoW.restype = wintypes.BOOL
    user32.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT), callback_type, wintypes.LPARAM]
    user32.EnumDisplayMonitors.restype = wintypes.BOOL
    user32.EnumDisplayDevicesW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(DisplayDevice), wintypes.DWORD]
    user32.EnumDisplayDevicesW.restype = wintypes.BOOL
    user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    result = {}

    @callback_type
    def collect(handle, dc, rect, data):
        info = MonitorInfo()
        info.size = ctypes.sizeof(info)
        if user32.GetMonitorInfoW(handle, ctypes.byref(info)):
            device = DisplayDevice()
            device.size = ctypes.sizeof(device)
            if not user32.EnumDisplayDevicesW(info.device, 0, ctypes.byref(device), 1) or not device.device_id:
                return True  # DISPLAY numbers may be reassigned to a different physical panel.
            bounds = info.monitor
            result[str(info.device)] = {
                'physical_bounds': [bounds.left, bounds.top, bounds.right - bounds.left, bounds.bottom - bounds.top],
                'device_id': str(device.device_id),
            }
        return True

    previous = user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    try:
        if not user32.EnumDisplayMonitors(None, None, collect, 0):
            return {}
    finally:
        if previous:
            user32.SetThreadDpiAwarenessContext(previous)
    return result


def monitor_snapshot() -> list[dict]:
    from PySide6 import QtCore, QtGui
    app = QtGui.QGuiApplication.instance()
    if app is None or QtCore.QThread.currentThread() != app.thread():
        return []
    try:
        native = _windows_monitors() if sys.platform.startswith('win') else {}
    except (OSError, AttributeError):
        native = {}
    monitors = []
    for index, screen in enumerate(app.screens()):
        geometry = screen.geometry()
        logical = [geometry.x(), geometry.y(), geometry.width(), geometry.height()]
        details = native.get(screen.name())
        if sys.platform.startswith('win') and not details:
            continue  # No guessing a physical crop from a different monitor.
        identity = {'device': (details or {}).get('device_id', screen.name()),
                    'serial': screen.serialNumber(), 'manufacturer': screen.manufacturer(), 'model': screen.model()}
        monitors.append(dict(identity=identity, label=f'Monitor {index + 1}', logical_bounds=logical,
                             physical_bounds=(details or {}).get('physical_bounds', logical)))
    return monitors


def monitor_map_is_current(monitors: list[dict]) -> bool:
    """Validate worker geometry without touching Qt screens off their GUI thread."""
    if not monitors:
        return False
    if not sys.platform.startswith('win'):
        return True
    try:
        native = _windows_monitors()
    except (OSError, AttributeError):
        return False
    expected = sorted((m['identity']['device'], tuple(m['physical_bounds'])) for m in monitors)
    actual = sorted((m['device_id'], tuple(m['physical_bounds'])) for m in native.values())
    return expected == actual

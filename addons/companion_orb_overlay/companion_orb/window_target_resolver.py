from __future__ import annotations

import datetime as _dt
import os
import sys
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return _dt.datetime.now(_dt.UTC).isoformat()


def _region_target(x: int, y: int, width: int, height: int, *, source: str = "companion_orb") -> dict[str, Any]:
    w = max(32, int(width or 320))
    h = max(32, int(height or 240))
    left = int(x) - (w // 2)
    top = int(y) - (h // 2)
    return {
        "target_type": "region",
        "window_id": "",
        "title": "Region around Companion Orb",
        "process_name": "",
        "bounds": [int(left), int(top), int(w), int(h)],
        "selected_at": _now_iso(),
        "source": source,
    }


def resolve_target_at(
    x: int,
    y: int,
    *,
    region_width: int = 640,
    region_height: int = 420,
    mode: str = "window",
) -> dict[str, Any]:
    mode = str(mode or "window").strip().lower()
    if mode == "region":
        return _region_target(x, y, region_width, region_height)
    if sys.platform.startswith("win"):
        target = _resolve_windows_target_at(int(x), int(y))
        if target:
            return target
    return _region_target(x, y, region_width, region_height)


def target_bounds(target: dict[str, Any] | None) -> list[int]:
    payload = dict(target or {})
    try:
        bounds = [int(value) for value in list(payload.get("bounds") or [])[:4]]
    except Exception:
        return []
    if len(bounds) != 4 or bounds[2] <= 0 or bounds[3] <= 0:
        return []
    return bounds


def target_is_available(target: dict[str, Any] | None) -> bool:
    payload = dict(target or {})
    if str(payload.get("target_type") or "") == "region":
        return bool(target_bounds(payload))
    if not sys.platform.startswith("win"):
        return bool(target_bounds(payload))
    try:
        import ctypes

        hwnd = int(str(payload.get("window_id") or "0"), 0)
        return bool(hwnd and ctypes.windll.user32.IsWindow(hwnd))
    except Exception:
        return bool(target_bounds(payload))


def refresh_window_target(target: dict[str, Any] | None) -> dict[str, Any] | None:
    payload = dict(target or {})
    if str(payload.get("target_type") or "").strip().lower() != "window":
        return payload if target_bounds(payload) else None
    if not sys.platform.startswith("win"):
        return payload if target_bounds(payload) else None
    try:
        hwnd = int(str(payload.get("window_id") or "0"), 0)
    except Exception:
        return None
    refreshed = _windows_target_from_hwnd(hwnd)
    if not refreshed:
        return None
    if payload.get("selected_at"):
        refreshed["selected_at"] = payload.get("selected_at")
    refreshed["refreshed_at"] = _now_iso()
    return refreshed


def _resolve_windows_target_at(x: int, y: int) -> dict[str, Any] | None:
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return None

    user32 = ctypes.windll.user32

    class POINT(ctypes.Structure):
        _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

    point = POINT(int(x), int(y))
    hwnd = user32.WindowFromPoint(point)
    if not hwnd:
        return None
    return _windows_target_from_hwnd(hwnd)


def _windows_target_from_hwnd(hwnd: int) -> dict[str, Any] | None:
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return None

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", wintypes.LONG),
            ("top", wintypes.LONG),
            ("right", wintypes.LONG),
            ("bottom", wintypes.LONG),
        ]

    GA_ROOT = 2
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

    root = user32.GetAncestor(hwnd, GA_ROOT) or hwnd
    if not root or not user32.IsWindow(root) or not user32.IsWindowVisible(root):
        return None

    rect = RECT()
    if not user32.GetWindowRect(root, ctypes.byref(rect)):
        return None
    width = int(rect.right - rect.left)
    height = int(rect.bottom - rect.top)
    if width <= 0 or height <= 0:
        return None

    title_length = int(user32.GetWindowTextLengthW(root))
    title_buffer = ctypes.create_unicode_buffer(max(1, title_length + 1))
    user32.GetWindowTextW(root, title_buffer, len(title_buffer))
    title = str(title_buffer.value or "").strip()

    process_id = wintypes.DWORD()
    user32.GetWindowThreadProcessId(root, ctypes.byref(process_id))
    process_name = ""
    if process_id.value:
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, process_id.value)
        if handle:
            try:
                buffer = ctypes.create_unicode_buffer(32768)
                size = wintypes.DWORD(len(buffer))
                if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                    process_name = Path(str(buffer.value)).name
            finally:
                kernel32.CloseHandle(handle)
    if not process_name and process_id.value:
        process_name = f"pid:{int(process_id.value)}"

    return {
        "target_type": "window",
        "window_id": hex(int(root)),
        "title": title or "Untitled window",
        "process_name": process_name,
        "bounds": [int(rect.left), int(rect.top), width, height],
        "selected_at": _now_iso(),
        "source": "companion_orb",
        "screen": os.environ.get("COMPUTERNAME", ""),
    }

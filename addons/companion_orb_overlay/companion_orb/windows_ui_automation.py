"""Bounded, worker-safe Windows UI Automation target discovery."""
from __future__ import annotations

import os
import queue
import re
import time
import math
import threading
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Sequence

from . import eye_tracking


INTERACTIVE_ROLES = {
    "ButtonControl": "Button",
    "HyperlinkControl": "Link",
    "TabItemControl": "Tab",
    "MenuItemControl": "Menu item",
    "ListItemControl": "List item",
    "TreeItemControl": "Tree item",
    "CheckBoxControl": "Checkbox",
    "RadioButtonControl": "Radio button",
    "ComboBoxControl": "Combo box",
    "EditControl": "Input",
    "SliderControl": "Slider",
    "SpinnerControl": "Spinner",
    "SplitButtonControl": "Split button",
    "DataItemControl": "Data item",
}


@dataclass(frozen=True, slots=True)
class AutomationScanResult:
    targets: tuple[eye_tracking.ClickTarget, ...] = ()
    available: bool = False
    timed_out: bool = False
    error: str = ""


Bounds = tuple[int, int, int, int]
Clock = Callable[[], float]
DEFAULT_MAX_NODES = 320
DEFAULT_TIMEOUT_SECONDS = 0.45
MINIMUM_TIMEOUT_SECONDS = 0.05


def _load_uiautomation() -> Any | None:
    """Import UI Automation only when semantic discovery is requested on Windows."""
    if os.name != "nt":
        return None
    try:
        import uiautomation
    except Exception:
        return None
    return uiautomation


def _normalized_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _rectangle_bounds(rectangle: object) -> Bounds | None:
    try:
        left = int(getattr(rectangle, "left"))
        top = int(getattr(rectangle, "top"))
        right = int(getattr(rectangle, "right"))
        bottom = int(getattr(rectangle, "bottom"))
    except (AttributeError, TypeError, ValueError):
        return None
    width = right - left
    height = bottom - top
    if width <= 0 or height <= 0:
        return None
    return left, top, width, height


def _intersects(first: Bounds, second: Bounds) -> bool:
    first_left, first_top, first_width, first_height = first
    second_left, second_top, second_width, second_height = second
    return (
        first_left < second_left + second_width
        and second_left < first_left + first_width
        and first_top < second_top + second_height
        and second_top < first_top + first_height
    )


def _runtime_id(control: object) -> tuple[int, ...]:
    try:
        return tuple(int(value) for value in control.GetRuntimeId())
    except (AttributeError, TypeError, ValueError):
        return ()


def _target_from_control(control: object, capture_bounds: Bounds) -> eye_tracking.ClickTarget | None:
    role_key = _normalized_text(getattr(control, "ControlTypeName", ""))
    role = INTERACTIVE_ROLES.get(role_key)
    name = _normalized_text(getattr(control, "Name", ""))
    bounds = _rectangle_bounds(getattr(control, "BoundingRectangle", None))
    if not role or not name or bounds is None or not _intersects(bounds, capture_bounds):
        return None
    runtime_id = _runtime_id(control)
    center = (bounds[0] + bounds[2] * 0.5, bounds[1] + bounds[3] * 0.5)
    if not runtime_id or not _point_in_bounds(center, capture_bounds):
        return None
    try:
        if not bool(control.IsEnabled) or bool(control.IsOffscreen) or bool(control.IsPassword):
            return None
    except (AttributeError, TypeError):
        return None
    return eye_tracking.ClickTarget(
        label=name,
        bounds=bounds,
        kind=role_key,
        confidence=1.0,
        role=role,
        source="uia",
        semantic=True,
        runtime_id=runtime_id,
    )


def _visible_window_handles_ctypes(capture_bounds: Bounds) -> tuple[int, ...]:
    """Enumerate visible top-level HWNDs without adding a pywin32 dependency."""
    if os.name != "nt":
        return ()
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return ()

    class Rect(ctypes.Structure):
        _fields_ = [
            ("left", wintypes.LONG),
            ("top", wintypes.LONG),
            ("right", wintypes.LONG),
            ("bottom", wintypes.LONG),
        ]

    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows.argtypes = (callback_type, wintypes.LPARAM)
        user32.EnumWindows.restype = wintypes.BOOL
        user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(Rect))
        user32.GetWindowRect.restype = wintypes.BOOL
    except Exception:
        return ()

    handles: list[int] = []

    @callback_type
    def visit_window(hwnd: int, _param: int) -> bool:
        try:
            if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
                return True
            rect = Rect()
            if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return True
            bounds = (
                int(rect.left),
                int(rect.top),
                int(rect.right - rect.left),
                int(rect.bottom - rect.top),
            )
            if bounds[2] > 0 and bounds[3] > 0 and _intersects(bounds, capture_bounds):
                handles.append(int(hwnd))
        except Exception:
            pass
        return True

    try:
        user32.EnumWindows(visit_window, 0)
    except Exception:
        return ()
    return tuple(handles)


def _visible_window_handles(capture_bounds: Bounds) -> tuple[int, ...]:
    """Return visible top-level HWNDs in EnumWindows z-order."""
    try:
        import win32gui
    except Exception:
        return _visible_window_handles_ctypes(capture_bounds)

    handles: list[int] = []

    def visit_window(hwnd: int, _param: object) -> bool:
        try:
            if not win32gui.IsWindowVisible(hwnd) or win32gui.IsIconic(hwnd):
                return True
            left, top, right, bottom = (int(value) for value in win32gui.GetWindowRect(hwnd))
        except Exception:
            return True
        bounds = (left, top, right - left, bottom - top)
        if bounds[2] > 0 and bounds[3] > 0 and _intersects(bounds, capture_bounds):
            handles.append(int(hwnd))
        return True

    try:
        win32gui.EnumWindows(visit_window, None)
    except Exception:
        return ()
    return tuple(handles)


def _normalized_timeout_seconds(value: object) -> float:
    try:
        timeout_seconds = float(value)
    except (TypeError, ValueError, OverflowError):
        return DEFAULT_TIMEOUT_SECONDS
    if not math.isfinite(timeout_seconds):
        return DEFAULT_TIMEOUT_SECONDS
    return max(MINIMUM_TIMEOUT_SECONDS, timeout_seconds)


def _normalized_max_nodes(value: object) -> int:
    try:
        if isinstance(value, float) and not math.isfinite(value):
            return DEFAULT_MAX_NODES
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return DEFAULT_MAX_NODES


def _discover_semantic_targets_in_thread(
    scan_bounds: Bounds,
    *,
    automation_module: Any,
    window_handle_provider: Callable[[Bounds], Iterable[int]],
    node_limit: int,
    timeout_seconds: float,
    now_fn: Clock,
) -> AutomationScanResult:
    deadline = now_fn() + timeout_seconds
    targets: list[eye_tracking.ClickTarget] = []
    visited = 0
    timed_out = False
    try:
        with automation_module.UIAutomationInitializerInThread():
            handles = window_handle_provider(scan_bounds)
            for hwnd in tuple(handles)[:6]:
                root = automation_module.ControlFromHandle(int(hwnd))
                if root is None:
                    continue
                for control, _depth in automation_module.WalkControl(
                    root,
                    includeTop=True,
                    maxDepth=18,
                ):
                    visited += 1
                    if visited > node_limit or now_fn() >= deadline:
                        timed_out = True
                        break
                    target = _target_from_control(control, scan_bounds)
                    if target is not None:
                        targets.append(target)
                if timed_out:
                    break
    except Exception as exc:
        return AutomationScanResult(tuple(targets), True, timed_out, str(exc))
    return AutomationScanResult(tuple(targets), True, timed_out, "")


def discover_semantic_targets(
    capture_bounds: Sequence[int | float],
    *,
    automation_module: Any | None = None,
    window_handle_provider: Callable[[Bounds], Iterable[int]] | None = None,
    max_nodes: int = 320,
    timeout_seconds: float = 0.45,
    now_fn: Clock = time.monotonic,
) -> AutomationScanResult:
    """Discover semantic controls without returning UI Automation objects."""
    try:
        scan_bounds = tuple(int(value) for value in capture_bounds[:4])
    except (TypeError, ValueError):
        return AutomationScanResult(error="invalid capture bounds")
    if len(scan_bounds) != 4 or scan_bounds[2] <= 0 or scan_bounds[3] <= 0:
        return AutomationScanResult(error="invalid capture bounds")

    auto = automation_module or _load_uiautomation()
    if auto is None:
        return AutomationScanResult(available=False, error="uiautomation is not installed")

    normalized_timeout = _normalized_timeout_seconds(timeout_seconds)
    node_limit = _normalized_max_nodes(max_nodes)
    results: queue.Queue[AutomationScanResult] = queue.Queue(maxsize=1)

    def scan() -> None:
        result = _discover_semantic_targets_in_thread(
            scan_bounds,
            automation_module=auto,
            window_handle_provider=window_handle_provider or _visible_window_handles,
            node_limit=node_limit,
            timeout_seconds=normalized_timeout,
            now_fn=now_fn,
        )
        results.put_nowait(result)

    hard_deadline = time.monotonic() + normalized_timeout
    try:
        threading.Thread(
            target=scan,
            daemon=True,
            name="companion-orb-uia-discovery",
        ).start()
    except Exception as exc:
        return AutomationScanResult(available=True, error=str(exc))
    try:
        return results.get(timeout=max(0.0, hard_deadline - time.monotonic()))
    except queue.Empty:
        return AutomationScanResult(available=True, timed_out=True)


def _point_in_bounds(point: tuple[float, float], bounds: Bounds) -> bool:
    x, y = point
    left, top, width, height = bounds
    return left <= x < left + width and top <= y < top + height


def _bounds_within_tolerance(expected: Bounds, current: Bounds, tolerance: int = 12) -> bool:
    return all(abs(expected_value - current_value) <= tolerance for expected_value, current_value in zip(expected, current))


def validate_semantic_target(
    target: eye_tracking.ClickTarget,
    point: tuple[float, float],
    *,
    automation_module: Any | None = None,
) -> bool:
    """Confirm a semantic target still matches the control beneath a click point."""
    auto = automation_module or _load_uiautomation()
    if auto is None or not target.runtime_id:
        return False
    try:
        x, y = float(point[0]), float(point[1])
        with auto.UIAutomationInitializerInThread():
            control = auto.ControlFromPoint(round(x), round(y))
            if control is None:
                return False
            current_bounds = _rectangle_bounds(getattr(control, "BoundingRectangle", None))
            current = _target_from_control(control, current_bounds) if current_bounds is not None else None
            if current is None or current_bounds is None:
                return False
            if not _point_in_bounds((x, y), current_bounds):
                return False
            if current.label != _normalized_text(target.label) or current.role != _normalized_text(target.role):
                return False
            if not current.runtime_id or current.runtime_id != target.runtime_id:
                return False
            return _bounds_within_tolerance(target.bounds, current_bounds)
    except Exception:
        return False

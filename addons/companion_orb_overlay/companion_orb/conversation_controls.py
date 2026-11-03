"""Turn-local names for native controls, revalidated before conversational hover."""
from __future__ import annotations

import threading

from .eye_tracking import ClickTarget
from . import windows_ui_automation


def discover_conversation_controls(bounds, windows):
    # OCR already identifies windows actually visible in this capture. Starting
    # with unrelated top-level overlays can exhaust the bounded UIA walk first.
    handles = []
    for window in windows:
        try:
            handle = int(str(window.get("window_id") or "0"), 0)
        except (TypeError, ValueError):
            continue
        if handle > 0 and handle not in handles:
            handles.append(handle)
    return windows_ui_automation.discover_semantic_targets(
        bounds, max_nodes=1500, timeout_seconds=1.0,
        window_handle_provider=(lambda _: tuple(handles)) if handles else None,
    )


def _label(target):
    return " ".join(target.label.split())[:160]


class ConversationControls:
    def __init__(self):
        self._generation = 0
        self._targets = {}
        self._lock = threading.Lock()

    def replace(self, targets, resolve_window):
        groups = {}
        accepted = []
        for target in targets:
            if not isinstance(target, ClickTarget) or not target.semantic or not target.runtime_id or not _label(target):
                continue
            if target.bounds[2] <= 0 or target.bounds[3] <= 0:
                continue
            try:
                window = resolve_window(*map(int, target.center)) or {}
            except Exception:
                window = {}
            key = str(window.get("window_id") or "unknown")
            group = groups.setdefault(key, {"window": str(window.get("title") or "Unknown window")[:120], "targets": []})
            group["targets"].append(target)
        # Share the bounded prompt space across windows, not just the first app.
        pending = [list(group["targets"]) for group in groups.values()]
        while any(pending) and len(accepted) < 120:
            for index, remaining in enumerate(pending):
                if remaining and len(accepted) < 120:
                    accepted.append((index, remaining.pop(0)))
        output = [{"window": group["window"], "items": []} for group in groups.values()]
        with self._lock:
            self._generation += 1
            self._targets = {}
            for index, (group_index, target) in enumerate(accepted):
                identity = f"uia-{self._generation}-{index}"
                self._targets[identity] = target
                output[group_index]["items"].append({
                    "id": identity, "label": _label(target), "role": target.role,
                    "bounds": list(target.bounds),
                })
        return [group for group in output if group["items"]]

    def resolve(self, identity, label, validate):
        with self._lock:
            target = self._targets.get(identity)
        if target is None or _label(target).casefold() != str(label).strip().casefold():
            return None
        try:
            if not validate(target, target.center):
                return None
        except Exception:
            return None
        with self._lock:
            return target if self._targets.get(identity) is target else None

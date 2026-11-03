from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[2]
VISUAL_REPLY_STATE_PATH = str(APP_ROOT / "runtime" / "visual_reply_state.json")

current_visual_reply_data = {
    "status": "idle",
    "image_path": "",
    "caption": "",
    "detail_text": "",
    "request_id": "",
    "updated_at": 0.0,
}

_snapshot_lock = threading.Lock()
_request_state_lock = threading.Lock()
_request_states: dict[str, dict[str, object]] = {}
_TERMINAL_REQUEST_STATUSES = {"ready", "error", "failed", "rejected", "cancelled", "retired"}


def record_request_state(payload: dict[str, object], *, binding_id: str = "") -> None:
    request_id = str(payload.get("request_id") or "").strip()
    if not request_id:
        return
    with _request_state_lock:
        previous = _request_states.get(request_id, {})
        if previous.get("status") in _TERMINAL_REQUEST_STATUSES and (
            not binding_id or previous.get("_binding_id") == binding_id
        ):
            return
        _request_states.pop(request_id, None)
        recorded = dict(payload)
        identity = str(binding_id or previous.get("_binding_id") or "")
        if identity:
            recorded["_binding_id"] = identity
        _request_states[request_id] = recorded
        while len(_request_states) > 64:
            _request_states.pop(next(iter(_request_states)))


def retire_request_state(request_id: str, binding_id: str, reason: str) -> None:
    """Settle an exact pending binding without publishing stale preview state."""
    with _request_state_lock:
        current = _request_states.get(str(request_id or ""))
        if not current or not binding_id or current.get("_binding_id") != binding_id:
            return
        if current.get("status") in _TERMINAL_REQUEST_STATUSES:
            return
        current.update(
            status="retired" if reason == "visual_request_retired" else "cancelled",
            image_path="",
            updated_at=time.time(),
        )


def request_states_snapshot() -> dict[str, dict[str, object]]:
    """Retain matched publications when another request replaces the preview."""
    with _request_state_lock:
        snapshots = {
            key: {field: item for field, item in value.items() if field != "_binding_id"}
            for key, value in _request_states.items()
        }
    current = dict(current_visual_reply_data or {})
    request_id = str(current.get("request_id") or "").strip()
    if request_id:
        snapshots.setdefault(request_id, current)
    return snapshots


def _ensure_snapshot_dir():
    os.makedirs(os.path.dirname(VISUAL_REPLY_STATE_PATH), exist_ok=True)


def write_visual_reply_snapshot(state=None):
    payload = dict(state if state is not None else current_visual_reply_data or {})
    _ensure_snapshot_dir()
    temp_path = f"{VISUAL_REPLY_STATE_PATH}.{threading.get_ident()}.tmp"
    with _snapshot_lock:
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=True)
        for attempt in range(8):
            try:
                os.replace(temp_path, VISUAL_REPLY_STATE_PATH)
                return
            except PermissionError:
                if attempt == 7:
                    raise
                time.sleep(0.005 * (attempt + 1))
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def set_current_visual_reply_data(state, *, binding_id: str = ""):
    global current_visual_reply_data
    next_state = dict(state or {})
    if "updated_at" not in next_state:
        next_state["updated_at"] = time.time()
    current_visual_reply_data = next_state
    record_request_state(next_state, binding_id=binding_id)
    write_visual_reply_snapshot(next_state)


def update_current_visual_reply_data(**updates):
    global current_visual_reply_data
    next_state = dict(current_visual_reply_data or {})
    next_state.update(updates)
    next_state["updated_at"] = time.time()
    current_visual_reply_data = next_state
    record_request_state(next_state)
    write_visual_reply_snapshot(next_state)

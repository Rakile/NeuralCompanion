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


def set_current_visual_reply_data(state):
    global current_visual_reply_data
    current_visual_reply_data = dict(state or {})
    if "updated_at" not in current_visual_reply_data:
        current_visual_reply_data["updated_at"] = time.time()
    write_visual_reply_snapshot(current_visual_reply_data)


def update_current_visual_reply_data(**updates):
    global current_visual_reply_data
    next_state = dict(current_visual_reply_data or {})
    next_state.update(updates)
    next_state["updated_at"] = time.time()
    current_visual_reply_data = next_state
    write_visual_reply_snapshot(current_visual_reply_data)

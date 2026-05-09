from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[2]
MUSE_PREVIEW_STATE_PATH = str(APP_ROOT / "runtime" / "musetalk_preview_state.json")
MUSE_PREVIEW_FRAME_PATH = str(APP_ROOT / "runtime" / "musetalk_preview_frame.json")
MUSE_PREVIEW_LOG_PATH = str(APP_ROOT / "runtime" / "MuseTalkPreview_log.txt")
MUSE_PREVIEW_FILE_LOG_ENABLED = str(os.environ.get("NC_MUSETALK_PREVIEW_LOG", "") or "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

current_musetalk_frame_data = {
    "frame_paths": [],
    "frame_dir": "",
    "fps": 24,
    "sync_time": 0.0,
    "duration_seconds": 0.0,
    "expected_frame_count": 0,
    "trim_start_frames": 0,
    "chunk_id": None,
    "text": "",
    "status": "idle",
    "loop": False,
    "preview_chunk_id": None,
    "preview_frame_index": -1,
    "preview_source_index": None,
}
current_musetalk_preview_chunk_id = None
current_musetalk_pipeline_data = {
    "reply_id": 0,
    "active": False,
    "stream_mode": False,
    "stream_open": False,
    "chunks": [],
    "updated_at": 0.0,
}

_musetalk_preview_feed = deque(maxlen=2048)
_musetalk_preview_feed_seq = 0
_snapshot_lock = threading.Lock()
_preview_log_lock = threading.Lock()
_pipeline_lock = threading.Lock()


def _ensure_snapshot_dir():
    os.makedirs(os.path.dirname(MUSE_PREVIEW_STATE_PATH), exist_ok=True)


def append_musetalk_preview_log(message):
    if not MUSE_PREVIEW_FILE_LOG_ENABLED:
        return
    if not message:
        return
    _ensure_snapshot_dir()
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    with _preview_log_lock:
        with open(MUSE_PREVIEW_LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def write_musetalk_preview_snapshot(state=None):
    payload = dict(state if state is not None else current_musetalk_frame_data or {})
    _ensure_snapshot_dir()
    temp_path = f"{MUSE_PREVIEW_STATE_PATH}.{threading.get_ident()}.tmp"
    with _snapshot_lock:
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=True)
        for attempt in range(8):
            try:
                os.replace(temp_path, MUSE_PREVIEW_STATE_PATH)
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


def write_musetalk_preview_frame(payload):
    global current_musetalk_preview_chunk_id, _musetalk_preview_feed_seq
    _ensure_snapshot_dir()
    with _snapshot_lock:
        chunk_id = (payload or {}).get("chunk_id")
        if current_musetalk_preview_chunk_id is not None and chunk_id != current_musetalk_preview_chunk_id:
            return
        _musetalk_preview_feed_seq += 1
        queued_payload = dict(payload or {})
        queued_payload["_seq"] = _musetalk_preview_feed_seq
        _musetalk_preview_feed.append(queued_payload)
        try:
            with open(MUSE_PREVIEW_FRAME_PATH, "w", encoding="utf-8") as handle:
                json.dump(queued_payload, handle, ensure_ascii=True)
                handle.flush()
        except OSError:
            return


def consume_musetalk_preview_feed(after_seq=0):
    with _snapshot_lock:
        return [dict(item) for item in _musetalk_preview_feed if int(item.get("_seq", 0) or 0) > int(after_seq or 0)]


def set_current_musetalk_frame_data(state):
    global current_musetalk_frame_data, current_musetalk_preview_chunk_id
    current_musetalk_frame_data = dict(state or {})
    current_musetalk_preview_chunk_id = current_musetalk_frame_data.get("chunk_id")
    write_musetalk_preview_snapshot(current_musetalk_frame_data)


def update_current_musetalk_frame_data(**updates):
    global current_musetalk_frame_data, current_musetalk_preview_chunk_id
    next_state = dict(current_musetalk_frame_data or {})
    next_state.update(updates)
    current_musetalk_frame_data = next_state
    current_musetalk_preview_chunk_id = current_musetalk_frame_data.get("chunk_id")
    write_musetalk_preview_snapshot(current_musetalk_frame_data)


def reset_musetalk_pipeline_data():
    global current_musetalk_pipeline_data
    with _pipeline_lock:
        current_musetalk_pipeline_data = {
            "reply_id": int((current_musetalk_pipeline_data or {}).get("reply_id", 0) or 0),
            "active": False,
            "stream_mode": False,
            "stream_open": False,
            "chunks": [],
            "updated_at": time.time(),
        }


def begin_musetalk_pipeline_reply(stream_mode=False):
    global current_musetalk_pipeline_data
    with _pipeline_lock:
        reply_id = int((current_musetalk_pipeline_data or {}).get("reply_id", 0) or 0) + 1
        current_musetalk_pipeline_data = {
            "reply_id": reply_id,
            "active": True,
            "stream_mode": bool(stream_mode),
            "stream_open": bool(stream_mode),
            "chunks": [],
            "updated_at": time.time(),
        }
        return reply_id


def _ensure_pipeline_chunk(chunks, sequence_index):
    index = max(0, int(sequence_index or 0))
    while len(chunks) <= index:
        chunks.append(
            {
                "sequence_index": len(chunks),
                "status": "planned",
                "playback_state": "pending",
                "text": "",
                "emotion": "",
                "duration_seconds": 0.0,
                "expected_frame_count": 0,
            }
        )
    return chunks[index]


def update_musetalk_pipeline_chunk(sequence_index, reply_id=None, **updates):
    global current_musetalk_pipeline_data
    with _pipeline_lock:
        data = dict(current_musetalk_pipeline_data or {})
        active_reply_id = int(data.get("reply_id", 0) or 0)
        if reply_id is not None and int(reply_id or 0) != active_reply_id:
            return False
        chunks = [dict(item or {}) for item in data.get("chunks", [])]
        chunk = _ensure_pipeline_chunk(chunks, sequence_index)
        chunk.update(updates)
        chunk["sequence_index"] = max(0, int(sequence_index or 0))
        data["chunks"] = chunks
        data["updated_at"] = time.time()
        current_musetalk_pipeline_data = data
        return True


def update_musetalk_pipeline_flags(reply_id=None, **updates):
    global current_musetalk_pipeline_data
    with _pipeline_lock:
        data = dict(current_musetalk_pipeline_data or {})
        active_reply_id = int(data.get("reply_id", 0) or 0)
        if reply_id is not None and int(reply_id or 0) != active_reply_id:
            return False
        data.update(updates)
        data["updated_at"] = time.time()
        current_musetalk_pipeline_data = data
        return True


def get_musetalk_pipeline_snapshot():
    with _pipeline_lock:
        payload = dict(current_musetalk_pipeline_data or {})
        payload["chunks"] = [dict(item or {}) for item in payload.get("chunks", [])]
        return payload

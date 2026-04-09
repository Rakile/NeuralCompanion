import json
import os
import sys
import threading
import time
from collections import OrderedDict
import json

from PySide6 import QtCore, QtGui, QtWidgets
from shared_state import MUSE_PREVIEW_FRAME_PATH, MUSE_PREVIEW_STATE_PATH


POLL_INTERVAL_MS = 8
STATE_SYNC_INTERVAL_MS = 16
SLOW_FETCH_LOG_MS = 80.0
QT_PREVIEW_CACHE_LIMIT = 256
QT_PREVIEW_INITIAL_PRELOAD = 64
QT_PREVIEW_AHEAD_PRELOAD = 32
FRAME_ANOMALY_DT_MS = 120.0


class MuseTalkQtPreview(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MuseTalk Preview (Qt)")
        self.resize(420, 760)

        self.status_label = QtWidgets.QLabel("MuseTalk preview idle")
        self.status_label.setStyleSheet("color: #d7d7d7; padding: 8px;")
        self.image_label = QtWidgets.QLabel()
        self.image_label.setAlignment(QtCore.Qt.AlignCenter)
        self.image_label.setStyleSheet("background: #1f1f1f;")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self.status_label)
        layout.addWidget(self.image_label, 1)

        self.current_sync_time = 0.0
        self.frame_paths = []
        self.source_indices = []
        self.frame_dir = ""
        self.current_frame_index = -1
        self.current_pixmap = None
        self.fps = 24
        self.duration_seconds = 0.0
        self.expected_frame_count = 0
        self.trim_start_frames = 0
        self.chunk_started_at = 0.0
        self.is_looping = False
        self.next_frame_dir_scan_at = 0.0
        self.last_chunk_id = None
        self.last_start_index = 0
        self.last_frame_dir = ""
        self.last_slow_fetch_log_at = 0.0
        self.last_slow_render_log_at = 0.0
        self.last_slow_scan_log_at = 0.0
        self.last_snapshot_mtime_ns = 0
        self.last_frame_snapshot_mtime_ns = 0
        self.last_presented_at = 0.0
        self.last_presented_chunk_id = None
        self.last_presented_source_index = None
        self.last_presented_frame_index = -1
        self.last_consumed_feed_chunk_id = None
        self.last_consumed_feed_source_index = None
        self.pending_handoff_debug = None
        self.preloaded_frame_images = OrderedDict()
        self.preload_generation = 0
        self.preload_target_size = None
        self.preload_frontier = -1
        self.preload_lock = threading.Lock()

        self.state_timer = QtCore.QTimer(self)
        self.state_timer.timeout.connect(self.sync_state)
        self.state_timer.start(STATE_SYNC_INTERVAL_MS)

        self.frame_timer = QtCore.QTimer(self)
        self.frame_timer.timeout.connect(self.on_frame_tick)
        self.frame_timer.start(POLL_INTERVAL_MS)

    def _source_index_for_frame(self, frame_index):
        if self.source_indices and 0 <= frame_index < len(self.source_indices):
            try:
                return int(self.source_indices[frame_index])
            except Exception:
                pass
        return self.last_start_index + max(frame_index, 0)

    def fetch_state(self):
        fetch_started_at = time.time()
        try:
            if not os.path.exists(MUSE_PREVIEW_STATE_PATH):
                return None
            snapshot_mtime_ns = os.stat(MUSE_PREVIEW_STATE_PATH).st_mtime_ns
            if snapshot_mtime_ns <= self.last_snapshot_mtime_ns:
                return None
            with open(MUSE_PREVIEW_STATE_PATH, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            self.last_snapshot_mtime_ns = snapshot_mtime_ns
            fetch_ms = (time.time() - fetch_started_at) * 1000.0
            now = time.time()
            if fetch_ms >= SLOW_FETCH_LOG_MS and (now - self.last_slow_fetch_log_at) > 0.25:
                self.last_slow_fetch_log_at = now
                print(f"🛰️ [MuseTalkQtPreview] Slow state fetch: {fetch_ms:.1f} ms")
            return payload
        except (OSError, json.JSONDecodeError):
            return None

    def _get_target_size(self):
        size = self.image_label.size()
        return max(size.width(), 1), max(size.height(), 1)

    def _get_cached_image(self, frame_path):
        with self.preload_lock:
            for cache_key, cached_image in list(self.preloaded_frame_images.items()):
                if cache_key[0] == frame_path:
                    self.preloaded_frame_images.move_to_end(cache_key)
                    return cached_image, cache_key[1]
        return None

    def _store_cached_image(self, frame_path, target_size, image):
        cache_key = (frame_path, target_size)
        with self.preload_lock:
            self.preloaded_frame_images[cache_key] = image
            self.preloaded_frame_images.move_to_end(cache_key)
            while len(self.preloaded_frame_images) > QT_PREVIEW_CACHE_LIMIT:
                self.preloaded_frame_images.popitem(last=False)

    def _build_cached_image(self, frame_path, target_size):
        image = QtGui.QImage(frame_path)
        if image.isNull():
            return None
        width, height = target_size
        if width > 0 and height > 0:
            image = image.scaled(
                width,
                height,
                QtCore.Qt.KeepAspectRatio,
                QtCore.Qt.SmoothTransformation,
            )
        return image

    def _start_frame_preload(self, start_index=0, count=QT_PREVIEW_AHEAD_PRELOAD):
        if not self.frame_paths:
            return
        target_size = self._get_target_size()
        if target_size != self.preload_target_size:
            self.preload_generation += 1
            self.preload_target_size = target_size
            self.preload_frontier = -1
            with self.preload_lock:
                self.preloaded_frame_images = OrderedDict()
        generation = self.preload_generation
        if start_index + count <= self.preload_frontier:
            return
        self.preload_frontier = max(self.preload_frontier, start_index + count)
        preload_paths = list(self.frame_paths[start_index:start_index + count])

        def worker():
            for frame_path in preload_paths:
                if generation != self.preload_generation:
                    return
                if not frame_path or not os.path.exists(frame_path):
                    continue
                if self._get_cached_image(frame_path) is not None:
                    continue
                image = self._build_cached_image(frame_path, target_size)
                if image is None:
                    continue
                self._store_cached_image(frame_path, target_size, image)

        threading.Thread(target=worker, daemon=True).start()

    def _refresh_frame_paths_from_dir(self):
        if not self.frame_dir or not os.path.isdir(self.frame_dir):
            return
        scanned_paths = sorted(
            [
                os.path.join(self.frame_dir, name)
                for name in os.listdir(self.frame_dir)
                if name.lower().endswith(".png")
            ]
        )
        if self.trim_start_frames > 0 and scanned_paths:
            trimmed = scanned_paths[min(self.trim_start_frames, len(scanned_paths) - 1):]
            if trimmed:
                scanned_paths = trimmed
        if scanned_paths:
            self.frame_paths = scanned_paths
            self.expected_frame_count = max(self.expected_frame_count, len(self.frame_paths))

    def render_current_frame(self, frame_path):
        if not frame_path or not os.path.exists(frame_path):
            return
        render_started_at = time.time()
        target_size = self._get_target_size()
        load_ms = 0.0
        pixmap_ms = 0.0
        set_ms = 0.0
        cache_hit = False
        cached_item = self._get_cached_image(frame_path)
        if cached_item is not None:
            cache_hit = True
            image, _cached_target = cached_item
        else:
            load_started_at = time.time()
            image = self._build_cached_image(frame_path, target_size)
            load_ms = (time.time() - load_started_at) * 1000.0
            if image is None:
                return
            self._store_cached_image(frame_path, target_size, image)
        pixmap_started_at = time.time()
        pixmap = QtGui.QPixmap.fromImage(image)
        pixmap_ms = (time.time() - pixmap_started_at) * 1000.0
        if pixmap.isNull():
            return
        self.current_pixmap = pixmap
        set_started_at = time.time()
        self.image_label.setPixmap(self.current_pixmap)
        set_ms = (time.time() - set_started_at) * 1000.0
        render_ms = (time.time() - render_started_at) * 1000.0
        now = time.time()
        current_source_index = self._source_index_for_frame(self.current_frame_index)
        present_dt_ms = ((now - self.last_presented_at) * 1000.0) if self.last_presented_at else 0.0
        previous_source_index = self.last_presented_source_index
        source_delta = (
            current_source_index - previous_source_index
            if previous_source_index is not None
            else None
        )
        chunk_switched = self.last_presented_chunk_id != self.last_chunk_id
        anomaly_reason = None
        if self.last_presented_at:
            if (
                present_dt_ms >= FRAME_ANOMALY_DT_MS
                and (chunk_switched or not self.is_looping)
            ):
                anomaly_reason = "late_present"
            elif (
                not self.is_looping
                and source_delta is not None
                and source_delta <= 0
            ):
                anomaly_reason = "nonadvancing_source"
        if chunk_switched and self.pending_handoff_debug is not None:
            handoff = self.pending_handoff_debug
            if current_source_index <= int(handoff.get("next_start", current_source_index)):
                anomaly_reason = anomaly_reason or "handoff_hold"
        if anomaly_reason:
            handoff = self.pending_handoff_debug or {}
            print(
                f"⚠️ [MuseTalkQtPreview] Frame anomaly: reason={anomaly_reason}, "
                f"dt={present_dt_ms:.1f} ms, chunk={self.last_chunk_id}, frame={self.current_frame_index}, "
                f"source={current_source_index}, source_delta={source_delta}, chunk_switched={chunk_switched}, "
                f"render={render_ms:.1f} ms, cache={'hit' if cache_hit else 'miss'}, "
                f"load={load_ms:.1f} ms, pixmap={pixmap_ms:.1f} ms, set={set_ms:.1f} ms, "
                f"handoff_prev={handoff.get('prev_source')}, handoff_next={handoff.get('next_start')}, "
                f"expected={self.expected_frame_count}"
            )
        if chunk_switched:
            self.pending_handoff_debug = None
        self.last_presented_at = now
        self.last_presented_chunk_id = self.last_chunk_id
        self.last_presented_source_index = current_source_index
        self.last_presented_frame_index = self.current_frame_index
        if render_ms >= 20.0 and (now - self.last_slow_render_log_at) > 0.25:
            self.last_slow_render_log_at = now
            print(
                f"🖼️ [MuseTalkQtPreview] Slow frame render: {render_ms:.1f} ms "
                f"(chunk={self.last_chunk_id}, frame={self.current_frame_index}, "
                f"cache={'hit' if cache_hit else 'miss'}, load={load_ms:.1f} ms, "
                f"pixmap={pixmap_ms:.1f} ms, set={set_ms:.1f} ms)"
            )

    def consume_frame_feed(self):
        try:
            if not os.path.exists(MUSE_PREVIEW_FRAME_PATH):
                return False
            snapshot_mtime_ns = os.stat(MUSE_PREVIEW_FRAME_PATH).st_mtime_ns
            if snapshot_mtime_ns <= self.last_frame_snapshot_mtime_ns:
                return False
            with open(MUSE_PREVIEW_FRAME_PATH, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            self.last_frame_snapshot_mtime_ns = snapshot_mtime_ns
        except (OSError, json.JSONDecodeError):
            return False

        frame_path = payload.get("frame_path")
        frame_index = int(payload.get("frame_index", 0) or 0)
        source_index = int(payload.get("source_index", frame_index) or frame_index)
        chunk_id = payload.get("chunk_id")
        if (
            (chunk_id == self.last_presented_chunk_id and source_index == self.last_presented_source_index)
            or (chunk_id == self.last_consumed_feed_chunk_id and source_index == self.last_consumed_feed_source_index)
        ):
            return True
        self.last_consumed_feed_chunk_id = chunk_id
        self.last_consumed_feed_source_index = source_index
        self.last_chunk_id = chunk_id or self.last_chunk_id
        self.current_frame_index = frame_index
        self.last_start_index = source_index - frame_index
        if self.source_indices and 0 <= frame_index < len(self.source_indices):
            self.last_start_index = int(self.source_indices[frame_index]) - frame_index
        self.is_looping = bool(payload.get("loop", False))
        if self.frame_dir and (
            not self.frame_paths
            or frame_index + QT_PREVIEW_AHEAD_PRELOAD >= len(self.frame_paths)
        ):
            self._refresh_frame_paths_from_dir()
        if self.frame_paths:
            self._start_frame_preload(
                start_index=frame_index + 1,
                count=min(
                    max(len(self.frame_paths) - (frame_index + 1), 0),
                    QT_PREVIEW_AHEAD_PRELOAD,
                ),
            )
        self.render_current_frame(frame_path)
        return True

    def on_frame_tick(self):
        if self.consume_frame_feed():
            return
        if self.is_looping and self.frame_paths and self.chunk_started_at:
            elapsed = max(0.0, time.time() - self.chunk_started_at)
            frame_index = int(elapsed * max(self.fps, 1)) % len(self.frame_paths)
            if frame_index != self.current_frame_index:
                self.current_frame_index = frame_index
                self.render_current_frame(self.frame_paths[frame_index])

    def sync_state(self):
        state = self.fetch_state()
        if state:
            sync_time = float(state.get("sync_time", 0.0) or 0.0)
            if sync_time != self.current_sync_time:
                incoming_chunk_id = state.get("chunk_id")
                incoming_frame_dir = state.get("frame_dir", "")
                incoming_start_index = int(state.get("start_index", 0) or 0)
                same_chunk = (
                    incoming_chunk_id == self.last_chunk_id
                    and incoming_frame_dir == self.last_frame_dir
                    and incoming_start_index == self.last_start_index
                )
                previous_chunk_id = self.last_chunk_id
                previous_frame_index = self.current_frame_index
                previous_start_index = self.last_start_index
                self.current_sync_time = sync_time
                self.fps = int(state.get("fps", 24) or 24)
                self.duration_seconds = float(state.get("duration_seconds", 0.0) or 0.0)
                self.expected_frame_count = int(state.get("expected_frame_count", 0) or len(state.get("frame_paths", [])))
                self.trim_start_frames = int(state.get("trim_start_frames", 0) or 0)
                self.chunk_started_at = sync_time
                self.is_looping = bool(state.get("loop", False))
                incoming_source_indices = list(state.get("source_indices", []) or [])
                text = state.get("text", "").strip()
                if state.get("status") == "ready":
                    self.status_label.setText(f"MuseTalk: {text[:60]}")
                elif incoming_chunk_id and str(incoming_chunk_id).startswith("first_chunk_plan:"):
                    self.status_label.setText("MuseTalk warming speech")
                elif self.is_looping:
                    self.status_label.setText("MuseTalk idle")
                else:
                    self.status_label.setText("MuseTalk preview idle")
                if same_chunk:
                    pass
                else:
                    self.frame_paths = list(state.get("frame_paths", []) or [])
                    self.source_indices = incoming_source_indices
                    self.frame_dir = incoming_frame_dir
                    self.last_chunk_id = incoming_chunk_id
                    self.last_start_index = incoming_start_index
                    self.last_frame_dir = incoming_frame_dir
                    self.preload_generation += 1
                    self.preload_frontier = -1
                    if previous_chunk_id and self.last_chunk_id and previous_chunk_id != self.last_chunk_id:
                        previous_source_index = self._source_index_for_frame(previous_frame_index)
                        self.pending_handoff_debug = {
                            "prev_chunk_id": previous_chunk_id,
                            "next_chunk_id": self.last_chunk_id,
                            "prev_source": previous_source_index,
                            "next_start": self.last_start_index,
                            "buffered": len(self.frame_paths),
                            "expected": self.expected_frame_count,
                        }
                        print(
                            f"🧪 [MuseTalkQtPreview] Handoff {previous_chunk_id} -> {self.last_chunk_id}: "
                            f"prev_frame={previous_frame_index}, prev_source={previous_source_index}, "
                            f"next_start={self.last_start_index}, buffered={len(state.get('frame_paths', []) or [])}, expected={self.expected_frame_count}"
                        )
                    if self.frame_paths:
                        initial_frame_index = 0
                        previous_source_index = self.last_presented_source_index
                        if (
                            previous_source_index is not None
                            and incoming_start_index <= previous_source_index + 1
                            and incoming_start_index >= previous_source_index - 12
                        ):
                            if self.source_indices:
                                for idx, source_idx in enumerate(self.source_indices):
                                    try:
                                        if int(source_idx) > int(previous_source_index):
                                            initial_frame_index = idx
                                            break
                                    except Exception:
                                        continue
                            else:
                                initial_frame_index = max(0, int(previous_source_index) - incoming_start_index + 1)
                                initial_frame_index = min(initial_frame_index, max(len(self.frame_paths) - 1, 0))
                        self.current_frame_index = initial_frame_index
                        self._start_frame_preload(
                            start_index=initial_frame_index,
                            count=min(max(len(self.frame_paths) - initial_frame_index, 1), QT_PREVIEW_INITIAL_PRELOAD),
                        )
                        first_frame_path = self.frame_paths[initial_frame_index]
                        if first_frame_path and os.path.exists(first_frame_path):
                            self.last_consumed_feed_chunk_id = self.last_chunk_id
                            self.last_consumed_feed_source_index = self._source_index_for_frame(initial_frame_index)
                            self.render_current_frame(first_frame_path)


def main():
    app = QtWidgets.QApplication(sys.argv)
    window = MuseTalkQtPreview()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

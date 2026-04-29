"""Telemetry widgets for chunk rendering and playback progress."""

from PySide6 import QtCore, QtGui, QtWidgets


class ChunkProgressTelemetryBar(QtWidgets.QWidget):
    def __init__(self, title, mode="preview", parent=None):
        super().__init__(parent)
        self.title = str(title or "")
        self.mode = str(mode or "preview")
        self._snapshot = {}
        self._preview_state = {}
        self.setMinimumHeight(26)

    def set_snapshot(self, snapshot, preview_state):
        self._snapshot = dict(snapshot or {})
        self._preview_state = dict(preview_state or {})
        self.update()

    def _ordered_chunks(self):
        chunks = list((self._snapshot or {}).get("chunks", []) or [])
        chunks.sort(key=lambda item: int((item or {}).get("sequence_index", 0) or 0))
        return chunks

    def _chunk_render_progress(self, chunk):
        chunk = dict(chunk or {})
        status = str(chunk.get("status", "") or "")
        if status in {"rendered"}:
            return 1.0
        expected = int(chunk.get("expected_frame_count", 0) or 0)
        rendered = int(chunk.get("rendered_frame_count", 0) or 0)
        if expected > 0 and rendered > 0:
            return max(0.0, min(float(rendered) / float(expected), 1.0))
        if status == "rendering":
            return 0.0
        return 0.0

    def _chunk_stage(self, chunk):
        chunk = dict(chunk or {})
        status = str(chunk.get("status", "") or "")
        playback_state = str(chunk.get("playback_state", "") or "")
        rendered = int(chunk.get("rendered_frame_count", 0) or 0)
        if status in {"failed"} or playback_state == "failed":
            return "failed"
        if status in {"cancelled"} or playback_state == "cancelled":
            return "cancelled"
        if playback_state in {"completed"}:
            return "completed"
        if playback_state in {"playing"}:
            return "playing"
        if status in {"rendered"}:
            return "rendered"
        if status == "rendering":
            return "rendering_frames" if rendered > 0 else "rendering_setup"
        if status == "queued_for_render":
            return "queued"
        if status == "generating_audio":
            return "tts"
        return "planned"

    def _render_bar_stage(self, chunk):
        stage = self._chunk_stage(chunk)
        if stage == "playing":
            return "rendered"
        if stage == "completed":
            return "completed"
        return stage

    def _stage_colors(self, stage):
        stage = str(stage or "planned")
        if stage == "tts":
            return (QtGui.QColor("#34255a"), QtGui.QColor("#8b6cf0"))
        if stage == "queued":
            return (QtGui.QColor("#4b3317"), QtGui.QColor("#d69c42"))
        if stage == "rendering_setup":
            return (QtGui.QColor("#4e2218"), QtGui.QColor("#ef8a5b"))
        if stage == "rendering_frames":
            return (QtGui.QColor("#18344f"), QtGui.QColor("#4fc3f7"))
        if stage == "rendered":
            return (QtGui.QColor("#1b3348"), QtGui.QColor("#70d6ff"))
        if stage == "playing":
            return (QtGui.QColor("#1f3d2a"), QtGui.QColor("#58d68d"))
        if stage == "completed":
            return (QtGui.QColor("#24303d"), QtGui.QColor("#8aa0b5"))
        if stage == "failed":
            return (QtGui.QColor("#4a1a20"), QtGui.QColor("#ff6b81"))
        if stage == "cancelled":
            return (QtGui.QColor("#2a2f36"), QtGui.QColor("#7f8a96"))
        return (QtGui.QColor("#223042"), QtGui.QColor("#3a4d63"))

    def _chunk_preview_progress(self, chunk):
        chunk = dict(chunk or {})
        playback_state = str(chunk.get("playback_state", "") or "")
        if playback_state == "completed":
            return 1.0
        state = dict(self._preview_state or {})
        try:
            active_index = int(state.get("sequence_index"))
        except Exception:
            active_index = None
        chunk_index = int(chunk.get("sequence_index", 0) or 0)
        if active_index is not None:
            if chunk_index < active_index:
                return 1.0
            if chunk_index > active_index:
                return 0.0
            preview_frame_index = int(state.get("preview_frame_index", -1) or -1)
            expected_frames = int(state.get("expected_frame_count", 0) or state.get("frame_count", 0) or chunk.get("expected_frame_count", 0) or 0)
            if preview_frame_index < 0 or expected_frames <= 1:
                return 0.0
            return max(0.0, min(float(preview_frame_index) / max(expected_frames - 1, 1), 1.0))
        return 1.0 if playback_state == "completed" else 0.0

    def _segment_count(self):
        if bool((self._snapshot or {}).get("stream_mode")):
            chunks = self._ordered_chunks()
            return max(1, len(chunks))
        return max(1, len(self._visual_segments()))

    def _ready_progress(self):
        progress = 0.0
        for chunk in self._ordered_chunks():
            status = str(chunk.get("status", "") or "")
            if status == "rendered":
                progress += 1.0
                continue
            partial = self._chunk_render_progress(chunk)
            if partial > 0.0:
                progress += partial
            break
        return progress

    def _preview_progress(self):
        chunks = self._ordered_chunks()
        completed_progress = 0.0
        for chunk in chunks:
            if str(chunk.get("playback_state", "") or "") == "completed":
                completed_progress += 1.0
            else:
                break
        state = dict(self._preview_state or {})
        sequence_index = state.get("sequence_index")
        preview_frame_index = int(state.get("preview_frame_index", -1) or -1)
        expected_frames = int(state.get("expected_frame_count", 0) or state.get("frame_count", 0) or 0)
        if sequence_index is None or preview_frame_index < 0 or expected_frames <= 1:
            return completed_progress
        try:
            sequence_index = int(sequence_index)
        except Exception:
            return completed_progress
        intra = max(0.0, min(float(preview_frame_index) / max(expected_frames - 1, 1), 1.0))
        return max(completed_progress, float(sequence_index) + intra)

    def _startup_gate_fraction(self, chunk):
        chunk = dict(chunk or {})
        startup_frames = int(chunk.get("startup_buffer_frames", 0) or 0)
        expected = int(chunk.get("expected_frame_count", 0) or 0)
        if startup_frames <= 0 or expected <= 0:
            return 0.0
        return max(0.0, min(float(startup_frames) / float(expected), 1.0))

    def _visual_segments(self):
        segments = []
        for chunk in self._ordered_chunks():
            gate_fraction = self._startup_gate_fraction(chunk)
            sequence_index = int(chunk.get("sequence_index", -1) or -1)
            expected = int(chunk.get("expected_frame_count", 0) or 0)
            total_weight = float(expected if expected > 0 else 1.0)
            if sequence_index == 0 and 0.0 < gate_fraction < 1.0:
                startup_weight = max(total_weight * gate_fraction, 1.0)
                remainder_weight = max(total_weight - startup_weight, 1.0)
                segments.append(
                    {
                        "chunk": chunk,
                        "part": "startup",
                        "start_fraction": 0.0,
                        "end_fraction": gate_fraction,
                        "weight": startup_weight,
                    }
                )
                segments.append(
                    {
                        "chunk": chunk,
                        "part": "remainder",
                        "start_fraction": gate_fraction,
                        "end_fraction": 1.0,
                        "weight": remainder_weight,
                    }
                )
            else:
                segments.append(
                    {
                        "chunk": chunk,
                        "part": "whole",
                        "start_fraction": 0.0,
                        "end_fraction": 1.0,
                        "weight": total_weight,
                    }
                )
        return segments

    def _segment_fill_fraction(self, segment, chunk_fraction):
        segment = dict(segment or {})
        start_fraction = float(segment.get("start_fraction", 0.0) or 0.0)
        end_fraction = float(segment.get("end_fraction", 1.0) or 1.0)
        span = max(end_fraction - start_fraction, 1e-6)
        if chunk_fraction <= start_fraction:
            return 0.0
        if chunk_fraction >= end_fraction:
            return 1.0
        return max(0.0, min((float(chunk_fraction) - start_fraction) / span, 1.0))

    def _progress_value(self):
        if self.mode == "ready":
            return self._ready_progress()
        return self._preview_progress()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)
        painter.setPen(QtGui.QPen(QtGui.QColor("#273342"), 1))
        painter.setBrush(QtGui.QColor("#10161f"))
        painter.drawRoundedRect(rect, 9, 9)

        title_rect = QtCore.QRectF(rect.left() + 8, rect.top() + 2, 100, 12)
        painter.setPen(QtGui.QColor("#8da6c1"))
        painter.setFont(QtGui.QFont("Segoe UI", 8))
        painter.drawText(title_rect, QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, self.title)

        bar_rect = QtCore.QRectF(rect.left() + 8, rect.top() + 14, rect.width() - 16, rect.height() - 18)
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QColor("#192331"))
        painter.drawRoundedRect(bar_rect, 6, 6)

        total_segments = self._segment_count()
        progress = max(0.0, min(self._progress_value(), float(total_segments)))
        stream_mode = bool((self._snapshot or {}).get("stream_mode"))

        fill_color = QtGui.QColor("#4fc3f7") if self.mode == "ready" else QtGui.QColor("#58d68d")
        border_color = QtGui.QColor("#8cc7ff") if self.mode == "ready" else QtGui.QColor("#9cf2bd")

        if stream_mode:
            fill_ratio = progress / max(float(total_segments), 1.0)
            filled_rect = QtCore.QRectF(bar_rect)
            filled_rect.setWidth(bar_rect.width() * fill_ratio)
            painter.setBrush(fill_color)
            painter.drawRoundedRect(filled_rect, 6, 6)

            if total_segments > 1:
                painter.setBrush(QtCore.Qt.NoBrush)
                separator_pen = QtGui.QPen(QtGui.QColor("#d7e3f1" if self.mode == "preview" else "#b8d4ea"))
                separator_pen.setWidth(1)
                separator_pen.setCosmetic(True)
                separator_pen.setStyle(QtCore.Qt.DotLine)
                separator_pen.setColor(QtGui.QColor(separator_pen.color().red(), separator_pen.color().green(), separator_pen.color().blue(), 90))
                painter.setPen(separator_pen)
                for index in range(1, total_segments):
                    x = bar_rect.left() + (bar_rect.width() * float(index) / float(total_segments))
                    painter.drawLine(
                        QtCore.QPointF(x, bar_rect.top() + 1.0),
                        QtCore.QPointF(x, bar_rect.bottom() - 1.0),
                    )
                painter.setPen(QtCore.Qt.NoPen)
        else:
            visual_segments = self._visual_segments()
            gap = 2.0
            total_gap = gap * max(total_segments - 1, 0)
            usable_width = max(12.0, bar_rect.width() - total_gap)
            total_weight = sum(max(float(seg.get("weight", 1.0) or 1.0), 0.001) for seg in visual_segments)
            seg_x = bar_rect.left()
            for index in range(total_segments):
                segment = visual_segments[index] if index < len(visual_segments) else {}
                weight = max(float(segment.get("weight", 1.0) or 1.0), 0.001)
                if index == total_segments - 1:
                    segment_width = max(3.0, (bar_rect.right() - seg_x))
                else:
                    segment_width = max(3.0, usable_width * (weight / max(total_weight, 0.001)))
                seg_rect = QtCore.QRectF(seg_x, bar_rect.top(), segment_width, bar_rect.height())
                chunk = dict(segment.get("chunk", {}) or {})
                if self.mode == "ready":
                    stage = self._render_bar_stage(chunk)
                    stage_bg, stage_fg = self._stage_colors(stage)
                else:
                    stage_fg = fill_color
                if self.mode == "ready":
                    painter.setBrush(stage_bg)
                else:
                    painter.setBrush(QtGui.QColor("#223042"))
                painter.drawRoundedRect(seg_rect, 4, 4)
                if self.mode == "ready":
                    chunk_fill_fraction = self._chunk_render_progress(chunk)
                else:
                    chunk_fill_fraction = self._chunk_preview_progress(chunk)
                fill_fraction = self._segment_fill_fraction(segment, chunk_fill_fraction)
                if fill_fraction <= 0:
                    if self.mode == "ready" and stage in {"tts", "queued", "rendering_setup"}:
                        painter.setPen(QtGui.QPen(stage_fg, 1))
                        painter.setBrush(QtCore.Qt.NoBrush)
                        painter.drawRoundedRect(seg_rect.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
                        painter.setPen(QtCore.Qt.NoPen)
                    continue
                if segment.get("part") == "startup":
                    painter.setPen(QtGui.QPen(QtGui.QColor("#9fdcff"), 1))
                else:
                    painter.setPen(QtCore.Qt.NoPen)
                painter.setBrush(stage_fg if self.mode == "ready" else fill_color)
                filled = QtCore.QRectF(seg_rect)
                filled.setWidth(max(1.0, seg_rect.width() * fill_fraction))
                painter.drawRoundedRect(filled, 4, 4)
                painter.setPen(QtCore.Qt.NoPen)
                seg_x += segment_width + gap

        painter.setPen(QtGui.QPen(border_color, 1))
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawRoundedRect(bar_rect, 6, 6)


class PipelineTelemetryWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.summary_label = QtWidgets.QLabel("Telemetry appears during MuseTalk and VaM replies.")
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet("color: #9fb2c6;")
        layout.addWidget(self.summary_label)

        self.legend_label = QtWidgets.QLabel(
            "<span style='color:#8b6cf0;'>TTS</span>  "
            "<span style='color:#d69c42;'>Queued</span>  "
            "<span style='color:#ef8a5b;'>Render Setup</span>  "
            "<span style='color:#4fc3f7;'>Frames</span>  "
            "<span style='color:#9fdcff;'>First chunk split at startup gate</span>"
        )
        self.legend_label.setStyleSheet("color: #7f95ab;")
        layout.addWidget(self.legend_label)

        self.ready_bar = ChunkProgressTelemetryBar("Render Ready", mode="ready")
        self.preview_bar = ChunkProgressTelemetryBar("Preview / Playback", mode="preview")
        layout.addWidget(self.ready_bar)
        layout.addWidget(self.preview_bar)

    def update_snapshot(self, snapshot, preview_state):
        snapshot = dict(snapshot or {})
        preview_state = dict(preview_state or {})
        self.ready_bar.set_snapshot(snapshot, preview_state)
        self.preview_bar.set_snapshot(snapshot, preview_state)

        chunks = list(snapshot.get("chunks", []) or [])
        chunk_total = len(chunks)
        if chunk_total <= 0:
            self.summary_label.setText("Telemetry appears during MuseTalk and VaM replies.")
            return

        ready_progress = self.ready_bar._ready_progress()
        preview_progress = self.preview_bar._preview_progress()
        lead_chunks = ready_progress - preview_progress
        stream_mode = bool(snapshot.get("stream_mode"))
        stream_open = bool(snapshot.get("stream_open"))
        engine_mode = str(snapshot.get("engine_mode", "") or "").strip().lower()
        if stream_mode and stream_open:
            phase = "Streaming"
        elif stream_mode:
            phase = "Stream settling"
        elif engine_mode == "vam":
            phase = "VaM delegated playback"
        else:
            phase = "Chunked reply"
        if lead_chunks >= 1.5:
            assessment = "Comfortable buffer lead"
            color = "#9cf2bd"
        elif lead_chunks >= 0.5:
            assessment = "Tight but healthy"
            color = "#f5d76e"
        else:
            assessment = "Preview is close to the buffer edge"
            color = "#ff8f8f"
        self.summary_label.setText(
            f"{phase}: preview {preview_progress:.2f}/{chunk_total} chunks, "
            f"render ready {ready_progress:.2f}/{chunk_total}, "
            f"lead {lead_chunks:.2f} chunks. "
            f"<span style='color:{color}; font-weight:700;'>{assessment}.</span>"
        )
        if not stream_mode and chunks:
            first_chunk = dict(chunks[0] or {})
            gate_frames = int(first_chunk.get("startup_buffer_frames", 0) or 0)
            expected_frames = int(first_chunk.get("expected_frame_count", 0) or 0)
            if gate_frames > 0 and expected_frames > 0:
                self.summary_label.setText(
                    self.summary_label.text()
                    + f" <span style='color:#9fdcff;'>Chunk 1 split: startup {gate_frames}/{expected_frames} frames.</span>"
                )

    def value(self):
        return int(self._value)

    def setValue(self, value):
        bounded = max(self._minimum, min(self._maximum, int(value)))
        changed = bounded != self._value
        self._value = bounded
        self.line_edit.setText(str(bounded))
        if changed and not self._suppress_signal:
            self.valueChanged.emit(self._value)

    def stepBy(self, amount):
        self.setValue(self._value + int(amount))

    def _commit_text(self):
        text = (self.line_edit.text() or "").replace(",", "").strip()
        try:
            value = int(text)
        except Exception:
            value = self._value
        self.setValue(value)

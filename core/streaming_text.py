"""Streaming reply text assembly and cut-point decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import threading
import time
from typing import Callable


STREAM_FIRST_CHUNK_MIN_CHARS = 40
STREAM_FORCE_FLUSH_SECONDS = 0.30
STREAM_FORCE_FLUSH_LATER_SECONDS = 0.70
STREAM_FLUSH_RELAX_LEAD_SECONDS = 1.0
STREAM_FLUSH_DISABLE_LEAD_SECONDS = 2.5
STREAM_FIRST_CHUNK_PLAN_SECONDS = 1.25
STREAM_FIRST_CHUNK_PLAN_SYNC_MAX_SECONDS = 0.75
STREAM_FIRST_CHUNK_IDLE_SYNC_MAX_SECONDS = 0.6


@dataclass
class StreamingReplyState:
    full_text: str = ""
    error: str | None = None
    done: threading.Event = field(default_factory=threading.Event)
    cancel_requested: threading.Event = field(default_factory=threading.Event)
    first_chunk_emitted: threading.Event = field(default_factory=threading.Event)


class StreamingChunkAssembler:
    def __init__(
        self,
        target_chars,
        max_chars,
        *,
        min_chunk_size=10,
        config_getter: Callable[[str, object], object] | None = None,
        available_emotion_tags_getter: Callable[[], list[str]] | None = None,
        last_emotion_getter: Callable[[str], str | None] | None = None,
        control_prefix_checker: Callable[[str], bool] | None = None,
        visual_prefix_checker: Callable[[str], bool] | None = None,
        visual_tail_filter: Callable[[str], tuple[str, str | None]] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.min_chunk_size = max(1, int(min_chunk_size))
        self.target_chars = max(self.min_chunk_size, int(target_chars))
        self.max_chars = max(self.target_chars + 20, int(max_chars))
        self.config_getter = config_getter or (lambda _key, default=None: default)
        self.available_emotion_tags_getter = available_emotion_tags_getter or (lambda: [])
        self.last_emotion_getter = last_emotion_getter or (lambda _text: None)
        self.control_prefix_checker = control_prefix_checker or (lambda _fragment: False)
        self.visual_prefix_checker = visual_prefix_checker or (lambda _fragment: False)
        self.visual_tail_filter = visual_tail_filter
        self.clock = clock
        self.buffer = ""
        self.active_emotion = "neutral"
        self.emission_count = 0
        self.buffer_started_at = None
        self.buffer_chars_received = 0
        self.visual_tail_suppressed = False

    def feed(self, text, final=False, force=False):
        if text and not self.visual_tail_suppressed:
            if not self.buffer:
                self.buffer_started_at = self.clock()
                self.buffer_chars_received = 0
            self.buffer += text
            self.buffer_chars_received += len(text)
            self._filter_visual_tail()
        emitted = []
        while True:
            decision = self._find_cut_index(final=final, force=force)
            cut = int(decision.get("cut", 0) or 0)
            if cut <= 0:
                break
            chunk_info = self._emit_chunk(cut, decision)
            if chunk_info:
                emitted.append(chunk_info)
        return emitted

    def _filter_visual_tail(self):
        if self.visual_tail_filter is None or not self.buffer:
            return
        cleaned, prompt = self.visual_tail_filter(self.buffer)
        cleaned_text = str(cleaned or "")
        if not prompt and cleaned_text == self.buffer:
            return
        self.buffer = cleaned_text
        self.visual_tail_suppressed = True

    def _config(self, key, default):
        return self.config_getter(key, default)

    def _effective_max(self):
        working = self.buffer
        effective_max = min(len(working), self.max_chars)
        unmatched_open = working.rfind("[", 0, effective_max)
        unmatched_close = working.rfind("]", 0, effective_max)
        if unmatched_open > unmatched_close:
            fragment = working[unmatched_open + 1:effective_max]
            if (not fragment or self.control_prefix_checker(fragment)
                    or self.visual_prefix_checker(fragment)):
                effective_max = unmatched_open
        return effective_max

    def _flush_policy(self):
        first_min = int(self._config("stream_first_chunk_min_chars", STREAM_FIRST_CHUNK_MIN_CHARS) or STREAM_FIRST_CHUNK_MIN_CHARS)
        minimum = first_min if self.emission_count == 0 else max(self.min_chunk_size, self.target_chars // 2)
        seconds = (
            float(self._config("stream_force_flush_seconds", STREAM_FORCE_FLUSH_SECONDS) or STREAM_FORCE_FLUSH_SECONDS)
            if self.emission_count == 0
            else float(self._config("stream_force_flush_later_seconds", STREAM_FORCE_FLUSH_LATER_SECONDS) or STREAM_FORCE_FLUSH_LATER_SECONDS)
        )
        return first_min, minimum, seconds

    def next_flush_deadline(self) -> float | None:
        """Return the pending eligible deadline; ineligible text needs new input."""
        if self.buffer_started_at is None or not self.buffer.strip():
            return None
        _first_min, minimum, seconds = self._flush_policy()
        if self._effective_max() < minimum:
            return None
        return self.buffer_started_at + seconds

    def _find_cut_index(self, final=False, force=False):
        working = self.buffer
        if not working.strip():
            return {"cut": len(working) if final and working else 0, "quality": 0.0, "reason": "empty"}
        effective_max = self._effective_max()
        if final:
            if effective_max == len(working):
                return {"cut": effective_max, "quality": 0.2, "reason": "final"}
            return self._emergency_force_cut(working, effective_max, self.min_chunk_size, quality_floor=0.2, reason_prefix="final")
        target_chars = self.target_chars
        configured_first_min, min_force_chars, max_allowed_time = self._flush_policy()
        if force and effective_max >= min_force_chars:
            return self._emergency_force_cut(working, effective_max, min_force_chars)

        if self.emission_count == 0:
            target_chars = max(configured_first_min, self.target_chars)

        elapsed_time = 0.0
        if self.buffer_started_at is not None:
            elapsed_time = max(0.0, self.clock() - self.buffer_started_at)
        # Flush settings are deadlines, not hints extended by playback buffering.
        if elapsed_time >= max_allowed_time and effective_max >= min_force_chars:
            return self._emergency_force_cut(working, effective_max, min_force_chars, reason_prefix="timeout")

        if effective_max >= target_chars:
            # Use the last sentence boundary already available, without waiting to
            # fill the maximum or guessing an early word/clause boundary.
            strong_cut = self._find_last_boundary_cluster(
                working, effective_max - 1, target_chars - 1, ".!?\n"
            )
            if strong_cut is not None:
                return {"cut": strong_cut, "quality": 1.0, "reason": "strong"}

        if effective_max >= self.max_chars:
            return self._emergency_force_cut(
                working, effective_max, self.min_chunk_size, reason_prefix="max_chars",
            )
        return {"cut": 0, "quality": 0.0, "reason": "wait"}

    def _best_punctuation_cut(self, working, effective_max, min_force_chars):
        strong_cut = self._find_last_boundary_cluster(working, effective_max - 1, min_force_chars - 1, ".!?\n")
        if strong_cut is not None:
            return {"cut": strong_cut, "quality": 0.7, "reason": "strong"}
        weak_cut = self._find_last_boundary_cluster(working, effective_max - 1, min_force_chars - 1, ",;:")
        if weak_cut is not None:
            return {"cut": weak_cut, "quality": 0.5, "reason": "weak"}
        return None


    def _emergency_force_cut(self, working, effective_max, min_force_chars, quality_floor=0.0, reason_prefix="forced"):
        punct_decision = self._best_punctuation_cut(working, effective_max, min_force_chars)
        if punct_decision is not None:
            punct_decision["quality"] = max(quality_floor, punct_decision["quality"])
            punct_decision["reason"] = f"{reason_prefix}_{punct_decision['reason']}"
            return punct_decision
        for index in range(effective_max - 1, min_force_chars - 1, -1):
            if working[index].isspace():
                return {"cut": index + 1, "quality": max(quality_floor, 0.2), "reason": f"{reason_prefix}_whitespace"}
        for index in range(min(effective_max - 1, min_force_chars - 2), self.min_chunk_size - 1, -1):
            if working[index].isspace():
                return {
                    "cut": index + 1,
                    "quality": max(quality_floor, 0.1),
                    "reason": f"{reason_prefix}_short_whitespace",
                }
        return {"cut": effective_max, "quality": 0.0, "reason": f"{reason_prefix}_panic"}

    @staticmethod
    def _find_last_boundary_cluster(text, start_index, min_index, boundary_chars):
        for index in range(start_index, min_index - 1, -1):
            if text[index] in boundary_chars:
                cluster_end = index + 1
                while cluster_end <= start_index and (
                    text[cluster_end] in "\"')]}»”’"
                    or text[cluster_end] in ".!?,;:-"
                ):
                    cluster_end += 1
                return cluster_end
        return None

    def _emit_chunk(self, cut_index, decision):
        raw = self.buffer[:cut_index]
        self.buffer = self.buffer[cut_index:].lstrip()
        chunk = re.sub(r"\s+", " ", raw).strip()
        if not chunk:
            return None

        if self.active_emotion != "neutral":
            starts_with_emotion = False
            for tag in self.available_emotion_tags_getter():
                if chunk.lower().startswith(tag):
                    starts_with_emotion = True
                    break
            if not starts_with_emotion:
                chunk = f"[{self.active_emotion}] {chunk}"

        last_emotion = self.last_emotion_getter(chunk)
        if last_emotion:
            self.active_emotion = last_emotion

        self.emission_count += 1
        if not self.buffer:
            self.buffer_started_at = None
            self.buffer_chars_received = 0
        else:
            self.buffer_started_at = self.clock()
            self.buffer_chars_received = 0
        return {
            "text": chunk,
            "quality": float(decision.get("quality", 0.0) or 0.0),
            "reason": str(decision.get("reason", "unknown") or "unknown"),
            "chars": len(chunk),
        }

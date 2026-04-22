"""Streaming reply text assembly and cut-point decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import threading
import time
from typing import Callable


STREAM_FIRST_CHUNK_MIN_CHARS = 28
STREAM_FORCE_FLUSH_SECONDS = 0.9
STREAM_FORCE_FLUSH_LATER_SECONDS = 1.4
STREAM_FIRST_CHUNK_PLAN_SECONDS = 1.25
STREAM_FIRST_CHUNK_PLAN_SYNC_MAX_SECONDS = 0.75
STREAM_FIRST_CHUNK_IDLE_SYNC_MAX_SECONDS = 0.6
STREAM_TINY_TAIL_CHARS = 18
STREAM_WHITESPACE_FALLBACK_MARGIN = 24
STREAM_POST_TARGET_PUNCTUATION_MARGIN = 18
STREAM_POST_TARGET_PUNCTUATION_WAIT_SECONDS = 0.45
STREAM_CLAUSE_FALLBACK_MARGIN = 40
STREAM_CLAUSE_FALLBACK_MIN_SCORE = 1.15
STREAM_CLAUSE_FALLBACK_WAIT_SECONDS = 0.85

STREAM_CLAUSE_STARTERS = {
    "and", "but", "so", "then", "because", "though", "although", "however",
    "instead", "meanwhile", "afterward", "afterwards", "therefore", "thus",
    "still", "yet", "while", "when", "where", "if", "since", "before",
    "once", "unless", "except", "plus", "also", "besides", "meanwhile",
}

STREAM_BAD_ENDING_WORDS = {
    "a", "an", "and", "as", "at", "because", "but", "by", "for", "from",
    "if", "in", "into", "of", "on", "or", "so", "than", "that", "the",
    "this", "those", "through", "to", "under", "until", "with", "without",
    "while", "which", "who", "whom", "whose", "your", "our", "their", "my",
    "his", "her", "its",
}


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
        clock: Callable[[], float] = time.time,
    ):
        self.min_chunk_size = max(1, int(min_chunk_size))
        self.target_chars = max(self.min_chunk_size, int(target_chars))
        self.max_chars = max(self.target_chars + 20, int(max_chars))
        self.config_getter = config_getter or (lambda _key, default=None: default)
        self.available_emotion_tags_getter = available_emotion_tags_getter or (lambda: [])
        self.last_emotion_getter = last_emotion_getter or (lambda _text: None)
        self.control_prefix_checker = control_prefix_checker or (lambda _fragment: False)
        self.visual_prefix_checker = visual_prefix_checker or (lambda _fragment: False)
        self.clock = clock
        self.buffer = ""
        self.active_emotion = "neutral"
        self.emission_count = 0
        self.buffer_started_at = None
        self.buffer_chars_received = 0

    def feed(self, text, final=False, force=False):
        if text:
            if not self.buffer:
                self.buffer_started_at = self.clock()
                self.buffer_chars_received = 0
            self.buffer += text
            self.buffer_chars_received += len(text)
        emitted = []
        while True:
            decision = self._find_cut_index(final=final, force=force)
            cut = int(decision.get("cut", 0) or 0)
            if cut <= 0:
                break
            chunk_info = self._emit_chunk(cut, decision)
            if chunk_info:
                emitted.append(chunk_info)
            if final:
                break
        return emitted

    def _config(self, key, default):
        return self.config_getter(key, default)

    def _find_cut_index(self, final=False, force=False):
        working = self.buffer
        if not working.strip():
            return {"cut": len(working) if final and working else 0, "quality": 0.0, "reason": "empty"}

        effective_max = min(len(working), self.max_chars)
        unmatched_open = working.rfind("[", 0, effective_max)
        unmatched_close = working.rfind("]", 0, effective_max)
        if unmatched_open > unmatched_close:
            unmatched_fragment = working[unmatched_open + 1:effective_max]
            if self.control_prefix_checker(unmatched_fragment) or self.visual_prefix_checker(unmatched_fragment):
                effective_max = unmatched_open

        if final:
            return self._emergency_force_cut(working, effective_max, self.min_chunk_size, quality_floor=0.2, reason_prefix="final")
        target_chars = self.target_chars
        configured_first_min = int(self._config("stream_first_chunk_min_chars", STREAM_FIRST_CHUNK_MIN_CHARS) or STREAM_FIRST_CHUNK_MIN_CHARS)
        min_force_chars = configured_first_min if self.emission_count == 0 else max(self.min_chunk_size, self.target_chars // 2)
        if force and effective_max >= min_force_chars:
            return self._emergency_force_cut(working, effective_max, min_force_chars)

        if self.emission_count == 0:
            target_chars = max(configured_first_min, min(self.target_chars, 48))

        elapsed_time = 0.0
        if self.buffer_started_at is not None:
            elapsed_time = max(0.0, self.clock() - self.buffer_started_at)
        max_allowed_time = (
            float(self._config("stream_force_flush_seconds", STREAM_FORCE_FLUSH_SECONDS) or STREAM_FORCE_FLUSH_SECONDS)
            if self.emission_count == 0
            else float(self._config("stream_force_flush_later_seconds", STREAM_FORCE_FLUSH_LATER_SECONDS) or STREAM_FORCE_FLUSH_LATER_SECONDS)
        )

        if elapsed_time > max_allowed_time and effective_max >= min_force_chars:
            return self._emergency_force_cut(working, effective_max, min_force_chars, reason_prefix="timeout")

        if effective_max < target_chars:
            if effective_max >= min_force_chars and elapsed_time > 0.0:
                cps = float(self.buffer_chars_received) / max(elapsed_time, 0.1)
                chars_needed = max(0, target_chars - effective_max)
                predicted_time_to_target = chars_needed / max(cps, 1.0)
                max_patience = 0.75 if self.emission_count == 0 else 1.5
                if predicted_time_to_target > max_patience:
                    punct_decision = self._best_punctuation_cut(working, effective_max, min_force_chars)
                    if punct_decision is not None:
                        punct_decision["reason"] = f"cps_{punct_decision['reason']}"
                        return punct_decision
            return {"cut": 0, "quality": 0.0, "reason": "wait"}

        pretarget_floor = max(
            configured_first_min if self.emission_count == 0 else max(self.min_chunk_size, target_chars // 2),
            self.min_chunk_size,
        )

        pretarget_strong_cut = self._find_last_boundary_cluster(working, effective_max - 1, pretarget_floor - 1, ".!?\n")
        if pretarget_strong_cut is not None:
            trailing_tail = re.sub(r"\s+", " ", working[pretarget_strong_cut:effective_max]).strip()
            if trailing_tail and len(trailing_tail) <= STREAM_TINY_TAIL_CHARS:
                quality = 0.9 if len(trailing_tail.split()) <= 3 else 0.7
                return {"cut": pretarget_strong_cut, "quality": quality, "reason": "pretarget_strong"}

        pretarget_weak_cut = self._find_last_boundary_cluster(working, effective_max - 1, pretarget_floor - 1, ",;:")
        if pretarget_weak_cut is not None:
            trailing_tail = re.sub(r"\s+", " ", working[pretarget_weak_cut:effective_max]).strip()
            if trailing_tail and len(trailing_tail) <= max(10, STREAM_TINY_TAIL_CHARS // 2):
                return {"cut": pretarget_weak_cut, "quality": 0.5, "reason": "pretarget_weak"}

        strong_cut = self._find_last_boundary_cluster(working, effective_max - 1, target_chars - 1, ".!?\n")
        if strong_cut is not None:
            trailing_tail = re.sub(r"\s+", " ", working[strong_cut:effective_max]).strip()
            if trailing_tail and len(trailing_tail) <= STREAM_TINY_TAIL_CHARS:
                quality = 0.9 if len(trailing_tail.split()) <= 3 else 1.0
                return {"cut": strong_cut, "quality": quality, "reason": "strong"}
            return {"cut": strong_cut, "quality": 1.0, "reason": "strong"}

        weak_cut = self._find_last_boundary_cluster(working, effective_max - 1, target_chars - 1, ",;:")
        if weak_cut is not None:
            trailing_tail = re.sub(r"\s+", " ", working[weak_cut:effective_max]).strip()
            if trailing_tail and len(trailing_tail) <= max(10, STREAM_TINY_TAIL_CHARS // 2):
                return {"cut": weak_cut, "quality": 0.8, "reason": "weak"}
            return {"cut": weak_cut, "quality": 0.8, "reason": "weak"}

        if self.emission_count > 0:
            punctuation_lookahead_cap = min(
                self.max_chars,
                target_chars + STREAM_WHITESPACE_FALLBACK_MARGIN + STREAM_POST_TARGET_PUNCTUATION_MARGIN,
            )
            punctuation_waiting_window = (
                effective_max < punctuation_lookahead_cap
                and elapsed_time < max_allowed_time
                and elapsed_time < STREAM_POST_TARGET_PUNCTUATION_WAIT_SECONDS + (0.003 * max(0, effective_max - target_chars))
            )
            if punctuation_waiting_window:
                return {"cut": 0, "quality": 0.0, "reason": "wait_punctuation"}

        clause_cut = self._find_clause_fallback_cut(working, effective_max, target_chars, min_force_chars)
        if clause_cut is not None:
            clause_waiting_window = (
                self.emission_count > 0
                and effective_max < min(self.max_chars, target_chars + STREAM_CLAUSE_FALLBACK_MARGIN)
                and elapsed_time < max_allowed_time
                and elapsed_time < STREAM_CLAUSE_FALLBACK_WAIT_SECONDS + (0.003 * max(0, effective_max - target_chars))
            )
            if not clause_waiting_window:
                return clause_cut

        whitespace_fallback_ready = (
            effective_max >= min(self.max_chars, target_chars + STREAM_WHITESPACE_FALLBACK_MARGIN)
            or elapsed_time > (0.9 if self.emission_count == 0 else 1.8)
        )
        for index in range(effective_max - 1, target_chars - 1, -1):
            if whitespace_fallback_ready and working[index].isspace():
                return {"cut": index + 1, "quality": 0.2, "reason": "whitespace"}

        if effective_max >= self.max_chars:
            return {"cut": effective_max, "quality": 0.0, "reason": "max_chars"}
        return {"cut": 0, "quality": 0.0, "reason": "wait"}

    def _best_punctuation_cut(self, working, effective_max, min_force_chars):
        strong_cut = self._find_last_boundary_cluster(working, effective_max - 1, min_force_chars - 1, ".!?\n")
        if strong_cut is not None:
            return {"cut": strong_cut, "quality": 0.7, "reason": "strong"}
        weak_cut = self._find_last_boundary_cluster(working, effective_max - 1, min_force_chars - 1, ",;:")
        if weak_cut is not None:
            return {"cut": weak_cut, "quality": 0.5, "reason": "weak"}
        return None

    @staticmethod
    def _normalize_boundary_word(value):
        return re.sub(r"^[^A-Za-z0-9]+|[^A-Za-z0-9]+$", "", value or "").lower()

    @staticmethod
    def _split_boundary_words(value):
        if not value:
            return []
        return re.findall(r"[A-Za-z0-9']+", value)

    def _find_clause_fallback_cut(self, working, effective_max, target_chars, min_force_chars):
        best_choice = None
        best_score = STREAM_CLAUSE_FALLBACK_MIN_SCORE
        search_start = max(target_chars - 1, min_force_chars - 1)
        search_end = max(search_start, min(effective_max - 1, target_chars + STREAM_CLAUSE_FALLBACK_MARGIN))
        for index in range(search_end, search_start - 1, -1):
            if not working[index].isspace():
                continue

            left = working[:index].rstrip()
            right = working[index + 1:effective_max].lstrip()
            if len(left) < min_force_chars or len(right) < 2:
                continue

            left_words = self._split_boundary_words(left[-40:])
            right_words = self._split_boundary_words(right[:40])
            last_word = self._normalize_boundary_word(left_words[-1] if left_words else "")
            next_word_raw = right_words[0] if right_words else ""
            next_word = self._normalize_boundary_word(next_word_raw)
            score = 0.0
            reason = "clause_soft"

            left_tail = left[-16:]
            if left and left[-1] in "\"')]}»”’":
                score += 0.55
                reason = "clause_quote"
            if left_tail.endswith(" --") or left_tail.endswith(" -") or left_tail.endswith(":") or left_tail.endswith(";"):
                score += 0.7
                reason = "clause_dash" if "-" in left_tail else "clause_soft"
            elif re.search(r"[,:;]\s*[\"')\]}»”’]*$", left_tail):
                score += 0.45

            if re.search(r"[,:;]\s+[A-Z][^ ]*$", working[max(0, index - 24):effective_max]):
                score += 0.45
            if next_word in STREAM_CLAUSE_STARTERS:
                score += 0.95
                reason = "clause_starter"
            elif next_word_raw[:1].isupper() and next_word_raw.lower() != next_word_raw:
                score += 0.55
                reason = "clause_capital"

            if len(right_words) <= 4:
                score -= 0.3
            if last_word in STREAM_BAD_ENDING_WORDS:
                score -= 1.1
            elif len(last_word) <= 2:
                score -= 0.25

            overshoot = max(0, index - target_chars)
            score += min(0.45, overshoot / 36.0)

            if score > best_score:
                quality = 0.55 if score >= 1.7 else 0.45
                best_choice = {"cut": index + 1, "quality": quality, "reason": reason}
                best_score = score
        return best_choice

    def _emergency_force_cut(self, working, effective_max, min_force_chars, quality_floor=0.0, reason_prefix="forced"):
        punct_decision = self._best_punctuation_cut(working, effective_max, min_force_chars)
        if punct_decision is not None:
            punct_decision["quality"] = max(quality_floor, punct_decision["quality"])
            punct_decision["reason"] = f"{reason_prefix}_{punct_decision['reason']}"
            return punct_decision
        for index in range(effective_max - 1, min_force_chars - 1, -1):
            if working[index].isspace():
                return {"cut": index + 1, "quality": max(quality_floor, 0.2), "reason": f"{reason_prefix}_whitespace"}
        return {"cut": effective_max, "quality": 0.0, "reason": f"{reason_prefix}_panic"}

    @staticmethod
    def _find_last_boundary_cluster(text, start_index, min_index, boundary_chars):
        for index in range(start_index, min_index - 1, -1):
            if text[index] in boundary_chars:
                cluster_end = index + 1
                while cluster_end < len(text) and (
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

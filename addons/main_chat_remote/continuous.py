"""Reusable host-owned Continuous Mode. No Qt, history writes or speech control."""
from __future__ import annotations
from dataclasses import asdict
from .continuous_guidance import guidance_presets, selected_guidance
import threading
import time
import uuid

from core.runtime.contracts import CancellationToken
from .continuous_settings import ContinuousSettings
from .continuous_reply import AutoReplyDraft


FUTURE_REPLY_TEXT_SETTINGS = frozenset({
    "default_reply", "guidance", "use_premade", "guidance_preset", "guidance_strength",
})


def preserves_current_reply(patch: object) -> bool:
    """Text direction edits affect the next turn, not prepared speech."""
    return isinstance(patch, dict) and bool(patch) and patch.keys() <= FUTURE_REPLY_TEXT_SETTINGS


class ContinuousController:
    def __init__(self, *, settings=None, save_settings=None, clock=time.monotonic):
        self.settings = settings or ContinuousSettings()
        self._save = save_settings or (lambda value: None)
        self._clock = clock
        self._lock = threading.RLock()
        self._owner = ""
        self._heartbeat = 0.0
        self._revision = 0
        self._state = "stopped"
        self._reason = ""
        self._queue: list[dict[str, str]] = []
        self._boundary: dict = {}
        self._consumed = ""
        self._deadline: float | None = None
        self._prepared: dict | None = None
        self._job: dict | None = None
        self._prefetched: dict | None = None
        self._manual_reply = ""
        self._manual_previous = ""
        self._awaiting_reply = ""
        self._count = 0
        self._failures = 0
        self._single = False
        self._force_boundary = None
        self._expired_reply_boundary = None
        self._claimed: dict[str, dict] = {}

    def _invalidate(self):
        self._force_boundary = None
        for item in (self._prepared, self._job, self._prefetched):
            if item: item["token"].cancel("continuous_changed")
        self._prepared = self._job = None
        self._prefetched = None
        self._deadline = None

    def _invalidate_future_text(self, reason: str, *, boundary: dict | None = None):
        for item in (self._job, self._prefetched):
            if item:
                item["token"].cancel(reason)
        self._job = self._prefetched = None
        current = self._prepared
        committed = bool(current and (current.get("speech_started") or current["id"] in self._claimed))
        if current and not committed and current["source"] != "queued_manual":
            current["token"].cancel(reason)
            self._prepared = None
        elif current and boundary is not None:
            # Keep text/audio already handed to the phone. Only the NEXT model
            # request uses this new prompt; old assistant stages stay invalid.
            current["boundary"] = dict(current["boundary"], persona=boundary.get("persona"))
        if not self._prepared and self._state not in {"paused", "stopped", "suspended"}:
            self._state = "waiting"

    def _pause(self, reason):
        self._invalidate(); self._state = "paused"; self._reason = reason

    def _suspend(self, reason):
        self._invalidate(); self._state = "suspended"; self._reason = reason

    def heartbeat(self, owner):
        with self._lock:
            if self._owner and owner != self._owner and self._clock() - self._heartbeat >= 10:
                self._suspend("Previous phone disconnected. Reconnect to continue.")
                self._queue.clear(); self._claimed.clear(); self._awaiting_reply = ""
                self._manual_reply = self._manual_previous = ""
                self._owner = ""; self._revision += 1
            if owner == self._owner:
                self._heartbeat = self._clock()
                if self._state == "suspended":
                    self._state = "waiting"; self._reason = ""

    def observe(self, boundary: dict):
        with self._lock:
            old = self._boundary
            # Only the runtime's exact history-preserving route close may rebase
            # a draft. Edits, new input and settings still invalidate speculation.
            if (old and type(boundary.get("retired_revision")) is int
                    and boundary["retired_revision"] == old.get("revision")
                    and boundary.get("revision") == old["revision"] + 1
                    and not boundary.get("manual_input_pending")
                    and all(old.get(key) == boundary.get(key) for key in
                            ("session", "persona", "assistant_id", "content", "history",
                             "provider_id", "model_id", "voice_fingerprint"))):
                for item in (self._prepared, self._job, self._prefetched):
                    if item and item["boundary"].get("revision") == old["revision"]:
                        item["boundary"] = dict(item["boundary"], revision=boundary["revision"])
                old = dict(old, revision=boundary["revision"])
            identity_key = ("persona_identity" if old.get("persona_identity") and boundary.get("persona_identity")
                            else "persona")
            if old and (old.get("session"), old.get(identity_key)) != (boundary.get("session"), boundary.get(identity_key)):
                self._pause("Conversation or persona changed")
                self._expired_reply_boundary = None
                self._queue.clear(); self._awaiting_reply = ""; self._consumed = ""; self._revision += 1
                self._manual_reply = self._manual_previous = ""
            elif any(old.get(key) != boundary.get(key) for key in
                     ("assistant_id", "revision", "provider_id", "model_id", "voice_fingerprint")):
                self._invalidate()
                self._expired_reply_boundary = None
                if self._state not in {"paused", "stopped", "suspended"}: self._state = "waiting"
            elif old.get("persona") != boundary.get("persona"):
                self._invalidate_future_text("persona_prompts_changed", boundary=boundary)
                self._revision += 1
            if boundary.get("manual_input_pending"):
                self._invalidate()
                self._expired_reply_boundary = None
                if self._state not in {"paused", "stopped", "suspended"}: self._state = "waiting"
            self._boundary = dict(boundary)
            if self._manual_reply and boundary.get("ready") and boundary.get("reply_id") == self._manual_reply:
                self._manual_reply = self._manual_previous = ""
            if boundary.get("reply_ended"):
                if (self._awaiting_reply and not self._manual_reply
                        and boundary.get("error") == "Current reply was cancelled or replaced"
                        and boundary.get("assistant_id") and boundary.get("forceable")):
                    self._expired_reply_boundary = (boundary.get("session"), boundary.get("revision"),
                                                    boundary.get("assistant_id"))
                if self._manual_reply:
                    self._manual_reply = self._manual_previous = ""
                    if self._state != "stopped":
                        self._pause("Manual reply ended before playback confirmation. Check the conversation, then resume.")
                elif self._awaiting_reply and self._state == "suspended":
                    self._pause("Automatic reply ended before playback confirmation. Check the conversation, then resume.")
                self._awaiting_reply = ""
            if self._awaiting_reply and boundary.get("reply_id") == self._awaiting_reply and boundary.get("ready"):
                self._awaiting_reply = ""; self._count += 1
                if self.settings.max_turns and self._count >= self.settings.max_turns:
                    self._pause("Turn limit reached")
            if boundary.get("error") and self._state not in {"paused", "stopped", "suspended"}:
                self._pause(str(boundary["error"]))

    def command(self, owner: str, kind: str, data: dict, revision: int) -> dict:
        with self._lock:
            if kind not in {"pause", "stop"} and revision != self._revision:
                raise ValueError("Continuous settings changed. Refresh and try again.")
            if self._owner and owner != self._owner:
                if self._state != "stopped": raise ValueError("Another phone owns Continuous Mode")
                self._queue.clear(); self._revision += 1
            self._owner = owner; self._heartbeat = self._clock()
            if kind == "settings":
                patch = data.get("settings", {})
                settings = self.settings.updated(patch)
                self._save(settings)  # API worker, never the Qt thread
                self.settings = settings
                if preserves_current_reply(patch):
                    self._invalidate_future_text("guidance_changed")
                else:
                    self._invalidate()
                    if settings.mode == "off": self._state = "stopped"
                    elif self._state not in {"paused", "stopped", "suspended"}: self._state = "waiting"
            elif kind == "force_continue":
                boundary = self._boundary
                if self.settings.mode == "off": raise ValueError("Choose Simple or AI Guided")
                if self.settings.max_turns and self._count >= self.settings.max_turns:
                    raise ValueError("Turn limit reached. Start a new run or increase the limit.")
                if boundary.get("error") not in (None, "", "Current reply was cancelled or replaced") or not boundary.get("forceable") or not boundary.get("assistant_id") or not str(boundary.get("content") or "").strip():
                    raise ValueError("Wait for the desktop to finish stopping, then try Force continuation again.")
                self._single = False
                self._expired_reply_boundary = None
                self._manual_reply = self._manual_previous = ""
                self._invalidate()
                self._force_boundary = (boundary.get("session"), boundary.get("revision"), boundary.get("assistant_id"))
                self._awaiting_reply = ""
                self._state = "waiting"; self._reason = ""; self._deadline = self._clock()
            elif kind in {"start", "resume", "send_next"}:
                if self.settings.mode == "off" and kind != "send_next": raise ValueError("Choose Simple or AI Guided")
                if self.settings.mode == "off" and not self._queue:
                    raise ValueError("Queue a reply before using Send Next with mode Off")
                if kind == "start": self._count = 0; self._failures = 0
                self._single = kind == "send_next" and self._state in {"stopped", "paused"}
                if kind == "resume" and data.get("preserve_user_speech") is True \
                        and self._state == "paused" and self._prepared and self.settings.speak_user_messages:
                    self._state = "ready"; self._reason = ""
                else:
                    self._invalidate(); self._state = "waiting"; self._reason = ""
                    boundary = self._boundary
                    current = (boundary.get("session"), boundary.get("revision"), boundary.get("assistant_id"))
                    if (kind == "resume" and self._expired_reply_boundary == current
                            and boundary.get("forceable") and not boundary.get("manual_input_pending")
                            and str(boundary.get("content") or "").strip()):
                        self._force_boundary = current
                    if kind in {"start", "resume"}:
                        self._expired_reply_boundary = None
                if kind == "send_next": self._deadline = self._clock()
            elif kind in {"pause", "stop", "disconnect"}:
                if kind == "disconnect": self._suspend("Connection lost. Reconnect to continue.")
                elif kind == "pause" and data.get("preserve_user_speech") is True \
                        and self._state == "ready" and self._prepared and self.settings.speak_user_messages:
                    self._state = "paused"; self._reason = ""
                else: self._pause("")
                if kind == "stop": self._state = "stopped"
                if kind == "stop": self._expired_reply_boundary = None
            elif kind in {"add", "edit", "delete", "reorder", "clear", "skip_next"}:
                if kind in {"add", "edit"}:
                    text = data.get("text")
                    if type(text) is not str or not 1 <= len(text.strip()) <= 8000: raise ValueError("Enter 1–8000 characters")
                    if kind == "add":
                        if len(self._queue) >= 100: raise ValueError("Queue is full (100 replies)")
                        self._queue.append({"id": uuid.uuid4().hex, "text": text.strip()})
                    else:
                        item = next((row for row in self._queue if row["id"] == data.get("id")), None)
                        if item is None: raise ValueError("Queue item no longer exists")
                        item["text"] = text.strip()
                elif kind == "delete": self._queue = [row for row in self._queue if row["id"] != data.get("id")]
                elif kind == "clear": self._queue.clear()
                elif kind == "reorder":
                    ids = data.get("ids")
                    if (not isinstance(ids, list) or any(type(i) is not str for i in ids)
                            or len(ids) != len(self._queue) or set(ids) != {r["id"] for r in self._queue}):
                        raise ValueError("Queue order changed")
                    rows = {r["id"]: r for r in self._queue}; self._queue = [rows[i] for i in ids]
                elif self._queue: self._queue.pop(0)
                else:
                    self._pause("Next automatic reply skipped. Resume when ready.")
                self._invalidate()
                if self._state not in {"paused", "stopped", "suspended"}: self._state = "waiting"
            else: raise ValueError("Unknown Continuous command")
            self._revision += 1
            return self.snapshot(owner)

    def reply_interrupted(self, owner: str, request_id: str) -> None:
        with self._lock:
            if owner != self._owner: return
            if self._manual_reply and request_id != self._manual_reply: return
            if self._awaiting_reply and self._awaiting_reply != request_id: return
            self._awaiting_reply = ""
            if self._state not in {"paused", "stopped", "suspended"}:
                self._pause("Reply playback was interrupted. Resume after the next reply finishes.")

    def manual_input_accepted(self, owner: str, request_id: str) -> None:
        """Manual text or an image replaces speculation; wait for its own reply."""
        with self._lock:
            if not self._owner and self._state == "suspended":
                self._owner = owner
                self._heartbeat = self._clock()
            if owner != self._owner: return
            self._invalidate()
            self._expired_reply_boundary = None
            self._manual_reply = request_id
            self._manual_previous = self._boundary.get("assistant_id", "")
            self._awaiting_reply = ""
            self._revision += 1
            if self._state not in {"paused", "stopped", "suspended"}: self._state = "waiting"

    def tick(self):
        with self._lock:
            if self._state in {"paused", "stopped", "suspended"}: return
            if self.settings.max_turns and self._count >= self.settings.max_turns:
                self._pause("Turn limit reached. Start a new run or increase the limit."); return
            if self._clock() - self._heartbeat >= 10:
                self._suspend("Phone connection lost. Reconnect to continue."); return
            boundary = self._boundary
            if self._prefetched and self._clock() - self._prefetched["started_at"] >= 300:
                self._prefetched["token"].cancel("continuous_prefetch_expired")
                self._prefetched = None
            forced = self._force_boundary is not None and self._force_boundary == (
                boundary.get("session"), boundary.get("revision"), boundary.get("assistant_id"))
            # Speculate only on final assistant text. Never expose a speech or
            # submission token until the authoritative phone drain arrives.
            if boundary.get("manual_input_pending") or (self._manual_reply and boundary.get("assistant_id") == self._manual_previous):
                self._state = "waiting"; return
            if (boundary.get("generation_ready") and boundary.get("assistant_id") != self._consumed
                    and str(boundary.get("content") or "").strip() and not self._queue
                    and self.settings.mode == "ai_guided" and not self._single
                    and not self._prepared and not self._job and self._prefetched is None):
                self._start_generation()
            if (boundary.get("generation_ready") and boundary.get("assistant_id") != self._consumed
                    and str(boundary.get("content") or "").strip() and not self._prepared
                    and not self._job and self._prefetched is None and not self._single):
                if self._queue:
                    row = self._queue[0]
                    self._prefetched = self._candidate(row["text"], "queued_manual", row["id"])
                elif self.settings.mode == "simple":
                    self._prefetched = self._candidate(self.settings.default_reply, "continuous_simple")
            if self._manual_reply or self._awaiting_reply or not (boundary.get("ready") or (forced and boundary.get("forceable"))) or not boundary.get("assistant_id"):
                self._state = "waiting"; return
            if not str(boundary.get("content") or "").strip():
                self._pause("Assistant response was empty"); return
            if boundary["assistant_id"] == self._consumed and not forced: return
            if self._prepared: return
            if self._deadline is None: self._deadline = self._clock() + self.settings.delay_seconds
            if self._clock() < self._deadline: self._state = "delay"; return
            if self._prefetched is not None:
                self.mark_next_current(self._owner, self._prefetched["id"])
                return
            if self._job:
                self._state = "generating"; return
            if self._queue and not forced:
                self._prepare(self._queue[0]["text"], "queued_manual", self._queue[0]["id"])
            elif self.settings.mode == "ai_guided":
                self._start_generation()
            else: self._prepare(self.settings.default_reply, "continuous_simple")

    def _start_generation(self):
        self._state = "generating"
        self._job = {"id": uuid.uuid4().hex, "token": CancellationToken(),
                     "settings": self.settings, "boundary": dict(self._boundary), "started": False}

    def _candidate(self, text, source, queue_id=None, *, boundary=None):
        draft = text if isinstance(text, AutoReplyDraft) else None
        return {"id": uuid.uuid4().hex, "kind": "user", "text": draft.automated_user_response if draft else text,
                "speech_text": draft.speech_text(self.settings.speak_guidance_and_example) if draft else text,
                "speech_segments": draft.speech_segments(self.settings.speak_guidance_and_example) if draft else (),
                "draft": draft, "source": source, "queue_id": queue_id, "token": CancellationToken(),
                "boundary": dict(boundary or self._boundary), "started_at": self._clock()}

    def next_candidate(self, owner: str) -> dict | None:
        with self._lock:
            return self._prefetched if owner == self._owner and self._state not in {"paused", "stopped", "suspended"} else None

    def invalidate_next(self, reason: str) -> None:
        with self._lock:
            if self._prefetched is not None:
                self._prefetched["token"].cancel(reason)
                self._prefetched = None

    def mark_next_current(self, owner: str, identity: str) -> bool:
        with self._lock:
            candidate = self.next_candidate(owner)
            boundary = self._boundary
            if (candidate is None or candidate["id"] != identity or candidate["token"].cancelled
                    or boundary.get("manual_input_pending") or self._manual_reply or self._awaiting_reply):
                return False
            previous = candidate["boundary"]
            if any(previous.get(key) != boundary.get(key) for key in
                   ("session", "revision", "assistant_id", "persona", "provider_id", "model_id", "voice_fingerprint")):
                return False
            forced = self._force_boundary == (boundary.get("session"), boundary.get("revision"), boundary.get("assistant_id"))
            if not (boundary.get("ready") or (forced and boundary.get("forceable"))):
                return False
            if self._deadline is None: self._deadline = self._clock() + self.settings.delay_seconds
            if self._clock() < self._deadline: return False
            self._prefetched = None
            self._prepare(candidate["draft"] or candidate["text"], candidate["source"],
                          candidate["queue_id"], identity=identity, token=candidate["token"])
            return self._prepared is not None

    def _prepare(self, text, source, queue_id=None, *, identity=None, token=None):
        draft = text if isinstance(text, AutoReplyDraft) else None
        text = draft.automated_user_response if draft else text
        if not text.strip(): self._pause("No valid next reply"); return
        self._prepared = {"id": identity or uuid.uuid4().hex, "text": text.strip(), "source": source,
                           "queue_id": queue_id, "token": token or CancellationToken(), "boundary": dict(self._boundary),
                          "speech_text": draft.speech_text(self.settings.speak_guidance_and_example) if draft else text.strip()}
        if draft:
            self._prepared["auto_reply_guidance"] = draft.guidance_metadata()
            self._prepared["auto_reply_guidance"].update(
                strength=self.settings.guidance_strength,
                user_guidance=selected_guidance(self.settings) if self.settings.guidance_strength else "")
            self._prepared["speech_segments"] = draft.speech_segments(self.settings.speak_guidance_and_example)
        self._state = "ready"

    def generation_job(self):
        with self._lock:
            if not self._job or self._job["started"]: return None
            self._job["started"] = True
            return self._job

    def generation_finished(self, job, text=None):
        with self._lock:
            if self._job is not job or job["token"].cancelled: return
            self._job = None
            if isinstance(text, AutoReplyDraft):
                self._failures = 0; self._prefetched = self._candidate(text, "continuous_ai", boundary=job["boundary"])
            else:
                self._failures += 1
                if self._failures >= 3 or not self.settings.fallback:
                    self._pause("Auto-Reply generation failed. Check its provider.")
                else: self._prefetched = self._candidate(self.settings.default_reply, "continuous_simple", boundary=job["boundary"])
            self.tick()

    def speech_preparation(self, owner, identity, *, begin=False):
        with self._lock:
            if owner != self._owner or self._state != "ready" or not self._prepared or self._prepared["id"] != identity:
                raise ValueError("Prepared user reply is no longer current.")
            if begin:
                # Speech release is the atomic boundary: subsequent edits must
                # never retract text/audio already handed to the phone.
                self._prepared["speech_started"] = True
            return self._prepared, self.settings

    def claim(self, owner, identity):
        with self._lock:
            self.heartbeat(owner)
            if owner != self._owner or not self._prepared or self._prepared["id"] != identity: return None
            if self._state not in {"ready", "submitting"}: return None
            self._state = "submitting"
            self._claimed[identity] = self._prepared
            return self._prepared

    def settle(self, identity, result):
        with self._lock:
            if result.get("status") == "pending": return
            prepared = self._claimed.pop(identity, None) or self._prepared
            if not prepared or prepared["id"] != identity:
                return
            if result.get("status") == "accepted":
                self._awaiting_reply = str(result.get("phone_request_id") or "")
                if prepared and prepared["id"] == identity:
                    self._consumed = prepared["boundary"].get("assistant_id", "")
                    self._queue = [r for r in self._queue if r["id"] != prepared["queue_id"]]
                    self._revision += 1
            if self._prepared is prepared and prepared and prepared["id"] == identity:
                self._invalidate()
                if self._state not in {"paused", "stopped", "suspended"}:
                    if result.get("status") == "accepted":
                        self._state = "paused" if self._single else "waiting"
                    else: self._pause("Conversation changed before submission. Resume explicitly.")

    def snapshot(self, owner):
        with self._lock:
            if self._owner and owner != self._owner:
                return {"version": 1, "owned": False, "state": self._state, "revision": self._revision}
            return {"version": 1, "owned": True, "revision": self._revision, "state": self._state,
                    "reason": self._reason, "settings": asdict(self.settings), "queue": [dict(r) for r in self._queue],
                    "guidance_presets": guidance_presets(), "force_continuation_supported": True,
                    "structured_auto_reply_supported": True,
                    "guidance_strength_supported": True,
                    "completed_turns": self._count,
                    "remaining_seconds": max(0, (self._deadline or 0) - self._clock()),
                    "prepared_id": self._prepared["id"] if self._prepared else None,
                    "pending_reply": self._prepared["text"] if self._prepared else "",
                    "user_speech": ({"text": self._prepared["text"], "voice_id": self.settings.user_voice,
                                     "operation_id": self._prepared["id"], "transport": "backend_hq"}
                                    if self._prepared and self.settings.speak_user_messages
                                    and self.settings.mode != "off" and (not self._single or self._force_boundary is not None) else None)}

    def close(self):
        with self._lock:
            self._invalidate(); self._state = "stopped"

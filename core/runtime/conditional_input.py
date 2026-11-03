"""Opt-in low-priority input admission; never owns speech or provider execution."""
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
import hashlib
import json
import threading

from core.runtime.contracts import CancellationToken
from core.runtime.auto_reply_guidance import normalize_auto_reply_guidance


class ConditionalInputAdmission:
    def __init__(self, conversation, session, normal_chat):
        self.conversation, self.session, self.normal_chat = conversation, session, normal_chat
        self._lock = threading.Lock()
        self._records: OrderedDict[str, tuple[bytes, dict]] = OrderedDict()
        self._active: str | None = None

    def submit(self, text: str, *, operation_id: str, expected_revision: int,
               expected_session: int, metadata: Mapping[str, object],
               cancellation: CancellationToken) -> dict[str, object]:
        if (type(text) is not str or not 1 <= len(text.strip()) <= 8000
                or type(operation_id) is not str or not 1 <= len(operation_id) <= 128
                or type(expected_revision) is not int or expected_revision < 0
                or type(expected_session) is not int or expected_session < 0
                or not isinstance(cancellation, CancellationToken)):
            raise ValueError("Invalid conditional input")
        # Only phone delivery, provenance and validated turn-local direction cross this port.
        allowed = {k: metadata[k] for k in ("remote_capture_id", "phone_reply_control",
                   "phone_shared_queue", "source") if k in metadata}
        if "auto_reply_guidance" in metadata:
            direction = normalize_auto_reply_guidance(metadata["auto_reply_guidance"])
            if direction is None:
                raise ValueError("Invalid Auto-Reply guidance")
            allowed["auto_reply_guidance"] = direction
        if "continuous_stage_id" in metadata:
            stage_id = metadata["continuous_stage_id"]
            binding = metadata.get("continuous_stage_binding")
            fields = ("session_generation", "conversation_revision", "source_turn_id",
                      "owner_id", "persona_id", "provider_id", "model_id",
                      "settings_revision", "voice_fingerprint")
            if (not isinstance(stage_id, str) or len(stage_id) != 32
                    or any(ch not in "0123456789abcdef" for ch in stage_id)
                    or not isinstance(binding, Mapping) or set(binding) != set(fields)
                    or binding["session_generation"] != expected_session
                    or binding["conversation_revision"] != expected_revision
                    or binding["owner_id"] != metadata.get("continuous_owner_id")
                    or type(binding["settings_revision"]) is not int
                    or any(type(binding[key]) is not str for key in (
                        "source_turn_id", "owner_id", "persona_id", "provider_id",
                        "model_id", "voice_fingerprint"))
                    or not allowed.get("phone_shared_queue")
                    or allowed.get("source") not in (
                        "continuous_simple", "continuous_ai", "queued_manual")):
                raise ValueError("Invalid Continuous stage permit")
            allowed["continuous_stage_id"] = stage_id
            allowed["continuous_stage_binding"] = dict(binding)
        fingerprint = hashlib.sha256(json.dumps([text, expected_revision, expected_session, allowed],
                                                sort_keys=True).encode()).digest()
        with self._lock:
            previous = self._records.get(operation_id)
            if previous:
                if previous[0] != fingerprint:
                    raise ValueError("Operation ID already used")
                return dict(previous[1])
            if self._active is not None:
                return {"status": "pending" if self._active == operation_id else "busy"}
            self._active = operation_id
        result = {"status": "unavailable"}
        accepted = None
        lease = None
        try:
            before = self.conversation.snapshot()
            epoch = self.session.conditional_input_epoch()
            if cancellation.cancelled:
                result = {"status": "cancelled"}
            elif before.session_generation.value != expected_session or before.revision != expected_revision:
                result = {"status": "stale"}
            elif epoch is None:
                result = {"status": "busy"}
            else:
                turn = {"content": text.strip(), "role": "user", "origin": "input", **allowed}
                accepted = self.normal_chat.begin(turn, expected_history_revision=expected_revision,
                                                  source_lease=self.conversation.session_lease())
                lease = self.normal_chat.accepted_input_lease(accepted)
                # Cancellation cannot return before this short publication finishes.
                with cancellation.admission_scope() as current:
                    if not current:
                        result = {"status": "cancelled"}
                    elif lease is not None and self.session.stage_conditional_input(
                            accepted, epoch=epoch, before=before, lease=lease):
                        result = {"status": "accepted", "phone_request_id": allowed.get("remote_capture_id", "")}
                    else:
                        result = {"status": "stale"}
        except RuntimeError:
            result = {"status": "stale"}
        finally:
            if accepted is not None and result["status"] != "accepted":
                self.normal_chat.discard_continuous_stage(
                    str(accepted.get("normal_chat_transaction_id") or ""))
                if lease is not None:
                    self.conversation.discard_accepted_turn(lease)
                self.session.discard_unpublished_input(accepted)
            with self._lock:
                self._records[operation_id] = (fingerprint, dict(result))
                self._active = None
                while len(self._records) > 512:
                    self._records.popitem(last=False)
        if result["status"] == "accepted":
            try:
                self.session.request_chat_view_rebuild()
            except Exception:
                # Publication already committed. A view notification failure must
                # not turn it into a rejection and invite a duplicate submission.
                pass
        return result

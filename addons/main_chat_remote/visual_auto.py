"""Conversation-scoped automatic Visual Reply decisions for Main Chat Remote.

This module reserves a trigger only; image work remains in the existing Visual Reply
service. Reservations are written before dispatch so reconnect/restart cannot replay
a potentially paid request.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import threading
from typing import Any, Mapping, Sequence

MODES = frozenset({"off", "user", "assistant", "story"})
TERMINAL = frozenset({"ready", "failed", "skipped_busy", "abandoned"})


class VisualAutoPolicy:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            self._conversations = loaded if isinstance(loaded, dict) else {}
        except (OSError, ValueError):
            self._conversations = {}
        for state in self._conversations.values():
            if isinstance(state, dict):
                for receipt in state.get("receipts", []):
                    if isinstance(receipt, dict) and receipt.get("status") in {"reserved", "dispatched"}:
                        receipt["status"] = "abandoned" if receipt["status"] == "reserved" else "failed"

    @staticmethod
    def _new_state() -> dict[str, Any]:
        return {"mode": "off", "images_per_beat": 1, "revision": 0,
                "last_seen": "", "receipts": []}

    def _state(self, conversation_id: str) -> dict[str, Any]:
        state = self._conversations.get(conversation_id)
        if not isinstance(state, dict):
            state = self._new_state()
            self._conversations[conversation_id] = state
        return state

    def _commit(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        try:
            temporary.write_text(json.dumps(self._conversations, ensure_ascii=False), encoding="utf-8")
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _conversation(scope: Mapping[str, object]) -> str:
        conversation = scope.get("conversation_id")
        if not isinstance(conversation, str) or not conversation:
            raise ValueError("An active conversation is required.")
        return conversation

    def snapshot(self, conversation_id: str) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._state(conversation_id))

    def has_seen(self, conversation_id: str, turn_id: str) -> bool:
        with self._lock:
            return self._state(conversation_id)["last_seen"] == turn_id

    def seed_latest(self, scope: Mapping[str, object], turns: Sequence[Mapping[str, object]]) -> None:
        """Treat already visible history as old when the policy first opens."""
        if not turns:
            return
        assistant = next((turn for turn in reversed(turns) if turn.get("role") == "assistant"), None)
        turn_id = str((assistant or {}).get("turn_id") or (assistant or {}).get("id") or "")[:120]
        if not turn_id:
            return
        with self._lock:
            state = self._state(self._conversation(scope))
            if not state["last_seen"]:
                state["last_seen"] = turn_id
                self._commit()

    def phone_status(self, scope: Mapping[str, object], plan: Mapping[str, object] | None) -> dict[str, Any]:
        state = self.snapshot(self._conversation(scope))
        visit = str((plan or {}).get("beat_visit_id") or "")
        plan_id = str((plan or {}).get("plan_id") or "")
        count = sum(1 for receipt in state["receipts"]
                    if receipt.get("beat_visit_id") == visit and visit
                    and receipt.get("plan_id") == plan_id and plan_id
                    and receipt.get("status") in {"dispatched", "ready", "failed"})
        active = next((receipt.get("status") for receipt in reversed(state["receipts"])
                       if receipt.get("status") in {"reserved", "dispatched"}), None)
        return {"mode": state["mode"], "images_per_beat": state["images_per_beat"],
                "revision": state["revision"], "beat_count": count, "active": active or "",
                "story_dormant": state["mode"] == "story" and (plan or {}).get("status") != "active"}

    def update(self, scope: Mapping[str, object], payload: Mapping[str, object]) -> dict[str, Any]:
        conversation = self._conversation(scope)
        mode = payload.get("mode")
        quota = payload.get("images_per_beat")
        if mode not in MODES or type(quota) is not int or not 1 <= quota <= 5:
            raise ValueError("Choose a Visual Reply mode and 1–5 images per beat.")
        with self._lock:
            state = self._state(conversation)
            if type(payload.get("revision")) is not int or payload["revision"] != state["revision"]:
                raise ValueError("Visual Reply settings changed. Refresh and try again.")
            if (mode, quota) != (state["mode"], state["images_per_beat"]):
                state.update(mode=mode, images_per_beat=quota, revision=state["revision"] + 1)
                self._commit()
            return copy.deepcopy(state)

    def observe(self, scope: Mapping[str, object], turns: Sequence[Mapping[str, object]],
                plan: Mapping[str, object] | None, *, external_busy: bool = False) -> dict[str, str] | None:
        """Reserve at most one new, completed assistant turn from a live history event."""
        conversation = self._conversation(scope)
        if not turns or turns[-1].get("role") != "assistant":
            return None
        assistant = turns[-1]
        turn_id = str(assistant.get("turn_id") or assistant.get("id") or "")[:120]
        content = str(assistant.get("content") or "").strip()
        if not turn_id or not content or assistant.get("hidden_proactive"):
            return None
        with self._lock:
            state = self._state(conversation)
            if state["last_seen"] == turn_id:
                return None
            state["last_seen"] = turn_id
            mode = state["mode"]
            previous = next((turn for turn in reversed(turns[:-1])
                             if turn.get("role") in {"user", "assistant"}
                             and not turn.get("hidden_proactive")), None)
            user = previous if previous and previous.get("role") == "user" else None
            eligible = mode == "assistant"
            if mode == "user":
                eligible = bool(user and str(user.get("content") or "").strip()
                                and not user.get("attachment_image_path"))
                if eligible and assistant.get("normal_chat_transaction_id") and user.get("normal_chat_transaction_id"):
                    eligible = assistant["normal_chat_transaction_id"] == user["normal_chat_transaction_id"]
            if mode == "story":
                eligible = (plan or {}).get("status") == "active"
            visit = str((plan or {}).get("beat_visit_id") or "") if mode == "story" else ""
            plan_id = str((plan or {}).get("plan_id") or "") if mode == "story" else ""
            if mode == "story" and not (visit and plan_id):
                eligible = False
            if eligible and mode == "story":
                used = sum(1 for receipt in state["receipts"]
                           if receipt.get("beat_visit_id") == visit and receipt.get("plan_id") == plan_id
                           and receipt.get("status") in {"dispatched", "ready", "failed"})
                eligible = used < state["images_per_beat"]
            if not eligible:
                self._commit()
                return None
            key = f"{scope.get('session_generation')}:{mode}:{turn_id}:{plan_id}:{visit}"
            if any(receipt.get("key") == key for receipt in state["receipts"]):
                self._commit()
                return None
            busy = external_busy or any(receipt.get("status") in {"reserved", "dispatched"}
                       for receipt in state["receipts"])
            receipt = {"key": key, "turn_id": turn_id, "mode": mode,
                       "policy_revision": state["revision"],
                       "plan_id": plan_id,
                       "beat_visit_id": visit, "status": "skipped_busy" if busy else "reserved",
                       "request_id": ""}
            if mode == "user" and user:
                receipt["user_turn_id"] = str(user.get("turn_id") or user.get("id") or "")[:120]
            state["receipts"].append(receipt)
            state["receipts"] = state["receipts"][-500:]
            self._commit()
            return None if busy else {**receipt, "content": content}

    def can_dispatch(self, scope: Mapping[str, object], key: str) -> bool:
        with self._lock:
            state = self._state(self._conversation(scope))
            return any(receipt.get("key") == key and receipt.get("status") == "reserved"
                       and receipt.get("policy_revision") == state["revision"]
                       for receipt in state["receipts"])

    def finish(self, scope: Mapping[str, object], key: str, *, accepted: bool,
               request_id: str = "", busy: bool = False) -> None:
        with self._lock:
            state = self._state(self._conversation(scope))
            for receipt in state["receipts"]:
                if receipt.get("key") == key and receipt.get("status") == "reserved":
                    receipt["status"] = "dispatched" if accepted else "skipped_busy" if busy else "failed"
                    receipt["request_id"] = request_id[:120]
                    self._commit()
                    return

    def abandon(self, scope: Mapping[str, object], key: str) -> None:
        with self._lock:
            state = self._state(self._conversation(scope))
            for receipt in state["receipts"]:
                if receipt.get("key") == key and receipt.get("status") == "reserved":
                    receipt["status"] = "abandoned"
                    self._commit()
                    return

    def refresh(self, scope: Mapping[str, object], requests: Sequence[Mapping[str, object]]) -> None:
        statuses = {str(item.get("request_id") or ""): str(item.get("status") or "")
                    for item in requests}
        with self._lock:
            state = self._state(self._conversation(scope))
            changed = False
            for receipt in state["receipts"]:
                if receipt.get("status") == "dispatched":
                    status = statuses.get(receipt.get("request_id", ""), "")
                    if status in {"ready", "failed", "error", "rejected"}:
                        receipt["status"] = "ready" if status == "ready" else "failed"
                        changed = True
            if changed:
                self._commit()

    def export(self, conversation_id: str) -> dict[str, Any]:
        return self.snapshot(conversation_id)

    @staticmethod
    def validate_snapshot(value: object) -> dict[str, Any]:
        if not isinstance(value, Mapping) or value.get("mode") not in MODES:
            raise ValueError("Saved Visual Reply settings are invalid.")
        quota = value.get("images_per_beat")
        if type(quota) is not int or not 1 <= quota <= 5:
            raise ValueError("Saved Visual Reply quota is invalid.")
        receipts = value.get("receipts")
        if (not isinstance(receipts, list) or len(receipts) > 500
                or any(not isinstance(row, Mapping)
                       or not isinstance(row.get("key"), str)
                       or row.get("status") not in TERMINAL | {"reserved", "dispatched"}
                       for row in receipts)):
            raise ValueError("Saved Visual Reply receipts are invalid.")
        return {"mode": value["mode"], "images_per_beat": quota,
                "revision": max(0, int(value.get("revision") or 0)),
                "last_seen": str(value.get("last_seen") or "")[:120],
                "receipts": [dict(row) for row in receipts]}

    def restore(self, conversation_id: str, value: object) -> None:
        validated = self.validate_snapshot(value)
        for receipt in validated["receipts"]:
            if receipt["status"] == "reserved":
                receipt["status"] = "abandoned"
            elif receipt["status"] == "dispatched":
                receipt["status"] = "failed"
        with self._lock:
            self._conversations[conversation_id] = validated
            self._commit()

    def forget(self, conversation_id: str) -> None:
        with self._lock:
            if self._conversations.pop(conversation_id, None) is not None:
                self._commit()

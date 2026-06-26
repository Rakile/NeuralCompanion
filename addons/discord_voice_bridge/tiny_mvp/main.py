from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

try:
    import winsound
except Exception:  # pragma: no cover - non-Windows fallback
    winsound = None


APP_DIR = Path(__file__).resolve().parent
SETTINGS_PATH = APP_DIR / "settings.example.json"


@dataclass
class Participant:
    id: str
    name: str
    kind: str
    connected: bool = True
    current: bool = False
    next: bool = False
    queued_audio: int = 0
    playback_state: str = "idle"
    last_event: str = ""
    updated_at: str = ""


class TinyRoomState:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.playback_condition = threading.Condition(self.lock)
        self.participants: dict[str, Participant] = {}
        self.route_flow: list[dict[str, Any]] = []
        self.current_id = ""
        self.next_id = ""
        self.playback_owner_id = ""
        self.capture_owner_id = ""
        self.moderator_state = self._default_moderator_state()
        self.playback_epoch = 0
        self.last_playback_stop_reason = ""
        self.started_at = datetime.now().isoformat(timespec="seconds")
        self.load_settings()

    def _default_moderator_state(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "pending_route": {},
            "route_next_target_bot_id": "",
            "pending_human_route": {},
            "route_next_speaker_user_id": "",
            "route_next_speaker_name": "",
            "current_human_route": {},
            "current_speaker_user_id": "",
            "current_speaker_name": "",
            "current_bot_id": "",
            "current_bot_name": "",
            "floor_target_bot_id": "",
            "floor_speaker_user_id": "",
            "floor_speaker_name": "",
            "muted_bot_ids": [],
            "only_bot_ids": [],
            "muted_speaker_user_ids": [],
            "allow_current_interruption": False,
            "enforcer_bot_id": "",
            "enforcer_bot_name": "",
            "enforce_discord_mute": False,
            "last_command": "",
            "last_error": "",
            "updated_at_ms": self.now_ms(),
        }

    def load_settings(self) -> None:
        settings = {
            "participants": [
                {"id": "echo", "name": "Echo", "type": "bot", "connected": True},
                {"id": "nova", "name": "Nova", "type": "bot", "connected": True},
                {"id": "rakila", "name": "Rakila", "type": "human", "connected": True},
            ]
        }
        if SETTINGS_PATH.exists():
            settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        with self.lock:
            for item in settings.get("participants", []):
                self.upsert_participant(
                    str(item.get("id") or "").strip(),
                    str(item.get("name") or item.get("id") or "").strip(),
                    str(item.get("type") or item.get("kind") or "bot").strip().lower(),
                    bool(item.get("connected", True)),
                    log=False,
                )
            self.add_flow("system", "", "room", "TinyMVP room initialized.")
            self.ensure_capture_owner("startup")

    def reset_room(self, reason: str = "reset") -> None:
        if winsound is not None:
            winsound.PlaySound(None, winsound.SND_PURGE)
        for participant in self.participants.values():
            participant.current = False
            participant.next = False
            participant.queued_audio = 0
            participant.playback_state = "idle"
            participant.last_event = f"room reset: {reason}"
            participant.updated_at = self.now()
        self.route_flow.clear()
        self.current_id = ""
        self.next_id = ""
        self.playback_owner_id = ""
        self.capture_owner_id = ""
        self.moderator_state = self._default_moderator_state()
        self.playback_epoch += 1
        self.last_playback_stop_reason = f"room reset: {reason}"
        self.ensure_capture_owner("room reset")
        self.add_flow("reset", "", "", f"Room reset | {reason}")
        with self.playback_condition:
            self.playback_condition.notify_all()

    def upsert_participant(self, participant_id: str, name: str, kind: str, connected: bool = True, *, log: bool = True) -> None:
        if not participant_id:
            raise ValueError("participant id is required")
        kind = kind if kind in {"bot", "human"} else "bot"
        now = self.now()
        existing = self.participants.get(participant_id)
        if existing:
            existing.name = name or participant_id
            existing.kind = kind
            existing.connected = connected
            existing.updated_at = now
            existing.last_event = "updated"
        else:
            self.participants[participant_id] = Participant(
                id=participant_id,
                name=name or participant_id,
                kind=kind,
                connected=connected,
                last_event="connected" if connected else "disconnected",
                updated_at=now,
            )
        if log:
            self.add_flow("participant", participant_id, "", f"{name or participant_id} {kind} {'connected' if connected else 'disconnected'}.")
        self.ensure_capture_owner("participant updated")

    def remove_participant(self, participant_id: str) -> None:
        participant = self.participants.pop(participant_id, None)
        if not participant:
            return
        if self.current_id == participant_id:
            self.current_id = ""
        if self.next_id == participant_id:
            self.next_id = ""
        if self.capture_owner_id == participant_id:
            self.capture_owner_id = ""
        self._clear_moderator_participant_refs(participant_id)
        self.add_flow("participant", participant_id, "", f"{participant.name} removed.")
        self.ensure_capture_owner("participant removed")

    def set_connected(self, participant_id: str, connected: bool) -> None:
        participant = self.require_participant(participant_id)
        participant.connected = connected
        participant.last_event = "connected" if connected else "disconnected"
        participant.updated_at = self.now()
        self.add_flow("participant", participant_id, "", f"{participant.name} {participant.last_event}.")
        if not connected and self.capture_owner_id == participant_id:
            self.capture_owner_id = ""
        self.ensure_capture_owner("participant connected" if connected else "participant disconnected")

    def set_current(self, participant_id: str, reason: str = "external command") -> None:
        participant = self.require_participant(participant_id)
        self.current_id = participant_id
        if self.next_id == participant_id:
            self.next_id = ""
            self._clear_pending_routes()
        self._sync_flags()
        self._set_moderator_current(participant, reason)
        participant.last_event = f"current: {reason}"
        participant.updated_at = self.now()
        self.add_flow("current", participant_id, "", f"Current -> {participant.name} | {reason}")

    def set_next(self, participant_id: str, reason: str = "external command") -> None:
        participant = self.require_participant(participant_id)
        self.next_id = participant_id
        self._sync_flags()
        self._set_moderator_next(participant, reason)
        participant.last_event = f"next: {reason}"
        participant.updated_at = self.now()
        self.add_flow("route", self.current_id, participant_id, f"Next -> {participant.name} | {reason}")

    def clear_current(self, reason: str = "external command") -> None:
        old = self.current_id
        self.current_id = ""
        self._sync_flags()
        self.moderator_state.update(
            {
                "current_human_route": {},
                "current_speaker_user_id": "",
                "current_speaker_name": "",
                "current_bot_id": "",
                "current_bot_name": "",
                "last_command": "clear_current",
                "last_error": "",
                "updated_at_ms": self.now_ms(),
            }
        )
        self.add_flow("current", old, "", f"Current cleared | {reason}")

    def clear_next(self, reason: str = "external command") -> None:
        old = self.next_id
        self.next_id = ""
        self._sync_flags()
        self._clear_pending_routes(last_command="clear_pending")
        self.add_flow("route", old, "", f"Next cleared | {reason}")

    def clear_pending(self, reason: str = "external command") -> None:
        self.clear_next(reason)

    def set_allow_current_interruption(self, allowed: bool, reason: str = "external command") -> None:
        self.moderator_state.update(
            {
                "allow_current_interruption": bool(allowed),
                "last_command": "allow_current_interruption" if allowed else "protect_current_speaker",
                "last_error": "",
                "updated_at_ms": self.now_ms(),
            }
        )
        self.add_flow("moderator", "", "", f"Allow interrupt current -> {'on' if allowed else 'off'} | {reason}")

    def set_allow_only(self, participant_id: str, reason: str = "external command") -> None:
        participant = self.require_participant(participant_id)
        self._clear_pending_routes()
        if participant.kind == "human":
            self.moderator_state.update(
                {
                    "floor_speaker_user_id": participant.id,
                    "floor_speaker_name": participant.name,
                    "floor_target_bot_id": "",
                    "only_bot_ids": [],
                    "last_command": f"accept_human:{participant.name}",
                    "last_error": "",
                    "updated_at_ms": self.now_ms(),
                }
            )
        else:
            self.moderator_state.update(
                {
                    "floor_target_bot_id": participant.id,
                    "floor_speaker_user_id": "",
                    "floor_speaker_name": "",
                    "only_bot_ids": [participant.id],
                    "last_command": f"allow_bot:{participant.id}",
                    "last_error": "",
                    "updated_at_ms": self.now_ms(),
                }
        )
        self.add_flow("moderator", "", participant.id, f"Allow only {participant.name} | {reason}")

    def route_allowed_by_speaker_lock(self, target_id: str) -> tuple[bool, str]:
        target_id = str(target_id or "").strip()
        if not target_id:
            return True, ""
        floor_bot = str(self.moderator_state.get("floor_target_bot_id") or "").strip()
        floor_human = str(self.moderator_state.get("floor_speaker_user_id") or "").strip()
        only_bots = {str(item or "").strip() for item in self.moderator_state.get("only_bot_ids", []) if str(item or "").strip()}
        if floor_bot and target_id != floor_bot:
            return False, f"speaker_lock:{floor_bot}"
        if floor_human and target_id != floor_human:
            return False, f"speaker_lock:{floor_human}"
        if only_bots and target_id not in only_bots:
            return False, f"speaker_lock:{','.join(sorted(only_bots))}"
        return True, ""

    def participant_is_muted(self, participant_id: str) -> bool:
        participant_id = str(participant_id or "").strip()
        if not participant_id:
            return False
        participant = self.participants.get(participant_id)
        if participant and participant.kind == "human":
            muted = {str(item or "").strip() for item in self.moderator_state.get("muted_speaker_user_ids", []) if str(item or "").strip()}
            return participant_id in muted
        muted = {str(item or "").strip() for item in self.moderator_state.get("muted_bot_ids", []) if str(item or "").strip()}
        return participant_id in muted

    def apply_route_decision(self, source_id: str, target_id: str, reason: str, answer: bool) -> bool:
        source_id = str(source_id or "").strip()
        target_id = str(target_id or "").strip()
        reason = str(reason or "route decision").strip()
        if self.participant_is_muted(source_id):
            self.route_decision(source_id, target_id, f"muted_speaker:{reason}", False)
            return False
        if not answer or not target_id:
            self.route_decision(source_id, target_id, reason, False)
            return False
        try:
            target = self.require_participant(target_id)
        except KeyError:
            self.route_decision(source_id, target_id, f"unknown_target:{reason}", False)
            return False
        if not target.connected:
            self.route_decision(source_id, target_id, f"target_disconnected:{reason}", False)
            return False
        allowed, lock_reason = self.route_allowed_by_speaker_lock(target_id)
        if not allowed:
            self.route_decision(source_id, target_id, f"{lock_reason}:{reason}", False)
            return False
        if target.kind == "human" and not self.current_id and not self.playback_owner_id:
            self.set_current(target_id, reason)
        else:
            self.set_next(target_id, reason)
        self.route_decision(source_id, target_id, reason, True)
        return True

    def clear_speaker_locks(self, reason: str = "external command") -> None:
        self.moderator_state.update(
            {
                "floor_target_bot_id": "",
                "floor_speaker_user_id": "",
                "floor_speaker_name": "",
                "only_bot_ids": [],
                "last_command": "clear_speaker_locks",
                "last_error": "",
                "updated_at_ms": self.now_ms(),
            }
        )
        self.add_flow("moderator", "", "", f"Speaker locks cleared | {reason}")

    def clear_all_moderator(self, reason: str = "external command") -> None:
        enforcer_bot_id = self.moderator_state.get("enforcer_bot_id", "")
        enforcer_bot_name = self.moderator_state.get("enforcer_bot_name", "")
        enforce_discord_mute = bool(self.moderator_state.get("enforce_discord_mute", False))
        self.moderator_state = self._default_moderator_state()
        self.moderator_state.update(
            {
                "enforcer_bot_id": enforcer_bot_id,
                "enforcer_bot_name": enforcer_bot_name,
                "enforce_discord_mute": enforce_discord_mute,
                "last_command": "clear",
            }
        )
        self.current_id = ""
        self.next_id = ""
        self._sync_flags()
        self.add_flow("moderator", "", "", f"Moderator state cleared | {reason}")

    def handle_moderator_command(self, payload: dict[str, Any]) -> dict[str, Any]:
        action = str(payload.get("action") or "").strip().lower()
        reason = str(payload.get("reason") or "human moderator").strip()
        target_id = str(payload.get("target_bot_id") or payload.get("bot_id") or payload.get("target_id") or "").strip()
        speaker_id = str(payload.get("speaker_user_id") or payload.get("user_id") or "").strip()
        speaker_name = str(payload.get("speaker_name") or speaker_id).strip()
        if action == "moderator_route_next":
            self.set_next(target_id, reason)
        elif action == "moderator_give_floor":
            self.set_allow_only(target_id, reason)
        elif action == "moderator_route_next_human":
            if speaker_id and speaker_id not in self.participants:
                self.upsert_participant(speaker_id, speaker_name or speaker_id, "human", True)
            self.set_next(speaker_id, reason)
        elif action == "moderator_give_human_floor":
            if speaker_id and speaker_id not in self.participants:
                self.upsert_participant(speaker_id, speaker_name or speaker_id, "human", True)
            self.set_allow_only(speaker_id, reason)
        elif action == "moderator_mute":
            muted = set(self.moderator_state.get("muted_bot_ids", []))
            if target_id:
                muted.add(target_id)
            self.moderator_state.update({"muted_bot_ids": sorted(muted), "last_command": f"mute:{target_id}", "updated_at_ms": self.now_ms()})
            self.add_flow("moderator", "", target_id, f"Muted {target_id} | {reason}")
        elif action == "moderator_unmute":
            muted = [item for item in self.moderator_state.get("muted_bot_ids", []) if item != target_id]
            self.moderator_state.update({"muted_bot_ids": muted, "only_bot_ids": [], "last_command": f"unmute:{target_id}", "updated_at_ms": self.now_ms()})
            self.add_flow("moderator", "", target_id, f"Unmuted {target_id} | {reason}")
        elif action == "moderator_mute_human":
            muted = set(self.moderator_state.get("muted_speaker_user_ids", []))
            if speaker_id:
                muted.add(speaker_id)
            self.moderator_state.update({"muted_speaker_user_ids": sorted(muted), "last_command": f"mute_human:{speaker_name}", "updated_at_ms": self.now_ms()})
            self.add_flow("moderator", "", speaker_id, f"Muted human {speaker_name or speaker_id} | {reason}")
        elif action == "moderator_unmute_human":
            muted = [item for item in self.moderator_state.get("muted_speaker_user_ids", []) if item != speaker_id]
            self.moderator_state.update({"muted_speaker_user_ids": muted, "last_command": f"unmute_human:{speaker_name}", "updated_at_ms": self.now_ms()})
            self.add_flow("moderator", "", speaker_id, f"Unmuted human {speaker_name or speaker_id} | {reason}")
        elif action == "moderator_mute_all_except":
            self.set_allow_only(target_id, reason)
        elif action == "moderator_clear_pending":
            self.clear_pending(reason)
        elif action == "moderator_clear_floor":
            self.clear_speaker_locks(reason)
        elif action == "moderator_clear":
            self.clear_all_moderator(reason)
            self.stop_playback("moderator_clear")
        elif action == "moderator_set_current_interruption":
            self.set_allow_current_interruption(bool(payload.get("allow_current_interruption")), reason)
        elif action == "moderator_set_enforcer":
            target = self.participants.get(target_id)
            self.moderator_state.update(
                {
                    "enforcer_bot_id": target_id,
                    "enforcer_bot_name": target.name if target else target_id,
                    "last_command": f"hard_moderator:{target_id}",
                    "last_error": "",
                    "updated_at_ms": self.now_ms(),
                }
            )
        elif action == "moderator_clear_enforcer":
            self.moderator_state.update(
                {
                    "enforcer_bot_id": "",
                    "enforcer_bot_name": "",
                    "enforce_discord_mute": False,
                    "last_command": "clear_hard_moderator",
                    "last_error": "",
                    "updated_at_ms": self.now_ms(),
                }
            )
        elif action == "moderator_set_mute_enforcement":
            self.moderator_state.update(
                {
                    "enforce_discord_mute": bool(payload.get("enabled")),
                    "last_command": "tiny_mvp_mute_enforcement_state",
                    "last_error": "",
                    "updated_at_ms": self.now_ms(),
                }
            )
        else:
            raise ValueError(f"unknown moderator action: {action}")
        return self.snapshot()

    def route_decision(self, source_id: str, target_id: str, reason: str, answer: bool) -> None:
        source = self.participants.get(source_id)
        target = self.participants.get(target_id)
        source_name = source.name if source else source_id or "Room"
        target_name = target.name if target else target_id or "no route"
        verdict = "answer=yes" if answer else "answer=no"
        self.add_flow("room_router", source_id, target_id if answer else "", f"{source_name} -> {target_name} | {verdict} | {reason}")

    def speech_event(self, speaker_id: str, text: str, reason: str = "speech") -> None:
        participant = self.require_participant(speaker_id)
        if self.participant_is_muted(speaker_id):
            participant.last_event = f"muted speech ignored: {text[:120]}"
            participant.updated_at = self.now()
            self.add_flow("speech", speaker_id, "", f"{participant.name} muted; speech ignored.")
            return
        can_take_current = (
            not self.current_id
            or self.current_id == speaker_id
            or participant.kind == "bot"
            or bool(self.moderator_state.get("allow_current_interruption"))
        )
        if can_take_current:
            self.set_current(speaker_id, reason)
        participant.last_event = f"said: {text[:120]}"
        participant.updated_at = self.now()
        self.add_flow("speech", speaker_id, "", f"{participant.name}: {text}")

    def dead_air(self, reason: str = "dead air") -> str:
        preferred_id = str(self.moderator_state.get("enforcer_bot_id") or "").strip()
        preferred = self.participants.get(preferred_id) if preferred_id else None
        if preferred and preferred.kind == "bot" and preferred.connected and preferred.id != self.current_id:
            target = preferred
        else:
            target = next(
                (
                    item
                    for item in self.participants.values()
                    if item.kind == "bot" and item.connected and item.id != self.current_id
                ),
                None,
            )
        if not target:
            self.add_flow("dead_air", "", "", "No connected bot available for dead-air recovery.")
            return ""
        self.set_next(target.id, reason)
        self.add_flow("dead_air", "", target.id, f"Dead-air recovery chose {target.name}.")
        return target.id

    def maybe_recover_dead_air(self, reason: str = "dead air") -> str:
        if self.current_id:
            self.clear_current(f"dead-air recovery: {reason}")
        return self.dead_air(reason)

    def play_wav(self, participant_id: str, wav_path: str, *, playback_epoch: int | None = None) -> bool:
        path = Path(wav_path)
        if not path.exists():
            raise FileNotFoundError(wav_path)
        with self.playback_condition:
            if playback_epoch is not None and playback_epoch != self.playback_epoch:
                self.add_flow("playback", participant_id, "", f"Playback rejected as stale for {participant_id}: {path.name}")
                return False
            participant = self.require_participant(participant_id)
            if self.playback_owner_id and self.playback_owner_id != participant_id:
                participant.queued_audio += 1
                participant.playback_state = "queued"
                participant.last_event = f"queued wav: {path.name}"
                participant.updated_at = self.now()
                self.add_flow("playback", participant_id, self.playback_owner_id, f"Playback queued for {participant.name}: {path.name}")
                while self.playback_owner_id and self.playback_owner_id != participant_id:
                    self.playback_condition.wait(timeout=0.25)
                participant.queued_audio = max(0, participant.queued_audio - 1)
            participant.playback_state = "playing"
            participant.last_event = f"playing wav: {path.name}"
            participant.updated_at = self.now()
            self.playback_owner_id = participant_id
            if self.current_id != participant_id:
                self.set_current(participant_id, "audio playback")
            self.add_flow("playback", participant_id, "", f"Playback started as {participant.name}: {path}")
        if winsound is not None:
            winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
        return True

    def stop_playback(self, reason: str = "external command") -> None:
        if (
            ("speech probe" in reason or "user speech" in reason)
            and not bool(self.moderator_state.get("allow_current_interruption"))
            and (self.playback_owner_id or self.current_id)
        ):
            self.add_flow("playback", "", "", f"Playback interruption blocked | {reason}")
            return
        old_owner = self.playback_owner_id
        if winsound is not None:
            winsound.PlaySound(None, winsound.SND_PURGE)
        for participant in self.participants.values():
            if participant.playback_state in {"playing", "queued"} or participant.queued_audio:
                participant.queued_audio = 0
                participant.playback_state = "stopped"
                participant.last_event = f"playback stopped: {reason}"
                participant.updated_at = self.now()
        self.playback_epoch += 1
        self.last_playback_stop_reason = reason
        self.playback_owner_id = ""
        if "speech probe" in reason or "user speech" in reason:
            old_next = self.next_id
            self.next_id = ""
            if old_next:
                self.add_flow("route", old_next, "", f"Next cleared | {reason}")
        should_clear_current = (
            self.current_id == old_owner
            and (
                reason in {"clear_queue", "stop_speech"}
                or reason == "moderator_clear"
                or reason.endswith("turn finished")
                or "speech probe" in reason
                or "user speech" in reason
            )
        )
        if should_clear_current:
            self.current_id = ""
            self._sync_flags()
            self.add_flow("current", old_owner, "", f"Current cleared | {reason}")
        if reason.endswith("turn finished"):
            next_participant = self.participants.get(self.next_id)
            if next_participant and next_participant.kind == "human":
                self.set_current(next_participant.id, f"human next after {reason}")
        self.add_flow("playback", "", "", f"Playback stopped | {reason}")
        with self.playback_condition:
            self.playback_condition.notify_all()

    def ensure_capture_owner(self, reason: str = "capture owner check") -> str:
        owner = self.participants.get(self.capture_owner_id)
        if owner and owner.kind == "bot" and owner.connected:
            return owner.id
        previous = self.capture_owner_id
        self.capture_owner_id = ""
        for participant in self.participants.values():
            if participant.kind == "bot" and participant.connected:
                self.capture_owner_id = participant.id
                break
        if self.capture_owner_id != previous:
            owner_name = self.participants[self.capture_owner_id].name if self.capture_owner_id else "none"
            self.add_flow("capture", self.capture_owner_id, "", f"Capture owner -> {owner_name} | {reason}")
        return self.capture_owner_id

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            self._sync_flags()
            self.ensure_capture_owner("snapshot")
            return {
                "ok": True,
                "service": "TinyMVP fake voice channel",
                "started_at": self.started_at,
                "updated_at": self.now(),
                "current_id": self.current_id,
                "next_id": self.next_id,
                "playback_owner_id": self.playback_owner_id,
                "capture_owner_id": self.capture_owner_id,
                "playback_epoch": self.playback_epoch,
                "last_playback_stop_reason": self.last_playback_stop_reason,
                "moderator_state": dict(self.moderator_state),
                "participants": [asdict(item) for item in self.participants.values()],
                "route_flow": list(self.route_flow[-100:]),
            }

    def require_participant(self, participant_id: str) -> Participant:
        participant = self.participants.get(participant_id)
        if not participant:
            raise KeyError(f"unknown participant: {participant_id}")
        return participant

    def add_flow(self, event_type: str, source_id: str, target_id: str, message: str) -> None:
        if self.route_flow:
            previous = self.route_flow[-1]
            if (
                previous.get("type") == event_type
                and previous.get("source_id") == source_id
                and previous.get("target_id") == target_id
                and previous.get("message") == message
            ):
                return
        self.route_flow.append(
            {
                "index": len(self.route_flow) + 1,
                "time": datetime.now().strftime("%H:%M:%S"),
                "type": event_type,
                "source_id": source_id,
                "target_id": target_id,
                "message": message,
            }
        )

    def _sync_flags(self) -> None:
        for participant in self.participants.values():
            participant.current = participant.id == self.current_id
            participant.next = participant.id == self.next_id

    def _set_moderator_next(self, participant: Participant, reason: str) -> None:
        if participant.kind == "human":
            self.moderator_state.update(
                {
                    "pending_human_route": {
                        "speaker_user_id": participant.id,
                        "speaker_name": participant.name,
                        "reason": reason,
                        "created_at_ms": self.now_ms(),
                    },
                    "route_next_speaker_user_id": participant.id,
                    "route_next_speaker_name": participant.name,
                    "pending_route": {},
                    "route_next_target_bot_id": "",
                    "last_command": f"route_next_human:{participant.name}",
                    "last_error": "",
                    "updated_at_ms": self.now_ms(),
                }
            )
            return
        self.moderator_state.update(
            {
                "pending_route": {
                    "target_bot_id": participant.id,
                    "created_at_ms": self.now_ms(),
                    "source": "human_moderator" if "moderator" in reason.lower() else "tinymvp",
                    "manual": "moderator" in reason.lower(),
                    "user_command": "moderator" in reason.lower(),
                    "reason": reason,
                },
                "route_next_target_bot_id": participant.id,
                "pending_human_route": {},
                "route_next_speaker_user_id": "",
                "route_next_speaker_name": "",
                "last_command": f"route_next:{participant.id}",
                "last_error": "",
                "updated_at_ms": self.now_ms(),
            }
        )

    def _set_moderator_current(self, participant: Participant, reason: str) -> None:
        if participant.kind == "human":
            self.moderator_state.update(
                {
                    "current_human_route": {
                        "speaker_user_id": participant.id,
                        "speaker_name": participant.name,
                        "reason": reason,
                        "created_at_ms": self.now_ms(),
                    },
                    "current_speaker_user_id": participant.id,
                    "current_speaker_name": participant.name,
                    "current_bot_id": "",
                    "current_bot_name": "",
                    "last_command": f"current_human:{participant.name}",
                    "last_error": "",
                    "updated_at_ms": self.now_ms(),
                }
            )
            return
        self.moderator_state.update(
            {
                "current_bot_id": participant.id,
                "current_bot_name": participant.name,
                "current_human_route": {},
                "current_speaker_user_id": "",
                "current_speaker_name": "",
                "last_command": f"current_bot:{participant.id}",
                "last_error": "",
                "updated_at_ms": self.now_ms(),
            }
        )

    def _clear_pending_routes(self, *, last_command: str = "clear_pending") -> None:
        self.moderator_state.update(
            {
                "pending_route": {},
                "route_next_target_bot_id": "",
                "pending_human_route": {},
                "route_next_speaker_user_id": "",
                "route_next_speaker_name": "",
                "last_command": last_command,
                "last_error": "",
                "updated_at_ms": self.now_ms(),
            }
        )

    def _clear_moderator_participant_refs(self, participant_id: str) -> None:
        if self.moderator_state.get("current_bot_id") == participant_id:
            self.moderator_state.update({"current_bot_id": "", "current_bot_name": ""})
        if self.moderator_state.get("route_next_target_bot_id") == participant_id:
            self.moderator_state.update({"pending_route": {}, "route_next_target_bot_id": ""})
        if self.moderator_state.get("floor_target_bot_id") == participant_id:
            self.moderator_state.update({"floor_target_bot_id": ""})
        if self.moderator_state.get("current_speaker_user_id") == participant_id:
            self.moderator_state.update({"current_human_route": {}, "current_speaker_user_id": "", "current_speaker_name": ""})
        if self.moderator_state.get("route_next_speaker_user_id") == participant_id:
            self.moderator_state.update({"pending_human_route": {}, "route_next_speaker_user_id": "", "route_next_speaker_name": ""})
        if self.moderator_state.get("floor_speaker_user_id") == participant_id:
            self.moderator_state.update({"floor_speaker_user_id": "", "floor_speaker_name": ""})
        self.moderator_state["muted_bot_ids"] = [item for item in self.moderator_state.get("muted_bot_ids", []) if item != participant_id]
        self.moderator_state["only_bot_ids"] = [item for item in self.moderator_state.get("only_bot_ids", []) if item != participant_id]
        self.moderator_state["muted_speaker_user_ids"] = [
            item for item in self.moderator_state.get("muted_speaker_user_ids", []) if item != participant_id
        ]
        self.moderator_state["updated_at_ms"] = self.now_ms()

    @staticmethod
    def now() -> str:
        return datetime.now().isoformat(timespec="seconds")

    @staticmethod
    def now_ms() -> int:
        return int(time.time() * 1000)


ROOM = TinyRoomState()


class TinyRoomHandler(BaseHTTPRequestHandler):
    server_version = "TinyMVP/0.2"

    def do_GET(self) -> None:
        if self.path in {"/", "/health", "/state"}:
            self.send_json(ROOM.snapshot())
            return
        if self.path.startswith("/events"):
            self.send_json({"ok": True, "route_flow": ROOM.snapshot()["route_flow"]})
            return
        self.send_json({"ok": False, "error": "not found"}, status=404)

    def do_POST(self) -> None:
        try:
            payload = self.read_json()
            path = self.path.rstrip("/")
            with ROOM.lock:
                if path == "/participants/upsert":
                    ROOM.upsert_participant(
                        str(payload.get("id") or payload.get("participant_id") or "").strip(),
                        str(payload.get("name") or payload.get("id") or "").strip(),
                        str(payload.get("type") or payload.get("kind") or "bot").strip().lower(),
                        bool(payload.get("connected", True)),
                    )
                elif path == "/participants/remove":
                    ROOM.remove_participant(str(payload.get("id") or payload.get("participant_id") or "").strip())
                elif path == "/participants/connect":
                    ROOM.set_connected(str(payload.get("id") or payload.get("participant_id") or "").strip(), True)
                elif path == "/participants/disconnect":
                    ROOM.set_connected(str(payload.get("id") or payload.get("participant_id") or "").strip(), False)
                elif path == "/speech":
                    ROOM.speech_event(
                        str(payload.get("speaker_id") or payload.get("id") or "").strip(),
                        str(payload.get("text") or "").strip(),
                        str(payload.get("reason") or "speech").strip(),
                    )
                elif path in {"/route", "/next"}:
                    ROOM.apply_route_decision(
                        str(payload.get("source_id") or payload.get("speaker_id") or "").strip(),
                        str(payload.get("target_id") or payload.get("id") or "").strip(),
                        str(payload.get("reason") or "external route").strip(),
                        True,
                    )
                elif path == "/decision":
                    ROOM.apply_route_decision(
                        str(payload.get("source_id") or payload.get("speaker_id") or "").strip(),
                        str(payload.get("target_id") or "").strip(),
                        str(payload.get("reason") or "route decision").strip(),
                        bool(payload.get("answer")),
                    )
                elif path == "/moderator":
                    state = ROOM.handle_moderator_command(payload)
                    self.send_json({"ok": True, "state": state})
                    return
                elif path in {"/call", "/current"}:
                    ROOM.set_current(
                        str(payload.get("target_id") or payload.get("id") or "").strip(),
                        str(payload.get("reason") or "external call").strip(),
                    )
                elif path == "/clear/current":
                    ROOM.clear_current(str(payload.get("reason") or "external command").strip())
                elif path == "/clear/next":
                    ROOM.clear_next(str(payload.get("reason") or "external command").strip())
                elif path == "/dead-air":
                    target = ROOM.dead_air(str(payload.get("reason") or "dead air").strip())
                    self.send_json({"ok": True, "target_id": target, "state": ROOM.snapshot()})
                    return
                elif path == "/play":
                    accepted = ROOM.play_wav(
                        str(payload.get("speaker_id") or payload.get("id") or "").strip(),
                        str(payload.get("wav_path") or payload.get("path") or "").strip(),
                        playback_epoch=int(payload["playback_epoch"]) if "playback_epoch" in payload else None,
                    )
                    if not accepted:
                        self.send_json({"ok": False, "reason": "stale_playback_epoch", "state": ROOM.snapshot()})
                        return
                elif path == "/stop":
                    ROOM.stop_playback(str(payload.get("reason") or "external command").strip())
                elif path == "/reset":
                    ROOM.reset_room(str(payload.get("reason") or "external command").strip())
                else:
                    self.send_json({"ok": False, "error": "not found"}, status=404)
                    return
            self.send_json({"ok": True, "state": ROOM.snapshot()})
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, status=400)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError):
            return

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[TinyMVP] {self.address_string()} - {format % args}")


def run_server(host: str, port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), TinyRoomHandler)
    print(f"TinyMVP fake voice channel running at http://{host}:{port}")
    print("Endpoints: GET /state, POST /participants/upsert, /speech, /route, /call, /moderator, /dead-air, /play, /stop, /clear/current, /clear/next")
    server.serve_forever()
    return server


def run_monitor(url: str, interval_ms: int = 500) -> int:
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title("TinyMVP Room Monitor")
    root.geometry("1240x760")
    root.columnconfigure(0, weight=1)
    root.rowconfigure(2, weight=1)
    root.rowconfigure(3, weight=1)

    status_var = tk.StringVar(value=f"URL: {url}")
    status = ttk.Label(root, textvariable=status_var, anchor="w")
    status.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))

    toolbar = ttk.Frame(root)
    toolbar.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 6))
    toolbar.columnconfigure(5, weight=1)

    last_state: dict[str, Any] = {}
    local_log_floor_index = 0

    def post(path: str, payload: dict[str, Any] | None = None) -> None:
        endpoint = url.rsplit("/", 1)[0] + path
        data = json.dumps(payload or {}).encode("utf-8")
        request = urllib.request.Request(endpoint, data=data, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=1.5) as response:
            response.read()

    def refresh_now() -> None:
        poll(schedule=False)

    def clear_log_view() -> None:
        nonlocal local_log_floor_index
        flow.delete("1.0", "end")
        events = last_state.get("route_flow") if isinstance(last_state, dict) else []
        if isinstance(events, list) and events:
            indexes = [int(item.get("index") or 0) for item in events if isinstance(item, dict)]
            if indexes:
                local_log_floor_index = max(indexes)

    def safe_command(label: str, path: str, payload: dict[str, Any] | None = None) -> None:
        try:
            post(path, payload)
            refresh_now()
        except Exception as exc:
            status_var.set(f"{label} failed: {exc}")

    ttk.Button(toolbar, text="Refresh", command=refresh_now).grid(row=0, column=0, padx=(0, 6))
    ttk.Button(toolbar, text="Clear Log View", command=clear_log_view).grid(row=0, column=1, padx=(0, 6))
    ttk.Button(toolbar, text="Stop Playback", command=lambda: safe_command("Stop playback", "/stop", {"reason": "monitor stop playback"})).grid(row=0, column=2, padx=(0, 6))
    ttk.Button(toolbar, text="Clear Current", command=lambda: safe_command("Clear current", "/clear/current", {"reason": "monitor clear current"})).grid(row=0, column=3, padx=(0, 6))
    ttk.Button(toolbar, text="Clear Next", command=lambda: safe_command("Clear next", "/clear/next", {"reason": "monitor clear next"})).grid(row=0, column=4, padx=(0, 6))

    columns = ("id", "name", "type", "connected", "current", "next", "capture", "playback_owner", "queued", "playback", "event")
    table_frame = ttk.Frame(root)
    table_frame.grid(row=2, column=0, sticky="nsew", padx=8, pady=(0, 8))
    table_frame.columnconfigure(0, weight=1)
    table_frame.rowconfigure(0, weight=1)
    table = ttk.Treeview(table_frame, columns=columns, show="headings", height=12)
    headings = {
        "id": "ID",
        "name": "Name",
        "type": "Type",
        "connected": "Connected",
        "current": "Current",
        "next": "Next",
        "capture": "Capture",
        "playback_owner": "Playback Owner",
        "queued": "Queued",
        "playback": "Playback",
        "event": "Last Event",
    }
    widths = {
        "id": 140,
        "name": 120,
        "type": 70,
        "connected": 80,
        "current": 70,
        "next": 70,
        "capture": 70,
        "playback_owner": 110,
        "queued": 65,
        "playback": 100,
        "event": 430,
    }
    for col in columns:
        table.heading(col, text=headings[col])
        table.column(col, width=widths[col], stretch=col == "event")
    table.tag_configure("current", background="#245238", foreground="#ffffff")
    table.tag_configure("next", background="#27496d", foreground="#ffffff")
    table.tag_configure("capture", background="#4a3d1d", foreground="#ffffff")
    table.tag_configure("playback_owner", background="#4a2f1d", foreground="#ffffff")
    table.tag_configure("bot", background="#1b2633", foreground="#ffffff")
    table.tag_configure("human", background="#202a22", foreground="#ffffff")
    table.tag_configure("disconnected", background="#2e2e2e", foreground="#dddddd")
    table.grid(row=0, column=0, sticky="nsew")
    table_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=table.yview)
    table.configure(yscrollcommand=table_scroll.set)
    table_scroll.grid(row=0, column=1, sticky="ns")

    flow_frame = ttk.LabelFrame(root, text="Route / Event Flow")
    flow_frame.grid(row=3, column=0, sticky="nsew", padx=8, pady=(0, 8))
    flow_frame.columnconfigure(0, weight=1)
    flow_frame.rowconfigure(0, weight=1)
    flow = tk.Text(flow_frame, wrap="none", height=14)
    flow.grid(row=0, column=0, sticky="nsew")
    flow_scroll_y = ttk.Scrollbar(flow_frame, orient="vertical", command=flow.yview)
    flow_scroll_x = ttk.Scrollbar(flow_frame, orient="horizontal", command=flow.xview)
    flow.configure(yscrollcommand=flow_scroll_y.set, xscrollcommand=flow_scroll_x.set)
    flow_scroll_y.grid(row=0, column=1, sticky="ns")
    flow_scroll_x.grid(row=1, column=0, sticky="ew")

    def participant_name(participants: list[dict[str, Any]], participant_id: str) -> str:
        for participant in participants:
            if str(participant.get("id") or "") == participant_id:
                return str(participant.get("name") or participant_id)
        return participant_id or "-"

    def format_status(state: dict[str, Any]) -> str:
        participants = list(state.get("participants") or [])
        current_id = str(state.get("current_id") or "")
        next_id = str(state.get("next_id") or "")
        playback_owner_id = str(state.get("playback_owner_id") or "")
        capture_owner_id = str(state.get("capture_owner_id") or "")
        return (
            f"URL: {url} | started: {state.get('started_at') or '-'} | updated: {state.get('updated_at') or '-'} | "
            f"current: {participant_name(participants, current_id)} | next: {participant_name(participants, next_id)} | "
            f"playback: {participant_name(participants, playback_owner_id)} | capture: {participant_name(participants, capture_owner_id)} | "
            f"epoch: {state.get('playback_epoch', 0)} | last stop: {state.get('last_playback_stop_reason') or '-'}"
        )

    def flow_line(item: dict[str, Any], participants: list[dict[str, Any]]) -> str:
        source_id = str(item.get("source_id") or "")
        target_id = str(item.get("target_id") or "")
        source = participant_name(participants, source_id) if source_id else "Room"
        target = participant_name(participants, target_id) if target_id else "no route"
        return f"{item.get('time') or '--:--:--'}  {source} -> {target} [{item.get('type') or '-'}] | {item.get('message') or ''}"

    def poll(*, schedule: bool = True) -> None:
        nonlocal last_state
        try:
            with urllib.request.urlopen(url, timeout=1.0) as response:
                state = json.loads(response.read().decode("utf-8"))
            last_state = state if isinstance(state, dict) else {}
            status_var.set(format_status(last_state))
            current_id = str(last_state.get("current_id") or "")
            next_id = str(last_state.get("next_id") or "")
            playback_owner_id = str(last_state.get("playback_owner_id") or "")
            capture_owner_id = str(last_state.get("capture_owner_id") or "")
            table.delete(*table.get_children())
            for participant in last_state.get("participants", []):
                participant_id = str(participant.get("id") or "")
                if not participant.get("connected"):
                    tag = "disconnected"
                elif participant_id == current_id:
                    tag = "current"
                elif participant_id == next_id:
                    tag = "next"
                elif participant_id == playback_owner_id:
                    tag = "playback_owner"
                elif participant_id == capture_owner_id:
                    tag = "capture"
                else:
                    tag = participant.get("kind", "bot")
                table.insert(
                    "",
                    "end",
                    values=(
                        participant.get("id", ""),
                        participant.get("name", ""),
                        participant.get("kind", ""),
                        "yes" if participant.get("connected") else "no",
                        "yes" if participant_id == current_id else "no",
                        "yes" if participant_id == next_id else "no",
                        "yes" if participant_id == capture_owner_id else "no",
                        "yes" if participant_id == playback_owner_id else "no",
                        str(participant.get("queued_audio", 0)),
                        participant.get("playback_state", ""),
                        participant.get("last_event", ""),
                    ),
                    tags=(tag,),
                )
            participants = list(last_state.get("participants") or [])
            events = [
                item
                for item in last_state.get("route_flow", [])[-100:]
                if isinstance(item, dict) and int(item.get("index") or 0) > local_log_floor_index
            ]
            lines = [flow_line(item, participants) for item in events[-80:]]
            text = "\n".join(lines)
            if flow.get("1.0", "end-1c") != text:
                at_bottom = flow.yview()[1] >= 0.98
                flow.delete("1.0", "end")
                flow.insert("1.0", text)
                if at_bottom:
                    flow.see("end")
        except Exception as exc:
            status_var.set(f"Monitor could not read {url}: {exc}")
        if schedule:
            root.after(interval_ms, poll)

    poll()
    root.mainloop()
    return 0

def run_self_test() -> int:
    contract_room = TinyRoomState()
    with contract_room.lock:
        contract_room.participants.clear()
        contract_room.route_flow.clear()
        contract_room.current_id = ""
        contract_room.next_id = ""
        contract_room.playback_owner_id = ""
        contract_room.capture_owner_id = ""
        contract_room.upsert_participant("echo", "Echo", "bot", True, log=False)
        contract_room.upsert_participant("nova", "Nova", "bot", True, log=False)
        contract_room.upsert_participant("moderator", "Moderator", "bot", True, log=False)
        contract_room.upsert_participant("rakila", "Rakila", "human", True, log=False)
        contract_room.set_next("rakila", "self-test human next")
        human_next_state = contract_room.snapshot()
        contract_room.set_current("rakila", "self-test human current")
        human_current_state = contract_room.snapshot()
        contract_room.set_current("echo", "self-test active bot")
        contract_room.set_next("rakila", "self-test human next after bot")
        contract_room.playback_owner_id = "echo"
        contract_room.stop_playback("echo turn finished")
        human_promoted_state = contract_room.snapshot()
        contract_room.set_current("echo", "self-test active bot without next")
        contract_room.playback_owner_id = "echo"
        contract_room.stop_playback("echo turn finished")
        quiet_after_finish_state = contract_room.snapshot()
        contract_room.set_next("nova", "self-test bot next")
        bot_next_state = contract_room.snapshot()
        contract_room.set_allow_only("echo", "self-test speaker lock")
        locked_state = contract_room.snapshot()
        contract_room.set_allow_only("rakila", "self-test human speaker lock")
        human_locked_state = contract_room.snapshot()
        contract_room.handle_moderator_command(
            {
                "action": "moderator_mute_human",
                "speaker_user_id": "rakila",
                "speaker_name": "Rakila",
                "reason": "self-test human mute",
            }
        )
        human_muted_state = contract_room.snapshot()
        contract_room.handle_moderator_command(
            {
                "action": "moderator_mute",
                "target_bot_id": "nova",
                "reason": "self-test bot mute",
            }
        )
        bot_muted_state = contract_room.snapshot()
        contract_room.handle_moderator_command({"action": "moderator_clear", "reason": "self-test clear all"})
        cleared_all_state = contract_room.snapshot()
        contract_room.set_allow_current_interruption(False, "self-test protect current")
        protected_state = contract_room.snapshot()
        contract_room.clear_pending("self-test clear pending")
        cleared_pending_state = contract_room.snapshot()
        contract_room.set_current("echo", "self-test protected bot")
        contract_room.playback_owner_id = "echo"
        contract_room.set_allow_current_interruption(False, "self-test protect active bot")
        contract_room.speech_event("rakila", "I should be recorded but not steal current", "self-test protected speech")
        protected_speech_state = contract_room.snapshot()
        contract_room.set_allow_current_interruption(True, "self-test allow interrupt")
        contract_room.speech_event("rakila", "Now I can become current", "self-test allowed speech")
        allowed_speech_state = contract_room.snapshot()
        contract_room.clear_all_moderator("self-test reset before locks")
        contract_room.playback_owner_id = ""
        contract_room.current_id = ""
        contract_room.next_id = ""
        contract_room._sync_flags()
        contract_room.set_allow_only("echo", "self-test lock routes to echo")
        locked_echo_accepted = contract_room.apply_route_decision("rakila", "echo", "direct echo", True)
        locked_nova_accepted = contract_room.apply_route_decision("rakila", "nova", "direct nova", True)
        locked_route_state = contract_room.snapshot()
        contract_room.clear_all_moderator("self-test reset before human lock")
        contract_room.playback_owner_id = ""
        contract_room.current_id = ""
        contract_room.next_id = ""
        contract_room._sync_flags()
        contract_room.set_allow_only("rakila", "self-test lock speaker")
        human_locked_bot_accepted = contract_room.apply_route_decision("nova", "echo", "bot route blocked by human lock", True)
        human_locked_self_accepted = contract_room.apply_route_decision("nova", "rakila", "human route accepted", True)
        human_lock_route_state = contract_room.snapshot()
        contract_room.clear_all_moderator("self-test reset before recovery")
        contract_room.handle_moderator_command(
            {
                "action": "moderator_set_enforcer",
                "target_bot_id": "moderator",
                "reason": "self-test appointed moderator",
            }
        )
        contract_room.set_current("rakila", "self-test active human")
        contract_room.apply_route_decision("rakila", "", "no route after human speech", False)
        recovered_target = contract_room.maybe_recover_dead_air("no route after human speech")
        recovery_state = contract_room.snapshot()
        contract_room.clear_all_moderator("self-test reset before mute enforcement")
        contract_room.handle_moderator_command(
            {
                "action": "moderator_mute_human",
                "speaker_user_id": "rakila",
                "speaker_name": "Rakila",
                "reason": "self-test mute blocks speech",
            }
        )
        muted_route_accepted = contract_room.apply_route_decision("rakila", "echo", "muted route", True)
        contract_room.speech_event("rakila", "Muted user should not become current", "self-test muted speech")
        muted_enforced_state = contract_room.snapshot()
    assert human_next_state["next_id"] == "rakila"
    assert human_next_state["moderator_state"]["pending_human_route"]["speaker_user_id"] == "rakila"
    assert human_current_state["current_id"] == "rakila"
    assert human_current_state["moderator_state"]["current_human_route"]["speaker_user_id"] == "rakila"
    assert human_promoted_state["current_id"] == "rakila"
    assert human_promoted_state["next_id"] == ""
    assert quiet_after_finish_state["current_id"] == ""
    assert quiet_after_finish_state["next_id"] == ""
    assert bot_next_state["next_id"] == "nova"
    assert bot_next_state["moderator_state"]["pending_route"]["target_bot_id"] == "nova"
    assert locked_state["moderator_state"]["floor_target_bot_id"] == "echo"
    assert locked_state["moderator_state"]["only_bot_ids"] == ["echo"]
    assert human_locked_state["moderator_state"]["floor_speaker_user_id"] == "rakila"
    assert human_locked_state["moderator_state"]["floor_target_bot_id"] == ""
    assert human_locked_state["moderator_state"]["only_bot_ids"] == []
    assert human_muted_state["moderator_state"]["muted_speaker_user_ids"] == ["rakila"]
    assert bot_muted_state["moderator_state"]["muted_bot_ids"] == ["nova"]
    assert cleared_all_state["current_id"] == ""
    assert cleared_all_state["next_id"] == ""
    assert cleared_all_state["moderator_state"]["floor_speaker_user_id"] == ""
    assert cleared_all_state["moderator_state"]["floor_target_bot_id"] == ""
    assert cleared_all_state["moderator_state"]["muted_speaker_user_ids"] == []
    assert cleared_all_state["moderator_state"]["muted_bot_ids"] == []
    assert protected_state["moderator_state"]["allow_current_interruption"] is False
    assert cleared_pending_state["next_id"] == ""
    assert cleared_pending_state["moderator_state"]["pending_route"] == {}
    assert cleared_pending_state["moderator_state"]["pending_human_route"] == {}
    assert protected_speech_state["current_id"] == "echo"
    assert protected_speech_state["playback_owner_id"] == "echo"
    assert any("I should be recorded but not steal current" in item["message"] for item in protected_speech_state["route_flow"])
    assert allowed_speech_state["current_id"] == "rakila"
    assert locked_echo_accepted is True
    assert locked_nova_accepted is False
    assert locked_route_state["next_id"] == "echo"
    assert any("speaker_lock" in item["message"] for item in locked_route_state["route_flow"])
    assert human_locked_bot_accepted is False
    assert human_locked_self_accepted is True
    assert human_lock_route_state["current_id"] == "rakila"
    assert recovered_target == "moderator"
    assert recovery_state["next_id"] == recovered_target
    assert recovery_state["current_id"] == ""
    assert muted_route_accepted is False
    assert muted_enforced_state["current_id"] == ""
    assert muted_enforced_state["next_id"] == ""
    assert any("muted" in item["message"] for item in muted_enforced_state["route_flow"])

    with ROOM.lock:
        ROOM.upsert_participant("test_bot", "Test Bot", "bot", True)
        ROOM.upsert_participant("test_human", "Test Human", "human", True)
        ROOM.speech_event("test_human", "hello from a local fake room", "self-test")
        ROOM.set_next("test_bot", "self-test route")
        state = ROOM.snapshot()
    assert any(item["id"] == "test_bot" for item in state["participants"])
    assert any(item["id"] == "test_human" for item in state["participants"])
    assert state["capture_owner_id"]
    assert state["next_id"] == "test_bot"
    assert state["route_flow"]
    with ROOM.lock:
        ROOM.set_current("test_bot", "self-test playback")
        ROOM.set_next("test_human", "self-test pending")
        ROOM.playback_owner_id = "test_bot"
        ROOM.set_allow_current_interruption(False, "self-test protect room current")
        ROOM.stop_playback("nc microphone accepted 4.0s speech probe")
        protected_stop_state = ROOM.snapshot()
        ROOM.set_allow_current_interruption(True, "self-test allow room interrupt")
        ROOM.stop_playback("nc microphone accepted 4.0s speech probe")
        stopped_state = ROOM.snapshot()
    assert protected_stop_state["current_id"] == "test_bot"
    assert protected_stop_state["next_id"] == "test_human"
    assert stopped_state["current_id"] == ""
    assert stopped_state["next_id"] == ""
    print("TinyMVP self-test passed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="TinyMVP fake voice channel service.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--monitor", "--gui", action="store_true", help="Open a passive monitor window instead of running the server.")
    parser.add_argument("--monitor-url", default="http://127.0.0.1:8788/state")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return run_self_test()
    if args.monitor:
        return run_monitor(args.monitor_url)
    try:
        run_server(args.host, args.port)
    except KeyboardInterrupt:
        print("\nTinyMVP stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

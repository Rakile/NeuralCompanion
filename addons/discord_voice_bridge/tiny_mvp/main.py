from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
import urllib.request
import urllib.parse
import uuid
import wave
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
    admission_id: str = ""
    admission_index: int = 0
    membership_phase: str = 'ready'
    last_event: str = ""
    updated_at: str = ""


class TinyRoomState:
    def __init__(self) -> None:
        self.transcript_path = Path(os.environ['NC_LOCAL_ROOM_TRANSCRIPT']) if os.environ.get('NC_LOCAL_ROOM_TRANSCRIPT') else None
        self.conversation_id = os.environ.get('NC_LOCAL_ROOM_CONVERSATION_ID', '')
        self._logged_utterances = set()
        self.lock = threading.RLock()
        self.playback_condition = threading.Condition(self.lock)
        self._output_lock = threading.Lock()
        self._output_cancel = threading.Event()
        self._output_player = None
        self.audio_output_underruns = 0
        self.participants: dict[str, Participant] = {}
        self.route_flow: list[dict[str, Any]] = []
        self.current_id = ""
        self.next_id = ""
        self.playback_owner_id = ""
        self.capture_owner_id = ""
        self.moderator_state = self._default_moderator_state()
        self.playback_epoch = 0
        self.paused = False
        self.pause_after_turn = False
        self.pause_current_id = ""
        self.last_playback_stop_reason = ""
        self.last_dead_air_target_id = ""
        self.pending_recovery: dict[str, Any] = {}
        self.local_behavior: dict[str, Any] | None = None
        self.behavior_revision = ""
        self.active_human_ids: set[str] = set()
        self.last_recovery_started: float | None = None
        self.active_recovery_token = ""
        self.directive: dict[str, Any] = {}
        self.cancelled_routes_through: dict[str, int] = {}
        self._turn_contexts: dict[str, dict[str, Any]] = {}
        self._skipped_turns: dict[str, dict[str, Any]] = {}
        self._departures: dict[str, dict[str, Any]] = {}
        self.started_at = datetime.now().isoformat(timespec="seconds")
        self.load_settings()

    def configure_local_behavior(self, behavior: dict[str, Any], revision: str = "") -> None:
        """Change local automation without interrupting audio already on the floor."""
        root = str(Path(__file__).resolve().parents[3])
        if root not in sys.path:
            sys.path.insert(0, root)
        from addons.discord_voice_bridge.local_room_behavior import normalize_behavior
        normalized = normalize_behavior(behavior)
        with self.playback_condition:
            revision = str(revision or self.behavior_revision)
            if normalized == self.local_behavior and revision == self.behavior_revision:
                return
            previous_recovery = dict(self.pending_recovery)
            self.cancel_recovery(str(previous_recovery.get('token') or ''))
            cutoff = self.route_flow[-1]['index'] if self.route_flow else 0
            last_next = next((e for e in reversed(self.route_flow)
                              if e.get('type') == 'route' and e.get('target_id') == self.next_id), {})
            explicit_next = bool(last_next.get('manual_next')) or any(
                word in str(last_next.get('message') or '').lower()
                for word in ('manual', 'user command', 'external command'))
            if self.next_id and not explicit_next:
                self.clear_next('Local room behavior changed')
            for pid, participant in self.participants.items():
                if participant.kind == 'bot' and pid not in {self.current_id, self.playback_owner_id, self.next_id}:
                    self.cancelled_routes_through[pid] = cutoff
            self.local_behavior = normalized
            self.behavior_revision = revision
            self.add_flow('behavior', '', '', 'Local room behavior updated.')
            self.playback_condition.notify_all()

    def set_human_activity(self, participant_id: str, active: bool) -> None:
        """VAD/PTT begins before transcription, so withdraw unheard moderator audio now."""
        with self.playback_condition:
            if self.local_behavior is None:
                return
            if active:
                self.active_human_ids.add(participant_id)
                self.cancel_recovery(str(self.pending_recovery.get('token') or ''))
            else:
                self.active_human_ids.discard(participant_id)
                if self.pending_recovery and not self.active_human_ids:
                    self.pending_recovery['quiet_since'] = time.monotonic()
            self.playback_condition.notify_all()

    def _recovery_wait_seconds(self, token: str, participant_id: str) -> float | None:
        """Central playback guard; None means this preparation has been cancelled."""
        recovery = self.pending_recovery
        if self.playback_owner_id == participant_id and self.active_recovery_token == token:
            return 0.0
        if self.paused and self.pause_after_turn:
            return 0.25
        if self.paused or (self.local_behavior is not None and
                           (self.local_behavior['speaker_selection'] == 'manual'
                            or not self.local_behavior['moderator_help'])):
            return None
        if recovery.get('token') != token:
            # A manual Next change can withdraw the handoff while current audio finishes.
            return 0.0 if self.local_behavior is None and self.playback_owner_id == participant_id else None
        if participant_id not in self.participants or not self.participants[participant_id].connected:
            return None
        if recovery.get('playback_started'):
            return 0.0
        if self.active_human_ids:
            recovery['quiet_since'] = None
            recovery['status'] = 'waiting_for_human'
            return 0.25
        if not recovery.get('playback_delay_seconds') and self.local_behavior is None:
            return 0.0
        owner = self.playback_owner_id
        source = self.participants.get(self.current_id)
        if ((owner and (owner != participant_id or owner == recovery.get('source_id')))
                or (source and source.kind == 'bot' and source.id != participant_id)):
            recovery['quiet_since'] = None
            recovery['status'] = 'preparing_while_source_speaks'
            return 0.25
        if recovery.get('quiet_since') is None:
            recovery['quiet_since'] = time.monotonic()
        remaining = max(0.0, recovery.get('playback_delay_seconds', 0.0)
                        - (time.monotonic() - recovery['quiet_since']))
        cooldown_remaining = max(0.0, recovery.get('cooldown_ready_at', 0.0) - time.monotonic())
        recovery['status'] = ('waiting_for_cooldown' if cooldown_remaining > remaining
                              else 'waiting_for_silence' if remaining else 'ready')
        return max(remaining, cooldown_remaining)

    def _wait_recovery_ready(self, token: str, participant_id: str) -> bool:
        with self.playback_condition:
            while True:
                remaining = self._recovery_wait_seconds(token, participant_id)
                if remaining is None:
                    return False
                if remaining <= 0:
                    return True
                self.playback_condition.wait(timeout=min(0.25, remaining))

    def _finish_silent_recovery(self, token: str, participant_id: str) -> None:
        with self.playback_condition:
            if not self._wait_recovery_ready(token, participant_id):
                return
            recovery = self.pending_recovery
            if recovery.get('token') != token:
                return
            self.pending_recovery = {}
            self.last_recovery_started = time.monotonic()
            self.set_next(participant_id, str(recovery.get('reason') or 'silent recovery handoff'))
            self.last_dead_air_target_id = participant_id
            target = self.participants.get(participant_id)
            if target and target.kind == 'human' and not self.playback_owner_id:
                self.set_current(participant_id, 'silent recovery handoff')
            self.playback_condition.notify_all()

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
        with self.lock:
            self.add_flow("system", "", "room", "TinyMVP room initialized.")
            self.ensure_capture_owner("startup")

    def reset_room(self, reason: str = "reset") -> None:
        self.cancel_directive(reason)
        self._output_cancel.set()
        self._output_cancel = threading.Event()
        self.paused = False
        self.pause_after_turn = False
        self.pause_current_id = ""
        self.active_human_ids.clear()
        self.last_recovery_started = None
        self.active_recovery_token = ""
        self.pending_recovery = {}
        self.cancelled_routes_through.clear()
        self._turn_contexts.clear()
        self._skipped_turns.clear()
        self._departures.clear()
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
        self.last_dead_air_target_id = ""
        self.ensure_capture_owner("room reset")
        self.add_flow("reset", "", "", f"Room reset | {reason}")
        with self.playback_condition:
            self.playback_condition.notify_all()

    def upsert_participant(self, participant_id: str, name: str, kind: str, connected: bool = True, *, log: bool = True, admission_id: str = "", membership_phase: str = '') -> None:
        if not participant_id:
            raise ValueError("participant id is required")
        kind = kind if kind in {"bot", "human"} else "bot"
        now = self.now()
        existing = self.participants.get(participant_id)
        if existing:
            if (self.local_behavior is not None and self.pending_recovery and (not connected or
                    (admission_id and admission_id != existing.admission_id)
                    or existing.kind != kind or (name and name != existing.name))):
                self.cancel_recovery(str(self.pending_recovery.get('token') or ''))
            if not connected or (admission_id and admission_id != existing.admission_id):
                self.invalidate_turn_contexts(participant_id)
            if connected and (not existing.connected or (admission_id and admission_id != existing.admission_id)):
                existing.admission_index = len(self.route_flow) + 1
                existing.membership_phase = membership_phase or 'ready'
            if admission_id:
                existing.admission_id = admission_id
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
                admission_id=admission_id,
                admission_index=len(self.route_flow) + 1,
                membership_phase=membership_phase or 'ready',
            )
        if log:
            self.add_flow("participant", participant_id, "", f"{name or participant_id} {kind} {'connected' if connected else 'disconnected'}.")
        self.ensure_capture_owner("participant updated")

    def request_departure(self, participant_id: str, admission_id: str) -> dict[str, Any]:
        """Fence new work while retaining the exact audible reply and identity."""
        with self.lock:
            member = self.require_participant(participant_id)
            if not admission_id or member.admission_id != admission_id:
                raise ValueError('This Local room admission has changed.')
            previous = self._departures.get(participant_id, {})
            if previous.get('admission_id') == admission_id:
                return self.departure_status(participant_id, admission_id)
            current = participant_id in {self.current_id, self.playback_owner_id}
            context = self._turn_contexts.get(participant_id, {})
            pending_skip = next((item for item in self._skipped_turns.values()
                if item['source_id'] == participant_id and item['source_admission_id'] == admission_id
                and not item.get('context_delivered') and not item.get('delivery_failed')), None)
            if pending_skip: context = pending_skip
            draining = bool(context.get('turn_id') and (current or context.get('delivered') or pending_skip))
            self._departures[participant_id] = dict(id=participant_id, admission_id=admission_id,
                phase='leaving', drain_turn_id=context.get('turn_id', '') if draining else '',
                delivered_settled=not draining, was_current=draining)
            if not draining and self.current_id == participant_id:
                self.current_id = ''
                self._sync_flags()
            if self.next_id == participant_id:
                self.next_id = ''
                self._sync_flags()
                self._clear_pending_routes(last_command='participant_departing')
            self._clear_moderator_participant_refs(participant_id)
            if not draining:
                self.invalidate_turn_contexts(participant_id, source_only=True)
                self.cancelled_routes_through[participant_id] = len(self.route_flow)
            recovery = self.pending_recovery
            affected = (recovery and (participant_id in {recovery.get('target_id'), recovery.get('moderator_id'),
                        recovery.get('fallback_target')} or (not recovery.get('target_id')
                        and participant_id in recovery.get('eligible_target_ids', []))))
            if affected and not current:
                self.cancel_recovery(str(recovery.get('token') or ''))
            self.playback_condition.notify_all()
            return self.departure_status(participant_id, admission_id)

    def admit_participant(self, participant_id: str, admission_id: str) -> None:
        with self.lock:
            member = self.require_participant(participant_id)
            if not admission_id or member.admission_id != admission_id or self.participant_is_departing(participant_id):
                raise ValueError('This Local room admission has changed.')
            member.membership_phase = 'ready'

    def participant_is_departing(self, participant_id: str) -> bool:
        member = self.participants.get(participant_id)
        return bool(member and self._departures.get(participant_id, {}).get('admission_id') == member.admission_id)

    def departure_status(self, participant_id: str, admission_id: str) -> dict[str, Any]:
        with self.lock:
            departure = self._departures.get(participant_id, {})
            if not admission_id or departure.get('admission_id') != admission_id:
                return dict(id=participant_id, admission_id=admission_id, phase='unknown',
                            drain_turn_id='', delivered_settled=False, drained=False)
            return dict(departure, drained=bool(departure['delivered_settled']
                and participant_id not in {self.current_id, self.playback_owner_id}
                and not self.participants.get(participant_id, Participant('', '', '')).queued_audio))

    def remove_participant(self, participant_id: str) -> None:
        self.invalidate_turn_contexts(participant_id)
        if (self.local_behavior is not None and self.pending_recovery and participant_id in {
                self.pending_recovery.get('target_id'), self.pending_recovery.get('moderator_id'),
                self.pending_recovery.get('fallback_target'),
                *(self.pending_recovery.get('eligible_target_ids', []) if not self.pending_recovery.get('target_id') else [])}):
            self.cancel_recovery(str(self.pending_recovery.get('token') or ''))
        if self.directive.get('moderator_id') == participant_id:
            self.cancel_directive('Moderator removed from room.')
        self.active_human_ids.discard(participant_id)
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
        if self.playback_owner_id == participant_id:
            self.stop_playback("participant removed")
        self._sync_flags()
        self.add_flow("participant", participant_id, "", f"{participant.name} removed.")
        self.ensure_capture_owner("participant removed")

    def set_connected(self, participant_id: str, connected: bool) -> None:
        if not connected:
            self.invalidate_turn_contexts(participant_id)
        if self.local_behavior is not None and not connected and self.pending_recovery:
            self.cancel_recovery(str(self.pending_recovery.get('token') or ''))
        if not connected and self.directive.get('moderator_id') == participant_id:
            self.cancel_directive('Moderator disconnected.')
            if self.playback_owner_id == participant_id:
                self.stop_playback('participant disconnected', expected_owner=participant_id)
            if self.current_id == participant_id:
                self.clear_current('Moderator disconnected.')
        participant = self.require_participant(participant_id)
        participant.connected = connected
        participant.last_event = "connected" if connected else "disconnected"
        participant.updated_at = self.now()
        self.add_flow("participant", participant_id, "", f"{participant.name} {participant.last_event}.")
        if not connected and self.capture_owner_id == participant_id:
            self.capture_owner_id = ""
        self.ensure_capture_owner("participant connected" if connected else "participant disconnected")

    def set_current(self, participant_id: str, reason: str = "external command") -> None:
        if self.participant_is_departing(participant_id) and participant_id not in {self.current_id, self.playback_owner_id}:
            raise ValueError('This participant is leaving the room.')
        if self.paused and (not self.pause_after_turn or participant_id != self.pause_current_id):
            return
        participant = self.require_participant(participant_id)
        if self.participant_is_muted(participant_id) and participant_id not in {self.current_id, self.playback_owner_id}:
            raise ValueError("This participant is muted and can only listen.")
        expected_recovery_playback = (
            participant_id == self.pending_recovery.get("moderator_id") and reason == "audio playback"
        )
        completed_current_speech = participant_id == self.current_id and reason == "nc_reply_complete"
        if self.pending_recovery and not (expected_recovery_playback or completed_current_speech):
            self.pending_recovery = {}
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
        if self.participant_is_departing(participant_id):
            raise ValueError('This participant is leaving the room.')
        participant = self.require_participant(participant_id)
        if self.participant_is_muted(participant_id):
            raise ValueError("This participant is muted and can only listen.")
        self.pending_recovery = {}
        self.next_id = participant_id
        self._sync_flags()
        self._set_moderator_next(participant, reason)
        participant.last_event = f"next: {reason}"
        participant.updated_at = self.now()
        self.add_flow("queued" if self.paused else "route", self.current_id, participant_id,
                      f"Next -> {participant.name} | {reason}")

    def clear_current(self, reason: str = "external command") -> None:
        self.pending_recovery = {}
        old = self.current_id
        if self.pause_current_id == old:
            self.pause_current_id = ""
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

    def replace_next(self, participant_id: str, reason: str) -> None:
        """Manual Next invalidates displaced preparations, never current playback."""
        self.require_participant(participant_id)
        if self.participant_is_muted(participant_id):
            raise ValueError("This participant is muted and can only listen.")
        if participant_id != self.directive.get('moderator_id'):
            self.cancel_directive('Next speaker replaced.', queued_only=True)
        if participant_id == self.next_id and self.local_behavior is None:
            return
        cutoff = self.route_flow[-1]["index"] if self.route_flow else 0
        for pid, participant in self.participants.items():
            if participant.kind == "bot" and pid not in {participant_id, self.current_id, self.playback_owner_id}:
                self.cancelled_routes_through[pid] = cutoff
        self.set_next(participant_id, reason)
        self.route_flow[-1]["manual_next"] = True
        with self.playback_condition:
            self.playback_condition.notify_all()

    def route_is_cancelled(self, participant_id: str, route_index: int) -> bool:
        return bool((self.participant_is_departing(participant_id)
                     and not self._departures[participant_id].get('was_current'))
                    or (self.paused and not self.pause_after_turn) or (route_index and route_index <= self.cancelled_routes_through.get(participant_id, 0))
                    or (self.participant_is_muted(participant_id)
                        and participant_id not in {self.current_id, self.playback_owner_id}))

    def _cancel_muted_participant_routes(self, participant_id: str) -> None:
        # Let a reply already on the floor finish. Old preparations must stay
        # cancelled even after unmuting, until a fresh turn is selected.
        if participant_id not in {self.current_id, self.playback_owner_id}:
            cutoff = self.route_flow[-1]["index"] if self.route_flow else 0
            self.cancelled_routes_through[participant_id] = max(
                self.cancelled_routes_through.get(participant_id, 0), cutoff)
        if self.next_id == participant_id:
            self.clear_next("Participant muted; listener only")
        if (self.moderator_state.get("floor_target_bot_id") == participant_id
                or self.moderator_state.get("floor_speaker_user_id") == participant_id
                or participant_id in self.moderator_state.get("only_bot_ids", [])):
            self.clear_speaker_locks("Participant muted; listener only")
        with self.playback_condition:
            self.playback_condition.notify_all()

    def clear_next(self, reason: str = "external command") -> None:
        self.cancel_directive(reason, queued_only=True)
        self.pending_recovery = {}
        old = self.next_id
        self.next_id = ""
        self._sync_flags()
        self._clear_pending_routes(last_command="clear_pending")
        self.add_flow("route", old, "", f"Next cleared | {reason}")
        with self.playback_condition:
            self.playback_condition.notify_all()

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
        if self.participant_is_muted(participant_id):
            raise ValueError("This participant is muted and can only listen.")
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
        if self.participant_is_departing(target_id):
            return False, 'participant_leaving'
        if self.participants.get(target_id) and self.participants[target_id].membership_phase != 'ready':
            return False, 'participant_joining'
        if self.paused and not self.pause_after_turn:
            return False, "room_paused"
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

    def _resolve_participant_id(self, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        lowered = text.casefold()
        for participant in self.participants.values():
            if participant.id.casefold() == lowered or participant.name.casefold() == lowered:
                return participant.id
        return ""

    def _eligible_dead_air_participants(
        self, source_id: str = "", *, avoid_recent_speakers: bool = True,
    ) -> list[Participant]:
        source_id = self._resolve_participant_id(source_id) or str(source_id or "").strip()
        candidates: list[Participant] = []
        for participant in self.participants.values():
            if not participant.connected:
                continue
            if self.participant_is_muted(participant.id):
                continue
            allowed, _lock_reason = self.route_allowed_by_speaker_lock(participant.id)
            if not allowed:
                continue
            candidates.append(participant)
        if avoid_recent_speakers and len(candidates) > 1:
            non_current = [item for item in candidates if item.id != self.current_id]
            if non_current:
                candidates = non_current
        if avoid_recent_speakers and len(candidates) > 1 and source_id:
            non_source = [item for item in candidates if item.id != source_id]
            if non_source:
                candidates = non_source
        return candidates

    def _candidate_by_id(self, candidates: list[Participant], value: str) -> Participant | None:
        target_id = self._resolve_participant_id(value)
        if not target_id:
            return None
        return next((item for item in candidates if item.id == target_id), None)

    def _candidate_mentioned_in_reason(self, candidates: list[Participant], reason: str) -> Participant | None:
        text = str(reason or "")
        if not text:
            return None
        matches: list[tuple[int, Participant]] = []
        for participant in candidates:
            terms = {participant.id, participant.name}
            for term in terms:
                term = str(term or "").strip()
                if not term:
                    continue
                pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])", re.IGNORECASE)
                match = pattern.search(text)
                if match:
                    matches.append((match.start(), participant))
                    break
        if not matches:
            return None
        matches.sort(key=lambda item: item[0])
        return matches[0][1]

    def _round_robin_dead_air_candidate(self, candidates: list[Participant], source_id: str = "") -> Participant | None:
        if not candidates:
            return None
        ids = [item.id for item in self.participants.values()]
        anchors = [
            self.last_dead_air_target_id,
            self._resolve_participant_id(source_id),
            self.current_id,
        ]
        start = 0
        for anchor in anchors:
            if anchor and anchor in ids:
                start = ids.index(anchor) + 1
                break
        ordered_ids = ids[start:] + ids[:start]
        candidate_by_id = {item.id: item for item in candidates}
        for participant_id in ordered_ids:
            candidate = candidate_by_id.get(participant_id)
            if candidate:
                return candidate
        return candidates[0]

    def apply_route_decision(self, source_id: str, target_id: str, reason: str, answer: bool,
                             *, local_room_behavior: dict[str, Any] | None = None,
                             local_room_behavior_revision: str | None = None) -> bool:
        if self.local_behavior is not None and (self.local_behavior['speaker_selection'] == 'manual'
                or (local_room_behavior is not None and local_room_behavior != self.local_behavior)
                or (local_room_behavior_revision is not None and local_room_behavior_revision != self.behavior_revision)):
            return False
        if self.directive.get('status') in {'queued', 'preparing'}:
            self.route_decision(source_id, target_id, 'Moderator guidance queued', False)
            return False
        source_id = str(source_id or "").strip()
        target_id = str(target_id or "").strip()
        reason = str(reason or "route decision").strip()
        if self.participant_is_muted(source_id) and source_id not in {self.current_id, self.playback_owner_id}:
            self.route_decision(source_id, target_id, f"muted_speaker:{reason}", False)
            return False
        if not answer or not target_id:
            self.route_decision(source_id, target_id, reason, False)
            return False
        if source_id and target_id == source_id and not (self.local_behavior and self.local_behavior['allow_repeat']):
            self.route_decision(source_id, target_id, f"self_route:{reason}", False)
            return False
        try:
            target = self.require_participant(target_id)
        except KeyError:
            self.route_decision(source_id, target_id, f"unknown_target:{reason}", False)
            return False
        if not target.connected:
            self.route_decision(source_id, target_id, f"target_disconnected:{reason}", False)
            return False
        if self.participant_is_muted(target_id):
            self.route_decision(source_id, target_id, f"muted_target:{reason}", False)
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
        self.cancel_directive(reason)
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
        if action == "moderator_resume":
            for item in self._skipped_turns.values():
                if item.get('delivery_failed'): item['error_acknowledged'] = True
        if action == "moderator_pause_after_turn":
            if not self.paused:
                current = self.participants.get(self.current_id)
                self.pause_current_id = self.playback_owner_id or (self.current_id if current and current.kind == 'bot' else '')
                self.pause_after_turn = True
                self.paused = True
                self.add_flow("moderator", "", "", "Pause requested; finishing the current turn")
        elif action == "moderator_pause":
            self.pause_after_turn = False
            self.pause_current_id = ""
            self.paused = True
            cutoff = self.route_flow[-1]["index"] if self.route_flow else 0
            for participant in self.participants.values():
                if participant.kind == "bot":
                    self.cancelled_routes_through[participant.id] = cutoff
            self.stop_playback("local_room_pause")
            self.clear_current("Local room paused")
            self.add_flow("moderator", "", "", "Local room paused")
        elif action == "moderator_resume":
            was_graceful = self.pause_after_turn
            self.paused = False
            self.pause_after_turn = False
            self.pause_current_id = ""
            # Existing preparations retain their route identity. Only a handoff
            # selected during the pause needs its first dispatch on Resume.
            last_next = next((event for event in reversed(self.route_flow)
                              if event.get("type") in {"route", "queued"}
                              and event.get("target_id") == self.next_id), {})
            pending_directive = (self.directive.get('status') in {'queued', 'preparing'}
                                 and self.directive.get('moderator_id') == self.next_id)
            if self.next_id and not pending_directive and (not was_graceful or last_next.get("type") == "queued"):
                self.set_next(self.next_id, "Local room resumed")
            self.add_flow("moderator", "", "", "Local room resumed")
            with self.playback_condition:
                self.playback_condition.notify_all()
        elif action == "moderator_route_next":
            self.replace_next(target_id, reason)
        elif action == "moderator_give_floor":
            self.set_allow_only(target_id, reason)
        elif action == "moderator_route_next_human":
            if speaker_id and speaker_id not in self.participants:
                self.upsert_participant(speaker_id, speaker_name or speaker_id, "human", True)
            self.replace_next(speaker_id, reason)
        elif action == "moderator_give_human_floor":
            if speaker_id and speaker_id not in self.participants:
                self.upsert_participant(speaker_id, speaker_name or speaker_id, "human", True)
            self.set_allow_only(speaker_id, reason)
        elif action == "moderator_mute":
            if target_id and target_id == self.moderator_state.get("enforcer_bot_id"):
                raise ValueError("The room moderator cannot be muted.")
            muted = set(self.moderator_state.get("muted_bot_ids", []))
            if target_id:
                muted.add(target_id)
            self.moderator_state.update({"muted_bot_ids": sorted(muted), "last_command": f"mute:{target_id}", "updated_at_ms": self.now_ms()})
            if target_id:
                self._cancel_muted_participant_routes(target_id)
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
            if speaker_id:
                self._cancel_muted_participant_routes(speaker_id)
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
            if target_id != self.directive.get('moderator_id'):
                self.cancel_directive('Room moderator changed.')
            target = self.participants.get(target_id)
            self.moderator_state["muted_bot_ids"] = [
                item for item in self.moderator_state.get("muted_bot_ids", []) if item != target_id]
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

    def speech_event(self, speaker_id: str, text: str, reason: str = "speech", *, utterance_id: str = '') -> None:
        participant = self.require_participant(speaker_id)
        if self.participant_is_muted(speaker_id) and speaker_id not in {self.current_id, self.playback_owner_id}:
            participant.last_event = f"muted speech ignored: {text[:120]}"
            participant.updated_at = self.now()
            self.add_flow("speech", speaker_id, "", f"{participant.name} muted; speech ignored.")
            return
        if self.local_behavior is not None and participant.kind == 'human' and self.pending_recovery:
            self.cancel_recovery(str(self.pending_recovery.get('token') or ''))
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
        if not utterance_id or utterance_id not in self._logged_utterances:
            self.record_heard_chunk(speaker_id, text, utterance_id)

    def record_heard_chunk(self, speaker_id, text, utterance_id):
        with self.lock:
            context = self._turn_contexts.get(speaker_id, {})
            if text.strip() and utterance_id and context.get('turn_id') == utterance_id:
                context['delivered'] = True
                prefix = context.get('presentation_delivered_text', '')
                context['presentation_delivered_text'] = prefix + (' ' if prefix else '') + text
            if self.transcript_path is None or not self.conversation_id or not text.strip():
                return
            participant = self.participants.get(speaker_id)
            self.transcript_path.parent.mkdir(parents=True, exist_ok=True)
            with self.transcript_path.open('a', encoding='utf-8') as handle:
                handle.write(json.dumps({'conversation_id': self.conversation_id,
                    'name': participant.name if participant else speaker_id, 'speaker_id': speaker_id,
                    'text': text, 'utterance_id': utterance_id, 'time': self.now()}, ensure_ascii=False) + '\n')
            if utterance_id:
                self._logged_utterances.add(utterance_id)

    def dead_air(
        self,
        reason: str = "dead air",
        *,
        source_id: str = "",
        strategy: str = "",
        fallback_target: str = "",
        preferred_target: str = "",
        action_mode: str = "",
        playback_delay_seconds: float = 0.0,
        cooldown_seconds: float = 0.0,
        local_room_behavior: dict[str, Any] | None = None,
        local_room_behavior_revision: str | None = None,
    ) -> str:
        if (self.local_behavior is not None and (
                (local_room_behavior is not None and local_room_behavior != self.local_behavior)
                or (local_room_behavior_revision is not None and local_room_behavior_revision != self.behavior_revision))):
            return ""
        if self.local_behavior is not None and (self.local_behavior['speaker_selection'] == 'manual'
                                               or not self.local_behavior['moderator_help']):
            return ""
        playback_delay_seconds = max(0.0, float(playback_delay_seconds))
        cooldown_seconds = max(0.0, float(cooldown_seconds))
        if self.local_behavior is not None:
            cooldown_seconds = self.local_behavior['cooldown_seconds']
            source = self.participants.get(source_id)
            if (source and source.kind == 'human'
                    and self.local_behavior['trigger'] == 'no_route_after_bot_speech'):
                return ""
        if (self.local_behavior is None and self.last_recovery_started is not None
                and time.monotonic() - self.last_recovery_started < cooldown_seconds):
            return ""
        if self.paused or self.skip_delivery_pending():
            return ""
        if action_mode and (self.next_id or self.pending_recovery):
            self.add_flow("dead_air", "", "", "Recovery skipped: a next speaker or recovery is already pending.")
            return ""
        if action_mode in {"moderator_speaks_and_calls_next", "moderator_speaks_only"}:
            return self._start_moderated_recovery(
                reason, source_id, strategy, fallback_target, preferred_target, action_mode, playback_delay_seconds,
            )
        strategy = str(strategy or "llm_choose").strip().lower()
        candidates = self._eligible_dead_air_participants(source_id)
        if self.local_behavior is not None:
            candidates = self._eligible_dead_air_participants(avoid_recent_speakers=False)
            if not self.local_behavior['allow_repeat']:
                candidates = [p for p in candidates if p.id != source_id]
        target = self._candidate_by_id(candidates, preferred_target)
        if self.local_behavior is not None and action_mode == 'silent_call_next' and not target:
            self.add_flow('dead_air', '', '', 'Recovery has no target from the room speaker-selection rule.')
            return ""
        if not target and strategy == "selected_fallback":
            target = self._candidate_by_id(candidates, fallback_target)
        if not target and action_mode == "silent_call_next" and strategy == "round_robin":
            target = self._round_robin_dead_air_candidate(candidates, source_id)
        if not target:
            target = self._candidate_mentioned_in_reason(candidates, reason)
        if not target:
            enforcer_id = str(self.moderator_state.get("enforcer_bot_id") or "").strip()
            target = self._candidate_by_id(candidates, enforcer_id)
        if not target and strategy == "round_robin":
            target = self._round_robin_dead_air_candidate(candidates, source_id)
        if not target and fallback_target:
            target = self._candidate_by_id(candidates, fallback_target)
        if not target:
            target = self._round_robin_dead_air_candidate(candidates, source_id)
        if not target:
            self.add_flow("dead_air", "", "", "No connected participant available for dead-air recovery.")
            return ""
        if self.local_behavior is None:
            self.last_recovery_started = time.monotonic()
        if action_mode == 'silent_call_next' and (playback_delay_seconds > 0 or self.local_behavior is not None):
            token = uuid.uuid4().hex
            self.pending_recovery = dict(token=token, action_mode=action_mode, moderator_id='',
                source_id=source_id, target_id=target.id, reason=reason,
                playback_delay_seconds=playback_delay_seconds, quiet_since=None, status='waiting_for_silence',
                cooldown_ready_at=(self.last_recovery_started + cooldown_seconds
                                   if self.local_behavior is not None and self.last_recovery_started is not None else 0))
            self._recovery_wait_seconds(token, target.id)
            threading.Thread(target=self._finish_silent_recovery, args=(token, target.id),
                             name='Local room silent recovery', daemon=True).start()
            return target.id
        self.set_next(target.id, reason)
        self.last_recovery_started = time.monotonic()
        self.last_dead_air_target_id = target.id
        self.add_flow("dead_air", "", target.id, f"Dead-air recovery chose {target.name}.")
        return target.id

    def _start_moderated_recovery(
        self, reason: str, source_id: str, strategy: str, fallback_target: str,
        preferred_target: str, action_mode: str, playback_delay_seconds: float = 0.0,
    ) -> str:
        moderator_id = str(self.moderator_state.get("enforcer_bot_id") or "")
        moderator = self.participants.get(moderator_id)
        if (not moderator or moderator.kind != "bot" or not moderator.connected
                or self.participant_is_muted(moderator_id)
                or not self.route_allowed_by_speaker_lock(moderator_id)[0]):
            self.add_flow("dead_air", "", "", "Recovery skipped: assigned moderator is unavailable or speaker-locked.")
            return ""
        strategy = str(strategy or "llm_choose").lower()
        allow_repeat = bool(self.local_behavior and self.local_behavior['allow_repeat'])
        automatic_candidates = [p for p in self._eligible_dead_air_participants(source_id)
                                if p.id != moderator_id or allow_repeat]
        candidates = automatic_candidates
        if strategy == "llm_choose":
            # An explicit moderator handoff may return to the previous speaker.
            # Recent-speaker avoidance is a fallback preference, not a safety restriction.
            candidates = [p for p in self._eligible_dead_air_participants(avoid_recent_speakers=False)
                          if p.id != moderator_id or allow_repeat]
        target = None
        if action_mode == "moderator_speaks_and_calls_next":
            if strategy == "selected_fallback":
                target = self._candidate_by_id(candidates, fallback_target)
            if not target and strategy != "llm_choose":
                target = self._round_robin_dead_air_candidate(candidates, source_id)
        fallback = self._candidate_by_id(candidates, fallback_target)
        if not fallback:
            fallback = self._round_robin_dead_air_candidate(automatic_candidates, source_id)
        recovery = {
            "token": uuid.uuid4().hex, "action_mode": action_mode,
            "moderator_id": moderator_id, "source_id": source_id,
            "strategy": strategy, "target_id": target.id if target else "",
            "fallback_target": fallback.id if fallback else "",
            "eligible_target_ids": [p.id for p in candidates],
            "playback_delay_seconds": playback_delay_seconds, "quiet_since": None,
            "status": "preparing",
            "cooldown_ready_at": (self.last_recovery_started + self.local_behavior['cooldown_seconds']
                                  if self.local_behavior is not None and self.last_recovery_started is not None else 0),
        }
        self.set_next(moderator_id, reason)
        # Additive route metadata travels with this exact invitation, not global UI state.
        self.route_flow[-1]["recovery"] = dict(recovery)
        self.pending_recovery = recovery
        if self.local_behavior is None:
            self.last_recovery_started = time.monotonic()
        self._recovery_wait_seconds(recovery['token'], moderator_id)
        self.add_flow("dead_air", "", moderator_id, f"Recovery: {moderator.name} speaks first | {action_mode}")
        return moderator_id

    def _recovery_target(self, recovery: dict[str, Any], preferred_target: str) -> Participant | None:
        candidates = [p for p in self._eligible_dead_air_participants(
                          recovery["source_id"], avoid_recent_speakers=recovery["strategy"] != "llm_choose")
                      if p.id in recovery["eligible_target_ids"]]
        choice = (preferred_target if recovery["strategy"] == "llm_choose" else recovery["target_id"])
        if self.local_behavior is not None:
            return self._candidate_by_id(candidates, choice)
        return self._candidate_by_id(candidates, choice or recovery["fallback_target"])

    def prepare_recovery(self, token: str, moderator_id: str, preferred_target: str, reply_text: str) -> str:
        """Invite a bot to render ahead while retaining the moderator's audio floor."""
        recovery = self.pending_recovery
        if (not recovery or recovery["token"] != token or recovery["moderator_id"] != moderator_id
                or self.current_id != moderator_id or self.playback_owner_id != moderator_id
                or self.next_id or self.moderator_state.get("enforcer_bot_id") != moderator_id
                or recovery["action_mode"] != "moderator_speaks_and_calls_next" or not reply_text.strip()):
            return ""
        target = self._recovery_target(recovery, preferred_target)
        if not target or target.kind != "bot":
            return ""
        self.set_next(target.id, "dead-air moderator reply ready; preparing next bot")
        self.route_flow[-1]["prepared_recovery"] = {
            "token": token, "text": reply_text, "source_id": moderator_id,
            "speaker_name": self.require_participant(moderator_id).name,
        }
        recovery["prepared_target_id"] = target.id
        self.pending_recovery = recovery
        return target.id

    def complete_recovery(self, token: str, moderator_id: str, preferred_target: str = "") -> str:
        """Called only after the recovery worker has finished delivering its audio."""
        recovery = self.pending_recovery
        if (not recovery or recovery["token"] != token or recovery["moderator_id"] != moderator_id
                or self.current_id != moderator_id or self.playback_owner_id != moderator_id):
            return ""
        self.pending_recovery = {}
        prepared = str(recovery.get("prepared_target_id") or "")
        if prepared and self.next_id == prepared:
            target = self._recovery_target(recovery, prepared)
            if not target or self.moderator_state.get("enforcer_bot_id") != moderator_id:
                self.clear_next("prepared recovery target is no longer eligible")
                return ""
            self.last_dead_air_target_id = target.id
            for event in reversed(self.route_flow):
                invitation = event.get("prepared_recovery") or {}
                if invitation.get("token") == token:
                    invitation["committed"] = True
                    break
            self.add_flow("dead_air", moderator_id, target.id, f"Recovery handoff -> {target.name}")
            return target.id
        if (self.next_id or self.moderator_state.get("enforcer_bot_id") != moderator_id
                or recovery["action_mode"] == "moderator_speaks_only"):
            return ""
        target = self._recovery_target(recovery, preferred_target)
        if not target:
            self.add_flow("dead_air", moderator_id, "", "Recovery handoff skipped: chosen participant is no longer eligible.")
            return ""
        self.set_next(target.id, "dead-air moderator speech delivered")
        self.last_dead_air_target_id = target.id
        self.add_flow("dead_air", moderator_id, target.id, f"Recovery handoff -> {target.name}")
        return target.id

    def cancel_recovery(self, token: str) -> None:
        if self.pending_recovery.get("token") != token:
            return
        moderator_id = self.pending_recovery["moderator_id"]
        prepared = self.pending_recovery.get("prepared_target_id")
        self.pending_recovery = {}
        if self.next_id == moderator_id or (prepared and self.next_id == prepared):
            self.clear_next("recovery ended without a completed handoff")

    def maybe_recover_dead_air(self, reason: str = "dead air", **options: Any) -> str:
        if self.current_id:
            self.clear_current(f"dead-air recovery: {reason}")
        return self.dead_air(reason, **options)

    def _record_skipped_reply(self, context):
        if not self.transcript_path or not context.get('text'):
            return
        self.transcript_path.parent.mkdir(parents=True, exist_ok=True)
        with self.transcript_path.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(dict(conversation_id=context['conversation_id'],
                speaker_id=context['source_id'], name=context['speaker_name'],
                utterance_id=context['turn_id'], text=context['text'],
                time=context.get('presentation_time', self.now()), display_only=True), ensure_ascii=False) + '\n')

    def skip_speech(self):
        """Keep generated text for display while cancelling only the current voice."""
        with self.lock:
            source_id = self.playback_owner_id or self.current_id
            member = self.participants.get(source_id)
            if not member or member.kind != 'bot':
                return False
            context = self._presentation_context(source_id)
            if context:
                saved = dict(context, text=context.get('presentation_text') or context.get('text') or '',
                    text_complete=bool(context.get('presentation_text') or context.get('ready')),
                    audience={p.id:p.admission_id for p in self.participants.values() if p.connected and p.kind == 'bot' and p.admission_id},
                    context_delivered=False)
                self._skipped_turns[saved['turn_id']] = saved
                self._record_skipped_reply(saved)
                recovery = self.pending_recovery
                if recovery.get('moderator_id') == source_id:
                    if recovery.get('prepared_target_id'):
                        self.complete_recovery(recovery['token'], source_id, recovery['prepared_target_id'])
                    else:
                        self.cancel_recovery(recovery['token'])
            self.stop_playback('skip_speech')
            if self.current_id == source_id:
                self.current_id = ''
                self._sync_flags()
            # Skip counts the complete reply as delivered, so already-prepared
            # responses remain valid. The receipt gate holds their playback.
            return True

    def skip_delivery_pending(self):
        return any(not item.get('context_delivered') and not item.get('delivery_failed')
            and item.get('conversation_id') == self.conversation_id
            and self.participants.get(item['source_id'])
            and self.participants[item['source_id']].admission_id == item['source_admission_id']
            for item in self._skipped_turns.values())

    def fail_skipped_reply(self, source_id, turn_id, conversation_id, admission_id, reason):
        with self.lock:
            item = self._skipped_turns.get(turn_id)
            if (not item or item['source_id'] != source_id or item['source_admission_id'] != admission_id
                    or conversation_id != self.conversation_id or item.get('context_delivered')):
                return False
            item.update(delivery_failed=True, error=str(reason or 'Reply generation failed.'))
            self.paused = True
            self.pause_after_turn = False
            departure = self._departures.get(source_id, {})
            if departure.get('drain_turn_id') == turn_id:
                departure['delivered_settled'] = True
            self.playback_condition.notify_all()
            return True

    def complete_skipped_reply(self, source_id, turn_id, conversation_id, admission_id):
        with self.lock:
            item = self._skipped_turns.get(turn_id)
            member = self.participants.get(source_id)
            if (not item or not item.get('text_complete') or not member
                    or member.admission_id != admission_id or item['source_id'] != source_id
                    or item['source_admission_id'] != admission_id
                    or conversation_id != self.conversation_id):
                return False
            if item.get('context_delivered'):
                return True
            if self.transcript_path:
                with self.transcript_path.open('a', encoding='utf-8') as handle:
                    handle.write(json.dumps(dict(conversation_id=conversation_id, speaker_id=source_id,
                        name=item['speaker_name'], utterance_id=turn_id, text=item['text'],
                        time=item.get('presentation_time', self.now()), replace_utterance=True),ensure_ascii=False)+'\n')
            item['context_delivered'] = True
            departure = self._departures.get(source_id, {})
            if departure.get('admission_id') == admission_id and departure.get('drain_turn_id') == turn_id:
                departure['delivered_settled'] = True
            self.playback_condition.notify_all()
            return True

    def begin_turn_context(self, source_id: str, turn_id: str, conversation_id: str, admission_id: str) -> bool:
        if self.participant_is_departing(source_id) or (self.participants.get(source_id)
                and self.participants[source_id].membership_phase != 'ready'):
            return False
        previous = self._turn_contexts.get(source_id, {})
        if previous.get('delivered') and previous.get('source_admission_id') == admission_id:
            return False  # A previous audible history obligation still owns this admission.
        member = self.participants.get(source_id)
        if (not turn_id or not self.conversation_id or conversation_id != self.conversation_id
                or not member or not member.connected or not admission_id or member.admission_id != admission_id):
            return False
        self._turn_contexts[source_id] = dict(source_id=source_id, turn_id=turn_id,
            conversation_id=conversation_id, source_admission_id=admission_id,
            speaker_name=member.name, text='', ready=False, cancelled=False,
            presentation_time=self.now(),
            playback_epoch=self.playback_epoch,
            listeners={p.id:p.admission_id for p in self.participants.values() if p.connected and p.admission_id},
            dependents={})
        return True

    def ready_turn_context(self, source_id: str, turn_id: str, conversation_id: str,
                           admission_id: str, text: str) -> bool:
        context = self._turn_contexts.get(source_id, {})
        member = self.participants.get(source_id)
        if (context.get('turn_id') != turn_id or context.get('cancelled') or not member or not member.connected
                or conversation_id != self.conversation_id or context.get('conversation_id') != conversation_id
                or member.admission_id != admission_id or context.get('source_admission_id') != admission_id):
            return False
        context.update(text=str(text or '').strip(), ready=bool(str(text or '').strip()))
        return bool(context['ready'])

    def preview_turn_context(self, source_id: str, turn_id: str, conversation_id: str,
                             admission_id: str, text: str) -> bool:
        skipped = self._skipped_turns.get(turn_id)
        if skipped is not None:
            member = self.participants.get(source_id)
            if (not member or member.admission_id != admission_id
                    or skipped['source_id'] != source_id or skipped['source_admission_id'] != admission_id
                    or conversation_id != self.conversation_id or skipped['conversation_id'] != conversation_id):
                return False
            if str(text).strip() and skipped.get('text') != str(text).strip():
                skipped['text'] = str(text).strip()
                skipped['text_complete'] = True
                self._record_skipped_reply(skipped)
            return True
        context = self._presentation_context(source_id, turn_id, admission_id)
        if not context or conversation_id != self.conversation_id:
            return False
        context['presentation_text'] = str(text or '').strip()
        return bool(context['presentation_text'])

    def end_turn_context(self, source_id: str, turn_id: str, conversation_id: str,
                         admission_id: str, completed: bool = False, history_settled: bool = False) -> bool:
        context = self._turn_contexts.get(source_id, {})
        member = self.participants.get(source_id)
        if (not member or member.admission_id != admission_id or conversation_id != self.conversation_id
                or context.get('turn_id') != turn_id or context.get('conversation_id') != conversation_id
                or context.get('source_admission_id') != admission_id):
            return False
        departure = self._departures.get(source_id, {})
        skipped = self._skipped_turns.get(turn_id)
        settled = (not context.get('delivered') or history_settled is True) and not (skipped and not skipped.get('context_delivered') and not skipped.get('delivery_failed'))
        if departure.get('admission_id') == admission_id and departure.get('drain_turn_id') == turn_id:
            departure['delivered_settled'] = settled
        if not completed and (not skipped or skipped.get('delivery_failed')):
            self.invalidate_turn_contexts(source_id, source_only=True)
            if self.playback_owner_id == source_id:
                self.stop_playback('source preparation failed', expected_owner=source_id)
        if settled:
            self._turn_contexts.pop(source_id, None)
        else:
            context['ended'] = True
        if not self.playback_owner_id and self.current_id == source_id:
            self.clear_current('source preparation ended')
        return True

    def invalidate_turn_contexts(self, participant_id: str, *, source_only: bool = False) -> None:
        context = self._turn_contexts.get(participant_id)
        if context:
            context['cancelled'] = True
            for target, index in context['dependents'].items():
                self.cancelled_routes_through[target] = max(self.cancelled_routes_through.get(target, 0), index)
        if not source_only:
            for other in self._turn_contexts.values():
                other['listeners'].pop(participant_id, None)

    def prepared_turn_context(self, target_id: str, admission_id: str, conversation_id: str,
                              route_index: int = 0) -> dict[str, Any]:
        if self.skip_delivery_pending():
            return {'status':'waiting'}
        if self.participant_is_departing(target_id):
            return {'status': 'cancelled'}
        target = self.participants.get(target_id)
        if (not target or not target.connected or not admission_id or target.admission_id != admission_id
                or not self.conversation_id or conversation_id != self.conversation_id
                or self.route_is_cancelled(target_id, route_index)):
            return {'status':'cancelled'}
        source_id = self.playback_owner_id or self.current_id
        source = self.participants.get(source_id)
        context = self._turn_contexts.get(source_id)
        if not source or source.kind != 'bot' or source_id == target_id:
            return {'status':'clear'}
        if (not route_index or not context or context.get('cancelled') or not context.get('ready')
                or context['listeners'].get(target_id) != admission_id
                or context.get('source_admission_id') != source.admission_id):
            return {'status':'waiting'}
        context['dependents'][target_id] = max(context['dependents'].get(target_id, 0), route_index)
        scoped = {key:value for key,value in context.items() if key not in {
            'listeners', 'dependents', 'cancelled', 'ready', 'presentation_time', 'presentation_chunk',
            'presentation_delivered_text', 'presentation_text'}}
        scoped.update(target_id=target_id, target_admission_id=admission_id,
                      playback_epoch=self.playback_epoch)
        return {'status':'ready', 'context':scoped}

    def prepared_playback_allowed(self, route_index: int, participant_id: str) -> bool:
        if not route_index:
            return True
        event = next((item for item in self.route_flow if item.get("index") == route_index), {})
        invitation = event.get("prepared_recovery") or {}
        return bool(invitation.get("committed") and event.get("target_id") == participant_id
                    and participant_id in {self.next_id, self.current_id, self.playback_owner_id}
                    and ((self.participant_is_muted(participant_id)
                          and participant_id in {self.current_id, self.playback_owner_id})
                         or self._candidate_by_id(self._eligible_dead_air_participants(avoid_recent_speakers=False), participant_id)))

    def playback_held_for_pause(self, participant_id: str) -> bool:
        return bool(self.skip_delivery_pending() or (self.paused and self.pause_after_turn and participant_id != self.pause_current_id))

    def _presentation_context(self, source_id: str, turn_id: str = '', admission_id: str = '') -> dict[str, Any]:
        """Display metadata has the same lifetime as its admitted preparation."""
        context = self._turn_contexts.get(source_id, {})
        member = self.participants.get(source_id)
        if (not member or not member.connected or member.kind != 'bot'
                or context.get('cancelled') or context.get('ended')
                or context.get('conversation_id') != self.conversation_id
                or context.get('source_admission_id') != member.admission_id
                or context.get('playback_epoch') != self.playback_epoch
                or (turn_id and context.get('turn_id') != turn_id)
                or (admission_id and member.admission_id != admission_id)):
            return {}
        return context

    def _presentation_turn(self) -> dict[str, Any]:
        source_id = self.playback_owner_id or self.current_id
        context = self._presentation_context(source_id)
        if (not context or self.playback_held_for_pause(source_id)
                or (self.paused and not self.pause_after_turn)):
            return {}
        chunk = context.get('presentation_chunk') or {}
        active = bool(chunk.get('active') and self.playback_owner_id == source_id)
        duration = chunk.get('duration', 0)
        progress = (min(1., max(0., (time.monotonic() - chunk['started']) / duration))
                    if active and duration > 0 else float(bool(chunk) and not active))
        return dict(source_id=source_id, turn_id=context['turn_id'],
            conversation_id=context['conversation_id'], admission_id=context['source_admission_id'],
            name=context['speaker_name'], text=context.get('presentation_text') or context['text'], time=context['presentation_time'],
            display_pending=not bool(context.get('presentation_text') or context.get('ready')),
            delivered=bool(context.get('delivered')), speech_active=active,
            speech_progress=progress, spoken_text=str(chunk.get('text') or ''),
            spoken_prefix=str(chunk.get('prefix') or ''))

    def _playback_epoch_matches(self, epoch, participant_id, turn_id, admission_id):
        if turn_id and turn_id in self._skipped_turns:
            return False
        if epoch is None or epoch == self.playback_epoch:
            return True
        # Only an explicitly retained, current admission may cross a completed
        # handoff. Cancelled preparations and the skipped source remain barred.
        return bool(epoch < self.playback_epoch and turn_id and admission_id
                    and (self.last_playback_stop_reason == 'skip_speech'
                         or self.last_playback_stop_reason.endswith('turn finished'))
                    and self._presentation_context(participant_id, turn_id, admission_id))

    def play_wav(
        self, participant_id: str, wav_path: str, *, playback_epoch: int | None = None,
        recovery_token: str = "",
        prepared_route_index: int = 0,
        route_index: int = 0,
        wait_for_completion: bool = False,
        turn_id: str = '', admission_id: str = '', spoken_text: str = '',
    ) -> bool:
        path = Path(wav_path)
        if not path.exists():
            raise FileNotFoundError(wav_path)
        with self.playback_condition:
            if turn_id and turn_id in self._skipped_turns:
                return False  # Never restart skipped speech with a refreshed epoch.
            if self.participant_is_departing(participant_id):
                departure = self._departures[participant_id]
                if (not departure['drain_turn_id'] or turn_id != departure['drain_turn_id']
                        or admission_id != departure['admission_id']):
                    return False
            if self.route_is_cancelled(participant_id, route_index):
                return False
            if not self.prepared_playback_allowed(prepared_route_index, participant_id):
                return False
            if (recovery_token and self.pending_recovery.get("token") != recovery_token
                    and self.playback_owner_id != participant_id):
                return False
            if not self._playback_epoch_matches(playback_epoch, participant_id, turn_id, admission_id):
                self.add_flow("playback", participant_id, "", f"Playback rejected as stale for {participant_id}: {path.name}")
                return False
            participant = self.require_participant(participant_id)
            if (self.playback_held_for_pause(participant_id)
                    or (self.playback_owner_id and self.playback_owner_id != participant_id)):
                participant.queued_audio += 1
                participant.playback_state = "queued"
                participant.last_event = f"queued wav: {path.name}"
                participant.updated_at = self.now()
                self.add_flow("playback", participant_id, self.playback_owner_id, f"Playback queued for {participant.name}: {path.name}")
                while (self.playback_held_for_pause(participant_id)
                       or (self.playback_owner_id and self.playback_owner_id != participant_id)):
                    self.playback_condition.wait(timeout=0.25)
                    if self.route_is_cancelled(participant_id, route_index):
                        participant.queued_audio = max(0, participant.queued_audio - 1)
                        participant.playback_state = "idle"
                        return False
                participant.queued_audio = max(0, participant.queued_audio - 1)
            # The condition wait releases the lock: recheck pause and generation too.
            if not self._playback_epoch_matches(playback_epoch, participant_id, turn_id, admission_id):
                return False
            if self.route_is_cancelled(participant_id, route_index):
                return False
            if not self.prepared_playback_allowed(prepared_route_index, participant_id):
                return False
            while (self.local_behavior is not None and self.active_human_ids
                   and self.playback_owner_id != participant_id):
                self.playback_condition.wait(timeout=0.25)
                if (self.route_is_cancelled(participant_id, route_index)
                        or participant_id not in self.participants
                        or (recovery_token and self.pending_recovery.get('token') != recovery_token)):
                    return False
            if recovery_token and not self._wait_recovery_ready(recovery_token, participant_id):
                return False
            if self.route_is_cancelled(participant_id, route_index):
                return False
            if recovery_token and self.pending_recovery.get('token') == recovery_token:
                if not self.pending_recovery.get('playback_started'):
                    self.last_recovery_started = time.monotonic()
                self.pending_recovery.update(playback_started=True, status='speaking')
                self.active_recovery_token = recovery_token
            participant.playback_state = "playing"
            participant.last_event = f"playing wav: {path.name}"
            participant.updated_at = self.now()
            self.playback_owner_id = participant_id
            if (self.directive.get('status') == 'preparing'
                    and self.directive.get('moderator_id') == participant_id
                    and self.directive.get('route_index') == route_index):
                self.directive.update(status='delivering', detail='Moderator is speaking.')
            if self.current_id != participant_id:
                self.set_current(participant_id, "audio playback")
            self.add_flow("playback", participant_id, "", f"Playback started as {participant.name}: {path}")
            output_cancel = self._output_cancel
            output_epoch = self.playback_epoch
        if wait_for_completion:
            # HTTP controls must remain available while audio drains or waits for
            # the physical output. Each request retains its original cancellation.
            with self._output_lock:
                with self.lock:
                    if (output_cancel.is_set() or self.playback_epoch != output_epoch
                            or participant_id not in self.participants
                            or self.playback_owner_id != participant_id
                            or self.route_is_cancelled(participant_id, route_index)
                            or not self.prepared_playback_allowed(prepared_route_index, participant_id)):
                        return False
                try:
                    if self._output_player is None:
                        if __package__:
                            from .audio_output import CancellableWavPlayer
                        else:
                            from audio_output import CancellableWavPlayer
                        self._output_player = CancellableWavPlayer()
                    # Start the display clock only after admission and the output
                    # lock. Queued/held audio must never advance a reading cursor.
                    duration = 0.
                    if spoken_text:
                        try:
                            with wave.open(str(path), 'rb') as audio:
                                duration = audio.getnframes() / float(audio.getframerate())
                        except (OSError, EOFError, wave.Error, ZeroDivisionError):
                            pass  # Unknown timing must not prevent audio delivery.
                    with self.lock:
                        context = self._presentation_context(participant_id, turn_id, admission_id) if turn_id else {}
                        chunk = dict(text=spoken_text, prefix=context.get('presentation_delivered_text', ''),
                                     started=time.monotonic(), duration=duration, active=duration > 0)
                        if context and not output_cancel.is_set() and self.playback_epoch == output_epoch:
                            context['presentation_chunk'] = chunk
                    completed = self._output_player.play(path, output_cancel)
                except Exception:
                    with self.lock:
                        if self.playback_epoch == output_epoch and self.playback_owner_id == participant_id:
                            self.stop_playback("audio output error")
                    raise
                with self.lock:
                    if context.get('presentation_chunk') is chunk:
                        chunk['active'] = False
                    self.audio_output_underruns = self._output_player.underruns
                    if self.audio_output_underruns:
                        self.add_flow("playback", participant_id, "", f"Audio output underruns: {self.audio_output_underruns}")
                    if not completed and self.playback_epoch == output_epoch and self.playback_owner_id == participant_id:
                        self.stop_playback("audio output error")
                    return bool(completed and not output_cancel.is_set()
                                and self.playback_epoch == output_epoch
                                and self.playback_owner_id == participant_id)
        if winsound is not None:
            winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
        return True

    def stop_playback(self, reason: str = "external command", *, expected_owner: str = "", recovery_token: str = "") -> None:
        if expected_owner and self.playback_owner_id != expected_owner:
            return
        if recovery_token:
            self.cancel_recovery(recovery_token)
        if (
            ("speech probe" in reason or "user speech" in reason)
            and not bool(self.moderator_state.get("allow_current_interruption"))
            and (self.playback_owner_id or self.current_id)
        ):
            self.add_flow("playback", "", "", f"Playback interruption blocked | {reason}")
            return
        old_owner = self.playback_owner_id
        advances_turn = reason.endswith('turn finished') or reason == 'skip_speech'
        if (reason.endswith('turn finished') and not self.participant_is_departing(old_owner or self.current_id)
                and not self._turn_contexts.get(old_owner or self.current_id, {}).get('delivered')):
            self._turn_contexts.pop(old_owner or self.current_id, None)
        if not advances_turn:
            # A response prepared from undelivered source speech must never play.
            for source_id in tuple(self._turn_contexts):
                self.invalidate_turn_contexts(source_id, source_only=True)
        if (advances_turn and self.pending_recovery
                and old_owner == self.pending_recovery.get('source_id')
                and not self.pending_recovery.get('playback_started')):
            self.pending_recovery['quiet_since'] = time.monotonic()
            self.pending_recovery['status'] = 'waiting_for_silence'
        if not advances_turn:
            self.cancel_directive(reason)
        self._output_cancel.set()
        self._output_cancel = threading.Event()
        if not advances_turn:
            self.cancel_recovery(str(self.pending_recovery.get("token") or ""))
        if winsound is not None:
            winsound.PlaySound(None, winsound.SND_PURGE)
        for participant in self.participants.values():
            if participant.playback_state in {"playing", "queued"} or participant.queued_audio:
                participant.queued_audio = 0
                participant.playback_state = "stopped"
                participant.last_event = f"playback stopped: {reason}"
                participant.updated_at = self.now()
        previous_playback_epoch = self.playback_epoch
        self.playback_epoch += 1
        if advances_turn:
            # Prepared replies remain admitted across an ordinary speaker handoff.
            # Skip also completes the turn; explicit holds still invalidate them.
            for context in self._turn_contexts.values():
                if (context.get('playback_epoch') == previous_playback_epoch
                        and not context.get('cancelled') and not context.get('ended')):
                    context['playback_epoch'] = self.playback_epoch
        self.last_playback_stop_reason = reason
        self.playback_owner_id = ""
        self.active_recovery_token = ""
        directive_next = (self.directive.get('status') in {'queued', 'preparing'}
                          and self.directive.get('moderator_id') == self.next_id)
        recovery_next = bool(self.local_behavior is not None and self.pending_recovery
                             and self.pending_recovery.get('moderator_id') == self.next_id)
        repeat_next = bool(self.local_behavior and self.local_behavior['allow_repeat'] and self.next_id == old_owner)
        if (advances_turn and old_owner and self.next_id == old_owner
                and not directive_next and not recovery_next and not repeat_next):
            self.next_id = ""
            self._clear_pending_routes(last_command="clear_pending")
            self.add_flow("route", old_owner, "", f"Next cleared | stale self route after {reason}")
        if "speech probe" in reason or "user speech" in reason:
            old_next = self.next_id
            self.next_id = ""
            if old_next:
                self.add_flow("route", old_next, "", f"Next cleared | {reason}")
        should_clear_current = (
            self.current_id == old_owner
            and (
                reason in {"clear_queue", "stop_speech", "skip_speech", "audio output error"}
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
        if advances_turn:
            if self.pause_current_id == old_owner:
                self.pause_current_id = ""
            next_participant = self.participants.get(self.next_id)
            if next_participant and next_participant.kind == "human":
                self.set_current(next_participant.id, f"human next after {reason}")
        self.add_flow("playback", "", "", f"Playback stopped | {reason}")
        with self.playback_condition:
            self.playback_condition.notify_all()

    def ensure_capture_owner(self, reason: str = "capture owner check") -> str:
        if self.paused:
            self.capture_owner_id = ""
            return ""
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
            if self.pending_recovery:
                recovery = self.pending_recovery
                participant_id = str(recovery.get('moderator_id') or recovery.get('target_id') or '')
                remaining = self._recovery_wait_seconds(str(recovery.get('token') or ''), participant_id)
                recovery['playback_ready'] = remaining is not None and remaining <= 0
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
                "presentation_turn": self._presentation_turn(),
                "skip_delivery_pending": self.skip_delivery_pending(),
                "skip_error": next((item.get('error', '') for item in reversed(list(self._skipped_turns.values())) if item.get('delivery_failed') and not item.get('error_acknowledged')), ''),
                "skipped_turn_ids": list(self._skipped_turns),
                "skipped_replies": [{key:item.get(key) for key in ('source_id','turn_id','source_admission_id','conversation_id','audience','text','text_complete','context_delivered','delivery_failed')} for item in self._skipped_turns.values()],
                "paused": self.paused,
                "pause_after_turn": self.pause_after_turn,
                "pause_current_id": self.pause_current_id,
                "pausing": bool(self.paused and self.pause_after_turn and self.pause_current_id
                                and self.pause_current_id in {self.current_id, self.playback_owner_id}),
                "audio_output_underruns": self.audio_output_underruns,
                "last_playback_stop_reason": self.last_playback_stop_reason,
                "pending_recovery": dict(self.pending_recovery),
                **({'behavior': dict(self.local_behavior), 'active_human_ids': sorted(self.active_human_ids),
                    'active_recovery_token': self.active_recovery_token, 'behavior_revision': self.behavior_revision}
                   if self.local_behavior is not None else {}),
                "directive": dict(self.directive),
                "cancelled_routes_through": dict(self.cancelled_routes_through),
                "moderator_state": dict(self.moderator_state),
                "participants": [dict(asdict(item), muted=self.participant_is_muted(item.id))
                                 for item in self.participants.values()],
                'departures': {pid: self.departure_status(pid, entry['admission_id'])
                               for pid, entry in self._departures.items()},
                "route_flow": list(self.route_flow[-100:]),
            }

    def queue_directive(self, kind: str, text: str, moderator_id: str, conversation_id: str, *, restore: bool = False) -> dict[str, Any]:
        """Ephemeral Local room action; private text never enters the room transcript."""
        with self.lock:
            if not self.conversation_id or conversation_id != self.conversation_id:
                raise ValueError('This Local room conversation has changed.')
            if self.paused and not (restore and self.pause_after_turn):
                raise ValueError('Resume the room first.')
            moderator = self.require_participant(moderator_id)
            if moderator.kind != 'bot' or not moderator.connected or self.participant_is_muted(moderator_id):
                raise ValueError('Choose an available, unmuted bot.')
            if kind not in {'guide', 'say'} or not str(text).strip():
                raise ValueError('Enter guidance or text to say first.')
            if self.directive.get('status') in {'queued', 'preparing', 'delivering'}:
                raise ValueError('Wait for the pending guidance or announcement to finish.')
            self.replace_next(moderator_id, 'Local room moderator action')
            cutoff = self.route_flow[-1]['index'] if self.route_flow else 0
            for pid, member in self.participants.items():
                if member.kind == 'bot' and pid not in {self.current_id, self.playback_owner_id}:
                    self.cancelled_routes_through[pid] = cutoff
            self.directive = dict(id=uuid.uuid4().hex, kind=kind, text=str(text).strip(),
                moderator_id=moderator_id, conversation_id=conversation_id,
                status='queued', detail='Waiting for the current speaker to finish.')
            self.add_flow('guidance', '', moderator_id, 'Moderator action queued.')
            self.route_flow[-1]['directive_id'] = self.directive['id']
            self.directive['route_index'] = self.route_flow[-1]['index']
            return dict(self.directive)

    def claim_directive(self, directive_id: str, moderator_id: str, conversation_id: str) -> bool:
        with self.lock:
            if self.skip_delivery_pending():
                return False
            d = self.directive
            if (d.get('id') != directive_id or d.get('moderator_id') != moderator_id
                    or d.get('conversation_id') != conversation_id or d.get('status') != 'queued'
                    or self.paused):
                return False
            moderator = self.participants.get(moderator_id)
            if not moderator or not moderator.connected or self.participant_is_muted(moderator_id):
                self.cancel_directive('Moderator is no longer available.')
                return False
            if d.get('kind') == 'guide':
                # Like manual Next, generation can run before the floor is free.
                # The existing playback queue waits and claims Current on audio.
                d.update(status='preparing', detail='Preparing the moderator reply; playback waits for the current speaker.')
                return True
            current = self.participants.get(self.current_id)
            if self.playback_owner_id or (current and current.kind == 'bot' and current.id != moderator_id):
                d.update(status='preparing', detail='Preparing speech; playback waits for the current speaker.')
                return True
            d.update(status='delivering', detail='Moderator is preparing and speaking.')
            self.set_current(moderator_id, 'Local room moderator action')
            self.route_flow[-1]['directive_id'] = directive_id
            # Reserve the now-free floor before another prepared worker can claim it.
            self.playback_owner_id = moderator_id
            return True

    def finish_directive(self, directive_id: str, moderator_id: str, conversation_id: str,
                         delivered: bool, detail: str = '') -> bool:
        with self.lock:
            d = self.directive
            if (d.get('id') != directive_id or d.get('moderator_id') != moderator_id
                    or d.get('conversation_id') != conversation_id
                    or d.get('status') not in {'preparing', 'delivering'}
                    or (delivered and d.get('status') != 'delivering')):
                return False
            if not delivered and d.get('status') == 'preparing':
                self.cancel_directive(detail or 'Moderator preparation failed.', queued_only=True)
            d.update(status='delivered' if delivered else 'failed',
                     detail=detail or ('Moderator finished speaking.' if delivered else 'No complete audio was delivered.'))
            return True

    def cancel_directive(self, reason: str, *, queued_only: bool = False) -> None:
        with self.lock:
            d = self.directive
            if d.get('status') not in ({'queued', 'preparing'} if queued_only else {'queued', 'preparing', 'delivering'}):
                return
            if d.get('status') == 'preparing':
                moderator_id = d['moderator_id']
                self.cancelled_routes_through[moderator_id] = max(
                    self.cancelled_routes_through.get(moderator_id, 0), int(d.get('route_index') or 0))
            if d.get('status') in {'queued', 'preparing'} and self.next_id == d.get('moderator_id'):
                self.next_id = ''
                self._clear_pending_routes()
                self._sync_flags()
            d.update(status='cancelled', detail=str(reason))

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
        if self.path.startswith('/participants/departure?'):
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            self.send_json(ROOM.departure_status(query.get('id', [''])[0], query.get('admission_id', [''])[0]))
            return
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
            if path == "/play" and payload.get("wait_for_completion") is True:
                # The normal dispatcher holds ROOM.lock. Completion playback
                # owns its own short state locks, never that outer request lock.
                accepted = ROOM.play_wav(
                    str(payload.get("speaker_id") or payload.get("id") or "").strip(),
                    str(payload.get("wav_path") or payload.get("path") or "").strip(),
                    playback_epoch=int(payload["playback_epoch"]) if "playback_epoch" in payload else None,
                    recovery_token=str(payload.get("recovery_token") or ""),
                    prepared_route_index=int(payload.get("prepared_route_index") or 0),
                    route_index=int(payload.get("route_index") or 0), wait_for_completion=True,
                    turn_id=str(payload.get('utterance_id') or ''), admission_id=str(payload.get('admission_id') or ''),
                    spoken_text=str(payload.get('spoken_text') or ''),
                )
                if accepted:
                    ROOM.record_heard_chunk(str(payload.get('speaker_id') or ''),
                        str(payload.get('spoken_text') or ''), str(payload.get('utterance_id') or ''))
                self.send_json({"ok": accepted, "playback_complete": accepted,
                                "reason": "" if accepted else "playback_cancelled", "state": ROOM.snapshot()})
                return
            with ROOM.lock:
                if path == "/participants/upsert":
                    ROOM.upsert_participant(
                        str(payload.get("id") or payload.get("participant_id") or "").strip(),
                        str(payload.get("name") or payload.get("id") or "").strip(),
                        str(payload.get("type") or payload.get("kind") or "bot").strip().lower(),
                        bool(payload.get("connected", True)),
                        admission_id=str(payload.get('admission_id') or ''),
                        membership_phase=str(payload.get('membership_phase') or ''),
                    )
                elif path == '/participants/depart':
                    self.send_json(dict(ok=True, **ROOM.request_departure(
                        str(payload.get('id') or ''), str(payload.get('admission_id') or ''))))
                    return
                elif path == '/participants/admit':
                    ROOM.admit_participant(str(payload.get('id') or ''), str(payload.get('admission_id') or ''))
                elif path == "/participants/remove":
                    expected = str(payload.get('admission_id') or '')
                    member = ROOM.participants.get(str(payload.get('id') or ''))
                    if expected and member and member.admission_id != expected:
                        raise ValueError('This Local room admission has changed.')
                    ROOM.remove_participant(str(payload.get("id") or payload.get("participant_id") or "").strip())
                elif path == "/participants/connect":
                    ROOM.set_connected(str(payload.get("id") or payload.get("participant_id") or "").strip(), True)
                elif path == "/participants/disconnect":
                    ROOM.set_connected(str(payload.get("id") or payload.get("participant_id") or "").strip(), False)
                elif path == '/local-room/turn-context':
                    action = str(payload.get('action') or '')
                    if action == 'get':
                        result = ROOM.prepared_turn_context(str(payload.get('target_id') or ''),
                            str(payload.get('admission_id') or ''), str(payload.get('conversation_id') or ''),
                            int(payload.get('route_index') or 0))
                        self.send_json(dict(result, state=ROOM.snapshot()))
                        return
                    identity = dict(source_id=str(payload.get('source_id') or ''),
                        turn_id=str(payload.get('turn_id') or ''), conversation_id=str(payload.get('conversation_id') or ''),
                        admission_id=str(payload.get('admission_id') or ''))
                    if action == 'begin':
                        accepted = ROOM.begin_turn_context(**identity)
                    elif action == 'ready':
                        accepted = ROOM.ready_turn_context(**identity, text=str(payload.get('text') or ''))
                    elif action == 'preview':
                        accepted = ROOM.preview_turn_context(**identity, text=str(payload.get('text') or ''))
                    elif action == 'end':
                        accepted = ROOM.end_turn_context(**identity, completed=payload.get('text') == 'complete',
                            history_settled=payload.get('history_settled') is True)
                    else:
                        raise ValueError('Unknown turn context action.')
                    self.send_json({'ok': accepted})
                    return
                elif path == "/speech":
                    expected_owner = str(payload.get("expected_owner") or "")
                    if expected_owner and (ROOM.playback_owner_id != expected_owner
                            or payload.get("playback_epoch", ROOM.playback_epoch) != ROOM.playback_epoch):
                        self.send_json({"ok": False, "reason": "stale_speech_owner"})
                        return
                    ROOM.speech_event(
                        str(payload.get("speaker_id") or payload.get("id") or "").strip(),
                        str(payload.get("text") or "").strip(),
                        str(payload.get("reason") or "speech").strip(),
                        utterance_id=str(payload.get('utterance_id') or ''),
                    )
                elif path in {"/route", "/next"}:
                    ROOM.apply_route_decision(
                        str(payload.get("source_id") or payload.get("speaker_id") or "").strip(),
                        str(payload.get("target_id") or payload.get("id") or "").strip(),
                        str(payload.get("reason") or "external route").strip(),
                        True,
                        local_room_behavior=payload.get("local_room_behavior"),
                        local_room_behavior_revision=payload.get("local_room_behavior_revision"),
                    )
                elif path == "/decision":
                    ROOM.apply_route_decision(
                        str(payload.get("source_id") or payload.get("speaker_id") or "").strip(),
                        str(payload.get("target_id") or "").strip(),
                        str(payload.get("reason") or "route decision").strip(),
                        bool(payload.get("answer")),
                        local_room_behavior=payload.get("local_room_behavior"),
                        local_room_behavior_revision=payload.get("local_room_behavior_revision"),
                    )
                elif path == '/local-room/human-speaking':
                    ROOM.set_human_activity(str(payload.get('id') or 'human'), bool(payload.get('active')))
                elif path == '/local-room/behavior':
                    ROOM.configure_local_behavior(payload.get('behavior') or {}, str(payload.get('revision') or ''))
                elif path == '/local-room/skipped-reply':
                    args = (str(payload.get('source_id') or ''),str(payload.get('turn_id') or ''),
                        str(payload.get('conversation_id') or ''),str(payload.get('admission_id') or ''))
                    accepted = (ROOM.fail_skipped_reply(*args,str(payload.get('reason') or '')) if payload.get('action') == 'fail'
                                else ROOM.complete_skipped_reply(*args))
                    self.send_json({'ok': True, 'accepted': accepted, 'state': ROOM.snapshot()})
                    return
                elif path == '/local-room/skip-speech':
                    accepted = ROOM.skip_speech()
                    self.send_json({'ok': True, 'accepted': accepted, 'state': ROOM.snapshot()})
                    return
                elif path == '/local-room/directive':
                    action = str(payload.get('action') or 'queue')
                    args = (str(payload.get('id') or ''), str(payload.get('moderator_id') or ''),
                            str(payload.get('conversation_id') or ''))
                    accepted = True
                    if action == 'queue':
                        ROOM.queue_directive(str(payload.get('kind') or ''), str(payload.get('text') or ''),
                                             args[1], args[2], restore=bool(payload.get('restore')))
                    elif action == 'claim':
                        accepted = ROOM.claim_directive(*args)
                    elif action == 'complete':
                        accepted = ROOM.finish_directive(*args, bool(payload.get('delivered')), str(payload.get('detail') or ''))
                    elif action == 'cancel':
                        ROOM.cancel_directive(str(payload.get('reason') or 'Cancelled by user.'))
                    else:
                        raise ValueError('Unknown Local room directive action.')
                    self.send_json({'ok': True, 'accepted': accepted, 'state': ROOM.snapshot()})
                    return
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
                    target = ROOM.dead_air(
                        str(payload.get("reason") or "dead air").strip(),
                        source_id=str(payload.get("source_id") or payload.get("speaker_id") or "").strip(),
                        strategy=str(payload.get("strategy") or "").strip(),
                        fallback_target=str(payload.get("fallback_target") or payload.get("selected_fallback_target") or "").strip(),
                        preferred_target=str(payload.get("preferred_target") or payload.get("preferred_target_id") or "").strip(),
                        action_mode=str(payload.get("action_mode") or "").strip(),
                        playback_delay_seconds=float(payload.get("playback_delay_seconds") or 0),
                        cooldown_seconds=float(payload.get("cooldown_seconds") or 0),
                        local_room_behavior=payload.get("local_room_behavior"),
                        local_room_behavior_revision=payload.get("local_room_behavior_revision"),
                    )
                    self.send_json({"ok": True, "target_id": target, "state": ROOM.snapshot()})
                    return
                elif path == "/dead-air/prepare":
                    target = ROOM.prepare_recovery(
                        str(payload.get("token") or ""), str(payload.get("moderator_id") or ""),
                        str(payload.get("preferred_target") or ""), str(payload.get("reply_text") or ""),
                    )
                    self.send_json({"ok": True, "target_id": target, "state": ROOM.snapshot()})
                    return
                elif path == "/dead-air/complete":
                    target = ROOM.complete_recovery(
                        str(payload.get("token") or ""), str(payload.get("moderator_id") or ""),
                        str(payload.get("preferred_target") or ""),
                    )
                    self.send_json({"ok": True, "target_id": target, "state": ROOM.snapshot()})
                    return
                elif path == "/dead-air/cancel":
                    ROOM.cancel_recovery(str(payload.get("token") or ""))
                elif path == "/play":
                    accepted = ROOM.play_wav(
                        str(payload.get("speaker_id") or payload.get("id") or "").strip(),
                        str(payload.get("wav_path") or payload.get("path") or "").strip(),
                        playback_epoch=int(payload["playback_epoch"]) if "playback_epoch" in payload else None,
                        recovery_token=str(payload.get("recovery_token") or ""),
                        prepared_route_index=int(payload.get("prepared_route_index") or 0),
                        route_index=int(payload.get("route_index") or 0),
                    )
                    if not accepted:
                        self.send_json({"ok": False, "reason": "stale_playback_epoch", "state": ROOM.snapshot()})
                        return
                elif path == "/stop":
                    ROOM.stop_playback(
                        str(payload.get("reason") or "external command").strip(),
                        expected_owner=str(payload.get("expected_owner") or ""),
                        recovery_token=str(payload.get("recovery_token") or ""),
                    )
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
        try:
            status = str(args[1] if len(args) > 1 else "")
            if status == "200":
                return
        except Exception:
            pass
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
    assert contract_room.participants == {}
    with contract_room.lock:
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
        contract_room.set_current("echo", "self-test active bot with stale self next")
        contract_room.set_next("echo", "self-test stale self route")
        contract_room.playback_owner_id = "echo"
        contract_room.stop_playback("echo turn finished")
        stale_self_next_finished_state = contract_room.snapshot()
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
        contract_room.clear_all_moderator("self-test reset before self route")
        contract_room.playback_owner_id = ""
        contract_room.current_id = "echo"
        contract_room.next_id = ""
        contract_room._sync_flags()
        self_route_accepted = contract_room.apply_route_decision("echo", "echo", "open room question", True)
        self_route_state = contract_room.snapshot()
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
        contract_room.clear_all_moderator("self-test reset before mentioned recovery")
        contract_room.handle_moderator_command(
            {
                "action": "moderator_set_enforcer",
                "target_bot_id": "moderator",
                "reason": "self-test appointed moderator",
            }
        )
        contract_room.set_current("moderator", "self-test active moderator")
        mentioned_recovery_target = contract_room.dead_air(
            "dead_air_recovery:The moderator's turn is complete; awaiting responses from Kalle or Nova.",
            strategy="llm_choose",
        )
        mentioned_recovery_state = contract_room.snapshot()
        contract_room.clear_all_moderator("self-test reset before round-robin recovery")
        contract_room.set_current("moderator", "self-test active moderator")
        round_robin_target = contract_room.dead_air(
            "dead_air_recovery:The moderator is asking the whole room.",
            strategy="llm_choose",
        )
        round_robin_state = contract_room.snapshot()
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
    assert stale_self_next_finished_state["current_id"] == ""
    assert stale_self_next_finished_state["next_id"] == ""
    assert stale_self_next_finished_state["moderator_state"]["pending_route"] == {}
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
    assert self_route_accepted is False
    assert self_route_state["next_id"] == ""
    assert self_route_state["moderator_state"]["pending_route"] == {}
    assert any("self_route" in item["message"] for item in self_route_state["route_flow"])
    assert human_locked_bot_accepted is False
    assert human_locked_self_accepted is True
    assert human_lock_route_state["current_id"] == "rakila"
    assert recovered_target == "moderator"
    assert recovery_state["next_id"] == recovered_target
    assert recovery_state["current_id"] == ""
    assert mentioned_recovery_target in {"rakila", "nova"}
    assert mentioned_recovery_state["next_id"] == mentioned_recovery_target
    assert mentioned_recovery_target != "echo"
    assert round_robin_target != "echo"
    assert round_robin_state["next_id"] == round_robin_target
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

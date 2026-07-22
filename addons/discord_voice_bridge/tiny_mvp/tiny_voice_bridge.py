from __future__ import annotations

import argparse
import json
import os
import queue
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
import wave
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


def safe_print(*args: Any, sep: str = " ", end: str = "\n", file: Any = None, flush: bool = True) -> None:
    stream = file if file is not None else sys.stdout
    text = sep.join(str(arg) for arg in args) + end
    try:
        stream.write(text)
    except UnicodeEncodeError:
        encoding = getattr(stream, "encoding", None) or "utf-8"
        stream.write(text.encode(encoding, errors="replace").decode(encoding, errors="replace"))
    if flush:
        stream.flush()


print = safe_print


@dataclass
class SpeechMemory:
    index: int
    source_id: str
    speaker_name: str
    text: str


class TinyVoiceBridge:
    def __init__(
        self,
        *,
        bot_id: str,
        bot_name: str,
        tiny_url: str,
        nc_turn_url: str,
        poll_seconds: float,
        capture_mic: bool = False,
        mic_user_id: str = "human",
        mic_user_name: str = "Human",
        mic_seconds: float = 6.0,
        mic_sample_rate: int = 16000,
        mic_device: str = "",
        route_protected_mic_speech: bool = False,
    ) -> None:
        self.bot_id = safe_id(bot_id)
        self.bot_name = bot_name.strip() or self.bot_id
        self.tiny_url = tiny_url.rstrip("/")
        self.nc_turn_url = nc_turn_url
        self.poll_seconds = max(0.05, float(poll_seconds))
        self.capture_mic = bool(capture_mic)
        self.mic_user_id = safe_id(mic_user_id) or "human"
        self.mic_user_name = mic_user_name.strip() or self.mic_user_id
        self.mic_seconds = max(0.25, float(mic_seconds))
        self.mic_sample_rate = max(8000, int(mic_sample_rate or 16000))
        self.mic_device = str(mic_device or "").strip()
        self.route_protected_mic_speech = bool(route_protected_mic_speech)
        self.mic_dir = Path(os.environ.get("NC_DISCORD_BRIDGE_CAPTURE_DIR") or (Path(__file__).resolve().parent / "mic_captures")).resolve()
        self.settings_path = optional_path(os.environ.get("NC_DISCORD_BRIDGE_SETTINGS_JSON", ""))
        self.status_path = optional_path(os.environ.get("NC_DISCORD_BRIDGE_STATUS_JSON", ""))
        self.command_path = optional_path(os.environ.get("NC_DISCORD_BRIDGE_COMMAND_JSONL", ""))
        self.bridge_token = str(os.environ.get("NC_DISCORD_BRIDGE_TOKEN") or "").strip()
        self.last_flow_index = 0
        self.latest_speech: SpeechMemory | None = None
        self.processed_routes: set[int] = set()
        self.last_transcript = ""
        self.last_error = ""
        self.last_route_decision: dict[str, Any] = {}
        self.render_ready_chunks = 0
        self.render_total_chunks = 0
        self.playback_completed_chunks = 0
        self.playback_total_chunks = 0
        self.microphone_thread_started = False
        self.turn_cancel_epoch = 0
        self.active_turn_id = ""
        self._delivered_reply_lock = threading.Lock()
        self._delivered_reply_parts: list[str] = []
        self._delivered_reply_participants: list[dict[str, Any]] = []
        self._delivered_reply_published = False
        self.moderator_state: dict[str, Any] = {
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
            "route_flow": [],
            "updated_at_ms": now_ms(),
        }

    def run(self) -> None:
        self.register()
        print(f"[TinyBridge:{self.bot_id}] connected to {self.tiny_url}")
        print(f"[TinyBridge:{self.bot_id}] NC turn endpoint {self.nc_turn_url}")
        while True:
            try:
                self.poll_once()
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                self.last_error = str(exc)
                print(f"[TinyBridge:{self.bot_id}] poll error: {exc}")
                self.write_status("poll_error")
            time.sleep(self.poll_seconds)

    def register(self) -> None:
        self.post_json(
            f"{self.tiny_url}/participants/upsert",
            {"id": self.bot_id, "name": self.bot_name, "type": "bot", "connected": True},
        )
        self.write_status("connected")

    def poll_once(self) -> None:
        self.process_commands()
        state = self.get_json(f"{self.tiny_url}/state")
        self.maybe_start_microphone_thread(state)
        participants = list(state.get("participants") or [])
        names = {str(item.get("id") or ""): str(item.get("name") or item.get("id") or "") for item in participants}
        for event in state.get("route_flow", []):
            index = int_or_zero(event.get("index"))
            if index <= self.last_flow_index:
                continue
            self.last_flow_index = max(self.last_flow_index, index)
            event_type = str(event.get("type") or "")
            source_id = str(event.get("source_id") or "")
            target_id = str(event.get("target_id") or "")
            effective_target_id = source_id if event_type == "current" and not target_id else target_id
            message = str(event.get("message") or "")
            if event_type == "speech":
                self.latest_speech = SpeechMemory(
                    index=index,
                    source_id=source_id,
                    speaker_name=names.get(source_id, source_id),
                    text=self.extract_speech_text(message),
                )
                self.last_transcript = self.latest_speech.text
            if not self.is_routing_event(event_type, message):
                continue
            route_reason = self.route_reason(event_type, source_id, effective_target_id, message, names)
            if effective_target_id == self.bot_id:
                self.last_route_decision = {
                    "answer": True,
                    "target_bot_id": self.bot_id,
                    "reason": route_reason,
                    "source_id": source_id,
                }
                self.handle_routed_event(index, event_type, source_id, message, participants)
            elif effective_target_id:
                self.last_route_decision = {
                    "answer": False,
                    "target_bot_id": effective_target_id,
                    "reason": route_reason,
                    "source_id": source_id,
                }
        self.sync_moderator_state_from_room(state)
        self.write_status("connected", state)

    def maybe_start_microphone_thread(self, state: dict[str, Any]) -> None:
        if not self.capture_mic or self.microphone_thread_started:
            return
        if not os.isatty(0):
            return
        capture_owner_id = safe_id(state.get("capture_owner_id") or "")
        if capture_owner_id != self.bot_id:
            return
        self.start_microphone_thread()

    def start_microphone_thread(self) -> None:
        self.microphone_thread_started = True
        thread = threading.Thread(target=self.microphone_loop, name=f"TinyMVP mic {self.mic_user_id}", daemon=True)
        thread.start()

    def microphone_loop(self) -> None:
        print(
            f"[TinyBridge:{self.bot_id}] microphone input enabled for {self.mic_user_name}; this bot is TinyMVP capture owner. "
            f"Press Enter to record {self.mic_seconds:.1f}s, or Ctrl+C to stop."
        )
        while True:
            try:
                input()
                if not self.is_capture_owner():
                    print(f"[TinyBridge:{self.bot_id}] microphone ignored; this bot is no longer capture owner.")
                    continue
                wav_path = self.record_microphone_wav()
                self.submit_microphone_wav(wav_path)
            except EOFError:
                return
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                self.last_error = f"microphone failed: {exc}"
                print(f"[TinyBridge:{self.bot_id}] {self.last_error}")
            self.write_status("mic_error")

    def is_capture_owner(self) -> bool:
        try:
            state = self.get_json(f"{self.tiny_url}/state")
        except Exception:
            return False
        return safe_id(state.get("capture_owner_id") or "") == self.bot_id

    def record_microphone_wav(self) -> Path:
        try:
            import sounddevice as sd  # type: ignore[import-not-found]
        except Exception as exc:
            raise RuntimeError("microphone capture needs the optional 'sounddevice' Python package") from exc

        self.mic_dir.mkdir(parents=True, exist_ok=True)
        wav_path = self.mic_dir / f"mic_{self.mic_user_id}_{int(time.time() * 1000)}.wav"
        chunks: list[bytes] = []

        def callback(indata, _frames, _time_info, status) -> None:
            if status:
                print(f"[TinyBridge:{self.bot_id}] microphone status: {status}")
            chunks.append(bytes(indata))

        device = self.mic_device or None
        print(f"[TinyBridge:{self.bot_id}] recording microphone for {self.mic_seconds:.1f}s...")
        with sd.RawInputStream(
            samplerate=self.mic_sample_rate,
            channels=1,
            dtype="int16",
            device=device,
            callback=callback,
        ):
            time.sleep(self.mic_seconds)
        with wave.open(str(wav_path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(self.mic_sample_rate)
            handle.writeframes(b"".join(chunks))
        print(f"[TinyBridge:{self.bot_id}] microphone WAV captured: {wav_path}")
        return wav_path

    def submit_microphone_wav(self, wav_path: Path) -> None:
        state = self.get_json(f"{self.tiny_url}/state")
        participants = list(state.get("participants") or [])
        route_key = f"tinymvp_mic_{self.mic_user_id}_{int(time.time() * 1000)}"
        if self.participant_is_muted(state, self.mic_user_id):
            self.post_json(
                f"{self.tiny_url}/decision",
                {
                    "source_id": self.mic_user_id,
                    "target_id": "",
                    "answer": False,
                    "reason": "muted_speaker",
                },
            )
            print(f"[TinyBridge:{self.bot_id}] microphone ignored; {self.mic_user_name} is muted.")
            self.write_status("mic_muted", state)
            return
        if self.current_speaker_blocks_user(state, self.mic_user_id) and not self.route_protected_mic_speech:
            self.post_json(
                f"{self.tiny_url}/decision",
                {
                    "source_id": self.mic_user_id,
                    "target_id": "",
                    "answer": False,
                    "reason": "current_speaker_protected",
                },
            )
            print(f"[TinyBridge:{self.bot_id}] microphone ignored; current speaker is protected.")
            self.write_status("mic_current_protected", state)
            return
        protected_current_speech = self.current_speaker_blocks_user(state, self.mic_user_id)
        payload = {
            "route_key": route_key,
            "user_id": self.mic_user_id,
            "speaker_name": self.mic_user_name,
            "captured_at": datetime.now().isoformat(timespec="seconds"),
            "wav_path": str(wav_path),
            "duration_seconds": wav_duration_seconds(str(wav_path)) or self.mic_seconds,
            "participants": participants,
            "room_context": self.room_context(participants),
            "record_route_context": bool(protected_current_speech and self.route_protected_mic_speech),
        }
        decision = self.post_json_to_nc(self.nc_route_url(), payload)
        self.last_route_decision = dict(decision)
        input_text = str(decision.get("input_text") or "").strip()
        if input_text:
            self.last_transcript = input_text
            self.post_json(
                f"{self.tiny_url}/speech",
                {"speaker_id": self.mic_user_id, "text": input_text, "reason": "microphone"},
            )
        target_id = safe_id(decision.get("target_bot_id") or "")
        reason = str(decision.get("reason") or "microphone route").strip()
        if bool(decision.get("answer")) and target_id:
            try:
                fresh_state = self.get_json(f"{self.tiny_url}/state")
            except Exception:
                fresh_state = {}
            if self.should_preserve_existing_next(fresh_state, self.mic_user_id):
                queued_next = safe_id(fresh_state.get("next_id") or "")
                preserve_reason = f"manual next already queued: {queued_next}"
                self.post_json(
                    f"{self.tiny_url}/decision",
                    {
                        "source_id": self.mic_user_id,
                        "target_id": queued_next,
                        "answer": False,
                        "reason": preserve_reason,
                    },
                )
                print(f"[TinyBridge:{self.bot_id}] microphone route skipped; {preserve_reason}")
                return
            self.post_json(f"{self.tiny_url}/route", {"target_id": target_id, "reason": reason})
            print(f"[TinyBridge:{self.bot_id}] microphone routed {self.mic_user_name} -> {target_id}: {reason}")
        else:
            self.post_json(
                f"{self.tiny_url}/decision",
                {
                    "source_id": self.mic_user_id,
                    "target_id": target_id,
                    "answer": False,
                    "reason": reason,
                },
            )
            print(f"[TinyBridge:{self.bot_id}] microphone no-route: {reason}")
        if input_text:
            self.broadcast_room_turn_to_histories(
                input_text,
                speaker_name=self.mic_user_name,
                source_id=self.mic_user_id,
                participants=participants,
                route_key=route_key,
                selected_target_id=target_id if bool(decision.get("answer")) else "",
            )
        self.write_status("mic_route", state)

    def process_commands(self) -> None:
        if self.command_path is None:
            return
        try:
            text = self.command_path.read_text(encoding="utf-8")
            self.command_path.unlink(missing_ok=True)
        except FileNotFoundError:
            return
        except Exception as exc:
            self.last_error = f"command read failed: {exc}"
            self.write_status("command_error")
            return
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                command = json.loads(line)
            except Exception as exc:
                self.last_error = f"bad command json: {exc}"
                continue
            self.handle_command(command)

    def handle_command(self, command: dict[str, Any]) -> None:
        action = str(command.get("action") or "").strip().lower()
        payload = command.get("payload") if isinstance(command.get("payload"), dict) else {}
        print(f"[TinyBridge:{self.bot_id}] command: {action}")
        if action in {"stop_speech", "clear_queue"}:
            self.cancel_active_turn(action)
            result = self.post_json(f"{self.tiny_url}/stop", {"reason": action})
            state = result.get("state") if isinstance(result, dict) else {}
            if isinstance(state, dict):
                self.sync_moderator_state_from_room(state)
            self.write_status("moderator_updated", state if isinstance(state, dict) else None)
            return
        if action == "reset_context":
            self.processed_routes.clear()
            self.latest_speech = None
            self.last_transcript = ""
            result = self.post_json(f"{self.tiny_url}/reset", {"reason": "reset_context"})
            state = result.get("state") if isinstance(result, dict) else {}
            if isinstance(state, dict):
                self.sync_moderator_state_from_room(state)
            self.update_moderator(last_command="reset_context")
            return
        if action == "disconnect":
            result = self.post_json(f"{self.tiny_url}/participants/disconnect", {"id": self.bot_id})
            state = result.get("state") if isinstance(result, dict) else {}
            if isinstance(state, dict):
                self.sync_moderator_state_from_room(state)
            self.write_status("disconnected", state if isinstance(state, dict) else None)
            return
        if action == "reconnect":
            result = self.post_json(f"{self.tiny_url}/participants/connect", {"id": self.bot_id})
            state = result.get("state") if isinstance(result, dict) else {}
            if isinstance(state, dict):
                self.sync_moderator_state_from_room(state)
            self.write_status("connected", state if isinstance(state, dict) else None)
            return
        if action == "reload_settings":
            self.update_moderator(last_command="reload_settings")
            return
        if action == "send_message":
            text = str(payload.get("text") or payload.get("message") or "").strip()
            if text:
                if payload.get("moderator_announcement"):
                    self.speak_text_direct(text)
                else:
                    participants = list(self.get_json(f"{self.tiny_url}/state").get("participants") or [])
                    self.send_turn_to_nc(text, "TinyMVP", "tinymvp", participants, manual_call_on=True)
            return
        if action == "tiny_mvp_record_mic":
            if not self.is_capture_owner():
                print(f"[TinyBridge:{self.bot_id}] microphone command ignored; this bot is not capture owner.")
                return
            wav_path = self.record_microphone_wav()
            self.submit_microphone_wav(wav_path)
            return
        if action == "moderator_call_on":
            target = safe_id(payload.get("target_bot_id") or payload.get("bot_id") or self.bot_id)
            if target and target != self.bot_id:
                return
            result = self.post_json(f"{self.tiny_url}/call", {"target_id": self.bot_id, "reason": "human moderator call on target"})
            state = result.get("state") if isinstance(result, dict) else {}
            if isinstance(state, dict):
                self.sync_moderator_state_from_room(state)
            self.write_status("moderator_updated", state if isinstance(state, dict) else None)
            return
        if action.startswith("moderator_"):
            self.handle_moderator_command(action, payload)

    def handle_moderator_command(self, action: str, payload: dict[str, Any]) -> None:
        target = safe_id(payload.get("target_bot_id") or payload.get("bot_id") or "")
        speaker_user_id = str(payload.get("speaker_user_id") or payload.get("user_id") or "").strip()
        speaker_name = str(payload.get("speaker_name") or speaker_user_id).strip()
        if action in {
            "moderator_route_next",
            "moderator_give_floor",
            "moderator_route_next_human",
            "moderator_give_human_floor",
            "moderator_mute",
            "moderator_unmute",
            "moderator_mute_human",
            "moderator_unmute_human",
            "moderator_mute_all_except",
            "moderator_clear_pending",
            "moderator_clear_floor",
            "moderator_clear",
            "moderator_set_current_interruption",
            "moderator_set_enforcer",
            "moderator_clear_enforcer",
            "moderator_set_mute_enforcement",
        }:
            command_payload = dict(payload)
            command_payload["action"] = action
            if target:
                command_payload["target_bot_id"] = target
            if speaker_user_id:
                command_payload["speaker_user_id"] = speaker_user_id
                command_payload["speaker_name"] = speaker_name
            result = self.post_json(f"{self.tiny_url}/moderator", command_payload)
            state = result.get("state") if isinstance(result, dict) else {}
            if isinstance(state, dict):
                self.sync_moderator_state_from_room(state)
            self.write_status("moderator_updated", state if isinstance(state, dict) else None)
            return

    def sync_moderator_state_from_room(self, state: dict[str, Any]) -> None:
        participants = list(state.get("participants") or [])
        by_id = {str(item.get("id") or ""): item for item in participants if isinstance(item, dict)}
        shared_moderator = state.get("moderator_state")
        if isinstance(shared_moderator, dict):
            self.moderator_state.update(dict(shared_moderator))
        current_id = str(state.get("current_id") or "").strip()
        next_id = str(state.get("next_id") or "").strip()
        current = by_id.get(current_id, {})
        nxt = by_id.get(next_id, {})
        if current_id and str(current.get("kind") or "") == "human":
            self.moderator_state.update({
                "current_human_route": {"speaker_user_id": current_id, "speaker_name": str(current.get("name") or current_id), "reason": "tinymvp current"},
                "current_speaker_user_id": current_id,
                "current_speaker_name": str(current.get("name") or current_id),
                "current_bot_id": "",
                "current_bot_name": "",
            })
        elif current_id:
            self.moderator_state.update({
                "current_bot_id": current_id,
                "current_bot_name": str(current.get("name") or current_id),
                "current_human_route": {},
                "current_speaker_user_id": "",
                "current_speaker_name": "",
            })
        if next_id and str(nxt.get("kind") or "") == "human":
            self.moderator_state.update({
                "pending_human_route": {"speaker_user_id": next_id, "speaker_name": str(nxt.get("name") or next_id), "reason": "tinymvp next"},
                "route_next_speaker_user_id": next_id,
                "route_next_speaker_name": str(nxt.get("name") or next_id),
                "pending_route": {},
                "route_next_target_bot_id": "",
            })
        elif next_id:
            self.moderator_state.update({
                "pending_route": {"target_bot_id": next_id, "reason": "tinymvp next", "created_at_ms": now_ms()},
                "route_next_target_bot_id": next_id,
                "pending_human_route": {},
                "route_next_speaker_user_id": "",
                "route_next_speaker_name": "",
            })
        self.moderator_state["route_flow"] = [
            {
                "captured_at": str(item.get("time") or ""),
                "speaker_name": participant_name(by_id, str(item.get("source_id") or "")) or str(item.get("source_id") or "Room"),
                "source_name": participant_name(by_id, str(item.get("source_id") or "")) or str(item.get("source_id") or "Room"),
                "speaker_bot_id": str(item.get("source_id") or ""),
                "target_bot_id": str(item.get("target_id") or ""),
                "target_name": participant_name(by_id, str(item.get("target_id") or "")) or str(item.get("target_id") or "no route"),
                "answer": bool(str(item.get("target_id") or "").strip()),
                "source": str(item.get("type") or "tinymvp"),
                "kind": str(item.get("type") or "tinymvp"),
                "reason": str(item.get("message") or ""),
            }
            for item in state.get("route_flow", [])[-24:]
            if isinstance(item, dict)
        ]
        self.moderator_state["updated_at_ms"] = now_ms()

    def update_moderator(self, **updates: Any) -> None:
        self.moderator_state.update(updates)
        self.moderator_state["last_error"] = ""
        self.moderator_state["updated_at_ms"] = now_ms()
        self.write_status("moderator_updated")

    def write_status(self, state_text: str, state: dict[str, Any] | None = None) -> None:
        if self.status_path is None:
            return
        room_available = True
        try:
            room_state = state if isinstance(state, dict) else self.get_json(f"{self.tiny_url}/state")
        except Exception:
            room_available = False
            room_state = {}
        participants = list(room_state.get("participants") or [])
        current_id = str(room_state.get("current_id") or "").strip()
        playback_owner = str(room_state.get("playback_owner_id") or "").strip()
        capture_owner = str(room_state.get("capture_owner_id") or "").strip()
        own = next((item for item in participants if str(item.get("id") or "") == self.bot_id), {})
        playback_owner_item = next((item for item in participants if str(item.get("id") or "") == playback_owner), {})
        capture_owner_item = next((item for item in participants if str(item.get("id") or "") == capture_owner), {})
        playback_owner_name = str(playback_owner_item.get("name") or playback_owner).strip() if isinstance(playback_owner_item, dict) else playback_owner
        capture_owner_name = str(capture_owner_item.get("name") or capture_owner).strip() if isinstance(capture_owner_item, dict) else capture_owner
        capture_owner_label = f"{capture_owner_name} ({capture_owner})" if capture_owner else ""
        if not room_available:
            self.moderator_state.update(
                {
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
                    "route_flow": [],
                    "last_error": self.last_error,
                    "updated_at_ms": now_ms(),
                }
            )
        status = {
            "state": "connected" if room_available and bool(own.get("connected", True)) else "disconnected",
            "bot_tag": self.bot_name,
            "bot_name": self.bot_name,
            "bot_id": self.bot_id,
            "guild_name": "TinyMVP",
            "voice_channel_name": "TinyMVP local room",
            "speaking": room_available and playback_owner == self.bot_id,
            "local_speaking": room_available and playback_owner == self.bot_id,
            "listening": room_available and str(room_state.get("capture_owner_id") or "") == self.bot_id,
            "reply_floor_owner": playback_owner,
            "reply_floor_owner_bot": playback_owner_name,
            "owns_reply_floor": room_available and playback_owner == self.bot_id,
            "capture_owner_enabled": True,
            "capture_owner": capture_owner_label,
            "owns_capture": room_available and capture_owner == self.bot_id,
            "active_captures": 1 if room_available and capture_owner == self.bot_id else 0,
            "queued_audio": int(own.get("queued_audio") or 0) if isinstance(own, dict) else 0,
            "active_turn_id": str(self.active_turn_id or ""),
            "last_transcript": self.last_transcript,
            "last_error": self.last_error,
            "last_route_decision": self.last_route_decision,
            "moderator_state": self.moderator_state,
            "participants": [
                {
                    "id": str(item.get("id") or ""),
                    "name": str(item.get("name") or item.get("id") or ""),
                    "is_bot": str(item.get("kind") or "") == "bot",
                    "connected": bool(item.get("connected")),
                    "current": bool(item.get("current")),
                    "next": bool(item.get("next")),
                }
                for item in participants
                if isinstance(item, dict)
            ],
            "render_ready_chunks": self.render_ready_chunks,
            "render_total_chunks": self.render_total_chunks,
            "playback_completed_chunks": self.playback_completed_chunks,
            "playback_total_chunks": self.playback_total_chunks,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "bridge_mode": "tiny_mvp",
            "transport": "tinymvp",
            "event": state_text,
        }
        try:
            self.status_path.parent.mkdir(parents=True, exist_ok=True)
            self.status_path.write_text(json.dumps(status, indent=2), encoding="utf-8")
        except Exception as exc:
            print(f"[TinyBridge:{self.bot_id}] status write failed: {exc}")

    def handle_routed_event(self, index: int, event_type: str, source_id: str, message: str, participants: list[dict[str, Any]]) -> None:
        if index in self.processed_routes:
            return
        self.processed_routes.add(index)
        speech = self.latest_speech
        if speech and speech.source_id == self.bot_id and safe_id(source_id) == self.bot_id:
            print(f"[TinyBridge:{self.bot_id}] ignoring self-route from latest speech.")
            return
        if speech and speech.text and (not source_id or safe_id(speech.source_id) == safe_id(source_id)):
            input_text = speech.text
            speaker_name = speech.speaker_name
            user_id = speech.source_id
            manual_call_on = False
        else:
            source = next(
                (
                    item
                    for item in participants
                    if isinstance(item, dict) and safe_id(item.get("id") or "") == safe_id(source_id)
                ),
                {},
            )
            input_text = (
                "Continue the current room conversation from your perspective. Respond to the latest relevant thing "
                "in the room context or your conversation history. Do not mention hidden routing, moderator controls, "
                "or system mechanics."
            )
            speaker_name = str(source.get("name") or source_id or "Room")
            user_id = source_id or "room"
            manual_call_on = True
        print(f"[TinyBridge:{self.bot_id}] routed event #{index} ({event_type}): {speaker_name} -> {self.bot_name}")
        self.send_turn_to_nc(input_text, speaker_name, user_id, participants, manual_call_on=manual_call_on, route_index=index)

    def send_turn_to_nc(
        self,
        input_text: str,
        speaker_name: str,
        user_id: str,
        participants: list[dict[str, Any]],
        *,
        manual_call_on: bool = False,
        route_index: int = 0,
    ) -> None:
        turn_id = f"tinymvp_{self.bot_id}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
        payload = {
            "turn_id": turn_id,
            "user_id": user_id,
            "speaker_name": speaker_name,
            "captured_at": datetime.now().isoformat(timespec="seconds"),
            "input_text": input_text,
            "duration_seconds": 1.0,
            "participants": participants,
            "room_context": self.room_context(participants),
            "room_router_selected": True,
            "node_reply_floor_managed": True,
            "manual_call_on": manual_call_on,
        }
        reply_parts: list[str] = []
        playback_queue: queue.Queue[tuple[str, str] | None] = queue.Queue()
        playback_failed = {"failed": False}
        cancel_epoch = self.turn_cancel_epoch
        room_playback_epoch = self.room_playback_epoch()
        expected_route_target = self.bot_id if not manual_call_on else ""
        self.active_turn_id = turn_id
        self.reset_delivered_reply_state(participants)
        self.render_ready_chunks = 0
        self.render_total_chunks = 0
        self.playback_completed_chunks = 0
        self.playback_total_chunks = 0
        playback_thread = threading.Thread(
            target=self.playback_queue_worker,
            args=(playback_queue, playback_failed, cancel_epoch, expected_route_target, route_index),
            name=f"TinyMVP playback {self.bot_id}",
            daemon=True,
        )
        playback_thread.start()
        self.write_status("turn_started")
        cancelled = False
        completed_reply_text = ""
        routed_completed_text = False
        try:
            for event in self.post_ndjson(self.nc_turn_url, payload):
                self.process_commands()
                if (
                    self.is_turn_cancelled(cancel_epoch)
                    or self.is_room_playback_stale(room_playback_epoch)
                    or self.is_route_target_replaced(expected_route_target, route_index=route_index)
                ):
                    cancelled = True
                    self.cancel_active_turn("local stop, clear command, playback epoch change, or route replacement")
                    self.write_status("turn_cancelled")
                    break
                event_type = str(event.get("type") or "")
                if event_type == "transcript":
                    self.last_transcript = str(event.get("input_text") or input_text or "")
                    print(f"[TinyBridge:{self.bot_id}] NC transcript accepted: {self.last_transcript[:120]}")
                elif event_type == "audio_chunk":
                    if (
                        self.is_turn_cancelled(cancel_epoch)
                        or self.is_room_playback_stale(room_playback_epoch)
                        or self.is_route_target_replaced(expected_route_target, route_index=route_index)
                    ):
                        cancelled = True
                        self.cancel_active_turn("local stop, clear command, playback epoch change, or route replacement")
                        self.write_status("turn_cancelled")
                        break
                    wav_path = str(event.get("reply_wav_path") or "")
                    text = str(event.get("reply_text") or "")
                    if text:
                        reply_parts.append(text)
                    if wav_path:
                        self.render_ready_chunks += 1
                        self.render_total_chunks = max(self.render_total_chunks, self.render_ready_chunks)
                        self.playback_total_chunks += 1
                        playback_queue.put((wav_path, text))
                        self.write_status("audio_chunk_queued")
                elif event_type == "done":
                    if (
                        self.is_turn_cancelled(cancel_epoch)
                        or self.is_room_playback_stale(room_playback_epoch)
                        or self.is_route_target_replaced(expected_route_target, route_index=route_index)
                    ):
                        cancelled = True
                        self.write_status("turn_cancelled")
                        break
                    completed_reply_text = str(event.get("reply_text") or " ".join(reply_parts)).strip()
                    if completed_reply_text and self.is_current_or_playback_speaker():
                        self.route_completed_reply_text(completed_reply_text, participants, broadcast_history=False)
                        routed_completed_text = True
                    print(f"[TinyBridge:{self.bot_id}] NC reply complete.")
                elif event_type in {"skipped", "cancelled", "error"}:
                    print(f"[TinyBridge:{self.bot_id}] NC {event_type}: {event}")
        finally:
            playback_queue.put(None)
            join_deadline = time.time() + 900.0
            while playback_thread.is_alive() and time.time() < join_deadline:
                if completed_reply_text and not routed_completed_text and self.is_current_or_playback_speaker():
                    self.route_completed_reply_text(
                        completed_reply_text,
                        participants,
                        broadcast_history=False,
                    )
                    routed_completed_text = True
                playback_thread.join(timeout=0.1)
            if self.active_turn_id == turn_id:
                self.active_turn_id = ""
        if cancelled or playback_failed.get("failed"):
            self.publish_delivered_reply_once(route=False)
            return
        if completed_reply_text:
            self.finish_nc_turn(turn_id)
            self.publish_delivered_reply_once(route=not routed_completed_text)
        self.post_json(f"{self.tiny_url}/stop", {"reason": f"{self.bot_id} turn finished"})
        self.write_status("turn_finished")

    def publish_and_route_completed_reply(self, reply_text: str, participants: list[dict[str, Any]]) -> None:
        self.post_completed_reply_speech(reply_text)
        self.route_completed_reply_text(reply_text, participants)

    def reset_delivered_reply_state(self, participants: list[dict[str, Any]]) -> None:
        with self._delivered_reply_lock:
            self._delivered_reply_parts = []
            self._delivered_reply_participants = [
                dict(item)
                for item in participants
                if isinstance(item, dict)
            ]
            self._delivered_reply_published = False

    def delivered_reply_text(self) -> str:
        with self._delivered_reply_lock:
            return " ".join(part for part in self._delivered_reply_parts if part).strip()

    def mark_reply_chunk_delivered(self, chunk_text: str) -> None:
        text = str(chunk_text or "").strip()
        if not text:
            return
        with self._delivered_reply_lock:
            self._delivered_reply_parts.append(text)

    def publish_delivered_reply_once(self, *, route: bool) -> str:
        with self._delivered_reply_lock:
            if self._delivered_reply_published:
                return ""
            text = " ".join(part for part in self._delivered_reply_parts if part).strip()
            participants = [dict(item) for item in self._delivered_reply_participants]
            self._delivered_reply_published = bool(text)
        if not text:
            return ""
        self.post_completed_reply_speech(text)
        if route:
            self.route_completed_reply_text(text, participants)
        else:
            route_key = f"tinymvp_cancelled_bot_text_{self.bot_id}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
            self.broadcast_room_turn_to_histories(
                text,
                speaker_name=self.bot_name,
                source_id=self.bot_id,
                participants=participants,
                route_key=route_key,
                selected_target_id="",
            )
        return text

    def post_completed_reply_speech(self, reply_text: str) -> None:
        self.post_json(
            f"{self.tiny_url}/speech",
            {"speaker_id": self.bot_id, "text": reply_text, "reason": "nc_reply_complete"},
        )

    def route_completed_reply_text(
        self,
        reply_text: str,
        participants: list[dict[str, Any]],
        *,
        broadcast_history: bool = True,
    ) -> None:
        text = str(reply_text or "").strip()
        if not text:
            return
        try:
            state = self.get_json(f"{self.tiny_url}/state")
        except Exception:
            state = {}
        queued_next = safe_id(state.get("next_id") or "")
        if self.should_preserve_existing_next(state, self.bot_id):
            reason = f"manual next already queued: {queued_next}"
            self.last_route_decision = {
                "answer": False,
                "target_bot_id": queued_next,
                "reason": reason,
                "source_id": self.bot_id,
            }
            print(f"[TinyBridge:{self.bot_id}] skipping LLM route; {reason}")
            self.write_status("manual_next_preserved")
            return
        route_key = f"tinymvp_bot_text_{self.bot_id}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
        payload = {
            "route_key": route_key,
            "user_id": self.bot_id,
            "speaker_name": self.bot_name,
            "captured_at": datetime.now().isoformat(timespec="seconds"),
            "input_text": text,
            "duration_seconds": 1.0,
            "participants": participants,
            "room_context": self.room_context(participants),
        }
        try:
            decision = self.post_json_to_nc(self.nc_route_url(), payload)
        except Exception as exc:
            self.last_error = f"bot-text route failed: {exc}"
            self.write_status("route_error")
            print(f"[TinyBridge:{self.bot_id}] {self.last_error}")
            return
        self.last_route_decision = dict(decision)
        target_id = safe_id(decision.get("target_bot_id") or "")
        reason = str(decision.get("reason") or "bot text route").strip()
        if bool(decision.get("answer")) and target_id == self.bot_id:
            reason = f"self_route:{reason}"
            target_id = ""
        if broadcast_history:
            self.broadcast_room_turn_to_histories(
                text,
                speaker_name=self.bot_name,
                source_id=self.bot_id,
                participants=participants,
                route_key=route_key,
                selected_target_id=target_id if bool(decision.get("answer")) else "",
            )
        if bool(decision.get("answer")) and target_id:
            self.post_json(f"{self.tiny_url}/route", {"target_id": target_id, "reason": reason})
            print(f"[TinyBridge:{self.bot_id}] bot text routed {self.bot_name} -> {target_id}: {reason}")
        else:
            self.post_json(
                f"{self.tiny_url}/decision",
                {
                    "source_id": self.bot_id,
                    "target_id": target_id,
                    "answer": False,
                    "reason": reason,
                },
            )
            self.maybe_recover_dead_air(reason)
            print(f"[TinyBridge:{self.bot_id}] bot text no-route: {reason}")
        self.write_status("route_decision")

    def broadcast_room_turn_to_histories(
        self,
        input_text: str,
        *,
        speaker_name: str,
        source_id: str,
        participants: list[dict[str, Any]],
        route_key: str,
        selected_target_id: str = "",
    ) -> None:
        text = str(input_text or "").strip()
        if not text:
            return
        source = safe_id(source_id)
        selected = safe_id(selected_target_id)
        participant_ids = {
            safe_id(item.get("id") or "")
            for item in participants
            if isinstance(item, dict)
            and safe_id(item.get("id") or "")
            and str(item.get("kind") or "").strip().lower() == "bot"
            and bool(item.get("connected", True))
        }
        endpoint_by_id = self._runtime_history_endpoints()
        recorded = 0
        skipped = 0
        for candidate_id in sorted(participant_ids):
            if candidate_id == source:
                skipped += 1
                continue
            endpoint = endpoint_by_id.get(candidate_id)
            if not endpoint:
                skipped += 1
                continue
            try:
                result = self.post_json_to_nc(
                    endpoint,
                    {
                        "route_key": f"{route_key}:history:{candidate_id}",
                        "input_text": text,
                        "speaker_name": str(speaker_name or source_id or "").strip(),
                        "user_id": source_id,
                        "captured_at": datetime.now().isoformat(timespec="seconds"),
                        "source_bot_id": self.bot_id,
                        "speaker_bot_id": source if source in participant_ids else "",
                        "target_bot_id": selected,
                        "record_only": True,
                    },
                )
                if bool(result.get("recorded")):
                    recorded += 1
                else:
                    skipped += 1
            except Exception as exc:
                skipped += 1
                print(f"[TinyBridge:{self.bot_id}] room history broadcast failed for {candidate_id}: {exc}")
        if recorded or skipped:
            print(f"[TinyBridge:{self.bot_id}] broadcast room turn to bot histories: recorded={recorded}, skipped={skipped}")

    def _runtime_history_endpoints(self) -> dict[str, str]:
        endpoints: dict[str, str] = {}
        settings = self.bridge_settings()
        router = settings.get("room_router") if isinstance(settings.get("room_router"), dict) else {}
        candidates = router.get("candidate_bots") if isinstance(router.get("candidate_bots"), list) else []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            candidate_id = safe_id(candidate.get("id") or candidate.get("name") or "")
            if not candidate_id:
                continue
            endpoint = self._record_user_turn_endpoint(candidate)
            if endpoint:
                endpoints[candidate_id] = endpoint
        endpoints.setdefault(self.bot_id, self.nc_record_user_turn_url())
        return endpoints

    def _record_user_turn_endpoint(self, candidate: dict[str, Any]) -> str:
        runtime = candidate.get("nc_runtime") if isinstance(candidate.get("nc_runtime"), dict) else {}
        explicit = str(candidate.get("http_endpoint") or runtime.get("http_endpoint") or "").strip()
        if explicit.lower().startswith(("http://", "https://")):
            return explicit.rstrip("/").removesuffix("/turn") + "/record_user_turn"
        host = str(candidate.get("runtime_host") or runtime.get("host") or "127.0.0.1").strip() or "127.0.0.1"
        try:
            port = int(candidate.get("runtime_port") or runtime.get("port") or 0)
        except (TypeError, ValueError):
            port = 0
        if port <= 0:
            return ""
        return f"http://{host}:{port}/record_user_turn"

    def maybe_recover_dead_air(self, reason: str) -> None:
        if not self.dead_air_recovery_for_bot_no_route_enabled():
            return
        silence_timeout = self.dead_air_silence_timeout_seconds()
        payload = self.dead_air_recovery_payload(reason)
        if silence_timeout > 0:
            threading.Thread(
                target=self._recover_dead_air_after_quiet_delay,
                args=(payload, silence_timeout),
                name=f"TinyMVP dead-air recovery {self.bot_id}",
                daemon=True,
            ).start()
            return
        self.post_json(f"{self.tiny_url}/dead-air", payload)

    def dead_air_recovery_payload(self, reason: str) -> dict[str, Any]:
        settings = self.bridge_settings()
        router = settings.get("room_router") if isinstance(settings.get("room_router"), dict) else {}
        recovery = router.get("dead_air_recovery") if isinstance(router.get("dead_air_recovery"), dict) else {}
        strategy = str(recovery.get("next_speaker_strategy") or "llm_choose").strip()
        preferred_target = ""
        if strategy.lower() == "llm_choose":
            preferred_target = self.choose_dead_air_recovery_target(reason)
        return {
            "reason": f"dead_air_recovery:{reason}",
            "source_id": self.bot_id,
            "source_name": self.bot_name,
            "strategy": strategy,
            "fallback_target": str(recovery.get("selected_fallback_target") or "").strip(),
            "preferred_target": preferred_target,
        }

    def choose_dead_air_recovery_target(self, reason: str) -> str:
        try:
            state = self.get_json(f"{self.tiny_url}/state")
        except Exception as exc:
            print(f"[TinyBridge:{self.bot_id}] dead-air LLM choose skipped; room state unavailable: {exc}")
            return ""
        participants = [item for item in state.get("participants", []) if isinstance(item, dict)]
        prompt = (
            "The moderated room reached dead air because the latest completed turn did not select a next speaker. "
            f"Previous speaker: {self.bot_name}. "
            "Choose the single best next room participant, bot or human, to continue the conversation. "
            "Do not choose the previous speaker unless no other eligible participant exists."
        )
        payload = {
            "route_key": f"tinymvp_dead_air_choose_{self.bot_id}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}",
            "user_id": "dead_air_recovery",
            "speaker_name": "Moderator",
            "captured_at": datetime.now().isoformat(timespec="seconds"),
            "input_text": prompt,
            "duration_seconds": 0.0,
            "participants": participants,
            "room_context": self.room_context(participants),
            "dead_air_reason": str(reason or "").strip(),
        }
        try:
            decision = self.post_json_to_nc(self.nc_route_url(), payload)
        except Exception as exc:
            print(f"[TinyBridge:{self.bot_id}] dead-air LLM choose failed: {exc}")
            return ""
        if not bool(decision.get("answer")):
            return ""
        target_id = self.resolve_participant_id(participants, decision.get("target_bot_id") or "")
        if not target_id:
            return ""
        if target_id == self.bot_id and len([item for item in participants if item.get("connected")]) > 1:
            return ""
        return target_id

    @staticmethod
    def resolve_participant_id(participants: list[dict[str, Any]], value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        lowered = text.casefold()
        safe_text = safe_id(text)
        for participant in participants:
            participant_id = str(participant.get("id") or "").strip()
            name = str(participant.get("name") or "").strip()
            if (
                participant_id.casefold() == lowered
                or name.casefold() == lowered
                or safe_id(participant_id) == safe_text
                or safe_id(name) == safe_text
            ):
                return participant_id
        return safe_text

    def dead_air_recovery_for_bot_no_route_enabled(self) -> bool:
        settings = self.bridge_settings()
        if not settings:
            return True
        router = settings.get("room_router") if isinstance(settings.get("room_router"), dict) else {}
        recovery = router.get("dead_air_recovery") if isinstance(router.get("dead_air_recovery"), dict) else {}
        if not as_bool(recovery.get("enabled"), False):
            return False
        trigger_mode = str(recovery.get("trigger_mode") or "no_route_after_bot_speech").strip().lower()
        return trigger_mode in {"no_route_after_bot_speech", "no_route_after_any_speech", "bot_or_human", "any_speech"}

    def dead_air_silence_timeout_seconds(self) -> float:
        settings = self.bridge_settings()
        router = settings.get("room_router") if isinstance(settings.get("room_router"), dict) else {}
        recovery = router.get("dead_air_recovery") if isinstance(router.get("dead_air_recovery"), dict) else {}
        try:
            return max(0.0, float(recovery.get("silence_timeout_seconds", 10.0)))
        except (TypeError, ValueError):
            return 10.0

    def speak_text_direct(self, text: str) -> None:
        clean_text = str(text or "").strip()
        if not clean_text:
            return
        participants: list[dict[str, Any]] = []
        try:
            participants = list(self.get_json(f"{self.tiny_url}/state").get("participants") or [])
        except Exception:
            participants = []
        turn_id = f"tinymvp_manual_{self.bot_id}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
        self.active_turn_id = turn_id
        self.render_ready_chunks = 0
        self.render_total_chunks = 0
        self.playback_completed_chunks = 0
        self.playback_total_chunks = 0
        cancel_epoch = self.turn_cancel_epoch
        room_playback_epoch = self.room_playback_epoch()
        self.write_status("manual_speak")
        result = self.post_json_to_nc(self.nc_speak_url(), {"turn_id": turn_id, "text": clean_text})
        if not result.get("ok"):
            self.last_error = str(result.get("error") or result.get("reason") or "manual speak failed")
            self.write_status("manual_speak_failed")
            return
        raw_chunks = result.get("reply_chunks") if isinstance(result.get("reply_chunks"), list) else []
        chunks = [item for item in raw_chunks if isinstance(item, dict)]
        if not chunks:
            chunks = [dict(result)]
        reply_text = str(result.get("reply_text") or clean_text).strip()
        self.render_total_chunks = len(chunks)
        self.playback_total_chunks = len(chunks)
        played_any = False
        for item in chunks:
            wav_path = str(item.get("reply_wav_path") or "").strip()
            if not wav_path:
                continue
            self.render_ready_chunks += 1
            self.write_status("manual_speak_chunk")
            if not self.play_wav_chunk(wav_path, playback_epoch=room_playback_epoch, cancel_epoch=cancel_epoch):
                break
            played_any = True
        if played_any:
            self.post_completed_reply_speech(reply_text)
            self.post_json(f"{self.tiny_url}/stop", {"reason": f"{self.bot_id} direct speak finished"})
            self.route_completed_reply_text(reply_text, participants)
            self.write_status("manual_speak_done")

    def _recover_dead_air_after_quiet_delay(self, payload: dict[str, Any], silence_timeout: float) -> None:
        timeout = max(0.0, float(silence_timeout))
        poll_interval = min(0.25, max(0.02, timeout / 2.0 if timeout else 0.02))
        deadline = time.time() + max(30.0, timeout + 5.0)
        quiet_since: float | None = None
        while time.time() < deadline:
            try:
                state = self.get_json(f"{self.tiny_url}/state")
            except Exception:
                return
            if self.room_has_active_or_pending_speaker(state):
                quiet_since = None
                time.sleep(poll_interval)
                continue
            now = time.time()
            if quiet_since is None:
                quiet_since = now
            if now - quiet_since >= timeout:
                self.post_json(f"{self.tiny_url}/dead-air", payload)
                return
            time.sleep(poll_interval)

    @staticmethod
    def room_has_active_or_pending_speaker(state: dict[str, Any]) -> bool:
        return bool(
            safe_id(state.get("current_id") or "")
            or safe_id(state.get("next_id") or "")
            or safe_id(state.get("playback_owner_id") or "")
        )

    def bridge_settings(self) -> dict[str, Any]:
        if not self.settings_path:
            return {}
        try:
            return json.loads(self.settings_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def wait_for_playback_floor(
        self,
        timeout_seconds: float = 600.0,
        *,
        expected_epoch: int | None = None,
        cancel_epoch: int | None = None,
        expected_route_target: str = "",
        route_index: int = 0,
    ) -> dict[str, Any] | None:
        deadline = time.time() + max(1.0, float(timeout_seconds))
        self.write_status("waiting_playback_floor")
        while time.time() < deadline:
            if cancel_epoch is not None and self.is_turn_cancelled(cancel_epoch):
                self.write_status("turn_cancelled")
                return None
            if self.is_route_target_replaced(expected_route_target, route_index=route_index):
                self.write_status("route_replaced")
                return None
            state = self.get_json(f"{self.tiny_url}/state")
            if expected_epoch is not None and self.is_state_playback_stale(state, expected_epoch):
                self.last_error = "TinyMVP playback floor became stale while waiting"
                self.write_status("turn_stale")
                return None
            owner = safe_id(state.get("playback_owner_id") or "")
            if not owner or owner == self.bot_id:
                return state
            time.sleep(0.1)
        return None

    def playback_queue_worker(
        self,
        playback_queue: queue.Queue[tuple[str, str] | None],
        playback_failed: dict[str, bool],
        cancel_epoch: int,
        expected_route_target: str,
        route_index: int = 0,
    ) -> None:
        playback_epoch: int | None = None
        expected_epoch = int_or_zero(self.get_json(f"{self.tiny_url}/state").get("playback_epoch"))
        while True:
            if self.is_turn_cancelled(cancel_epoch) or self.is_route_target_replaced(expected_route_target, route_index=route_index):
                playback_failed["failed"] = True
                self.write_status("turn_cancelled")
                return
            try:
                item = playback_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if item is None:
                return
            wav_path, chunk_text = item
            if playback_epoch is None:
                floor_state = self.wait_for_playback_floor(
                    expected_epoch=expected_epoch,
                    cancel_epoch=cancel_epoch,
                    expected_route_target=expected_route_target,
                    route_index=route_index,
                )
                if floor_state is None:
                    if not self.last_error:
                        self.last_error = "timed out waiting for TinyMVP playback floor"
                        self.write_status("turn_floor_timeout")
                    playback_failed["failed"] = True
                    return
                playback_epoch = int_or_zero(floor_state.get("playback_epoch"))
            if not self.play_wav_chunk(wav_path, playback_epoch=playback_epoch, cancel_epoch=cancel_epoch, chunk_text=chunk_text):
                print(f"[TinyBridge:{self.bot_id}] stopping turn after room rejected playback.")
                self.write_status("turn_stale")
                playback_failed["failed"] = True
                return

    def play_wav_chunk(self, wav_path: str, *, playback_epoch: int, cancel_epoch: int, chunk_text: str = "") -> bool:
        if self.is_turn_cancelled(cancel_epoch) or self.is_room_playback_stale(playback_epoch):
            self.write_status("turn_cancelled")
            return False
        result = self.post_json(
            f"{self.tiny_url}/play",
            {"speaker_id": self.bot_id, "wav_path": wav_path, "playback_epoch": playback_epoch},
        )
        if result.get("ok") is False:
            self.last_error = str(result.get("reason") or result.get("error") or "playback rejected")
            self.write_status("playback_rejected")
            return False
        self.mark_reply_chunk_delivered(chunk_text)
        display_chunk = self.playback_completed_chunks + 1
        if self.playback_total_chunks > 0:
            display_chunk = min(display_chunk, self.playback_total_chunks)
        self.playback_completed_chunks = max(self.playback_completed_chunks, display_chunk)
        self.write_status("playback")
        duration = wav_duration_seconds(wav_path)
        deadline = time.time() + max(0.0, duration)
        while time.time() < deadline:
            if self.is_turn_cancelled(cancel_epoch) or self.is_room_playback_stale(playback_epoch):
                self.cancel_active_turn("room playback epoch changed")
                self.write_status("turn_cancelled")
                return False
            time.sleep(min(0.1, max(0.0, deadline - time.time())))
        self.playback_completed_chunks = max(self.playback_completed_chunks, display_chunk)
        self.write_status("playback_done")
        return True

    def is_turn_cancelled(self, cancel_epoch: int) -> bool:
        return int(cancel_epoch) != int(self.turn_cancel_epoch)

    def room_playback_epoch(self) -> int:
        try:
            return int_or_zero(self.get_json(f"{self.tiny_url}/state").get("playback_epoch"))
        except Exception:
            return -1

    def is_room_playback_stale(self, expected_epoch: int | None) -> bool:
        if expected_epoch is None:
            return False
        try:
            state = self.get_json(f"{self.tiny_url}/state")
        except Exception:
            return False
        return self.is_state_playback_stale(state, expected_epoch)

    @staticmethod
    def is_state_playback_stale(state: dict[str, Any], expected_epoch: int | None) -> bool:
        if expected_epoch is None:
            return False
        current = int_or_zero(state.get("playback_epoch"))
        if int(current) == int(expected_epoch):
            return False
        reason = str(state.get("last_playback_stop_reason") or "").strip()
        if reason.endswith("turn finished"):
            return False
        return True

    def is_route_target_replaced(self, expected_target: str, *, route_index: int = 0) -> bool:
        expected = safe_id(expected_target)
        if not expected:
            return False
        try:
            state = self.get_json(f"{self.tiny_url}/state")
        except Exception:
            return False
        current_id = safe_id(state.get("current_id") or "")
        playback_owner_id = safe_id(state.get("playback_owner_id") or "")
        if current_id == expected or playback_owner_id == expected:
            return False
        next_id = safe_id(state.get("next_id") or "")
        if next_id == expected:
            return False
        latest_route_target = self.latest_route_target_from_state(state, min_index=route_index)
        if latest_route_target == expected:
            return False
        if latest_route_target:
            self.last_error = f"Prepared route to {expected} was replaced by {latest_route_target}"
            return True
        self.last_error = f"Prepared route to {expected} was replaced by {next_id or 'none'}"
        return True

    @classmethod
    def latest_route_target_from_state(cls, state: dict[str, Any], *, min_index: int = 0) -> str:
        flow = state.get("route_flow") if isinstance(state, dict) else []
        if not isinstance(flow, list):
            return ""
        latest_index = 0
        latest_target = ""
        for item in flow:
            if not isinstance(item, dict):
                continue
            index = int_or_zero(item.get("index"))
            if min_index and index < int(min_index):
                continue
            event_type = str(item.get("type") or "")
            message = str(item.get("message") or "")
            if not cls.is_routing_event(event_type, message):
                continue
            target_id = safe_id(item.get("target_id") or "")
            if not target_id or index < latest_index:
                continue
            latest_index = index
            latest_target = target_id
        return latest_target

    def is_current_or_playback_speaker(self) -> bool:
        try:
            state = self.get_json(f"{self.tiny_url}/state")
        except Exception:
            return False
        current_id = safe_id(state.get("current_id") or "")
        playback_owner_id = safe_id(state.get("playback_owner_id") or "")
        return current_id == self.bot_id or playback_owner_id == self.bot_id

    @staticmethod
    def should_preserve_existing_next(state: dict[str, Any], completing_speaker_id: str) -> bool:
        next_id = safe_id((state or {}).get("next_id") or "")
        if not next_id:
            return False
        return next_id != safe_id(completing_speaker_id)

    @staticmethod
    def participant_is_muted(state: dict[str, Any], participant_id: str) -> bool:
        participant_id = str(participant_id or "").strip()
        if not participant_id or not isinstance(state, dict):
            return False
        moderator_state = state.get("moderator_state") if isinstance(state.get("moderator_state"), dict) else {}
        participants = state.get("participants") if isinstance(state.get("participants"), list) else []
        participant = next(
            (item for item in participants if isinstance(item, dict) and str(item.get("id") or "").strip() == participant_id),
            {},
        )
        is_human = str((participant or {}).get("kind") or "").strip().lower() == "human"
        key = "muted_speaker_user_ids" if is_human else "muted_bot_ids"
        muted = {str(item or "").strip() for item in moderator_state.get(key, []) if str(item or "").strip()}
        return participant_id in muted

    @staticmethod
    def current_speaker_blocks_user(state: dict[str, Any], participant_id: str) -> bool:
        participant_id = safe_id(participant_id)
        if not participant_id or not isinstance(state, dict):
            return False
        active_id = safe_id(state.get("playback_owner_id") or state.get("current_id") or "")
        if not active_id or active_id == participant_id:
            return False
        moderator_state = state.get("moderator_state") if isinstance(state.get("moderator_state"), dict) else {}
        if "allow_current_interruption" not in moderator_state:
            return False
        return not as_bool(moderator_state.get("allow_current_interruption"), False)

    def cancel_active_turn(self, reason: str) -> None:
        self.turn_cancel_epoch += 1
        delivered_text = self.publish_delivered_reply_once(route=False)
        self.render_ready_chunks = 0
        self.render_total_chunks = 0
        self.playback_completed_chunks = 0
        self.playback_total_chunks = 0
        turn_id = str(self.active_turn_id or "").strip()
        if turn_id:
            self.cancel_nc_turn(turn_id, reason, spoken_text=delivered_text)
        self.write_status("turn_cancelled")

    def cancel_nc_turn(self, turn_id: str, reason: str, spoken_text: str = "") -> None:
        turn_id = str(turn_id or "").strip()
        if not turn_id:
            return
        payload = {
            "turn_id": turn_id,
            "reason": reason,
            "record_user_turn": False,
        }
        text = str(spoken_text or "").strip()
        if text:
            payload["spoken_text"] = text
        try:
            self.post_json_to_nc(
                self.nc_cancel_url(),
                payload,
            )
        except Exception as exc:
            print(f"[TinyBridge:{self.bot_id}] NC turn cancel failed: {exc}")

    def finish_nc_turn(self, turn_id: str) -> None:
        turn_id = str(turn_id or "").strip()
        if not turn_id:
            return
        try:
            self.post_json_to_nc(self.nc_finish_url(), {"turn_id": turn_id})
        except Exception as exc:
            print(f"[TinyBridge:{self.bot_id}] NC turn finish failed: {exc}")

    def room_context(self, participants: list[dict[str, Any]]) -> list[dict[str, Any]]:
        names = {
            safe_id(item.get("id") or ""): str(item.get("name") or item.get("id") or "").strip()
            for item in participants
            if isinstance(item, dict) and safe_id(item.get("id") or "")
        }
        participant_parts = []
        for item in participants:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("id") or "").strip()
            if not name:
                continue
            state = []
            if bool(item.get("current")):
                state.append("current")
            if bool(item.get("next")):
                state.append("next")
            if not bool(item.get("connected", True)):
                state.append("disconnected")
            kind = "bot" if str(item.get("kind") or "") == "bot" else "human"
            suffix = f" ({kind}{'; ' + ', '.join(state) if state else ''})"
            participant_parts.append(f"{name}{suffix}")
        entries: list[dict[str, Any]] = []
        if participant_parts:
            entries.append({
                "role": "system",
                "content": "Current room participants: " + ", ".join(participant_parts),
                "answer": False,
                "reason": "participants",
            })
        try:
            state = self.get_json(f"{self.tiny_url}/state")
        except Exception:
            state = {}
        flow = state.get("route_flow") if isinstance(state, dict) else []
        if isinstance(flow, list):
            for item in flow[-self.context_entry_limit():]:
                if not isinstance(item, dict):
                    continue
                message = " ".join(str(item.get("message") or "").split())
                source_id = safe_id(item.get("source_id") or "")
                target_id = safe_id(item.get("target_id") or "")
                event_type = str(item.get("type") or "event").strip() or "event"
                if not self.flow_entry_is_model_relevant(message, event_type):
                    continue
                source_name = names.get(source_id, source_id) or "Room"
                target_name = names.get(target_id, target_id) if target_id else ""
                route_text = f"{source_name} -> {target_name}: " if target_name else f"{source_name}: "
                entries.append({
                    "role": "user",
                    "content": f"{route_text}{message}",
                    "answer": bool(target_id),
                    "reason": event_type,
                })
        return entries

    @staticmethod
    def extract_speech_text(message: str) -> str:
        if ":" in message:
            return message.split(":", 1)[1].strip()
        return message.strip()

    @staticmethod
    def flow_entry_is_model_relevant(message: str, event_type: str = "") -> bool:
        text = str(message or "").strip()
        if not text:
            return False
        event_key = str(event_type or "").strip().lower()
        if event_key in {
            "playback",
            "current",
            "capture",
            "queue",
            "render",
            "moderator_updated",
            "participant",
            "system",
            "status",
            "route",
            "dead_air",
            "dead_air_recovery",
            "human_moderator",
            "bot_text_router",
            "room_router",
        }:
            return False
        internal_patterns = (
            "Playback started as ",
            "Playback stopped",
            "Current cleared",
            "Current -> ",
            "Capture owner",
            "Dead-air recovery chose",
            "Next ->",
            " -> no route | answer=",
            " -> no route | ",
            "queue_cleared",
            "runtime_replies",
            ".wav",
        )
        if any(pattern in text for pattern in internal_patterns):
            return False
        lower_text = text.lower()
        lifecycle_patterns = (
            "room initialized",
            "human connected",
            "bot connected",
            " removed.",
            "participant updated",
        )
        return not any(pattern in lower_text for pattern in lifecycle_patterns)

    @staticmethod
    def is_routing_event(event_type: str, message: str) -> bool:
        if event_type == "route":
            return True
        if event_type == "dead_air":
            return False
        if event_type != "current":
            return False
        text = message.lower()
        if text.startswith("current cleared"):
            return False
        return "audio playback" not in text and "nc_reply_complete" not in text

    @staticmethod
    def route_reason(
        event_type: str,
        source_id: str,
        target_id: str,
        message: str,
        names: dict[str, str],
    ) -> str:
        source = names.get(source_id, source_id) or "Room"
        target = names.get(target_id, target_id) or "no route"
        clean_message = " ".join(str(message or "").split())
        if clean_message:
            return f"{event_type}:{source}->{target}: {clean_message}"
        return f"{event_type}:{source}->{target}"

    @staticmethod
    def get_json(url: str) -> dict[str, Any]:
        with urllib.request.urlopen(url, timeout=5.0) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=10.0) as response:
            return json.loads(response.read().decode("utf-8"))

    def post_ndjson(self, url: str, payload: dict[str, Any]) -> Iterable[dict[str, Any]]:
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/x-ndjson"}
        if self.bridge_token:
            headers["X-NC-Discord-Bridge-Token"] = self.bridge_token
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(request, timeout=300.0) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if line:
                    yield json.loads(line)

    def nc_route_url(self) -> str:
        if self.nc_turn_url.rstrip("/").endswith("/turn"):
            return self.nc_turn_url.rstrip("/")[:-5] + "/route"
        return self.nc_turn_url.rstrip("/") + "/route"

    def nc_record_user_turn_url(self) -> str:
        if self.nc_turn_url.rstrip("/").endswith("/turn"):
            return self.nc_turn_url.rstrip("/")[:-5] + "/record_user_turn"
        return self.nc_turn_url.rstrip("/") + "/record_user_turn"

    def nc_cancel_url(self) -> str:
        if self.nc_turn_url.rstrip("/").endswith("/turn"):
            return self.nc_turn_url.rstrip("/")[:-5] + "/cancel"
        return self.nc_turn_url.rstrip("/") + "/cancel"

    def nc_finish_url(self) -> str:
        if self.nc_turn_url.rstrip("/").endswith("/turn"):
            return self.nc_turn_url.rstrip("/")[:-5] + "/finish"
        return self.nc_turn_url.rstrip("/") + "/finish"

    def nc_speak_url(self) -> str:
        if self.nc_turn_url.rstrip("/").endswith("/turn"):
            return self.nc_turn_url.rstrip("/")[:-5] + "/speak"
        return self.nc_turn_url.rstrip("/") + "/speak"

    def context_entry_limit(self) -> int:
        try:
            if self.settings_path and self.settings_path.exists():
                payload = json.loads(self.settings_path.read_text(encoding="utf-8"))
                chat = payload.get("chat") if isinstance(payload, dict) else {}
                value = chat.get("context_entries") if isinstance(chat, dict) else None
                return min(1000, max(1, int(value or 20)))
        except Exception:
            pass
        return 20

    def post_json_to_nc(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.bridge_token:
            headers["X-NC-Discord-Bridge-Token"] = self.bridge_token
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(request, timeout=300.0) as response:
            return json.loads(response.read().decode("utf-8"))


def wav_duration_seconds(path: str) -> float:
    try:
        with wave.open(str(Path(path)), "rb") as handle:
            frames = handle.getnframes()
            rate = handle.getframerate()
            return frames / float(rate) if rate else 0.0
    except Exception:
        return 0.0


def now_ms() -> int:
    return int(time.time() * 1000)


def int_or_zero(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def optional_path(value: str) -> Path | None:
    text = str(value or "").strip()
    return Path(text) if text else None


def safe_id(value: Any) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value or "").strip()).strip("_")


def participant_name(participants_by_id: dict[str, dict[str, Any]], participant_id: str) -> str:
    item = participants_by_id.get(participant_id)
    return str(item.get("name") or participant_id) if isinstance(item, dict) else ""


def run_self_test() -> int:
    import io

    encoded_stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
    safe_print("TinyMVP replacement char: \ufffd", file=encoded_stream)

    assert TinyVoiceBridge.extract_speech_text("Rakila: hello") == "hello"
    assert TinyVoiceBridge.extract_speech_text("hello") == "hello"
    assert TinyVoiceBridge.is_routing_event("current", "Current -> Echo | human moderator call on target") is True
    assert TinyVoiceBridge.is_routing_event("current", "Current -> Echo | audio playback") is False
    assert TinyVoiceBridge.is_routing_event("current", "Current cleared | stop_speech") is False
    assert TinyVoiceBridge.is_routing_event("route", "Next -> Echo | human moderator") is True
    assert TinyVoiceBridge.is_routing_event("dead_air", "Dead-air recovery chose Echo.") is False
    assert TinyVoiceBridge.latest_route_target_from_state(
        {
            "route_flow": [
                {"index": 10, "type": "route", "target_id": "kalle", "message": "Next -> Kalle"},
                {"index": 11, "type": "dead_air", "target_id": "moderator", "message": "Dead-air recovery chose Moderator."},
            ]
        }
    ) == "kalle"
    assert TinyVoiceBridge.is_routing_event("speech", "Echo: finished reply") is False
    assert TinyVoiceBridge.is_state_playback_stale({"playback_epoch": 2, "last_playback_stop_reason": "echo turn finished"}, 1) is False
    assert TinyVoiceBridge.is_state_playback_stale({"playback_epoch": 2, "last_playback_stop_reason": "stop_speech"}, 1) is True
    bridge = TinyVoiceBridge(
        bot_id="Echo!",
        bot_name="Echo",
        tiny_url="http://127.0.0.1:8788",
        nc_turn_url="http://127.0.0.1:8768/turn",
        poll_seconds=0.25,
    )
    assert bridge.bot_id == "echo"
    assert bridge.nc_route_url() == "http://127.0.0.1:8768/route"
    assert bridge.nc_cancel_url() == "http://127.0.0.1:8768/cancel"
    protected_bridge = TinyVoiceBridge(
        bot_id="Echo!",
        bot_name="Echo",
        tiny_url="http://127.0.0.1:8788",
        nc_turn_url="http://127.0.0.1:8768/turn",
        poll_seconds=0.25,
        route_protected_mic_speech=True,
    )
    assert protected_bridge.route_protected_mic_speech is True
    bridge.get_json = lambda _url: {"current_id": "echo", "playback_owner_id": "", "next_id": "nova"}  # type: ignore[method-assign]
    assert bridge.is_route_target_replaced("echo") is False
    assert bridge.is_route_target_replaced("nova") is False
    assert bridge.is_route_target_replaced("mira") is True
    bridge.get_json = lambda _url: {  # type: ignore[method-assign]
        "current_id": "mira",
        "playback_owner_id": "mira",
        "next_id": "mira",
        "route_flow": [
            {
                "index": 10,
                "type": "route",
                "source_id": "mira",
                "target_id": "moderator",
                "message": "Next -> Moderator | dead_air_recovery:Mira is speaking.",
            }
        ],
    }
    assert bridge.is_route_target_replaced("moderator", route_index=10) is False
    bridge.get_json = lambda _url: {"current_id": "echo", "playback_owner_id": "", "next_id": "nova"}  # type: ignore[method-assign]
    assert bridge.is_current_or_playback_speaker() is True
    bridge.get_json = lambda _url: {"current_id": "nova", "playback_owner_id": "echo", "next_id": ""}  # type: ignore[method-assign]
    assert bridge.is_current_or_playback_speaker() is True
    bridge.get_json = lambda _url: {"current_id": "nova", "playback_owner_id": "", "next_id": "echo"}  # type: ignore[method-assign]
    assert bridge.is_current_or_playback_speaker() is False
    assert TinyVoiceBridge.should_preserve_existing_next({"next_id": ""}, "echo") is False
    assert TinyVoiceBridge.should_preserve_existing_next({"next_id": "echo"}, "echo") is False
    assert TinyVoiceBridge.should_preserve_existing_next({"next_id": "nova"}, "echo") is True
    original_write_status = bridge.write_status
    try:
        bridge.write_status = lambda _stage, _state=None: None  # type: ignore[method-assign]
        bridge.turn_cancel_epoch = 4
        bridge.render_ready_chunks = 3
        bridge.render_total_chunks = 5
        bridge.playback_completed_chunks = 2
        bridge.playback_total_chunks = 5
        bridge.active_turn_id = ""
        bridge.cancel_active_turn("self-test clear queues")
        assert bridge.turn_cancel_epoch == 5
        assert bridge.render_ready_chunks == 0
        assert bridge.render_total_chunks == 0
        assert bridge.playback_completed_chunks == 0
        assert bridge.playback_total_chunks == 0

        progress_bridge = TinyVoiceBridge(
            bot_id="Echo!",
            bot_name="Echo",
            tiny_url="http://127.0.0.1:8788",
            nc_turn_url="http://127.0.0.1:8768/turn",
            poll_seconds=0.25,
        )
        progress_bridge.write_status = lambda _stage, _state=None: None  # type: ignore[method-assign]
        progress_bridge.get_json = lambda _url: {  # type: ignore[method-assign]
            "current_id": "echo",
            "playback_owner_id": "echo",
            "next_id": "",
            "playback_epoch": 0,
            "participants": [{"id": "echo", "name": "Echo", "kind": "bot", "connected": True}],
        }
        progress_bridge.post_json = lambda _url, _payload: {"ok": True, "state": progress_bridge.get_json("")}  # type: ignore[method-assign]
        progress_bridge.play_wav_chunk = lambda _wav_path, playback_epoch, cancel_epoch, chunk_text="": True  # type: ignore[method-assign]
        progress_bridge.publish_and_route_completed_reply = lambda _text, _participants: None  # type: ignore[method-assign]
        progress_nc_posts: list[tuple[str, dict[str, Any]]] = []
        progress_bridge.post_json_to_nc = lambda url, payload: progress_nc_posts.append((url, dict(payload))) or {"ok": True}  # type: ignore[method-assign]
        progress_bridge.post_ndjson = lambda _url, _payload: iter(  # type: ignore[method-assign]
            [
                {"type": "transcript", "input_text": "test"},
                *[
                    {"type": "audio_chunk", "reply_wav_path": f"chunk_{index}.wav", "reply_text": f"chunk {index}"}
                    for index in range(5)
                ],
                {"type": "done", "reply_text": "done", "reply_chunks": 5},
            ]
        )
        progress_bridge.send_turn_to_nc("test", "Tester", "tester", [{"id": "echo", "name": "Echo", "kind": "bot"}])
        assert progress_bridge.render_ready_chunks == 5
        assert progress_bridge.render_total_chunks == 5
        assert progress_bridge.playback_total_chunks == 5
        route_index = next(index for index, (url, _payload) in enumerate(progress_nc_posts) if url.endswith("/route"))
        finish_index = next(index for index, (url, payload) in enumerate(progress_nc_posts) if url.endswith("/finish") and payload.get("turn_id"))
        assert route_index < finish_index, progress_nc_posts
        assert not any(url.endswith("/record_user_turn") for url, _payload in progress_nc_posts), progress_nc_posts

        cancel_bridge = TinyVoiceBridge(
            bot_id="Echo!",
            bot_name="Echo",
            tiny_url="http://127.0.0.1:8788",
            nc_turn_url="http://127.0.0.1:8768/turn",
            poll_seconds=0.25,
        )
        cancel_bridge.write_status = lambda _stage, _state=None: None  # type: ignore[method-assign]
        cancel_bridge.active_turn_id = "turn_cancelled"
        cancel_bridge.reset_delivered_reply_state([
            {"id": "echo", "name": "Echo", "kind": "bot", "connected": True},
            {"id": "nova", "name": "Nova", "kind": "bot", "connected": True},
        ])
        cancel_posts: list[tuple[str, dict[str, Any]]] = []
        cancel_bridge.post_json = lambda url, payload: cancel_posts.append((url, dict(payload))) or {"ok": True}  # type: ignore[method-assign]
        cancel_bridge.post_json_to_nc = lambda url, payload: cancel_posts.append((url, dict(payload))) or {"ok": True}  # type: ignore[method-assign]
        cancel_bridge._runtime_history_endpoints = lambda: {"nova": "http://127.0.0.1:8770/record_user_turn"}  # type: ignore[method-assign]
        assert cancel_bridge.play_wav_chunk("delivered.wav", playback_epoch=0, cancel_epoch=0, chunk_text="Delivered chunk.") is True
        assert cancel_bridge.delivered_reply_text() == "Delivered chunk."
        cancel_bridge.cancel_active_turn("self-test interruption")
        assert any(url.endswith("/speech") and payload.get("text") == "Delivered chunk." for url, payload in cancel_posts), cancel_posts
        assert any(url.endswith("/cancel") and payload.get("spoken_text") == "Delivered chunk." for url, payload in cancel_posts), cancel_posts
        assert any(url.endswith("/record_user_turn") and payload.get("input_text") == "Delivered chunk." for url, payload in cancel_posts), cancel_posts
    finally:
        bridge.write_status = original_write_status  # type: ignore[method-assign]
    bridge.get_json = lambda _url: {  # type: ignore[method-assign]
        "route_flow": [
            {
                "index": 1,
                "type": "speech",
                "source_id": "rakila",
                "target_id": "",
                "message": "Rakila: Hello room.",
            },
            {
                "index": 2,
                "type": "room_router",
                "source_id": "rakila",
                "target_id": "echo",
                "message": "Rakila -> Echo | answer=yes | addressed Echo.",
            },
        ],
    }
    context = bridge.room_context([
        {"id": "echo", "name": "Echo", "kind": "bot", "connected": True, "current": False, "next": True},
        {"id": "rakila", "name": "Rakila", "kind": "human", "connected": True, "current": True, "next": False},
    ])
    assert isinstance(context, list)
    assert any("Rakila: Hello room." in str(item.get("content") or "") for item in context if isinstance(item, dict))
    joined_context = "\n".join(str(item.get("content") or "") for item in context if isinstance(item, dict))
    assert "Current room participants" in joined_context
    assert "TinyMVP" not in joined_context
    sent_turns: list[dict[str, Any]] = []
    direct_speech: list[str] = []
    bridge.get_json = lambda _url: {  # type: ignore[method-assign]
        "participants": [
            {"id": "echo", "name": "Echo", "kind": "bot", "connected": True, "current": False, "next": False},
            {"id": "rakila", "name": "Rakila", "kind": "human", "connected": True, "current": False, "next": False},
        ],
    }
    bridge.send_turn_to_nc = (  # type: ignore[method-assign]
        lambda input_text, speaker_name, user_id, participants, *, manual_call_on=False, route_index=0:
        sent_turns.append(
            {
                "input_text": input_text,
                "speaker_name": speaker_name,
                "user_id": user_id,
                "participant_count": len(participants),
                "manual_call_on": manual_call_on,
            }
        )
    )
    bridge.speak_text_direct = lambda text: direct_speech.append(text)  # type: ignore[method-assign]
    bridge.handle_command({"action": "send_message", "payload": {"text": "Please speak through Echo.", "moderator_announcement": True}})
    assert direct_speech == ["Please speak through Echo."]
    assert sent_turns == []
    bridge.latest_speech = SpeechMemory(index=90, source_id="echo", speaker_name="Echo", text="stale echo turn")
    bridge.handle_routed_event(
        91,
        "route",
        "mira",
        "Next -> Echo | dead_air_recovery:Mira is speaking.",
        [
            {"id": "echo", "name": "Echo", "kind": "bot", "connected": True},
            {"id": "mira", "name": "Mira", "kind": "bot", "connected": True},
        ],
    )
    assert sent_turns[-1]["speaker_name"] == "Mira"
    assert sent_turns[-1]["user_id"] == "mira"
    assert sent_turns[-1]["manual_call_on"] is True
    sent_turns.clear()
    direct_events: list[tuple[Any, ...]] = []
    bridge.speak_text_direct = TinyVoiceBridge.speak_text_direct.__get__(bridge, TinyVoiceBridge)  # type: ignore[method-assign]
    bridge.post_json_to_nc = lambda _url, payload: {  # type: ignore[method-assign]
        "ok": True,
        "reply_wav_path": "direct.wav",
        "reply_text": payload["text"],
    }
    bridge.play_wav_chunk = lambda wav_path, *, playback_epoch, cancel_epoch, chunk_text="": direct_events.append(("play", wav_path)) or True  # type: ignore[method-assign]
    bridge.post_completed_reply_speech = lambda text: direct_events.append(("speech", text))  # type: ignore[method-assign]
    bridge.route_completed_reply_text = lambda text, participants: direct_events.append(("route", text, len(participants)))  # type: ignore[method-assign]
    bridge.post_json = lambda url, payload: direct_events.append(("post", url, payload.get("reason"))) or {"ok": True}  # type: ignore[method-assign]
    bridge.handle_command({"action": "send_message", "payload": {"text": "Route this direct speech.", "moderator_announcement": True}})
    assert ("play", "direct.wav") in direct_events
    assert ("speech", "Route this direct speech.") in direct_events
    assert any(event[0] == "post" and str(event[1]).endswith("/stop") for event in direct_events)
    assert ("route", "Route this direct speech.", 2) in direct_events
    direct_events.clear()
    bridge.post_json_to_nc = lambda _url, payload: {  # type: ignore[method-assign]
        "ok": True,
        "reply_wav_path": "first.wav",
        "reply_text": payload["text"],
        "reply_chunks": [
            {"reply_wav_path": "first.wav", "reply_text": "First part."},
            {"reply_wav_path": "second.wav", "reply_text": "Second part."},
        ],
    }
    bridge.handle_command({"action": "send_message", "payload": {"text": "First part. Second part.", "moderator_announcement": True}})
    assert ("play", "first.wav") in direct_events
    assert ("play", "second.wav") in direct_events
    assert ("speech", "First part. Second part.") in direct_events
    assert ("route", "First part. Second part.", 2) in direct_events
    bridge.route_completed_reply_text = TinyVoiceBridge.route_completed_reply_text.__get__(bridge, TinyVoiceBridge)  # type: ignore[method-assign]
    bridge.play_wav_chunk = TinyVoiceBridge.play_wav_chunk.__get__(bridge, TinyVoiceBridge)  # type: ignore[method-assign]
    bridge.handle_command({"action": "send_message", "payload": {"text": "Ask TinyMVP.", "moderator_announcement": False}})
    assert sent_turns == [
        {
            "input_text": "Ask TinyMVP.",
            "speaker_name": "TinyMVP",
            "user_id": "tinymvp",
            "participant_count": 2,
            "manual_call_on": True,
        }
    ]
    posted: list[tuple[str, dict[str, Any]]] = []

    def fake_post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
        posted.append((url, dict(payload)))
        target_id = safe_id(payload.get("target_bot_id") or payload.get("speaker_user_id") or "")
        moderator_state: dict[str, Any] = {
            "last_command": str(payload.get("action") or ""),
            "pending_route": {"target_bot_id": safe_id(payload.get("target_bot_id") or "")} if payload.get("target_bot_id") else {},
            "pending_human_route": {"speaker_user_id": str(payload.get("speaker_user_id") or "")} if payload.get("speaker_user_id") else {},
            "muted_bot_ids": [safe_id(payload.get("target_bot_id") or "")] if payload.get("action") == "moderator_mute" else [],
        }
        return {
            "ok": True,
            "state": {
                "current_id": "",
                "next_id": target_id,
                "participants": [],
                "moderator_state": moderator_state,
                "route_flow": [],
            },
        }

    bridge.post_json = fake_post_json  # type: ignore[method-assign]
    bridge.handle_moderator_command("moderator_mute", {"target_bot_id": "Echo!"})
    assert posted[-1][0].endswith("/moderator")
    assert posted[-1][1]["action"] == "moderator_mute"
    assert bridge.moderator_state["muted_bot_ids"] == ["echo"]
    bridge.sync_moderator_state_from_room(
        {
            "current_id": "rakila",
            "next_id": "nova",
            "participants": [
                {"id": "echo", "name": "Echo", "kind": "bot", "connected": True, "current": False, "next": False},
                {"id": "nova", "name": "Nova", "kind": "bot", "connected": True, "current": False, "next": True},
                {"id": "rakila", "name": "Rakila", "kind": "human", "connected": True, "current": True, "next": False},
            ],
            "moderator_state": {
                "enabled": True,
                "floor_target_bot_id": "nova",
                "only_bot_ids": ["nova"],
                "allow_current_interruption": False,
                "pending_route": {"target_bot_id": "nova", "reason": "shared room"},
                "pending_human_route": {},
                "current_human_route": {"speaker_user_id": "rakila", "speaker_name": "Rakila"},
                "muted_bot_ids": ["echo"],
                "muted_speaker_user_ids": ["other_user"],
                "last_command": "shared_state",
            },
            "route_flow": [
                {
                    "time": "12:34:56",
                    "type": "bot_text_router",
                    "source_id": "echo",
                    "target_id": "nova",
                    "message": "Echo explicitly asks Nova to respond.",
                }
            ],
        }
    )
    assert bridge.moderator_state["floor_target_bot_id"] == "nova"
    assert bridge.moderator_state["only_bot_ids"] == ["nova"]
    assert bridge.moderator_state["muted_bot_ids"] == ["echo"]
    assert bridge.moderator_state["muted_speaker_user_ids"] == ["other_user"]
    assert bridge.moderator_state["allow_current_interruption"] is False
    assert bridge.moderator_state["current_human_route"]["speaker_user_id"] == "rakila"
    route_entry = bridge.moderator_state["route_flow"][0]
    assert route_entry["speaker_name"] == "Echo"
    assert route_entry["target_name"] == "Nova"
    assert route_entry["source"] == "bot_text_router"
    assert route_entry["answer"] is True
    assert route_entry["captured_at"] == "12:34:56"
    bridge.handle_moderator_command("moderator_route_next", {"target_bot_id": "Nova"})
    bridge.handle_moderator_command("moderator_route_next_human", {"speaker_user_id": "rakila", "speaker_name": "Rakila"})
    assert posted[-2][0].endswith("/moderator")
    assert posted[-2][1]["action"] == "moderator_route_next"
    assert posted[-2][1]["target_bot_id"] == "nova"
    assert posted[-1][0].endswith("/moderator")
    assert posted[-1][1]["action"] == "moderator_route_next_human"
    assert posted[-1][1]["speaker_user_id"] == "rakila"
    posted.clear()

    def fake_call_post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
        posted.append((url, dict(payload)))
        return {
            "ok": True,
            "state": {
                "current_id": "echo",
                "next_id": "",
                "participants": [
                    {"id": "echo", "name": "Echo", "kind": "bot", "connected": True, "current": True, "next": False},
                ],
                "moderator_state": {
                    "current_bot_id": "echo",
                    "current_bot_name": "Echo",
                    "last_command": "current:echo",
                },
                "route_flow": [],
            },
        }

    bridge.post_json = fake_call_post_json  # type: ignore[method-assign]
    bridge.handle_command({"action": "moderator_call_on", "payload": {"target_bot_id": "echo"}})
    assert posted[-1][0].endswith("/call")
    assert bridge.moderator_state["current_bot_id"] == "echo"
    posted.clear()

    bridge.get_json = lambda _url: {"current_id": "echo", "playback_owner_id": "echo", "next_id": ""}  # type: ignore[method-assign]
    bridge.post_json_to_nc = lambda _url, _payload: {  # type: ignore[method-assign]
        "answer": False,
        "target_bot_id": "",
        "reason": "moderator asked human for topic",
    }
    bridge.route_completed_reply_text(
        "Is there something specific you'd like to discuss with the group?",
        [
            {"id": "echo", "name": "Echo", "kind": "bot", "connected": True},
            {"id": "moderator", "name": "Moderator", "kind": "bot", "connected": True},
            {"id": "rakila", "name": "Rakila", "kind": "human", "connected": True},
        ],
    )
    assert any(url.endswith("/decision") for url, _payload in posted)
    assert not any(url.endswith("/dead-air") for url, _payload in posted)
    posted.clear()

    bridge.get_json = lambda _url: {"current_id": "echo", "playback_owner_id": "echo", "next_id": ""}  # type: ignore[method-assign]
    bridge.post_json_to_nc = lambda _url, _payload: {  # type: ignore[method-assign]
        "answer": True,
        "target_bot_id": "echo",
        "reason": "open_invitation:Echo asked the room a question.",
    }
    recovered_reasons: list[str] = []
    bridge.maybe_recover_dead_air = lambda reason: recovered_reasons.append(reason)  # type: ignore[method-assign]
    bridge.route_completed_reply_text(
        "How do we build the fence without turning humans into obstacles?",
        [
            {"id": "echo", "name": "Echo", "kind": "bot", "connected": True},
            {"id": "moderator", "name": "Moderator", "kind": "bot", "connected": True},
            {"id": "rakila", "name": "Rakila", "kind": "human", "connected": True},
        ],
    )
    assert not any(url.endswith("/route") for url, _payload in posted), posted
    assert any(url.endswith("/decision") and _payload.get("answer") is False for url, _payload in posted), posted
    assert recovered_reasons, posted
    assert "self_route" in recovered_reasons[-1], recovered_reasons
    bridge.maybe_recover_dead_air = TinyVoiceBridge.maybe_recover_dead_air.__get__(bridge, TinyVoiceBridge)  # type: ignore[method-assign]
    posted.clear()

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".json") as settings_file:
        json.dump(
            {
                "room_router": {
                    "candidate_bots": [
                        {"id": "echo", "name": "Echo", "nc_runtime": {"host": "127.0.0.1", "port": 8768}},
                        {"id": "nova", "name": "Nova", "nc_runtime": {"host": "127.0.0.1", "port": 8770}},
                        {"id": "moderator", "name": "Moderator", "nc_runtime": {"host": "127.0.0.1", "port": 8771}},
                    ]
                }
            },
            settings_file,
        )
        history_settings_path = Path(settings_file.name)
    try:
        bridge.settings_path = history_settings_path
        history_posts: list[tuple[str, dict[str, Any]]] = []
        bridge.post_json_to_nc = lambda url, payload: history_posts.append((url, dict(payload))) or {"ok": True, "recorded": True}  # type: ignore[method-assign]
        bridge.broadcast_room_turn_to_histories(
            "Moderator: Please share one topic each.",
            speaker_name="Moderator",
            source_id="moderator",
            participants=[
                {"id": "echo", "name": "Echo", "kind": "bot", "connected": True},
                {"id": "nova", "name": "Nova", "kind": "bot", "connected": True},
                {"id": "moderator", "name": "Moderator", "kind": "bot", "connected": True},
                {"id": "kalle", "name": "Kalle", "kind": "human", "connected": True},
            ],
            route_key="room_turn_1",
            selected_target_id="echo",
        )
        recorded_endpoints = [url for url, _payload in history_posts]
        assert "http://127.0.0.1:8770/record_user_turn" in recorded_endpoints, history_posts
        assert "http://127.0.0.1:8768/record_user_turn" in recorded_endpoints, history_posts
        assert "http://127.0.0.1:8771/record_user_turn" not in recorded_endpoints, history_posts
        assert all(payload.get("record_only") is True for _url, payload in history_posts)
        assert history_posts[-1][1]["speaker_name"] == "Moderator", history_posts
        assert history_posts[-1][1]["input_text"] == "Moderator: Please share one topic each.", history_posts
    finally:
        try:
            history_settings_path.unlink(missing_ok=True)
        except Exception:
            pass
        bridge.settings_path = None

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".json") as settings_file:
        json.dump(
            {
                "room_router": {
                    "dead_air_recovery": {
                        "enabled": True,
                        "trigger_mode": "no_route_after_bot_speech",
                        "silence_timeout_seconds": 0.05,
                        "cooldown_seconds": 0.0,
                        "next_speaker_strategy": "selected_fallback",
                        "selected_fallback_target": "nova",
                    }
                }
            },
            settings_file,
        )
        delayed_settings_path = Path(settings_file.name)
    try:
        posted.clear()
        bridge.settings_path = delayed_settings_path
        bridge.post_json = fake_post_json  # type: ignore[method-assign]
        state_sequence = [
            {"current_id": "echo", "next_id": "", "playback_owner_id": "echo"},
            {"current_id": "echo", "next_id": "", "playback_owner_id": "echo"},
            {"current_id": "", "next_id": "", "playback_owner_id": ""},
        ]

        def fake_delayed_get_json(_url: str) -> dict[str, Any]:
            if state_sequence:
                return state_sequence.pop(0)
            return {"current_id": "", "next_id": "", "playback_owner_id": ""}

        bridge.get_json = fake_delayed_get_json  # type: ignore[method-assign]
        bridge.maybe_recover_dead_air("delayed while speaking")
        assert not any(url.endswith("/dead-air") for url, _payload in posted)
        time.sleep(0.16)
        assert any(url.endswith("/dead-air") for url, _payload in posted)
        assert posted[-1][1]["strategy"] == "selected_fallback"
        assert posted[-1][1]["fallback_target"] == "nova"
        assert posted[-1][1]["source_id"] == "echo"
        posted.clear()
        bridge.get_json = lambda _url: {"current_id": "", "next_id": "", "playback_owner_id": ""}  # type: ignore[method-assign]
        bridge.maybe_recover_dead_air("delayed quiet room")
        assert not any(url.endswith("/dead-air") for url, _payload in posted)
        time.sleep(0.08)
        assert any(url.endswith("/dead-air") for url, _payload in posted)
    finally:
        try:
            delayed_settings_path.unlink(missing_ok=True)
        except Exception:
            pass
        bridge.settings_path = None
    posted.clear()

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".json") as settings_file:
        json.dump(
            {
                "room_router": {
                    "dead_air_recovery": {
                        "enabled": True,
                        "trigger_mode": "no_route_after_bot_speech",
                        "silence_timeout_seconds": 0.0,
                        "next_speaker_strategy": "llm_choose",
                        "selected_fallback_target": "",
                    }
                }
            },
            settings_file,
        )
        llm_choose_settings_path = Path(settings_file.name)
    try:
        posted.clear()
        bridge.settings_path = llm_choose_settings_path
        bridge.post_json = fake_post_json  # type: ignore[method-assign]
        bridge.get_json = lambda _url: {  # type: ignore[method-assign]
            "current_id": "echo",
            "next_id": "",
            "playback_owner_id": "",
            "participants": [
                {"id": "echo", "name": "Echo", "kind": "bot", "connected": True},
                {"id": "nova", "name": "Nova", "kind": "bot", "connected": True},
                {"id": "kalle", "name": "Kalle", "kind": "human", "connected": True},
            ],
            "route_flow": [],
        }
        bridge.post_json_to_nc = lambda _url, _payload: {  # type: ignore[method-assign]
            "answer": True,
            "target_bot_id": "Nova",
            "reason": "dead-air should continue with Nova",
        }
        bridge.maybe_recover_dead_air("Echo asked the room a question.")
        assert any(url.endswith("/dead-air") for url, _payload in posted)
        assert posted[-1][1]["strategy"] == "llm_choose"
        assert posted[-1][1]["preferred_target"] == "nova"
    finally:
        try:
            llm_choose_settings_path.unlink(missing_ok=True)
        except Exception:
            pass
        bridge.settings_path = None
    posted.clear()

    def fake_stop_post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
        posted.append((url, dict(payload)))
        return {
            "ok": True,
            "state": {
                "current_id": "",
                "next_id": "",
                "participants": [
                    {"id": "echo", "name": "Echo", "kind": "bot", "connected": True, "current": False, "next": False},
                ],
                "moderator_state": {
                    "current_bot_id": "",
                    "current_bot_name": "",
                    "last_command": str(payload.get("reason") or ""),
                },
                "route_flow": [],
            },
        }

    bridge.post_json = fake_stop_post_json  # type: ignore[method-assign]
    bridge.moderator_state["current_bot_id"] = "echo"
    bridge.handle_command({"action": "stop_speech"})
    assert posted[-1][0].endswith("/stop")
    assert bridge.moderator_state["current_bot_id"] == ""
    posted.clear()

    def fake_connect_post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
        posted.append((url, dict(payload)))
        connected = url.endswith("/participants/connect")
        return {
            "ok": True,
            "state": {
                "current_id": "",
                "next_id": "nova" if connected else "",
                "participants": [
                    {"id": "echo", "name": "Echo", "kind": "bot", "connected": connected, "current": False, "next": False},
                    {"id": "nova", "name": "Nova", "kind": "bot", "connected": True, "current": False, "next": connected},
                ],
                "moderator_state": {
                    "pending_route": {"target_bot_id": "nova"} if connected else {},
                    "route_next_target_bot_id": "nova" if connected else "",
                    "last_command": "connect" if connected else "disconnect",
                },
                "route_flow": [],
            },
        }

    bridge.post_json = fake_connect_post_json  # type: ignore[method-assign]
    bridge.moderator_state["pending_route"] = {"target_bot_id": "old"}
    bridge.handle_command({"action": "disconnect"})
    assert posted[-1][0].endswith("/participants/disconnect")
    assert bridge.moderator_state["pending_route"] == {}
    bridge.handle_command({"action": "reconnect"})
    assert posted[-1][0].endswith("/participants/connect")
    assert bridge.moderator_state["pending_route"]["target_bot_id"] == "nova"
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_wav:
        mic_wav_path = Path(temp_wav.name)
    try:
        with wave.open(str(mic_wav_path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(16000)
            handle.writeframes(b"\x00\x00" * 1600)
        posted.clear()
        bridge.get_json = lambda _url: {  # type: ignore[method-assign]
            "current_id": "echo",
            "next_id": "nova",
            "participants": [
                {"id": "echo", "name": "Echo", "kind": "bot", "connected": True, "current": True, "next": False},
                {"id": "nova", "name": "Nova", "kind": "bot", "connected": True, "current": False, "next": True},
                {"id": "rakila", "name": "Rakila", "kind": "human", "connected": True, "current": False, "next": False},
            ],
        }
        bridge.post_json_to_nc = lambda _url, _payload: {  # type: ignore[method-assign]
            "answer": True,
            "target_bot_id": "echo",
            "reason": "router wanted echo",
            "input_text": "hello there",
        }
        bridge.submit_microphone_wav(mic_wav_path)
        assert any(url.endswith("/speech") for url, _payload in posted)
        assert not any(url.endswith("/route") for url, _payload in posted)
        assert any(url.endswith("/decision") for url, _payload in posted)
        posted.clear()
        nc_route_calls: list[dict[str, Any]] = []
        bridge.get_json = lambda _url: {  # type: ignore[method-assign]
            "current_id": "echo",
            "next_id": "",
            "playback_owner_id": "echo",
            "participants": [
                {"id": "echo", "name": "Echo", "kind": "bot", "connected": True, "current": True, "next": False},
                {"id": "rakila", "name": "Rakila", "kind": "human", "connected": True, "current": False, "next": False},
            ],
            "moderator_state": {
                "allow_current_interruption": False,
            },
        }
        bridge.post_json_to_nc = lambda _url, payload: nc_route_calls.append(dict(payload)) or {  # type: ignore[method-assign]
            "answer": True,
            "target_bot_id": "echo",
            "reason": "should not be reached",
            "input_text": "protected current interruption",
        }
        bridge.submit_microphone_wav(mic_wav_path)
        assert nc_route_calls == []
        assert any(payload.get("reason") == "current_speaker_protected" for _url, payload in posted)
        protected_bridge.get_json = bridge.get_json  # type: ignore[method-assign]
        protected_bridge.post_json = lambda url, payload: posted.append((url, dict(payload))) or {"ok": True}  # type: ignore[method-assign]
        protected_bridge.post_json_to_nc = lambda _url, payload: nc_route_calls.append(dict(payload)) or {  # type: ignore[method-assign]
            "answer": True,
            "target_bot_id": "echo",
            "reason": "protected speech routed",
            "input_text": "protected current interruption",
        }
        posted.clear()
        nc_route_calls.clear()
        protected_bridge.submit_microphone_wav(mic_wav_path)
        assert any(url.endswith("/speech") for url, _payload in posted)
        assert any(url.endswith("/route") for url, _payload in posted)
        assert nc_route_calls
        assert any(call.get("record_route_context") is True for call in nc_route_calls), nc_route_calls
    finally:
        try:
            mic_wav_path.unlink()
        except OSError:
            pass
    with tempfile.NamedTemporaryFile(delete=False, suffix=".status.json") as temp_status:
        status_path = Path(temp_status.name)
    try:
        bridge.status_path = status_path
        bridge.get_json = lambda _url: {  # type: ignore[method-assign]
            "current_id": "echo",
            "next_id": "",
            "playback_owner_id": "echo",
            "capture_owner_id": "echo",
            "participants": [
                {"id": "echo", "name": "Echo", "kind": "bot", "connected": True, "current": True, "next": False},
                {"id": "rakila", "name": "Rakila", "kind": "human", "connected": True, "current": False, "next": False},
            ],
        }
        bridge.write_status("connected")
        status_payload = json.loads(status_path.read_text(encoding="utf-8"))
        assert status_payload["capture_owner"] == "Echo (echo)"
        assert status_payload["bridge_mode"] == "tiny_mvp"
        assert status_payload["owns_capture"] is True
        assert status_payload["reply_floor_owner"] == "echo"
        assert status_payload["reply_floor_owner_bot"] == "Echo"
        assert status_payload["owns_reply_floor"] is True
        assert status_payload["active_captures"] == 1
    finally:
        try:
            status_path.unlink()
        except OSError:
            pass
        bridge.status_path = None
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_wav:
        playback_wav_path = Path(temp_wav.name)
    try:
        with wave.open(str(playback_wav_path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(16000)
            handle.writeframes(b"")
        status_samples: list[tuple[str, int, int]] = []
        bridge.post_json = lambda _url, _payload: {"ok": True}  # type: ignore[method-assign]
        bridge.is_room_playback_stale = lambda _epoch: False  # type: ignore[method-assign]
        bridge.playback_completed_chunks = 0
        bridge.playback_total_chunks = 4

        def capture_status(stage: str, _room_state: dict[str, Any] | None = None) -> None:
            status_samples.append((stage, bridge.playback_completed_chunks, bridge.playback_total_chunks))

        bridge.write_status = capture_status  # type: ignore[method-assign]
        assert bridge.play_wav_chunk(str(playback_wav_path), playback_epoch=0, cancel_epoch=bridge.turn_cancel_epoch) is True
        assert ("playback", 1, 4) in status_samples
    finally:
        try:
            playback_wav_path.unlink()
        except OSError:
            pass
    run_process_contract_self_test()
    print("Tiny voice bridge self-test passed.")
    return 0


def run_process_contract_self_test() -> None:
    """Exercise the NC-style status/command-file process contract end-to-end."""
    host = "127.0.0.1"
    port = find_free_port()
    tiny_url = f"http://{host}:{port}"
    server_process: subprocess.Popen | None = None
    bridge_process: subprocess.Popen | None = None
    with tempfile.TemporaryDirectory(prefix="tinymvp_bridge_contract_") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        status_path = temp_dir / "echo.status.json"
        command_path = temp_dir / "echo.commands.jsonl"
        env = os.environ.copy()
        env["NC_DISCORD_BRIDGE_STATUS_JSON"] = str(status_path)
        env["NC_DISCORD_BRIDGE_COMMAND_JSONL"] = str(command_path)
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            server_process = subprocess.Popen(
                [
                    sys.executable,
                    str(Path(__file__).with_name("main.py")),
                    "--host",
                    host,
                    "--port",
                    str(port),
                ],
                cwd=str(Path(__file__).resolve().parent),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=creationflags,
            )
            wait_for_http_json(f"{tiny_url}/state")
            bridge_process = subprocess.Popen(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--bot-id",
                    "echo",
                    "--bot-name",
                    "Echo",
                    "--tiny-url",
                    tiny_url,
                    "--nc-turn-url",
                    "http://127.0.0.1:1/turn",
                    "--poll-seconds",
                    "0.05",
                ],
                cwd=str(Path(__file__).resolve().parent),
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=creationflags,
            )
            status = wait_for_status(status_path, lambda item: item.get("state") == "connected")
            assert status["bot_id"] == "echo"
            assert status["bridge_mode"] == "tiny_mvp"
            assert status["transport"] == "tinymvp"
            write_command(command_path, "moderator_route_next", {"target_bot_id": "nova"})
            status = wait_for_status(
                status_path,
                lambda item: item.get("moderator_state", {}).get("pending_route", {}).get("target_bot_id") == "nova",
            )
            state = wait_for_http_json(f"{tiny_url}/state")
            assert state["moderator_state"]["pending_route"]["target_bot_id"] == "nova"
            assert any(entry.get("target_name") == "Nova" for entry in status["moderator_state"]["route_flow"])
            write_command(command_path, "moderator_clear_pending", {})
            status = wait_for_status(
                status_path,
                lambda item: not item.get("moderator_state", {}).get("pending_route")
                and item.get("moderator_state", {}).get("last_command") == "clear_pending",
            )
            assert not status["moderator_state"]["pending_route"]
        finally:
            terminate_process(bridge_process)
            terminate_process(server_process)


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as handle:
        handle.bind(("127.0.0.1", 0))
        return int(handle.getsockname()[1])


def wait_for_http_json(url: str, timeout_seconds: float = 5.0) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.5) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            last_error = exc
            time.sleep(0.05)
    raise AssertionError(f"Timed out waiting for {url}: {last_error}")


def wait_for_status(status_path: Path, predicate, timeout_seconds: float = 5.0) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last_status: dict[str, Any] | None = None
    while time.time() < deadline:
        try:
            status = json.loads(status_path.read_text(encoding="utf-8"))
        except Exception:
            time.sleep(0.05)
            continue
        last_status = status
        if predicate(status):
            return status
        time.sleep(0.05)
    raise AssertionError(f"Timed out waiting for TinyMVP bridge status. Last status: {last_status}")


def write_command(command_path: Path, action: str, payload: dict[str, Any]) -> None:
    command_path.write_text(json.dumps({"action": action, "payload": payload}) + "\n", encoding="utf-8")


def terminate_process(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2.0)


def main() -> int:
    parser = argparse.ArgumentParser(description="TinyMVP local voice bridge for NC /turn testing.")
    parser.add_argument("--bot-id", default="echo")
    parser.add_argument("--bot-name", default="")
    parser.add_argument("--tiny-url", default="http://127.0.0.1:8788")
    parser.add_argument("--nc-turn-url", default="http://127.0.0.1:8768/turn")
    parser.add_argument("--poll-seconds", type=float, default=0.25)
    parser.add_argument("--capture-mic", action="store_true", help="Enable console push-to-talk microphone capture for this bridge process.")
    parser.add_argument("--mic-user-id", default="human")
    parser.add_argument("--mic-user-name", default="Human")
    parser.add_argument("--mic-seconds", type=float, default=6.0)
    parser.add_argument("--mic-sample-rate", type=int, default=16000)
    parser.add_argument("--mic-device", default="")
    parser.add_argument("--route-protected-mic-speech", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return run_self_test()
    bridge = TinyVoiceBridge(
        bot_id=args.bot_id,
        bot_name=args.bot_name or args.bot_id,
        tiny_url=args.tiny_url,
        nc_turn_url=args.nc_turn_url,
        poll_seconds=args.poll_seconds,
        capture_mic=args.capture_mic,
        mic_user_id=args.mic_user_id,
        mic_user_name=args.mic_user_name,
        mic_seconds=args.mic_seconds,
        mic_sample_rate=args.mic_sample_rate,
        mic_device=args.mic_device,
        route_protected_mic_speech=args.route_protected_mic_speech,
    )
    try:
        bridge.run()
    except KeyboardInterrupt:
        print(f"\n[TinyBridge:{args.bot_id}] stopped.")
    except urllib.error.URLError as exc:
        print(f"[TinyBridge:{args.bot_id}] connection failed: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

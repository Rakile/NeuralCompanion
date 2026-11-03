from __future__ import annotations
from contextlib import contextmanager

import copy
import json
import threading
import time
import urllib.request
import urllib.parse
import uuid
from typing import Any

from addons.discord_voice_bridge.settings import load_settings, save_local_settings, _deep_merge
from addons.discord_voice_bridge.local_room_cast import ROLES, room_cast, persisted_cast, validate_cast
from addons.discord_voice_bridge.linked_personas import member_reference, resolve_member, visible_member
from addons.discord_voice_bridge import local_room_memory
from addons.discord_voice_bridge.room_anonymous import apply_anonymous
from addons.discord_voice_bridge.local_room_behavior import apply_behavior, behavior_from_settings, normalize_behavior

_ROLE_ORDER = ROLES
_HUMAN_ID = "human"
_HUMAN_NAME = "You"
_MESSAGE_LIMIT = 80


def _overlay_skipped_replies(rows, skipped, utterance_rows):
    for turn_id, (entry, position) in skipped.items():
        canonical = str(utterance_rows[turn_id] + 1) if turn_id in utterance_rows else ''
        row = next((r for r in rows if r.get('id') == canonical), None) if canonical else None
        if row is None:
            row = dict(id='skipped:' + turn_id, name=entry['name'], time=entry.get('time', ''))
            insert_at = next((i for i, r in enumerate(rows)
                if str(r.get('id', '')).isdigit() and int(r['id']) > position), len(rows))
            rows.insert(insert_at, row)
        row.update(text=entry['text'], role='assistant', speech_active=False,
            speech_progress=1., display_pending=False, speech_skipped=True)
    return rows


def _local_display_messages(messages: list[dict[str, Any]], state: dict[str, Any],
                            conversation: dict[str, Any]) -> list[dict[str, Any]]:
    """Overlay only the current turn; the delivered transcript stays authoritative.

    Canonical row IDs are positional. Consult the transcript's utterance identity
    rather than matching text/names, which can repeat across consecutive replies.
    """
    rows = copy.deepcopy(messages)
    turn = state.get('presentation_turn') or {}
    if turn.get('conversation_id') != conversation.get('id'):
        turn = {}
    participant_kinds = {member.get('id'): member.get('kind')
                         for member in state.get('participants') or [] if isinstance(member, dict)}
    roles = {}
    skipped = {}
    utterance_rows = {}
    tail = {}
    row_count = len(conversation.get('messages') or [])
    tail_name = (conversation['messages'][-1].get('name', '')
                 if conversation.get('messages') else '')
    tail_text = (conversation['messages'][-1].get('text', '')
                 if conversation.get('messages') else '')
    path = local_room_memory.INSTANCE_ROOT/'local_room/transcript.jsonl'
    if path.is_symlink():
        return rows
    try:
        for line in path.read_text(encoding='utf-8').splitlines():
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if (isinstance(entry, dict) and entry.get('conversation_id') == conversation.get('id')
                    and entry.get('display_only') and entry.get('utterance_id')
                    and isinstance(entry.get('text'), str) and isinstance(entry.get('name'), str)):
                skipped[entry['utterance_id']] = (entry, row_count)
                continue
            if (isinstance(entry, dict) and entry.get('conversation_id') == conversation.get('id')
                    and isinstance(entry.get('name'), str) and isinstance(entry.get('text'), str)):
                utterance = str(entry.get('utterance_id') or '')
                previous = str(tail.get('utterance_id') or '')
                if entry.get('replace_utterance') and utterance in utterance_rows:
                    if tail.get('utterance_id') == utterance:
                        tail_text = entry['text']
                        tail = entry
                    continue
                if utterance and utterance == previous and row_count and tail_name == entry['name']:
                    tail_text += ' ' + entry['text']
                elif (not utterance and previous and row_count and entry.get('speaker_id')
                      and entry.get('speaker_id') == tail.get('speaker_id') and entry.get('time')
                      and entry.get('time') == tail.get('time') and tail_name == entry['name']
                      and ' '.join(tail_text.split()) == ' '.join(entry['text'].split())):
                    pass  # Preserve messages()'s legacy completion-echo grouping.
                else:
                    row_count += 1
                    tail_name, tail_text = entry['name'], entry['text']
                speaker_id = entry.get('speaker_id')
                if speaker_id == _HUMAN_ID or participant_kinds.get(speaker_id) == 'human':
                    roles[row_count - 1] = 'user'
                elif (participant_kinds.get(speaker_id) == 'bot'
                      or speaker_id in (conversation.get('members') or {})):
                    roles[row_count - 1] = 'assistant'
                tail = entry
                if utterance: utterance_rows[utterance] = row_count - 1
    except FileNotFoundError:
        pass
    except (OSError, UnicodeError):
        return rows
    if len(rows) != row_count:
        return rows  # Canonical read and transcript identity read straddled an append.
    for index, role in roles.items():
        if 0 <= index < len(rows):
            rows[index]['role'] = role
    if not turn:
        return _overlay_skipped_replies(rows, skipped, utterance_rows)
    same_turn = (tail.get('utterance_id') == turn.get('turn_id')
                 and tail.get('speaker_id') == turn.get('source_id') and tail.get('name') == turn.get('name'))
    if same_turn:
        # A transcript append can race the preceding messages() read. Defer
        # this overlay one poll if those two observations do not agree yet.
        if not rows or rows[-1].get('name') != tail['name'] or not rows[-1].get('text', '').endswith(tail['text']):
            return _overlay_skipped_replies(rows, skipped, utterance_rows)
        row = rows[-1]
    else:
        if turn.get('delivered'):
            return _overlay_skipped_replies(rows, skipped, utterance_rows)
        row = dict(id=str(len(rows)+1), name=turn['name'], time=turn.get('time', ''))
        rows.append(row)
    row.update(text=turn['text'], role='assistant', speech_active=bool(turn.get('speech_active')),
               speech_progress=max(0., min(1., float(turn.get('speech_progress') or 0.))),
               spoken_text=str(turn.get('spoken_text') or ''), spoken_prefix=str(turn.get('spoken_prefix') or ''),
               display_pending=bool(turn.get('display_pending')))
    return _overlay_skipped_replies(rows, skipped, utterance_rows)


def _local_room_user_name(settings: dict[str, Any]) -> str:
    local = settings.get('local_room') or {}
    tiny = settings.get('tiny_mvp') or {}
    return (str(local.get('user_name') or '').strip() if isinstance(local, dict) else '') or (
        str(tiny.get('mic_user_name') or '').strip() if isinstance(tiny, dict) else '') or _HUMAN_NAME


def build_local_room_settings(
    saved_settings: dict[str, Any], *, joined: bool, muted: bool, input_mode: str
) -> dict[str, Any]:
    settings = copy.deepcopy(saved_settings if isinstance(saved_settings, dict) else {})
    mode = _input_mode(input_mode)
    settings["bridge_mode"] = "tiny_mvp"
    settings["start_on_nc_launch"] = False
    settings["auto_start_bridge"] = False
    settings["_local_room_session"] = True
    tiny = settings.setdefault("tiny_mvp", {})
    if not isinstance(tiny, dict):
        tiny = {}
        settings["tiny_mvp"] = tiny
    tiny.update(
        {
            "start_with_gui": False,
            "capture_mic": bool(joined and not muted and mode != "text_only"),
            "mic_user_id": _HUMAN_ID,
            "mic_user_name": _local_room_user_name(settings),
        }
    )
    room_router = settings.setdefault("room_router", {})
    if not isinstance(room_router, dict):
        room_router = {}
        settings["room_router"] = room_router
    apply_behavior(settings, behavior_from_settings(settings), revision=uuid.uuid4().hex)
    marked = [
        copy.deepcopy(bot)
        for bot in room_cast(settings)
        if isinstance(bot, dict)
        and bool(bot.get("enabled", True))
        and _bot_role(bot) in _ROLE_ORDER
    ]
    marked.sort(key=lambda bot: _ROLE_ORDER.index(_bot_role(bot)))
    moderators = [bot for bot in marked if _bot_role(bot) == "moderator"]
    if len(moderators) != 1:
        raise ValueError("Local room needs exactly one enabled saved moderator bot. Restore or enable it in Bots.")
    if not any(_bot_role(bot) != "moderator" for bot in marked) and (settings.get('local_room') or {}).get('membership_version') != 1:
        raise ValueError("Local room needs at least one enabled saved debating bot. Restore or enable one in Bots.")
    settings["bots"] = marked
    return settings


class LocalRoomController:
    def __init__(self, addon) -> None:
        self._addon = addon
        self._lock = threading.RLock()
        self._operation_lock = threading.RLock()
        self._phase = "idle"
        self._joined = True
        self._muted = False
        self._error = ""
        self._owned = False
        self._tearing_down = False
        self._settings: dict[str, Any] | None = None
        self._messages: list[dict[str, str]] = []
        self._next_message_id = 1
        self._seen_flow_indexes: set[int] = set()
        self._mic_device: str | None = None
        self._last_mic_gate_diagnostic = ""
        self._desired_cast = None
        self._paused = False
        self._continuing = False
        self._stop_request = None
        self._stop_thread = None
        self._membership_epoch = 0
        self._membership_jobs = {}
        self._membership_io_lock = threading.RLock()

    @staticmethod
    def preview_participants(
        joined: bool = True, bots: list[dict[str, Any]] | None = None, user_name: str = _HUMAN_NAME
    ) -> list[dict[str, Any]]:
        cast = _enabled_cast_bots(bots if bots is not None else list(load_settings().get("bots") or []))
        human = [{
            "id": _HUMAN_ID,
            "name": user_name,
            "role": "human",
            "connected": True,
            "speaking": False,
        }] if joined else []
        return human + [
            {
                "id": str(bot.get("id") or ""),
                "name": str(bot.get("name") or bot.get("id") or "Bot"),
                "role": _bot_role(bot),
                "connected": False,
                "speaking": False,
                "persona_id": str(bot.get("local_room_persona_id") or ""),
                "avatar_path": str(bot.get("local_room_avatar_path") or ""),
                "voice_path": str((bot.get("persona") or {}).get("voice_clone_wav") or ""),
                "prompt": str((bot.get("persona") or {}).get("system_prompt") or ""),
            }
            for bot in cast
        ]

    def _preview_participants(self, joined: bool) -> list[dict[str, Any]]:
        bots = list((self._settings or {}).get("bots") or []) if self._settings is not None else self._desired_cast
        if bots is None:
            bots = room_cast(load_settings())
        resolved = [visible_member(bot) for bot in bots]
        participants = self.preview_participants(joined, resolved, self._user_name())
        self._add_reply_settings(participants, resolved)
        return participants

    def _add_reply_settings(self, participants, bots):
        from core.persona_overrides import resolve_persona_reply_settings

        capability = getattr(getattr(getattr(self._addon, 'context', None), 'capabilities', None), 'runtime_config', None)
        snapshot = getattr(capability, 'snapshot', None)
        try:
            runtime_config = dict(snapshot() or {}) if callable(snapshot) else {}
        except Exception:
            runtime_config = {}
        settings = self._settings if self._settings is not None else load_settings()
        base_chat = settings.get('chat') if isinstance(settings.get('chat'), dict) else {}
        live_settings = {
            str(getattr(instance, 'instance_id', '')): getattr(instance, 'settings', {})
            for instance in list(getattr(self._addon, '_bridge_instances', []) or [])
        } if self._phase == 'running' else {}
        by_id = {str(bot.get('id') or ''): bot for bot in bots}
        for participant in participants:
            if participant['role'] == 'human':
                continue
            bot = by_id.get(participant['id'], {})
            raw_chat = bot.get('chat') if isinstance(bot.get('chat'), dict) else {}
            chat = _deep_merge(base_chat, raw_chat)
            # Retained workers can receive live Chat updates independently of
            # the room controller's session copy. Their effective Chat wins.
            live = live_settings.get(participant['id'])
            live_chat = live.get('chat') if isinstance(live, dict) else None
            if isinstance(live_chat, dict):
                chat = copy.deepcopy(live_chat)
            overrides = bot.get('persona_overrides') if bot.get('local_room_persona_id') else None
            summary = resolve_persona_reply_settings(runtime_config, chat, overrides, local_room=True)
            inherited = resolve_persona_reply_settings(runtime_config, chat, {}, local_room=True)
            if 'context_entries' in raw_chat or chat.get('context_entries') != base_chat.get('context_entries'):
                inherited['context_source'] = 'participant'
                if summary['context_source'] != 'persona':
                    summary['context_source'] = 'participant'
            summary['inherited_defaults'] = inherited
            participant['reply_settings'] = summary

    def _user_name(self) -> str:
        return _local_room_user_name(self._settings if self._settings is not None else load_settings())

    def _refresh_linked_metadata(self):
        with self._lock:
            if not self._settings:
                return
            previous = self._settings.get('bots') or []
            current = [dict(visible_member(bot), **{key: copy.deepcopy(value) for key, value in bot.items()
                        if key.startswith('_local_room_')}) for bot in previous]
            if current == previous:
                return
            self._settings['bots'] = current
            settings = copy.deepcopy(self._settings) if self._phase == 'running' else None
        if settings is not None:
            # Persona content is resolved per request by each runtime server.
            # Only routing metadata needs a live update in the retained workers.
            publish = getattr(self._addon, 'publish_local_room_membership', None)
            if callable(publish):
                publish(settings)
            else:
                self._addon.apply_live_settings(settings=settings, sections=('room_router',))

    @property
    def session_settings(self) -> dict[str, Any] | None:
        with self._lock:
            return copy.deepcopy(self._settings) if self._settings is not None else None

    def snapshot(self) -> dict[str, Any]:
        self._refresh_linked_metadata()
        mic_sync_settings: dict[str, Any] | None = None
        restart_mic = False
        with self._lock:
            phase = self._phase
            joined = self._joined
            muted = self._muted
            input_mode = self._input_mode()
            if phase == "running" and self._settings is not None and not self._tearing_down:
                tiny = self._settings.get("tiny_mvp") if isinstance(self._settings.get("tiny_mvp"), dict) else {}
                previous_capture = bool(tiny.get("capture_mic"))
                self._refresh_capture_setting()
                capture_wanted = bool(tiny.get("capture_mic"))
                mic_error = str(getattr(self._addon, "_tiny_mvp_mic_error", "") or "").strip()
                running_check = getattr(self._addon, "_tiny_mvp_local_mic_running", None)
                current_device = self._audio_input_device()
                device_changed = self._mic_device is not None and current_device != self._mic_device
                capture_missing = False
                mic_running = False
                if capture_wanted and callable(running_check):
                    try:
                        mic_running = bool(running_check())
                        capture_missing = not mic_running
                    except Exception:
                        capture_missing = False
                if not capture_wanted:
                    if previous_capture:
                        mic_sync_settings = copy.deepcopy(self._settings)
                    self._clear_addon_mic_error()
                    self._mic_device = None
                else:
                    if self._mic_device is None:
                        self._mic_device = current_device
                    if device_changed:
                        self._clear_addon_mic_error()
                        mic_error = ""
                        restart_mic = mic_running
                    if capture_wanted != previous_capture or device_changed or (capture_missing and not mic_error):
                        self._mic_device = current_device
                        mic_sync_settings = copy.deepcopy(self._settings)
            else:
                self._mic_device = None
            visible_mic_error = ""
            if phase == "running" and self._settings is not None:
                tiny = self._settings.get("tiny_mvp") if isinstance(self._settings.get("tiny_mvp"), dict) else {}
                if bool(tiny.get("capture_mic")):
                    visible_mic_error = str(getattr(self._addon, "_tiny_mvp_mic_error", "") or "").strip()
            linked_errors = [bot.get('local_room_error') for bot in (self._settings or {}).get('bots', [])
                             if bot.get('local_room_error')]
            error = self._error or visible_mic_error or (linked_errors[0] if linked_errors else '')
            participants = self._preview_participants(joined)
            state = {}
            if phase == "running" and self._settings is not None:
                try:
                    state = _http_json("GET", f"{self._tiny_url()}/state", timeout=0.5)
                    self._paused = bool(state.get("paused", False))
                    if state.get('skip_error'):
                        error = ('Skip speech could not finish the reply: ' + str(state['skip_error'])
                                 + ' Choose the next speaker and Resume room.')
                    participants = self._participants_from_state(state, joined)
                    self._collect_room_messages(state)
                except Exception as exc:
                    error = str(exc)
            anonymous_available = True
            try:
                conversation = local_room_memory.load()
            except (OSError, ValueError, KeyError) as exc:
                error = 'Local room history is unavailable: ' + str(exc)
                conversation = dict(id='', topic='', messages=[], members={})
                anonymous_available = False
            try:
                saved_messages = local_room_memory.messages()
                has_history = (local_room_memory.has_history() if phase in {'idle', 'error'} and not self._owned
                    else bool(saved_messages) or bool(conversation.get('continuation')))
            except (OSError, ValueError, KeyError) as exc:
                error = 'Local room history is unavailable: ' + str(exc)
                saved_messages = []
                has_history = False
            for participant in participants:
                if participant['role'] != 'human':
                    try:
                        entries = local_room_memory.read_history(participant['id'])
                    except (OSError, ValueError) as exc:
                        participant['history_error'] = str(exc)
                        error = 'Local room history is unavailable: ' + str(exc)
                        entries = []
                    participant['history_count'] = len(entries)
                    has_history = has_history or bool(entries)
            bots_by_id = {bot['id']: bot for bot in (self._settings or {}).get('bots', [])}
            running_ids = {item.instance_id for item in getattr(self._addon, '_bridge_instances', []) if _instance_running(item)}
            for participant in participants:
                if participant['role'] == 'human':
                    continue
                bot = bots_by_id.get(participant['id'], {})
                membership_phase = bot.get('_local_room_phase', 'ready')
                participant.update(participant_id=participant['id'], bot_id=participant['id'],
                    admission_id=bot.get('_local_room_admission_id', ''), membership_phase=membership_phase,
                    membership_error=bot.get('_local_room_membership_error', ''),
                    desired=membership_phase not in {'leaving', 'left'}, present=participant['connected'],
                    eligible=membership_phase == 'ready' and participant['connected'], owned=participant['id'] in running_ids,
                    can_retry=membership_phase == 'failed' and not self._stop_request,
                    can_remove=participant['role'] != 'moderator' and membership_phase in {'ready', 'failed'} and not self._stop_request,
                    can_replace=membership_phase == 'ready' and not self._stop_request)
            result = {
                "phase": phase,
                'anonymous': conversation.get('anonymous', False),
                'capabilities': {'edit_anonymous': anonymous_available, 'local_microphone': True,
                    'edit_cast': phase in {'idle', 'error', 'running'} and not self._stop_request, 'live_membership': True},
                "user_name": self._user_name(),
                "joined": joined,
                "muted": muted,
                "input_mode": input_mode,
                "error": error,
                "participants": participants,
                "messages": copy.deepcopy(self._messages),
                "paused": self._paused if phase == "running" else False,
                "pausing": bool(state.get("pausing")) if phase == "running" else False,
                "stopping": self._stop_request is not None,
                "current_id": str(state.get("playback_owner_id") or state.get("current_id") or ""),
                "next_id": str(state.get("next_id") or "") if phase == "running" else str(
                    (conversation.get('continuation') or {}).get('next_id') or ''),
                "moderator": copy.deepcopy(state.get("moderator_state") or {}),
                "directive": copy.deepcopy(state.get("directive") or {}),
                "pending_recovery": copy.deepcopy(state.get("pending_recovery") or {}),
                "behavior": behavior_from_settings(self._settings if self._settings is not None else load_settings()),
                'conversation': {'id': conversation['id'], 'topic': conversation['topic'],
                    'has_history': has_history or bool(conversation.get('continuation')), 'continuing': self._continuing,
                    'saved': bool(conversation['id']), 'member_count': len(conversation['members'])},
            }
            if phase != 'running' and saved_messages:
                result['messages'] = saved_messages
            result['display_messages'] = _local_display_messages(result['messages'], state, conversation)
        if mic_sync_settings is not None:
            if restart_mic:
                stop_mic = getattr(self._addon, "_stop_tiny_mvp_local_mic", None)
                if callable(stop_mic):
                    stop_mic()
            self._addon._sync_tiny_mvp_local_mic(mic_sync_settings)
        return result

    @contextmanager
    def resource_maintenance(self):
        if not self._operation_lock.acquire(blocking=False):
            raise RuntimeError('Local room is starting or stopping.')
        try:
            yield
        finally:
            self._operation_lock.release()

    def start(self, saved_settings: dict[str, Any]) -> dict[str, Any]:
        with self._operation_lock:
            with self._lock:
                if self._owned and self._tearing_down:
                    raise RuntimeError('The room is still stopping. Retry Stop room before starting again.')
                if self._phase in {"starting", "running"}:
                    return self.snapshot()
                running = [item for item in list(getattr(self._addon, "_bridge_instances", []) or []) if _instance_running(item)]
                if running:
                    raise RuntimeError("Another Discord/TinyMVP bridge is already running. Stop it explicitly before starting Local room.")
                mode = self._input_mode()
                if self._main_runtime_owns_microphone():
                    raise RuntimeError("Stop the normal chat engine before starting a Local room.")
                try:
                    source_settings = copy.deepcopy(saved_settings)
                    if self._desired_cast is not None:
                        source_settings.setdefault('local_room', {})['cast'] = persisted_cast(self._desired_cast)
                        source_settings['local_room']['membership_version'] = 1
                    session_settings = build_local_room_settings(
                        source_settings,
                        joined=self._joined,
                        muted=self._muted,
                        input_mode=mode,
                    )
                    entries = (source_settings.get('local_room') or {}).get('cast')
                    if isinstance(entries, list):
                        references = persisted_cast(entries)
                        if references != entries:
                            save_local_settings({'local_room': {'cast': references}})
                        session_settings['local_room']['cast'] = references
                    conversation = local_room_memory.prepare(session_settings['bots'])
                    session_settings['_local_room_conversation_id'] = conversation['id']
                    session_settings['_room_anonymous'] = conversation['anonymous']
                    for bot in session_settings['bots']:
                        bot['_local_room_admission_id'] = uuid.uuid4().hex
                        bot['_local_room_phase'] = 'ready'
                    self._membership_epoch += 1
                    self._continuing = bool(local_room_memory.messages()) or any(
                        local_room_memory.read_history(bot['id']) for bot in session_settings['bots'])
                except Exception as exc:
                    self._phase = "error"
                    self._error = str(exc) or exc.__class__.__name__
                    self._settings = None
                    raise
                self._phase = "starting"
                self._last_mic_gate_diagnostic = ""
                self._error = ""
                self._messages = local_room_memory.messages()
                self._seen_flow_indexes.clear()
                self._next_message_id = 1 + max((int(message['id']) for message in self._messages), default=0)
                self._settings = session_settings
                launch_settings = copy.deepcopy(self._settings)
            try:
                self._owned = True
                self._addon._start_instances_from_settings(
                    launch_settings, force=True, sync_tiny_mvp_mic=False
                )
                running_ids = {
                    str(getattr(item, "instance_id", "") or "")
                    for item in list(getattr(self._addon, "_bridge_instances", []) or [])
                    if _instance_running(item)
                }
                expected = self._cast_ids()
                if running_ids != expected:
                    missing = sorted(expected - running_ids)
                    raise RuntimeError(
                        "Local room could not start its saved participants"
                        + (f": {', '.join(missing)}." if missing else ".")
                    )
                ready_state = self._wait_for_ready()
                moderator_id = self._bot_id_for_role("moderator")
                moderator_result = _http_json(
                    "POST",
                    f"{self._tiny_url()}/moderator",
                    {"action": "moderator_set_enforcer", "target_bot_id": moderator_id, "reason": "Local room startup"},
                    timeout=1.5,
                )
                moderator_state = dict((moderator_result.get("state") or ready_state).get("moderator_state") or {})
                if moderator_state.get("enforcer_bot_id") != moderator_id:
                    raise RuntimeError("Local room moderator assignment was not confirmed.")
                self._room_request('local-room/behavior', {'behavior': behavior_from_settings(self._settings),
                    'revision': self._settings['room_router']['local_room_behavior_revision']})
                with self._lock:
                    self._refresh_capture_setting()
                    self._phase = "running"
                    self._mic_device = self._audio_input_device() if self._microphone_wanted(self._input_mode()) else None
                self._sync_human_presence()
                self._addon._sync_tiny_mvp_local_mic(copy.deepcopy(self._settings))
                try:
                    from .linked_personas import cleanup_legacy_assets
                    cleanup_legacy_assets()
                except OSError:
                    pass  # Cleanup must never prevent a room from starting.
                if not self._restore_continuation():
                    self._open_room_once()
            except Exception as exc:
                with self._lock:
                    self._phase = "error"
                    self._error = str(exc) or exc.__class__.__name__
                if self._owned:
                    try:
                        self._addon.stop_bridge_instances()
                    except Exception:
                        pass
                with self._lock:
                    self._owned = False
                    self._settings = None
                raise
            return self.snapshot()

    def stop_after_turn(self) -> dict[str, Any]:
        """The user-facing Stop action drains the current turn off the UI thread."""
        with self._lock:
            if self._stop_request is not None:
                return self.snapshot()
            running = self._phase == "running" and self._owned and not self._tearing_down
        if not running:
            return self.stop()
        with self._lock:
            if self._stop_request is not None:
                return self.snapshot()
            self._require_owned_room()
            self._room_request('moderator', {'action': 'moderator_pause_after_turn',
                'reason': 'Finish the current turn before stopping the room'})
            token = object()
            self._stop_request = token
            self._stop_thread = threading.Thread(target=self._finish_stopping,
                args=(token,), name='Local room finish and stop', daemon=True)
            self._stop_thread.start()
        return self.snapshot()

    def _finish_stopping(self, token) -> None:
        try:
            while True:
                with self._lock:
                    if self._stop_request is not token or not self._owned:
                        return
                    url = self._tiny_url()
                state = _http_json('GET', f'{url}/state', timeout=0.5)
                if not state.get('pausing') and not state.get('skip_delivery_pending'):
                    self.stop(save_continuation=True, expected_request=token)
                    return
                time.sleep(0.1)
        except Exception as exc:
            with self._lock:
                if self._stop_request is token:
                    self._stop_request = None
                    self._error = 'The room could not finish stopping: ' + str(exc)

    def _save_continuation(self) -> None:
        state = _http_json('GET', f'{self._tiny_url()}/state', timeout=0.5)
        moderator = state.get('moderator_state') or {}
        directive = state.get('directive') or {}
        saved_directive = ({key: directive[key] for key in ('kind', 'text', 'moderator_id')}
                           if directive.get('status') in {'queued', 'preparing'} else {})
        local_room_memory.update(continuation={
            'directive': saved_directive,
            'next_id': str(state.get('next_id') or (_HUMAN_ID if state.get('current_id') == _HUMAN_ID and self._joined else '')),
            'muted_bot_ids': list(moderator.get('muted_bot_ids') or []),
            'human_muted': _HUMAN_ID in (moderator.get('muted_speaker_user_ids') or []),
            'speaker_lock': str(moderator.get('floor_target_bot_id') or moderator.get('floor_speaker_user_id') or ''),
            'allow_current_interruption': bool(moderator.get('allow_current_interruption')),
        })

    def _restore_continuation(self) -> bool:
        checkpoint = local_room_memory.load().get('continuation')
        if not isinstance(checkpoint, dict) or not checkpoint:
            return False
        self._continuing = True
        self._room_request('moderator', {'action': 'moderator_pause_after_turn'})
        moderator_id = self._bot_id_for_role('moderator')
        muted = set(checkpoint.get('muted_bot_ids') or []) & self._cast_ids() - {moderator_id}
        for participant_id in sorted(muted):
            self._room_request('moderator', {'action': 'moderator_mute', 'target_bot_id': participant_id})
        if checkpoint.get('human_muted'):
            self._room_request('moderator', {'action': 'moderator_mute_human', 'speaker_user_id': _HUMAN_ID})
        self._room_request('moderator', {'action': 'moderator_set_current_interruption',
            'allow_current_interruption': bool(checkpoint.get('allow_current_interruption'))})
        locked = str(checkpoint.get('speaker_lock') or '')
        if locked in self._cast_ids() - muted or (locked == _HUMAN_ID and self._joined and not checkpoint.get('human_muted')):
            self.control('only', locked)
        next_id = str(checkpoint.get('next_id') or '')
        if next_id and (next_id not in self._cast_ids() | ({_HUMAN_ID} if self._joined else set())
                        or next_id in muted or (next_id == _HUMAN_ID and checkpoint.get('human_muted'))):
            self._error = 'The saved next speaker is unavailable. Choose another participant and Resume room.'
            return True  # Keep the saved handoff and wait for an explicit choice.
        directive = checkpoint.get('directive') or {}
        if directive and directive.get('moderator_id') not in self._cast_ids() - muted:
            self._error = 'The saved guidance target is unavailable. Choose the next speaker and Resume room.'
            return True
        if directive:
            self._room_request('local-room/directive', {**directive, 'restore': True,
                'conversation_id': local_room_memory.load()['id']})
        elif next_id:
            self.control('next', next_id)
        self.control('resume')
        if not next_id and not directive:
            self._start_bots_only_opening()
        return True

    def stop(self, *, save_continuation: bool = False, expected_request=None,
             unload_models: bool = True) -> dict[str, Any]:
        with self._operation_lock:
            with self._lock:
                if expected_request is not None and self._stop_request is not expected_request:
                    return self.snapshot()
                self._membership_epoch += 1
                owned = self._owned
            if owned and save_continuation:
                self._save_continuation()  # A failed write leaves the held room running.
            if owned:
                try:
                    self.snapshot()  # Capture speech completed since the last UI poll.
                    try:
                        self._room_request('local-room/directive', {'action': 'cancel', 'reason': 'Room stopped.'})
                    except Exception:
                        # The room may already be gone. Stopping its workers below
                        # also prevents an unacknowledged action from running later.
                        pass
                finally:
                    with self._lock:
                        self._tearing_down = True
                    self._addon.stop_bridge_instances()
            with self._lock:
                if self._settings and any(bot.get('_local_room_departing') for bot in self._settings['bots']):
                    retained = []
                    for bot in self._settings['bots']:
                        if bot.get('_local_room_departing'):
                            if bot.get('_local_room_replacement'):
                                retained.append(copy.deepcopy(bot['_local_room_replacement']))
                        else:
                            retained.append(bot)
                    self._settings['bots'] = retained
                    try:
                        self._persist_membership()
                    except Exception as exc:
                        self._error = 'Local room stopped; saving its participant changes failed: ' + str(exc)
                self._owned = False
                self._settings = None
                self._paused = False
                self._stop_request = None
                self._phase = "idle"
                self._tearing_down = False
                self._error = ""
                self._mic_device = None
                self._clear_addon_mic_error()
            if owned and unload_models:
                speech = getattr(getattr(getattr(self._addon, 'context', None), 'capabilities', None), 'speech', None)
                release = getattr(speech, 'release_idle_models', None)
                if callable(release):
                    from .runtime_server import DiscordVoiceRuntimeServer
                    # All endpoints are fenced. Drain the last in-flight synthesis
                    # before unloading, so a cancelled request cannot reload it.
                    with DiscordVoiceRuntimeServer._TTS_SYNTHESIS_LOCK:
                        try:
                            result = release()
                            if isinstance(result, dict) and not result.get('ok', True):
                                raise RuntimeError(result.get('message') or 'Speech model cleanup failed.')
                        except Exception as exc:
                            with self._lock:
                                self._error = 'Local room stopped; model cleanup failed: ' + str(exc)
                        finally:
                            DiscordVoiceRuntimeServer._GLOBAL_TTS_READY_KEY = None
            return self.snapshot()

    def new_conversation(self, *, start=True) -> dict[str, Any]:
        if self._main_runtime_owns_microphone():
            raise RuntimeError("Stop the normal chat engine before starting a Local room.")
        saved_settings = load_settings()
        with self._lock:
            if self._phase == "starting":
                raise RuntimeError("Wait for Local room to finish starting.")
            if not start and (self._phase not in {'idle', 'error'} or self._owned):
                raise RuntimeError('Stop the Local room before preparing a stopped conversation.')
            session_settings = self._settings
            if session_settings is None:
                session_settings = build_local_room_settings(
                    saved_settings,
                    joined=self._joined,
                    muted=self._muted,
                    input_mode=self._input_mode(),
                )
            running = self._phase == "running" and self._owned
        if running:
            self.stop(unload_models=False)
        try:
            if not (local_room_memory.INSTANCE_ROOT/'local_room/conversation.json').exists():
                local_room_memory.prepare(session_settings['bots'])
            local_room_memory.reset()
        except Exception as exc:
            with self._lock:
                self._phase = "error"
                self._error = str(exc) or exc.__class__.__name__
            raise
        if not start:
            with self._lock:
                self._settings = None
                self._phase, self._error = 'idle', ''
                self._messages = []
                self._seen_flow_indexes.clear()
                self._next_message_id = 1
                self._continuing = self._paused = False
                self._stop_request = None
            return self.snapshot()
        return self.start(saved_settings)

    def history(self, participant_id):
        participant = next((p for p in self._preview_participants(self._joined)
                            if p['id'] == participant_id and p['role'] != 'human'), None)
        if participant is None:
            raise ValueError('Choose a participant in this Local room.')
        settings = self._settings or load_settings()
        bot = next((b for b in settings.get('bots', []) if b.get('id') == participant_id), {})
        value = (bot.get('chat') or {}).get('context_entries', (settings.get('chat') or {}).get('context_entries', 20))
        try:
            limit = max(0, int(value)) if value is not None and str(value).strip() else 20
        except (TypeError, ValueError):
            limit = 20
        entries = local_room_memory.read_history(participant_id)
        return dict(participant_id=participant_id, conversation_id=local_room_memory.load()['id'],
                    entries=entries, context_entries=limit, count=len(entries))

    def set_topic(self, topic):
        text = str(topic or '').strip()
        local_room_memory.prepare(self._editable_cast())
        local_room_memory.update(topic=text)
        return self.snapshot()

    def set_anonymous(self, anonymous):
        if not isinstance(anonymous, bool):
            raise ValueError('Anonymous must be enabled or disabled.')
        with self._operation_lock, self._lock:
            previous = local_room_memory.load()['anonymous']
            owned_ids = self._cast_ids() if self._owned else set()
            apply_anonymous(self._addon, self._settings, owned_ids, anonymous, previous,
                lambda value: local_room_memory.update(anonymous=value))
            return self.snapshot()

    def join(self) -> dict[str, Any]:
        return self._set_joined(True)

    def leave(self) -> dict[str, Any]:
        return self._set_joined(False)

    def _set_joined(self, joined: bool) -> dict[str, Any]:
        mic_sync_settings: dict[str, Any] | None = None
        departure_state: dict[str, Any] | None = None
        with self._lock:
            self._joined = bool(joined)
            self._refresh_capture_setting()
            if self._phase == "running":
                departure_state = self._sync_human_presence()
                mic_sync_settings = copy.deepcopy(self._settings)
                if not self._microphone_wanted(self._input_mode()):
                    self._mic_device = None
                    self._clear_addon_mic_error()
                else:
                    self._mic_device = self._audio_input_device()
        if mic_sync_settings is not None:
            self._addon._sync_tiny_mvp_local_mic(mic_sync_settings)
        if departure_state is not None:
            with self._lock:
                if self._phase == "running" and not self._joined:
                    self._handoff_human_floor_after_leave(departure_state)
        return self.snapshot()

    def set_muted(self, muted: bool) -> dict[str, Any]:
        mic_sync_settings: dict[str, Any] | None = None
        with self._lock:
            self._muted = bool(muted)
            self._refresh_capture_setting()
            if self._phase == "running":
                mic_sync_settings = copy.deepcopy(self._settings)
                if not self._microphone_wanted(self._input_mode()):
                    self._mic_device = None
                    self._clear_addon_mic_error()
                else:
                    self._mic_device = self._audio_input_device()
        if mic_sync_settings is not None:
            self._addon._sync_tiny_mvp_local_mic(mic_sync_settings)
        return self.snapshot()

    def send(self, text: str) -> dict[str, Any]:
        message = str(text or "").strip()
        if not message:
            raise ValueError("Local room message text is required.")
        with self._lock:
            if self._phase != "running":
                raise RuntimeError("Local room is not running.")
            if self._paused:
                raise RuntimeError("Resume Local room before sending a message.")
            if not self._joined:
                raise RuntimeError("Join Local room before sending a message.")
            _http_json(
                "POST",
                f"{self._tiny_url()}/speech",
                {"speaker_id": _HUMAN_ID, "text": message, "reason": "Local room text chat"},
                timeout=1.5,
            )
            self._addon._route_tiny_mvp_text(message, copy.deepcopy(self._settings))
            return self.snapshot()

    def _require_owned_room(self):
        if self._phase != "running" or not self._owned or not self._settings:
            raise RuntimeError("Start the Local room before using its conversation controls.")
        running = {str(item.instance_id) for item in getattr(self._addon, "_bridge_instances", [])
                   if _instance_running(item)}
        expected = {bot['id'] for bot in self._settings['bots']
                    if bot.get('_local_room_phase', 'ready') in {'ready', 'leaving'}}
        if not expected <= running or not running <= self._cast_ids():
            raise RuntimeError("Local room ownership changed. Stop and start the room before controlling participants.")

    def _room_request(self, path, payload):
        result = _http_json("POST", f"{self._tiny_url()}/{path}", payload, timeout=1.5)
        if result.get("ok") is False:
            raise RuntimeError(str(result.get("error") or "The Local room did not accept this action."))
        return result

    def _update_cast(self, bots):
        validate_cast(bots, allow_moderator_only=True)
        with self._operation_lock:
            with self._lock:
                if self._phase == "starting":
                    raise RuntimeError("Wait for Local room startup to finish.")
                running = self._phase == "running"
                if running:
                    self._require_owned_room()
                old = copy.deepcopy(self._settings)
                source = copy.deepcopy(load_settings())
                source.setdefault('local_room', {})['cast'] = persisted_cast(bots)
                source['local_room']['membership_version'] = 1
                candidate = build_local_room_settings(source, joined=self._joined,
                    muted=self._muted, input_mode=self._input_mode())
                if running and old:
                    # Membership edits reuse the running room's rule and generation.
                    apply_behavior(candidate, behavior_from_settings(old),
                        revision=old['room_router']['local_room_behavior_revision'])
                conversation = local_room_memory.prepare(candidate['bots'])
                candidate['_local_room_conversation_id'] = conversation['id']
                candidate['_room_anonymous'] = conversation['anonymous']
                previous = {b['id']: b for b in (old or {}).get('bots', [])}
                for bot in candidate['bots']:
                    bot['_local_room_admission_id'] = previous.get(bot['id'], {}).get('_local_room_admission_id') or uuid.uuid4().hex
                try:
                    if running:
                        self._addon.sync_local_room_instances(candidate)
                        self._wait_for_ready(expected={bot["id"] for bot in candidate["bots"]})
                        moderator_id = next(bot["id"] for bot in bots if _bot_role(bot) == "moderator")
                        result = self._room_request("moderator", {"action": "moderator_set_enforcer",
                            "target_bot_id": moderator_id, "reason": "Local room cast updated"})
                        if (result.get("state") or {}).get("moderator_state", {}).get("enforcer_bot_id") != moderator_id:
                            raise RuntimeError("Local room moderator assignment was not confirmed.")
                    save_local_settings({"local_room": {"cast": persisted_cast(bots), 'membership_version': 1}})
                except Exception:
                    if running and old:
                        try:
                            self._addon.sync_local_room_instances(old)
                            old_moderator = next(bot["id"] for bot in old["bots"] if _bot_role(bot) == "moderator")
                            self._room_request("moderator", {"action": "moderator_set_enforcer",
                                "target_bot_id": old_moderator, "reason": "Restore Local room cast"})
                        except Exception as recovery_error:
                            self._phase = "error"
                            self._error = f"Cast update failed and restoration needs attention: {recovery_error}"
                    raise
                self._desired_cast = copy.deepcopy(bots)
                if running:
                    self._settings = candidate
        return self.snapshot()

    def _editable_cast(self):
        if self._desired_cast is not None:
            return copy.deepcopy(self._desired_cast)
        if self._settings:
            return copy.deepcopy(self._settings["bots"])
        return room_cast(load_settings())

    def add_persona(self, record, bot_id=''):
        bot = resolve_member(member_reference(record.get('id')))
        with self._lock:
            bots = self._editable_cast()
            if any(item["id"] == bot["id"] for item in bots):
                return self.snapshot()
            if self._phase != 'running':
                return self._update_cast([*bots, bot])
        return self._admit_member(bot)

    def _persist_membership(self):
        bots = list((self._settings or {}).get('bots') or [])
        self._settings.setdefault('local_room', {}).update(cast=persisted_cast(bots), membership_version=1)
        with local_room_memory.LOCK:
            state = local_room_memory.update_membership(bots)
            drains = [bot for bot in bots if '_local_room_drain_turn_id' in bot]
            if drains:
                membership = state['membership']
                for bot in drains:
                    membership[bot['id']]['drain_turn_id'] = bot['_local_room_drain_turn_id']
                local_room_memory.update(membership=membership)
        save_local_settings({'local_room': {'cast': persisted_cast(bots), 'membership_version': 1}})
        self._desired_cast = copy.deepcopy(bots)

    def _member_job_valid(self, identity, admission, epoch):
        return (epoch == self._membership_epoch and self._phase == 'running' and self._owned and self._stop_request is None
            and any(bot['id'] == identity and bot.get('_local_room_admission_id') == admission
                    for bot in (self._settings or {}).get('bots', [])))

    def _launch_member_job(self, identity, target):
        bot = next(bot for bot in self._settings['bots'] if bot['id'] == identity)
        admission, epoch = bot['_local_room_admission_id'], self._membership_epoch
        thread = threading.Thread(target=self._run_member_job,
            args=(identity, admission, epoch, target), name='Local room membership ' + identity, daemon=True)
        self._membership_jobs[identity] = thread
        thread.start()

    def _runtime_cast_settings(self, *, include='', exclude=''):
        candidate = copy.deepcopy(self._settings)
        candidate['_local_room_membership_epoch'] = self._membership_epoch
        present = {item.instance_id for item in getattr(self._addon, '_bridge_instances', []) if _instance_running(item)}
        candidate['bots'] = [bot for bot in candidate['bots'] if bot['id'] != exclude
                             and (bot['id'] in present or bot['id'] == include)]
        return candidate

    def _admit_member(self, bot):
        with self._operation_lock, self._lock:
            self._require_owned_room()
            if self._stop_request:
                raise RuntimeError('Wait for Local room stop to finish.')
            if any(item['id'] == bot['id'] for item in self._settings['bots']):
                raise ValueError('This persona is already present or changing membership.')
            bot = copy.deepcopy(bot)
            bot.update(_local_room_admission_id=uuid.uuid4().hex, _local_room_phase='joining')
            validate_cast([*self._settings['bots'], bot], allow_moderator_only=True)
            self._settings['bots'].append(bot)
            try:
                self._persist_membership()
            except Exception:
                self._settings['bots'].remove(bot)
                raise
            self._launch_member_job(bot['id'], 'join')
        return self.snapshot()

    def request_remove(self, participant_id):
        return self._depart_member(participant_id)

    def replace_persona(self, participant_id, record, bot_id=''):
        replacement = resolve_member(member_reference(record.get('id')))
        return self._depart_member(participant_id, replacement=replacement)

    def _depart_member(self, participant_id, *, replacement=None):
        with self._operation_lock, self._lock:
            bots = self._editable_cast()
            selected = next((bot for bot in bots if bot['id'] == participant_id), None)
            if selected is None:
                raise ValueError('Choose a participant in this Local room.')
            if replacement is None and _bot_role(selected) == 'moderator':
                raise ValueError('Keep exactly one moderator in the Local room.')
            if replacement is not None:
                if any(bot['id'] == replacement['id'] for bot in bots):
                    raise ValueError('This persona is already in the Local room.')
                replacement = copy.deepcopy(replacement)
                replacement['local_room_role'] = _bot_role(selected)
            if self._phase != 'running':
                return self._update_cast([bot for bot in bots if bot['id'] != participant_id]
                                         + ([replacement] if replacement else []))
            self._require_owned_room()
            if self._stop_request:
                raise RuntimeError('Wait for Local room stop to finish.')
            bot = next(bot for bot in self._settings['bots'] if bot['id'] == participant_id)
            if bot.get('_local_room_phase', 'ready') == 'leaving':
                return self.snapshot()
            if bot.get('_local_room_phase', 'ready') == 'joining':
                raise ValueError('Wait for this persona to finish joining.')
            bot.update(_local_room_phase='leaving', _local_room_membership_error='')
            if replacement is not None:
                bot['_local_room_replacement'] = replacement
            self._persist_membership()
            bot['_local_room_departing'] = True
            self._launch_member_job(participant_id, 'depart')
        return self.snapshot()

    def retry_join(self, participant_id):
        with self._operation_lock, self._lock:
            self._require_owned_room()
            bot = next((bot for bot in self._settings['bots'] if bot['id'] == participant_id), None)
            if not bot or bot.get('_local_room_phase') != 'failed':
                raise ValueError('Choose a failed participant to retry.')
            target = 'depart' if bot.get('_local_room_departing') else 'join'
            if target == 'join':
                bot['_local_room_admission_id'] = uuid.uuid4().hex
            bot.update(_local_room_phase='leaving' if target == 'depart' else 'joining', _local_room_membership_error='')
            self._persist_membership()
            self._launch_member_job(participant_id, target)
        return self.snapshot()

    def _run_member_job(self, identity, admission, epoch, target):
        try:
            if target == 'depart':
                with self._lock:
                    if not self._member_job_valid(identity, admission, epoch):
                        return
                    bot = next(bot for bot in self._settings['bots'] if bot['id'] == identity)
                    bot['_local_room_departing'] = True
                    present = any(item.instance_id == identity and _instance_running(item)
                                  for item in getattr(self._addon, '_bridge_instances', []))
                if present:
                    response = self._room_request('participants/depart', {'id': identity, 'admission_id': admission})
                    with self._operation_lock, self._lock:
                        if not self._member_job_valid(identity, admission, epoch):
                            return
                        if response.get('admission_id') != admission:
                            raise RuntimeError('The Local room departure admission has changed.')
                        drain_turn = str(response.get('drain_turn_id') or '')
                        bot = next(bot for bot in self._settings['bots'] if bot['id'] == identity)
                        bot['_local_room_drain_turn_id'] = drain_turn
                        self._persist_membership()
                    errors_since = None
                    while True:
                        with self._lock:
                            if not self._member_job_valid(identity, admission, epoch):
                                return
                        try:
                            query = urllib.parse.urlencode({'id': identity, 'admission_id': admission})
                            status = _http_json('GET', f'{self._tiny_url()}/participants/departure?{query}', timeout=.5)
                            errors_since = None
                            if (status.get('admission_id') == admission and status.get('drain_turn_id') == drain_turn
                                    and status.get('delivered_settled') and status.get('drained')):
                                break
                        except Exception:
                            errors_since = errors_since or time.monotonic()
                            if time.monotonic() - errors_since > 5:
                                raise
                        time.sleep(.025)
            with self._membership_io_lock:
                with self._lock:
                    if not self._member_job_valid(identity, admission, epoch):
                        return
                    candidate = self._runtime_cast_settings(include=identity if target == 'join' else '',
                                                            exclude=identity if target == 'depart' else '')
                self._addon.sync_local_room_instances(candidate)
                if target == 'join':
                    self._wait_for_ready(expected={identity})
                    self._room_request('participants/admit', {'id': identity, 'admission_id': admission})
                with self._lock:
                    if not self._member_job_valid(identity, admission, epoch):
                        # The helper removes only instances of this captured admission.
                        cleanup = getattr(self._addon, 'stop_local_room_admission', None)
                        if callable(cleanup):
                            cleanup(identity, admission, conversation_id=candidate['_local_room_conversation_id'])
                        return
                    bot = next(bot for bot in self._settings['bots'] if bot['id'] == identity)
                    replacement = bot.get('_local_room_replacement') if target == 'depart' else None
                    if target == 'join':
                        bot['_local_room_phase'] = 'ready'
                        if _bot_role(bot) == 'moderator':
                            self._room_request('moderator', {'action': 'moderator_set_enforcer', 'target_bot_id': identity,
                                                           'reason': 'Local room moderator replacement'})
                    else:
                        self._collect_room_messages(_http_json('GET', f'{self._tiny_url()}/state', timeout=.5))
                        self._settings['bots'].remove(bot)
                        if replacement:
                            replacement = copy.deepcopy(replacement)
                            replacement.update(_local_room_phase='joining', _local_room_admission_id=uuid.uuid4().hex)
                            if _bot_role(bot) == 'moderator':
                                replacement['_local_room_restore'] = {key: copy.deepcopy(value) for key, value in bot.items()
                                    if not key.startswith('_local_room_')}
                            self._settings['bots'].append(replacement)
                    self._persist_membership()
                    if replacement:
                        self._launch_member_job(replacement['id'], 'join')
        except Exception as exc:
            if target == 'join':
                cleanup = getattr(self._addon, 'stop_local_room_admission', None)
                if callable(cleanup):
                    try:
                        cleanup(identity, admission, conversation_id=(self._settings or {}).get('_local_room_conversation_id', ''))
                    except Exception as cleanup_error:
                        exc = RuntimeError(f'{exc}; participant cleanup needs attention: {cleanup_error}')
            with self._lock:
                if self._member_job_valid(identity, admission, epoch):
                    bot = next(bot for bot in self._settings['bots'] if bot['id'] == identity)
                    bot.update(_local_room_phase='failed', _local_room_membership_error=str(exc))
                    try:
                        self._persist_membership()
                    except Exception as persistence_error:
                        bot['_local_room_membership_error'] += '; ' + str(persistence_error)
                    restore = bot.get('_local_room_restore') if target == 'join' else None
                    if restore:
                        restored = copy.deepcopy(restore)
                        restored.update(_local_room_phase='joining', _local_room_admission_id=uuid.uuid4().hex,
                                        _local_room_membership_error='')
                        self._settings['bots'].remove(bot)
                        self._settings['bots'].append(restored)
                        try:
                            self._persist_membership()
                            self._launch_member_job(restored['id'], 'join')
                        except Exception as restore_error:
                            restored.update(_local_room_phase='failed', _local_room_membership_error=str(restore_error))

    def set_user_name(self, name: str) -> dict[str, Any]:
        value = str(name or '').strip()
        if not value or any(ord(char) < 32 for char in value):
            raise ValueError('Enter a name on a single line for this Local room.')
        with self._operation_lock, self._lock:
            if self._phase == 'starting':
                raise RuntimeError('Wait for Local room startup to finish.')
            previous = copy.deepcopy(self._settings)
            running = self._phase == 'running'
            try:
                if running:
                    self._require_owned_room()
                    self._settings.setdefault('local_room', {})['user_name'] = value
                    self._settings.setdefault('tiny_mvp', {})['mic_user_name'] = value
                    self._sync_human_presence()
                save_local_settings({'local_room': {'user_name': value}})
            except Exception:
                self._settings = previous
                if running and previous is not None:
                    try:
                        self._sync_human_presence()
                    except Exception:
                        pass
                raise
            mic_settings = copy.deepcopy(self._settings) if running else None
        if mic_settings is not None:
            # Existing capture reads the live session each turn; no restart needed.
            self._addon._sync_tiny_mvp_local_mic(mic_settings)
        return self.snapshot()

    def save_behavior(self, value):
        behavior = normalize_behavior(value)
        with self._operation_lock:
            with self._lock:
                if self._phase == 'starting':
                    raise RuntimeError('Wait for Local room to finish starting before changing behavior.')
                running = self._phase == 'running' and self._owned and self._settings is not None
                previous = copy.deepcopy(self._settings)
                candidate = copy.deepcopy(self._settings if running else load_settings())
                previous_behavior = behavior_from_settings(candidate)
                apply_behavior(candidate, behavior, revision=uuid.uuid4().hex)
            try:
                if running:
                    self._room_request('local-room/behavior', {'behavior': behavior,
                        'revision': candidate['room_router']['local_room_behavior_revision']})
                    self._addon.apply_live_settings(settings=candidate, sections=('room_router',))
                save_local_settings({'local_room': {'behavior': behavior}})
            except Exception as exc:
                rollback_error = ''
                if running:
                    try:
                        self._addon.apply_live_settings(settings=previous, sections=('room_router',))
                        self._room_request('local-room/behavior', {'behavior': previous_behavior,
                            'revision': previous['room_router']['local_room_behavior_revision']})
                    except Exception as rollback:
                        rollback_error = ' Stop and start the room before continuing: ' + str(rollback)
                with self._lock:
                    self._error = 'Behavior was not saved: ' + str(exc) + rollback_error
                raise RuntimeError(self._error) from exc
            with self._lock:
                if running:
                    self._settings = candidate
                self._error = ''
            return self.snapshot()

    def control(self, action, participant_id="", text=""):
        action = str(action)
        participant_id = str(participant_id)
        if action == 'set_name':
            return self.set_user_name(text)
        if action == 'remove':
            return self.request_remove(participant_id)
        if action == 'retry':
            return self.retry_join(participant_id)
        if action == 'moderator':
            with self._lock:
                bots = self._editable_cast()
                selected = next((bot for bot in bots if bot["id"] == participant_id), None)
                if selected is None:
                    raise ValueError("Choose a participant in this Local room.")
                if action == "remove":
                    bots.remove(selected)
                else:
                    for bot in bots:
                        if _bot_role(bot) == "moderator":
                            bot["local_room_role"] = "participant"
                    selected["local_room_role"] = "moderator"
            return self._update_cast(bots)
        with self._lock:
            self._require_owned_room()
            targeted = action in {"next", "invite", "only", "mute", "unmute"}
            if targeted and any(bot['id'] == participant_id and bot.get('_local_room_phase', 'ready') != 'ready'
                                for bot in self._settings['bots']):
                raise ValueError('Choose a ready participant in this Local room.')
            if targeted and (participant_id not in self._cast_ids() | {_HUMAN_ID}
                             or (participant_id == _HUMAN_ID and not self._joined)):
                raise ValueError("Choose an available participant in this Local room.")
            human = participant_id == _HUMAN_ID
            payload = {"reason": "Local room control"}
            if targeted:
                payload.update({"speaker_user_id": _HUMAN_ID, "speaker_name": self._user_name()}
                               if human else {"target_bot_id": participant_id})
            commands = {
                "next": "moderator_route_next_human" if human else "moderator_route_next",
                "only": "moderator_give_human_floor" if human else "moderator_give_floor",
                "mute": "moderator_mute_human" if human else "moderator_mute",
                "unmute": "moderator_unmute_human" if human else "moderator_unmute",
                "clear_next": "moderator_clear_pending", "clear_floor": "moderator_clear_floor",
                "pause": "moderator_pause_after_turn", "stop_speech": "moderator_pause", "resume": "moderator_resume",
            }
            if action == 'skip_speech':
                self._room_request('local-room/skip-speech', {})
            elif action in commands:
                payload["action"] = commands[action]
                result = self._room_request("moderator", payload)
                state = result.get("state") or result
                self._paused = bool(state.get("paused", action in {"pause", "stop_speech"}))
                if action == 'resume' and local_room_memory.load().get('continuation'):
                    local_room_memory.update(continuation={})
                    if self._error.startswith(('The saved next speaker', 'The saved guidance')):
                        self._error = ''
            elif action == "invite":
                state = _http_json("GET", f"{self._tiny_url()}/state", timeout=0.5)
                if state.get("paused") or state.get("playback_owner_id"):
                    raise RuntimeError("Wait for speech to finish, or stop speech before inviting someone.")
                if human:
                    return self.control("next", _HUMAN_ID)
                self._room_request("call", {"target_id": participant_id, "reason": "Local room invitation"})
            elif action in {"guide", "announce"}:
                if self._paused:
                    raise RuntimeError("Resume the room before making an announcement.")
                if not str(text).strip():
                    raise ValueError("Enter guidance or text to say first.")
                target_id = participant_id or self._bot_id_for_role('moderator')
                target = next((b for b in self._settings['bots'] if b['id'] == target_id), None)
                if not target or target.get('_local_room_phase', 'ready') != 'ready':
                    raise ValueError('Choose a ready bot in this Local room.')
                self._room_request('local-room/directive', {'kind': 'guide' if action == 'guide' else 'say',
                    'text': str(text).strip(), 'moderator_id': target_id,
                    'conversation_id': local_room_memory.load()['id']})
            else:
                raise ValueError("Unknown Local room action.")
        return self.snapshot()

    def microphone_capture_allowed(self) -> bool:
        with self._lock:
            if self._paused or not self.microphone_capture_enabled():
                self._trace_mic_gate(f"Capture blocked: room={self._phase}, joined={self._joined}, muted={self._muted}, mode={self._input_mode()}")
                return False
            if self._input_mode() != "push_to_talk":
                self._trace_mic_gate("Voice activation enabled.")
                return True
            interaction = getattr(getattr(getattr(self._addon, "context", None), "capabilities", None), "interaction", None)
            snapshot = getattr(interaction, "snapshot", None)
            try:
                state = (snapshot() or {}) if callable(snapshot) else {}
                held = bool(state.get("push_to_talk_capture_held"))
                key = str(state.get("push_to_talk_hotkey") or "unknown")
                self._trace_mic_gate(f"PTT {key}: {'pressed' if held else 'released'}; capture field present={'push_to_talk_capture_held' in state}")
                return held
            except Exception as exc:
                self._trace_mic_gate(f"PTT check failed: {exc}")
                return False

    def _trace_mic_gate(self, message: str) -> None:
        # Emit transitions only; this gate is polled repeatedly during capture.
        if message != self._last_mic_gate_diagnostic:
            self._last_mic_gate_diagnostic = message
            print(f"[Local room mic] {message}", flush=True)

    def microphone_capture_enabled(self) -> bool:
        with self._lock:
            if self._phase != "running" or not self._microphone_wanted(self._input_mode()):
                return False
            tiny = self._settings.get("tiny_mvp") if isinstance(self._settings, dict) else {}
            return bool(isinstance(tiny, dict) and tiny.get("capture_mic"))

    def _input_mode(self) -> str:
        runtime_config = getattr(getattr(getattr(self._addon, "context", None), "capabilities", None), "runtime_config", None)
        getter = getattr(runtime_config, "get", None)
        try:
            value = getter("input_mode", "voice_activation") if callable(getter) else "voice_activation"
        except Exception:
            value = "voice_activation"
        return _input_mode(value)

    def _audio_input_device(self) -> str:
        runtime_config = getattr(getattr(getattr(self._addon, "context", None), "capabilities", None), "runtime_config", None)
        getter = getattr(runtime_config, "get", None)
        try:
            value = getter("audio_input_device", "Default Input") if callable(getter) else "Default Input"
        except Exception:
            value = "Default Input"
        return str(value or "Default Input").strip() or "Default Input"

    def _clear_addon_mic_error(self) -> None:
        if hasattr(self._addon, "_tiny_mvp_mic_error"):
            self._addon._tiny_mvp_mic_error = ""

    def _main_runtime_owns_microphone(self) -> bool:
        status_service = getattr(getattr(getattr(self._addon, "context", None), "capabilities", None), "runtime_status", None)
        snapshot = getattr(status_service, "snapshot", None)
        try:
            state = dict(snapshot() or {}) if callable(snapshot) else {}
        except Exception:
            return False
        return str(state.get("lifecycle_state") or "stopped").strip().lower() in {"starting", "running", "stopping", "initialized", "cleanup_pending", "cleanup_failed"}

    def _microphone_wanted(self, mode: str) -> bool:
        return bool(self._joined and not self._muted and mode != "text_only")

    def _refresh_capture_setting(self) -> None:
        if self._settings is None:
            return
        tiny = self._settings.setdefault("tiny_mvp", {})
        capture = self._microphone_wanted(self._input_mode())
        ownership_error = "The main NC runtime is already using microphone capture. Stop it before enabling Local room voice input."
        if capture and self._main_runtime_owns_microphone():
            capture = False
            self._error = ownership_error
        elif self._error == ownership_error:
            self._error = ""
        tiny["capture_mic"] = capture

    def _tiny_url(self) -> str:
        tiny = (self._settings or {}).get("tiny_mvp")
        return str((tiny if isinstance(tiny, dict) else {}).get("url") or "http://127.0.0.1:8788").rstrip("/")

    def _sync_human_presence(self) -> dict[str, Any] | None:
        if not self._joined:
            state = _http_json("GET", f"{self._tiny_url()}/state", timeout=0.5)
            if not any(item.get("id") == _HUMAN_ID for item in state.get("participants") or []):
                return
            # Remove routing eligibility and speaker locks before any bot recovery.
            _http_json("POST", f"{self._tiny_url()}/participants/disconnect", {"id": _HUMAN_ID}, timeout=1.5)
            _http_json("POST", f"{self._tiny_url()}/participants/remove", {"id": _HUMAN_ID}, timeout=1.5)
            return state
        _http_json(
            "POST",
            f"{self._tiny_url()}/participants/upsert",
            {"id": _HUMAN_ID, "name": self._user_name(), "type": "human", "connected": True},
            timeout=1.5,
        )

    def _open_room_once(self) -> None:
        if behavior_from_settings(self._settings or load_settings())['speaker_selection'] == 'manual':
            return
        if self._continuing or local_room_memory.load().get('topic'):
            self._start_bots_only_opening()
            return
        if self._joined:
            _http_json(
                "POST",
                f"{self._tiny_url()}/moderator",
                {
                    "action": "moderator_route_next_human",
                    "speaker_user_id": _HUMAN_ID,
                    "speaker_name": self._user_name(),
                    "reason": "Wait for the human topic",
                },
                timeout=1.5,
            )
            text = "Welcome. What topic would you like the room to discuss?"
            self._addon.send_instance_command(
                self._bot_id_for_role("moderator"),
                "send_message",
                {"text": text, "moderator_announcement": True},
            )
            return
        self._start_bots_only_opening()

    def _handoff_human_floor_after_leave(self, departure_state: dict[str, Any]) -> None:
        if departure_state.get("paused"):
            return
        # Removal already cleared human floor/next references; use the prior state
        # only to decide whether the bots need a new opening.
        if (str(departure_state.get("next_id") or "") == _HUMAN_ID
                or (str(departure_state.get("current_id") or "") == _HUMAN_ID
                    and not str(departure_state.get("playback_owner_id") or ""))):
            # Microphone shutdown may let another route or pause settle first.
            live = _http_json("GET", f"{self._tiny_url()}/state", timeout=0.5)
            if live.get("paused") or live.get("next_id") or live.get("pending_recovery"):
                return
            self._start_bots_only_opening()

    def _start_bots_only_opening(self) -> None:
        behavior = behavior_from_settings(self._settings or load_settings())
        if behavior['speaker_selection'] == 'manual' or not behavior['moderator_help']:
            return
        moderator_id = self._bot_id_for_role("moderator")
        fallback_id = self._fallback_bot_id()
        recovery = _http_json(
            "POST",
            f"{self._tiny_url()}/dead-air",
            {
                "reason": "Local room bots-only opening",
                "strategy": "selected_fallback",
                "fallback_target": fallback_id,
                "action_mode": "moderator_speaks_and_calls_next",
            },
            timeout=1.5,
        )
        if str(recovery.get("target_id") or "") != moderator_id:
            raise RuntimeError("Local room moderator opening route was not confirmed.")

    def _wait_for_ready(self, timeout: float = 5.0, *, expected=None) -> dict[str, Any]:
        deadline = time.monotonic() + max(0.1, float(timeout))
        expected = self._cast_ids() if expected is None else expected
        last_state: dict[str, Any] = {}
        while time.monotonic() < deadline:
            last_state = _http_json("GET", f"{self._tiny_url()}/state", timeout=0.5)
            connected = {
                str(item.get("id") or "")
                for item in list(last_state.get("participants") or [])
                if isinstance(item, dict) and bool(item.get("connected"))
            }
            if expected.issubset(connected):
                return last_state
            time.sleep(0.05)
        missing = sorted(expected - {
            str(item.get("id") or "")
            for item in list(last_state.get("participants") or [])
            if isinstance(item, dict) and bool(item.get("connected"))
        })
        raise RuntimeError(f"Local room participants did not become ready: {', '.join(missing) or 'unknown'}.")

    def _participants_from_state(self, state: dict[str, Any], joined: bool) -> list[dict[str, Any]]:
        by_id = {
            str(item.get("id") or ""): item
            for item in list((state or {}).get("participants") or [])
            if isinstance(item, dict)
        }
        playback_owner = str((state or {}).get("playback_owner_id") or "")
        floor_owner = playback_owner or str((state or {}).get("current_id") or "")
        result = self._preview_participants(joined)
        for item in result:
            live = by_id.get(item["id"])
            if live is not None:
                item["connected"] = bool(live.get("connected"))
                if not item.get('persona_id'):
                    item["name"] = str(live.get("name") or item["name"])
            item["speaking"] = bool(
                item["id"] == playback_owner
                or (live is not None and str(live.get("playback_state") or "") == "playing")
            )
            item["has_floor"] = bool(item["connected"] and item["id"] == floor_owner)
            moderator = state.get("moderator_state") or {}
            item["is_next"] = item["id"] == state.get("next_id")
            item["muted"] = item["id"] in (moderator.get("muted_speaker_user_ids" if item["role"] == "human" else "muted_bot_ids") or [])
            item["only"] = item["id"] in (moderator.get("only_bot_ids") or []) or item["id"] == moderator.get("floor_speaker_user_id")
        return result

    def _collect_room_messages(self, state: dict[str, Any]) -> None:
        if (local_room_memory.INSTANCE_ROOT/'local_room/transcript.jsonl').exists():
            self._messages = local_room_memory.messages()
            return
        changed = False
        # Historical speech keeps its speaker name even while that person observes.
        participants = {item["id"]: item["name"] for item in self._preview_participants(True)}
        for event in list((state or {}).get("route_flow") or []):
            if not isinstance(event, dict) or event.get("type") != "speech":
                continue
            try:
                index = int(event.get("index") or 0)
            except (TypeError, ValueError):
                index = 0
            if index and index in self._seen_flow_indexes:
                continue
            source_id = str(event.get("source_id") or "")
            raw = str(event.get("message") or "").strip()
            prefix = f"{participants.get(source_id, source_id)}: "
            text = raw[len(prefix):] if prefix and raw.startswith(prefix) else raw
            if text:
                self._append_message(participants.get(source_id, source_id or "Room"), text,
                                     stamp=str(event.get("time") or ""))
                changed = True
            if index:
                self._seen_flow_indexes.add(index)
        if changed:
            local_room_memory.update(messages=self._messages)

    def _append_message(self, name: str, text: str, *, stamp: str = "") -> None:
        self._messages.append({"id": str(self._next_message_id), "name": str(name),
                               "text": str(text), "time": stamp})
        self._next_message_id += 1

    def _cast_ids(self) -> set[str]:
        return {
            str(bot.get("id") or "")
            for bot in list((self._settings or {}).get("bots") or [])
            if isinstance(bot, dict) and str(bot.get("id") or "")
        }

    def _bot_id_for_role(self, role: str) -> str:
        matches = [
            str(bot.get("id") or "")
            for bot in list((self._settings or {}).get("bots") or [])
            if isinstance(bot, dict) and _bot_role(bot) == role and str(bot.get("id") or "")
        ]
        if len(matches) != 1:
            raise RuntimeError(f"Local room needs exactly one enabled saved {role} bot.")
        return matches[0]

    def _fallback_bot_id(self) -> str:
        for role in _ROLE_ORDER:
            if role == "moderator":
                continue
            matches = [
                str(bot.get("id") or "")
                for bot in list((self._settings or {}).get("bots") or [])
                if isinstance(bot, dict) and _bot_role(bot) == role and str(bot.get("id") or "")
            ]
            if matches:
                return matches[0]
        if ((self._settings or {}).get('local_room') or {}).get('membership_version') == 1:
            return self._bot_id_for_role('moderator')
        raise RuntimeError("Local room needs at least one enabled saved debating bot.")


def _input_mode(value: Any) -> str:
    mode = str(value or "voice_activation").strip().lower()
    return mode if mode in {"voice_activation", "push_to_talk", "text_only"} else "voice_activation"


def _bot_role(bot: dict[str, Any]) -> str:
    return str(bot.get("local_room_role") or "").strip().lower()


def _enabled_cast_bots(bots: list[Any]) -> list[dict[str, Any]]:
    result = [
        bot
        for bot in bots
        if isinstance(bot, dict)
        and bool(bot.get("enabled", True))
        and _bot_role(bot) in _ROLE_ORDER
    ]
    return sorted(result, key=lambda bot: _ROLE_ORDER.index(_bot_role(bot)))


def _instance_running(instance: Any) -> bool:
    process = getattr(instance, "process", None)
    if process is not None:
        try:
            if process.poll() is None:
                return True
        except Exception:
            pass
    return bool(getattr(getattr(instance, "runtime_server", None), "running", False))


def _http_json(method: str, url: str, payload: dict[str, Any] | None = None, *, timeout: float = 2.0) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(str(url), data=data, method=str(method).upper(), headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        result = json.loads(response.read().decode("utf-8"))
    return result if isinstance(result, dict) else {}

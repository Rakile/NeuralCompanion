"""Presentation-only controls for the embedded local room."""
import copy

from ui.qml_bridge.native_contracts import NativeChoice, NativeControl, NativeControlKind


_PENDING_DIRECTIVE_STATUSES = {"queued", "preparing", "delivering"}


def _directive(room):
    value = room.get("directive")
    return value if isinstance(value, dict) else {}


def local_room_controls(state, draft="", selected="", personas=(), persona_id="", announcement=""):
    room = copy.deepcopy(state or {})
    available = bool(room)
    phase = str(room.get("phase", "unavailable"))
    discord = room.get("mode") == "discord"
    stopped = available and phase in {"idle", "error", "stopped"} and not room.get("stopping")
    edit_cast = bool(room.get("capabilities", {}).get("edit_cast", stopped if discord else True))
    local_microphone = not discord and bool(room.get("capabilities", {}).get("local_microphone", True))
    joined = bool(room.get("joined", True))
    muted = bool(room.get("muted", False))
    live = available and phase == "running"
    stopping = bool(room.get("stopping"))
    running = live and not stopping
    paused = bool(room.get("paused"))
    directive = _directive(room)
    directive_pending = str(directive.get("status") or "").strip().lower() in _PENDING_DIRECTIVE_STATUSES
    guidance = str(announcement or "").strip()
    participants = list(room.get("participants") or [])
    target = next((p for p in participants if str(p.get("participant_id") or p.get("id")) == selected), None)
    bot = bool(target and target.get("role") != "human")
    member = bool(target and (target.get("role") != "human" or joined or discord))
    can_speak = member and not bool((target or {}).get("muted")) and (target or {}).get('membership_phase', 'ready') == 'ready'
    free_account = not discord or 'available_accounts' not in room or any(a.get('available') for a in room['available_accounts'])
    can_remove = bot and (target or {}).get('can_remove', edit_cast and target.get('role') != 'moderator' and len([p for p in participants if p.get('role') != 'human']) > 2)
    can_replace = bot and (target or {}).get('can_replace', edit_cast)
    saved_persona = next((p for p in personas if p.get("id") == persona_id), None)
    already_added = any(p.get("persona_id") == persona_id for p in participants) if persona_id else False
    controls = [NativeControl(
        "discord_local_room_state", "Local room", NativeControlKind.DISPLAY,
        section="Local room", value=phase, metadata={"roomState": room,
            "personaLibrary": list(personas), "selectedParticipantId": selected})]
    controls.extend((NativeControl(
        "discord_room_mode", "Room transport", NativeControlKind.CHOICE,
        section="Local room", value="discord" if discord else "local", enabled=stopped,
        choices=(NativeChoice("local", "Local"), NativeChoice("discord", "Discord"))),
        NativeControl("discord_room_anonymous", "Anonymous", NativeControlKind.BOOLEAN,
                      section="Local room", value=bool(room.get("anonymous", False)), default_value=False,
                      description="Hide which participants are human or AI.",
                      enabled=room.get("capabilities", {}).get("edit_anonymous") is True),
        NativeControl("discord_room_bot_binding", "Prepared bot", NativeControlKind.ACTION,
                      section="Local room", enabled=discord and edit_cast)))
    for suffix, label, enabled in (
        ("start", "Start room", available and phase in {"idle", "error"}),
        ("stop", "Stopping after current speaker…" if stopping else "Stop room", available and not stopping and phase in {"running", "starting", "error"}),
        ("new_conversation", "New conversation", (not discord or stopped) and available and not stopping and phase in {"idle", "running", "error"}),
        ("view_history", "View room history", available and phase in {"idle", "running"} and bot),
        ("set_topic", "Save topic", available and not stopping and phase != "starting"),
        ("save_name", "Save name", local_microphone and available and not stopping and phase != "starting"),
        ("save_behavior", "Save behavior", not discord and available and not stopping and phase in {"idle", "running", "error"}),
        ("join", "Leave conversation" if joined else "Join conversation", local_microphone and available and not stopping and phase != "starting"),
        ("mute", "Unmute mic" if muted else "Mute mic", local_microphone and available and not stopping and joined and phase != "starting"),
        ("send", "Send", running and (joined or discord) and not paused and bool(draft.strip())
         and (not discord or room.get('text_sender_available', True))),
        ("set_sender", "Send as", discord and available and not stopping and phase != 'starting'),
        ("pause", "Pause room", running and not paused),
        ("resume", "Resume room", running and paused),
        ("skip_speech", "Skip speech", not discord and running and bool(room.get("current_id")) and any(p.get("id") == room.get("current_id") and p.get("role") != "human" for p in participants)),
        ("stop_speech", "Stop speech & hold", live and (not paused or bool(room.get("pausing")))),
        ("next", "Speak next", running and can_speak),
        ("invite", "Invite now", running and can_speak and (not discord or bot) and not paused and not room.get("current_id")),
        ("only", "Only this speaker", running and can_speak),
        ("mute_participant", "Moderator stays unmuted" if (target or {}).get("role") == "moderator" else "Mute routing" if discord else "Mute participant",
         running and member and (target or {}).get("role") != "moderator" and not bool((target or {}).get("muted"))),
        ("unmute_participant", "Unmute routing" if discord else "Unmute participant", running and member and bool((target or {}).get("muted"))),
        ("set_moderator", "Make moderator", (stopped if discord else edit_cast) and available and not stopping and phase != "starting" and bot and target.get("role") != "moderator"),
        ("remove", "Remove from room", available and not stopping and phase != "starting" and can_remove),
        ("replace_persona", "Replace persona", available and not stopping and phase != "starting" and can_replace),
        ("retry_join", "Retry join", available and not stopping and bot and bool(target.get('can_retry'))),
        ("clear_next", "Clear next speaker", running),
        ("clear_floor", "Release speaker lock", running),
        ("guide", "Guide bot", running and not paused and bool(guidance) and not directive_pending and (not selected or (bot and can_speak and (not discord or target.get("role") == "moderator")))),
        ("announce", "Speak through bot", running and not paused and bool(guidance) and not directive_pending and (not selected or (bot and can_speak and (not discord or target.get("role") == "moderator")))),
        ("add_persona", "Add to room", edit_cast and available and not stopping and phase != "starting" and free_account and bool(saved_persona) and not already_added),
    ):
        controls.append(NativeControl(
            "discord_local_room_" + suffix, label, NativeControlKind.ACTION,
            section="Local room", enabled=enabled,
            description='No free prepared Discord account. Add an account in Discord setup or wait for cleanup.' if suffix == 'add_persona' and not free_account else ''))
    controls.append(NativeControl(
        "discord_local_room_message", "Message", NativeControlKind.TEXT,
        section="Local room", value=draft, enabled=running and (joined or discord) and not paused))
    for suffix, value in (("participant", selected), ("persona", persona_id), ("announcement", announcement)):
        controls.append(NativeControl("discord_local_room_" + suffix, suffix.title(), NativeControlKind.TEXT,
                                      section="Local room", value=value))
    return tuple(controls)


def local_room_action(control_id, state, draft, selected="", personas=(), persona_id="", announcement="", topic="", user_name="", behavior=None, sender_id=None):
    controls = {item.id: item for item in local_room_controls(state, draft, selected, personas, persona_id, announcement)}
    control = controls.get(control_id)
    if control is None or control.kind is not NativeControlKind.ACTION:
        raise KeyError(f"Unknown local room action {control_id!r}.")
    if not control.enabled:
        raise ValueError("This room action is not currently available.")
    suffix = control_id.removeprefix("discord_local_room_")
    target = next((p for p in state.get('participants', []) if str(p.get('participant_id') or p.get('id')) == selected), {})
    wire_id = str(target.get('id') or selected)
    if suffix == "join":
        return ("local_room_leave" if state.get("joined", True) else "local_room_join"), {}
    if suffix == "mute":
        return "local_room_mute", {"muted": not bool(state.get("muted"))}
    if suffix == "send":
        payload = {"text": draft.strip()}
        if state.get('mode') == 'discord' and sender_id is not None:
            payload['sender_id'] = str(sender_id)
        return "local_room_send", payload
    if suffix == 'set_sender':
        return 'local_room_control', dict(command='set_sender', participant_id=selected)
    if suffix == "add_persona":
        return "local_room_add_persona", {}
    if suffix == 'replace_persona':
        if not persona_id or not any(p.get('id') == persona_id for p in personas):
            raise ValueError('Choose an available saved Persona.')
        if any(p.get('persona_id') == persona_id for p in state.get('participants', [])):
            raise ValueError('This Persona is already in the room.')
        return 'local_room_replace_persona', dict(participant_id=selected, persona_id=persona_id)
    if suffix == 'retry_join':
        return 'local_room_retry_join', dict(participant_id=selected)
    if suffix == "view_history":
        return "local_room_history", {"participant_id": wire_id}
    if suffix == "save_behavior":
        if not isinstance(behavior, dict):
            raise ValueError("Provide the complete conversation behavior before saving.")
        return "local_room_save_behavior", {"behavior": copy.deepcopy(behavior)}
    if suffix == "set_topic":
        return "local_room_set_topic", {"topic": topic.strip()}
    if suffix == 'save_name':
        return 'local_room_control', {'command':'set_name','text':user_name.strip()}
    if suffix in {"next", "invite", "only", "mute_participant", "unmute_participant", "set_moderator", "remove"}:
        command = {"mute_participant": "mute", "unmute_participant": "unmute", "set_moderator": "moderator"}.get(suffix, suffix)
        return "local_room_control", {"command": command, "participant_id": selected if suffix in {'remove', 'set_moderator'} else wire_id}
    if suffix in {"guide", "announce"}:
        text = str(announcement or "").strip()
        return "local_room_control", {"command": suffix, "text": text, **({"participant_id": wire_id} if selected else {})}
    if suffix in {"pause", "resume", "stop_speech", "skip_speech", "clear_next", "clear_floor"}:
        return "local_room_control", {"command": suffix}
    return "local_room_" + suffix, {}

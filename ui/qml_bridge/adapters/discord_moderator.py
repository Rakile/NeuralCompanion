"""Read-only Discord moderator presentation; no transport or runtime ownership."""
from __future__ import annotations

from datetime import datetime
import json
from typing import Any


def _number(value: Any) -> int:
    try:
        return max(0, int(float(value or 0)))
    except (TypeError, ValueError, OverflowError):
        return 0


def _progress(node: dict, current: str, total: str) -> str:
    maximum = _number(node.get(total))
    return f"{min(_number(node.get(current)), maximum)}/{maximum}"


def participant_value(participant: dict) -> str:
    return json.dumps({key: str(participant.get(key) or "") for key in ("id", "name", "kind")})


def room_participants(instances: list[dict], moderator: dict) -> list[dict]:
    """Merge configured bots with their Discord identities, keeping user IDs."""
    found: dict[tuple[str, str], dict] = {}
    aliases: dict[str, set[str]] = {}
    for instance in instances:
        bot_id = str(instance.get("id") or "")
        if not bot_id:
            continue
        node = dict(instance.get("node_status") or {})
        running = bool(instance.get("runtime_connected"))
        if not running:
            node = {}
        found[("bot", bot_id)] = {
            "id": bot_id, "name": str(instance.get("name") or bot_id), "kind": "bot",
            "connected": node.get("state") == "connected", "running": running,
            "speaking": bool(node.get("speaking")), "listening": bool(node.get("listening")),
            "queued": _number(node.get("queued_audio")), "conflict": False,
        }
        for alias in (bot_id, instance.get("name"), instance.get("discord_bot_id"),
                      node.get("bot_id"), node.get("bot_name"), node.get("bot_tag")):
            if alias:
                aliases.setdefault(str(alias).casefold(), set()).add(bot_id)
    for instance in instances:
        node = dict(instance.get("node_status") or {})
        # A stopped process's last snapshot must not keep departed users active.
        if not instance.get("runtime_connected"):
            continue
        for raw in node.get("participants") or []:
            if not isinstance(raw, dict) or not str(raw.get("id") or "").strip():
                continue
            item_id = str(raw["id"])
            name = str(raw.get("name") or item_id)
            kind = "bot" if raw.get("is_bot") else "human"
            if kind == "bot":
                candidates = aliases.get(item_id.casefold(), set()) or aliases.get(name.casefold(), set())
                if len(candidates) == 1:
                    item_id = next(iter(candidates))
            key = (kind, item_id)
            previous = found.get(key, {})
            found[key] = {**previous, "id": item_id, "name": previous.get("name", name), "kind": kind,
                          "connected": True, "conflict": bool(previous.get("conflict") or raw.get("display_name_conflict"))}
    for row in found.values():
        bot = row["kind"] == "bot"
        item_id = row["id"]
        flags = []
        current = moderator.get("current_bot_id") if bot else dict(moderator.get("current_human_route") or {}).get("speaker_user_id")
        pending = dict(moderator.get("pending_route") or {}).get("target_bot_id") if bot else dict(moderator.get("pending_human_route") or {}).get("speaker_user_id")
        floor = moderator.get("floor_target_bot_id") if bot else moderator.get("floor_speaker_user_id")
        for flag, selected in (("current", current), ("next", pending), ("allowed", floor)):
            if selected and str(selected) == item_id:
                flags.append(flag)
        if item_id in (moderator.get("muted_bot_ids" if bot else "muted_speaker_user_ids") or []):
            flags.append("muted")
        if bot and item_id in (moderator.get("only_bot_ids") or []):
            flags.append("only")
        if row.get("conflict"):
            flags.append("name conflict")
        row["flags"] = flags
    return sorted(found.values(), key=lambda row: (row["name"].casefold(), row["kind"], row["id"]))


def route_line(entry: dict) -> str:
    try:
        stamp = datetime.fromtimestamp(_number(entry.get("at_ms")) / 1000).strftime("%H:%M:%S") if entry.get("at_ms") else "--:--:--"
    except (ValueError, OSError, OverflowError):
        stamp = "--:--:--"
    speaker = str(entry.get("speaker_name") or entry.get("speaker_bot_id") or "unknown")
    target = str(entry.get("target_name") or entry.get("target_bot_id") or "")
    route = target if target and entry.get("answer") else "no route"
    source = f" [{entry['source']}]" if entry.get("source") else ""
    reason = f" | {entry['reason']}" if entry.get("reason") else ""
    return f"{stamp}  {speaker} -> {route}{source}{reason}"


def moderator_view(instances: list[dict], moderator: dict, participants: list[dict],
                   target: str, selected: dict, selection_lost: bool, settings: dict) -> dict:
    running_ids = {str(i.get("id")) for i in instances if i.get("runtime_connected")}
    running = bool(running_ids)
    speaking = any(bool(dict(i.get("node_status") or {}).get("speaking")) for i in instances if str(i.get("id")) in running_ids)
    names = {str(i.get("id")): str(i.get("name") or i.get("id")) for i in instances}
    bot_target = selected.get("id") if selected.get("kind") == "bot" else (target if not selected else "")
    bot_available = bot_target in running_ids and not selection_lost
    selected_available = (selected.get("id") in running_ids if selected.get("kind") == "bot"
                          else bool(selected.get("connected"))) if selected else bot_available
    allowed = running and selected_available and not selected.get("conflict") and not selection_lost
    enabled = {key: bool(allowed) for key in (
        "discord_moderator_route_next_button", "discord_moderator_give_floor_button",
        "discord_moderator_mute_button", "discord_moderator_unmute_button")}
    enabled.update({key: running for key in (
        "discord_moderator_clear_pending_button", "discord_moderator_clear_floor_button",
        "discord_moderator_clear_button", "discord_moderator_stop_all_button",
        "discord_moderator_clear_all_queues_button", "discord_moderator_allow_interrupt_current_checkbox")})
    enforcer_running = str(moderator.get("enforcer_bot_id") or "") in running_ids
    enabled.update({
        "discord_moderator_call_on_button": bool(bot_available and not speaking),
        "discord_moderator_announce_button": bool(bot_available),
        "discord_moderator_set_enforcer_button": target in running_ids and not selection_lost,
        "discord_moderator_clear_enforcer_button": enforcer_running,
        "discord_moderator_enforce_mute_checkbox": enforcer_running,
    })
    current_bot = str(moderator.get("current_bot_id") or "")
    current_human = dict(moderator.get("current_human_route") or {})
    current = names.get(current_bot, current_bot) or str(current_human.get("speaker_name") or current_human.get("speaker_user_id") or "")
    next_bot = str(dict(moderator.get("pending_route") or {}).get("target_bot_id") or "")
    next_human = dict(moderator.get("pending_human_route") or {})
    next_name = names.get(next_bot, next_bot) or str(next_human.get("speaker_name") or next_human.get("speaker_user_id") or "")
    floor = str(moderator.get("floor_target_bot_id") or moderator.get("floor_speaker_name") or moderator.get("floor_speaker_user_id") or "")
    last_route = ""
    instance_rows = []
    for instance in instances:
        node = dict(instance.get("node_status") or {}) if str(instance.get("id")) in running_ids else {}
        decision = dict(node.get("last_route_decision") or {})
        route = str(decision.get("target_name") or decision.get("target_bot_id") or decision.get("reason") or "")
        if route:
            last_route = f"{instance.get('name') or instance.get('id')}: {route}"
        instance_rows.append({"value": str(instance.get("id") or ""), "cells": [
            str(instance.get("id") or ""), str(instance.get("name") or instance.get("id") or ""),
            str(node.get("state") or "stopped"), "yes" if node.get("speaking") else "no",
            "yes" if node.get("listening") else "no", str(_number(node.get("queued_audio"))),
            _progress(node, "render_ready_chunks", "render_total_chunks"),
            _progress(node, "playback_completed_chunks", "playback_total_chunks"), route or "—"]})
    warning = str(moderator.get("last_error") or "No moderator warning.")
    if selected.get("conflict"):
        warning = "Duplicate display name. Rename or alias this participant before routing."
    if selection_lost:
        warning = "The selected participant is no longer available. Choose a connected participant."
    selected_action = f"Selected participant: {selected.get('name')}" if selected else (f"Selected bot: {names.get(target, target)}" if target and not selection_lost else "Select a room participant to see the available moderator action.")
    next_action = (f"{next_name} is queued next; routing waits for the current speaker to finish." if next_name
                   else f"{floor} remains the allowed speaker until cleared." if floor
                   else "Choose Next to queue a participant after current speech." if current or speaking
                   else "Room is quiet. Use Call Target Now to make a bot speak.")
    badges = [f"{row['name']}: {', '.join(row['flags'])}" for row in participants if row["flags"]]
    summary = [("Now", current or ("Bot speech is active" if speaking else "Room is quiet")),
               ("Next", next_name or "automatic"), ("Badges", "; ".join(badges) or "No active moderator locks or queues."),
               ("Speaker lock", names.get(floor, floor) or "automatic routing"),
               ("Speaker rule", "Speaker type is handled internally; moderation uses participants."),
               ("Last command", str(moderator.get("last_command") or "No manual command yet.")),
               ("Last route", last_route or "No route decision yet."),
               ("Selected action", selected_action), ("Warning", warning), ("What happens next", next_action)]
    participant_rows, quick = [], []
    for row in participants:
        bot = row["kind"] == "bot"
        can_next = running and (row.get("running") if bot else row.get("connected")) and not row.get("conflict")
        participant_rows.append({"value": participant_value(row), "cells": [row["id"], row["name"],
            "yes" if row.get("connected") else "running" if row.get("running") else "no",
            ("yes" if row.get("speaking") else "no") if bot else ("yes" if "current" in row["flags"] else ""),
            ("yes" if row.get("listening") else "no") if bot else "",
            str(row.get("queued", 0)) if bot else "", ", ".join(row["flags"]) or "—"]})
        quick.append({"value": participant_value(row), "name": row["name"], "targetId": row["id"] if bot else "",
                      "canNext": bool(can_next), "canCall": bool(can_next and bot and not speaking)})
    recovery = dict(moderator.get("dead_air_recovery") or {})
    configured = dict(dict(settings.get("room_router") or {}).get("dead_air_recovery") or {})
    saved_enabled = bool(configured.get("enabled", False))
    saved_status = "on" if saved_enabled else "off"
    if not running:
        runtime_status = "stopped"
    elif "enabled" not in recovery:
        runtime_status = "not yet reported"
    else:
        runtime_status = "on" if recovery["enabled"] else "off"
        if bool(recovery["enabled"]) != saved_enabled:
            runtime_status += " (saved change pending confirmation)"
    recovery_status = f"Saved: {saved_status} | Runtime: {runtime_status}"
    if recovery:
        recovery_status += f" | {recovery.get('last_reason') or 'no recovery activity yet'} | next: {recovery.get('last_next_target_bot_id') or 'none'}"
        if recovery.get("cooldown_remaining_ms"):
            recovery_status += f" | cooldown: {_number(recovery['cooldown_remaining_ms']) / 1000:.1f}s"
        if recovery.get("last_error"):
            recovery_status += f" | {recovery['last_error']}"
    else:
        recovery_status += " | no recovery activity yet"
    return {"summaryRows": [{"label": label, "value": value} for label, value in summary],
            "quickChoices": quick, "instances": instance_rows, "participants": participant_rows,
            "enabled": enabled, "warning": warning, "selectedAction": selected_action,
            "nextAction": next_action, "recoveryStatus": recovery_status}

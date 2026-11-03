"""Conversation-scoped Story Plans for the phone remote.

The store owns only planning state. It never queues a chat turn or controls audio.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from pathlib import Path
import threading
import uuid
from typing import Any, Mapping

STORY_PACE_REPLY_RANGES: dict[str, tuple[int, int]] = {
    "slow": (5, 8), "medium": (3, 4), "fast": (1, 2),
}


def _field(value: object, label: str, limit: int) -> str:
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= limit:
        raise ValueError(f"Story {label} must contain 1–{limit} characters.")
    return value.strip()


def validate_story_plan(value: object, *, max_beats: int = 30) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("Story Plan must be an object.")
    beats = value.get("beats")
    if not isinstance(beats, list) or not 2 <= len(beats) <= max_beats:
        raise ValueError(f"Story Plan needs 2–{max_beats} ordered beats.")
    result: dict[str, Any] = {
        "title": _field(value.get("title"), "title", 160),
        "premise": _field(value.get("premise"), "premise", 2400),
        "constraints": _field(value.get("constraints"), "constraints", 2400),
        "opening_cue": _field(value.get("opening_cue"), "opening cue", 2000),
        "beats": [],
    }
    for beat in beats:
        if not isinstance(beat, Mapping):
            raise ValueError("Every story beat needs a title and summary.")
        result["beats"].append({"title": _field(beat.get("title"), "beat title", 120),
                                "summary": _field(beat.get("summary"), "beat summary", 1000)})
    if 'pace' in value:
        pace = value['pace']
        if not isinstance(pace, str) or pace not in STORY_PACE_REPLY_RANGES:
            raise ValueError('Choose Slow, Medium or Fast story pace.')
        result['pace'] = pace
    return result


class StoryPlanStore:
    """One plan per conversation ID, persisted atomically outside user settings."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            self._plans = value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            self._plans = {}
        migrated = False
        for plan in self._plans.values():
            if isinstance(plan, dict):
                migrated = migrated or "plan_id" not in plan or "beat_visit_id" not in plan
                plan.setdefault("plan_id", uuid.uuid4().hex)
                plan.setdefault("beat_visit_id", uuid.uuid4().hex)
                plan.setdefault("pace", "medium")
                plan.setdefault("replies_in_beat", 0)
                plan.setdefault("pace_epoch", 0)
                plan.setdefault("completion_seen", False)
        if migrated:
            self._commit()

    def _commit(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        try:
            temporary.write_text(json.dumps(self._plans, ensure_ascii=False), encoding="utf-8")
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def snapshot(self, conversation_id: str) -> dict[str, Any] | None:
        with self._lock:
            plan = self._plans.get(conversation_id)
            return copy.deepcopy(plan) if isinstance(plan, dict) else None

    def save(self, conversation_id: str, value: object) -> dict[str, Any]:
        if not isinstance(conversation_id, str) or not conversation_id.strip():
            raise ValueError("An active conversation is required.")
        plan = validate_story_plan(value)
        with self._lock:
            previous = self._plans.get(conversation_id) or {}
            plan.update(status="saved", progression="automatic", pace=plan.get("pace", "medium"),
                        plan_id=uuid.uuid4().hex, beat_visit_id=uuid.uuid4().hex,
                        current_beat=0, replies_in_beat=0, pace_epoch=0,
                        completion_seen=False,
                        last_assessed_reply_id="", revision=int(previous.get("revision", 0)) + 1)
            self._plans[conversation_id] = plan
            self._commit()
            return copy.deepcopy(plan)

    def _current(self, conversation_id: str, revision: int) -> dict[str, Any]:
        plan = self._plans.get(conversation_id)
        if not isinstance(plan, dict):
            raise ValueError("Story Plan is unavailable in this conversation.")
        if type(revision) is not int or plan.get("revision") != revision:
            raise ValueError("Story Plan changed. Refresh and try again.")
        return plan

    def start(self, conversation_id: str, revision: int, latest_assistant_id: str) -> dict[str, Any]:
        with self._lock:
            plan = self._current(conversation_id, revision)
            if plan["status"] != "saved":
                raise ValueError("This Story Plan has already started.")
            plan.update(status="active", replies_in_beat=0, completion_seen=False,
                        last_assessed_reply_id=str(latest_assistant_id or "")[:160])
            plan["revision"] += 1
            self._commit()
            return copy.deepcopy(plan)

    def append_beats(self, conversation_id: str, revision: int, plan_id: str,
                     operation_id: str, beats: object, pace: str) -> dict[str, Any]:
        """Commit an extension and its retry receipt together; never rewrite old beats."""
        if not isinstance(operation_id, str) or not re.fullmatch(r'[a-f0-9]{32}', operation_id):
            raise ValueError('A story extension operation id is required.')
        if not isinstance(beats, list) or not 5 <= len(beats) <= 20:
            raise ValueError('Choose 5–20 extra beats.')
        validated = validate_story_plan({'title': 'Extension', 'premise': 'Extension',
            'constraints': 'Preserve story', 'opening_cue': 'Continue', 'beats': beats, 'pace': pace})
        fingerprint = hashlib.sha256(json.dumps([plan_id, revision, validated['beats'], pace],
            sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()
        with self._lock:
            current = self._plans.get(conversation_id)
            if not current or current.get('plan_id') != plan_id:
                raise ValueError('The story changed. Refine the extension again.')
            receipts = current.get('extension_receipts', {})
            if operation_id in receipts:
                if receipts[operation_id] != fingerprint:
                    raise ValueError('This extension operation id has already been used.')
                return copy.deepcopy(current)
            current = self._current(conversation_id, revision)
            if current['status'] not in {'active', 'complete'}:
                raise ValueError('Start the story before adding a continuation.')
            if len(current['beats']) + len(beats) > 1000:
                raise ValueError('This story has reached the 1000-beat limit. Save it and start a sequel.')
            old_titles = {beat['title'].casefold() for beat in current['beats']}
            titles = [beat['title'].casefold() for beat in validated['beats']]
            if len(set(titles)) != len(titles) or old_titles.intersection(titles):
                raise ValueError('Give the new beats distinct titles rather than repeating existing beats.')
            plan = copy.deepcopy(current)
            first = len(plan['beats'])
            plan['beats'].extend(validated['beats'])
            plan.update(pace=pace, revision=revision + 1)
            if plan['status'] == 'complete' or plan['current_beat'] == first - 1:
                plan.update(status='active', current_beat=first, replies_in_beat=0,
                            completion_seen=False, beat_visit_id=uuid.uuid4().hex)
            plan.setdefault('extension_receipts', {})[operation_id] = fingerprint
            self._plans[conversation_id] = plan
            try:
                self._commit()
            except OSError:
                self._plans[conversation_id] = current
                raise
            return copy.deepcopy(plan)

    def set_progression(self, conversation_id: str, revision: int, mode: str) -> dict[str, Any]:
        if mode not in {"automatic", "manual"}:
            raise ValueError("Choose Automatic or Manual progression.")
        with self._lock:
            plan = self._current(conversation_id, revision)
            plan["progression"] = mode
            plan["revision"] += 1
            self._commit()
            return copy.deepcopy(plan)

    def set_pace(self, conversation_id: str, revision: int, pace: str) -> dict[str, Any]:
        if pace not in STORY_PACE_REPLY_RANGES:
            raise ValueError("Choose Slow, Medium or Fast story pace.")
        with self._lock:
            plan = self._current(conversation_id, revision)
            plan["pace"] = pace
            plan["pace_epoch"] += 1
            plan["revision"] += 1
            self._commit()
            return copy.deepcopy(plan)

    def set_beat(self, conversation_id: str, revision: int, index: int) -> dict[str, Any]:
        with self._lock:
            plan = self._current(conversation_id, revision)
            if type(index) is not int or not 0 <= index < len(plan["beats"]):
                raise ValueError("Choose a beat from this plan.")
            if plan["current_beat"] != index:
                plan["replies_in_beat"] = 0
                plan["completion_seen"] = False
                plan["beat_visit_id"] = uuid.uuid4().hex
            plan["current_beat"] = index
            plan["status"] = "active"
            plan["revision"] += 1
            self._commit()
            return copy.deepcopy(plan)

    def apply_auto_assessment(self, conversation_id: str, reply_id: str,
                              complete: bool, revision: int,
                              original_plan: Mapping[str, Any] | None = None) -> bool:
        with self._lock:
            plan = self._plans.get(conversation_id)
            if (not isinstance(plan, dict) or plan.get("status") != "active"
                    or plan.get("progression") != "automatic"
                    or not reply_id or plan.get("last_assessed_reply_id") == reply_id):
                return False
            if plan.get("revision") != revision:
                # Only pace actions may rebase an assessment in flight. Compare
                # under the store lock so edits and beat changes cannot slip in.
                if original_plan is None or plan["revision"] - revision != (
                        plan.get("pace_epoch", 0) - original_plan.get("pace_epoch", 0)):
                    return False
                if any(plan.get(key) != original_plan.get(key) for key in (
                        "status", "progression", "current_beat", "replies_in_beat",
                        "completion_seen", "last_assessed_reply_id")):
                    return False
            plan["last_assessed_reply_id"] = reply_id[:160]
            plan["replies_in_beat"] += 1
            plan["completion_seen"] = bool(plan["completion_seen"] or complete)
            minimum, _ = STORY_PACE_REPLY_RANGES[plan["pace"]]
            advanced = plan["completion_seen"] and plan["replies_in_beat"] >= minimum
            if advanced:
                next_beat = plan["current_beat"] + 1
                if next_beat == len(plan["beats"]):
                    plan["status"] = "complete"
                else:
                    plan["current_beat"] = next_beat
                    plan["beat_visit_id"] = uuid.uuid4().hex
                    plan["replies_in_beat"] = 0
                    plan["completion_seen"] = False
            plan["revision"] += 1
            self._commit()
            return bool(advanced)

    def prompt_context(self, conversation_id: str) -> str:
        plan = self.snapshot(conversation_id)
        if not plan or plan.get("status") != "active":
            return ""
        index = plan["current_beat"]
        beats = plan["beats"]
        completed = ", ".join(beat["title"] for beat in beats[:index]) or "none"
        upcoming = "; ".join(beat["title"] for beat in beats[index + 1:index + 4]) or "none"
        pace = plan["pace"]
        minimum, target_high = STORY_PACE_REPLY_RANGES[pace]
        replies = plan["replies_in_beat"]
        if plan["completion_seen"] and replies < minimum:
            pace_guidance = ("The beat's key event has happened. Explore its consequences "
                             "and character reactions without repeating that event.")
        elif replies + 1 < minimum:
            pace_guidance = "Develop only part of this beat; leave its central outcome unresolved in this reply."
        elif replies >= target_high:
            pace_guidance = "Bring this beat toward a satisfying conclusion without repeating or rushing."
        else:
            pace_guidance = "Continue this beat naturally; resolve it only when its key event is earned."
        return (f"Story Plan — {plan['title']}\nPremise: {plan['premise']}\n"
                f"Constraints: {plan['constraints']}\nCompleted beats: {completed}\n"
                f"Current beat ({index + 1}/{len(beats)}): {beats[index]['title']} — {beats[index]['summary']}\n"
                f"Upcoming beats (do not resolve early): {upcoming}\n"
                f"Story pace: {pace.title()} (roughly {minimum}–{target_high} assistant replies per beat); "
                f"{replies} replies completed in this beat. {pace_guidance}\n"
                "Write only the next scene. Do not finish the whole story in one response. "
                "Established events take precedence over a lagging plan. Do not reset the scene "
                "or replay completed actions to satisfy this beat; develop their consequences. "
                "Preserve the user's latest request.")

    def remove(self, conversation_id: str, revision: int) -> None:
        with self._lock:
            self._current(conversation_id, revision)
            del self._plans[conversation_id]
            self._commit()

    def export(self, conversation_id: str) -> dict[str, Any] | None:
        return self.snapshot(conversation_id)

    @staticmethod
    def validate_snapshot(value: object) -> dict[str, Any] | None:
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise ValueError("Saved Story Plan is invalid.")
        validated = validate_story_plan(value, max_beats=1000)
        status = value.get("status")
        mode = value.get("progression")
        pace = value.get("pace", "medium")
        replies = value.get("replies_in_beat", 0)
        pace_epoch = value.get("pace_epoch", 0)
        completion_seen = value.get("completion_seen", False)
        index = value.get("current_beat")
        if (status not in {"saved", "active", "complete"} or mode not in {"automatic", "manual"}
                or pace not in STORY_PACE_REPLY_RANGES or type(replies) is not int or replies < 0
                or type(pace_epoch) is not int or pace_epoch < 0
                or type(completion_seen) is not bool
                or type(index) is not int or not 0 <= index < len(validated["beats"])):
            raise ValueError("Saved Story Plan state is invalid.")
        validated.update(status=status, progression=mode, pace=pace,
                         plan_id=str(value.get("plan_id") or uuid.uuid4().hex)[:64],
                         beat_visit_id=str(value.get("beat_visit_id") or uuid.uuid4().hex)[:64],
                         current_beat=index, replies_in_beat=replies,
                         pace_epoch=pace_epoch, completion_seen=completion_seen,
                         last_assessed_reply_id=str(value.get("last_assessed_reply_id") or "")[:160],
                         revision=max(1, int(value.get("revision") or 1)))
        return validated

    def restore(self, conversation_id: str, value: object) -> None:
        validated = self.validate_snapshot(value)
        if validated is None:
            return
        with self._lock:
            self._plans[conversation_id] = validated
            self._commit()

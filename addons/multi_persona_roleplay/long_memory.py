from __future__ import annotations

import re
import time
import uuid
from typing import Any

from .models import AR_MODE, PersonaConfig, RoleplaySessionState, normalize_persona_id


MEMORY_PATH = "memory/long_memory.json"
MAX_EVENTS = 1000
CHAPTER_SIZE = 12


def _compact(text: Any, limit: int = 1000) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(value) <= limit:
        return value
    return value[:limit].rstrip(" \t\r\n,;:.-")


def _keywords(text: str) -> set[str]:
    stop = {
        "about", "after", "again", "all", "and", "are", "because", "been", "but",
        "can", "continue", "did", "for", "from", "have", "her", "him", "his",
        "into", "just", "like", "not", "now", "out", "over", "she", "that",
        "the", "their", "them", "then", "there", "they", "this", "through",
        "was", "were", "what", "when", "with", "you", "your",
    }
    return {item for item in re.findall(r"[a-z0-9_']+", str(text or "").lower()) if len(item) > 2 and item not in stop}


class RoleplayLongMemory:
    """Addon-local long memory for both standard roleplay and AR mode.

    This intentionally uses JSON storage first. It gives the addon one stable
    memory shape before any optional database backend is introduced.
    """

    def __init__(self, storage, logger=None):
        self.storage = storage
        self.logger = logger

    def load(self) -> dict[str, Any]:
        payload = self.storage._read_json(MEMORY_PATH, {})
        if not isinstance(payload, dict):
            self._log("[LONG_MEMORY] Corrupt memory payload; starting fresh.")
            payload = {}
        return self._normalize(payload)

    def save(self, payload: dict[str, Any]) -> None:
        self.storage._write_json(MEMORY_PATH, self._normalize(payload))

    def clear(self) -> None:
        self.save({})
        self._log("[LONG_MEMORY] Cleared roleplay memory.")

    def record_turn(
        self,
        *,
        session: RoleplaySessionState,
        personas: list[PersonaConfig],
        user_text: str,
        assistant_text: str,
    ) -> dict[str, Any]:
        assistant = _compact(assistant_text, 1800)
        if not assistant:
            return {}
        payload = self.load()
        event = self._build_event(
            session=session,
            personas=personas,
            user_text=user_text,
            assistant_text=assistant,
        )
        events = list(payload.get("events") or [])
        events.append(event)
        payload["events"] = events[-MAX_EVENTS:]
        payload["chapters"] = self._build_chapters(payload["events"])
        payload["character_memory"] = self._build_character_memory(payload["events"], personas)
        payload["location_memory"] = self._build_location_memory(payload["events"])
        payload["updated_at"] = time.time()
        self.save(payload)
        self._log("[LONG_MEMORY] Recorded turn %s mode=%s", event.get("turn_index"), event.get("mode"))
        return event

    def prompt_context(
        self,
        *,
        session: RoleplaySessionState,
        personas: list[PersonaConfig],
        query: str = "",
        limit: int = 6,
    ) -> str:
        payload = self.load()
        events = list(payload.get("events") or [])
        if not events:
            return ""

        query_text = " ".join(
            item for item in (
                query,
                session.scene_title,
                session.location,
                session.objective,
                session.mood,
                session.ar_state.current_scene,
                session.ar_state.location,
                session.ar_state.story_goal,
                " ".join(session.ar_state.active_characters),
            )
            if str(item or "").strip()
        )
        recent = events[-max(2, min(8, limit)) :]
        recent_ids = {event.get("id") for event in recent}
        relevant = [
            event for event in self._rank_events(events[:-len(recent)] if len(events) > len(recent) else [], query_text)
            if event.get("id") not in recent_ids
        ][: max(0, limit - 2)]
        chapters = self._rank_chapters(list(payload.get("chapters") or []), query_text)[:3]
        active_character_ids = set(session.ar_state.active_characters or [])
        if session.current_speaker_id:
            active_character_ids.add(session.current_speaker_id)
        if session.active_persona_id:
            active_character_ids.add(session.active_persona_id)
        character_lines = []
        character_memory = dict(payload.get("character_memory") or {})
        for persona in personas:
            if persona.id in active_character_ids and character_memory.get(persona.id):
                character_lines.append(f"- {persona.display_name}: {character_memory[persona.id]}")

        lines = ["Long-term roleplay memory:"]
        raw_pinned = payload.get("pinned_facts")
        if isinstance(raw_pinned, str):
            raw_pinned = raw_pinned.splitlines()
        pinned = [str(item).strip() for item in list(raw_pinned or []) if str(item).strip()]
        if pinned:
            lines.append("Pinned story facts:")
            lines.extend(f"- {item}" for item in pinned[:12])
        if chapters:
            lines.append("Relevant chapter memory:")
            lines.extend(f"- {chapter.get('title')}: {chapter.get('summary')}" for chapter in chapters)
        if relevant:
            lines.append("Relevant older events:")
            lines.extend(f"- {event.get('summary')}" for event in relevant)
        if recent:
            lines.append("Recent remembered events:")
            lines.extend(f"- {event.get('summary')}" for event in recent)
        if character_lines:
            lines.append("Character memory:")
            lines.extend(character_lines[:6])
        return "\n".join(line for line in lines if str(line or "").strip())

    def _build_event(
        self,
        *,
        session: RoleplaySessionState,
        personas: list[PersonaConfig],
        user_text: str,
        assistant_text: str,
    ) -> dict[str, Any]:
        ar_state = session.ar_state
        active_ids = list(ar_state.active_characters or [])
        if not active_ids and session.current_speaker_id:
            active_ids = [session.current_speaker_id]
        summary = self._summarize_turn(user_text=user_text, assistant_text=assistant_text, session=session)
        keyword_text = " ".join(
            [
                user_text,
                assistant_text,
                session.scene_title,
                session.location,
                session.objective,
                ar_state.current_scene,
                ar_state.location,
                ar_state.story_goal,
                " ".join(active_ids),
            ]
        )
        return {
            "id": uuid.uuid4().hex[:12],
            "created_at": time.time(),
            "turn_index": int(session.turn_index or 0),
            "mode": str(session.mode or ""),
            "scene": _compact(ar_state.current_scene or session.scene_title, 240),
            "location": _compact(ar_state.location or session.location, 180),
            "mood": _compact(ar_state.mood or session.mood, 160),
            "story_goal": _compact(ar_state.story_goal or session.objective, 260),
            "active_characters": [normalize_persona_id(item) for item in active_ids][:8],
            "user_text": _compact(user_text, 900),
            "assistant_text": _compact(assistant_text, 1600),
            "summary": summary,
            "keywords": sorted(_keywords(keyword_text))[:80],
        }

    def _summarize_turn(self, *, user_text: str, assistant_text: str, session: RoleplaySessionState) -> str:
        mode = "AR" if str(session.mode or "") == AR_MODE else "Roleplay"
        user = _compact(user_text, 180)
        assistant = _compact(re.sub(r"\[[A-Z: a-z0-9_-]+\]", " ", assistant_text), 360)
        if user:
            return _compact(f"{mode}: Player/User: {user} -> {assistant}", 520)
        return _compact(f"{mode}: {assistant}", 520)

    def _build_chapters(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        chapters = []
        for index in range(0, len(events), CHAPTER_SIZE):
            chunk = events[index : index + CHAPTER_SIZE]
            if not chunk:
                continue
            first = chunk[0]
            last = chunk[-1]
            title = first.get("scene") or first.get("location") or f"Chapter {len(chapters) + 1}"
            summary = "; ".join(_compact(event.get("summary"), 180) for event in chunk[-5:] if event.get("summary"))
            chapters.append(
                {
                    "id": f"chapter_{len(chapters) + 1}",
                    "title": _compact(title, 120),
                    "start_turn": int(first.get("turn_index", 0) or 0),
                    "end_turn": int(last.get("turn_index", 0) or 0),
                    "summary": _compact(summary, 900),
                    "keywords": sorted(set().union(*(_keywords(event.get("summary", "")) for event in chunk)))[:80],
                }
            )
        return chapters[-80:]

    def _build_character_memory(self, events: list[dict[str, Any]], personas: list[PersonaConfig]) -> dict[str, str]:
        result = {}
        known = {persona.id: persona.display_name for persona in personas}
        for persona_id in known:
            matching = [
                event for event in events
                if persona_id in list(event.get("active_characters") or [])
                or persona_id in _keywords(event.get("summary", ""))
            ][-5:]
            if matching:
                result[persona_id] = _compact("; ".join(event.get("summary", "") for event in matching), 700)
        return result

    def _build_location_memory(self, events: list[dict[str, Any]]) -> dict[str, str]:
        result: dict[str, list[str]] = {}
        for event in events:
            location = _compact(event.get("location"), 120)
            if not location:
                continue
            result.setdefault(location, []).append(event.get("summary", ""))
        return {key: _compact("; ".join(values[-4:]), 700) for key, values in result.items()}

    def _rank_events(self, events: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
        wanted = _keywords(query)
        if not wanted:
            return list(events)[-6:]
        scored = []
        for offset, event in enumerate(events):
            haystack = set(event.get("keywords") or []) | _keywords(event.get("summary", ""))
            score = len(wanted & haystack)
            if score > 0:
                scored.append((score, offset, event))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [item[2] for item in scored]

    def _rank_chapters(self, chapters: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
        wanted = _keywords(query)
        if not wanted:
            return list(chapters)[-2:]
        scored = []
        for offset, chapter in enumerate(chapters):
            haystack = set(chapter.get("keywords") or []) | _keywords(chapter.get("summary", ""))
            score = len(wanted & haystack)
            if score > 0:
                scored.append((score, offset, chapter))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [item[2] for item in scored]

    def _normalize(self, payload: dict[str, Any]) -> dict[str, Any]:
        events = payload.get("events") if isinstance(payload.get("events"), list) else []
        chapters = payload.get("chapters") if isinstance(payload.get("chapters"), list) else []
        raw_pinned = payload.get("pinned_facts")
        if isinstance(raw_pinned, str):
            raw_pinned = raw_pinned.splitlines()
        return {
            "version": 1,
            "backend": "json",
            "events": [event for event in events if isinstance(event, dict)][-MAX_EVENTS:],
            "chapters": [chapter for chapter in chapters if isinstance(chapter, dict)][-80:],
            "pinned_facts": [str(item).strip()[:500] for item in list(raw_pinned or []) if str(item).strip()][:80],
            "character_memory": dict(payload.get("character_memory") or {}) if isinstance(payload.get("character_memory"), dict) else {},
            "location_memory": dict(payload.get("location_memory") or {}) if isinstance(payload.get("location_memory"), dict) else {},
            "updated_at": float(payload.get("updated_at", 0.0) or 0.0),
        }

    def _log(self, message: str, *args) -> None:
        if self.logger is not None:
            try:
                self.logger.info(message, *args)
            except Exception:
                pass

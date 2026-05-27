from __future__ import annotations

import re
from typing import Any

from . import prompting
from .models import PersonaConfig, RoleplaySessionState


class RoleplayEngine:
    def __init__(self, controller):
        self.controller = controller
        self._recent_assistant_texts: list[str] = []
        self._latest_user_requested_image = False
        self._latest_user_input_text = ""
        self._last_visual_scene_key = ""
        self._last_visual_location_key = ""
        self._last_visual_speaker_id = ""

    def chat_context(self, payload: dict[str, Any] | None = None) -> dict[str, Any] | None:
        payload = dict(payload or {})
        session: RoleplaySessionState = self.controller.session
        if not session.enabled:
            return None
        latest_user = self._latest_user_text(payload.get("messages"))
        self._latest_user_input_text = latest_user
        prompt_personas = self.controller.story_prompt_personas() if hasattr(self.controller, "story_prompt_personas") else self.controller.personas
        if prompting.is_alternative_reality_mode(session):
            self.controller.ensure_ar_state(latest_user)
            context_text = prompting.build_alternative_reality_prompt(
                prompt_personas,
                session,
                latest_user_text=latest_user,
                available_audio=self.controller.available_story_audio_files(),
                narrator_persona_id=self.controller.selected_narrator_persona_id(),
            )
            memory_context = self._long_memory_context(session=session, query=latest_user, limit=8)
            if memory_context:
                context_text = context_text + "\n\n" + memory_context
            self._latest_user_requested_image = self._looks_like_image_request(latest_user)
            debug = {
                "sources": ["multi_persona_roleplay", "alternative_reality"],
                "active_persona_id": session.active_persona_id,
                "current_speaker_id": session.current_speaker_id,
                "mode": session.mode,
            }
            self.controller.set_debug_prompt(context_text)
            return {"context": context_text, "debug": debug}
        persona = self.controller.prompt_persona()
        if persona is None or not persona.enabled:
            return None
        if hasattr(self.controller, "story_prompt_persona"):
            persona = self.controller.story_prompt_persona(persona.id) or persona
        context_text = prompting.build_persona_system_prompt(persona, session)
        if session.mode != "Single active persona":
            context_text = context_text + "\n\n" + prompting.build_multi_character_prompt(prompt_personas, session)
        memory_context = self._long_memory_context(session=session, query=latest_user, limit=6)
        if memory_context:
            context_text = context_text + "\n\n" + memory_context
        self._latest_user_requested_image = self._looks_like_image_request(latest_user)
        if self._recent_assistant_texts:
            threshold = float(self.controller.settings.get("repetition_threshold", 0.8) or 0.8)
            if latest_user:
                max_similarity = max(
                    prompting.token_jaccard_similarity(latest_user, previous)
                    for previous in self._recent_assistant_texts[-4:]
                )
                if max_similarity >= threshold:
                    context_text += "\n\nAvoid repeating recent phrasing. Move the scene or explanation forward with fresh wording."
                    logger = getattr(self.controller.context, "logger", None)
                    if logger is not None:
                        logger.warning("Recent text similarity exceeded threshold %.2f", threshold)
        debug = {
            "sources": ["multi_persona_roleplay"],
            "active_persona_id": persona.id,
            "mode": session.mode,
        }
        self.controller.set_debug_prompt(context_text)
        return {"context": context_text, "debug": debug}

    def record_assistant_text(self, text: str) -> None:
        value = str(text or "").strip()
        if not value:
            return
        self._recent_assistant_texts.append(value)
        self._recent_assistant_texts = self._recent_assistant_texts[-8:]
        session = self.controller.session
        try:
            self.controller.ensure_personas_from_assistant_text(value)
        except Exception as exc:
            logger = getattr(self.controller.context, "logger", None)
            if logger is not None:
                logger.warning("[MPRC] Auto persona creation from assistant reply failed: %s", exc)
        session.turn_index += 1
        if session.update_scene_after_reply:
            event = value[:220].strip()
            if event:
                session.recent_events.append(event)
                session.recent_events = session.recent_events[-20:]
        if prompting.is_alternative_reality_mode(session):
            self.controller.record_ar_reply(value)
        self._record_long_memory(session=session, assistant_text=value)
        self.controller.save_active_story_memory_snapshot()
        self.controller.save_state()
        self._maybe_auto_visual_reply(value)

    def _maybe_auto_visual_reply(self, assistant_text: str = "") -> None:
        session = self.controller.session
        persona = self._visual_persona_for_reply(assistant_text)
        if bool(getattr(self.controller, "_suppress_next_auto_visual_reply", False)):
            self._remember_visual_baseline(session)
            return
        if persona is None or not session.enabled or not persona.visual.enabled:
            self._remember_visual_baseline(session)
            return
        mode = str(persona.visual.mode or "off")
        scene_key = self._visual_scene_key(session)
        location_key = self._visual_location_key(session)
        speaker_key = str(session.current_speaker_id or "")
        reason = ""
        if mode == "auto_every_reply":
            reason = "assistant_reply"
        elif mode == "auto_scene_change" and (session.update_scene_after_reply or (scene_key and scene_key != self._last_visual_scene_key)):
            reason = "scene_changed"
        elif mode == "auto_new_location" and location_key and location_key != self._last_visual_location_key:
            reason = "new_location"
        elif mode == "auto_character_change" and speaker_key and speaker_key != self._last_visual_speaker_id:
            reason = "character_change"
        elif mode == "auto_choices" and self._has_choices(assistant_text):
            reason = "choices_present"
        elif mode == "auto_important_moment" and self._looks_like_visual_moment(assistant_text):
            reason = "important_moment"
        elif mode == "auto_story_beat" and self._is_ar_story_beat(assistant_text, session):
            reason = "ar_story_beat"
        elif mode == "auto_every_n_replies":
            interval = max(1, int(getattr(persona.visual, "auto_reply_interval", 1) or 1))
            if session.turn_index > 0 and session.turn_index % interval == 0:
                reason = "reply_interval"
        elif mode == "auto_user_asks" and self._latest_user_requested_image:
            reason = "user_requested_image"
        self._remember_visual_baseline(session)
        if not reason:
            return

        recorder = getattr(self.controller, "_record_visual_debug", None)
        if callable(recorder):
            try:
                recorder(
                    source="auto_visual_decision",
                    reason=reason,
                    persona=persona,
                    accepted=None,
                    message=f"Auto trigger matched Visual Reply mode '{mode}'.",
                )
            except Exception:
                pass

        requester = getattr(self.controller, "request_auto_visual_reply", None)
        if callable(requester):
            requester(persona.id, reason)
            return
        self.controller.visual_reply.request_generation(persona=persona, reason=reason)

    def _visual_persona_for_reply(self, assistant_text: str) -> PersonaConfig | None:
        labeled = self._persona_from_visual_text(assistant_text)
        if labeled is not None:
            return labeled
        current = self.controller.current_speaker_persona()
        if current is not None:
            return current
        active = self.controller.active_persona()
        if active is not None:
            return active
        for persona in list(self.controller.personas or []):
            if getattr(persona, "enabled", False) and bool(getattr(persona.visual, "enabled", False)):
                return persona
        return None

    def _persona_from_visual_text(self, text: str) -> PersonaConfig | None:
        value = str(text or "")
        labels = re.findall(r"\[CHARACTER:\s*([^\]]+)\]", value, flags=re.IGNORECASE)
        labels.extend(re.findall(r"^\s*([A-Za-z][A-Za-z0-9 _'-]{1,48})\s*:", value, flags=re.MULTILINE))
        for raw_name in labels:
            wanted = str(raw_name or "").strip().lower()
            if not wanted:
                continue
            for persona in list(self.controller.personas or []):
                if wanted in {persona.id.lower(), persona.display_name.strip().lower()}:
                    return persona
        return None

    def _remember_visual_baseline(self, session: RoleplaySessionState) -> None:
        self._last_visual_scene_key = self._visual_scene_key(session)
        self._last_visual_location_key = self._visual_location_key(session)
        self._last_visual_speaker_id = str(session.current_speaker_id or "")

    @staticmethod
    def _visual_scene_key(session: RoleplaySessionState) -> str:
        state = session.ar_state
        parts = [
            session.scene_title,
            session.scene_summary,
            session.location,
            session.mood,
            getattr(state, "current_scene", ""),
            getattr(state, "location", ""),
            getattr(state, "mood", ""),
        ]
        return "|".join(str(item or "").strip().lower()[:180] for item in parts if str(item or "").strip())

    @staticmethod
    def _visual_location_key(session: RoleplaySessionState) -> str:
        state = session.ar_state
        return str(getattr(state, "location", "") or session.location or "").strip().lower()

    def _has_choices(self, assistant_text: str) -> bool:
        if "[CHOICES]" in str(assistant_text or "").upper():
            return True
        choices = list(getattr(self.controller.session.ar_state, "pending_choices", []) or [])
        return any(str(item or "").strip() for item in choices)

    def _looks_like_visual_moment(self, assistant_text: str) -> bool:
        text = f"{self._latest_user_input_text}\n{assistant_text}".lower()
        if not text.strip():
            return False
        keywords = (
            "arrives",
            "attack",
            "battle",
            "breaks",
            "burst",
            "choice",
            "crashes",
            "discovers",
            "dragon",
            "explodes",
            "falls",
            "fight",
            "fire",
            "magic",
            "monster",
            "opens",
            "portal",
            "reveals",
            "screams",
            "suddenly",
            "thunder",
            "trap",
            "turns",
        )
        if any(word in text for word in keywords):
            return True
        try:
            return int(getattr(self.controller.session.ar_state, "tension_level", 0) or 0) >= 7
        except Exception:
            return False

    def _is_ar_story_beat(self, assistant_text: str, session: RoleplaySessionState) -> bool:
        if not prompting.is_alternative_reality_mode(session):
            return False
        if session.turn_index <= 1 or self._has_choices(assistant_text) or self._looks_like_visual_moment(assistant_text):
            return True
        persona = self._visual_persona_for_reply(assistant_text)
        interval = max(1, int(getattr(getattr(persona, "visual", None), "auto_reply_interval", 2) or 2))
        return session.turn_index > 0 and session.turn_index % interval == 0

    def _long_memory_context(self, *, session: RoleplaySessionState, query: str, limit: int) -> str:
        try:
            return self.controller.long_memory.prompt_context(
                session=session,
                personas=self.controller.personas,
                query=query,
                limit=limit,
            )
        except Exception as exc:
            logger = getattr(self.controller.context, "logger", None)
            if logger is not None:
                logger.warning("[LONG_MEMORY] Retrieval failed: %s", exc)
            return ""

    def _record_long_memory(self, *, session: RoleplaySessionState, assistant_text: str) -> None:
        try:
            self.controller.long_memory.record_turn(
                session=session,
                personas=self.controller.personas,
                user_text=self._latest_user_input_text,
                assistant_text=assistant_text,
            )
        except Exception as exc:
            logger = getattr(self.controller.context, "logger", None)
            if logger is not None:
                logger.warning("[LONG_MEMORY] Record failed: %s", exc)

    @staticmethod
    def _latest_user_text(messages: Any) -> str:
        if not isinstance(messages, list):
            return ""
        for message in reversed(messages):
            if not isinstance(message, dict):
                continue
            if str(message.get("role") or "").strip().lower() != "user":
                continue
            content = message.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        parts.append(str(item.get("text") or ""))
                return "\n".join(parts).strip()
        return ""

    @staticmethod
    def _looks_like_image_request(text: str) -> bool:
        lowered = str(text or "").lower()
        if not lowered:
            return False
        request_words = ("image", "picture", "visual", "photo", "draw", "show me", "generate")
        return any(word in lowered for word in request_words)

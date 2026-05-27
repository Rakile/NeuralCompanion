from __future__ import annotations

import time
from typing import Any

from . import prompting
from .models import PersonaConfig, RoleplaySessionState


class PersonaVisualReply:
    def __init__(self, controller):
        self.controller = controller

    def style_prompt(self, style_id: str) -> str:
        key = str(style_id or "").strip().lower()
        for style in list(self.controller.visual_styles or []):
            if str(style.get("id") or "").strip().lower() == key:
                return str(style.get("prompt") or "").strip()
        return ""

    def build_prompt(self, persona: PersonaConfig | None = None, reason: str = "manual") -> dict[str, Any]:
        persona = persona or self.controller.current_speaker_persona() or self.controller.active_persona()
        if persona is None:
            return prompting.build_visual_json_contract("", "", reason)
        session: RoleplaySessionState = self.controller.session
        prompt = prompting.build_visual_reply_prompt(
            persona,
            session,
            style_prompt=self.style_prompt(persona.visual.style_preset),
            reason=reason,
        )
        return prompting.build_visual_json_contract(prompt, persona.id, reason)

    def _record_debug(
        self,
        source: str,
        reason: str,
        persona: PersonaConfig | None,
        accepted: bool | None,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        recorder = getattr(self.controller, "_record_visual_debug", None)
        if not callable(recorder):
            return
        prompt = ""
        if isinstance(payload, dict):
            prompt = str(payload.get("image_prompt") or "")
        try:
            recorder(
                source=source,
                reason=str(reason or "manual"),
                persona=persona,
                accepted=accepted,
                message=message,
                prompt=prompt,
            )
        except Exception:
            return

    def can_auto_generate(self, persona: PersonaConfig | None = None, reason: str = "manual") -> tuple[bool, str]:
        persona = persona or self.controller.current_speaker_persona() or self.controller.active_persona()
        if persona is None:
            return False, "No active persona."
        visual = persona.visual
        if not visual.enabled or visual.mode == "off":
            return False, "Visual replies are disabled for this persona."
        if reason != "manual":
            allowed_reasons = {
                "manual": {"manual"},
                "auto_every_reply": {"assistant_reply", "tts_reply"},
                "auto_scene_change": {"scene_changed", "tts_reply"},
                "auto_new_location": {"new_location"},
                "auto_character_change": {"character_change", "tts_reply"},
                "auto_choices": {"choices_present"},
                "auto_important_moment": {"important_moment", "tts_reply"},
                "auto_story_beat": {"ar_story_beat", "choices_present", "important_moment"},
                "auto_every_n_replies": {"reply_interval", "tts_reply"},
                "auto_user_asks": {"user_requested_image"},
            }.get(visual.mode, set())
            if reason not in allowed_reasons:
                return False, f"Visual Reply mode '{visual.mode}' does not match this auto trigger."
        session = self.controller.session
        if visual.max_auto_images_per_session and session.auto_image_count >= visual.max_auto_images_per_session:
            return False, "Auto image limit reached for this session."
        elapsed = time.time() - float(session.last_visual_reply_at or 0.0)
        if reason != "manual" and elapsed < max(0, int(visual.cooldown_seconds or 0)):
            return False, "Visual Reply cooldown is active."
        return True, ""

    def request_generation(self, persona: PersonaConfig | None = None, reason: str = "manual") -> dict[str, Any]:
        persona = persona or self.controller.current_speaker_persona() or self.controller.active_persona()
        payload = self.build_prompt(persona, reason=reason)
        if not payload.get("should_generate"):
            self._record_debug("persona_visual_reply", reason, persona, False, "No visual prompt was generated.", payload)
            return {"accepted": False, "message": "No visual prompt was generated.", "payload": payload}
        self._record_debug("persona_visual_reply", reason, persona, None, "Visual Reply prompt built.", payload)
        allowed, message = self.can_auto_generate(persona, reason=reason)
        if not allowed:
            self._record_debug("persona_visual_reply", reason, persona, False, message, payload)
            return {"accepted": False, "message": message, "payload": payload}
        visual_service = self.controller.visual_reply_service
        if visual_service is None or not hasattr(visual_service, "request_generation"):
            self._record_debug(
                "persona_visual_reply",
                reason,
                persona,
                False,
                "Visual Reply generation service is unavailable. Prompt preview still works.",
                payload,
            )
            return {
                "accepted": False,
                "message": "Visual Reply generation service is unavailable. Prompt preview still works.",
                "payload": payload,
            }
        visual = persona.visual if persona is not None else None
        try:
            accepted = bool(
                visual_service.request_generation(
                    prompt=str(payload.get("image_prompt") or ""),
                    caption=str(payload.get("caption") or ""),
                    provider=str(getattr(visual, "provider", "inherit") or "inherit"),
                    model=str(getattr(visual, "model", "") or ""),
                    size=str(getattr(visual, "size", "inherit") or "inherit"),
                    source="nc.multi_persona_roleplay",
                    metadata={
                        "persona_id": str(payload.get("active_persona_id") or ""),
                        "scene_title": str(self.controller.session.scene_title or ""),
                        "reason": str(reason or "manual"),
                    },
                    auto_show=bool(getattr(visual, "auto_show_dock", True)),
                )
            )
        except Exception as exc:
            logger = getattr(self.controller.context, "logger", None)
            if logger is not None:
                logger.exception("Visual Reply request failed.")
            self._record_debug("persona_visual_reply", reason, persona, False, f"Visual Reply request failed: {exc}", payload)
            return {"accepted": False, "message": str(exc), "payload": payload}
        if accepted:
            lock = getattr(self.controller, "_state_lock", None)
            if lock is None:
                self.controller.session.last_visual_reply_at = time.time()
                if reason != "manual":
                    self.controller.session.auto_image_count += 1
                self.controller.save_state()
            else:
                with lock:
                    if getattr(self.controller, "_shutting_down", False):
                        return {"accepted": False, "message": "MPRC is shutting down.", "payload": payload}
                    self.controller.session.last_visual_reply_at = time.time()
                    if reason != "manual":
                        self.controller.session.auto_image_count += 1
                    self.controller.save_state()
        result_message = "Visual Reply requested." if accepted else "Visual Reply request was not accepted."
        self._record_debug("persona_visual_reply", reason, persona, accepted, result_message, payload)
        return {"accepted": accepted, "message": result_message, "payload": payload}

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

    def effective_provider(self, persona: PersonaConfig | None = None) -> str:
        return str(self.effective_provider_info(persona).get("effective_provider") or "inherit")

    def active_provider_snapshot(self) -> dict[str, Any]:
        service = getattr(self.controller, "visual_reply_service", None)
        snapshotter = getattr(service, "settings_snapshot", None)
        if not callable(snapshotter):
            return {}
        try:
            snapshot = snapshotter()
        except Exception:
            return {}
        return dict(snapshot or {}) if isinstance(snapshot, dict) else {}

    def effective_provider_info(self, persona: PersonaConfig | None = None) -> dict[str, Any]:
        visual = getattr(persona, "visual", None)
        persona_provider_raw = str(getattr(visual, "provider", "inherit") or "inherit").strip().lower()
        persona_provider = prompting.normalize_visual_provider_id(persona_provider_raw) or "inherit"
        snapshot = self.active_provider_snapshot()
        active_provider_raw = str(snapshot.get("provider_value") or snapshot.get("provider") or "").strip().lower()
        active_provider = prompting.normalize_visual_provider_id(active_provider_raw)
        effective_provider = persona_provider if persona_provider and persona_provider != "inherit" else active_provider
        if not effective_provider:
            effective_provider = "inherit"
        return {
            "effective_provider": effective_provider,
            "prompt_style": prompting.visual_prompt_style(effective_provider),
            "persona_provider_override": persona_provider_raw or "inherit",
            "persona_provider_normalized": persona_provider,
            "active_provider_snapshot": active_provider or "",
            "active_provider_raw": active_provider_raw,
        }

    def build_prompt(
        self,
        persona: PersonaConfig | None = None,
        policy_persona: PersonaConfig | None = None,
        reason: str = "manual",
        source_text: str = "",
        use_action_prompt: bool = True,
        scene_focused: bool = False,
    ) -> dict[str, Any]:
        persona = persona or self.controller.current_speaker_persona() or self.controller.active_persona()
        if persona is None:
            return prompting.build_visual_json_contract("", "", reason)
        policy_persona = policy_persona or persona
        session: RoleplaySessionState = self.controller.session
        provider_info = self.effective_provider_info(persona)
        provider = str(provider_info.get("effective_provider") or "inherit")
        prompt = prompting.build_visual_reply_prompt(
            persona,
            session,
            style_prompt=self.style_prompt(persona.visual.style_preset),
            reason=reason,
            provider=provider,
            source_text=source_text,
            scene_focused=scene_focused,
        )
        debugger = getattr(self.controller, "set_chat_visual_prompt_debug_from_parts", None)
        if callable(debugger):
            debugger(
                persona=persona,
                reason=reason,
                provider=provider,
                stage="fallback/base prompt",
                final_prompt=prompt,
                base_prompt=prompt,
                source_text=str(source_text or ""),
                request_payload={"provider_info": provider_info},
            )
        if use_action_prompt and str(source_text or "").strip():
            refiner = getattr(self.controller, "build_visual_action_prompt", None)
            if callable(refiner):
                refined = refiner(
                    persona=persona,
                    source_text=str(source_text or ""),
                    base_prompt=prompt,
                    reason=reason,
                    provider=provider,
                    scene_focused=scene_focused,
                )
                if str(refined or "").strip():
                    prompt = str(refined or "").strip()
        payload = prompting.build_visual_json_contract(prompt, persona.id, reason)
        payload["effective_provider"] = provider
        payload["prompt_style"] = str(provider_info.get("prompt_style") or prompting.visual_prompt_style(provider))
        payload["persona_provider_override"] = str(provider_info.get("persona_provider_override") or "inherit")
        payload["active_visual_provider"] = str(provider_info.get("active_provider_snapshot") or "")
        payload["visual_policy_persona_id"] = str(getattr(policy_persona, "id", "") or "")
        payload["scene_focused"] = bool(scene_focused)
        return payload

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
        provider = ""
        prompt_style = ""
        if isinstance(payload, dict):
            prompt = str(payload.get("image_prompt") or "")
            provider = str(payload.get("effective_provider") or "")
            prompt_style = str(payload.get("prompt_style") or "")
        try:
            detail = str(message or "")
            if provider or prompt_style:
                detail = f"{detail} Provider={provider or 'inherit'} style={prompt_style or prompting.visual_prompt_style(provider)}.".strip()
            recorder(
                source=source,
                reason=str(reason or "manual"),
                persona=persona,
                accepted=accepted,
                message=detail,
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

    def request_generation(
        self,
        persona: PersonaConfig | None = None,
        policy_persona: PersonaConfig | None = None,
        reason: str = "manual",
        source_text: str = "",
        scene_focused: bool = False,
    ) -> dict[str, Any]:
        persona = persona or self.controller.current_speaker_persona() or self.controller.active_persona()
        policy_persona = policy_persona or persona
        payload = self.build_prompt(
            persona,
            policy_persona=policy_persona,
            reason=reason,
            source_text=source_text,
            use_action_prompt=False,
            scene_focused=scene_focused,
        )
        if not payload.get("should_generate"):
            self._record_debug("persona_visual_reply", reason, persona, False, "No visual prompt was generated.", payload)
            return {"accepted": False, "message": "No visual prompt was generated.", "payload": payload}
        allowed, message = self.can_auto_generate(policy_persona, reason=reason)
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
        if str(source_text or "").strip():
            payload = self.build_prompt(
                persona,
                policy_persona=policy_persona,
                reason=reason,
                source_text=source_text,
                use_action_prompt=True,
                scene_focused=scene_focused,
            )
            if not payload.get("should_generate"):
                self._record_debug("persona_visual_reply", reason, persona, False, "No visual prompt was generated.", payload)
                return {"accepted": False, "message": "No visual prompt was generated.", "payload": payload}
        self._record_debug("persona_visual_reply", reason, persona, None, "Visual Reply prompt built.", payload)
        visual = persona.visual if persona is not None else None
        provider = str(payload.get("effective_provider") or self.effective_provider(persona) or "inherit")
        if provider == "inherit":
            provider = str(getattr(visual, "provider", "inherit") or "inherit")
        try:
            accepted = bool(
                visual_service.request_generation(
                    prompt=str(payload.get("image_prompt") or ""),
                    caption=str(payload.get("caption") or ""),
                    provider=provider,
                    model=str(getattr(visual, "model", "") or ""),
                    size=str(getattr(visual, "size", "inherit") or "inherit"),
                    source="nc.multi_persona_roleplay",
                    metadata={
                        "persona_id": str(payload.get("active_persona_id") or ""),
                        "visual_policy_persona_id": str(payload.get("visual_policy_persona_id") or ""),
                        "scene_focused": bool(payload.get("scene_focused")),
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

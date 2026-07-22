from __future__ import annotations

from core.addons import BaseAddon
from addons.companion_orb_overlay.companion_orb import eye_tracking


class Addon(BaseAddon):
    TAB_ID = "companion_orb_overlay_tab"

    def initialize(self, context):
        super().initialize(context)
        from addons.companion_orb_overlay.companion_orb.companion_orb_controller import CompanionOrbController
        from addons.companion_orb_overlay.controller import CompanionOrbOverlaySettingsController

        self.controller = CompanionOrbOverlaySettingsController(context)
        self.orb_controller = CompanionOrbController(context)
        self.controller.set_companion_orb_service(self.orb_controller)
        context.ui.register_tab(
            id=self.TAB_ID,
            title="Companion Orb",
            factory=self._build_tab,
            area="top_level",
            order=126,
            tooltip="Configure the Companion Orb Overlay, movement, particles, voice sync, sensory target, and hotkeys.",
            icon_path="../../ui_icons/side_tabs/companion_orb.png",
            metadata={"runtime_role": "companion_orb_overlay"},
        )
        context.services.register(
            "ai_presence.companion_orb",
            self.orb_controller,
            metadata={"kind": "visual_overlay", "target_provider": "companion_orb_target"},
        )
        self._event_tokens = []
        for event_name, handler in (
            ("sensory.hidden_pong.parsed", self._on_hidden_pong_parsed),
            ("sensory.hidden_action.proactive_queued", self._on_proactive_queued),
        ):
            try:
                self._event_tokens.append(context.events.subscribe(event_name, handler))
            except Exception as exc:
                context.logger.warning("[CompanionOrbOverlay] Could not subscribe to %s: %s", event_name, exc)
        context.logger.info("[CompanionOrbOverlay] Companion Orb Overlay addon initialized.")

    def _build_tab(self, _context):
        controller = getattr(self, "controller", None)
        if controller is None:
            raise RuntimeError("Companion Orb Overlay settings controller is unavailable.")
        return controller.build_tab()

    def export_session_state(self):
        controller = getattr(self, "controller", None)
        payload = controller.export_session_state() if controller is not None else {}
        orb = getattr(self, "orb_controller", None)
        if orb is not None:
            try:
                payload.update(orb.export_session_state() or {})
            except Exception:
                pass
        return payload

    def import_session_state(self, session):
        controller = getattr(self, "controller", None)
        if controller is not None:
            controller.import_session_state(session)
        orb = getattr(self, "orb_controller", None)
        if orb is not None:
            return orb.import_session_state(session)
        return None

    def invoke_capability(self, capability, payload=None):
        capability_name = str(capability or "").strip().lower()
        request = dict(payload or {})
        orb = getattr(self, "orb_controller", None)
        if capability_name == "chat.user_text_command" and orb is not None:
            return self._handle_eye_tracking_user_text_command(request)
        if capability_name.startswith("companion_orb.") and orb is not None:
            if capability_name == "companion_orb.target_info":
                return {"ok": True, "target": orb.target_info()}
            if capability_name == "companion_orb.clear_target":
                orb.clear_target()
                return {"ok": True, "cleared": True}
            if capability_name == "companion_orb.edit_mode":
                enabled = bool(request.get("enabled", True))
                orb.set_edit_mode(enabled)
                return {"ok": True, "edit_mode": enabled}
            if capability_name == "companion_orb.placement_mode":
                enabled = bool(request.get("enabled", True))
                orb.set_placement_mode(enabled)
                return {"ok": True, "placement_mode": enabled}
            if capability_name == "companion_orb.click_through":
                enabled = bool(request.get("enabled", True))
                orb.set_click_through(enabled)
                return {"ok": True, "click_through": enabled}
            if capability_name == "companion_orb.reset_position":
                orb.reset_position()
                return {"ok": True, "position_reset": True}
            if capability_name == "companion_orb.focus_comment":
                orb.focus_comment_text(request)
                return {"ok": True, "focused": True}
            if capability_name == "companion_orb.eye_tracking_status":
                return {"ok": True, **orb.eye_tracking_status()}
            if capability_name == "companion_orb.reconnect_eye_tracking":
                return orb.reconnect_eye_tracking()
            if capability_name == "companion_orb.react_at_gaze":
                return orb.react_at_gaze(force=bool(request.get("force", True)))
        return None

    def _handle_eye_tracking_user_text_command(self, request):
        role = str(request.get("role") or "user").strip().lower()
        if role and role != "user":
            return None
        text = str(request.get("text") or request.get("utterance") or "").strip()
        if not eye_tracking.is_explicit_orb_gaze_command(text):
            return None
        orb = getattr(self, "orb_controller", None)
        if orb is None:
            return None
        result = orb.react_at_gaze(force=True)
        ok = bool(isinstance(result, dict) and result.get("ok"))
        response_text = (
            "I am checking where you are looking."
            if ok
            else str((result or {}).get("error") or "No recent eye-tracker focus is available.")
        )
        return {
            "ok": ok,
            "handled": True,
            "response_text": response_text,
            "use_llm_response": False,
            "result": result,
        }

    def _on_hidden_pong_parsed(self, payload):
        orb = getattr(self, "orb_controller", None)
        if orb is None:
            return
        try:
            data = dict(payload or {})
            orb.request_snapshot_context({"snapshots": list(data.get("snapshots") or [])})
            if data.get("focus_bounds") or data.get("focus_text"):
                orb.request_comment_focus(
                    {
                        "focus_bounds": data.get("focus_bounds") or [],
                        "focus_text": data.get("focus_text") or "",
                        "focus_label": data.get("focus_label") or data.get("attention") or "",
                        "candidate": data.get("proactive_candidate") or "",
                        "summary": data.get("summary") or "",
                        "attention": data.get("attention") or "",
                        "duration_seconds": 14.0,
                    }
                )
        except Exception:
            pass

    def _on_proactive_queued(self, payload):
        orb = getattr(self, "orb_controller", None)
        if orb is None:
            return
        try:
            orb.focus_comment_text(dict(payload or {}))
        except Exception:
            pass

    def shutdown(self):
        orb_controller = getattr(self, "orb_controller", None)
        if orb_controller is not None:
            try:
                orb_controller.shutdown()
            except Exception:
                pass
        controller = getattr(self, "controller", None)
        if controller is not None:
            try:
                controller.shutdown()
            except Exception:
                pass
        self.orb_controller = None
        self.controller = None
        return None

from __future__ import annotations

from core.addons import BaseAddon
from addons.companion_orb_overlay.companion_orb import eye_tracking, spatial_commands, visual_questions
from addons.companion_orb_overlay.companion_orb.conversation_context import OrbConversationContext


_CAPABILITIES = frozenset(
    {
        "chat.user_text_command", "chat_context.collect",
        "companion_orb.assistant_focus", "companion_orb.target_info",
        "companion_orb.conversation_tools",
        "companion_orb.clear_target", "companion_orb.edit_mode",
        "companion_orb.placement_mode", "companion_orb.click_through",
        "companion_orb.reset_position", "companion_orb.focus_comment",
        "companion_orb.eye_tracking_status", "companion_orb.reconnect_eye_tracking",
        "companion_orb.react_at_gaze", "companion_orb.tutorial.try_action",
        "companion_orb.tutorial.restore_settings",
        "runtime.companion_orb.native_snapshot",
        "runtime.companion_orb.native_update_control",
        "runtime.companion_orb.native_control_action",
    }
)


class Addon(BaseAddon):
    TAB_ID = "companion_orb_overlay_tab"

    def initialize(self, context):
        super().initialize(context)
        from addons.companion_orb_overlay.companion_orb.companion_orb_controller import CompanionOrbController
        from addons.companion_orb_overlay.settings_controller import CompanionOrbOverlaySettingsController

        self.controller = CompanionOrbOverlaySettingsController(context)
        self.orb_controller = CompanionOrbController(context)
        self.controller.set_companion_orb_service(self.orb_controller)
        from addons.companion_orb_overlay.companion_orb.watch_state import OrbWatchState
        from addons.companion_orb_overlay.companion_orb.watch_context import OrbWatchContext
        self.orb_controller.watch_context = OrbWatchContext(OrbWatchState(),
            self.orb_controller.orb_runtime,
            self.controller._register_companion_orb_supervisor_contributor,
            capture_target_available=self.orb_controller._watch_capture_target_available,
            shared_policy_config=context.capabilities.runtime_config.snapshot)
        self._event_tokens = []
        for event_name, handler in (
            ("sensory.hidden_pong.parsed", self._on_hidden_pong_parsed),
            ("sensory.hidden_action.proactive_queued", self._on_proactive_queued),
            ('sensory.orb_watch.reply_delivered', self._on_watch_delivered),
            ('sensory.orb_watch.publish_reply', self._on_watch_publication),
        ):
            try:
                self._event_tokens.append(context.events.subscribe(event_name, handler))
            except Exception as exc:
                context.logger.warning("[CompanionOrbOverlay] Could not subscribe to %s: %s", event_name, exc)
        context.logger.info("[CompanionOrbOverlay] Companion Orb Overlay addon initialized.")

    def invoke_capability(self, capability, payload=None):
        name = str(capability or "").strip().lower()
        if name not in _CAPABILITIES:
            return None
        request = dict(payload or {})
        handlers = {
            "chat.user_text_command": lambda: self.handle_user_text_command(
                request.get("role"), request.get("text") or request.get("utterance")
            ),
            "chat_context.collect": lambda: self.collect_chat_context(
                request.get("messages", request.get("history")) or (),
                request_kind=request.get("request_kind", "normal_chat"),
            ),
            "companion_orb.assistant_focus": lambda: self.assistant_focus(request),
            "companion_orb.conversation_tools": lambda: self.conversation_tools(request),
            "companion_orb.target_info": self.target_info,
            "companion_orb.clear_target": self.clear_target,
            "companion_orb.edit_mode": lambda: self.set_edit_mode(request.get("enabled", True)),
            "companion_orb.placement_mode": lambda: self.set_placement_mode(request.get("enabled", True)),
            "companion_orb.click_through": lambda: self.set_click_through(request.get("enabled", True)),
            "companion_orb.reset_position": self.reset_position,
            "companion_orb.focus_comment": lambda: self.focus_comment(request),
            "companion_orb.eye_tracking_status": self.eye_tracking_status,
            "companion_orb.reconnect_eye_tracking": self.reconnect_eye_tracking,
            "companion_orb.react_at_gaze": lambda: self.react_at_gaze(force=request.get("force", True)),
            "companion_orb.tutorial.try_action": lambda: self.perform_tutorial_try_action(request),
            "companion_orb.tutorial.restore_settings": lambda: self.restore_tutorial_settings(
                request.get("settings") or {}
            ),
            "runtime.companion_orb.native_snapshot": self.controller.native_snapshot,
            "runtime.companion_orb.native_update_control": lambda: self.controller.native_update_control(
                request.get("control_id"), request.get("value")
            ),
            "runtime.companion_orb.native_control_action": lambda: self.controller.native_control_action(
                request.get("control_id"), request.get("payload")
            ),
        }
        return handlers[name]()

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

    def _orb(self):
        return getattr(self, "orb_controller", None)

    def handle_user_text_command(self, role, text):
        request = {"role": str(role or "user"), "text": str(text or "")}
        gaze_result = self._handle_eye_tracking_user_text_command(request)
        if gaze_result is not None:
            return gaze_result
        # Screen conversation belongs to Normal Chat, with its persona and history.
        # Do not turn a question or compound look-and-comment request into a move.
        if visual_questions.is_visual_question(text):
            return None
        spatial_result = self._handle_spatial_user_text_command(request)
        if spatial_result is not None:
            return spatial_result
        return None

    def target_info(self):
        orb = self._orb()
        return None if orb is None else {"ok": True, "target": orb.target_info()}

    def collect_chat_context(self, history, *, request_kind="normal_chat"):
        orb = self._orb()
        if orb is None:
            return None
        if request_kind == 'normal_chat' and history and history[-1].get('companion_orb_conversation_tools') is True:
            return None  # Native tools own inspection and focus; do not also offer text directives.
        spatial = orb.collect_spatial_chat_context(history)
        watch_owner = getattr(orb, 'watch_context', None)
        watch = watch_owner.collect(history, request_kind=request_kind,
            config=orb._last_runtime_config) if watch_owner is not None else {}
        if not hasattr(self, "_conversation_context"):
            self._conversation_context = OrbConversationContext()
        visual_context = self._conversation_context.collect_context(orb, history, request_kind=request_kind)
        visual = '\n\n'.join(filter(None, (watch.get('context', ''), visual_context.get('context', ''))))
        if not visual:
            return spatial
        spatial_text = str((spatial or {}).get("context") or "") if isinstance(spatial, dict) else str(spatial or "")
        return {**visual_context, **watch,
            "current_turn_context": "\n\n".join(filter(None, (
                watch.get('current_turn_context', ''), visual_context.get('current_turn_context', '')))),
            "context": "\n\n".join(part for part in (spatial_text, visual) if part)}

    def conversation_tools(self, payload):
        from dataclasses import asdict
        from core.conversation_tools import ToolCall
        from addons.companion_orb_overlay.companion_orb.conversation_tools import OrbConversationTools
        orb = self._orb()
        if orb is None or getattr(orb, 'watch_context', None) is None:
            if payload.get('operation') == 'publish':
                return None
            return dict(available=False, ok=False, reason='Orb is unavailable.')
        owner = getattr(self, '_conversation_tools', None)
        if owner is None or owner.orb is not orb:
            owner = self._conversation_tools = OrbConversationTools(orb.watch_context, orb)
        operation = payload.get('operation')
        if operation == 'offer':
            return owner.offer(history=payload.get('history') or [], session_key=payload.get('session_key', ''),
                turn_key=payload.get('turn_key', ''), is_current=payload.get('is_current'))
        if operation == 'current':
            return owner.current_state(payload.get('ticket', ''))
        if operation == 'publish':
            return owner.publish(payload.get('ticket', ''), payload.get('publish'))
        if operation == 'execute':
            try:
                call = ToolCall(**payload['call'])
            except (KeyError, TypeError):
                return dict(ok=False, reason='Invalid tool call.')
            return asdict(owner.execute(payload.get('ticket', ''), call))
        return dict(ok=False, reason='Unsupported Orb tool operation.')

    def assistant_focus(self, payload):
        orb = self._orb()
        return None if orb is None else orb.handle_assistant_focus(dict(payload or {}))

    def clear_target(self):
        orb = self._orb()
        if orb is None: return None
        orb.clear_target()
        return {"ok": True, "cleared": True}

    def set_edit_mode(self, enabled):
        orb = self._orb()
        if orb is None: return None
        value = bool(enabled)
        orb.set_edit_mode(value)
        return {"ok": True, "edit_mode": value}

    def set_placement_mode(self, enabled):
        orb = self._orb()
        if orb is None: return None
        value = bool(enabled)
        orb.set_placement_mode(value)
        return {"ok": True, "placement_mode": value}

    def set_click_through(self, enabled):
        orb = self._orb()
        if orb is None: return None
        value = bool(enabled)
        orb.set_click_through(value)
        return {"ok": True, "click_through": value}

    def reset_position(self):
        orb = self._orb()
        if orb is None: return None
        orb.reset_position()
        return {"ok": True, "position_reset": True}

    def focus_comment(self, payload):
        orb = self._orb()
        if orb is None: return None
        orb.focus_comment_text(dict(payload or {}))
        return {"ok": True, "focused": True}

    def eye_tracking_status(self):
        orb = self._orb()
        return None if orb is None else {"ok": True, **orb.eye_tracking_status()}

    def reconnect_eye_tracking(self):
        orb = self._orb()
        return None if orb is None else orb.reconnect_eye_tracking()

    def react_at_gaze(self, *, force=True):
        orb = self._orb()
        return None if orb is None else orb.react_at_gaze(force=bool(force))

    def perform_tutorial_try_action(self, action):
        controller = getattr(self, "controller", None)
        if controller is None:
            return {"accepted": False, "error": "Companion Orb settings are unavailable."}
        return controller.perform_tutorial_try_action(dict(action or {}))

    def restore_tutorial_settings(self, settings):
        controller = getattr(self, "controller", None)
        if controller is None:
            return {"accepted": False, "error": "Companion Orb settings are unavailable."}
        return controller.restore_tutorial_settings(dict(settings or {}))

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

    def _handle_spatial_user_text_command(self, request):
        role = str(request.get("role") or "user").strip().lower()
        if role and role != "user":
            return None
        command = spatial_commands.parse_spatial_command(
            request.get("text") or request.get("utterance") or ""
        )
        if command is None:
            return None
        if visual_questions.needs_conversation_reference(command.target_text):
            return None
        orb = getattr(self, "orb_controller", None)
        if orb is None:
            return None
        return orb.execute_spatial_command(command)

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
                        "stay_during_speech": True,
                        "return_behavior": "after_speech",
                    }
                )
            # The fallback inspection has produced its answer (or decided no
            # reply is needed). Only its own drop may release temporary focus.
            for snapshot in data.get('snapshots') or []:
                metadata = snapshot.get('metadata') or {}
                inspection_id = metadata.get('manual_inspection_id')
                if type(inspection_id) is int and inspection_id > 0:
                    orb._request_drop_capture_finish(inspection_id)
        except Exception:
            pass

    def _on_watch_delivered(self, payload):
        from addons.companion_orb_overlay.companion_orb.watch_state import WatchEpoch
        owner = getattr(self._orb(), 'watch_context', None)
        watch = dict(payload or {}).get('orb_watch') or {}
        if owner and watch:
            delivered = (owner.state.mark_delivered(dict(watch)) if watch.get('schema_version') == 2 else
                owner.state.mark_delivered(WatchEpoch(watch.get('session_key'), watch.get('revision')), watch.get('event_id')))
            if delivered:
                owner.on_change()
            owner.record('watch.delivery_result',dict(delivered=delivered,bundle=watch,state=owner.state.snapshot()),
                session_key=watch.get('session_key',''))

    def _on_watch_publication(self, payload):
        from core.orb_watch_contract import WatchReplyPublication
        command=payload.get('publication')
        owner=getattr(self._orb(),'watch_context',None)
        if not owner or not isinstance(command,WatchReplyPublication) or command.claimed:
            return
        command.claimed=True
        try:
            command.result=owner.state.publish_reply(command.bundle,command.publish)
        except Exception as exc:
            owner.record('watch.delivery_result',dict(delivered=False,bundle=command.bundle,error=str(exc),state=owner.state.snapshot()),
                session_key=command.bundle.get('session_key',''))
            raise
        delivered=bool(command.result is not None and command.result.accepted and command.result.value is not None)
        owner.record('watch.delivery_result',dict(delivered=delivered,bundle=command.bundle,state=owner.state.snapshot()),
            session_key=command.bundle.get('session_key',''))
        if delivered:
            owner.on_change()

    def _on_proactive_queued(self, payload):
        orb = getattr(self, "orb_controller", None)
        if orb is None:
            return
        try:
            data = dict(payload or {})
            data.setdefault("stay_during_speech", True)
            data.setdefault("return_behavior", "after_speech")
            orb.focus_comment_text(data)
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

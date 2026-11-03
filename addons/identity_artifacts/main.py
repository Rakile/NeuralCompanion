from __future__ import annotations

from addons.identity_artifacts.native_controller import IdentityArtifactsController
from core.addons import BaseAddon


class Addon(BaseAddon):
    """Identity Relay domain service used directly by the native QML adapter."""

    def initialize(self, context):
        super().initialize(context)
        relay_runtime = context.capabilities.identity_relay_runtime
        self.controller = IdentityArtifactsController(
            app_root=context.app_root,
            storage=context.storage,
            dialogs=context.capabilities.dialogs,
            shell=context.capabilities.shell_session,
            runtime_config=context.capabilities.runtime_config,
            runtime_embedding=(relay_runtime.embedding if relay_runtime is not None else None),
            runtime_delete_transaction=(
                relay_runtime.delete_transaction if relay_runtime is not None else None
            ),
            runtime_derivative_purge=(
                relay_runtime.purge_derivatives if relay_runtime is not None else None
            ),
        )
        self._runtime_controller_lease = None
        if relay_runtime is not None and relay_runtime.artifact_controller is not None:
            self._runtime_controller_lease = relay_runtime.artifact_controller.bind(
                self.controller
            )
        context.logger.info("Identity Artifacts native service initialized.")

    def export_session_state(self):
        return self.controller.export_session_state()

    def import_session_state(self, payload):
        return self.controller.import_session_state(payload)

    def export_preset_state(self):
        return self.controller.export_preset_state()

    def import_preset_state(self, payload):
        return self.controller.import_preset_state(payload)

    def invoke_capability(self, capability, payload=None):
        request = dict(payload or {})
        controller = self.controller
        explicit_v2 = request.get("schema_version") == 2
        handlers = {
            "runtime.identity_artifacts.snapshot": lambda: controller.native_snapshot(
                request.get("selected_ref")
            ),
            "runtime.identity_artifacts.set_owner_override": lambda: controller.native_set_owner_override(
                request.get("enabled")
            ),
            "runtime.identity_artifacts.request_connection": lambda: controller.native_request_connection(
                request.get("artifact_ref")
            ),
            "runtime.identity_artifacts.activate_persona": lambda: controller.native_activate_persona(
                request.get("artifact_ref")
            ),
            "runtime.identity_artifacts.set_enabled": lambda: controller.native_set_relay_enabled(
                request.get("enabled")
            ),
            "runtime.identity_artifacts.apply_connection_review": lambda: controller.native_apply_connection_review(
                payload
            ),
            "runtime.identity_artifacts.cancel_connection_review": controller.native_cancel_connection_review,
            "runtime.identity_artifacts.action": lambda: controller.native_action(
                request.get("action"), request.get("payload") or {}
            ),
            "identity_relay.capture_mode": lambda: controller.capture_mode() if explicit_v2 else None,
            "identity_relay.capture_turn": lambda: (
                controller.capture_turn(request)
                if explicit_v2
                else controller.capture_turn_snapshot()
            ),
            "identity_relay.prepare_turn": lambda: controller.prepare_turn(request) if explicit_v2 else None,
            "identity_relay.render_judge_request": lambda: controller.render_judge_request(request) if explicit_v2 else None,
            "identity_relay.finalize_turn": lambda: controller.finalize_turn(request) if explicit_v2 else None,
            "identity_relay.restore_persisted_snapshot": lambda: controller.restore_persisted_snapshot(request) if explicit_v2 else None,
            "identity_relay.chat_session.export": lambda: (
                controller.export_chat_session_state_v2()
                if explicit_v2
                else controller.export_chat_session_state()
            ),
            "identity_relay.chat_session.import": lambda: controller.import_chat_session_state(request),
            "identity_relay.chat_session.reset": controller.reset_chat_session_state,
            "chat_context.collect": lambda: controller.collect_chat_context(request),
        }
        handler = handlers.get(str(capability or "").strip())
        return handler() if handler is not None else None

    def shutdown(self):
        lease = getattr(self, "_runtime_controller_lease", None)
        self._runtime_controller_lease = None
        if lease is not None:
            lease.close()
        controller = getattr(self, "controller", None)
        self.controller = None
        if controller is not None:
            controller.shutdown()

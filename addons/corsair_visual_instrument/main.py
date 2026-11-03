from __future__ import annotations

from dataclasses import asdict

from core.addons import BaseAddon

from addons.corsair_visual_instrument.settings import settings_to_dict


class Addon(BaseAddon):
    TAB_ID = "corsair_visual_instrument_tab"

    def initialize(self, context):
        super().initialize(context)
        from addons.corsair_visual_instrument.controller import CorsairVisualInstrumentController

        self.controller = CorsairVisualInstrumentController(context)
        context.ui.register_manifest_tab(id=self.TAB_ID, factory=self._build_tab)
        context.logger.info("[Corsair LEDs] Corsair Visual Instrument addon initialized.")

    def _build_tab(self, _context):
        controller = getattr(self, "controller", None)
        if controller is None:
            raise RuntimeError("Corsair Visual Instrument controller is unavailable.")
        return controller.build_tab()

    def invoke_capability(self, capability, payload=None):
        controller = getattr(self, "controller", None)
        if controller is None:
            raise RuntimeError("Corsair Visual Instrument controller is unavailable.")
        capability = str(capability or "").strip()
        payload = dict(payload or {})
        if capability == "runtime.corsair.snapshot":
            return {
                "status_state": str(controller.status_state or ""),
                "status_detail": str(controller.status_detail or ""),
                "devices": [asdict(device) for device in controller.devices],
                "settings": settings_to_dict(controller.settings),
            }
        if capability == "runtime.corsair.update":
            settings = controller.update_settings(**dict(payload.get("changes") or {}))
            return settings_to_dict(settings)
        if capability == "runtime.corsair.rescan":
            controller.rescan()
            return {"accepted": True}
        if capability == "runtime.corsair.preview_state":
            state = str(payload.get("state") or "").strip().lower()
            if state not in {"idle", "listening", "thinking", "speaking"}:
                raise ValueError(f"Unknown Corsair preview state: {state}")
            controller.preview_state(state)
            return {"accepted": True, "state": state}
        return None

    def shutdown(self):
        controller = getattr(self, "controller", None)
        if controller is not None:
            try:
                controller.shutdown()
            except Exception:
                pass
        self.controller = None
        return None

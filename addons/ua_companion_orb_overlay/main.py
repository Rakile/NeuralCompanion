from __future__ import annotations

from core.addons import BaseAddon


class Addon(BaseAddon):
    def initialize(self, context):
        super().initialize(context)
        context.services.register(
            "ua_companion_orb_overlay.stream",
            self,
            metadata={"kind": "visual_overlay_stream", "transport": "named_pipe"},
        )
        context.logger.info("[UaCompanionOrbOverlay] Named-pipe stream addon initialized.")
        return None

    def invoke_capability(self, capability, payload=None):
        capability_name = str(capability or "").strip().lower()
        request = dict(payload or {})
        if capability_name == "stream.publish_frame_path":
            from addons.ua_companion_orb_overlay import stream_runtime

            return {
                "ok": bool(
                    stream_runtime.publish_frame_path(
                        request.get("frame_path"),
                        frame_index=int(request.get("frame_index", 0) or 0),
                        runtime_config=request.get("runtime_config") or {},
                    )
                )
            }
        return None

    def shutdown(self):
        try:
            from addons.ua_companion_orb_overlay import stream_runtime

            stream_runtime.shutdown()
        except Exception:
            pass
        return None

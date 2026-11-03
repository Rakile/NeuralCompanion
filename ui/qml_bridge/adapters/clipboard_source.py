"""Native QML settings for the Clipboard sensory source."""

from __future__ import annotations

from ui.qml_bridge.adapters.addon_session import AddonSessionNativeAdapter
from ui.qml_bridge.native_contracts import NativeControl, NativeControlKind, NativeSurface


def build_clipboard_source_adapter(application_facade, *, persist=None):
    return AddonSessionNativeAdapter(
        application_facade,
        NativeSurface(
            id="clipboard_source_tab",
            addon_id="nc.clipboard_source",
            title="Clipboard Source",
            description="Control how copied images enter the conversation and sensory loop.",
            sections=("Delivery", "Background awareness"),
            controls=(
                NativeControl(
                    "clipboard_source_auto_attach_next_user_turn",
                    "Attach to the next user turn",
                    NativeControlKind.BOOLEAN,
                    section="Delivery",
                    description="Attach the newest clipboard image to the next submitted message.",
                    default_value=False,
                ),
                NativeControl(
                    "clipboard_source_auto_send_immediately",
                    "Send copied images immediately",
                    NativeControlKind.BOOLEAN,
                    section="Delivery",
                    description="Submit a copied image without waiting for another user message.",
                    default_value=False,
                ),
                NativeControl(
                    "clipboard_source_hidden_loop_enabled",
                    "Use copied images in background awareness",
                    NativeControlKind.BOOLEAN,
                    section="Background awareness",
                    description="Make clipboard images available as hidden sensory context.",
                    default_value=False,
                ),
            ),
        ),
        persist=persist,
    )


__all__ = ["build_clipboard_source_adapter"]

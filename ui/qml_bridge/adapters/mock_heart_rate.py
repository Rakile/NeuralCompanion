"""Native QML settings for the mock heart-rate source."""

from __future__ import annotations

from ui.qml_bridge.adapters.addon_session import AddonSessionNativeAdapter
from ui.qml_bridge.native_contracts import NativeControl, NativeControlKind, NativeSurface


def build_mock_heart_rate_adapter(application_facade, *, persist=None):
    return AddonSessionNativeAdapter(
        application_facade,
        NativeSurface(
            id="heart_rate_source_tab",
            addon_id="nc.mock_heart_rate",
            title="Mock Heart Rate",
            description="Set the development heart-rate signal and its floating monitor.",
            sections=("Signal", "Monitor"),
            controls=(
                NativeControl(
                    "mock_heart_rate_bpm",
                    "Heart rate",
                    NativeControlKind.INTEGER,
                    section="Signal",
                    description="Published mock sensor value in beats per minute.",
                    default_value=72,
                    minimum=0,
                    maximum=200,
                ),
                NativeControl(
                    "mock_heart_rate_window_visible",
                    "Show floating heart-rate monitor",
                    NativeControlKind.BOOLEAN,
                    section="Monitor",
                    default_value=False,
                ),
            ),
        ),
        persist=persist,
    )


__all__ = ["build_mock_heart_rate_adapter"]

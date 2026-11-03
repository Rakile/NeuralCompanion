from __future__ import annotations

from dataclasses import dataclass


CUSTOM_PALETTE_ID = "custom"


@dataclass(frozen=True)
class OrbColorPalette:
    palette_id: str
    label: str
    primary: str
    secondary: str
    accent: str
    glow: str

    def as_color_settings(self) -> dict[str, str]:
        return {
            "companion_orb_primary_color": self.primary,
            "companion_orb_secondary_color": self.secondary,
            "companion_orb_accent_color": self.accent,
            "companion_orb_glow_color": self.glow,
        }


ORB_COLOR_PALETTES: tuple[OrbColorPalette, ...] = (
    OrbColorPalette(CUSTOM_PALETTE_ID, "Custom colors", "#22d3ee", "#38bdf8", "#a78bfa", "#67e8f9"),
    OrbColorPalette("neural_prism", "Neural Prism", "#22d3ee", "#8b5cf6", "#f59e0b", "#a5f3fc"),
    OrbColorPalette("aurora_rose", "Aurora Rose", "#60a5fa", "#c084fc", "#fb7185", "#bae6fd"),
    OrbColorPalette("ember_circuit", "Ember Circuit", "#fb7185", "#f59e0b", "#38bdf8", "#fed7aa"),
    OrbColorPalette("deep_signal", "Deep Signal", "#4f46e5", "#14b8a6", "#a78bfa", "#93c5fd"),
    OrbColorPalette("soft_focus", "Soft Focus", "#2dd4bf", "#86efac", "#facc15", "#ccfbf1"),
)

_PALETTES_BY_ID = {item.palette_id: item for item in ORB_COLOR_PALETTES}


def palette_options() -> list[tuple[str, str]]:
    return [(item.label, item.palette_id) for item in ORB_COLOR_PALETTES]


def normalize_palette_id(value) -> str:
    palette_id = str(value or CUSTOM_PALETTE_ID).strip().lower().replace(" ", "_").replace("-", "_")
    return palette_id if palette_id in _PALETTES_BY_ID else CUSTOM_PALETTE_ID


def palette_for_id(value) -> OrbColorPalette:
    return _PALETTES_BY_ID[normalize_palette_id(value)]

"""VaM avatar addon defaults and path helpers."""

from __future__ import annotations

from pathlib import Path

from addons.vam_avatar import path_helpers


APP_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_EMOTION_PRESET_MAP = {
    "neutral": "nc_neutral",
    "happy": "nc_happy",
    "angry": "nc_angry",
    "sad": "nc_sad",
    "surprised": "nc_surprised",
    "shy": "nc_shy",
    "default": "nc_neutral",
}

DEFAULT_TIMELINE_CLIP_MAP = {
    "happy": "talk_happy",
    "angry": "talk_angry",
    "sad": "talk_sad",
    "surprised": "talk_surprised",
    "shy": "talk_shy",
    "default": "talk_default",
}


def detect_default_root() -> str:
    return path_helpers.detect_default_root(app_root=APP_ROOT)


def legacy_bridge_roots() -> tuple[str, ...]:
    return tuple(path_helpers.legacy_bridge_roots(app_root=APP_ROOT))


DEFAULT_ROOT = detect_default_root()
LEGACY_BRIDGE_ROOTS = legacy_bridge_roots()


def derive_bridge_root(vam_root: str) -> str:
    return path_helpers.derive_bridge_root(vam_root, app_root=APP_ROOT)


def derive_plugin_dir(vam_root: str) -> str:
    return path_helpers.derive_plugin_dir(vam_root)


def normalize_root(raw_value=None, migrate_legacy=True) -> str:
    return path_helpers.normalize_root(
        raw_value,
        default_root=DEFAULT_ROOT,
        legacy_roots=LEGACY_BRIDGE_ROOTS,
        migrate_legacy=migrate_legacy,
    )


def normalize_bridge_root(raw_value=None, migrate_legacy=True) -> str:
    return path_helpers.normalize_bridge_root(
        raw_value,
        app_root=APP_ROOT,
        default_root=DEFAULT_ROOT,
        legacy_roots=LEGACY_BRIDGE_ROOTS,
        migrate_legacy=migrate_legacy,
    )


DEFAULT_BRIDGE_ROOT = derive_bridge_root(DEFAULT_ROOT)

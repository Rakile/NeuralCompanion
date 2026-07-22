from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_ai_presence_session_groups_flat_keys_under_top_dictionary() -> None:
    from core.ai_presence_session_schema import group_ai_presence_session, with_flat_ai_presence_settings

    grouped = group_ai_presence_session(
        {
            "ai_presence_enabled": True,
            "ai_presence_display_mode": "floating",
            "ai_presence": {"ai_presence_visual_style": "neural_network_pulse"},
            "unrelated": "kept",
        }
    )

    assert grouped["unrelated"] == "kept"
    assert "ai_presence_enabled" not in grouped
    assert "ai_presence_display_mode" not in grouped
    assert grouped["ai_presence"]["ai_presence_enabled"] is True
    assert grouped["ai_presence"]["ai_presence_display_mode"] == "floating"
    assert grouped["ai_presence"]["ai_presence_visual_style"] == "neural_network_pulse"

    flattened = with_flat_ai_presence_settings(grouped)
    assert flattened["ai_presence_enabled"] is True
    assert flattened["ai_presence_display_mode"] == "floating"


def test_companion_orb_session_groups_flat_keys_under_top_dictionary() -> None:
    from core.companion_orb_session_schema import group_companion_orb_session, with_flat_companion_orb_settings

    grouped = group_companion_orb_session(
        {
            "companion_orb_enabled": True,
            "companion_orb_target_info": {"title": "Orb target"},
            "companion_orb": {"companion_orb_display_mode": "always"},
            "unrelated": "kept",
        }
    )

    assert grouped["unrelated"] == "kept"
    assert "companion_orb_enabled" not in grouped
    assert "companion_orb_target_info" not in grouped
    assert grouped["companion_orb"]["companion_orb_enabled"] is True
    assert grouped["companion_orb"]["companion_orb_display_mode"] == "always"
    assert grouped["companion_orb"]["companion_orb_target_info"] == {"title": "Orb target"}

    flattened = with_flat_companion_orb_settings(grouped)
    assert flattened["companion_orb_enabled"] is True
    assert flattened["companion_orb_target_info"] == {"title": "Orb target"}


def test_ua_companion_orb_session_groups_flat_keys_under_top_dictionary() -> None:
    from core.ua_companion_orb_session_schema import (
        group_ua_companion_orb_session,
        with_flat_ua_companion_orb_settings,
    )

    grouped = group_ua_companion_orb_session(
        {
            "ua_companion_orb_send_musetalk_face_mask": True,
            "ua_companion_orb_overlay": {"ua_companion_orb_mask_size": 1024},
            "unrelated": "kept",
        }
    )

    assert grouped["unrelated"] == "kept"
    assert "ua_companion_orb_send_musetalk_face_mask" not in grouped
    assert grouped["ua_companion_orb_overlay"]["ua_companion_orb_send_musetalk_face_mask"] is True
    assert grouped["ua_companion_orb_overlay"]["ua_companion_orb_mask_size"] == 1024

    flattened = with_flat_ua_companion_orb_settings(grouped)
    assert flattened["ua_companion_orb_send_musetalk_face_mask"] is True
    assert flattened["ua_companion_orb_mask_size"] == 1024


def test_musetalk_brush_transparency_uses_musetalk_top_dictionary() -> None:
    from core.musetalk_session_schema import group_musetalk_session, with_flat_musetalk_settings

    grouped = group_musetalk_session(
        {
            "musetalk_debug_brush_transparency": 42,
            "musetalk": {"preprocess": {"debug_brush_size": 21}},
            "unrelated": "kept",
        }
    )

    assert grouped["unrelated"] == "kept"
    assert "musetalk_debug_brush_transparency" not in grouped
    assert grouped["musetalk"]["preprocess"]["debug_brush_transparency"] == 42
    assert grouped["musetalk"]["preprocess"]["debug_brush_size"] == 21

    flattened = with_flat_musetalk_settings(grouped)
    assert flattened["musetalk_debug_brush_transparency"] == 42


def test_main_window_session_uses_addon_namespace_helpers() -> None:
    source = (ROOT / "ui" / "runtime" / "main_window_session.py").read_text(encoding="utf-8")
    assert "group_ai_presence_session(session)" in source
    assert "group_companion_orb_session(session)" in source
    assert "group_ua_companion_orb_session(session)" in source
    assert "with_flat_ai_presence_settings(" in source
    assert "with_flat_companion_orb_settings(" in source
    assert "with_flat_ua_companion_orb_settings(" in source


if __name__ == "__main__":
    test_ai_presence_session_groups_flat_keys_under_top_dictionary()
    test_companion_orb_session_groups_flat_keys_under_top_dictionary()
    test_ua_companion_orb_session_groups_flat_keys_under_top_dictionary()
    test_musetalk_brush_transparency_uses_musetalk_top_dictionary()
    test_main_window_session_uses_addon_namespace_helpers()
    print("smoke_addon_session_namespaces: ok")

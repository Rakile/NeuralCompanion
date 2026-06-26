"""Smoke checks for Screen Source auto-attach session persistence."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.sensory_session_schema import group_sensory_session, with_flat_sensory_settings


def test_screen_auto_attach_key_round_trips_through_grouped_session():
    grouped = group_sensory_session({"screen_source_auto_attach_next_user_turn": True})
    flattened = with_flat_sensory_settings(grouped)
    assert flattened["screen_source_auto_attach_next_user_turn"] is True


def test_main_session_saves_screen_auto_attach_runtime_key():
    source = (ROOT_DIR / "ui" / "runtime" / "main_window_session.py").read_text(encoding="utf-8")
    save_block = source.split("session = {", 1)[1].split("self._save_addon_session_surface_visibility(session)", 1)[0]
    assert '"screen_source_auto_attach_next_user_turn": bool(RUNTIME_CONFIG.get("screen_source_auto_attach_next_user_turn", False))' in save_block


def test_main_session_restores_screen_auto_attach_runtime_key():
    source = (ROOT_DIR / "ui" / "runtime" / "main_window_session.py").read_text(encoding="utf-8")
    restore_block = source.split("def restore_session", 1)[1].split("emotional_instructions = session.get", 1)[0]
    assert 'screen_source_auto_attach_next_user_turn = session.get("screen_source_auto_attach_next_user_turn")' in restore_block
    assert 'update_runtime_config("screen_source_auto_attach_next_user_turn", screen_auto_attach_enabled)' in restore_block


def test_source_setup_does_not_duplicate_screen_auto_attach_checkbox():
    source = (ROOT_DIR / "ui" / "runtime" / "backend_sensory_tabs.py").read_text(encoding="utf-8")
    assert "Attach screen capture to each user message" not in source


if __name__ == "__main__":
    test_screen_auto_attach_key_round_trips_through_grouped_session()
    test_main_session_saves_screen_auto_attach_runtime_key()
    test_main_session_restores_screen_auto_attach_runtime_key()
    test_source_setup_does_not_duplicate_screen_auto_attach_checkbox()
    print("screen_source_auto_attach_session smoke checks passed.")

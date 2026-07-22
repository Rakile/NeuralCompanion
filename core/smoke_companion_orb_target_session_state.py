from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
try:
    sys.path.remove(str(ROOT))
except ValueError:
    pass
sys.path.insert(0, str(ROOT))


def test_companion_orb_target_source_normalization():
    from core.sensory_source_selection import (
        normalize_companion_orb_target_source_selection,
        resolve_companion_orb_target_source_selection,
    )

    assert normalize_companion_orb_target_source_selection(["screen", "companion_orb_target"], False) == ["screen"]
    assert normalize_companion_orb_target_source_selection(["screen"], True) == ["screen", "companion_orb_target"]
    assert normalize_companion_orb_target_source_selection(["companion_orb_target"], False) == []
    assert normalize_companion_orb_target_source_selection([], True) == ["companion_orb_target"]

    assert resolve_companion_orb_target_source_selection("off", True, explicit=True) == []
    assert resolve_companion_orb_target_source_selection("screen", True, explicit=True) == ["screen"]
    assert resolve_companion_orb_target_source_selection(
        "screen,companion_orb_target",
        False,
        explicit=True,
    ) == ["screen", "companion_orb_target"]
    assert resolve_companion_orb_target_source_selection(
        "screen",
        True,
        explicit=False,
    ) == ["screen", "companion_orb_target"]


def test_session_save_restore_uses_orb_target_normalization():
    session_source = (ROOT / "ui" / "runtime" / "main_window_session.py").read_text(encoding="utf-8")
    core_source = (ROOT / "core" / "sensory_source_selection.py").read_text(encoding="utf-8")
    sensory_config_source = (ROOT / "ui" / "runtime" / "backend_sensory_config.py").read_text(encoding="utf-8")
    preset_source = (ROOT / "ui" / "runtime" / "backend_preset_body_runtime.py").read_text(encoding="utf-8")
    dry_run_source = (ROOT / "ui" / "runtime" / "backend_dry_run_runtime.py").read_text(encoding="utf-8")
    orb_controller = (ROOT / "addons" / "companion_orb_overlay" / "controller.py").read_text(encoding="utf-8")

    assert "normalize_companion_orb_target_source_selection" in core_source
    assert "resolve_companion_orb_target_source_selection" in sensory_config_source
    assert "def refresh_sensory_feedback_source_options(self, selected_value=None, *, explicit_selection=False):" in sensory_config_source
    assert "explicit=explicit_selection" in sensory_config_source
    assert 'update_runtime_config("companion_orb_sensory_target_enabled", orb_enabled)' in sensory_config_source
    assert "refresh_sensory_feedback_source_options(selected_value=source_value, explicit_selection=True)" in preset_source
    assert "refresh_sensory_feedback_source_options(selected_value=source_value, explicit_selection=True)" in dry_run_source
    assert "refresh_sensory_feedback_source_options(selected_value=source_value, explicit_selection=True)" in session_source
    assert "normalize_companion_orb_target_source_selection" in session_source
    assert '"companion_orb_sensory_target_enabled"' in session_source
    assert "companion_orb_supervisor_enabled" in orb_controller
    assert 'elif key == "companion_orb_supervisor_enabled":\n            if bool(value):' not in orb_controller
    assert "if bool(_runtime_config().get(\"companion_orb_supervisor_enabled\", False)):" not in orb_controller


if __name__ == "__main__":
    test_companion_orb_target_source_normalization()
    test_session_save_restore_uses_orb_target_normalization()
    print("smoke_companion_orb_target_session_state: ok")

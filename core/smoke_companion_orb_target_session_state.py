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
    from core.sensory_source_selection import normalize_companion_orb_target_source_selection

    assert normalize_companion_orb_target_source_selection(["screen", "companion_orb_target"], False) == ["screen"]
    assert normalize_companion_orb_target_source_selection(["screen"], True) == ["screen", "companion_orb_target"]
    assert normalize_companion_orb_target_source_selection(["companion_orb_target"], False) == []
    assert normalize_companion_orb_target_source_selection([], True) == ["companion_orb_target"]


def test_session_save_restore_uses_orb_target_normalization():
    session_source = (ROOT / "ui" / "runtime" / "main_window_session.py").read_text(encoding="utf-8")
    core_source = (ROOT / "core" / "sensory_source_selection.py").read_text(encoding="utf-8")
    orb_controller = (ROOT / "addons" / "companion_orb_overlay" / "controller.py").read_text(encoding="utf-8")

    assert "normalize_companion_orb_target_source_selection" in core_source
    assert "normalize_companion_orb_target_source_selection" in session_source
    assert '"companion_orb_sensory_target_enabled"' in session_source
    assert "companion_orb_supervisor_enabled" in orb_controller
    assert 'elif key == "companion_orb_supervisor_enabled":\n            if bool(value):' not in orb_controller
    assert "if bool(_runtime_config().get(\"companion_orb_supervisor_enabled\", False)):" not in orb_controller


if __name__ == "__main__":
    test_companion_orb_target_source_normalization()
    test_session_save_restore_uses_orb_target_normalization()
    print("smoke_companion_orb_target_session_state: ok")

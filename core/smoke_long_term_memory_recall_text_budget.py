from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import long_term_memory


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_recall_text_budget_normalization() -> None:
    assert long_term_memory.normalize_recall_text_budget(None) == -1
    assert long_term_memory.normalize_recall_text_budget("") == -1
    assert long_term_memory.normalize_recall_text_budget(-99) == -1
    assert long_term_memory.normalize_recall_text_budget(-1) == -1
    assert long_term_memory.normalize_recall_text_budget(0) == 0
    assert long_term_memory.normalize_recall_text_budget(12000) == 12000


def test_recall_text_budget_is_visible_and_wired_through_session_paths() -> None:
    key = "long_term_memory_recall_text_budget"
    expected_files = [
        "engine.py",
        "core/chat_runtime_session_schema.py",
        "ui/runtime/backend_system_shaping_builders.py",
        "ui/runtime/backend_chat_session_runtime.py",
        "ui/runtime/backend_engine_lifecycle.py",
        "ui/runtime/backend_console_chat.py",
        "ui/runtime/main_window_session.py",
        "ui/runtime/real_ui_actions_chat_sensory.py",
        "ui/runtime/real_ui_bindings.py",
        "ui/runtime/real_ui_sync_frontend.py",
        "ui/runtime/real_ui_surfaces.py",
    ]
    missing = [path for path in expected_files if key not in _read(path)]
    assert not missing, f"{key} missing from {missing}"
    assert '"long_term_memory_recall_text_budget": -1' in _read("engine.py")
    assert "Recall text budget (chars, -1 = no cap)" in _read("ui/runtime/backend_system_shaping_builders.py")
    assert "Recall text budget (chars, -1 = no cap)" in _read("ui/runtime/real_ui_surfaces.py")


def main() -> int:
    test_recall_text_budget_normalization()
    test_recall_text_budget_is_visible_and_wired_through_session_paths()
    print("long term memory recall text budget smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

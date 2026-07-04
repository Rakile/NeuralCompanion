import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import long_term_memory


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_image_recall_limit_normalization() -> None:
    assert long_term_memory.normalize_image_recall_limit(None) == 1
    assert long_term_memory.normalize_image_recall_limit("") == 1
    assert long_term_memory.normalize_image_recall_limit(0) == 0
    assert long_term_memory.normalize_image_recall_limit(1) == 1
    assert long_term_memory.normalize_image_recall_limit(42) == 42
    assert long_term_memory.normalize_image_recall_limit(-1) == -1
    assert long_term_memory.normalize_image_recall_limit(-99) == 1


def test_image_recall_limit_wired_through_ui_and_session_paths() -> None:
    key = "long_term_memory_recall_image_limit"
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
    assert "Long-Term Memory recalled images to attach" in _read("ui/runtime/backend_system_shaping_builders.py")
    assert "Long-Term Memory recalled images to attach" in _read("ui/runtime/real_ui_surfaces.py")


def main() -> int:
    test_image_recall_limit_normalization()
    test_image_recall_limit_wired_through_ui_and_session_paths()
    print("long term memory recall image limit smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

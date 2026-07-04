from __future__ import annotations

import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
try:
    sys.path.remove(str(ROOT))
except ValueError:
    pass
sys.path.insert(0, str(ROOT))


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_export_session_memory_report_writes_readable_dump_without_image_blobs():
    addons_module = types.ModuleType("addons")
    addons_module.__path__ = [str(ROOT / "addons")]
    sys.modules["addons"] = addons_module
    import addons.vam_avatar.config  # noqa: F401 - prime repo namespace for engine bootstrap imports

    import engine

    memory_id = "codex_memory_export_smoke"
    output_path = Path("runtime") / "memory_exports" / f"{memory_id}.md"
    if output_path.exists():
        output_path.unlink()

    engine.RUNTIME_CONFIG["continuity_memory_id"] = memory_id
    engine.RUNTIME_CONFIG["active_chat_context_name"] = memory_id
    engine.RUNTIME_CONFIG["active_chat_context_path"] = str(Path("chat_session") / f"{memory_id}.json")
    engine.conversation_history[:] = [
        {"role": "user", "content": "Hello", "attachment_source": "clipboard"},
        {"role": "assistant", "content": "Hello back", "visual_reply_image_path": "runtime/visual_replies/example.png"},
    ]

    result = engine.export_session_memory_report(output_path)
    assert Path(result["path"]).is_file()

    text = output_path.read_text(encoding="utf-8")
    assert "Session Memory Export" in text
    assert "Conversation Memory" in text
    assert "Long-Term Memory Archive" in text
    assert "Recent Chat Messages" in text
    assert "blob" not in text.lower()
    assert "base64" not in text.lower()


def test_export_session_memory_ui_wiring_exists():
    builder = _read("ui/runtime/backend_system_shaping_builders.py")
    runtime = _read("ui/runtime/backend_chat_session_runtime.py")
    real_ui = _read("ui/runtime/real_ui_surfaces.py")
    bindings = _read("ui/runtime/real_ui_bindings.py")

    assert "btn_export_session_memory" in builder
    assert "export_session_memory_report" in builder
    assert "def export_session_memory_report" in runtime
    assert "btn_export_session_memory" in real_ui
    assert "export_session_memory_report" in bindings
    assert 'setTitle("Chat context")' in real_ui


if __name__ == "__main__":
    test_export_session_memory_report_writes_readable_dump_without_image_blobs()
    test_export_session_memory_ui_wiring_exists()
    print("smoke_session_memory_export_report: ok")

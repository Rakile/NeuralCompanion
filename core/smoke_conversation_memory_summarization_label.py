from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_conversation_memory_summarization_label_is_enable_switch() -> None:
    backend = _read("ui/runtime/backend_system_shaping_builders.py")
    frontend = _read("ui/runtime/real_ui_surfaces.py")
    assert 'QCheckBox("Enable Conversation Memory summarization")' in backend
    assert 'QCheckBox("Enable Conversation Memory summarization"' in frontend
    assert 'auto_checkbox.setText("Enable Conversation Memory summarization")' in frontend
    assert "Auto summarize at interval" not in backend
    assert "Auto summarize at interval" not in frontend


if __name__ == "__main__":
    test_conversation_memory_summarization_label_is_enable_switch()
    print("smoke_conversation_memory_summarization_label: ok")

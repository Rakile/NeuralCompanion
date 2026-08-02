from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_archive_rebuild_candidate_button_is_isolated_and_wired() -> None:
    builder = (ROOT / "ui" / "runtime" / "backend_system_shaping_builders.py").read_text(encoding="utf-8")
    runtime = (ROOT / "ui" / "runtime" / "backend_chat_session_runtime.py").read_text(encoding="utf-8")
    real_surface = (ROOT / "ui" / "runtime" / "real_ui_surfaces.py").read_text(encoding="utf-8")
    real_bindings = (ROOT / "ui" / "runtime" / "real_ui_bindings.py").read_text(encoding="utf-8")

    assert 'QPushButton("Rebuild Archive Candidate...")' in builder
    assert 'setObjectName("btn_rebuild_long_term_memory_archive_candidate")' in builder
    assert "self.rebuild_long_term_memory_archive_candidate_now" in builder
    assert "archive_button_row.addWidget(self.btn_rebuild_long_term_memory_archive_candidate)" in builder
    assert '"btn_rebuild_long_term_memory_archive_candidate"' in runtime
    assert "def rebuild_long_term_memory_archive_candidate_now(self):" in runtime
    assert "long_term_memory_archive_rebuild.rebuild_archive_candidate(" in runtime
    assert "chunk_size=chunk_size" in runtime
    assert "inactive candidate" in runtime.lower()
    assert "never replaces" in runtime.lower()
    assert 'QPushButton("Rebuild Archive Candidate...", archive_box)' in real_surface
    assert 'setObjectName("btn_rebuild_long_term_memory_archive_candidate")' in real_surface
    assert "archive_button_row.addWidget(rebuild_archive_candidate)" in real_surface
    assert '"btn_rebuild_long_term_memory_archive_candidate": getattr(self.backend, "rebuild_long_term_memory_archive_candidate_now", None)' in real_bindings


def test_archive_interval_widget_uses_authoritative_default() -> None:
    builder = (ROOT / "ui" / "runtime" / "backend_system_shaping_builders.py").read_text(encoding="utf-8")
    assert 'runtime_config.get("long_term_memory_archive_batch_turns", long_term_memory.DEFAULT_EXTRACTION_TURNS)' in builder
    assert "self.long_term_memory_archive_batch_turns_spin.setSingleStep(1)" in builder
    for relative_path in (
        "ui/runtime/backend_chat_session_runtime.py",
        "ui/runtime/backend_console_chat.py",
        "ui/runtime/backend_engine_lifecycle.py",
        "ui/runtime/main_window_session.py",
        "ui/runtime/real_ui_surfaces.py",
    ):
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        relevant_lines = [
            line for line in source.splitlines()
            if "long_term_memory_archive_batch_turns" in line
        ]
        assert all("120" not in line and "250" not in line for line in relevant_lines), relative_path


if __name__ == "__main__":
    test_archive_rebuild_candidate_button_is_isolated_and_wired()
    test_archive_interval_widget_uses_authoritative_default()
    print("long term memory archive rebuild UI smoke passed")

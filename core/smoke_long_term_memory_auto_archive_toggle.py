from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_engine_auto_archive_has_explicit_default_off_gate() -> None:
    source = _read("engine.py")
    assert '"long_term_memory_auto_archive_enabled": False' in source
    assert "def _long_term_memory_store_exists" in source
    assert "def initialize_long_term_memory_store(*, create=True)" in source
    assert 'def _long_term_memory_archive_write_enabled' in source
    assert 'RUNTIME_CONFIG.get("long_term_memory_auto_archive_enabled", False)' in source
    list_start = source.index("def list_long_term_memory_records")
    list_end = source.index("def search_long_term_memory_records", list_start)
    list_body = source[list_start:list_end]
    assert "if not _long_term_memory_store_exists()" in list_body
    chunk_start = source.index("def list_long_term_memory_chunks")
    chunk_end = source.index("def search_long_term_memory_chunks", chunk_start)
    chunk_body = source[chunk_start:chunk_end]
    assert "if not _long_term_memory_store_exists()" in chunk_body
    retrieve_start = source.index("def retrieve_long_term_memory")
    retrieve_end = source.index("def build_long_term_memory_recall", retrieve_start)
    retrieve_body = source[retrieve_start:retrieve_end]
    assert "if not _long_term_memory_store_exists()" in retrieve_body
    asset_refresh_start = source.index("def _refresh_long_term_memory_assets_for_current_chat")
    asset_refresh_end = source.index("def sync_long_term_memory_archive_from_current_chat", asset_refresh_start)
    asset_refresh_body = source[asset_refresh_start:asset_refresh_end]
    assert "if not _long_term_memory_archive_write_enabled()" in asset_refresh_body
    assert "if not _long_term_memory_archive_enabled()" not in asset_refresh_body
    status_start = source.index("def long_term_memory_embedding_status")
    status_end = source.index("def rebuild_long_term_memory_embeddings", status_start)
    status_body = source[status_start:status_end]
    assert "if _long_term_memory_store_exists()" in status_body
    sync_start = source.index("def sync_long_term_memory_archive_from_current_chat")
    sync_end = source.index("_long_term_memory_auto_archive_lock", sync_start)
    sync_gate = source[sync_start:sync_end]
    assert "_long_term_memory_archive_write_enabled()" in sync_gate
    gate_start = source.index("def maybe_start_long_term_memory_auto_archive")
    gate_end = source.index("def _long_term_memory_extraction_payload", gate_start)
    gate = source[gate_start:gate_end]
    assert "_long_term_memory_archive_write_enabled()" in gate


def test_chat_session_saves_and_loads_auto_archive_setting() -> None:
    schema = _read("core/chat_runtime_session_schema.py")
    assert '("long_term_memory_auto_archive_enabled", ("archive", "auto_archive_enabled"))' in schema

    session = _read("ui/runtime/main_window_session.py")
    assert '"long_term_memory_auto_archive_enabled"' in session
    assert "long_term_memory_auto_archive_enabled_checkbox" in session

    console = _read("ui/runtime/backend_console_chat.py")
    assert '"long_term_memory_auto_archive_enabled"' in console
    assert "long_term_memory_auto_archive_enabled_checkbox" in console


def test_backend_and_frontend_have_auto_archive_checkbox_wiring() -> None:
    backend_builder = _read("ui/runtime/backend_system_shaping_builders.py")
    assert 'QCheckBox("Enable long-term memory archiving")' in backend_builder
    assert "manual Save Chat Context only writes Long-Term Memory when this is enabled" in backend_builder
    assert "long_term_memory_auto_archive_enabled_checkbox" in backend_builder

    console = _read("ui/runtime/backend_console_chat.py")
    flush_start = console.index("def _start_chat_context_memory_flush")
    flush_end = console.index("@QtCore.Slot(object, object)", flush_start)
    flush = console[flush_start:flush_end]
    assert 'config.get("long_term_memory_auto_archive_enabled", False)' in flush

    backend_runtime = _read("ui/runtime/backend_chat_session_runtime.py")
    assert "def on_long_term_memory_auto_archive_enabled_changed" in backend_runtime
    assert '"long_term_memory_auto_archive_enabled"' in backend_runtime
    assert "Long-Term Memory archiving is off." in backend_runtime
    assert "initialize_long_term_memory_store(create=auto_archive_enabled)" in backend_runtime
    assert "initialize_long_term_memory_store(create=False)" in backend_runtime

    lifecycle = _read("ui/runtime/backend_engine_lifecycle.py")
    assert '"long_term_memory_auto_archive_enabled"' in lifecycle

    frontend = _read("ui/runtime/real_ui_surfaces.py")
    assert 'QCheckBox("Enable long-term memory archiving"' in frontend
    assert "long_term_memory_auto_archive_enabled_checkbox" in frontend

    actions = _read("ui/runtime/real_ui_actions_chat_sensory.py")
    assert "def _on_frontend_long_term_memory_auto_archive_enabled_changed" in actions

    bindings = _read("ui/runtime/real_ui_bindings.py")
    assert "long_term_memory_auto_archive_enabled_checkbox" in bindings
    assert "_on_frontend_long_term_memory_auto_archive_enabled_changed" in bindings

    sync = _read("ui/runtime/real_ui_sync_frontend.py")
    assert '"long_term_memory_auto_archive_enabled_checkbox"' in sync


if __name__ == "__main__":
    test_engine_auto_archive_has_explicit_default_off_gate()
    test_chat_session_saves_and_loads_auto_archive_setting()
    test_backend_and_frontend_have_auto_archive_checkbox_wiring()
    print("smoke_long_term_memory_auto_archive_toggle: ok")

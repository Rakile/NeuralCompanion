from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SESSION_MODEL_KEY = "long_term_memory_embedding_session_model"
SESSION_CONTEXT_KEY = "long_term_memory_embedding_session_context_length"


def _text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def main() -> int:
    engine_text = _text("engine.py")
    chat_runtime_text = _text("ui/runtime/backend_chat_session_runtime.py")
    main_window_session_text = _text("ui/runtime/main_window_session.py")
    schema_text = _text("core/chat_runtime_session_schema.py")

    assert SESSION_MODEL_KEY in engine_text, "chat context export/import must preserve embedding session model"
    assert SESSION_CONTEXT_KEY in engine_text, "chat context export/import must preserve embedding session context"
    assert "def _long_term_memory_embedding_write_blocked" in engine_text, "embedding writes must be guarded by chat-session embedding model"
    assert "_embed_long_term_memory_target(target, *, allow_session_mismatch=False)" in engine_text, "normal embedding writes must reject session model mismatches by default"
    assert "allow_session_mismatch=bool(clear_existing)" in engine_text, "explicit rebuild must be the only model-change embedding escape hatch"
    rebuild_start = engine_text.index("def rebuild_long_term_memory_embeddings")
    rebuild_end = engine_text.index("def create_long_term_memory_record", rebuild_start)
    rebuild_text = engine_text[rebuild_start:rebuild_end]
    assert "_refresh_long_term_memory_assets_for_current_chat()" in rebuild_text, "rebuild must backfill saved visualization prompts before hashing embedding targets"
    assert rebuild_text.index("_refresh_long_term_memory_assets_for_current_chat()") < rebuild_text.index("list_embedding_targets("), "asset metadata refresh must happen before embedding targets are calculated"
    assert "backfill_all_visualization_prompts_from_original_paths()" in rebuild_text, "rebuild must recover legacy prompts from matching original image comments"
    assert rebuild_text.index("backfill_all_visualization_prompts_from_original_paths()") < rebuild_text.index("list_embedding_targets("), "image comment recovery must happen before embedding targets are calculated"
    assert "writes_blocked" in engine_text, "embedding status must expose blocked writes for UI warnings"
    assert "long_term_memory_embedding_blocked_event" in engine_text, "blocked archive embedding attempts must be exposed to the UI"
    assert "_record_long_term_memory_embedding_blocked_attempt" in engine_text, "blocked embedding attempts must create a user-visible event"
    assert "embeddings_blocked" in engine_text, "archive sync must skip embedding writes when the session model is mismatched"
    assert "Conversation Memory can still be saved normally" in chat_runtime_text, "UI warning must explain ordinary Conversation Memory is unaffected"
    assert "QMessageBox.warning" in chat_runtime_text and "Long-Term Memory embeddings locked" in chat_runtime_text, "UI must show a modal warning for blocked archive embeddings"
    assert SESSION_MODEL_KEY not in main_window_session_text, "qt_session must not store embedding session model"
    assert SESSION_CONTEXT_KEY not in main_window_session_text, "qt_session must not store embedding session context"
    assert SESSION_MODEL_KEY not in schema_text, "qt_session chat_runtime schema must not map embedding session model"
    assert SESSION_CONTEXT_KEY not in schema_text, "qt_session chat_runtime schema must not map embedding session context"
    print("long_term_memory embedding session boundary smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
